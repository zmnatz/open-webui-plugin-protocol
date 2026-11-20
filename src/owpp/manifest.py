"""Reading plugin.yaml, and the small value helpers the bundler shares."""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

import yaml

from .errors import OwppError


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
