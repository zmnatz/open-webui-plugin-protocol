"""Type stubs for `open_webui`, written from the mock Open-WebUI (docs/testing/mock.md).

Open-WebUI is not installed to write a plugin, so an editor cannot resolve `open_webui.*`. The
mock stands in for it in tests, and must have every name a plugin uses, so the stubs are what the
mock has: a stub-only package, `open_webui-stubs` (PEP 561), shipped with owpp. It is partial, so
an editor with the real Open-WebUI installed still finds the modules the mock does not have.

    python -m owpp.testing.stubs      # rewrite src/open_webui-stubs from the mock

tests/test_stubs.py checks the stubs are current. An editable install (this repository's own
environment) holds a copy of them: `uv sync --reinstall-package owpp` refreshes it.
"""

from __future__ import annotations

import inspect
import sys
import types
from pathlib import Path

STUBS = Path(__file__).resolve().parents[2] / "open_webui-stubs"
HEADER = "# Generated from the mock Open-WebUI (owpp.testing.stubs): do not edit.\n"
BUILTIN = (str, int, float, bool)


def _parameters(fn, method: bool = False) -> str:
    """The parameters of `fn` typed Any, defaults as `...`. With `method`, it takes `self` first
    (added when `fn` is a plain function stored on an object, which is called bound)."""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return "self, *args: Any, **kwargs: Any" if method else "*args: Any, **kwargs: Any"
    out, kinds = [], inspect.Parameter
    star = False
    for p in signature.parameters.values():
        if p.kind is kinds.KEYWORD_ONLY and not star:
            out.append("*")
            star = True
        if p.kind is kinds.VAR_POSITIONAL:
            out.append(f"*{p.name}: Any")
            star = True
        elif p.kind is kinds.VAR_KEYWORD:
            out.append(f"**{p.name}: Any")
        elif method and not out and p.name in ("self", "cls"):
            out.append(p.name)
        else:
            out.append(f"{p.name}: Any" + (" = ..." if p.default is not p.empty else ""))
    if method and not (out and out[0] in ("self", "cls")):
        out.insert(0, "self")
    return ", ".join(out)


def _def(name: str, fn, indent: str = "", method: bool = False) -> str:
    target = fn.__func__ if isinstance(fn, (staticmethod, classmethod)) else fn
    prefix = "async def" if inspect.iscoroutinefunction(target) else "def"
    params = _parameters(target, method and not isinstance(fn, staticmethod))
    if isinstance(fn, classmethod):
        params = "cls" + params.removeprefix("self")
    decorator = (
        f"{indent}@staticmethod\n"
        if isinstance(fn, staticmethod)
        else f"{indent}@classmethod\n"
        if isinstance(fn, classmethod)
        else ""
    )
    returns = "None" if name == "__init__" else "Any"
    return f"{decorator}{indent}{prefix} {name}({params}) -> {returns}: ...\n"


def _fields(cls) -> list[str]:
    """Attribute names a row or form class has: pydantic fields, SQLAlchemy columns."""
    if hasattr(cls, "model_fields"):
        return list(cls.model_fields)
    table = getattr(cls, "__table__", None)
    if table is not None:
        return [column.name for column in table.columns]
    return []


def _class(name: str, cls) -> str:
    own = {k: v for k, v in vars(cls).items() if not k.startswith("_") or k == "__init__"}
    lines = [f"class {name}:\n"]
    for field in _fields(cls):
        lines.append(f"    {field}: Any\n")
    for attr, value in own.items():
        if isinstance(value, (staticmethod, classmethod)) or inspect.isfunction(value):
            lines.append(_def(attr, value, "    ", method=True))
        elif attr not in _fields(cls) and not isinstance(value, (property, type)):
            lines.append(f"    {attr}: Any\n")
    if "__init__" not in own:
        lines.append("    def __init__(self, *args: Any, **kwargs: Any) -> None: ...\n")
    # Rows and forms carry more than they declare (Record is a SimpleNamespace).
    lines.append("    def __getattr__(self, name: str) -> Any: ...\n")
    return "".join(lines)


def _value(name: str, value) -> str:
    if isinstance(value, BUILTIN):
        return f"{name}: {type(value).__name__}\n"
    if isinstance(value, list):
        return f"{name}: list[Any]\n"
    if isinstance(value, dict):
        return f"{name}: dict[str, Any]\n"
    return f"{name}: Any\n"


def render_module(module: types.ModuleType) -> str:
    """The stub of one of the mock's modules."""
    body: list[str] = []
    for name, value in sorted(vars(module).items()):
        if name.startswith("__") or isinstance(value, types.ModuleType):
            continue
        if isinstance(value, type):
            body.append(_class(name, value))
        elif inspect.isfunction(value):
            body.append(_def(name, value))
        elif isinstance(value, types.SimpleNamespace):  # socket.main's sio: emit()
            members = "".join(
                _def(k, v, "    ", method=True) for k, v in sorted(vars(value).items())
            )
            body.append(f"class _{name.title()}:\n{members}\n{name}: _{name.title()}\n")
        elif type(value).__name__ == "FastAPI":
            body.append(f"{name}: FastAPI\n")
        else:
            body.append(_value(name, value))
    imports = "from typing import Any\n"
    if any(": FastAPI" in b for b in body):
        imports += "\nfrom fastapi import FastAPI\n"
    return HEADER + "\n" + imports + ("\n\n" + "\n\n".join(body) if body else "")


def render() -> dict[str, str]:
    """{path inside open_webui-stubs: text}, from a mock that is not installed."""
    from .mock import MockOpenWebUI

    mock = MockOpenWebUI()
    try:
        modules = mock._modules()
    finally:
        mock.close()
    packages = {name.rpartition(".")[0] for name in modules if "." in name}
    files = {"py.typed": "partial\n"}
    for name, module in modules.items():
        parts = name.split(".")[1:]
        path = "/".join(
            [*parts, "__init__.pyi"] if name in packages else [*parts[:-1], f"{parts[-1]}.pyi"]
        )
        files[path] = render_module(module)
    return dict(sorted(files.items()))


def write(root: Path = STUBS) -> list[Path]:
    """Rewrite the stubs under `root`, removing stale ones; the files written."""
    files = render()
    for old in [p for p in root.rglob("*") if p.is_file()] if root.exists() else []:
        if old.relative_to(root).as_posix() not in files:
            old.unlink()
    written = []
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in write():
        print(path.relative_to(STUBS.parent))
    sys.exit(0)
