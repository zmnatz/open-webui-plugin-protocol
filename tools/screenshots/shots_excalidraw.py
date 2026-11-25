"""Excalidraw on a real Open-WebUI: a model draws, and the editor opens beside the reply."""

from __future__ import annotations

import re

import pytest
from conftest import URL, send

MODEL = "diagram-assistant"
ASK = "Draw our API and the database it reads from."


@pytest.fixture(scope="module")
def diagram_model(api):
    """A workspace model on aimock's screenshot-model, with the Excalidraw tool and native calling."""
    api(
        "POST",
        "/api/v1/models/create",
        {
            "id": MODEL,
            "base_model_id": "screenshot-model",
            "name": "Diagram assistant",
            "meta": {"toolIds": ["excalidraw"], "description": "Draws with Excalidraw"},
            "params": {"function_calling": "native"},
        },
    )
    yield MODEL
    api("POST", "/api/v1/models/model/delete", {"id": MODEL})


def same_origin(api, allowed: bool) -> None:
    """Admin Settings > General > Default Interface Settings: iframe Sandbox Allow Same Origin."""
    config = api("GET", "/api/v1/auths/admin/config")
    defaults = dict(config.get("DEFAULT_INTERFACE_SETTINGS") or {})
    defaults["iframeSandboxAllowSameOrigin"] = allowed
    api("POST", "/api/v1/auths/admin/config", {**config, "DEFAULT_INTERFACE_SETTINGS": defaults})


def ask_for_a_drawing(page) -> None:
    page.goto(f"{URL}/?models={MODEL}")
    send(page, ASK)
    page.get_by_text("Here is the diagram").wait_for(timeout=60_000)


def editor_frame(page):
    for _ in range(120):
        for frame in page.frames:
            if "/excalidraw/view/" in frame.url:
                return frame
        page.wait_for_timeout(500)
    raise AssertionError("the Artifacts panel never opened the editor")


def test_the_editor_opens_beside_the_reply(admin, api, shot, diagram_model):
    """By hand: ask a model that has the Excalidraw tool to draw something. The reply says so,
    and the editor opens in the Artifacts panel with the drawing in it."""
    same_origin(api, True)
    ask_for_a_drawing(admin)
    frame = editor_frame(admin)
    frame.locator(".excalidraw canvas").first.wait_for(timeout=60_000)
    admin.wait_for_timeout(2000)  # the hand-drawn font, and the scene's first poll
    shot(
        admin,
        "excalidraw",
        "editor-in-chat",
        "The model called show_excalidraw; the filter added the editor to the reply, and it "
        "opened in the Artifacts panel with the drawing.",
        illustrates=[
            "test_the_tools_artifact_is_added_to_the_reply_as_an_html_block",
            "test_show_creates_the_drawing_and_hands_the_filter_an_artifact",
            "test_the_api_serves_the_drawing_with_the_pages_token",
        ],
    )


def test_without_same_origin_the_editor_is_refused(admin, api, shot, diagram_model):
    """By hand: with "iframe Sandbox Allow Same Origin" off (Open-WebUI's default), ask for a
    drawing. The panel shows {"detail": "Sign in to Open-WebUI first."}: the sandboxed panel
    sends no session cookie, so the editor page cannot tell who you are."""
    same_origin(api, False)
    try:
        ask_for_a_drawing(admin)
        frame = editor_frame(admin)
        frame.get_by_text("Sign in to Open-WebUI first.").wait_for(timeout=30_000)
        shot(
            admin,
            "excalidraw",
            "editor-without-same-origin",
            'Known limitation: with "iframe Sandbox Allow Same Origin" off, Open-WebUI\'s '
            "default, the editor page gets no session and answers 401.",
        )
    finally:
        same_origin(api, True)


def test_signed_out_the_editor_sends_you_to_sign_in(signed_out, shot):
    """By hand: open an editor address in a private window. You land on the sign-in page, and
    after signing in you are taken back to the editor."""
    signed_out.goto(f"{URL}/excalidraw/view/an-example-chat")
    signed_out.wait_for_url(re.compile(r".*/auth\?redirect=%2Fexcalidraw%2Fview%2F.*"))
    signed_out.locator("input[name=email]").wait_for()
    shot(
        signed_out,
        "excalidraw",
        "signed-out-redirect",
        "Signed out, the editor's address sends the browser to Open-WebUI's sign-in page, "
        "with a redirect back to the editor.",
        illustrates=["test_the_page_needs_a_signed_in_user"],
    )
