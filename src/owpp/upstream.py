"""A whole plugin folder taken from git: `source: {git, ref, path, plugin: true}`.

The folder at `path` is an owpp plugin itself (it has a plugin.yaml). Its files are fetched at the
pinned commit and written to a scratch folder named after the local plugin, with the local
manifest's few overrides applied to its plugin.yaml and a local config.yaml put in place of the
upstream's. That folder is then bundled, checked and tested like any local plugin, by the owpp
that reads it. Nothing in it is run while bundling: only its files are read.
"""

from __future__ import annotations

import atexit
import base64
import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .errors import OwppError
from .manifest import SOURCED_OVERRIDES as OVERRIDES
from .manifest import get, read_manifest, read_text
from .sources import (
    Fetcher,
    Value,
    _source_files,
    fetch_sources,
    git_fetcher,
    plugin_folders,
    source_key,
    source_keys,
)


def is_plugin_source(manifest: dict) -> bool:
    """Whether the manifest takes a whole plugin folder from git."""
    return get(manifest.get("source"), "plugin") is True


def plugin_key(name: str, source: dict) -> str:
    """The key of the whole plugin folder, as fetch_sources takes it (a directory)."""
    return source_key(name, source, "", True)


_ROOT: Path | None = None
_MADE: dict[str, Path] = {}


def _scratch() -> Path:
    global _ROOT
    if _ROOT is None:
        _ROOT = Path(tempfile.mkdtemp(prefix="owpp-upstream-"))
        atexit.register(shutil.rmtree, _ROOT, True)
    return _ROOT


def _merge(upstream: dict, local: dict) -> dict:
    merged = dict(upstream)
    for block, keys in OVERRIDES.items():
        mine = local.get(block)
        if not isinstance(mine, dict) or not mine:
            continue
        theirs = merged.get(block)
        if not isinstance(theirs, dict):
            raise OwppError(f"the upstream plugin has no `{block}:` for the local one to change")
        section = dict(theirs)
        for key in keys:
            if key not in mine:
                continue
            if (
                key == "valves"
                and isinstance(section.get("valves"), dict)
                and isinstance(mine[key], dict)
            ):
                section["valves"] = {**section["valves"], **mine[key]}
            else:
                section[key] = mine[key]
        merged[block] = section
    return merged


def plugin_root(folder: Path, manifest: dict, remote: dict[str, Value]) -> Path:
    """The folder to bundle: `folder` itself, or for a sourced plugin the upstream folder as
    fetched, with the local overrides applied (made once per run)."""
    if not is_plugin_source(manifest):
        return folder
    prefix = plugin_key(folder.name, manifest["source"])
    files = {k[len(prefix) :]: v for k, v in remote.items() if k.startswith(prefix)}
    if not files:
        raise OwppError(f"{folder.name}: {prefix} was not fetched (call fetch_all first)")
    if "plugin.yaml" not in files:
        raise OwppError(
            f"{folder.name}: {prefix} has no plugin.yaml, so it is not an owpp plugin; "
            "take its files with `function: {file}`, `tool: {file}` or `skills:` instead"
        )
    local_text = read_text(folder / "plugin.yaml")
    config = folder / "config.yaml"
    config_text = read_text(config) if config.is_file() else None
    digest = hashlib.sha256(
        repr((str(folder.resolve()), prefix, local_text, config_text, sorted(files))).encode()
    ).hexdigest()[:16]
    if digest in _MADE:
        return _MADE[digest]
    root = _scratch() / digest / folder.name
    for rel, value in files.items():
        parts = rel.split("/")
        if any(p in ("", ".", "..") for p in parts):
            raise OwppError(f"{folder.name}: {prefix}{rel} is not a plain path")
        path = root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (
            value.encode("utf-8") if isinstance(value, str) else base64.b64decode(value["base64"])
        )
        path.write_bytes(data)
        if data.startswith(b"#!"):  # git's file mode is not fetched; a script keeps its x bit
            path.chmod(0o755)
    where = f"{folder.name}: the upstream {prefix}plugin.yaml"
    try:
        upstream = read_manifest(root)
    except OwppError as e:
        raise OwppError(f"{where}: {e}") from e
    if is_plugin_source(upstream):
        raise OwppError(f"{where} takes a whole plugin from git itself; point at that one instead")
    try:
        merged = _merge(upstream, manifest)
    except OwppError as e:
        raise OwppError(f"{where}: {e}") from e
    (root / "plugin.yaml").write_text(
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    if config_text is not None:
        (root / "config.yaml").write_text(config_text, encoding="utf-8")
    read_manifest(root)  # the merged manifest is still a valid one
    _MADE[digest] = root
    return root


_FETCHED: dict[tuple[Fetcher, str], dict[str, Value]] = {}


def _fetch(keys: list[str], fetcher: Fetcher) -> dict[str, Value]:
    """fetch_sources, once per key and fetcher in a run (a key names a commit, so it never changes)."""
    missing = [k for k in keys if (fetcher, k) not in _FETCHED]
    if missing:
        got = fetch_sources(missing, fetcher)
        for k in missing:
            _FETCHED[(fetcher, k)] = {
                f: v for f, v in got.items() if f == k or (k.endswith("/") and f.startswith(k))
            }
    out: dict[str, Value] = {}
    for k in keys:
        out.update(_FETCHED[(fetcher, k)])
    return out


def fetch_all(directory: Path | str, fetcher: Fetcher = git_fetcher) -> dict[str, Value]:
    """Every file the plugins folder takes from git, including what a whole plugin taken from git
    takes from git itself (an upstream plugin with its own `source:`)."""
    directory = Path(directory)
    remote = _fetch(source_keys(directory), fetcher)
    nested: list[str] = []
    for folder in plugin_folders(directory):
        manifest = read_manifest(folder)
        if not is_plugin_source(manifest):
            continue
        inner = read_manifest(plugin_root(folder, manifest, remote))
        if inner.get("source"):
            nested += [
                source_key(folder.name, inner["source"], rel, d) for rel, d in _source_files(inner)
            ]
    if nested:
        remote.update(_fetch(nested, fetcher))
    return remote


def root_of(folder: Path, remote: dict[str, Any]) -> Path:
    """plugin_root, reading the manifest itself."""
    return plugin_root(folder, read_manifest(folder), remote)
