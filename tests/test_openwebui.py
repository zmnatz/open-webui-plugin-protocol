"""The Open-WebUI adapter (owpp.openwebui). The contract test runs it over urllib against a real
HTTP server (the in-memory Open-WebUI, served): what every other test does through the fake, it
does here over a socket. The rest is the adapter's own behaviour: health, sign-in, the meta."""

from __future__ import annotations

import ssl

import pytest
from fake_open_webui import FakeOpenWebUI

from owpp.errors import OwppError
from owpp.live.client import Api
from owpp.openwebui import FunctionMeta, OpenWebUI, SignInRefused, urllib_fetch

# ---- the contract: urllib against a real server ---------------------------------------------


@pytest.fixture
def served(open_webui):
    """An in-memory Open-WebUI behind a real HTTP server, and the adapter over urllib to it."""
    fake = open_webui(accounts={"admin@example.com": "pw"})
    return fake, OpenWebUI(fake.serve(), urllib_fetch)


def test_over_urllib_it_waits_for_health_and_signs_in(served):
    fake, api = served
    api.wait_for_health(attempts=1, delay=0)
    session = api.sign_in("admin@example.com", "pw")
    assert session["token"] == "admin-token" and session["role"] == "admin"
    assert fake.calls == ["POST /api/v1/auths/signin"]


def test_over_urllib_a_refused_sign_in_says_what_open_webui_said(served):
    _, api = served
    with pytest.raises(SignInRefused, match=r"HTTP 400: The email or password .* incorrect"):
        api.sign_in("admin@example.com", "wrong")


def test_over_urllib_every_functions_endpoint(served):
    """Create, list, get, update, toggle, toggle global, valves, delete: what a deploy sends,
    and what it reads back, survive the trip through urllib and a socket."""
    fake, api = served
    api = api.as_account(api.sign_in("admin@example.com", "pw")["token"])
    meta = FunctionMeta("mine", "Ünïcode description", {"https://x.git": "a" * 40}, {"k": True})
    created = api.create_function("demo", "Demo", "class Filter:\n    pass\n", meta)
    assert created["meta"] == {**meta.stored(), "manifest": {}}  # no header in that code
    assert [f["id"] for f in api.functions()] == ["demo"]
    assert "content" not in api.functions()[0]
    assert FunctionMeta.of(api.function("demo")) == meta
    api.update_function("demo", "Demo", "class Filter:\n    x = 1\n", meta)
    assert api.function("demo")["content"].endswith("x = 1\n")
    assert api.toggle("demo")["is_active"] is True
    assert api.toggle_global("demo")["is_global"] is True
    api.update_valves("demo", {"LEVEL": "strict"})
    assert api.valves("demo") == {"LEVEL": "strict"}
    assert api.delete_function("demo") is True
    assert fake.state == {}


def test_over_urllib_an_error_status_keeps_its_body(served):
    """urllib raises HTTPError for a 4xx; the adapter answers with its status and body instead,
    so `call` can say why, and `request` (the live tests' Api) can return it."""
    _, api = served
    assert api.request("GET", "/api/v1/functions/list") == (401, {"detail": "nope"})
    with pytest.raises(OwppError, match=r"GET /api/v1/functions/id/x -> HTTP 401: .*not found"):
        api.as_account("sk-good").function("x")


def test_the_live_tests_api_returns_status_and_body_over_the_same_transport(served, monkeypatch):
    fake, api = served
    monkeypatch.setenv("OWPP_LIVE_URL", api.base_url)
    assert Api("sk-good")("GET", "/api/v1/functions/list") == (200, [])
    assert Api("wrong")("GET", "/api/v1/functions/list") == (401, {"detail": "nope"})
    assert Api("")("POST", "/api/v1/auths/signin", {"email": "x", "password": "y"})[0] == 400


def test_over_urllib_nothing_listening_is_not_healthy_and_the_wait_gives_up():
    api = OpenWebUI("http://127.0.0.1:1", urllib_fetch)
    assert api.healthy() is False
    with pytest.raises(OwppError, match="did not answer"):
        api.wait_for_health(attempts=2, delay=0)


# ---- health ----------------------------------------------------------------------------------


def test_the_wait_tries_again_until_it_answers():
    sleeps: list[float] = []
    fake = FakeOpenWebUI(starting=2)
    OpenWebUI(fake.base_url, fake).wait_for_health(attempts=3, delay=5, sleep=sleeps.append)
    assert sleeps == [5, 5]


def test_a_tls_failure_is_not_waited_out():
    def fetch(method, url, headers=None, body=None):
        error = ssl.SSLCertVerificationError("certificate verify failed")
        error.verify_message = "self-signed certificate"  # as OpenSSL sets it
        raise error

    sleeps: list[float] = []
    with pytest.raises(OwppError, match="TLS failed.*OPEN_WEBUI_CA_CERT"):
        OpenWebUI("https://x", fetch).wait_for_health(sleep=sleeps.append)
    assert sleeps == []


# ---- signing up ------------------------------------------------------------------------------


def test_the_first_account_signed_up_is_the_admin_who_adds_the_others():
    fake = FakeOpenWebUI()
    api = OpenWebUI(fake.base_url, fake)
    admin = api.sign_up("Ada", "ada@example.com", "pw")
    api.as_account(admin["token"]).add_user("Bob", "bob@example.com", "pw2")
    assert fake.accounts["bob@example.com"]["role"] == "user"
    assert api.sign_in("bob@example.com", "pw2")["role"] == "user"
    with pytest.raises(SignInRefused, match="already registered"):
        api.sign_up("Ada", "ada@example.com", "pw")


# ---- the meta the deploy stores --------------------------------------------------------------


def test_the_stored_meta_has_requires_always_and_sources_only_when_there_are_some():
    assert FunctionMeta("owpp", "d").stored() == {
        "description": "d",
        "managed_by": "owpp",
        "requires": {},
    }
    assert FunctionMeta("owpp", "d", {"g": "s"}).stored()["sources"] == {"g": "s"}


def test_meta_read_back_says_when_requires_was_never_recorded():
    """A function made by hand, or by an owpp from before `requires`, has none: None, not {}."""
    assert FunctionMeta.of({"meta": {"managed_by": "owpp"}}) == FunctionMeta("owpp")
    assert FunctionMeta.of({"meta": {"managed_by": "owpp"}}).requires is None
    assert FunctionMeta.of({"meta": {"requires": {}}}).requires == {}
    assert FunctionMeta.of({"meta": None}) == FunctionMeta.of({}) == FunctionMeta()
