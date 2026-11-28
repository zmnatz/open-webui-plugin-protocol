"""Turns a plugin folder into the single code blob Open-WebUI stores (docs/bundling.md).

A plugin is a folder <id>/ holding a plugin.yaml manifest, or (functions only) a single
<id>.py. The manifest's `function:` section is the parent: its keys become the docstring
header and the code is function.py. A plugin may also have

  tool:     `id`, `access: public`, and either `from: function` (the function's own bundle
            is the tool) or its own header keys with code in tool.py
  include:  built-in libraries (see libraries.py, the library catalogue)
  skills/<id>/   a skill folder: SKILL.md plus any supporting files
  static/   files served as they are, to signed-in users unless `static:` says otherwise
  templates/   files the function renders itself, embedded and never served (plugin_template_text())
  assets/   loader.js and custom.css: this plugin's fragments of the Shared Assets Protocol's
            two shared files, published by `class Event(PluginAssets)`
  config.yaml   structured settings shipped with the plugin, parsed here and read with plugin_config()
  jobs:     the default of the sync mixin's SYNC_INTERVAL_MINUTES valve, and adopt_markers
  source:   `{git, ref, path}`: `tool: {file: ...}`, `skills: {<id>: {file|dir: ...}}` and
            `function: {file: ...}` are read from that repo at a pinned commit

Those are embedded in the function bundle together with runtime/plugin_runtime.py, which
installs them while the function is enabled and removes them when it is disabled or
deleted. Open-WebUI stores a function as one file and cannot import siblings, so the
folder is bundled: function.py and tool.py are each one file; a `{{file:NAME}}` token in
one is replaced by the text of that file in the same folder.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import envtemplate
from .embedding import embed_runtime
from .errors import OwppError
from .events import problem_with
from .flatten import FILE_TOKEN, flatten
from .libraries import (
    BY_NAME,
    FROM_RUNTIME,
    LIBRARIES,
    exports,
    hoist_future,
    link,
    wanted,
)
from .manifest import (
    coalesce,
    folder_files,
    get,
    omit,
    parse_yaml,
    plugin_folders,
    read_manifest,
    read_text,
    text_of,
)
from .openwebui import MANAGED_BY, FunctionMeta
from .sources import ResolvedPlugin, Sources, upstream_parts

NOTE = "Git-controlled: edits made here are overwritten on the next deploy."

# Open-WebUI's own rule: an identifier, lowercased.
VALID_ID = re.compile(r"[a-z_][a-z0-9_]*")
VALID_SKILL_ID = re.compile(r"[a-z0-9_-]+")

DOCSTRING = re.compile(r'\s*"""\n?([\s\S]*?)"""')


# ---- header -----------------------------------------------------------------


def parse_frontmatter(content: str) -> dict:
    """The module docstring as Open-WebUI reads it: one `key: value` per line, split at
    the first colon. (Not YAML: a value such as `author: @G30` is fine here and invalid there.)"""
    m = DOCSTRING.match(content)
    if not m:
        return {}
    doc: dict[str, Any] = {}
    for line in m.group(1).split("\n"):
        i = line.find(":")
        if i <= 0:
            continue
        key, value = line[:i].strip(), line[i + 1 :].strip()
        doc[key] = True if value == "true" else False if value == "false" else value
    return doc


def check_frontmatter(file: str, content: str) -> None:
    """Open-WebUI reads the header line by line, so a YAML block value such as
    `description: >` is stored as ">" and the lines under it are lost."""
    m = DOCSTRING.match(content)
    if not m:
        return
    for line in m.group(1).split("\n"):
        if not line.strip():
            continue
        if not re.match(r"[A-Za-z_]+:\s*\S", line) or re.fullmatch(
            r"[A-Za-z_]+:\s*[>|][+-]?\s*", line
        ):
            raise OwppError(
                f"{file}: the header must be one `key: value` per line (Open-WebUI reads it "
                "line by line); put long text in a comment below it. "
                f'Offending line: "{line.strip()[:60]}"'
            )


def render_header(folder: Path | str, keys: dict) -> str:
    lines = []
    for k, v in keys.items():
        value = text_of(v)
        if (
            isinstance(v, (dict, list))
            or v is None
            or "\n" in value
            or not re.fullmatch(r"[A-Za-z_]+", str(k))
            or not value.strip()
        ):
            raise OwppError(
                f"{folder}/plugin.yaml: `{k}` must be a one-line value "
                "(Open-WebUI reads the header line by line)"
            )
        lines.append(f"{k}: {value}")
    return '"""\n' + "\n".join(lines) + '\n"""\n'


# ---- function.py / tool.py --------------------------------------------------


def _has_code(folder: Path, name: str) -> bool:
    return (folder / f"{name}.py").exists()


def _bundle_code(folder: Path, name: str, keys: dict) -> tuple[str, dict[str, str]]:
    """Header, then shared.py (code both the function and the tool need), then
    function.py or tool.py, with their imports of each other and of owpp.lib removed. The
    built-in libraries are added after this (link). Returns the code and the names imported
    from owpp.lib, each with where it is imported (`path:line`), for _check_lib_imports."""
    file = folder / f"{name}.py"
    if not file.exists():
        raise OwppError(f"{folder}: no {name}.py")
    shared_file = folder / "shared.py"
    shared = read_text(shared_file) if shared_file.exists() else None
    lib = exports()
    from_lib: dict[str, str] = {}
    shared_code = ""
    if shared is not None:
        shared_code, names = flatten("shared", shared, None, f"{shared_file}", lib)
        from_lib |= {n: f"{shared_file}:{line}" for n, line in names.items()}
    code, names = flatten(name, read_text(file), shared, f"{file}", lib)
    from_lib |= {n: f"{file}:{line}" for n, line in names.items()}
    source = shared_code + code
    if shared_code:
        lines, rest = hoist_future(source)
        source = lines + rest

    def include(m: re.Match) -> str:
        try:
            return read_text(folder / m.group(1))
        except OSError as e:
            raise OwppError(
                f"{folder}: {{{{file:{m.group(1)}}}}} in {name}.py names a file that is not "
                "in the plugin folder"
            ) from e

    body = FILE_TOKEN.sub(include, source)
    return render_header(folder, keys) + body, from_lib


def _check_lib_imports(
    folder: Path, from_lib: dict[str, str], libs: list[str], *, runtime: bool, include: str
) -> None:
    """Each name imported from owpp.lib must come from a library the bundle has (`libs`), or
    from the runtime when it has that. `include` names the manifest key, for the message."""
    lib = exports()
    for name, where in from_lib.items():
        source = lib[name]
        if source == FROM_RUNTIME:
            if not runtime:
                raise OwppError(
                    f"{where}: {name} is the plugin runtime's, which a bundle has only when "
                    "the plugin has a tool or skills"
                )
        elif source not in libs:
            raise OwppError(
                f"{where}: {name} is from the {source} library, which this bundle does not "
                f"have: add it to {include} in {folder}/plugin.yaml"
            )


def parse_skill(file: str, text: str) -> tuple[dict, str]:
    raw = text.replace("\r\n", "\n")
    m = re.match(r"---\n([\s\S]*?)\n---\n?", raw)
    fm: dict = {}
    if m:
        try:
            parsed = parse_yaml(m.group(1))
        except yaml.YAMLError as e:
            raise OwppError(f"{file}: the front matter is not valid YAML ({e})") from e
        fm = parsed if isinstance(parsed, dict) else {}
    return fm, raw[m.end() :] if m else raw


# ---- reading files and folders ------------------------------------------------


def _tool_data(folder: Path, tool: dict) -> dict:
    """What the tool's libraries embed: only the data of those it asks for (`tool.include:`), so
    a function's templates are not copied into its tool. A library's key under `tool:` (such as
    `tool.templates`, which narrows them) needs the library there."""
    include = tool.get("include")
    asked = (
        [n for n in include if n in BY_NAME and BY_NAME[n].for_tools]
        if isinstance(include, list)
        else []
    )
    for name in _tool_library_keys():
        if name in tool and name not in asked:
            raise OwppError(
                f"{folder.name}/plugin.yaml: tool.{name} needs `{name}` in tool.include"
            )
    return {name: BY_NAME[name].read_tool(folder, tool) for name in asked}


def _tool_library_keys() -> list[str]:
    """The keys under `tool:` that belong to a library a tool may ask for."""
    return [lib.name for lib in LIBRARIES if lib.for_tools]


def _tool_valves(folder: Path, valves: Any) -> dict:
    if valves is None:
        return {}
    if not isinstance(valves, dict):
        raise OwppError(
            f"{folder.name}/plugin.yaml: tool.valves must be a map of valve name to value"
        )
    return valves


def _plugin_resources(plugin: ResolvedPlugin) -> dict:
    """The tool and skills a plugin declares, as the data the runtime installs."""
    folder, manifest = plugin.root, plugin.manifest
    parts = upstream_parts(manifest)
    tools: list[dict] = []
    tool = manifest.get("tool")
    if isinstance(tool, dict):
        is_self = parts.tool_is_function
        tool_id = text_of(coalesce(tool.get("id"), folder.name)).lower()
        if is_self:
            content = None
        elif parts.tool_file:
            content = plugin.read(parts.tool_file)
        else:
            code, from_lib = _bundle_code(
                folder,
                "tool",
                omit(
                    tool,
                    ["id", "from", "access", "file", "valves", "include", *_tool_library_keys()],
                ),
            )
            # A tool bundle carries the runtime too (below), with just the ids to remove.
            libs = wanted(tool.get("include"), set(), f"{folder.name}/plugin.yaml")
            _check_lib_imports(folder, from_lib, libs, runtime=True, include="tool.include")
            content = link(code, tool.get("include"), folder.name, None, _tool_data(folder, tool))
        tools.append(
            {
                "id": tool_id,
                "name": text_of(
                    coalesce(
                        tool.get("title"), coalesce(get(manifest.get("function"), "title"), tool_id)
                    )
                ),
                "access": "public" if tool.get("access") == "public" else "private",
                "self": is_self,
                "valves": _tool_valves(folder, tool.get("valves")),
                "content": content,
            }
        )

    skills: list[dict] = []

    def add_skill(label: str, skill_id: str, files: list[dict], access: Any = None) -> None:
        """`files` is the whole skill, SKILL.md included verbatim (with its front matter,
        as Open-WebUI's own importer stores it)."""
        root = next((f for f in files if f["path"] == "SKILL.md"), None)
        if root is None or "encoding" in root:
            raise OwppError(f"{label}: a skill needs a UTF-8 SKILL.md at its root")
        fm, _ = parse_skill(label, root["content"])
        skill_id = skill_id.lower()
        if not VALID_SKILL_ID.fullmatch(skill_id):
            raise OwppError(f"{label}: a skill id may only use a-z, 0-9, _ and -")
        if any(s["id"] == skill_id for s in skills):
            raise OwppError(f'{folder.name}: the skill id "{skill_id}" is declared twice')
        skills.append(
            {
                "id": skill_id,
                "name": text_of(coalesce(fm.get("name"), skill_id)),
                "description": " ".join(text_of(fm.get("description")).split()),
                "access": "public" if coalesce(access, fm.get("access")) == "public" else "private",
                "files": files,
            }
        )

    declared = manifest.get("skills")
    for skill_id, sk in declared.items() if isinstance(declared, dict) else []:
        label = f"{folder.name}/skills.{skill_id}"
        path, is_dir = parts.skill_path(skill_id) or ("", False)
        if is_dir:
            add_skill(label, str(skill_id), plugin.read_dir(path), sk.get("access"))
        elif path:
            text = plugin.read(path)
            add_skill(
                label, str(skill_id), [{"path": "SKILL.md", "content": text}], sk.get("access")
            )
        else:
            raise OwppError(f"{folder.name}/plugin.yaml: skills.{skill_id} needs a file or a dir")

    skills_dir = folder / "skills"
    if skills_dir.exists():
        with os.scandir(skills_dir) as it:
            local = sorted((e for e in it if e.is_dir(follow_symlinks=False)), key=lambda e: e.name)
        for sk in local:
            file = f"{folder.name}/skills/{sk.name}/SKILL.md"
            if not (skills_dir / sk.name / "SKILL.md").exists():
                raise OwppError(f"{file} is missing")
            add_skill(file, sk.name, folder_files(skills_dir / sk.name))

    # A tool carries the runtime too (with just the ids to remove), so that when it loads
    # after a restart it can notice its function was disabled in the meantime and remove
    # the plugin. The function's own runtime data lists the full content, which a tool
    # must not embed in itself.
    ids = {
        "tools": [{"id": t["id"]} for t in tools],
        "skills": [{"id": k["id"]} for k in skills],
    }
    for t in tools:
        if not t["self"]:
            t["content"] = embed_runtime(t["content"], ids)
    return {"tools": tools, "skills": skills}


def env_references(folder: Path | str) -> list[tuple[str, str | None]]:
    """The environment variables a plugin's `jobs:` and config.yaml refer to, with their defaults:
    what the Open-WebUI container may set. Nothing here reads the environment."""
    folder = Path(folder)
    manifest = read_manifest(folder)
    config = BY_NAME["config"].read(folder, manifest)
    return envtemplate.references([manifest.get("jobs"), config])


# The library mixins that are PluginEvents classes themselves.
_EVENT_BASES = {"PluginEvents", "PluginAssets", "PluginScheduledSync"}
_MOUNTERS = {"include_router", "add_api_route", "add_route", "add_api_websocket_route", "mount"}
# What changes a list in place: on app.routes it adds or removes routes past the guard.
_LIST_CHANGES = {"insert", "append", "extend", "remove", "pop", "clear", "sort", "reverse"}


def _refuse_direct_mounts(folder: Path, code: str) -> None:
    """Routes added straight to the app skip the sign-in check that plugin_mount puts on every
    route, so the function's own code may not do it."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return  # `owpp check` reports it

    def on_app(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in ("app", "__app__", "application")
        if isinstance(node, ast.Attribute):  # request.app, app.router
            return node.attr == "app" or (node.attr == "router" and on_app(node.value))
        return False

    def route_list(node: ast.AST) -> bool:
        """`<app>.routes` or `<app>.router.routes`, or a subscript of it (`app.routes[:]`)."""
        if isinstance(node, ast.Subscript):
            node = node.value
        return isinstance(node, ast.Attribute) and node.attr == "routes" and on_app(node.value)

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MOUNTERS
            and on_app(node.func.value)
        ):
            found.append(
                (
                    node.lineno,
                    f"`.{node.func.attr}()` on the app adds a route that skips the sign-in check",
                )
            )
        change = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LIST_CHANGES
            and route_list(node.func.value)
        ):
            change = f"`{ast.unparse(node.func)}()`"
        elif isinstance(node, ast.Delete) and any(route_list(t) for t in node.targets):
            change = f"`{ast.unparse(node)}`"
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            hit = next((t for t in targets if route_list(t)), None)
            if hit is not None:
                op = "+=" if isinstance(node, ast.AugAssign) else "="
                change = f"`{ast.unparse(hit)} {op} ...`"
        if change:
            found.append(
                (
                    node.lineno,
                    f"{change} changes the app's route list directly, which adds routes that skip "
                    "the sign-in check (or removes Open-WebUI's own)",
                )
            )
    if found:
        line, what = min(found)
        raise OwppError(
            f"{folder}: line {line}: {what}; mount routes with plugin_mount(), which requires a "
            "signed-in user on every route"
        )


def _is_on_decorator(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "on"


def _check_events(folder: Path, code: str) -> None:
    """`@on("event.name")` handlers: the names must be event names (a typo would never fire),
    and the class must inherit PluginEvents, or nothing would ever call them."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return  # `owpp check` reports it
    # Module-level `NAME = "event.name"` constants may be used in @on(NAME).
    constants = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}

    def base_names(cls: ast.ClassDef) -> list[str]:
        return [
            b.id if isinstance(b, ast.Name) else b.attr
            for b in cls.bases
            if isinstance(b, (ast.Name, ast.Attribute))
        ]

    def inherits_events(cls: ast.ClassDef, seen: frozenset = frozenset()) -> bool:
        """PluginEvents is a base, directly or through a class defined in this file."""
        return any(
            name in _EVENT_BASES
            or (
                name in classes
                and name not in seen
                and inherits_events(classes[name], seen | {name})
            )
            for name in base_names(cls)
        )

    def all_bases_known(cls: ast.ClassDef, seen: frozenset = frozenset()) -> bool:
        """Every base is one we can see into: `object`, or a class defined in this file."""
        return all(
            name == "object"
            or (
                name in classes
                and name not in seen
                and all_bases_known(classes[name], seen | {name})
            )
            for name in base_names(cls)
        ) and len(base_names(cls)) == len(cls.bases)

    for cls in classes.values():
        handlers = [
            (method, decorator)
            for method in cls.body
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            for decorator in method.decorator_list
            if _is_on_decorator(decorator)
        ]
        for _method, decorator in handlers:
            if not decorator.args:
                raise OwppError(f"{folder}: line {decorator.lineno}: @on() needs an event name")
            for arg in decorator.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    name = arg.value
                elif isinstance(arg, ast.Name) and arg.id in constants:
                    name = constants[arg.id]
                else:
                    raise OwppError(
                        f"{folder}: line {arg.lineno}: @on() takes event names written as strings "
                        "or module-level string constants, so they can be checked"
                    )
                problem = problem_with(name)
                if problem:
                    raise OwppError(f"{folder}: line {arg.lineno}: {problem}")
        # An unknown base (imported from elsewhere) might inherit it, so only refuse what is certain.
        if handlers and not inherits_events(cls) and all_bases_known(cls):
            raise OwppError(
                f"{folder}: line {cls.lineno}: class {cls.name} has @on handlers but does not "
                f"inherit PluginEvents, so none would ever be called: `class {cls.name}(PluginEvents)`"
            )


