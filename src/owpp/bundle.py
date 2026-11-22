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
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import envtemplate
from .errors import OwppError
from .events import problem_with
from .flatten import flatten
from .libraries import BY_NAME, hoist_future, json_literal, link
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
from .sources import ResolvedPlugin, Sources

RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
RUNTIME = RUNTIME_DIR / "plugin_runtime.py"

NOTE = "Git-controlled: edits made here are overwritten on the next deploy."

# Open-WebUI's own rule: an identifier, lowercased.
VALID_ID = re.compile(r"[a-z_][a-z0-9_]*")
VALID_SKILL_ID = re.compile(r"[a-z0-9_-]+")

_DOCSTRING = re.compile(r'\s*"""\n?([\s\S]*?)"""')


# ---- header -----------------------------------------------------------------


def parse_frontmatter(content: str) -> dict:
    """The module docstring as Open-WebUI reads it: one `key: value` per line, split at
    the first colon. (Not YAML: a value such as `author: @G30` is fine here and invalid there.)"""
    m = _DOCSTRING.match(content)
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
    m = _DOCSTRING.match(content)
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


def _bundle_code(folder: Path, name: str, keys: dict) -> str:
    """Header, then shared.py (code both the function and the tool need), then
    function.py or tool.py. The built-in libraries are added after this (with_includes)."""
    file = folder / f"{name}.py"
    if not file.exists():
        raise OwppError(f"{folder}: no {name}.py")
    shared_file = folder / "shared.py"
    shared = read_text(shared_file) if shared_file.exists() else None
    if shared is not None:
        flatten("shared", shared, None, f"{shared_file}")
    code = flatten(name, read_text(file), shared, f"{file}")
    shared = shared or ""
    source = shared + code
    if shared:
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

    body = re.sub(r"\{\{file:([A-Za-z0-9_.-]+)\}\}", include, source)
    return render_header(folder, keys) + body


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


def _tool_valves(folder: Path, valves: Any) -> dict:
    if valves is None:
        return {}
    if not isinstance(valves, dict):
        raise OwppError(
            f"{folder.name}/plugin.yaml: tool.valves must be a map of valve name to value"
        )
    return valves


def _runtime_source(data: dict) -> str:
    return read_text(RUNTIME).replace("__PLUGIN_DATA__", json_literal(data), 1)


def _plugin_resources(plugin: ResolvedPlugin) -> dict:
    """The tool and skills a plugin declares, as the data the runtime installs."""
    folder, manifest = plugin.root, plugin.manifest
    tools: list[dict] = []
    tool = manifest.get("tool")
    if isinstance(tool, dict):
        is_self = tool.get("from") == "function"
        tool_id = text_of(coalesce(tool.get("id"), folder.name)).lower()
        if is_self:
            content = None
        elif tool.get("file"):
            content = plugin.read(tool["file"])
        else:
            content = link(
                _bundle_code(
                    folder,
                    "tool",
                    omit(tool, ["id", "from", "access", "file", "valves", "include"]),
                ),
                tool.get("include"),
                folder.name,
            )
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
        if get(sk, "dir"):
            add_skill(label, str(skill_id), plugin.read_dir(sk["dir"]), sk.get("access"))
        elif get(sk, "file"):
            text = plugin.read(sk["file"])
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
            t["content"] += _runtime_source(ids)
    return {"tools": tools, "skills": skills}


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
    cfg = coalesce(manifest.get("static"), {})
    if not isinstance(cfg, dict):
        raise OwppError(f"{where} must be a mapping (prefix, access)")
    unknown = [str(k) for k in cfg if k not in ("prefix", "access")]
    if unknown:
        raise OwppError(f"{where}: unknown key {', '.join(unknown)} (known: prefix, access)")
    access = coalesce(cfg.get("access"), "user")
    if access not in ACCESS_LEVELS:
        raise OwppError(
            f"{where}.access must be user, admin or public (exactly one of those words), "
            f"not {access!r}: files need a signed-in user unless it says public in so many words"
        )
    prefix = text_of(coalesce(get(cfg, "prefix"), f"/{folder.name}"))
    if not re.fullmatch(r"/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*", prefix):
        raise OwppError(f"{where}.prefix must be a path such as /name (letters, digits, _ and -)")
    files = {f["path"]: omit(f, ["path"]) for f in folder_files(folder / "static")}
    if not files:
        raise OwppError(f"{folder.name}: static/ has no files")
    return {"prefix": prefix, "access": access, "files": files}


