"""Fixtures for the screenshot scripts (shots_*.py). run.py starts Open-WebUI, deploys the
examples and runs these with pytest; the repository's own test run never collects them.

Each script signs in through the real login page, follows a plugin's By hand steps in a
browser, and calls `shot(...)` at each step worth seeing. A shot names the plugin tests it
illustrates, so the test catalogue can show it next to their By hand steps.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import subprocess
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "docs" / "screenshots"
MANIFEST = OUT / "screenshots.json"
URL = os.environ.get("OWPP_SCREENSHOT_URL", "http://127.0.0.1:3000")
VIEWPORT = {"width": 1280, "height": 800}

# Hide the toasts ("You're now logged in.") that would otherwise sit on top of every shot.
HIDE_TOASTS = """
document.addEventListener("DOMContentLoaded", () => {
  const style = document.createElement("style");
  style.textContent = "[data-sonner-toaster] { display: none !important; }";
  document.head.appendChild(style);
});
"""

_taken: list[dict] = []


def _account(name: str) -> dict:
    raw = os.environ.get(f"OWPP_SCREENSHOT_{name}")
    if not raw:
        pytest.exit("Run the screenshots with tools/screenshots/run.py", returncode=2)
    return json.loads(raw)


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
def admin_account() -> dict:
    return _account("ADMIN")


@pytest.fixture(scope="session")
def user_account() -> dict:
    return _account("USER")


@pytest.fixture(scope="session")
def api(admin_account) -> Api:
    return Api(admin_account["token"])


@pytest.fixture(scope="session")
def user_api(user_account) -> Api:
    return Api(user_account["token"])


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


def _new_page(browser: Browser) -> Page:
    context = browser.new_context(viewport=VIEWPORT, color_scheme="light")
    context.add_init_script(HIDE_TOASTS)
    return context.new_page()


def sign_in(browser: Browser, account: dict) -> Page:
    """Sign in on Open-WebUI's own login page, and close the What's New dialog."""
    page = _new_page(browser)
    page.goto(URL + "/auth")
    page.fill("input[name=email]", account["email"])
    page.fill("input[name=password]", account["password"])
    page.keyboard.press("Enter")
    page.wait_for_url(URL + "/")
    with contextlib.suppress(PlaywrightTimeout):
        page.get_by_text("Okay, Let's Go!").click(timeout=5000)
    return page


@pytest.fixture
def admin(browser, admin_account):
    page = sign_in(browser, admin_account)
    yield page
    page.context.close()


@pytest.fixture
def user(browser, user_account):
    page = sign_in(browser, user_account)
    yield page
    page.context.close()


@pytest.fixture
def signed_out(browser):
    page = _new_page(browser)
    yield page
    page.context.close()


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
