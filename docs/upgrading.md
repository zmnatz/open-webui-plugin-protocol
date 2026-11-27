# Upgrading owpp

owpp copies the runtime and the libraries into each bundle, so a new owpp changes the code that you deploy. Do the upgrade on a branch, check it, and review the report of a dry run. Then deploy from the merged change.

## Steps

Caution: move all the pins before you migrate (CI, the action, your own computer). An older owpp refuses a manifest with a newer protocol.

1. **Move the pin.** Change the version in each place where you run owpp: `uvx owpp@0.7.2`, `uv tool install owpp==0.7.2`, or the action's `uses: zmnatz/open-webui-plugin-protocol@v0.7.2`.
2. **See what the migration changes:** run `uvx owpp@0.7.2 migrate --dry-run`.
3. **Migrate the manifests:** run `uvx owpp@0.7.2 migrate`. To migrate only some plugins, give their ids.

    ```sh
    uvx owpp@0.7.2 migrate --dry-run
    uvx owpp@0.7.2 migrate
    ```

4. **Check:** run `uvx owpp@0.7.2 check --strict`. It bundles each plugin as the deploy does.
5. **Do a dry run:** run `owpp deploy --dry-run` against your instance. It shows the functions, tools and skills that the new bundles will update.
6. **Commit** the pin and the manifest changes together.
7. **Deploy.**

`migrate` changes only what each version step changes, and it keeps comments and layout. It lists each file that it writes, and it does not change a manifest that is already at the current version.

`check` gives a note for each manifest that is still on an older protocol. It gives a warning for a manifest with no `protocol:` key, and `--strict` makes that warning a failure.

## 0.7 -> 0.8

