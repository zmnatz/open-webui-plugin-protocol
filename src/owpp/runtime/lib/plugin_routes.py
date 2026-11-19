# Plugin routes library (docs/libraries.md), inserted by `include: [routes]`.
# Mounts a FastAPI router on Open-WebUI so it survives an in-place code update
# and is not shadowed by the single-page-app catch-all, and puts every route behind a
# signed-in user. A route is open to any signed-in user and is marked `user: PluginAdmin` (or a chat
# marker) where it needs more, never checked by hand in the handler. Only a mount that says
# access="public", in so many words, serves people who are not signed in.

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
