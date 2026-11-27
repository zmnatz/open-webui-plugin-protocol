"""`owpp import`: code that already exists becomes a plugin folder, ready to test.

- **A function's code** (a file, or a function read from Open-WebUI): its docstring header moves
  into plugin.yaml under `function:`, and the rest is function.py, so the bundle is the code
  again. A README, a CHANGELOG and a first test are written beside it.
- **A folder in a git repository**: the function, the tool and the skills in it are found and
  pinned at the commit its branch points at (`source:`), never copied. The folder is written by
  `owpp create`'s renderer, as a spec of type `upstream` (or `installer`) would write it.

Nothing here decides who may use what it installs: a tool and skills are private (admins only)
unless asked otherwise, and the report says so.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .bundle import (
    DOCSTRING,
    VALID_ID,
    VALID_SKILL_ID,
    function_type,
    parse_frontmatter,
    parse_skill,
)
from .create import PluginSpec, SkillSpec, SourceSpec, ToolSpec, _yaml, write_plugin
from .errors import OwppError
from .imports import add_lib_imports
from .libraries import BY_NAME, LIBRARIES, VENDORED
from .manifest import Value, files_of, read_text
from .openwebui import FunctionMeta, field_of
from .protocol import VERSION as PROTOCOL_VERSION
from .sources import GIT_URL, Sources, refname
from .unbundle import Unbundled, unbundle
from .versioning import changelog_text

# Header keys that mean something else in plugin.yaml's `function:` section.
_MANIFEST_ONLY = ("file", "valves")
_HEADER_KEY = re.compile(r"[A-Za-z_]+")


@dataclass
class Imported:
    """The plugin folder an import wrote, and what the person should know about it."""

    folder: Path
    notes: list[str] = field(default_factory=list)


def to_id(name: str) -> str:
    """A function id from a file or folder name: lowercase, `[a-z0-9_]`, not starting with a
    digit (`Shout-It.py` -> `shout_it`)."""
    stem = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    stem = re.sub(r"_+", "_", stem)
    if stem[:1].isdigit():
        stem = f"_{stem}"
    if not VALID_ID.fullmatch(stem):
        raise OwppError(f"cannot make a function id from {name!r}: give one with --id")
    return stem


def _check_id(plugin_id: str) -> str:
    if not VALID_ID.fullmatch(plugin_id):
        raise OwppError(
            f'"{plugin_id}" is not a valid id: lowercase letters, digits and _ (no hyphens)'
        )
    return plugin_id


def _header_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return _yaml(str(value))


def _write(folder: Path, files: dict[str, str | bytes]) -> None:
    if folder.exists():
        raise OwppError(f"{folder} already exists")
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))


def _flow(value: Any) -> str:
    """A value on one line of plugin.yaml: JSON, which YAML reads as it is."""
    return json.dumps(value, ensure_ascii=False)


def _header_keys(header: dict) -> dict:
    return {k: v for k, v in header.items() if _HEADER_KEY.fullmatch(k) and str(v).strip()}


def _taken_out(
    plugin_id: str, own: Unbundled
) -> tuple[list[str], dict[str, str | bytes], list[str]]:
    """What unbundling took out of a function, back as plugin.yaml lines, files and notes."""
    lines: list[str] = []
    files: dict[str, str | bytes] = {}
    notes: list[str] = []
    if own.include:
        lines.append(f"include: [{', '.join(own.include)}]")
    templates = own.data.get("templates")
    if templates is not None:
        files |= {f"templates/{p}": v for p, v in files_of(templates).items()}
    for name in ("static", "assets"):
        if (value := own.data.get(name)) is not None:
            got, keys = BY_NAME[name].write(plugin_id, value)
            files |= got
            lines += [f"{key}: {_flow(v)}" for key, v in keys.items()]
    jobs = own.data.get("jobs")
    if jobs is not None and jobs != BY_NAME["jobs"].default:
        lines.append(f"jobs: {_flow(jobs)}")
    if (config := own.data.get("config")) is not None:
        files["config.yaml"] = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    left = [
        lib.name
        for lib in LIBRARIES
        if lib.name not in own.found and lib.name not in VENDORED and lib.end in own.code
    ]
    protocol = [n for n in VENDORED if n not in own.found and BY_NAME[n].end in own.code]
    if protocol:
        notes.append(
            "its Shared Assets Protocol block is not byte-identical to owpp's (another version "
            "of the protocol), so it stays in function.py, where `owpp check` refuses its change "
            "to app.routes: import it from git instead (`owpp import <URL>`), which takes the "
            f"code as it is, or replace the block with include: [{', '.join(protocol)}]"
        )
    if left:
        notes.append(
            f"function.py still holds owpp's {', '.join(left)} (a `# end ...` line): a copy this "
            "owpp does not recognise, from another version. Delete each block and add its name "
            "to include:, or `owpp check` refuses what it does"
        )
    if own.found:
        notes.append(
            f"owpp's code in it is back to what it was made from: {', '.join(own.found)}"
            + (f" (include: [{', '.join(own.include)}])" if own.include else "")
        )
    if len(own.tools) > 1:
        raise OwppError(
            f"the function installs {len(own.tools)} tools ({', '.join(t['id'] for t in own.tools)}); "
            "owpp takes one tool per plugin"
        )
    for tool in own.tools:
        lines += ["tool:", f"  id: {tool['id']}"]
        if tool.get("access") == "public":
            lines.append("  access: public")
        if tool.get("valves"):
            lines.append(f"  valves: {_flow(tool['valves'])}")
        if tool.get("self"):
            lines.append("  from: function")
            notes.append(f"the tool {tool['id']} is the function itself (tool: from: function)")
            continue
        code = unbundle(tool.get("content") or "")
        m = DOCSTRING.match(code.code)
        keys = _header_keys(parse_frontmatter(code.code)) if m else {}
        lines += [f"  {k}: {_header_value(v)}" for k, v in keys.items()]
        # A tool's libraries are never turned on by the plugin's files: it names them all.
        tool_include = [
            lib.name
            for lib in LIBRARIES
            if lib.name in code.include or (lib.for_tools and lib.name in code.data)
        ]
        if tool_include:
            lines.append(f"  include: [{', '.join(tool_include)}]")
        theirs = code.data.get("templates")
        if theirs is not None:
            if templates is None or set(theirs) != set(templates):
                lines.append(f"  templates: {_flow(sorted(theirs))}")
            files |= {
                f"templates/{p}": v
                for p, v in files_of(theirs).items()
                if f"templates/{p}" not in files
            }
        body = code.code[m.end() :] if m else code.code
        files["tool.py"] = add_lib_imports(body[1:] if body.startswith("\n") else body)
        notes.append(
            f"the tool {tool['id']} came with it: tool.py and `tool:` in plugin.yaml. Code the "
            "function and the tool shared (a shared.py) is in both files now: it can go back "
            "into a shared.py"
        )
    for skill in own.skills:
        skill_files = files_of(skill.get("files") or [])
        root = skill_files.get("SKILL.md")
        front = parse_skill("SKILL.md", root)[0] if isinstance(root, str) else {}
        if skill.get("access") == "public" and front.get("access") != "public":
            # A local skill says it is public in its front matter (docs/plugin-format.md).
            assert isinstance(root, str)
            end = root.index("\n---", 3)
            skill_files["SKILL.md"] = root[:end] + "\naccess: public" + root[end:]
            notes.append(f"the skill {skill['id']} is public: its SKILL.md now says access: public")
        files |= {f"skills/{skill['id']}/{p}": v for p, v in skill_files.items()}
    if own.skills:
        notes.append(f"skills that came with it: {', '.join(s['id'] for s in own.skills)}")
    return lines, files, notes


def import_code(
    directory: Path | str,
    content: str,
    plugin_id: str,
    where: str,
    today: str | None = None,
    requires: dict | None = None,
) -> Imported:
    """Write `<directory>/<plugin_id>/` from a function's code: plugin.yaml holds its header,
    function.py the rest. `where` says where the code came from, for the README; `requires` is
    plugin.yaml's `requires:`, when the deploy recorded it."""
    plugin_id = _check_id(plugin_id)
    m = DOCSTRING.match(content)
    header = parse_frontmatter(content)
    if not m or not header:
        raise OwppError(
            f"{where}: no docstring header (title:, version:, ...) at the top, so this is not "
            "a function as Open-WebUI stores it"
        )
    types = function_type(content)
    if len(types) != 1:
        raise OwppError(
            f"{where}: a function defines exactly one of class Pipe, Filter, Action or Event "
            f"(found {', '.join(types) if types else 'none'})"
        )
    own = unbundle(content)
    content = own.code
    m = DOCSTRING.match(content)
    extra, more_files, notes = _taken_out(plugin_id, own)
    for line in m.group(1).split("\n"):
        key, colon, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not line.strip():
            continue
        if not colon or not _HEADER_KEY.fullmatch(key) or not value:
            notes.append(f"dropped a header line that is not `key: value`: {line.strip()!r}")
            continue
        if key in _MANIFEST_ONLY:
            raise OwppError(
                f"{where}: the header's `{key}:` means something else in plugin.yaml; rename or "
                "remove it first"
            )
    keys = _header_keys(header)
    body = content[m.end() :]
    body = body[1:] if body.startswith("\n") else body
    if (
        own.found or own.tools or own.skills
    ):  # its code finds the libraries' names in scope no more: it imports them
        body = add_lib_imports(body)
    title = str(keys.get("title") or plugin_id)
    version = str(keys.get("version") or "")
    manifest = [
        f"# Imported from {where} by owpp import. The function: keys are its docstring header.",
        f'protocol: "{PROTOCOL_VERSION}"',
        "function:",
        *(f"  {k}: {_header_value(v)}" for k, v in keys.items()),
        *extra,
        *(["requires:", *(f"  {k}: {_flow(v)}" for k, v in requires.items())] if requires else []),
    ]
    files: dict[str, str | bytes] = {
        **more_files,
        "plugin.yaml": "\n".join(manifest) + "\n",
        "function.py": body,
        "README.md": _readme(plugin_id, title, types[0], where),
        f"tests/test_{plugin_id}.py": _first_test(plugin_id, title, types[0]),
    }
    if version:
        files["CHANGELOG.md"] = changelog_text(
            title,
            version,
            [f"Imported from {where}."],
            today or _dt.date.today().isoformat(),
        )
    folder = Path(directory) / plugin_id
    _write(folder, files)
    return Imported(folder, notes)


