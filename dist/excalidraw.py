"""
title: Excalidraw
author: zmnatz
version: 3.1.0
global: true
required_open_webui_version: 0.10.0
license: MIT
description: A shared Excalidraw drawing per chat, opened in the Artifacts side panel.
"""

import logging as _logging
import os as _os
import re as _re
import sys as _sys
import time as _time

_core_valves_cache = {}


def plugin_function_id():
    """This function's id, from the module name Open-WebUI gives it
    (function_<id>_<32 hex>), or None outside Open-WebUI."""
    match = _re.fullmatch(r"function_(.+?)(?:_[0-9a-f]{32})?", __name__)
    return match.group(1) if match else None


def plugin_app():
    """Open-WebUI's FastAPI app, or None before it has been imported."""
    return getattr(_sys.modules.get("open_webui.main"), "app", None)


async def plugin_is_active(function_id: str = None) -> bool:
    """Whether this function is still installed and enabled. True when that cannot
    be told (no id, or the lookup failed): callers use it to stop work, and
    stopping on a hiccup would be worse than carrying on."""
    function_id = function_id or plugin_function_id()
    if not function_id:
        return True
    try:
        from open_webui.models.functions import Functions

        function = await Functions.get_function_by_id(function_id)
    except Exception:
        return True
    return bool(function and function.is_active)


async def plugin_stored_valves(valves_cls, function_id: str = None, ttl: float = 0):
    """The function's valves as stored. A running instance only has them applied
    when it handles an event or a chat, so routes and background jobs read them
    here. `ttl` reuses a read for that many seconds (a page that polls)."""
    function_id = function_id or plugin_function_id()
    key = (function_id, valves_cls)
    cached = _core_valves_cache.get(key)
    if ttl and cached and _time.monotonic() - cached[0] < ttl:
        return cached[1]
    stored = {}
    if function_id:
        try:
            from open_webui.models.functions import Functions

            stored = await Functions.get_function_valves_by_id(function_id) or {}
        except Exception:
            import logging

            logging.getLogger(__name__).warning("core: could not read the stored valves", exc_info=True)
    valves = valves_cls(**stored)
    _core_valves_cache[key] = (_time.monotonic(), valves)
    return valves


# Keep in step with TEMPLATE in owpp/envtemplate.py (a test compares them).
_ENV_TEMPLATE = _re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_ENV_ESCAPE = "\x00"


def _env_typed(text: str):
    """A value read from the environment, typed like a YAML 1.2 scalar: 60 is a number, true a
    boolean, null empty; anything else stays text."""
    s = text.strip()
    if _re.fullmatch(r"true|True|TRUE", s):
        return True
    if _re.fullmatch(r"false|False|FALSE", s):
        return False
    if _re.fullmatch(r"null|Null|NULL|~", s):
        return None
    if _re.fullmatch(r"[-+]?[0-9]+", s):
        return int(s)
    if _re.fullmatch(r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][-+]?[0-9]+)?", s):
        return float(s)
    return text


def _env_lookup(name: str, default):
    """The variable if it is set and not empty, else the default (like `${NAME:-default}`), else None."""
    value = _os.environ.get(name)
    return value if value not in (None, "") else default


def plugin_env(value):
    """Resolve `${NAME}` and `${NAME:-default}` templates from the container's environment, in a
    string or in the strings of a dict or list (keys are left alone). A string that is one template
    is typed (`${N:-60}` is the number 60); a template inside a longer string is text. An unset or
    empty variable uses its default; with no default a whole-string template is None (with a
    warning) and an embedded one is empty. `$${` writes a literal `${`."""
    if isinstance(value, dict):
        return {k: plugin_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plugin_env(v) for v in value]
    if not isinstance(value, str):
        return value
    text = value.replace("$${", _ENV_ESCAPE + "{")
    whole = _ENV_TEMPLATE.fullmatch(text)
    if whole:
        found = _env_lookup(whole.group(1), whole.group(2))
        if found is None:
            _logging.getLogger(__name__).warning("core: %s is not set and has no default", whole.group(1))
            return None
        return _env_typed(found)

    def fill(match):
        found = _env_lookup(match.group(1), match.group(2))
        if found is None:
            _logging.getLogger(__name__).warning("core: %s is not set and has no default", match.group(1))
        return found or ""

    return _ENV_TEMPLATE.sub(fill, text).replace(_ENV_ESCAPE, "$")


# end plugin core library

import base64 as _base64
import hashlib as _hashlib
import hmac as _hmac
import logging as _logging
import re as _re
import time as _time
from urllib.parse import quote as _urlquote
from typing import Annotated as _Annotated, Any as _Any

from fastapi import (
    Depends as _Depends,
    HTTPException as _HTTPException,
    Request as _Request,
    Response as _Response,
)



_routes_log = _logging.getLogger(__name__ + ".routes")


def _routes_owner(module_name):
    """Open-WebUI names a function's module function_<id>_<32 hex>; the hex part
    can differ between loads of the same function, so compare without it."""
    return _re.sub(r"_[0-9a-f]{32}$", "", module_name or "")


def _routes_access(access):
    if access not in ("user", "admin", "public"):
        raise ValueError(
            f"access must be 'user', 'admin' or 'public' (exactly that word), not {access!r}"
        )
    return access


async def plugin_user(request, token: str = None):
    """The signed-in Open-WebUI user for this request, or None. It is Open-WebUI's own session
    (a bearer header, else its `token` cookie, or `token` if one is given), and only a user or an
    admin counts, as in Open-WebUI's get_verified_user. Imports happen here, not at module level:
    only module-level names can appear in a dependency's annotations."""
    state = getattr(request, "state", None)
    cached = getattr(state, "_plugin_user", None)
    if cached is not None and token is None:  # the mount's guard and a route's own marker both ask
        return cached[0]

    from fastapi import BackgroundTasks, Response
    from fastapi.security import HTTPAuthorizationCredentials
    from open_webui.utils.auth import get_current_user

    scheme, _, credentials = (
        ("bearer", "", token) if token else (request.headers.get("Authorization") or "").partition(" ")
    )
    auth_token = (
        HTTPAuthorizationCredentials(scheme=scheme, credentials=credentials.strip())
        if scheme.lower() == "bearer" and credentials.strip()
        else None
    )
    try:
        user = await get_current_user(request, Response(), BackgroundTasks(), auth_token)
    except _HTTPException:
        user = None
    user = user if getattr(user, "role", None) in ("user", "admin") else None
    if state is not None:
        state._plugin_user = (user,)
    return user


def _wants_a_page(request) -> bool:
    """A browser navigation (a GET that asks for HTML), not an API call."""
    return request.method == "GET" and "text/html" in request.headers.get("accept", "")


def _login_url(request) -> str:
    """Open-WebUI's login page, which brings the person back here afterwards. The address is a
    plain absolute path of this site (never `//host`), so it cannot send anyone elsewhere."""
    path = "/" + request.url.path.lstrip("/")
    if request.url.query:
        path += "?" + request.url.query
    return "/auth?redirect=" + _urlquote(path, safe="")


async def _plugin_sign_in(request):
    """The sign-ins that need no input from the person (trusted headers from a proxy, or
    authentication switched off), done the way Open-WebUI's own login page does them: a call to its
    sign-in endpoint with empty credentials, carrying this request's headers. It runs inside the
    app (no socket, so no host, port or TLS to get wrong). Returns (token, Set-Cookie headers) or
    None. OIDC and LDAP cannot be done here; they need the login page."""
    try:
        import httpx

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in ("host", "cookie", "authorization", "content-length", "content-type", "accept", "accept-encoding", "connection", "transfer-encoding")
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=request.app),
            base_url=f"{request.url.scheme}://{request.url.netloc}",
            timeout=10,
        ) as client:
            reply = await client.post(
                "/api/v1/auths/signin", json={"email": "", "password": ""}, headers=headers
            )
        token = (reply.json() or {}).get("token") if reply.status_code == 200 else None
        return (token, reply.headers.get_list("set-cookie")) if token else None
    except Exception as error:  # no automatic sign-in here: fall back to the login page
        _routes_log.debug("routes: automatic sign-in not possible: %s", type(error).__name__)
        return None


def plugin_guard(access: str = None):
    """A route dependency for who may reach a route: 404 once this function is disabled, a
    signed-in user (see below), and (for access="admin") 403 unless the user is an admin. The
    default is "user". It returns the user. access="public" is the one level that needs no one:
    it only checks the function is enabled, and returns None. `PluginUser` and `PluginAdmin` below are its two
    ready-made forms for marking a single route.

    Someone with no session is not simply turned away if they are opening a page in a browser: the
    sign-ins that need no input (trusted headers, auth switched off) are tried first and the session
    is handed to the browser, then, if that did not work, the browser is sent to Open-WebUI's login
    page (which handles OIDC and LDAP) and back. Anything else (an API call, a fetch, an iframe)
    gets 401. A page in Open-WebUI's Artifacts panel only has a session when the user's "iframe
    Sandbox Allow Same Origin" setting is on (off by default); see docs/libraries.md."""
    access = _routes_access("user" if access is None else access)

    if access == "public":
        # Deliberately open: nobody is signed in or asked to be (no session lookup, no sign-in
        # attempt, no redirect). It is still switched off with the function. A marker on a route
        # of a public mount still applies, so one route can ask for more.
        async def open_guard():
            await plugin_require_active()

        return open_guard

    async def guard(request: _Request, response: _Response):
        await plugin_require_active()
        user = await plugin_user(request)
        if user is None and _wants_a_page(request):
            signed = await _plugin_sign_in(request)
            if signed:
                token, cookies = signed
                user = await plugin_user(request, token=token)
                if user is not None:
                    for cookie in cookies:
                        response.headers.append("set-cookie", cookie)
        if user is None:
            if _wants_a_page(request) and request.headers.get("sec-fetch-dest", "document") == "document":
                raise _HTTPException(status_code=302, headers={"Location": _login_url(request)})
            raise _HTTPException(status_code=401, detail="Sign in to Open-WebUI first.")
        if access == "admin" and user.role != "admin":
            raise _HTTPException(status_code=403, detail="Admins only.")
        return user

    return guard


# Mark a route by the type of a parameter: `async def purge(user: PluginAdmin)` is admin-only,
# `user: PluginUser` is any signed-in user, and the handler receives the user. This can only
# tighten what plugin_mount already requires (a signed-in user), never loosen it, and there is
# no marker for a public route.
PluginUser = _Annotated[_Any, _Depends(plugin_guard("user"))]
PluginAdmin = _Annotated[_Any, _Depends(plugin_guard("admin"))]


def plugin_chat_guard(permission: str = "write", param: str = "chat_id"):
    """A route dependency for a chat the signed-in user may access: 401 without a signed-in user,
    404 unless the user has `permission` ("read" or "write") on the chat named by the path
    parameter `param` (404, not 403, so a chat's existence is not revealed). It returns the chat
    id. A temporary chat ("local:...") has no stored record to check, so any signed-in user passes
    for one: keep nothing private there. `ReadableChat` and `WritableChat` are its two ready-made
    forms for marking a route."""
    if permission not in ("read", "write"):
        raise ValueError(f"permission must be 'read' or 'write', not {permission!r}")

    async def guard(request: _Request):
        user = await plugin_user(request)
        if user is None:
            raise _HTTPException(status_code=401, detail="Sign in to Open-WebUI first.")
        chat_id = request.path_params.get(param)
        if chat_id is None:
            raise RuntimeError(f"this route has no {{{param}}} path parameter to check access to")
        if not str(chat_id).startswith("local:"):
            from open_webui.models.chats import Chats

            if not await Chats.has_chat_access(chat_id, user, permission=permission):
                raise _HTTPException(status_code=404, detail="Not found")
        return chat_id

    return guard


# Mark a route by the chat it serves: `async def view(chat_id: WritableChat)` runs only for a
# signed-in user who can write to that chat, and receives the chat id.
ReadableChat = _Annotated[str, _Depends(plugin_chat_guard("read"))]
WritableChat = _Annotated[str, _Depends(plugin_chat_guard("write"))]


def _token_key() -> bytes:
    """Scoped to this function, so one plugin's tokens never validate in another."""
    from open_webui.env import WEBUI_SECRET_KEY

    return _hashlib.sha256(f"owpp-token:{plugin_function_id()}:{WEBUI_SECRET_KEY}".encode()).digest()


