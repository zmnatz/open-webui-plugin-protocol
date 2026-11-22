# Plugin static files library (docs/libraries.md), inserted automatically when a plugin has a
# static/ folder. Every file in it is served, as it is, at <prefix>/<path>, with no code. A file
# named index.html is the plugin's page: it is served at <prefix>/ (and <prefix> redirects there).
# Needs the routes library, which puts every route behind a signed-in user unless the plugin says
# `static: {access: public}`. Files the function renders itself belong in templates/, which is
# never served.

import base64 as _base64
import hashlib as _hashlib
import json as _json
import mimetypes as _mimetypes

from fastapi import APIRouter as _APIRouter, Request as _Request
from fastapi.responses import Response as _Response

from .plugin_core import plugin_app
from .plugin_routes import plugin_mount

# {"prefix": "/id", "access": "user" | "admin" | "public", "files": {path: {"content", "encoding"?}}}
__STATIC_DATA__ = '{"prefix": "", "files": {}}'  # for imports; the bundler drops it
_STATIC = _json.loads(__STATIC_DATA__)


def plugin_static_files() -> list:
    return sorted(_STATIC["files"])


def _static_bytes(path: str) -> bytes:
    entry = _STATIC["files"][path]
    if entry.get("encoding") == "base64":
        return _base64.b64decode(entry["content"])
    return entry["content"].encode("utf-8")


def _static_endpoint(path: str):
    data = _static_bytes(path)
    etag = '"' + _hashlib.sha1(data).hexdigest()[:20] + '"'
    kind = _mimetypes.guess_type(path)[0] or "application/octet-stream"
    if kind.startswith("text/") or kind in ("application/javascript", "application/json", "image/svg+xml"):
        kind += "; charset=utf-8"
    headers = {"ETag": etag, "Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"}

    # Only module-level names (Request) may appear in the annotations: with
    # postponed evaluation FastAPI resolves them in this module's globals.
    async def endpoint(request: _Request):
        if request.headers.get("if-none-match") == etag:
            return _Response(status_code=304, headers=headers)
        return _Response(content=data, media_type=kind, headers=headers)

    return endpoint


def _index_redirect(location: str):
    async def endpoint():
        return _Response(status_code=307, headers={"Location": location, "Cache-Control": "no-cache"})

    return endpoint


def plugin_static_serve(router, prefix: str = None) -> int:
    """Add a GET route per static file to `router`. Returns how many."""
    prefix = prefix or _STATIC["prefix"]
    added = 0
    for path in plugin_static_files():
        router.add_api_route(
            f"{prefix}/{path}",
            _static_endpoint(path),
            methods=["GET"],
            include_in_schema=False,
        )
        added += 1
        if path == "index.html":
            # The plugin's single page: <prefix>/ serves it, and <prefix> redirects
            # there so relative links in the page (app.js, img/a.png) resolve.
            router.add_api_route(
                f"{prefix}/",
                _static_endpoint(path),
                methods=["GET"],
                include_in_schema=False,
            )
            router.add_api_route(
                prefix,
                _index_redirect(prefix + "/"),
                methods=["GET"],
                include_in_schema=False,
            )
            added += 2
    return added


def plugin_static_ensure(app=None) -> bool:
    """Mount the static files on the app (idempotent: a later call replaces the earlier routes).
    Runs when the library loads; call it again with `request.app` if the app was not there yet."""
    app = app or plugin_app()
    if app is None:
        return False
    router = _APIRouter()
    if plugin_static_serve(router):
        plugin_mount(app, router, _STATIC["prefix"], name="static", access=_STATIC.get("access"))
    return True


plugin_static_ensure()

# end plugin static library
