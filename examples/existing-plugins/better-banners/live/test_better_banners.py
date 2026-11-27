"""Better Banners on a real Open-WebUI v0.13.5: what its script does on the chat page.

The unit tests (plugins/better_banners/tests) cover the server side: the script in
/static/loader.js and the socket signal. These cover what only a browser shows: where the
banners go, collapsing and dismissing, live updates, rendering, and the language.
"""

from __future__ import annotations

import time
import urllib.request

import pytest

from owpp.live import url

ID = "better_banners"
ROOT = "#owui-better-banners"


def banner(id: str, content: str, **extra) -> dict:
    return {
        "id": id,
        "type": extra.pop("type", "info"),
        "title": extra.pop("title", ""),
        "content": content,
        "dismissible": extra.pop("dismissible", False),
        "timestamp": int(time.time()),
        **extra,
    }


@pytest.fixture
def set_banners(api):
    """Save the admin's banners (Admin Panel > Settings > General > Banners); none after."""

    def save(*items):
        status, body = api("POST", "/api/v1/configs/banners", {"banners": list(items)})
        assert status == 200, body
        return body

    yield save
    save()


def new_chat(client) -> str:
    status, body = client(
        "POST",
        "/api/v1/chats/new",
        {"chat": {"title": "Banners", "messages": [], "history": {"messages": {}}}},
    )
    assert status == 200, body
    return body["id"]


@pytest.fixture
def admin_chat(api) -> str:
    return new_chat(api)


@pytest.fixture
def valves(api):
    """Save Better Banners' valves; its defaults again after."""

    def save(**values):
        status, body = api("POST", f"/api/v1/functions/id/{ID}/valves/update", values)
        assert status == 200, body

    yield save
    save(position="top", max_height_px=160, resync_interval_seconds=300)


def open_chat(page, chat_id: str) -> None:
    page.goto(f"{url()}/c/{chat_id}")
    page.wait_for_function("window.__owuiBetterBanners === true", timeout=60_000)


def test_a_banner_shows_at_the_top_of_an_open_chat(admin, admin_chat, set_banners):
    """By hand: add a banner, open an existing chat: it is at the top of the chat pane."""
    set_banners(banner("b1", "Maintenance at noon"))
    open_chat(admin, admin_chat)
    root = admin.locator(ROOT)
    root.get_by_text("Maintenance at noon").wait_for(timeout=30_000)
    assert root.get_attribute("data-position") == "top"
    assert root.evaluate("el => el.parentElement.id") == "chat-pane"


def test_a_user_who_is_not_an_admin_sees_them_too(user, user_api, set_banners):
    """By hand: sign in as a user, open one of their chats: the banner is there."""
    set_banners(banner("b1", "For everyone"))
    open_chat(user, new_chat(user_api))
    user.locator(ROOT).get_by_text("For everyone").wait_for(timeout=30_000)


def test_it_is_not_on_the_new_chat_screen_where_open_webui_shows_its_own(admin, set_banners):
    """Open-WebUI shows the banners itself on the new-chat screen; Better Banners stays out
    of it, so each shows once.

    By hand: with a banner, open a new chat: one banner, Open-WebUI's.
    """
    set_banners(banner("b1", "Only once"))
    admin.goto(url() + "/")
    admin.wait_for_function("window.__owuiBetterBanners === true", timeout=60_000)
    admin.get_by_text("Only once").first.wait_for(timeout=30_000)
    admin.wait_for_timeout(1500)
    assert admin.locator(ROOT).count() == 0
    assert admin.get_by_text("Only once").count() == 1


def test_a_new_banner_reaches_an_open_tab_without_a_reload(admin, admin_chat, set_banners):
    """By hand: with a chat open in one tab, add a banner in another: it appears in the
    first within a few seconds, with no reload.
    """
    set_banners()
    open_chat(admin, admin_chat)
    admin.wait_for_timeout(1000)
    assert admin.locator(ROOT).count() == 0
    set_banners(banner("b1", "Arrived live"))
    admin.locator(ROOT).get_by_text("Arrived live").wait_for(timeout=15_000)


def test_collapsing_them_into_the_pill_is_remembered_after_a_reload(admin, admin_chat, set_banners):
    """By hand: with two banners, click the pill: they fold into it, which shows 2.
    Reload: still folded. Click it again: both are back.
    """
    set_banners(banner("b1", "First"), banner("b2", "Second", type="warning"))
    open_chat(admin, admin_chat)
    root = admin.locator(ROOT)
    root.get_by_text("Second").wait_for(timeout=30_000)
    pill = root.locator(".obb-pill")
    assert pill.get_attribute("aria-expanded") == "true"
    assert pill.locator(".obb-count").inner_text() == "2"
    assert "obb-warning" in pill.get_attribute("class")  # the highest level of the two
    pill.click()
    root.locator(".obb-banner").first.wait_for(state="detached", timeout=5_000)
    assert pill.get_attribute("aria-expanded") == "false"

    open_chat(admin, admin_chat)
    pill = admin.locator(ROOT).locator(".obb-pill")
    pill.wait_for(timeout=30_000)
    admin.wait_for_timeout(500)
    assert pill.get_attribute("aria-expanded") == "false"
    assert admin.locator(f"{ROOT} .obb-banner").count() == 0
    pill.click()
    admin.locator(ROOT).get_by_text("First").wait_for(timeout=5_000)


