"""Shared helpers: plugin folders on disk, an Open-WebUI in memory, fake git repositories."""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from fake_open_webui import FakeOpenWebUI, serve

from owpp.bundle import load_function_files
from owpp.embedding import runtime_data, runtime_start
from owpp.openwebui import MANAGED_BY
from owpp.sources import SHA40, Sources

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "plugins"
DOCS = Path(__file__).resolve().parent.parent / "docs"

FILTER = '''"""
title: Demo Filter
author: me
description: A demo filter.
"""
class Filter:
    pass
'''

SKILL_MD = "---\nname: s\n---\nbody\n"


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    """A served fake Open-WebUI is on localhost; never send those requests through a proxy."""
    for name in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ):
        monkeypatch.delenv(name, raising=False)


def write_tree(root: Path, files: dict[str, str | bytes]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return root


CODE_FILES = ("function.py", "tool.py", "shared.py")


def with_imports(code: str) -> str:
    """`code` with the `from owpp.lib import ...` a plugin writes for the library names it uses,
    for fixtures written to exercise the libraries rather than the imports."""
    from owpp.imports import add_lib_imports

    return add_lib_imports(code)


def write_plugin(root: Path, files: dict[str, str | bytes]) -> Path:
    """write_tree, with each plugin source file given its library imports (with_imports)."""
    return write_tree(
        root,
        {
            name: with_imports(content)
            if name in CODE_FILES and isinstance(content, str)
            else content
            for name, content in files.items()
        },
    )


def embedded(code: str) -> dict:
    """The data of the runtime a bundle must have."""
    assert runtime_start(code) >= 0, "no runtime in the bundle"
    return runtime_data(code)


def above_runtime(code: str) -> str:
    """A bundle's code before its runtime (a tool's code is also in the runtime's data)."""
    assert runtime_start(code) >= 0, "no runtime in the bundle"
    return code[: runtime_start(code)]


def fake_fetcher(overrides: dict[str, str] | None = None):
    """A git that holds a stand-in for every file asked for, so no test needs the network:
    a SKILL.md and a reference under a folder, else a skill or a tool by the extension.
    `overrides` holds the content of some paths instead ({path in the repo: text})."""

    def fetcher(git: str, ref: str, paths: list[str]) -> dict:
        out: dict = {}
        for path in paths:
            if path.endswith("/"):
                out[f"{path}SKILL.md"] = SKILL_MD
                out[f"{path}references/a.md"] = "ref\n"
            elif overrides and path in overrides:
                out[path] = overrides[path]
            else:
                out[path] = (
                    SKILL_MD
                    if path.endswith(".md")
                    else "class Tools:\n    pass\n\nclass Event:\n    pass\n"
                )
        return out

    return fetcher


def fake_sources(overrides: dict[str, str] | None = None) -> Sources:
    """Sources over fake_fetcher."""
    return Sources(fake_fetcher(overrides))


class FakeRepo:
    """A git repository held in memory, so that the files, the commits and the branch-or-tag
    answers a test reads cannot disagree. `sources()` is a Sources that reads it.

    `files` ({path in the repository: content}) are what the commit `sha` holds; `commits`
    ({sha: files}) holds more than one. `branches` and `tags` are {name: sha}, and `head` is the
    default branch's commit. Another URL, or a name it does not have, is not found.

    `fetched`, `looked_up` and `kinds_asked` record what was asked."""

    def __init__(
        self,
        url: str,
        files: dict | None = None,
        *,
        sha: str = "a" * 40,
        commits: dict[str, dict] | None = None,
        branches: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
        head: str | None = None,
    ):
        self.url = url
        self.commits = commits if commits is not None else {sha: files or {}}
        self.branches = branches or {}
        self.tags = tags or {}
        self.head = head
        self.fetched: list[tuple[str, str, list[str]]] = []
        self.looked_up: list[tuple[str, str]] = []
        self.kinds_asked: list[tuple[str, str]] = []

    def fetch(self, git: str, sha: str, paths: list[str]) -> dict:
        self.fetched.append((git, sha, list(paths)))
        assert git == self.url, git
        files = self.commits[sha]
        out: dict = {}
        for path in paths:
            if path.endswith("/"):  # a folder; "./" is the whole repository
                base = "" if path == "./" else path
                out |= {k: v for k, v in files.items() if k.startswith(base)}
            elif path in files:
                out[path] = files[path]
        return out

    def lookup(self, git: str, ref: str) -> str | None:
        self.looked_up.append((git, ref))
        if SHA40.fullmatch(ref):  # a commit is itself
            return ref
        if git != self.url:
            return None
        if ref == "HEAD":
            return self.head
        if ref.startswith("refs/heads/"):
            return self.branches.get(ref.removeprefix("refs/heads/"))
        if ref.startswith("refs/tags/"):
            return self.tags.get(ref.removeprefix("refs/tags/"))
        return self.tags.get(ref) or self.branches.get(ref)  # a tag wins, as in git

    def kind(self, git: str, name: str) -> str | None:
        self.kinds_asked.append((git, name))
        if git != self.url:
            return None
        return "tag" if name in self.tags else "branch" if name in self.branches else None

    def sources(self) -> Sources:
        return Sources(self.fetch, self.lookup, self.kind)


@pytest.fixture
def functions_dir(tmp_path):
    """Make a plugins folder from {name: text}."""
    counter = iter(range(1000))

    def make(files: dict[str, str | bytes]) -> Path:
        return write_tree(tmp_path / f"fn{next(counter)}", files)

    return make


@pytest.fixture
def git_fn(functions_dir):
    """A live function this deploy already manages."""

    def make(fn_id: str, content: str, **extra) -> dict:
        (file,) = load_function_files(functions_dir({f"{fn_id}.py": content}))
        return {
            "id": fn_id,
            "name": file.name,
            "content": content,
            "meta": {"description": file.meta.description, "managed_by": MANAGED_BY},
            "type": "filter",
            "is_active": True,
            "is_global": False,
            **extra,
        }

    return make


# ---- the real Open-WebUI, behind the Fetch port (real_open_webui.py) --------------------


@pytest.fixture
def real_open_webui():
    """Make a RealOpenWebUI: the test harness, as deploy and import are given an Open-WebUI.
    One for each test."""
    from real_open_webui import RealOpenWebUI

    from owpp.testing import Harness

    with contextlib.ExitStack() as stack:

        def make(**kwargs) -> RealOpenWebUI:
            return RealOpenWebUI(stack.enter_context(Harness()), **kwargs)

        yield make


# ---- an Open-WebUI in memory (fake_open_webui.py) --------------------------------------


@pytest.fixture
def open_webui():
    """Make a FakeOpenWebUI; `.serve()` on the made one puts it behind a real HTTP server, until
    the test ends, and gives its URL."""
    with contextlib.ExitStack() as stack:

        def make(**kwargs) -> FakeOpenWebUI:
            fake = FakeOpenWebUI(**kwargs)
            fake.serve = lambda: stack.enter_context(serve(fake))
            return fake

        yield make
