"""Who may reach a plugin's routes: declared in plugin.yaml, enforced by the routes library.

Real FastAPI does the dependency resolution; only Open-WebUI's session check and its function
table are stubbed. Every route needs a signed-in user unless a mount says `public` in so many words."""

from __future__ import annotations

import json
import re
import sys
import types

import pytest
from conftest import write_plugin
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from owpp.bundle import bundle_function, load_function_files
from owpp.errors import OwppError

USER = {"Authorization": "Bearer user-token"}
ADMIN = {"Authorization": "Bearer admin-token"}
PENDING = {"Authorization": "Bearer pending-token"}
ROLES = {"user-token": "user", "admin-token": "admin", "pending-token": "pending"}


def _data(code, var):
    """The JSON a library embeds in a bundle (`_STATIC = _json.loads("...")`)."""
    return json.loads(json.loads(re.search(rf'{var} = _json\.loads\((".*")\)\n', code).group(1)))


class Site:
    """A stand-in Open-WebUI: an app, a session check, and the function table."""

    def __init__(self, monkeypatch):
        site = self
        self.app = FastAPI()
        self.active = True
        self.lookups = 0
        self.signins = 0
        self.signin_broken = False
        self.chats: dict = {}  # chat id -> {user id: {"read", "write"}}
        self.chat_checks: list = []

        async def get_current_user(request, response, background_tasks, auth_token):
            site.lookups += 1
            role = ROLES.get(getattr(auth_token, "credentials", None))
            if role is None:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return types.SimpleNamespace(id=f"{role}-1", role=role)

        class Chats:
            @staticmethod
            async def has_chat_access(chat_id, user, permission="read"):
                site.chat_checks.append((chat_id, user.id, permission))
                return permission in site.chats.get(chat_id, {}).get(user.id, set())

        class Functions:
            @staticmethod
            async def get_function_by_id(function_id):
                return types.SimpleNamespace(is_active=site.active)

            @staticmethod
            async def get_function_valves_by_id(function_id):
                return {}

        @self.app.post("/api/v1/auths/signin")
        async def signin(request: Request):
            """Open-WebUI's sign-in with empty credentials, which works when a proxy sends a trusted header."""
            site.signins += 1
            if site.signin_broken:
                raise HTTPException(status_code=500, detail="broken")
            who = request.headers.get("x-trusted-email", "").split("@")[0]
            if who not in ("user", "admin", "pending"):
                raise HTTPException(status_code=400, detail="Invalid trusted header")
            reply = JSONResponse({"token": f"{who}-token", "token_type": "Bearer"})
            reply.set_cookie("token", f"{who}-token", httponly=True)
            return reply

        main = types.ModuleType("open_webui.main")
        main.app = self.app
        for name, attrs in {
            "open_webui": {},
            "open_webui.utils": {},
            "open_webui.utils.auth": {"get_current_user": get_current_user},
            "open_webui.models": {},
            "open_webui.models.functions": {"Functions": Functions},
            "open_webui.models.chats": {"Chats": Chats},
            "open_webui.env": {"WEBUI_SECRET_KEY": "test-secret"},
        }.items():
            module = types.ModuleType(name)
            module.__dict__.update(attrs)
            monkeypatch.setitem(sys.modules, name, module)
        monkeypatch.setitem(sys.modules, "open_webui.main", main)

    def load(self, folder):
        namespace: dict = {"__name__": "function_demo_" + "0" * 32}
        exec(compile(bundle_function(folder), "demo.py", "exec"), namespace)
        return namespace

    def get(self, path, headers=None):
        # Redirects are not followed: a redirect to the login page is what is being looked at.
        return TestClient(self.app, follow_redirects=False).get(path, headers=headers)


@pytest.fixture
def site(monkeypatch):
    return Site(monkeypatch)


def plugin(tmp_path, manifest="function:\n  title: T\ninclude: [routes]\n", files=None):
    folder = tmp_path / "demo"
    write_plugin(
        folder,
        {"plugin.yaml": manifest, "function.py": "class Event:\n    pass\n", **(files or {})},
    )
    return folder


def mount_page(ns, site, **kwargs):
    router = APIRouter()

    @router.get("/demo/page")
    async def page(request: Request):
        user = await ns["plugin_user"](request)
        return {"who": user.role}

    ns["plugin_mount"](site.app, router, "/demo", **kwargs)