def _token_mac(subject: str, expiry: int) -> str:
    mac = _hmac.new(_token_key(), f"{subject}:{expiry}".encode(), _hashlib.sha256).digest()[:18]
    return _base64.urlsafe_b64encode(mac).decode()


def plugin_token(subject: str, hours: float = 12) -> str:
    """A short-lived signed token for `subject` (a chat id, say), for a route that cannot carry a
    session and so uses `plugin_mount(guard=...)`. Mint it only inside a route that required a
    signed-in user (the page that loads the sandboxed iframe), never in the chat, and verify it
    with `plugin_check_token`. Stateless, so every worker agrees; it is scoped to this function
    and to `subject`, and it expires.

    Do not put it in the iframe's address to avoid needing a session on the page: the address is
    stored in the chat's HTML. Inside the Artifacts panel the page gets a session only with
    Open-WebUI's "iframe Sandbox Allow Same Origin" on, which the plugin's README must state."""
    if hours <= 0:
        raise ValueError("a token must last more than zero hours")
    expiry = int(_time.time() + hours * 3600)
    return f"s.{expiry}.{_token_mac(str(subject), expiry)}"


def plugin_check_token(token, subject: str) -> bool:
    """Whether `token` is an unexpired plugin_token for exactly this `subject`."""
    parts = str(token).split(".")
    if len(parts) != 3 or parts[0] != "s" or not parts[1].isdigit():
        return False
    expiry = int(parts[1])
    if expiry < _time.time():
        return False
    return _hmac.compare_digest(parts[2].encode(), _token_mac(str(subject), expiry).encode())


async def _plugin_active_guard():
    await plugin_require_active()


def plugin_mount(
    app, router, prefix: str, owner: str = None, name: str = "", access: str = None, guard=None
) -> int:
    """Mount `router` (an APIRouter whose paths all live under `prefix`).

    - Every route requires a signed-in user (see plugin_guard): `access` is "user" or "admin"
      and defaults to "user"; "public" (that exact word) serves people who are not signed in, and
      is only ever chosen on purpose: `owpp check` lists every public mount.
    - `guard` replaces that check, only for routes that cannot carry an Open-WebUI session (an
      API called from a sandboxed iframe, which sends no cookies). It is a FastAPI dependency
      that must verify a credential minted from a real login; the library cannot check that
      for you. The function still has to be enabled.

    - Routes an earlier load of this same function mounted under `prefix` are
      dropped first, because Starlette cannot swap a handler in place and the old
      page or API would keep serving until a restart. Only routes whose endpoint
      belongs to this function are dropped, never Open-WebUI's own.
    - `name` is the mount's identity: mounting a name again replaces the earlier mount
      of that name wherever it was (so a configurable path that changed drops the old
      one by itself), and mounts with different names never replace each other (the
      static/ files, the function's page, its API). Give each mount its own name.
    - The new routes are moved ahead of Open-WebUI's catch-all mount at "/",
      which otherwise swallows anything added after it.
    Returns how many routes the router had."""
    prefix = "/" + prefix.strip("/ ")
    if prefix == "/":
        raise ValueError("a plugin may not mount at '/': it would shadow the app")
    if guard is not None and access is not None:
        raise ValueError("pass access or guard, not both")
    dependencies = (
        [_Depends(_plugin_active_guard), _Depends(guard)]
        if guard is not None
        else [_Depends(plugin_guard(access))]
    )
    owner = _routes_owner(owner or __name__)
    routes = app.router.routes

    def stale(route):
        if getattr(route, "plugin_mount_name", "") != name:
            return False
        # What a mount adds is tagged with its owner and name. Newer FastAPI adds one wrapper object
        # for the whole router (no path, no endpoint), and an earlier mount of this name may have
        # been at another prefix, so the tag is what identifies it.
        if getattr(route, "plugin_mount_owner", None) == owner:
            return True
        # Routes mounted before the tag existed: this function's endpoints under the prefix.
        endpoint = getattr(route, "endpoint", None)
        path = str(getattr(route, "path", None) or "")
        return (
            endpoint is not None
            and (path == prefix or path.startswith(prefix + "/"))
            and _routes_owner(getattr(endpoint, "__module__", None)) == owner
        )

    dropped = {id(r) for r in routes if stale(r)}
    if dropped:
        routes[:] = [r for r in routes if id(r) not in dropped]
    before = len(routes)
    app.include_router(router, dependencies=dependencies)
    added = routes[before:]
    for route in added:
        route.plugin_mount_name = name
        route.plugin_mount_owner = owner
    spa = next((i for i, r in enumerate(routes) if getattr(r, "name", None) == "spa-static-files"), None)
    if spa is not None and added:
        del routes[before:]
        routes[spa:spa] = added
    return len(getattr(router, "routes", ()))


async def plugin_require_active(function_id: str = None) -> None:
    """For a route dependency: routes outlive a disable or delete until the next
    restart, so answer 404 unless this function is still enabled."""
    if not await plugin_is_active(function_id):
        from fastapi import HTTPException

        raise HTTPException(status_code=404)


# end plugin routes library

import asyncio as _asyncio
import inspect as _inspect
import json as _json
import re as _re
import sys as _sys
import types as _types


class ChatNotSaved(RuntimeError):
    """The chat has no database row (yet). The message is what a model sees."""

    def __init__(self, chat_id: str):
        super().__init__(f"Chat {chat_id} is not saved yet: send a message first, then retry.")


def _chat_state() -> _types.ModuleType:
    """State shared by every plugin's copy of this code (the function's and the
    tool's are separate modules): the temporary chats' values and the locks."""
    state = _sys.modules.get("_plugin_chat_data")
    if state is None:
        state = _types.ModuleType("_plugin_chat_data")
        state.temp, state.locks = {}, {}
        _sys.modules["_plugin_chat_data"] = state
    return state


def _chat_key(key: str) -> str:
    """The key goes into SQL, so it is restricted to a plain identifier. Pick one
    per plugin (its id is a good choice); two plugins must not share one."""
    if not isinstance(key, str) or not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
        raise ValueError("a chat data key must be a plain identifier (letters, digits, _)")
    return key


def plugin_chat_is_temp(chat_id: str) -> bool:
    return str(chat_id).startswith("local:")


async def plugin_chat_read(chat_id: str, key: str):
    """The value saved under `key` for the chat, or None. Raises ChatNotSaved if
    the chat has no row."""
    key = _chat_key(key)
    if plugin_chat_is_temp(chat_id):
        return _chat_state().temp.get((key, chat_id))
    from open_webui.internal.db import get_async_db_context
    from open_webui.models.chats import Chat
    from sqlalchemy import select

    async with get_async_db_context() as session:
        row = (await session.execute(select(Chat.meta).filter_by(id=chat_id))).one_or_none()
    if row is None:
        raise ChatNotSaved(chat_id)
    meta = row[0] or {}
    if isinstance(meta, str):
        meta = _json.loads(meta)
    return meta.get(key)


async def plugin_chat_write(chat_id: str, value, key: str) -> None:
    """Save a JSON-serialisable value under `key`. Raises ChatNotSaved if the chat
    has no row."""
    key = _chat_key(key)
    if plugin_chat_is_temp(chat_id):
        _chat_state().temp[(key, chat_id)] = value
        return
    from open_webui.internal.db import get_async_db_context
    from open_webui.models.chats import Chat
    from sqlalchemy import select, text, update

    encoded = _json.dumps(value)
    table = Chat.__tablename__
    async with get_async_db_context() as session:
        dialect = session.get_bind().dialect.name
        # Set only our key, in place, so this never overwrites what Open-WebUI keeps
        # in meta (tags and the like), and leave updated_at alone so a write does
        # not reorder the chat list.
        if dialect == "sqlite":
            result = await session.execute(
                text(f"UPDATE {table} SET meta = json_set(COALESCE(meta, '{{}}'), '$.{key}', json(:v)) WHERE id = :id"),
                {"v": encoded, "id": chat_id},
            )
        elif dialect == "postgresql":
            result = await session.execute(
                text(
                    f"UPDATE {table} SET meta = CAST(COALESCE(CAST(meta AS jsonb), CAST('{{}}' AS jsonb)) "
                    f"|| jsonb_build_object('{key}', CAST(:v AS jsonb)) AS json) WHERE id = :id"
                ),
                {"v": encoded, "id": chat_id},
            )
        else:
            row = (await session.execute(select(Chat.meta).filter_by(id=chat_id))).one_or_none()
            if row is None:
                raise ChatNotSaved(chat_id)
            result = await session.execute(
                update(Chat).filter_by(id=chat_id).values(meta={**(row[0] or {}), key: value})
            )
        await session.commit()
    if result.rowcount == 0:
        raise ChatNotSaved(chat_id)


async def plugin_chat_update(chat_id: str, change, key: str, default=None):
    """Read-modify-write under a lock for this chat and key, so concurrent changes
    do not lose each other (within one process). `change(current, is_new)` gets the
    saved value, or `default` when nothing is saved, and returns the new value, or
    None to keep things as they are. Returns the value now in effect."""
    key = _chat_key(key)
    locks = _chat_state().locks
    lock = locks.get((key, chat_id))
    if lock is None:
        lock = locks[(key, chat_id)] = _asyncio.Lock()
    async with lock:
        saved = await plugin_chat_read(chat_id, key)
        current = default if saved is None else saved
        new = change(current, saved is None)
        if _inspect.isawaitable(new):
            new = await new
        if new is None:
            return current
        await plugin_chat_write(chat_id, new, key)
        return new


# end plugin chat data library

import base64 as _base64
import json as _json