def import_file(
    directory: Path | str, path: Path | str, plugin_id: str = "", today: str | None = None
) -> Imported:
    """`import_code` for a `.py` file on disk; the id defaults to the file's name."""
    path = Path(path)
    if not path.is_file():
        raise OwppError(f"{path}: no such file")
    return import_code(directory, read_text(path), plugin_id or to_id(path.stem), path.name, today)


def import_instance(
    directory: Path | str, instance, function_id: str, plugin_id: str = "", today: str | None = None
) -> Imported:
    """`import_code` for a function on an Open-WebUI instance (an `Instance`, signed in as the
    deploy signs in). The id stays the instance's, so the first deploy updates that function."""
    from .deploy import sign_in

    sign_in(instance)
    stored = instance.open_webui.function(function_id)
    content = field_of(stored, "content")
    if not isinstance(content, str) or not content:
        raise OwppError(f"Open-WebUI returned no code for the function {function_id}")
    meta = FunctionMeta.of(stored)
    # Where it came from, without the instance's address: plugin.yaml and the README are committed.
    imported = import_code(
        directory,
        content,
        plugin_id or function_id,
        f"Open-WebUI (function {function_id})",
        today,
        meta.requires,
    )
    if meta.managed_by and meta.requires is None:
        imported.notes.append(
            "an owpp that did not record `requires:` deployed it: if its plugin.yaml had one "
            "(iframe_sandbox_allow_same_origin), add it back"
        )
    imported.notes.append(
        "valves are not copied (they may hold keys or passwords): the deploy keeps the "
        "instance's, and defaults go under `function: valves:` in plugin.yaml"
    )
    return imported


