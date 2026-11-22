"""Writing imports into a plugin's source: the `from owpp.lib import` line `owpp create` gives a
file it generates (add_lib_imports), and `owpp migrate`'s 0.3 -> 0.5 step, which gives each file
the imports it used to do without (upgrade; docs/adr/0002-plugin-source-is-python.md).

Before protocol 0.5, function.py and tool.py relied on shared.py and the libraries being pasted
in above them, and shared.py held imports only the next file used. This works out, for each
file, what it uses without binding and where that comes from:

- a name shared.py defines: `from shared import NAME`;
- a name shared.py imports: the same import, copied into the file;
- a library name: `from owpp.lib import NAME`.

Then shared.py loses the imports only the other files used, `from __future__` lines are made
the same in all three, and the runtime's `_plugin_ensure` becomes `plugin_ensure`. A name it
cannot place is reported, not guessed at.
"""

from __future__ import annotations

import ast
import builtins
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .flatten import LIB, SHARED, bound_name, defined, unbound
from .libraries import exports

FILES = ("shared.py", "function.py", "tool.py")
# What a module has without importing it.
MODULE_NAMES = {"__name__", "__file__", "__doc__", "__spec__", "__loader__", "__package__"}
MODULE_NAMES |= {"__builtins__", "__annotations__", "__path__"}
BUILTINS = set(dir(builtins)) | MODULE_NAMES


@dataclass
class Upgrade:
    """What the step does to a plugin's code: the files it rewrites, and what it could not do."""

    files: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Import:
    """One name a top-level import binds: `import module [as alias]` (name None) or
    `from module import name [as alias]`, and the name it binds (`bound`)."""

    module: str
    name: str | None
    alias: str | None
    bound: str


def _imports(tree: ast.Module) -> dict[str, _Import]:
    """The names a module's top-level imports bind, other than __future__, shared and owpp."""
    out: dict[str, _Import] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                out.setdefault(
                    bound_name(a, False), _Import(a.name, None, a.asname, bound_name(a, False))
                )
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            if node.module == "__future__" or node.module.split(".")[0] in (SHARED, "owpp"):
                continue
            for a in node.names:
                if a.name != "*":
                    bound = bound_name(a, True)
                    out.setdefault(bound, _Import(node.module, a.name, a.asname, bound))
    return out


def isort_key(name: str) -> tuple[int, str]:
    """isort's (and ruff's) order inside one import: constants, then classes, then the rest."""
    return (0 if name.isupper() else 1 if name[0].isupper() else 2, name.lower())


def import_line(module: str, names: list[str], width: int = 100) -> str:
    """`from <module> import <names>` on one line, or one name per line when it is too long."""
    line = f"from {module} import {', '.join(names)}\n"
    if len(line) <= width + 1:
        return line
    return f"from {module} import (\n" + "".join(f"    {n},\n" for n in names) + ")\n"


def missing_lib_imports(text: str, lib: dict[str, str]) -> list[str]:
    """Names of owpp.lib that `text` uses but never binds or imports: what it is missing to
    import, written the way bundles used to work, with the libraries simply above the file."""
    return sorted((n for n in unbound(text) if n in lib), key=isort_key)


def add_lib_imports(text: str, lib: dict[str, str]) -> str:
    """`text` with a `from owpp.lib import ...` for the library names it uses without importing,
    after its other top-level imports (ahead of `from shared import`). Unchanged if none."""
    names = missing_lib_imports(text, lib)
    return _add_imports(text, [import_line(LIB, names)]) if names else text


def _group(module: str) -> int:
    root = module.split(".")[0]
    return 0 if root in sys.stdlib_module_names else 1


def _render(imports: list[_Import]) -> list[str]:
    """Import statements for `imports`, standard library first, then third-party, one blank line
    between the groups; `from` imports of one module are one statement."""
    blocks: list[str] = []
    for group in (0, 1):
        plain = sorted(
            {i for i in imports if i.name is None and _group(i.module) == group},
            key=lambda i: i.module,
        )
        lines = [f"import {i.module}" + (f" as {i.alias}" if i.alias else "") + "\n" for i in plain]
        by_module: dict[str, list[str]] = {}
        for i in imports:
            if i.name is not None and _group(i.module) == group:
                by_module.setdefault(i.module, []).append(
                    i.name + (f" as {i.alias}" if i.alias else "")
                )
        for module in sorted(by_module):
            lines.append(import_line(module, sorted(set(by_module[module]), key=isort_key)))
        if lines:
            blocks.append("".join(lines))
    return blocks


def _header_end(lines: list[str], tree: ast.Module) -> int:
    """The line after the module's docstring, or after its leading `#` comments: where its first
    statement may go (a `from __future__` line must be first)."""
    first = tree.body[0] if tree.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        return first.end_lineno or first.lineno
    at = 0
    while at < len(lines) and lines[at].startswith("#"):
        at += 1
    return at


