"""Playwright on the stack run.py starts: the fixtures the screenshot scripts (shots_*.py) and the
live suite's browser tests (tools/live) share. Each conftest imports them.

- `admin`, `user`: a page signed in on Open-WebUI's own login page as that account.
- `signed_out`: a page with no session.
- `send(page, text)`: type a message into the chat and send it.

When a test that used one of the pages fails, what it saw (each page as a PNG and its text, and
what aimock was asked) is kept in tools/screenshots/failures/ (not committed).
"""

from __future__ import annotations

import contextlib
import json
import os
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

URL = os.environ.get("OWPP_SCREENSHOT_URL", "http://127.0.0.1:3000")
AIMOCK = "http://127.0.0.1:4010"
VIEWPORT = {"width": 1280, "height": 800}
FAILURES = Path(__file__).resolve().parent / "failures"
PAGES = ("admin", "user", "signed_out")

# Hide the toasts ("You're now logged in.") that would otherwise sit on top of every page.
HIDE_TOASTS = """
document.addEventListener("DOMContentLoaded", () => {
  const style = document.createElement("style");
  style.textContent = "[data-sonner-toaster] { display: none !important; }";
  document.head.appendChild(style);
});
"""


def account(name: str) -> dict:
    """The ADMIN or USER account run.py signed up, with its token."""
    raw = os.environ.get(f"OWPP_SCREENSHOT_{name}")
    if not raw:
        pytest.exit("Start it with tools/screenshots/run.py (or run.py --live)", returncode=2)
    return json.loads(raw)


@pytest.fixture(scope="session")
def admin_account() -> dict:
    return account("ADMIN")


@pytest.fixture(scope="session")
def user_account() -> dict:
    return account("USER")


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


def new_page(browser: Browser) -> Page:
    context = browser.new_context(viewport=VIEWPORT, color_scheme="light")
    context.add_init_script(HIDE_TOASTS)
    return context.new_page()


def sign_in(browser: Browser, account: dict) -> Page:
    """Sign in on Open-WebUI's own login page, and close the What's New dialog."""
    page = new_page(browser)
    page.goto(URL + "/auth")
    page.fill("input[name=email]", account["email"])
    page.fill("input[name=password]", account["password"])
    page.keyboard.press("Enter")
    page.wait_for_url(URL + "/")
    with contextlib.suppress(PlaywrightTimeout):
        page.get_by_text("Okay, Let's Go!").click(timeout=5000)
    return page


def send(page: Page, text: str) -> None:
    """Type a message into the chat input and send it. Since v0.13.5 the input takes typing
    while the models and tools are still loading, and can be redrawn once they arrive, losing
    what was typed so far: so check the input holds the whole message before pressing Enter,
    and type it again when it does not. The input turns ' into a curly ’, so leave apostrophes
    out of `text`."""
    chat_input = page.locator("#chat-input")
    for _ in range(5):
        chat_input.click()
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(text)
        page.wait_for_timeout(300)
        if chat_input.inner_text().strip() == text:
            page.keyboard.press("Enter")
            return
    raise AssertionError(f"the chat input never held {text!r}: {chat_input.inner_text()!r}")


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
    page = new_page(browser)
    yield page
    page.context.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """When a test with a page fails, keep what it saw: each open page as a PNG and its text,
    and what aimock was asked, in tools/screenshots/failures/."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    pages = {n: item.funcargs[n] for n in item.funcargs if n in PAGES or n.endswith("_page")}
    if not pages:
        return
    FAILURES.mkdir(exist_ok=True)
    for name, page in pages.items():
        stem = FAILURES / f"{item.name}-{name}"
        with contextlib.suppress(Exception):
            page.screenshot(path=f"{stem}.png", full_page=True)
            stem.with_suffix(".txt").write_text(page.inner_text("body"))
    with contextlib.suppress(Exception):
        url = AIMOCK + "/__aimock/journal?path=/v1/chat/completions"
        with urllib.request.urlopen(url, timeout=10) as response:
            asked = [e["body"] for e in json.loads(response.read()) if e.get("body")][-8:]
        summary = [
            {
                "model": r.get("model"),
                "stream": r.get("stream"),
                "tools": [t.get("function", {}).get("name") for t in r.get("tools") or []],
                "messages": [[m.get("role"), str(m.get("content"))[:300]] for m in r["messages"]],
            }
            for r in asked
        ]
        (FAILURES / f"{item.name}-requests.json").write_text(json.dumps(summary, indent=2))
    report.sections.append(("saved", f"what it saw: {FAILURES}/{item.name}-*"))
