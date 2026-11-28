"""What `owpp check` finds (docs/commands/check.md): every plugin bundled as the deploy would
bundle it, each bundle compiled and searched for undefined names, then what lint, the changelog,
the protocol version, the environment variables and `--since` say about the plugin.

`check_plugins` yields the findings; the cli prints them.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .bundle import FunctionFile, env_references, load_function_files
from .embedding import runtime_data
from .errors import OwppError
from .flatten import undefined
from .lint import lint_notes, lint_plugin
from .manifest import read_manifest, require_plugins_folder
from .protocol import report as protocol_report
from .sources import Sources
from .versioning import changelog_problem, check_since, version_of

Kind = Literal["ok", "fail", "warn", "note", "env"]


@dataclass(frozen=True)
class Finding:
    """One thing a check says. `ok`: a bundle that compiles with every name defined. `fail`:
    what is wrong with one, or a change without a new version. `warn`: fails a strict check.
    `note`: worth knowing, never a failure. `env`: an environment variable a plugin reads."""

    kind: Kind
    message: str

    def __str__(self) -> str:
        """The line `owpp check` prints."""
        return f"{'FAIL' if self.kind == 'fail' else self.kind:<6}{self.message}"


class UnknownPlugin(OwppError):
    """An id asked for that is not in the plugins folder."""


def warning_count(findings: Iterable[Finding]) -> int:
    return sum(f.kind == "warn" for f in findings)


def failed(findings: Iterable[Finding], strict: bool = False) -> bool:
    """Whether the check fails: on any failure, and when `strict` on any warning."""
    failing = ("fail", "warn") if strict else ("fail",)
    return any(f.kind in failing for f in findings)


def check_bundle(code: str, name: str = "bundle.py") -> str | None:
    """Compile `code` and list undefined names. None when it is fine, else the problem."""
    try:
        tree = ast.parse(code, filename=name)
        compile(tree, name, "exec")
    except (SyntaxError, ValueError) as e:
        detail = f"{e.msg} (line {e.lineno})" if isinstance(e, SyntaxError) else str(e)
        return f"does not compile: {type(e).__name__}: {detail}"
    names = undefined(code)
    return f"undefined names: {', '.join(names)}" if names else None


def bundle_parts(fn: FunctionFile) -> list[tuple[str, str]]:
    """The function bundle, then each tool bundle the runtime embeds for it."""
    tools = runtime_data(fn.content)["tools"]
    return [(fn.id, fn.content)] + [
        (f"tool {t['id']}", t["content"]) for t in tools if not t.get("self")
    ]


def check_plugins(
    directory: Path | str,
    sources: Sources | None = None,
    ids: Sequence[str] = (),
    since: str | None = None,
) -> Iterator[Finding]:
    """The findings for the plugins in `directory` (those in `ids`, else all of them), as they
    are made. `since`, a git ref, adds a failure for each change without a new version. Plugins
    from git are fetched with `sources`; without it, with one that lasts as long as this does."""
    directory = Path(directory)
    require_plugins_folder(directory)
    with Sources() if sources is None else nullcontext(sources) as sources:
        functions = load_function_files(directory, sources)
        known = {fn.id for fn in functions}
        missing = [i for i in ids if i not in known]
        if missing:
            raise UnknownPlugin(f"no plugin {', '.join(missing)} in {directory}")
        chosen = [fn for fn in functions if not ids or fn.id in ids]
        for fn in chosen:
            yield from _check_function(directory, fn, sources)
        if since:
            for found in check_since(directory, since, list(ids), sources, new_files=chosen):
                yield Finding("fail", str(found))


def _check_function(directory: Path, fn: FunctionFile, sources: Sources) -> Iterator[Finding]:
    for part, code in bundle_parts(fn):
        problem = check_bundle(code, f"{fn.id}.py")
        if problem:
            yield Finding("fail", f"{part}: {problem}")
        else:
            yield Finding("ok", f"{part} ({len(code)} chars)")
    name = fn.file.rstrip("/")
    for found in lint_plugin(directory / name, name):
        yield Finding("warn", str(found))
    for found in lint_notes(directory / name, name):
        yield Finding("note", str(found))
    if fn.file.endswith("/"):
        yield from _check_folder(directory / name, fn, sources)


def _check_folder(folder: Path, fn: FunctionFile, sources: Sources) -> Iterator[Finding]:
    """What only a plugin folder has: a changelog, a manifest and the variables it reads."""
    # No root: a plugin taken whole from git, whose upstream copy `sources` holds.
    root = fn.root or sources.resolve(folder).root
    problem = changelog_problem(root, version_of(fn.content))
    if problem:
        yield Finding("warn", f"{fn.id}/{problem}")
    warn, note = protocol_report(
        f"{folder.name}/plugin.yaml", read_manifest(folder).get("protocol")
    )
    if warn:
        yield Finding("warn", warn)
    if note:
        yield Finding("note", note)
    for variable, default in env_references(root):
        shown = (
            "no default"
            if default is None
            else f"default {default}"
            if default
            else "default empty"
        )
        yield Finding("env", f"{variable} ({shown})")
