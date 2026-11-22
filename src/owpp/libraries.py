"""The library catalogue: every built-in library owpp links into a bundle, with what it pulls in,
what turns it on and what data it carries (see GLOSSARY.md and docs/libraries.md).

A plugin asks for libraries with `include:`, and some are turned on by what the plugin holds
(a `static/` folder turns on routes and static). `link()` adds each wanted library, and the ones
it pulls in, to the code after its docstring header, in catalogue order.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from .errors import OwppError
from .flatten import defined, strip_relative_imports
from .manifest import read_text

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
    ),
    Library(
        "templates",
        "plugin_templates",
        "end plugin templates library",
        on_when="templates/",
        placeholder="__TEMPLATES_DATA__",
        data_needs="templates/",
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
    (`runtime` for the plugin runtime's). The vendored Shared Assets Protocol files are not in
    it: plugins use them through the assets library."""
    names: dict[str, str] = {}
    for lib in LIBRARIES:
        if lib.name not in VENDORED:
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
                f"{where}: include: {lib.name} needs {HELD[lib.data_needs].replace('`', '')} "
                "(it applies to the function bundle only)"
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
