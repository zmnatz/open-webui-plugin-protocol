# Plugin format

## Folder

```
plugins/<id>/
  plugin.yaml      required
  function.py      the function (omit it for a plugin that is only a tool and skills)
  tool.py          the tool
  shared.py        code placed in front of function.py and of tool.py
  skills/<id>/     SKILL.md plus any supporting files, installed as a whole folder
  static/          files served as they are, to signed-in users unless `static:` says otherwise; index.html is the plugin's page
  templates/       files the function renders itself (a page it fills in); embedded, never served
  assets/          loader.js and custom.css: this plugin's fragments of the shared /static files
  config.yaml      structured settings shipped with the plugin; read with plugin_config()
  README.md        required in practice: see "Documentation" in the authoring guide
```

A plugin may also be a single `<id>.py` (a function with no tool or skills). The **function id is the folder (or file) name** and must match Open-WebUI's id rule: lowercase, `[a-z_][a-z0-9_]*`. Hyphens are not allowed, so `my-plugin.py` becomes `my_plugin/`.

## `plugin.yaml`

All sections are optional except that a tool or skills need a `function:` section: the function is the parent. The current protocol version is `0.2`.

### `protocol:`

```yaml
protocol: "0.2"   # the version of the plugin format this manifest was written for
```

A quoted major.minor string that tracks owpp's major.minor. It changes only when a release changes what a manifest key means or takes one away; `owpp init`, `owpp create` and the examples in this repository write `protocol: "0.2"`. It is a manifest key: unlike `function:`'s keys, it is not copied into the deployed header.

- **Write the quotes.** Unquoted `0.2` is a YAML number and is refused, as is a patch version such as `"0.2.0"`.
- A **newer** version than the owpp reading the manifest is refused: its keys may mean something else. Upgrade owpp first.
- An **older** version is accepted; `owpp check` prints a note pointing at the migration. A manifest with **no key** is a 0.1 plugin, from before the key existed: `owpp check` warns and `owpp check --strict` fails.
- [`owpp migrate`](commands/migrate.md) brings old manifests up to 0.2. The 0.1 -> 0.2 step changes only the `protocol:` line, adding it when absent: what 0.2 added is optional. See [upgrading owpp](upgrading.md).

### `function:`

Header keys become the docstring Open-WebUI reads as the function's manifest, one `key: value` per line, written in the order given.

| Key | Meaning |
| --- | --- |
| `title`, `author`, `author_url`, `funding_url`, `version`, `license`, `description`, `required_open_webui_version`, ... | Written into the header verbatim. Every value must fit on one line. |
| `global` | Read by the deploy script only. `true`: keep the function active and global on every run. `false`: never make it global, and take it out of global on every run: for a filter that each user switches on (a toggle). Left out: a new filter is made global once, on first deploy. Filters and actions only; an event or pipe with `global: true` is refused. |
| `valves` | `{name: value}` applied after deploy, for the declared keys only. |
| `file` | With `source:`, take the function from the git repo verbatim, header included. Then no header keys are allowed (they come from the file). |

Open-WebUI reads the header line by line, split at the first colon. It is not YAML, so `author: @someone` is fine, and a block value such as `description: >` is stored as `>` and the following lines are lost. The loader refuses such a header.

### Function type

A function has one type, decided as Open-WebUI decides it, by the class defined at the top level of the code: `class Pipe`, `class Filter`, `class Action` or `class Event`. Defining none or more than one is an error. The type is shown by `owpp list` and in the deploy report, and it governs `global`:

| Type | Runs | `global` | Typical use |
| --- | --- | --- | --- |
| **filter** | On every chat completion (`inlet`/`outlet`/`stream`), for the models it is attached to, or all models when global. May be a user toggle (`self.toggle = True`). | yes | Change the request or reply, add artifacts, attach files |
| **action** | A button under a message | yes | User-triggered operations |
| **event** | On Open-WebUI lifecycle events (`system.startup.completed`, `function.enable_started`, `function.valves_updated`, ...), not tied to a chat | **no** | Sync jobs, schedulers, routes, dashboards |
| **pipe** | Appears as a model | no | Custom model backends |

A new filter is made global on first deploy (a filter that is not attached to a model does nothing), unless it says `global: false`; `global: true` additionally re-asserts active+global on every run, and `global: false` keeps it out of global.

### `tool:`

