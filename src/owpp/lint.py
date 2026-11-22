"""What `owpp check` says about a plugin's own source (never about code taken from `source:`):
warnings, and notes. A **note** is information a reviewer should see, not a problem: every place a
plugin serves people who are not signed in.

Both are about what the people using the plugin see:

- **Valves.** The admin UI lists each valve with its description, so a valve with none is a
  mystery setting.
- **Tools.** Open-WebUI builds the tool spec the model reads from each method's type hints and
  its docstring's `:param name:` lines, so a method without them gives the model a poor spec.

And two about the files becoming one module when bundled (docs/bundling.md):

- **A library name defined again.** The plugin's definition replaces the library's.
- **`from __future__` lines that differ.** They move to the top of the bundle, so shared.py's
  apply to function.py and tool.py too, which an editor reading one file cannot know.
"""

from __future__ import annotations

import ast
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .errors import OwppError
from .flatten import defined
from .libraries import exports, wanted
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
    return (
        findings
        + _shadowed_library_names(path, shown)
        + _future_imports(path, shown)
        + _file_tokens(path, shown)
    )


def _file_tokens(path: Path, shown: str) -> list[Finding]:
    """`{{file:NAME}}`, deprecated: text put into the source, where templates/ is Python."""
    findings = []
    for name in SOURCE_FILES:
        if not (path / name).exists():
            continue
        for number, line in enumerate(read_text(path / name).splitlines(), 1):
            for m in re.finditer(r"\{\{file:([A-Za-z0-9_.-]+)\}\}", line):
                findings.append(
                    Finding(
                        f"{shown}/{name}",
                        number,
                        f"{{{{file:{m.group(1)}}}}} is deprecated: move {m.group(1)} into "
                        f'templates/ and read it with plugin_template_text("{m.group(1)}") '
                        "(a tool adds `include: [templates]` under `tool:`)",
                    )
                )
    return findings


def _trees(path: Path) -> dict[str, ast.Module]:
    trees = {}
    for name in SOURCE_FILES:
        if (path / name).exists():
            with suppress(SyntaxError):  # `owpp check` reports it
                trees[name] = ast.parse(read_text(path / name))
    return trees


def _bundle_libraries(path: Path) -> dict[str, set[str]]:
    """The libraries each source file is bundled with: the function's, the tool's, both for
    shared.py. Empty when plugin.yaml names a library that does not exist (`owpp check` says so)."""
    manifest = read_manifest(path)
    held = {
        key
        for key, present in (
            ("static/", (path / "static").is_dir()),
            ("templates/", (path / "templates").is_dir()),
            ("assets/", (path / "assets").is_dir()),
            ("config.yaml", (path / "config.yaml").is_file()),
            ("jobs:", manifest.get("jobs") is not None),
        )
        if present
    }
    tool = manifest.get("tool")
    try:
        function = set(wanted(manifest.get("include"), held, "plugin.yaml"))
        tool = (
            set(wanted(tool.get("include"), set(), "plugin.yaml"))
            if isinstance(tool, dict)
            else set()
        )
    except OwppError:
        return {}
    return {"function.py": function, "tool.py": tool, "shared.py": function | tool}


def _shadowed_library_names(path: Path, shown: str) -> list[Finding]:
    libraries, lib = _bundle_libraries(path), exports()
    findings = []
    for name, tree in _trees(path).items():
        for own, line in defined(tree, imports=False).items():
            if lib.get(own) in libraries.get(name, ()):
                findings.append(
                    Finding(
                        f"{shown}/{name}",
                        line,
                        f"{own} is also the {lib[own]} library's (owpp.lib): bundled, this "
                        "definition replaces it. Rename it",
                    )
                )
    return findings


def _futures(tree: ast.Module) -> set[str]:
    return {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for alias in node.names
    }


def _future_imports(path: Path, shown: str) -> list[Finding]:
    """shared.py goes in front of function.py and of tool.py, and the bundle's `from __future__`
    lines are all of theirs: each of the three should have the same ones."""
    trees = _trees(path)
    if "shared.py" not in trees:
        return []
    findings = []
    for name in ("function.py", "tool.py"):
        if name not in trees:
            continue
        mine, shared = _futures(trees[name]), _futures(trees["shared.py"])
        for feature, missing_in, has in sorted(
            [
                *((f, name, "shared.py") for f in shared - mine),
                *((f, "shared.py", name) for f in mine - shared),
            ]
        ):
            findings.append(
                Finding(
                    f"{shown}/{missing_in}",
                    1,
                    f"has no `from __future__ import {feature}`, which {has} has: bundled, it "
                    "applies here too, so add it to read this file the way it runs",
                )
            )
    return list(dict.fromkeys(findings))
