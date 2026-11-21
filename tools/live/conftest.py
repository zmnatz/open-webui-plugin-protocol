"""Fixtures for the live suite (test_*.py here). `tools/screenshots/run.py --live` starts
Open-WebUI, deploys examples/plugins and runs these with pytest; the repository's own test run
never collects them."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

URL = os.environ.get("OWPP_SCREENSHOT_URL", "http://127.0.0.1:3000")


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


def _account(name: str) -> dict:
    raw = os.environ.get(f"OWPP_SCREENSHOT_{name}")
    if not raw:
        pytest.exit("Run the live suite with tools/screenshots/run.py --live", returncode=2)
    return json.loads(raw)


@pytest.fixture(scope="session")
def api() -> Api:
    return Api(_account("ADMIN")["token"])


@pytest.fixture(scope="session")
def user_api() -> Api:
    return Api(_account("USER")["token"])