_ASSETS_ONLY_EVENT = '''
class Event(PluginAssets):
    """Does nothing itself: this function publishes the plugin's assets/ files."""
'''


def _stub_parent(res: dict) -> str:
    """A parent that does nothing itself, for a plugin that is only a tool and skills.
    Global, so Open-WebUI loads it at startup and the runtime installs the rest."""
    valves = []
    if res["tools"]:
        valves.append(
            "        INSTALL_TOOLS: bool = Field(\n"
            '            default=True, description="Install this plugin\'s tool. Off removes it, leaving the rest."\n'
            "        )"
        )
    if res["skills"]:
        valves.append(
            "        INSTALL_SKILLS: bool = Field(\n"
            '            default=True, description="Install this plugin\'s skills. Off removes them, leaving the rest."\n'
            "        )"
        )
    if res["tools"]:
        valves.append(
            "        TOOL_VALVES: str = Field(\n"
            '            default="{}",\n'
            '            description=\'JSON: {"<tool id>": {"<valve>": value}} sets those valves on the tool '
            "each time it syncs (they win over plugin.yaml and manual edits).',\n"
            "        )"
        )
    joined = "\n".join(valves)
    return f'''
from pydantic import BaseModel, Field


class Filter:
    """Does nothing itself: this function installs and removes the plugin's tool and skills."""

    class Valves(BaseModel):
{joined}

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, **kwargs) -> dict:
        await plugin_ensure()
        return body
'''


