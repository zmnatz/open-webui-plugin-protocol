"""Files a plugin takes from a git repo (`source:` in plugin.yaml), pinned to a commit."""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from .errors import OwppError
from .manifest import get, read_manifest, text_of

# A file's content: text when it is UTF-8, else {"base64": ...} (a skill may ship an image or a font).
Value = str | dict
Fetcher = Callable[[str, str, "list[str]"], "dict[str, Value]"]

SHA40 = re.compile(r"[0-9a-f]{40}")
# A branch or tag a plugin follows (`source: track:`), as git allows it, never an option.
TRACK = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]*")
MAX_SOURCE_BYTES = 2_000_000
MAX_SKILL_FILES = 1000

# Where a repo can be cloned from: https, ssh or scp-style, never a local path or an
# exotic git transport (ext::, file://), and never something git would read as an option.
GIT_URL = re.compile(r"(https://|ssh://|[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:)[^\s#]+")


def source_key(folder: str, src: object, rel: str, directory: bool = False) -> str:
    """A file in a plugin's `source`, as the key fetch_sources and the bundler share."""
    where = f"{folder}/plugin.yaml: source"
    if not isinstance(src, dict):
        raise OwppError(f"{where} must have git, ref and path")
    git = text_of(src.get("git"))
    ref = text_of(src.get("ref"))
    if not GIT_URL.fullmatch(git):
        raise OwppError(f"{where}.git must be an https://, ssh:// or user@host:path git URL")
    if not ref:
        raise OwppError(
            f"{where} has no `ref:`; run `owpp sync {folder}` to pin it to the latest commit"
        )
    if not SHA40.fullmatch(ref):
        raise OwppError(
            f"{where}.ref must be a full 40-character commit SHA, not a branch or tag "
            "(those can change under you)"
        )
    track = text_of(src.get("track"))
    if track and not TRACK.fullmatch(track):
        raise OwppError(f"{where}.track must be a branch or tag name (owpp sync follows it)")
    parts = [p for p in [*text_of(src.get("path")).split("/"), *str(rel).split("/")] if p]
    if any(p in ("..", ".") for p in parts):
        raise OwppError(f"{where}: paths may not contain . or ..")
    if directory and not parts:
        raise OwppError(f"{where}: a directory needs a path")
    return f"{git}#{ref}:{'/'.join(parts)}{'/' if directory else ''}"


def _source_files(manifest: dict) -> list[tuple[str, bool]]:
    """The files (and skill directories) in `source` that a manifest refers to: (path, is_dir).
    A whole plugin taken from git is one directory: the source's `path`."""
    if get(manifest.get("source"), "plugin") is True:
        return [("", True)]
    files: list[tuple[str, bool]] = []
    if get(manifest.get("function"), "file"):
        files.append((manifest["function"]["file"], False))
    if get(manifest.get("tool"), "file"):
        files.append((manifest["tool"]["file"], False))
    skills = manifest.get("skills")
    for sk in skills.values() if isinstance(skills, dict) else []:
        if get(sk, "dir"):
            files.append((sk["dir"], True))
        elif get(sk, "file"):
            files.append((sk["file"], False))
    return files


