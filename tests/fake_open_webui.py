"""An Open-WebUI in memory, behind the same `Fetch` port urllib is (owpp.openwebui): the deploy,
`owpp import --instance` and `owpp live`'s stack are tested against it. `serve()` puts it behind
a real HTTP server, for the contract test of the urllib adapter and for commands run through
`main()` with only an OPEN_WEBUI_URL."""

from __future__ import annotations

import contextlib
import json
import re
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

from owpp.bundle import function_type, parse_frontmatter
from owpp.deploy import Choices, Instance
from owpp.openwebui import HttpResponse, replace_imports

INSTANCE_FIELDS = set(Instance.__dataclass_fields__)


class Target(NamedTuple):
    """Where and what to deploy: `deploy(*target)`."""

    instance: Instance
    choices: Choices


class FakeOpenWebUI:
    """Just enough of Open-WebUI to see which calls are made, and what they leave behind.

    `calls` lists each call ("METHOD /path") but /health, and a functions call only once it got
    past the credential check; `state` is the functions by id; `accounts` the accounts by email.
    """

    base_url = "http://open-webui.test"

    def __init__(
        self,
        live=(),
        key="sk-good",  # an admin's API key
        created_type="filter",
        created_active=False,
        fail_delete=False,
        accounts=None,  # {email: password}: /auths/signin, with `role`
        ldap=None,  # {user: password}: /auths/ldap
        oidc=None,  # {provider: token}: /auths/oauth/<provider>/token/exchange
        open_signin=False,  # an empty sign-in works (WEBUI_AUTH=False, or a trusted header)
        role="admin",  # of whoever signs in to an account given above
        interface_settings=None,  # DEFAULT_INTERFACE_SETTINGS in the admin config
        admin_config_status=200,  # 403: a signed-in account that cannot read the admin config
        valves=None,  # {function id: its valves}
        starting=0,  # how many /health checks fail (connection refused) before it is up
    ):
        self.calls: list[str] = []
        self.state: dict[str, dict] = {f["id"]: dict(f) for f in live}
        self.accounts: dict[str, dict] = {
            email: {"email": email, "password": pw, "role": role, "name": email}
            for email, pw in (accounts or {}).items()
        }
        self.tokens: dict[str, str] = {key: "admin"}  # token: role
        self.key, self.role = key, role
        self.created_type, self.created_active, self.fail_delete = (
            created_type,
            created_active,
            fail_delete,
        )
        self.ldap, self.oidc, self.open_signin = ldap or {}, oidc or {}, open_signin
        self.interface_settings = interface_settings or {}
        self.admin_config_status = admin_config_status
        self.valves: dict[str, dict] = dict(valves or {})
        self.starting = starting

    # ---- as deploy and import are given it

    def instance(self, **kwargs) -> Instance:
        """This Open-WebUI, signed in with the good key unless told otherwise."""
        kwargs.setdefault("api_key", self.key)
        return Instance(base_url=self.base_url, fetch=self, **kwargs)

    def options(self, directory: Path, **kwargs) -> Target:
        """(instance, choices) for deploying `directory` here: the keyword arguments that are
        Instance fields go to the instance, the rest to the choices."""
        connection = {k: kwargs.pop(k) for k in list(kwargs) if k in INSTANCE_FIELDS}
        return Target(self.instance(**connection), Choices(dir=Path(directory), **kwargs))

    # ---- the Fetch port

    def __call__(self, method, url, headers=None, body=None) -> HttpResponse:
        path = urlsplit(url).path
        form = json.loads(body) if body else None
        auth = (headers or {}).get("Authorization", "")
        token = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else ""
        if path == "/health":
            if self.starting:
                self.starting -= 1
                raise ConnectionRefusedError("starting")
            return _json({"status": True})
        if path.startswith("/api/v1/auths/"):
            self.calls.append(f"{method} {path}")
            return self._auths(method, path, form or {}, token)
        if self.tokens.get(token) != "admin":
            return _json({"detail": "nope"}, 401)
        self.calls.append(f"{method} {path}")
        return self._functions(method, path, form)

    # ---- signing in

    def _session(self, account: dict) -> HttpResponse:
        token = f"{account['email'].split('@')[0]}-token"
        self.tokens[token] = account["role"]
        return _json({"token": token, "role": account["role"], "email": account["email"]})

    def _auths(self, method, path, form, token) -> HttpResponse:
        if path == "/api/v1/auths/admin/config":
            if self.admin_config_status != 200:
                return _json({"detail": "not allowed"}, self.admin_config_status)
            return _json({"DEFAULT_INTERFACE_SETTINGS": self.interface_settings})
        if path == "/api/v1/auths/signin":
            if form.get("email") == "" and form.get("password") == "":
                if self.open_signin:
                    return self._session({"email": "admin@example.com", "role": self.role})
            else:
                account = self.accounts.get(form.get("email"))
                if account and account["password"] == form.get("password"):
                    return self._session(account)
            return _json({"detail": "The email or password provided is incorrect."}, 400)
        if path == "/api/v1/auths/signup":
            if form["email"] in self.accounts:
                return _json({"detail": "Uh-oh! This email is already registered."}, 400)
            role = "user" if self.accounts else "admin"  # the first account is the admin
            self.accounts[form["email"]] = {**form, "role": role}
            return self._session(self.accounts[form["email"]])
        if path == "/api/v1/auths/add":
            if self.tokens.get(token) != "admin":
                return _json({"detail": "nope"}, 401)
            self.accounts[form["email"]] = {**form, "role": form.get("role") or "pending"}
            return _json({"email": form["email"], "role": self.accounts[form["email"]]["role"]})
        if path == "/api/v1/auths/ldap":
            if not self.ldap:
                return _json({"detail": "LDAP authentication is not enabled"}, 400)
            if self.ldap.get(form.get("user")) == form.get("password"):
                return self._session({"email": form["user"], "role": self.role})
            return _json({"detail": "Invalid credentials"}, 400)
        exchange = re.fullmatch(r"/api/v1/auths/oauth/([^/]+)/token/exchange", path)
        if exchange:
            if not self.oidc:
                return _json({"detail": "Token exchange is disabled"}, 403)
            if self.oidc.get(exchange.group(1)) == form.get("token"):
                return self._session({"email": "oidc@example.com", "role": self.role})
            return _json({"detail": "Invalid token"}, 400)
        return _json({"detail": "not found"}, 404)

    # ---- functions

    def _functions(self, method, path, body) -> HttpResponse:
        state = self.state
        # Like the real API: the list has no `content`; GET /id/<id> does.
        if path == "/api/v1/functions/list":
            return _json([{k: v for k, v in f.items() if k != "content"} for f in state.values()])
        if path == "/api/v1/functions/create":
            f = {
                "id": body["id"],
                "name": body["name"],
                **_saved(body),
                "type": self.created_type,
                "is_active": self.created_active,
                "is_global": False,
            }
            state[body["id"]] = f
            return _json(f)
        m = re.fullmatch(r"/api/v1/functions/id/([^/]+)(/.*)?", path)
        if not m:
            return _json("?", 404)
        fn_id, rest = m.group(1), m.group(2) or ""
        if rest == "/delete" and method == "DELETE":
            existed = state.pop(fn_id, None) is not None
            return _json(False if self.fail_delete else existed)
        f = state.get(fn_id)
        if not f:  # Open-WebUI answers a missing function as unauthorised
            return _json({"detail": "not found"}, 401)
        if rest == "" and method == "GET":
            return _json(f)
        if rest == "/update":
            f.update(name=body["name"], **_saved(body))
        elif rest == "/toggle":
            f["is_active"] = not f["is_active"]
        elif rest == "/toggle/global":
            f["is_global"] = not f["is_global"]
        elif rest == "/valves" and method == "GET":
            return _json(self.valves.get(fn_id))
        elif rest == "/valves/update":
            self.valves[fn_id] = body
            return _json(body)
        else:
            return _json("?", 404)
        return _json(f)


def _saved(form: dict) -> dict:
    """The code and meta as Open-WebUI saves them: imports rewritten, the header it reads from
    the code added to the meta as `manifest`, and `toggle`: whether a filter has the switch
    (Open-WebUI reads `toggle` off the loaded module; here, a `self.toggle = True` in the code)."""
    content = replace_imports(form["content"])
    toggle = function_type(content)[:1] == ["filter"] and bool(
        re.search(r"self\.toggle\s*=\s*True", content)
    )
    meta = {**form["meta"], "manifest": parse_frontmatter(content), "toggle": toggle}
    return {"content": content, "meta": meta}


def _json(obj, status=200) -> HttpResponse:
    return HttpResponse(status, json.dumps(obj))


@contextlib.contextmanager
def serve(fetch, tls: ssl.SSLContext | None = None):
    """`fetch` (a FakeOpenWebUI) behind a real HTTP server on localhost, over HTTPS with `tls`:
    yields its base URL."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _handle(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items()}
            res = fetch(self.command, f"http://fake{self.path}", headers, body)
            data = res.text.encode()
            self.send_response(res.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_DELETE = _handle

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        yield f"{'https' if tls else 'http'}://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
