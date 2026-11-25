"""Theme Designer Pro's instance theme: saving it, serving it to every page (and to the sign-in
page), and the first-paint fragments of /static/custom.css and /static/loader.js. Run with
`owpp test theme_designer_pro`."""

import json

import pytest

BASE = "/api/v1/theme-designer"


def test_nothing_saved_yet_is_an_empty_theme(td):
    """Before any save, the theme is empty, which the bootloader reads as "no theme": pages
    look like Open-WebUI's own.

    By hand: on a fresh instance, enable the function and open a chat: nothing changes.
    """
    css, state = td.anon.get(BASE + "/theme.css"), td.anon.get(BASE + "/state.json")
    assert (css.status_code, css.text, css.headers["cache-control"]) == (200, "", "no-store")
    assert (state.status_code, state.text) == (200, "{}")
    assert "owui-theme-designer-pro" not in td.anon.get("/static/custom.css").text


def test_an_admin_saves_the_theme_and_every_page_gets_it(td):
    """A save by an admin is served to every page, signed in or not (the sign-in page is themed
    too): its CSS, and its state with the CSS sections the sign-in page assembles.

    By hand: as an admin, pick a theme in the designer (in Live mode). Open a chat in another
    browser, and the sign-in page in a private window: both show it.
    """
    saved = td.save(origin="tab1")
    assert saved.status_code == 200
    assert saved.json()["status"] == "ok" and saved.json()["cssTag"]
    css = td.anon.get(BASE + "/theme.css")
    assert css.text == td.CSS and css.headers["etag"] == saved.json()["cssTag"]
    state = td.anon.get(BASE + "/state.json").json()
    assert state["dark"] == td.STATE["dark"]
    assert state["_cssSections"]["vars"] == td.SECTIONS["vars"]


def test_an_unchanged_theme_is_not_sent_again(td):
    """A page that already has the theme gets a 304 for it, a gzipping proxy's weakened tag
    included.

    By hand: reload a chat with DevTools > Network open: theme.css and state.json answer 304.
    """
    td.save()
    etag = td.anon.get(BASE + "/theme.css").headers["etag"]
    assert td.anon.get(BASE + "/theme.css", headers={"if-none-match": etag}).status_code == 304
    assert (
        td.anon.get(BASE + "/theme.css", headers={"if-none-match": "W/" + etag}).status_code == 304
    )


def test_saving_the_same_theme_again_writes_nothing(td):
    """The same theme again (a designer sends it as it opens) is not written, and tells no open
    page to reload.

    By hand: open the designer in two tabs and reload one: the other does not reload.
    """
    td.save()
    page = td.stream()
    again = td.save()
    assert again.json()["noop"] is True
    assert td.heard(page) == []


def test_a_user_cannot_save_the_instance_theme(td):
    """Only an admin changes what everyone sees.

    By hand: as a user, POST to /api/v1/theme-designer (from DevTools): 403.
    """
    assert td.save(td.user).status_code == 403
    assert td.save(td.anon).status_code == 401
    assert td.anon.get(BASE + "/theme.css").text == ""


@pytest.mark.parametrize(
    "headers",
    [
        {"sec-fetch-site": "cross-site"},
        {"sec-fetch-site": "same-site"},
        {"origin": "https://evil.example"},
        {"origin": "null"},
    ],
)
def test_a_change_sent_from_another_site_is_refused(td, headers):
    """A page on another site can send the session cookie along; a change it sends is refused,
    told by the browser's Sec-Fetch-Site, or the Origin where there is none.

    By hand: not repeatable without a second site; from another origin's DevTools, a fetch
    with credentials to /api/v1/theme-designer answers 403.
    """
    response = td.admin.post(BASE, json={"css": td.CSS}, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"error": "Changes must come from Open WebUI's own pages"}


def test_a_change_from_open_webuis_own_pages_goes_through(td, owui):
    """The same page's Sec-Fetch-Site, or an Origin with this site's host or WEBUI_URL's, is
    Open-WebUI's own page.

    By hand: save in the designer: it saves.
    """
    for headers in ({"sec-fetch-site": "same-origin"}, {"origin": "http://testserver"}):
        assert td.admin.post(BASE, json={"css": td.CSS + "\n"}, headers=headers).status_code == 200
    owui.config["webui.url"] = "https://chat.example"
    assert (
        td.admin.post(
            BASE, json={"css": td.CSS}, headers={"origin": "https://chat.example"}
        ).status_code
        == 200
    )