# ---- what an imported function's folder starts with ------------------------------------

_LIVE = {
    "filter": "Turn it on for a model (or make it global) and send a message.",
    "action": "Under a reply, press its button.",
    "pipe": "Pick its model in a new chat and send a message.",
    "event": "Restart Open-WebUI (or enable the function) and look for what it does.",
}


def _readme(plugin_id: str, title: str, kind: str, where: str) -> str:
    return "\n".join(
        [
            f"# {title}",
            "",
            f"Imported from {where} with `owpp import`: function.py is its code, and plugin.yaml",
            "holds its header. Say here what it does, and list its valves.",
            "",
            "## Test",
            "",
            f"- `owpp check {plugin_id} --strict` bundles it as the deploy does and compiles it.",
            f"- `owpp test {plugin_id}` runs `tests/` against a mock Open-WebUI.",
            f"- On a live Open-WebUI: {_LIVE[kind]}",
            "",
            "## Deploy",
            "",
            f"- Function type: **{kind}**.",
            f"- `owpp deploy --only {plugin_id} --dry-run`, then without `--dry-run`. A function",
            f"  with the id `{plugin_id}` already on the instance is updated, and kept that way.",
            f"- A change is a new version: `owpp version {plugin_id} patch`.",
            "",
        ]
    )


