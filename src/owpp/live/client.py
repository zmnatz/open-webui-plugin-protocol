"""The running stack, as the live tests reach it: its address, the accounts, the API, aimock."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def url() -> str:
    """Open-WebUI's address (OWPP_LIVE_URL, which `owpp live` sets)."""
    return os.environ.get("OWPP_LIVE_URL", "http://127.0.0.1:3000")


def aimock_url() -> str:
    return os.environ.get("OWPP_LIVE_AIMOCK_URL", "http://127.0.0.1:4010")


def account(name: str) -> dict:
    """The ADMIN or USER account `owpp live` signed up, with its token."""
    import pytest

    raw = os.environ.get("OWPP_LIVE_ADMIN") if name == "ADMIN" else os.environ.get("OWPP_LIVE_USER")
    if not raw:
        pytest.exit(
            "live tests run against the Open-WebUI `owpp live` starts: run `owpp live`, or "
            "`owpp live --up` and the exports it prints",
            returncode=2,
        )
    return json.loads(raw)


class Api:
    """Open-WebUI's HTTP API as one account. Returns (status, parsed body), also on an error."""

    def __init__(self, token: str, timeout: float = 120):
        self.token = token
        self.timeout = timeout

    def __call__(self, method: str, path: str, body: dict | list | None = None):
        request = urllib.request.Request(
            url() + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            # Keep the body: Open-WebUI says why in `detail`.
            text = error.read().decode(errors="replace")
            try:
                return error.code, json.loads(text)
            except json.JSONDecodeError:
                return error.code, text


class Aimock:
    """aimock, the stack's models."""

    def requests(self, path: str = "/v1/chat/completions") -> list[dict]:
        """Every request aimock was sent at `path`, from its journal: what Open-WebUI sent
        the model, after every filter ran."""
        address = f"{aimock_url()}/__aimock/journal?path={path}"
        with urllib.request.urlopen(address, timeout=10) as response:
            return [entry["body"] for entry in json.loads(response.read()) if entry.get("body")]