def test_a_save_must_be_json(td):
    """A save is JSON: anything else would be a form another site can send without asking.

    By hand: not repeatable from the designer, which always sends JSON.
    """
    response = td.admin.post(BASE, content=b"{}", headers={"content-type": "text/plain"})
    assert response.status_code == 415


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"css": "x" * (5 * 1024 * 1024 + 1)}, "css exceeds 5MB limit"),
        ({"state": "x" * (5 * 1024 * 1024 + 1)}, "state exceeds 5MB limit"),
        ({"sections": {"vars": "x" * (5 * 1024 * 1024 + 1)}}, "sections exceeds 5MB limit"),
    ],
)
def test_an_oversized_theme_is_refused(td, body, error):
    """A theme over its limits (5 MB of CSS, of state or of sections; 20 MB of gallery; 64 MB
    in all) is refused before it is written.

    By hand: not repeatable from the designer, which keeps themes far smaller.
    """
    response = td.admin.post(BASE, json=body)
    assert (response.status_code, response.json()) == (413, {"error": error})


def test_a_body_bigger_than_the_whole_limit_is_refused_unread(td):
    """A body that says it is over 64 MB is refused before it is read.

    By hand: not repeatable from the designer.
    """
    response = td.admin.post(
        BASE,
        content=b"{}",
        headers={"content-type": "application/json", "content-length": str(65 * 1024 * 1024)},
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ([1, 2], "Expected a JSON object"),
        ({"css": 5}, "css must be a string"),
        ({"css": "a", "state": "[]"}, "state must be a JSON object"),
        ({"css": "a", "library": "nope"}, "library must be a JSON object"),
    ],
)
def test_a_save_that_is_not_a_theme_is_refused(td, body, error):
    """What would load as an empty designer or an empty gallery is refused, so its next save
    cannot write that over the theme.

    By hand: not repeatable from the designer.
    """
    response = td.admin.post(BASE, json=body)
    assert (response.status_code, response.json()) == (400, {"error": error})


def test_a_gallery_alone_is_saved_and_tells_open_designers(td):
    """Saving only the gallery (themes and presets, as Draft mode does) keeps the theme, and
    open designers hear of it; the same gallery again is not written.

    By hand: in Draft mode, save a preset; another open designer shows it after it reloads.
    """
    td.save()
    page = td.stream()
    library = json.dumps({"presets": ["a"]})
    response = td.admin.post(BASE, json={"css": "", "library": library})
    assert response.json()["library_only"] is True
    assert td.admin.get(BASE + "/library.json").json() == {"presets": ["a"]}
    assert td.anon.get(BASE + "/theme.css").text == td.CSS
    assert [name for name, _ in td.heard(page)] == ["library-update"]
    assert td.admin.post(BASE, json={"css": "", "library": library}).json()["noop"] is True
    assert td.admin.post(BASE, json={"css": ""}).json() == {"status": "ok", "noop": True}


def test_the_gallery_is_for_admins(td):
    """The instance gallery is the admins'.

    By hand: as a user, open /api/v1/theme-designer/library.json: 403.
    """
    assert td.user.get(BASE + "/library.json").status_code == 403
    assert td.admin.get(BASE + "/library.json").json() == {}


def test_a_global_reset_removes_the_instance_theme_from_every_page(td):
    """Global Reset deletes the theme, its sections and its gallery; open pages drop it, and
    /static/custom.css no longer carries it.

    By hand: in the designer, Docs > Danger Zone > Global Reset. Open chats go back to
    Open-WebUI's own look without a reload.
    """
    td.save(library=json.dumps({"presets": []}))
    page = td.stream()
    assert td.admin.post(BASE, json={"reset": True}).json() == {"status": "reset"}
    assert td.anon.get(BASE + "/theme.css").text == ""
    assert td.admin.get(BASE + "/library.json").json() == {}
    assert "owui-theme-designer-pro" not in td.anon.get("/static/custom.css").text
    assert td.heard(page)[0][0] == "theme-disable" and td.heard(page) == []


def test_canvas_fx_off_takes_the_scripts_out_of_what_is_served(td):
    """With `enable_canvas_fx` off no page runs an animation: the served state has none, and
    the saved theme keeps it for when it is turned back on.

    By hand: with an animated theme saved, turn Enable Canvas FX off. Chats show the theme
    without its animation; turn it back on and the animation is back.
    """
    td.save()
    td.valves(enable_canvas_fx=False)
    served = td.anon.get(BASE + "/state.json").json()["dark"]
    assert served["canvasEnabled"] is False and "canvasScript" not in served
    td.valves(enable_canvas_fx=True)
    assert td.anon.get(BASE + "/state.json").json()["dark"]["canvasScript"] == "draw()"


def test_sign_in_page_theming_off_keeps_the_sign_in_page_plain(td):
    """With `enable_auth_page_theming` off, every Show on Auth Pages flag is served off.

    By hand: with a theme shown on the sign-in page, turn Enable Auth Page Theming off. The
    sign-in page (private window) is plain again.
    """
    td.save()
    td.valves(enable_auth_page_theming=False)
    assert td.anon.get(BASE + "/state.json").json()["dark"]["themeShowAuth"] is False


