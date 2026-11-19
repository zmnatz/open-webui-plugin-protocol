"""Take the documentation screenshots on a real Open-WebUI.

    uv run --group screenshots python tools/screenshots/run.py            # everything
    uv run --group screenshots python tools/screenshots/run.py -k stale   # some of them
    uv run --group screenshots python tools/screenshots/run.py --keep     # leave it running

1. Starts compose.yaml: Open-WebUI (the version the protocol targets), a scripted model and
   mcpo. Nothing is kept between runs.
2. Signs up the admin (the first account is the admin) and adds a user.
3. Deploys examples/plugins with `owpp deploy`, exactly as a plugin repository would.
4. Runs the Playwright scripts in this folder (shots_*.py). Each follows the By hand steps of
   some plugin tests and saves screenshots into docs/screenshots/, with screenshots.json
   saying which test each one illustrates. tools/build_docs.py puts them on the site.
5. Stops and removes the containers, unless --keep.

Needs Docker, and Chromium for Playwright (`uv run --group screenshots playwright install
chromium`). The browser loads Excalidraw from esm.sh, so it needs internet access.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
COMPOSE = ["docker", "compose", "-f", str(HERE / "compose.yaml")]
URL = "http://127.0.0.1:3000"

# Throwaway accounts on a throwaway instance; never reused anywhere.
ADMIN = {"name": "Ada Admin", "email": "admin@example.com", "password": "screenshots-admin"}
USER = {
    "name": "Bob User",
    "email": "bob@example.com",
    "password": "screenshots-user",
    "role": "user",
}


def api(method: str, path: str, body: dict | None = None, token: str | None = None):
    request = urllib.request.Request(
        URL + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}
        | ({"Authorization": f"Bearer {token}"} if token else {}),
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


def wait_for_health(seconds: int = 600) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if api("GET", "/health").get("status"):
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(2)
    raise SystemExit(f"Open-WebUI did not answer {URL}/health within {seconds}s")


def accounts() -> tuple[str, str]:
    """The admin's and the user's tokens. Signs them up on a fresh instance."""
    try:
        admin = api("POST", "/api/v1/auths/signup", ADMIN)["token"]
        api("POST", "/api/v1/auths/add", USER, admin)
    except urllib.error.HTTPError:  # already there (--keep, then run again)
        admin = api("POST", "/api/v1/auths/signin", ADMIN)["token"]
    user = api("POST", "/api/v1/auths/signin", USER)["token"]
    return admin, user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Take the documentation screenshots.")
    parser.add_argument("--keep", action="store_true", help="leave Open-WebUI running")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER, help="passed on to pytest")
    args = parser.parse_args(argv)
    if args.pytest_args[:1] == ["--"]:
        args.pytest_args = args.pytest_args[1:]

    subprocess.run([*COMPOSE, "up", "-d", "--wait"], check=True)
    try:
        wait_for_health()
        admin, user = accounts()
        env = os.environ | {"OPEN_WEBUI_URL": URL, "OPEN_WEBUI_API_KEY": admin}
        subprocess.run(
            [sys.executable, "-m", "owpp", "deploy", "--dir", str(ROOT / "examples" / "plugins")],
            check=True,
            env=env,
            cwd=ROOT,
        )
        env |= {
            "OWPP_SCREENSHOT_URL": URL,
            "OWPP_SCREENSHOT_ADMIN": json.dumps({**ADMIN, "token": admin}),
            "OWPP_SCREENSHOT_USER": json.dumps({**USER, "token": user}),
        }
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(HERE),
                "-o",
                "python_files=shots_*.py",
                "-p",
                "no:cacheprovider",
                *args.pytest_args,
            ],
            env=env,
            cwd=ROOT,
        ).returncode
    finally:
        if args.keep:
            print(f"Open-WebUI is still running at {URL}. Stop it with: {' '.join(COMPOSE)} down")
        else:
            subprocess.run([*COMPOSE, "down", "--volumes"], check=False)


if __name__ == "__main__":
    sys.exit(main())