def _read_templates(folder: Path) -> dict | None:
    """The plugin's templates/ folder: files embedded in the function bundle and read back with
    plugin_template_text(). They are never served."""
    if not (folder / "templates").exists():
        return None
    files = {f["path"]: omit(f, ["path"]) for f in folder_files(folder / "templates")}
    if not files:
        raise OwppError(f"{folder.name}: templates/ has no files")
    return files


ASSET_FILES = ("loader.js", "custom.css")


def _read_assets(folder: Path, manifest: dict) -> dict | None:
    """assets/loader.js and assets/custom.css: this plugin's fragments of the Shared Assets
    Protocol's two files, embedded as text and published by the assets library."""
    where = f"{folder.name}/plugin.yaml: assets"
    cfg = manifest.get("assets")
    if not (folder / "assets").exists():
        if cfg is not None:
            raise OwppError(f"{where} needs an assets/ folder")
        return None
    cfg = coalesce(cfg, {})
    if not isinstance(cfg, dict):
        raise OwppError(f"{where} must be a mapping (order, wrap)")
    unknown = [str(k) for k in cfg if k not in ("order", "wrap")]
    if unknown:
        raise OwppError(f"{where}: unknown key {', '.join(unknown)} (known: order, wrap)")
    order = coalesce(cfg.get("order"), 0)
    if isinstance(order, bool) or not isinstance(order, int):
        raise OwppError(f"{where}.order must be a whole number (lower composes first)")
    wrap = coalesce(cfg.get("wrap"), True)
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


def _read_jobs(folder: Path, manifest: dict) -> dict:
    """`jobs: {sync_every_minutes: N, adopt_markers: [...]}`: the default of the
    SYNC_INTERVAL_MINUTES valve that the sync mixin adds to the function (0 = only on startup,
    enable and valve changes), and the markers of an earlier sync to treat as its own."""
    jobs = _read_jobs_interval(folder, manifest)
    cfg = manifest.get("jobs")
    markers = cfg.get("adopt_markers") if isinstance(cfg, dict) else None
    if markers is not None:
        where = f"{folder.name}/plugin.yaml: jobs.adopt_markers"
        if not isinstance(markers, list) or not all(
            isinstance(m, str) and m.strip() and m == m.strip() for m in markers
        ):
            raise OwppError(f"{where} must be a list of markers (non-empty text, no spaces around)")
        if markers:
            jobs["adopt_markers"] = list(dict.fromkeys(markers))
    return jobs


def _read_jobs_interval(folder: Path, manifest: dict) -> dict:
    where = f"{folder.name}/plugin.yaml: jobs"
    cfg = manifest.get("jobs")
    if cfg is None:
        return dict(BY_NAME["jobs"].default)
    if not isinstance(cfg, dict):
        raise OwppError(f"{where} must be a mapping (sync_every_minutes, adopt_markers)")
    unknown = [str(k) for k in cfg if k not in ("sync_every_minutes", "adopt_markers")]
    if unknown:
        raise OwppError(
            f"{where}: unknown key {', '.join(unknown)} (known: sync_every_minutes, adopt_markers)"
        )
    minutes = coalesce(cfg.get("sync_every_minutes"), BY_NAME["jobs"].default["sync_every_minutes"])
    if isinstance(minutes, str):  # ${NAME} or ${NAME:-minutes}, resolved in the container
        template = envtemplate.TEMPLATE.fullmatch(minutes)
        default = template.group(2) if template else None
        if not template or (default is not None and not re.fullmatch(r"[0-9]+", default)):
            raise OwppError(
                f"{where}.sync_every_minutes must be a whole number of minutes, or a template "
                f"like ${{NAME:-60}} whose default is one (got {minutes!r})"
            )
        return {"sync_every_minutes": minutes}
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
        raise OwppError(f"{where}.sync_every_minutes must be a whole number of minutes, 0 or more")
    return {"sync_every_minutes": minutes}


def env_references(folder: Path | str) -> list[tuple[str, str | None]]:
    """The environment variables a plugin's `jobs:` and config.yaml refer to, with their defaults:
    what the Open-WebUI container may set. Nothing here reads the environment."""
    folder = Path(folder)
    manifest = read_manifest(folder)
    return envtemplate.references([manifest.get("jobs"), _read_config(folder)])


