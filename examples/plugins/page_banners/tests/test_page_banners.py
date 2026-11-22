"""Page Banners against a mock Open-WebUI: its script and stylesheet are assets/ files,
served through the Shared Assets Protocol. Run with `owpp test page_banners`."""

import json
import re

import pytest


@pytest.fixture
def started(owui, plugin):
    owui.startup()
    return plugin


def get(owui, path):
    return owui.client().get(path)


def config(owui):
    text = get(owui, "/static/loader.js").text
    assert "__CONFIG__" not in text
    return json.loads(re.search(r"var CFG = (\{.*?\});", text).group(1))


def test_the_script_and_the_stylesheet_are_published_into_the_shared_files(owui, started):
    """At startup, its script and stylesheet are published into /static/loader.js and
    /static/custom.css, each in its own owui:page_banners block, served as JavaScript and CSS.

    By hand: open <host>/static/loader.js and <host>/static/custom.css. Each has an
    owui:page_banners:start block, and the network tab shows loader.js as
    application/javascript.
    """
    js, css = get(owui, "/static/loader.js"), get(owui, "/static/custom.css")
    assert js.status_code == css.status_code == 200
    assert js.headers["content-type"].startswith("application/javascript")
    assert "// owui:page_banners:start" in js.text and "/* owui:page_banners:start */" in css.text
    assert "#owui-page-banners" in css.text and "window.__owuiPageBanners" in js.text


def test_they_are_served_to_everyone_who_loads_the_page(owui, started):
    """The files need no sign-in, because the sign-in page loads them too.

    By hand: in a private window, open <host>/static/loader.js. It loads.
    """
    # loader.js and custom.css are loaded by the login page too: no sign-in needed.
    assert get(owui, "/static/loader.js").status_code == 200


def test_the_valves_reach_the_script_as_its_config(owui, started):
    """The valves reach the script as its CFG (by default top, 160 and 300), and a change shows up
    in the served script.

    By hand: open /static/loader.js and find `var CFG = {...}`. Set position to bottom and
    max_height_px to 240 in the function's valves, save and reload: CFG has the new values, and
    banners show above the message input.
    """
    assert config(owui) == {
        "event": "owui:page-banners",
        "position": "top",
        "maxHeight": 160,
        "resync": 300,
    }
    owui.set_valves("page_banners", position="bottom", max_height_px=240)
    assert config(owui)["position"] == "bottom"
    assert config(owui)["maxHeight"] == 240


def test_a_valve_out_of_range_is_refused(owui, started):
    """max_height_px below its minimum (60) is refused.

    By hand: set max_height_px to 10 and save. Open-WebUI refuses the valves.
    """
    with pytest.raises(ValueError):
        owui.set_valves("page_banners", max_height_px=10)


def test_the_file_on_disk_is_kept_and_its_block_goes_after_it(owui, started):
    """A custom.css already in Open-WebUI's static folder is kept, with the plugin's block after
    it.

    By hand: put `body { color: red; }` in the static folder's custom.css and restart.
    /static/custom.css starts with your rule, followed by the owui:page_banners block.
    """
    (owui.static_dir / "custom.css").write_text("body { color: red; }\n")
    css = get(owui, "/static/custom.css").text
    assert css.startswith("body { color: red; }\n\n/* owui:page_banners:start */")


def test_the_script_runs_inside_a_try_catch_the_stylesheet_is_plain(owui, started):
    """The script runs inside a try/catch, so an error in it cannot break the page; the stylesheet
    has no wrapper.

    By hand: read /static/loader.js: its block ends in `} catch (e) {`. /static/custom.css has
    no catch.
    """
    assert "} catch (e) {" in get(owui, "/static/loader.js").text
    assert "catch" not in get(owui, "/static/custom.css").text


def test_disabling_it_withdraws_both_and_enabling_brings_them_back(owui, started):
    """Disabling the function takes its blocks out of both files; enabling puts them back.

    By hand: switch the function off and open both files: no owui:page_banners block. Switch it
    on: the blocks are back.
    """
    owui.disable("page_banners")
    assert get(owui, "/static/loader.js").text == ""
    assert get(owui, "/static/custom.css").text == ""
    owui.enable("page_banners")
    assert "owui:page_banners" in get(owui, "/static/custom.css").text


def test_an_admin_edit_is_pushed_to_open_tabs(owui, started):
    """When an admin edits the banners, open tabs are told over the socket (owui:page-banners).

    By hand: keep a chat open in one tab and add a banner under Admin Panel > Settings > General
    in another. It appears in the first tab without a reload.
    """
    owui.emit("config.banners.updated")
    assert owui.emitted == [("owui:page-banners", {})]


def test_an_unchanged_file_is_answered_with_not_modified(owui, started):
    """Asking again for an unchanged file, with its ETag, gets 304 Not Modified.

    By hand: load /static/loader.js twice with the network tab open and the cache on. The second
    answer is 304.
    """
    client = owui.client()
    first = client.get("/static/loader.js")
    again = client.get("/static/loader.js", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304


def test_the_script_file_is_only_a_body_and_is_wrapped_once(owui, plugin_dir, started):
    """assets/loader.js holds only the script's body; owpp adds the wrapper, with "use strict" and
    the try, exactly once.

    By hand: assets/loader.js neither starts with (function nor contains use strict. The served
    /static/loader.js has "use strict" once, followed by `try {` and the file's `// Page
    Banners` header.
    """
    source = (plugin_dir / "assets" / "loader.js").read_text()
    code = [line for line in source.splitlines() if line.strip() and not line.startswith("//")]
    assert not code[0].startswith("(function"), "owpp adds the wrapper; the file must not"
    assert "use strict" not in source  # the wrapper supplies it
    served = get(owui, "/static/loader.js").text
    assert served.count('"use strict"') == 1
    assert "try {\n// Page Banners" in served  # our wrapper, then the file's own header comment


def test_it_can_sit_beside_better_banners(plugin_dir):
    """None of Better Banners' ids, classes or socket event are left, so the two can run side by
    side.

    By hand: `grep -rE 'owui-better-banners|obb-|owui:better-banners|__owuiBetterBanners' assets
    function.py` finds nothing. Or install both: each shows its banners.
    """
    # The ids, classes and socket event are renamed: nothing of the original is left to collide.
    text = "".join(
        (plugin_dir / f).read_text()
        for f in ("assets/loader.js", "assets/custom.css", "function.py")
    )
    for original in ("owui-better-banners", "obb-", "owui:better-banners", "__owuiBetterBanners"):
        assert original not in text, original
