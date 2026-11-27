# Authoring a plugin

## Start with `owpp create`

```sh
uvx owpp create
```

The wizard scaffolds the plugin, with stubs, tests and a README for you to fill in. The code can be written here (a filter, action, event or pipe, or an installer of a tool and skills). It can also come from a git repository, pinned to a commit. See [creating a plugin](creating.md).

## Pick the function type first

The type sets how the function runs, and if `global` applies to it. [Plugin format](plugin-format.md#function-type) has the table of types.

- Does it change a chat request or reply, or add something to a message? **Filter.**
- Is it a button that the user pushes on a message? **Action.**
- Does it react to Open-WebUI itself (startup, enable, valve change)? Does it run on a schedule, or serve its own routes with no chat? **Event.** Events do not use `global`.
- Is it a model? **Pipe.**

A **filter** that serves HTTP routes (Excalidraw) mounts them when the filter loads. For a global filter, that is at startup. An **event** that serves routes mounts them on `system.startup.completed`, `function.enable_started`, `function.updated` and `function.valves_updated`.

## Conventions every plugin follows

1. **One function class**: `Pipe`, `Filter`, `Action` or `Event`.
2. **Each file imports what it uses**, as ordinary Python. It imports the libraries with `from owpp.lib import ...`, and the names of `shared.py` with `from shared import ...` ([bundling](bundling.md#imports-between-the-files)).
3. **The header is in the manifest**, not in the code, for code that is in this repository. Put long text in a comment, not in the header.
4. **Valves are `UPPER_SNAKE`**, each with a description. `owpp check` gives a warning for a valve without one. A sync event subclasses `PluginScheduledSync`, which adds the `ENABLE` and `SYNC_INTERVAL_MINUTES` valves. The interval is 60 by default, and 0 runs the sync only on events.
5. **Use the libraries. Do not copy them.**
    - Routes: `plugin_mount`.
    - Repeated work: `plugin_every` or `PluginScheduledSync`.
    - Per-chat data: `chat_data`.
    - Static files: `static/`.
    - Pages that the function renders: `templates/`.
    - "Is the function still enabled?": `plugin_is_active`.
    - Stored valves: `plugin_stored_valves`.
6. **One page is one file.** A page that is only a file goes in `static/` with its assets, and its index is at `<prefix>/`. A page that needs data or an access check for each request is a file in `templates/`. The function reads it with `plugin_template_text()` and renders it behind a guarded route. It is never served raw. HTML is not kept in Python strings.
7. **Handle events with `@on`.** Use `include: [events]`, `class Event(PluginEvents)` and `@on("function.valves_updated", own=True)` on a method. Do not write an `event()` full of `if __event_name__` checks. `owpp check` finds a mistyped event name.
8. **Stop when disabled.** Routes answer 404 (the guard of `plugin_mount`), and jobs stop by themselves. The runtime removes the tools and skills that it installed.
9. **Own only what you made.** Mark what a sync writes (`managed_by`), and change only those objects.
10. **Log with a fixed prefix** (`"My Plugin: ..."`), so that you can find the lines of a plugin.
11. **Make a public route only when you must.** [Public is deliberate](#public-is-deliberate) gives the rules.
12. **Pin third-party code** by full commit SHA, and review it before the SHA moves. `owpp pull` moves the SHA, and you review and commit the change.

### Public is deliberate

Each route needs a signed-in user. `plugin_mount` enforces this for each route and for the `static/` files, so mount all routes with it.

- **A route that shows the data of other users:** mark it `user: PluginAdmin`.
- **An admin route:** mark the handler, for example `async def purge(user: PluginAdmin)`.
- **A mount where all routes are for admins only:** use `plugin_mount(..., access="admin")`. For the static files, use `static: {access: admin}`.
- **A route about one chat:** give it `chat_id: WritableChat` or `ReadableChat`. This checks that the user can get access to that chat.
- **A route for people who are not signed in:** put it on a mount of its own with `access="public"`, or use `static: {access: public}`. Write these exact words. `owpp check` lists each one, so keep them few.

For a check that these cannot do, the function uses the `user` that it gets.

## Steps

1. Make the plugin with `owpp create`. You can also use `owpp init <id> --type event|filter|action|pipe`, or write `plugins/<id>/plugin.yaml` and `function.py` yourself. The manifest needs a `function:` section.
2. Add `tool.py`, `shared.py`, `skills/`, `static/`, `templates/` or `include:` only when the plugin needs them.
3. Run `owpp check <id>`, and fix what it reports until it is clean.
4. Add tests ([writing a test](testing/writing.md)). Test through the mock, or test pure logic with `plugin_source()`.
5. Put each Open-WebUI import inside the function that uses it.
6. Write the README ([below](#documentation-the-readme-every-plugin-has)). Add to it the checks to do on a live instance. `owpp init` starts a README with the required sections.
7. Run `owpp deploy --only <id> --dry-run`.
8. Deploy, or merge the change if CI deploys.

## Documentation: the README every plugin has

`owpp init` writes these headings. To make them mandatory, add a test such as `test_every_example_documents_how_to_test_and_deploy_itself` in this repository's `tests/test_bundle.py`.

- **A description:** what the plugin does, which libraries it uses, and what it changes in Open-WebUI.
- **Settings:** the valves, and each environment variable or external setup that the deploy cannot do. A plugin that shows a page in the Artifacts panel says that it needs **iframe Sandbox Allow Same Origin**, and what that costs ([libraries](libraries.md#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin)).
- **`## Test`:** how to check the plugin offline (`owpp check <id>`, `owpp bundle <id>`), what your tests cover, and the steps to verify it on a live Open-WebUI.
- **`## Deploy`:** its function type, how it is deployed (CI on merge, or `owpp deploy --only <id>`), and what it needs before the deploy.

For a plugin taken from git, the README also gives the origin of the code, the pinned commit, and how to review an upgrade.

## Checklist

- [ ] exactly one function class; `global` only on a filter or action
- [ ] header keys in `plugin.yaml`, one line each
- [ ] libraries through `include:` and `from owpp.lib import ...`, no pasted copies
- [ ] each file imports what it uses
- [ ] when the function is disabled, its routes and jobs stop
- [ ] `owpp check <id>` passes
- [ ] the README has Test and Deploy sections
- [ ] routes that show data have an access check
- [ ] a page in the Artifacts panel: the README gives the same-origin requirement and its cost
- [ ] remote code pinned to a full SHA
- [ ] a change has a new version (`owpp version <id> patch`, and a CHANGELOG.md entry); `owpp check --since origin/main` passes
