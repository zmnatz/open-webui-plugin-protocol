"""What the mock cannot promise, asserted on a real Open-WebUI whose model is aimock, answering
from tools/screenshots/aimock/ (docs/testing/live.md)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

MODEL = "screenshot-model"
PLAIN = "Hello! I am the screenshot model"
AIMOCK = "http://127.0.0.1:4010"


def _requests() -> list[dict]:
    """Every chat request aimock has received, from its journal: what Open-WebUI sent."""
    url = AIMOCK + "/__aimock/journal?path=/v1/chat/completions"
    with urllib.request.urlopen(url, timeout=10) as response:
        return [entry["body"] for entry in json.loads(response.read()) if entry.get("body")]


def test_the_deployed_functions_are_installed_and_active(api):
    status, functions = api("GET", "/api/v1/functions/")
    assert status == 200
    by_id = {f["id"]: f for f in functions}
    for plugin in ("excalidraw", "stale_data", "page_banners"):
        assert plugin in by_id, f"{plugin} was not deployed"
        assert by_id[plugin]["is_active"], f"{plugin} is not active"


def test_a_public_tool_is_readable_by_a_user_who_is_not_the_owner(user_api):
    """`access: public` once used a grant Open-WebUI ignores for tools (the mock agreed)."""
    status, tools = user_api("GET", "/api/v1/tools/")
    assert status == 200
    assert "excalidraw" in {t["id"] for t in tools}


def test_the_scripted_model_answers_a_chat(user_api):
    status, models = user_api("GET", "/api/models")
    assert status == 200
    assert MODEL in {m["id"] for m in models["data"]}
    status, reply = user_api(
        "POST",
        "/api/chat/completions",
        {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": "Hi"}]},
    )
    assert status == 200
    assert PLAIN in reply["choices"][0]["message"]["content"]


def test_a_deployed_tool_is_offered_to_the_model_and_the_model_calls_it(user_api):
    """With `tool_ids`, Open-WebUI offers the deployed tool's functions to the model (the scripted
    model records the request) and hands back the call the model makes. It does not run the tool:
    for an API call with no saved chat, the client does that.

    By hand: in a chat with the Excalidraw tool on, ask for a drawing.
    """
    status, reply = user_api(
        "POST",
        "/api/chat/completions",
        {
            "model": MODEL,
            "stream": False,
            "tool_ids": ["excalidraw"],
            "messages": [{"role": "user", "content": "tool-offer-check-2d5c"}],
        },
    )
    assert status == 200, reply
    choice = reply["choices"][0]
    assert choice["finish_reason"] == "tool_calls", reply
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "show_excalidraw", reply
    offered = [
        [t["function"]["name"] for t in r.get("tools") or []]
        for r in _requests()
        if "tool-offer-check-2d5c" in str(r["messages"])
    ]
    assert any("show_excalidraw" in names for names in offered), offered


def test_an_outlet_turns_unfinished_reasoning_into_the_answer(user_api):
    """POST /api/chat/completed runs the outlets. A reply that ends in reasoning with no answer
    comes back as a message, in `output` (what 0.12+ renders) and in `content`."""
    reasoning = {"type": "reasoning", "id": "r1", "content": [{"type": "output_text", "text": "x"}]}
    assistant = {"role": "assistant", "content": "", "output": [reasoning]}
    # The endpoint checks that the chat belongs to the user, so it must exist.
    status, chat = user_api(
        "POST", "/api/v1/chats/new", {"chat": {"title": "outlet check", "messages": []}}
    )
    assert status == 200, chat
    status, reply = user_api(
        "POST",
        "/api/chat/completed",
        {
            "model": MODEL,
            "chat_id": chat["id"],
            "id": "m1",
            "session_id": "s1",
            "messages": [{"role": "user", "content": "Hi"}, assistant],
        },
    )
    assert status == 200, reply
    last = reply["messages"][-1]
    assert last["content"] == "x"
    assert last["output"][-1]["type"] == "message"


def test_an_inlet_can_send_a_message_with_an_image_to_another_model(api, user_api):
    """The vision_router filter's valve names a model; a message with an image is then sent to it
    (aimock's journal records the model it was asked for), and one without is not."""
    _, models = user_api("GET", "/api/models")
    known = sorted(m["id"] for m in models["data"])
    assert "screenshot-vision" in known, known
    before = api("GET", "/api/v1/functions/id/vision_router/valves")[1] or {}
    api(
        "POST",
        "/api/v1/functions/id/vision_router/valves/update",
        {**before, "vision_model_id": "screenshot-vision"},
    )
    try:
        image = {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
            },
        }
        for text, image_parts in (("routed-check-9c1d", [image]), ("plain-check-4b8e", [])):
            status, reply = user_api(
                "POST",
                "/api/chat/completions",
                {
                    "model": MODEL,
                    "stream": False,
                    "messages": [
                        {"role": "user", "content": [{"type": "text", "text": text}, *image_parts]}
                    ],
                },
            )
            assert status == 200, reply
        models = {
            text: {r["model"] for r in _requests() if text in str(r["messages"])}
            for text in ("routed-check-9c1d", "plain-check-4b8e")
        }
    finally:
        api("POST", "/api/v1/functions/id/vision_router/valves/update", before)
    assert models["routed-check-9c1d"] == {"screenshot-vision"}
    assert models["plain-check-4b8e"] == {MODEL}


