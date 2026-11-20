# Bundling

Open-WebUI keeps a function or tool as one string of code, so the deploy turns a plugin folder into one file per function and per tool.

## Order

A bundle is always, in this order, with no numbering or naming scheme to maintain:

1. **Docstring header**, generated from the manifest's `function:` (or `tool:`) keys. (With `function: {file}` the upstream file's own header is kept.)
2. **`from __future__` lines** found anywhere below, hoisted here (they are a SyntaxError after other code).
3. **Libraries** from `include:`, in the library order (`live_reload`, `shared_assets`, `core`, `routes`, `jobs`, `chat_data`, `static`, `templates`, `assets`, `config`; `assets` adds `shared_assets` and `core`). A library is skipped if its end marker is already in the code (an upstream function that ships its own copy).
4. **`shared.py`**, if present.
5. **`function.py`** (or **`tool.py`**).
6. **The plugin runtime**, when the plugin has a tool or skills, with the tools and skills embedded as a JSON literal.

A function bundle and a tool bundle are separate Open-WebUI modules. They share code through `shared.py` (each gets a copy) and, where state must be shared, through `sys.modules` (the `chat_data` library does this for temporary chats).

## `{{file:NAME}}`

In `function.py` or `tool.py`, `{{file:NAME}}` is replaced by the text of the sibling file `NAME`. Use it to keep an HTML page or large literal out of a Python string. For files served over HTTP prefer a `public/` folder.

## Tool bundles carry the runtime too

A tool bundle includes the runtime with **only the ids to remove**, so a tool that loads after a restart can notice its parent function was disabled while Open-WebUI was down, and remove itself.

## Git sources

```yaml
source: { git: https://github.com/owner/repo.git, ref: <40-char SHA>, path: dir }
```

- `git` is an https URL, an ssh URL or `user@host:path`, read with the `git` CLI (so any host works and ssh deploy keys need no new secret). Only the `https` and `ssh` protocols are allowed.
- `ref` must be a **full commit SHA**. A branch or tag can move, and this code runs with admin rights, so anything else is refused. Upgrading is a reviewed change of the SHA: [`owpp sync`](tooling.md#owpp-sync-moving-a-pinned-commit) makes it, and lists the files that changed.
- The files are fetched before bundling by a shallow fetch of that exact commit into a scratch repository, then embedded, so the deployed bundle is reproducible from the repo, the pinned commit and the owpp version that bundles it.
- With `plugin: true` the whole folder at `path` is fetched and bundled as a local plugin would be, by the owpp reading the manifest. See [a whole plugin from git](plugin-format.md#a-whole-plugin-from-git).
- Directory entries (`dir:`) list the directory in that commit and take every regular file. Symlinks and submodules are skipped. Limits: 1000 files per skill, 2 MB per file. A file that is not UTF-8 is embedded as base64.

Different plugins may pin different commits of the same repo; one fetch is made per `git#sha`.

## Skills

A skill is installed as its whole folder, as Open-WebUI stores it (a `files` list: `SKILL.md` plus references, templates, examples). `SKILL.md` is stored verbatim, front matter included; `name` and `description` come from that front matter. An update sends the whole file set with the skill's current version (`expected_version_id`); a skill whose files and name already match is left alone.

## Assets

`assets/loader.js` and `assets/custom.css` are this plugin's fragments of the [Shared Assets Protocol](https://github.com/Classic298/open-webui-plugins/tree/main/shared-assets-protocol)'s two shared files. They are embedded in the function bundle as a JSON literal (`__ASSETS_DATA__`), together with the settings from the manifest's `assets:` key, and published by the [`assets` library](libraries.md#assets). The protocol block (`shared_assets`) and `core` are added with it; `live_reload` is opt-in. A plugin with an `assets/` folder and no `function.py` gets a generated `Event(PluginAssets)`.

## Config

`config.yaml` is parsed during bundling (a YAML or shape error stops the bundle) and embedded as a JSON literal (`__CONFIG_DATA__`). The [`config` library](libraries.md#config) reads it with `plugin_config()`.

## Static files and templates

Files under `static/` are embedded in the function bundle as a JSON literal (`__STATIC_DATA__`, with the prefix and the access level from `static:`) and served by the [`static` library](libraries.md#static). Files under `templates/` are embedded the same way (`__TEMPLATES_DATA__`) and read back with `plugin_template_text()`; nothing serves them.

## What the deploy script does with a bundle

For each plugin function: not present is created, activated, and made global if it is a filter; present with different code is updated (comparison ignores line endings and trailing whitespace, and applies Open-WebUI's own import rewriting to the local copy first); identical is left alone. Valves stored in the database are never overwritten except for keys the manifest declares. See [tooling](tooling.md).
