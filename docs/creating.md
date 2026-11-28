# Creating a plugin

`owpp create` is a wizard that scaffolds a plugin. It asks what the plugin is, one stage at a time. Then it writes a plugin folder with all the parts in place for you to fill in: the manifest, stubs for the code, tests and a README.

```sh
uvx owpp create              # asks for the id
uvx owpp create my_plugin    # starts with that id
uvx owpp create --dir src    # into another plugins folder than ./plugins
```

[`owpp create`](commands/create.md) gives its flags, and the default plugins folder ([`OWPP_PLUGINS_DIR`](environment-variables.md#owpp_plugins_dir)).

- **Each question has a default.** Enter accepts it. If you push Enter for each question, you get a minimal event plugin, the same as `owpp init <id>`.
- **The wizard writes nothing until the last stage.** At that stage, it lists the files and asks before it writes them. Ctrl-C, or the end of input, stops the wizard and it writes nothing. It never overwrites a folder that exists.
- **It asks a question again after an incorrect answer**, and gives the reason. Examples are an id with a hyphen, an event name that looks like a typo, or a git URL that is a local path.
- **At the end, it runs `owpp check --strict`** on the new plugin. Then it lists what you must write, and the commands to run next.

The wizard is a scaffold, not a code generator. It writes the structure and the stubs: each hook, handler and tool method is a stub for you to fill in. You add the valves yourself (see [what it does not ask](#what-it-does-not-ask)).

## The first branch: where the code lives

After the name, the wizard asks where the code lives. The answer sets the stages that follow.

| Answer | What it is | Stages |
| --- | --- | --- |
| **here** | Code that you write in this repository: a function (filter, action, event or pipe), or an [installer](#installers) of a tool and skills | 9 |
| **git** | Code from [another git repository](#from-a-git-repository), pinned to a commit: the function itself, or a tool and skills | 6 |

## Code written here

```text
▸ Stage 3/9 · Pick the plugin type  (~6 min left)

  The function is the plugin's parent: its tool and skills come and go with it.
  What kind of plugin?
    1. filter  changes chat requests and replies (inlet, stream, outlet)
    2. action  a button under a message
   *3. event  reacts to Open-WebUI events, runs on a schedule, serves pages
    4. pipe  appears as a model
    5. installer  no code of its own: deploys a tool and/or skills
    6. help  not sure: ask me a few questions
  Choice [3] filter
```

| Stage | What it asks | What it writes |
| --- | --- | --- |
| 1. Name the plugin | The id and the title. The id is the folder name and the function id in Open-WebUI. It has lowercase letters, digits and `_`, and it cannot change after the first deploy | `plugins/<id>/` |
| 2. Where the code lives | here | |
| 3. Pick the plugin type | filter, action, event, pipe or installer. With **help**, it asks the questions of the [authoring guide](authoring.md#pick-the-function-type-first) and selects the type | `class Filter`, `Action`, `Event` or `Pipe` in `function.py`. An installer has no `function.py` |
| 4. Describe it | The description, the author (from `git config user.name`), the version, the license, and the oldest Open-WebUI it supports. An installer does not get the last question | the `function:` header in `plugin.yaml` |
| 5. Type options | It changes with the type: see [below](#type-options) | the methods and attributes of the class |
| 6. Tool | If you want a tool. Then its id, the method names, the title, `access: public`, a method that shows a page in the chat, and `chat_data` | `tool.py`, and `tool:` in `plugin.yaml` |
| 7. Skills | The name of each skill (lowercase letters and hyphens), when it applies, and `access: public` | `skills/<name>/SKILL.md` |
| 8. Pages and libraries | A page, and who can open it. `chat_data`. A `config.yaml`. For an event, `assets/` and `live_reload` | the files, and `include:` |
| 9. Review and write | Yes or no | the folder, then `owpp check --strict` |

### Type options

| Type | Asks | Writes |
| --- | --- | --- |
| **filter** | The hooks: `inlet` (one time for each user turn), `request` (each call to the model, tool loops included), `stream` (each chunk) and `outlet` (the finished reply). If it is a user toggle. If it is not a toggle, when to make it global. `file_handler`. A `priority` valve | One stub for each hook. A toggle sets `self.toggle = True` and `global: false`. `file_handler` sets `self.file_handler = True` |
| **action** | If it has more than one button, and the id and name of each button. If it is global. A page (HTML) shown above the message. A `priority` valve | `actions = [...]`, and an `action()` that branches on `__id__`. Status events through `__event_emitter__`. `templates/embed.html`, returned as an inline `HTMLResponse` |
| **event** | If it has a scheduled sync, and its default interval. The events to handle, from the known list and any others | For a sync: `class Event(PluginScheduledSync)` with `sync()`, and `jobs: sync_every_minutes: ${<ID>_SYNC_MINUTES:-60}`. One `@on(...)` handler for each event on `PluginEvents` (`own=True` for `function.*` events) |
| **pipe** | If it has more than one model (a manifold), and the id and name of each model. If it streams | `pipes()` and `pipe()`, and a chunk generator if it streams |
| **installer** | Nothing: owpp generates its function | nothing |

### Tools

A tool written here gets a `tool.py` with one stub for each method name. Each stub has a typed `query: str` parameter, a docstring with a `:param` line, and status events. Thus `owpp check --strict` passes before you change the tool.

The model reads the docstring and the type hints. Rename the parameters, and describe them for the model.

A method that shows a page returns `templates/tool.html` as an inline `HTMLResponse`. It reads the file with `plugin_template_text()`. For this, the tool asks for the templates with `include: [templates]` under `tool:`.

With `access: public`, all signed-in users can use the tool. Without it, only admins can use it.

### Skills

A skill gets `skills/<name>/SKILL.md`. The file has Open-WebUI's front matter: `name`, `description`, and `access` when the skill is public. It also has the sections of Open-WebUI's [skill authoring layout](https://docs.openwebui.com/features/workspace/skills): When to Use, Prerequisites, How to Run, Quick Reference, Procedure, Pitfalls, Verification. Put the files that the skill uses next to it. The runtime installs the whole folder.

### Pages and libraries

| Choice | Writes |
| --- | --- |
| A page served as it is | `static/index.html`, served at `/<id>/` to signed-in users. With `static: {access: admin \| public}`, it is served to admins, or to all people |
| A page the function renders | `templates/page.html`, and a route at `/<id>/` mounted with `plugin_mount`. The handler marks the access (`PluginUser`, `PluginAdmin`), or the mount does (`access="public"`). An event mounts it on startup, enable, update and saved valves. The other types mount it when they load |
| `chat_data` | `include: [chat_data]`, and a `CHAT_KEY` for `plugin_chat_read` and `plugin_chat_write` |
| `config.yaml` | The file, with one setting read from `${<ID>_GREETING:-Hello}`, and a `_settings()` that reads it with `plugin_config()` |
| `assets/` (events) | `assets/loader.js` and `assets/custom.css`, `class Event(PluginAssets)`, and `asset_vars()` |
| `live_reload` | `include: [live_reload]` |

The wizard lets you make a public page, but it gives a warning. `owpp check` lists each public page as a `note`. [Libraries](libraries.md) describes each library.

## Installers

An **installer** is a plugin with no code of its own: it has only a tool, skills, or both. This protocol uses installers to deploy tools and skills. An installer has no `function.py`. The bundler generates its parent function: a global filter that installs the tool and skills when it is enabled. The filter removes them when it is disabled or deleted. [Runtime](runtime.md#valves-on-the-parent) describes the filter's three valves (`INSTALL_TOOLS`, `INSTALL_SKILLS` and `TOOL_VALVES`).

```
plugins/my_kit/
  plugin.yaml        function: header and global: true, tool:
  tool.py
  skills/my-skill/SKILL.md
  README.md
  tests/test_my_kit.py
```

For an installer, the default answer of the tool stage is yes. If the installer has no tool, the skills stage asks for at least one skill.

## From a git repository

For code that is already in a repository, you can also use [`owpp import <URL>`](commands/import.md). It asks nothing: it finds the function, the tool and the skills in the folder, and pins them. Use the wizard to select the parts yourself.

```text
▸ Stage 3/6 · The repository  (~3 min left)

  The plugin takes its files from this repository at one commit, so what is
  deployed never changes until you move the commit yourself.
  Git URL (https://, ssh:// or user@host:path) https://github.com/Classic298/open-webui-plugins.git
  Branch, tag or commit SHA [main]
  ✓ main is commit 917c88f3029c0c6500139ba7b7b061f358d8aaea
  Folder in the repository the files are in (Enter for the root) inline-visualizer-v2
```

| Stage | What it asks |
| --- | --- |
| 1. Name the plugin | The id and the title |
| 2. Where the code lives | git |
| 3. The repository | The URL: https, ssh or `user@host:path`, never a local path. Then a branch, a tag or a commit, and the folder in the repository that has the files ([below](#how-it-pins-a-branch-or-tag)) |
| 4. What it takes | The function itself (its file, taken as it is, with its header). A tool (its file and id). Skills (the id of each skill, and its folder or its `SKILL.md`). `access: public` for the tool and for each skill |
| 5. Describe it, or Global? | Without the function, the plugin is an installer, and the wizard asks for its header. With the function, the header comes from the file. Then the only question is if the function is global (filters and actions only) |
| 6. Review and write | Yes or no |

### How it pins a branch or tag

The wizard finds the commit of a branch or tag with `git ls-remote`, and pins its full commit SHA. It records the name as `branch:` or `tag:`, as the repository shows, for [`owpp pull`](commands/pull.md). If it cannot tell which of the two the name is, it asks you. If the lookup fails, you type the SHA. The lookup fails when you are offline, when the repository is private, or when the name does not exist.

### What it writes

The wizard writes no code. It writes only `plugin.yaml`, a README and tests, and a `CHANGELOG.md` for an installer:

```yaml
# plugin.yaml
protocol: "0.7"
source:
  git: "https://github.com/Classic298/open-webui-plugins.git"
  ref: 917c88f3029c0c6500139ba7b7b061f358d8aaea
  path: inline-visualizer-v2
  branch: main
function:
  title: Viz
  ...
  global: true # Open-WebUI loads it at startup, so it installs the rest
tool:
  id: viz
  file: tool.py
  access: public
skills:
  visualize:
    file: SKILL.md
    access: public
```

The README gives the origin of the code, the pinned commit and how to upgrade it. To upgrade, `owpp pull <id>` moves `ref` to the latest commit and lists the files that changed. You review the diff before you commit.

The tests read the pinned files. They need the network until [`.owpp/`](bundling.md#the-owpp-folder) holds the files. The test file tells how to load the plugin with stand-ins: `owui.load(plugin_dir, sources={...})`. [`inline_visualizer`](../examples/plugins/inline_visualizer) does this. See [bundling: git sources](bundling.md#git-sources).

## What it writes, in every case

- **`plugin.yaml`**, with comments that tell where each part goes.
- **`CHANGELOG.md`**, with an entry for the first version. A function from another repository gets no changelog, because its versions are the upstream's. [`owpp version`](commands/version.md) adds the entries that follow.
- **`README.md`**, with the sections that the [authoring guide](authoring.md#documentation-the-readme-every-plugin-has) requires: a description, settings, `## Test` and `## Deploy`.
- **`tests/test_<id>.py`**, with one test for each part. The parts are the valves, the entry point of the type, the tool and each method, the skills, the page and who can open it, and the config. The entry point is a chat through the filter, the action's button, the pipe's models, or the event's startup. Each test has the docstring and the `By hand:` steps that [testing](testing/writing.md#describe-every-test) asks for.

This repository's tests (`tests/test_create.py`) check each combination. Each one bundles and compiles, gets no warnings from `owpp check --strict`, and passes the tests that it writes.

## What it does not ask

You edit these in the files, because they depend on what the plugin does:

- **Valves.** `Valves` has `ENABLE` (a scheduled sync adds its own), and `priority` if you selected it. A comment points to [Open-WebUI's valve docs](https://docs.openwebui.com/features/extensibility/plugin/development/valves) for dropdowns, sliders and masked fields. Filters, actions and pipes also get an empty `UserValves`. Give each valve a description: `owpp check` gives a warning for a valve without one.
- **Header keys** such as `icon_url` (an action's button, a toggle's chip), `requirements` (pip packages installed when the function is saved) and `funding_url`. Add them under `function:` in `plugin.yaml`.
- **Tool parameters.** Each method starts with `query: str`.
- **Other parts:** `shared.py`, the `include:` libraries that it did not offer (`jobs` without a sync, `routes` without a page), and `jobs: adopt_markers`.

## After it is written

1. Run `owpp check my_plugin --strict`. It passes immediately. Keep it clean.
2. Run `uvx --python 3.12 --from 'owpp[test]' owpp test my_plugin` to run the tests that the wizard wrote.
3. Run `owpp deploy --only my_plugin --dry-run`, then run it again without `--dry-run`.
4. Follow the [authoring guide](authoring.md): its conventions and its checklist.

```sh
owpp check my_plugin --strict                              # clean right away; keep it clean
uvx --python 3.12 --from 'owpp[test]' owpp test my_plugin  # the tests it wrote
owpp deploy --only my_plugin --dry-run                     # then without --dry-run
```

## From a spec

`owpp create --spec <file>` asks nothing. The file gives the answers to the wizard's questions, as YAML or JSON (`-` reads the file from stdin). Then the command writes the plugin and checks it. It is for scripts and for [AI agents](ai-agents.md). An id on the command line overrides the id in the file.

```yaml
id: notes
type: filter                 # filter | action | event | pipe | installer | upstream
description: Keeps notes on the chat.
hooks: [inlet, outlet]
toggle: false
tool: {id: notes, methods: [save, search]}
skills:
  - {id: take-notes, description: Use when the user asks to remember something.}
page: rendered
page_access: admin
chat_data: true
```

The keys are those of `PluginSpec` ([below](#from-code)):

- `tool`, `skills` and `source` are mappings.
- `buttons` and `models` are lists of ids or of `{id, name}`.
- You can write `global` for `global_`.

The command refuses a key that it does not know, so a typo never becomes a silent default. The [owpp skill's spec reference](../skills/owpp/references/spec.md) has the full list, with a plugin from git.

## From code

The wizard only collects answers. `owpp.create` writes the folder from a `PluginSpec`, and asks no questions:

```python
from owpp.create import PluginSpec, SkillSpec, ToolSpec, write_plugin

write_plugin(
    "plugins",
    PluginSpec(
        id="notes",
        type="filter",
        hooks=["inlet", "outlet"],
        tool=ToolSpec("notes", methods=["save", "search"]),
        skills=[SkillSpec("take-notes", "Use when the user asks to remember something.")],
    ),
)
```

`render(spec)` returns the files as `{path: text}` and does not write them. Both functions refuse a spec that cannot work, with an `OwppError` that gives the reason. Examples are a hyphen in the id, `global` on an event, or `assets/` on a type that is not an event.