# {path: {"content", "encoding"?}}
_TEMPLATES = _json.loads("{\"viewer.html\":{\"content\":\"<!doctype html>\\n<html>\\n<head>\\n<meta charset=\\\"utf-8\\\">\\n<meta name=\\\"viewport\\\" content=\\\"width=device-width, initial-scale=1\\\">\\n<title>Excalidraw</title>\\n<!--esm.sh-->\\n<link rel=\\\"stylesheet\\\" href=\\\"https://esm.sh/@excalidraw/excalidraw@__VERSION__/dist/prod/index.css\\\">\\n<script type=\\\"importmap\\\">\\n{\\\"imports\\\":{\\n  \\\"react\\\":\\\"https://esm.sh/react@18.3.1\\\",\\n  \\\"react/jsx-runtime\\\":\\\"https://esm.sh/react@18.3.1/jsx-runtime\\\",\\n  \\\"react-dom\\\":\\\"https://esm.sh/react-dom@18.3.1\\\",\\n  \\\"react-dom/client\\\":\\\"https://esm.sh/react-dom@18.3.1/client\\\",\\n  \\\"@excalidraw/excalidraw\\\":\\\"https://esm.sh/@excalidraw/excalidraw@__VERSION__?external=react,react-dom\\\"\\n}}\\n</script>\\n<!--/esm.sh-->\\n<!--hosted-->\\n<link rel=\\\"stylesheet\\\" href=\\\"__ASSETS_URL__/index.css\\\">\\n<!--/hosted-->\\n<style>\\nhtml,body,#root{height:100%;margin:0}\\n/* Opens libraries.excalidraw.com in a new window, which Open-WebUI's iframe\\n   sandbox (no allow-popups) blocks. The library itself still works. */\\n.library-menu-browse-button{display:none!important}\\n</style>\\n</head>\\n<body>\\n<div id=\\\"root\\\"></div>\\n<script type=\\\"module\\\">\\n// The server keeps one of the two marked blocks (CDN or self-hosted); the markers must not appear\\n// elsewhere in this file.\\n<!--esm.sh-->\\nwindow.EXCALIDRAW_ASSET_PATH =\\n  \\\"https://esm.sh/@excalidraw/excalidraw@__VERSION__/dist/prod/\\\";\\nconst React = await import(\\\"react\\\");\\nconst { createRoot } = await import(\\\"react-dom/client\\\");\\nconst { Excalidraw, MainMenu, convertToExcalidrawElements } =\\n  await import(\\\"@excalidraw/excalidraw\\\");\\n<!--/esm.sh-->\\n<!--hosted-->\\nwindow.EXCALIDRAW_ASSET_PATH = \\\"__ASSETS_URL__/\\\";\\nconst { React, createRoot, Excalidraw, MainMenu, convertToExcalidrawElements } =\\n  await import(\\\"__ASSETS_URL__/editor.js\\\");\\n<!--/hosted-->\\n\\n// The sandboxed panel sends no cookies, so API calls carry the token rendered into this page.\\nconst parts = location.pathname.split(\\\"/\\\");\\nconst id = decodeURIComponent(parts.pop());\\nparts.pop();\\nconst base = parts.join(\\\"/\\\");\\nconst token = \\\"__TOKEN__\\\";\\nconst url = (query = \\\"\\\") =>\\n  `${base}/api/scenes/${encodeURIComponent(id)}?t=${encodeURIComponent(token)}${query}`;\\nconst me = crypto.randomUUID();\\nconst dark = matchMedia(\\\"(prefers-color-scheme: dark)\\\").matches;\\nconst hash = (els) => els.map((e) => e.id + \\\":\\\" + e.version).join(\\\",\\\");\\n// A non-finite x/y blanks the canvas (zoom \\\"NaN%\\\") with no recovery; LLM skeletons can have\\n// one, so repair geometry before and after conversion.\\nconst num = (v) => (typeof v === \\\"boolean\\\" || v === \\\"\\\" ? NaN : Number(v));\\nconst finite = (v) => Number.isFinite(num(v));\\nconst mid = (e) => [\\n  num(e.x) + Math.abs(num(e.width) || 0) / 2,\\n  num(e.y) + Math.abs(num(e.height) || 0) / 2,\\n];\\n// Where the line from e's centre towards `to` leaves e's box, so a bound\\n// arrow starts and ends at the shapes rather than through their middles.\\nconst edge = (e, to) => {\\n  const [cx, cy] = mid(e);\\n  const [tx, ty] = to;\\n  const dx = tx - cx, dy = ty - cy;\\n  const w = Math.abs(num(e.width) || 0) / 2, h = Math.abs(num(e.height) || 0) / 2;\\n  const s = Math.min(dx ? w / Math.abs(dx) : Infinity, dy ? h / Math.abs(dy) : Infinity);\\n  return Number.isFinite(s) ? [cx + dx * s, cy + dy * s] : [cx, cy];\\n};\\nconst repair = (els, converted) => {\\n  const list = (Array.isArray(els) ? els : [])\\n    .filter((e) => e && typeof e === \\\"object\\\" && !Array.isArray(e))\\n    .map((e) => ({ ...e, id: e.id || crypto.randomUUID() }));\\n  const byId = new Map(list.map((e) => [e.id, e]));\\n  // A bound arrow without x/y would start at the origin; route it between its shapes.\\n  const route = (e) => {\\n    const a = byId.get(e.start?.id), b = byId.get(e.end?.id);\\n    if (!a || !b || !finite(a.x) || !finite(a.y) || !finite(b.x) || !finite(b.y)) return null;\\n    const p = edge(a, mid(b)), q = edge(b, mid(a));\\n    return { x: p[0], y: p[1], points: [[0, 0], [q[0] - p[0], q[1] - p[1]]] };\\n  };\\n  return list.map((source) => {\\n    const e = { ...source };\\n    const ends =\\n      !converted && (e.type === \\\"arrow\\\" || e.type === \\\"line\\\") && !(finite(e.x) && finite(e.y))\\n        ? route(e)\\n        : null;\\n    e.x = finite(e.x) ? num(e.x) : 0;\\n    e.y = finite(e.y) ? num(e.y) : 0;\\n    for (const k of [\\\"width\\\", \\\"height\\\", \\\"angle\\\", \\\"fontSize\\\"]) {\\n      const fallback = k === \\\"fontSize\\\" ? 16 : 0;\\n      if (!(k in e)) {\\n        if (converted && k !== \\\"fontSize\\\") e[k] = fallback;\\n        continue;\\n      }\\n      if (finite(e[k])) e[k] = num(e[k]);\\n      else if (converted) e[k] = fallback;\\n      else delete e[k];\\n    }\\n    if (Array.isArray(e.points)) {\\n      e.points = e.points\\n        .filter((p) => Array.isArray(p) && finite(p[0]) && finite(p[1]))\\n        .map(([x, y]) => [num(x), num(y)]);\\n      if (!e.points.length) {\\n        if (converted && (e.type === \\\"arrow\\\" || e.type === \\\"line\\\")) e.points = [[0, 0], [1, 0]];\\n        else delete e.points;\\n      }\\n    }\\n    if (ends) Object.assign(e, ends);\\n    return e;\\n  });\\n};\\n// Skeletons and full elements may be mixed; conversion fills in the skeletons.\\nconst normalize = (els) =>\\n  repair(convertToExcalidrawElements(repair(els, false), { regenerateIds: false }), true);\\n\\nlet api = null, version = -1, lastHash = \\\"\\\", pointerDown = false, timer = null;\\n\\nasync function save(elements) {\\n  timer = null;\\n  // text/plain keeps this a CORS \\\"simple\\\" request: no preflight.\\n  const r = await fetch(url(), {\\n    method: \\\"POST\\\",\\n    headers: { \\\"content-type\\\": \\\"text/plain;charset=utf-8\\\" },\\n    body: JSON.stringify({ client: me, elements }),\\n  });\\n  if (r.ok) version = (await r.json()).version;\\n}\\n\\nfunction onChange(elements) {\\n  const h = hash(elements);\\n  if (h === lastHash) return;\\n  lastHash = h;\\n  clearTimeout(timer);\\n  timer = setTimeout(() => save(elements), 700);\\n}\\n\\nfunction fit(els) {\\n  if (api && els.length) api.scrollToContent(els, { fitToViewport: true, animate: true });\\n}\\n\\n// Reset a non-finite viewport (blank canvas, \\\"NaN%\\\") and refit.\\nfunction recover() {\\n  if (!api) return;\\n  const s = api.getAppState();\\n  if (Number.isFinite(s.zoom?.value) && Number.isFinite(s.scrollX) && Number.isFinite(s.scrollY)) return;\\n  api.updateScene({ appState: { zoom: { value: 1 }, scrollX: 0, scrollY: 0 } });\\n  fit(api.getSceneElements());\\n}\\n\\nasync function poll() {\\n  try {\\n    if (api && !pointerDown && timer === null) {\\n      const d = await (await fetch(url(`&since=${version}`))).json();\\n      if (d.changed) {\\n        version = d.version;\\n        if (d.writer !== me) {\\n          const els = normalize(d.elements);\\n          lastHash = hash(els);\\n          api.updateScene({ elements: els });\\n          fit(els);\\n        }\\n      }\\n    }\\n  } catch (e) { /* server restarting; retry next tick */ }\\n  recover();\\n  setTimeout(poll, 1500);\\n}\\n\\nconst first = await (await fetch(url())).json();\\nversion = first.version;\\nconst initial = normalize(first.elements);\\nlastHash = hash(initial);\\n\\n// Pop-ups are blocked in the sandbox, so the menu offers only in-page items.\\nconst D = MainMenu.DefaultItems;\\nconst menu = React.createElement(\\n  MainMenu,\\n  null,\\n  React.createElement(D.SaveAsImage),\\n  React.createElement(D.Export),\\n  React.createElement(D.SearchMenu),\\n  React.createElement(D.ClearCanvas),\\n  React.createElement(MainMenu.Separator),\\n  React.createElement(D.ToggleTheme),\\n  React.createElement(D.ChangeCanvasBackground),\\n);\\n\\ncreateRoot(document.getElementById(\\\"root\\\")).render(\\n  React.createElement(Excalidraw, {\\n    initialData: { elements: initial, scrollToContent: initial.length > 0 },\\n    excalidrawAPI: (a) => { api = a; },\\n    onChange,\\n    onPointerDown: () => { pointerDown = true; },\\n    onPointerUp: () => { pointerDown = false; },\\n    theme: dark ? \\\"dark\\\" : \\\"light\\\",\\n    UIOptions: { canvasActions: { loadScene: false } },\\n  }, menu),\\n);\\npoll();\\n</script>\\n</body>\\n</html>\\n\"}}")


def plugin_template_files() -> list:
    return sorted(_TEMPLATES)


def plugin_template_bytes(path: str) -> bytes:
    entry = _TEMPLATES.get(path)
    if entry is None:
        raise FileNotFoundError(path)
    if entry.get("encoding") == "base64":
        return _base64.b64decode(entry["content"])
    return entry["content"].encode("utf-8")


def plugin_template_text(path: str) -> str:
    """A template as text, to be filled in."""
    return plugin_template_bytes(path).decode("utf-8")


# end plugin templates library

import copy as _copy
import json as _json

_CONFIG = _json.loads("{\"assets_url\":\"${EXCALIDRAW_ASSETS_URL:-}\"}")


def _plugin_config_merge(base: dict, over: dict) -> dict:
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _plugin_config_merge(base[key], value)
        else:
            base[key] = _copy.deepcopy(value)
    return base


def plugin_config(defaults: dict = None) -> dict:
    """The plugin's config.yaml laid over `defaults`: mappings merge key by key, anything else
    (a list, a number, a string) is replaced. `${NAME:-default}` templates in the file's values are
    filled from the container's environment (see plugin_env). A fresh copy, so callers may change it."""
    return _plugin_config_merge(_copy.deepcopy(defaults or {}), plugin_env(_CONFIG))


# end plugin config library
# Shared by the function and the tool: constants, the scene store, tokens and element helpers.

import json
import logging
import re
import secrets
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

PREFIX = "/excalidraw"
# Key the tool sets in show_excalidraw's result; its value is the artifact HTML.
MARKER = "excalidraw_artifact"
# Key under chat.meta that holds the drawing.
META_KEY = "excalidraw"
EXCALIDRAW_VERSION = "0.18.0"
NO_STORE = {"Cache-Control": "no-store"}
# The Artifacts iframe has an opaque origin, so API calls are cross-origin and cookie-free.
CORS = {**NO_STORE, "Access-Control-Allow-Origin": "*"}
_ID = re.compile(r"[A-Za-z0-9_:-]{1,128}")  # chat UUIDs, plus "local:..." temporary chats


# A scene is {"version", "writer", "elements", "updated_at"} under chat.meta["excalidraw"].
# Temporary chats have no row, so theirs live in memory until restart.


# The scene store is the `chat_data` library.
_NoChat = ChatNotSaved


def _empty() -> dict:
    return {"version": 0, "writer": "tool", "elements": []}


async def _load(chat_id: str) -> dict | None:
    """The chat's scene, or None if it has none. Raises _NoChat."""
    scene = await plugin_chat_read(chat_id, META_KEY)
    return scene if isinstance(scene, dict) and isinstance(scene.get("elements"), list) else None


async def _save(chat_id: str, scene: dict) -> None:
    await plugin_chat_write(chat_id, scene, META_KEY)


async def _mutate(chat_id: str, change: Callable, writer: str, pass_new: bool = False) -> dict:
    """Apply change(elements) under the chat's lock and save a new version.
    change may return None to keep the scene as it is."""

    def apply(current: dict | None, is_new: bool) -> dict | None:
        valid = isinstance(current, dict) and isinstance(current.get("elements"), list)
        scene = current if valid else _empty()
        elements = (
            change(scene["elements"], is_new or not valid)
            if pass_new
            else change(scene["elements"])
        )
        if elements is None:
            return None
        return {
            "version": scene["version"] + 1,
            "writer": writer,
            "elements": elements,
            "updated_at": int(time.time()),
        }

    return await plugin_chat_update(chat_id, apply, META_KEY, default=_empty()) or _empty()


# Fields worth showing the model; Excalidraw elements carry ~30 more.
_KEEP = (
    "id",
    "type",
    "x",
    "y",
    "width",
    "height",
    "text",
    "strokeColor",
    "backgroundColor",
    "points",
    "angle",
)


def _simplify(elements: list[dict]) -> list[dict]:
    """Compact view for the model: drop deleted, fold bound text into `label`."""
    labels = {
        e["containerId"]: e.get("text", "")
        for e in elements
        if e.get("type") == "text" and e.get("containerId") and not e.get("isDeleted")
    }
    out = []
    for e in elements:
        if e.get("isDeleted") or (e.get("type") == "text" and e.get("containerId")):
            continue
        s = {k: e[k] for k in _KEEP if k in e}
        label = labels.get(e.get("id")) or (
            e["label"].get("text") if isinstance(e.get("label"), dict) else None
        )
        if label:
            s["label"] = label
        for side in ("start", "end"):
            binding = e.get(f"{side}Binding")
            if isinstance(binding, dict) and binding.get("elementId"):
                s[side] = {"id": binding["elementId"]}
            elif isinstance(e.get(side), dict):
                s[side] = e[side]
        out.append(s)
    return out


