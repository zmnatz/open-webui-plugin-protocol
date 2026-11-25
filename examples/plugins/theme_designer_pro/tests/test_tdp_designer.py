"""Theme Designer Pro's designer page: who opens it, which theme it edits, and what the valves
tell it. Run with `owpp test theme_designer_pro`."""

import json
import re

import pytest

BASE = "/api/v1/theme-designer"


def test_an_admin_opens_the_designer_on_the_instance_theme(td):
    """An admin opens the designer at its URL; it edits the theme every user sees, and is never
    cached.

    By hand: as an admin, open /api/v1/theme-designer. The designer opens on the Themes tab,
    with "Theme Designer Pro | v1.23.0" in its footer.
    """
    page = td.page(td.admin)
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "<title>Theme Designer Pro</title>" in page.text and "v1.23.0" in page.text
    assert td.config(td.admin)["scope"] == "instance"


def test_a_user_who_is_not_an_admin_cannot_open_the_instance_designer(td):
    """The instance designer is for admins: a user is refused.

    By hand: as a user who is not an admin, open /api/v1/theme-designer. The page answers
    {"detail": "Admins only."}.
    """
    assert td.page(td.user).status_code == 403


def test_someone_signed_out_is_sent_to_sign_in_first(owui, td):
    """Opening the designer without a session goes to Open-WebUI's sign-in page, which brings
    the person back to the designer; a fetch with no session gets a 401.

    By hand: in a private window, open /api/v1/theme-designer. The sign-in page opens; after
    signing in as an admin, the designer opens.
    """
    page = owui.client(follow_redirects=False).get(BASE, headers={"accept": "text/html"})
    assert page.status_code == 302
    assert page.headers["location"] == "/auth?redirect=%2Fapi%2Fv1%2Ftheme-designer"
    assert td.anon.get(BASE).status_code == 401


def test_with_personal_themes_off_a_user_gets_a_sentence_not_the_designer(td):
    """With `allow_personal_themes` off (it is on by default), the personal designer
    (?scope=me) answers a short page saying so in a frame, and JSON to a fetch.

    By hand: turn Allow Personal Themes off; as a user, open /api/v1/theme-designer?scope=me.
    The page says "Personal themes are turned off on this instance."
    """
    td.valves(allow_personal_themes=False)
    page = td.page(td.user, "?scope=me")
    assert page.status_code == 403
    assert "<p>Personal themes are turned off on this instance.</p>" in page.text
    assert td.user.get(BASE + "?scope=me").json() == {
        "error": "Personal themes are turned off on this instance"
    }


def test_with_personal_themes_on_a_user_designs_their_own_theme(td):
    """With `allow_personal_themes` on, ?scope=me opens the designer on the user's own theme:
    marked personal from its first line, saving to /me, with its own storage keys, and never in
    Draft mode.

    By hand: turn on Allow Personal Themes. As a user, open Settings: a Themes tab opens the
    designer, saying it edits your own theme.
    """
    td.valves(allow_personal_themes=True, draft_mode_default=True)
    page = td.page(td.user, "?scope=me")
    assert page.status_code == 200
    assert '<html lang="en" id="tool-html" data-tdp-scope="me">' in page.text
    assert f"fetch('{BASE}/me', " in page.text and "'owui_tdp_me_theme_v1" in page.text
    assert 'id="tdp-personal-style"' in page.text
    config = td.config(td.user, "?scope=me")
    assert config["scope"] == "me" and config["draftModeDefault"] is False
    assert config["personalHasTheme"] is False


def test_the_designer_starts_from_the_theme_the_server_serves(td):
    """The designer starts from the saved theme and gallery, not from a copy the browser kept
    that another browser's save may have overtaken.

    By hand: save a theme in one browser, then open the designer in another. It shows that
    theme.
    """
    td.save(library=json.dumps({"snapshots": [1]}))
    page = td.page(td.admin).text
    assert json.loads(td.script_value(page, "__THEME_PRO_SAVED_STATE__")) == td.STATE
    assert json.loads(td.script_value(page, "__THEME_PRO_LIBRARY__")) == {"snapshots": [1]}


def test_a_personal_designer_starts_from_the_instance_theme_without_its_gallery_marks(td):
    """A user with no theme of their own starts from the instance theme, less the marks naming
    entries of the admin's gallery, which would pick unrelated entries of theirs.

    By hand: with Allow Personal Themes on and an instance theme saved from a gallery entry, a
    user opens their Themes tab: it shows the instance theme, and no gallery entry is marked.
    """
    td.save(state=json.dumps({**td.STATE, "_activeThemeRef": 3}))
    td.valves(allow_personal_themes=True)
    state = json.loads(
        td.script_value(td.page(td.user, "?scope=me").text, "__THEME_PRO_SAVED_STATE__")
    )
    assert state == td.STATE


