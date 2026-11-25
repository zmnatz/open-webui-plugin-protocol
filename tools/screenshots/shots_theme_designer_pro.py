"""Theme Designer Pro on a real Open-WebUI: an admin makes a theme in the designer and a chat
wears it, a user's own designer, the Admin Panel page, and a theme the Launcher built in a chat.

The admin and the user sign in once for the whole module: Open-WebUI limits how often one
account may sign in, and these steps need many pages."""

from __future__ import annotations

import time

import pytest
from conftest import URL, send, sign_in

ID = "theme_designer_pro"
BASE = "/api/v1/theme-designer"
MODEL = "theme-assistant"
ASK = "Make my chat a deep teal lagoon."


@pytest.fixture(scope="module")
def admin_page(browser, admin_account):
    page = sign_in(browser, admin_account)
    yield page
    page.context.close()


@pytest.fixture(scope="module")
def user_page(browser, user_account):
    page = sign_in(browser, user_account)
    yield page
    page.context.close()


def switch(api, on: bool) -> None:
    """Admin Panel > Functions: the function's switch."""
    function = api("GET", f"/api/v1/functions/id/{ID}")
    if bool(function["is_active"]) != on:
        api("POST", f"/api/v1/functions/id/{ID}/toggle")


def restore(api, valves: dict) -> None:
    api("POST", f"/api/v1/functions/id/{ID}/valves/update", valves)


@pytest.fixture(scope="module")
def chat(api):
    """An existing chat to open, with no theme saved yet; the theme is reset afterwards."""
    api("POST", BASE, {"reset": True})
    now = int(time.time())
    messages = {
        "u1": {
            "id": "u1",
            "role": "user",
            "content": "Plan a weekend in Lisbon.",
            "childrenIds": ["a1"],
        },
        "a1": {
            "id": "a1",
            "parentId": "u1",
            "role": "assistant",
            "childrenIds": [],
            "content": "Saturday: Alfama and the castle. Sunday: Belém, then sunset at a miradouro.",
        },
    }
    created = api(
        "POST",
        "/api/v1/chats/import",
        {
            "chats": [
                {
                    "chat": {
                        "title": "Weekend in Lisbon",
                        "messages": list(messages.values()),
                        "history": {"currentId": "a1", "messages": messages},
                    },
                    "created_at": now,
                    "updated_at": now,
                }
            ]
        },
    )
    yield created[0]["id"]
    api("POST", BASE, {"reset": True})


def design(page, mode: str, hue: int, chroma: int) -> None:
    """In the designer: pick a mode, and on the Core Palette tab move Hue and Chroma. It saves
    at once (Live mode)."""
    page.goto(f"{URL}{BASE}")
    page.locator("#theme-designer-container").wait_for(timeout=30_000)
    page.locator(f'button[data-mode="{mode}"]').first.click()
    page.locator("#tab-btn-lch").click()
    page.locator("#sl-h").wait_for(timeout=30_000)
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith(BASE) and r.ok, timeout=30_000
    ):
        page.evaluate(
            """([hue, chroma]) => {
                for (const [id, value] of [['sl-h', hue], ['sl-c', chroma]]) {
                    const el = document.getElementById(id);
                    el.value = value;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }""",
            [hue, chroma],
        )
    page.wait_for_timeout(1500)


def open_chat(page, chat_id: str, themed: bool) -> None:
    """The chat in Open-WebUI's dark mode, where a palette shows best."""
    page.goto(f"{URL}/c/{chat_id}")
    page.evaluate("localStorage.setItem('theme', 'dark')")
    page.reload()
    page.get_by_text("Saturday: Alfama").wait_for(timeout=30_000)
    if themed:
        page.locator("#owui-dev-live-theme").wait_for(state="attached", timeout=30_000)
    page.wait_for_timeout(1500)