def _with_ids(elements: list[dict]) -> list[dict]:
    """Models often omit ids; give each element one so it can be read, updated
    and deleted later. (Nested label/start/end skeleton fields are untouched.)"""
    return [e if e.get("id") else {**e, "id": secrets.token_urlsafe(6)} for e in elements]


def _merge(existing: list[dict], incoming: list[dict]) -> list[dict]:
    incoming = _with_ids(incoming)
    by_id = {e["id"]: e for e in incoming}
    merged = [by_id.pop(e.get("id"), e) for e in existing]
    return merged + [e for e in incoming if e["id"] in by_id]


def _as_list(elements: Any) -> list[dict]:
    """Models pass elements as a list, one object, or JSON text; accept all."""
    if isinstance(elements, str):
        elements = json.loads(elements)
    if isinstance(elements, dict):
        elements = [elements]
    return [json.loads(e) if isinstance(e, str) else e for e in elements or []]
# Serves the editor, adds it to replies as an artifact and keeps the Excalidraw tool installed.

import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# Editor assets: the browser loads React and Excalidraw from esm.sh (no integrity check), or
# from EXCALIDRAW_ASSETS_URL when self-hosted (self-host/build.sh). To upgrade Excalidraw, change
# EXCALIDRAW_VERSION in shared.py and self-host/package.json together.
VIEWER = plugin_template_text("viewer.html")  # templates/viewer.html, rendered per request below

# A plain http(s) URL or path, safe inside an HTML attribute and a JS string.
_ASSETS_URL = re.compile(r"(?:https?://|/)[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]*")


def _assets_url() -> str:
    """Where this deployment hosts the editor's files (config.yaml: assets_url), or "" for esm.sh."""
    url = str(plugin_config().get("assets_url") or "").strip().rstrip("/")
    if url and not _ASSETS_URL.fullmatch(url):
        log.warning(
            "Excalidraw: assets_url %r is not a plain http(s) URL or path; using esm.sh", url
        )
        return ""
    return url


def _editor_page(token: str) -> str:
    """The editor page for one signed-in view: the self-hosted head or the esm.sh one, the token."""
    url = _assets_url()
    keep, drop = ("hosted", "esm.sh") if url else ("esm.sh", "hosted")
    html = re.sub(
        rf"<!--{re.escape(drop)}-->.*?<!--/{re.escape(drop)}-->\n?", "", VIEWER, flags=re.S
    )
    html = re.sub(rf"<!--/?{re.escape(keep)}-->\n?", "", html)
    return (
        html.replace("__ASSETS_URL__", url)
        .replace("__VERSION__", EXCALIDRAW_VERSION)
        .replace("__TOKEN__", token)
    )


def _reply(body: dict) -> dict | None:
    """The assistant message this outlet run is for."""
    messages = body.get("messages") or []
    target = body.get("id")
    for m in reversed(messages):
        if target and m.get("id") == target:
            return m
    for m in reversed(messages):
        if m.get("role") == "assistant":
            return m
    return None


def _shown(message: dict) -> str:
    """The text of a reply, from content and its structured output."""
    return _text(message.get("content")) + "".join(
        _text(item.get("content"))
        for item in message.get("output") or []
        if item.get("type") == "message"
    )


def _artifacts(output: list[dict]) -> list[str]:
    found = []
    for item in output:
        if item.get("type") != "function_call_output":
            continue
        result = _first_json_object(_text(item.get("output")))
        if isinstance(result, dict) and isinstance(result.get(MARKER), str):
            found.append(result[MARKER])
    return found


def _first_json_object(text: str) -> Any:
    """The tool result, even if Open-WebUI appended context after it."""
    start = text.find("{")
    if start == -1:
        return None
    try:
        return json.JSONDecoder().raw_decode(text, start)[0]
    except ValueError:
        return None


