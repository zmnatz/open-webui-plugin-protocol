# Authoring a plugin

## Start with `owpp create`

```sh
uvx owpp create
```

A wizard that scaffolds the plugin: code written here (a filter, action, event or pipe, or an installer of a tool and skills) or taken from a git repository pinned to a commit, with stubs, tests and a README ready to fill in. See [creating a plugin](creating.md).

## Pick the function type first

The type decides how the function runs and whether `global` applies (see the table in [plugin format](plugin-format.md#function-type)).

- Does it change a chat request or reply, or add something to a message? **Filter.**
- Is it a button the user presses on a message? **Action.**
- Does it react to Open-WebUI itself (startup, enable, valve change), run on a schedule, or serve its own routes with no chat involved? **Event.** Events do not use `global`.
- Is it a model? **Pipe.**

A plugin that serves HTTP routes from a **filter** (Excalidraw) mounts them when the filter loads, which for a global filter is at startup. One that serves routes from an **event** mounts them on `system.startup.completed`, `function.enable_started`, `function.updated` and `function.valves_updated`.

## Conventions every plugin follows

1. **One function class**, one of `Pipe`, `Filter`, `Action`, `Event`.
2. **Every file imports what it uses**, as ordinary Python: the libraries `from owpp.lib import ...`, `shared.py`'s names `from shared import ...` ([bundling](bundling.md#imports-between-the-files)).
3. **Header in the manifest**, not in the code, for code that lives in the repo. Keep long text in a comment, not the header.
4. **Valves are `UPPER_SNAKE`**, each with a description (`owpp check` warns about one without). A sync-style event has `ENABLE` and `SYNC_INTERVAL_MINUTES` (default 60, 0 = only on events) and subclasses `PluginScheduledSync`.
5. **Use the libraries, do not copy them.** Routes go through `plugin_mount`, repeating work through `plugin_every`/`PluginScheduledSync`, per-chat data through `chat_data`, static files through `static/`, pages it renders through `templates/`, "am I still enabled" through `plugin_is_active`, stored valves through `plugin_stored_valves`.
6. **One page means one file.** A page that is just a file, with its assets, goes in `static/` (index at `<prefix>/`). A page that needs per-request data or a per-resource check is a file in `templates/`, which the function reads with `plugin_template_text()` and renders behind a guarded route; it is never served raw. HTML does not live in Python strings.
7. **Handle events with `@on`.** `include: [events]`, `class Event(PluginEvents)` and `@on("function.valves_updated", own=True)` on a method, not an `event()` of `if __event_name__` checks; `owpp check` catches a mistyped event name.
8. **Stop when disabled.** Routes answer 404 (the `plugin_mount` guard), jobs stop by themselves, installed tools and skills are removed by the runtime.
9. **Own only what you made.** Mark what a sync writes (`managed_by`) and touch only that.
10. **Log with a fixed prefix** (`"My Plugin: ..."`) so a plugin's lines can be found.
11. **Public is deliberate.** Every route needs a signed-in user. Mount with `plugin_mount`, which enforces that, `static/` files included, and mark a route that exposes other users' data `user: PluginAdmin`. Serving people who are not signed in takes `access="public"` on a mount of its own (or `static: {access: public}`), in those exact words; `owpp check` lists each one, so keep them few. An admin route is marked on the handler: `async def purge(user: PluginAdmin)`; a mount where every route is admin-only uses `plugin_mount(..., access="admin")`; the static files use `static: {access: admin}`. A route about one chat takes `chat_id: WritableChat` or `ReadableChat`, which checks that this user can reach that chat. Whatever those cannot express is still the function's, using the `user` it is given.
12. **Third-party code is pinned** by full commit SHA and reviewed before the SHA moves (`owpp pull` moves it; you review and commit).

## Steps

1. `owpp create` (or `owpp init <id> --type event|filter|action|pipe`, or write `plugins/<id>/plugin.yaml` with a `function:` section and `function.py` by hand).
2. Add `tool.py`, `shared.py`, `skills/`, `static/`, `templates/` or `include:` only when needed.
3. `owpp check <id>` until it is clean.
4. Add tests ([writing a test](testing/writing.md): through the mock, or `plugin_source()` for pure logic; keep Open-WebUI imports inside the functions that use them) and note any live checks in the README.
5. Write the README (below). `owpp init` starts one with the required sections.
6. `owpp deploy --only <id> --dry-run`, then deploy (or merge, if CI deploys).

## Documentation: the README every plugin has

Required headings (`owpp init` writes them; add a test like the example repo's if you want them enforced):

- A description: what it does, which libraries it uses, what it changes in Open-WebUI.
- Settings: valves and any environment variable or external setup the deploy cannot do. A plugin that shows a page in the Artifacts panel states that it needs **iframe Sandbox Allow Same Origin**, and what that costs ([libraries](libraries.md#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin)).
- **`## Test`**: how to check it offline (`owpp check <id>`, `owpp bundle <id>`), what your tests cover, and the steps to verify it on a live Open-WebUI.
- **`## Deploy`**: its function type, how it gets deployed (CI on merge, or `owpp deploy --only <id>`), and prerequisites.

For a plugin taken from git, also say where it comes from, the pinned commit, and how to review an upgrade.

## Checklist

- [ ] exactly one function class; `global` only on a filter or action
- [ ] header keys in `plugin.yaml`, one line each
- [ ] libraries via `include:` and `from owpp.lib import ...`, no pasted copies
- [ ] every file imports what it uses
- [ ] disabling the function stops its routes and jobs
- [ ] `owpp check <id>` passes
- [ ] README has Test and Deploy sections
- [ ] data-exposing routes are gated
- [ ] a page in the Artifacts panel: README states the same-origin requirement and its cost
- [ ] remote code pinned to a full SHA
- [ ] a change has a new version (`owpp version <id> patch`, and a CHANGELOG.md entry); `owpp check --since origin/main` passes
