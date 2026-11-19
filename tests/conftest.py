"""Shared helpers: plugin folders on disk, a stand-in for Open-WebUI's admin API, fake git sources."""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from owpp.bundle import load_function_files
from owpp.deploy import MANAGED_BY, Options
from owpp.sources import source_keys

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "plugins"
DOCS = Path(__file__).resolve().parent.parent / "docs"

FILTER = '''"""
title: Demo Filter
author: me
description: A demo filter.
"""
class Filter:
    pass
'''

SKILL_MD = "---\nname: s\n---\nbody\n"


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    """The mock server is on localhost; never send those requests through a proxy."""
    for name in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ):
        monkeypatch.delenv(name, raising=False)


def write_tree(root: Path, files: dict[str, str | bytes]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return root


def embedded(code: str) -> dict:
    """The data the runtime reads back: the JSON string literal in the bundle."""
    m = re.search(r'_PLUGIN = _json\.loads\((".*")\)\n', code)
    assert m, "no runtime data in the bundle"
    return json.loads(json.loads(m.group(1)))


def fake_remote(directory: Path) -> dict:
    """Stand-ins for the files plugins take from git, so no test needs the network."""
    out = {}
    for key in source_keys(directory):
        if key.endswith("/"):
            out[f"{key}SKILL.md"] = SKILL_MD
            out[f"{key}references/a.md"] = "ref\n"
        else:
            out[key] = (
                SKILL_MD
                if key.endswith(".md")
                else "class Tools:\n    pass\n\nclass Event:\n    pass\n"
            )
    return out


@pytest.fixture
def functions_dir(tmp_path):
    """Make a plugins folder from {name: text}."""
    counter = iter(range(1000))

    def make(files: dict[str, str | bytes]) -> Path:
        return write_tree(tmp_path / f"fn{next(counter)}", files)

    return make


@pytest.fixture
def git_fn(functions_dir):
    """A live function this deploy already manages."""

    def make(fn_id: str, content: str, **extra) -> dict:
        (file,) = load_function_files(functions_dir({f"{fn_id}.py": content}))
        return {
            "id": fn_id,
            "name": file.name,
            "content": content,
            "meta": {"description": file.description, "managed_by": MANAGED_BY},
            "type": "filter",
            "is_active": True,
            "is_global": False,
            **extra,
        }

    return make


# ---- a stand-in for Open-WebUI's admin API --------------------------------------


class MockServer:
    """Just enough state to see which calls a deploy makes."""

    def __init__(
        self, live=(), key="sk-good", created_type="filter", created_active=False, fail_delete=False
    ):
        self.calls: list[str] = []
        self.state: dict[str, dict] = {f["id"]: dict(f) for f in live}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, obj, status=200):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, method):
                path = urlsplit(self.path).path
                if path == "/health":
                    return self._send({"status": True})
                if self.headers.get("Authorization") != f"Bearer {key}":
                    return self._send({"detail": "nope"}, 401)
                body = None
                if method == "POST":
                    raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                    body = json.loads(raw) if raw else None
                outer.calls.append(f"{method} {path}")
                state = outer.state
                # Like the real API: the list has no `content`; GET /id/<id> does.
                if path == "/api/v1/functions/list":
                    return self._send(
                        [{k: v for k, v in f.items() if k != "content"} for f in state.values()]
                    )
                one = re.fullmatch(r"/api/v1/functions/id/([^/]+)", path)
                if one and method == "GET":
                    f = state.get(one.group(1))
                    return self._send(f) if f else self._send({"detail": "not found"}, 401)
                if path == "/api/v1/functions/create":
                    f = {
                        "id": body["id"],
                        "name": body["name"],
                        "content": body["content"],
                        "meta": body["meta"],
                        "type": created_type,
                        "is_active": created_active,
                        "is_global": False,
                    }
                    state[body["id"]] = f
                    return self._send(f)
                delete = re.fullmatch(r"/api/v1/functions/id/([^/]+)/delete", path)
                if delete and method == "DELETE":
                    existed = state.pop(delete.group(1), None) is not None
                    return self._send(False if fail_delete else existed)
                m = re.fullmatch(r"/api/v1/functions/id/([^/]+)/(update|toggle)(/global)?", path)
                if m:
                    f = state.get(m.group(1))
                    if not f:
                        return self._send({"detail": "not found"}, 401)
                    if m.group(2) == "update":
                        f.update(content=body["content"], name=body["name"], meta=body["meta"])
                    elif m.group(3):
                        f["is_global"] = not f["is_global"]
                    else:
                        f["is_active"] = not f["is_active"]
                    return self._send(f)
                return self._send("?", 404)

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_DELETE(self):
                self._handle("DELETE")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()

    def options(self, directory: Path, **kwargs) -> Options:
        kwargs.setdefault("api_key", "sk-good")
        return Options(base_url=self.base_url, dir=directory, **kwargs)

    def close(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def mock_server():
    servers: list[MockServer] = []

    def make(**kwargs) -> MockServer:
        servers.append(MockServer(**kwargs))
        return servers[-1]

    yield make
    for s in servers:
        s.close()
