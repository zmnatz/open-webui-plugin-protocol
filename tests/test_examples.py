"""Behaviour of the example plugins, run from their real bundles with Open-WebUI's own modules stubbed."""

from __future__ import annotations

import asyncio
import shutil
import sys
import types

import pytest
from conftest import EXAMPLES

from owpp.bundle import bundle_function

ROUTES = ["time", "filesystem", "other"]


@pytest.fixture
def event_class(monkeypatch):
    """Bundle an example folder and return its Event class."""
    # Only aiohttp, imported at the top of mcpo_sync's bundle, needs a stand-in (pydantic is real).
    monkeypatch.setitem(sys.modules, "aiohttp", types.ModuleType("aiohttp"))
    for name in (
        "MCPO_SYNC_MINUTES",
        "MCPO_SERVERS_ENABLED",
    ):  # what the example reads from the container
        monkeypatch.delenv(name, raising=False)

    def load(folder, module_name="function_mcpo_sync_" + "0" * 32):
        namespace: dict = {"__name__": module_name}
        exec(compile(bundle_function(folder), "mcpo_sync.py", "exec"), namespace)
        return namespace["Event"]

    return load


def connections(event_class, folder):
    return {
        c["info"]["id"]: c
        for c in event_class(folder)().build_connections("http://mcpo:8000", "key", ROUTES)
    }


def test_mcpo_sync_applies_the_config_it_ships(event_class):
    got = connections(event_class, EXAMPLES / "mcpo_sync")
    assert got["mcpo-time"]["info"]["name"] == "Clock"
    assert got["mcpo-time"]["info"]["description"] == "The current time and time zone conversions."
    assert got["mcpo-time"]["config"] == {"enable": True}
    assert got["mcpo-filesystem"]["config"] == {"enable": False}
    assert (
        got["mcpo-filesystem"]["info"]["name"] == "filesystem (mcpo)"
    )  # no name override: default
    # A server the config does not mention keeps every default.
    assert got["mcpo-other"]["info"]["name"] == "other (mcpo)"
    assert got["mcpo-other"]["info"]["description"] == "other MCP server via mcpo (OpenAPI)"
    assert got["mcpo-other"]["config"] == {"enable": True}


def test_a_changed_config_changes_what_is_synced(event_class, tmp_path):
    folder = tmp_path / "mcpo_sync"
    shutil.copytree(EXAMPLES / "mcpo_sync", folder)
    (folder / "config.yaml").write_text(
        "enable: false\nservers:\n  other: {enable: true, name: Other}\n"
    )
    got = connections(event_class, folder)
    assert got["mcpo-time"]["config"] == {"enable": False}  # the global default flipped
    assert got["mcpo-other"]["config"] == {"enable": True}
    assert got["mcpo-other"]["info"]["name"] == "Other"


def test_a_malformed_servers_entry_is_ignored_not_fatal(event_class, tmp_path):
    folder = tmp_path / "mcpo_sync"
    shutil.copytree(EXAMPLES / "mcpo_sync", folder)
    (folder / "config.yaml").write_text("servers: [time, filesystem]\n")
    got = connections(event_class, folder)
    assert got["mcpo-time"]["info"]["name"] == "time (mcpo)"
    (folder / "config.yaml").write_text("servers:\n  time: just-a-string\n")
    assert connections(event_class, folder)["mcpo-time"]["info"]["name"] == "time (mcpo)"


def test_an_empty_config_leaves_the_defaults(event_class, tmp_path):
    folder = tmp_path / "mcpo_sync"
    shutil.copytree(EXAMPLES / "mcpo_sync", folder)
    (folder / "config.yaml").write_text("")
    got = connections(event_class, folder)
    assert all(c["config"] == {"enable": True} for c in got.values())
    assert got["mcpo-time"]["info"]["name"] == "time (mcpo)"