def _text(value: Any) -> str:
    """Output fields are either a string or a list of {"text": ...} parts."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in value)
    return ""


class Filter:
    class Valves(BaseModel):
        SESSION_TOKEN_HOURS: int = Field(
            default=12,
            description="How long the editor's API token lasts once the page is opened.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.mounted = False
        # Global filters load at startup, so the routes are up before any chat; inlet/outlet retry.
        self._mount(plugin_app())

    async def inlet(self, body: dict, __request__=None) -> dict:
        self._ensure(__request__)
        await plugin_ensure()
        return body

    # ----------------------------------------------------------- artifact
    def outlet(self, body: dict, __request__=None) -> dict:
        self._ensure(__request__)
        message = _reply(body)
        if message is None:
            return body
        output = message.get("output") or []
        # The panel keeps blocks from every reply, so add the editor only once per chat.
        shown = "".join(
            _shown(m) for m in body.get("messages") or [] if m.get("role") == "assistant"
        )
        blocks = []
        for html in _artifacts(output):
            if html not in shown and html not in blocks:
                blocks.append(html)
        if not blocks:
            return body

        text = "".join(f"\n\n```html\n{html}\n```" for html in blocks)
        message["content"] = (message.get("content") or "") + text
        if output:
            output.append(
                {
                    "type": "message",
                    "id": f"msg_{MARKER}_{len(output)}",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text.lstrip()}],
                }
            )
        log.info(
            "Excalidraw: added %d artifact(s) to message %s",
            len(blocks),
            message.get("id"),
        )
        return body

    async def _stored_valves(self) -> "Filter.Valves":
        """Valves are only applied to this instance when a chat runs the
        filter, so read them fresh outside one. The editor polls its API every
        couple of seconds, so a read is reused for a few seconds."""
        return await plugin_stored_valves(self.Valves, ttl=10)

    # ------------------------------------------------------- editor routes
    def _ensure(self, request) -> None:
        if not self.mounted and request is not None:
            self._mount(request.app)

    def _mount(self, app) -> None:
        if app is None:
            return

        async def authorised(chat_id: str, t: str = "") -> str:
            # The sandboxed panel sends no cookies, so the API takes the chat-bound token the page was
            # rendered with instead of a session.
            if not _ID.fullmatch(chat_id) or not plugin_check_token(t, chat_id):
                raise HTTPException(404, "Not found")
            return chat_id

        page = APIRouter(prefix=PREFIX)
        api = APIRouter(prefix=PREFIX)

        # WritableChat: signed in and allowed to write to this chat.
        @page.get("/view/{chat_id}", response_class=HTMLResponse)
        async def view(chat_id: WritableChat):
            if not _ID.fullmatch(chat_id):
                raise HTTPException(404, "Not found")
            valves = await self._stored_valves()
            token = plugin_token(chat_id, valves.SESSION_TOKEN_HOURS)
            return HTMLResponse(_editor_page(token), headers=NO_STORE)

        @api.get("/api/scenes/{chat_id}")
        async def get_scene(chat_id: str, since: int = -1):
            try:
                scene = await _load(chat_id) or _empty()
            except _NoChat:
                raise HTTPException(404, "Not found") from None
            if scene["version"] == since:
                return JSONResponse({"changed": False, "version": since}, headers=CORS)
            return JSONResponse({"changed": True, **scene}, headers=CORS)

        # A text/plain POST is a CORS simple request: no preflight.
        @api.post("/api/scenes/{chat_id}")
        async def put_scene(request: Request, chat_id: str):
            try:
                body = json.loads(await request.body())
                elements, client = body["elements"], str(body["client"])
                if not isinstance(elements, list):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise HTTPException(400, "expected {client, elements}") from None
            try:
                scene = await _mutate(chat_id, lambda _: elements, client)
            except _NoChat:
                raise HTTPException(404, "Not found") from None
            return JSONResponse({"version": scene["version"]}, headers=CORS)

        # The page mount replaces any earlier routes; the API mount uses the token guard.
        plugin_mount(app, page, PREFIX)
        plugin_mount(app, api, PREFIX, name="api", guard=authorised)
        self.mounted = True
        log.info("Excalidraw: mounted %s/*", PREFIX)


# =============================================================== plugin runtime
# Appended to a plugin's function by the bundler (src/owpp/bundle.py) when the
# plugin also declares a tool or skills (docs/runtime.md). The function is the parent:
# while it is enabled this installs (and keeps current) the plugin's tool and
# skills, and when it is disabled or deleted it removes them again. Edit this
# file in src/owpp/runtime/, not in a deployed copy.
import asyncio as _asyncio
import json as _json
import logging as _logging
import sys as _sys
import time as _time
import types as _types
from typing import Optional as _Optional

_plog = _logging.getLogger(__name__ + ".plugin")
# {"tools": [{id, name, access, self, valves, content}], "skills": [{id, name, description, access, files: [{path, content, encoding?}]}]}
_PLUGIN = _json.loads("{\"tools\":[{\"id\":\"excalidraw\",\"name\":\"Excalidraw\",\"access\":\"public\",\"self\":false,\"valves\":{},\"content\":\"\\\"\\\"\\\"\\ntitle: Excalidraw\\ndescription: Show, read and change the shared Excalidraw drawing of the chat.\\n\\\"\\\"\\\"\\n\\nimport asyncio as _asyncio\\nimport inspect as _inspect\\nimport json as _json\\nimport re as _re\\nimport sys as _sys\\nimport types as _types\\n\\n\\nclass ChatNotSaved(RuntimeError):\\n    \\\"\\\"\\\"The chat has no database row (yet). The message is what a model sees.\\\"\\\"\\\"\\n\\n    def __init__(self, chat_id: str):\\n        super().__init__(f\\\"Chat {chat_id} is not saved yet: send a message first, then retry.\\\")\\n\\n\\ndef _chat_state() -> _types.ModuleType:\\n    \\\"\\\"\\\"State shared by every plugin's copy of this code (the function's and the\\n    tool's are separate modules): the temporary chats' values and the locks.\\\"\\\"\\\"\\n    state = _sys.modules.get(\\\"_plugin_chat_data\\\")\\n    if state is None:\\n        state = _types.ModuleType(\\\"_plugin_chat_data\\\")\\n        state.temp, state.locks = {}, {}\\n        _sys.modules[\\\"_plugin_chat_data\\\"] = state\\n    return state\\n\\n\\ndef _chat_key(key: str) -> str:\\n    \\\"\\\"\\\"The key goes into SQL, so it is restricted to a plain identifier. Pick one\\n    per plugin (its id is a good choice); two plugins must not share one.\\\"\\\"\\\"\\n    if not isinstance(key, str) or not _re.fullmatch(r\\\"[A-Za-z_][A-Za-z0-9_]{0,63}\\\", key):\\n        raise ValueError(\\\"a chat data key must be a plain identifier (letters, digits, _)\\\")\\n    return key\\n\\n\\ndef plugin_chat_is_temp(chat_id: str) -> bool:\\n    return str(chat_id).startswith(\\\"local:\\\")\\n\\n\\nasync def plugin_chat_read(chat_id: str, key: str):\\n    \\\"\\\"\\\"The value saved under `key` for the chat, or None. Raises ChatNotSaved if\\n    the chat has no row.\\\"\\\"\\\"\\n    key = _chat_key(key)\\n    if plugin_chat_is_temp(chat_id):\\n        return _chat_state().temp.get((key, chat_id))\\n    from open_webui.internal.db import get_async_db_context\\n    from open_webui.models.chats import Chat\\n    from sqlalchemy import select\\n\\n    async with get_async_db_context() as session:\\n        row = (await session.execute(select(Chat.meta).filter_by(id=chat_id))).one_or_none()\\n    if row is None:\\n        raise ChatNotSaved(chat_id)\\n    meta = row[0] or {}\\n    if isinstance(meta, str):\\n        meta = _json.loads(meta)\\n    return meta.get(key)\\n\\n\\nasync def plugin_chat_write(chat_id: str, value, key: str) -> None:\\n    \\\"\\\"\\\"Save a JSON-serialisable value under `key`. Raises ChatNotSaved if the chat\\n    has no row.\\\"\\\"\\\"\\n    key = _chat_key(key)\\n    if plugin_chat_is_temp(chat_id):\\n        _chat_state().temp[(key, chat_id)] = value\\n        return\\n    from open_webui.internal.db import get_async_db_context\\n    from open_webui.models.chats import Chat\\n    from sqlalchemy import select, text, update\\n\\n    encoded = _json.dumps(value)\\n    table = Chat.__tablename__\\n    async with get_async_db_context() as session:\\n        dialect = session.get_bind().dialect.name\\n        # Set only our key, in place, so this never overwrites what Open-WebUI keeps\\n        # in meta (tags and the like), and leave updated_at alone so a write does\\n        # not reorder the chat list.\\n        if dialect == \\\"sqlite\\\":\\n            result = await session.execute(\\n                text(f\\\"UPDATE {table} SET meta = json_set(COALESCE(meta, '{{}}'), '$.{key}', json(:v)) WHERE id = :id\\\"),\\n                {\\\"v\\\": encoded, \\\"id\\\": chat_id},\\n            )\\n        elif dialect == \\\"postgresql\\\":\\n            result = await session.execute(\\n                text(\\n                    f\\\"UPDATE {table} SET meta = CAST(COALESCE(CAST(meta AS jsonb), CAST('{{}}' AS jsonb)) \\\"\\n                    f\\\"|| jsonb_build_object('{key}', CAST(:v AS jsonb)) AS json) WHERE id = :id\\\"\\n                ),\\n                {\\\"v\\\": encoded, \\\"id\\\": chat_id},\\n            )\\n        else:\\n            row = (await session.execute(select(Chat.meta).filter_by(id=chat_id))).one_or_none()\\n            if row is None:\\n                raise ChatNotSaved(chat_id)\\n            result = await session.execute(\\n                update(Chat).filter_by(id=chat_id).values(meta={**(row[0] or {}), key: value})\\n            )\\n        await session.commit()\\n    if result.rowcount == 0:\\n        raise ChatNotSaved(chat_id)\\n\\n\\nasync def plugin_chat_update(chat_id: str, change, key: str, default=None):\\n    \\\"\\\"\\\"Read-modify-write under a lock for this chat and key, so concurrent changes\\n    do not lose each other (within one process). `change(current, is_new)` gets the\\n    saved value, or `default` when nothing is saved, and returns the new value, or\\n    None to keep things as they are. Returns the value now in effect.\\\"\\\"\\\"\\n    key = _chat_key(key)\\n    locks = _chat_state().locks\\n    lock = locks.get((key, chat_id))\\n    if lock is None:\\n        lock = locks[(key, chat_id)] = _asyncio.Lock()\\n    async with lock:\\n        saved = await plugin_chat_read(chat_id, key)\\n        current = default if saved is None else saved\\n        new = change(current, saved is None)\\n        if _inspect.isawaitable(new):\\n            new = await new\\n        if new is None:\\n            return current\\n        await plugin_chat_write(chat_id, new, key)\\n        return new\\n\\n\\n# end plugin chat data library\\n# Shared by the function and the tool: constants, the scene store, tokens and element helpers.\\n\\nimport json\\nimport logging\\nimport re\\nimport secrets\\nimport time\\nfrom collections.abc import Callable\\nfrom typing import Any\\n\\nlog = logging.getLogger(__name__)\\n\\nPREFIX = \\\"/excalidraw\\\"\\n# Key the tool sets in show_excalidraw's result; its value is the artifact HTML.\\nMARKER = \\\"excalidraw_artifact\\\"\\n# Key under chat.meta that holds the drawing.\\nMETA_KEY = \\\"excalidraw\\\"\\nEXCALIDRAW_VERSION = \\\"0.18.0\\\"\\nNO_STORE = {\\\"Cache-Control\\\": \\\"no-store\\\"}\\n# The Artifacts iframe has an opaque origin, so API calls are cross-origin and cookie-free.\\nCORS = {**NO_STORE, \\\"Access-Control-Allow-Origin\\\": \\\"*\\\"}\\n_ID = re.compile(r\\\"[A-Za-z0-9_:-]{1,128}\\\")  # chat UUIDs, plus \\\"local:...\\\" temporary chats\\n\\n\\n# A scene is {\\\"version\\\", \\\"writer\\\", \\\"elements\\\", \\\"updated_at\\\"} under chat.meta[\\\"excalidraw\\\"].\\n# Temporary chats have no row, so theirs live in memory until restart.\\n\\n\\n# The scene store is the `chat_data` library.\\n_NoChat = ChatNotSaved\\n\\n\\ndef _empty() -> dict:\\n    return {\\\"version\\\": 0, \\\"writer\\\": \\\"tool\\\", \\\"elements\\\": []}\\n\\n\\nasync def _load(chat_id: str) -> dict | None:\\n    \\\"\\\"\\\"The chat's scene, or None if it has none. Raises _NoChat.\\\"\\\"\\\"\\n    scene = await plugin_chat_read(chat_id, META_KEY)\\n    return scene if isinstance(scene, dict) and isinstance(scene.get(\\\"elements\\\"), list) else None\\n\\n\\nasync def _save(chat_id: str, scene: dict) -> None:\\n    await plugin_chat_write(chat_id, scene, META_KEY)\\n\\n\\nasync def _mutate(chat_id: str, change: Callable, writer: str, pass_new: bool = False) -> dict:\\n    \\\"\\\"\\\"Apply change(elements) under the chat's lock and save a new version.\\n    change may return None to keep the scene as it is.\\\"\\\"\\\"\\n\\n    def apply(current: dict | None, is_new: bool) -> dict | None:\\n        valid = isinstance(current, dict) and isinstance(current.get(\\\"elements\\\"), list)\\n        scene = current if valid else _empty()\\n        elements = (\\n            change(scene[\\\"elements\\\"], is_new or not valid)\\n            if pass_new\\n            else change(scene[\\\"elements\\\"])\\n        )\\n        if elements is None:\\n            return None\\n        return {\\n            \\\"version\\\": scene[\\\"version\\\"] + 1,\\n            \\\"writer\\\": writer,\\n            \\\"elements\\\": elements,\\n            \\\"updated_at\\\": int(time.time()),\\n        }\\n\\n    return await plugin_chat_update(chat_id, apply, META_KEY, default=_empty()) or _empty()\\n\\n\\n# Fields worth showing the model; Excalidraw elements carry ~30 more.\\n_KEEP = (\\n    \\\"id\\\",\\n    \\\"type\\\",\\n    \\\"x\\\",\\n    \\\"y\\\",\\n    \\\"width\\\",\\n    \\\"height\\\",\\n    \\\"text\\\",\\n    \\\"strokeColor\\\",\\n    \\\"backgroundColor\\\",\\n    \\\"points\\\",\\n    \\\"angle\\\",\\n)\\n\\n\\ndef _simplify(elements: list[dict]) -> list[dict]:\\n    \\\"\\\"\\\"Compact view for the model: drop deleted, fold bound text into `label`.\\\"\\\"\\\"\\n    labels = {\\n        e[\\\"containerId\\\"]: e.get(\\\"text\\\", \\\"\\\")\\n        for e in elements\\n        if e.get(\\\"type\\\") == \\\"text\\\" and e.get(\\\"containerId\\\") and not e.get(\\\"isDeleted\\\")\\n    }\\n    out = []\\n    for e in elements:\\n        if e.get(\\\"isDeleted\\\") or (e.get(\\\"type\\\") == \\\"text\\\" and e.get(\\\"containerId\\\")):\\n            continue\\n        s = {k: e[k] for k in _KEEP if k in e}\\n        label = labels.get(e.get(\\\"id\\\")) or (\\n            e[\\\"label\\\"].get(\\\"text\\\") if isinstance(e.get(\\\"label\\\"), dict) else None\\n        )\\n        if label:\\n            s[\\\"label\\\"] = label\\n        for side in (\\\"start\\\", \\\"end\\\"):\\n            binding = e.get(f\\\"{side}Binding\\\")\\n            if isinstance(binding, dict) and binding.get(\\\"elementId\\\"):\\n                s[side] = {\\\"id\\\": binding[\\\"elementId\\\"]}\\n            elif isinstance(e.get(side), dict):\\n                s[side] = e[side]\\n        out.append(s)\\n    return out\\n\\n\\ndef _with_ids(elements: list[dict]) -> list[dict]:\\n    \\\"\\\"\\\"Models often omit ids; give each element one so it can be read, updated\\n    and deleted later. (Nested label/start/end skeleton fields are untouched.)\\\"\\\"\\\"\\n    return [e if e.get(\\\"id\\\") else {**e, \\\"id\\\": secrets.token_urlsafe(6)} for e in elements]\\n\\n\\ndef _merge(existing: list[dict], incoming: list[dict]) -> list[dict]:\\n    incoming = _with_ids(incoming)\\n    by_id = {e[\\\"id\\\"]: e for e in incoming}\\n    merged = [by_id.pop(e.get(\\\"id\\\"), e) for e in existing]\\n    return merged + [e for e in incoming if e[\\\"id\\\"] in by_id]\\n\\n\\ndef _as_list(elements: Any) -> list[dict]:\\n    \\\"\\\"\\\"Models pass elements as a list, one object, or JSON text; accept all.\\\"\\\"\\\"\\n    if isinstance(elements, str):\\n        elements = json.loads(elements)\\n    if isinstance(elements, dict):\\n        elements = [elements]\\n    return [json.loads(e) if isinstance(e, str) else e for e in elements or []]\\n# Lets the model show, read and change the chat's drawing.\\n\\nimport json\\nfrom typing import Any\\nfrom urllib.parse import quote\\n\\nELEMENT_DOC = \\\"\\\"\\\"\\\\\\nElements use Excalidraw's skeleton format. Every element, arrows included, needs\\na finite numeric \\\"x\\\" and \\\"y\\\"; without them the editor canvas goes blank:\\n  {\\\"type\\\":\\\"rectangle\\\",\\\"id\\\":\\\"a\\\",\\\"x\\\":0,\\\"y\\\":0,\\\"width\\\":160,\\\"height\\\":80,\\\"label\\\":{\\\"text\\\":\\\"API\\\"}}\\n  {\\\"type\\\":\\\"ellipse\\\"|\\\"diamond\\\", ... same fields}\\n  {\\\"type\\\":\\\"text\\\",\\\"x\\\":0,\\\"y\\\":0,\\\"text\\\":\\\"Hello\\\",\\\"fontSize\\\":20}\\n  {\\\"type\\\":\\\"arrow\\\"|\\\"line\\\",\\\"x\\\":0,\\\"y\\\":0,\\\"points\\\":[[0,0],[200,0]]}\\n  Give shapes an \\\"id\\\" so arrows can connect to them; arrow points are relative\\n  to the arrow's x/y, so put that x/y where the arrow starts:\\n  {\\\"type\\\":\\\"arrow\\\",\\\"x\\\":160,\\\"y\\\":40,\\\"points\\\":[[0,0],[120,0]],\\\"start\\\":{\\\"id\\\":\\\"a\\\"},\\\"end\\\":{\\\"id\\\":\\\"b\\\"},\\\"label\\\":{\\\"text\\\":\\\"calls\\\"}}\\nOptional: strokeColor, backgroundColor, fillStyle (\\\"solid\\\"|\\\"hachure\\\"|\\\"cross-hatch\\\"),\\nstrokeStyle (\\\"solid\\\"|\\\"dashed\\\"|\\\"dotted\\\"), roughness (0 clean, 1 sketchy).\\nLayout: ~200px between box columns, ~120px between rows; y grows downward.\\\"\\\"\\\"\\n\\n\\nclass Tools:\\n    # -------------------------------------------------------------- tools\\n\\n    async def show_excalidraw(\\n        self,\\n        elements: list[dict[str, Any]] | None = None,\\n        __metadata__: dict | None = None,\\n    ) -> dict:\\n        \\\"\\\"\\\"\\n        Show this chat's Excalidraw drawing to the user as a live editor they can\\n        draw in. Creates it on first use. Call this whenever the user asks for a\\n        diagram, sketch, whiteboard or drawing, passing the initial elements in\\n        the same call. The editor opens in the side panel on its own; do not\\n        paste a link, iframe or code. Call it once per chat: the panel keeps the\\n        editor open across later replies, so later changes go through\\n        upsert_excalidraw_elements and appear in the same editor within about\\n        two seconds. Call it again only if the user asks to see the drawing.\\n\\n        :param elements: Optional elements to add before showing. See the element format below.\\n        \\\"\\\"\\\"\\n        chat_id = _tool_chat_id(__metadata__)\\n        incoming = _as_list(elements)\\n        scene = await _mutate(\\n            chat_id,\\n            lambda current, new: (\\n                _merge(current, incoming) if incoming else (None if not new else [])\\n            ),\\n            \\\"tool\\\",\\n            pass_new=True,\\n        )\\n        src = f\\\"{PREFIX}/view/{quote(chat_id, safe='')}\\\"\\n        # The function's outlet adds this to the reply as an ```html block for the Artifacts panel.\\n        artifact = (\\n            f'<iframe src=\\\"{src}\\\" title=\\\"Excalidraw\\\" '\\n            'style=\\\"position:fixed;inset:0;width:100%;height:100%;border:0\\\" '\\n            'allow=\\\"clipboard-read; clipboard-write\\\"></iframe>'\\n        )\\n        return {\\n            \\\"status\\\": (\\n                \\\"The editor opens in the Artifacts side panel when your reply \\\"\\n                \\\"finishes. Do not paste a link, iframe or code for it.\\\"\\n            ),\\n            \\\"version\\\": scene[\\\"version\\\"],\\n            \\\"note\\\": \\\"Use upsert_excalidraw_elements to change it and read_excalidraw to see the user's edits.\\\",\\n            MARKER: artifact,\\n        }\\n\\n    async def read_excalidraw(self, __metadata__: dict | None = None) -> str:\\n        \\\"\\\"\\\"\\n        Read the drawing as the user currently sees it, including their edits.\\n        Bound text is folded into each shape's `label`; arrows list `start` and\\n        `end` shape ids. Call this before changing a drawing the user has been\\n        editing.\\n        \\\"\\\"\\\"\\n        scene = await _load(_tool_chat_id(__metadata__)) or _empty()\\n        return json.dumps({\\\"version\\\": scene[\\\"version\\\"], \\\"elements\\\": _simplify(scene[\\\"elements\\\"])})\\n\\n    async def upsert_excalidraw_elements(\\n        self, elements: list[dict[str, Any]], __metadata__: dict | None = None\\n    ) -> str:\\n        \\\"\\\"\\\"\\n        Add elements to the drawing, or update existing ones by id. Elements not\\n        mentioned are untouched, so the user's work is preserved. Prefer this\\n        over replace_excalidraw_elements. The open editor updates by itself.\\n\\n        :param elements: Elements to add or update. See the element format below.\\n        \\\"\\\"\\\"\\n        incoming = _as_list(elements)\\n        scene = await _mutate(\\n            _tool_chat_id(__metadata__),\\n            lambda current: _merge(current, incoming),\\n            \\\"tool\\\",\\n        )\\n        return f\\\"Updated. The open editor will show it shortly (version {scene['version']}).\\\"\\n\\n    async def replace_excalidraw_elements(\\n        self, elements: list[dict[str, Any]], __metadata__: dict | None = None\\n    ) -> str:\\n        \\\"\\\"\\\"\\n        Replace everything in the drawing. This discards the user's edits, so use\\n        it only to start over.\\n\\n        :param elements: The complete new set of elements. See the element format below.\\n        \\\"\\\"\\\"\\n        incoming = _with_ids(_as_list(elements))\\n        scene = await _mutate(_tool_chat_id(__metadata__), lambda _: incoming, \\\"tool\\\")\\n        return f\\\"Replaced (version {scene['version']}).\\\"\\n\\n    async def delete_excalidraw_elements(\\n        self, ids: list[str], __metadata__: dict | None = None\\n    ) -> str:\\n        \\\"\\\"\\\"\\n        Remove elements from the drawing by id (get ids from read_excalidraw).\\n\\n        :param ids: Ids of the elements to remove.\\n        \\\"\\\"\\\"\\n        drop = set(ids)\\n        scene = await _mutate(\\n            _tool_chat_id(__metadata__),\\n            lambda current: [\\n                e for e in current if e.get(\\\"id\\\") not in drop and e.get(\\\"containerId\\\") not in drop\\n            ],\\n            \\\"tool\\\",\\n        )\\n        return f\\\"Deleted (version {scene['version']}).\\\"\\n\\n\\n# Inserted before the :param lines so it stays in the tool description.\\nfor _fn in (\\n    Tools.show_excalidraw,\\n    Tools.upsert_excalidraw_elements,\\n    Tools.replace_excalidraw_elements,\\n):\\n    _head, _sep, _params = (_fn.__doc__ or \\\"\\\").partition(\\\":param\\\")\\n    _fn.__doc__ = _head.rstrip() + \\\"\\\\n\\\\n\\\" + ELEMENT_DOC + \\\"\\\\n\\\\n        \\\" + _sep + _params\\n\\n\\ndef _tool_chat_id(__metadata__: dict | None) -> str:\\n    chat_id = (__metadata__ or {}).get(\\\"chat_id\\\")\\n    if not chat_id or not _ID.fullmatch(chat_id):\\n        raise RuntimeError(\\\"No chat id: send a message first, then retry.\\\")\\n    return chat_id\\n\\n\\n# =============================================================== plugin runtime\\n# Appended to a plugin's function by the bundler (src/owpp/bundle.py) when the\\n# plugin also declares a tool or skills (docs/runtime.md). The function is the parent:\\n# while it is enabled this installs (and keeps current) the plugin's tool and\\n# skills, and when it is disabled or deleted it removes them again. Edit this\\n# file in src/owpp/runtime/, not in a deployed copy.\\nimport asyncio as _asyncio\\nimport json as _json\\nimport logging as _logging\\nimport sys as _sys\\nimport time as _time\\nimport types as _types\\nfrom typing import Optional as _Optional\\n\\n_plog = _logging.getLogger(__name__ + \\\".plugin\\\")\\n# {\\\"tools\\\": [{id, name, access, self, valves, content}], \\\"skills\\\": [{id, name, description, access, files: [{path, content, encoding?}]}]}\\n_PLUGIN = _json.loads(\\\"{\\\\\\\"tools\\\\\\\":[{\\\\\\\"id\\\\\\\":\\\\\\\"excalidraw\\\\\\\"}],\\\\\\\"skills\\\\\\\":[]}\\\")\\n_PLUGIN_TAG = \\\"plugin:\\\"  # skills carry plugin:<function id> in their tags\\n_PLUGIN_EVENTS = {\\n    \\\"function.enabled\\\",\\n    \\\"function.disabled\\\",\\n    \\\"function.updated\\\",\\n    \\\"function.valves_updated\\\",  # INSTALL_TOOLS, INSTALL_SKILLS, TOOL_VALVES apply on save\\n    \\\"function.deleted\\\",\\n}\\n\\n\\ndef _plugin_module_id(prefix: str) -> _Optional[str]:\\n    \\\"\\\"\\\"Open-WebUI names a module <prefix>_<id>_<32 hex chars>.\\\"\\\"\\\"\\n    name = __name__\\n    if not name.startswith(prefix + \\\"_\\\"):\\n        return None\\n    return name[len(prefix) + 1 :].rsplit(\\\"_\\\", 1)[0] or None\\n\\n\\ndef _plugin_state(function_id: str) -> _types.ModuleType:\\n    \\\"\\\"\\\"State that survives this module being loaded again (Open-WebUI reloads\\n    function modules), keyed by function id.\\\"\\\"\\\"\\n    key = f\\\"_plugin_runtime_{function_id}\\\"\\n    module = _sys.modules.get(key)\\n    if module is None:\\n        module = _types.ModuleType(key)\\n        module.sink = None\\n        module.last = 0.0\\n        _sys.modules[key] = module\\n    return module\\n\\n\\ndef _plugin_public_read() -> list:\\n    \\\"\\\"\\\"Read for every signed-in user: Open-WebUI's `user:*` grant. (Not its `anyone:*` grant,\\n    which is a separate no-auth audience that its tool and skill access checks ignore.)\\\"\\\"\\\"\\n    return [{\\\"principal_type\\\": \\\"user\\\", \\\"principal_id\\\": \\\"*\\\", \\\"permission\\\": \\\"read\\\"}]\\n\\n\\ndef _plugin_grant(grant) -> tuple:\\n    if isinstance(grant, dict):\\n        return (grant.get(\\\"principal_type\\\"), grant.get(\\\"principal_id\\\"), grant.get(\\\"permission\\\"))\\n    return (\\n        getattr(grant, \\\"principal_type\\\", None),\\n        getattr(grant, \\\"principal_id\\\", None),\\n        getattr(grant, \\\"permission\\\", None),\\n    )\\n\\n\\nasync def _plugin_repair_public(resource_type: str, item: dict, grants) -> None:\\n    \\\"\\\"\\\"Runtimes before this one granted a public tool or skill to `anyone:*`, which\\n    Open-WebUI does not honour for them, so only admins could use it. Swap exactly that\\n    grant for `user:*` read, once, and leave any other grants as the admin set them.\\\"\\\"\\\"\\n    if item[\\\"access\\\"] != \\\"public\\\":\\n        return\\n    triples = [_plugin_grant(g) for g in grants or []]\\n    if (\\\"anyone\\\", \\\"*\\\", \\\"read\\\") not in triples or (\\\"user\\\", \\\"*\\\", \\\"read\\\") in triples:\\n        return\\n    from open_webui.models.access_grants import AccessGrants\\n\\n    kept = [\\n        {\\\"principal_type\\\": a, \\\"principal_id\\\": b, \\\"permission\\\": c}\\n        for a, b, c in triples\\n        if (a, b, c) != (\\\"anyone\\\", \\\"*\\\", \\\"read\\\")\\n    ]\\n    await AccessGrants.set_access_grants(resource_type, item[\\\"id\\\"], kept + _plugin_public_read())\\n    _plog.info(\\\"plugin: %s %r made readable by every user\\\", resource_type, item[\\\"id\\\"])\\n\\n\\nasync def _plugin_valves(function_id: str) -> dict:\\n    \\\"\\\"\\\"The function's stored valves that steer this runtime: INSTALL_TOOLS and\\n    INSTALL_SKILLS (default on) and TOOL_VALVES, a JSON {tool id: {valve: value}}.\\n    Read from the database because a function's own valves are only applied to\\n    its instance when a chat runs it.\\\"\\\"\\\"\\n    from open_webui.models.functions import Functions\\n\\n    stored = await Functions.get_function_valves_by_id(function_id) or {}\\n    overrides = {}\\n    raw = stored.get(\\\"TOOL_VALVES\\\")\\n    if raw:\\n        try:\\n            overrides = _json.loads(raw) if isinstance(raw, str) else dict(raw)\\n            if not isinstance(overrides, dict):\\n                raise ValueError(\\\"not an object\\\")\\n        except ValueError:\\n            _plog.warning(\\\"plugin %s: TOOL_VALVES is not a JSON object; ignored\\\", function_id)\\n            overrides = {}\\n    return {\\n        \\\"tools\\\": stored.get(\\\"INSTALL_TOOLS\\\", True) is not False,\\n        \\\"skills\\\": stored.get(\\\"INSTALL_SKILLS\\\", True) is not False,\\n        \\\"tool_valves\\\": overrides,\\n    }\\n\\n\\nasync def _plugin_sync(function_id: str) -> None:\\n    \\\"\\\"\\\"Make Open-WebUI match the function's state. Never raises.\\\"\\\"\\\"\\n    try:\\n        from open_webui.models.functions import Functions\\n\\n        function = await Functions.get_function_by_id(function_id)\\n        if function is None or not function.is_active:\\n            await _plugin_remove(function_id)\\n            return\\n        valves = await _plugin_valves(function_id)\\n        if valves[\\\"tools\\\"]:\\n            await _plugin_install_tools(function, valves[\\\"tool_valves\\\"])\\n        else:\\n            await _plugin_remove(function_id, skills=False)\\n        if valves[\\\"skills\\\"]:\\n            await _plugin_install_skills(function)\\n        else:\\n            await _plugin_remove(function_id, tools=False)\\n    except Exception:\\n        _plog.exception(\\\"plugin %s: could not sync its tool and skills\\\", function_id)\\n\\n\\nasync def _plugin_apply_valves(item: dict, overrides: dict) -> None:\\n    \\\"\\\"\\\"Set the valves plugin.yaml and TOOL_VALVES declare on the tool; other\\n    valves keep whatever the admin set.\\\"\\\"\\\"\\n    wanted = {**(item.get(\\\"valves\\\") or {}), **(overrides.get(item[\\\"id\\\"]) or {})}\\n    if not wanted:\\n        return\\n    from open_webui.models.tools import Tools\\n    from open_webui.utils.plugin import load_tool_module_by_id\\n\\n    current = await Tools.get_tool_valves_by_id(item[\\\"id\\\"]) or {}\\n    merged = {**current, **wanted}\\n    if merged == current:\\n        return\\n    tool = await Tools.get_tool_by_id(item[\\\"id\\\"])\\n    module, _, _ = await load_tool_module_by_id(item[\\\"id\\\"], content=tool.content)\\n    if hasattr(module, \\\"Valves\\\"):\\n        try:\\n            module.Valves(**merged)  # refuse values the tool would reject\\n        except Exception as error:\\n            _plog.warning(\\\"plugin: valves for tool %r not applied: %s\\\", item[\\\"id\\\"], error)\\n            return\\n    await Tools.update_tool_valves_by_id(item[\\\"id\\\"], merged)\\n    _plog.info(\\\"plugin: set valves %s on tool %r\\\", sorted(wanted), item[\\\"id\\\"])\\n\\n\\nasync def _plugin_install_tools(function, overrides: dict) -> None:\\n    if not _PLUGIN[\\\"tools\\\"]:\\n        return\\n    # Imported lazily: these only exist inside Open-WebUI.\\n    from open_webui.models.tools import ToolForm, ToolMeta, Tools\\n    from open_webui.utils.plugin import load_tool_module_by_id, replace_imports\\n    from open_webui.utils.tools import get_tool_specs\\n\\n    for item in _PLUGIN[\\\"tools\\\"]:\\n        content = replace_imports(function.content if item[\\\"self\\\"] else item[\\\"content\\\"])\\n        tool = await Tools.get_tool_by_id(item[\\\"id\\\"])\\n        if tool is not None:\\n            parent = (tool.meta.manifest or {}).get(\\\"parent_function_id\\\")\\n            if parent != function.id:\\n                _plog.warning(\\n                    \\\"plugin %s: tool %r exists and is not this plugin's; left alone\\\",\\n                    function.id,\\n                    item[\\\"id\\\"],\\n                )\\n                continue\\n            await _plugin_repair_public(\\\"tool\\\", item, getattr(tool, \\\"access_grants\\\", None))\\n            if tool.content == content:\\n                await _plugin_apply_valves(item, overrides)\\n                continue\\n        module, frontmatter, _ = await load_tool_module_by_id(item[\\\"id\\\"], content=content)\\n        meta = ToolMeta(\\n            description=(frontmatter or {}).get(\\\"description\\\"),\\n            # The parent id lets the tool's own module notice, after a restart,\\n            # that the function was disabled while Open-WebUI was down.\\n            manifest={**(frontmatter or {}), \\\"parent_function_id\\\": function.id},\\n            has_user_valves=hasattr(module, \\\"UserValves\\\"),\\n        )\\n        specs = get_tool_specs(module)\\n        if tool is None:\\n            form = ToolForm(\\n                id=item[\\\"id\\\"],\\n                name=item[\\\"name\\\"],\\n                content=content,\\n                meta=meta,\\n                access_grants=_plugin_public_read() if item[\\\"access\\\"] == \\\"public\\\" else [],\\n            )\\n            await Tools.insert_new_tool(function.user_id, form, specs, module=module)\\n            _plog.info(\\\"plugin %s: installed tool %r\\\", function.id, item[\\\"id\\\"])\\n        else:\\n            # Access grants are left as the admin set them.\\n            await Tools.update_tool_by_id(\\n                item[\\\"id\\\"],\\n                {\\\"content\\\": content, \\\"meta\\\": meta.model_dump(), \\\"specs\\\": specs},\\n                user_id=function.user_id,\\n                module=module,\\n            )\\n            _plog.info(\\\"plugin %s: updated tool %r\\\", function.id, item[\\\"id\\\"])\\n        await _plugin_apply_valves(item, overrides)\\n\\n\\nasync def _plugin_install_skills(function) -> None:\\n    if not _PLUGIN[\\\"skills\\\"]:\\n        return\\n    from open_webui.models.skills import SkillForm, SkillMeta, Skills\\n\\n    tag = _PLUGIN_TAG + function.id\\n    for item in _PLUGIN[\\\"skills\\\"]:\\n        skill = await Skills.get_skill_by_id(item[\\\"id\\\"])\\n        meta = SkillMeta(tags=[tag])\\n        # The whole skill folder: SKILL.md plus any supporting files, sorted by path\\n        # the way Open-WebUI stores them.\\n        files = sorted(item[\\\"files\\\"], key=lambda f: f[\\\"path\\\"])\\n        if skill is None:\\n            await Skills.insert_new_skill(\\n                function.user_id,\\n                SkillForm(\\n                    id=item[\\\"id\\\"],\\n                    name=item[\\\"name\\\"],\\n                    description=item[\\\"description\\\"],\\n                    files=files,\\n                    meta=meta,\\n                    is_active=True,\\n                    access_grants=_plugin_public_read() if item[\\\"access\\\"] == \\\"public\\\" else [],\\n                ),\\n            )\\n            _plog.info(\\\"plugin %s: installed skill %r (%d files)\\\", function.id, item[\\\"id\\\"], len(files))\\n        elif tag not in (skill.meta.tags or []):\\n            _plog.warning(\\n                \\\"plugin %s: skill %r exists and is not this plugin's; left alone\\\",\\n                function.id,\\n                item[\\\"id\\\"],\\n            )\\n            continue\\n        else:\\n            await _plugin_repair_public(\\\"skill\\\", item, getattr(skill, \\\"access_grants\\\", None))\\n        if skill is not None and (skill.name, skill.description, (skill.data or {}).get(\\\"files\\\")) != (\\n            item[\\\"name\\\"],\\n            item[\\\"description\\\"],\\n            files,\\n        ):\\n            await Skills.update_skill_by_id(\\n                item[\\\"id\\\"],\\n                {\\n                    \\\"name\\\": item[\\\"name\\\"],\\n                    \\\"description\\\": item[\\\"description\\\"],\\n                    \\\"files\\\": files,\\n                    \\\"meta\\\": meta.model_dump(),\\n                    # File updates must name the version they were based on.\\n                    \\\"expected_version_id\\\": skill.version_id,\\n                },\\n                user_id=function.user_id,\\n            )\\n            _plog.info(\\\"plugin %s: updated skill %r (%d files)\\\", function.id, item[\\\"id\\\"], len(files))\\n\\n\\nasync def _plugin_remove(function_id: str, tools: bool = True, skills: bool = True) -> None:\\n    \\\"\\\"\\\"Remove what this plugin installed (the tools, the skills or both). Safe to\\n    call repeatedly; only things marked as this function's are touched.\\\"\\\"\\\"\\n    from open_webui.models.skills import Skills\\n    from open_webui.models.tools import Tools\\n\\n    for item in _PLUGIN[\\\"tools\\\"] if tools else []:\\n        tool = await Tools.get_tool_by_id(item[\\\"id\\\"])\\n        if tool is not None and (tool.meta.manifest or {}).get(\\\"parent_function_id\\\") == function_id:\\n            await Tools.delete_tool_by_id(item[\\\"id\\\"])\\n            _plog.info(\\\"plugin %s: removed tool %r (function disabled or gone)\\\", function_id, item[\\\"id\\\"])\\n    for item in _PLUGIN[\\\"skills\\\"] if skills else []:\\n        skill = await Skills.get_skill_by_id(item[\\\"id\\\"])\\n        if skill is not None and (_PLUGIN_TAG + function_id) in (skill.meta.tags or []):\\n            await Skills.delete_skill_by_id(item[\\\"id\\\"])\\n            _plog.info(\\\"plugin %s: removed skill %r (function disabled or gone)\\\", function_id, item[\\\"id\\\"])\\n\\n\\nasync def plugin_ensure() -> None:\\n    \\\"\\\"\\\"Sync now unless a sync ran in the last few seconds. Cheap enough to call\\n    from a Filter's inlet, which retries a sync that failed at startup.\\\"\\\"\\\"\\n    function_id = _plugin_module_id(\\\"function\\\")\\n    if not function_id:\\n        return\\n    state = _plugin_state(function_id)\\n    if _time.monotonic() - state.last < 10:\\n        return\\n    state.last = _time.monotonic()\\n    await _plugin_sync(function_id)\\n\\n\\nclass _PluginSink:\\n    \\\"\\\"\\\"Open-WebUI stops loading a function once it is disabled, so the function's\\n    own code never sees that. An event sink is the hook that still runs; it\\n    resyncs when this function is enabled, disabled, updated or deleted, or when an\\n    admin saves its valves (a user saving their own UserValves is not a reason).\\\"\\\"\\\"\\n\\n    function_id: _Optional[str] = None\\n\\n    # Open-WebUI 0.10.0 calls handle_event(app, event, request=...); newer\\n    # versions call handle_event(request, event). Accept either.\\n    async def handle_event(self, first, event, **kwargs) -> None:\\n        if not self.function_id:\\n            return\\n        get = event.get if isinstance(event, dict) else lambda key: getattr(event, key, None)\\n        if (get(\\\"subject\\\") or {}).get(\\\"id\\\") != self.function_id:\\n            return\\n        if get(\\\"event\\\") not in _PLUGIN_EVENTS:\\n            return\\n        if (get(\\\"data\\\") or {}).get(\\\"scope\\\") == \\\"user\\\":\\n            return\\n        await _plugin_sync(self.function_id)\\n\\n\\nasync def _plugin_check_parent() -> None:\\n    \\\"\\\"\\\"Run when the tool's module loads: remove the plugin if its function was\\n    disabled while Open-WebUI was down (the function never loaded to notice).\\\"\\\"\\\"\\n    tool_id = _plugin_module_id(\\\"tool\\\")\\n    if not tool_id:\\n        return\\n    try:\\n        from open_webui.models.functions import Functions\\n        from open_webui.models.tools import Tools\\n\\n        tool = await Tools.get_tool_by_id(tool_id)\\n        parent = ((tool.meta.manifest or {}) if tool else {}).get(\\\"parent_function_id\\\")\\n        if not parent:\\n            return\\n        function = await Functions.get_function_by_id(parent)\\n        if function is None or not function.is_active:\\n            await _plugin_remove(parent)\\n    except Exception:\\n        _plog.exception(\\\"plugin: could not check the tool's parent function\\\")\\n\\n\\ndef _plugin_start() -> None:\\n    try:\\n        loop = _asyncio.get_running_loop()\\n    except RuntimeError:\\n        return\\n    function_id = _plugin_module_id(\\\"function\\\")\\n    if function_id:\\n        try:\\n            from open_webui.events import EVENT_SINKS\\n        except Exception:\\n            EVENT_SINKS = None\\n        state = _plugin_state(function_id)\\n        if EVENT_SINKS is not None and not isinstance(state.sink, _PluginSink):\\n            if state.sink is not None:\\n                try:\\n                    EVENT_SINKS.remove(state.sink)\\n                except ValueError:\\n                    pass\\n            state.sink = _PluginSink()\\n            EVENT_SINKS.append(state.sink)\\n        if state.sink is not None:\\n            state.sink.function_id = function_id\\n        loop.create_task(plugin_ensure())\\n    elif _plugin_module_id(\\\"tool\\\"):\\n        loop.create_task(_plugin_check_parent())\\n\\n\\n_plugin_start()\\n\"}],\"skills\":[]}")
_PLUGIN_TAG = "plugin:"  # skills carry plugin:<function id> in their tags
_PLUGIN_EVENTS = {
    "function.enabled",
    "function.disabled",
    "function.updated",
    "function.valves_updated",  # INSTALL_TOOLS, INSTALL_SKILLS, TOOL_VALVES apply on save
    "function.deleted",
}


def _plugin_module_id(prefix: str) -> _Optional[str]:
    """Open-WebUI names a module <prefix>_<id>_<32 hex chars>."""
    name = __name__
    if not name.startswith(prefix + "_"):
        return None
    return name[len(prefix) + 1 :].rsplit("_", 1)[0] or None


def _plugin_state(function_id: str) -> _types.ModuleType:
    """State that survives this module being loaded again (Open-WebUI reloads
    function modules), keyed by function id."""
    key = f"_plugin_runtime_{function_id}"
    module = _sys.modules.get(key)
    if module is None:
        module = _types.ModuleType(key)
        module.sink = None
        module.last = 0.0
        _sys.modules[key] = module
    return module


def _plugin_public_read() -> list:
    """Read for every signed-in user: Open-WebUI's `user:*` grant. (Not its `anyone:*` grant,
    which is a separate no-auth audience that its tool and skill access checks ignore.)"""
    return [{"principal_type": "user", "principal_id": "*", "permission": "read"}]


def _plugin_grant(grant) -> tuple:
    if isinstance(grant, dict):
        return (grant.get("principal_type"), grant.get("principal_id"), grant.get("permission"))
    return (
        getattr(grant, "principal_type", None),
        getattr(grant, "principal_id", None),
        getattr(grant, "permission", None),
    )


async def _plugin_repair_public(resource_type: str, item: dict, grants) -> None:
    """Runtimes before this one granted a public tool or skill to `anyone:*`, which
    Open-WebUI does not honour for them, so only admins could use it. Swap exactly that
    grant for `user:*` read, once, and leave any other grants as the admin set them."""
    if item["access"] != "public":
        return
    triples = [_plugin_grant(g) for g in grants or []]
    if ("anyone", "*", "read") not in triples or ("user", "*", "read") in triples:
        return
    from open_webui.models.access_grants import AccessGrants

    kept = [
        {"principal_type": a, "principal_id": b, "permission": c}
        for a, b, c in triples
        if (a, b, c) != ("anyone", "*", "read")
    ]
    await AccessGrants.set_access_grants(resource_type, item["id"], kept + _plugin_public_read())
    _plog.info("plugin: %s %r made readable by every user", resource_type, item["id"])


async def _plugin_valves(function_id: str) -> dict:
    """The function's stored valves that steer this runtime: INSTALL_TOOLS and
    INSTALL_SKILLS (default on) and TOOL_VALVES, a JSON {tool id: {valve: value}}.
    Read from the database because a function's own valves are only applied to
    its instance when a chat runs it."""
    from open_webui.models.functions import Functions

    stored = await Functions.get_function_valves_by_id(function_id) or {}
    overrides = {}
    raw = stored.get("TOOL_VALVES")
    if raw:
        try:
            overrides = _json.loads(raw) if isinstance(raw, str) else dict(raw)
            if not isinstance(overrides, dict):
                raise ValueError("not an object")
        except ValueError:
            _plog.warning("plugin %s: TOOL_VALVES is not a JSON object; ignored", function_id)
            overrides = {}
    return {
        "tools": stored.get("INSTALL_TOOLS", True) is not False,
        "skills": stored.get("INSTALL_SKILLS", True) is not False,
        "tool_valves": overrides,
    }


async def _plugin_sync(function_id: str) -> None:
    """Make Open-WebUI match the function's state. Never raises."""
    try:
        from open_webui.models.functions import Functions

        function = await Functions.get_function_by_id(function_id)
        if function is None or not function.is_active:
            await _plugin_remove(function_id)
            return
        valves = await _plugin_valves(function_id)
        if valves["tools"]:
            await _plugin_install_tools(function, valves["tool_valves"])
        else:
            await _plugin_remove(function_id, skills=False)
        if valves["skills"]:
            await _plugin_install_skills(function)
        else:
            await _plugin_remove(function_id, tools=False)
    except Exception:
        _plog.exception("plugin %s: could not sync its tool and skills", function_id)


