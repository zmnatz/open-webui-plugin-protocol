"""The library catalogue: every built-in library owpp links into a bundle, with what it pulls in,
what turns it on and what data it carries (see GLOSSARY.md and docs/libraries.md).

A plugin asks for libraries with `include:`, and some are turned on by what the plugin holds
(a `static/` folder turns on routes and static). `link()` adds each wanted library, and the ones
it pulls in, to the code after its docstring header, in catalogue order.

An entry that carries data owns it both ways, with its settings' defaults: `read` takes it from
the plugin's folder for bundling, and `write` turns it back into files and plugin.yaml keys for
`owpp import` (static and assets so far).
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from .errors import OwppError
from .flatten import defined, strip_relative_imports
from .manifest import coalesce, files_of, folder_files, get, omit, read_text, text_of

LIB_DIR = Path(__file__).resolve().parent / "runtime" / "lib"

# What a plugin can hold that turns a library on, as `held` names it, and how the docs say it.
HELD = {
    "static/": "a `static/` folder",
    "templates/": "a `templates/` folder",
    "assets/": "an `assets/` folder",
    "config.yaml": "a `config.yaml`",
    "jobs:": "a `jobs:` section in `plugin.yaml`",
}


@dataclass(frozen=True)
class Library:
    name: str
    # runtime/lib/<file>.py; its leading comment lines are not copied.
    file: str
    # The library's last line, `# --- <end> ---`: code that already has it is not given it again.
    end: str
    # Libraries it is built on, added with it.
    pulls_in: tuple[str, ...] = ()
    # A library that must be in the bundle already (it is not added: the plugin asks for it).
    needs: str | None = None
    # What the plugin holds that turns it on without `include:` (a HELD key).
    on_when: str | None = None
    # The placeholder in the library that the plugin's data replaces.
    placeholder: str | None = None
    # What the plugin must hold for its data, when it cannot be had without it (a HELD key).
    data_needs: str | None = None
    # The data when the bundle has none (a tool bundle).
    default: Any = None
    # A tool can ask for it, data included (`tool.include:`); otherwise its data is the function's.
    for_tools: bool = False
    # Its plugin.yaml key's settings, with their defaults; `{plugin}` stands for the plugin's id.
    settings: dict[str, Any] = field(default_factory=dict, compare=False)
    # Its data both ways: read(folder, manifest) is the data from the plugin's folder (None when
    # it holds none), and write(plugin id, data) is that data as files and plugin.yaml keys.
    read: Callable[[Path, dict], Any] | None = field(default=None, compare=False)
    write: Callable[[str, Any], tuple[dict[str, str | bytes], dict[str, Any]]] | None = field(
        default=None, compare=False
    )

    def defaults(self, plugin: str) -> dict[str, Any]:
        """Its settings' defaults for the plugin with id `plugin`."""
        return {
            k: v.format(plugin=plugin) if isinstance(v, str) else v
            for k, v in self.settings.items()
        }

    def changed(self, plugin: str, data: dict) -> dict[str, Any]:
        """The plugin.yaml key that gives `data`'s settings: only those that are not defaults."""
        keys = {
            k: data[k]
            for k, default in self.defaults(plugin).items()
            if data.get(k) not in (None, default)
        }
        return {self.name: keys} if keys else {}

    def settings_of(self, folder: Path, manifest: dict) -> dict[str, Any]:
        """Its plugin.yaml key's settings, each one the plugin leaves out at its default."""
        where = f"{folder.name}/plugin.yaml: {self.name}"
        known = ", ".join(self.settings)
        cfg = coalesce(manifest.get(self.name), {})
        if not isinstance(cfg, dict):
            raise OwppError(f"{where} must be a mapping ({known})")
        unknown = [str(k) for k in cfg if k not in self.settings]
        if unknown:
            raise OwppError(f"{where}: unknown key {', '.join(unknown)} (known: {known})")
        return {k: coalesce(get(cfg, k), v) for k, v in self.defaults(folder.name).items()}


# ---- the data of static and assets, both ways -------------------------------------

