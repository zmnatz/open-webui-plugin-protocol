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
import symtable
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
                    from_import = isinstance(node, ast.ImportFrom)
                    names.setdefault(bound_name(alias, from_import), node.lineno)
    return names


def bound_name(alias: ast.alias, from_import: bool) -> str:
    """The name an import alias binds: `as` name, else the name (`import a.b` binds `a`)."""
    if alias.asname:
        return alias.asname
    return alias.name if from_import else alias.name.split(".")[0]


def bindings(tree: ast.Module) -> list[tuple[str, int, str | None]]:
    """Every binding of a module-level name, in order: (name, line, module) where module is
    what an import binds it from (None for any other binding). Covers assignments, defs and
    classes, imports, `for`/`with`/`except`/`match` targets, `:=`, and a `global` name that a
    function assigns."""
    out: list[tuple[str, int, str | None]] = []
    comprehensions = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)

    def walk(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append((node.name, node.lineno, None))
            for part in (*node.decorator_list, *getattr(node, "bases", ())):
                walk(part)
            _global_assignments(node)
            return
        if isinstance(node, (ast.Lambda, *comprehensions)):
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.append((node.id, node.lineno, None))
        elif isinstance(node, ast.Import):
            out.extend([(bound_name(a, False), node.lineno, a.name) for a in node.names])
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            out.extend(
                [(bound_name(a, True), node.lineno, module) for a in node.names if a.name != "*"]
            )
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            out.append((node.name, node.lineno, None))
        elif isinstance(node, ast.MatchMapping) and node.rest:
            out.append((node.rest, node.lineno, None))
        for child in ast.iter_child_nodes(node):
            walk(child)

    def _global_assignments(scope: ast.AST) -> None:
        declared = {n for g in ast.walk(scope) if isinstance(g, ast.Global) for n in g.names}
        for node in ast.walk(scope):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Store)
                and node.id in declared
            ):
                out.append((node.id, node.lineno, None))

    for statement in tree.body:
        walk(statement)
    return out


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
    shared_where = where.rsplit("/", 1)[0] + "/shared.py"
    shared_tree = _parse(shared, shared_where) if shared is not None else ast.Module([], [])
    shared_bound = defined(shared_tree)  # what shared.py binds, its imports included
    shared_own = {n for n, _, module in bindings(shared_tree) if module is None}

    def fail(node: ast.AST, message: str) -> OwppError:
        return OwppError(f"{where}:{node.lineno}: {message}")

    def removable(node: ast.ImportFrom, module: str, scope: str) -> None:
        """What the bundler can remove without leaving a name undefined: a top-level
        `from <module> import NAME`, no `*`, no `as`. `scope` says what is in scope instead."""
        if id(node) not in top:
            raise fail(
                node,
                f"`from {module} import` must be at the top level of the file: the bundler "
                f"removes it there, and {scope} are in scope everywhere below",
            )
        for alias in node.names:
            if alias.name == "*":
                raise fail(node, f"`from {module} import *`: name what you use")
            if alias.asname:
                raise fail(
                    node,
                    f"`from {module} import {alias.name} as {alias.asname}`: no `as`. The "
                    f"bundler removes the line, so {alias.asname} would be undefined",
                )

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
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        module = (node.module or "").split(".")[0]
        if node.level:  # the bundle is not in a package, so nothing is relative to it
            sibling = module or next((a.name for a in node.names if a.name in others), "")
            if sibling in others:
                raise _separate(fail, node, name, sibling)
            raise fail(
                node,
                "a relative import has no package to resolve against once bundled: write "
                "`from shared import NAME` for the plugin's own code",
            )
        if module == "owpp":
            if node.module != LIB:
                raise fail(node, _owpp_form(f"from {node.module} import ..."))
            removable(node, LIB, "the libraries")
            for alias in node.names:
                if alias.name not in lib:
                    raise fail(node, f"owpp.lib has no {alias.name}")
                from_lib.setdefault(alias.name, node.lineno)
            drop.append((node.lineno, node.end_lineno or node.lineno))
        elif module in others:
            raise _separate(fail, node, name, module)
        elif module == SHARED:
            removable(node, SHARED, "shared.py's names")
            if shared is None:
                raise fail(node, "`from shared import` but the plugin has no shared.py")
            for alias in node.names:
                if alias.name not in shared_bound:
                    raise fail(node, f"{alias.name} is not defined in shared.py")
            drop.append((node.lineno, node.end_lineno or node.lineno))

    _refuse_unimported(text, where, lib, shared_own, shared_bound)

    # shared.py's own names (not what it imports) may be bound here only by importing them.
    for bound, line, module in bindings(tree):
        if bound in shared_own and module != SHARED:
            raise OwppError(
                f"{where}:{line}: {bound} is defined in shared.py and bound here too. They are "
                "one namespace once bundled, so one would replace the other: rename one"
            )

    return _drop(text, drop), from_lib


