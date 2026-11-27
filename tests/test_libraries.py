"""The library catalogue: what each built-in library pulls in, what turns it on, what it carries."""

from __future__ import annotations

import ast
import importlib

import pytest
from conftest import write_tree

import owpp.lib
from owpp.bundle import bundle_function
from owpp.errors import OwppError
from owpp.importer import import_code
from owpp.libraries import (
    BY_NAME,
    FROM_RUNTIME,
    LIB_DIR,
    LIBRARIES,
    RUNTIME_FILE,
    VENDORED,
    closure,
    exports,
    fill,
    link,
    table,
    wanted,
)
from owpp.manifest import read_manifest
from owpp.testing.mock import MockOpenWebUI
from owpp.unbundle import unbundle

CODE = '"""\ntitle: T\n"""\nx = 1\n'


def test_every_library_file_is_in_the_catalogue_and_ends_with_its_marker():
    assert sorted(lib.file for lib in LIBRARIES) == sorted(
        p.stem for p in LIB_DIR.glob("*.py") if p.stem != "__init__"
    )
    for lib in LIBRARIES:
        assert lib.end in (LIB_DIR / f"{lib.file}.py").read_text(), lib.name
        if lib.placeholder:
            assert lib.placeholder in (LIB_DIR / f"{lib.file}.py").read_text(), lib.name
        for name in (*lib.pulls_in, *([lib.needs] if lib.needs else [])):
            assert name in BY_NAME, (lib.name, name)


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        (["jobs"], ["core", "events", "jobs"]),
        (["assets"], ["shared_assets", "core", "events", "assets"]),
        (["static"], ["core", "routes", "static"]),
        (["routes", "config"], ["core", "routes", "config"]),
        (["chat_data"], ["chat_data"]),
    ],
)
def test_a_library_pulls_in_what_it_is_built_on_in_catalogue_order(asked, expected):
    assert closure(asked) == expected


@pytest.mark.parametrize(
    ("held", "expected"),
    [
        ({"static/"}, ["core", "routes", "static"]),
        ({"jobs:"}, ["core", "events", "jobs"]),
        ({"templates/"}, ["templates"]),
        ({"config.yaml"}, ["core", "config"]),
        ({"assets/"}, ["shared_assets", "core", "events", "assets"]),
        (set(), []),
    ],
)
def test_what_a_plugin_holds_turns_its_libraries_on(held, expected):
    assert wanted(None, held, "p/plugin.yaml") == expected


def test_link_adds_each_library_once_after_the_header_with_its_data():
    out = link(CODE, ["config"], "p", {"config.yaml"}, {"config": {"greeting": "hi"}})
    assert out.startswith('"""\ntitle: T\n"""\n')
    assert out.index(BY_NAME["core"].end) < out.index(BY_NAME["config"].end) < out.index("x = 1")
    assert '"{\\"greeting\\":\\"hi\\"}"' in out
    assert link(out, ["config"], "p", {"config.yaml"}, {"config": {}}) == out  # already there


def test_a_library_with_no_data_gets_its_default():
    out = link(CODE, ["jobs"], "p")
    assert '"{\\"sync_every_minutes\\":60}"' in out


@pytest.mark.parametrize(
    ("include", "message"),
    [
        ("jobs", "include must be a list"),
        (["nope"], "unknown include nope"),
        (
            ["config"],
            r"include: config needs a config\.yaml \(it applies to the function bundle only\)",
        ),
        (["static"], "include: static needs a static/ folder"),
        (["live_reload"], "live_reload needs shared_assets too"),
    ],
)
def test_refuses_what_cannot_be_linked(include, message):
    with pytest.raises(OwppError, match=message):
        link(CODE, include, "p")


def test_include_needs_a_docstring_header():
    with pytest.raises(OwppError, match="needs a docstring header"):
        link("x = 1\n", ["core"], "p")


def test_the_docs_table_has_a_row_per_library():
    rows = table().splitlines()[2:]
    assert [r.split("|")[1].strip() for r in rows] == [f"`{lib.name}`" for lib in LIBRARIES]
    assert "| `static` | `core`, `routes` | a `static/` folder | a `static/` folder |" in rows


def test_owpp_lib_exports_every_public_library_name_from_its_library():
    """owpp.lib is what plugins import; the bundler decides what to include from exports().
    live_reload's names load on first use, since it imports open_webui (the mock, here)."""
    assert sorted(owpp.lib.__all__) == sorted(exports())
    with MockOpenWebUI():
        for name, lib in exports().items():
            module = "plugin_runtime" if lib == FROM_RUNTIME else f"lib.{BY_NAME[lib].file}"
            source = importlib.import_module(f"owpp.runtime.{module}")
            assert getattr(owpp.lib, name) is getattr(source, name), name
    with pytest.raises(AttributeError):
        owpp.lib.nope  # noqa: B018


