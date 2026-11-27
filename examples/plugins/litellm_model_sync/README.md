# LiteLLM Model Sync

An **event** function that reads each [LiteLLM](https://docs.litellm.ai/) gateway's `/model/info` and writes what it learns into Open-WebUI's model configs. A gateway knows each model's friendly name, provider, family and capabilities; Open-WebUI only sees ids. After a sync:

- each model has the gateway's **display name**, and tags for its **vendor** and **family** (optionally its capabilities too);
- its **vision** capability is set as the gateway states it;
- **non-chat models** (embeddings, decision, transcription) are hidden from the model selector but stay enabled;
- every config it wrote has a **public read grant** (Open-WebUI's `user:*`), so users who are not admins can pick the model.

It walks the OpenAI connections configured in Open-WebUI, asks each one for `/model/info` (the connection URL minus `/v1`, with the connection's key) and skips any that are not LiteLLM. The config id is the one Open-WebUI gives the connection's model (`prefix.name`), so the config overrides it.

Like [mcpo Sync](../mcpo_sync), it uses the scheduled-sync pattern: `class Event(PluginScheduledSync)` from the `jobs` library runs `sync()` at startup, when the function is enabled or its valves are saved, and then every `SYNC_INTERVAL_MINUTES` (default 60, on one worker; 0 turns the repeat off). The interval's default comes from `LITELLM_SYNC_MINUTES` in the Open-WebUI container's environment (`jobs:` in `plugin.yaml`).

**What it never touches.** It changes and deletes only configs it wrote (marked `managed_by` with this function's id), plus configs nobody named (still the raw id, which Open-WebUI creates when a model is merely toggled). A config someone renamed is left alone unless `ADOPT_EXISTING` is on. It prunes a config only when that config's own connection answered with models in this run, so a gateway that is down or returns nothing deletes nothing. Tags a person added are kept; only the ones it wrote are replaced.

Valves: `INFO_PATH`, `INCLUDE_CONNECTIONS`, `SET_VISION`, `TAG_VENDOR`, `TAG_FAMILY`, `TAG_CAPABILITIES`, `NATIVE_FUNCTION_CALLING` (off by default: it changes how tool calls are made), `PRUNE_MISSING`, `PUBLIC_READ`, `ADOPT_EXISTING`, `HIDE_MODES`, `REQUEST_TIMEOUT`, `SYNC_INTERVAL_MINUTES`, `ENABLE`.

**Moving from another sync.** Configs an earlier sync wrote carry its marker. Name it in `plugin.yaml` (`jobs: adopt_markers: [litellm-model-sync]`) and deploy: they are then updated, take this function's marker, and are pruned like its own ([plugin format](../../../docs/plugin-format.md#jobs)).

## Test

- `owpp check litellm_model_sync` bundles it exactly as the deploy does, compiles it and lists names it uses but never defines.
- `owpp bundle litellm_model_sync out.py` writes the deployed code to read or diff.
- `owpp test litellm_model_sync` runs `tests/` against the real Open-WebUI, in process and a stand-in LiteLLM gateway (docs/testing.md).
- On a live Open-WebUI: with an OpenAI connection to a LiteLLM gateway, save the valves. The log shows `LiteLLM Model Sync: N model config(s) written, M removed`, Admin Settings > Models shows the display names and tags, and a user who is not an admin sees the models in the selector.

## Deploy

- Function type: **event**.
- `owpp deploy --only litellm_model_sync --dry-run`, then without `--dry-run`. A single-plugin deploy never prunes.
