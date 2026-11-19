"""The Stale Data Dashboard on a real Open-WebUI, with chats that really are old."""

from __future__ import annotations

import time

import pytest
from conftest import URL

DAY = 86400


def old_chat(title: str, days: int, pinned: bool = False) -> dict:
    when = int(time.time()) - days * DAY
    return {
        "chat": {"title": title, "messages": [], "history": {"messages": {}, "currentId": None}},
        "pinned": pinned,
        "created_at": when - DAY,
        "updated_at": when,
    }


@pytest.fixture(scope="module", autouse=True)
def old_chats(api, user_api):
    """Chats last touched days ago, for the admin and for a user (Open-WebUI's chat import keeps
    their timestamps), plus one fresh chat that must not be listed."""
    api(
        "POST",
        "/api/v1/chats/import",
        {
            "chats": [
                old_chat("Q3 roadmap draft", 41, pinned=True),
                old_chat("Vendor comparison", 12),
            ]
        },
    )
    user_api(
        "POST",
        "/api/v1/chats/import",
        {
            "chats": [
                old_chat("Trip itinerary", 27),
                old_chat("Cover letter ideas", 3),
                {**old_chat("Fresh chat, not stale", 0), "updated_at": int(time.time())},
            ]
        },
    )


def test_the_dashboard_lists_what_is_old(admin, shot):
    """By hand: as an admin, open /stale-data. Chats older than STALE_THRESHOLD_HOURS are
    listed with their owners, the pinned one is marked, and the fresh one is not there."""
    admin.goto(f"{URL}/stale-data")
    admin.get_by_text("Q3 roadmap draft").wait_for()
    shot(
        admin,
        "stale_data",
        "dashboard",
        "The dashboard as an admin: chats older than the threshold, with owners, flags and age. "
        "The fresh chat is not listed.",
        illustrates=["test_it_lists_what_is_older_than_the_threshold_and_not_the_rest"],
        full_page=True,
    )


def test_a_user_is_refused(user, shot):
    """By hand: open /stale-data as a user who is not an admin. The answer is 403, "Admins
    only."."""
    user.goto(f"{URL}/stale-data")
    user.get_by_text("Admins only.").wait_for()
    shot(
        user,
        "stale_data",
        "not-an-admin",
        'A user who is not an admin gets 403, "Admins only.".',
        illustrates=["test_only_admins_see_it"],
    )
