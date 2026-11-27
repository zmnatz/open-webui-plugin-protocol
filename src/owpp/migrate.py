"""`owpp migrate`: bring a plugin up to the current protocol version.

Each version has one step from the version before it. A step changes the manifest text, leaving
comments and layout alone, and a step may also rewrite the plugin's code (0.3 -> 0.5 adds the
imports, owpp.imports), so the change is there to review and commit. A manifest with no
`protocol:` was written for 0.1, before the key existed. owpp 0.4 left the format at 0.3, so
there is no 0.4: the protocol follows owpp's major.minor.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import OwppError
from .imports import Upgrade, upgrade
from .manifest import get, parse_yaml, plugin_folders, read_text, rename_key, set_key, text_of
from .protocol import VERSION, parse
from .sources import Sources


class Undecided(OwppError):
    """A step that needs something it could not find out; the manifest is left as it was."""


def _to_0_2(text: str, manifest: dict, sources: Sources) -> str:
    """0.1 -> 0.2: record the version. Everything 0.2 adds is optional, so nothing else changes."""
    return set_key(text, "protocol", '"0.2"')


def _to_0_3(text: str, manifest: dict, sources: Sources) -> str:
    """0.2 -> 0.3: `source: track:` becomes `branch:` or `tag:`, whichever the name is in the
    repository (asked with `git ls-remote`)."""
    source = manifest.get("source")
    name = text_of(get(source, "track"))
    if name:
        git = text_of(source.get("git"))
        kind = sources.kind(git, name)
        if kind not in ("branch", "tag"):
            raise Undecided(
                f"could not tell whether `track: {name}` is a branch or a tag of {git} "
                "(offline, private, or no such ref): write `branch:` or `tag:` in its place, "
                'and `protocol: "0.3"`'
            )
        text = rename_key(text, "source.track", kind)
    return set_key(text, "protocol", '"0.3"')


def _to_0_5(text: str, manifest: dict, sources: Sources) -> str:
    """0.3 -> 0.5: record the version; the code step adds the imports (owpp.imports)."""
    return set_key(text, "protocol", '"0.5"')


def _to_0_7(text: str, manifest: dict, sources: Sources) -> str:
    """0.5 -> 0.7: record the version. 0.7 matches owpp 0.7 and changes no key."""
    return set_key(text, "protocol", '"0.7"')


def _code_to_0_5(folder: Path, manifest: dict) -> Upgrade:
    """Each file imports what it used to find already in scope. Only the files in the folder are
    read: one the bundler takes from git instead (`function: {file}`, `tool: {file}`) is the
    upstream's, so a local file of that name is not bundled and is left alone."""
    from_git = {
        f"{key}.py"
        for key in ("function", "tool")
        if isinstance(manifest.get(key), dict) and manifest[key].get("file")
    }
    return upgrade(folder, skip=from_git)


@dataclass(frozen=True)
class Step:
    """One migration: from one protocol version to the next. `code` rewrites the plugin's
    files, for a step that changes how they are written."""

    old: str
    new: str
    apply: Callable[[str, dict, Sources], str]
    code: Callable[[Path, dict], Upgrade] | None = None


STEPS = (
    Step("0.1", "0.2", _to_0_2),
    Step("0.2", "0.3", _to_0_3),
    Step("0.3", "0.5", _to_0_5, _code_to_0_5),
    Step("0.5", "0.7", _to_0_7),
)


def migrate_text(text: str, value: Any, path: str, sources: Sources) -> tuple[str, str, list[str]]:
    """The manifest text at the current protocol, the version it came from, and the steps it
    took. Raises Undecided when a step cannot be made without the user."""
    version = parse(value, path)
    old = version
    applied: list[str] = []
    while version != VERSION:
        step = next((s for s in STEPS if s.old == version), None)
        if step is None:
            raise OwppError(f"{path}: cannot migrate protocol {version} to {VERSION}")
        text = step.apply(text, parse_yaml(text) or {}, sources)
        applied.append(version)
        version = step.new
    return text, old, applied


def migrate(
    directory: Path,
    ids: list[str] | None = None,
    dry_run: bool = False,
    out: Callable[[str], None] = print,
    *,
    sources: Sources,
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
                read_text(path), get(declared, "protocol"), str(path), sources
            )
        except Undecided as e:
            out(f"FAIL  {folder.name}: {e}")
            left += 1
            continue
        if not steps:
            out(f"ok    {folder.name}: protocol {VERSION}")
            continue
        code = _code_changes(folder, steps, parse_yaml(text) or {})
        verb = "would migrate" if dry_run else "migrated"
        versions = [old, *steps[1:], VERSION]  # steps are the versions migrated *from*
        out(f"new   {folder.name}: {verb} {' -> '.join(versions)}")
        for note in code.notes:
            out(f"        {note}")
        written = {"plugin.yaml": text, **code.files}
        for name, content in written.items():
            if dry_run:
                out(f"        would write {name}")
                if name in code.files:  # code is less obvious than a version line: show it
                    for line in _changed_lines(read_text(folder / name), content):
                        out(f"          {line}")
            else:
                (folder / name).write_bytes(content.encode("utf-8"))
                out(f"        wrote {name}")
        if code.notes:
            left += 1
    return 1 if left else 0


def _changed_lines(old: str, new: str) -> list[str]:
    """The lines `new` adds (+) and drops (-), without the diff's headers and context."""
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
    return [line for line in diff if line[:1] in "+-" and line[:3] not in ("+++", "---")]


def _code_changes(folder: Path, steps: list[str], manifest: dict) -> Upgrade:
    """What the code steps among `steps` (the versions migrated from) do to the folder's files.
    Each works on the files as they are; one step's changes are not seen by the next, which is
    fine while only one step has code."""
    out = Upgrade()
    for step in STEPS:
        if step.old in steps and step.code is not None:
            done = step.code(folder, manifest)
            out.files.update(done.files)
            out.notes += done.notes
    return out
