"""`owpp migrate`'s 0.3 -> 0.5 step for a plugin's code: give each file the imports it used to
do without (docs/adr/0002-plugin-source-is-python.md).

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

from .flatten import LIB, SHARED, _isort, defined, import_line, unbound
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
    """One name a top-level import binds: `import module [as alias]` or
    `from module import name [as alias]`."""

    module: str
    name: str | None = None  # None for `import module`
    alias: str | None = None

    @property
    def bound(self) -> str:
        if self.alias:
            return self.alias
        return self.name if self.name is not None else self.module.split(".")[0]


def _imports(tree: ast.Module) -> dict[str, _Import]:
    """The names a module's top-level imports bind, other than __future__, shared and owpp."""
    out: dict[str, _Import] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                imp = _Import(a.name, None, a.asname)
                out.setdefault(imp.bound, imp)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            if node.module == "__future__" or node.module.split(".")[0] in (SHARED, "owpp"):
                continue
            for a in node.names:
                if a.name != "*":
                    imp = _Import(node.module, a.name, a.asname)
                    out.setdefault(imp.bound, imp)
    return out


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
            lines.append(import_line(module, sorted(set(by_module[module]), key=_isort)))
        if lines:
            blocks.append("".join(lines))
    return blocks


def _insert_point(lines: list[str], tree: ast.Module) -> int:
    """After the leading docstring, comments and imports: where new imports go."""
    at = 0
    for node in tree.body:
        is_doc = isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (is_doc and node is tree.body[0]):
            at = node.end_lineno or node.lineno
        else:
            break
    if at == 0:
        while at < len(lines) and lines[at].startswith("#"):
            at += 1
    return at


def _add_imports(text: str, blocks: list[str]) -> str:
    if not blocks:
        return text
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    at = _insert_point(lines, tree)
    block = "\n".join(blocks)
    before = "\n" if at and lines[at - 1].strip() else ""
    rest = lines[at:]
    while rest and not rest[0].strip():
        rest.pop(0)
    # Two blank lines before a top-level def or class, as PEP 8 (and ruff) want; one otherwise.
    top_level = rest and rest[0].startswith(("def ", "async def ", "class ", "@"))
    gap = "\n\n" if top_level else "\n" if rest else ""
    return "".join(lines[:at]) + before + block + gap + "".join(rest)


def _add_future(text: str, features: set[str]) -> str:
    """`text` with `from __future__ import X` for each feature in `features` it lacks, first."""
    tree = ast.parse(text)
    have = {
        a.name
        for n in tree.body
        if isinstance(n, ast.ImportFrom) and n.module == "__future__"
        for a in n.names
    }
    missing = sorted(features - have)
    if not missing:
        return text
    lines = text.splitlines(keepends=True)
    first = tree.body[0] if tree.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        at = first.end_lineno or first.lineno
    else:
        at = 0
        while at < len(lines) and lines[at].startswith("#"):
            at += 1
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
        keep = [
            a
            for a in node.names
            if (a.asname or (a.name if isinstance(node, ast.ImportFrom) else a.name.split(".")[0]))
            not in unused
        ]
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


def upgrade(folder: Path) -> Upgrade:
    """The 0.3 -> 0.5 rewrite of the plugin's code in `folder` (nothing for code from git)."""
    texts = {n: (folder / n).read_text(encoding="utf-8") for n in FILES if (folder / n).exists()}
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
            blocks.append(import_line(LIB, sorted(from_lib, key=_isort)))
        if from_shared:
            blocks.append(import_line(SHARED, sorted(from_shared, key=_isort)))
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
