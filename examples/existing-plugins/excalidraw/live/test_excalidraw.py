"""Excalidraw on a real Open-WebUI v0.13.5: the chat page running the tool a model calls, the
editor in the Artifacts panel, and the round trip between the editor and the model.

aimock's `draw-model` (live/aimock/models.json) calls the tool for three messages: "Draw the
API and its database" (show), "Add a cache" (upsert) and "What is in the drawing" (read).
live/compose.yaml turns on iframe Sandbox Allow Same Origin, which the editor needs.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import pytest

from owpp.live import send, url

ID = "excalidraw"
MODEL = "live-draw"


@pytest.fixture(scope="module")
def draw_model(api):
    """A workspace model on aimock's draw-model, with the Excalidraw tool and native calling."""
    form = {
        "id": MODEL,
        "name": "Live draw",
        "base_model_id": "draw-model",
        "meta": {"description": "", "toolIds": [ID]},
        "params": {"function_calling": "native"},
    }
    status, body = api("POST", "/api/v1/models/create", form)
    if "already registered" in str(body):  # a stack kept up from an earlier run
        status, body = api("POST", f"/api/v1/models/model/update?id={MODEL}", form)
    assert status == 200, body
    return MODEL


def editor_frame(page, timeout: float = 60):
    """The editor's frame, inside the Artifacts panel, once its canvas is up."""
    end = time.time() + timeout
    while time.time() < end:
        for frame in page.frames:
            if "/excalidraw/view/" in frame.url:
                frame.wait_for_selector(".excalidraw", timeout=30_000)
                return frame
        page.wait_for_timeout(500)
    raise AssertionError(f"no editor frame; frames: {[f.url for f in page.frames]}")


def chat_id(page) -> str:
    assert "/c/" in page.url, page.url
    return page.url.rsplit("/c/", 1)[1].split("?")[0]


def drawing(client, chat: str) -> dict:
    status, body = client("GET", f"/api/v1/chats/{chat}")
    assert status == 200, body
    return (body.get("meta") or {}).get("excalidraw") or {}


def tool_results(aimock, ask: str) -> list[str]:
    """The tool results in the latest request to the model about `ask` (the journal keeps
    every run's)."""
    for request in reversed(aimock.requests()):
        messages = request["messages"]
        users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        if not users or ask not in str(messages[users[-1]].get("content")):
            continue  # another turn, or one of Open-WebUI's tasks (a title) quoting the chat
        results = [str(m.get("content")) for m in messages[users[-1] :] if m.get("role") == "tool"]
        if results:
            return results
    raise AssertionError(f"no tool result in a request about {ask!r}")