# ---- the function bundle --------------------------------------------------------


def _offline(git: str, ref: str, paths: list[str]) -> dict:
    raise OwppError(
        f"{git} at {ref[:7]}: reading a plugin's `source:` needs a Sources; "
        "bundle it with bundle_function(Sources().resolve(folder))"
    )


def bundle_function(plugin: Path | str | ResolvedPlugin) -> str | None:
    """The function's bundled code (with the runtime and the embedded tool and skills when
    the plugin declares them), or None when there is no function section.

    A path is bundled as it is on disk; a plugin that takes files from git must be resolved
    first (Sources.resolve)."""
    if not isinstance(plugin, ResolvedPlugin):
        with Sources(_offline) as offline:
            return bundle_function(offline.resolve(plugin))
    folder, manifest = plugin.root, plugin.manifest
    fn = manifest.get("function")
    from_lib: dict[str, str] = {}
    res = _plugin_resources(plugin)
    has_resources = bool(res["tools"] or res["skills"])
    if not isinstance(fn, dict):
        if has_resources:
            raise OwppError(
                f"{folder}/plugin.yaml: a tool or skills need a `function:` section; the "
                "function is the parent that installs and removes them"
            )
        return None
    keys = omit(fn, ["valves"])
    held, data = _library_data(folder, manifest)
    assets = data.get("assets")
    parts = upstream_parts(manifest)
    if parts.function:
        # The function itself comes from `source`, verbatim (its own header and all).
        extra = list(omit(fn, ["file", "global", "valves"]))
        if not manifest.get("source"):
            raise OwppError(f"{folder}/plugin.yaml: function.file needs a `source:`")
        if extra:
            raise OwppError(
                f"{folder}/plugin.yaml: with function.file the header comes from the file; "
                f"remove {', '.join(extra)}"
            )
        code = plugin.read(parts.function_file)
    elif not _has_code(folder, "function") and assets is not None:
        if has_resources:
            raise OwppError(
                f"{folder}: assets/ together with a tool or skills needs a function.py "
                "(an Event class); the generated parent can only be one of them"
            )
        code = render_header(folder, keys) + _ASSETS_ONLY_EVENT
    elif not _has_code(folder, "function") and has_resources:
        code = render_header(folder, keys) + _stub_parent(res)
    else:
        code, from_lib = _bundle_code(folder, "function", keys)
        _refuse_direct_mounts(folder, code)
        _check_events(folder, code)
    if assets is not None and not re.search(
        r"^class Event\([^)]*\bPluginAssets\b", code, re.MULTILINE
    ):
        raise OwppError(
            f"{folder}: with an assets/ folder the function must define `class Event(PluginAssets)`, "
            "which publishes the files (or delete function.py to have it generated)"
        )
    if from_lib:
        libs = wanted(manifest.get("include"), held, f"{folder.name}/plugin.yaml")
        _check_lib_imports(folder, from_lib, libs, runtime=has_resources, include="include")
    code = link(code, manifest.get("include"), folder.name, held, data)
    if has_resources:
        code = embed_runtime(code, res)
    return code