@pytest.mark.parametrize(
    ("valve", "value", "key", "expected"),
    [
        ("enable_canvas_fx", False, "enableCanvasFx", False),
        ("enable_canvas_api_access", True, "enableCanvasApiAccess", True),
        ("enable_url_import", False, "enableUrlImport", False),
        ("allowed_import_domains", " a.com, ,b.org ", "allowedImportDomains", ["a.com", "b.org"]),
        ("enable_custom_css", False, "enableCustomCss", False),
        ("enable_auth_page_theming", False, "enableAuthPageTheming", False),
        ("enable_gradient_builder", False, "enableGradientBuilder", False),
        ("enable_community_themes", False, "enableCommunityThemes", False),
        ("enable_theme_update_checks", False, "enableThemeUpdateChecks", False),
        ("draft_mode_default", True, "draftModeDefault", True),
        ("auto_sync", False, "autoSync", False),
        ("allow_personal_themes", False, "allowPersonalThemes", False),
        ("enable_ai_consultant", False, "enableAiConsultant", False),
    ],
)
def test_each_valve_reaches_the_designer(td, valve, value, key, expected):
    """Each valve that shapes the designer reaches its page, which shows or hides its part:
    Enable Canvas FX the Canvas FX tab, Enable Custom CSS the Style Overrides tab, Enable
    Gradient Builder the Gradient tab, Enable Url Import the Load from URL controls, Enable
    Community Themes the community grid, Enable Theme Update Checks the Updates button, Enable
    Auth Page Theming the sign-in toggles, Auto Sync the Sync All switch, Draft Mode Default the
    mode it opens in, and Enable Ai Consultant the AI Consultant.

    By hand: change the valve (Admin Panel > Functions > Theme Designer Pro > Valves), reload the
    designer: the part it names is shown or hidden, as its description says.
    """
    assert td.config(td.admin)[key] != expected
    td.valves(**{valve: value})
    assert td.config(td.admin)[key] == expected


def test_the_designer_carries_the_bootloader_set_for_its_previews(td):
    """The designer embeds the bootloader its previews run, on and with the designer's own URL,
    and with no theme of its own (the designer applies the one it edits).

    By hand: not repeatable as such; in the designer, the live preview shows the theme being
    edited, with Canvas FX running when Enable Canvas FX is on.
    """
    td.valves(enable_canvas_fx=False, calm_chat_column=True, enable_canvas_api_access=True)
    page = td.page(td.admin).text
    src = re.search(
        r'<script type="text/plain" id="bootloader-src">(.*?)</script>', page, re.S
    ).group(1)
    assert "var _themeActive = true;" in src and "var _personalEnabled = false;" in src
    assert "var embeddedState = null;" in src and "var _cachedCanvasOk = false;" in src
    assert "const _script = true ?" in src and "authToken: true &&" in src
    assert f"readAsset('{BASE}/theme.css')" in src


def test_oled_is_kept_under_its_own_key_so_open_webui_leaves_it_alone(td):
    """Open-WebUI 0.13.5 turns a stored 'oled-dark' theme into 'dark' and a black colour of its
    own on the next page load. So the designer stores OLED as Open-WebUI's 'dark' plus a key of
    its own, and the bootloader on every page reads the two as OLED again.

    By hand: on Open-WebUI 0.13.5, pick OLED in the designer and give it a hue, then open a chat
    and reload it: it still wears the OLED palette, Settings > General > Colors has no colour
    of Open-WebUI's own set, and the designer opens on OLED again.
    """
    td.save()
    page = td.page(td.admin).text
    loader = td.anon.get("/static/loader.js").text
    for script in (page, loader):
        assert "OLED_KEY = 'owui_tdp_oled'" in script
    assert "localStorage.setItem('theme', mode === 'oled' ? 'dark'" in page
    assert "if (theme === 'dark') return 'oled-dark';" in loader


def test_the_page_is_its_files_put_together(td, plugin_dir):
    """The designer is templates/designer/page.html with each file it includes put in its
    place, every one of them once, and nothing left to include.

    By hand: not repeatable in Open-WebUI; compare the page the designer serves with
    templates/designer/ (view the frame's source).
    """
    page = td.plugin.module.DESIGNER_PAGE
    assert "<!--#include" not in page
    outline = (plugin_dir / "templates/designer/page.html").read_text()
    included = re.findall(r"<!--#include ([\w./-]+)-->", outline)
    files = sorted(
        str(p.relative_to(plugin_dir / "templates/designer"))
        for p in (plugin_dir / "templates/designer").rglob("*")
        if p.is_file() and p.name not in ("page.html", "personal.html")
    )
    assert sorted(included) == files
    for name in included:
        assert (plugin_dir / "templates/designer" / name).read_text().removesuffix("\n") in page
