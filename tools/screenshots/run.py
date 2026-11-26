"""Take the documentation screenshots, or run the live suite, on a real Open-WebUI.

    uv run python tools/screenshots/run.py            # the screenshots
    uv run python tools/screenshots/run.py -- -k stale  # some of them
    uv run python tools/screenshots/run.py --keep     # leave it running
    uv run python tools/screenshots/run.py --live     # the live suite (tools/live): assert, no screenshots
    uv run python tools/screenshots/run.py --up       # only start it, to try

It is `owpp live` (owpp-live, packages/owpp-live) with this repository's pieces:

1. owpp's stack (Open-WebUI at the version the protocol targets, aimock as its models), with
   compose.yaml here layered on it: nginx serving fixed files for a LiteLLM gateway and mcpo,
   and the Open-WebUI settings the examples need. aimock answers from aimock/ here.
2. `owpp live` signs up an admin and a user and deploys examples/plugins with `owpp deploy`,
   exactly as a plugin repository would.
3. It runs the Playwright scripts in this folder (shots_*.py), each following the By hand steps
   of some plugin tests and saving screenshots into docs/screenshots/, with screenshots.json
   saying which test each one illustrates; or, with --live, the tests in tools/live.
4. It stops and removes the containers, unless --keep or --up.

Needs Docker, and Chromium for Playwright (`uv run playwright install chromium`). The browser
loads Excalidraw from esm.sh, so it needs internet access.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def owpp_live_args(argv: list[str] | None = None) -> list[str]:
    parser = argparse.ArgumentParser(description="Take the documentation screenshots.")
    parser.add_argument("--keep", action="store_true", help="leave Open-WebUI running")
    parser.add_argument(
        "--live", action="store_true", help="run the live suite (tools/live), not the screenshots"
    )
    parser.add_argument(
        "--up", action="store_true", help="start it and deploy the examples, run nothing"
    )
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER, help="passed on to pytest")
    args = parser.parse_args(argv)
    if args.pytest_args[:1] == ["--"]:
        args.pytest_args = args.pytest_args[1:]
    tests = HERE.parent / "live" if args.live else HERE
    pick = [] if args.live else ["-o", "python_files=shots_*.py"]
    return [
        "live",
        "--dir",
        str(ROOT / "examples" / "plugins"),
        "--tests",
        str(tests),
        "--compose",
        str(HERE / "compose.yaml"),
        "--fixtures",
        str(HERE / "aimock"),
        *(["--up"] if args.up else ["--keep"] if args.keep else []),
        "--",
        *pick,
        *args.pytest_args,
    ]


def main(argv: list[str] | None = None) -> int:
    from owpp.cli import console_main

    sys.argv = ["owpp", *owpp_live_args(argv)]
    return console_main()


if __name__ == "__main__":
    sys.exit(main())