def _library_data(folder: Path, manifest: dict) -> tuple[set[str], dict]:
    """The data each library reads from the plugin's folder ({library name: data}), and what the
    plugin holds that turns libraries on: whatever there is data for."""
    data = {}
    for lib in LIBRARIES:
        if lib.read and (value := lib.read(folder, manifest)) is not None:
            data[lib.name] = value
    return {BY_NAME[name].on_when for name in data}, data


def file_libraries(folder: Path) -> dict[str, set[str]]:
    """The libraries each source file is bundled with: the function's, the tool's, and both
    for shared.py, which goes into each."""
    manifest = read_manifest(folder)
    held, _ = _library_data(folder, manifest)
    tool = manifest.get("tool") if isinstance(manifest.get("tool"), dict) else {}
    where = f"{folder.name}/plugin.yaml"
    function = set(wanted(manifest.get("include"), held, where))
    tool_libs = set(wanted(tool.get("include"), set(), where)) if tool else set()
    return {"function.py": function, "tool.py": tool_libs, "shared.py": function | tool_libs}


def library_code(folder: Path | str, name: str = "function") -> str:
    """The libraries `name`.py (function or tool) is bundled with, and the runtime when the bundle
    has it, as the code of one module, with this plugin's data: what owpp.testing.plugin_source()
    gives a plugin file in place of owpp.lib. shared.py is bundled into both, so it gets the
    function's. A plugin folder on disk, not one that takes code from git."""
    folder = Path(folder)
    with Sources(_offline) as offline:
        plugin = offline.resolve(folder)
    manifest = plugin.manifest
    header = '"""\n"""\n'
    res = _plugin_resources(plugin)
    if name == "tool":
        tool = manifest.get("tool") if isinstance(manifest.get("tool"), dict) else {}
        code = link(header, tool.get("include"), folder.name, None, _tool_data(folder, tool))
        ids = {
            "tools": [{"id": t["id"]} for t in res["tools"]],
            "skills": [{"id": k["id"]} for k in res["skills"]],
        }
        return embed_runtime(code, ids)
    held, data = _library_data(folder, manifest)
    code = link(header, manifest.get("include"), folder.name, held, data)
    if res["tools"] or res["skills"]:
        code = embed_runtime(code, res)
    return code


