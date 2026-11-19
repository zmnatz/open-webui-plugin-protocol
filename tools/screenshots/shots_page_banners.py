"""Page Banners on a real Open-WebUI: the admin's banners in every chat, live."""

from __future__ import annotations

import time

import pytest
from conftest import URL

MAINTENANCE = {
    "id": "maintenance",
    "type": "info",
    "title": "Maintenance",
    "content": "Open-WebUI restarts at **18:00 UTC** for an upgrade.",
    "dismissible": True,
    "timestamp": int(time.time()),
}
POLICY = {
    "id": "policy",
    "type": "warning",
    "title": "New data policy",
    "content": "Chats older than 90 days are archived from next month.",
    "dismissible": False,
    "timestamp": int(time.time()),
}


def banners(api, *items) -> None:
    """Admin Settings > General > Banners, saved."""
    api("POST", "/api/v1/configs/banners", {"banners": list(items)})


@pytest.fixture(scope="module")
def chat(api):
    """An existing chat to open, so the banners are seen where Open-WebUI shows none itself."""
    now = int(time.time())
    created = api(
        "POST",
        "/api/v1/chats/import",
        {
            "chats": [
                {
                    "chat": {
                        "title": "Release planning",
                        "messages": [
                            {
                                "id": "u1",
                                "role": "user",
                                "content": "What is left for the release?",
                            },
                            {
                                "id": "a1",
                                "parentId": "u1",
                                "role": "assistant",
                                "content": "Two reviews and the changelog.",
                            },
                        ],
                        "history": {
                            "currentId": "a1",
                            "messages": {
                                "u1": {
                                    "id": "u1",
                                    "role": "user",
                                    "content": "What is left for the release?",
                                    "childrenIds": ["a1"],
                                },
                                "a1": {
                                    "id": "a1",
                                    "parentId": "u1",
                                    "role": "assistant",
                                    "content": "Two reviews and the changelog.",
                                    "childrenIds": [],
                                },
                            },
                        },
                    },
                    "created_at": now,
                    "updated_at": now,
                }
            ]
        },
    )
    return created[0]["id"]


def open_chat(page, chat_id: str) -> None:
    page.goto(f"{URL}/c/{chat_id}")
    page.locator("#owui-page-banners").get_by_text("Maintenance").wait_for(timeout=30_000)
    page.wait_for_timeout(800)  # the banner's entrance animation


def test_banners_show_in_every_chat(admin, api, shot, chat):
    """By hand: add a banner under Admin Settings > General > Banners and open any chat. The
    banner is at the top of the chat, not only on the new-chat screen."""
    banners(api, MAINTENANCE)
    open_chat(admin, chat)
    shot(
        admin,
        "page_banners",
        "banner-in-a-chat",
        "An admin banner at the top of an existing chat, where Open-WebUI itself shows none.",
        illustrates=[
            "test_the_script_and_the_stylesheet_are_published_into_the_shared_files",
            "test_the_valves_reach_the_script_as_its_config",
        ],
    )


def test_an_edit_reaches_an_open_tab(admin, api, shot, chat):
    """By hand: keep a chat open, and in another tab add a second banner. It appears in the
    first tab without a reload."""
    banners(api, MAINTENANCE)
    open_chat(admin, chat)
    banners(api, MAINTENANCE, POLICY)
    admin.locator("#owui-page-banners").get_by_text("New data policy").wait_for(timeout=30_000)
    admin.wait_for_timeout(800)
    shot(
        admin,
        "page_banners",
        "live-update",
        "A second banner, added by an admin while this chat was open, appears without a reload.",
        illustrates=["test_an_admin_edit_is_pushed_to_open_tabs"],
    )


def test_collapsed_into_a_pill(admin, api, shot, chat):
    """By hand: click the pill above the banners. They fold into it, and stay folded after a
    reload."""
    banners(api, MAINTENANCE, POLICY)
    open_chat(admin, chat)
    admin.locator("#owui-page-banners .opb-pill").click()
    admin.wait_for_timeout(1500)
    shot(
        admin,
        "page_banners",
        "collapsed",
        "The banners folded into the pill, which counts them. The choice is remembered.",
    )
    admin.locator("#owui-page-banners .opb-pill").click()  # unfold again for the next shots


def test_above_the_message_input(admin, api, shot, chat):
    """By hand: set the function's position valve to bottom and save, then reload a chat. The
    banners sit right above the message input."""
    banners(api, MAINTENANCE)
    before = api.valves("page_banners", position="bottom")
    try:
        open_chat(admin, chat)
        shot(
            admin,
            "page_banners",
            "position-bottom",
            "With the position valve set to bottom, the banner sits above the message input.",
            illustrates=["test_the_valves_reach_the_script_as_its_config"],
        )
    finally:
        api("POST", "/api/v1/functions/id/page_banners/valves/update", before)
