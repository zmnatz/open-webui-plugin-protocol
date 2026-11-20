"""owpp: the Open-WebUI plugin protocol CLI (docs/tooling.md).

  owpp list                          plugins with their function type
  owpp check [id ...]                bundle, compile, report undefined names
  owpp bundle <id> [out.py]          print (or write) the exact code that would be deployed
  owpp deploy [--only id,id] [--dry-run] [--force-prune] [--managed-by marker]
  owpp test [id ...] [--upstream] [-- pytest args]  run each plugin's tests/ against a mock Open-WebUI
  owpp pull [id ...] [--dry-run] [--bump part]   move plugins taken from git to their latest commit
  owpp version [id] [patch|minor|major|X.Y.Z] [--tool | --skill name] [-m text]
  owpp migrate [id ...] [--dry-run]  bring plugin.yaml to the current protocol version
  owpp create [id]                   a wizard: asks what the plugin is, then writes it
  owpp init <id> [--type event|filter|action|pipe]   scaffold a plugin folder

Every command takes --dir <plugins folder> (default: $OWPP_PLUGINS_DIR, else ./plugins).
"""

from __future__ import annotations

import argparse
import ast
import builtins
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from . import __version__
from .bundle import FunctionFile, env_references, load_function_files, runtime_data
from .create import CLASS, PluginSpec, spec_from_data, write_plugin
from .deploy import options_from_env, run_deploy
from .errors import OwppError
from .lint import lint_notes, lint_plugin
from .manifest import parse_yaml, read_manifest, read_text
from .protocol import report as protocol_report
from .sources import plugin_folders
from .upstream import fetch_all, is_plugin_source, root_of
from .versioning import bump, changelog_problem, check_since, version_of, versions_of

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
    tools = runtime_data(fn.content)["tools"]
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
    return load_function_files(directory, fetch_all(directory))


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
        if fn.file.endswith("/"):  # a plugin folder
            name = fn.file.rstrip("/")
            root = fn.root or directory / name
            problem = changelog_problem(root, version_of(fn.content))
            if problem:
                print(f"warn  {fn.id}/{problem}")
                warnings += 1
            warn, note = protocol_report(
                f"{name}/plugin.yaml", read_manifest(directory / name).get("protocol")
            )
            if warn:
                print(f"warn  {warn}")
                warnings += 1
            if note:
                print(f"note  {note}")
            for var, default in env_references(root):
                shown = (
                    "no default"
                    if default is None
                    else f"default {default}"
                    if default
                    else "default empty"
                )
                print(f"env   {var} ({shown})")
    if args.since:
        chosen = [f for f in all_functions if not args.ids or f.id in args.ids]
        for finding in check_since(directory, args.since, args.ids, new_files=chosen):
            print(f"FAIL  {finding}")
            bad += 1
    if warnings:
        print(f"{warnings} warning(s){'; failing because of --strict' if args.strict else ''}")
    return 1 if bad or (args.strict and warnings) else 0


