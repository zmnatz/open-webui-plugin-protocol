"""Reading plugin.yaml and a plugin's files, and the small value helpers the bundler shares."""

from __future__ import annotations

import base64
import difflib
import os
import re
from pathlib import Path
from typing import Any

import yaml

from .errors import OwppError
from .protocol import parse as parse_protocol


class _Loader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 scalars: only true/false are booleans, `on`/`no`/`12:30`
    stay strings, and nothing is turned into a date. A header value is deployed as text,
    so it must not be reinterpreted on the way."""


_DROP = {
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:timestamp",
}
_Loader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag not in _DROP]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    re.compile(r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$"),
    list("-+0123456789"),
)
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(
        r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?"
        r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"
    ),
    list("-+0123456789."),
)


def parse_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_Loader)  # noqa: S506 (a SafeLoader subclass)


def read_text(path: Path | str) -> str:
    """UTF-8 text with no newline translation, so a bundle is the same on every OS."""
    return Path(path).read_bytes().decode("utf-8")


# The top-level keys of plugin.yaml. Anything else is refused: a setting that is silently ignored
# (a typo, or a key that no longer exists) is worst when it is a security one.
MANIFEST_KEYS = (
    "function",
    "tool",
    "skills",
    "source",
    "include",
    "static",
    "assets",
    "jobs",
    "requires",
    "protocol",
)
# Instance settings a plugin can say it needs. `owpp deploy` warns when one is missing; it never
# changes the instance or refuses the deploy.
REQUIREMENT_KEYS = ("iframe_sandbox_allow_same_origin",)
REMOVED_KEYS = {
    "routes": "is gone. A route is open to any signed-in user; mark one that needs more with "
    "`user: PluginAdmin` (or a chat marker) on its handler, and set the level of the static/ "
    "files with `static: {access: admin}`",
    "public": "is now `static:` (files served as they are; `prefix`, `access`). The files a function "
    "renders itself, which `dynamic:` used to list, go in a templates/ folder instead",
}


def check_keys(path: Path, manifest: dict) -> None:
    for key in manifest:
        if key in REMOVED_KEYS:
            raise OwppError(f"{path}: `{key}:` {REMOVED_KEYS[key]}")
        if key not in MANIFEST_KEYS and not str(key).startswith("x-"):
            close = difflib.get_close_matches(str(key), MANIFEST_KEYS, n=1, cutoff=0.6)
            hint = f"; did you mean `{close[0]}:`?" if close else ""
            raise OwppError(
                f"{path}: unknown key `{key}:` (known: {', '.join(MANIFEST_KEYS)}){hint}"
            )
    protocol = parse_protocol(manifest.get("protocol"), str(path))
    if isinstance(manifest.get("source"), dict):
        follows(manifest["source"], protocol, path)
    check_sourced_plugin(path, manifest)
    requires = manifest.get("requires")
    if requires is not None:
        if not isinstance(requires, dict):
            raise OwppError(f"{path}: `requires:` must be a mapping")
        for key, value in requires.items():
            if key not in REQUIREMENT_KEYS:
                raise OwppError(
                    f"{path}: unknown requirement `{key}:` (known: {', '.join(REQUIREMENT_KEYS)})"
                )
            if not isinstance(value, bool):
                raise OwppError(f"{path}: requirement `{key}:` must be true or false")


# A branch or tag a plugin follows (`source: branch:` or `tag:`), as git allows it, never an option.
TRACK = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]*")


def _version(protocol: str) -> tuple[int, ...]:
    return tuple(int(n) for n in protocol.split("."))


def follows(source: dict, protocol: str, path: Path | str) -> tuple[str, str]:
    """What `owpp pull` moves a `source:` to the latest commit of: ("branch", name),
    ("tag", name), or ("default", "HEAD") for the repository's default branch. A manifest
    written for protocol 0.2 may still say `track:` (a branch or a tag, git decides):
    ("either", name)."""
    where = f"{path}: source"
    branch, tag = (text_of(source.get(k)) for k in ("branch", "tag"))
    if "track" in source:
        if _version(protocol) >= (0, 3):
            raise OwppError(
                f"{where}.track is gone in protocol 0.3: it is `branch:` or `tag:` now "
                "(`owpp migrate` rewrites it)"
            )
        if branch or tag:
            raise OwppError(f"{where}: `track:` and `branch:`/`tag:` cannot be used together")
    if branch and tag:
        raise OwppError(f"{where}: follow a `branch:` or a `tag:`, not both")
    kind, name = (
        ("branch", branch)
        if branch
        else ("tag", tag)
        if tag
        else ("either", text_of(source.get("track")))
        if text_of(source.get("track"))
        else ("default", "HEAD")
    )
    if kind != "default" and not TRACK.fullmatch(name):
        raise OwppError(
            f"{where}.{'track' if kind == 'either' else kind} must be a branch or tag name"
        )
    return kind, name


# What a local plugin.yaml may say, besides `protocol:` and `source:`, when its source is a whole
# plugin folder (`source: {plugin: true}`). Everything else is the upstream's: two manifests merged
# key by key would be hard to read and to review.
SOURCED_OVERRIDES = {
    "function": ("valves", "global"),
    "tool": ("id", "access", "valves"),
}


def check_sourced_plugin(path: Path | str, manifest: dict) -> None:
    """Refuse a manifest with a whole-plugin source that says more than it may."""
    source = manifest.get("source")
    plugin = source.get("plugin") if isinstance(source, dict) else None
    if plugin is not None and not isinstance(plugin, bool):
        raise OwppError(f"{path}: source.plugin must be true or false")
    if not plugin:
        return
    allowed = ", ".join(
        f"{block}.{key}" for block, keys in SOURCED_OVERRIDES.items() for key in keys
    )
    extra: list[str] = []
    for key, value in manifest.items():
        if key in ("protocol", "source") or str(key).startswith("x-"):
            continue
        if key in SOURCED_OVERRIDES and isinstance(value, dict):
            extra += [f"{key}.{k}" for k in value if k not in SOURCED_OVERRIDES[key]]
        else:
            extra.append(str(key))
    if extra:
        raise OwppError(
            f"{path}: a plugin taken whole from `source:` comes with its own manifest; here only "
            f"{allowed} can be set (remove {', '.join(extra)})"
        )


def read_manifest(folder: Path | str) -> dict:
    path = Path(folder) / "plugin.yaml"
    try:
        manifest = parse_yaml(read_text(path))
    except yaml.YAMLError as e:
        raise OwppError(f"{path}: not valid YAML ({e})") from e
    if manifest is None:
        return {}
    if not isinstance(manifest, dict):
        raise OwppError(f"{path}: the manifest must be a mapping")
    check_keys(path, manifest)
    return manifest


def get(obj: Any, key: str) -> Any:
    """obj[key] when obj is a mapping that has it, else None."""
    return obj.get(key) if isinstance(obj, dict) else None


def coalesce(value: Any, default: Any) -> Any:
    return default if value is None else value


def text_of(value: Any) -> str:
    """A manifest value as the text that is written to a header."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def omit(obj: dict, keys: list[str]) -> dict:
    return {k: v for k, v in obj.items() if k not in keys}


