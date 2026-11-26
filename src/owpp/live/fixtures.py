"""pytest fixtures for live tests. They are not registered in every pytest run where owpp is
installed: `owpp live` starts the stack, sets the variables they read (OWPP_LIVE_*) and loads
this module with PYTEST_PLUGINS=owpp.live.fixtures, which `owpp live --up` prints for a run
of your own.

- `api`, `user_api`: Open-WebUI's HTTP API as the admin, or as a user who is not one.
- `aimock`: what Open-WebUI sent the model (`aimock.requests()`, from aimock's journal).
- `admin`, `user`, `signed_out`: a Playwright page signed in on Open-WebUI's own login page as
  that account, or with no session. `send(page, text)` (from owpp.live) chats on one.
- `admin_account`, `user_account`: the accounts, with their tokens (name, email, password).

When a test with a page fails, what it saw (each page as a PNG and its text, and what aimock was
last asked) is kept in the tests folder's `failures/`.

Nothing is imported or started until a test asks for it: Playwright only for a page (it comes
with `owpp[live]`), and a fixture used outside `owpp live` says to start it.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

import pytest

from .client import Aimock, Api, account
from .pages import PAGES, new_page, sign_in, signed_in_state


@pytest.fixture(scope="session")
def admin_account() -> dict:
    return account("ADMIN")


@pytest.fixture(scope="session")
def user_account() -> dict:
    return account("USER")


@pytest.fixture(scope="session")
def api(admin_account) -> Api:
    """Open-WebUI's API as the admin. Each call returns (status, body), the body on an error
    too: Open-WebUI says what went wrong in `detail`."""
    return Api(admin_account["token"])


@pytest.fixture(scope="session")
def user_api(user_account) -> Api:
    """Open-WebUI's API as a user who is not an admin."""
    return Api(user_account["token"])


@pytest.fixture(scope="session")
def aimock() -> Aimock:
    """aimock: `aimock.requests()` is every chat request it was sent, newest last."""
    return Aimock()


@pytest.fixture(scope="session")
def browser():
    """Chromium, through Playwright, for the session."""
    account("ADMIN")  # outside `owpp live`, say so before starting a browser
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture(scope="session")
def admin_session(browser, admin_account) -> dict:
    """The admin's browser session, signed in once (Open-WebUI limits sign-ins)."""
    return signed_in_state(browser, admin_account)


@pytest.fixture(scope="session")
def user_session(browser, user_account) -> dict:
    """The user's browser session, signed in once."""
    return signed_in_state(browser, user_account)


@pytest.fixture
def admin(browser, admin_account, admin_session):
    """A page signed in as the admin, in a fresh context (its own localStorage)."""
    page = sign_in(browser, admin_account, admin_session)
    yield page
    page.context.close()


@pytest.fixture
def user(browser, user_account, user_session):
    """A page signed in as a user who is not an admin, in a fresh context."""
    page = sign_in(browser, user_account, user_session)
    yield page
    page.context.close()


@pytest.fixture
def signed_out(browser):
    """A page with no session."""
    page = new_page(browser)
    yield page
    page.context.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """When a test with a page fails, keep what it saw."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    funcargs = getattr(item, "funcargs", {})
    pages = {n: funcargs[n] for n in funcargs if n in PAGES or n.endswith("_page")}
    folder = os.environ.get("OWPP_LIVE_FAILURES")
    if not pages or not folder:
        return
    failures = Path(folder)
    failures.mkdir(parents=True, exist_ok=True)
    for name, page in pages.items():
        stem = failures / f"{item.name}-{name}"
        with contextlib.suppress(Exception):
            page.screenshot(path=f"{stem}.png", full_page=True)
            stem.with_suffix(".txt").write_text(page.inner_text("body"))
    with contextlib.suppress(Exception):
        summary = [
            {
                "model": r.get("model"),
                "stream": r.get("stream"),
                "tools": [t.get("function", {}).get("name") for t in r.get("tools") or []],
                "messages": [[m.get("role"), str(m.get("content"))[:300]] for m in r["messages"]],
            }
            for r in Aimock().requests()[-8:]
        ]
        (failures / f"{item.name}-requests.json").write_text(json.dumps(summary, indent=2))
    report.sections.append(("saved", f"what it saw: {failures}/{item.name}-*"))
