"""Shared helpers: plugin folders on disk, an Open-WebUI in memory, fake git sources."""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from fake_open_webui import FakeOpenWebUI, serve

from owpp.bundle import load_function_files
from owpp.embedding import runtime_data, runtime_start
from owpp.openwebui import MANAGED_BY
from owpp.sources import Sources

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
            "meta": {"description": file.description, "managed_by": MANAGED_BY},
            "type": "filter",
            "is_active": True,
            "is_global": False,
            **extra,
        }

    return make


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
