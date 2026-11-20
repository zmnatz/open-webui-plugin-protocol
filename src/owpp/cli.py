"""owpp: the Open-WebUI plugin protocol CLI (docs/tooling.md).

  owpp list                          plugins with their function type
  owpp check [id ...]                bundle, compile, report undefined names
  owpp bundle <id> [out.py]          print (or write) the exact code that would be deployed
  owpp deploy [--only id,id] [--dry-run] [--force-prune] [--managed-by marker]
  owpp test [id ...] [-- pytest args]  run each plugin's tests/ against a mock Open-WebUI
  owpp sync [id ...] [--dry-run]     move plugins taken from git to their latest commit
  owpp create [id]                   a wizard: asks what the plugin is, then writes it
  owpp init <id> [--type event|filter|action|pipe]   scaffold a plugin folder

Every command takes --dir <plugins folder> (default: $OWPP_PLUGINS_DIR, else ./plugins).
"""

from __future__ import annotations

import argparse
import ast
import builtins
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from . import __version__
from .bundle import FunctionFile, env_references, load_function_files
from .create import CLASS, PluginSpec, write_plugin
from .deploy import options_from_env, run_deploy
from .errors import OwppError
from .lint import lint_notes, lint_plugin
from .sources import fetch_sources, plugin_folders, source_keys

# ---- check --------------------------------------------------------------------


def _globals_guard(n: ast.AST) -> bool:
    """`"name" in globals()`: code that uses `name` only when another library defined it."""
    return (
        isinstance(n, ast.Compare)
        and isinstance(n.left, ast.Constant)
        and isinstance(n.left.value, str)
        and len(n.ops) == 1
        and isinstance(n.ops[0], ast.In)
        and isinstance(n.comparators[0], ast.Call)
        and isinstance(n.comparators[0].func, ast.Name)
        and n.comparators[0].func.id == "globals"
    )


def undefined_names(tree: ast.AST) -> list[str]:
    """Names a bundle uses without defining or importing them (a typo, or a library a
    plugin forgot to include)."""
    defined = set(dir(builtins))
    loaded = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(n.name)
        elif isinstance(n, ast.Name):
            if isinstance(n.ctx, (ast.Store, ast.Del)):
                defined.add(n.id)
            else:
                loaded.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                defined.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.arg):
            defined.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)
        elif _globals_guard(n):  # `if "name" in globals(): name()`, an optional library's name
            defined.add(n.left.value)
    return sorted(loaded - defined)


def check_bundle(code: str, name: str = "bundle.py") -> str | None:
    """Compile `code` and list undefined names. None when it is fine, else the problem."""
    try:
        tree = ast.parse(code, filename=name)
        compile(tree, name, "exec")
    except (SyntaxError, ValueError) as e:
        detail = f"{e.msg} (line {e.lineno})" if isinstance(e, SyntaxError) else str(e)
        return f"does not compile: {type(e).__name__}: {detail}"
    names = undefined_names(tree)
    return f"undefined names: {', '.join(names)}" if names else None


def bundle_parts(fn: FunctionFile) -> list[tuple[str, str]]:
    """The function bundle, then each tool bundle the runtime embeds for it."""
    m = re.search(r'_PLUGIN = _json\.loads\((".*")\)\n', fn.content)
    tools = json.loads(json.loads(m.group(1))).get("tools", []) if m else []
    return [(fn.id, fn.content)] + [
        (f"tool {t['id']}", t["content"]) for t in tools if not t.get("self")
    ]


# ---- init ---------------------------------------------------------------------


def scaffold(directory: Path | str, plugin_id: str, type: str = "event") -> Path:
    """`owpp init`: the smallest plugin of a type (what `owpp create` makes when every answer is
    the default)."""
    if type not in CLASS:
        raise OwppError(f"--type must be one of {', '.join(CLASS)}")
    return write_plugin(directory, PluginSpec(id=plugin_id, type=type))


# ---- commands -----------------------------------------------------------------


