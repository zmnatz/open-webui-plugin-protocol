"""Theme Designer Pro on a real Open-WebUI: the designer, a chat before and after a theme, a
user's own designer, the Admin Panel page, and a theme the Launcher built in a chat."""

from __future__ import annotations

import time

import pytest
from conftest import URL

ID = "theme_designer_pro"
BASE = "/api/v1/theme-designer"
MODEL = "theme-assistant"
ASK = "Make my chat a deep teal lagoon."

# A teal palette in Open-WebUI's own grey steps, as the designer writes them for dark mode.
STEPS = {50: 0.98, 100: 0.94, 200: 0.88, 300: 0.8, 400: 0.7, 500: 0.58, 600: 0.47, 700: 0.38,
         800: 0.3, 850: 0.26, 900: 0.22, 950: 0.17}
TEAL = ":root, .dark {\n" + "".join(
    f"  --color-gray-{step}: oklch({lightness} {0.02 + 0.03 * (1 - abs(lightness - 0.5))} 195);\n"
    for step, lightness in STEPS.items()
) + "}\n"
TEAL_STATE = '{"dark": {"h": 195, "c": 22, "l": 17, "themeShowAuth": false}}'


def save_theme(api, css: str | None) -> None:
    """The instance theme, as the designer's Live mode saves it (None: Global Reset)."""
    body = {"reset": True} if css is None else {"css": css, "state": TEAL_STATE}
    api("POST", BASE, body)


def switch(api, on: bool) -> None:
    """Admin Panel > Functions: the function's switch."""
    function = api("GET", f"/api/v1/functions/id/{ID}")
    if bool(function["is_active"]) != on:
        api("POST", f"/api/v1/functions/id/{ID}/toggle")


@pytest.fixture(scope="module")
def chat(api):
    """An existing chat to open, so the theme is seen around a conversation."""
    now = int(time.time())
    messages = {
        "u1": {"id": "u1", "role": "user", "content": "Plan a weekend in Lisbon.", "childrenIds": ["a1"]},
        "a1": {"id": "a1", "parentId": "u1", "role": "assistant", "childrenIds": [],
               "content": "Saturday: Alfama and the castle. Sunday: Belém, then sunset at a miradouro."},
    }
    created = api("POST", "/api/v1/chats/import", {"chats": [{
        "chat": {"title": "Weekend in Lisbon", "messages": list(messages.values()),
                 "history": {"currentId": "a1", "messages": messages}},
        "created_at": now, "updated_at": now,
    }]})
    yield created[0]["id"]
    save_theme(api, None)


def open_chat(page, chat_id: str, themed: bool) -> None:
    page.goto(f"{URL}/c/{chat_id}")
    page.get_by_text("Saturday: Alfama").wait_for(timeout=30_000)
    if themed:
        page.locator("#owui-dev-live-theme").wait_for(state="attached", timeout=30_000)
    page.wait_for_timeout(1500)


def test_a_chat_before_and_after_a_theme(admin, api, shot, chat):
    """By hand: with the function off, open a chat: Open-WebUI's own look. Turn it on, save a
    theme in the designer, and open the chat again: it wears the theme."""
    switch(api, False)
    try:
        open_chat(admin, chat, themed=False)
        shot(admin, "theme_designer_pro", "chat-before",
             "Before: the function off, a chat in Open-WebUI's own dark theme.")
    finally:
        switch(api, True)
    save_theme(api, TEAL)
    open_chat(admin, chat, themed=True)
    shot(
        admin,
        "theme_designer_pro",
        "chat-after",
        "After: the function on and a teal theme saved; every page, this chat included, wears it "
        "from its first paint.",
        illustrates=[
            "test_an_admin_saves_the_theme_and_every_page_gets_it",
            "test_the_first_paint_stylesheet_carries_the_theme_colours",
            "test_the_bootloader_is_on_every_page",
        ],
    )


def test_the_designer_opens_for_an_admin(admin, shot):
    """By hand: as an admin, open /api/v1/theme-designer. The designer opens on its Themes tab."""
    admin.goto(f"{URL}{BASE}")
    admin.locator("#theme-designer-container").wait_for(timeout=30_000)
    admin.wait_for_timeout(2000)
    shot(
        admin,
        "theme_designer_pro",
        "designer",
        "The designer, at its own URL: palette, custom CSS, Canvas FX, gradient, surfaces and "
        "backgrounds tabs. Its page is templates/designer/, put together from thirty files.",
        illustrates=[
            "test_an_admin_opens_the_designer_on_the_instance_theme",
            "test_the_page_is_its_files_put_together",
        ],
    )


def test_the_palette_tab(admin, shot):
    """By hand: in the designer, open the Palette tab: the OKLCH sliders and the colour ramp."""
    admin.goto(f"{URL}{BASE}")
    admin.locator("#tab-btn-lch").click()
    admin.locator("#tab-lch").wait_for(timeout=30_000)
    admin.wait_for_timeout(1000)
    shot(admin, "theme_designer_pro", "palette", "The Palette tab: hue, chroma and lightness, and the ramp they make.",
         illustrates=["test_each_valve_reaches_the_designer"])


