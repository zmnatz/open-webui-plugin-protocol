"""A whole plugin folder taken from git: `source: {git, ref, path, plugin: true}`.

The folder at `path` is an owpp plugin itself (it has a plugin.yaml). Its files are written to a
folder named after the local plugin (in `.owpp/modules/`, else a scratch folder), with the local
manifest's few overrides applied to its plugin.yaml and a local config.yaml put in place of the
upstream's. That folder is then
bundled, checked and tested like any local plugin, by the owpp that reads it. Nothing in it is
run while bundling: only its files are read.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..errors import OwppError
from ..manifest import SOURCED_OVERRIDES as OVERRIDES
from ..manifest import Value, get, is_plain_path, read_manifest, read_text, value_bytes


def is_plugin_source(manifest: dict) -> bool:
    """Whether the manifest takes a whole plugin folder from git."""
    return get(manifest.get("source"), "plugin") is True


def merge(upstream: dict, local: dict) -> dict:
    """The upstream manifest with the local one's overrides (SOURCED_OVERRIDES) applied;
    valves are merged key by key."""
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


def write_upstream(root: Path, folder: Path, manifest: dict, files: dict[str, Value], where: str):
    """Write the upstream folder's `files` ({path inside it: content}) to `root`, then its
    plugin.yaml merged with the local `manifest`, and the local config.yaml if there is one."""
    if "plugin.yaml" not in files:
        raise OwppError(
            f"{folder.name}: {where} has no plugin.yaml, so it is not an owpp plugin; "
            "take its files with `function: {file}`, `tool: {file}` or `skills:` instead"
        )
    for rel, value in files.items():
        if not is_plain_path(rel):
            raise OwppError(f"{folder.name}: {where}{rel} is not a plain path")
        path = root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        data = value_bytes(value)
        path.write_bytes(data)
        if data.startswith(b"#!"):  # git's file mode is not fetched; a script keeps its x bit
            path.chmod(0o755)
    label = f"{folder.name}: the upstream {where}plugin.yaml"
    try:
        upstream = read_manifest(root)
    except OwppError as e:
        raise OwppError(f"{label}: {e}") from e
    if is_plugin_source(upstream):
        raise OwppError(f"{label} takes a whole plugin from git itself; point at that one instead")
    try:
        merged = merge(upstream, manifest)
    except OwppError as e:
        raise OwppError(f"{label}: {e}") from e
    (root / "plugin.yaml").write_text(
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    config = folder / "config.yaml"
    if config.is_file():
        (root / "config.yaml").write_text(read_text(config), encoding="utf-8")
    read_manifest(root)  # the merged manifest is still a valid one