def test_signed_out_the_designer_sends_you_to_sign_in(signed_out, shot):
    """By hand: in a private window, open /api/v1/theme-designer: the sign-in page opens, and
    brings you back after."""
    signed_out.goto(f"{URL}{BASE}")
    signed_out.wait_for_url(f"{URL}/auth?redirect=%2Fapi%2Fv1%2Ftheme-designer")
    signed_out.locator("input[name=email]").wait_for()
    shot(
        signed_out,
        "theme_designer_pro",
        "sign-in-first",
        "Signed out, owpp's guard sends the designer's visitor to Open-WebUI's sign-in page.",
        illustrates=["test_someone_signed_out_is_sent_to_sign_in_first"],
    )


def test_an_admin_makes_a_theme_and_a_chat_wears_it(admin_page, api, shot, chat):
    """By hand: with the function off, open a chat in dark mode: Open-WebUI's own look. Turn it
    on, open the designer, pick Dark, and on the Core Palette tab move Hue to 185 and Chroma to
    60: it saves at once (Live mode). Open the chat again: it wears the theme."""
    page = admin_page
    switch(api, False)
    try:
        open_chat(page, chat, themed=False)
        shot(
            page,
            "theme_designer_pro",
            "chat-before",
            "Before: the function off, a chat in Open-WebUI's own dark theme.",
        )
    finally:
        switch(api, True)

    design(page, "dark", hue=185, chroma=60)
    shot(
        page,
        "theme_designer_pro",
        "designer",
        "The designer's Core Palette tab, after moving Hue and Chroma: the ramp of Open-WebUI's "
        "greys it makes, saved for everyone at once in Live mode. The page is templates/designer/, "
        "put together from thirty files.",
        illustrates=[
            "test_an_admin_opens_the_designer_on_the_instance_theme",
            "test_the_page_is_its_files_put_together",
            "test_each_valve_reaches_the_designer",
        ],
    )

    open_chat(page, chat, themed=True)
    shot(
        page,
        "theme_designer_pro",
        "chat-after",
        "After: the function on and that palette saved; every page, this chat included, wears it "
        "from its first paint.",
        illustrates=[
            "test_an_admin_saves_the_theme_and_every_page_gets_it",
            "test_the_first_paint_stylesheet_carries_the_theme_colours",
            "test_the_bootloader_is_on_every_page",
        ],
    )


def test_personal_themes_off_says_so(user_page, api, shot):
    """By hand: turn Allow Personal Themes off, then as a user open
    /api/v1/theme-designer?scope=me: a sentence says personal themes are off."""
    before = api.valves(ID, allow_personal_themes=False)
    try:
        user_page.goto(f"{URL}{BASE}?scope=me")
        user_page.get_by_text("Personal themes are turned off on this instance.").wait_for(
            timeout=30_000
        )
        shot(
            user_page,
            "theme_designer_pro",
            "personal-off",
            "Personal themes off: a user's designer link answers with a sentence.",
            illustrates=["test_with_personal_themes_off_a_user_gets_a_sentence_not_the_designer"],
        )
    finally:
        restore(api, before)


def test_a_user_designs_their_own_theme(user_page, api, shot, chat):
    """By hand: turn on Allow Personal Themes. As a user, open /api/v1/theme-designer?scope=me:
    the designer edits your own theme, which only you see."""
    before = api.valves(ID, allow_personal_themes=True)
    try:
        user_page.goto(f"{URL}{BASE}?scope=me")
        user_page.locator("html[data-tdp-scope=me] #theme-designer-container").wait_for(
            timeout=30_000
        )
        user_page.wait_for_timeout(2000)
        shot(
            user_page,
            "theme_designer_pro",
            "personal-designer",
            "With Allow Personal Themes on, a user's own designer, starting from the instance theme: "
            "the instance-only controls are gone, and saves change only their theme.",
            illustrates=[
                "test_with_personal_themes_on_a_user_designs_their_own_theme",
                "test_a_personal_theme_reaches_only_its_owner",
            ],
        )
    finally:
        restore(api, before)