# Who may fetch static/ files: signed-in is the default; "public" must be spelled out.
ACCESS_LEVELS = ("user", "admin", "public")

_MOVED_PUBLIC = (
    "public/ is now two folders: static/ for files that are served as they are, and templates/ for "
    "files the function renders itself and never serves (what `dynamic:` used to list). Move the files "
    "and rename the manifest key `public:` to `static:` (its `dynamic:` list is gone)"
)


def _read_static(folder: Path, manifest: dict) -> dict | None:
    """The plugin's static/ folder: every file is served as it is at <prefix>/<path>, to signed-in users
    unless `static: {access: admin | public}`, by the static library (included with routes)."""
    if (folder / "public").exists():
        raise OwppError(f"{folder}: {_MOVED_PUBLIC}")
    if not (folder / "static").exists():
        if manifest.get("static") is not None:
            raise OwppError(f"{folder.name}/plugin.yaml: static: needs a static/ folder")
        return None
    where = f"{folder.name}/plugin.yaml: static"
    cfg = BY_NAME["static"].settings_of(folder, manifest)
    access = cfg["access"]
    if access not in ACCESS_LEVELS:
        raise OwppError(
            f"{where}.access must be user, admin or public (exactly one of those words), "
            f"not {access!r}: files need a signed-in user unless it says public in so many words"
        )
    prefix = text_of(cfg["prefix"])
    if not re.fullmatch(r"/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*", prefix):
        raise OwppError(f"{where}.prefix must be a path such as /name (letters, digits, _ and -)")
    files = {f["path"]: omit(f, ["path"]) for f in folder_files(folder / "static")}
    if not files:
        raise OwppError(f"{folder.name}: static/ has no files")
    return {"prefix": prefix, "access": access, "files": files}


def _write_static(plugin: str, data: dict) -> tuple[dict[str, str | bytes], dict[str, Any]]:
    files = {f"static/{p}": v for p, v in files_of(data.get("files") or {}).items()}
    return files, BY_NAME["static"].changed(plugin, data)


ASSET_FILES = ("loader.js", "custom.css")


def _read_assets(folder: Path, manifest: dict) -> dict | None:
    """assets/loader.js and assets/custom.css: this plugin's fragments of the Shared Assets
    Protocol's two files, embedded as text and published by the assets library."""
    where = f"{folder.name}/plugin.yaml: assets"
    if not (folder / "assets").exists():
        if manifest.get("assets") is not None:
            raise OwppError(f"{where} needs an assets/ folder")
        return None
    cfg = BY_NAME["assets"].settings_of(folder, manifest)
    order, wrap = cfg["order"], cfg["wrap"]
    if isinstance(order, bool) or not isinstance(order, int):
        raise OwppError(f"{where}.order must be a whole number (lower composes first)")
    if not isinstance(wrap, bool):
        raise OwppError(f"{where}.wrap must be true or false")
    files = {}
    for f in folder_files(folder / "assets"):
        if f["path"] not in ASSET_FILES:
            raise OwppError(
                f"{folder.name}: assets/{f['path']}: the protocol has two shared files, "
                f"so assets/ may hold only {' and '.join(ASSET_FILES)}"
            )
        if "encoding" in f:
            raise OwppError(f"{folder.name}: assets/{f['path']} must be UTF-8 text")
        files[f["path"]] = f["content"]
    if not files:
        raise OwppError(f"{folder.name}: assets/ has neither loader.js nor custom.css")
    return {"id": folder.name.lower(), "order": order, "wrap": wrap, "files": files}


def _write_assets(plugin: str, data: dict) -> tuple[dict[str, str | bytes], dict[str, Any]]:
    files = {f"assets/{p}": v for p, v in (data.get("files") or {}).items()}
    return files, BY_NAME["assets"].changed(plugin, data)