async def _plugin_apply_valves(item: dict, overrides: dict) -> None:
    """Set the valves plugin.yaml and TOOL_VALVES declare on the tool; other
    valves keep whatever the admin set."""
    wanted = {**(item.get("valves") or {}), **(overrides.get(item["id"]) or {})}
    if not wanted:
        return
    from open_webui.models.tools import Tools
    from open_webui.utils.plugin import load_tool_module_by_id

    current = await Tools.get_tool_valves_by_id(item["id"]) or {}
    merged = {**current, **wanted}
    if merged == current:
        return
    tool = await Tools.get_tool_by_id(item["id"])
    module, _, _ = await load_tool_module_by_id(item["id"], content=tool.content)
    if hasattr(module, "Valves"):
        try:
            module.Valves(**merged)  # refuse values the tool would reject
        except Exception as error:
            _plog.warning("plugin: valves for tool %r not applied: %s", item["id"], error)
            return
    await Tools.update_tool_valves_by_id(item["id"], merged)
    _plog.info("plugin: set valves %s on tool %r", sorted(wanted), item["id"])


async def _plugin_install_tools(function, overrides: dict) -> None:
    if not _PLUGIN["tools"]:
        return
    # Imported lazily: these only exist inside Open-WebUI.
    from open_webui.models.tools import ToolForm, ToolMeta, Tools
    from open_webui.utils.plugin import load_tool_module_by_id, replace_imports
    from open_webui.utils.tools import get_tool_specs

    for item in _PLUGIN["tools"]:
        content = replace_imports(function.content if item["self"] else item["content"])
        tool = await Tools.get_tool_by_id(item["id"])
        if tool is not None:
            parent = (tool.meta.manifest or {}).get("parent_function_id")
            if parent != function.id:
                _plog.warning(
                    "plugin %s: tool %r exists and is not this plugin's; left alone",
                    function.id,
                    item["id"],
                )
                continue
            await _plugin_repair_public("tool", item, getattr(tool, "access_grants", None))
            if tool.content == content:
                await _plugin_apply_valves(item, overrides)
                continue
        module, frontmatter, _ = await load_tool_module_by_id(item["id"], content=content)
        meta = ToolMeta(
            description=(frontmatter or {}).get("description"),
            # The parent id lets the tool's own module notice, after a restart,
            # that the function was disabled while Open-WebUI was down.
            manifest={**(frontmatter or {}), "parent_function_id": function.id},
            has_user_valves=hasattr(module, "UserValves"),
        )
        specs = get_tool_specs(module)
        if tool is None:
            form = ToolForm(
                id=item["id"],
                name=item["name"],
                content=content,
                meta=meta,
                access_grants=_plugin_public_read() if item["access"] == "public" else [],
            )
            await Tools.insert_new_tool(function.user_id, form, specs, module=module)
            _plog.info("plugin %s: installed tool %r", function.id, item["id"])
        else:
            # Access grants are left as the admin set them.
            await Tools.update_tool_by_id(
                item["id"],
                {"content": content, "meta": meta.model_dump(), "specs": specs},
                user_id=function.user_id,
                module=module,
            )
            _plog.info("plugin %s: updated tool %r", function.id, item["id"])
        await _plugin_apply_valves(item, overrides)