class TestEveryRouteNeedsASignedInUser:
    def test_the_default_is_any_signed_in_user(self, site, tmp_path):
        mount_page(site.load(plugin(tmp_path)), site)
        assert site.get("/demo/page").status_code == 401
        assert site.get("/demo/page", USER).json() == {"who": "user"}
        assert site.get("/demo/page", ADMIN).json() == {"who": "admin"}

    def test_a_pending_account_is_not_signed_in(self, site, tmp_path):
        mount_page(site.load(plugin(tmp_path)), site)
        assert site.get("/demo/page", PENDING).status_code == 401

    def test_a_bad_token_is_not_signed_in(self, site, tmp_path):
        mount_page(site.load(plugin(tmp_path)), site)
        assert site.get("/demo/page", {"Authorization": "Bearer nope"}).status_code == 401
        assert site.get("/demo/page", {"Authorization": "Basic abc"}).status_code == 401

    @pytest.mark.parametrize(
        "access",
        [
            "none",
            "anyone",
            "Public",
            "PUBLIC",
            " public",
            "true",
            True,
            False,
            "",
            0,
            None.__class__,
        ],
    )
    def test_only_the_exact_word_public_opens_a_mount(self, site, tmp_path, access):
        ns = site.load(plugin(tmp_path))
        with pytest.raises(ValueError, match="exactly that word"):
            mount_page(ns, site, access=access)
        with pytest.raises(ValueError, match="exactly that word"):
            ns["plugin_guard"](access)

    def test_disabled_answers_404_before_asking_who_you_are(self, site, tmp_path):
        mount_page(site.load(plugin(tmp_path)), site)
        site.active = False
        assert site.get("/demo/page").status_code == 404
        assert site.get("/demo/page", ADMIN).status_code == 404


MARKED = """from fastapi import APIRouter

class Event:
    pass

router = APIRouter()


@router.get("/demo/open")
async def open_page():
    return {"ok": True}


@router.get("/demo/user")
async def user_page(user: PluginUser):
    return {"role": user.role}


@router.get("/demo/admin")
async def admin_page(user: PluginAdmin):
    return {"role": user.role}
"""