def test_a_user_designs_their_own_theme(user, api, shot):
    """By hand: turn on Allow Personal Themes. As a user, open /api/v1/theme-designer?scope=me:
    the designer edits your own theme, which only you see."""
    before = api.valves(ID, allow_personal_themes=True)
    try:
        user.goto(f"{URL}{BASE}?scope=me")
        user.locator("html[data-tdp-scope=me] #theme-designer-container").wait_for(timeout=30_000)
        user.wait_for_timeout(2000)
        shot(
            user,
            "theme_designer_pro",
            "personal-designer",
            "With Allow Personal Themes on, a user's own designer: the instance-only controls are "
            "gone, and saves change only their theme.",
            illustrates=[
                "test_with_personal_themes_on_a_user_designs_their_own_theme",
                "test_a_personal_theme_reaches_only_its_owner",
            ],
        )
    finally:
        api("POST", f"/api/v1/functions/id/{ID}/valves/update", before)


def test_personal_themes_off_says_so(user, shot):
    """By hand: with Allow Personal Themes off, a user opens /api/v1/theme-designer?scope=me: a
    sentence says personal themes are off."""
    user.goto(f"{URL}{BASE}?scope=me")
    user.get_by_text("Personal themes are turned off on this instance.").wait_for(timeout=30_000)
    shot(user, "theme_designer_pro", "personal-off",
         "Personal themes off (the default): a user's designer link answers with a sentence.",
         illustrates=["test_with_personal_themes_off_a_user_gets_a_sentence_not_the_designer"])


def test_the_admin_panel_has_a_themes_page(admin, api, shot):
    """By hand: turn on Show In Admin Panel and open the Admin Panel: a Themes page sits between
    Functions and Settings, with the designer in it."""
    before = api.valves(ID, show_in_admin_panel=True)
    try:
        admin.goto(f"{URL}/admin/functions")
        admin.get_by_role("link", name="Themes").or_(admin.get_by_text("Themes", exact=True)).first.click()
        admin.frame_locator("iframe").first.locator("#theme-designer-container").wait_for(timeout=30_000)
        admin.wait_for_timeout(2000)
        shot(admin, "theme_designer_pro", "admin-panel-page",
             "Show In Admin Panel on: a Themes page in the Admin Panel's top bar.",
             illustrates=["test_the_themes_tab_and_page_follow_their_valves"])
    finally:
        api("POST", f"/api/v1/functions/id/{ID}/valves/update", before)


def test_signed_out_the_designer_sends_you_to_sign_in(signed_out, shot):
    """By hand: in a private window, open /api/v1/theme-designer: the sign-in page opens, and
    brings you back after."""
    signed_out.goto(f"{URL}{BASE}")
    signed_out.wait_for_url(f"{URL}/auth?redirect=%2Fapi%2Fv1%2Ftheme-designer")
    signed_out.locator("input[name=email]").wait_for()
    shot(signed_out, "theme_designer_pro", "sign-in-first",
         "Signed out, owpp's guard sends the designer's visitor to Open-WebUI's sign-in page.",
         illustrates=["test_someone_signed_out_is_sent_to_sign_in_first"])


@pytest.fixture(scope="module")
def theme_model(api):
    """A workspace model on aimock's screenshot-model, with the Launcher and native calling."""
    api("POST", "/api/v1/models/create", {
        "id": MODEL,
        "base_model_id": "screenshot-model",
        "name": "Theme assistant",
        "meta": {"toolIds": ["theme_designer_pro_launcher"], "description": "Designs themes"},
        "params": {"function_calling": "native"},
    })
    yield MODEL
    api("POST", "/api/v1/models/model/delete", {"id": MODEL})


def test_the_launcher_builds_a_theme_in_a_chat(user, api, shot, theme_model):
    """By hand: with Allow Personal Themes on, ask a model that has the Launcher "make my chat a
    deep teal lagoon". A card shows the theme with a live preview and Apply."""
    before = api.valves(ID, allow_personal_themes=True)
    try:
        user.goto(f"{URL}/?models={MODEL}")
        user.locator("#chat-input").click()
        user.keyboard.type(ASK)
        user.keyboard.press("Enter")
        user.get_by_text("Press Apply on the card").wait_for(timeout=60_000)
        user.frame_locator("iframe").last.get_by_text("Teal Lagoon").first.wait_for(timeout=30_000)
        user.wait_for_timeout(2500)  # the preview's animation frame
        shot(
            user,
            "theme_designer_pro",
            "launcher-card",
            "The model called the Launcher's create_theme; its card shows the theme, with Apply "
            "signed for this user only.",
            illustrates=[
                "test_a_described_theme_comes_back_as_a_card_that_applies_it",
                "test_the_launcher_carries_only_its_own_templates",
            ],
        )
    finally:
        api("POST", f"/api/v1/functions/id/{ID}/valves/update", before)
