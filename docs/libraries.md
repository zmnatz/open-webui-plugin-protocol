# Libraries

A library is built-in code that owpp links into a plugin's bundle. Each library is a plain Python file in `src/owpp/runtime/lib/`. A plugin gets a library when `include:` lists it. It also gets one when the plugin holds something that turns it on, such as a `static/` folder. Libraries sit above the plugin's code in the bundle ([order](bundling.md#order)).

The libraries are **vendored**: the bundle contains a copy, so a plugin has no runtime dependency on owpp. When you upgrade owpp, the next deploy puts the new library code into every plugin that uses it.

Private names in a library start with `_`, so that they do not collide with plugin code. Most public names start with `plugin_`. Each file ends with a marker comment, such as `# end plugin core library`. The bundler does not add a library whose marker is already in the code.

A plugin imports what it uses from **`owpp.lib`**, which re-exports every library's public names:

```python
from owpp.lib import PluginAdmin, plugin_mount
```

The import is for your editor and your tests. Open-WebUI does not have owpp, so the bundler removes the line and puts the library above your code. The bundle must have the library of each name you import. [Imports between the files](bundling.md#imports-between-the-files) gives the forms of import that the bundler accepts.

The libraries import each other relatively (`from .plugin_core import plugin_app`), and the bundler removes those imports too. A library that carries data gives its data placeholder a default (`__CONFIG_DATA__ = '{}'`), so you can import it alone. In a bundle, the plugin's data replaces the default.

| Library | Adds |
| --- | --- |
| [`core`](#core) | function id, app, is-enabled, stored valves, environment templates |
| [`routes`](#routes) | mount a FastAPI router that survives reloads |
| [`jobs`](#jobs) | background and repeating jobs, one worker per period |
| [`chat_data`](#chat_data) | JSON values saved with a chat |
| [`events`](#events) | `@on("event.name")` handlers instead of an `event()` full of `if` checks |
| [`static`](#static) | files from `static/`, served as they are |
| [`templates`](#templates) | files from `templates/`, embedded and rendered by the function, never served |
| [`config`](#config) | a `config.yaml` shipped with the plugin, parsed at bundle time, read with `plugin_config()` |
| [`assets`](#assets) | `assets/loader.js` and `assets/custom.css` published as this plugin's fragments of the Shared Assets Protocol |
| [`shared_assets`, `live_reload`](#shared_assets-and-live_reload) | Classic298's Shared Assets Protocol, unmodified |

A library brings in the libraries it is built on. Some plugin content turns a library on without `include:`. When the site is built, this table is generated from the library catalogue (`src/owpp/libraries.py`):

<!-- library catalogue -->

## core

- `plugin_function_id()`: returns this function's id, from the module name `function_<id>_<32 hex>`. Outside Open-WebUI it returns `None`.
- `plugin_app()`: returns Open-WebUI's FastAPI app. Before Open-WebUI imports the app, it returns `None`.
- `await plugin_is_active(function_id=None)`: tells you whether the function is still installed and enabled. Use it to decide when to stop work. If it cannot tell (no id, or a failed lookup), it returns **True**. To stop work after a short fault is worse than to continue.
- `await plugin_stored_valves(valves_cls, function_id=None, ttl=0)`: returns the valves as the database stores them. A running instance applies valves only when it handles an event or a chat, so routes and jobs must read them here. `ttl` reuses a read for that many seconds (for a page that polls).
- `plugin_env(value)`: resolves **environment templates** (`${NAME}`, `${NAME:-default}`) from the Open-WebUI container's environment. [Environment templates](plugin-format.md#environment-templates) gives the rules for defaults, value types and `$${`.
    - It accepts a string, or a dict or list. In a dict or list, it resolves the strings and leaves the keys alone.
    - A template inside a longer string, with no value and no default, becomes empty text, with a warning.
    - `jobs:` in `plugin.yaml` and `config.yaml` use it for you. For a value in code, call it yourself.

## routes

**Every route requires a signed-in user, unless a mount says `public` in so many words.** Any signed-in user can open a route. If a route needs more, **mark** it. Do not write the check in its handler.

You set the access level on a route (a marker) or on a mount (`access=`). For the `static/` files, you set it in [`static:`](plugin-format.md#static-and-the-static-and-templates-folders). There is no plugin-wide setting.

`plugin_mount(app, router, prefix, owner=None, name="", access=None, guard=None) -> int`

### What the guard does

`plugin_mount` puts a guard on every route it mounts, the `static/` files included. For each request, the guard does these checks in order:

1. If the function is disabled, it answers **404**. It does this before it asks who you are, so a disabled plugin reveals nothing.
2. It requires a signed-in user. The session is Open-WebUI's own: a bearer header, else its `token` cookie. A pending account is not signed in.
3. If the access level is `admin` and the user is not an admin, it answers **403**.

A person who opens a plugin's address directly can have no session cookie yet. Many sign-ins occur by themselves when the app's home page loads: a proxy's trusted headers, authentication switched off, or an OIDC session at the identity provider.

For a browser navigation (a `GET` that asks for HTML) with no session, the guard therefore does this:

1. It **tries the sign-ins that need no input**. It calls Open-WebUI's own sign-in endpoint with empty credentials and the request's headers. The login page does the same for trusted-header and no-auth setups. The call runs inside the app, with no socket, so no host, port or TLS setting can be wrong.
2. If the sign-in works, it continues as that user. It also gives the session cookie to the browser, so the next request has one.
3. If not, it **sends the browser to Open-WebUI's login page** (`/auth?redirect=<where they were going>`). The login page handles OIDC, LDAP and passwords, then sends the person back. The target keeps the query string, and is always a plain path on this site.

The guard cannot do an OIDC or LDAP sign-in itself: those need a redirect to the identity provider, or a password. For this reason, its last step is the login page and not an error.

Other requests never get a redirect:

- An **iframe** (such as the Artifacts panel): the guard tries the automatic sign-in, and otherwise answers **401**. A login page inside a sandboxed panel is no use. With Open-WebUI's default settings, the panel sends no session at all, so the sign-in usually fails there ([below](#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin)).
- An **API call or fetch** (a request that does not ask for HTML): the guard answers a plain **401**, and never creates a session for it.

### Mounts

- `access` is the mount's level: `"user"` (the default), `"admin"` or `"public"`. Any other value, `"Public"` and `True` included, raises `ValueError`. So a typo cannot open a mount.
- `name` identifies a mount. If you mount a name again, the new mount replaces the earlier one, at any prefix. For example, if a configurable path changes, the old path goes away.
- Mounts with different names never replace each other (the static files, a page, an API). Give each mount of a function its own name. Two mounts without a name count as one.
- A mount replaces only this function's own routes, also those from an earlier load. It never removes Open-WebUI's routes. Without this, Starlette keeps the old handler until a restart.
- To remove a mount's routes, mount an **empty** router with its name.
- A mount moves its routes ahead of Open-WebUI's catch-all mount at `/`, which otherwise takes the requests for routes added later.
- `plugin_mount` refuses the prefix `/`. It returns the number of routes in the router.

### Mark a route

To mark one route, type a parameter of its handler:

```python
@router.get("/purge")
async def purge(user: PluginAdmin):  # admin-only; `user` is the signed-in admin
    ...


@router.get("/mine")
async def mine(user: PluginUser):  # any signed-in user; `user` is that user
    ...
```

`PluginUser` and `PluginAdmin` are ordinary FastAPI `Annotated` dependencies. The handler receives the user, an object with `.id` and `.role`.

A marker **only tightens** what the mount requires. `PluginAdmin` makes one route admin-only. `PluginUser` on a route of an `access="admin"` mount does not open the route, because the mount's guard still applies. No marker makes a route public. All the guards of one request share the session lookup.

If **every** route of a mount is admin-only, use `plugin_mount(..., access="admin")` instead of a marker on each route. A route that you add later is then admin-only by default. Otherwise, mark each route that needs more than a signed-in user.

### Public mounts

**`access="public"` serves people who are not signed in.** The guard does no session lookup, sign-in attempt or redirect. It still answers 404 when the function is disabled.

The level applies to every route of the mount. Give a public endpoint (a webhook, an OAuth callback, a health check) a mount of its own, with its own `name`. Keep public mounts few.

A marker on a route of a public mount still applies: `user: PluginUser` there requires a signed-in user. A handler can ask who is there, if anyone, with `plugin_user(request)`. `owpp check` lists every public mount as a `note`, so that a reviewer sees it.

### Mark a route by its chat

For a route about one chat, type the chat's path parameter:

```python
@router.get("/view/{chat_id}")
async def view(chat_id: WritableChat):  # signed in, and can write to this chat; receives the id
    ...


@router.get("/export/{chat_id}")
async def export(chat_id: ReadableChat):  # signed in, and can read this chat
    ...
```

`ReadableChat` and `WritableChat` check the signed-in user with Open-WebUI's own chat access (`Chats.has_chat_access`). The handler receives the chat id.

- Without access, the answer is **404**, not 403, so that the route does not reveal that the chat exists.
- Without a signed-in user, the answer is 401.
- A temporary chat (`local:...`) has no stored record, so any signed-in user passes. Do not keep private data in one, because the guard cannot check who owns it.
- `plugin_chat_guard(permission, param="chat_id")` builds the same dependency for a path parameter with another name.
- A route that does not have the path parameter fails with a 500 error.

For example, `stale_data` marks its one route `user: PluginAdmin`, and Excalidraw's page takes `chat_id: WritableChat`.

### Other functions

- `await plugin_user(request, token=None)`: returns the signed-in user or `None`, for code that has the request but no marked parameter. `token` is a session token to use instead of the request's own.
- `plugin_guard(access=None)`: the dependency behind the markers and the mount.
- `await plugin_require_active(function_id=None)`: raises 404 if the function is not enabled. The guard calls it for you. Do not use it directly as a dependency, because that exposes `function_id` as a query parameter.

FastAPI resolves a dependency's annotations by name. If a module uses postponed annotations, FastAPI cannot resolve a type that you import *inside* a function. It then reports the parameter as a required query parameter (422). In a dependency's signature, use only module-level types (`Request`), and build the other values in the code.

### The one exception: `guard=`

Some routes cannot carry an Open-WebUI session, such as an API that a sandboxed iframe calls without cookies. Such a mount can pass its own FastAPI dependency as `guard`. It replaces the sign-in check for that mount only. The function must still be enabled. You cannot use `guard` and `access` together.

Make your guard verify a credential that was **created from a real login**. The library cannot check this for you. Keep the page that creates the credential behind the normal guard. That page needs a session. Inside the Artifacts panel, it gets one only with **iframe Sandbox Allow Same Origin** on ([below](#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin)).

`plugin_token(subject, hours=12)` and `plugin_check_token(token, subject)` give you that credential. It is a short-lived signed token for one subject (a chat id, for example). It expires. It is stateless, so every worker agrees. Only this function accepts it: another plugin's tokens never pass. To use it:

1. Create the token inside the signed-in page that loads the iframe.
2. In the API's guard, call `plugin_check_token`.

Excalidraw does this. Its page needs a login and a writable chat, and its API takes the token that the page received.

### Routes that skip the guard

`owpp` refuses a `function.py` or `shared.py` that adds a route without the guard, or changes the app's route list:

- a call to `include_router`, `add_api_route`, `add_route`, `add_api_websocket_route` or `mount` on the app (`app`, `__app__`, `application`, `request.app`, `app.router`);
- a change to `app.routes` or `app.router.routes`: `insert`, `append`, `extend`, `remove`, `pop`, `clear`, `sort`, `reverse`, `=`, `+=` or `del`.

Such code adds routes that the guard never sees, or removes Open-WebUI's own routes. Mount with `plugin_mount` instead. It also removes the routes that an earlier load mounted. Code can still read the route list.

This check finds the usual patterns and mistakes in the plugin's own code. It does not stop an author who avoids it on purpose (`r = app.routes; r.insert(...)`). A plugin runs with Open-WebUI's rights either way, so a reviewer must read its code ([reviewing](reviewing.md)).

### Pages in the Artifacts panel need "iframe Sandbox Allow Same Origin"

A filter can put an `<iframe>` in a reply to show a plugin's page in the Artifacts panel, as Excalidraw does. The panel is a **sandboxed iframe**. What it can do depends on a per-user Open-WebUI setting, **iframe Sandbox Allow Same Origin**. The setting is **off by default** (v0.13.4 and v0.13.5):

| Setting | The frame's origin | The page behind the guard | Measured on v0.13.4 and v0.13.5 |
| --- | --- | --- | --- |
| off (default) | opaque | Gets no session. The browser does not send the `token` cookie (`SameSite=Lax`), so the guard answers **401**. | `{"detail":"Sign in to Open-WebUI first."}` |
| on | Open-WebUI's own | Gets the session like any page, and can create a `plugin_token` for its API. | 200 |

So **`guard=` covers the API, not the page.** A signed-in user must load the page, so that it can create the token. Inside the panel, this occurs only with the setting on. This library cannot change that, because Open-WebUI controls the panel's sandbox.

**Caution: the setting applies to every artifact, not only yours.** With it on, script in any HTML that a model writes runs with Open-WebUI's origin. The script can read the sign-in token that Open-WebUI keeps in `localStorage`, and call the API as the user. A prompt injection that makes a model write such an artifact would work. No plugin can narrow this Open-WebUI permission. Inline Visualizer needs the same setting for live rendering, and its upstream documents it the same way.

**If your plugin shows a page in the panel, do these things:**

- **State the requirement and its cost in your README.** Excalidraw's README is the model.
- Give both ways to turn the setting on. A user can turn it on under **Settings > Interface**. An admin can set it for everyone under **Admin Settings > General > Default Interface Settings** (`DEFAULT_INTERFACE_SETTINGS='{"iframeSandboxAllowSameOrigin": true}'`). A user's own setting still wins.
- Say that the setting is only for instances where you trust what models put into artifacts.
- Declare it in [`requires:`](plugin-format.md#requires), so that `owpp deploy` warns when it is off.
- **Keep the page behind the normal guard.** Do not make it `public`, and do not put a token in the iframe's address.
- **Know which requests are cross-origin.** With the setting on, calls from the page to the plugin's routes are same-origin and need no CORS header. A host that serves files to the page needs `Access-Control-Allow-Origin: *` (Excalidraw's [self-hosting](examples/excalidraw.md#self-hosting-the-editor) section).

We considered both of those workarounds for Excalidraw and refused them:

- A token in the address goes into the chat's stored HTML, where anyone who can read the chat can read it. The token has also expired when someone reopens an old chat, unless it lasts so long that it is a permanent link.
- A public page can ask the parent window for a credential over `postMessage`, but Open-WebUI does not answer ([issue #6](https://github.com/zmnatz/open-webui-plugin-protocol/issues/6)).

We will review this if Open-WebUI gives artifacts a way to get a scoped credential.

## jobs

- `await plugin_claim(key, ttl_seconds) -> bool`: returns true to exactly one caller across all workers during the ttl. It uses Redis `SET NX EX` through `app.state.redis` when present, else a map in the process. The ttl is at least 1 second, and also works as a cooldown.
- `await plugin_unclaim(key)`: cancels a claim whose work never ran.
- `plugin_spawn(name, factory, on_skip=None)`: runs an async `factory()` in the background. Each process runs one job at a time per function. If a job is already running, it skips the new one and calls `on_skip`.
- `plugin_every(name, seconds, factory, first_after=None)`: repeats a job on one worker per period (a claim). It stops when the function is disabled or deleted, which it checks each period. A second call with the same name **replaces** the earlier loop, so you can call it on every load. It needs a running event loop.
- `plugin_stop_jobs()`: cancels this function's repeating jobs.
- `class PluginScheduledSync`: a base class for an Event function that repeats one job, `class Event(PluginScheduledSync)`. See [scheduled sync](#scheduled-sync).
- `plugin_sync_markers() -> set[str]`: returns the `managed_by` markers that a sync treats as its own when it replaces and prunes. These are the function id, plus the [`jobs: adopt_markers`](plugin-format.md#jobs) of `plugin.yaml`. The set is empty when the function id is unknown, so that nothing matches by accident. Mark what you write with the function id, and use this set to test ownership.

Open-WebUI reloads functions. A new load replaces the old load's loops and does not double them, because the state is in a `sys.modules` entry.

**Multiple workers.** The guarantee of one worker per period depends on `app.state.redis`. Without Redis, each worker process runs its own loop.

### Scheduled sync

Define `async def sync(self)` in your `class Event(PluginScheduledSync)`. The class runs `sync()` at these events: `system.startup.completed`, `function.enable_started` and `function.valves_updated` (the last two for this function only). It then repeats `sync()` every `SYNC_INTERVAL_MINUTES` minutes. With `0`, `sync()` runs only at those events.

The class adds the `ENABLE` (bool) and `SYNC_INTERVAL_MINUTES` (int) valves to your `Valves`. [`jobs:`](plugin-format.md#jobs) in `plugin.yaml` sets the default interval. To change a valve's description or default, define the valve yourself.

When `ENABLE` is off, each event stops the jobs, and no `@on` handler of the class runs.

It is a [`PluginEvents`](#events) class, so your own `@on` handlers work with it.

## events

Use a decorator to give each of Open-WebUI's lifecycle events a handler. An Event function then does not need one `event()` method full of `if __event_name__ ...` checks:

```python
class Event(PluginEvents):
    @on("system.startup.completed")
    async def started(self): ...

    @on("function.enable_started", "function.updated", "function.valves_updated", own=True)
    async def reload(self, app):  # takes the arguments it names
        ...
```

- **`@on(*names, own=False)`** marks a method as the handler for those events. With `own=True`, the handler ignores events about *other* functions. An event with no subject, such as startup, still counts.
- You can stack decorators. Several handlers can listen to one event, and they run in definition order. A subclass inherits its parent's handlers.
- **Arguments by name.** A handler can take any of `event` (the event dict), `name`, `id` (this function's id), `app` and `request`. It can be sync or async. `app` is the `__app__` that Open-WebUI passed, else `request.app`, else the app that `plugin_app()` finds.
- **A handler that fails does not stop the others**, or the next base class. The library logs the error, and the other handlers run.
- **Valves.** The class creates `self.valves` from its `Valves`, so you do not need an `__init__` for that. If you write one, call `super().__init__()`.
- **Other base classes.** `PluginAssets` and `PluginScheduledSync` are `PluginEvents` classes and bring this library in. So `@on` works in them, and you can combine them (`class Event(PluginAssets, PluginScheduledSync)`). Each one passes events on to the next, except [a scheduled sync that is off](#scheduled-sync). If you override `event()`, call `await super().event(...)`.

`owpp check` checks your handlers:

- Event names must be strings, or module-level string constants.
- It refuses a value that does not look like an event name.
- It refuses a likely typo of a known name, and suggests the correct name. For example, `function.valve_updated` never fires: did you mean `function.valves_updated`?
- It accepts a new name that looks correct (`function.created`), because Open-WebUI adds events.
- It refuses a class that has `@on` handlers but does not inherit `PluginEvents`, because nothing calls them. It cannot tell this for a class with a base class from another file, so it accepts that one.

Known events: `system.startup.completed`, `function.enable_started`, `function.disable_started`, `function.enabled`, `function.disabled`, `function.updated`, `function.valves_updated`, `function.deleted`, `tool.deleted`, `chat.created`, `config.banners.updated`.

## chat_data

This library saves a JSON value with a chat, in the chat's metadata, under a key of your plugin. The value is deleted with the chat.

- `await plugin_chat_read(chat_id, key)`: returns the saved value, or `None`.
- `await plugin_chat_write(chat_id, value, key)`: saves a JSON value.
- `await plugin_chat_update(chat_id, change, key, default=None)`: reads, changes and writes the value under a lock. `change(current, is_new)` is sync or async. `current` is the saved value, or `default` when nothing is saved, and `is_new` says which. `change` returns the new value, or `None` to keep the old one. The call returns the value now in effect. The lock covers one process.
- `plugin_chat_is_temp(chat_id)`: temporary chats have `local:` ids and no database row. Their values stay in memory until a restart.
- `ChatNotSaved`: raised for a chat that has no row yet. The model sees its message ("send a message first, then retry").

A write sets only your plugin's key, in place. It does not rewrite the rest of `meta`, and does not change `updated_at`, so the chat list keeps its order. The `key` goes into SQL, so it must be a plain identifier (`[A-Za-z_][A-Za-z0-9_]{0,63}`). Use a different key in each plugin, such as the plugin id.

The library works with SQLite (`json_set`) and PostgreSQL (`jsonb_build_object`). A function bundle and its tool bundle share the store for temporary chats through `sys.modules`.

## static

A `static/` folder turns on this library. The library serves every file as it is at `<prefix>/<path>`, with no code in the plugin. Each response has a content type, an `ETag`, `Cache-Control: no-cache` and `nosniff`. A matching `If-None-Match` gets 304. The default prefix is `/<plugin id>`. As in Flask and Django, `static/` is served and [`templates/`](#templates) is not.

[`static:`](plugin-format.md#static-and-the-static-and-templates-folders) in `plugin.yaml` sets **who can fetch the files**. By default, any signed-in user can. The files go through the same guard as every mounted route, with the [sign-in steps](#what-the-guard-does). They answer 404 when the function is disabled.

Use `public` only for files that are meant for anyone, because anyone who can reach the URL can then fetch them. It is for a caller that cannot sign in, such as an iframe that sends no cookies, or a script that another site includes.

**A plugin with a single page puts it at `static/index.html`.** The library serves it at `<prefix>/`, and `<prefix>` redirects there (307), so that relative links such as `app.js` resolve. Put other pages and files beside it.

A page that needs data for each request, or a check for each resource, is a [template](#templates). The function renders it at a route that it chooses. `stale_data` does this at its `DASHBOARD_PATH`, behind `user: PluginAdmin`. Excalidraw has one editor page per chat, at `/excalidraw/view/<chat_id>`.

- `plugin_static_files()`: returns the paths that are served, sorted.
- `plugin_static_serve(router, prefix=None)`: adds the file routes to a router.
- `plugin_static_ensure(app=None)`: mounts the files, under the mount name `static`. It runs when the library loads. If the app was not there yet, call it again with `request.app`.

## templates

A `templates/` folder turns on this library, with no manifest key. owpp embeds the files in the function bundle as JSON, so they can hold any quotes or backslashes. The files are **never served**. The function reads one with `plugin_template_text("page.html")` and renders it. You do not declare or guard anything, because nobody gets a file until the function returns it from a guarded route.

- `plugin_template_text(path)`: returns a file as text.
- `plugin_template_bytes(path)`: returns a file as bytes. owpp stores binary files as base64.
- `plugin_template_files()`: returns the paths, sorted.
- A path that does not exist raises `FileNotFoundError`.

The function bundle gets every template. A tool gets templates only with `include: [templates]` under `tool:`, so that a function's pages are not copied into its tool. To give a tool only some of them, use [`tool.templates`](plugin-format.md#tool).

Reads come from memory, so a route can read a template on every request.

```python
PAGE = plugin_template_text("page.html")  # templates/page.html, filled in per request below
```

## assets

The Shared Assets Protocol lets any number of plugins add JavaScript and CSS to every page. Each plugin gives *fragments* of two shared files, `/static/loader.js` and `/static/custom.css`. This library publishes a plugin's fragments **from files**, so the script and the stylesheet are not Python strings:

```
plugins/page_banners/
  plugin.yaml
  function.py        optional: class Event(PluginAssets), only for what must run on the server
  assets/
    loader.js        this plugin's fragment of /static/loader.js
    custom.css       this plugin's fragment of /static/custom.css
```

An `assets/` folder turns on this library. If the plugin has no `function.py`, owpp generates `class Event(PluginAssets)`. So a plugin that is only a stylesheet is `plugin.yaml` plus `assets/custom.css`. A plugin that also has a tool or skills needs its own `function.py`. [`page_banners`](../examples/plugins/page_banners) is a worked example: a variant of Classic298's Better Banners, with a `function.py` of about sixty lines.

The library does these things for you:

- **It publishes** each file as a fragment keyed by this function's id (the protocol's rule), from the Event's handler. The markers are `// owui:<id>:start` and `:end` (`/* ... */` in CSS). [`assets:`](plugin-format.md#assets-and-the-assets-folder) in `plugin.yaml` sets the `order`.
- **It wraps `loader.js`**, so you write only its body. All the plugins' fragments go into one `/static/loader.js`, so the protocol asks each fragment to run in its own function with a `try/catch`. owpp generates that, in strict mode:

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

- **It switches off** the fragments of a disabled function: it returns `""`, which is the protocol's only way to withdraw a fragment. It also calls `asset_withdraw_deleted`, so that a deleted plugin's fragments go too.
- **It fills `__NAME__` placeholders** from `asset_vars()`, so that a valve can reach the script or the stylesheet. The values are strings. The library fills the placeholders in one pass and does not read the values again. So a value that holds another placeholder's text (a valve someone typed) is served as written. A `__NAME__` that `asset_vars()` does not return stays as it is.
- **It rebuilds a fragment** only when the values change. `asset_vars()` runs on every page load.
- **It defines `register(app)`**, which [`live_reload`](#shared_assets-and-live_reload) calls on every container.

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

Because of the wrapper, these rules apply to `loader.js`:

- Do not write your own `(function () { ... })()` or `'use strict'`, because the file would be wrapped twice.
- Check the script for syntax errors. A **syntax error** stops the whole shared file, because the browser fails to parse it before any `try` runs.
- A top-level `const` or `let` cannot clash with another plugin's. An early `return` works. A runtime error in your code is logged, and the plugins after yours still run.
- A top-level `function` or `var` is local. To share one on purpose, use `window.myThing = ...`.
- A clone of the plugin has its own fragment. Guard code that must run once: `if (window.__myPlugin) return; window.__myPlugin = true;`.
- The wrapper does not minify or obfuscate the file. The browser gets readable code.
- For a script that must be top-level, set `assets: {wrap: false}`. The library then serves it exactly as written.

These limits also apply:

- **Only the two files.** Any other file in `assets/` is an error, because the protocol has no other paths. Put a page or template that the function renders in [`templates/`](#templates).
- **`include: [live_reload]`** (you opt in) makes a code or valve change, or a disable, reach every container within a second. It needs Redis and Open-WebUI 0.11 or newer. Without Redis it does nothing extra.
- **Inline only.** The protocol notes that a `<script src>` or `@import` inside a fragment arrives after the app has started.
- A `function.py` must define `class Event(PluginAssets)`, or owpp refuses the bundle.
- The library is for the function bundle only.

## config

A `config.yaml` beside `plugin.yaml` turns on this library. It holds structured settings that ship with the plugin: overrides per item, lists, nested options. owpp parses the file when it bundles. So a mistake fails `owpp check`, and a deployed plugin needs no YAML parser. The settings are read-only at runtime. To change them, change the file and deploy again.

- `plugin_config(defaults=None)`: returns the file laid over `defaults`. Mappings merge key by key. Any other value (a list, a number, a string) replaces the default. The result is a new copy.
- Keep the defaults in the function, so that the plugin works with an empty `config.yaml`. The library exists only when the file exists. So a function that calls `plugin_config()` must ship the file; an empty file is sufficient.
- Only `true` and `false` are booleans. Values such as `on`, `no` and `12:30` stay text.
- A value can be an [environment template](plugin-format.md#environment-templates) (`flag: ${MCPO_ENABLED:-true}`). The function resolves it from the container's environment each time it reads the file.
- Do not write a secret in `config.yaml` as text, because the file is in git. Write a reference, `${NAME}`.
- The library is for the function bundle only.

**Config or valves?** Use a valve for a value that an admin changes in the UI, one at a time, without a deploy. Use `config.yaml` for structured data that belongs in git with the code. `mcpo_sync` keeps its URL and intervals as valves. It keeps the `name`, `description` and `enable` overrides for each server in `config.yaml`. `function.valves` in `plugin.yaml` sets valves after a deploy, but it cannot hold a structure.

## shared_assets and live_reload

These two libraries are [Classic298's Shared Assets Protocol](https://github.com/Classic298/open-webui-plugins/tree/main/shared-assets-protocol), vendored unmodified (`ASSET_IMPL_VERSION` 5). `live_reload` needs `shared_assets`: list it in `include:`, or let an `assets/` folder add it. The order in `include:` does not matter, because the bundler puts `live_reload` first. When several plugins in one process carry the protocol, the newest `ASSET_IMPL_VERSION` wins.

### Writing the registration yourself

`assets/` covers the usual case. For full control, include the libraries and call the protocol directly. The libraries hold only the protocol's fixed part: the registry, the route and the live-reload listener. That part stays byte-identical in every plugin that carries it. Your plugin defines everything that makes it *its own*:

| The plugin defines | Example |
| --- | --- |
| the path it contributes to | `LOADER_PATH` (`/static/loader.js`) or `CUSTOM_CSS_PATH` |
| its start and end markers | `// owui-<id>:start` and `// owui-<id>:end` |
| the producer: what the fragment contains | a prebuilt string; no I/O, no locks (it runs on every request) |
| `order` | lower composes first (default 0) |
| `register(app)` | calls `asset_register(...)`; must be idempotent; gate each producer on `reload_active(app)` |
| the hooks | `reload_bootstrap()` in `__init__`, `await reload_on_event(...)` in `event()` |

1. Include the libraries:

    ```yaml
    include: [live_reload, shared_assets]
    ```

2. Import the protocol's names from `owpp.lib`, as for any library: `from owpp.lib import CUSTOM_CSS_PATH, asset_register, reload_active, reload_bootstrap, reload_on_event`.
3. Define the parts in the table.

In a test, the names of `live_reload` need Open-WebUI: open a [test harness](testing/harness.md) first. The file imports `open_webui` at its top, so `owpp.lib` loads those names on first use.

There are two other ways to use an existing plugin that has the protocol:

- **Unchanged, pinned.** `source: {git, ref, path}` with `function: {file: event.py}` bundles the upstream file verbatim, so the deployed code is that of the pinned commit. Such a file carries its own copy of both blocks. The bundler sees their end markers and inserts neither block again.
- **Native.** Move the header into `plugin.yaml`, delete the two blocks, and put the script and the stylesheet in [`assets/`](#assets). `page_banners` is the result for [Better Banners](https://github.com/Classic298/open-webui-plugins/tree/main/better-banners) (a 46 KB single file): the two asset files, a `function.py` of valves and one hook, and a manifest.
