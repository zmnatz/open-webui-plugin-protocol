"""The Excalidraw filter: the artifact it adds to replies, and the editor page and API it
serves, against a mock Open-WebUI. Run with `owpp test excalidraw`."""

import json
import re

import pytest

RECT = {"type": "rectangle", "id": "a", "x": 0, "y": 0, "width": 160, "height": 80}


@pytest.fixture
def ada(owui):
    return owui.add_user("Ada")


@pytest.fixture
def chat(owui, plugin, ada):
    """A chat with a drawing in it, made by the tool."""
    chat_id = owui.add_chat(ada)
    owui.tool("excalidraw").call("show_excalidraw", elements=[RECT], chat_id=chat_id)
    return chat_id


def token_for(owui, ada, chat):
    page = owui.client(ada).get(f"/excalidraw/view/{chat}")
    assert page.status_code == 200
    return re.search(r'const token = "([^"]+)";', page.text).group(1)


# ---- outlet: the artifact ------------------------------------------------------------


def reply_with_tool_result(artifact: str, earlier: list | None = None) -> dict:
    result = json.dumps({"version": 1, "excalidraw_artifact": artifact})
    return {
        "id": "m2",
        "messages": [
            *(earlier or []),
            {"role": "user", "content": "draw it"},
            {
                "id": "m2",
                "role": "assistant",
                "content": "Here it is.",
                "output": [{"type": "function_call_output", "output": result + "\n(context)"}],
            },
        ],
    }


def test_the_tools_artifact_is_added_to_the_reply_as_an_html_block(plugin):
    body = plugin.outlet(reply_with_tool_result("<iframe src='/x'></iframe>"))
    reply = body["messages"][-1]
    assert reply["content"] == "Here it is.\n\n```html\n<iframe src='/x'></iframe>\n```"
    assert reply["output"][-1]["type"] == "message"


def test_an_artifact_an_earlier_reply_already_shows_is_not_added_again(plugin):
    html = "<iframe src='/x'></iframe>"
    earlier = [{"role": "assistant", "content": f"```html\n{html}\n```"}]
    body = plugin.outlet(reply_with_tool_result(html, earlier))
    assert body["messages"][-1]["content"] == "Here it is."


def test_a_reply_without_the_tool_passes_through(plugin):
    body = {"messages": [{"role": "assistant", "content": "hi"}]}
    assert plugin.outlet(json.loads(json.dumps(body))) == body


def test_inlet_leaves_the_request_alone(plugin, ada):
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert plugin.inlet(dict(body), user=ada) == body


# ---- the editor page -----------------------------------------------------------------


def test_the_page_needs_a_signed_in_user(owui, chat):
    assert owui.client().get(f"/excalidraw/view/{chat}").status_code == 401
    browser = owui.client(follow_redirects=False).get(
        f"/excalidraw/view/{chat}", headers={"accept": "text/html"}
    )
    assert browser.status_code == 302
    assert browser.headers["location"] == f"/auth?redirect=%2Fexcalidraw%2Fview%2F{chat}"


def test_the_page_is_only_for_people_who_can_write_to_the_chat(owui, chat):
    bob = owui.add_user("Bob")
    assert owui.client(bob).get(f"/excalidraw/view/{chat}").status_code == 404
    owui.grant_chat(chat, bob, "read")
    assert owui.client(bob).get(f"/excalidraw/view/{chat}").status_code == 404
    owui.grant_chat(chat, bob, "write")
    assert owui.client(bob).get(f"/excalidraw/view/{chat}").status_code == 200


def test_the_page_carries_a_token_for_this_chat_and_is_never_cached(owui, ada, chat):
    page = owui.client(ada).get(f"/excalidraw/view/{chat}")
    assert page.headers["cache-control"] == "no-store"
    assert re.search(r'const token = "s\.\d+\.[\w-]+";', page.text)
    assert "__TOKEN__" not in page.text and "__VERSION__" not in page.text


def test_the_token_lasts_as_long_as_the_valve_says(owui, ada, chat):
    import time

    owui.set_valves("excalidraw", SESSION_TOKEN_HOURS=1)
    expiry = int(token_for(owui, ada, chat).split(".")[1])
    assert 3500 < expiry - time.time() <= 3600


# ---- the editor's API (token, not session) ----------------------------------------------


def test_the_api_serves_the_drawing_with_the_pages_token(owui, ada, chat):
    token = token_for(owui, ada, chat)
    api = owui.client()  # the sandboxed iframe sends no cookies
    got = api.get(f"/excalidraw/api/scenes/{chat}", params={"t": token})
    assert got.status_code == 200
    assert got.headers["access-control-allow-origin"] == "*"
    assert got.json()["elements"] == [RECT] and got.json()["changed"] is True
    same = api.get(f"/excalidraw/api/scenes/{chat}", params={"t": token, "since": 1})
    assert same.json() == {"changed": False, "version": 1}


def test_the_api_refuses_a_missing_wrong_or_other_chats_token(owui, ada, chat):
    other = owui.add_chat(ada)
    api = owui.client()
    assert api.get(f"/excalidraw/api/scenes/{chat}").status_code == 404
    assert api.get(f"/excalidraw/api/scenes/{chat}", params={"t": "s.9999999999.x"}).status_code == 404
    other_token = token_for(owui, ada, other)
    assert api.get(f"/excalidraw/api/scenes/{chat}", params={"t": other_token}).status_code == 404


def test_the_editor_saves_the_users_edits_for_the_model_to_read(owui, ada, chat):
    token = token_for(owui, ada, chat)
    edited = [{**RECT, "x": 300}]
    saved = owui.client().post(
        f"/excalidraw/api/scenes/{chat}",
        params={"t": token},
        content=json.dumps({"client": "browser-1", "elements": edited}),
        headers={"content-type": "text/plain"},
    )
    assert saved.json() == {"version": 2}
    stored = owui.chat(chat).meta["excalidraw"]
    assert stored["elements"] == edited and stored["writer"] == "browser-1"
    read = json.loads(owui.tool("excalidraw").call("read_excalidraw", chat_id=chat))
    assert read["elements"][0]["x"] == 300


def test_a_malformed_save_is_refused(owui, ada, chat):
    token = token_for(owui, ada, chat)
    for body in ("not json", '{"elements": []}', '{"client": "c", "elements": {}}'):
        got = owui.client().post(f"/excalidraw/api/scenes/{chat}", params={"t": token}, content=body)
        assert got.status_code == 400, body


def test_once_disabled_nothing_is_served(owui, ada, chat):
    token = token_for(owui, ada, chat)
    owui.disable("excalidraw")
    assert owui.client(ada).get(f"/excalidraw/view/{chat}").status_code == 404
    assert owui.client().get(f"/excalidraw/api/scenes/{chat}", params={"t": token}).status_code == 404


def test_a_new_version_replaces_the_routes_instead_of_adding_to_them(owui, plugin, chat):
    def mounted():
        return [r for r in owui.app.routes if str(getattr(r, "path", "")).startswith("/excalidraw")]

    before = len(mounted())
    owui.update("excalidraw")
    assert len(mounted()) == before
    assert owui.app.routes[-1].name == "spa-static-files"  # still ahead of the catch-all