# ---- a plugin's files ---------------------------------------------------------------

# A file's content: text when it is UTF-8, else {"base64": ...} (a skill may ship an image or a font).
Value = str | dict


def file_value(buf: bytes) -> Value:
    try:
        return buf.decode("utf-8")
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(buf).decode("ascii")}


def value_bytes(value: Value) -> bytes:
    """The bytes of a file as file_value read it."""
    return value.encode("utf-8") if isinstance(value, str) else base64.b64decode(value["base64"])


def is_plain_path(path: str) -> bool:
    """Whether the path of a file in a repository stays inside the folder it is written to."""
    if os.sep == "\\" and "\\" in path:  # on Windows it separates folders too
        return False
    return not any(p in ("", ".", "..") or Path(p).anchor for p in path.split("/"))


def file_entry(path: str, value: Value) -> dict:
    """A file as the runtime installs it: {path, content, encoding?}."""
    if isinstance(value, str):
        return {"path": path, "content": value}
    return {"path": path, "content": value["base64"], "encoding": "base64"}


def folder_files(directory: Path) -> list[dict]:
    """Every file under `directory` as [{path, content, encoding?}] sorted by path. Symlinks
    are never followed, and .DS_Store is skipped."""
    files: list[dict] = []

    def walk(here: Path, base: str) -> None:
        with os.scandir(here) as it:
            entries = sorted(it, key=lambda e: e.name)
        for e in entries:
            if e.name == ".DS_Store":
                continue
            path = f"{base}/{e.name}" if base else e.name
            if e.is_dir(follow_symlinks=False):
                walk(Path(e.path), path)
            elif e.is_file(follow_symlinks=False):
                files.append(file_entry(path, file_value(Path(e.path).read_bytes())))

    walk(directory, "")
    return sorted(files, key=lambda f: f["path"])