def test_a_dismissed_banner_stays_gone_and_open_webui_knows_it(admin, admin_chat, set_banners):
    """Dismissals go in Open-WebUI's own `dismissedBannerIds`, so its banners agree.

    By hand: dismiss a dismissible banner, reload: it does not come back, here or on the
    new-chat screen. A banner that is not dismissible has no close button.
    """
    set_banners(banner("keep", "Stays"), banner("go", "Dismiss me", dismissible=True))
    open_chat(admin, admin_chat)
    root = admin.locator(ROOT)
    root.get_by_text("Dismiss me").wait_for(timeout=30_000)
    assert root.locator('.obb-banner[data-id="keep"] .obb-close').count() == 0
    root.locator('.obb-banner[data-id="go"]').get_by_role("button", name="Dismiss").click()
    root.get_by_text("Dismiss me").wait_for(state="detached", timeout=5_000)
    assert admin.evaluate("JSON.parse(localStorage.getItem('dismissedBannerIds'))") == ["go"]

    open_chat(admin, admin_chat)
    admin.locator(ROOT).get_by_text("Stays").wait_for(timeout=30_000)
    assert admin.locator(ROOT).get_by_text("Dismiss me").count() == 0


def test_at_the_bottom_they_sit_right_above_the_message_input(
    admin, admin_chat, set_banners, valves
):
    """By hand: set position to bottom, save, reload a chat: the banners are just above
    the message input.
    """
    valves(position="bottom")
    set_banners(banner("b1", "Down here"))
    open_chat(admin, admin_chat)
    root = admin.locator(ROOT)
    root.get_by_text("Down here").wait_for(timeout=30_000)
    assert root.get_attribute("data-position") == "bottom"
    assert root.evaluate("el => !!el.nextElementSibling.querySelector('#message-input-container')")


def test_markdown_renders_and_html_cannot_run_code(admin, admin_chat, set_banners):
    """Content is Markdown, or HTML when it has a tag; nothing in it can run.

    By hand: a banner `**Bold** and [docs](https://example.com)` shows Bold in bold and a
    link opening in a new tab. A banner with `<script>` and a `javascript:` link shows
    the text only.
    """
    set_banners(
        banner("md", "**Bold** and [docs](https://example.com)"),
        banner(
            "html",
            "<b>Strong</b><script>window.__bbRan = 1</script>"
            '<img src=x onerror="window.__bbRan = 2"><a href="javascript:window.__bbRan=3">bad</a>',
        ),
    )
    open_chat(admin, admin_chat)
    root = admin.locator(ROOT)
    root.get_by_text("Strong").wait_for(timeout=30_000)
    md = root.locator('.obb-banner[data-id="md"] .obb-content')
    assert md.locator("strong").inner_text() == "Bold"
    link = md.locator("a")
    assert link.get_attribute("href") == "https://example.com"
    assert link.get_attribute("target") == "_blank"
    html = root.locator('.obb-banner[data-id="html"] .obb-content')
    assert html.locator("b").inner_text() == "Strong"
    assert html.locator("script, img").count() == 0
    assert html.locator("a").get_attribute("href") is None
    html.get_by_text("bad").click()
    assert admin.evaluate("window.__bbRan") is None


def test_a_banner_shows_in_the_language_of_the_page(admin, admin_chat, set_banners):
    """By hand: a banner with a German translation; switch the interface to Deutsch: the
    banner changes to it without a reload.
    """
    set_banners(banner("b1", "Hello", i18n={"de": {"content": "Hallo"}}))
    open_chat(admin, admin_chat)
    root = admin.locator(ROOT)
    root.get_by_text("Hello").wait_for(timeout=30_000)
    admin.evaluate("document.documentElement.setAttribute('lang', 'de-DE')")
    root.get_by_text("Hallo").wait_for(timeout=5_000)


def test_disabled_its_banners_are_gone_after_a_reload(api, admin, admin_chat, set_banners):
    """By hand: disable Better Banners and reload a chat: no banners from it, and
    /static/loader.js has no owui-better-banners block. Enable it again after.
    """
    set_banners(banner("b1", "Soon gone"))
    status, body = api("POST", f"/api/v1/functions/id/{ID}/toggle")
    assert status == 200 and body["is_active"] is False, body
    try:
        with urllib.request.urlopen(url() + "/static/loader.js", timeout=30) as response:
            assert "owui-better-banners" not in response.read().decode()
        admin.goto(f"{url()}/c/{admin_chat}")
        admin.wait_for_timeout(3000)
        assert admin.locator(ROOT).count() == 0
        assert admin.evaluate("window.__owuiBetterBanners") is None
    finally:
        status, body = api("POST", f"/api/v1/functions/id/{ID}/toggle")
        assert body["is_active"] is True, body


def test_hostile_markup_in_any_field_cannot_run(admin, admin_chat, set_banners):
    """Every field a banner shows is input from an admin's form: event-handler attributes on
    allowed tags are dropped, and a title is text, never markup.

    By hand: a banner titled `<b onmouseover=alert(1)>T</b>` with content
    `<b onclick="alert(1)">Click</b>`: the title shows the tags as text, and hovering or
    clicking runs nothing.
    """
    set_banners(
        banner(
            "x",
            '<b onclick="window.__bbRan = 1" onmouseover="window.__bbRan = 2">Click me</b>',
            title='<img src=x onerror="window.__bbRan = 3">Title<b onclick="window.__bbRan = 4">!</b>',
        )
    )
    open_chat(admin, admin_chat)
    root = admin.locator(ROOT)
    content = root.locator('.obb-banner[data-id="x"] .obb-content')
    content.get_by_text("Click me").wait_for(timeout=30_000)
    assert content.locator("[onclick], [onmouseover]").count() == 0
    title = root.locator('.obb-banner[data-id="x"] .obb-title')
    assert title.locator("*").count() == 0
    assert title.inner_text().startswith("<img src=x")
    content.get_by_text("Click me").hover()
    content.get_by_text("Click me").click()
    title.click()
    assert admin.evaluate("window.__bbRan") is None