async def _plugin_install_skills(function) -> None:
    if not _PLUGIN["skills"]:
        return
    from open_webui.models.skills import SkillForm, SkillMeta, Skills

    tag = _PLUGIN_TAG + function.id
    for item in _PLUGIN["skills"]:
        skill = await Skills.get_skill_by_id(item["id"])
        meta = SkillMeta(tags=[tag])
        # The whole skill folder: SKILL.md plus any supporting files, sorted by path
        # the way Open-WebUI stores them.
        files = sorted(item["files"], key=lambda f: f["path"])
        if skill is None:
            await Skills.insert_new_skill(
                function.user_id,
                SkillForm(
                    id=item["id"],
                    name=item["name"],
                    description=item["description"],
                    files=files,
                    meta=meta,
                    is_active=True,
                    access_grants=_plugin_public_read() if item["access"] == "public" else [],
                ),
            )
            _plog.info("plugin %s: installed skill %r (%d files)", function.id, item["id"], len(files))
        elif tag not in (skill.meta.tags or []):
            _plog.warning(
                "plugin %s: skill %r exists and is not this plugin's; left alone",
                function.id,
                item["id"],
            )
            continue
        else:
            await _plugin_repair_public("skill", item, getattr(skill, "access_grants", None))
        if skill is not None and (skill.name, skill.description, (skill.data or {}).get("files")) != (
            item["name"],
            item["description"],
            files,
        ):
            await Skills.update_skill_by_id(
                item["id"],
                {
                    "name": item["name"],
                    "description": item["description"],
                    "files": files,
                    "meta": meta.model_dump(),
                    # File updates must name the version they were based on.
                    "expected_version_id": skill.version_id,
                },
                user_id=function.user_id,
            )
            _plog.info("plugin %s: updated skill %r (%d files)", function.id, item["id"], len(files))


