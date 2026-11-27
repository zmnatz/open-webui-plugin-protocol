"""Better Banners on the test harness: `owpp test better_banners` (docs/testing.md).

`plugin` is this folder, bundled as the deploy would and deployed into `owui`, the real Open-WebUI in process.
Its files are fetched from the pinned commit, so these tests need the network.

The server side is all there is to test here: the script it adds to the shared
/static/loader.js, the valves that shape it, and the socket signal it sends when the
banners change. What the script does on the page is in the live tests (live/).
"""

import pydantic
import pytest

ID = "better_banners"
START = "// owui-better-banners:start"
END = "// owui-better-banners:end"
DEFAULT_CONFIG = (
    '{"event": "owui:better-banners", "position": "top", "maxHeight": 160, "resync": 300}'
)


def loader(owui, **headers):
    return owui.client().get("/static/loader.js", headers=headers)


def fragments(owui) -> dict:
    return owui.app.state._owui_static_fragments["/static/loader.js"]


def test_the_upstream_function_loads_as_an_event(plugin):
    """The function taken from the repository loads, as an event function.

    By hand: after deploy, Admin Panel > Functions lists Better Banners.
    """
    assert plugin.type == "event"


def test_after_startup_the_shared_loader_carries_its_script_between_its_markers(owui, plugin):
    """Its script is a block of /static/loader.js, with its default settings in it.

    By hand: open /static/loader.js: it has `// owui-better-banners:start`, then the
    script with `"position": "top", "maxHeight": 160, "resync": 300`, then the end marker.
    """
    owui.startup()
    response = loader(owui)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/javascript; charset=utf-8"
    text = response.text
    assert text.startswith(START + "\n(function () {")
    assert text.endswith(END + "\n")
    assert f"var CFG = {DEFAULT_CONFIG};" in text
    assert "__CONFIG__" not in text and "__CSS__" not in text


def test_its_stylesheet_travels_inside_the_script_not_in_custom_css(owui, plugin):
    """The CSS is a string in the script, added to the page by it; /static/custom.css
    carries nothing of Better Banners.

    By hand: open /static/custom.css: no `owui-better-banners`; the page's <head> has a
    <style> starting `#owui-better-banners{`.
    """
    owui.startup()
    assert 'var CSS = "#owui-better-banners{--obb-enter-y:-10px;' in loader(owui).text
    assert "owui-better-banners" not in owui.client().get("/static/custom.css").text


def test_saving_the_valves_changes_the_settings_in_the_script(owui, plugin):
    """Position, the tallest a banner gets, and the resync interval reach the script.

    By hand: set position to bottom, max height to 240, resync to 0, save, and open
    /static/loader.js: `"position": "bottom", "maxHeight": 240, "resync": 0`.
    """
    owui.startup()
    owui.set_valves(ID, position="bottom", max_height_px=240, resync_interval_seconds=0)
    assert (
        'var CFG = {"event": "owui:better-banners", "position": "bottom", "maxHeight": 240, '
        '"resync": 0};'
    ) in loader(owui).text


@pytest.mark.parametrize(
    "valves",
    [
        {"position": "middle"},
        {"max_height_px": 59},
        {"max_height_px": 601},
        {"resync_interval_seconds": -1},
        {"resync_interval_seconds": 3601},
    ],
)
def test_valves_out_of_range_are_refused(plugin, valves):
    """Open-WebUI's valve form refuses them, as pydantic does here.

    By hand: set max height to 59 and save: Open-WebUI says the value is invalid.
    """
    with pytest.raises(pydantic.ValidationError):
        plugin.instance.Valves(**valves)


def test_the_edges_of_each_range_are_accepted(plugin):
    """By hand: max height 60 and 600, resync 0 and 3600 each save."""
    for valves in ({"max_height_px": 60}, {"max_height_px": 600}):
        assert plugin.instance.Valves(**valves).max_height_px == valves["max_height_px"]
    for seconds in (0, 3600):
        assert (
            plugin.instance.Valves(resync_interval_seconds=seconds).resync_interval_seconds
            == seconds
        )


