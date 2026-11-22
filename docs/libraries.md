# Libraries

Libraries are plain Python files in `src/owpp/runtime/lib/`, inserted into a bundle by `include:` (see [bundling](bundling.md#order)). They are **vendored**: the bundle contains a copy, so a plugin has no runtime dependency on this repository. Public names start with `plugin_`; private helpers start with `_<lib>_` so nothing collides with plugin code. Each file ends with a marker comment (`# end plugin <lib> library`) used to avoid inserting it twice.

A plugin imports what it uses from **`owpp.lib`**, which re-exports every library's public names:

```python
from owpp.lib import PluginAdmin, plugin_mount
```

The import is for an editor and for tests; owpp is a development dependency, not something Open-WebUI has. The bundler removes the line and inlines the library, so it must be a top-level `from owpp.lib import NAME`, without `as`. The library must also be in the bundle: asked for with `include:`, or turned on by what the plugin holds. The bundler names the library when it is not. The libraries import each other the same way, relatively (`from .plugin_core import plugin_app`), and those imports go too. Each library also gives its data placeholder a default (`__CONFIG_DATA__ = '{}'`), so it imports on its own; in a bundle the plugin's data takes its place.

| Library | Adds |
| --- | --- |
| [`core`](#core) | function id, app, is-enabled, stored valves |
| [`routes`](#routes) | mount a FastAPI router that survives reloads |
| [`jobs`](#jobs) | background and repeating jobs, one worker per period |
| [`chat_data`](#chat_data) | JSON values saved with a chat |
| [`events`](#events) | `@on("event.name")` handlers instead of an `event()` full of `if` checks |
| [`static`](#static) | files from `static/`, served as they are |
| [`templates`](#templates) | files from `templates/`, embedded and rendered by the function, never served |
| [`config`](#config) | a `config.yaml` shipped with the plugin, parsed at bundle time, read with `plugin_config()` |
| [`assets`](#assets) | `assets/loader.js` and `assets/custom.css` published as this plugin's fragments of the Shared Assets Protocol |
| `shared_assets`, `live_reload` | Classic298's Shared Assets Protocol, unmodified |

A library brings in the ones it is built on, and some are turned on by what the plugin holds, without `include:`. The table below is generated from the library catalogue (`src/owpp/libraries.py`) when the site is built:

<!-- library catalogue -->

Updating a vendored library updates every plugin that includes it on its next deploy.

## core

- `plugin_function_id()`: this function's id, from the module name `function_<id>_<32 hex>`; `None` outside Open-WebUI.
- `plugin_app()`: Open-WebUI's FastAPI app, or `None` before import.
- `await plugin_is_active(function_id=None)`: still installed and enabled. Returns **True when it cannot tell** (no id, lookup failed): it is used to decide whether to stop work, and stopping on a hiccup is worse than carrying on.
- `await plugin_stored_valves(valves_cls, function_id=None, ttl=0)`: the valves as stored in the database. A running instance only has valves applied when it handles an event or a chat, so routes and jobs read them here. `ttl` reuses a read for that many seconds (for a page that polls).
- `plugin_env(value)`: resolves **environment templates**, `${NAME}` and `${NAME:-default}`, from the Open-WebUI container's environment, in a string or in the strings of a dict or list (keys are left alone). A string that is *one* template is typed like a YAML scalar (`${N:-60}` is the number 60, `${FLAG:-true}` is `True`); a template inside a longer string is text (`http://${HOST}:8000`). An unset or empty variable uses its default; with no default a whole-string template is `None` and an embedded one is empty, both with a warning. `$${` writes a literal `${`. `plugin.yaml`'s `jobs:` and `config.yaml` use it for you; call it yourself for a value in code.

## routes

**Every route requires a signed-in user, unless a mount says `public` in so many words.** A route is open to any signed-in user; one that needs more is **marked** (below), never checked by hand in its handler. The level belongs on the route, or on the mount (`access=`), or, for the `static/` files, on [`static:`](plugin-format.md#static-and-the-static-and-templates-folders). There is no plugin-wide setting.

`plugin_mount(app, router, prefix, owner=None, name="", access=None, guard=None) -> int`

- **Puts the guard on everything it mounts**, the `static/` files included. Per request: **404** once the function is disabled (before asking who you are, so a disabled plugin reveals nothing), then a signed-in user (below), then **403** for a signed-in non-admin when the access is `admin`. A pending account is not signed in. The session is Open-WebUI's own (a bearer header, else its `token` cookie).
- **Someone opening a page with no session is not just turned away.** Many sign-ins happen by themselves when the app's home page loads (a proxy's trusted headers, authentication switched off, an OIDC session at the identity provider), so a person who goes straight to a plugin's address has no cookie yet through no fault of their own. For a browser navigation (a `GET` that asks for HTML) the guard therefore:
  1. **tries the sign-ins that need no input**: it calls Open-WebUI's own sign-in endpoint with empty credentials, carrying the request's headers, exactly as its login page does for trusted-header and no-auth setups. The call runs inside the app (no socket, so no host, port or TLS to get wrong). On success it carries on as that user and hands the session cookie to the browser, so the next request has one;
  2. **else sends the browser to Open-WebUI's login page** (`/auth?redirect=<where they were going>`, query string included, always a plain path on this site), which handles OIDC, LDAP and passwords and brings them back;
  3. but an **iframe** (the Artifacts panel) is signed in if it can be and otherwise gets a 401, never a redirect, since a login page inside a sandboxed panel is no use. Inside the panel it usually *cannot* be: with Open-WebUI's default settings the panel sends no session at all ([below](#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin)); and an **API call or fetch** (anything not asking for HTML) always gets a plain **401** and never has a session minted for it.

  OIDC and LDAP cannot be done silently from here (they need a redirect to the identity provider, or a password), which is why the fall back is the login page rather than a failure.
- `access` is the mount's level: `"user"` (the default), `"admin"` or `"public"`. Anything else, `"Public"` and `True` included, is a `ValueError`, so a typo can never open a mount. Use `name` for a second mount with a different level.
- Drops the routes an earlier load of this same function mounted under `prefix` (Starlette cannot swap a handler in place, so the old page would otherwise keep serving until restart). Only routes whose endpoint belongs to this function are dropped, never Open-WebUI's.
- **`name` is a mount's identity.** Mounting a name again replaces the earlier mount of that name *wherever it was* (a configurable path that changed drops the old one by itself, with no state kept), and mounts with different names never replace each other (the static `public/` files, a page, an API). Give each mount of a function its own name; two unnamed mounts count as one.
- Moves the new routes ahead of Open-WebUI's catch-all mount at `/`, which otherwise swallows anything added later.
- Refuses prefix `/`.
- Mounting an **empty** router removes that name's routes. (Matching uses the tags the mount puts on what it adds, because current FastAPI adds one wrapper object per router, not a route per path.)

**Marking a route.** To mark one route, type a parameter of its handler:

```python
@router.get("/purge")
async def purge(user: PluginAdmin):  # admin-only; `user` is the signed-in admin
    ...


@router.get("/mine")
async def mine(user: PluginUser):  # any signed-in user; `user` is that user
    ...
```

`PluginUser` and `PluginAdmin` are ordinary FastAPI `Annotated` dependencies, and the handler receives the user (an object with `.id` and `.role`). - **`access="public"` serves people who are not signed in.** It is the one level that needs no one: no session lookup, no sign-in attempt, no redirect. It is still switched off with the function (404), and it is **per mount**, because a mount's guard covers every route in it, so a public endpoint (a webhook, an OAuth callback, a health check) gets a mount of its own, with its own `name`. A marker on a route of a public mount still applies (`user: PluginUser` there asks for a signed-in user), and a handler can ask who is there, if anyone, with `plugin_user(request)`. `owpp check` lists every public mount as a `note`, so a reviewer sees them; a plugin should have few.

A marker **only tightens** what the mount requires: `PluginAdmin` makes one route admin-only, but `PluginUser` on a route of an `access="admin"` mount does not open it, because the mount's guard still applies. There is no marker for a public route. The session is looked up once per request however many guards ask.

**Marking a route by the chat it serves.** For a route about one chat, type the chat's path parameter:

```python
@router.get("/view/{chat_id}")
async def view(chat_id: WritableChat):  # signed in, and can write to this chat; receives the id
    ...


@router.get("/export/{chat_id}")
async def export(chat_id: ReadableChat):  # signed in, and can read this chat
    ...
```

`ReadableChat` and `WritableChat` check Open-WebUI's own chat access (`Chats.has_chat_access`) for the signed-in user and hand the handler the chat id. No access answers **404**, not 403, so a chat's existence is not revealed (401 without a signed-in user). A temporary chat (`local:...`) has no stored record, so any signed-in user passes for one: keep nothing private there. `plugin_chat_guard(permission, param="chat_id")` builds the same dependency for another path-parameter name. A route that has no such path parameter fails with a 500, loudly. Excalidraw's page uses `WritableChat`, replacing the check it used to write by hand.

Which to use: mark each route that needs more than a signed-in user. If **every** route of a mount is admin-only, mount it with `plugin_mount(..., access="admin")` instead of marking each one, so a route added to it later is admin-only by default. `stale_data` marks its one route `user: PluginAdmin`; Excalidraw's page takes `chat_id: WritableChat`.

`await plugin_user(request)`: the signed-in user or `None`, for code that has the request but not a marked parameter. `plugin_user(request, token=None)` also takes a session token to use in place of the request's own. `plugin_guard(access=None)` is the dependency behind the markers and the mount.

**The one exception: `guard=`.** A route that cannot carry an Open-WebUI session, such as an API called from a sandboxed iframe (which sends no cookies), can pass its own FastAPI dependency as `guard`, which replaces the sign-in check for that mount only. It must verify a credential that was **minted from a real login**, so keep the page that mints it behind the normal guard. That page needs a session of its own, which inside the Artifacts panel it only gets with **iframe Sandbox Allow Same Origin** on ([below](#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin)). The function must still be enabled. `guard` and `access` cannot be combined.

`plugin_token(subject, hours=12)` and `plugin_check_token(token, subject)` are that credential, ready-made: a short-lived signed token for one subject (a chat id, say), stateless so every worker agrees, scoped to this function (another plugin's tokens never validate here) and expiring. Mint one inside the signed-in page that loads the iframe, and have the API's guard call `plugin_check_token`. Excalidraw does exactly that: its page needs a login and a writable chat, and its API takes the token the page was rendered with.

### Pages in the Artifacts panel need "iframe Sandbox Allow Same Origin"

A filter can show a plugin's page in the Artifacts panel by putting an `<iframe>` in a reply, as Excalidraw does. The panel is a **sandboxed iframe**, and what it can do depends on a per-user Open-WebUI setting, **iframe Sandbox Allow Same Origin**, which is **off by default** (v0.13.4):

| Setting | The frame's origin | The page behind the guard | Measured on v0.13.4 |
| --- | --- | --- | --- |
| off (default) | opaque | gets no session: the `token` cookie is `SameSite=Lax` and is not sent, so the guard answers **401** | `{"detail":"Sign in to Open-WebUI first."}` |
| on | Open-WebUI's own | gets the session like any page, and can mint a `plugin_token` for its API | 200 |

So **`guard=` covers the API, not the page.** The page has to be loaded by a signed-in user so it can mint the token, and inside the panel that only happens with the setting on. Nothing in this library can change that: the panel's sandbox is Open-WebUI's.

**What the setting costs.** It applies to every artifact, not only yours. With it on, the script in any HTML a model produces runs with Open-WebUI's origin, so it can read the sign-in token Open-WebUI keeps in `localStorage` and call the API as the user; a prompt injection that gets a model to emit such an artifact would work. It is an Open-WebUI permission that no plugin can narrow. Inline Visualizer needs the same setting for live rendering, and its upstream documents it the same way.

**What a plugin that shows a page in the panel must do:**

- **State the requirement and its cost in its README**, with both ways to turn it on: per user under **Settings > Interface**, or for everyone under **Admin Settings > General > Default Interface Settings** (`DEFAULT_INTERFACE_SETTINGS='{"iframeSandboxAllowSameOrigin": true}'`; a user's own setting still wins). Say it is for instances where what models put into artifacts is trusted. Excalidraw's README is the model.
- **Keep the page behind the normal guard.** Do not make it `public` or put a token in the iframe's address to get around the setting. Both were considered for Excalidraw and refused: a token in the address is written into the chat's stored HTML, readable by anyone who can read the chat, and has expired by the time an old chat is reopened, unless it lives long enough to be a permanent link; a public page that asks the parent window for a credential over `postMessage` needs Open-WebUI to answer, and it does not ([issue #6](https://github.com/zmnatz/open-webui-plugin-protocol/issues/6)).
- **Serve what the page fetches with care.** With the setting off, files the page loads from another host are cross-origin from an opaque origin, so a self-hosted asset server needs `Access-Control-Allow-Origin: *` (Excalidraw's [self-hosting](examples/excalidraw.md#self-hosting-the-editor) section).

This is revisited if Open-WebUI gives artifacts a way to obtain a scoped credential.

**No way around it in code.** `owpp` refuses a `function.py` that calls `include_router`, `add_api_route`, `add_route` or `mount` on the app (`app`, `__app__`, `request.app`, `app.router`), because that adds a route the guard never sees. Mount with `plugin_mount`.

`await plugin_require_active(function_id=None)`: raises 404 unless the function is still enabled. The guard calls it for you. Do not use it directly as a dependency (it would expose `function_id` as a query parameter).

**Dependency signatures.** FastAPI resolves annotations by name. A module using postponed annotations cannot resolve types imported *inside* a function, and reports them as required query parameters (422). Keep only module-level types (`Request`) in dependency signatures and build the rest by hand.

## jobs

- `await plugin_claim(key, ttl_seconds) -> bool`: true for exactly one caller across all workers within the ttl. Uses Redis `SET NX EX` through `app.state.redis` when present, else an in-process expiry map. The ttl is at least 1 second and doubles as a cooldown. `await plugin_unclaim(key)` undoes a claim whose work never ran.
- `plugin_spawn(name, factory, on_skip=None)`: run an async `factory()` in the background, one job at a time per function in this process.
- `plugin_every(name, seconds, factory, first_after=None)`: repeat on one worker per period (a claim) until the function is disabled or deleted (checked each period). Calling it again with the same name **replaces** the earlier loop, so it is safe to call on every load. Needs a running event loop.
- `plugin_stop_jobs()`: cancel this function's repeating jobs.
- `class PluginScheduledSync`: a mixin, `class Event(PluginScheduledSync)`, built on the [events](#events) library: its `@on("system.startup.completed", "function.enable_started", "function.valves_updated", own=True)` handler runs the class's `async sync()` and then repeats it every `SYNC_INTERVAL_MINUTES`, and every event stops the jobs when `ENABLE` is off. The class needs `Valves` with `ENABLE` (bool) and `SYNC_INTERVAL_MINUTES` (int; 0 means only on those events), `self.valves`, and `sync()`. It is a `PluginEvents` class, so your own `@on` handlers work beside it. Adds `events` (and `core`).
- `plugin_sync_markers() -> set[str]`: the `managed_by` markers a sync treats as its own when it replaces and prunes: the function id, plus `jobs: adopt_markers` from `plugin.yaml` ([plugin format](plugin-format.md#jobs)). Empty when the function id is unknown, so nothing matches by accident. Mark what you write with the function id, and test ownership with this.

State survives the module being loaded again (Open-WebUI reloads functions) in a `sys.modules` entry, so a new load replaces the old load's loops instead of doubling them.

**Multi-worker.** The one-worker-per-period guarantee depends on `app.state.redis`. Without Redis each worker process runs its own loop.

## events

Handlers for Open-WebUI's lifecycle events, by decorator, so an Event function does not need one `event()` method of `if __event_name__ ...` checks:

```python
class Event(PluginEvents):
    @on("system.startup.completed")
    async def started(self): ...

    @on("function.enable_started", "function.updated", "function.valves_updated", own=True)
    async def reload(self, app):  # takes the arguments it names
        ...
```

- **`@on(*names, own=False)`** marks a method as the handler for those events. `own=True` ignores events about *other* functions (an event with no subject, such as startup, still counts); it replaces the `subject_id != __id__` check every handler used to write. Decorators can be stacked, several handlers may listen to one event (they run in definition order), and a subclass inherits its parent's handlers.
- **Arguments by name.** A handler may take any of `event` (the event dict), `name`, `id` (this function's id), `app` and `request`, and may be sync or async. `app` is the `__app__` Open-WebUI passed, else `request.app`, else the app found by `plugin_app()`.
- **One failing handler does not stop the rest**, or the next mixin: it is logged and the others run.
- **Valves.** The mixin creates `self.valves` from the class's `Valves` (and the library mixins add theirs to it), so a class needs no `__init__` of its own just for that; write one for anything more and call `super().__init__()`.
- **Mixins.** The library's other mixins, `PluginAssets` and `PluginScheduledSync`, are `PluginEvents` classes themselves and bring this library in, so `@on` works in them and they combine freely (`class Event(PluginAssets, PluginScheduledSync)`). Each passes every event on to the next. If you override `event()` yourself, call `await super().event(...)`.
- **Checked by `owpp check`.** The names must be event names, and a name that looks like a typo of a known one is refused with a suggestion (`function.valve_updated` never fires: did you mean `function.valves_updated`?). A name it has not seen but that looks plausible (`function.created`) is accepted, because Open-WebUI adds events. Names must be strings or module-level string constants. A class that has `@on` handlers but does not inherit `PluginEvents` is refused, since nothing would ever call them.

Known events: `system.startup.completed`, `function.enable_started`, `function.disable_started`, `function.enabled`, `function.disabled`, `function.updated`, `function.valves_updated`, `function.deleted`, `tool.deleted`, `chat.created`, `config.banners.updated`. Adds `core`.

## chat_data

Save and read a JSON value that lives with a chat, under a key of the plugin's own, in that chat's metadata, so it is deleted with the chat.

- `await plugin_chat_read(chat_id, key)`
- `await plugin_chat_write(chat_id, value, key)`
- `await plugin_chat_update(chat_id, change, key, default=None)`: locked read-modify-write; `change` is a function (sync or async) from the old value to the new one.
- `plugin_chat_is_temp(chat_id)`: temporary chats have `local:` ids and no database row; their values are kept in memory until restart.
- `ChatNotSaved`: raised for a chat with no row yet; its message is what a model sees ("send a message first, then retry").

Only the plugin's own key is set, in place; the rest of `meta` is not rewritten and `updated_at` is left alone, so a write does not reorder the chat list. `key` goes into SQL, so it must be a plain identifier (`[A-Za-z_][A-Za-z0-9_]{0,63}`). SQLite (`json_set`) and PostgreSQL (`jsonb_build_object`) are both handled. A function bundle and its tool bundle share the temporary-chat store through `sys.modules`.

## static

Added automatically (with `routes`) when the plugin has a `static/` folder. Every file is served as it is at `<prefix>/<path>` with no code: a content type, an `ETag` (a matching `If-None-Match` gets 304), `Cache-Control: no-cache` and `nosniff`. The prefix defaults to `/<plugin id>`. It is the Flask and Django convention: `static/` is served, [`templates/`](#templates) is not.

**Who may fetch them** is `static: {access: user | admin | public}` in `plugin.yaml` (`user`, any signed-in user, is the default). They go through the same guard as every mounted route, including the sign-in handling in [routes](#routes), and answer 404 once the function is disabled. `public` is for files that must be fetched by someone who cannot sign in (an iframe that sends no cookies, a script another site includes); say it only for files that are meant for anyone, since they are then reachable by anyone who can reach the URL.

**A plugin with a single page puts it at `static/index.html`.** It is served at `<prefix>/` (and `<prefix>` redirects there with a 307, so relative links such as `app.js` resolve). Other pages and assets sit beside it. A page that needs per-request data, or a per-resource check, is not served as a file: it is a [template](#templates) that the function renders at a route it chooses (the `stale_data` plugin does this, behind `user: PluginAdmin`, at its configurable `DASHBOARD_PATH`; Excalidraw's editor at `/excalidraw/view/<chat_id>` is one per chat).

- `plugin_static_files()`: the paths served, sorted.
- `plugin_static_serve(router, prefix=None)`, `plugin_static_ensure(app=None)`: mounting; `ensure` runs on load and can be called again with `request.app` if the app was not there yet. The mount is named `static`.

## templates

Added automatically when the plugin has a `templates/` folder (no manifest key). The files are embedded in the function bundle as JSON, so they can hold any quotes or backslashes, and are **never served**: the function reads one with `plugin_template_text("page.html")` and renders it. There is nothing to declare and nothing to guard, because nothing is reachable until the function chooses to return it from a route it has guarded.

- `plugin_template_text(path)`: a file as text. `plugin_template_bytes(path)`: as bytes (binary files are stored as base64). `plugin_template_files()`: the paths, sorted. A missing path raises `FileNotFoundError`.
- Function bundle only; a tool bundle does not get them.
- Reads come from memory, so a route may call them on every request.

```python
PAGE = plugin_template_text("page.html")  # templates/page.html, filled in per request below
```

## assets

The Shared Assets Protocol lets any number of plugins add JavaScript and CSS to every page by contributing *fragments* of two shared files, `/static/loader.js` and `/static/custom.css`. This library publishes a plugin's fragments **from files**, so the script and the stylesheet are not Python strings:

```
plugins/page_banners/
  plugin.yaml
  function.py        optional: class Event(PluginAssets), only for what must run on the server
  assets/
    loader.js        this plugin's fragment of /static/loader.js
    custom.css       this plugin's fragment of /static/custom.css
```

A folder with `assets/` adds the [`shared_assets`](#shared_assets-and-live_reload) block, `core` and this library. With no `function.py`, `owpp` generates `class Event(PluginAssets)`, so a plugin that is only a stylesheet is `plugin.yaml` plus `assets/custom.css`. [`page_banners`](../examples/plugins/page_banners) is the worked example: a variant of Classic298's Better Banners, with the script and the stylesheet as files and a `function.py` of about sixty lines.

What the library does, so you do not write it:

- **Publishes** each file as a fragment keyed by this function's id (the protocol's rule), from the Event's handler. The markers are `// owui:<id>:start`/`:end` (`/* ... */` in CSS). `order` comes from the manifest's [`assets:`](plugin-format.md#assets-and-the-assets-folder) key.
- **Wraps `loader.js`** so you write only its body. All plugins' fragments end up in one `/static/loader.js`, so the protocol asks each to run in its own function with a `try/catch`; `owpp` generates exactly that, in strict mode:

  ```js
  (function () {
    "use strict";
    try {
  /* your assets/loader.js, as written */
    } catch (e) {
      console.error("[<plugin id>]", e);
    }
  })();
  ```

  So **do not write your own `(function () { ... })()` or `'use strict'`** in the file (it would be wrapped twice). A top-level `const` or `let` can no longer clash with another plugin's, an early `return` works, and a runtime error in your code is logged instead of stopping every plugin after it. Two things it cannot do: a **syntax error** still stops the whole shared file (the browser fails to parse it before any `try` runs), so check the script; and a top-level `function` or `var` is now local, so share something on purpose with `window.myThing = ...`. Guard code that must run once, since a clone of the plugin has its own fragment (`if (window.__myPlugin) return; window.__myPlugin = true;`). The wrapper is not minification or obfuscation: the file is served readable. `assets: {wrap: false}` serves it exactly as written, for a script that has to be top-level.
- **Switches off** by returning `""` (the protocol's only way to withdraw a fragment) when the function is disabled, and calls `asset_withdraw_deleted` so a deleted plugin's fragments go too.
- **Fills `__NAME__` placeholders** from `asset_vars()`, so a valve can reach the script or the stylesheet. The fragment is rebuilt only when the values change, because the producer runs on every page load.
- **Defines `register(app)`**, the function [`live_reload`](#shared_assets-and-live_reload) calls on every container.

```python
class Event(PluginAssets):
    class Valves(BaseModel):
        position: str = "top"

    def asset_vars(self) -> dict:  # fills __CONFIG__ in assets/loader.js; values are strings
        return {"CONFIG": json.dumps({"position": self.valves.position})}

    async def event(self, event=None, __event_name__="", __app__=None, **kwargs):
        await super().event(event, __event_name__=__event_name__, __app__=__app__, **kwargs)
        ...  # your own handling
```

- **Only the two files.** Any other file in `assets/` is an error: the protocol has no other paths. A page or template the function renders belongs in [`templates/`](#templates).
- **`include: [live_reload]`** (opt in) makes a code or valve change, or disabling the function, reach every container within a second. It needs Redis and Open-WebUI 0.11+; without Redis it does nothing extra.
- **Inline only.** The protocol notes that a `<script src>` or `@import` inside a fragment arrives after the app has started.
- A `function.py` must define `class Event(PluginAssets)`, or the bundle is refused. Function bundle only.

## config

A `config.yaml` next to `plugin.yaml` (added automatically) holds structured settings that ship with the plugin: per-item overrides, lists, nested options. `owpp` parses it when it bundles, so a mistake fails `owpp check` and a deployed plugin needs no YAML parser. It is read-only at runtime: change the file and redeploy.

- `plugin_config(defaults=None)`: the file laid over `defaults`. Mappings merge key by key; anything else (a list, a number, a string) is replaced. The result is a fresh copy.
- Keep the defaults in the function, so a plugin works with an empty `config.yaml`. The library exists only when the file does, so a function that calls `plugin_config()` must ship one (an empty file is fine).
- Scalars YAML would guess at stay text (`on`, `no`, `12:30`); only `true` and `false` are booleans.
- **Values may be environment templates** (`flag: ${MCPO_ENABLED:-true}`), resolved from the container's environment each time the file is read, and typed (see `plugin_env` in [core](#core)). The file is in git, so a secret goes in as a reference, `${NAME}`, never as text.
- Function bundle only.

**Config or valves?** Valves are for values an admin changes in the UI, one at a time, without a deploy. The config file is for structured data that belongs in git with the code. `mcpo_sync` keeps its URL and intervals as valves and its per-server name, description and `enable` overrides in `config.yaml`. (`function.valves` in `plugin.yaml` sets valves after a deploy; it cannot hold a structure.)

## shared_assets and live_reload

[Classic298's Shared Assets Protocol](https://github.com/Classic298/open-webui-plugins/tree/main/shared-assets-protocol), vendored unmodified (`ASSET_IMPL_VERSION` 5). `live_reload` must come first, and requires `shared_assets`. When several plugins in one process carry the protocol, the newest `ASSET_IMPL_VERSION` wins.

### Writing the registration yourself

`assets/` covers the usual case. When you need full control, include the libraries and call the protocol directly. The libraries are only the protocol's fixed part (the registry, the route, the live-reload listener), and they stay byte-identical in every plugin that carries them; everything that makes a plugin *its own* is yours:

| The plugin defines | Example |
| --- | --- |
| the path it contributes to | `LOADER_PATH` (`/static/loader.js`) or `CUSTOM_CSS_PATH` |
| its start and end markers | `// owui-<id>:start` and `// owui-<id>:end` |
| the producer: what the fragment contains | a prebuilt string; no I/O, no locks (it runs on every request) |
| `order` | lower composes first (default 0) |
| `register(app)` | calls `asset_register(...)`; must be idempotent; gate each producer on `reload_active(app)` |
| the hooks | `reload_bootstrap()` in `__init__`, `await reload_on_event(...)` in `event()` |

```yaml
include: [live_reload, shared_assets]   # in this order
```

Two other ways to use an existing protocol plugin:

- **Unchanged, pinned.** `source: {git, ref, path}` with `function: {file: event.py}` bundles the upstream file verbatim, so the deployed code is exactly the pinned commit. Such a file already carries its own copy of both blocks; the bundler sees their end markers and inserts nothing twice.
- **Native.** Move the header into `plugin.yaml`, delete the two blocks, and put the script and the stylesheet in `assets/`: [Better Banners](https://github.com/Classic298/open-webui-plugins/tree/main/better-banners) (a 46 KB single file) becomes `assets/loader.js`, `assets/custom.css`, a `function.py` of valves and one hook, and a manifest. That is what [`page_banners`](../examples/plugins/page_banners) is.
