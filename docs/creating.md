# Creating a plugin

`owpp create` is a wizard that scaffolds a plugin. It asks what the plugin is, one stage at a time, and writes a folder that uses owpp with every piece in place and ready to fill in: the manifest, stubs for the code, tests and a README.

```sh
uvx owpp create              # asks for the id
uvx owpp create my_plugin    # starts with that id
uvx owpp create --dir src    # into another plugins folder (default: $OWPP_PLUGINS_DIR, else ./plugins)
```

- **Every question has a default.** Enter takes it. Pressing Enter all the way makes a minimal event plugin, the same as `owpp init <id>`.
- **Nothing is written until the last stage.** It lists the files and asks before writing them. Ctrl-C, or the end of input, stops without writing anything. A folder that already exists is never overwritten.
- **A wrong answer is asked again**, with the reason (an id with a hyphen, an event name that looks like a typo, a git URL that is a local path).
- **It ends with `owpp check --strict`** on the new plugin, then lists what is left to write and the commands to run next.

It is a scaffold, not a code generator. It writes the structure and the stubs: every hook, handler and tool method is a stub to fill in, and valves are left for you to add (see [what it does not ask](#what-it-does-not-ask)).

## The first branch: where the code lives

After the name, the wizard asks where the code lives. The answer decides the rest of the stages.

| Answer | What it is | Stages |
| --- | --- | --- |
| **here** | Code you write in this repository: a function (filter, action, event or pipe), or an [installer](#installers) of a tool and skills | 9 |
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
| 1. Name the plugin | The id, which is the folder name and the function id in Open-WebUI (lowercase, digits and `_`; it cannot change once deployed), and the title | `plugins/<id>/` |
| 2. Where the code lives | here | |
| 3. Pick the plugin type | filter, action, event, pipe or installer. With **help**, it asks the questions from the [authoring guide](authoring.md#pick-the-function-type-first) and picks one | `class Filter`, `Action`, `Event` or `Pipe` in `function.py`; no `function.py` for an installer |
| 4. Describe it | Description, author (from `git config user.name`), version, license, oldest supported Open-WebUI (an installer skips this one) | the `function:` header in `plugin.yaml` |
| 5. Type options | Depends on the type: see [below](#type-options) | the class's methods and attributes |
| 6. Tool | Whether to add one, then its id, the method names, title, `access: public`, a method that shows a page in the chat, `chat_data` | `tool.py`, `tool:` in `plugin.yaml` |
| 7. Skills | Each skill's name (lowercase, hyphens) and when it applies, `access: public` | `skills/<name>/SKILL.md` |
| 8. Pages and libraries | A page, and who may open it; `chat_data`; a `config.yaml`; for an event, `assets/` and `live_reload` | the files, and `include:` |
| 9. Review and write | Yes or no | the folder, then `owpp check --strict` |

### Type options

| Type | Asks | Writes |
| --- | --- | --- |
| **filter** | Which hooks: `inlet` (once per user turn), `request` (every call to the model, tool loops included), `stream` (each chunk), `outlet` (the finished reply). A user toggle. If it is not a toggle, when to make it global. `file_handler`. A `priority` valve | one stub per hook. A toggle sets `self.toggle = True` and `global: false`. `self.file_handler = True` |
| **action** | Several buttons, each with an id and a name. Global. A page (HTML) shown above the message. A `priority` valve | `actions = [...]` and an `action()` that branches on `__id__`; status events through `__event_emitter__`; `templates/embed.html` returned as an inline `HTMLResponse` |
| **event** | A scheduled sync, and its default interval. The events to handle, from the known list plus any others | `class Event(PluginScheduledSync)` with `sync()`, and `jobs: sync_every_minutes: ${<ID>_SYNC_MINUTES:-60}`. One `@on(...)` handler per event (`own=True` for `function.*` events), on `PluginEvents` |
| **pipe** | Several models (a manifold), each with an id and a name. Streaming | `pipes()` and `pipe()`, and a chunk generator when it streams |
| **installer** | Nothing: its function is generated | nothing |

### Tools

A tool written here gets a `tool.py` with one stub per method name. Each stub has a typed `query: str` parameter, a docstring with a `:param` line, and status events, so `owpp check --strict` passes before you change it. Rename the parameters and describe them for the model. The docstring and the type hints are what the model reads. A method that shows a page returns `embed.html` as an inline `HTMLResponse`, and the bundler puts the file into `tool.py` with `{{file:embed.html}}`. `access: public` lets every signed-in user use the tool. Without it, only admins can.

### Skills

A skill gets `skills/<name>/SKILL.md` with Open-WebUI's front matter (`name`, `description`, and `access` when public) and the sections of its [skill authoring layout](https://docs.openwebui.com/features/workspace/skills): When to Use, Prerequisites, How to Run, Quick Reference, Procedure, Pitfalls, Verification. Put supporting files beside it. The whole folder is installed.

### Pages and libraries

| Choice | Writes |
| --- | --- |
| A page served as it is | `static/index.html`, served at `/<id>/` to signed-in users, or with `static: {access: admin \| public}` to admins or to anyone |
| A page the function renders | `templates/page.html`, and a route mounted with `plugin_mount` at `/<id>/`. The access is marked on the handler (`PluginUser`, `PluginAdmin`) or on the mount (`access="public"`). An event mounts it on startup, enable, update and saved valves. Other types mount it when they load |
| `chat_data` | `include: [chat_data]` and a `CHAT_KEY` for `plugin_chat_read` and `plugin_chat_write` |
| `config.yaml` | the file, with one setting read from `${<ID>_GREETING:-Hello}`, and `_settings()` reading it with `plugin_config()` |
| `assets/` (events) | `assets/loader.js` and `assets/custom.css`, `class Event(PluginAssets)`, and `asset_vars()` |
| `live_reload` | `include: [live_reload]` |

A public page is allowed, with a warning, and `owpp check` lists it as a `note`. See [libraries](libraries.md) for each one.

## Installers

An **installer** is a plugin with no code of its own: only a tool, skills, or both. It is how this protocol deploys tools and skills. There is no `function.py`. The bundler generates the parent function, a global filter that installs the tool and skills when it is enabled and removes them when it is disabled or deleted. It has three valves: `INSTALL_TOOLS` and `INSTALL_SKILLS` (off removes that part) and `TOOL_VALVES` (valves to set on the tool). See [runtime](runtime.md).

```
plugins/my_kit/
  plugin.yaml        function: header and global: true, tool:
  tool.py
  skills/my-skill/SKILL.md
  README.md
  tests/test_my_kit.py
```

The tool stage defaults to yes for an installer. If it has no tool, the skills stage asks for at least one skill.

## From a git repository

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
| 1. Name the plugin | The id and title |
| 2. Where the code lives | git |
| 3. The repository | The URL (https, ssh or `user@host:path`; never a local path). A branch, tag or commit: a branch or tag is looked up with `git ls-remote` and pinned to its full commit SHA, and recorded as `track:` for [`owpp sync`](tooling.md#owpp-sync-moving-a-pinned-commit); if the lookup fails (offline, a private repository, no such ref) you type the SHA. The folder in the repository the files are in |
| 4. What it takes | The function itself (its file, taken verbatim with its header). A tool (its file and id). Skills (each one's id, and its folder or its `SKILL.md`). `access: public` for the tool and each skill |
| 5. Describe it, or Global? | Without the function, it is an installer and asks for its header. With the function, the header comes from the file, and the only question is whether to make it global (filters and actions only) |
| 6. Review and write | Yes or no |

It writes no code, only `plugin.yaml`, a README and tests:

```yaml
# plugin.yaml
source:
  git: "https://github.com/Classic298/open-webui-plugins.git"
  ref: 917c88f3029c0c6500139ba7b7b061f358d8aaea
  path: inline-visualizer-v2
  track: main
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

The README states where the code comes from, the pinned commit and how to upgrade it: `owpp sync <id>` moves `ref` to the latest commit and lists the files that changed, and you review the diff before committing. The tests fetch the pinned files, so they need the network. The test file says how to load the plugin with stand-ins instead (`owui.load(plugin_dir, sources={...})`), as [`inline_visualizer`](../examples/plugins/inline_visualizer) does. See [bundling: git sources](bundling.md#git-sources).

## What it writes, in every case

- **`plugin.yaml`**, with comments that say where each part goes.
- **`CHANGELOG.md`**, with an entry for the first version (not for an upstream function, whose versions are the upstream's). [`owpp version`](tooling.md#versions) adds the next ones.
- **`README.md`**, with the sections the [authoring guide](authoring.md#documentation-the-readme-every-plugin-has) requires: a description, settings, `## Test` and `## Deploy`.
- **`tests/test_<id>.py`**, with one test per part: the valves, the type's entry point (a chat through the filter, the action's button, the pipe's models, startup), the tool and each method, the skills, the page and who may open it, the config. Each test has the docstring and the `By hand:` steps that [testing](testing.md#describe-every-test) asks for.

Every combination is checked in this repository's tests (`tests/test_create.py`): it bundles, compiles, has no `owpp check --strict` warnings, and passes the tests it writes.

## What it does not ask

These are left to edit in the files, because they depend on what the plugin does:

- **Valves.** `Valves` has `ENABLE` (and `priority` if you chose it), plus a comment pointing to [Open-WebUI's valve docs](https://docs.openwebui.com/features/extensibility/plugin/development/valves) for dropdowns, sliders and masked fields. Filters, actions and pipes also get an empty `UserValves`. Give each valve a description: `owpp check` warns about one without.
- **Header keys** such as `icon_url` (an action's button, a toggle's chip), `requirements` (pip packages installed when the function is saved) and `funding_url`. Add them under `function:` in `plugin.yaml`.
- **Tool parameters.** Every method starts with `query: str`.
- **`shared.py`**, `include:` libraries it did not offer (`jobs` without a sync, `routes` without a page), and `jobs: adopt_markers`.

## After it is written

```sh
owpp check my_plugin --strict                   # clean right away; keep it clean
uvx --from 'owpp[test]' owpp test my_plugin     # the tests it wrote
owpp deploy --only my_plugin --dry-run          # then without --dry-run
```

Then follow the [authoring guide](authoring.md): its conventions and its checklist.

## From a spec

`owpp create --spec <file>` asks nothing: the file says what the wizard would have asked, as YAML or JSON (`-` reads it from stdin), and it writes the plugin and checks it. It is for scripts and [AI agents](ai-agents.md). An id on the command line wins over the file's.

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

The keys are those of `PluginSpec` (below), with `tool`, `skills` and `source` as mappings and `buttons` and `models` as lists of ids or `{id, name}`. `global` may be written for `global_`. A key it does not know is refused, so a typo is never a silent default. The full list, with a plugin from git, is in the [owpp skill's spec reference](../skills/owpp/references/spec.md).

## From code

The wizard only collects answers. `owpp.create` writes the folder from a `PluginSpec`, with no questions asked:

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

`render(spec)` returns the files as `{path: text}` without writing them. Both refuse a spec that would not work, such as a hyphen in the id, `global` on an event, or `assets/` on anything but an event, with an `OwppError` that says why.
