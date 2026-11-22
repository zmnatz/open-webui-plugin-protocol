"""The Shared Assets Protocol end to end: bundled plugins publish their assets/ files and the
real shared route (the vendored block) serves them, through Starlette."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from conftest import write_plugin
from starlette.applications import Starlette
from starlette.testclient import TestClient

from owpp.bundle import bundle_function

HEX = "0" * 32
LOADER = "/static/loader.js"
CSS = "/static/custom.css"


def load(tmp_path, plugin_id, files, manifest="function:\n  title: T\n"):
    """Bundle a plugin folder and run it as Open-WebUI would: a module named function_<id>_<hex>."""
    folder = tmp_path / plugin_id
    write_plugin(folder, {"plugin.yaml": manifest, **files})
    namespace: dict = {"__name__": f"function_{plugin_id}_{HEX}"}
    exec(compile(bundle_function(folder), f"{plugin_id}.py", "exec"), namespace)
    return namespace


def send(namespace, app, name, subject=None):
    """Deliver one lifecycle event to the plugin's Event, as Open-WebUI does."""
    event = {"subject": {"id": subject}} if subject else {}
    asyncio.run(namespace["Event"]().event(event, __event_name__=name, __app__=app))


def started(namespace, app):
    send(namespace, app, "system.startup.completed")


@pytest.fixture
def app():
    return Starlette()


def get(app, path, **headers):
    return TestClient(app).get(path, headers=headers)


class TestPublishing:
    def test_both_files_are_served_with_the_plugins_markers(self, tmp_path, app):
        ns = load(
            tmp_path,
            "theme",
            {"assets/loader.js": "boot();\n", "assets/custom.css": "a{color:red}\n"},
        )
        started(ns, app)
        js, css = get(app, LOADER), get(app, CSS)
        assert js.status_code == css.status_code == 200
        assert js.headers["content-type"].startswith("application/javascript")
        assert css.headers["content-type"].startswith("text/css")
        assert js.text.startswith("// owui:theme:start\n") and js.text.rstrip().endswith(
            "// owui:theme:end"
        )
        assert css.text.startswith("/* owui:theme:start */\na{color:red}\n/* owui:theme:end */")

    def test_the_script_is_wrapped_in_its_own_function_with_a_try_catch(self, tmp_path, app):
        started(load(tmp_path, "theme", {"assets/loader.js": "boot();\n"}), app)
        text = get(app, LOADER).text
        assert '(function () {\n  "use strict";\n  try {\nboot();\n  } catch (e) {' in text
        assert 'console.error("[theme]", e);' in text

    def test_the_script_runs_in_strict_mode_with_its_own_scope(self, tmp_path, app):
        # `return` works at the top of the file, and a top-level const cannot clash with another
        # plugin's in the shared loader.js, because both are inside this function.
        started(
            load(
                tmp_path,
                "theme",
                {"assets/loader.js": "if (window.__x) return;\nconst shared = 1;\n"},
            ),
            app,
        )
        text = get(app, LOADER).text
        assert text.count("(function () {") == 1 and text.count('"use strict"') == 1
        assert text.index('"use strict"') < text.index("try {") < text.index("const shared")

    def test_wrap_false_leaves_the_script_as_written(self, tmp_path, app):
        ns = load(
            tmp_path,
            "theme",
            {"assets/loader.js": "boot();\n"},
            "function:\n  title: T\nassets: {wrap: false}\n",
        )
        started(ns, app)
        assert "try {" not in get(app, LOADER).text

    def test_the_stylesheet_is_never_wrapped(self, tmp_path, app):
        started(load(tmp_path, "theme", {"assets/custom.css": "a{}\n"}), app)
        assert "function" not in get(app, CSS).text

    def test_a_plugin_with_one_file_leaves_the_other_path_alone(self, tmp_path, app):
        started(load(tmp_path, "theme", {"assets/custom.css": "a{}\n"}), app)
        assert get(app, CSS).status_code == 200
        assert get(app, LOADER).status_code == 404

    def test_the_browser_cache_validator_works(self, tmp_path, app):
        started(load(tmp_path, "theme", {"assets/custom.css": "a{}\n"}), app)
        first = get(app, CSS)
        assert get(app, CSS, **{"If-None-Match": first.headers["etag"]}).status_code == 304

    def test_nothing_is_published_until_the_function_loads(self, tmp_path, app):
        load(tmp_path, "theme", {"assets/custom.css": "a{}\n"})
        assert get(app, CSS).status_code == 404


class TestSharingWithOtherPlugins:
    def test_two_plugins_share_the_files_ordered_by_order(self, tmp_path, app):
        late = load(
            tmp_path,
            "late",
            {"assets/custom.css": ".late{}\n"},
            "function:\n  title: L\nassets: {order: 10}\n",
        )
        early = load(
            tmp_path,
            "early",
            {"assets/custom.css": ".early{}\n"},
            "function:\n  title: E\nassets: {order: -10}\n",
        )
        started(late, app)
        started(early, app)  # loaded second, but composed first
        text = get(app, CSS).text
        assert text.index(".early{}") < text.index(".late{}")
        assert "owui:early:start" in text and "owui:late:start" in text

    def test_each_plugin_is_keyed_by_its_own_id(self, tmp_path, app):
        for name in ("one", "two"):
            started(load(tmp_path, name, {"assets/loader.js": f"{name}();\n"}), app)
        text = get(app, LOADER).text
        assert "one();" in text and "two();" in text

    def test_a_deleted_plugin_is_withdrawn_by_the_next_event_of_another(self, tmp_path, app):
        gone = load(tmp_path, "gone", {"assets/custom.css": ".gone{}\n"})
        stays = load(tmp_path, "stays", {"assets/custom.css": ".stays{}\n"})
        started(gone, app)
        started(stays, app)
        assert ".gone{}" in get(app, CSS).text
        send(
            stays, app, "function.deleted", subject="gone"
        )  # a deleted plugin never sees its own deletion
        text = get(app, CSS).text
        assert ".gone{}" not in text and ".stays{}" in text