def files_of(entries: dict[str, dict] | list[dict]) -> dict[str, str | bytes]:
    """{path: text or bytes} from the runtime's file entries ({path: {content, encoding?}} or
    [{path, content, encoding?}])."""
    items = entries.items() if isinstance(entries, dict) else ((e["path"], e) for e in entries)
    return {
        path: base64.b64decode(e["content"]) if e.get("encoding") == "base64" else e["content"]
        for path, e in items
    }


def require_plugins_folder(directory: Path) -> None:
    if not directory.exists():
        raise OwppError(f"no plugins folder at {directory} (pass --dir, or set OWPP_PLUGINS_DIR)")


def plugin_folders(directory: Path | str) -> list[Path]:
    """Sub-folders of `directory` that hold a plugin.yaml, by name."""
    with os.scandir(directory) as it:
        entries = sorted(it, key=lambda e: e.name)
    return [
        Path(e.path)
        for e in entries
        if e.is_dir(follow_symlinks=False) and (Path(e.path) / "plugin.yaml").exists()
    ]


# ---- changing one value in plugin.yaml text --------------------------------------------

_SCALAR = r"""(?P<value>"[^"\n]*"|'[^'\n]*'|[^\s#'"{\[][^#\n]*?)?"""
_FLOW_ONE_LINE = re.compile(r"\{(?P<body>[^{}]*)\}(?P<trail>\s*(?:#.*)?)$")


def _ending(line: str) -> str:
    return "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""


def _quoted_like(old: str | None, value: str) -> str:
    """`value` in the quotes `old` was written in, unless `value` brings its own."""
    if old and old[0] in "\"'" and value[:1] not in ("'", '"'):
        return f"{old[0]}{value}{old[0]}"
    return value


def _set_line(line: str, key: str, value: str) -> str | None:
    """`line` (`<indent>key: <scalar> [# comment]`) with the scalar replaced, or None when it
    is not that key. A key whose value is not a plain one-line scalar is refused."""
    body, end = line[: len(line) - len(_ending(line))], _ending(line)
    m = re.fullmatch(
        rf"(?P<lead>\s*{re.escape(key)}:)(?P<gap>[ \t]*){_SCALAR}(?P<trail>\s*(?:#.*)?)", body
    )
    if not m:
        if re.match(rf"\s*{re.escape(key)}:", body):
            raise OwppError(f"`{key}:` is not a one-line value; edit plugin.yaml by hand")
        return None
    gap = m.group("gap") or " "
    return f"{m.group('lead')}{gap}{_quoted_like(m.group('value'), value)}{m.group('trail')}{end}"


def _split_flow(body: str) -> list[str]:
    """The items of a one-line flow mapping's body, split on the commas outside quotes."""
    items, current, quote = [], "", ""
    for ch in body:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == ",":
            items.append(current)
            current = ""
            continue
        current += ch
    items.append(current)
    return items


def _set_flow(rest: str, key: str, value: str, after: str | None) -> str:
    """`rest` (` {a: 1, b: 2} # comment`) with `key` set in the one-line mapping."""
    ending = _ending(rest)
    text = rest[: len(rest) - len(ending)]
    start = text.index("{")
    m = _FLOW_ONE_LINE.fullmatch(text, start)
    if not m:
        raise OwppError("a `{ ... }` mapping over several lines; edit plugin.yaml by hand")
    body = m.group("body")
    items = _split_flow(body)
    for i, item in enumerate(items):
        found = re.fullmatch(rf"(\s*{re.escape(key)}:\s*)(.*?)(\s*)", item)
        if found:
            items[i] = f"{found.group(1)}{_quoted_like(found.group(2), value)}{found.group(3)}"
            body = ",".join(items)
            break
    else:
        names = [(re.match(r"\s*([^:\s]*)", it).group(1)) for it in items]
        if not body.strip():
            body = f"{key}: {value}"
        elif after in names:
            at = names.index(after) + 1
            body = ",".join([*items[:at], f" {key}: {value}", *items[at:]])
        else:
            lead = re.match(r"\s*", body).group()
            body = f"{lead}{key}: {value}, {body[len(lead) :]}"
    return f"{text[:start]}{{{body}}}{m.group('trail')}{ending}"


