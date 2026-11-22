"""Theme Designer Pro's live updates (the stream every page keeps open) and its lifecycle: startup,
valve changes, disabling, a new Designer Url, shutdown. Run with `owpp test theme_designer_pro`.

The mock cannot hold an endless response open, so these tests open a page's stream the way the
stream route registers it (`td.stream()`) and read what is sent to it."""

import json

BASE = "/api/v1/theme-designer"


def test_a_save_reaches_every_open_page(td):
    """A save tells every open page, with the new theme's tags (a page that has them already
    skips the refetch) and the tab that saved (which does not reload itself).

    By hand: open a chat in a second browser, then save a theme in the designer: the chat
    changes without a reload.
    """
    page = td.stream()
    saved = td.save(origin="tab1").json()
    ((name, data),) = td.heard(page)
    assert name == "theme-update"
    assert (data["cssTag"], data["stateTag"], data["origin"]) == (saved["cssTag"], saved["stateTag"], "tab1")


def test_a_personal_save_reaches_only_its_owners_pages(owui, td):
    """A personal save is told to its owner's pages only.

    By hand: a user changes their theme in Settings > Themes; their other open tab follows, an
    admin's tab does not.
    """
    td.valves(allow_personal_themes=True)
    mine, theirs, signed_out = td.stream(td.ada), td.stream(owui.admin), td.stream()
    td.save(td.user, "/me")
    assert [n for n, _ in td.heard(mine)] == ["personal-theme-update"]
    assert td.heard(theirs) == [] and td.heard(signed_out) == []


def test_a_page_claims_its_stream_to_hear_its_own_theme(td):
    """The stream sends only cookies, which a signed-in page may lack; the page claims its
    stream by the id the stream announced, with its own token. A malformed id, or no session,
    is refused.

    By hand: not repeatable by hand; with Allow Personal Themes on, a user's two tabs follow
    each other's saves even after a browser restart.
    """
    td.valves(allow_personal_themes=True)
    page = td.stream()
    page._tdp_cid = "a" * 24
    td.event._sse_cids[page._tdp_cid] = page
    answer = td.user.post(BASE + "/events/bind", json={"cid": page._tdp_cid})
    assert answer.json() == {"status": "ok", "cssTag": None, "stateTag": None}
    assert page._tdp_user == td.ada.id
    assert td.user.post(BASE + "/events/bind", json={"cid": "short"}).status_code == 400
    assert td.anon.post(BASE + "/events/bind", json={"cid": "a" * 24}).status_code == 401


def test_a_worker_past_its_stream_limit_tells_pages_to_come_back_later(owui, plugin_dir, monkeypatch):
    """Each worker holds at most `sse_max_clients` streams (config.yaml, 8192 by default, or
    TDP_SSE_MAX_CLIENTS); past it a page is told to retry in a minute.

    By hand: set TDP_SSE_MAX_CLIENTS=0 on the Open-WebUI container and restart it: a chat's
    /events request (DevTools > Network) answers "retry: 60000" and ends.
    """
    monkeypatch.setenv("TDP_SSE_MAX_CLIENTS", "0")
    monkeypatch.setenv("TDP_SSE_HEARTBEAT_SECONDS", "5")
    plugin = owui.load(plugin_dir)
    owui.startup()
    assert plugin.module.Event._SSE_HEARTBEAT_SECONDS == 5
    body = owui.client().get(BASE + "/events").text
    assert body.startswith("retry: 60000\n\nevent: hello\n")


def test_the_limits_default_to_the_originals(td):
    """Without the variables, config.yaml's limits are the original's: 8192 streams per worker,
    a keep-alive every 15 seconds, and 3 seconds between one user's AI Consultant requests.

    By hand: `owpp check theme_designer_pro` lists the three variables with these defaults.
    """
    assert (td.event._SSE_MAX_CLIENTS, td.event._SSE_HEARTBEAT_SECONDS, td.event.CONSULT_INTERVAL) == (8192, 15, 3)


def test_a_valve_that_changes_the_look_tells_open_pages(td):
    """Saving the valves pushes the change to open pages when it changes how they look (Canvas
    FX, sidebar, overlays), and not otherwise.

    By hand: with a chat open in another browser, set Sidebar Transparency to translucent: the
    chat's sidebar turns to glass without a reload.
    """
    td.save()
    page = td.stream()
    td.valves(auto_sync=True)
    assert td.heard(page) == []
    td.valves(sidebar_transparency="translucent")
    assert [n for n, _ in td.heard(page)] == ["theme-update"]


def test_disabling_strips_the_theme_and_enabling_brings_it_back(owui, td):
    """Disabling tells open pages to drop the theme, withdraws it from /static/custom.css, and
    leaves an inactive bootloader in /static/loader.js, which clears the theme a page kept;
    enabling tells open pages to fetch it again.

    By hand: with a theme on, disable the function (Admin Panel > Functions): open chats go back
    to Open-WebUI's look. Enable it: they are themed again (within a minute, as the stream
    reconnects).
    """
    td.save()
    page = td.stream()
    owui.disable("theme_designer_pro")
    assert td.heard(page)[0] == ("theme-disable", {"reason": "disabled"})
    assert "owui-theme-designer-pro" not in td.anon.get("/static/custom.css").text
    assert "var _themeActive = false;" in td.anon.get("/static/loader.js").text
    assert td.anon.get(BASE + "/theme.css").status_code == 404
    owui.enable("theme_designer_pro")
    assert "theme-update" in [n for n, _ in td.heard(page)]
    assert "var _themeActive = true;" in td.anon.get("/static/loader.js").text