async def _plugin_remove(function_id: str, tools: bool = True, skills: bool = True) -> None:
    """Remove what this plugin installed (the tools, the skills or both). Safe to
    call repeatedly; only things marked as this function's are touched."""
    from open_webui.models.skills import Skills
    from open_webui.models.tools import Tools

    for item in _PLUGIN["tools"] if tools else []:
        tool = await Tools.get_tool_by_id(item["id"])
        if tool is not None and (tool.meta.manifest or {}).get("parent_function_id") == function_id:
            await Tools.delete_tool_by_id(item["id"])
            _plog.info("plugin %s: removed tool %r (function disabled or gone)", function_id, item["id"])
    for item in _PLUGIN["skills"] if skills else []:
        skill = await Skills.get_skill_by_id(item["id"])
        if skill is not None and (_PLUGIN_TAG + function_id) in (skill.meta.tags or []):
            await Skills.delete_skill_by_id(item["id"])
            _plog.info("plugin %s: removed skill %r (function disabled or gone)", function_id, item["id"])


async def plugin_ensure() -> None:
    """Sync now unless a sync ran in the last few seconds. Cheap enough to call
    from a Filter's inlet, which retries a sync that failed at startup."""
    function_id = _plugin_module_id("function")
    if not function_id:
        return
    state = _plugin_state(function_id)
    if _time.monotonic() - state.last < 10:
        return
    state.last = _time.monotonic()
    await _plugin_sync(function_id)


class _PluginSink:
    """Open-WebUI stops loading a function once it is disabled, so the function's
    own code never sees that. An event sink is the hook that still runs; it
    resyncs when this function is enabled, disabled, updated or deleted, or when an
    admin saves its valves (a user saving their own UserValves is not a reason)."""

    function_id: _Optional[str] = None

    # Open-WebUI 0.10.0 calls handle_event(app, event, request=...); newer
    # versions call handle_event(request, event). Accept either.
    async def handle_event(self, first, event, **kwargs) -> None:
        if not self.function_id:
            return
        get = event.get if isinstance(event, dict) else lambda key: getattr(event, key, None)
        if (get("subject") or {}).get("id") != self.function_id:
            return
        if get("event") not in _PLUGIN_EVENTS:
            return
        if (get("data") or {}).get("scope") == "user":
            return
        await _plugin_sync(self.function_id)


async def _plugin_check_parent() -> None:
    """Run when the tool's module loads: remove the plugin if its function was
    disabled while Open-WebUI was down (the function never loaded to notice)."""
    tool_id = _plugin_module_id("tool")
    if not tool_id:
        return
    try:
        from open_webui.models.functions import Functions
        from open_webui.models.tools import Tools

        tool = await Tools.get_tool_by_id(tool_id)
        parent = ((tool.meta.manifest or {}) if tool else {}).get("parent_function_id")
        if not parent:
            return
        function = await Functions.get_function_by_id(parent)
        if function is None or not function.is_active:
            await _plugin_remove(parent)
    except Exception:
        _plog.exception("plugin: could not check the tool's parent function")


def _plugin_start() -> None:
    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        return
    function_id = _plugin_module_id("function")
    if function_id:
        try:
            from open_webui.events import EVENT_SINKS
        except Exception:
            EVENT_SINKS = None
        state = _plugin_state(function_id)
        if EVENT_SINKS is not None and not isinstance(state.sink, _PluginSink):
            if state.sink is not None:
                try:
                    EVENT_SINKS.remove(state.sink)
                except ValueError:
                    pass
            state.sink = _PluginSink()
            EVENT_SINKS.append(state.sink)
        if state.sink is not None:
            state.sink.function_id = function_id
        loop.create_task(plugin_ensure())
    elif _plugin_module_id("tool"):
        loop.create_task(_plugin_check_parent())


_plugin_start()
