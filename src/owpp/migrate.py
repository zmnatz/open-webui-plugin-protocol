"""`owpp migrate`: bring a plugin.yaml up to the current protocol version.

Each version has one step from the version before it. A step changes only the manifest text,
so a migration leaves comments and layout alone and the change is there to review and commit.
A manifest with no `protocol:` was written for 0.1, before the key existed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import OwppError
from .manifest import read_manifest, read_text
from .protocol import VERSION, parse
from .sources import plugin_folders

_KEY_LINE = re.compile(r"""^(protocol\s*:\s*)(?:"[^"]*"|'[^']*'|[^\s#\r\n]+)""", re.MULTILINE)


def _add_protocol_key(text: str) -> str:
    """0.1 -> 0.2: record the version. Everything 0.2 adds is optional, so nothing else changes."""
    line = f'protocol: "{VERSION}"'
    found, count = _KEY_LINE.subn(lambda m: f'{m.group(1)}"{VERSION}"', text, count=1)
    if count:
        return found
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    first = next(
        (i for i, line in enumerate(lines) if line.strip() and not line.lstrip().startswith("#")),
        len(lines),
    )
    lines.insert(first, line + newline)
    return "".join(lines)


@dataclass(frozen=True)
class Step:
    """One migration: from one protocol version to the next."""

    old: str
    new: str
    apply: Callable[[str], str]


STEPS = (Step("0.1", VERSION, _add_protocol_key),)


def migrate_text(text: str, value: Any, path: str) -> tuple[str, str, list[str]]:
    """The manifest text at the current protocol, the version it came from, and the steps it took."""
    version = parse(value, path)
    old = version
    applied: list[str] = []
    while version != VERSION:
        step = next((s for s in STEPS if s.old == version), None)
        if step is None:
            raise OwppError(f"{path}: cannot migrate protocol {version} to {VERSION}")
        text = step.apply(text)
        applied.append(version)
        version = step.new
    return text, old, applied


def migrate(
    directory: Path,
    ids: list[str] | None = None,
    dry_run: bool = False,
    out: Callable[[str], None] = print,
) -> int:
    """`owpp migrate`: 0 when every plugin is current or was migrated, 1 on an unknown id."""
    folders = {f.name: f for f in plugin_folders(directory)}
    missing = [i for i in ids or [] if i not in folders]
    if missing:
        raise OwppError(f"no plugin {', '.join(missing)} in {directory}")
    chosen = [f for name, f in folders.items() if not ids or name in ids]
    if not chosen:
        out("no plugin folders here (`plugin.yaml`); `owpp init` makes one")
        return 1 if ids else 0
    for folder in chosen:
        path = folder / "plugin.yaml"
        declared = read_manifest(folder).get("protocol")
        text, old, steps = migrate_text(read_text(path), declared, str(path))
        if not steps:
            out(f"ok    {folder.name}: protocol {VERSION}")
            continue
        verb = "would migrate" if dry_run else "migrated"
        versions = [old, *steps[1:], VERSION]  # steps are the versions migrated *from*
        out(f"new   {folder.name}: {verb} {' -> '.join(versions)}")
        if not dry_run:
            path.write_bytes(text.encode("utf-8"))
            out("        wrote plugin.yaml")
    return 0
