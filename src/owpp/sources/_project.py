"""`.owpp/`: what owpp takes from git, kept in the project as Node keeps node_modules.

    .owpp/store/<repository>/<sha>/tree/<path>          the upstream files, as fetched
    .owpp/store/<repository>/<sha>/records/<key>.json   one fetched entry: its files and hashes
    .owpp/modules/<plugin id>/                          a whole plugin from git, as bundled

The store never changes once written: a commit holds the same files for ever. A module is written
again when what it is made from changes. What owpp wrote is bundled only as owpp wrote it: a
changed file is refused, since this code runs with admin rights and the same pins must give the
same bundle. A `.owpp/` that git tracks is refused for the same reason: its records would arrive
with the files they vouch for.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from ..errors import OwppError
from ..locking import locked
from ..manifest import Value, file_value, value_bytes
from ._git import SHA40, Fetcher

FOLDER = ".owpp"
# A module's record: what it was made from, and the hash of everything in it.
RECORD = ".owpp-record.json"
# What running Python or opening a folder leaves behind. __pycache__ is deleted, so that nothing
# in it can be bundled; the bundler itself skips .DS_Store.
_CACHE = "__pycache__"
_IGNORED = ".DS_Store"


class ProjectFolder:
    """The `.owpp/` of the project that holds the plugins folder `plugins`: beside that folder,
    or inside it when it is itself a git repository."""

    def __init__(self, plugins: Path):
        self.plugins = plugins.resolve()
        own_repository = (self.plugins / ".git").exists()
        self.project = self.plugins if own_repository else self.plugins.parent
        self.path = self.project / FOLDER
        self._checked = False
        self._unwritable = False

    def holds(self, folder: Path) -> bool:
        """Whether `folder` is a plugin of this plugins folder (not of a temporary copy)."""
        return folder.resolve().parent == self.plugins

    def fetcher(self, fetch: Fetcher) -> Fetcher:
        """`fetch`, reading each entry the store holds and keeping each one it has to fetch."""

        def kept(git: str, sha: str, paths: list[str]) -> dict[str, Value]:
            if not SHA40.fullmatch(sha):
                return fetch(git, sha, paths)
            self._refuse_tracked()
            commit = self.path / "store" / _repository(git) / sha
            found: dict[str, Value] = {}
            missing = []
            for entry in paths:
                held = _read(commit, entry)
                if held is None:
                    missing.append(entry)
                else:
                    found |= held
            if missing:
                got = fetch(git, sha, missing)
                for entry in missing:
                    self._keep(commit, entry, _under(got, entry))
                found |= got
            return found

        return kept

    def module(self, name: str, inputs: str, write: Callable[[Path], None]) -> Path | None:
        """`modules/<name>`: as it is when it was made from `inputs`, else made by `write`.
        None when the project cannot be written."""
        self._refuse_tracked()
        try:
            self._create()
            modules = self.path / "modules"
            modules.mkdir(exist_ok=True)
            # Processes that start at once (owpp test -- -n auto) take turns.
            with locked(modules / f".{name}.lock"):
                target = modules / name
                if target.exists() and _verified(target) == inputs:
                    return target
                with tempfile.TemporaryDirectory(dir=modules, prefix=".new-") as work:
                    new = Path(work) / name
                    write(new)
                    record = {"inputs": inputs, "files": _hashes(new)}
                    (new / RECORD).write_text(json.dumps(record, indent=1) + "\n")
                    if target.exists():
                        target.rename(Path(work) / "old")
                    new.rename(target)
                return target
        except OSError as e:
            self._cannot_write(e)
            return None

    # ---- inside -------------------------------------------------------------------------

    def _keep(self, commit: Path, entry: str, files: dict[str, Value]) -> None:
        if not files:
            return  # not found: nothing to remember
        data = {path: value_bytes(value) for path, value in files.items()}
        targets = {path: commit / "tree" / _plain(path) for path in data}
        try:
            self._create()
            for path, target in targets.items():
                _replace(target, data[path])
            # A file system that ignores case can give two paths one file: do not record that.
            if any(target.read_bytes() != data[path] for path, target in targets.items()):
                return
            record = {"entry": entry, "files": {p: _hash(b) for p, b in data.items()}}
            _replace(_record(commit, entry), (json.dumps(record, indent=1) + "\n").encode())
        except OSError as e:
            self._cannot_write(e)

    def _create(self) -> None:
        try:
            self.path.mkdir()
        except FileExistsError:
            if not self.path.is_dir():
                raise
            return
        # Only the process that made the folder says this. Exit code 1: in a repository that
        # does not ignore it.
        if _git(self.project, "check-ignore", "-q", f"{FOLDER}/").returncode == 1:
            print(
                f"note  {self.path} holds what owpp takes from git: add `{FOLDER}/` to your "
                ".gitignore",
                file=sys.stderr,
            )

    def _refuse_tracked(self) -> None:
        if self._checked or not os.path.lexists(self.path):
            return
        tracked = _git(self.project, "ls-files", "--", FOLDER)
        if tracked.returncode == 0 and tracked.stdout.strip():
            raise OwppError(
                f"git tracks files in {self.path}, so owpp cannot trust them: run "
                f"`git rm -r --cached {FOLDER}` there, add `{FOLDER}/` to .gitignore, and delete "
                "the folder"
            )
        self._checked = True

    def _cannot_write(self, error: OSError) -> None:
        if not self._unwritable:
            print(
                f"note  cannot write {self.path} ({error}): nothing from git is kept",
                file=sys.stderr,
            )
        self._unwritable = True


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """git in `cwd`, for what it says about the project; exit code 128 when it cannot say."""
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(args, 128, b"", b"")


def _repository(git: str) -> str:
    """A folder name for a repository: readable, and different for every URL."""
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", git.split("://")[-1]).strip("-.")[-60:]
    return f"{readable}-{_hash(git.encode())[:8]}"


def _plain(path: str) -> str:
    """`path` of a file in a repository, refused when it could lead outside the folder."""
    parts = path.split("/")
    if "\\" in path or any(p in ("", ".", "..") or Path(p).anchor for p in parts):
        raise OwppError(f"{path!r} from git is not a plain path")
    return path


def _under(files: dict[str, Value], entry: str) -> dict[str, Value]:
    """What a fetch returned for one entry: a file, a folder ("dir/") or everything ("./")."""
    if entry == "./":
        return files
    if entry.endswith("/"):
        return {k: v for k, v in files.items() if k.startswith(entry)}
    return {entry: files[entry]} if entry in files else {}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(commit: Path, entry: str) -> Path:
    return commit / "records" / f"{_hash(entry.encode())[:32]}.json"


def _changed(path: Path, delete: Path) -> OwppError:
    return OwppError(
        f"{path} is not as owpp wrote it, so it is not the pinned code. Delete {delete} and "
        "run again"
    )


def _read(commit: Path, entry: str) -> dict[str, Value] | None:
    """The entry as the store holds it, each file checked; None when it does not hold it."""
    record = _record(commit, entry)
    if not record.is_file():
        return None
    try:
        recorded = dict(json.loads(record.read_text())["files"])
    except (ValueError, KeyError, TypeError) as e:
        raise _changed(record, commit) from e
    out: dict[str, Value] = {}
    for path, digest in recorded.items():
        file = commit / "tree" / _plain(path)
        data = file.read_bytes() if file.is_file() else None
        if data is None or _hash(data) != digest:
            raise _changed(file, commit)
        out[path] = file_value(data)
    return out


def _replace(path: Path, data: bytes) -> None:
    """Write a file so that no other process ever reads part of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = path.parent / f".new-{uuid.uuid4().hex}"
    try:
        new.write_bytes(data)
        new.replace(path)
    finally:
        new.unlink(missing_ok=True)