class TestPageBanners:
    """The Better Banners variant: its script and stylesheet are assets/ files, served through the protocol."""

    FOLDER = EXAMPLES / "page_banners"

    @pytest.fixture
    def banners(self, monkeypatch):
        from starlette.applications import Starlette

        codec = types.ModuleType("open_webui.utils.json_codec")
        codec.JSONCodec = type("JSONCodec", (), {})
        emitted: list = []
        sio = types.SimpleNamespace(emit=None)

        async def emit(name, payload):
            emitted.append((name, payload))

        sio.emit = emit
        socket_main = types.ModuleType("open_webui.socket.main")
        socket_main.sio = sio
        for name, module in (
            ("open_webui", types.ModuleType("open_webui")),
            ("open_webui.utils", types.ModuleType("open_webui.utils")),
            ("open_webui.utils.json_codec", codec),
            ("open_webui.socket", types.ModuleType("open_webui.socket")),
            ("open_webui.socket.main", socket_main),
        ):
            monkeypatch.setitem(sys.modules, name, module)
        # A real registered module, as Open-WebUI makes one: pydantic resolves postponed
        # annotations (Literal) through sys.modules[cls.__module__].
        module = types.ModuleType("function_page_banners_" + "0" * 32)
        monkeypatch.setitem(sys.modules, module.__name__, module)
        namespace = module.__dict__
        exec(compile(bundle_function(self.FOLDER), "page_banners.py", "exec"), namespace)
        event = namespace["Event"]()
        return types.SimpleNamespace(ns=namespace, event=event, app=Starlette(), emitted=emitted)

    @staticmethod
    def send(b, name, subject=None):
        payload = {"subject": {"id": subject}} if subject else {}
        asyncio.run(b.event.event(payload, __event_name__=name, __app__=b.app))

    @staticmethod
    def get(b, path):
        from starlette.testclient import TestClient

        return TestClient(b.app).get(path)

    def test_the_script_and_the_stylesheet_are_published_into_the_shared_files(self, banners):
        self.send(banners, "system.startup.completed")
        js, css = self.get(banners, "/static/loader.js"), self.get(banners, "/static/custom.css")
        assert js.status_code == css.status_code == 200
        assert (
            "// owui:page_banners:start" in js.text and "/* owui:page_banners:start */" in css.text
        )
        assert "#owui-page-banners" in css.text and "window.__owuiPageBanners" in js.text

    @staticmethod
    def config(b):
        import json
        import re

        text = TestPageBanners.get(b, "/static/loader.js").text
        assert "__CONFIG__" not in text
        return json.loads(re.search(r"var CFG = (\{.*?\});", text).group(1))

    def test_the_valves_reach_the_script_as_its_config(self, banners):
        self.send(banners, "system.startup.completed")
        assert self.config(banners) == {
            "event": "owui:page-banners",
            "position": "top",
            "maxHeight": 160,
            "resync": 300,
        }
        banners.event.valves.position = "bottom"
        banners.event.valves.max_height_px = 240
        assert self.config(banners)["position"] == "bottom"
        assert self.config(banners)["maxHeight"] == 240

    def test_the_script_runs_inside_a_try_catch_the_stylesheet_is_plain(self, banners):
        self.send(banners, "system.startup.completed")
        assert "} catch (e) {" in self.get(banners, "/static/loader.js").text
        assert "catch" not in self.get(banners, "/static/custom.css").text

    def test_disabling_it_withdraws_both_and_enabling_brings_them_back(self, banners):
        self.send(banners, "system.startup.completed")
        self.send(banners, "function.disable_started", subject="page_banners")
        assert self.get(banners, "/static/loader.js").text == ""
        assert self.get(banners, "/static/custom.css").text == ""
        self.send(banners, "function.enable_started", subject="page_banners")
        assert "owui:page_banners" in self.get(banners, "/static/custom.css").text

    def test_an_admin_edit_is_pushed_to_open_tabs(self, banners):
        self.send(banners, "config.banners.updated")
        assert banners.emitted == [("owui:page-banners", {})]

    def test_the_script_file_is_only_a_body_and_is_wrapped_once(self, banners):
        source = (self.FOLDER / "assets" / "loader.js").read_text()
        code = [line for line in source.splitlines() if line.strip() and not line.startswith("//")]
        assert not code[0].startswith("(function"), "owpp adds the wrapper; the file must not"
        assert "use strict" not in source  # the wrapper supplies it
        self.send(banners, "system.startup.completed")
        served = self.get(banners, "/static/loader.js").text
        assert served.count('"use strict"') == 1
        assert "try {\n// Page Banners" in served  # our wrapper, then the file's own header comment

    def test_it_can_sit_beside_better_banners(self):
        # The ids, classes and socket event are renamed: nothing of the original is left to collide.
        text = "".join(
            (self.FOLDER / f).read_text()
            for f in ("assets/loader.js", "assets/custom.css", "function.py")
        )
        for original in (
            "owui-better-banners",
            "obb-",
            "owui:better-banners",
            "__owuiBetterBanners",
        ):
            assert original not in text, original


def test_mcpo_sync_gets_its_sync_valves_from_the_jobs_library(event_class):
    valves = event_class(EXAMPLES / "mcpo_sync").Valves()
    assert valves.ENABLE is True
    assert (
        valves.SYNC_INTERVAL_MINUTES == 60
    )  # plugin.yaml: ${MCPO_SYNC_MINUTES:-60}, and the container has nothing set
    names = list(type(valves).model_fields)
    assert names[:6] == [
        "MCPO_BASE_URL",
        "MCPO_API_KEY",
        "INCLUDE_SERVERS",
        "EXCLUDE_SERVERS",
        "PRUNE_MANAGED",
        "REQUEST_TIMEOUT",
    ]
    assert names[-2:] == [
        "ENABLE",
        "SYNC_INTERVAL_MINUTES",
    ]  # the function's own valves first, then the library's


