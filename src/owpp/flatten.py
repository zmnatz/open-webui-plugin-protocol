"""Turning a plugin's files, written as ordinary Python, into the one module Open-WebUI stores.

`function.py` and `tool.py` import what they use, including the plugin's own code:
`from shared import NAME`. That is a real import for an editor and for tests. In the bundle,
shared.py is already above the file, so the bundler removes the line and the name is in scope.
Removing it is only safe for a top-level `from shared import NAME` without `as`, and only if
the two files do not define the same name, since they become one namespace. Anything else is
refused here, with the line it is on (docs/adr/0002-plugin-source-is-python.md).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

from .errors import OwppError

SHARED = "shared"
# function.py and tool.py are bundled into separate modules, so neither can import the other.
SEPARATE = ("function", "tool")


def _top_level(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """The module's statements, including those inside a top-level if/try/with/for/while."""
    for node in body:
        yield node
        if isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for field in ("body", "orelse", "finalbody"):
                yield from _top_level(getattr(node, field, []))
            for handler in getattr(node, "handlers", []):
                yield from _top_level(handler.body)


def _targets(node: ast.expr) -> Iterator[ast.Name]:
    if isinstance(node, ast.Name):
        yield node
    elif isinstance(node, (ast.Tuple, ast.List)):
        for element in node.elts:
            yield from _targets(element)
    elif isinstance(node, ast.Starred):
        yield from _targets(node.value)


def defined(tree: ast.Module, imports: bool = True) -> dict[str, int]:
    """Names the module binds at its top level, with the line of the first binding. With
    `imports=False`, names bound by an import do not count."""
    names: dict[str, int] = {}
    for node in _top_level(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.setdefault(node.name, node.lineno)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _targets(target):
                    names.setdefault(name.id, node.lineno)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            for name in _targets(node.target):
                names.setdefault(name.id, node.lineno)
        elif imports and isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name != "*":
                    names.setdefault((alias.asname or alias.name).split(".")[0], node.lineno)
    return names


def _parse(text: str, where: str) -> ast.Module:
    try:
        return ast.parse(text)
    except SyntaxError as e:
        raise OwppError(f"{where}:{e.lineno}: {e.msg}") from e


def flatten(name: str, text: str, shared: str | None, where: str) -> str:
    """`text` (function.py or tool.py, `name` without .py) with its `from shared import`
    lines removed, ready to go below `shared` (shared.py's text, or None without one).
    `where` is how errors name the file (`plugins/x/function.py`)."""
    tree = _parse(text, where)
    top = set(map(id, tree.body))
    others = [other for other in SEPARATE if other != name]
    shared_names = defined(_parse(shared, where.rsplit("/", 1)[0] + "/shared.py")) if shared else {}

    def fail(node: ast.AST, message: str) -> OwppError:
        return OwppError(f"{where}:{node.lineno}: {message}")

    drop: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root == SHARED:
                    raise fail(
                        node,
                        f"`import {alias.name}`: write `from shared import NAME`. The bundler "
                        "removes that line, because shared.py is already above this file",
                    )
                if root in others:
                    raise _separate(fail, node, name, root)
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if node.level and module == SHARED:
                raise fail(node, "write `from shared import NAME`, without the dot")
            if module in others and not node.level:
                raise _separate(fail, node, name, module)
            if module != SHARED or node.level:
                continue
            if id(node) not in top:
                raise fail(
                    node,
                    "`from shared import` must be at the top level of the file: the bundler "
                    "removes it there, and shared.py's names are in scope everywhere below",
                )
            if shared is None:
                raise fail(node, "`from shared import` but the plugin has no shared.py")
            for alias in node.names:
                if alias.name == "*":
                    raise fail(node, "`from shared import *`: name what you use")
                if alias.asname:
                    raise fail(
                        node,
                        f"`from shared import {alias.name} as {alias.asname}`: no `as`. The "
                        f"bundler removes the line, so {alias.asname} would be undefined",
                    )
                if alias.name not in shared_names:
                    raise fail(node, f"{alias.name} is not defined in shared.py")
            drop.append((node.lineno, node.end_lineno or node.lineno))

    for own, line in defined(tree, imports=False).items():
        if own in shared_names:
            raise OwppError(
                f"{where}:{line}: {own} is defined here and in shared.py. They are one "
                "namespace once bundled, so one would replace the other: rename one"
            )

    lines = text.splitlines(keepends=True)
    for start, end in sorted(drop, reverse=True):
        del lines[start - 1 : end]
    return "".join(lines)


def _separate(fail, node: ast.AST, name: str, other: str) -> OwppError:
    return fail(
        node,
        f"{name}.py and {other}.py are bundled into separate modules, so {name}.py cannot "
        f"import from {other}.py: move what both need into shared.py",
    )