def _cmd_version(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    if args.how is None:  # show
        if args.tool or args.skill or args.message:
            print("--tool, --skill and -m go with a new version: patch, minor, major or X.Y.Z")
            return 1
        ids = (
            [args.id]
            if args.id
            else [f.name for f in plugin_folders(directory)]
            + sorted(p.stem for p in directory.glob("*.py"))
        )
        for plugin_id in ids:
            for i, (what, version) in enumerate(versions_of(directory, plugin_id)):
                name = plugin_id if i == 0 else f"  {what}"
                print(f"{name:<28}{version or '(no version)'}")
        return 0
    if not args.id:
        print("say which plugin: owpp version <id> patch|minor|major|X.Y.Z")
        return 1
    for b in bump(directory, args.id, args.how, args.tool, args.skill, args.message or ""):
        print(f"{b.what}: {b.old or '(no version)'} -> {b.new} ({b.file})")
    changelog = directory / args.id / "CHANGELOG.md"
    if not (args.tool or args.skill or args.message) and changelog.exists():
        print(f"now say what changed, in the new entry of {changelog}")
    return 0


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
        latest=args.latest,
        force=args.force,
        ca_cert=args.ca_cert,
        client_cert=args.client_cert,
        client_key=args.client_key,
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
    upstream_tested: set[str] = set()
    whole = [f for f in chosen if is_plugin_source(read_manifest(f))]
    if args.upstream and whole:
        remote = fetch_all(directory)
        for f in whole:
            tests = root_of(f, remote) / "tests"
            if tests.is_dir():
                paths.append(str(tests))
                upstream_tested.add(f.name)
                print(
                    f"note  {f.name}: running the upstream plugin's tests, from the pinned commit"
                )
        # This runs code from another repository: leave it nothing to sign in to an instance with.
        for name in [n for n in os.environ if n.startswith("OPEN_WEBUI_")]:
            del os.environ[name]
    elif whole:
        print(
            "note  taken whole from git, upstream tests not run (`owpp test --upstream` runs "
            f"them): {', '.join(f.name for f in whole)}"
        )
    untested = [
        f.name
        for f in chosen
        if not (f / "tests").is_dir() and f.name not in upstream_tested and f not in whole
    ]
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


def _cmd_migrate(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    from .migrate import migrate

    if not directory.exists():
        raise OwppError(f"no plugins folder at {directory} (pass --dir, or set OWPP_PLUGINS_DIR)")
    return migrate(directory, args.ids, dry_run=args.dry_run)


def _cmd_pull(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    from .pull import pull

    if not directory.exists():
        raise OwppError(f"no plugins folder at {directory} (pass --dir, or set OWPP_PLUGINS_DIR)")
    return pull(directory, args.ids, dry_run=args.dry_run, bump_by=args.bump)


def _cmd_create(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    from .wizard import run_wizard

    def check(folder: Path, plugin_id: str) -> int:
        print()
        return main(["check", plugin_id, "--strict", "--dir", str(folder)], env)

    if args.spec:  # no questions: the plugin described in a file (for scripts and agents)
        text = sys.stdin.read() if args.spec == "-" else read_text(args.spec)
        try:
            data = parse_yaml(text)
        except yaml.YAMLError as e:
            raise OwppError(f"{args.spec}: not valid YAML or JSON ({e})") from e
        folder = write_plugin(directory, spec_from_data(data, args.id or ""))
        print(f"created {folder}")
        return check(directory, folder.name)
    return run_wizard(directory, args.id or "", check=check)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="owpp",
        description="Write, test and deploy Open-WebUI plugins from a git repository.",
        epilog="deploy needs OPEN_WEBUI_URL, and signs in with OPEN_WEBUI_API_KEY, "
        "OPEN_WEBUI_USERNAME and OPEN_WEBUI_PASSWORD, OPEN_WEBUI_OIDC_TOKEN, or nothing. "
        "Docs: docs/tooling.md#signing-in",
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
        help="fail on warnings too (valves with no description, poorly described tools, "
        "a CHANGELOG.md with no entry for the version)",
    )
    check.add_argument(
        "--since",
        metavar="ref",
        help="also fail when a plugin changed since this git ref (e.g. origin/main) but its "
        "version did not",
    )
    bundle = add("bundle", _cmd_bundle, "print (or write) the code that would be deployed")
    bundle.add_argument("id")
    bundle.add_argument("out", nargs="?", metavar="out.py")
    deploy = add("deploy", _cmd_deploy, "deploy the plugins to an Open-WebUI instance")
    deploy.add_argument("--only", metavar="id,id", help="deploy just these (no pruning)")
    deploy.add_argument(
        "--ca-cert",
        metavar="PEM",
        help="a PEM file of CA certificates to trust besides the system's (default "
        "$OPEN_WEBUI_CA_CERT)",
    )
    deploy.add_argument(
        "--client-cert",
        metavar="PEM",
        help="a client certificate to present, for mutual TLS (default $OPEN_WEBUI_CLIENT_CERT)",
    )
    deploy.add_argument(
        "--client-key",
        metavar="PEM",
        help="its private key, when not in the same file (default $OPEN_WEBUI_CLIENT_KEY)",
    )
    deploy.add_argument(
        "--dry-run", action="store_true", help="list what would change, with versions"
    )
    deploy.add_argument(
        "--force",
        action="store_true",
        help="deploy even where the instance runs a newer version (a downgrade)",
    )
    deploy.add_argument(
        "--latest",
        action="store_true",
        help="with --dry-run: at the latest commit each git-sourced plugin tracks (owpp pull)",
    )
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
    test.add_argument(
        "--upstream",
        action="store_true",
        help="also run the tests of plugins taken whole from git, from the pinned commit "
        "(this runs their code; OPEN_WEBUI_* variables are removed first)",
    )
    migrate = add("migrate", _cmd_migrate, "bring plugin.yaml to the current protocol version")
    migrate.add_argument("ids", nargs="*", metavar="id", help="plugins to migrate (default: all)")
    migrate.add_argument(
        "--dry-run", action="store_true", help="say what would change; write nothing"
    )
    pull = add("pull", _cmd_pull, "move plugins taken from git to the latest commit they track")
    pull.add_argument("ids", nargs="*", metavar="id", help="plugins to pull (default: all)")
    pull.add_argument("--dry-run", action="store_true", help="say what would move; write nothing")
    pull.add_argument(
        "--bump",
        choices=["patch", "minor", "major", "none"],
        default="patch",
        help="bump a moved plugin's version, with a CHANGELOG.md entry (default patch)",
    )
    version = add(
        "version", _cmd_version, "show the versions of the plugins, or give one a new version"
    )
    version.add_argument("id", nargs="?", help="the plugin (default: every plugin, shown)")
    version.add_argument(
        "how", nargs="?", help="the new version: patch, minor, major or X.Y.Z (default: show)"
    )
    version.add_argument("--tool", action="store_true", help="the tool's version")
    version.add_argument("--skill", metavar="name", help="that skill's version")
    version.add_argument(
        "-m", "--message", help="the CHANGELOG.md entry (for the plugin's own version)"
    )
    create = add("create", _cmd_create, "create a plugin, answering a few questions (a wizard)")
    create.add_argument("id", nargs="?", help="the plugin id (asked if left out)")
    create.add_argument(
        "--spec",
        metavar="FILE",
        help="ask nothing: create the plugin a YAML or JSON file describes (- reads stdin)",
    )
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
