"""The running stack, as the live tests reach it: its address, the accounts, the API, aimock."""

from __future__ import annotations

import functools
import json
import os
import urllib.request

from owpp.openwebui import OpenWebUI, urllib_fetch


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
    """Open-WebUI's HTTP API as one account. Returns (status, parsed body), also on an error:
    Open-WebUI says why in `detail`. A thin layer over owpp's own adapter (owpp.openwebui)."""

    def __init__(self, token: str, timeout: float = 120):
        self.token = token
        self.timeout = timeout

    def __call__(self, method: str, path: str, body: dict | list | None = None):
        fetch = functools.partial(urllib_fetch, timeout=self.timeout)
        return OpenWebUI(url(), fetch, self.token).request(method, path, body)


class Aimock:
    """aimock, the stack's models."""

    def requests(self, path: str = "/v1/chat/completions") -> list[dict]:
        """Every request aimock was sent at `path`, from its journal: what Open-WebUI sent
        the model, after every filter ran."""
        address = f"{aimock_url()}/__aimock/journal?path={path}"
        with urllib.request.urlopen(address, timeout=10) as response:
            return [entry["body"] for entry in json.loads(response.read()) if entry.get("body")]
