"""Turning a plugin's files, written as ordinary Python, into the one module Open-WebUI stores.

`function.py` and `tool.py` import what they use, including the plugin's own code
(`from shared import NAME`) and the libraries (`from owpp.lib import NAME`). Those are real
imports for an editor and for tests. In the bundle, shared.py and the libraries are already
above the file, so the bundler removes the lines and the names are in scope. Removing one is only
safe for a top-level import without `as`, and only if the files do not define the same name,
since they become one namespace. Anything else is refused here, with the line it is on
(docs/adr/0002-plugin-source-is-python.md). The libraries import each other relatively
(`from .plugin_core import plugin_app`), and those imports go the same way.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

from .errors import OwppError

SHARED = "shared"
LIB = "owpp.lib"
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


def flatten(
    name: str, text: str, shared: str | None, where: str, lib: dict[str, str]
) -> tuple[str, dict[str, int]]:
    """`text` (function.py or tool.py, `name` without .py) with its `from shared import` and
    `from owpp.lib import` lines removed, ready to go below `shared` (shared.py's text, or None
    without one) and the libraries. `lib` is what owpp.lib exports ({name: library}). Returns
    the code and the names it imports from owpp.lib, with their lines, so the caller can check
    their libraries are in the bundle. `where` is how errors name the file."""
    tree = _parse(text, where)
    top = set(map(id, tree.body))
    others = [other for other in SEPARATE if other != name]
    shared_names = defined(_parse(shared, where.rsplit("/", 1)[0] + "/shared.py")) if shared else {}

    def fail(node: ast.AST, message: str) -> OwppError:
        return OwppError(f"{where}:{node.lineno}: {message}")

    drop: list[tuple[int, int]] = []
    from_lib: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root == "owpp":
                    raise fail(node, _owpp_form(f"import {alias.name}"))
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
            if module == "owpp" and not node.level:
                if node.module != LIB:
                    raise fail(node, _owpp_form(f"from {node.module} import ..."))
                if id(node) not in top:
                    raise fail(
                        node,
                        "`from owpp.lib import` must be at the top level of the file: the "
                        "bundler removes it there, and the libraries are in scope everywhere below",
                    )
                for alias in node.names:
                    if alias.name == "*":
                        raise fail(node, "`from owpp.lib import *`: name what you use")
                    if alias.asname:
                        raise fail(
                            node,
                            f"`from owpp.lib import {alias.name} as {alias.asname}`: no `as`. The "
                            f"bundler removes the line, so {alias.asname} would be undefined",
                        )
                    if alias.name not in lib:
                        raise fail(node, f"owpp.lib has no {alias.name}")
                    from_lib.setdefault(alias.name, node.lineno)
                drop.append((node.lineno, node.end_lineno or node.lineno))
                continue
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

    return _drop(text, drop), from_lib


def _drop(text: str, spans: list[tuple[int, int]]) -> str:
    """`text` without the lines in `spans` (1-based, inclusive). Where the removed lines were set
    off by blank lines on both sides, the two runs meet: the longer one is kept."""
    lines = text.splitlines(keepends=True)
    for start, end in sorted(spans, reverse=True):
        del lines[start - 1 : end]
        first = last = start - 1
        while first > 0 and not lines[first - 1].strip():
            first -= 1
        while last < len(lines) and not lines[last].strip():
            last += 1
        before, after = start - 1 - first, last - (start - 1)
        if before and after:
            del lines[first + max(before, after) : last]
    return "".join(lines)


def strip_relative_imports(text: str, where: str) -> str:
    """A library's text without its top-level relative imports of the other libraries, and
    without an `if _TYPE_CHECKING:` block that holds only such imports. In a bundle the
    libraries are one module, in catalogue order, so the names are already there."""
    tree = _parse(text, where)
    spans = []
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.level
            or (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id in ("TYPE_CHECKING", "_TYPE_CHECKING")
                and not node.orelse
                and all(isinstance(n, ast.ImportFrom) and n.level for n in node.body)
            )
        ):
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return _drop(text, spans)


def _owpp_form(written: str) -> str:
    return (
        f"`{written}`: owpp is not installed in Open-WebUI, so the only import of it a plugin "
        "can have is `from owpp.lib import NAME`, which the bundler removes"
    )


def _separate(fail, node: ast.AST, name: str, other: str) -> OwppError:
    return fail(
        node,
        f"{name}.py and {other}.py are bundled into separate modules, so {name}.py cannot "
        f"import from {other}.py: move what both need into shared.py",
    )


def missing_lib_imports(text: str, lib: dict[str, str]) -> list[str]:
    """Names of owpp.lib that `text` uses but never binds or imports: what it is missing to
    import, written the way bundles used to work, with the libraries simply above the file."""
    tree = ast.parse(text)
    bound: set[str] = set()
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (used if isinstance(node.ctx, ast.Load) else bound).add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return sorted((n for n in used - bound if n in lib), key=_isort)


def _isort(name: str) -> tuple[int, str]:
    """isort's (and ruff's) order inside one import: constants, then classes, then the rest."""
    return (0 if name.isupper() else 1 if name[0].isupper() else 2, name.lower())


def import_line(module: str, names: list[str], width: int = 100) -> str:
    """`from <module> import <names>` on one line, or one name per line when it is too long."""
    line = f"from {module} import {', '.join(names)}\n"
    if len(line) <= width + 1:
        return line
    return f"from {module} import (\n" + "".join(f"    {n},\n" for n in names) + ")\n"


def add_lib_imports(text: str, lib: dict[str, str]) -> str:
    """`text` with a `from owpp.lib import ...` for the library names it uses without importing,
    after its other top-level imports (ahead of `from shared import`). Unchanged if none."""
    names = missing_lib_imports(text, lib)
    if not names:
        return text
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    leading = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            leading.append(node)
        elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            break
    shared = [n for n in leading if isinstance(n, ast.ImportFrom) and n.module == SHARED]
    if shared:
        at, block = shared[0].lineno - 1, import_line(LIB, names) + "\n"
    elif leading:
        at, block = leading[-1].end_lineno or 0, "\n" + import_line(LIB, names)
    else:
        at = 0
        while at < len(lines) and lines[at].startswith("#"):
            at += 1
        block = ("\n" if at else "") + import_line(LIB, names) + "\n"
    return "".join(lines[:at]) + block + "".join(lines[at:])