- **Nothing to migrate.** The protocol does not change, and the bundles that a deploy writes are the same.
- **The tests run the real Open-WebUI.** `owpp test` runs each plugin on the [test harness](testing/harness.md): Open-WebUI v0.13.5 in the test process, in place of the mock ([why](adr/0004-unit-tests-run-the-real-open-webui.md)). The `owui` fixture keeps its calls.
- **Run the tests on Python 3.12**, the Python of Open-WebUI v0.13.5: `uvx --python 3.12 --from 'owpp[test]' owpp test`. On a different Python, `owpp test` stops and gives this command. The `test` extra now installs the packages of Open-WebUI's slim image, at Open-WebUI's versions. Your own test dependencies must agree with those versions.
- **The first run downloads Open-WebUI** (about 110 MB) to [`OWPP_CACHE_DIR`](environment-variables.md#owpp_cache_dir). Later runs use the cache. In CI, cache that folder.
- **Some tests need a change**, because Open-WebUI does what the mock did not:
    - The rows in `owui.tools`, `owui.models` and the other tables are copies. A change to a row, or `owui.tool_valves[...] = ...`, does not go into the database. Use `owui.set_tool_valves()`, Open-WebUI's models in `owui.run(...)`, or its API through `owui.client(owui.admin)` ([the rows are copies](testing/harness.md#state-to-set-up-and-assert-on)).
    - Access grants are Open-WebUI's `AccessGrantModel`s. Compare them with `grants(row)` from `owpp.testing`.
    - `owui.load()` switches the function on through Open-WebUI's API, so the function gets `function.enable_started` when it loads, as on a deploy.
    - Valves that Open-WebUI refuses raise `OwppError` with `HTTP 400`, not a `ValueError`.
    - `owui.client()` is an `httpx.Client`, not a Starlette `TestClient`.
    - `MockOpenWebUI` and `Record` are gone. Outside pytest, use `with Harness() as owui:` from `owpp.testing`.
- **The `open_webui` type stubs are gone.** An editor finds `open_webui` in the cached wheel: `owpp test --editor` gives its folder ([in an editor](testing/harness.md#in-an-editor)).

## 0.6 -> 0.7

- **Protocol 0.7.** `owpp migrate` sets `protocol: "0.7"` and changes nothing else. 0.7 changes no key, so a manifest that stays at 0.5 has the same meaning. `owpp check --strict` only gives a note for it. owpp 0.6 refuses a 0.7 manifest (see the caution in [steps](#steps)).
- **Live tests, if you want them.** [`owpp live`](commands/live.md) runs the `live/` tests of a repository on a throwaway Open-WebUI in Docker. Nothing changes for a repository without a `live/` folder. Tests in the browser need the `live` extra: run `playwright install chromium`, then `uvx --from 'owpp[live]' owpp live` ([live tests in your repository](testing/live.md#live-tests-in-your-repository)).
- **The deploy records `requires:`** in the `meta.requires` of each function, for [`owpp import --instance`](commands/import.md#what-owpp-put-into-it-taken-back-out). The deploy does not update a deployed function only for this key: the function gets it on its next update.
- **The Excalidraw example** (3.1.1) does not send a CORS header from its scene API now. A copy taken from this repository changes only if you `owpp pull` it.

## 0.5 -> 0.6

- **Nothing to migrate.** Manifests stay at `protocol: "0.5"`. 0.6 adds a key and removes none. The bundles that a deploy writes are the same as those of 0.5.0, unless a plugin uses the new key.
- **`tool: templates:`** lists the files of `templates/` that a tool embeds (`[launcher/]`). Without it, a tool that includes templates embeds all of them ([plugin format](plugin-format.md#tool)).
- **From 0.6.1, owpp refuses a plugin that edits `app.routes`** (`app.routes.insert(...)`, `app.routes[:] = ...`, `del app.routes[0]`, ...). Such a plugin added routes that the sign-in guard did not protect. `owpp check` gives the line. Mount those routes with `plugin_mount` ([libraries](libraries.md#routes)).
- **`asset_vars()` values are filled in one pass.** Thus a value that holds the text of another placeholder is served as it is written.
- **Plugin tests:** `owui.emit` also takes the subject itself, for events about users and models. The mock has `decode_token`, and the chat pipeline that a plugin calls to ask a model (`owui.model_reply`, `owui.completions`). A test that patched those stand-ins continues to work. It can use the stand-ins of the mock. (owpp 0.8 replaced the mock with the [test harness](testing/harness.md).)

## 0.4 -> 0.5

- **Each file imports what it uses** ([why](adr/0002-plugin-source-is-python.md)). Before 0.5, the libraries and the names of `shared.py` were already in scope in `function.py`, `tool.py` and `shared.py`. Now each file imports them, with `from owpp.lib import ...` and `from shared import ...`, and the bundler removes those lines ([bundling](bundling.md#imports-between-the-files)).
- **This release has no compatibility period.** owpp refuses a file that uses a name and does not import it. Run `owpp migrate`. Its 0.3 -> 0.5 step does these changes:
    - It writes the imports into each file.
    - It moves the imports that `shared.py` had for `function.py` and `tool.py` into those files.
    - It makes the `from __future__` lines the same in the three files.
    - It sets `protocol: "0.5"`.
- **`migrate` reports each name that it cannot put in place**, and exits with 1. Import those names yourself. Then run `ruff check --fix` (or your formatter) to sort the imports as you want them.
- **Code taken from git stays as it is.** owpp refuses a plugin that pins a 0.3-style commit after its `plugin.yaml` says 0.5. Use `owpp pull` to move it to a commit that the upstream migrated. This repository's examples are migrated from 0.5.0.
- **Renamed:** the runtime's `_plugin_ensure()` is now `plugin_ensure()`. `migrate` renames the calls.
- **Editors:** install owpp as a development dependency (`uv add --dev 'owpp[test]'`), so that an editor finds `owpp.lib` and `open_webui` ([adopting](adopting.md#a-new-repository)).
- **`include: [static]`** now brings in `routes`, which it needs to mount the files.

## 0.3 -> 0.4

- **Nothing to migrate.** Manifests stay at `protocol: "0.3"`. The bundles that a deploy writes are the same as those of 0.3.1, so the first deploy changes nothing on the instance.
- **Plugin tests:** a filter that a test calls through the mock now gets `__model__`. The value is `{"id": "mock-model", ...}`, unless the test gives `model=`. A filter that got `None` for `__model__` before now gets a model.

## 0.2 -> 0.3

- **Manifests:** `source: track:` is now `branch:` or `tag:`, as the repository shows the name. Other tools that follow a git ref use the same keys.
- **`owpp migrate` changes the key.** It asks the repository (`git ls-remote`), changes the key and keeps its value and comment, and sets `protocol: "0.3"`. If it cannot get to the repository, or the name is not a branch or a tag, it tells you and does not change that manifest. Then write `branch:` or `tag:` yourself.
- **A 0.2 manifest with `track:`** continues to work with owpp 0.3 until you migrate it. owpp refuses a 0.3 manifest with `track:`.
- **Renamed:** `owpp sync` is now `owpp pull`, and `owpp deploy --dry-run --sync` is now `--dry-run --latest`. The action's `sync` input is now `latest`. The old names are removed, with no aliases: change your scripts and workflows.

## 0.1 -> 0.2

- **Manifests:** add `protocol: "0.2"`. That is the full step, and `owpp migrate` does it. All else that 0.2 added is optional. owpp reads a manifest with no key as 0.1, so it continues to deploy. But `owpp check` gives a warning, and `owpp check --strict` fails, until the manifest has the key.
- **First deploy:** a function that takes its code from a `source:` is updated one time. The reason is that the deploy now records the upstream commit in the function's meta (`meta.sources`). The deploy keeps its valves and its active and global state.
- **New refusals:** `owpp deploy` refuses to put back an older version than the instance runs, unless you give `--force` (action input `force`). If a dry run gives a warning about this, make sure that you are on the correct branch.

The [changelog](../CHANGELOG.md) has the full list of changes.

## How versions relate

`protocol:` in `plugin.yaml` is a quoted major.minor version that follows owpp's major.minor. A release moves it when it changes the meaning of a manifest key, removes a key, or changes how the code must be written (0.5). 0.7 moved it only to match the release. A patch release never moves it, so a patch release never needs a migration. An owpp that is older than the protocol of a manifest refuses it: upgrade owpp first. See [the protocol key](plugin-format.md#protocol).
