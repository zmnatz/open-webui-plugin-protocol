"""What `owpp check` says about a plugin's own source (never about code taken from `source:`):
warnings, and notes. A **note** is information a reviewer should see, not a problem: every place a
plugin serves people who are not signed in.

Both are about what the people using the plugin see:

- **Valves.** The admin UI lists each valve with its description, so a valve with none is a
  mystery setting.
- **Tools.** Open-WebUI builds the tool spec the model reads from each method's type hints and
  its docstring's `:param name:` lines, so a method without them gives the model a poor spec.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .manifest import read_manifest, read_text

SOURCE_FILES = ("function.py", "tool.py", "shared.py")


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.message}"


def _is_field(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == "Field")
        or (isinstance(node.func, ast.Attribute) and node.func.attr == "Field")
    )


def _has_description(value: ast.expr | None) -> bool:
    """`Field(..., description=<anything non-empty>)`. A plain default has no description."""
    if value is None or not _is_field(value):
        return False
    for keyword in value.keywords:
        if keyword.arg == "description":
            const = keyword.value
            return not (isinstance(const, ast.Constant) and not str(const.value).strip())
    return False


def _injected(name: str) -> bool:
    """`__user__`, `__metadata__`, ...: Open-WebUI fills these in; the model never sees them."""
    return name.startswith("__") and name.endswith("__")


def _lint_valves(cls: ast.ClassDef, file: str) -> list[Finding]:
    return [
        Finding(
            file, node.lineno, f"valve {node.target.id} has no description: the admin UI shows it"
        )
        for node in cls.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and not node.target.id.startswith("_")
        and not _has_description(node.value)
    ]


def _lint_tool_method(method: ast.FunctionDef | ast.AsyncFunctionDef, file: str) -> list[Finding]:
    docstring = ast.get_docstring(method)
    if not docstring:
        return [
            Finding(
                file,
                method.lineno,
                f"tool method {method.name}() has no docstring: it is what the model reads",
            )
        ]
    described = set(re.findall(r":param\s+(\w+)\s*:", docstring))
    findings = []
    args = [*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs]
    for arg in args:
        if arg.arg == "self" or _injected(arg.arg):
            continue
        if arg.annotation is None:
            findings.append(
                Finding(
                    file, method.lineno, f"{method.name}(): parameter {arg.arg} has no type hint"
                )
            )
        if arg.arg not in described:
            findings.append(
                Finding(
                    file,
                    method.lineno,
                    f"{method.name}(): parameter {arg.arg} is not described (`:param {arg.arg}:` in the docstring)",
                )
            )
    return findings


def lint_source(path: Path, shown: str | None = None) -> list[Finding]:
    file = shown or path.name
    try:
        tree = ast.parse(read_text(path))
    except SyntaxError:
        return []  # `owpp check` reports it
    findings: list[Finding] = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        if cls.name in ("Valves", "UserValves"):
            findings += _lint_valves(cls, file)
        elif cls.name == "Tools":
            for method in cls.body:
                if isinstance(
                    method, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and not method.name.startswith("_"):
                    findings += _lint_tool_method(method, file)
    return sorted(findings, key=lambda f: (f.file, f.line))


def _public_mounts(path: Path, file: str) -> list[Finding]:
    """`plugin_mount(..., access="public")`, and mounts whose access is computed (so unknowable)."""
    try:
        tree = ast.parse(read_text(path))
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        if name != "plugin_mount":
            continue
        for keyword in node.keywords:
            if keyword.arg != "access":
                continue
            if isinstance(keyword.value, ast.Constant):
                if keyword.value.value == "public":
                    found.append(
                        Finding(
                            file,
                            node.lineno,
                            'mounts routes that serve people who are not signed in (access="public")',
                        )
                    )
            else:
                found.append(
                    Finding(
                        file,
                        node.lineno,
                        "plugin_mount's access is computed here, so whether it is public cannot be told",
                    )
                )
    return found


def _public_static(folder: Path, shown: str) -> list[Finding]:
    """`static: {access: public}` in plugin.yaml."""
    static = read_manifest(folder).get("static")
    if not (isinstance(static, dict) and static.get("access") == "public"):
        return []
    lines = read_text(folder / "plugin.yaml").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("static:")), 0)
    at = next(
        (
            i
            for i in range(start, len(lines))
            if re.match(r"\s*(static:\s*\{.*)?access:\s*public", lines[i])
            or "access: public" in lines[i]
        ),
        start,
    )
    return [
        Finding(
            f"{shown}/plugin.yaml",
            at + 1,
            "serves its static/ files to people who are not signed in (static: access: public)",
        )
    ]


def lint_notes(path: Path, shown: str) -> list[Finding]:
    """Every place the plugin serves people who are not signed in: a note, not a warning."""
    findings: list[Finding] = []
    if path.is_file():
        return _public_mounts(path, shown)
    if (path / "plugin.yaml").exists():
        findings += _public_static(path, shown)
    for name in SOURCE_FILES:
        if (path / name).exists():
            findings += _public_mounts(path / name, f"{shown}/{name}")
    return sorted(findings, key=lambda f: (f.file, f.line))


def lint_plugin(path: Path, shown: str) -> list[Finding]:
    """Findings for a plugin: a folder (its function.py, tool.py and shared.py) or a loose <id>.py.
    A plugin that takes code from a pinned `source:` is not ours to lint."""
    if path.is_file():
        return lint_source(path, shown)
    if read_manifest(path).get("source"):
        return []
    findings: list[Finding] = []
    for name in SOURCE_FILES:
        if (path / name).exists():
            findings += lint_source(path / name, f"{shown}/{name}")
    return findings