# ---- what Open-WebUI makes of it ------------------------------------------------

FUNCTION_TYPES = {"Pipe": "pipe", "Filter": "filter", "Action": "action", "Event": "event"}


def function_type(content: str) -> list[str]:
    """Open-WebUI decides a function's type from which class it defines at the top level
    (the same test is used here, so the deploy and the report agree with it)."""
    found = [
        FUNCTION_TYPES[m.group(1)]
        for m in re.finditer(r"^class (Pipe|Filter|Action|Event)\b", content, re.MULTILINE)
    ]
    return list(dict.fromkeys(found))


@dataclass
class FunctionFile:
    """One function to deploy.

    `root` is the folder that was bundled, when it stays on disk: the plugin's folder in the
    plugins folder, or for a plugin taken whole from git its `.owpp/modules/<id>`. It is None
    when that folder is a temporary one: a scratch copy of a whole plugin (its Sources keeps no
    `.owpp/`; `Sources.resolve` gives the copy while it is open), or anything made from a
    temporary copy of the plugins folder (a build at the latest commits, the old tree of
    `check --since`). It is also None for a loose <id>.py and a function read from a build."""

    id: str
    content: str = ""
    file: str = ""
    type: str = ""
    kind: str = "function"
    want_global: bool = False
    not_global: bool = False  # `global: false`: never global, kept so on every run
    valves: dict | None = None
    name: str = ""
    # What the deploy stores with it (function_meta): the description, the commit of each git
    # source ({"<git>[ <path>]": sha}) and the instance settings it `requires:`.
    meta: FunctionMeta = field(default_factory=lambda: FunctionMeta(MANAGED_BY, requires={}))
    root: Path | None = None


