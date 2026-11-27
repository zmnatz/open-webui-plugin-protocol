**Adapted from [Theme Designer Pro](https://github.com/silentoplayz/theme-designer-pro-presets/tree/34345eaffb8678ddfd38b45d7bc173f5b0d27132) 1.23.0 and its Launcher 2.1.2 by G30**, under the MIT licence (the notice is in [`NOTICE.md`](../../../NOTICE.md)). It does what the original does, with one change so that its OLED mode keeps working on Open-WebUI v0.13.5 ([below](#what-changed-for-open-webui-v0135)); the rest of what changed is where the code lives and what owpp does for it, all listed below in [How owpp broke it down](#how-owpp-broke-it-down).

# Theme Designer Pro

Themes the whole of Open-WebUI for every user: a palette in Open-WebUI's own grey steps, accents, gradients, animated Canvas FX backgrounds, frosted glass surfaces, pictures behind pages and on the sign-in page, and custom CSS, designed in a page of its own at `/api/v1/theme-designer`. Saves reach every open page live, and the theme is there from the first paint, the sign-in page included. With **Allow Personal Themes** on, each user designs a theme of their own that only they see.

Enabling the function installs two things, and disabling it removes them:

- the **Theme Designer Pro Launcher** tool: in a chat, it builds a theme someone describes ("make my chat a koi pond") and shows it as a card with a live preview and Apply, or opens the designer inside the chat;
- the **theme-designer-pro** skill, with its references and templates, which tells the chat model how to design a theme and write a new animation.

It is the largest example in this repository, chosen for that: a 1.3 MB, 20,900-line single file, kept working exactly as its author wrote it while it was broken into the plugin format.

## Valves

The function's, in Admin Panel > Functions > Theme Designer Pro > Valves. Every one has a test (`tests/`), named in the [test catalogue](../../../docs/testing/writing.md#describe-every-test).

| Valve | Default | What it does |
| --- | --- | --- |
| `enable_canvas_fx` | on | Canvas FX animations; off hides the tab and serves every theme without its script. |
| `calm_chat_column` | off | Animations fade behind the chat, each by its own Center Calm. |
| `enable_custom_css` | on | The Style Overrides tab. |
| `enable_gradient_builder` | on | The Gradient tab. |
| `enable_ai_consultant` | on | The AI Consultant: a description in words, a palette from a model on the instance. |
| `enable_theme_update_checks` | on | Update checks for installed themes. |
| `enable_community_themes` | on | The Community Themes browser. |
| `enable_auth_page_theming` | on | Theming the sign-in pages; off serves every sign-in flag off. |
| `draft_mode_default` | off | The designer opens in Draft mode. |
| `show_in_admin_settings` | on | A Themes tab in the Admin part of Settings. |
| `show_in_admin_panel` | off | A Themes page in the Admin Panel's top bar. |
| `allow_personal_themes` | on | A personal theme for every user, from their own Settings. |
| `auto_sync` | on | Skip the Selective Sync dialog. |
| `enable_canvas_api_access` | off | Gives every animation each viewer's token. Leave it off unless you audited every script. |
| `enable_url_import` | on | The Load from URL controls. |
| `allowed_import_domains` | empty | Domains the designer may fetch from; empty is any. |
| `designer_url` | `/api/v1/theme-designer` | Where the designer is served (kept under `/api/v1`). |
| `ai_consultant_model` | empty | The model the AI Consultant asks; empty is the task model. |

The Launcher's, in Workspace > Tools > Theme Designer Pro Launcher > Valves: `designer_url` (must match the function's), `background_animations`, `model_written_animations`, `model_written_css`, `canvas_catalog_url`, `iframe_height`, `iframe_scale`.

[`config.yaml`](config.yaml) has three limits of one worker, each settable from the Open-WebUI container's environment: `TDP_SSE_MAX_CLIENTS` (8192 live-update streams), `TDP_SSE_HEARTBEAT_SECONDS` (15) and `TDP_CONSULT_INTERVAL_SECONDS` (3). The defaults are the original's numbers.

## Requirements