def test_disabling_it_withdraws_its_script_and_enabling_brings_it_back(owui, plugin):
    """By hand: disable Better Banners and reload a chat: no banners from it, and
    /static/loader.js has no `owui-better-banners` block. Enable it: the block is back.
    """
    owui.startup()
    owui.disable(ID)
    assert START not in loader(owui).text
    owui.enable(ID)
    assert START in loader(owui).text


def test_a_change_to_the_banners_tells_every_open_tab(owui, plugin):
    """When the admin saves the banners, it sends `owui:better-banners` on the socket,
    which the script in each tab answers by fetching the banners again.

    By hand: with a chat open in a second tab, add a banner and save: it appears there
    without a reload, within about two seconds.
    """
    owui.startup()
    owui.emitted.clear()
    owui.emit("config.banners.updated")
    assert owui.emitted == [("owui:better-banners", {})]


def test_other_events_send_nothing_on_the_socket(owui, plugin):
    """By hand: save another setting with a chat open: no banner request is made."""
    owui.startup()
    owui.emitted.clear()
    owui.emit("config.updated")
    owui.set_valves(ID, position="bottom")
    assert owui.emitted == []


def test_the_fragment_of_a_version_before_1_0_3_is_dropped(owui, plugin):
    """Up to 1.0.2 its block was registered under `better-banners`; a newer one drops it,
    so a tab never runs the script twice.

    By hand: upgrade from 1.0.2 without a restart: /static/loader.js has one
    `owui-better-banners` block.
    """
    fragments(owui)["better-banners"] = {
        "start": START,
        "end": END,
        "js": lambda: "LEGACY",
        "order": 0,
    }
    owui.startup()
    assert "better-banners" not in fragments(owui)
    assert "LEGACY" not in loader(owui).text
    assert loader(owui).text.count(START) == 1


def test_another_plugin_deleted_has_its_fragment_withdrawn(owui, plugin):
    """A deleted plugin never sees its own deletion; Better Banners drops its fragments.

    By hand: install another plugin that adds to /static/loader.js, delete it: its block
    is gone from /static/loader.js without a restart.
    """
    owui.startup()
    fragments(owui)["function_other"] = {
        "start": "// other:start",
        "end": "// other:end",
        "js": lambda: "// other:start\nOTHER\n// other:end",
        "order": 0,
    }
    assert "OTHER" in loader(owui).text
    owui.emit("function.deleted", "other")
    assert "OTHER" not in loader(owui).text


def test_the_loader_is_revalidated_with_its_etag(owui, plugin):
    """Browsers keep it, but ask each time: the same content answers 304, also with the
    weak tag a gzipping proxy sends back.

    By hand: reload a chat twice with the browser's network panel open: the second
    /static/loader.js is 304.
    """
    owui.startup()
    first = loader(owui)
    etag = first.headers["etag"]
    assert etag.startswith('"owui-') and etag.endswith('"') and len(etag) == 2 + 5 + 32
    assert first.headers["cache-control"] == "no-cache, must-revalidate, private"
    assert loader(owui, **{"If-None-Match": etag}).status_code == 304
    assert loader(owui, **{"If-None-Match": "W/" + etag}).status_code == 304
    assert loader(owui, **{"If-None-Match": '"owui-other"'}).status_code == 200


def test_a_loader_js_on_disk_is_kept_and_an_old_block_in_it_removed(owui, plugin):
    """What Open-WebUI ships in static/loader.js stays first; a block an older,
    file-writing build left there is not served twice.

    By hand: put `console.log("disk")` in Open-WebUI's static/loader.js and restart:
    /static/loader.js starts with it, then `;`, then the Better Banners block.
    """
    (owui.static_dir / "loader.js").write_text(
        f'console.log("disk");\n{START}\nOLD BLOCK\n{END}\n', encoding="utf-8"
    )
    owui.startup()
    text = loader(owui).text
    assert text.startswith(f'console.log("disk");\n;\n{START}\n')
    assert "OLD BLOCK" not in text
