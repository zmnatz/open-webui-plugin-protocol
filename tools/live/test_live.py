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
