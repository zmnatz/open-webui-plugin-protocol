# Upgrading owpp

The runtime and libraries are copied into every bundle, so a new owpp changes the code you deploy. Upgrade on a branch, check it, review the report of a dry run, and deploy from the merged change.

## Steps

1. **Move the pin.** Change the version wherever you run owpp: `uvx owpp@0.6.0`, `uv tool install owpp==0.6.0`, or the action's `uses: zmnatz/open-webui-plugin-protocol@v0.6.0`.
2. **Migrate the manifests.** See what would change, then write it:

   ```sh
   uvx owpp@0.6.0 migrate --dry-run
   uvx owpp@0.6.0 migrate
   ```

   `migrate` rewrites only what each version step changes, keeps comments and layout, and lists every file it writes. A manifest already at the current version is left alone. Pass ids to migrate only some plugins.
3. **Check.** `uvx owpp@0.6.0 check --strict` bundles every plugin as the deploy would. `check` notes any manifest still on an older protocol and warns about one with no `protocol:` key; `--strict` makes that warning fail.
4. **Dry run.** `owpp deploy --dry-run` against your instance shows which functions, tools and skills the new bundles would update.
5. **Commit** the pin and the manifest changes together, and deploy.

## 0.5 -> 0.6

- **Nothing to migrate.** Manifests stay `protocol: "0.5"`: 0.6 adds a key and takes none away, and the bundles a deploy writes are the same as 0.5.0's unless a plugin uses the new key.
- **`tool: templates:`** lists the files of `templates/` a tool embeds (`[launcher/]`); without it a tool that includes templates still embeds them all ([plugin format](plugin-format.md#tool)).
- **From 0.6.1, a plugin that edits `app.routes` is refused** (`app.routes.insert(...)`, `app.routes[:] = ...`, `del app.routes[0]`, ...): it added routes past the sign-in guard. `owpp check` names the line; mount those routes with `plugin_mount` instead ([libraries](libraries.md#routes)). And `asset_vars()` values are filled in one pass, so a value holding another placeholder's text is served as written.
- **Plugin tests:** `owui.emit` also takes the subject itself, for events about users and models, and the mock has `decode_token` and the chat pipeline a plugin calls to ask a model (`owui.model_reply`, `owui.completions`). A test that patched those stand-ins still works; it can use the mock's instead ([the mock](testing/mock.md)).

## 0.4 -> 0.5

- **Every file imports what it uses** ([why](adr/0002-plugin-source-is-python.md)). A plugin's `function.py`, `tool.py` and `shared.py` used to find the libraries and `shared.py`'s names already in scope; now they import them, `from owpp.lib import ...` and `from shared import ...`, and the bundler removes those lines ([bundling](bundling.md#imports-between-the-files)). A file that uses one without importing it is refused, so this release has no compatibility period: run `owpp migrate`. Its 0.3 -> 0.5 step writes the imports into each file, copies into `function.py` and `tool.py` the imports `shared.py` held for them and drops them from `shared.py`, makes `from __future__` lines the same in all three, and sets `protocol: "0.5"`. It reports any name it cannot place, and exits 1, for you to import yourself. Code taken from git is left alone, and a plugin that pins a 0.3-style commit is refused once its `plugin.yaml` says 0.5: `owpp pull` it to a commit that has been migrated upstream (this repository's examples are, from 0.5.0 on). Run `ruff check --fix` (or your formatter) afterwards to sort the imports your way.
- **Renamed:** the runtime's `_plugin_ensure()` is `plugin_ensure()`; `migrate` renames the calls.
- **Editors:** install owpp as a development dependency (`uv add --dev 'owpp[test]'`) for an editor to resolve `owpp.lib` and `open_webui` ([adopting](adopting.md#a-new-repository)).
- **`include: [static]`** now brings in `routes`, which it needs to mount the files.

## 0.3 -> 0.4

- **Nothing to migrate.** Manifests stay `protocol: "0.3"`, and the bundles a deploy writes are the same as 0.3.1's, so the first deploy changes nothing on the instance.
- **Plugin tests:** a filter called through the mock now gets `__model__` (`{"id": "mock-model", ...}` unless a test passes `model=`). A filter that read `__model__` and got `None` before now gets a model.

## 0.2 -> 0.3

- **Manifests:** `source: track:` is now `branch:` or `tag:`, whichever the name is in the repository, as other tools that follow a git ref write it. `owpp migrate` asks the repository (`git ls-remote`) and rewrites the key, keeping its value and comment, and sets `protocol: "0.3"`. When it cannot reach the repository, or the name is neither, it says so and leaves that manifest: write `branch:` or `tag:` yourself. A 0.2 manifest with `track:` still works with owpp 0.3 until it is migrated; a 0.3 manifest with `track:` is refused.
- **Renamed:** `owpp sync` is now `owpp pull`, and `owpp deploy --dry-run --sync` is now `--dry-run --latest`. The action's `sync` input is now `latest`. The old names are removed, not aliased: change your scripts and workflows.

## 0.1 -> 0.2

- **Manifests:** add `protocol: "0.2"`. That is the whole step (`owpp migrate` does it): everything else 0.2 added is optional. A manifest with no key is read as 0.1, so it still deploys, but `owpp check` warns and `owpp check --strict` fails until it has one.
- **First deploy:** a function that takes its code from a `source:` updates once, because the deploy now records the upstream commit in its meta (`meta.sources`). Its valves and active/global state are kept.
- **New refusals:** `owpp deploy` refuses to put back an older version than the instance runs, unless given `--force` (action input `force`). If a dry run warns about it, check that you are on the right branch.

The full list of what changed is in the [changelog](../CHANGELOG.md).

## How versions relate

`protocol:` in `plugin.yaml` is a quoted major.minor that tracks owpp's major.minor. It changes only when a release changes what a manifest key means or takes one away, so a patch release never needs a migration. An owpp older than a manifest's protocol refuses it: upgrade owpp first. See [the protocol key](plugin-format.md#protocol).
