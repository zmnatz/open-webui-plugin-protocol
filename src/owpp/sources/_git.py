"""The git transport: reading files at an exact commit, and looking up the commit a branch or
tag points at. Only https and ssh remotes; never a local path or an exotic transport."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable

from ..errors import OwppError
from ..manifest import TRACK, Value, file_value

# (git URL, commit SHA, paths) -> {path: content}. A path ending in "/" is a directory: every
# file under it is returned, keyed by its full path.
Fetcher = Callable[[str, str, "list[str]"], "dict[str, Value]"]
# (git URL, branch, tag or HEAD) -> the commit SHA it points at, or None.
Lookup = Callable[[str, str], "str | None"]
# (git URL, name) -> "branch" or "tag", or None.
KindOf = Callable[[str, str], "str | None"]

SHA40 = re.compile(r"[0-9a-f]{40}")
MAX_SOURCE_BYTES = 2_000_000

# Where a repo can be cloned from: https, ssh or scp-style, never a local path or an
# exotic git transport (ext::, file://), and never something git would read as an option.
GIT_URL = re.compile(r"(https://|ssh://|[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:)[^\s#]+")


def pick_sha(ls_remote: str, ref: str) -> str | None:
    """The commit `ref` names in `git ls-remote` output. An annotated tag's commit is its
    peeled `^{}` entry; a tag wins over a branch of the same name, as in git itself."""
    found = {
        name: sha
        for sha, _, name in (line.partition("\t") for line in ls_remote.splitlines())
        if SHA40.fullmatch(sha)
    }
    if ref == "HEAD":
        names = ["HEAD"]
    elif ref.startswith("refs/"):  # exactly that branch or tag
        names = [f"{ref}^{{}}", ref]
    else:
        names = [f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", f"refs/heads/{ref}"]
    return next((found[n] for n in names if n in found), None)


def refname(kind: str, name: str) -> str:
    """What to look up for a plugin that follows (kind, name) (see manifest.follows)."""
    return {"branch": f"refs/heads/{name}", "tag": f"refs/tags/{name}"}.get(kind, name)


def kind_in(ls_remote: str, name: str) -> str | None:
    """ "tag" or "branch": what `name` is in `git ls-remote` output (a tag wins, as in git)."""
    names = {line.partition("\t")[2] for line in ls_remote.splitlines()}
    if f"refs/tags/{name}" in names:
        return "tag"
    if f"refs/heads/{name}" in names:
        return "branch"
    return None


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


def ref_kind(git: str, name: str) -> str | None:
    """Whether `name` is a "tag" or a "branch" of `git`, asked with `git ls-remote`; None when
    it is neither, or the repository cannot be reached."""
    if not GIT_URL.fullmatch(git) or not TRACK.fullmatch(name) or not shutil.which("git"):
        return None
    try:
        done = subprocess.run(
            ["git", "ls-remote", "--", git, f"refs/heads/{name}", f"refs/tags/{name}"],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "GIT_ALLOW_PROTOCOL": "https:ssh", "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return kind_in(done.stdout, name) if done.returncode == 0 else None


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