def test_the_first_paint_stylesheet_carries_the_theme_colours(td):
    """/static/custom.css, which blocks the first paint, carries the theme's colours and custom
    CSS inside a switch the bootloader turns off where the theme does not belong, and leaves
    the transparency rules to the bootloader.

    By hand: reload a themed chat: it paints in the theme's colours with no flash of
    Open-WebUI's own.
    """
    td.save()
    css = td.anon.get("/static/custom.css").text
    assert "/* owui-theme-designer-pro:start */\n@supports (--tdp-instance: 1) {" in css
    assert td.SECTIONS["vars"] in css and ".chat { color: red; }" in css
    assert "/* structural rules deferred to bootloader */" in css and "#sidebar" not in css


def test_custom_css_with_unbalanced_braces_waits_for_the_bootloader(td):
    """Custom CSS whose braces don't balance would break out of its switch in a stylesheet
    shared with other plugins, so it is left to the bootloader.

    By hand: not repeatable from the designer, which balances what it writes.
    """
    sections = {**td.SECTIONS, "custom": ".chat { color: red;\n"}
    td.save(sections=sections, css=td.CSS.replace("red; }", "red;"))
    css = td.anon.get("/static/custom.css").text
    assert "/* custom CSS deferred to bootloader */" in css and "color: red" not in css


def test_the_bootloader_is_on_every_page(td):
    """/static/loader.js carries the bootloader, set to this designer URL, with the theme's
    state inlined for the first paint, minus the animations' code.

    By hand: open a chat and DevTools > Sources > /static/loader.js: it holds the
    "owui-theme-designer-pro" block.
    """
    td.save()
    js = td.anon.get("/static/loader.js").text
    assert "// owui-theme-designer-pro:start" in js and "var _themeActive = true;" in js
    assert f"readAsset('{BASE}/theme.css')" in js
    embedded = json.loads(json.loads(js.split("var embeddedState = ", 1)[1].split(";\n", 1)[0]))
    assert embedded["dark"] == {"canvasEnabled": True, "themeShowAuth": True}


def test_a_saved_theme_holding_placeholder_text_is_served_as_it_is(td):
    """The theme is inlined after every placeholder is filled in, so a theme that happens to
    hold one's text (say, in an animation's comment) is served as written.

    By hand: not repeatable by hand.
    """
    td.save(state=json.dumps({"dark": {"name": "__THEME_ROUTE__ and __CANVAS_FX__"}}))
    js = td.anon.get("/static/loader.js").text
    embedded = json.loads(json.loads(js.split("var embeddedState = ", 1)[1].split(";\n", 1)[0]))
    assert embedded["dark"]["name"] == "__THEME_ROUTE__ and __CANVAS_FX__"


@pytest.mark.parametrize(
    ("valves", "tab", "page"),
    [
        ({}, True, False),
        ({"show_in_admin_settings": False, "allow_personal_themes": False}, False, False),
        ({"show_in_admin_settings": False, "allow_personal_themes": True}, True, False),
        ({"show_in_admin_panel": True}, True, True),
    ],
)
def test_the_themes_tab_and_page_follow_their_valves(td, valves, tab, page):
    """`show_in_admin_settings` (on by default) adds a Themes tab to the Admin part of
    Settings, `allow_personal_themes` (on by default too) one to every user's Settings, and
    `show_in_admin_panel` a Themes page to the Admin Panel's top bar.

    By hand: open Settings: an admin sees Admin > Themes. Turn Show In Admin Panel on: the
    Admin Panel has a Themes page between Functions and Settings.
    """
    td.valves(**valves)
    js = td.anon.get("/static/loader.js").text
    assert ("window.__owuiTdpSettingsTab" in js) is tab
    assert ("window.__owuiTdpAdminPage" in js) is page
    if tab:
        personal = valves.get("allow_personal_themes", True)
        admin = valves.get("show_in_admin_settings", True)
        assert f"if ({str(personal).lower()}) SPECS.push({{ key: 'personal'" in js
        assert f"if ({str(admin).lower()}) SPECS.push({{ key: 'admin'" in js


@pytest.mark.parametrize(
    ("valve", "on", "off"),
    [
        ("calm_chat_column", "const _script = true ?", "const _script = false ?"),
        ("enable_canvas_api_access", "authToken: true &&", "authToken: false &&"),
        ("enable_canvas_fx", "var _cachedCanvasOk = true;", "var _cachedCanvasOk = false;"),
        ("allow_personal_themes", "var _personalEnabled = true;", "var _personalEnabled = false;"),
    ],
)
def test_the_bootloader_follows_its_valves(td, valve, on, off):
    """The bootloader on every page follows `calm_chat_column` (animations fade behind the
    chat), `enable_canvas_api_access` (animations get the viewer's token: leave it off),
    `enable_canvas_fx` and `allow_personal_themes`.

    By hand: turn Calm Chat Column on and reload a chat with an animated theme: the animation
    fades behind the messages.
    """
    default = getattr(td.plugin.instance.Valves(), valve)
    js = td.anon.get("/static/loader.js").text
    assert (on if default else off) in js
    td.valves(**{valve: not default})
    js = td.anon.get("/static/loader.js").text
    assert (off if default else on) in js
