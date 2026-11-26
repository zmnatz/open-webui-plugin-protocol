"""Fixtures for the screenshot scripts (shots_*.py). run.py starts Open-WebUI (`owpp live`), deploys
the examples and runs these with pytest; the repository's own test run never collects them.

Each script signs in through the real login page, follows a plugin's By hand steps in a
browser, and calls `shot(...)` at each step worth seeing. A shot names the plugin tests it
illustrates, so the test catalogue can show it next to their By hand steps.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import urllib.request
from pathlib import Path

import pytest
from owpp_live import send, sign_in, url  # noqa: F401  (for the scripts: from conftest import ...)
from owpp_live.client import account

# The browser pages (admin, user, signed_out), the accounts and the failure capture are
# owpp-live's fixtures; `api` and `user_api` here return the body alone, for setting things up.
URL = url()

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "docs" / "screenshots"
MANIFEST = OUT / "screenshots.json"

_taken: list[dict] = []


class Api:
    """Open-WebUI's HTTP API as one account: for setting things up, never for what is shown."""

    def __init__(self, token: str):
        self.token = token

    def __call__(self, method: str, path: str, body: dict | list | None = None):
        request = urllib.request.Request(
            URL + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"null")

    def valves(self, function_id: str, **changes) -> dict:
        """Change some of a function's valves, as saving them in the admin UI does."""
        valves = self("GET", f"/api/v1/functions/id/{function_id}/valves") or {}
        before = dict(valves)
        self("POST", f"/api/v1/functions/id/{function_id}/valves/update", {**valves, **changes})
        return before


@pytest.fixture(scope="session")
def api() -> Api:
    return Api(account("ADMIN")["token"])


@pytest.fixture(scope="session")
def user_api() -> Api:
    return Api(account("USER")["token"])


@pytest.fixture
def shot(request):
    """shot(page, plugin, name, caption, illustrates=(...)): save and record one screenshot."""

    def take(page_or_locator, plugin: str, name: str, caption: str, illustrates=(), **options):
        path = OUT / plugin / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        page_or_locator.screenshot(path=path, animations="disabled", **options)
        _taken.append(
            {
                "file": path.relative_to(OUT).as_posix(),
                "plugin": plugin,
                "caption": caption,
                "illustrates": list(illustrates),
                "script": request.node.nodeid.split("tools/screenshots/")[-1],
            }
        )

    return take


def pytest_sessionfinish(session, exitstatus):
    """Merge this run's shots into screenshots.json (a run with -k keeps the others)."""
    if not _taken:
        return
    known = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"shots": []}
    files = {s["file"] for s in _taken}
    shots = [s for s in known["shots"] if s["file"] not in files] + _taken
    try:
        version = Api("")("GET", "/api/version")["version"]
    except OSError:
        version = known.get("open_webui", "")
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    MANIFEST.write_text(
        json.dumps(
            {
                "open_webui": version,
                "taken": datetime.date.today().isoformat(),
                "commit": commit,
                "shots": sorted(shots, key=lambda s: (s["plugin"], s["file"])),
            },
            indent=2,
        )
        + "\n"
    )