class TestSwitchingOffAndOn:
    def test_disabling_the_function_withdraws_its_fragments(self, tmp_path, app):
        ns = load(tmp_path, "theme", {"assets/custom.css": "a{}\n"})
        started(ns, app)
        assert "a{}" in get(app, CSS).text
        send(ns, app, "function.disable_started", subject="theme")
        assert get(app, CSS).text == ""  # the protocol's way to switch a fragment off
        send(ns, app, "function.enable_started", subject="theme")
        assert "a{}" in get(app, CSS).text

    def test_another_plugins_disable_event_changes_nothing(self, tmp_path, app):
        ns = load(tmp_path, "theme", {"assets/custom.css": "a{}\n"})
        started(ns, app)
        send(ns, app, "function.disable_started", subject="someone_else")
        assert "a{}" in get(app, CSS).text


class TestVariables:
    """asset_vars() fills __NAME__ placeholders, so a valve can reach the script and the stylesheet."""

    FUNCTION = (
        "class Event(PluginAssets):\n"
        "    accent = '#4f46e5'\n"
        "    def asset_vars(self):\n"
        "        return {'ACCENT': Event.accent}\n"
    )

    def build(self, tmp_path):
        return load(
            tmp_path,
            "theme",
            {
                "function.py": self.FUNCTION,
                "assets/custom.css": ":root { --accent: __ACCENT__; --other: __UNKNOWN__; }\n",
                "assets/loader.js": "var accent = '__ACCENT__';\n",
            },
        )

    def test_placeholders_are_filled_and_unknown_ones_are_left(self, tmp_path, app):
        started(self.build(tmp_path), app)
        css = get(app, CSS).text
        assert "--accent: #4f46e5;" in css and "--other: __UNKNOWN__;" in css
        assert "var accent = '#4f46e5';" in get(app, LOADER).text

    def test_a_value_is_served_as_written_even_when_it_holds_a_placeholder(self, tmp_path, app):
        """Every placeholder is filled in one pass: a value (often a valve someone typed) that
        holds another placeholder's text is not filled again, whatever order the names sort in,
        and a placeholder used twice is filled both times (#69)."""
        ns = load(
            tmp_path,
            "stamp",
            {
                "function.py": (
                    "class Event(PluginAssets):\n"
                    "    def asset_vars(self):\n"
                    "        return {'NOTE': 'see __ROUTE__ or __A__', 'ROUTE': '/r', 'A': 'x __NOTE__'}\n"
                ),
                "assets/loader.js": "log('__NOTE__', '__ROUTE__', '__A__', '__ROUTE__');\n",
            },
        )
        started(ns, app)
        assert "log('see __ROUTE__ or __A__', '/r', 'x __NOTE__', '/r');" in get(app, LOADER).text

    def test_a_changed_value_reaches_the_next_request(self, tmp_path, app):
        ns = self.build(tmp_path)
        started(ns, app)
        assert "#4f46e5" in get(app, CSS).text
        ns["Event"].accent = "#ff0000"
        assert "--accent: #ff0000;" in get(app, CSS).text

    def test_the_fragment_is_only_rebuilt_when_the_values_change(self, tmp_path, app):
        ns = self.build(tmp_path)
        started(ns, app)
        get(app, CSS)
        state = ns["_asset_state"]["cache"]["custom.css"]
        get(app, CSS)
        assert (
            ns["_asset_state"]["cache"]["custom.css"] is state
        )  # the same prebuilt string, no new work


class TestWithLiveReload:
    """include: [live_reload] gates the fragments on the add-on's own active flag."""

    @pytest.fixture(autouse=True)
    def _stub_open_webui(self, monkeypatch):
        codec = types.ModuleType("open_webui.utils.json_codec")
        codec.JSONCodec = type("JSONCodec", (), {})
        for name, module in (
            ("open_webui", types.ModuleType("open_webui")),
            ("open_webui.utils", types.ModuleType("open_webui.utils")),
            ("open_webui.utils.json_codec", codec),
        ):
            monkeypatch.setitem(sys.modules, name, module)

    def build(self, tmp_path):
        return load(
            tmp_path,
            "theme",
            {"assets/custom.css": "a{}\n"},
            "function:\n  title: T\ninclude: [live_reload]\n",
        )

    def test_it_publishes_once_loaded_and_withdraws_when_disabled(self, tmp_path, app):
        ns = self.build(tmp_path)
        assert "reload_active" in ns and "reload_bootstrap" in ns
        started(ns, app)
        assert "a{}" in get(app, CSS).text
        send(ns, app, "function.disable_started", subject="theme")
        assert get(app, CSS).text == ""
        send(ns, app, "function.enable_started", subject="theme")
        assert "a{}" in get(app, CSS).text

    def test_register_is_the_function_the_add_on_calls(self, tmp_path, app):
        ns = self.build(tmp_path)
        ns["register"](app)  # what reload_mark_loaded does on any container
        ns["reload_state"](app)["active"] = True
        assert "a{}" in get(app, CSS).text