def set_key(text: str, key: str, value: str, after: str | None = None) -> str:
    """plugin.yaml `text` with one value set, and nothing else changed: comments, layout,
    quoting and line endings are kept, so the diff is that one line.

    `key` is a top-level key (`protocol`) or a key in a top-level mapping (`source.ref`), in
    block style or a one-line `{...}` mapping. `value` is the YAML scalar as it is written;
    a value that was quoted stays quoted. A missing key is added after the key `after` of the
    same mapping, else first (a top-level key goes before the first one). Anything else (a
    mapping over several lines, a value that is not one line, a missing mapping) is refused
    with an error that says to edit plugin.yaml by hand."""
    parts = key.split(".")
    if len(parts) not in (1, 2) or not all(parts):
        raise OwppError(f"cannot set `{key}`: only `key` or `mapping.key`")
    lines = text.splitlines(keepends=True)
    newline = next((_ending(line) for line in lines if _ending(line)), "\n")
    top = [
        i
        for i, line in enumerate(lines)
        if line.strip() and not line[0].isspace() and line[0] != "#"
    ]

    def insert(at: int, line: str) -> str:
        if at > 0 and not _ending(lines[at - 1]):
            lines[at - 1] += newline
        lines.insert(at, line + (newline if at < len(lines) or text.endswith(("\n",)) else ""))
        return "".join(lines)

    if len(parts) == 1:
        for i in top:
            changed = _set_line(lines[i], parts[0], value)
            if changed is not None:
                lines[i] = changed
                return "".join(lines)
        after_line = (
            next((i for i in top if re.match(rf"{re.escape(after)}:", lines[i])), None)
            if after
            else None
        )
        at = after_line + 1 if after_line is not None else (top[0] if top else len(lines))
        return insert(at, f"{parts[0]}: {value}")

    block, child = parts
    start = next((i for i in top if re.match(rf"{re.escape(block)}:", lines[i])), None)
    if start is None:
        raise OwppError(f"plugin.yaml has no `{block}:` section")
    header = lines[start]
    rest = header[len(block) + 1 :]
    if rest.lstrip().startswith("{"):
        lines[start] = header[: len(block) + 1] + _set_flow(rest, child, value, after)
        return "".join(lines)
    if not re.fullmatch(r"[ \t]*(#.*)?", rest.rstrip("\r\n")):
        raise OwppError(f"`{block}:` is not a mapping; edit plugin.yaml by hand")
    end = next((i for i in top if i > start), len(lines))
    children = [
        i
        for i in range(start + 1, end)
        if lines[i].strip() and not lines[i].lstrip().startswith("#")
    ]
    indent = re.match(r"[ \t]+", lines[children[0]]).group() if children else "  "
    own = [i for i in children if re.match(rf"{indent}\S", lines[i])]
    for i in own:
        if re.match(rf"{indent}{re.escape(child)}:", lines[i]):
            following = next((j for j in children if j > i), None)
            if following is not None and following not in own:  # its value is nested lines
                raise OwppError(f"`{child}:` is not a one-line value; edit plugin.yaml by hand")
            changed = _set_line(lines[i], child, value)
            if changed is not None:
                lines[i] = changed
                return "".join(lines)
    at = start + 1
    if after:
        pos = next(
            (n for n, i in enumerate(own) if re.match(rf"{indent}{re.escape(after)}:", lines[i])),
            None,
        )
        if pos is not None:
            nxt = own[pos + 1] if pos + 1 < len(own) else None
            # After that key's own lines (a nested value), before the next key of the mapping.
            last = max(
                (i for i in children if i >= own[pos] and (nxt is None or i < nxt)),
                default=own[pos],
            )
            at = last + 1
    return insert(at, f"{indent}{child}: {value}")


def rename_key(text: str, key: str, new: str) -> str:
    """plugin.yaml `text` with the key `mapping.key` renamed to `new`, its value, comment and
    the rest of the file kept. Refused (edit by hand) unless the key is there exactly once."""
    block, child = key.split(".")
    lines = text.splitlines(keepends=True)
    top = [
        i
        for i, line in enumerate(lines)
        if line.strip() and not line[0].isspace() and line[0] != "#"
    ]
    start = next((i for i in top if re.match(rf"{re.escape(block)}:", lines[i])), None)
    if start is None:
        raise OwppError(f"plugin.yaml has no `{block}:` section")
    if lines[start][len(block) + 1 :].lstrip().startswith("{"):
        at = [start]
        pattern = rf"([{{,]\s*){re.escape(child)}(\s*:)"
    else:
        end = next((i for i in top if i > start), len(lines))
        at = list(range(start + 1, end))
        pattern = rf"^(\s+){re.escape(child)}(\s*:)"
    found = [(i, m) for i in at for m in [re.search(pattern, lines[i])] if m]
    if len(found) != 1:
        raise OwppError(
            f"found {len(found)} `{child}:` keys in `{block}:`; edit plugin.yaml by hand"
        )
    i, m = found[0]
    lines[i] = lines[i][: m.start()] + m.group(1) + new + m.group(2) + lines[i][m.end() :]
    return "".join(lines)
