"""The Stale Data Dashboard on the test harness. Run with `owpp test stale_data`."""

import time

import pytest

DAY = 86400


@pytest.fixture
def started(owui, plugin):
    owui.startup()
    return plugin


@pytest.fixture
def ada(owui):
    return owui.add_user("Ada Lovelace")


def dashboard(owui, path="/stale-data"):
    got = owui.client(owui.admin).get(path)
    assert got.status_code == 200, got.text
    return got.text


# ---- who may see it ---------------------------------------------------------------------


def test_only_admins_see_it(owui, started, ada):
    """Signed out, a client gets 401 (a browser is sent to sign in); a user who is not an admin
    gets 403; an admin gets the dashboard.

    By hand: open /stale-data in a private window: the sign-in page. As a user who is not an
    admin: 403, "Admins only.". As an admin: the dashboard.
    """
    assert owui.client().get("/stale-data").status_code == 401
    assert owui.client(ada).get("/stale-data").status_code == 403
    assert owui.client(owui.admin).get("/stale-data").status_code == 200


def test_it_is_gone_once_the_function_is_disabled(owui, started):
    """Once the function is disabled, the dashboard is gone.

    By hand: switch the function off and reload /stale-data as an admin: 404.
    """
    owui.disable("stale_data")
    assert owui.client(owui.admin).get("/stale-data").status_code == 404


def test_switching_it_on_mounts_the_dashboard_without_a_restart(owui, plugin):
    """A deploy switches the function on, and that mounts /stale-data at once: Open-WebUI does
    not have to start again.

    By hand: deploy the function to a running instance and open /stale-data as an admin.
    """
    assert "Stale" in dashboard(owui)


def test_a_new_path_moves_the_page(owui, started):
    """Changing DASHBOARD_PATH moves the page, and the old path goes back to Open-WebUI's web app.

    By hand: set DASHBOARD_PATH to /admin/stale and save. /admin/stale shows the dashboard and
    /stale-data shows Open-WebUI.
    """
    owui.set_valves("stale_data", DASHBOARD_PATH="/admin/stale")
    assert "Stale" in dashboard(owui, "/admin/stale")
    # The old path falls through to the web app again.
    assert "<title>Open WebUI</title>" in owui.client(owui.admin).get("/stale-data").text


# ---- what it lists ----------------------------------------------------------------------


def test_it_lists_what_is_older_than_the_threshold_and_not_the_rest(owui, started, ada):
    """Chats, notes and files older than the threshold are listed, with their owners' names, file
    sizes, and pinned chats marked; newer ones are not. A line says how many of each were
    scanned.

    By hand: on an instance with chats, notes and files older than STALE_THRESHOLD_HOURS, open
    the dashboard. The old ones are listed with their owners, a pinned chat is marked pinned,
    newer ones are missing, and the `Scanned ...` line matches what there is.
    """
    old = int(time.time()) - 3 * DAY
    owui.add_chat(ada, title="Old plans", updated_at=old, pinned=True)
    owui.add_chat(ada, title="Fresh chat")
    owui.add_note(ada, title="Old note", markdown="remember", updated_at=old * 10**9)
    owui.add_note(ada, title="Fresh note")
    owui.add_file(ada, filename="old.pdf", size=2048, created_at=old)
    html = dashboard(owui)
    assert "Old plans" in html and "Fresh chat" not in html
    assert "Old note" in html and "Fresh note" not in html  # notes are in nanoseconds
    assert "old.pdf" in html and "2.0 KB" in html
    assert "Ada Lovelace" in html  # owners by name
    assert "pinned" in html
    assert "Scanned 2 chat(s), 2 note(s), 1 file(s)." in html


def test_the_threshold_is_a_valve_read_again_after_a_few_seconds(owui, started, ada):
    """STALE_THRESHOLD_HOURS (default 1) sets how old is stale. The page keeps its read of the
    valves for 5 seconds, so a change shows up after that.

    By hand: with a chat last changed two hours ago, open the dashboard: it is listed. Set
    STALE_THRESHOLD_HOURS to 24 and save, wait 5 seconds and reload: it is gone.
    """
    owui.add_chat(ada, title="Two hours old", updated_at=int(time.time()) - 7200)
    assert "Two hours old" in dashboard(owui)  # default: older than 1 hour
    owui.set_valves("stale_data", STALE_THRESHOLD_HOURS=24)
    assert "Two hours old" in dashboard(owui)  # the page reuses its read of the valves (ttl=5)
    started.module._core_valves_cache.clear()  # ... until it expires
    assert "Two hours old" not in dashboard(owui)


def test_a_file_names_the_chats_it_is_attached_to(owui, started, ada):
    """A file's row names the chats it is attached to.

    By hand: attach an old file to a chat. On the dashboard, that file's row names the chat.
    """
    old = int(time.time()) - 3 * DAY
    file_id = owui.add_file(ada, filename="report.csv", created_at=old)
    owui.add_chat(ada, title="Quarterly review", files=[file_id])
    html = dashboard(owui)
    row = html[html.index("report.csv") :]
    assert "Quarterly review" in row.split("</tr>")[0]


def test_titles_are_escaped(owui, started, ada):
    """Titles are escaped, so a title cannot inject HTML or script into the page.

    By hand: rename an old chat to <script>alert(1)</script>. The dashboard shows that text, and
    no alert pops up.
    """
    owui.add_chat(ada, title="<script>alert(1)</script>", updated_at=1)
    html = dashboard(owui)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_a_title_that_looks_like_a_placeholder_is_shown_as_it_is(owui, started, ada):
    """A title that looks like one of the page's own placeholders (__N_NOTES__) is shown as it is,
    not filled in.

    By hand: rename an old chat to __N_NOTES__. The dashboard shows __N_NOTES__.
    """
    owui.add_chat(ada, title="__N_NOTES__", updated_at=1)
    assert "__N_NOTES__" in dashboard(owui)


def test_with_nothing_stale_it_says_so(owui, started):
    """With nothing stale, the page says so.

    By hand: set STALE_THRESHOLD_HOURS very high and open the dashboard: "No stale chats found!"
    and "No stale notes found!".
    """
    html = dashboard(owui)
    assert "No stale chats found!" in html and "No stale notes found!" in html