# In the order they are added to a bundle: each is a vendored, byte-identical copy put right after
# the docstring header, so plugin code can call it without carrying a copy. live_reload goes
# first because the Shared Assets Protocol wants it above the shared asset block.
LIBRARIES: tuple[Library, ...] = (
    Library("live_reload", "live_reload", "end live reload block", needs="shared_assets"),
    Library("shared_assets", "shared_assets", "end shared asset block"),
    # Function id, app, is-it-enabled, stored valves: what most others build on.
    Library("core", "plugin_core", "end plugin core library"),
    Library("routes", "plugin_routes", "end plugin routes library", ("core",), on_when="static/"),
    Library("events", "plugin_events", "end plugin events library", ("core",)),
    Library(
        "jobs",
        "plugin_jobs",
        "end plugin jobs library",
        ("events",),  # its mixin is a PluginEvents class
        on_when="jobs:",
        placeholder="__JOBS_DATA__",
        default={"sync_every_minutes": 60},
    ),
    Library("chat_data", "plugin_chat_data", "end plugin chat data library"),
    Library(
        "static",
        "plugin_static",
        "end plugin static library",
        ("core", "routes"),  # it mounts its files with plugin_mount
        on_when="static/",
        placeholder="__STATIC_DATA__",
        data_needs="static/",
        settings={"prefix": "/{plugin}", "access": "user"},
        read=_read_static,
        write=_write_static,
    ),
    Library(
        "templates",
        "plugin_templates",
        "end plugin templates library",
        on_when="templates/",
        placeholder="__TEMPLATES_DATA__",
        data_needs="templates/",
        for_tools=True,
    ),
    Library(
        "assets",
        "plugin_assets",
        "end plugin assets library",
        # Its mixin is a PluginEvents class; it publishes into the shared asset registry.
        ("events", "shared_assets"),
        on_when="assets/",
        placeholder="__ASSETS_DATA__",
        data_needs="assets/",
        settings={"order": 0, "wrap": True},
        read=_read_assets,
        write=_write_assets,
    ),
    Library(
        "config",
        "plugin_config",
        "end plugin config library",
        ("core",),
        on_when="config.yaml",
        placeholder="__CONFIG_DATA__",
        data_needs="config.yaml",
    ),
)
BY_NAME = {lib.name: lib for lib in LIBRARIES}


def json_literal(data: Any) -> str:
    """`data` as a Python string literal holding its JSON (compact, non-ASCII kept)."""
    inner = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(inner, ensure_ascii=False)


# A string literal as json_literal writes it (one line), as a regex group.
LITERAL = r'("(?:[^"\\\n]|\\.)*")'


def hoist_future(code: str) -> tuple[str, str]:
    """`from __future__ import ...` must be the first statement after the docstring, so
    when code is put in front of a file that has one, the line moves to the top."""
    lines: list[str] = []

    def take(m: re.Match) -> str:
        if m.group(0) not in lines:
            lines.append(m.group(0))
        return ""

    rest = re.sub(r"^from __future__ import [^\n]+\n", take, code, flags=re.MULTILINE)
    return "".join(lines), rest


def closure(names: list[str] | tuple[str, ...]) -> list[str]:
    """`names` with every library they pull in, transitively, in catalogue order."""
    seen: set[str] = set()
    todo = list(names)
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo += BY_NAME[name].pulls_in
    return [lib.name for lib in LIBRARIES if lib.name in seen]


def wanted(include: Any, held: set[str], where: str) -> list[str]:
    """The libraries a bundle gets: `include:` plus the ones what the plugin holds turns on,
    and what they pull in. `where` names the manifest in errors."""
    asked = [] if include is None else include
    if not isinstance(asked, list):
        raise OwppError(f"{where}: include must be a list")
    bad = [str(n) for n in asked if n not in BY_NAME]
    if bad:
        raise OwppError(f"{where}: unknown include {', '.join(bad)} (known: {', '.join(BY_NAME)})")
    on = [lib.name for lib in LIBRARIES if lib.on_when in held]
    return closure(list(dict.fromkeys([*asked, *on])))


