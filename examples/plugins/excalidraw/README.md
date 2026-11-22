# Excalidraw

A shared Excalidraw drawing per chat, opened in the Artifacts side panel.

[Excalidraw](https://excalidraw.com/) is an open-source, browser-based whiteboard for sketching diagrams that look hand-drawn: boxes, arrows, text and freehand strokes, stored as a scene you can share or keep in the browser. The editor is published as a [React component](https://github.com/excalidraw/excalidraw) with [documentation](https://docs.excalidraw.com/); this plugin embeds it in Open-WebUI's Artifacts panel and keeps one scene per chat.

| File | What it is |
|---|---|
| `function.py` | The Filter: serves the editor at `/excalidraw/view/<chat_id>` (mounted with the `routes` library) and appends it to replies so the panel opens. |
| `tool.py` | The Tool: lets the model show, read and change the drawing. |
| `shared.py` | In front of both, imported with `from shared import ...`: constants, the versioned scene on top of the `chat_data` library (a drawing lives in its chat's metadata under `excalidraw`) and the element helpers. |
| `templates/viewer.html` | The editor page, embedded in the bundle and never served raw: `function.py` reads it with `plugin_template_text()` and renders it at `/excalidraw/view/<chat_id>` for a signed-in user who can write to the chat, filling in a short-lived token. |
| `config.yaml` | `assets_url: ${EXCALIDRAW_ASSETS_URL:-}`: where the editor's files are, read from the Open-WebUI container's environment. Empty means esm.sh. |
| `self-host/` | A pinned build script that produces the editor's files for you to host yourself (see below). Not part of the deployed plugin. |

The function is global and is the parent of the tool: enabling it installs the `excalidraw` Tool (public), disabling or deleting it removes it. By default the editor's code (React, Excalidraw) loads from esm.sh in the user's browser; to run with nothing from the internet, [host it yourself](#self-hosting-the-editor).

Every route requires a signed-in user (the `routes` library). The editor page opens only for a user who can write to the chat (`chat_id: WritableChat`). Its API is called from the sandboxed panel, so it does not rely on cookies: it takes a short-lived token that is tied to the chat and handed out only on that signed-in page load; there is no permanent link. The page itself needs the session, which inside the panel means the setting [below](#requirement-iframe-sandbox-allow-same-origin) ([libraries](../../../docs/libraries.md#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin) explains why for any plugin).

Valve (Admin Panel > Functions > Excalidraw): `SESSION_TOKEN_HOURS`.

## Requirement: iframe Sandbox Allow Same Origin

**On a default Open-WebUI the editor answers 401 ("Sign in to Open-WebUI first.") inside the panel.** The Artifacts panel is a sandboxed iframe. Unless the user's **iframe Sandbox Allow Same Origin** setting is on, the panel sends no cookies at all, so the editor page (not only its API) cannot tell who is signed in. Open-WebUI v0.13.4 ships with the setting off. Found on a real Open-WebUI by the [screenshot run](../../../docs/screenshots.md#what-it-found).

To make it work, turn the setting on:

- for everyone: **Admin Settings > General > Default Interface Settings**, or the container variable `DEFAULT_INTERFACE_SETTINGS='{"iframeSandboxAllowSameOrigin": true}'`. A user's own setting still wins;
- or for one user: **Settings > Interface > iframe Sandbox Allow Same Origin**.

**Know what it costs.** The setting applies to every artifact, not only this one. With it on, the script in any HTML a model produces runs with Open-WebUI's own origin, so it can read the sign-in token Open-WebUI keeps in the browser and call the API as that user. This is an Open-WebUI permission that no plugin can narrow. **Use this plugin only on an instance where you trust what the models put into artifacts.**

It is the same setting, and the same cost, as [Inline Visualizer](../inline_visualizer/README.md) (its upstream README says so too): an instance that already runs it for live rendering has already accepted it, and Excalidraw adds nothing to it.

The plugin keeps the requirement on purpose rather than working around it ([issue #6](https://github.com/zmnatz/open-webui-plugin-protocol/issues/6)). A token in the iframe's address would be written into the chat's stored HTML and would have expired by the time an old chat is reopened; a public page that asks the parent window for a credential needs Open-WebUI to answer, which it does not today.

## Self-hosting the editor

Out of the box the user's browser fetches the editor from [esm.sh](https://esm.sh), a public CDN: it needs internet access, trusts esm.sh to serve the code (there is no integrity check), and tells esm.sh the user's IP and the Open-WebUI origin. To load everything from a host you run instead, so the page needs nothing from the internet:

1. **Build** the files (needs [bun](https://bun.sh) and network access once; the versions are pinned in `self-host/package.json` and `bun.lock`):

   ```sh
   cd self-host && ./build.sh /srv/excalidraw-assets
   ```

   This writes `editor.js` (React, ReactDOM and Excalidraw in one module), the code-split chunks it loads on demand (languages, diagram conversion), `index.css` and Excalidraw's fonts, about 21 MB in all (mostly one CJK font, `fonts/Xiaolai`, which you can delete: those characters then use system fonts).

2. **Serve** that folder from any static web server, **with an `Access-Control-Allow-Origin: *` header**. The editor runs in Open-WebUI's sandboxed Artifacts iframe, whose origin is opaque, so its module and font requests are cross-origin. For nginx:

   ```nginx
   location /excalidraw-assets/ {
       alias /srv/excalidraw-assets/;
       add_header Access-Control-Allow-Origin "*" always;
   }
   ```

3. **Tell the plugin** where it is, with an environment variable on the Open-WebUI container: `EXCALIDRAW_ASSETS_URL=https://static.example.com/excalidraw-assets` (or a path such as `/excalidraw-assets` if it is served from the same host). It is read when the plugin loads, not when it is deployed, and `owpp check excalidraw` lists it.

The page then contains no esm.sh at all. To check, open the editor with the browser's network tab showing, or block `esm.sh` and confirm it still loads. A value that is not a plain `http(s)://` URL or path (quotes, spaces, angle brackets) is ignored with a warning and the page falls back to esm.sh.

This host is outside Open-WebUI, so it is yours to keep up: its files are public (they are the editor's code, with nothing of anyone's in them), and to upgrade Excalidraw you change `EXCALIDRAW_VERSION` in `shared.py` and the versions in `self-host/package.json` together (a test checks they agree), rebuild, and replace the folder.

## Test

- `owpp check excalidraw` bundles it exactly as the deploy does, compiles it and lists names it uses but never defines (the function and any tool it embeds).
- `owpp bundle excalidraw out.py` writes the deployed code to read or diff.
- `owpp test excalidraw` runs `tests/` against a mock Open-WebUI (docs/testing.md).
- On a live Open-WebUI, with [iframe Sandbox Allow Same Origin](#requirement-iframe-sandbox-allow-same-origin) on: open a chat and ask the model to draw something: the editor opens in the Artifacts panel and edits survive a reload. With `EXCALIDRAW_ASSETS_URL` set, the network tab shows every file coming from your host.

## Deploy

- Function type: **filter (global)**.
- `owpp deploy --only excalidraw --dry-run`, then without `--dry-run`. A single-plugin deploy never prunes.
