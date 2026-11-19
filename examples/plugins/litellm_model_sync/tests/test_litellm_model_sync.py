"""LiteLLM Model Sync against a mock Open-WebUI and a stand-in LiteLLM gateway on localhost.
Run with `owpp test litellm_model_sync`."""

import copy
import json
import logging
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

PUBLIC = {"principal_type": "user", "principal_id": "*", "permission": "read"}


def deployment(name, display=None, provider="openai", family=None, mode="chat", order=None, **caps):
    """One row of LiteLLM's /model/info: a deployment of `name`."""
    return {
        "model_name": name,
        "litellm_params": {"order": order} if order is not None else {},
        "model_info": {
            "display_name": display,
            "litellm_provider": provider,
            "model_family": family,
            "mode": mode,
            "capabilities": {k: v for k, v in caps.items()},
        },
    }


MODELS = [
    deployment("gpt-fast", "GPT Fast", family="gpt", vision=True, tools=True),
    deployment("embed", "Embeddings", mode="embedding"),
    # Served by two providers: the lower order names it, and a capability needs both tiers.
    deployment("smart", "Smart", provider="anthropic", family="claude", order=1, vision=True),
    deployment("smart", "Smart (backup)", provider="openai", family="gpt", order=2, vision=False),
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("LITELLM_SYNC_MINUTES", raising=False)
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def gateway():
    """A LiteLLM gateway serving MODELS at /model/info, which wants the key "gw-key"."""
    state = {"models": copy.deepcopy(MODELS), "requests": 0, "status": 200}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state["requests"] += 1
            if self.path != "/model/info" or self.headers.get("Authorization") != "Bearer gw-key":
                self.send_response(404 if self.path != "/model/info" else 401)
                self.end_headers()
                return
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": state["models"]}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/v1"
    yield state
    server.shutdown()
    server.server_close()


@pytest.fixture
def connected(owui, gateway):
    """Open-WebUI has one OpenAI connection: the gateway, with prefix "gw"."""
    owui.config.update(
        {
            "openai.enable": True,
            "openai.api_base_urls": [gateway["url"]],
            "openai.api_keys": ["gw-key"],
            "openai.api_configs": {"0": {"enable": True, "prefix_id": "gw"}},
        }
    )
    return gateway


def sync(owui, **valves):
    """Save the valves: that runs a sync."""
    owui.set_valves("litellm_model_sync", SYNC_INTERVAL_MINUTES=0, **valves)


def tags(row):
    return [t["name"] for t in row.meta.model_dump()["tags"]]


# ---- what it writes ---------------------------------------------------------------------


def test_each_model_gets_its_display_name_tags_and_vision(owui, plugin, connected):
    """Every model the gateway serves gets a model config under the id Open-WebUI gives it
    (prefix.name): its display name, vendor and family tags, the vision capability, and a
    public read grant so users can pick it.

    By hand: point an OpenAI connection at a LiteLLM gateway and save this function's valves.
    Admin Settings > Models shows the friendly names and tags, and a user who is not an admin
    sees the models in the selector.
    """
    sync(owui)
    fast = owui.models["gw.gpt-fast"]
    assert fast.name == "GPT Fast"
    assert tags(fast) == ["openai", "gpt"]
    assert fast.meta.model_dump()["capabilities"] == {"vision": True}
    assert fast.access_grants == [PUBLIC]
    assert fast.meta.model_dump()["managed_by"] == "litellm_model_sync"
    assert fast.user_id == owui.admin.id


def test_non_chat_models_are_hidden_but_stay_usable(owui, plugin, connected):
    """Embedding (and decision, transcription) models are hidden from the model selector, but
    stay enabled, so Open-WebUI can still call them.

    By hand: after a sync, the embedding model is marked hidden in Admin Settings > Models and
    is missing from the chat's model selector, but it is still switched on.
    """
    sync(owui)
    embed = owui.models["gw.embed"]
    assert embed.meta.model_dump()["hidden"] is True and embed.is_active


def test_a_model_on_two_providers_is_named_by_the_first_and_needs_both_for_a_capability(
    owui, plugin, connected
):
    """A name served by several deployments is named by the one tried first (the lowest
    order), and a capability counts only if every deployment has it.

    By hand: give a model two deployments with different orders in LiteLLM, one with vision
    and one without. After a sync it carries the first one's name and tags, and no vision.
    """
    sync(owui)
    smart = owui.models["gw.smart"]
    assert smart.name == "Smart" and tags(smart) == ["anthropic", "claude"]
    assert smart.meta.model_dump()["capabilities"] == {"vision": False}


def test_native_function_calling_is_only_set_when_asked(owui, plugin, connected):
    """NATIVE_FUNCTION_CALLING sets native tool calling on models that state tool support.
    It is off by default, because it changes how tool calls are made.

    By hand: turn NATIVE_FUNCTION_CALLING on and save. GPT Fast's advanced parameters show
    function calling: native; the others are unchanged.
    """
    sync(owui)
    assert "function_calling" not in owui.models["gw.gpt-fast"].params.model_dump()
    sync(owui, NATIVE_FUNCTION_CALLING=True)
    assert owui.models["gw.gpt-fast"].params.model_dump()["function_calling"] == "native"
    assert "function_calling" not in owui.models["gw.smart"].params.model_dump()


def test_tags_a_person_added_are_kept(owui, plugin, connected):
    """Tags someone added by hand survive a sync; only the tags it wrote are replaced.

    By hand: add a tag to a synced model in Admin Settings > Models, then save this
    function's valves. Your tag is still there beside the synced ones.
    """
    sync(owui)
    fast = owui.models["gw.gpt-fast"]
    meta = fast.meta.model_dump()
    meta["tags"] = meta["tags"] + [{"name": "favourite"}]
    fast.meta = type(fast.meta).model_validate(meta)
    connected["models"][0]["model_info"]["model_family"] = "gpt-5"
    sync(owui)
    assert tags(owui.models["gw.gpt-fast"]) == ["favourite", "openai", "gpt-5"]


def test_capability_tags_are_optional(owui, plugin, connected):
    """TAG_CAPABILITIES also tags vision, tools and reasoning where a model states them.

    By hand: turn TAG_CAPABILITIES on and save. GPT Fast is tagged vision and tools too.
    """
    sync(owui, TAG_CAPABILITIES=True)
    assert tags(owui.models["gw.gpt-fast"]) == ["openai", "gpt", "vision", "tools"]


# ---- what it leaves alone ---------------------------------------------------------------


def test_a_config_someone_named_by_hand_is_left_alone(owui, plugin, connected, caplog):
    """A model config someone renamed by hand is not overwritten, unless ADOPT_EXISTING is on.
    A config nobody named (still the raw id) is taken over either way.

    By hand: rename a model in Admin Settings > Models, then save this function's valves.
    Your name stays, and the log says it was left alone. Turn ADOPT_EXISTING on and save: it
    gets the gateway's name.
    """
    sync(owui)
    owui.models["gw.gpt-fast"].name = "My GPT"
    owui.models["gw.gpt-fast"].meta = type(owui.models["gw.gpt-fast"].meta)()  # not managed
    with caplog.at_level(logging.INFO):
        sync(owui)
    assert owui.models["gw.gpt-fast"].name == "My GPT"
    assert "leaving hand-edited config gw.gpt-fast" in caplog.text
    sync(owui, ADOPT_EXISTING=True)
    assert owui.models["gw.gpt-fast"].name == "GPT Fast"


def test_a_model_gone_from_the_gateway_is_pruned(owui, plugin, connected):
    """A config it wrote whose model the gateway no longer serves is deleted; configs it did
    not write are not.

    By hand: remove a model from LiteLLM's config, restart it, and save this function's
    valves. That model's config is gone from Admin Settings > Models; one you made is kept.
    """
    sync(owui)
    connected["models"] = [m for m in MODELS if m["model_name"] != "embed"]
    sync(owui)
    assert "gw.embed" not in owui.models and "gw.gpt-fast" in owui.models


def test_an_empty_or_failed_answer_deletes_nothing(owui, plugin, connected):
    """An empty list, or an error from the gateway, is not taken to mean the models are gone.

    By hand: stop LiteLLM and save this function's valves. Every synced model is still in
    Admin Settings > Models, and the log says the gateway did not answer.
    """
    sync(owui)
    before = set(owui.models)
    connected["models"] = []
    sync(owui)
    connected["status"] = 500
    sync(owui)
    assert set(owui.models) == before


def test_connections_that_are_not_litellm_are_skipped(owui, plugin, connected):
    """A connection that does not answer /model/info (say, OpenAI itself) is skipped quietly,
    and INCLUDE_CONNECTIONS limits the sync to the connections it names.

    By hand: with a second OpenAI connection that is not LiteLLM, save the valves. Only the
    gateway's models are written, and the log notes the other one has no /model/info.
    """
    owui.config["openai.api_base_urls"] = [connected["url"], "http://127.0.0.1:9/v1"]
    owui.config["openai.api_keys"] = ["gw-key", ""]
    sync(owui)
    assert "gw.gpt-fast" in owui.models
    owui.models.clear()
    sync(owui, INCLUDE_CONNECTIONS="127.0.0.1:9")
    assert owui.models == {}


def test_adopted_markers_count_as_its_own(owui, tmp_path, plugin_dir, connected):
    """With plugin.yaml's jobs: adopt_markers naming an earlier sync's marker, configs that
    sync wrote are updated and pruned like this function's own.

    By hand: on an instance an earlier sync wrote to (marked, say, litellm-model-sync), add
    `adopt_markers: [litellm-model-sync]` under `jobs:` in plugin.yaml and deploy. Its configs
    take this function's marker, and those the gateway no longer serves are removed.
    """

    def load(adopt: bool):
        folder = tmp_path / ("adopting" if adopt else "plain") / "litellm_model_sync"
        shutil.copytree(plugin_dir, folder, ignore=shutil.ignore_patterns("tests"))
        if adopt:
            manifest = folder / "plugin.yaml"
            text = manifest.read_text().replace(
                "jobs:\n", "jobs:\n  adopt_markers: [litellm-model-sync]\n"
            )
            manifest.write_text(text)
        owui.load(folder)

    load(adopt=False)
    sync(owui)
    for row in owui.models.values():
        meta = row.meta.model_dump()
        row.meta = type(row.meta).model_validate({**meta, "managed_by": "litellm-model-sync"})
    connected["models"] = [m for m in MODELS if m["model_name"] != "embed"]
    sync(owui)  # not adopted: the old configs are left as they are
    assert "gw.embed" in owui.models
    load(adopt=True)
    sync(owui)
    assert "gw.embed" not in owui.models
    assert owui.models["gw.gpt-fast"].meta.model_dump()["managed_by"] == "litellm_model_sync"


# ---- valves -----------------------------------------------------------------------------


def test_it_gets_its_sync_valves_from_the_jobs_library(plugin):
    """ENABLE and SYNC_INTERVAL_MINUTES come from the jobs library, after its own valves, and
    the interval defaults to 60 minutes (LITELLM_SYNC_MINUTES unset).

    By hand: open the function's valves. ENABLE and SYNC_INTERVAL_MINUTES (60) are last.
    """
    names = list(type(plugin.valves).model_fields)
    assert names[-2:] == ["ENABLE", "SYNC_INTERVAL_MINUTES"]
    assert plugin.valves.SYNC_INTERVAL_MINUTES == 60


def test_switched_off_it_does_not_call_the_gateway(owui, plugin, connected):
    """With ENABLE off, saving the valves does not call the gateway.

    By hand: turn ENABLE off and save. LiteLLM's log shows no /model/info request.
    """
    owui.set_valves("litellm_model_sync", ENABLE=False, SYNC_INTERVAL_MINUTES=0)
    assert connected["requests"] == 0 and owui.models == {}
