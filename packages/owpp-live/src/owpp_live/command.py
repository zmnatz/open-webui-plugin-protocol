"""`owpp live`: the plugins deployed to a throwaway Open-WebUI (with aimock as its models), and
the repository's live tests run against it (docs/commands/live.md).

owpp-live registers it through owpp's `owpp.commands` entry points: `register(add)` gets owpp's
own function for adding a command, so `--dir` and `-- pytest args` work as for every other.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path

from owpp.cli import LIVE_HELP as HELP
from owpp.cli import main as owpp_main
from owpp.errors import OwppError

from .stack import Stack


def register(add) -> None:
    live = add("live", run_command, HELP)
    live.set_defaults(passthrough=True)
    live.add_argument(
        "--tests",
        metavar="FOLDER",
        default="live",
        help="the live tests, and the compose.yaml and aimock/ beside them (default: ./live)",
    )
    live.add_argument(
        "--compose",
        metavar="FILE",
        help="a compose file layered on owpp's (default: compose.yaml in --tests, if there)",
    )
    live.add_argument(
        "--fixtures",
        metavar="FOLDER",
        help="aimock's fixtures, in place of owpp's (default: aimock/ in --tests, if there)",
    )
    live.add_argument(
        "--port", type=int, default=3000, help="Open-WebUI's port on 127.0.0.1 (default 3000)"
    )
    live.add_argument(
        "--aimock-port", type=int, default=4010, help="aimock's port on 127.0.0.1 (default 4010)"
    )
    when = live.add_mutually_exclusive_group()
    when.add_argument(
        "--up",
        action="store_true",
        help="start it and deploy, run no tests, and leave it running (prints how to reach it)",
    )
    when.add_argument("--keep", action="store_true", help="leave it running after the tests")
    when.add_argument("--down", action="store_true", help="stop a stack left running, and go")


def run_command(
    args: argparse.Namespace, directory: Path, env: Mapping[str, str], **stack_options
) -> int:
    tests = Path(args.tests)
    stack = Stack.find(
        tests,
        Path(args.compose) if args.compose else None,
        Path(args.fixtures) if args.fixtures else None,
        port=args.port,
        aimock_port=args.aimock_port,
        env=env,
        **stack_options,
    )
    if args.down:
        stack.down()
        print("stopped")
        return 0
    if not args.up and not stack.tests.is_dir():
        raise OwppError(
            f"no live tests at {stack.tests}: write them there (docs/testing/live.md), or "
            "pass --tests FOLDER"
        )
    if not directory.exists():
        raise OwppError(f"no plugins folder at {directory} (pass --dir, or set OWPP_PLUGINS_DIR)")
    keep = args.keep or args.up
    stack.up()
    try:
        stack.wait_for_health()
        admin, user = stack.accounts()
        deploy_env = dict(env) | {"OPEN_WEBUI_URL": stack.url, "OPEN_WEBUI_API_KEY": admin["token"]}
        # Only the throwaway instance's credentials: never the ones in the caller's environment.
        signing_in = ("OPEN_WEBUI_URL", "OPEN_WEBUI_API_KEY")
        for name in [n for n in deploy_env if n.startswith("OPEN_WEBUI_") and n not in signing_in]:
            del deploy_env[name]
        code = owpp_main(["deploy", "--dir", str(directory)], deploy_env)
        if code:
            raise OwppError("owpp deploy to the live Open-WebUI failed (above)")
        test_env = stack.test_env(admin, user, stack.tests / "failures")
        if args.up:
            print(
                f"\nOpen-WebUI: {stack.url}\n"
                f"  admin: {admin['email']} / {admin['password']}\n"
                f"  user:  {user['email']} / {user['password']}\n"
                f"aimock: {stack.aimock_url} (what it was asked: /__aimock/journal)\n\n"
                "To deploy a change:\n"
                f"  OPEN_WEBUI_URL={stack.url} OPEN_WEBUI_API_KEY={admin['token']} "
                f"owpp deploy --dir {shlex.quote(str(directory))}\n"
                "To run the live tests against it again and again (pytest, with owpp-live):\n"
                + "\n".join(f"  export {k}={shlex.quote(v)}" for k, v in test_env.items())
                + f"\n  pytest {shlex.quote(str(stack.tests))}\n"
                "To stop it: owpp live --down"
            )
            return 0
        sys.stdout.flush()  # the deploy's report before pytest's
        command = [
            sys.executable,
            "-m",
            "pytest",
            str(stack.tests),
            "-p",
            "no:cacheprovider",
            *args.pytest_args,
        ]
        return stack.run(command, env=dict(env) | test_env).returncode
    finally:
        if keep:
            print(f"Open-WebUI is still running at {stack.url}. Stop it with: owpp live --down")
        else:
            stack.down()