def pick_sha(ls_remote: str, ref: str) -> str | None:
    """The commit `ref` names in `git ls-remote` output. An annotated tag's commit is its
    peeled `^{}` entry; a tag wins over a branch of the same name, as in git itself."""
    found = {
        name: sha
        for sha, _, name in (line.partition("\t") for line in ls_remote.splitlines())
        if SHA40.fullmatch(sha)
    }
    names = ["HEAD"] if ref == "HEAD" else []
    names += [f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", f"refs/heads/{ref}"]
    return next((found[n] for n in names if n in found), None)


def resolve_ref(git: str, ref: str) -> str | None:
    """The full commit SHA a branch or tag of `git` points at, looked up with `git ls-remote`
    (`HEAD`: the default branch), or None when it cannot be found. A SHA is returned as it is."""
    if SHA40.fullmatch(ref):
        return ref
    if not GIT_URL.fullmatch(git) or not (ref == "HEAD" or TRACK.fullmatch(ref)):
        return None
    if not shutil.which("git"):
        return None
    patterns = ["HEAD"] if ref == "HEAD" else [ref, f"{ref}^{{}}"]
    try:
        done = subprocess.run(
            ["git", "ls-remote", "--", git, *patterns],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "GIT_ALLOW_PROTOCOL": "https:ssh", "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return pick_sha(done.stdout, ref) if done.returncode == 0 else None


def plugin_folders(directory: Path) -> list[Path]:
    """Sub-folders of `directory` that hold a plugin.yaml, by name."""
    with os.scandir(directory) as it:
        entries = sorted(it, key=lambda e: e.name)
    return [
        Path(e.path)
        for e in entries
        if e.is_dir(follow_symlinks=False) and (Path(e.path) / "plugin.yaml").exists()
    ]


def source_keys(directory: Path | str) -> list[str]:
    """Every source file the plugins folder needs; fetch them with fetch_sources first."""
    keys: dict[str, None] = {}
    for folder in plugin_folders(Path(directory)):
        manifest = read_manifest(folder)
        if not manifest.get("source"):
            continue
        for rel, is_dir in _source_files(manifest):
            keys[source_key(folder.name, manifest["source"], rel, is_dir)] = None
    return list(keys)


def file_value(buf: bytes) -> Value:
    try:
        return buf.decode("utf-8")
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(buf).decode("ascii")}


def _size(value: Value) -> int:
    return len(value) if isinstance(value, str) else len(value["base64"])


def git_fetcher(
    git: str, ref: str, paths: list[str], protocols: str = "https:ssh"
) -> dict[str, Value]:
    """Read files at an exact commit with git itself, so any host works.

    The commit is fetched by SHA (shallow) into a scratch repo; only https and ssh are
    allowed. A path ending in "/" is a directory: every regular file under it is
    returned, keyed by its full path (symlinks and submodules are skipped)."""
    work = tempfile.mkdtemp(prefix="plugin-src-")
    env = {**os.environ, "GIT_ALLOW_PROTOCOL": protocols, "GIT_TERMINAL_PROMPT": "0"}

    def run(*args: str) -> bytes:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=work,
                env=env,
                check=True,
                capture_output=True,
            ).stdout
        except FileNotFoundError as e:
            raise OwppError("the git CLI is required to read a plugin's `source:`") from e

    def read(path: str) -> Value:
        try:
            size = int(run("cat-file", "-s", f"FETCH_HEAD:{path}"))
            if size > MAX_SOURCE_BYTES:
                raise OwppError(f"{git} {path} is larger than {MAX_SOURCE_BYTES} bytes")
            return file_value(run("cat-file", "blob", f"FETCH_HEAD:{path}"))
        except (subprocess.CalledProcessError, ValueError) as e:
            raise OwppError(f"{path} not found in {git} at {ref}") from e

    try:
        run("init", "-q")
        try:
            run("fetch", "-q", "--depth", "1", "--no-tags", "--", git, ref)
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or b"").decode("utf-8", "replace").strip()
            raise OwppError(f"git fetch {git} {ref} failed: {detail}") from e
        out: dict[str, Value] = {}
        for path in paths:
            if not path.endswith("/"):
                out[path] = read(path)
                continue
            listing = run("ls-tree", "-r", "-z", "FETCH_HEAD", "--", path)
            for entry in filter(None, listing.decode("utf-8").split("\0")):
                m = re.fullmatch(r"(\d+) blob [0-9a-f]+\t(.*)", entry, re.DOTALL)
                if m and m.group(1) in ("100644", "100755"):
                    out[m.group(2)] = read(m.group(2))
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def fetch_sources(keys: list[str], fetcher: Fetcher = git_fetcher) -> dict[str, Value]:
    """Fetch every key (grouped so each repo is fetched once) into {key: content}.

    A directory key (trailing "/") yields one entry per file under it."""
    groups: dict[str, tuple[str, str, list[str]]] = {}
    for key in keys:
        m = re.fullmatch(r"(.*)#([0-9a-f]{40}):(.*)", key, re.DOTALL)
        if not m:
            raise OwppError(f"bad source key {key}")
        git, ref, path = m.groups()
        groups.setdefault(f"{git}#{ref}", (git, ref, []))[2].append(path)

    out: dict[str, Value] = {}

    def put(git: str, ref: str, path: str, value: Value) -> None:
        if _size(value) > MAX_SOURCE_BYTES:
            raise OwppError(f"{git} {path} is larger than {MAX_SOURCE_BYTES} bytes")
        out[f"{git}#{ref}:{path}"] = value

    for git, ref, paths in groups.values():
        files = fetcher(git, ref, paths)
        for path in paths:
            if path.endswith("/"):
                under = [k for k in files if k.startswith(path)]
                if not under:
                    raise OwppError(f"no files under {path} in {git} at {ref}")
                if len(under) > MAX_SKILL_FILES:
                    raise OwppError(f"{path} in {git} has more than {MAX_SKILL_FILES} files")
                for k in under:
                    put(git, ref, k, files[k])
                continue
            if path not in files:
                raise OwppError(f"{path} not found in {git} at {ref}")
            put(git, ref, path, files[path])
    return out
