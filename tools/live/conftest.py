"""Fixtures for the live suite (test_*.py here). `tools/screenshots/run.py --live` starts
Open-WebUI, deploys examples/plugins and runs these with pytest; the repository's own test run
never collects them.

A test that needs the browser (what the chat page does, a button under a reply, the Artifacts
panel) takes the Playwright pages the screenshot scripts use: `admin`, `user` and `signed_out`,
with `send(page, text)` to chat (tools/screenshots/browser_fixtures.py)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# Appended, not prepended: `conftest` must stay this file for `from conftest import ...`.
sys.path.append(str(Path(__file__).resolve().parent.parent / "screenshots"))

from browser_fixtures import (  # noqa: E402, F401  (fixtures and the failure hook, for pytest)
    AIMOCK,
    URL,
    account,
    admin,
    admin_account,
    browser,
    pytest_runtest_makereport,
    send,
    signed_out,
    user,
    user_account,
)


class Api:
    """Open-WebUI's HTTP API as one account. Returns (status, parsed body), also on an error."""

    def __init__(self, token: str):
        self.token = token

    def __call__(self, method: str, path: str, body: dict | list | None = None):
        request = urllib.request.Request(
            URL + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            # Keep the body: Open-WebUI says why in `detail`.
            text = error.read().decode(errors="replace")
            try:
                return error.code, json.loads(text)
            except json.JSONDecodeError:
                return error.code, text


@pytest.fixture(scope="session")
def api() -> Api:
    return Api(account("ADMIN")["token"])


@pytest.fixture(scope="session")
def user_api() -> Api:
    return Api(account("USER")["token"])
