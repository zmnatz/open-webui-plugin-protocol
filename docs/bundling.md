# Bundling

Open-WebUI keeps each function and each tool as one string of code. For this reason, owpp turns a plugin folder into one file for the function and one for each tool. To read what a deploy stores, use [`owpp bundle`](commands/bundle.md).

## Order

owpp always puts the parts of a bundle in this order. You do not number or name files to control it.

1. **Docstring header**, from the keys of `function:` (or `tool:`) in the manifest.
2. **`from __future__` lines** from lower in the code. owpp moves them here, because they are a SyntaxError after other code.
3. **Libraries**, in the order of the [library catalogue](libraries.md). These are the ones in `include:`, the ones that the plugin's contents turn on, and the ones that those need. owpp does not add a library whose end marker is already in the code (an upstream function with its own copy).
4. **`shared.py`**, if there is one.
5. **`function.py`** (or **`tool.py`**).
6. **The plugin runtime**, if the plugin has a tool or skills. It holds the tools and skills as a JSON literal.

With `function: {file}` or `tool: {file}`, owpp uses the upstream file, with its own header, and adds no `shared.py`. It still adds the libraries and the runtime to a function. It adds only the runtime to a tool.

A function bundle and a tool bundle are separate Open-WebUI modules. They share code through `shared.py`: each gets a copy. Where they must share state, they use `sys.modules`, as the `chat_data` library does for temporary chats.

## Imports between the files

Each file imports what it uses, as in any Python project. Thus you can read, lint and type-check each file on its own ([why](adr/0002-plugin-source-is-python.md)). This includes the plugin's own code:

```python
# function.py
import json

from shared import PREFIX, _load
```

`from shared import ...` works in an editor and in tests. The bundle has no `shared` module, because `shared.py` is already above the file. For this reason, the bundler removes the line.

The bundler also removes `from owpp.lib import ...`: the libraries are above the file, and Open-WebUI does not have owpp ([libraries](libraries.md)). This work on the files is the **Flattening**: they become the one module that Open-WebUI stores.

The bundler can safely remove only some forms of import. It refuses the others and names the line:

- **Use only a top-level `from shared import NAME` or `from owpp.lib import NAME`.** Do not use `import shared`, `import owpp.lib`, `*`, a relative import, or an import inside a function.
- **Do not use `as`.** After the bundler removes the line, the alias is undefined.
- **The name must exist.** `shared.py` must define it, or `owpp.lib` must export it. A library name also needs its library in the bundle (`include:`, or `tool.include` for the tool). A name from the [runtime](runtime.md) needs a tool or skills.
- **Do not define one name in both `shared.py` and the file.** The two become one namespace, so one definition replaces the other. You can import the same module (`import json`) in both.
- **`function.py` and `tool.py` cannot import each other**, because they go into separate modules. Move the code that both need into `shared.py`.

The bundler also refuses a file that uses a library name or a `shared.py` name without an import.

## `{{file:NAME}}` (deprecated)

In `function.py`, `tool.py` or `shared.py`, owpp replaces `{{file:NAME}}` with the text of the file `NAME` in the same folder. This still works, but `owpp check` warns about it. The token puts text into the source, so the file does not read as the Python that runs.

Use a template instead:

1. Move the file into `templates/`.
2. If the tool reads the file, add `include: [templates]` under `tool:`.
3. Read the file with `plugin_template_text("NAME")` ([templates](libraries.md#templates)).

Put files that Open-WebUI serves over HTTP in `static/`.

## Tool bundles carry the runtime too

A separate tool bundle also includes the runtime, but with **only the ids** of the plugin's tools and skills. The runtime uses them [when the tool loads](runtime.md#when-it-syncs).

## Git sources

```yaml
source: { git: https://github.com/owner/repo.git, ref: <40-char SHA>, path: dir }
```

For each key, see [plugin format: `source:`](plugin-format.md#source). These rules apply when owpp fetches the code:

- `git` is an https URL, an ssh URL or `user@host:path`. owpp reads it with the `git` CLI, so any git host works, and ssh deploy keys need no new secret. owpp allows only the `https` and `ssh` protocols.
- `ref` must be a **full commit SHA**. A branch or a tag can move, and this code runs with admin rights, so owpp refuses anything else. To upgrade, change the SHA and review the change. [`owpp pull`](commands/pull.md) changes it and lists the files that changed.
- Before it bundles, owpp makes a shallow fetch of that exact commit into a scratch repository. Then it embeds the files. Thus the plugins repository, the pinned commit and the owpp version give the same bundle again.
- With `plugin: true`, owpp fetches the whole folder at `path` and bundles it as a local plugin. The owpp that reads your manifest does this. See [a whole plugin from git](plugin-format.md#a-whole-plugin-from-git).
- For a folder (`dir:`, or a whole plugin), owpp takes every regular file in that commit. It skips symlinks and submodules.
- The limits are 1000 files per folder and 2 MB per file. owpp embeds a file that is not UTF-8 as base64.

Plugins can pin different commits of the same repository. The **Sources** of a run are everything that it reads from git, and it fetches each file at a commit once.

## Skills

owpp takes a skill as its whole folder, as Open-WebUI stores it: a `files` list with `SKILL.md`, references, templates and examples. A skill given as a `file:` has only its `SKILL.md`. owpp stores `SKILL.md` unchanged, front matter included. The `name` and `description` come from that front matter.

When the runtime updates a skill, it sends the whole set of files with the skill's current version (`expected_version_id`). It does not change a skill whose name, description and files already match.

## Assets

owpp embeds `assets/loader.js` and `assets/custom.css` in the function bundle as a JSON literal (`__ASSETS_DATA__`), with the settings from the manifest's `assets:` key. They are this plugin's fragments of the two shared files of the [Shared Assets Protocol](https://github.com/Classic298/open-webui-plugins/tree/main/shared-assets-protocol). The [`assets` library](libraries.md#assets) publishes them.

## Config

When owpp bundles the plugin, it parses `config.yaml` and embeds it as a JSON literal (`__CONFIG_DATA__`). A YAML error or a wrong shape stops the bundle. The [`config` library](libraries.md#config) reads the data with `plugin_config()`.

## Static files and templates

owpp embeds the files of `static/` in the function bundle as a JSON literal (`__STATIC_DATA__`), with the prefix and the access level from `static:`. The [`static` library](libraries.md#static) serves them.

owpp embeds the files of `templates/` the same way (`__TEMPLATES_DATA__`). The plugin reads them with `plugin_template_text()`, and nothing serves them.

## What the deploy script does with a bundle

For each function in the plugins folder, the deploy compares it with the function on the instance:

| On the instance | The deploy |
| --- | --- |
| Not there | Creates it and activates it. It makes a filter global, unless the filter says `global: false`. |
| Different | Updates it. |
| Identical | Does not change its code. [`global`](plugin-format.md#function) can still change its state. |

A function is different if its code differs, or if its stored meta differs: the ownership marker, the description, the git sources or `requires:`. To compare the code, the deploy ignores the style of line endings and any whitespace at the end of the file. It also applies Open-WebUI's own import rewrite to the local copy first.

The deploy never overwrites the valves in the database, except the keys that the manifest declares. See [what a deploy does](commands/deploy.md#what-a-deploy-does).
