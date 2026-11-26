"""What only Open-WebUI's own chat page does, asserted in a browser (Playwright) on the same
stack as test_live.py: the pages are signed in on the real login page, and aimock answers."""

from __future__ import annotations

import pytest
from owpp_live import send, url

MODEL = "live-diagram-assistant"


@pytest.fixture(scope="module")
def diagram_model(api):
    """A workspace model on aimock's screenshot-model, with the Excalidraw tool and native calling."""
    status, body = api(
        "POST",
        "/api/v1/models/create",
        {
            "id": MODEL,
            "base_model_id": "screenshot-model",
            "name": "Live diagram assistant",
            "meta": {"toolIds": ["excalidraw"]},
            "params": {"function_calling": "native"},
        },
    )
    assert status == 200, body
    yield MODEL
    api("POST", "/api/v1/models/model/delete", {"id": MODEL})


def test_the_chat_page_runs_the_tool_the_model_calls_and_answers_with_its_result(
    admin, aimock, diagram_model
):
    """Over the API a tool call comes back to the caller (test_live.py); the chat page runs it:
    the deployed tool's result goes back to the model, and its answer is the reply.

    By hand: in a chat with a model that has the Excalidraw tool, ask for a drawing. The reply
    says "Here is the diagram".
    """
    ask = "Draw the API of the live suite and its database."
    admin.goto(f"{url()}/?models={MODEL}")
    send(admin, ask)
    admin.get_by_text("Here is the diagram").first.wait_for(timeout=60_000)
    asked = [r for r in aimock.requests() if ask in str(r["messages"])]
    results = [m for r in asked for m in r["messages"] if m.get("role") == "tool"]
    assert any("excalidraw_artifact" in str(m.get("content")) for m in results), asked[-1:]
