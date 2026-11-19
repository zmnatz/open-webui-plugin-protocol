# Excalidraw

A shared Excalidraw drawing per chat, opened in the Artifacts side panel.

| File | What it is |
|---|---|
| `function.py` | The Filter: serves the editor at `/excalidraw/view/<chat_id>` (mounted with the `routes` library) and appends it to replies so the panel opens. |
| `tool.py` | The Tool: lets the model show, read and change the drawing. |
| `shared.py` | In front of both: imports, constants, the versioned scene on top of the `chat_data` library (a drawing lives in its chat's metadata under `excalidraw`) and the element helpers. |
| `templates/viewer.html` | The editor page, embedded in the bundle and never served raw: `function.py` reads it with `plugin_template_text()` and renders it at `/excalidraw/view/<chat_id>` for a signed-in user who can write to the chat, filling in a short-lived token. |
| `config.yaml` | `assets_url: ${EXCALIDRAW_ASSETS_URL:-}`: where the editor's files are, read from the Open-WebUI container's environment. Empty means esm.sh. |
| `self-host/` | A pinned build script that produces the editor's files for you to host yourself (see below). Not part of the deployed plugin. |

The function is global and is the parent of the tool: enabling it installs the `excalidraw` Tool (public), disabling or deleting it removes it. By default the editor's code (React, Excalidraw) loads from esm.sh in the user's browser; to run with nothing from the internet, [host it yourself](#self-hosting-the-editor).

Every route requires a signed-in user (the `routes` library). The editor page opens only for a user who can write to the chat (`chat_id: WritableChat`). Its API is called from the sandboxed panel, which sends no cookies, so it takes a short-lived token that is tied to the chat and handed out only on that signed-in page load; there is no permanent link.

Valve (Admin Panel > Functions > Excalidraw): `SESSION_TOKEN_HOURS`.

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
- On a live Open-WebUI: open a chat and ask the model to draw something: the editor opens in the Artifacts panel and edits survive a reload. With `EXCALIDRAW_ASSETS_URL` set, the network tab shows every file coming from your host.

## Deploy

- Function type: **filter (global)**.
- `owpp deploy --only excalidraw --dry-run`, then without `--dry-run`. A single-plugin deploy never prunes.