def test_the_admin_panel_has_a_themes_page(admin_page, api, shot, chat):
    """By hand: turn on Show In Admin Panel and open the Admin Panel: a Themes page sits between
    Functions and Settings, with the designer in it."""
    before = api.valves(ID, show_in_admin_panel=True)
    try:
        admin_page.goto(f"{URL}/admin/functions")
        admin_page.get_by_role("link", name="Themes", exact=True).click(timeout=30_000)
        admin_page.frame_locator(".tdp-admin-page iframe").locator(
            "#theme-designer-container"
        ).wait_for(timeout=30_000)
        admin_page.wait_for_timeout(2000)
        shot(
            admin_page,
            "theme_designer_pro",
            "admin-panel-page",
            "Show In Admin Panel on: a Themes page in the Admin Panel's top bar, with the designer in it.",
            illustrates=["test_the_themes_tab_and_page_follow_their_valves"],
        )
    finally:
        restore(api, before)


@pytest.fixture(scope="module")
def theme_model(api):
    """A workspace model on aimock's screenshot-model, with the Launcher and native calling."""
    api(
        "POST",
        "/api/v1/models/create",
        {
            "id": MODEL,
            "base_model_id": "screenshot-model",
            "name": "Theme assistant",
            "meta": {"toolIds": ["theme_designer_pro_launcher"], "description": "Designs themes"},
            "params": {"function_calling": "native"},
        },
    )
    yield MODEL
    api("POST", "/api/v1/models/model/delete", {"id": MODEL})


def test_the_launcher_builds_a_theme_in_a_chat(admin_page, api, shot, theme_model):
    """By hand: ask a model that has the Launcher "make my chat a deep teal lagoon". A card
    shows the theme with a live preview and Apply."""
    page = admin_page
    page.goto(f"{URL}/?models={MODEL}")
    send(page, ASK)
    page.get_by_text("Press Apply on the card").wait_for(timeout=60_000)
    page.frame_locator("iframe").last.get_by_text("Teal Lagoon").first.wait_for(timeout=30_000)
    page.wait_for_timeout(2500)  # the preview's first frames
    shot(
        page,
        "theme_designer_pro",
        "launcher-card",
        "The model called the Launcher's create_theme; its card shows the theme with a live "
        "preview, and Apply signed for this user only.",
        illustrates=[
            "test_a_described_theme_comes_back_as_a_card_that_applies_it",
            "test_the_launcher_carries_only_its_own_templates",
        ],
    )


# What the page says about its mode and greys: Open-WebUI's stored theme, the designer's OLED
# key, Open-WebUI 0.13.5's own colours, and the grey the chat's background is drawn from.
MODE = """() => ({
    theme: localStorage.getItem('theme'),
    oled: localStorage.getItem('owui_tdp_oled'),
    ownColours: localStorage.getItem('themeColors'),
    dataTheme: document.documentElement.getAttribute('data-theme'),
    grey: getComputedStyle(document.documentElement).getPropertyValue('--color-base-950').trim(),
})"""


def test_oled_holds_on_open_webui_0_13_5(admin_page, shot, chat):
    """By hand (Open-WebUI 0.13.5): pick OLED in the designer and give it a hue, then open a chat
    and reload it: it still wears the OLED palette, Settings > General > Colors has nothing set,
    and the designer opens on OLED again."""
    page = admin_page
    try:
        design(page, "oled", hue=300, chroma=60)
        page.goto(f"{URL}/c/{chat}")
        page.get_by_text("Saturday: Alfama").wait_for(timeout=30_000)
        page.reload()
        page.get_by_text("Saturday: Alfama").wait_for(timeout=30_000)
        page.wait_for_timeout(1500)
        state = page.evaluate(MODE)
        assert (state["theme"], state["oled"], state["dataTheme"]) == ("dark", "1", "oled-dark")
        assert state["ownColours"] is None and state["grey"].endswith(" 300)"), state
        shot(
            page,
            "theme_designer_pro",
            "oled",
            "OLED picked in the designer, after a reload: still OLED's palette. Open-WebUI 0.13.5 "
            "has no OLED theme of its own; the designer keeps OLED under a key of its own.",
            illustrates=["test_oled_is_kept_under_its_own_key_so_open_webui_leaves_it_alone"],
        )
        page.goto(f"{URL}{BASE}")
        page.locator('.mode-btn.active[data-mode="oled"]').wait_for(timeout=30_000)
    finally:
        page.evaluate(
            "localStorage.removeItem('owui_tdp_oled'); localStorage.setItem('theme', 'dark')"
        )
