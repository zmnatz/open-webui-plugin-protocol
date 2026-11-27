"""Open-WebUI's HTTP API, as owpp speaks it: signing in and signing up, waiting for the instance
to be healthy, the functions endpoints, the `meta` the deploy stores with each function (and
`owpp import --instance` reads back), and the rewrite Open-WebUI makes to code before it stores it.
The deploy, `owpp import` and `owpp live`'s stack all talk to an instance through an `OpenWebUI`;
the live tests' `Api` is a thin layer over the same one.

Every request goes through a `Fetch`: urllib (`urllib_fetch`) in production, an in-memory
Open-WebUI in owpp's tests. Only the standard library is needed (docs/adr/0003).
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, NamedTuple

from .errors import OwppError

FUNCTIONS = "/api/v1/functions"
AUTHS = "/api/v1/auths"

# Stored in each deployed function's meta (meta.managed_by); the only thing pruning acts
# on, so a deploy never touches a function it did not create. Override it per deployment
# (--managed-by / OWPP_MANAGED_BY), and never change it for an instance that already has
# functions deployed: they would look hand-made and stop being pruned.
MANAGED_BY = "open-webui-plugin-protocol"


# ---- the transport ------------------------------------------------------------------


class HttpResponse(NamedTuple):
    status: int
    text: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


# (method, url, headers, body) -> the response, whatever its status. Raises OSError when the
# instance cannot be reached.
Fetch = Callable[[str, str, "dict[str, str] | None", "bytes | None"], HttpResponse]


def urllib_fetch(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    context: ssl.SSLContext | None = None,
    timeout: float = 60,
) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:  # noqa: S310 (admin-chosen URL)
            return HttpResponse(response.status, response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return HttpResponse(e.code, e.read().decode("utf-8", "replace"))


def _parsed(text: str) -> Any:
    """A response's JSON, its text when it is not JSON, None when it is empty."""
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def field_of(obj: Any, key: str) -> Any:
    """`obj[key]` when Open-WebUI answered with an object, else None."""
    return obj.get(key) if isinstance(obj, dict) else None


# ---- what Open-WebUI stores -------------------------------------------------------------


def replace_imports(content: Any) -> str:
    """Open-WebUI rewrites these import prefixes in the code before it stores it
    (utils/plugin.py replace_imports), so the stored copy of a file that uses them never
    equals the file. The deploy compares against the rewritten text, and the mock Open-WebUI
    stores it."""
    return (
        str(content or "")
        .replace("from utils", "from open_webui.utils")
        .replace("from apps", "from open_webui.apps")
        .replace("from main", "from open_webui.main")
        .replace("from config", "from open_webui.config")
    )


@dataclass(frozen=True)
class FunctionMeta:
    """What the deploy stores in a function's `meta`, and what `owpp import --instance` reads
    back: the ownership marker, the description the UI shows, the commit of each git source it
    was deployed from, and what plugin.yaml requires of the instance. `requires` is None when
    it was never recorded (a function made by hand, or deployed by an owpp from before it)."""

    managed_by: str = ""
    description: str = ""
    sources: dict = field(default_factory=dict)
    requires: dict | None = None

    @classmethod
    def of(cls, function: Any) -> FunctionMeta:
        """The meta of a function as Open-WebUI returns it."""
        meta = field_of(function, "meta")
        meta = meta if isinstance(meta, dict) else {}
        requires = meta.get("requires")
        return cls(
            managed_by=meta.get("managed_by") or "",
            description=meta.get("description") or "",
            sources=meta.get("sources") or {},
            requires=requires if isinstance(requires, dict) else None,
        )

    def stored(self) -> dict:
        """The meta as it is sent. An update replaces meta, so it is always sent whole."""
        meta: dict = {"description": self.description, "managed_by": self.managed_by}
        if self.sources:
            meta["sources"] = self.sources
        meta["requires"] = self.requires or {}
        return meta


# ---- the API -------------------------------------------------------------------------------


class SignInRefused(OwppError):
    """Open-WebUI did not sign in (or sign up) with what it was given; says why, as
    `HTTP <status>: <detail>`."""


def _tls_hint(error: ssl.SSLError) -> str:
    if isinstance(error, ssl.SSLCertVerificationError):
        return (
            f"{error.verify_message or error}: give the CA that signed its certificate with "
            "OPEN_WEBUI_CA_CERT (or --ca-cert)"
        )
    text = str(error)
    if "CERTIFICATE_REQUIRED" in text or "HANDSHAKE_FAILURE" in text:
        return (
            f"{text}: it may want a client certificate, OPEN_WEBUI_CLIENT_CERT (or --client-cert)"
        )
    return text