MIGRATE = "`owpp migrate` adds the imports a plugin written before protocol 0.5 is missing"


def _refuse_unimported(
    text: str, where: str, lib: dict[str, str], shared_own: set[str], shared_bound: dict
) -> None:
    """A library or shared.py name used without being imported. Bundled, it would still be in
    scope, but the file would not read as Python on its own, which is the point of importing.
    `shared_own` is what shared.py defines itself, `shared_bound` that and what it imports."""
    for name, line in sorted(unbound(text).items(), key=lambda item: item[1]):
        if name in shared_own:
            raise OwppError(
                f"{where}:{line}: {name} is shared.py's, used without importing it: add "
                f"`from shared import {name}` ({MIGRATE})"
            )
        if name in shared_bound:
            raise OwppError(
                f"{where}:{line}: {name} is imported in shared.py, not here: import it in this "
                f"file too ({MIGRATE})"
            )
        if name in lib:
            raise OwppError(
                f"{where}:{line}: {name} is used without importing it: add "
                f"`from owpp.lib import {name}` ({MIGRATE})"
            )


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


def unbound(text: str) -> dict[str, int]:
    """Names the module looks up as globals (from any scope) without binding them at its top
    level, with the line of the first such use: what it expects to find already in scope,
    builtins included. Resolved scope by scope, as the compiler does (symtable)."""
    top = symtable.symtable(text, "<plugin>", "exec")
    bound = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()}
    # Per scope (function and class bodies by their first line), the names it reads as globals.
    globals_in: dict[tuple[str, int], set[str]] = {}

    def visit(table: symtable.SymbolTable) -> None:
        names = {
            s.get_name()
            for s in table.get_symbols()
            if s.is_referenced() and (table.get_type() == "module" or s.is_global())
        }
        globals_in[(table.get_name(), table.get_lineno())] = names
        for child in table.get_children():
            visit(child)

    visit(top)
    tree = ast.parse(text)
    # Annotations name globals too, even postponed ones (`from __future__ import annotations`)
    # that symtable leaves out: FastAPI and pydantic look them up in the module at run time.
    annotated: dict[str, int] = {}
    for node in ast.walk(tree):
        notes = []
        if isinstance(node, ast.arg) and node.annotation is not None:
            notes.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns:
            notes.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            notes.append(node.annotation)
        for note in notes:
            for name in ast.walk(note):
                if isinstance(name, ast.Name):
                    annotated[name.id] = min(annotated.get(name.id, name.lineno), name.lineno)
    wanted = (set().union(*globals_in.values()) | set(annotated)) - bound
    lines: dict[str, int] = {n: line for n, line in annotated.items() if n in wanted}

    def walk(node: ast.AST, scope: set[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for part in (
                *node.decorator_list,
                *getattr(node, "bases", ()),
                *getattr(node, "keywords", ()),
            ):
                walk(part, scope)
            if not isinstance(node, ast.ClassDef):
                for default in (*node.args.defaults, *node.args.kw_defaults):
                    if default is not None:
                        walk(default, scope)
            inner = globals_in.get((node.name, node.lineno), scope)
            if node.decorator_list:  # symtable gives a decorated def the line of its def
                inner = globals_in.get((node.name, node.decorator_list[0].lineno), inner)
            for child in node.body:
                walk(child, inner)
            return
        is_load = isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        if is_load and node.id in wanted and node.id in scope:
            lines[node.id] = min(lines.get(node.id, node.lineno), node.lineno)
        for child in ast.iter_child_nodes(node):
            walk(child, scope)

    walk(tree, globals_in[("top", 0)] | set(annotated))
    return {name: lines.get(name, 1) for name in sorted(wanted)}


def missing_lib_imports(text: str, lib: dict[str, str]) -> list[str]:
    """Names of owpp.lib that `text` uses but never binds or imports: what it is missing to
    import, written the way bundles used to work, with the libraries simply above the file."""
    return sorted((n for n in unbound(text) if n in lib), key=_isort)


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
