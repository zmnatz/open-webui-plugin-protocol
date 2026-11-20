"""The library catalogue: what each built-in library pulls in, what turns it on, what it carries."""

from __future__ import annotations

import pytest

from owpp.errors import OwppError
from owpp.libraries import BY_NAME, LIB_DIR, LIBRARIES, closure, link, table, wanted

CODE = '"""\ntitle: T\n"""\nx = 1\n'


def test_every_library_file_is_in_the_catalogue_and_ends_with_its_marker():
    assert sorted(lib.file for lib in LIBRARIES) == sorted(p.stem for p in LIB_DIR.glob("*.py"))
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
        (["static"], ["core", "static"]),
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
    assert "| `static` | `core` | a `static/` folder | a `static/` folder |" in rows