def get(path: str, token: str | None = None) -> int:
    request = urllib.request.Request(
        url() + path, headers={"Authorization": f"Bearer {token}"} if token else {}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def draw(page, model: str) -> str:
    page.goto(f"{url()}/?models={model}")
    send(page, "Draw the API and its database")
    page.get_by_text("Here is the diagram of the API and its database.").first.wait_for(
        timeout=60_000
    )
    return chat_id(page)


def test_the_tool_is_installed_for_users_and_the_function_is_global(api, user_api):
    """By hand: as a user who is not an admin, Workspace > Tools lists Excalidraw; as the
    admin, Functions shows Excalidraw on and global.
    """
    status, functions = api("GET", "/api/v1/functions/")
    assert status == 200
    excalidraw = {f["id"]: f for f in functions}[ID]
    assert (excalidraw["is_active"], excalidraw["is_global"]) == (True, True)
    status, tools = user_api("GET", "/api/v1/tools/")
    assert status == 200 and ID in {t["id"] for t in tools}, tools


def test_a_model_calling_show_opens_the_editor_in_the_panel_with_the_drawing(
    user, user_api, aimock, draw_model
):
    """The chat page runs the tool the model calls, the reply gets the editor, and the
    Artifacts panel opens it with the model's shapes; the drawing is saved in the chat.

    By hand: as a user, choose a model with Excalidraw on and ask "Draw the API and its
    database": the side panel opens an editor with two boxes and an arrow.
    """
    chat = draw(user, draw_model)
    frame = editor_frame(user)
    assert frame.url.endswith(f"/excalidraw/view/{chat}")
    saved = drawing(user_api, chat)
    assert (saved["version"], saved["writer"]) == (1, "tool")
    assert [e["id"] for e in saved["elements"]] == ["api", "db", "calls"]
    (result,) = tool_results(aimock, "Draw the API and its database")
    assert "excalidraw_artifact" in result and f"/excalidraw/view/{chat}" in result


def test_a_change_by_the_model_reaches_the_open_editor_and_the_editor_is_not_added_again(
    user, user_api, draw_model
):
    """By hand: with the editor open, ask "Add a cache": within a few seconds the box
    appears in the open editor, and the reply has no second editor.
    """
    chat = draw(user, draw_model)
    editor_frame(user)
    with user.expect_response(
        lambda r: (
            "/excalidraw/api/scenes/" in r.url and "since=1" in r.url and r.json().get("changed")
        ),
        timeout=60_000,
    ) as polled:
        send(user, "Add a cache")
        user.get_by_text("Added the cache.").first.wait_for(timeout=60_000)
    assert polled.value.json()["version"] == 2
    assert [e["id"] for e in polled.value.json()["elements"]][-1] == "cache"
    status, body = user_api("GET", f"/api/v1/chats/{chat}")
    replies = [m for m in body["chat"]["history"]["messages"].values() if m["role"] == "assistant"]
    assert sum("/excalidraw/view/" in (m.get("content") or "") for m in replies) == 1


def test_a_shape_drawn_in_the_editor_is_saved_and_the_model_reads_it(
    user, user_api, aimock, draw_model
):
    """By hand: draw a rectangle in the editor, then ask "What is in the drawing": the model
    is given the user's rectangle along with its own shapes.
    """
    chat = draw(user, draw_model)
    frame = editor_frame(user)
    canvas = frame.locator("canvas.interactive")
    box = canvas.bounding_box()
    frame.locator('[data-testid="toolbar-rectangle"]').click(force=True)  # a radio under its icon
    user.mouse.move(box["x"] + 150, box["y"] + box["height"] - 150)
    user.mouse.down()
    user.mouse.move(box["x"] + 300, box["y"] + box["height"] - 60, steps=8)
    user.mouse.up()
    end = time.time() + 15
    while time.time() < end and drawing(user_api, chat).get("version") != 2:
        user.wait_for_timeout(500)
    saved = drawing(user_api, chat)
    assert saved["version"] == 2 and saved["writer"] != "tool", saved
    assert len(saved["elements"]) > 3
    send(user, "What is in the drawing")
    user.get_by_text("I have read the drawing.").first.wait_for(timeout=60_000)
    (result,) = tool_results(aimock, "What is in the drawing")
    elements = json.loads(result)["elements"]
    assert len([e for e in elements if e["type"] == "rectangle"]) == 3, elements


def test_the_editor_needs_a_signed_in_writer_and_its_api_the_pages_token(api, user_api, draw_model):
    """By hand: open /excalidraw/view/<chat id> signed out (401) and as another user (404);
    a scene request with a wrong `t=` is Not found.
    """
    status, body = user_api(
        "POST",
        "/api/v1/chats/new",
        {"chat": {"title": "Mine", "messages": [], "history": {"messages": {}}}},
    )
    assert status == 200, body
    chat = body["id"]
    assert get(f"/excalidraw/view/{chat}") == 401
    assert get(f"/excalidraw/view/{chat}", api.token) == 404
    assert get(f"/excalidraw/view/{chat}", user_api.token) == 200
    assert get(f"/excalidraw/api/scenes/{chat}?t=nope") == 404


def test_without_same_origin_the_panel_says_to_sign_in(admin, api, draw_model):
    """The requirement in plugin.yaml: with iframe Sandbox Allow Same Origin off, the
    sandboxed panel sends no cookies, and the editor answers that you are not signed in.

    By hand: Settings > Interface > iframe Sandbox Allow Same Origin off, ask for a drawing:
    the panel says "Sign in to Open-WebUI first."
    """
    status, settings = api("GET", "/api/v1/users/user/settings")
    assert status == 200, settings
    ui = dict((settings or {}).get("ui") or {})
    status, body = api(
        "POST",
        "/api/v1/users/user/settings/update",
        {"ui": {**ui, "iframeSandboxAllowSameOrigin": False}},
    )
    assert status == 200, body
    try:
        draw(admin, draw_model)
        end = time.time() + 60
        frame = None
        while time.time() < end and frame is None:
            frame = next((f for f in admin.frames if "/excalidraw/view/" in f.url), None)
            admin.wait_for_timeout(500)
        assert frame is not None
        frame.get_by_text("Sign in to Open-WebUI first.").wait_for(timeout=30_000)
    finally:
        api("POST", "/api/v1/users/user/settings/update", {"ui": ui})


def test_disabled_the_tool_and_the_editor_are_gone(api, user_api):
    """By hand: switch Excalidraw off: Workspace > Tools no longer lists it, and an open
    editor answers Not found on reload. Switch it on again after.
    """
    status, body = api("POST", f"/api/v1/functions/id/{ID}/toggle")
    assert status == 200 and body["is_active"] is False, body
    try:
        status, tools = user_api("GET", "/api/v1/tools/")
        assert ID not in {t["id"] for t in tools}, tools
        assert get("/excalidraw/view/anything", api.token) == 404
    finally:
        status, body = api("POST", f"/api/v1/functions/id/{ID}/toggle")
        assert body["is_active"] is True, body
