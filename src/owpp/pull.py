"""`owpp pull`: move the pinned commit of each plugin taken from git to the latest one.

A plugin's `source:` is pinned to a full commit SHA, so what is deployed changes only when that
SHA moves, in a change someone reviews. This makes the move easy without making it silent:

1. it looks up the latest commit of the branch or tag the plugin follows (`source: track:`, or
   the repository's default branch);
2. it fetches the files the plugin takes at both commits, and lists which of them were added,
   changed or removed (and a compare link, for GitHub);
3. it rewrites the `ref:` line in plugin.yaml, and nothing else, leaving the change to review
   and commit. Nothing is deployed.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from .errors import OwppError
from .manifest import plugin_folders, read_manifest, read_text, text_of
from .sources import SHA40, TRACK, Sources, source_label
from .versioning import add_changelog_entry, next_version, set_block_version


@dataclass
class Move:
    """What pull found for one plugin."""

    id: str
    track: str
    old: str
    new: str | None = None
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    error: str = ""
    compare: str = ""
    written: bool = False
    version: tuple[str, str] | None = None  # the plugin's own version, bumped: (old, new)

    @property
    def moved(self) -> bool:
        return bool(self.new) and self.new != self.old and not self.error


def track_of(folder: Path, source: dict) -> str:
    """The branch or tag a plugin follows: `source: track:`, else HEAD (the default branch)."""
    track = text_of(source.get("track")) or "HEAD"
    if track != "HEAD" and not TRACK.fullmatch(track):
        raise OwppError(f"{folder.name}/plugin.yaml: source.track must be a branch or tag name")
    return track


def compare_url(git: str, old: str, new: str) -> str:
    """A web page of the changes between two commits, for the hosts whose URL is known."""
    m = re.fullmatch(r"(?:https://|git@)(github\.com)[/:]([^/\s]+/[^/\s]+?)(?:\.git)?/?", git)
    return f"https://{m.group(1)}/{m.group(2)}/compare/{old}...{new}" if m else ""


def tree_url(git: str, sha: str, source: dict) -> str:
    """A web page of the files at a commit, for the hosts whose URL is known."""
    m = re.fullmatch(r"(?:https://|git@)(github\.com)[/:]([^/\s]+/[^/\s]+?)(?:\.git)?/?", git)
    path = text_of(source.get("path")).strip("/")
    return f"https://{m.group(1)}/{m.group(2)}/tree/{sha}{'/' + path if path else ''}" if m else ""


def rewrite_ref(text: str, old: str, new: str) -> str:
    """plugin.yaml with its `ref:` changed from `old` to `new`; comments and layout kept."""
    out, count = re.subn(rf"(\bref:\s*[\"']?){old}\b", rf"\g<1>{new}", text)
    if count != 1:
        raise OwppError(f"found {count} `ref: {old[:7]}...` lines; change it by hand")
    return out


def set_ref(text: str, old: str, new: str) -> str:
    """plugin.yaml pinned to `new`: its `ref:` line changed, or added after `git:` when the
    source has none yet (`old` is empty). Comments and layout are kept."""
    if old:
        return rewrite_ref(text, old, new)
    flow, count = re.subn(
        r"(^source:\s*\{[^}]*?\bgit:\s*[^,}\s]+)", rf"\g<1>, ref: {new}", text, flags=re.M
    )
    if count == 1:
        return flow
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if re.match(r"source:\s*(#.*)?$", line)), None)
    if start is not None:
        for i in range(start + 1, len(lines)):
            line = lines[i]
            if line.strip() and not line[0].isspace():
                break  # the next top-level key: the block ended without a git: line
            m = re.match(r"(\s+)git:", line)
            if m:
                newline = "\r\n" if line.endswith("\r\n") else "\n"
                if not line.endswith("\n"):
                    lines[i] = line + newline
                lines.insert(i + 1, f"{m.group(1)}ref: {new}{newline}")
                return "".join(lines)
    raise OwppError(
        "could not find the `git:` line of `source:` to add `ref:` after; add it by hand"
    )


def pull_plugin(
    folder: Path,
    sources: Sources,
    dry_run: bool = False,
    bump_by: str = "patch",
    today: str | None = None,
) -> Move:
    manifest = read_manifest(folder)
    source = manifest["source"]
    git, old = text_of(source.get("git")), text_of(source.get("ref"))
    track = track_of(folder, source)
    move = Move(folder.name, track, old)
    new = sources.latest(git, track)
    if not new or not SHA40.fullmatch(new):
        move.error = f"could not look up {track} in {git}"
        return move
    move.new = new
    if new == old:
        return move
    try:
        before = sources.resolve(folder).taken if old else {}
        after = sources.resolve(folder, ref=new).taken
    except OwppError as e:  # a file the plugin takes is gone at the new commit
        move.error = str(e)
        return move
    move.added = sorted(set(after) - set(before))
    move.removed = sorted(set(before) - set(after))
    move.changed = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    move.compare = compare_url(git, old, new) if old else tree_url(git, new, source)
    fn = manifest.get("function") if isinstance(manifest.get("function"), dict) else {}
    # The upstream files changed: a new version of the plugin, unless its function is the
    # upstream's own (whose header, and version, come from its file).
    whole = source.get("plugin") is True  # a whole plugin: its versions are the upstream's
    if (
        (move.changed or move.added or move.removed)
        and bump_by != "none"
        and not fn.get("file")
        and not whole
        and old
    ):
        current = text_of(fn.get("version"))
        move.version = (current, next_version(current, bump_by))
    if not dry_run:
        path = folder / "plugin.yaml"
        text = set_ref(read_text(path), old, new)
        if move.version:
            text, _ = set_block_version(text, "function", move.version[1])
        path.write_bytes(text.encode("utf-8"))
        if move.version:
            what = ", ".join(move.changed + move.added + move.removed)
            add_changelog_entry(
                folder,
                text_of(fn.get("title")) or folder.name,
                move.version[1],
                [f"Upstream {source_label(source)}: {old[:7]} -> {new[:7]} ({what})."],
                today or _dt.date.today().isoformat(),
            )
        move.written = True
    return move


def pull(
    directory: Path,
    ids: list[str] | None = None,
    dry_run: bool = False,
    sources: Sources | None = None,
    out: Callable[[str], None] = print,
    bump_by: str = "patch",
    today: str | None = None,
) -> int:
    """0 when every plugin is up to date or was moved, 1 when one could not be."""
    folders = {f.name: f for f in plugin_folders(directory)}
    missing = [i for i in ids or [] if i not in folders]
    if missing:
        raise OwppError(f"no plugin {', '.join(missing)} in {directory}")
    sourced = [
        f
        for name, f in folders.items()
        if (not ids or name in ids) and read_manifest(f).get("source")
    ]
    if not sourced:
        out("no plugin takes its code from git (`source:` in plugin.yaml)")
        return 1 if ids else 0
    with nullcontext(sources) if sources is not None else Sources() as s:
        moves = [pull_plugin(f, s, dry_run, bump_by, today) for f in sourced]
    for m in moves:
        where = f"({m.track})" if m.track != "HEAD" else "(default branch)"
        if m.error:
            out(f"FAIL  {m.id}: {m.error}")
        elif not m.moved:
            out(f"ok    {m.id}: up to date {where}, {m.old[:7]}")
        elif not m.old:
            verb = "would pin" if dry_run else "pinned"
            out(f"new   {m.id}: {verb} to {m.new} {where}")
            if m.compare:
                out(f"        {m.compare}")
            continue
        else:
            verb = "would move" if dry_run else "moved"
            out(f"new   {m.id}: {verb} {m.old[:7]} -> {m.new[:7]} {where}")
            for label, paths in (
                ("changed", m.changed),
                ("added", m.added),
                ("removed", m.removed),
            ):
                for p in paths:
                    out(f"        {label:<8}{p}")
            if not (m.changed or m.added or m.removed):
                out("        no file it takes changed")
            if m.compare:
                out(f"        {m.compare}")
            if m.version:
                verb = "would bump" if dry_run else "bumped"
                out(f"        {verb} the version {m.version[0] or '(none)'} -> {m.version[1]}")
    moved = [m for m in moves if m.moved]
    if moved and not dry_run:
        out(
            f"{len(moved)} plugin(s) moved: review the upstream changes, run `owpp check` and "
            "`owpp test`, then commit plugin.yaml"
        )
    return 1 if any(m.error for m in moves) else 0
