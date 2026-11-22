"""The open_webui type stubs: written from the mock, and the mock has what the plugins import."""

from __future__ import annotations

import ast

import pytest
from conftest import EXAMPLES

from owpp.manifest import read_manifest
from owpp.testing.mock import MockOpenWebUI
from owpp.testing.stubs import STUBS, render


def test_the_stubs_are_written_from_the_mock_as_it_is():
    """Rewrite them with `python -m owpp.testing.stubs` after changing the mock."""
    files = render()
    on_disk = {
        p.relative_to(STUBS).as_posix(): p.read_text() for p in STUBS.rglob("*") if p.is_file()
    }
    assert sorted(on_disk) == sorted(files)
    for path, text in files.items():
        assert on_disk[path] == text, f"{path} is stale: run python -m owpp.testing.stubs"
        if path.endswith(".pyi"):
            ast.parse(text)
    assert files["py.typed"] == "partial\n"  # modules the mock lacks resolve from a real install


def _open_webui_imports(path):
    """(module, name, line) for each name imported from open_webui, at any depth."""
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "open_webui":
            for alias in node.names:
                yield node.module, alias.name, node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "open_webui":
                    yield alias.name, None, node.lineno


OWN = sorted(
    p
    for p in EXAMPLES.glob("*/*.py")
    if p.name in ("function.py", "tool.py", "shared.py")
    and not read_manifest(p.parent).get("source")
)


@pytest.fixture(scope="module")
def modules():
    mock = MockOpenWebUI()
    yield mock._modules()
    mock.close()


@pytest.mark.parametrize("path", OWN, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_the_mock_has_every_open_webui_name_the_examples_import(path, modules):
    """What a plugin of this repository imports from Open-WebUI must be in the mock (and so in
    the stubs), or its test cannot reach it and an editor cannot resolve it. Code taken from git
    is not held to it: the mock's stand-ins let it load."""
    for module, name, line in _open_webui_imports(path):
        assert module in modules, f"{path}:{line}: the mock has no {module}"
        if name is not None:
            assert name in vars(modules[module]), f"{path}:{line}: the mock has no {module}.{name}"