# ---- Theme Designer Pro ---------------------------------------------------------------

TDP = "/api/v1/theme-designer"


def _get(path: str, token: str | None = None) -> tuple[int, str, str]:
    """A plain GET, as a page makes it: (status, content type, text)."""
    from conftest import URL

    request = urllib.request.Request(
        URL + path, headers={"Authorization": f"Bearer {token}"} if token else {}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return (
                response.status,
                response.headers.get("content-type", ""),
                response.read().decode(),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            error.headers.get("content-type", ""),
            error.read().decode(errors="replace"),
        )


def test_theme_designer_pros_routes_are_reached_ahead_of_open_webuis_own(api):
    """Its routes sit under /api/v1, where Open-WebUI's own API and its web app's catch-all also
    answer; plugin_mount has to put them first. A signed-out page gets the theme (the sign-in
    page is themed), and /static/loader.js carries the bootloader.

    By hand: in a private window, open /api/v1/theme-designer/theme.css: CSS (empty with no
    theme saved), not Open-WebUI's page or a 401.
    """
    status, kind, _ = _get(TDP + "/theme.css")
    assert (status, kind.split(";")[0]) == (200, "text/css")
    status, _, body = _get(TDP + "/state.json")
    assert status == 200 and body.startswith("{")
    assert "// owui-theme-designer-pro:start" in _get("/static/loader.js")[2]


def test_theme_designer_pros_designer_is_for_admins(api, user_api):
    """Only an admin opens the instance designer; a user is refused by owpp's guard.

    By hand: as a user, open /api/v1/theme-designer: {"detail": "Admins only."}.
    """
    status, kind, body = _get(TDP, api.token)
    assert status == 200 and "<title>Theme Designer Pro</title>" in body
    assert _get(TDP, user_api.token)[0] == 403


def test_theme_designer_pros_save_reaches_a_signed_out_page(api):
    """A save is served at once to someone not signed in, then Global Reset takes it away.

    By hand: save a theme in the designer; a private window's sign-in page reads it.
    """
    status, saved = api("POST", TDP, {"css": ":root { --tdp-live-check: 1; }\n", "state": "{}"})
    assert status == 200, saved
    try:
        assert "--tdp-live-check" in _get(TDP + "/theme.css")[2]
    finally:
        api("POST", TDP, {"reset": True})
    assert _get(TDP + "/theme.css")[2] == ""


def test_theme_designer_pros_launcher_and_skill_reach_a_user(user_api):
    """The function installs the Launcher and the skill with all seven files, and a user who is
    not an admin can use both (the grant Open-WebUI checks).

    By hand: as a user, Workspace > Tools lists Theme Designer Pro Launcher and Workspace >
    Skills lists theme-designer-pro.
    """
    status, tools = user_api("GET", "/api/v1/tools/")
    assert status == 200 and "theme_designer_pro_launcher" in {t["id"] for t in tools}
    status, skills = user_api("GET", "/api/v1/skills/")
    assert status == 200, skills
    listed = skills.get("items", skills) if isinstance(skills, dict) else skills
    assert "theme-designer-pro" in {s["id"] for s in listed}