def _first_test(plugin_id: str, title: str, kind: str) -> str:
    return "\n".join(
        [
            f'"""{title} against a mock Open-WebUI: `owpp test {plugin_id}`.',
            "",
            "One test per behaviour belongs here: each method Open-WebUI calls, each valve and",
            'each branch (docs/testing/writing.md)."""',
            "",
            "",
            "def test_it_loads_as_the_function_it_is(plugin):",
            f'    """It loads in Open-WebUI as a {kind}.',
            "",
            f"    By hand: after the deploy, Admin Panel > Functions lists {title} as a {kind}.",
            '    """',
            f'    assert plugin.type == "{kind}"',
            "",
        ]
    )


# ---- from git -------------------------------------------------------------------------------


@dataclass
class GitTarget:
    """What a URL names: the repository to clone, the branch or tag ("" for the default
    branch), the folder in it ("" for the root), and a file in that folder ("" for none)."""

    git: str
    name: str = ""
    path: str = ""
    file: str = ""


_GITHUB = re.compile(
    r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/(tree|blob)/([^/]+)(?:/(.*?))?)?/?"
)
_GITLAB = re.compile(r"(https://[^/]+/.+?)(?:\.git)?/-/(tree|blob)/([^/]+)(?:/(.*?))?/?")


def parse_git_url(url: str, path: str = "", name: str = "") -> GitTarget:
    """The repository, branch or tag, folder and file a URL names. A GitHub or GitLab page's
    URL (`.../tree/<branch>/<folder>`, `.../blob/<branch>/<folder>/<file>`) names all four; a
    clone URL names only the repository, and `path` and `name` give the rest. The branch is the
    first part after tree/ or blob/: a branch with a slash in it needs the clone URL and `name`."""
    url = url.strip()
    if not GIT_URL.fullmatch(url) or url.startswith("file:"):
        raise OwppError(
            f"{url!r} is not a git URL owpp reads from: an https://, ssh:// or user@host:path "
            "repository (a page of one on GitHub or GitLab works too)"
        )
    kind = rest = ""
    if m := _GITHUB.fullmatch(url):
        git = f"https://github.com/{m.group(1)}/{m.group(2)}.git"
        kind, url_name, rest = m.group(3) or "", m.group(4) or "", m.group(5) or ""
    elif m := _GITLAB.fullmatch(url):
        git = f"{m.group(1)}.git"
        kind, url_name, rest = m.group(2), m.group(3), m.group(4) or ""
    else:
        git, url_name = url, ""
    folder, file = rest, ""
    if kind == "blob":
        folder, _, file = rest.rpartition("/")
    folder = folder or path
    return GitTarget(git, url_name or name, folder.strip("/"), file)


def _is_function(text: Value) -> bool:
    return isinstance(text, str) and bool(parse_frontmatter(text)) and len(function_type(text)) == 1


def _is_tool(text: Value) -> bool:
    return isinstance(text, str) and bool(re.search(r"^class Tools\b", text, re.M))


def _skills(files: dict[str, Value], public: bool) -> list[SkillSpec]:
    """Each SKILL.md, outside the folders of the ones found before it (a skill's own files may
    hold another)."""
    found: list[SkillSpec] = []
    dirs: list[str] = []
    for rel in sorted(files, key=lambda r: (r.count("/"), r)):
        if rel.rpartition("/")[2] != "SKILL.md":
            continue
        folder = rel.rpartition("/")[0]
        if any(folder == d or folder.startswith(f"{d}/") for d in dirs) or "" in dirs:
            continue
        text = files[rel]
        front, _ = parse_skill(rel, text) if isinstance(text, str) else ({}, "")
        raw = str(front.get("name") or folder.rpartition("/")[2] or "skill")
        skill_id = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-")
        if not VALID_SKILL_ID.fullmatch(skill_id):
            raise OwppError(f"{rel}: cannot make a skill id from {raw!r}")
        dirs.append(folder)
        found.append(
            SkillSpec(skill_id, path=folder or "SKILL.md", is_dir=bool(folder), public=public)
        )
    return found


def _whole_plugin(folder: Path, src: SourceSpec) -> None:
    lines = [
        "# Taken whole from git by owpp import: the upstream's plugin.yaml is its manifest.",
        f'protocol: "{PROTOCOL_VERSION}"',
        "source:",
        f"  git: {_yaml(src.git)}",
        f"  ref: {src.ref}",
        *([f"  branch: {src.branch}"] if src.branch else []),
        *([f"  tag: {src.tag}"] if src.tag else []),
        f"  path: {_yaml(src.path) if src.path else chr(34) * 2}",
        "  plugin: true",
    ]
    _write(folder, {"plugin.yaml": "\n".join(lines) + "\n"})