def _load(directory: Path) -> list[FunctionFile]:
    if not directory.exists():
        raise OwppError(f"no plugins folder at {directory} (pass --dir, or set OWPP_PLUGINS_DIR)")
    return load_function_files(directory, fetch_sources(source_keys(directory)))


def _cmd_list(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    for f in _load(directory):
        print(f"{f.id:<24}{f.type}{' (global)' if f.want_global else ''}")
    return 0


def _cmd_check(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    all_functions = _load(directory)
    missing = [i for i in args.ids if not any(f.id == i for f in all_functions)]
    if missing:
        print(f"no plugin {', '.join(missing)} in {directory}", file=sys.stderr)
        return 1
    bad = warnings = 0
    for fn in all_functions:
        if args.ids and fn.id not in args.ids:
            continue
        for name, code in bundle_parts(fn):
            problem = check_bundle(code, f"{fn.id}.py")
            print(f"FAIL  {name}: {problem}" if problem else f"ok    {name} ({len(code)} chars)")
            bad += bool(problem)
        for finding in lint_plugin(directory / fn.file.rstrip("/"), fn.file.rstrip("/")):
            print(f"warn  {finding}")
            warnings += 1
        for finding in lint_notes(directory / fn.file.rstrip("/"), fn.file.rstrip("/")):
            print(f"note  {finding}")
        if fn.file.endswith("/"):  # a plugin folder: say which environment variables it reads
            for var, default in env_references(directory / fn.id):
                shown = (
                    "no default"
                    if default is None
                    else f"default {default}"
                    if default
                    else "default empty"
                )
                print(f"env   {var} ({shown})")
    if warnings:
        print(f"{warnings} warning(s){'; failing because of --strict' if args.strict else ''}")
    return 1 if bad or (args.strict and warnings) else 0


def _cmd_bundle(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    fn = next((f for f in _load(directory) if f.id == args.id), None)
    if fn is None:
        print(f'no plugin "{args.id}" in {directory}', file=sys.stderr)
        return 1
    data = fn.content.encode("utf-8")
    if args.out:
        Path(args.out).write_bytes(data)
    else:
        sys.stdout.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    return 0


def _cmd_deploy(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    opts = options_from_env(
        env,
        dir=directory,
        only=args.only,
        dry_run=args.dry_run,
        force_prune=args.force_prune,
        managed_by=args.managed_by,
    )
    return run_deploy(opts, env)


def _cmd_test(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    if not directory.exists():
        raise OwppError(f"no plugins folder at {directory} (pass --dir, or set OWPP_PLUGINS_DIR)")
    try:
        import pytest  # noqa: F401

        import owpp.testing.mock  # noqa: F401  (its imports: FastAPI, SQLAlchemy, ...)
    except ImportError as error:
        print(
            f"error: owpp test needs {error.name or 'pytest'}: run it as "
            "`uvx --from 'owpp[test]' owpp test`, or `pip install 'owpp[test]'`",
            file=sys.stderr,
        )
        return 1
    import pytest

    folders = {f.name: f for f in plugin_folders(directory)}
    missing = [i for i in args.ids if i not in folders]
    if missing:
        print(f"no plugin {', '.join(missing)} in {directory}", file=sys.stderr)
        return 1
    chosen = [folders[i] for i in args.ids] if args.ids else list(folders.values())
    paths = [str(f / "tests") for f in chosen if (f / "tests").is_dir()]
    untested = [f.name for f in chosen if not (f / "tests").is_dir()]
    if untested:
        print(f"note  no tests/ folder: {', '.join(untested)}")
    if not paths:
        print("no plugin has a tests/ folder: `owpp init` makes one, see docs/testing.md")
        return 1 if args.ids else 0
    # importlib: every plugin may have its own tests/test_function.py without a name clash.
    # owpp itself is already imported (this command), so pytest cannot rewrite its asserts; say nothing.
    pytest_args = [
        *paths,
        "--import-mode=importlib",
        "-W",
        "ignore::pytest.PytestAssertRewriteWarning",
        *args.pytest_args,
    ]
    if env.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD"):
        pytest_args += ["-p", "owpp.testing.pytest_plugin"]
    return int(pytest.main(pytest_args))


def _cmd_init(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    print(f"created {scaffold(directory, args.id, args.type)}")
    return 0


def _cmd_sync(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    from .sync import sync

    if not directory.exists():
        raise OwppError(f"no plugins folder at {directory} (pass --dir, or set OWPP_PLUGINS_DIR)")
    return sync(directory, args.ids, dry_run=args.dry_run)


def _cmd_create(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    from .wizard import run_wizard

    def check(folder: Path, plugin_id: str) -> int:
        print()
        return main(["check", plugin_id, "--strict", "--dir", str(folder)], env)

    return run_wizard(directory, args.id or "", check=check)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="owpp",
        description="Write, test and deploy Open-WebUI plugins from a git repository.",
        epilog="deploy needs OPEN_WEBUI_URL and OPEN_WEBUI_API_KEY. Docs: docs/README.md",
    )
    parser.add_argument("--version", action="version", version=f"owpp {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dir", metavar="FOLDER", help="plugins folder (default $OWPP_PLUGINS_DIR, else ./plugins)"
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    def add(name: str, handler, help: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, parents=[common], help=help, description=help)
        p.set_defaults(handler=handler)
        return p

    add("list", _cmd_list, "plugins with their function type")
    check = add("check", _cmd_check, "bundle, compile, report undefined names")
    check.add_argument("ids", nargs="*", metavar="id", help="plugins to check (default: all)")
    check.add_argument(
        "--strict",
        action="store_true",
        help="fail on warnings too (valves with no description, poorly described tools)",
    )
    bundle = add("bundle", _cmd_bundle, "print (or write) the code that would be deployed")
    bundle.add_argument("id")
    bundle.add_argument("out", nargs="?", metavar="out.py")
    deploy = add("deploy", _cmd_deploy, "deploy the plugins to an Open-WebUI instance")
    deploy.add_argument("--only", metavar="id,id", help="deploy just these (no pruning)")
    deploy.add_argument("--dry-run", action="store_true", help="list what would change")
    deploy.add_argument(
        "--force-prune",
        action="store_true",
        help="allow deleting over half of the managed functions",
    )
    deploy.add_argument(
        "--managed-by", metavar="marker", help="ownership marker (default $OWPP_MANAGED_BY)"
    )
    test = add("test", _cmd_test, "run each plugin's tests/ against a mock Open-WebUI")
    test.add_argument("ids", nargs="*", metavar="id", help="plugins to test (default: all)")
    sync = add("sync", _cmd_sync, "move plugins taken from git to the latest commit they track")
    sync.add_argument("ids", nargs="*", metavar="id", help="plugins to sync (default: all)")
    sync.add_argument("--dry-run", action="store_true", help="say what would move; write nothing")
    create = add("create", _cmd_create, "create a plugin, answering a few questions (a wizard)")
    create.add_argument("id", nargs="?", help="the plugin id (asked if left out)")
    init = add("init", _cmd_init, "scaffold a plugin folder")
    init.add_argument("id")
    init.add_argument("--type", choices=list(CLASS), default="event")
    return parser


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Everything after `--` goes to pytest (owpp test -- -k name -x).
    passthrough = argv[argv.index("--") + 1 :] if "--" in argv else []
    argv = argv[: argv.index("--")] if "--" in argv else argv
    args = parser.parse_args(argv)
    if passthrough and args.command != "test":
        parser.error("only `owpp test` takes arguments after --")
    args.pytest_args = passthrough
    if not getattr(args, "handler", None):
        parser.print_help()
        return 0
    directory = Path(args.dir or env.get("OWPP_PLUGINS_DIR") or "plugins").resolve()
    return args.handler(args, directory, env)


def console_main() -> int:
    try:
        return main()
    except (OwppError, OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