def function_meta(content: str, plugin: ResolvedPlugin | None = None) -> FunctionMeta:
    """The meta a deploy stores with a function, under its default ownership marker: the
    header's description behind the note the UI shows and, for a plugin folder, the commits its
    sources were pinned to and what its manifest `requires:`."""
    description = " ".join(text_of(parse_frontmatter(content).get("description")).split())
    requires = plugin.manifest.get("requires") if plugin else None
    return FunctionMeta(
        managed_by=MANAGED_BY,
        description=f"{NOTE} {description}" if description else NOTE,
        sources=dict(plugin.pins) if plugin else {},
        requires=dict(requires) if isinstance(requires, dict) else {},
    )


def _make_item(
    kind: str,
    id: str,
    file: str,
    content: str,
    valves: dict | None = None,
    global_: bool | None = None,
    plugin: ResolvedPlugin | None = None,
) -> FunctionFile:
    check_frontmatter(file, content)
    meta = parse_frontmatter(content)
    types = function_type(content)
    if len(types) != 1:
        raise OwppError(
            f"{file}: a function defines exactly one of class Pipe, Filter, Action or Event "
            f"(found {', '.join(types) if types else 'none'})"
        )
    declared = global_ if global_ is not None else meta.get("global")
    want_global = declared is True
    if want_global and types[0] in ("event", "pipe"):
        raise OwppError(
            f"{file}: `global` only applies to filters and actions, not to {types[0]} functions"
        )
    return FunctionFile(
        kind=kind,
        type=types[0],
        file=file,
        id=id.lower(),
        want_global=want_global,
        not_global=declared is False,
        content=content,
        valves=valves,
        name=text_of(coalesce(meta.get("title"), id)),
        meta=function_meta(content, plugin),
    )


