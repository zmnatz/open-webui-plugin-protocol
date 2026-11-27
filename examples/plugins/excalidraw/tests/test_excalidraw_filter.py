"""The Excalidraw filter: the artifact it adds to replies, and the editor page and API it
serves, on the test harness. Run with `owpp test excalidraw`."""

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
    """When the tool's result carries an artifact, the filter appends it to the reply as an html
    code block.

    By hand: ask the model to draw something. The reply ends with an html code block and the
    editor opens in the Artifacts panel.
    """
    body = plugin.outlet(reply_with_tool_result("<iframe src='/x'></iframe>"))
    reply = body["messages"][-1]
    assert reply["content"] == "Here it is.\n\n```html\n<iframe src='/x'></iframe>\n```"
    assert reply["output"][-1]["type"] == "message"


def test_an_artifact_an_earlier_reply_already_shows_is_not_added_again(plugin):
    """An artifact that an earlier reply in the chat already shows is not appended again.

    By hand: in a chat that has a drawing, ask the model to show the drawing again. The new
    reply has no second html block, and the Artifacts panel still shows one editor.
    """
    html = "<iframe src='/x'></iframe>"
    earlier = [{"role": "assistant", "content": f"```html\n{html}\n```"}]
    body = plugin.outlet(reply_with_tool_result(html, earlier))
    assert body["messages"][-1]["content"] == "Here it is."


def test_a_reply_without_the_tool_passes_through(plugin):
    """A reply in which the tool was not called is left exactly as it was.

    By hand: ask something that needs no drawing ("say hi"). The reply has no html block.
    """
    body = {"messages": [{"role": "assistant", "content": "hi"}]}
    assert plugin.outlet(json.loads(json.dumps(body))) == body


def test_inlet_leaves_the_request_alone(plugin, ada):
    """The filter does not change what the user sends.

    By hand: send a message: the model answers it as written. (Nothing else to see.)
    """
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert plugin.inlet(dict(body), user=ada) == body


# ---- the editor page -----------------------------------------------------------------


def test_the_page_needs_a_signed_in_user(owui, chat):
    """The editor page needs a signed-in user. A browser is sent to the sign-in page, with a
    redirect back; any other client gets 401.

    By hand: copy the editor's URL, /excalidraw/view/<chat id>, into a private window. You land
    on /auth, and after signing in you are back on the editor. `curl -i <URL>` gets 401.
    """
    assert owui.client().get(f"/excalidraw/view/{chat}").status_code == 401
    browser = owui.client(follow_redirects=False).get(
        f"/excalidraw/view/{chat}", headers={"accept": "text/html"}
    )
    assert browser.status_code == 302
    assert browser.headers["location"] == f"/auth?redirect=%2Fexcalidraw%2Fview%2F{chat}"


def test_the_page_is_only_for_people_who_can_write_to_the_chat(owui, chat):
    """Only someone who can write to the chat may open its editor. Without access, or with read
    access only, the answer is 404, which does not reveal that the chat exists.

    By hand: as a second user, open /excalidraw/view/<the first user's chat id>: 404. Give them
    read access to the chat: still 404. Give them write access: the editor opens.
    """
    bob = owui.add_user("Bob")
    assert owui.client(bob).get(f"/excalidraw/view/{chat}").status_code == 404
    owui.grant_chat(chat, bob, "read")
    assert owui.client(bob).get(f"/excalidraw/view/{chat}").status_code == 404
    owui.grant_chat(chat, bob, "write")
    assert owui.client(bob).get(f"/excalidraw/view/{chat}").status_code == 200


def test_the_page_carries_a_token_for_this_chat_and_is_never_cached(owui, ada, chat):
    """The editor page embeds a signed token for its chat (s.<expiry>.<signature>), has every
    placeholder filled in, and is sent with Cache-Control: no-store.

    By hand: open the editor with the browser's network tab open. The page's response headers
    include cache-control: no-store. View source: it has const token = "s.…", and no __TOKEN__
    or __VERSION__.
    """
    page = owui.client(ada).get(f"/excalidraw/view/{chat}")
    assert page.headers["cache-control"] == "no-store"
    assert re.search(r'const token = "s\.\d+\.[\w-]+";', page.text)
    assert "__TOKEN__" not in page.text and "__VERSION__" not in page.text


def test_the_token_lasts_as_long_as_the_valve_says(owui, ada, chat):
    """The SESSION_TOKEN_HOURS valve sets how long the page's token is good for.

    By hand: set the Excalidraw function's SESSION_TOKEN_HOURS valve to 2 and reload the editor.
    In its source, the number after s. in the token is a Unix time about two hours from now (`date
    -d @<number>`). (Not 1: code that ignored the valve for a fixed hour would pass.)
    """
    import time

    owui.set_valves("excalidraw", SESSION_TOKEN_HOURS=2)
    expiry = int(token_for(owui, ada, chat).split(".")[1])
    assert 7100 < expiry - time.time() <= 7200