# The library mixins that are PluginEvents classes themselves.
_EVENT_BASES = {"PluginEvents", "PluginAssets", "PluginScheduledSync"}
_MOUNTERS = {"include_router", "add_api_route", "add_route", "add_api_websocket_route", "mount"}


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

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MOUNTERS
            and on_app(node.func.value)
        ):
            raise OwppError(
                f"{folder}: line {node.lineno}: `.{node.func.attr}()` on the app adds a route that "
                "skips the sign-in check; mount routes with plugin_mount(), which requires a "
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


def _read_config(folder: Path) -> dict | None:
    """The plugin's config.yaml, parsed now and embedded as data; the function reads it with
    plugin_config(). It is in git, so secrets do not belong in it."""
    path = folder / "config.yaml"
    if not path.exists():
        return None
    try:
        config = parse_yaml(read_text(path))
    except yaml.YAMLError as e:
        raise OwppError(f"{folder.name}/config.yaml: not valid YAML ({e})") from e
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise OwppError(f"{folder.name}/config.yaml: must be a mapping (key: value)")
    if bad := envtemplate.problems(config):
        raise OwppError(f"{folder.name}/config.yaml: {bad[0]}")
    return config


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
        await _plugin_ensure()
        return body
'''


ACCESS_LEVELS = (
    "user",
    "admin",
    "public",
)  # signed-in is the default; "public" must be spelled out


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
    assets = _read_assets(folder, manifest)
    if "file" in fn:
        # The function itself comes from `source`, verbatim (its own header and all).
        extra = list(omit(fn, ["file", "global", "valves"]))
        if not manifest.get("source"):
            raise OwppError(f"{folder}/plugin.yaml: function.file needs a `source:`")
        if extra:
            raise OwppError(
                f"{folder}/plugin.yaml: with function.file the header comes from the file; "
                f"remove {', '.join(extra)}"
            )
        code = plugin.read(fn["file"])
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
        code = _bundle_code(folder, "function", keys)
        _refuse_direct_mounts(folder, code)
        _check_events(folder, code)
    if assets is not None and not re.search(
        r"^class Event\([^)]*\bPluginAssets\b", code, re.MULTILINE
    ):
        raise OwppError(
            f"{folder}: with an assets/ folder the function must define `class Event(PluginAssets)`, "
            "which publishes the files (or delete function.py to have it generated)"
        )
    static = _read_static(folder, manifest)
    templates = _read_templates(folder)
    config = _read_config(folder)
    jobs = _read_jobs(folder, manifest)
    held = {
        name
        for name, present in (
            ("jobs:", manifest.get("jobs") is not None),
            ("static/", bool(static)),
            ("templates/", templates is not None),
            ("assets/", assets is not None),
            ("config.yaml", config is not None),
        )
        if present
    }
    data = {
        "static": static,
        "templates": templates,
        "assets": assets,
        "config": config,
        "jobs": jobs,
    }
    code = link(code, manifest.get("include"), folder.name, held, data)
    if has_resources:
        code += _runtime_source(res)
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
    """One function to deploy."""

    id: str
    content: str = ""
    file: str = ""
    type: str = ""
    kind: str = "function"
    want_global: bool = False
    not_global: bool = False  # `global: false`: never global, kept so on every run
    valves: dict | None = None
    name: str = ""
    description: str = ""
    # The git repository the plugin takes code from, and the commit: {"<git>[ <path>]": sha}.
    sources: dict = field(default_factory=dict)
    # Instance settings the plugin needs (`requires:`), for the deploy's warning.
    requires: dict = field(default_factory=dict)
    # The folder that was bundled: the plugin folder, or for a plugin taken whole from git the
    # upstream folder as fetched, with the local overrides applied. None for a loose <id>.py.
    root: Path | None = None


def runtime_data(content: str | None) -> dict:
    """The tool and skills a function bundle installs (its embedded runtime data):
    {"tools": [...], "skills": [...]}, empty for code with none."""
    m = re.search(r'_PLUGIN = _json\.loads\((".*")\)\n', content or "")
    if not m:
        return {"tools": [], "skills": []}
    data = json.loads(json.loads(m.group(1)))
    return {"tools": data.get("tools", []), "skills": data.get("skills", [])}


def _make_item(
    kind: str,
    id: str,
    file: str,
    content: str,
    valves: dict | None = None,
    global_: bool | None = None,
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
    description = " ".join(text_of(meta.get("description")).split())
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
        description=f"{NOTE} {description}" if description else NOTE,
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
            plugin = sources.resolve(e.path)
            content = bundle_function(plugin)
            if content is None:
                continue
            fn = plugin.manifest["function"]
            declared = fn.get("global")
            item = _make_item(
                "function",
                e.name,
                f"{e.name}/",
                content,
                valves=fn.get("valves"),
                global_=declared if isinstance(declared, bool) and "file" in fn else None,
            )
            item.root = plugin.root
            item.sources = dict(plugin.pins)
            requires = plugin.manifest.get("requires")
            item.requires = dict(requires) if isinstance(requires, dict) else {}
            loaded.append(item)
    return loaded