def import_git(
    directory: Path | str,
    url: str,
    *,
    sources: Sources,
    plugin_id: str = "",
    path: str = "",
    name: str = "",
    public: bool = False,
    today: str | None = None,
) -> Imported:
    """Write a plugin that takes what a folder of a git repository holds, pinned at the commit
    its branch (or tag, or the default branch) points at: the function (a .py with a header and
    one function class), the tool (a .py with `class Tools`) and each skill (a SKILL.md), or the
    whole folder when it is an owpp plugin (a plugin.yaml). Nothing is copied."""
    target = parse_git_url(url, path, name)
    git, where = target.git, target.path or "the repository's root"
    kind = ""
    if target.name:
        kind = sources.kind(git, target.name) or ""
        if not kind:
            raise OwppError(f"no branch or tag {target.name} in {git}")
        sha = sources.latest(git, refname(kind, target.name))
    else:
        sha = sources.latest(git, "HEAD")
    if not sha:
        raise OwppError(f"could not look up the commit of {target.name or 'HEAD'} in {git}")
    files = sources.files(git, sha, target.path)
    src = SourceSpec(
        git,
        sha,
        target.path,
        branch=target.name if kind == "branch" else "",
        tag=target.name if kind == "tag" else "",
    )
    repo = git.rstrip("/").rpartition("/")[2].rpartition(":")[2].removesuffix(".git")
    default_id = Path(target.file).stem if target.file else target.path.rpartition("/")[2] or repo
    plugin_id = _check_id(plugin_id) if plugin_id else to_id(default_id)
    pinned = (
        f"pinned {git} at {sha[:7]} ({f'{kind} {target.name}' if kind else 'the default branch'})"
    )
    if "plugin.yaml" in files:
        folder = Path(directory) / plugin_id
        _whole_plugin(folder, src)
        return Imported(
            folder,
            [
                f"{where} is an owpp plugin: taken whole, its plugin.yaml is the manifest",
                pinned,
                "its tests are the upstream's: `owpp test --upstream` runs them",
            ],
        )
    top = {rel: text for rel, text in files.items() if "/" not in rel and rel.endswith(".py")}
    if target.file:
        if not _is_function(files.get(target.file, "")):
            raise OwppError(
                f"{target.file} in {git} is not a function: it needs a docstring header and "
                "exactly one of class Pipe, Filter, Action or Event"
            )
        functions = [target.file]
    else:
        functions = sorted(rel for rel, text in top.items() if _is_function(text))
    tools = sorted(rel for rel, text in top.items() if _is_tool(text) and rel not in functions)
    for what, found in (("functions", functions), ("tools", tools)):
        if len(found) > 1:
            raise OwppError(
                f"two {what} in {where}: {', '.join(found)}. Import one function with the URL "
                "of its file (.../blob/<branch>/<path>)"
                if what == "functions"
                else f"two {what} in {where}: {', '.join(found)}; owpp takes one tool per plugin"
            )
    skills = _skills(files, public)
    if not (functions or tools or skills):
        raise OwppError(
            f"no function, tool or skill in {where} of {git}: a function is a .py with a "
            "docstring header and one function class, a tool a .py with class Tools, a skill a "
            "SKILL.md"
        )
    header = parse_frontmatter(files[functions[0]]) if functions else {}
    src.function_file = functions[0] if functions else ""
    spec = PluginSpec(
        plugin_id,
        type="upstream" if functions else "installer",
        title=str(header.get("title") or ""),
        description=" ".join(str(header.get("description") or "").split()),
        tool=ToolSpec(plugin_id, file=tools[0], public=public) if tools else None,
        skills=skills,
        source=src,
    )
    folder = write_plugin(directory, spec, today)
    found = [f"function {functions[0]}"] if functions else []
    found += [f"tool {tools[0]}"] if tools else []
    found += [f"skill {s.id} ({s.path})" for s in skills]
    notes = [f"found in {where}: {', '.join(found)}", pinned]
    if not public and (tools or skills):
        notes.append(
            "the tool and skills are private (admins only): import with --public, or add "
            "`access: public` to them in plugin.yaml, for every user to have them"
        )
    return Imported(folder, notes)
