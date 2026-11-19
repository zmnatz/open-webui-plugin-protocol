# Page Banners

Shows the banners from Admin Panel > Settings > General > Banners in every chat, at the top of the page or right above the message input. Users can collapse them into a small pill and dismiss the dismissible ones, and both choices are remembered. Edits reach open tabs live.

**A variant of [Better Banners](https://github.com/Classic298/open-webui-plugins/tree/main/better-banners) by Classic298** (BSD-3-Clause; the notice is in `NOTICE.md`), reorganised as the example of the `assets/` folder. The behaviour is the same; what changed is where things live:

| File | What it is |
| --- | --- |
| `assets/loader.js` | The page-side script: a fragment of the shared `/static/loader.js`. A file, not a Python string. |
| `assets/custom.css` | The stylesheet: a fragment of the shared `/static/custom.css`. (Better Banners injects it from the script; here the protocol's own CSS file carries it.) |
| `function.py` | Only the server side: the valves, `asset_vars()` (the numbers the script is given) and the push to open tabs when the banners change. |
| `plugin.yaml` | The header and `include: [live_reload]`. |

`owpp` supplies the rest: the byte-identical Shared Assets Protocol blocks, the `assets` library (`class Event(PluginAssets)`), the function, strict mode and `try/catch` around the script that the protocol asks for (so `assets/loader.js` is only the body, with no wrapper of its own), the `__CONFIG__` placeholder filled from `asset_vars()`, and the marker comments. The element ids, CSS classes and socket event are renamed (`opb-`, `owui-page-banners`, `owui:page-banners`), so this and the original can be installed side by side.

Valves: `position` (`top` or `bottom`), `max_height_px`, `resync_interval_seconds`.

`include: [live_reload]` makes a code or valve change, or disabling the function, reach every container within a second. It needs Redis and Open-WebUI 0.11 or newer, and does nothing extra without Redis. Remove the line for a single container.

## Test

- `owpp check page_banners` bundles it exactly as the deploy does, compiles it and lists names it uses but never defines.
- `owpp bundle page_banners out.py` writes the deployed code to read or diff.
- On a live Open-WebUI: add a banner under Admin Panel > Settings > General, open a chat (it shows without a reload in an open tab), collapse and dismiss it, then disable the function and reload: the banners are gone and `/static/custom.css` no longer carries the `owui:page_banners` block.

## Deploy

- Function type: **event**.
- `owpp deploy --only page_banners --dry-run`, then without `--dry-run`. A single-plugin deploy never prunes.