def test_a_library_imports_only_libraries_it_pulls_in():
    """In a bundle the import is removed, so what it names must be inlined above: a library the
    catalogue pulls in. An `if TYPE_CHECKING:` import is optional (checked at run time)."""
    by_file = {lib.file: lib.name for lib in LIBRARIES}
    for lib in LIBRARIES:
        if lib.name in VENDORED:
            continue
        tree = ast.parse((LIB_DIR / f"{lib.file}.py").read_text())
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level:
                assert by_file[node.module] in closure(lib.pulls_in), (lib.name, node.module)


def test_fill_drops_the_default_and_puts_the_data_where_it_is_read():
    """A library imports with its default; a bundle has the plugin's data in its place."""
    text = "__X_DATA__ = '{}'  # for imports\n_X = _json.loads(__X_DATA__)\n"
    assert fill(text, "__X_DATA__", '"[1]"') == '_X = _json.loads("[1]")\n'


def test_library_files_import_on_their_own_with_their_defaults():
    """An editor and direct-import tests read them as modules, so they must import cleanly."""
    for lib in LIBRARIES:
        if lib.name != "live_reload":  # imports open_webui at its top; vendored, so left so
            importlib.import_module(f"owpp.runtime.lib.{lib.file}")
    importlib.import_module("owpp.runtime.plugin_runtime")
    assert RUNTIME_FILE.exists()


def test_every_library_a_tool_may_ask_for_has_a_reader_for_its_data():
    from owpp.bundle import TOOL_DATA_READERS

    assert sorted(TOOL_DATA_READERS) == sorted(lib.name for lib in LIBRARIES if lib.for_tools)


# Each entry that carries data reads it from a plugin folder and writes it back: a plugin with
# settings that are not the defaults, bundled and unbundled, is the same folder again.
ROUND_TRIPS = {
    "static": {
        "plugin.yaml": 'protocol: "0.5"\nfunction: {title: Demo}\n'
        "static: {prefix: /demo-files, access: admin}\n",
        "function.py": "class Filter:\n    pass\n",
        "static/app.js": "console.log(1)\n",
        "static/img/logo.bin": bytes([0xFF, 0x00, 0x10]),
    },
    "assets": {
        "plugin.yaml": 'protocol: "0.5"\nfunction: {title: Demo}\nassets: {order: 5, wrap: false}\n',
        "assets/loader.js": "console.log('demo')\n",
        "assets/custom.css": "body { color: red }\n",
    },
}


@pytest.mark.parametrize("name", ROUND_TRIPS)
def test_an_entry_reads_its_data_and_writes_it_back(tmp_path, name):
    """The entry's data, bundled into the function and unbundled out of it, writes back the
    files and the plugin.yaml key it was read from, settings that are not the defaults included."""
    folder = write_tree(tmp_path / "demo", ROUND_TRIPS[name])
    manifest = read_manifest(folder)
    lib = BY_NAME[name]
    data = lib.read(folder, manifest)
    own = unbundle(bundle_function(folder))
    assert own.data[name] == data
    files, keys = lib.write("demo", own.data[name])
    want = {p: v for p, v in ROUND_TRIPS[name].items() if p.startswith(f"{name}/")}
    assert {p: v.encode() if isinstance(v, str) else v for p, v in files.items()} == {
        p: v.encode() if isinstance(v, str) else v for p, v in want.items()
    }
    assert keys == {name: manifest[name]}


@pytest.mark.parametrize("name", ROUND_TRIPS)
def test_an_entry_with_its_defaults_writes_no_key(tmp_path, name):
    """Settings left at the entry's defaults are not written to plugin.yaml."""

    tree = dict(ROUND_TRIPS[name])
    tree["plugin.yaml"] = 'protocol: "0.5"\nfunction: {title: Demo}\n'
    folder = write_tree(tmp_path / "demo", tree)
    lib = BY_NAME[name]
    _, keys = lib.write("demo", lib.read(folder, read_manifest(folder)))
    assert keys == {}


def test_an_imported_plugin_with_static_and_assets_is_the_same_folder(tmp_path):
    """owpp import of a bundle with static/ and assets/, both with settings that are not the
    defaults, writes back the same files and plugin.yaml keys."""

    tree = {
        **ROUND_TRIPS["static"],
        **ROUND_TRIPS["assets"],
        "plugin.yaml": 'protocol: "0.5"\nfunction: {title: Demo}\n'
        "static: {prefix: /demo-files, access: public}\nassets: {order: -2, wrap: false}\n",
        "function.py": "from owpp.lib import PluginAssets\n\n\nclass Event(PluginAssets):\n    pass\n",
    }
    src = write_tree(tmp_path / "src" / "demo", tree)
    folder = import_code(tmp_path / "plugins", bundle_function(src), "demo", "x").folder
    got = read_manifest(folder)
    assert got["static"] == {"prefix": "/demo-files", "access": "public"}
    assert got["assets"] == {"order": -2, "wrap": False}
    for path in ("static/app.js", "static/img/logo.bin", "assets/loader.js", "assets/custom.css"):
        assert (folder / path).read_bytes() == (src / path).read_bytes()
    assert bundle_function(folder) == bundle_function(src)