def test_a_new_designer_url_moves_the_designer_and_keeps_old_pages_themed(td):
    """Changing `designer_url` serves the designer there; the old URL keeps serving the theme
    to pages loaded before the change, until a restart.

    By hand: set Designer Url to /api/v1/my-themes: the designer opens there, and a chat that was
    already open stays themed.
    """
    td.save()
    td.valves(designer_url="/api/v1/my-themes")
    assert "Theme Designer Pro" not in td.page(td.admin, "").text  # Open-WebUI's own web app now
    assert td.admin.get("/api/v1/my-themes", headers=td.FRAME).status_code == 200
    assert td.anon.get("/api/v1/my-themes/theme.css").text == td.CSS
    assert td.anon.get(BASE + "/theme.css").text == td.CSS
    assert "readAsset('/api/v1/my-themes/theme.css')" in td.anon.get("/static/loader.js").text


def test_a_designer_url_outside_the_api_is_moved_into_it(td):
    """The single-page app answers every path outside /api, so a Designer Url there is served
    under /api/v1 instead; one ending in /me, which personal themes use, keeps the default.

    By hand: set Designer Url to /themes: the designer opens at /api/v1/themes.
    """
    td.valves(designer_url="/themes")
    assert td.admin.get("/api/v1/themes", headers=td.FRAME).status_code == 200
    td.valves(designer_url="/api/v1/x/me")
    assert td.admin.get(BASE, headers=td.FRAME).status_code == 200


def test_a_picture_follows_a_new_designer_url(td):
    """Saved themes keep the address their pictures were uploaded at; after a Designer Url
    change they are served with the new one, which is the one that serves them.

    By hand: upload a page picture, then change Designer Url: the picture still shows.
    """
    state = {"_hiddenBackgrounds": {"pages": {"url": BASE + "/page-background?v=1"}}}
    td.save(state=json.dumps(state))
    td.valves(designer_url="/api/v1/my-themes")
    served = td.anon.get("/api/v1/my-themes/state.json").json()
    assert served["_hiddenBackgrounds"]["pages"]["url"] == "/api/v1/my-themes/page-background?v=1"


def test_a_changed_chat_background_tells_its_owners_pages(owui, td):
    """A user's Chat Background Image changing tells their pages, which fade it by its address.

    By hand: with a theme that fades backgrounds, change Settings > Interface > Chat Background
    Image: the open chat shows the new one, faded.
    """
    mine, other = td.stream(td.ada), td.stream(owui.admin)
    owui.emit("user.settings_updated", {"type": "user", "id": td.ada.id})
    assert td.heard(mine) == [("backgrounds-update", {"scope": "chat"})]
    assert td.heard(other) == []


def test_a_changed_model_image_tells_the_pages(owui, td):
    """A model's background image changing tells every page, naming the model when the
    instance theme fades it (its state names it publicly anyway), and only signed-in pages
    otherwise.

    By hand: edit a model's background in Workspace > Models: open chats with it update.
    """
    td.save(state=json.dumps({"_hiddenBackgrounds": {"models": {"m1": True}}}))
    signed_in, signed_out = td.stream(td.ada), td.stream()
    owui.emit("model.updated", {"type": "model", "id": "m1"})
    ((name, data),) = td.heard(signed_out)
    assert (name, data["ids"]) == ("backgrounds-update", ["m1"])
    assert [n for n, _ in td.heard(signed_in)] == ["backgrounds-update"]
    owui.emit("model.updated", {"type": "model", "id": "secret"})
    assert td.heard(signed_out) == []
    td.valves(allow_personal_themes=True)
    owui.emit("model.updated", {"type": "model", "id": "secret"})
    assert [n for n, _ in td.heard(signed_in)] == ["backgrounds-update"]
    assert td.heard(signed_out) == []


def test_a_shutdown_ends_the_streams(owui, td):
    """On shutdown every open stream is ended, so Open-WebUI stops at once instead of waiting
    for the container to be killed.

    By hand: with a chat open, `docker stop` the Open-WebUI container: it stops in about a
    second, not ten.
    """
    page = td.stream()
    owui.emit("system.shutdown.started")
    assert td.heard(page) == [("end", None)]


def test_a_bootloader_an_old_version_wrote_into_index_html_is_removed(owui, plugin):
    """Versions up to 1.6.2 wrote the bootloader into Open-WebUI's index.html; the first start
    removes it, and leaves the rest of the file alone.

    By hand: not repeatable without one of those versions' index.html.
    """
    from open_webui.env import FRONTEND_BUILD_DIR
    from pathlib import Path

    index = Path(FRONTEND_BUILD_DIR) / "index.html"
    index.write_text(
        "<html><head><!-- OWUI Theme Pro Bootloader -->\n<script>old()</script>\n<title>x</title></head></html>"
    )
    owui.startup()
    assert index.read_text() == "<html><head><title>x</title></head></html>"

