# Stale Data Dashboard

An event function that serves a read-only page at `/stale-data` listing chats, notes and files older than `STALE_THRESHOLD_HOURS` (default 1), with owner, size and the chats a file is attached to. Adapted from a hand-written flat file; it now mounts through the `routes` library (`include: [routes]`), so a saved edit replaces its own route and a changed `DASHBOARD_PATH` drops the old one.

It is **admin-only**, and that is marked on the route, not coded: the handler takes `user: PluginAdmin`, which the `routes` library enforces, because the page lists every user's chat titles, notes and file names. Without a session it answers 401, to a signed-in non-admin 403, and 404 once the function is disabled. There is no valve to open it up, and no public option at all. The earlier flat file had no check.

Valves: `DASHBOARD_PATH`, `STALE_THRESHOLD_HOURS`. Not a global function: event functions do not use `global`.

## Test

- `owpp check stale_data` bundles it exactly as the deploy does, compiles it and lists names it uses but never defines (the function and any tool it embeds).
- `owpp bundle stale_data out.py` writes the deployed code to read or diff.
- `owpp test stale_data` runs `tests/` against a mock Open-WebUI (docs/testing.md).
- On a live Open-WebUI: open `/stale-data` as an admin (the tables fill in), then in a private window (the sign-in page), and as a user who is not an admin (403).

## Deploy

- Function type: **event**.
- `owpp deploy --only stale_data --dry-run`, then without `--dry-run`. A single-plugin deploy never prunes.
