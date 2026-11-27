"""owpp: the Open-WebUI plugin protocol CLI (docs/tooling.md, and a page per command in docs/commands/).

  owpp list                          plugins with their function type
  owpp check [id ...]                bundle, compile, report undefined names
  owpp bundle <id> [out.py]          print (or write) the exact code that would be deployed
  owpp build [id ...] [--out dist] [--latest]   bundle the plugins into a folder to deploy elsewhere
  owpp deploy [--from dist] [--only id,id] [--dry-run [--latest]] [--force] [--no-prune | --force-prune] [--managed-by marker]
  owpp test [id ...] [--upstream] [-- pytest args]  run each plugin's tests/ against the real Open-WebUI, in process
  owpp pull [id ...] [--dry-run] [--bump part]   move plugins taken from git to their latest commit
  owpp version [id] [patch|minor|major|X.Y.Z] [--tool | --skill name] [-m text]
  owpp migrate [id ...] [--dry-run]  bring plugin.yaml to the current protocol version
  owpp create [id]                   a wizard: asks what the plugin is, then writes it
  owpp init <id> [--type event|filter|action|pipe]   scaffold a plugin folder
  owpp live [--up | --keep | --down] [-- pytest args]  the live tests, on a throwaway Open-WebUI (Docker)

Every command takes --dir <plugins folder> (default: $OWPP_PLUGINS_DIR, else ./plugins).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import yaml

from . import __version__
from .bundle import FunctionFile, load_function_files
from .check import UnknownPlugin, check_plugins, failed, warning_count
from .create import CLASS, PluginSpec, spec_from_data, write_plugin
from .deploy import Instance, choices_from_env, instance_from_env, run_deploy
from .errors import OwppError
from .manifest import (
    parse_yaml,
    plugin_folders,
    read_manifest,
    read_text,
    require_plugins_folder,
)
from .sources import Sources, is_plugin_source
from .versioning import bump, versions_of

# ---- init ---------------------------------------------------------------------


def scaffold(directory: Path | str, plugin_id: str, type: str = "event") -> Path:
    """`owpp init`: the smallest plugin of a type (what `owpp create` makes when every answer is
    the default)."""
    if type not in CLASS:
        raise OwppError(f"--type must be one of {', '.join(CLASS)}")
    return write_plugin(directory, PluginSpec(id=plugin_id, type=type))


# ---- commands -----------------------------------------------------------------


def _load(args: argparse.Namespace, directory: Path) -> list[FunctionFile]:
    require_plugins_folder(directory)
    return load_function_files(directory, args.sources)


def _cmd_list(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    for f in _load(args, directory):
        print(f"{f.id:<24}{f.type}{' (global)' if f.want_global else ''}")
    return 0


def _check(
    directory: Path,
    sources: Sources,
    ids: Sequence[str] = (),
    strict: bool = False,
    since: str | None = None,
) -> int:
    """Print what the check finds, as it is found, and return `owpp check`'s exit code."""
    findings = []
    try:
        for finding in check_plugins(directory, sources, ids, since):
            print(finding)
            findings.append(finding)
    except UnknownPlugin as e:
        print(e, file=sys.stderr)
        return 1
    if warnings := warning_count(findings):
        print(f"{warnings} warning(s){'; failing because of --strict' if strict else ''}")
    return int(failed(findings, strict))


