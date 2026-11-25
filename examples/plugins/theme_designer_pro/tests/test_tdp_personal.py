"""Theme Designer Pro's personal themes (`allow_personal_themes`) and its pictures: the sign-in
page's, the one behind pages without a chat, and a user's own. Run with `owpp test
theme_designer_pro`."""

import json

import pytest

BASE = "/api/v1/theme-designer"


@pytest.fixture
def personal(td):
    td.valves(allow_personal_themes=True)
    return td


def test_a_personal_theme_reaches_only_its_owner(owui, personal):
    """A user's own theme is served to them alone; everyone else, signed in or not, keeps the
    instance theme.

    By hand: with Allow Personal Themes on, a user picks a theme in Settings > Themes. Their
    chats show it; an admin's and another user's chats do not.
    """
    td = personal
    td.save()
    mine = td.save(td.user, "/me", css=td.CSS.replace("red", "blue"))
    assert mine.status_code == 200 and mine.json()["cssTag"]
    assert "blue" in td.user.get(BASE + "/me/theme.css").text
    assert (
        td.user.get(BASE + "/me/theme.css").headers["cache-control"]
        == "private, no-cache, must-revalidate"
    )
    bob = owui.client(owui.add_user("Bob"))
    assert bob.get(BASE + "/me/theme.css").text == ""
    assert td.anon.get(BASE + "/me/theme.css").text == ""
    assert td.anon.get(BASE + "/me/state.json").text == "{}"
    assert "red" in td.anon.get(BASE + "/theme.css").text


def test_with_personal_themes_off_the_personal_routes_have_nothing(td):
    """With `allow_personal_themes` off a user saves no theme of their own, and the personal
    routes answer "nothing saved", so every page shows the instance theme.

    By hand: turn Allow Personal Themes off: users' Settings have no Themes tab, and their
    chats show the instance theme.
    """
    td.valves(allow_personal_themes=False)
    assert td.save(td.user, "/me").status_code == 403
    assert td.user.get(BASE + "/me/theme.css").text == ""
    assert td.user.get(BASE + "/me/state.json").text == "{}"
    assert td.user.get(BASE + "/me/library.json").text == "{}"


def test_a_user_keeps_their_gallery_when_going_back_to_the_instance_theme(personal):
    """Use instance theme drops a user's own theme and keeps their saved themes; Factory Reset
    in their designer drops both.

    By hand: in Settings > Themes, press Use instance theme: the instance theme is back, and
    the gallery still has your themes. Factory Reset empties it too.
    """
    td = personal
    td.save(td.user, "/me", library=json.dumps({"presets": ["mine"]}))
    assert td.user.post(BASE + "/me", json={"reset": True}).json() == {"status": "reset"}
    assert td.user.get(BASE + "/me/theme.css").text == ""
    assert td.user.get(BASE + "/me/library.json").json() == {"presets": ["mine"]}
    td.user.post(BASE + "/me", json={"reset": True, "wipe_library": True})
    assert td.user.get(BASE + "/me/library.json").json() == {}


def test_a_personal_theme_stays_within_the_admins_limits(personal):
    """The valves hold for personal themes too: with Enable Canvas FX off, a user's animation
    does not run either.

    By hand: a user saves an animated personal theme; an admin turns Enable Canvas FX off: the
    user's chats show the theme without the animation.
    """
    td = personal
    td.save(td.user, "/me")
    td.valves(enable_canvas_fx=False)
    assert "canvasScript" not in td.user.get(BASE + "/me/state.json").json()["dark"]


def test_a_deleted_accounts_themes_go_with_it(owui, personal):
    """Deleting an account deletes its personal theme and gallery.

    By hand: delete a user who had a personal theme (Admin Panel > Users): their folder under
    DATA_DIR/theme/users/ is gone.
    """
    td = personal
    td.save(td.user, "/me")
    folder = td.plugin.instance._get_css_path(td.ada.id).parent
    assert folder.is_dir()
    owui.emit("user.deleted", {"type": "user", "id": td.ada.id})
    assert not folder.exists()


# ---- pictures ------------------------------------------------------------------------


def test_the_sign_in_picture_is_for_everyone_and_changed_by_admins(td):
    """The sign-in page's picture is read by anyone (nobody is signed in there) and uploaded or
    removed by an admin only.

    By hand: in the designer's Backgrounds tab, upload a sign-in picture. A private window's
    sign-in page shows it.
    """
    assert td.user.post(BASE + "/auth-background", content=td.PNG).status_code == 403
    assert td.anon.post(BASE + "/auth-background", content=td.PNG).status_code == 401
    url = td.admin.post(BASE + "/auth-background", content=td.PNG).json()["url"]
    assert url.startswith(BASE + "/auth-background?v=")
    picture = td.anon.get(BASE + "/auth-background")
    assert (picture.status_code, picture.headers["content-type"], picture.content) == (
        200,
        "image/png",
        td.PNG,
    )
    assert (
        td.anon.get(
            BASE + "/auth-background", headers={"if-none-match": picture.headers["etag"]}
        ).status_code
        == 304
    )
    assert td.admin.delete(BASE + "/auth-background").json() == {"ok": True}
    assert td.anon.get(BASE + "/auth-background").status_code == 404


@pytest.mark.parametrize(
    ("data", "status"),
    [(b"<svg onload=alert(1)></svg>", 415), (b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024), 413)],
)
def test_a_picture_must_be_a_picture_of_up_to_5_mb(td, data, status):
    """A picture is a PNG, JPEG, GIF or WebP by its own bytes (never SVG, which can carry
    script), of up to 5 MB.

    By hand: upload an SVG in the Backgrounds tab: "Use a PNG, JPEG, GIF or WebP picture".
    """
    assert td.admin.post(BASE + "/page-background", content=data).status_code == status


def test_the_page_picture_shows_to_anyone_signed_in(td):
    """The instance theme's picture behind pages without a chat shows to anyone signed in;
    only an admin changes it.

    By hand: an admin uploads a page picture in the Backgrounds tab; a user's home page shows it.
    """
    td.admin.post(BASE + "/page-background", content=td.PNG)
    assert td.user.get(BASE + "/page-background").content == td.PNG
    assert td.anon.get(BASE + "/page-background").status_code == 401
    assert td.user.post(BASE + "/page-background", content=td.PNG).status_code == 403


def test_a_personal_page_picture_is_its_owners(owui, td):
    """A personal theme's picture is uploaded by, and shown to, its owner alone, and only while
    personal themes are on.

    By hand: as a user, upload a page picture in your Settings > Themes; another user does not
    see it.
    """
    td.valves(allow_personal_themes=False)
    assert td.user.post(BASE + "/me/page-background", content=td.PNG).status_code == 403
    td.valves(allow_personal_themes=True)
    url = td.user.post(BASE + "/me/page-background", content=td.PNG).json()["url"]
    assert url.startswith(BASE + "/me/page-background?v=")
    assert td.user.get(BASE + "/me/page-background").content == td.PNG
    assert owui.client(owui.add_user("Bob")).get(BASE + "/me/page-background").status_code == 404


def test_a_change_to_a_picture_from_another_site_is_refused(td):
    """Uploading or removing a picture is a change, refused from another site's page.

    By hand: not repeatable without a second site.
    """
    cross = {"sec-fetch-site": "cross-site"}
    assert (
        td.admin.post(BASE + "/auth-background", content=td.PNG, headers=cross).status_code == 403
    )
    assert td.admin.delete(BASE + "/page-background", headers=cross).status_code == 403
