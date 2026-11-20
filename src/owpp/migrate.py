"""`owpp migrate`: bring a plugin.yaml up to the current protocol version.

Each version has one step from the version before it. A step changes only the manifest text,
so a migration leaves comments and layout alone and the change is there to review and commit.
A manifest with no `protocol:` was written for 0.1, before the key existed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import OwppError
from .manifest import get, parse_yaml, plugin_folders, read_text, rename_key, set_key, text_of
from .protocol import VERSION, parse
from .sources import ref_kind


class Undecided(OwppError):
    """A step that needs something it could not find out; the manifest is left as it was."""


KindOf = Callable[[str, str], "str | None"]


def _to_0_2(text: str, manifest: dict, kind_of: KindOf) -> str:
    """0.1 -> 0.2: record the version. Everything 0.2 adds is optional, so nothing else changes."""
    return set_key(text, "protocol", '"0.2"')


def _to_0_3(text: str, manifest: dict, kind_of: KindOf) -> str:
    """0.2 -> 0.3: `source: track:` becomes `branch:` or `tag:`, whichever the name is in the
    repository (asked with `git ls-remote`)."""
    source = manifest.get("source")
    name = text_of(get(source, "track"))
    if name:
        git = text_of(source.get("git"))
        kind = kind_of(git, name)
        if kind not in ("branch", "tag"):
            raise Undecided(
                f"could not tell whether `track: {name}` is a branch or a tag of {git} "
                "(offline, private, or no such ref): write `branch:` or `tag:` in its place, "
                'and `protocol: "0.3"`'
            )
        text = rename_key(text, "source.track", kind)
    return set_key(text, "protocol", '"0.3"')


@dataclass(frozen=True)
class Step:
    """One migration: from one protocol version to the next."""

    old: str
    new: str
    apply: Callable[[str, dict, KindOf], str]


STEPS = (Step("0.1", "0.2", _to_0_2), Step("0.2", "0.3", _to_0_3))


def migrate_text(
    text: str, value: Any, path: str, kind_of: KindOf = ref_kind
) -> tuple[str, str, list[str]]:
    """The manifest text at the current protocol, the version it came from, and the steps it
    took. Raises Undecided when a step cannot be made without the user."""
    version = parse(value, path)
    old = version
    applied: list[str] = []
    while version != VERSION:
        step = next((s for s in STEPS if s.old == version), None)
        if step is None:
            raise OwppError(f"{path}: cannot migrate protocol {version} to {VERSION}")
        text = step.apply(text, parse_yaml(text) or {}, kind_of)
        applied.append(version)
        version = step.new
    return text, old, applied


def migrate(
    directory: Path,
    ids: list[str] | None = None,
    dry_run: bool = False,
    out: Callable[[str], None] = print,
    kind_of: KindOf = ref_kind,
) -> int:
    """`owpp migrate`: 0 when every plugin is current or was migrated, 1 when one is left for
    the user (an unknown id is an error)."""
    folders = {f.name: f for f in plugin_folders(directory)}
    missing = [i for i in ids or [] if i not in folders]
    if missing:
        raise OwppError(f"no plugin {', '.join(missing)} in {directory}")
    chosen = [f for name, f in folders.items() if not ids or name in ids]
    if not chosen:
        out("no plugin folders here (`plugin.yaml`); `owpp init` makes one")
        return 1 if ids else 0
    left = 0
    for folder in chosen:
        path = folder / "plugin.yaml"
        declared = parse_yaml(read_text(path)) or {}
        try:
            text, old, steps = migrate_text(
                read_text(path), get(declared, "protocol"), str(path), kind_of
            )
        except Undecided as e:
            out(f"FAIL  {folder.name}: {e}")
            left += 1
            continue
        if not steps:
            out(f"ok    {folder.name}: protocol {VERSION}")
            continue
        verb = "would migrate" if dry_run else "migrated"
        versions = [old, *steps[1:], VERSION]  # steps are the versions migrated *from*
        out(f"new   {folder.name}: {verb} {' -> '.join(versions)}")
        if not dry_run:
            path.write_bytes(text.encode("utf-8"))
            out("        wrote plugin.yaml")
    return 1 if left else 0
