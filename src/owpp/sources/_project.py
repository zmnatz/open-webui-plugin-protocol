"""`.owpp/`: what owpp takes from git, kept in the project as Node keeps node_modules.

    .owpp/store/<repository>/<sha>/tree/<path>          the upstream files, as fetched
    .owpp/store/<repository>/<sha>/records/<key>.json   one fetched entry: its files and hashes
    .owpp/modules/<plugin id>/                          a whole plugin from git, as bundled
    .owpp/.gitignore                                    "*": git leaves the folder out

The store never changes once written: a commit holds the same files for ever. A module is written
again when what it is made from changes. What owpp wrote is bundled only as owpp wrote it: a
changed file is refused, since this code runs with admin rights and the same pins must give the
same bundle. A `.owpp/` that git tracks is refused for the same reason: its records would arrive
with the files they vouch for. When git cannot say what it tracks, `.owpp/` is left alone.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from ..errors import OwppError
from ..locking import locked
from ..manifest import Value, file_value, is_plain_path, value_bytes
from ._git import SHA40, Fetcher

FOLDER = ".owpp"
# A module's record: what it was made from, and the hash of everything in it.
RECORD = ".owpp-record.json"
# What running Python or opening a folder leaves behind (the bundler itself skips .DS_Store).
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
        self._trusted: bool | None = None
        self._unwritable = False

    def holds(self, folder: Path) -> bool:
        """Whether `folder` is a plugin of this plugins folder (not of a temporary copy)."""
        return folder.resolve().parent == self.plugins

    def fetcher(self, fetch: Fetcher) -> Fetcher:
        """`fetch`, reading each entry the store holds and keeping each one it has to fetch."""

        def kept(git: str, sha: str, paths: list[str]) -> dict[str, Value]:
            if not (SHA40.fullmatch(sha) and self._usable()):
                return fetch(git, sha, paths)
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

    def plugin_copy(self, name: str, inputs: str, write: Callable[[Path], None]) -> Path | None:
        """`modules/<name>`: as it is when it was made from `inputs`, else made by `write`.
        None when `.owpp/` cannot be used or written."""
        if not self._usable():
            return None
        try:
            self._create()
            modules = self.path / "modules"
            modules.mkdir(exist_ok=True)
            # Processes that start at once (owpp test -- -n auto) take turns.
            with locked(modules / f".{name}.lock"):
                target = modules / name
                if target.exists() and _made_from(target) == inputs:
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
        tree = commit / "tree"
        try:
            self._create()
            for path, content in data.items():
                if not is_plain_path(path):
                    raise OwppError(f"{path!r} from git is not a plain path")
                # A file system that ignores case can give two paths one file: such an entry
                # is not kept, and is fetched each time.
                if not _spelled(tree, path):
                    return
                target = tree / path
                if not target.exists():
                    _replace(target, content)
                elif target.read_bytes() != content:  # a commit's file never changes
                    raise _changed(target, commit)
            record = {"entry": entry, "files": {p: _hash(b) for p, b in data.items()}}
            _replace(_record(commit, entry), (json.dumps(record, indent=1) + "\n").encode())
        except OSError as e:
            self._cannot_write(e)

    def _create(self) -> None:
        if self.path.is_dir():
            return self._ignore_itself()
        # Asked before the folder exists, so that only the project's own rules answer.
        # Exit code 1: in a repository that does not ignore it.
        ignored = _git(self.project, "check-ignore", "-q", f"{FOLDER}/").returncode
        try:
            self.path.mkdir()
            self._trusted = True  # new, and owpp's own
        except FileExistsError:
            if not self.path.is_dir():
                raise
        else:
            if ignored == 1:  # only the process that made the folder says this
                print(
                    f"note  {self.path} holds what owpp takes from git: add `{FOLDER}/` to your "
                    ".gitignore",
                    file=sys.stderr,
                )
        self._ignore_itself()

    def _ignore_itself(self) -> None:
        """A .gitignore inside, so that git leaves the folder out even when the project's does
        not name it."""
        ignore = self.path / ".gitignore"
        if not ignore.exists():
            _replace(ignore, b"*\n")

    def _usable(self) -> bool:
        """Whether what `.owpp/` holds can be trusted. Refused when git tracks any of it."""
        if self._trusted is None:
            if not os.path.lexists(self.path):
                return True  # nothing in it yet
            self._trusted = self._untracked()
            if self._trusted:
                # A folder a CI cache restored has no .gitignore of its own.
                with contextlib.suppress(OSError):
                    self._ignore_itself()
        return self._trusted

    def _untracked(self) -> bool:
        """True when git tracks nothing in `.owpp/`; False, with a note, when the project is in
        a repository and git cannot say."""
        prefix = _git(self.project, "rev-parse", "--show-prefix")
        if prefix.returncode == 0:
            # In any case of its letters: some file systems open .OWPP/ as .owpp/.
            folder = f"{prefix.stdout.decode().strip()}{FOLDER}"
            tracked = _git(self.project, "ls-files", "--", f":(top,icase,literal){folder}")
            if tracked.returncode == 0:
                if tracked.stdout.strip():
                    raise OwppError(
                        f"git tracks files in {self.path}, so owpp cannot trust them: run "
                        f"`git rm -r --cached {FOLDER}` there, add `{FOLDER}/` to .gitignore, "
                        "and delete the folder"
                    )
                return True
        elif not any((p / ".git").exists() for p in (self.project, *self.project.parents)):
            return True  # no repository, so nothing is tracked
        print(
            f"note  git cannot say whether it tracks {self.path}, so it is not used",
            file=sys.stderr,
        )
        return False

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


def _under(files: dict[str, Value], entry: str) -> dict[str, Value]:
    """What a fetch returned for one entry: a file, a folder ("dir/") or everything ("./")."""
    if entry == "./":
        return files
    if entry.endswith("/"):
        return {k: v for k, v in files.items() if k.startswith(entry)}
    return {entry: files[entry]} if entry in files else {}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _spelled(tree: Path, path: str) -> bool:
    """Whether each part of `path` that exists under `tree` is written exactly as in `path`."""
    here = tree
    for part in path.split("/"):
        if not os.path.lexists(here / part):
            return True
        if part not in os.listdir(here):
            return False
        here = here / part
    return True


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
        if not is_plain_path(path):
            raise _changed(record, commit)
        file = commit / "tree" / path
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
                    found[f"{path}/"] = ""
                    walk(Path(e.path), f"{path}/")
                elif e.name != _IGNORED and path != RECORD:
                    found[path] = _hash(Path(e.path).read_bytes())

    walk(folder, "")
    return found


def _made_from(module: Path) -> str:
    """What a module was made from, once everything in it is as it was written. What Python
    added in a __pycache__ is deleted first, so that none of it can be bundled."""
    try:
        record = json.loads((module / RECORD).read_text())
        recorded, inputs = dict(record["files"]), str(record["inputs"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise _changed(module / RECORD, module) from e
    found = _hashes(module)
    # Deepest first, so that a folder is empty when its turn comes.
    for path in sorted(found.keys() - recorded.keys(), key=len, reverse=True):
        if _CACHE in path.split("/") and found[path] != "link":
            added = module / path
            added.rmdir() if path.endswith("/") else added.unlink()
            del found[path]
    if found != recorded:
        different = sorted(
            p for p in found.keys() | recorded.keys() if found.get(p) != recorded.get(p)
        )
        raise _changed(module / different[0], module)
    return inputs
