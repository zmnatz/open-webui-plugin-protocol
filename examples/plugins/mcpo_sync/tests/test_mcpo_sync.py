"""mcpo Sync against a mock Open-WebUI and a stand-in mcpo proxy on localhost.
Run with `owpp test mcpo_sync`."""

import json
import logging
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROUTES = ["time", "filesystem", "other"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # What the plugin reads from the container; the stand-in mcpo is on localhost, never proxied.
    for name in ("MCPO_SYNC_MINUTES", "MCPO_SERVERS_ENABLED", "MCPO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def mcpo():
    """An mcpo proxy serving ROUTES, which wants the key "mcpo-key"."""
    state = {"routes": list(ROUTES), "requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["requests"] += 1
            if self.headers.get("Authorization") != "Bearer mcpo-key":
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"detail": "bad key"}')
                return
            links = "\n".join(f"- [{r}](/{r}/docs)" for r in state["routes"])
            body = json.dumps({"info": {"title": "mcpo", "description": f"Servers:\n{links}"}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()
    server.server_close()


def synced(owui):
    return {c["info"]["id"]: c for c in owui.config.get("tool_server.connections", [])}


def configure(owui, mcpo, **valves):
    owui.set_valves("mcpo_sync", MCPO_BASE_URL=mcpo["url"], MCPO_API_KEY="mcpo-key", **valves)


# ---- a sync end to end ------------------------------------------------------------------


def test_saving_the_valves_syncs_every_mcpo_server_as_a_tool_server(owui, plugin, mcpo):
    configure(owui, mcpo)
    got = synced(owui)
    assert sorted(got) == ["mcpo-filesystem", "mcpo-other", "mcpo-time"]
    time = got["mcpo-time"]
    assert time["url"] == f"{mcpo['url']}/time" and time["path"] == "openapi.json"
    assert time["auth_type"] == "bearer" and time["key"] == "mcpo-key"
    assert time["info"]["managed_by"] == "mcpo_sync"


def test_startup_syncs_too_and_a_server_gone_from_mcpo_is_pruned(owui, plugin, mcpo):
    configure(owui, mcpo)
    mcpo["routes"] = ["time"]
    owui.startup()
    assert list(synced(owui)) == ["mcpo-time"]


def test_include_and_exclude_pick_the_servers(owui, plugin, mcpo):
    configure(owui, mcpo, INCLUDE_SERVERS="time, other", EXCLUDE_SERVERS="other")
    assert list(synced(owui)) == ["mcpo-time"]


def test_the_key_can_come_from_the_container(owui, plugin, mcpo, monkeypatch):
    monkeypatch.setenv("MCPO_API_KEY", "mcpo-key")
    owui.set_valves("mcpo_sync", MCPO_BASE_URL=mcpo["url"])
    assert "mcpo-time" in synced(owui)


def test_without_a_key_it_does_not_call_mcpo(owui, plugin, mcpo, caplog):
    with caplog.at_level(logging.WARNING):
        owui.set_valves("mcpo_sync", MCPO_BASE_URL=mcpo["url"])
    assert mcpo["requests"] == 0 and synced(owui) == {}
    assert "MCPO_API_KEY not set" in caplog.text


def test_a_refused_key_is_logged_and_nothing_is_written(owui, plugin, mcpo, caplog):
    owui.config["tool_server.connections"] = [{"url": "x", "info": {"id": "manual"}}]
    with caplog.at_level(logging.ERROR):
        owui.set_valves("mcpo_sync", MCPO_BASE_URL=mcpo["url"], MCPO_API_KEY="wrong")
    assert "HTTP 401" in caplog.text
    assert list(synced(owui)) == ["manual"]


def test_switched_off_it_does_nothing(owui, plugin, mcpo):
    configure(owui, mcpo, ENABLE=False)
    owui.startup()
    assert mcpo["requests"] == 0


def test_another_functions_valves_do_not_trigger_it(owui, plugin, mcpo):
    owui.function_valves["mcpo_sync"] = {"MCPO_BASE_URL": mcpo["url"], "MCPO_API_KEY": "mcpo-key"}
    owui.emit("function.valves_updated", "someone_else")
    assert mcpo["requests"] == 0


def test_with_an_interval_it_schedules_a_repeat(owui, plugin, mcpo):
    import sys

    configure(owui, mcpo, SYNC_INTERVAL_MINUTES=5)
    loops = sys.modules["_plugin_jobs_mcpo_sync"].loops
    assert list(loops) == ["sync"] and not loops["sync"].done()
    owui.set_valves("mcpo_sync", SYNC_INTERVAL_MINUTES=0)
    assert loops == {}


# ---- what it writes -------------------------------------------------------------------


def connections(plugin, routes=ROUTES):
    built = plugin.instance.build_connections("http://mcpo:8000", "key", routes)
    return {c["info"]["id"]: c for c in built}


def test_it_applies_the_config_it_ships(plugin):
    got = connections(plugin)
    assert got["mcpo-time"]["info"]["name"] == "Clock"
    assert got["mcpo-time"]["info"]["description"] == "The current time and time zone conversions."
    assert got["mcpo-time"]["config"] == {"enable": True}
    assert got["mcpo-filesystem"]["config"] == {"enable": False}
    assert got["mcpo-filesystem"]["info"]["name"] == "filesystem (mcpo)"  # no name override
    # A server the config does not mention keeps every default.
    assert got["mcpo-other"]["info"]["name"] == "other (mcpo)"
    assert got["mcpo-other"]["info"]["description"] == "other MCP server via mcpo (OpenAPI)"
    assert got["mcpo-other"]["config"] == {"enable": True}


def test_the_default_enable_comes_from_the_container(plugin, monkeypatch):
    monkeypatch.setenv("MCPO_SERVERS_ENABLED", "false")
    assert connections(plugin)["mcpo-other"]["config"] == {"enable": False}


@pytest.fixture
def copy(tmp_path, plugin_dir):
    folder = tmp_path / "mcpo_sync"
    shutil.copytree(plugin_dir, folder, ignore=shutil.ignore_patterns("tests"))
    return folder


def test_a_changed_config_changes_what_is_synced(owui, copy):
    (copy / "config.yaml").write_text("enable: false\nservers:\n  other: {enable: true, name: Other}\n")
    got = connections(owui.load(copy))
    assert got["mcpo-time"]["config"] == {"enable": False}  # the global default flipped
    assert got["mcpo-other"]["config"] == {"enable": True}
    assert got["mcpo-other"]["info"]["name"] == "Other"


@pytest.mark.parametrize("config", ["servers: [time, filesystem]\n", "servers:\n  time: just-a-string\n"])
def test_a_malformed_servers_entry_is_ignored_not_fatal(owui, copy, config):
    (copy / "config.yaml").write_text(config)
    assert connections(owui.load(copy))["mcpo-time"]["info"]["name"] == "time (mcpo)"


def test_an_empty_config_leaves_the_defaults(owui, copy):
    (copy / "config.yaml").write_text("")
    got = connections(owui.load(copy))
    assert all(c["config"] == {"enable": True} for c in got.values())
    assert got["mcpo-time"]["info"]["name"] == "time (mcpo)"


# ---- valves ---------------------------------------------------------------------------


def test_it_gets_its_sync_valves_from_the_jobs_library(plugin):
    valves = plugin.valves
    assert valves.ENABLE is True
    assert valves.SYNC_INTERVAL_MINUTES == 60  # plugin.yaml: ${MCPO_SYNC_MINUTES:-60}, nothing set
    names = list(type(valves).model_fields)
    assert names[:6] == [
        "MCPO_BASE_URL",
        "MCPO_API_KEY",
        "INCLUDE_SERVERS",
        "EXCLUDE_SERVERS",
        "PRUNE_MANAGED",
        "REQUEST_TIMEOUT",
    ]
    assert names[-2:] == ["ENABLE", "SYNC_INTERVAL_MINUTES"]  # its own valves, then the library's


def test_the_interval_default_comes_from_the_container(owui, plugin_dir, monkeypatch):
    monkeypatch.setenv("MCPO_SYNC_MINUTES", "15")
    assert owui.load(plugin_dir).valves.SYNC_INTERVAL_MINUTES == 15


def test_the_interval_default_comes_from_the_manifest(owui, copy):
    manifest = (copy / "plugin.yaml").read_text()
    (copy / "plugin.yaml").write_text(manifest.replace("${MCPO_SYNC_MINUTES:-60}", "15"))
    assert owui.load(copy).valves.SYNC_INTERVAL_MINUTES == 15


# ---- pruning only its own -------------------------------------------------------------


def connection(entry_id, managed_by=None):
    info = {"id": entry_id, "name": entry_id}
    if managed_by:
        info["managed_by"] = managed_by
    return {"url": f"http://x/{entry_id}", "info": info}


def persisted(owui, plugin, existing, prune=True, synced_ids=("mcpo-time",)):
    owui.config["tool_server.connections"] = existing
    plugin.instance.valves.PRUNE_MANAGED = prune
    owui.run(plugin.instance.persist([connection(i, "mcpo_sync") for i in synced_ids]))
    return [c["info"]["id"] for c in owui.config["tool_server.connections"]]


def test_it_prunes_only_what_it_wrote(owui, plugin):
    existing = [
        connection("mcpo-stale", "mcpo_sync"),  # written by this function, gone from mcpo
        connection("mcpo-time", "mcpo_sync"),  # written by this function, being replaced
        connection("manual"),  # hand-made: no marker
        connection("theirs", "some_other_function"),
    ]
    assert persisted(owui, plugin, existing) == ["manual", "theirs", "mcpo-time"]


def test_without_pruning_a_stale_entry_of_its_own_is_kept(owui, plugin):
    existing = [connection("mcpo-stale", "mcpo_sync"), connection("manual")]
    assert persisted(owui, plugin, existing, prune=False) == ["mcpo-stale", "manual", "mcpo-time"]


def test_a_hand_made_entry_with_a_synced_id_is_replaced_not_duplicated(owui, plugin):
    existing = [connection("mcpo-time"), connection("manual")]  # someone typed it in by hand
    assert persisted(owui, plugin, existing) == ["manual", "mcpo-time"]


def test_it_will_not_sync_when_it_cannot_tell_which_function_it_is(owui, plugin_dir, caplog):
    # Loaded under a module name Open-WebUI would never use, so it has no function id.
    from owpp.bundle import bundle_function

    namespace = {"__name__": "not_an_open_webui_module"}
    exec(compile(bundle_function(plugin_dir), "mcpo_sync.py", "exec"), namespace)
    event = namespace["Event"]()
    assert event.owner is None  # a None marker would match, and prune, every hand-made entry

    async def fetch_servers(*args):
        raise AssertionError("must not reach mcpo")

    event.fetch_servers = fetch_servers
    event.valves.MCPO_API_KEY = "key"
    with caplog.at_level(logging.WARNING):
        owui.run(event.sync())
    assert "cannot tell which function this is" in caplog.text