# ---- the editor's API (token, not session) ----------------------------------------------


def test_the_api_serves_the_drawing_with_the_pages_token(owui, ada, chat):
    """The editor's API serves the drawing to whoever holds the page's token, without a session.
    It sends no CORS header: the editor is same-origin, since it needs iframe Sandbox Allow Same
    Origin. Asked again with since=<that version>, it answers that nothing changed.

    By hand: copy the token from the editor's source and run `curl -i
    '<host>/excalidraw/api/scenes/<chat id>?t=<token>'`: the elements and changed: true. Add
    `&since=<the version it returned>`: {"changed": false, ...}.
    """
    token = token_for(owui, ada, chat)
    api = owui.client()  # no session: the token is the access check
    got = api.get(f"/excalidraw/api/scenes/{chat}", params={"t": token})
    assert got.status_code == 200
    assert "access-control-allow-origin" not in got.headers
    assert got.json()["elements"] == [RECT] and got.json()["changed"] is True
    same = api.get(f"/excalidraw/api/scenes/{chat}", params={"t": token, "since": 1})
    assert same.json() == {"changed": False, "version": 1}


def test_the_api_refuses_a_missing_wrong_or_other_chats_token(owui, ada, chat):
    """Without a token, with a made-up one, or with another chat's token, the API answers 404.

    By hand: repeat the curl above without ?t=, with t=s.9999999999.x, and with the token from a
    second chat's editor page. Each one gets 404.
    """
    other = owui.add_chat(ada)
    api = owui.client()
    assert api.get(f"/excalidraw/api/scenes/{chat}").status_code == 404
    assert (
        api.get(f"/excalidraw/api/scenes/{chat}", params={"t": "s.9999999999.x"}).status_code == 404
    )
    other_token = token_for(owui, ada, other)
    assert api.get(f"/excalidraw/api/scenes/{chat}", params={"t": other_token}).status_code == 404


def test_the_editor_saves_the_users_edits_for_the_model_to_read(owui, ada, chat):
    """An edit made in the editor is saved into the chat (the next version, marked with the
    browser's id), and the model's read_excalidraw sees it.

    By hand: in the editor, drag the rectangle to the right and wait a moment. Reload the
    editor: it is still moved. Ask the model what the drawing looks like: it calls
    read_excalidraw and describes the new position.
    """
    token = token_for(owui, ada, chat)
    edited = [{**RECT, "x": 300}]
    saved = owui.client().post(
        f"/excalidraw/api/scenes/{chat}",
        params={"t": token},
        content=json.dumps({"client": "browser-1", "elements": edited}),
        headers={"content-type": "application/json"},
    )
    assert saved.json() == {"version": 2}
    stored = owui.chat(chat).meta["excalidraw"]
    assert stored["elements"] == edited and stored["writer"] == "browser-1"
    read = json.loads(owui.tool("excalidraw").call("read_excalidraw", chat_id=chat))
    assert read["elements"][0]["x"] == 300


def test_a_malformed_save_is_refused(owui, ada, chat):
    """A save that is not JSON, has no client, or whose elements is not a list gets 400.

    By hand: `curl -i -X POST '<host>/excalidraw/api/scenes/<chat id>?t=<token>' -d 'not json'`:
    400. The same with `-d '{"elements": []}'` and with `-d '{"client": "c", "elements": {}}'`.
    """
    token = token_for(owui, ada, chat)
    for body in ("not json", '{"elements": []}', '{"client": "c", "elements": {}}'):
        got = owui.client().post(
            f"/excalidraw/api/scenes/{chat}", params={"t": token}, content=body
        )
        assert got.status_code == 400, body


def test_once_disabled_nothing_is_served(owui, ada, chat):
    """Once the function is disabled, neither the editor page nor its API is served, even with a
    valid token.

    By hand: with an editor open, switch Excalidraw off under Admin Panel > Functions. Reload
    the editor: 404. The API curl with the token: 404.
    """
    token = token_for(owui, ada, chat)
    owui.disable("excalidraw")
    assert owui.client(ada).get(f"/excalidraw/view/{chat}").status_code == 404
    assert (
        owui.client().get(f"/excalidraw/api/scenes/{chat}", params={"t": token}).status_code == 404
    )


def test_a_new_version_replaces_the_routes_instead_of_adding_to_them(owui, plugin, chat):
    """Updating the function replaces its routes rather than adding a second copy, and they stay
    ahead of Open-WebUI's catch-all web app.

    By hand: save the function's code again (Admin Panel > Functions > Excalidraw > Save), then
    open the editor: the editor loads, not the Open-WebUI app. That the routes were not
    duplicated can only be seen in this test.
    """

    def mounted():
        return [r for r in owui.app.routes if str(getattr(r, "path", "")).startswith("/excalidraw")]

    before = len(mounted())
    owui.update("excalidraw")
    assert len(mounted()) == before
    assert owui.app.routes[-1].name == "spa-static-files"  # still ahead of the catch-all
