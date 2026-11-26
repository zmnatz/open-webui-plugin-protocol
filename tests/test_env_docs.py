"""Every environment variable owpp (and owpp-live) reads has an entry on
docs/environment-variables.md, and every entry there is one they read."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "environment-variables.md"
SOURCES = sorted(
    [
        *(ROOT / "src" / "owpp").rglob("*.py"),
        *(ROOT / "packages" / "owpp-live" / "src").rglob("*.py"),
    ]
)


def _is_environment(node: ast.expr) -> bool:
    """`env` (the mapping the commands are given) or `os.environ`."""
    return (isinstance(node, ast.Name) and node.id == "env") or (
        isinstance(node, ast.Attribute) and node.attr == "environ"
    )


def _read(tree: ast.AST) -> set[str]:
    """The names read with env.get("X"), env["X"], os.environ.get("X"), os.getenv("X")."""
    names = set()
    for node in ast.walk(tree):
        key = None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
            reads = node.func.attr == "get" and _is_environment(node.func.value)
            if reads or node.func.attr == "getenv":
                key = node.args[0]
        elif isinstance(node, ast.Subscript) and _is_environment(node.value):
            key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            names.add(key.value)
    return names


READ = {name: path for path in SOURCES for name in _read(ast.parse(path.read_text()))}
ENTRIES = re.findall(r"^### `([A-Z][A-Z0-9_]*)`$", PAGE.read_text(), re.M)


def test_there_are_variables_to_check():
    assert {"OPEN_WEBUI_URL", "OWPP_PLUGINS_DIR", "OPEN_WEBUI_CLIENT_KEY"} <= set(READ)


@pytest.mark.parametrize("name", sorted(READ))
def test_each_variable_owpp_reads_has_an_entry(name):
    """A `### `NAME`` heading on the page, which is in zensical.toml's Guide section."""
    where = READ[name].relative_to(ROOT)
    assert name in ENTRIES, (
        f"{where} reads ${name}: give it an entry in docs/environment-variables.md"
    )
    toml = (ROOT / "zensical.toml").read_text()
    guide = re.search(r'\{ "Guide" = \[(.*?)\] \}', toml, re.S)
    assert guide and '"environment-variables.md"' in guide.group(1)


@pytest.mark.parametrize("name", ENTRIES)
def test_each_entry_is_a_variable_owpp_reads(name):
    """No entry outlives the code that read its variable."""
    assert name in READ, (
        f"docs/environment-variables.md has an entry for {name}, which owpp never reads"
    )