- Open-WebUI 0.13.4 or newer (the original's `required_open_webui_version`). Checked on v0.13.5, with the change [below](#what-changed-for-open-webui-v0135).
- **iframe Sandbox Allow Same Origin**, for the Launcher's Apply and for the designer inside a chat: without it, the chat's frame has no origin and the browser sends the designer no sign-in. `plugin.yaml` says so (`requires:`), and `owpp deploy` warns when it is off. Turn it on per user under Settings > Interface, or for everyone under Admin Settings > General > Default Interface Settings. It applies to every artifact, not only this plugin's: HTML a model writes then runs with Open-WebUI's origin and can act as the user, so turn it on only where what models put into artifacts is trusted ([the cost, in full](../../../docs/libraries.md#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin)).
- Live updates stream from the function: behind nginx, `proxy_buffering off;` for `/api/v1/theme-designer/events`.

## How owpp broke it down

This part is written for G30, the original's author, and for anyone adapting a function this size: what we did to your code, why, and how we checked that it still does what yours does.

### The short version

Your function is three things in one file: the Python that runs on the server, about 1.1 MB of HTML, CSS and JavaScript that it serves, and two copies of other people's code (the Shared Assets Protocol and its live-reload add-on). owpp keeps each kind in its own place:

| | The original | This plugin |
| --- | --- | --- |
| Python | about 3,900 of its 20,872 lines, between the strings | [`function.py`](function.py): 3,648 lines, only Python |
| The designer page | one 943 KB raw string in `_build_html` | [`templates/designer/`](templates/designer): 30 files, the page an outline of them |
| The bootloader, the Settings tab, the Admin Panel page | three class attributes, 156 KB | [`templates/bootloader.js`](templates/bootloader.js), [`settings_tab.js`](templates/settings_tab.js), [`admin_page.js`](templates/admin_page.js) |
| The Launcher | a 1,134-line file with its HTML in Python strings | [`tool.py`](tool.py) (735 lines) and [`templates/launcher/`](templates/launcher) |
| The signed Apply link | written twice, once in each file | [`shared.py`](shared.py), bundled into both |
| The header | a docstring in each file | [`plugin.yaml`](plugin.yaml) |
| Shared Assets Protocol, live reload | pasted in (403 lines) | owpp's copies, by `include:` |
| Sign-in checks, route insertion, stale-route cleanup | written by hand | owpp's `routes` library |
| `event()` | one 160-line method of `if` checks | `@on` handlers |
| The skill | [`skills/theme-designer-pro/`](skills/theme-designer-pro) | the same folder, one line added |

Nothing in `templates/` was edited: every file is a slice of your strings, cut at your own section boundaries, and [`adapt/split_upstream.py`](adapt/split_upstream.py) cuts them again from your repository, byte for byte. The Python kept your code wherever owpp had nothing to replace it with, comments included.

### Where each part of your file went

Line numbers are those of [`event-function/theme_designer_pro_event.py`](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py) at 1.23.0 (commit `34345ea`, one fix after the release).

| Your lines | What | Here |
| --- | --- | --- |
| [1-10](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L1-L10) | the header | `plugin.yaml`, `function:` |
| [31-237](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L31-L237) | live reload (`RELOAD_IMPL_VERSION = 2`) | `include: [live_reload]`: owpp's copy, the same version (below) |
| [238-433](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L238-L433) | the shared asset block | `include: [shared_assets]`: byte-identical to yours |
| [437-534](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L437-L534) | `Valves` | `function.py`, unchanged |
| [536-2627](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L536-L2627) | `BOOTLOADER_SCRIPT` | `templates/bootloader.js`, without the `<!-- -->` and `<script>` wrapper `_bootloader_body()` stripped on every call, so that method now just returns it |
| [2826-3130](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L2826-L3130) | `ADMIN_TAB_SCRIPT` | `templates/settings_tab.js` |
| [3132-3343](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L3132-L3343) | `ADMIN_PAGE_SCRIPT` | `templates/admin_page.js` |
| [3345-4153](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L3345-L4153) | fragments, storage, delivery caches, legacy index cleanup | `function.py`, unchanged |
| [4154-4249](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L4154-L4249) | `_require_admin`, `_require_user`, `_signed_in_user` | gone: owpp's guard ([sign-in](#sign-in-and-routes-the-routes-library)); `_cookie_user_id` stays |
| [4251-4907](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L4251-L4907) | `_register_route` | `function.py`, rewritten around `plugin_mount`, the handler bodies yours |
| [4908-5111](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L4908-L5111) | `_handle_css_save` | `function.py`, unchanged |
| [5112-5124](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L5112-L5124) | `CONSULT_PROMPT` | `templates/consult_prompt.txt` |
| [5125-5316](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L5125-L5316) | the token prefixes, `_read_apply_token`, the AI Consultant | `shared.py` has the token format; the rate limit is `plugin_claim`; the rest is unchanged |
| [5368-5525](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L5368-L5525) | `PERSONAL_DESIGNER_BLOCK` | `templates/designer/personal.html`, used as you used it |
| [5528-5545](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L5528-L5545) | `_notice_page` | `templates/notice.html`, the same one line, with `__TITLE__` and `__DETAIL__` |
| [5553-19526](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L5553-L19526) | `html_content` | `templates/designer/` ([the designer page](#the-designer-page)) |
| [19647-19761](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L19647-L19761) | the markup `_build_html` builds in Python | `templates/designer/parts/`: it never depends on a valve, so it was built once and kept as HTML |
| [19762-19786](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L19762-L19786) | the personal swaps and the final `.replace()` chain | `function.py`, unchanged but for the four placeholders that are files now |
| [19788-20685](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L19788-L20685) | post-processing, SSE, Redis relay, peer valve sync, shutdown | `function.py`, unchanged; two limits read from `config.yaml` |
| [20686-20847](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L20686-L20847) | `event()` | six `@on` handlers ([events](#events-the-events-library)) |
| [20848-20872](https://github.com/silentoplayz/theme-designer-pro-presets/blob/34345eaffb8678ddfd38b45d7bc173f5b0d27132/event-function/theme_designer_pro_event.py#L20848-L20872) | `register(app)` | `function.py`, unchanged |

### The designer page

`html_content` became [`templates/designer/page.html`](templates/designer/page.html), a 265-line outline of the page, and the files it includes, each where its text was:

```
templates/designer/
  page.html               the head, the tab bar, the footer, the modals: what the page is made of
  styles/designer.css     your <style> block (805 lines)
  styles/skin.css         <style id="owui-skin">, the look inside Settings and the Admin Panel
  tabs/*.html             the seven tab panels: themes, lch (Palette), custom, canvas, bg, surfaces, backgrounds
  docs.html               the in-designer documentation (1,558 lines)
  parts/*.html            the save and rename metadata grids, the Selective Sync options, the JSON editors
  scripts/01-core.js      the script, as sixteen files cut at your own "// --- Name ---" headers:
  ...                     core, storage and saves, modes, AI Consultant, animation settings,
  scripts/16-...js        gradient CSS, line numbers, gradient builder, surfaces, selective sync,
                          import/export, backgrounds, theme updates, community themes, update
                          diffs, snapshots and presets
  personal.html           PERSONAL_DESIGNER_BLOCK
```

An include is a line `<!--#include scripts/03-modes.js-->` (or, for the four parts, the marker where your `{SAVE_METADATA_GRID}` was). `_designer_page()` in `function.py` puts the files in, once, when the function loads, and the page that comes out is your `html_content` to the byte. Every request then runs your `_build_html` as before: the personal swaps, `{ROUTE_BASE}`, `{BOOTLOADER_SRC}`, the config tag. A test ([`test_the_page_is_its_files_put_together`](tests/test_tdp_designer.py)) checks that every file is included exactly once and nothing is left to include.

The script files are one `<script>` still. They are cut where your section headers are, at the script's top level, and put back in order, so nothing about how the browser runs it changed: they are files so that a person (or an editor's syntax highlighting) can read one feature at a time.

### What owpp's libraries replaced

Each of these is code you wrote that owpp has a library for. The libraries are vendored into the deployed bundle, so the deployed plugin needs nothing from owpp at run time.

#### Sign-in and routes: the `routes` library

Your `_signed_in_user` decoded the session and checked revocation and the trusted email header itself; your `_register_route` inserted Starlette routes in front of the SPA's mount by hand, and removed the previous load's paths (fourteen per base) before adding its own. owpp's `plugin_mount(app, router, prefix, name=...)` does both: it puts a sign-in guard on every route it mounts (Open-WebUI's own `get_current_user`, so revocation and trusted headers are Open-WebUI's checks), moves the routes ahead of the catch-all, and replaces this function's earlier mount *of the same name*, wherever it was. A route that needs more than a signed-in user says so in its signature: `user: PluginAdmin` or `user: PluginUser`.

So the routes are two FastAPI routers instead of a list of `Route`s:

| Route | Mount | Who | Was |
| --- | --- | --- | --- |
| `GET {base}` | designer | an admin; with `?scope=me`, any signed-in user | `_signed_in_user(("admin",))` / `_require_user` |
| `POST {base}` | designer | `PluginAdmin` | `_require_admin` |
| `POST {base}/me` | designer | `PluginUser` | `_require_user` |
| `POST {base}/consult` | designer | `PluginUser` | `_require_user` |
| `GET {base}/library.json` | designer | `PluginAdmin` | `_require_admin` |
| `POST {base}/events/bind` | designer | `PluginUser` | `_require_user` |
| `GET {base}/page-background` | designer | signed in | `_require_user` |
| `POST`, `DELETE {base}/page-background` | designer | `PluginAdmin` | `_require_admin` |
| `{base}/me/page-background` | designer | `PluginUser` | `_require_user` |
| `GET {base}/theme.css`, `/state.json`, `/events`, `/auth-background` | public | anyone | no check |
| `GET {base}/me/theme.css`, `/me/state.json`, `/me/library.json` | public | anyone; empty unless signed in | `_require_user`, empty on failure |
| `POST`, `DELETE {base}/auth-background` | public | `PluginAdmin` | `_require_admin` |

The designer's own route is the one place with two levels, decided by its query: `DesignerUser`, at the top of `function.py`, picks owpp's admin guard or its signed-in guard by `scope`, so the level is still on the route and still owpp's. The public mount is `access="public"` in so many words, and `owpp check` lists it, so a reviewer sees what anyone can reach. The personal reads are on it because the bootloader reads an empty answer as "use the instance theme", which is what you answered someone signed out, and what they still get.

Your aliases (the read-only routes kept at every Designer Url this app served, for pages loaded before a change) are public mounts too, one per old URL, each named after it. Your CSRF check (`_from_other_origin`), content-type check and size limits are not sign-in, so they stayed, as you wrote them.

#### Events: the `events` library

`event()` was one method: shutdown first, then live reload, then disable, enable, account deletion, background images, and the publishing. Each is now a method marked with the events it handles:

| Handler | Events | Was |
| --- | --- | --- |
| `_shutting_down` | `system.shutdown.started`, `.completed` | the first `if` |
| `_disabling` | `function.disable_started` (its own) | `if is_own and ... disable_started` |
| `_enabling` | `function.enable_started` (its own) | `if is_own and ... enable_started` |
| `_account_deleted` | `user.deleted` | `if __event_name__ == "user.deleted"` |
| `_background_changed` | `user.settings_updated`, `model.*` | `_broadcast_background_event` |
| `_sync` | `system.startup.started`, `.completed`, and its own `function.enable_started`, `.updated`, `.valves_updated` | the rest of `event()` |

`event()` itself is kept, short: it shares the stream set and calls `reload_on_event` (skipping shutdown, as you did), then hands over to the handlers. `owpp check` checks the event names, so a typo cannot silently never fire.

#### The Shared Assets Protocol and live reload: `include:`

Your two pasted blocks are owpp's copies now. The shared asset block is byte-identical to yours (`ASSET_IMPL_VERSION` 5). Live reload is the protocol's copy at the same version as yours (`RELOAD_IMPL_VERSION` 2): it ignores the events that arrive between a disable and its commit, and the newest copy in a process replaces the listener. You register the fragments yourself, and still do: `_publish_fragments` calls `asset_register` with your markers and order 100. owpp also has an `assets/` folder for plugins whose fragments are files, and it was not used here, on purpose: your loader fragment is the bootloader *and* the designer's preview script with other values, and it stays published while the function is off (with `__THEME_ACTIVE__` false, which clears the theme a page kept), which `assets/` would withdraw.

#### The signed link: `shared.py`

The Launcher signs a theme's hash for one user with `WEBUI_SECRET_KEY`, and the designer checks it; the format was written in both files, with a comment that they must match. [`shared.py`](shared.py) has it once (`_sign_token`, `_open_token`, the two prefixes), and owpp bundles it in front of both `function.py` and `tool.py`. What a token says (whose, until when, which scope) is still checked where it was, in `_read_apply_token`. It also has `_fill`, which fills `__NAME__` placeholders in one pass, for the notice page and the Launcher's frame.

#### The rest

- **The AI Consultant's rate limit** was a per-worker dict of last-request times; it is `plugin_claim(f"consult:{user.id}", 3)` (the `jobs` library), one claim across every worker when Open-WebUI has Redis, so a user with four workers gets one request per three seconds, not four.
- **Limits**: `_SSE_MAX_CLIENTS`, the 15-second heartbeat and `CONSULT_INTERVAL` are read from [`config.yaml`](config.yaml), with your numbers as defaults, so an operator behind a proxy with a shorter idle timeout can lower the heartbeat with an environment variable instead of editing code.
- **The Launcher's HTML**: `CARD_HTML` is [`templates/launcher/card.html`](templates/launcher/card.html) and the frame `_embed` built in an f-string is [`templates/launcher/embed.html`](templates/launcher/embed.html). A tool bundle normally embeds the whole `templates/` folder, which would have copied the 1 MB designer into the Launcher, so owpp gained `tool: templates: [launcher/]` while this was adapted: the Launcher's bundle is 81 KB.
- **`requires: iframe_sandbox_allow_same_origin: true`** in `plugin.yaml`: `owpp deploy` warns when an instance has it off, which your README asked people to check by hand.

### What stayed exactly as you wrote it

Everything a user's data depends on: the files under `DATA_DIR/theme/` (same names, same per-user folders), the function id `theme_designer_pro`, the routes and their answers, the storage keys in the browser, the token format, the markers in `/static/custom.css` and `/static/loader.js`. A Theme Designer Pro you deployed by hand can be replaced by this plugin and its themes, galleries and pictures carry over.

And the parts owpp has nothing for: the SSE fan-out and its heartbeat, the Redis relay with its resync after a reconnect, the peer valve sync, the exit hook that ends streams on SIGTERM, the delivery caches and their ETags, every post-processing step, the CSRF check, the legacy `index.html` cleanup and the old fragment key in `register()`. Two of those were looked at and kept on purpose:

- Your `_read_valves_from_db` returns None when the read fails, and the worker keeps its valves. owpp's `plugin_stored_valves` falls back to the defaults, which on a transient database error would switch a peer's valves back to the defaults. Yours stays.
- The heartbeat and the Redis subscriber run on every worker. owpp's `plugin_every` runs a job on one worker per period, which is the wrong shape for them.

### What behaves differently

Measured with [`adapt/compare_pages.py`](adapt/compare_pages.py), which sends both versions the same requests (below). All of it comes from owpp's sign-in guard answering before your handlers:

| When | Yours | This plugin |
| --- | --- | --- |
| Someone opens the designer in a browser, signed out | `401 {"error": "Not authenticated"}` | sent to Open-WebUI's sign-in page, and back after |
| A fetch with no session | `401 {"error": "Not authenticated"}` | `401 {"detail": "Sign in to Open-WebUI first."}` |
| A user on an admin route | `403 {"error": "Admin access required"}` | `403 {"detail": "Admins only."}` |
| The function is disabled | the designer `503`, the theme empty, the stream open | every route `404` |
| An API key (`sk-...`) | refused ("these routes take only a session") | accepted where Open-WebUI accepts API keys |
| The order of checks on a save | active, origin, type, size, then sign-in | sign-in first, then the rest |

The disabled case has one visible effect: your stream stayed open while the function was off, so re-enabling it reached open tabs at once. owpp's guard answers 404 for a disabled plugin, so the stream closes; your bootloader already retries a closed stream (up to a minute apart) and refetches when it reopens, and reads a 404 for the theme as "no theme", so open tabs drop the theme on disable and get it back within about a minute of re-enabling.

Besides the guard: the main handler (`_sync`) runs on the function's own lifecycle events rather than on every event Open-WebUI sends; routes mounted with `plugin_mount` do not go missing, so nothing needs re-registering on, say, `chat.created`. And the AI Consultant's limit holds across workers, as above.

### What changed for Open-WebUI v0.13.5

Your 1.23.0 already follows v0.13.5's colours: the palette sets its base scale (`--app-base-*`), and steps aside for someone who picked their own colours under Settings > General > Colors. One thing still breaks there, and is fixed in the page-side scripts (`templates/bootloader.js` and three of `templates/designer/scripts/`), and nowhere else:

- **OLED Dark lasted one page load.** v0.13.5 has no OLED theme of its own: as each page loads, it turns a stored `theme` of `oled-dark` into `dark`, and saves a black background as that person's own Dark colours. Picking OLED in the designer stored exactly that, so the next page was in Dark, the designer opened on Dark, and, since a person's own colours win, that person's Dark palette stepped aside for plain black from then on. Now OLED stores Open-WebUI's `theme` as `dark` and says OLED under a key of its own, `owui_tdp_oled`, which the designer and the bootloader read with it: OLED stays OLED, Open-WebUI's Settings show Dark, and nothing is saved under its Colors. Switching Open-WebUI to any other theme ends OLED.

Someone who used OLED before upgrading to v0.13.5 is moved by Open-WebUI itself, before any plugin's script runs: they pick OLED in the designer once more, and clear the black left under Settings > General > Colors, or their Dark palette stays aside.

The change is [`adapt/open-webui-0.13.5.patch`](adapt/open-webui-0.13.5.patch). On v0.13.4 a theme looks as it did, since the designer applies OLED itself either way; one thing differs there: with the function off, someone who picked OLED in the designer sees Open-WebUI's Dark, not its OLED Dark. [The screenshots](../../../docs/screenshots.md) show it on v0.13.5. It is worth sending upstream.

### Small fixes on the way

- The Launcher's header had a `description:` over several lines. Open-WebUI reads a header line by line, so it stored only the first one; it is one line in `plugin.yaml` now. The sentence about which function version it needs is gone, since the two ship together.
- The Launcher's docstrings listed their parameters under `Parameters:`. Open-WebUI gives the model a parameter's description from a `:param name:` line, so they are written that way (same words).
- `SKILL.md` has `access: public` in its front matter, so users who are not admins can read the skill, as the Launcher needs.
- The Python is laid out by `ruff format`, and holds to the repository's lint rules: a `try`/`except`/`pass` is `contextlib.suppress`, `%` and `.format()` strings are f-strings, a variable named `l` is `light` or `lum`, the Launcher's `__user__: dict = {}` defaults are `None` (then `{}`), and `_handle_css_save` and `_handle_consult` are annotated with a `JSONResponse` imported at the top instead of a string naming one imported inside them. The comparison below was run again after these: nothing moved.
- The bundle is 1.6 MB, against your 1.3 MB: the templates are embedded as JSON strings, whose escaping costs about 20%. It is still under 2 MB, the size Portainer's deployment notes treat as the limit for one function.

### How we checked it is the same

[`adapt/compare_pages.py`](adapt/compare_pages.py) loads your file and this plugin, each into owpp's mock Open-WebUI, sends both the same 63 requests (the designer for an admin and a user, saves, no-op saves, refused saves, resets, `theme.css`, `state.json`, `/static/loader.js` and `/static/custom.css` under five combinations of valves, personal themes, and disabling) and compares every status, content type and body. **55 are identical byte for byte**; the other 8 are the guard's answers in the table above. That is with the v0.13.5 change reversed (`git apply -R examples/plugins/theme_designer_pro/adapt/open-webui-0.13.5.patch`): with it, the 17 responses that carry the designer page or `/static/loader.js` differ by it too, and 38 are identical. [`adapt/compare_launcher.py`](adapt/compare_launcher.py) does the same for the Launcher: the frames, the cards, the refusals and what the model is told are identical, and each card's Apply link opens the designer with the theme for its own user and no one else's.

Then the plugin has its own tests, in `tests/` (109, at least one per valve and per route), and a real Open-WebUI in Docker checks what the test harness cannot: that the routes are reached ahead of Open-WebUI's own under `/api/v1`, that a save reaches a signed-out page, and that a user is given the Launcher and the skill ([the live suite](../../../tools/live/test_live.py)).

### What owpp learned from it

Adapting it changed owpp, and found two things to fix there:

- `tool: templates:`, so a tool embeds only the templates it uses (above).
- The test harness runs Open-WebUI's own code, so events about users and models (`owui.emit("user.deleted", {"type": "user", "id": ...})`), which `user.deleted` needed, and the `decode_token` that your `_cookie_user_id` calls are Open-WebUI's; it fakes the model for a plugin that asks one itself, as your AI Consultant does (`owui.model_reply`, `owui.completions`).
- Its `tests/` is the first example's with a `conftest.py`, and is a package (`tests/__init__.py`) so its fixtures do not take the module name `conftest` from owpp's own tests when one pytest run collects both.
- Two gaps, fixed in owpp 0.6.1. owpp refused a function that calls `include_router` or `mount` on the app, but your `app.routes.insert(...)` passed that check; it now refuses every change to the app's route list ([#68](https://github.com/zmnatz/open-webui-plugin-protocol/issues/68)). And the `assets/` library filled its placeholders one after another, so a saved value holding another placeholder's text was filled too, which is why your `_loader_fragment` fills the saved state last; it now fills them in one pass ([#69](https://github.com/zmnatz/open-webui-plugin-protocol/issues/69)).

### Moving to a newer upstream release

1. Clone [silentoplayz/theme-designer-pro-presets](https://github.com/silentoplayz/theme-designer-pro-presets) at the new commit, and read its diff since `34345ea`: this code runs with admin rights.
2. `python -I examples/plugins/theme_designer_pro/adapt/split_upstream.py <checkout> examples/plugins/theme_designer_pro` cuts `templates/` again. A new section in the script or a new tab may need a new cut in the script; it stops and says which boundary it could not find. Then `git apply examples/plugins/theme_designer_pro/adapt/open-webui-0.13.5.patch`, unless the new release handles v0.13.5 itself ([what changed for v0.13.5](#what-changed-for-open-webui-v0135)); fix by hand what no longer applies, and write the patch again with `git diff -- examples/plugins/theme_designer_pro/templates`.
3. Port the Python changes in the diff into `function.py` and `tool.py` by hand, by the map above, and the header changes into `plugin.yaml`. Move `VERSION` and the commit in the attribution comments.
4. `uv run python examples/plugins/theme_designer_pro/adapt/compare_pages.py <checkout> examples/plugins/theme_designer_pro` and `compare_launcher.py`, with the v0.13.5 patch reversed: the 55 must still be identical.
5. `owpp test theme_designer_pro`, `owpp check --strict theme_designer_pro`, and the screenshots.

## Test

- `owpp check theme_designer_pro` bundles it exactly as the deploy does, compiles it, lists the public mounts and the three environment variables, and checks the event names.
- `owpp bundle theme_designer_pro out.py` writes the deployed code to read or diff.
- `owpp test theme_designer_pro` runs `tests/` against owpp's mock Open-WebUI: the designer page (`test_tdp_designer.py`), saving and serving the theme and the first-paint fragments (`test_tdp_theme.py`), personal themes and pictures (`test_tdp_personal.py`), live updates and the lifecycle (`test_tdp_live.py`), the AI Consultant (`test_tdp_consultant.py`), the Launcher (`test_tdp_launcher.py`), the shared link format (`test_tdp_shared.py`) and what it installs (`test_tdp_install.py`).
- On a live Open-WebUI:
  - Enable the function: Workspace > Tools lists Theme Designer Pro Launcher and Workspace > Skills lists theme-designer-pro, for a user too.
  - As an admin, open `/api/v1/theme-designer`; as a user it answers 403; signed out it sends you to sign in.
  - Pick a theme in Live mode: a chat open in another browser changes without a reload, and a private window's sign-in page wears it if its Show on Auth Pages is on. DevTools > Network: `theme.css` answers 304 on a reload.
  - Settings: an admin has Admin > Themes. Turn Show In Admin Panel on: the Admin Panel has a Themes page.
  - With Allow Personal Themes on (the default): a user's Settings has a Themes tab, and the theme they save is theirs alone.
  - On the Surfaces tab, turn the sidebar's opacity down with an animated theme: the sidebar is frosted glass. Turn Enable Canvas FX off: the animation stops everywhere.
  - In a chat with the Launcher on, ask "make my chat a deep teal lagoon": a card shows the theme; Apply puts it on (needs iframe Sandbox Allow Same Origin).
  - Disable the function: chats go back to Open-WebUI's own look; enable it: they are themed again within a minute.
  - On v0.13.5: pick OLED in the designer and reload a chat: it is still OLED, and Settings > General > Colors has nothing set. Set a colour there: that person's chats show it instead of the palette.

## Deploy

- Function type: **event**. It installs the Launcher tool and the skill; disabling or deleting it removes both.
- `owpp deploy --only theme_designer_pro --dry-run`, then without `--dry-run`. A single-plugin deploy never prunes. The deploy report warns when iframe Sandbox Allow Same Origin is off.
- To use it from another repository (as a whole plugin from git), a `plugin.yaml` of `source: {git: https://github.com/zmnatz/open-webui-plugin-protocol.git, path: examples/plugins/theme_designer_pro, plugin: true}`, then `owpp pull theme_designer_pro`.
