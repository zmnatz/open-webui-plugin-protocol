"""`owpp sync`: move the pinned commit of each plugin taken from git to the latest one.

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

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .errors import OwppError
from .manifest import read_manifest, read_text, text_of
from .sources import (
    SHA40,
    TRACK,
    Fetcher,
    _source_files,
    fetch_sources,
    git_fetcher,
    plugin_folders,
    resolve_ref,
    source_key,
)

Resolver = Callable[[str, str], "str | None"]


@dataclass
class Move:
    """What sync found for one plugin."""

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


def _files(folder: Path, source: dict, sha: str, fetcher: Fetcher) -> dict[str, object]:
    """The files the plugin takes from its source at `sha`: {path in the repo: content}."""
    pinned = {**source, "ref": sha}
    keys = [
        source_key(folder.name, pinned, rel, d) for rel, d in _source_files(read_manifest(folder))
    ]
    prefix = f"{text_of(source.get('git'))}#{sha}:"
    return {k[len(prefix) :]: v for k, v in fetch_sources(keys, fetcher).items()}


def rewrite_ref(text: str, old: str, new: str) -> str:
    """plugin.yaml with its `ref:` changed from `old` to `new`; comments and layout kept."""
    out, count = re.subn(rf"(\bref:\s*[\"']?){old}\b", rf"\g<1>{new}", text)
    if count != 1:
        raise OwppError(f"found {count} `ref: {old[:7]}...` lines; change it by hand")
    return out


def sync_plugin(
    folder: Path,
    dry_run: bool = False,
    resolve: Resolver | None = None,
    fetcher: Fetcher = git_fetcher,
) -> Move:
    manifest = read_manifest(folder)
    source = manifest["source"]
    git, old = text_of(source.get("git")), text_of(source.get("ref"))
    track = track_of(folder, source)
    move = Move(folder.name, track, old)
    source_key(folder.name, source, "")  # the URL and the pinned SHA are valid
    new = (resolve or resolve_ref)(git, track)
    if not new or not SHA40.fullmatch(new):
        move.error = f"could not look up {track} in {git}"
        return move
    move.new = new
    if new == old:
        return move
    try:
        before = _files(folder, source, old, fetcher)
        after = _files(folder, source, new, fetcher)
    except OwppError as e:  # a file the plugin takes is gone at the new commit
        move.error = str(e)
        return move
    move.added = sorted(set(after) - set(before))
    move.removed = sorted(set(before) - set(after))
    move.changed = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    move.compare = compare_url(git, old, new)
    if not dry_run:
        path = folder / "plugin.yaml"
        path.write_bytes(rewrite_ref(read_text(path), old, new).encode("utf-8"))
        move.written = True
    return move


def sync(
    directory: Path,
    ids: list[str] | None = None,
    dry_run: bool = False,
    resolve: Resolver | None = None,
    fetcher: Fetcher = git_fetcher,
    out: Callable[[str], None] = print,
) -> int:
    """`owpp sync`: 0 when every plugin is up to date or was moved, 1 when one could not be."""
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
    moves = [sync_plugin(f, dry_run, resolve, fetcher) for f in sourced]
    for m in moves:
        where = f"({m.track})" if m.track != "HEAD" else "(default branch)"
        if m.error:
            out(f"FAIL  {m.id}: {m.error}")
        elif not m.moved:
            out(f"ok    {m.id}: up to date {where}, {m.old[:7]}")
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
    moved = [m for m in moves if m.moved]
    if moved and not dry_run:
        out(
            f"{len(moved)} plugin(s) moved: review the upstream changes, run `owpp check` and "
            "`owpp test`, then commit plugin.yaml"
        )
    return 1 if any(m.error for m in moves) else 0