def load_function_files(
    directory: Path | str, sources: Sources | None = None
) -> list[FunctionFile]:
    """Every function in the plugins folder: plugin folders and loose <id>.py files. A plugin
    that takes files from git is resolved with `sources` (without it, such a plugin is refused)."""
    if sources is None:
        with Sources(_offline) as offline:
            return load_function_files(directory, offline)
    directory = Path(directory)
    with os.scandir(directory) as it:
        entries = sorted(it, key=lambda e: e.name)
    loaded: list[FunctionFile] = []
    folders = {p.name for p in plugin_folders(directory)}
    for e in entries:
        if e.is_file(follow_symlinks=False) and e.name.endswith(".py"):
            loaded.append(
                _make_item(
                    "function",
                    e.name[: -len(".py")],
                    e.name,
                    read_text(e.path),
                )
            )
        elif e.name in folders:
            item = function_file(e.path, sources)
            if item is not None:
                loaded.append(item)
    return loaded


def function_file(folder: Path | str, sources: Sources) -> FunctionFile | None:
    """The function one plugin folder deploys, as `owpp deploy` sends it (None if the plugin
    has no function). Its id is the folder's name."""
    folder = Path(folder)
    plugin = sources.resolve(folder)
    content = bundle_function(plugin)
    if content is None:
        return None
    fn = plugin.manifest["function"]
    declared = fn.get("global")
    item = _make_item(
        "function",
        folder.name,
        f"{folder.name}/",
        content,
        valves=fn.get("valves"),
        global_=declared
        if isinstance(declared, bool) and upstream_parts(plugin.manifest).function
        else None,
        plugin=plugin,
    )
    item.root = None if plugin.temporary else plugin.root
    return item
