"""What the mock cannot promise, asserted on a real Open-WebUI with the scripted model
(tools/screenshots/fake_llm.py)."""

from __future__ import annotations

MODEL = "screenshot-model"
PLAIN = "Hello! I am the screenshot model"


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


def test_the_model_can_call_the_deployed_tool(user_api):
    """The script calls `show_excalidraw` whenever it is offered; the reply after the tool
    has answered is the script's text."""
    status, reply = user_api(
        "POST",
        "/api/chat/completions",
        {
            "model": MODEL,
            "stream": False,
            "tool_ids": ["excalidraw"],
            "messages": [{"role": "user", "content": "Draw an API and a database"}],
        },
    )
    assert status == 200
    assert "Here is the diagram" in reply["choices"][0]["message"]["content"]


FAKE_LLM = "http://127.0.0.1:9000"


def _requests() -> list[dict]:
    import json
    import urllib.request

    with urllib.request.urlopen(FAKE_LLM + "/requests", timeout=10) as response:
        return json.loads(response.read())["requests"]


def test_an_outlet_turns_unfinished_reasoning_into_the_answer(user_api):
    """POST /api/chat/completed runs the outlets. A reply that ends in reasoning with no answer
    comes back as a message, in `output` (what 0.12+ renders) and in `content`."""
    reasoning = {"type": "reasoning", "id": "r1", "content": [{"type": "output_text", "text": "x"}]}
    assistant = {"role": "assistant", "content": "", "output": [reasoning]}
    status, reply = user_api(
        "POST",
        "/api/chat/completed",
        {
            "model": MODEL,
            "chat_id": "live-test",
            "id": "m1",
            "session_id": "s1",
            "messages": [{"role": "user", "content": "Hi"}, assistant],
        },
    )
    assert status == 200
    last = reply["messages"][-1]
    assert last["content"] == "x"
    assert last["output"][-1]["type"] == "message"


def test_an_inlet_can_send_a_message_with_an_image_to_another_model(api, user_api):
    """The vision_router filter's valve names a model; a message with an image is then sent to it
    (the scripted model records the model it was asked for), and one without is not."""
    before = api("GET", "/api/v1/functions/id/vision_router/valves")[1] or {}
    api(
        "POST",
        "/api/v1/functions/id/vision_router/valves/update",
        {**before, "vision_model_id": "screenshot-vision"},
    )
    try:
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
        for text, image_parts in (("routed-check-9c1d", [image]), ("plain-check-4b8e", [])):
            status, _ = user_api(
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
            assert status == 200
        models = {
            text: {r["model"] for r in _requests() if text in str(r["messages"])}
            for text in ("routed-check-9c1d", "plain-check-4b8e")
        }
    finally:
        api("POST", "/api/v1/functions/id/vision_router/valves/update", before)
    assert models["routed-check-9c1d"] == {"screenshot-vision"}
    assert models["plain-check-4b8e"] == {MODEL}