def _insert_point(lines: list[str], tree: ast.Module) -> int:
    """Where new imports go: after the header and the leading imports, but ahead of a
    `from shared import`, which comes last (the plugin's own code)."""
    at = _header_end(lines, tree)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == SHARED and not node.level:
            return node.lineno - 1
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            at = node.end_lineno or node.lineno
        elif not (node is tree.body[0] and isinstance(node, ast.Expr)):
            break
    return at


def _add_imports(text: str, blocks: list[str]) -> str:
    """`text` with the import `blocks` (each a group of statements) at the insert point, a blank
    line between groups and around them: two before a top-level def or class, as PEP 8 wants."""
    if not blocks:
        return text
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    at = _insert_point(lines, tree)
    before = "\n" if at and lines[at - 1].strip() else ""
    rest = lines[at:]
    while rest and not rest[0].strip():
        rest.pop(0)
    top_level = rest and rest[0].startswith(("def ", "async def ", "class ", "@"))
    gap = "\n\n" if top_level else "\n" if rest else ""
    return "".join(lines[:at]) + before + "\n".join(blocks) + gap + "".join(rest)


def _add_future(text: str, features: set[str]) -> str:
    """`text` with `from __future__ import X` for each feature in `features` it lacks, first."""
    tree = ast.parse(text)
    missing = sorted(features - _futures(tree))
    if not missing:
        return text
    lines = text.splitlines(keepends=True)
    at = _header_end(lines, tree)
    line = f"from __future__ import {', '.join(missing)}\n"
    before = "\n" if at and lines[at - 1].strip() else ""
    after = "\n" if at < len(lines) and lines[at].strip() else ""
    return "".join(lines[:at]) + before + line + after + "".join(lines[at:])


def _drop_unused(text: str, unused: set[str]) -> str:
    """`text` without the top-level import aliases that bind a name in `unused`."""
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    edits: list[tuple[int, int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        from_import = isinstance(node, ast.ImportFrom)
        keep = [a for a in node.names if bound_name(a, from_import) not in unused]
        if len(keep) == len(node.names):
            continue
        new = ""
        if keep:
            node.names = keep
            new = ast.unparse(node) + "\n"
        edits.append((node.lineno, node.end_lineno or node.lineno, new))
    for start, end, new in sorted(edits, reverse=True):
        lines[start - 1 : end] = [new] if new else []
        if not new:  # the blank lines on either side of what went meet: keep one run
            at = start - 1
            while 0 < at < len(lines) and not lines[at].strip() and not lines[at - 1].strip():
                del lines[at]
    return "".join(lines)


def _futures(tree: ast.Module) -> set[str]:
    return {
        a.name
        for n in tree.body
        if isinstance(n, ast.ImportFrom) and n.module == "__future__"
        for a in n.names
    }


def upgrade(folder: Path, skip: set[str] | frozenset[str] = frozenset()) -> Upgrade:
    """The 0.3 -> 0.5 rewrite of the plugin's code in `folder`, leaving the files in `skip`."""
    texts = {
        n: (folder / n).read_text(encoding="utf-8")
        for n in FILES
        if (folder / n).exists() and n not in skip
    }
    original = dict(texts)
    result = Upgrade()
    texts = {n: re.sub(r"\b_plugin_ensure\b", "plugin_ensure", t) for n, t in texts.items()}
    lib = exports()

    shared_tree = ast.parse(texts["shared.py"]) if "shared.py" in texts else None
    shared_defs = defined(shared_tree, imports=False) if shared_tree else {}
    shared_imports = _imports(shared_tree) if shared_tree else {}
    copied: set[str] = set()

    for name in FILES:
        if name not in texts:
            continue
        needed: list[_Import] = []
        from_shared: list[str] = []
        from_lib: list[str] = []
        for used, line in sorted(unbound(texts[name]).items(), key=lambda item: item[1]):
            if used in BUILTINS:
                continue
            if name != "shared.py" and used in shared_defs:
                from_shared.append(used)
            elif name != "shared.py" and used in shared_imports:
                needed.append(shared_imports[used])
                copied.add(used)
            elif used in lib:
                from_lib.append(used)
            else:
                result.notes.append(
                    f"{name}:{line}: {used} is not defined anywhere owpp knows of: import it"
                )
        blocks = _render(needed)
        if from_lib:
            blocks.append(import_line(LIB, sorted(from_lib, key=isort_key)))
        if from_shared:
            blocks.append(import_line(SHARED, sorted(from_shared, key=isort_key)))
        texts[name] = _add_imports(texts[name], blocks)

    if "shared.py" in texts and copied:
        uses = set(unbound(_without_imports(texts["shared.py"])))
        texts["shared.py"] = _drop_unused(texts["shared.py"], copied - uses)

    if "shared.py" in texts:  # its __future__ lines apply to the bundles it is in
        features = set().union(*(_futures(ast.parse(t)) for t in texts.values()))
        texts = {n: _add_future(t, features) for n, t in texts.items()}

    result.files = {n: t for n, t in texts.items() if t != original[n]}
    return result


def _without_imports(text: str) -> str:
    """`text` with its top-level imports blanked out, so their names count as unbound when used."""
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for i in range(node.lineno - 1, node.end_lineno or node.lineno):
                lines[i] = "\n"
    return "".join(lines)