def fill(text: str, placeholder: str, literal: str) -> str:
    """`text` with its data placeholder filled. The file gives the placeholder a default on a
    line of its own (`__X_DATA__ = '{}'`), so it can be imported; the bundle has the data instead:
    that line goes and the placeholder's use gets the literal."""
    text = re.sub(rf"^{placeholder} = .*\n", "", text, count=1, flags=re.MULTILINE)
    return text.replace(placeholder, literal, 1)


def _text(lib: Library) -> str:
    text = re.sub(r"\A(#.*\n)+\n?", "", read_text(LIB_DIR / f"{lib.file}.py"))
    return strip_relative_imports(text, f"runtime/lib/{lib.file}.py")


# The plugin runtime: its names can be imported from owpp.lib too, by a plugin that has it.
RUNTIME_FILE = LIB_DIR.parent / "plugin_runtime.py"
FROM_RUNTIME = "runtime"


def public_names(path: Path) -> list[str]:
    """The names a library file defines at its top level for plugins: not starting with `_`."""
    return [name for name in defined(ast.parse(read_text(path)), imports=False) if name[0] != "_"]


@cache
def exports() -> dict[str, str]:
    """Every name a plugin can import from owpp.lib, with the library it comes from
    (`runtime` for the plugin runtime's), the Shared Assets Protocol's included."""
    names: dict[str, str] = {}
    for lib in LIBRARIES:
        names.update(dict.fromkeys(public_names(LIB_DIR / f"{lib.file}.py"), lib.name))
    names.update(dict.fromkeys(public_names(RUNTIME_FILE), FROM_RUNTIME))
    return names


# Classic298's files, kept byte-identical: they are not ours to add imports to.
VENDORED = ("live_reload", "shared_assets")


def link(
    code: str,
    include: Any,
    name: str,
    held: set[str] | None = None,
    data: dict[str, Any] | None = None,
) -> str:
    """`code` with its libraries added after its docstring header: what `include:` asks for,
    what the plugin `held` turns on, and what those pull in. `data` is what each library that
    carries data embeds ({library name: data}); a library missing it gets its default, or is
    refused when the plugin must hold something for it. `name` is the plugin's, for errors."""
    held, data = held or set(), data or {}
    where = f"{name}/plugin.yaml"
    asked = [] if include is None else include
    libs = wanted(include, held, where)
    header = re.match(r'\s*"""[\s\S]*?"""\n', code)
    if libs and not header:
        raise OwppError(f"{name}: the function needs a docstring header for include")
    for lib_name in asked:
        lib = BY_NAME[lib_name]
        if lib.data_needs and data.get(lib.name) is None:
            raise OwppError(
                f"{where}: include: {lib.name} needs {HELD[lib.data_needs].replace('`', '')}"
                + ("" if lib.for_tools else " (it applies to the function bundle only)")
            )
    add = ""
    for lib_name in libs:
        lib = BY_NAME[lib_name]
        if lib.end in code:
            continue
        text = _text(lib)
        if lib.placeholder:
            value = data.get(lib.name)
            text = fill(
                text, lib.placeholder, json_literal(lib.default if value is None else value)
            )
        add += "\n" + text
    out = code
    if add:
        lines, rest = hoist_future(code[header.end() :])
        out = code[: header.end()] + lines + add + rest
    for lib_name in libs:
        need = BY_NAME[lib_name].needs
        if need and BY_NAME[need].end not in out:
            raise OwppError(f"{where}: {lib_name} needs {need} too")
    return out


def table() -> str:
    """The catalogue as a Markdown table, for docs/libraries.md."""
    rows = [
        "| Library | Pulls in | Turned on by | Carries |",
        "| --- | --- | --- | --- |",
    ]
    for lib in LIBRARIES:
        pulls = ", ".join(f"`{n}`" for n in closure(lib.pulls_in)) or "—"
        if lib.needs:
            pulls += f" (needs `{lib.needs}` in `include:`)"
        on = HELD[lib.on_when] if lib.on_when else "`include:` only"
        carries = HELD[lib.data_needs] if lib.data_needs else "its settings" if lib.default else "—"
        rows.append(f"| `{lib.name}` | {pulls} | {on} | {carries} |")
    return "\n".join(rows) + "\n"
