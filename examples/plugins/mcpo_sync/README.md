# mcpo Sync

An **event** function that writes the servers an [mcpo](https://github.com/open-webui/mcpo) proxy serves into Open-WebUI as OpenAPI tool servers, so the tool list follows mcpo's config instead of being typed into the admin UI.

It shows the scheduled-sync pattern: `class Event(PluginScheduledSync)` from the `jobs` library (the `jobs:` section of `plugin.yaml`) runs `sync()` at startup, when the function is enabled or its valves are saved, and then every `SYNC_INTERVAL_MINUTES` (default 60, on one worker; 0 turns the repeat off). It only touches tool-server entries it created (marked `managed_by` with this function's own id) and removes stale ones when `PRUNE_MANAGED` is on.

Per-server overrides ship in `config.yaml`, read with `plugin_config()` (the `config` library, added automatically by the file): a display `name`, a `description`, or `enable: false` for each server, and a global `enable`. They are structured data, so they are a file rather than valves; change them and redeploy.

Two settings can come from the Open-WebUI container's environment, written as templates in the files: `MCPO_SYNC_MINUTES` (the interval valve's default, `jobs:` in `plugin.yaml`, default 60) and `MCPO_SERVERS_ENABLED` (`enable:` in `config.yaml`, default `true`). They are read when the plugin loads inside the container, never when it is deployed. `owpp check mcpo_sync` lists them.

Valves: `MCPO_BASE_URL` (default `http://mcpo:8000`), `MCPO_API_KEY` (empty uses the container's `MCPO_API_KEY` environment variable), `INCLUDE_SERVERS`, `EXCLUDE_SERVERS`, `PRUNE_MANAGED`, `REQUEST_TIMEOUT`, `SYNC_INTERVAL_MINUTES`, `ENABLE`.

## Test

- `owpp check mcpo_sync` bundles it exactly as the deploy does, compiles it and lists names it uses but never defines (the function and any tool it embeds).
- `owpp bundle mcpo_sync out.py` writes the deployed code to read or diff.
- `owpp test mcpo_sync` runs `tests/` against a mock Open-WebUI (docs/testing.md).
- On a live Open-WebUI: save the valves, then Admin Settings > Integrations > External Tool Servers lists the mcpo servers, and the log shows `mcpo Sync: N server(s) synced`.

## Deploy

- Function type: **event**.
- `owpp deploy --only mcpo_sync --dry-run`, then without `--dry-run`. A single-plugin deploy never prunes.
