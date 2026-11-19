"""Every example plugin's test says what it checks and how to repeat it by hand, as
docs/testing.md asks ("Describe every test"). The test catalogue on the docs site is built
from these docstrings."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "plugins"
TESTS = [
    (path, node)
    for path in sorted(EXAMPLES.glob("*/tests/test_*.py"))
    for node in ast.parse(path.read_text()).body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
]


def test_there_are_example_tests_to_check():
    assert len(TESTS) > 50


@pytest.mark.parametrize(
    ("path", "node"), TESTS, ids=[f"{p.parent.parent.name}::{n.name}" for p, n in TESTS]
)
def test_each_example_test_has_a_description_and_by_hand_steps(path, node):
    doc = ast.get_docstring(node) or ""
    what, _, hand = doc.partition("By hand:")
    assert what.strip(), f"{path.name}:{node.lineno} {node.name} has no docstring"
    assert hand.strip(), f"{path.name}:{node.lineno} {node.name} has no 'By hand:' steps"