def _hashes(folder: Path) -> dict[str, str]:
    """Every file ({path: hash}) and folder ({path/: ""}) in a module: an added folder can turn
    a library on. Links are never followed."""
    found: dict[str, str] = {}

    def walk(here: Path, base: str) -> None:
        with os.scandir(here) as entries:
            for e in sorted(entries, key=lambda e: e.name):
                path = f"{base}{e.name}"
                if e.is_symlink():
                    found[path] = "link"
                elif e.is_dir():
                    if e.name == _CACHE:
                        shutil.rmtree(e.path, ignore_errors=True)
                        continue
                    found[f"{path}/"] = ""
                    walk(Path(e.path), f"{path}/")
                elif e.name != _IGNORED and path != RECORD:
                    found[path] = _hash(Path(e.path).read_bytes())

    walk(folder, "")
    return found


def _verified(module: Path) -> str:
    """What a module was made from, once everything in it is as it was written."""
    try:
        record = json.loads((module / RECORD).read_text())
        recorded, inputs = dict(record["files"]), str(record["inputs"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise _changed(module / RECORD, module) from e
    found = _hashes(module)
    if found != recorded:
        different = sorted(
            p for p in found.keys() | recorded.keys() if found.get(p) != recorded.get(p)
        )
        raise _changed(module / different[0], module)
    return inputs