def _cmd_check(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    return _check(directory, args.sources, args.ids, args.strict, args.since)


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
    fn = next((f for f in _load(args, directory) if f.id == args.id), None)
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


def _cmd_build(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    from .build import write_build
    from .deploy import build_plugins

    if not directory.exists():
        raise OwppError(f"no plugins folder at {directory} (pass --dir, or set OWPP_PLUGINS_DIR)")
    built = build_plugins(directory, args.sources, args.ids, latest=args.latest)
    for path in write_build(built, args.out):
        print(f"built {path}")
    what = "every plugin" if built.complete else "only " + ", ".join(args.ids)
    at = " at the latest commits (deploys only as a dry run)" if built.latest else ""
    print(f"{len(built.files)} function(s) in {args.out}: {what}{at}")
    return 0


def _instance(args: argparse.Namespace, env: Mapping[str, str]) -> Instance:
    """The instance in the environment, with the command's certificate flags (_tls_flags)."""
    return instance_from_env(
        env, ca_cert=args.ca_cert, client_cert=args.client_cert, client_key=args.client_key
    )


def _cmd_deploy(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    instance = _instance(args, env)
    choices = choices_from_env(
        env,
        dir=directory,
        only=args.only,
        sources=args.sources,
        from_dir=args.from_dir,
        managed_by=args.managed_by,
        dry_run=args.dry_run,
        latest=args.latest,
        force=args.force,
        force_prune=args.force_prune,
        no_prune=args.no_prune,
    )
    return run_deploy(instance, choices, env)


def _cmd_test(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    if args.editor:
        from owpp.testing.wheel import open_webui_dir

        print(open_webui_dir())
        return 0
    if not directory.exists():
        raise OwppError(f"no plugins folder at {directory} (pass --dir, or set OWPP_PLUGINS_DIR)")
    from owpp.testing import pin

    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    command = f"uvx --python {pin.PYTHON} --from 'owpp[test]' owpp test"
    if running != pin.PYTHON:
        print(
            f"error: owpp test runs Open-WebUI v{pin.VERSION}, which runs on Python {pin.PYTHON}, "
            f"not {running}: run it as `{command}`",
            file=sys.stderr,
        )
        return 1
    try:
        import pytest  # noqa: F401
        import socketio  # noqa: F401  (one of Open-WebUI's packages, which the test extra adds)
    except ImportError as error:
        print(
            f"error: owpp test needs {error.name or 'pytest'}: run it as `{command}`, "
            "or `pip install 'owpp[test]'`",
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
        for f in whole:
            tests = args.sources.resolve(f).root / "tests"
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
    return migrate(directory, args.ids, dry_run=args.dry_run, sources=args.sources)


def _cmd_pull(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    from .pull import pull

    if not directory.exists():
        raise OwppError(f"no plugins folder at {directory} (pass --dir, or set OWPP_PLUGINS_DIR)")
    return pull(directory, args.ids, dry_run=args.dry_run, sources=args.sources, bump_by=args.bump)


def _cmd_create(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    from .wizard import run_wizard

    def check(folder: Path, plugin_id: str) -> int:
        print()
        return _check(folder, args.sources, [plugin_id], strict=True)

    if args.spec:  # no questions: the plugin described in a file (for scripts and agents)
        text = sys.stdin.read() if args.spec == "-" else read_text(args.spec)
        try:
            data = parse_yaml(text)
        except yaml.YAMLError as e:
            raise OwppError(f"{args.spec}: not valid YAML or JSON ({e})") from e
        folder = write_plugin(directory, spec_from_data(data, args.id or ""))
        print(f"created {folder}")
        return check(directory, folder.name)
    return run_wizard(directory, args.id or "", check=check, sources=args.sources)


def _cmd_import(args: argparse.Namespace, directory: Path, env: Mapping[str, str]) -> int:
    from .importer import import_file, import_git, import_instance

    if bool(args.what) == bool(args.instance):
        print(
            "say what to import: a git URL, a file, or --instance <id> (one of them)",
            file=sys.stderr,
        )
        return 1
    if args.instance:
        instance = _instance(args, env)
        if not instance.base_url:
            raise OwppError("OPEN_WEBUI_URL is not set: --instance reads the function from it")
        imported = import_instance(directory, instance, args.instance, args.id or "")
    elif Path(args.what).is_dir():
        raise OwppError(
            f"{args.what} is a folder on disk: give the URL of its git repository, so the "
            "code is pinned at a commit, or the file of one function"
        )
    elif Path(args.what).is_file():
        imported = import_file(directory, args.what, args.id or "")
    else:
        imported = import_git(
            directory,
            args.what,
            sources=args.sources,
            plugin_id=args.id or "",
            path=args.path or "",
            name=args.ref or "",
            public=args.public,
        )
    plugin_id = imported.folder.name
    print(f"created {imported.folder}")
    for note in imported.notes:
        print(f"note  {note}")
    print()
    code = _check(directory, args.sources, [plugin_id])
    print(
        f"\nnext: write its tests in {plugin_id}/tests/ and run `owpp test {plugin_id}` "
        "(docs/testing/writing.md)"
    )
    return code


def _tls_flags(parser: argparse.ArgumentParser) -> None:
    """The certificate flags of a command that talks to an instance."""
    parser.add_argument(
        "--ca-cert",
        metavar="PEM",
        help="a PEM file of CA certificates to trust besides the system's (default "
        "$OPEN_WEBUI_CA_CERT)",
    )
    parser.add_argument(
        "--client-cert",
        metavar="PEM",
        help="a client certificate to present, for mutual TLS (default $OPEN_WEBUI_CLIENT_CERT)",
    )
    parser.add_argument(
        "--client-key",
        metavar="PEM",
        help="its private key, when not in the same file (default $OPEN_WEBUI_CLIENT_KEY)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="owpp",
        description="Write, test and deploy Open-WebUI plugins from a git repository.",
        epilog="deploy needs OPEN_WEBUI_URL, and signs in with OPEN_WEBUI_API_KEY, "
        "OPEN_WEBUI_USERNAME and OPEN_WEBUI_PASSWORD, OPEN_WEBUI_OIDC_TOKEN, or nothing. "
        "Docs: docs/commands/deploy.md#signing-in",
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
    build = add("build", _cmd_build, "bundle the plugins into a folder that deploy --from deploys")
    build.add_argument("ids", nargs="*", metavar="id", help="plugins to build (default: all)")
    build.add_argument(
        "--out", default="dist", metavar="FOLDER", help="the folder to write (default ./dist)"
    )
    build.add_argument(
        "--latest",
        action="store_true",
        help="at the latest commit each git-sourced plugin follows (deploys only as a dry run)",
    )
    imp = add(
        "import",
        _cmd_import,
        "make a plugin folder from code that exists: a folder or file in a git repository "
        "(pinned, not copied), a .py file, or a function on Open-WebUI",
    )
    imp.add_argument(
        "what",
        nargs="?",
        metavar="url|file",
        help="a git URL (a GitHub or GitLab page of a folder or file works), or a .py file",
    )
    imp.add_argument(
        "--instance",
        metavar="ID",
        help="import the function with this id from OPEN_WEBUI_URL (signs in as deploy does)",
    )
    imp.add_argument("--id", help="the plugin's id (default: from the file, folder or instance)")
    imp.add_argument("--path", help="with a clone URL: the folder in the repository")
    imp.add_argument(
        "--ref", metavar="BRANCH|TAG", help="with a clone URL: the branch or tag to follow"
    )
    imp.add_argument(
        "--public",
        action="store_true",
        help="give every user the tool and skills it installs (default: admins only)",
    )
    _tls_flags(imp)
    deploy = add("deploy", _cmd_deploy, "deploy the plugins to an Open-WebUI instance")
    deploy.add_argument(
        "--from",
        dest="from_dir",
        metavar="FOLDER",
        help="deploy the build in FOLDER (owpp build) instead of the plugins folder",
    )
    deploy.add_argument(
        "--no-prune",
        action="store_true",
        help="delete nothing: list the functions a full deploy would delete",
    )
    deploy.add_argument("--only", metavar="id,id", help="deploy just these (no pruning)")
    _tls_flags(deploy)
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
        help="with --dry-run: at the latest commit each git-sourced plugin follows (owpp pull)",
    )
    deploy.add_argument(
        "--force-prune",
        action="store_true",
        help="allow deleting over half of the managed functions",
    )
    deploy.add_argument(
        "--managed-by", metavar="marker", help="ownership marker (default $OWPP_MANAGED_BY)"
    )
    test = add(
        "test", _cmd_test, "run each plugin's tests/ against the real Open-WebUI, in process"
    )
    test.add_argument("ids", nargs="*", metavar="id", help="plugins to test (default: all)")
    test.add_argument(
        "--upstream",
        action="store_true",
        help="also run the tests of plugins taken whole from git, from the pinned commit "
        "(this runs their code; OPEN_WEBUI_* variables are removed first)",
    )
    test.add_argument(
        "--editor",
        action="store_true",
        help="print the folder of the Open-WebUI code the tests run, for an editor's search "
        "path (downloads it once), and stop",
    )
    migrate = add("migrate", _cmd_migrate, "bring plugin.yaml to the current protocol version")
    migrate.add_argument("ids", nargs="*", metavar="id", help="plugins to migrate (default: all)")
    migrate.add_argument(
        "--dry-run", action="store_true", help="say what would change; write nothing"
    )
    pull = add("pull", _cmd_pull, "move plugins taken from git to the latest commit they follow")
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
    test.set_defaults(passthrough=True)
    from .live.command import register as add_live  # stdlib only; Docker and Playwright when run

    add_live(add)
    return parser


def parse_command(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """The command line (default: this process's), parsed. Everything after `--` is in
    `pytest_args`, for the commands that pass it to pytest."""
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Everything after `--` goes to pytest (owpp test -- -k name -x).
    passthrough = argv[argv.index("--") + 1 :] if "--" in argv else []
    argv = argv[: argv.index("--")] if "--" in argv else argv
    args = parser.parse_args(argv)
    if passthrough and not getattr(args, "passthrough", False):
        parser.error("only `owpp test` and `owpp live` take arguments after --")
    args.pytest_args = passthrough
    return args


def plugins_dir(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    """The plugins folder a command works on: --dir, else $OWPP_PLUGINS_DIR, else ./plugins."""
    return Path(args.dir or env.get("OWPP_PLUGINS_DIR") or "plugins").resolve()


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    sources: Callable[[], Sources] = Sources,
) -> int:
    """Run one command. `sources` makes what it reads plugin files from git through."""
    env = os.environ if env is None else env
    args = parse_command(argv)
    if not getattr(args, "handler", None):
        build_parser().print_help()
        return 0
    directory = plugins_dir(args, env)
    # One Sources for the command: each file from git is fetched once, and the upstream copies of
    # plugins taken whole from git last until the command (pytest, for `owpp test`) is done.
    with sources() as args.sources:
        return args.handler(args, directory, env)


def console_main() -> int:
    try:
        return main()
    except (OwppError, OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