class TestMarkingARoute:
    """`user: PluginAdmin` on a handler makes that route admin-only; the handler gets the user."""

    def mount(self, site, tmp_path, manifest="function:\n  title: T\ninclude: [routes]\n"):
        ns = site.load(plugin(tmp_path, manifest, {"function.py": MARKED}))
        ns["plugin_mount"](site.app, ns["router"], "/demo")
        return ns

    def test_one_admin_route_in_a_plugin_that_is_otherwise_open_to_users(self, site, tmp_path):
        self.mount(site, tmp_path)
        assert site.get("/demo/open", USER).status_code == 200
        assert site.get("/demo/admin").status_code == 401
        assert site.get("/demo/admin", USER).status_code == 403
        assert site.get("/demo/admin", ADMIN).json() == {"role": "admin"}

    def test_the_handler_receives_the_user(self, site, tmp_path):
        self.mount(site, tmp_path)
        assert site.get("/demo/user", USER).json() == {"role": "user"}
        assert site.get("/demo/user", ADMIN).json() == {"role": "admin"}

    def test_a_marker_cannot_loosen_what_the_mount_requires(self, site, tmp_path):
        ns = site.load(plugin(tmp_path, files={"function.py": MARKED}))
        ns["plugin_mount"](site.app, ns["router"], "/demo", access="admin")
        assert site.get("/demo/user", USER).status_code == 403  # PluginUser inside an admin mount
        assert site.get("/demo/open", USER).status_code == 403
        assert site.get("/demo/user", ADMIN).status_code == 200

    def test_every_marked_route_still_needs_the_function_enabled(self, site, tmp_path):
        self.mount(site, tmp_path)
        site.active = False
        for path in ("/demo/user", "/demo/admin"):
            assert site.get(path, ADMIN).status_code == 404

    def test_the_session_is_looked_up_once_however_many_guards_ask(self, site, tmp_path):
        self.mount(site, tmp_path)
        site.lookups = 0
        assert site.get("/demo/admin", ADMIN).status_code == 200  # the mount's guard and the marker
        assert site.lookups == 1

    def test_there_is_no_marker_for_a_public_route(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        marks = {
            name
            for name in ns
            if name.startswith("Plugin")
            and name[6:] in ("User", "Admin", "Public", "Anyone", "Anonymous")
        }
        assert marks == {"PluginUser", "PluginAdmin"}


CHATS = """from typing import Annotated

from fastapi import APIRouter, Depends

class Event:
    pass

router = APIRouter()


@router.get("/demo/write/{chat_id}")
async def write_page(chat_id: WritableChat):
    return {"chat": chat_id}


@router.get("/demo/read/{chat_id}")
async def read_page(chat_id: ReadableChat):
    return {"chat": chat_id}


@router.get("/demo/other/{cid}")
async def other_name(cid: Annotated[str, Depends(plugin_chat_guard("read", "cid"))]):
    return {"chat": cid}


@router.get("/demo/nochat")
async def no_chat_here(chat: WritableChat):
    return {}
"""


class TestChatAccessMarker:
    """`chat_id: WritableChat` runs only for a signed-in user who can write to that chat."""

    @pytest.fixture
    def ns(self, site, tmp_path):
        ns = site.load(plugin(tmp_path, files={"function.py": CHATS}))
        ns["plugin_mount"](site.app, ns["router"], "/demo")
        site.chats = {"c1": {"user-1": {"read", "write"}, "admin-1": {"read"}}}
        return ns

    def test_a_user_with_access_gets_the_chat_id(self, site, ns):
        assert site.get("/demo/write/c1", USER).json() == {"chat": "c1"}

    def test_write_needs_write_and_read_needs_read(self, site, ns):
        assert site.get("/demo/write/c1", ADMIN).status_code == 404  # the admin may only read it
        assert site.get("/demo/read/c1", ADMIN).json() == {"chat": "c1"}
        assert ("c1", "admin-1", "write") in site.chat_checks and (
            "c1",
            "admin-1",
            "read",
        ) in site.chat_checks

    def test_no_access_is_404_so_a_chats_existence_is_not_revealed(self, site, ns):
        assert (
            site.get("/demo/write/c1", {"Authorization": "Bearer pending-token"}).status_code == 401
        )
        assert site.get("/demo/write/c2", USER).status_code == 404  # a chat that does not exist
        assert site.get("/demo/write/c1", ADMIN).status_code == 404  # one the user cannot write to

    def test_a_signed_in_user_is_still_required(self, site, ns):
        assert site.get("/demo/write/c1").status_code == 401
        assert site.chat_checks == []  # nobody was looked up for an anonymous request

    def test_a_temporary_chat_has_no_record_so_any_signed_in_user_passes(self, site, ns):
        assert site.get("/demo/write/local:abc", USER).json() == {"chat": "local:abc"}
        assert site.chat_checks == []
        assert site.get("/demo/write/local:abc").status_code == 401

    def test_a_disabled_function_serves_nothing(self, site, ns):
        site.active = False
        assert site.get("/demo/write/c1", USER).status_code == 404

    def test_the_path_parameter_may_have_another_name(self, site, ns):
        assert site.get("/demo/other/c1", USER).json() == {"chat": "c1"}
        assert site.get("/demo/other/c2", USER).status_code == 404

    def test_a_route_without_the_path_parameter_fails_loudly(self, site, ns):
        client = TestClient(site.app, raise_server_exceptions=False)
        assert client.get("/demo/nochat", headers=USER).status_code == 500

    def test_only_read_and_write_are_permissions(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        for permission in ("admin", "delete", "", None):
            with pytest.raises(ValueError, match="'read' or 'write'"):
                ns["plugin_chat_guard"](permission)


PAGE = {"Accept": "text/html,application/xhtml+xml"}  # a browser opening the address
TRUSTED = {"X-Trusted-Email": "user@example.com"}  # what a trusted-header proxy adds
TRUSTED_ADMIN = {"X-Trusted-Email": "admin@example.com"}


class TestSomeoneWithNoSessionIsNotJustTurnedAway:
    """Opening a page without having visited the app's home page first: sign them in if the system
    does that by itself (trusted headers, auth off), else send them to the login page and back."""

    def mounted(self, site, tmp_path, **kwargs):
        ns = site.load(plugin(tmp_path))
        mount_page(ns, site, **kwargs)
        return ns

    def test_a_trusted_header_signs_them_in_and_the_browser_gets_the_session(self, site, tmp_path):
        self.mounted(site, tmp_path)
        reply = site.get("/demo/page", {**PAGE, **TRUSTED})
        assert reply.status_code == 200 and reply.json() == {"who": "user"}
        assert "token=user-token" in reply.headers["set-cookie"]
        assert site.signins == 1

    def test_the_same_goes_for_an_admin_page(self, site, tmp_path):
        self.mounted(site, tmp_path, access="admin")
        assert site.get("/demo/page", {**PAGE, **TRUSTED_ADMIN}).json() == {"who": "admin"}

    def test_a_signed_in_non_admin_is_refused_not_redirected(self, site, tmp_path):
        self.mounted(site, tmp_path, access="admin")
        assert site.get("/demo/page", {**PAGE, **TRUSTED}).status_code == 403

    def test_without_one_the_browser_is_sent_to_the_login_page_and_back(self, site, tmp_path):
        self.mounted(site, tmp_path)
        reply = site.get("/demo/page", PAGE)
        assert (
            reply.status_code == 302
            and reply.headers["location"] == "/auth?redirect=%2Fdemo%2Fpage"
        )

    def test_where_they_were_going_survives_the_trip_query_and_all(self, site, tmp_path):
        from urllib.parse import parse_qs, urlsplit

        self.mounted(site, tmp_path)
        reply = site.get("/demo/page?chat=a%20b&x=1", PAGE)
        assert parse_qs(urlsplit(reply.headers["location"]).query)["redirect"] == [
            "/demo/page?chat=a%20b&x=1"
        ]

    def test_the_address_sent_to_the_login_page_can_never_point_off_site(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        for path, expected in (
            ("//evil.example.com/x", "%2Fevil.example.com%2Fx"),
            ("///a", "%2Fa"),
            ("/ok", "%2Fok"),
        ):
            request = types.SimpleNamespace(url=types.SimpleNamespace(path=path, query=""))
            assert ns["_login_url"](request) == f"/auth?redirect={expected}"

    def test_if_the_automatic_sign_in_fails_it_is_the_login_page_not_an_error(self, site, tmp_path):
        self.mounted(site, tmp_path)
        site.signin_broken = True
        assert site.get("/demo/page", {**PAGE, **TRUSTED}).status_code == 302

    def test_a_pending_account_does_not_loop(self, site, tmp_path):
        self.mounted(site, tmp_path)
        reply = site.get("/demo/page", {**PAGE, "X-Trusted-Email": "pending@example.com"})
        assert reply.status_code == 302 and site.signins == 1

    def test_an_existing_session_is_used_and_no_sign_in_is_attempted(self, site, tmp_path):
        self.mounted(site, tmp_path)
        assert site.get("/demo/page", {**PAGE, **USER}).status_code == 200
        assert site.signins == 0

    def test_an_api_call_gets_a_401_and_no_session_is_minted_for_it(self, site, tmp_path):
        self.mounted(site, tmp_path)
        reply = site.get("/demo/page", {"Accept": "application/json", **TRUSTED})
        assert reply.status_code == 401 and "location" not in reply.headers
        assert site.signins == 0 and "set-cookie" not in reply.headers

    def test_a_page_in_an_iframe_is_signed_in_if_it_can_be_but_never_redirected(
        self, site, tmp_path
    ):
        self.mounted(site, tmp_path)
        frame = {**PAGE, "Sec-Fetch-Dest": "iframe"}
        assert site.get("/demo/page", {**frame, **TRUSTED}).status_code == 200
        reply = site.get(
            "/demo/page", frame
        )  # a login page inside a sandboxed panel would be useless
        assert reply.status_code == 401 and "location" not in reply.headers

    def test_a_disabled_function_is_a_404_before_anything_is_tried(self, site, tmp_path):
        self.mounted(site, tmp_path)
        site.active = False
        assert site.get("/demo/page", {**PAGE, **TRUSTED}).status_code == 404
        assert site.signins == 0

    def test_a_marked_route_works_after_an_automatic_sign_in(self, site, tmp_path):
        ns = site.load(plugin(tmp_path, files={"function.py": MARKED}))
        ns["plugin_mount"](site.app, ns["router"], "/demo")
        assert site.get("/demo/admin", {**PAGE, **TRUSTED_ADMIN}).json() == {"role": "admin"}
        assert site.get("/demo/admin", {**PAGE, **TRUSTED}).status_code == 403
        assert site.signins == 2

    def test_a_chat_marked_route_works_after_an_automatic_sign_in(self, site, tmp_path):
        ns = site.load(plugin(tmp_path, files={"function.py": CHATS}))
        ns["plugin_mount"](site.app, ns["router"], "/demo")
        site.chats = {"c1": {"user-1": {"read", "write"}}}
        assert site.get("/demo/write/c1", {**PAGE, **TRUSTED}).json() == {"chat": "c1"}
        assert site.get("/demo/write/c1", PAGE).status_code == 302

    def test_the_static_files_do_the_same(self, site, tmp_path):
        site.load(plugin(tmp_path, "function:\n  title: T\n", {"static/index.html": "<p>hi</p>\n"}))
        assert site.get("/demo/", {**PAGE, **TRUSTED}).text == "<p>hi</p>\n"
        assert site.get("/demo/", PAGE).status_code == 302


class TestAMountsAccessLevel:
    """plugin_mount(access=...): user (the default), admin or, on purpose, public."""

    def test_a_mount_can_be_admin_only_with_no_check_in_the_plugins_code(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        mount_page(ns, site, access="admin")
        assert site.get("/demo/page").status_code == 401
        assert site.get("/demo/page", USER).status_code == 403
        assert site.get("/demo/page", ADMIN).status_code == 200

    def test_the_default_is_any_signed_in_user(self, site, tmp_path):
        mount_page(site.load(plugin(tmp_path)), site)
        assert site.get("/demo/page", USER).status_code == 200

    def test_two_mounts_can_differ(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        open_router = APIRouter()
        open_router.add_api_route("/demo/open", lambda: {"ok": True}, methods=["GET"])
        ns["plugin_mount"](site.app, open_router, "/demo", name="open", access="user")
        mount_page(ns, site, access="admin")
        assert site.get("/demo/open", USER).status_code == 200
        assert site.get("/demo/open").status_code == 401  # still not public
        assert site.get("/demo/page", USER).status_code == 403


class TestStaticFiles:
    FILES = {"static/app.js": "console.log(1)\n", "static/index.html": "<p>hi</p>\n"}

    def test_they_need_a_signed_in_user_by_default(self, site, tmp_path):
        site.load(plugin(tmp_path, "function:\n  title: T\n", self.FILES))
        assert site.get("/demo/app.js").status_code == 401
        assert site.get("/demo/", {}).status_code == 401
        response = site.get("/demo/app.js", USER)
        assert response.status_code == 200 and response.text == "console.log(1)\n"
        assert site.get("/demo/", USER).text == "<p>hi</p>\n"

    def test_they_follow_the_access_the_static_section_declares(self, site, tmp_path):
        site.load(plugin(tmp_path, "function:\n  title: T\nstatic:\n  access: admin\n", self.FILES))
        assert site.get("/demo/app.js").status_code == 401
        assert site.get("/demo/app.js", USER).status_code == 403
        assert site.get("/demo/app.js", ADMIN).status_code == 200
        assert site.get("/demo/", USER).status_code == 403

    def test_public_serves_people_who_are_not_signed_in(self, site, tmp_path):
        site.load(
            plugin(tmp_path, "function:\n  title: T\nstatic:\n  access: public\n", self.FILES)
        )
        for who in ({}, USER, ADMIN):
            assert site.get("/demo/app.js", who).text == "console.log(1)\n"
        assert site.get("/demo/", PAGE).text == "<p>hi</p>\n"  # no redirect, no sign-in attempt
        assert site.signins == 0 and site.lookups == 0

    def test_a_public_folder_is_still_switched_off_with_the_function(self, site, tmp_path):
        site.load(
            plugin(tmp_path, "function:\n  title: T\nstatic:\n  access: public\n", self.FILES)
        )
        site.active = False
        assert site.get("/demo/app.js").status_code == 404

    def test_the_default_is_any_signed_in_user(self, site, tmp_path):
        site.load(plugin(tmp_path, "function:\n  title: T\nstatic: {}\n", self.FILES))
        assert site.get("/demo/app.js").status_code == 401
        assert site.get("/demo/app.js", USER).status_code == 200

    def test_they_are_withdrawn_when_the_function_is_disabled(self, site, tmp_path):
        site.load(plugin(tmp_path, "function:\n  title: T\n", self.FILES))
        site.active = False
        assert site.get("/demo/app.js", ADMIN).status_code == 404


class TestAPublicMount:
    """access="public": the one level that needs no one. Deliberate, in so many words, and per mount."""

    def public_and_private(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        mount_at(ns, site, "/hook", name="hook", access="public")
        mount_at(ns, site, "/inbox", name="inbox")
        return ns

    def test_nobody_needs_to_be_signed_in(self, site, tmp_path):
        self.public_and_private(site, tmp_path)
        for who in ({}, USER, ADMIN):
            assert site.get("/hook", who).json() == {"at": "/hook"}

    def test_nothing_is_looked_up_or_attempted_and_nobody_is_redirected(self, site, tmp_path):
        self.public_and_private(site, tmp_path)
        reply = site.get("/hook", {**PAGE, **TRUSTED})
        assert reply.status_code == 200 and "set-cookie" not in reply.headers
        assert site.lookups == 0 and site.signins == 0

    def test_it_is_a_property_of_the_mount_not_of_the_plugin(self, site, tmp_path):
        self.public_and_private(site, tmp_path)
        assert site.get("/inbox").status_code == 401  # the neighbouring mount is as guarded as ever
        assert site.get("/inbox", USER).status_code == 200

    def test_a_disabled_function_serves_nothing_even_publicly(self, site, tmp_path):
        self.public_and_private(site, tmp_path)
        site.active = False
        assert site.get("/hook").status_code == 404

    def test_a_marker_on_a_route_of_a_public_mount_still_asks_for_more(self, site, tmp_path):
        ns = site.load(plugin(tmp_path, files={"function.py": MARKED}))
        ns["plugin_mount"](site.app, ns["router"], "/demo", access="public")
        assert site.get("/demo/open").json() == {"ok": True}  # unmarked: open to everyone
        assert site.get("/demo/user").status_code == 401  # PluginUser: signed in
        assert site.get("/demo/user", USER).json() == {"role": "user"}
        assert site.get("/demo/admin", USER).status_code == 403  # PluginAdmin: an admin
        assert site.get("/demo/admin", ADMIN).json() == {"role": "admin"}

    def test_a_handler_can_still_see_who_is_there_if_anyone_is(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        router = APIRouter()

        async def who(request: Request):
            user = await ns["plugin_user"](request)
            return {"who": user.role if user else None}

        router.add_api_route("/hello", who, methods=["GET"])
        ns["plugin_mount"](site.app, router, "/hello", access="public")
        assert site.get("/hello").json() == {"who": None}
        assert site.get("/hello", ADMIN).json() == {"who": "admin"}


class TestARouteThatCannotCarryASession:
    """A sandboxed iframe sends no cookies. It may replace the sign-in check with its own guard,
    which has to verify a credential minted from a login; the function still has to be enabled."""

    def mount(self, ns, site):
        async def token_guard(chat_id: str, t: str = ""):
            if t != f"minted-for-{chat_id}":
                raise HTTPException(status_code=404)

        api = APIRouter()
        api.add_api_route("/demo/api/{chat_id}", lambda chat_id: {"chat": chat_id}, methods=["GET"])
        ns["plugin_mount"](site.app, api, "/demo", name="api", guard=token_guard)

    def test_the_token_stands_in_for_the_session(self, site, tmp_path):
        self.mount(site.load(plugin(tmp_path)), site)
        assert site.get("/demo/api/c1?t=minted-for-c1").json() == {"chat": "c1"}
        assert site.get("/demo/api/c1?t=minted-for-c2").status_code == 404
        assert site.get("/demo/api/c1").status_code == 404

    def test_a_disabled_function_still_answers_404(self, site, tmp_path):
        self.mount(site.load(plugin(tmp_path)), site)
        site.active = False
        assert site.get("/demo/api/c1?t=minted-for-c1").status_code == 404

    def test_access_and_guard_are_exclusive(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        with pytest.raises(ValueError, match="access or guard"):
            ns["plugin_mount"](site.app, APIRouter(), "/demo", access="user", guard=lambda: None)


class TestTheStaticSectionOfTheManifest:
    FILES = {"function.py": "class Event:\n    pass\n", "static/a.txt": "a"}

    def load(self, tmp_path, static):
        write_plugin(
            tmp_path / "p",
            {"plugin.yaml": f"function:\n  title: T\nstatic: {static}\n", **self.FILES},
        )
        return load_function_files(tmp_path)

    @pytest.mark.parametrize("access", ["none", "anyone", "false", "true", "0", "Public", "PUBLIC"])
    def test_only_user_admin_or_public_in_exactly_those_words(self, tmp_path, access):
        with pytest.raises(OwppError, match="exactly one of those words"):
            self.load(tmp_path, f"{{access: {access}}}")

    def test_other_shapes_are_refused(self, tmp_path):
        with pytest.raises(OwppError, match="must be a mapping"):
            self.load(tmp_path, "[admin]")
        with pytest.raises(OwppError, match="unknown key open"):
            self.load(tmp_path / "x", "{open: true}")

    def test_the_old_plugin_wide_key_is_refused_not_silently_ignored(self, tmp_path):
        # `routes:` used to set a level for every route. Ignoring it would leave an author believing a
        # plugin is admin-only while it is open to every signed-in user.
        write_plugin(
            tmp_path / "p",
            {"plugin.yaml": "function:\n  title: T\nroutes: {access: admin}\n", **self.FILES},
        )
        with pytest.raises(
            OwppError, match=r"`routes:` is gone.*user: PluginAdmin.*static: \{access: admin\}"
        ):
            load_function_files(tmp_path)

    def test_the_old_public_key_is_refused_and_says_where_everything_went(self, tmp_path):
        # `public: {access: admin}` ignored would leave a folder open to every signed-in user.
        write_plugin(
            tmp_path / "p",
            {"plugin.yaml": "function:\n  title: T\npublic: {access: admin}\n", **self.FILES},
        )
        with pytest.raises(OwppError, match=r"`public:` is now `static:`.*templates/"):
            load_function_files(tmp_path)

    @pytest.mark.parametrize("access", ["admin", "user", "public"])
    def test_the_three_levels_are_accepted_and_embedded(self, tmp_path, access):
        (fn,) = self.load(tmp_path / access, f"{{access: {access}}}")
        assert _data(fn.content, "_STATIC")["access"] == access

    def test_the_default_is_user(self, tmp_path):
        write_plugin(tmp_path / "p", {"plugin.yaml": "function:\n  title: T\n", **self.FILES})
        (fn,) = load_function_files(tmp_path)
        assert _data(fn.content, "_STATIC")["access"] == "user"


class TestNothingMountsStraightOntoTheApp:
    """Routes added to the app directly would skip the sign-in check, so the bundler refuses them."""

    @pytest.mark.parametrize(
        "line",
        [
            "app.include_router(router)",
            "__app__.include_router(router)",
            "request.app.add_api_route('/x', handler)",
            "__request__.app.mount('/x', sub)",
            "app.router.add_api_route('/x', handler)",
            "application.add_route('/x', handler)",
        ],
    )
    def test_refused(self, tmp_path, line):
        code = f"class Event:\n    def event(self, app, request, __app__, __request__, router, handler, sub, application):\n        {line}\n"
        folder = tmp_path / "p"
        write_plugin(folder, {"plugin.yaml": "function:\n  title: T\n", "function.py": code})
        with pytest.raises(OwppError, match="skips the sign-in check"):
            load_function_files(tmp_path)

    def test_the_sanctioned_ways_are_fine(self, tmp_path):
        code = (
            "# not app.include_router(router): a comment is not a call\n"
            "class Event:\n"
            "    def event(self, app, router, handler):\n"
            "        router.add_api_route('/x', handler)\n"
            "        router.include_router(router)\n"
            "        plugin_mount(app, router, '/x')\n"
        )
        folder = tmp_path / "p"
        write_plugin(
            folder,
            {"plugin.yaml": "function:\n  title: T\ninclude: [routes]\n", "function.py": code},
        )
        assert load_function_files(tmp_path)[0].type == "event"

    def test_the_examples_comply(self):
        from conftest import EXAMPLES, fake_sources

        assert len(load_function_files(EXAMPLES, fake_sources())) >= 4


class TestTheExamples:
    """The shipped plugins, bundled and mounted behind the real guard (Open-WebUI itself stubbed)."""

    def load(self, site, name, monkeypatch):
        from conftest import EXAMPLES

        env = types.ModuleType("open_webui.env")
        env.WEBUI_SECRET_KEY = "test-secret"
        monkeypatch.setitem(sys.modules, "open_webui.env", env)
        namespace: dict = {"__name__": f"function_{name}_" + "0" * 32}
        exec(compile(bundle_function(EXAMPLES / name), f"{name}.py", "exec"), namespace)
        return namespace

    def client(self, site):
        return TestClient(site.app, raise_server_exceptions=False)

    def test_stale_data_is_admin_only_by_the_marker_on_its_route(self, site, tmp_path, monkeypatch):
        import asyncio

        ns = self.load(site, "stale_data", monkeypatch)
        assert "REQUIRE_ADMIN" not in ns["Event"].Valves.model_fields  # no valve to open it up
        asyncio.run(
            ns["Event"]().event({}, __event_name__="system.startup.completed", __app__=site.app)
        )
        client = self.client(site)
        assert client.get("/stale-data").status_code == 401
        assert client.get("/stale-data", headers=USER).status_code == 403
        assert client.get("/stale-data", headers=ADMIN).status_code not in (401, 403, 404)
        site.active = False
        assert client.get("/stale-data", headers=ADMIN).status_code == 404

    def test_stale_data_moves_its_page_when_the_path_valve_changes(
        self, site, tmp_path, monkeypatch
    ):
        import asyncio

        ns = self.load(site, "stale_data", monkeypatch)
        event = ns["Event"]()
        assert (
            event.valves.DASHBOARD_PATH == "/stale-data"
        )  # made by the mixin: the class has no __init__
        asyncio.run(event.event({}, __event_name__="system.startup.completed", __app__=site.app))
        client = self.client(site)
        assert client.get("/stale-data", headers=ADMIN).status_code not in (401, 403, 404)

        event.valves.DASHBOARD_PATH = "/dash"  # an admin saved the valve
        about_me = {"subject": {"id": "stale_data"}}
        asyncio.run(
            event.event(about_me, __event_name__="function.valves_updated", __app__=site.app)
        )
        assert client.get("/stale-data", headers=ADMIN).status_code == 404  # the old path is gone
        assert client.get("/dash", headers=ADMIN).status_code not in (401, 403, 404)
        assert client.get("/dash").status_code == 401  # and the new one is just as guarded
        assert client.get("/dash", headers=USER).status_code == 403

    def test_another_functions_valve_change_does_not_remount_it(self, site, tmp_path, monkeypatch):
        import asyncio

        ns = self.load(site, "stale_data", monkeypatch)
        event = ns["Event"]()
        asyncio.run(event.event({}, __event_name__="system.startup.completed", __app__=site.app))
        event.valves.DASHBOARD_PATH = "/dash"
        elsewhere = {"subject": {"id": "some_other_function"}}
        asyncio.run(
            event.event(elsewhere, __event_name__="function.valves_updated", __app__=site.app)
        )
        assert self.client(site).get("/stale-data", headers=ADMIN).status_code not in (
            401,
            403,
            404,
        )  # own=True

    def test_excalidraws_page_needs_a_login_and_its_api_a_token(self, site, tmp_path, monkeypatch):
        ns = self.load(site, "excalidraw", monkeypatch)
        assert (
            "REQUIRE_LOGIN" not in ns["Filter"].Valves.model_fields
        )  # no way to turn the login off
        ns["Filter"]()  # mounts the routes on load
        client = self.client(site)
        # The page: the library's guard (any signed-in user).
        assert client.get("/excalidraw/view/local:abc").status_code == 401
        site.chats = {"c9": {"user-1": {"write"}}}
        assert (
            client.get("/excalidraw/view/c9", headers=USER).status_code == 200
        )  # they can write to it
        assert (
            client.get("/excalidraw/view/c9", headers=ADMIN).status_code == 404
        )  # this admin cannot
        assert client.get("/excalidraw/view/c8", headers=USER).status_code == 404  # no such chat
        page = client.get("/excalidraw/view/local:abc", headers=USER)
        assert page.status_code == 200 and "__TOKEN__" not in page.text
        import re

        token = re.search(r'const token = "(s\.[^"]+)";', page.text).group(1)
        assert ns["plugin_check_token"](
            token, "local:abc"
        )  # handed out only on that signed-in page load
        # The API: a sandboxed iframe sends no cookies, so it takes the token instead of a session.
        api = "/excalidraw/api/scenes/local:abc"
        assert client.get(api).status_code == 404
        assert client.get(f"{api}?t=nope").status_code == 404
        assert (
            client.get(f"{api}?t={ns['plugin_token']('local:other', 1)}").status_code == 404
        )  # another chat's
        assert client.get(f"{api}?t={token}").status_code not in (401, 404)  # past the guard
        site.active = False
        assert (
            client.get(f"{api}?t={token}").status_code == 404
        )  # a disabled function serves nothing


def mount_at(ns, site, path, name="", access=None):
    """Mount one route whose handler belongs to the plugin's own module, as a real plugin's does."""
    router = APIRouter()
    router.add_api_route(path, eval(f"lambda: {{'at': {path!r}}}", ns), methods=["GET"])
    ns["plugin_mount"](site.app, router, path, name=name, access=access)


class TestAMountsNameIsItsIdentity:
    def test_mounting_a_name_again_at_another_path_drops_the_old_one(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        mount_at(ns, site, "/old", name="page")
        assert site.get("/old", USER).status_code == 200
        mount_at(ns, site, "/new", name="page")  # a configurable path that changed
        assert site.get("/old", USER).status_code == 404
        assert site.get("/new", USER).json() == {"at": "/new"}

    def test_mounts_with_different_names_never_replace_each_other(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        mount_at(ns, site, "/page", name="page")
        mount_at(ns, site, "/api", name="api")
        mount_at(ns, site, "/page", name="page")  # again: replaced, not doubled
        assert (
            site.get("/page", USER).status_code == 200 and site.get("/api", USER).status_code == 200
        )
        mounts = [getattr(r, "plugin_mount_name", None) for r in site.app.router.routes]
        assert mounts.count("page") == 1 and mounts.count("api") == 1  # replaced, not doubled

    def test_the_unnamed_mount_is_one_mount_too(self, site, tmp_path):
        ns = site.load(plugin(tmp_path))
        mount_at(ns, site, "/a")
        mount_at(ns, site, "/b")  # the same (empty) name: replaces /a
        assert site.get("/a", USER).status_code == 404 and site.get("/b", USER).status_code == 200

    def test_another_functions_routes_are_never_dropped(self, site, tmp_path):
        mine = site.load(plugin(tmp_path / "a"))
        write_plugin(
            tmp_path / "b" / "demo",
            {
                "plugin.yaml": "function:\n  title: T\ninclude: [routes]\n",
                "function.py": "class Event:\n    pass\n",
            },
        )
        theirs = {"__name__": "function_other_" + "0" * 32}
        exec(compile(bundle_function(tmp_path / "b" / "demo"), "other.py", "exec"), theirs)
        mount_at(theirs, site, "/theirs")
        mount_at(mine, site, "/mine-1")
        mount_at(mine, site, "/mine-2")  # replaces /mine-1, not /theirs
        assert site.get("/theirs", USER).status_code == 200
        assert (
            site.get("/mine-1", USER).status_code == 404
            and site.get("/mine-2", USER).status_code == 200
        )

    def test_a_reload_of_the_same_function_replaces_its_mount(self, site, tmp_path):
        first = site.load(plugin(tmp_path / "a"))
        mount_at(first, site, "/old", name="page")
        second = site.load(
            plugin(tmp_path / "b")
        )  # Open-WebUI loads it again: same id, a new module
        mount_at(second, site, "/new", name="page")
        assert (
            site.get("/old", USER).status_code == 404 and site.get("/new", USER).status_code == 200
        )


class TestTokens:
    """plugin_token: what a route that cannot carry a session checks with `guard=`."""

    def tokens(self, site, tmp_path, name="demo"):
        folder = tmp_path / name
        write_plugin(
            folder,
            {
                "plugin.yaml": "function:\n  title: T\ninclude: [routes]\n",
                "function.py": "class Event:\n    pass\n",
            },
        )
        ns: dict = {"__name__": f"function_{name}_" + "0" * 32}
        exec(compile(bundle_function(folder), f"{name}.py", "exec"), ns)
        return ns["plugin_token"], ns["plugin_check_token"]

    def test_a_token_is_good_for_its_subject_only(self, site, tmp_path):
        mint, check = self.tokens(site, tmp_path)
        token = mint("chat-1")
        assert check(token, "chat-1") is True
        assert check(token, "chat-2") is False

    def test_it_expires(self, site, tmp_path, monkeypatch):
        import time

        mint, check = self.tokens(site, tmp_path)
        now = time.time()
        token = mint("c", hours=2)
        monkeypatch.setattr(time, "time", lambda: now + 3600)
        assert check(token, "c") is True
        monkeypatch.setattr(time, "time", lambda: now + 2 * 3600 + 5)
        assert check(token, "c") is False

    def test_it_cannot_be_forged_or_stretched(self, site, tmp_path):
        mint, check = self.tokens(site, tmp_path)
        prefix, expiry, mac = mint("c").split(".")
        assert (
            check(f"{prefix}.{int(expiry) + 9999}.{mac}", "c") is False
        )  # a later expiry, same signature
        assert check(f"{prefix}.{expiry}.{mac[:-2]}AA", "c") is False
        for junk in ("", "x", "s.1", "s.x.y", "s.1.2.3", None, 5, "a.b.c"):
            assert check(junk, "c") is False

    def test_one_functions_tokens_do_not_work_in_another(self, site, tmp_path):
        mint_a, check_a = self.tokens(site, tmp_path, "alpha")
        mint_b, check_b = self.tokens(site, tmp_path, "beta")
        token = mint_a("c")
        assert check_a(token, "c") is True and check_b(token, "c") is False

    def test_a_reload_of_the_same_function_still_accepts_its_tokens(self, site, tmp_path):
        mint, _ = self.tokens(site, tmp_path / "x")
        _, check_after_reload = self.tokens(site, tmp_path / "y")  # same id "demo", a new module
        assert check_after_reload(mint("c"), "c") is True

    def test_it_depends_on_the_servers_secret(self, site, tmp_path, monkeypatch):
        mint, check = self.tokens(site, tmp_path)
        token = mint("c")
        sys.modules["open_webui.env"].WEBUI_SECRET_KEY = "a different secret"
        assert check(token, "c") is False

    def test_a_token_must_last_some_time(self, site, tmp_path):
        mint, _ = self.tokens(site, tmp_path)
        for hours in (0, -1):
            with pytest.raises(ValueError):
                mint("c", hours=hours)