@dataclass
class OpenWebUI:
    """One Open-WebUI, reached through `fetch`, as the account `token` belongs to (none: only
    signing in and the health check work)."""

    base_url: str
    fetch: Fetch = field(default=urllib_fetch, repr=False)
    token: str = field(default="", repr=False)

    def as_account(self, token: str) -> OpenWebUI:
        return replace(self, token=token)

    # ---- requests

    def _send(self, method: str, path: str, body: Any = None) -> HttpResponse:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        return self.fetch(method, f"{self.base_url}{path}", headers, data)

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        """(status, parsed body), on an error too: Open-WebUI says what went wrong in `detail`."""
        res = self._send(method, path, body)
        return res.status, _parsed(res.text)

    def call(self, method: str, path: str, body: Any = None) -> Any:
        """The parsed body; raises OwppError when the status is not a success."""
        res = self._send(method, path, body)
        if not res.ok:
            raise OwppError(f"{method} {path} -> HTTP {res.status}: {res.text[:300]}")
        return _parsed(res.text)

    # ---- health

    def healthy(self) -> bool:
        """Whether /health answers. Raises OwppError on a TLS failure, which waiting will not fix."""
        try:
            return self.fetch("GET", f"{self.base_url}/health", None, None).ok
        except OSError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, ssl.SSLError):
                raise OwppError(f"{self.base_url}: TLS failed ({_tls_hint(reason)})") from e
            return False  # not up yet

    def wait_for_health(
        self,
        attempts: int = 6,
        delay: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Tries /health `attempts` times, `delay` seconds apart. Open-WebUI may still be
        starting: a deploy's stack redeploys on the same push, and `owpp live` has just started
        its container."""
        for i in range(attempts):
            if self.healthy():
                return
            if i < attempts - 1:
                sleep(delay)
        raise OwppError(f"{self.base_url}/health did not answer in time")

    # ---- signing in and signing up

    def _session(self, path: str, body: dict) -> dict:
        res = self.as_account("")._send("POST", f"{AUTHS}{path}", body)
        data = _parsed(res.text)
        if res.ok and isinstance(data, dict) and data.get("token"):
            return data
        detail = field_of(data, "detail")
        raise SignInRefused(f"HTTP {res.status}{f': {detail}' if detail else ''}")

    def sign_in(self, email: str, password: str) -> dict:
        """Open-WebUI's own accounts (both empty: an open sign-in, which it answers when sign-in
        is off or a proxy adds the trusted email header). The session: token, role, email…"""
        return self._session("/signin", {"email": email, "password": password})

    def sign_in_ldap(self, user: str, password: str) -> dict:
        return self._session("/ldap", {"user": user, "password": password})

    def exchange_oidc(self, provider: str, token: str) -> dict:
        """An OIDC token for a session; the instance must set ENABLE_OAUTH_TOKEN_EXCHANGE=true."""
        return self._session(f"/oauth/{provider}/token/exchange", {"token": token})

    def sign_up(self, name: str, email: str, password: str) -> dict:
        """A new account; on a fresh instance the first is its admin."""
        return self._session("/signup", {"name": name, "email": email, "password": password})

    def add_user(self, name: str, email: str, password: str, role: str = "user") -> Any:
        """An account added by the admin this is signed in as."""
        return self.call(
            "POST",
            f"{AUTHS}/add",
            {"name": name, "email": email, "password": password, "role": role},
        )

    def admin_config(self) -> Any:
        return self.call("GET", f"{AUTHS}/admin/config")

    # ---- functions

    def functions(self) -> list[dict]:
        """Every function, without its `content` (function() has it)."""
        live = self.call("GET", f"{FUNCTIONS}/list")
        if not isinstance(live, list):
            raise OwppError("GET /functions/list did not return a list")
        return live

    def function(self, function_id: str) -> Any:
        """One function, with its code. One that is not there is a 401, as unauthorised is."""
        return self.call("GET", f"{FUNCTIONS}/id/{function_id}")

    def create_function(self, function_id: str, name: str, content: str, meta: FunctionMeta) -> Any:
        return self.call("POST", f"{FUNCTIONS}/create", _form(function_id, name, content, meta))

    def update_function(self, function_id: str, name: str, content: str, meta: FunctionMeta) -> Any:
        return self.call(
            "POST", f"{FUNCTIONS}/id/{function_id}/update", _form(function_id, name, content, meta)
        )

    def toggle(self, function_id: str) -> Any:
        """Switches the function on, or off."""
        return self.call("POST", f"{FUNCTIONS}/id/{function_id}/toggle")

    def toggle_global(self, function_id: str) -> Any:
        """Makes the function global, or not."""
        return self.call("POST", f"{FUNCTIONS}/id/{function_id}/toggle/global")

    def delete_function(self, function_id: str) -> bool:
        """Whether Open-WebUI confirmed the delete."""
        return self.call("DELETE", f"{FUNCTIONS}/id/{function_id}/delete") is True

    def valves(self, function_id: str) -> dict:
        values = self.call("GET", f"{FUNCTIONS}/id/{function_id}/valves")
        return values if isinstance(values, dict) else {}

    def update_valves(self, function_id: str, values: dict) -> Any:
        return self.call("POST", f"{FUNCTIONS}/id/{function_id}/valves/update", values)


def _form(function_id: str, name: str, content: str, meta: FunctionMeta) -> dict:
    return {"id": function_id, "name": name, "content": content, "meta": meta.stored()}