def test_the_interval_default_comes_from_the_manifest(event_class, tmp_path):
    folder = tmp_path / "mcpo_sync"
    shutil.copytree(EXAMPLES / "mcpo_sync", folder)
    manifest = (folder / "plugin.yaml").read_text()
    (folder / "plugin.yaml").write_text(manifest.replace("${MCPO_SYNC_MINUTES:-60}", "15"))
    assert event_class(folder).Valves().SYNC_INTERVAL_MINUTES == 15


def connection(entry_id, managed_by=None):
    info = {"id": entry_id, "name": entry_id}
    if managed_by:
        info["managed_by"] = managed_by
    return {"url": f"http://x/{entry_id}", "info": info}


def persisted(event_class, monkeypatch, existing, prune=True, synced=("mcpo-time",)):
    """Run the real persist() against a stand-in for Open-WebUI's config table."""
    import asyncio

    store = {"tool_server.connections": existing}

    class Config:
        @staticmethod
        async def get(key, default=None):
            return store.get(key, default)

        @staticmethod
        async def upsert(values):
            store.update(values)

    models = types.ModuleType("open_webui.models.config")
    models.Config = Config
    for name, module in (
        ("open_webui", types.ModuleType("open_webui")),
        ("open_webui.models", types.ModuleType("open_webui.models")),
        ("open_webui.models.config", models),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    event = event_class(EXAMPLES / "mcpo_sync")()
    event.valves.PRUNE_MANAGED = prune
    asyncio.run(event.persist([connection(i, event.owner) for i in synced]))
    return [c["info"]["id"] for c in store["tool_server.connections"]]


def test_entries_are_marked_with_the_functions_own_id(event_class):
    got = connections(event_class, EXAMPLES / "mcpo_sync")
    assert {c["info"]["managed_by"] for c in got.values()} == {"mcpo_sync"}


def test_it_prunes_only_what_it_wrote(event_class, monkeypatch):
    existing = [
        connection("mcpo-stale", "mcpo_sync"),  # written by this function, gone from mcpo
        connection("mcpo-time", "mcpo_sync"),  # written by this function, being replaced
        connection("manual"),  # hand-made: no marker
        connection("theirs", "some_other_function"),
    ]
    assert persisted(event_class, monkeypatch, existing) == ["manual", "theirs", "mcpo-time"]


def test_without_pruning_a_stale_entry_of_its_own_is_kept(event_class, monkeypatch):
    existing = [connection("mcpo-stale", "mcpo_sync"), connection("manual")]
    assert persisted(event_class, monkeypatch, existing, prune=False) == [
        "mcpo-stale",
        "manual",
        "mcpo-time",
    ]


def test_a_hand_made_entry_with_a_synced_id_is_replaced_not_duplicated(event_class, monkeypatch):
    existing = [connection("mcpo-time"), connection("manual")]  # someone typed it in by hand
    assert persisted(event_class, monkeypatch, existing) == ["manual", "mcpo-time"]


def test_it_will_not_sync_when_it_cannot_tell_which_function_it_is(event_class, caplog):
    import asyncio
    import logging

    event = event_class(EXAMPLES / "mcpo_sync", module_name="not_an_open_webui_module")()
    assert event.owner is None  # a None marker would match, and prune, every hand-made entry

    async def fetch_servers(*args):
        raise AssertionError("must not reach mcpo")

    event.fetch_servers = fetch_servers
    event.valves.MCPO_API_KEY = "key"
    with caplog.at_level(logging.WARNING):
        asyncio.run(event.sync())
    assert "cannot tell which function this is" in caplog.text


class TestExcalidrawSelfHosting:
    """EXCALIDRAW_ASSETS_URL makes the editor page load everything from a host you run."""

    FOLDER = EXAMPLES / "excalidraw"

    @pytest.fixture
    def page(self, monkeypatch):
        monkeypatch.delenv("EXCALIDRAW_ASSETS_URL", raising=False)
        module = types.ModuleType("function_excalidraw_" + "0" * 32)
        monkeypatch.setitem(sys.modules, module.__name__, module)
        exec(compile(bundle_function(self.FOLDER), "excalidraw.py", "exec"), module.__dict__)

        def render(url=None, token="s.1.abc"):
            if url is None:
                monkeypatch.delenv("EXCALIDRAW_ASSETS_URL", raising=False)
            else:
                monkeypatch.setenv("EXCALIDRAW_ASSETS_URL", url)
            return module._editor_page(token)

        return render

    def test_by_default_it_comes_from_esm_sh(self, page):
        html = page()
        assert 'type="importmap"' in html and "https://esm.sh/@excalidraw/excalidraw@0.18.0" in html
        assert "editor.js" not in html and "index.css" in html  # esm.sh's own stylesheet

    def test_an_empty_value_is_the_default_too(self, page):
        assert page("") == page()

    def test_self_hosted_the_page_has_nothing_from_the_internet_in_it(self, page):
        html = page("https://static.example.com/excalidraw")
        assert "esm.sh" not in html and "importmap" not in html
        assert 'href="https://static.example.com/excalidraw/index.css"' in html
        assert 'await import("https://static.example.com/excalidraw/editor.js")' in html
        assert 'window.EXCALIDRAW_ASSET_PATH = "https://static.example.com/excalidraw/";' in html

    def test_a_trailing_slash_does_not_double_up(self, page):
        assert "excalidraw//" not in page("https://static.example.com/excalidraw/")

    def test_a_path_on_the_same_host_works_too(self, page):
        html = page("/excalidraw-static")
        assert (
            'href="/excalidraw-static/index.css"' in html
            and 'import("/excalidraw-static/editor.js")' in html
        )

    @pytest.mark.parametrize("mode", [None, "https://static.example.com/x"])
    def test_the_token_and_version_are_filled_in_and_nothing_is_left_over(self, page, mode):
        import re

        html = page(mode, token="s.123.sig")
        assert 'const token = "s.123.sig";' in html
        assert not re.search(r"__[A-Z_]+__", html) and "<!--" not in html

    @pytest.mark.parametrize(
        "bad",
        [
            'https://x.example.com/"><script>alert(1)</script>',
            "https://x.example.com/a b",
            "https://x.example.com/a'b",
            "https://x.example.com/a\\b",
            "javascript:alert(1)",
            "ftp://x.example.com/a",
            "static.example.com/excalidraw",
            "https://x.example.com/<b>",
        ],
    )
    def test_a_value_that_could_break_out_of_the_page_is_refused(self, page, bad, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            html = page(bad)
        assert html == page()  # fell back to esm.sh
        assert "is not a plain http(s) URL or path" in caplog.text

    def test_the_setting_is_in_config_yaml_and_listed_by_check(self):
        from owpp.bundle import env_references

        assert env_references(self.FOLDER) == [("EXCALIDRAW_ASSETS_URL", "")]


class TestTheSelfHostBuildMatchesThePage:
    FOLDER = EXAMPLES / "excalidraw"

    def test_the_pinned_versions_are_the_ones_the_page_uses(self):
        import json
        import re

        package = json.loads((self.FOLDER / "self-host" / "package.json").read_text())[
            "dependencies"
        ]
        shared = (self.FOLDER / "shared.py").read_text()
        viewer = (self.FOLDER / "templates" / "viewer.html").read_text()
        assert package["@excalidraw/excalidraw"] == re.search(
            r'EXCALIDRAW_VERSION = "([^"]+)"', shared
        ).group(1)
        assert (
            package["react"]
            == package["react-dom"]
            == re.search(r"esm\.sh/react@([\d.]+)", viewer).group(1)
        )
        assert all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in package.values()), (
            "pin exact versions"
        )

    def test_the_built_module_exports_what_the_page_imports(self):
        import re

        viewer = (self.FOLDER / "templates" / "viewer.html").read_text()
        hosted = re.search(r"<!--hosted-->\nwindow.*?<!--/hosted-->", viewer, re.S).group(0)
        wanted = set(
            re.search(r"const \{([^}]*)\} =\s*await import", hosted)
            .group(1)
            .replace(" ", "")
            .split(",")
        )
        entry = (self.FOLDER / "self-host" / "editor.js").read_text()
        exported = set(re.search(r"export \{([^}]*)\}", entry).group(1).replace(" ", "").split(","))
        assert (
            wanted
            == exported
            == {"React", "createRoot", "Excalidraw", "MainMenu", "convertToExcalidrawElements"}
        )

    def test_the_build_is_reproducible_and_runnable(self):
        import os

        script = self.FOLDER / "self-host" / "build.sh"
        assert os.access(script, os.X_OK) and (self.FOLDER / "self-host" / "bun.lock").exists()
        text = script.read_text()
        assert (
            "set -euo pipefail" in text
            and "--frozen-lockfile" in text
            and "index.css" in text
            and "fonts" in text
        )