| Key | Meaning |
| --- | --- |
| `id` | Tool id. |
| `title`, `description`, and other header keys | Header of the tool bundle (code in `tool.py`). |
| `file` | With `source:`, take the tool from the git repo verbatim. |
| `from: function` | Install the function's own bundle as the tool (one module serving as both). |
| `access` | `public` makes it readable by every signed-in user when first installed (Open-WebUI's `user:*` read grant); later changes in the UI are kept. Without it, only admins can use the tool. |
| `valves` | `{name: value}` enforced on every sync, for the declared keys only, validated against the tool's `Valves` class (a value it rejects is logged and skipped). |
| `include` | Libraries for the tool bundle (the function's `include:` does not apply to it). |

### `skills:`

```yaml
skills:
  my-skill:
    file: SKILL.md           # or:  dir: skills/my-skill   (the whole folder)
    access: public
```

Local skills are the folder `skills/<id>/`; a local skill sets its `access` in its SKILL.md front matter (`access: public`), as `owpp create` writes it. From a `source:` a skill is a `file:` or a `dir:`. A skill's `access` works like a tool's.

**Earlier copies of the runtime (portainer's, before it moved to owpp) granted `public` items to Open-WebUI's `anyone:*` audience.** That is the no-auth audience Open-WebUI uses for shared chats, and its tool and skill access checks ignore it, so only admins could use them. The runtime now swaps exactly that grant for `user:*` on the next sync of an item it installed, and leaves every other grant as the admin set it.

### `source:`

```yaml
source:
  git: https://github.com/owner/repo.git   # https, ssh, or user@host:path
  ref: 917c88f3029c0c6500139ba7b7b061f358d8aaea   # full 40-character commit SHA
  path: subfolder                           # "" for the repo root
  track: main                               # optional: the branch or tag `owpp pull` follows
```

Makes `tool: {file}`, `function: {file}` and `skills: {<id>: {file|dir}}` read from that repo at that commit. See [bundling](bundling.md#git-sources).

`ref` can be left out while writing the manifest: [`owpp pull`](commands/pull.md) looks up the latest commit and adds the line. Until it does, `owpp check` and `owpp deploy` refuse the plugin.

`track` is read only by [`owpp pull`](commands/pull.md), which moves `ref` to the latest commit of that branch or tag. Without it, `owpp pull` follows the repository's default branch. It never changes what is deployed: only `ref` does.

#### A whole plugin from git

When the folder at `path` is an owpp plugin itself (it has a `plugin.yaml`, like the [examples](../examples/plugins)), take all of it with `plugin: true`:

```yaml
protocol: "0.2"
source:
  git: https://github.com/zmnatz/open-webui-plugin-protocol.git
  path: examples/plugins/excalidraw
  plugin: true
# then: owpp pull excalidraw, which adds ref:
```

owpp fetches the folder at the pinned commit and bundles it like a local plugin, with the upstream's `plugin.yaml`. The local folder's name is the plugin's id. Besides `protocol:` and `source:`, the local manifest can only set:

| Key | Effect |
| --- | --- |
| `function: {valves, global}` | `valves` are merged into the upstream's, key by key; `global` replaces it. |
| `tool: {id, access, valves}` | Each replaces the upstream's. |
| a `config.yaml` file | Used instead of the upstream's. |

Anything else is refused, skills included: they are installed as the upstream wrote them. Its versions are the upstream's (`owpp version` refuses to change them), and `owpp pull` moves the commit without bumping one. The upstream manifest's `protocol:` is checked like a local one. An upstream plugin may take files from git itself, which are fetched too, but not a whole plugin. Nothing in the folder is run: no build script, no `package.json` script. Its `tests/` run only with [`owpp test --upstream`](commands/test.md).

### `include:`

`include: [core, routes, jobs, events, chat_data, shared_assets, live_reload]`: libraries inserted into the function bundle. `static` by a `static/` folder, `templates` by a `templates/` folder, `assets` by an `assets/` folder and `config` by a `config.yaml`; `core` is added by `routes`, `jobs` and `public`. See [libraries](libraries.md).

### `requires:`

```yaml
requires:
  iframe_sandbox_allow_same_origin: true
```

Instance settings the plugin needs but cannot set itself. `owpp deploy` reads the instance's admin config before writing anything and adds a **warning** to its report when one is missing; it never changes the setting or refuses the deploy. `iframe_sandbox_allow_same_origin: true` means Open-WebUI's **iframe Sandbox Allow Same Origin** must be on: without it a sandboxed artifact sends no session to a plugin page. Why, what turning it on costs, and how: [pages in the Artifacts panel](libraries.md#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin). Unknown requirement names and values that are not `true`/`false` are refused.

### `jobs:`

```yaml
jobs:
  sync_every_minutes: ${MCPO_SYNC_MINUTES:-60}   # a number, or an environment template
  adopt_markers: [mcpo-sync]                     # optional: an earlier sync's markers
```

Used with `PluginScheduledSync` (the `jobs` library, which the key brings in). The library adds the `ENABLE` and `SYNC_INTERVAL_MINUTES` valves to the function's `Valves`, and `sync_every_minutes` is the interval's default (`0` repeats nothing: only startup, enable and valve changes). See [libraries: jobs](libraries.md#jobs).

`adopt_markers` is for **moving from another sync**. A sync marks what it writes with its function id (`managed_by`) and replaces or prunes only entries with that mark, so entries an earlier sync wrote under another marker would be left behind. Listing that marker here makes them count as this sync's own: `plugin_sync_markers()` returns the function id plus these. It is a list of exact markers, checked by `owpp check`; leave it out to adopt nothing. It belongs here, not in a valve, because which sync this one succeeds is decided by the deployment, in git, and a valve is for an admin to change in the UI: a marker typed there by mistake would make the sync prune another sync's entries. Remove it once the old entries have been taken over, or keep it; it does nothing more once none carry the old mark.

### Environment templates

Where a value is data the plugin reads (`jobs.sync_every_minutes`, and any value in `config.yaml`), it may be `${NAME}` or `${NAME:-default}` instead of a literal. Write it in block style (`key: ${NAME:-60}`), because a `}` ends an inline `{...}` mapping.

- **Read when the plugin loads inside Open-WebUI, from the container's environment, never when `owpp` bundles or deploys.** The template is embedded as written. A bundle therefore depends only on the plugin folder: the same bundle comes out on every machine whatever it has set, and nothing from a CI environment is baked into the code Open-WebUI stores. The environment variable is set on the Open-WebUI container.
- A value that is one template is typed (`${N:-60}` is the number 60, `${FLAG:-true}` a boolean); inside a longer string it is text. `$${` writes a literal `${`.
- Unset or empty uses the default. With no default the value is absent (null), with a warning in the Open-WebUI log. A `jobs` interval that is not a whole number of minutes falls back to 60 with a warning.
- **It is the way to keep a secret out of git**: write `api_key: ${MY_PLUGIN_API_KEY}` in `config.yaml`, never the key.
- `owpp bundle` and `deploy` check the syntax (`${}`, `${N:60}` and similar are refused), and **`owpp check` lists the variables a plugin reads** and their defaults (`env   MCPO_SYNC_MINUTES (default 60)`).
- Not applied to `function.valves`: those are set by `owpp deploy` through the API, once, with the literal value written.

### `static:` and the `static/` and `templates/` folders

```yaml
static:
  prefix: /my_plugin        # default: /<id>
  access: admin             # user (default), admin or public
```

Optional. **`static/`** holds files that are served as they are, at `<prefix>/<path>`. Every file needs a signed-in user unless `access` says otherwise: `admin` restricts them to admins, and **`public`**, in exactly that word, serves people who are not signed in. Any other value (`none`, `Public`, `true`, ...) is refused. `owpp check` lists a public folder as a `note`.

**`templates/`** holds files the function renders itself, such as a page it fills in for the signed-in user. They are embedded and never served, so there is no key for them: read one with `plugin_template_text()`. See [libraries: static](libraries.md#static) and [templates](libraries.md#templates).

`public/` and `public:` no longer exist: the folder is `static/`, what `dynamic:` used to list is `templates/`, and a manifest or folder with the old names is refused with a message saying where everything went (silently ignoring `public: {access: admin}` would leave a folder open to every signed-in user). A route's own level is set in code, with a marker on the handler; see [libraries: routes](libraries.md#routes). (Not related to a tool's `access: public`, which is Open-WebUI's own visibility for the installed tool.) **Only the keys listed in this document are accepted at the top level of `plugin.yaml`**; anything else is an error with a suggestion, so a typo cannot be silently ignored (keys starting with `x-` are left alone).

### `assets:` and the `assets/` folder

```yaml
assets:
  order: 0     # lower composes first; in custom.css later plugins win a conflict (default 0)
  wrap: true   # run loader.js in its own strict-mode function with a try/catch (default true); write only its body
```

Optional. The folder is what matters: `assets/loader.js` becomes this plugin's fragment of `/static/loader.js` and `assets/custom.css` its fragment of `/static/custom.css`. Nothing else may be in `assets/`: the [Shared Assets Protocol](https://github.com/Classic298/open-webui-plugins/tree/main/shared-assets-protocol) has just those two files. A `__NAME__` in either file is filled from the function's `asset_vars()`. With no `function.py` an `Event` is generated; with one, it must be `class Event(PluginAssets)`. See [libraries: assets](libraries.md#assets).

### `config.yaml`

Structured settings that ship with the plugin, read by the function with `plugin_config()`. See [libraries: config](libraries.md#config).

## Example: a plugin with every part

```yaml
protocol: "0.2"
function:
  title: Excalidraw
  author: you
  version: 3.1.0
  global: true
  required_open_webui_version: 0.10.0
  license: MIT
  description: A shared drawing per chat, opened in the Artifacts panel.
tool:
  id: excalidraw
  title: Excalidraw
  include: [chat_data]
  access: public
include: [routes, chat_data]
```

with the page in `templates/viewer.html`, which needs no manifest entry.
