# Plugin format

## Folder

```
plugins/<id>/
  plugin.yaml      required
  function.py      the function (omit it for a plugin that is only a tool and skills)
  tool.py          the tool
  shared.py        code that both use: each does `from shared import NAME`
  skills/<id>/     SKILL.md plus any supporting files, installed as a whole folder
  static/          files served as they are; index.html is the plugin's page
  templates/       files that the plugin renders itself; embedded, never served
  assets/          loader.js and custom.css: this plugin's fragments of the shared /static files
  config.yaml      structured settings that ship with the plugin; read with plugin_config()
  README.md        required in practice: see "Documentation" in the authoring guide
```

A plugin can also be a single file, `<id>.py`: a function with no tool or skills.

The **function id** is the name of the folder, or the name of the file without `.py`. owpp makes it lowercase. The id must match Open-WebUI's rule, `[a-z_][a-z0-9_]*`, and `owpp deploy` refuses any other id. Hyphens are not allowed: use the name `my_plugin`, not `my-plugin`.

## `plugin.yaml`

A tool or skills need a `function:` section, because the function is their parent. All other sections are optional. The current protocol version is `0.7`.

At the top level of `plugin.yaml`, owpp accepts only the keys that this page describes. Any other key is an error, so a typing mistake cannot hide a setting. If the key is close to a known one, the error suggests it. owpp ignores keys that start with `x-`.

### `protocol:`

```yaml
protocol: "0.7"   # the version of the plugin format this manifest was written for
```

The value is a quoted major.minor string that follows owpp's major.minor version. A release moves the protocol version when it does one of these:

- changes what a manifest key means;
- removes a key;
- changes how you must write the plugin's code (0.5: every file imports what it uses).

owpp 0.7 also moved it, to match the release. 0.7 changes no key, so a 0.5 manifest means the same in 0.7. There is no 0.4 or 0.6: those releases did not change the version.

`owpp init`, `owpp create` and the examples in this repository use `protocol: "0.7"`. It is only a manifest key: unlike the keys of `function:`, owpp does not copy it into the deployed header.

- **Write the quotes.** owpp refuses an unquoted `0.5`, which is a YAML number. It also refuses a patch version such as `"0.5.0"`.
- owpp refuses a version that is **newer** than its own, because the keys can mean something else. Upgrade owpp first.
- owpp accepts an **older** version. `owpp check` prints a note that points to the migration.
- A manifest with **no key** is a 0.1 plugin, from before the key existed. `owpp check` warns about it, and `owpp check --strict` fails.

[`owpp migrate`](commands/migrate.md) brings old plugins up to 0.7, one version step at a time ([upgrading owpp](upgrading.md)):

| Step | What it does |
| --- | --- |
| 0.1 -> 0.2 | Adds the `protocol:` line. |
| 0.2 -> 0.3 | Changes `source: track:` into `branch:` or `tag:`. |
| 0.3 -> 0.5 | Adds the imports that each file now needs. |
| 0.5 -> 0.7 | Changes only the version. |

### `function:`

owpp writes the keys of `function:` into the docstring header, which Open-WebUI reads as the function's manifest. It writes one `key: value` line for each key, in the order that you give. It does not write `valves` into the header.

| Key | Meaning |
| --- | --- |
| `title`, `author`, `author_url`, `funding_url`, `version`, `license`, `description`, `required_open_webui_version`, ... | owpp writes them into the header unchanged. Each value must fit on one line. |
| `global` | Controls whether the function is global (see below). |
| `valves` | `{name: value}`. Each deploy sets these valves. All other valves keep their values. |
| `file` | With `source:`, owpp takes the function from the git repository unchanged, header included. The only other keys allowed are then `global` and `valves`. |

`global` applies to filters and actions only. owpp refuses `global: true` on an event or a pipe.

| `global` | What a deploy does |
| --- | --- |
| `true` | Makes the function active and global, on every run. |
| `false` | Never makes it global, and removes it from global on every run. Use this for a filter that each user switches on (a toggle). |
| not set | Makes a new filter global once, on its first deploy, because a filter that is not attached to a model does nothing. |

Open-WebUI reads the header line by line and splits each line at the first colon. The header is not YAML. Open-WebUI stores a block value such as `description: >` as `>`, and the lines below it are lost. owpp refuses such a header. In a header, `author: @someone` is valid. In `plugin.yaml`, which is YAML, put that value in quotes.

### Function type

A function has one type. owpp finds it as Open-WebUI does, from the class at the top level of the code: `class Pipe`, `class Filter`, `class Action` or `class Event`. If the code defines none of them, or more than one, that is an error. `owpp list` and the deploy report show the type. The type controls whether `global` applies:

| Type | Runs | `global` | Typical use |
| --- | --- | --- | --- |
| **filter** | On every chat completion (`inlet`/`outlet`/`stream`), for its attached models, or for all models when global. It can be a user toggle (`self.toggle = True`). | yes | Change the request or reply, add artifacts, attach files |
| **action** | A button under a message | yes | User-triggered operations |
| **event** | On Open-WebUI lifecycle events (`system.startup.completed`, `function.enable_started`, `function.valves_updated`, ...), not tied to a chat | **no** | Sync jobs, schedulers, routes, dashboards |
| **pipe** | Appears as a model | no | Custom model backends |

### `tool:`

| Key | Meaning |
| --- | --- |
| `id` | The tool id. Default: the plugin id. |
| `title`, `description`, and other header keys | The header of the tool bundle. Its code is `tool.py`. |
| `file` | With `source:`, owpp takes the tool from the git repository unchanged. |
| `from: function` | Installs the function's own bundle as the tool: one module is both. |
| `access` | `public` lets every signed-in user use the tool. Without it, only admins can. See [public tools and skills](runtime.md#public-tools-and-skills). |
| `valves` | `{name: value}`, set on the tool. See [valves on the parent](runtime.md#valves-on-the-parent). |
| `include` | Libraries for the tool bundle. The function's `include:` does not apply to the tool. |
| `templates` | The files of `templates/` that the tool embeds. It needs `include: [templates]`. Each entry is a path, or a folder with a final `/` (`[launcher/]`). Without this key, the tool embeds every template. owpp refuses an entry that matches no file. |

### `skills:`

```yaml
skills:
  my-skill:
    file: SKILL.md           # or:  dir: skills/my-skill   (the whole folder)
    access: public
```

owpp includes each local skill, a folder `skills/<id>/`, without an entry here. A local skill sets its access in the front matter of its SKILL.md (`access: public`), as `owpp create` writes it.

Use `skills:` for other skills, such as those from a `source:`. Each one is a `file:` (a SKILL.md) or a `dir:` (a whole folder). A skill's `access` works like [a tool's](runtime.md#public-tools-and-skills). If both the entry and the front matter give `access`, the entry wins.

### `source:`

```yaml
source:
  git: https://github.com/owner/repo.git   # https, ssh, or user@host:path
  ref: 917c88f3029c0c6500139ba7b7b061f358d8aaea   # full 40-character commit SHA
  path: subfolder                           # "" for the repo root
  branch: main                              # optional: the branch `owpp pull` follows (or tag:)
```

With `source:`, owpp reads `function: {file}`, `tool: {file}` and `skills: {<id>: {file|dir}}` from that repository at that commit. For the allowed URLs and the limits, see [bundling: git sources](bundling.md#git-sources). owpp keeps the files in [`.owpp/`](bundling.md#the-owpp-folder). Add that folder to your `.gitignore`.

You can write the manifest without `ref`. [`owpp pull`](commands/pull.md) then looks up the latest commit and adds the line. Until then, `owpp check` and `owpp deploy` refuse the plugin.

`branch` or `tag` names what [`owpp pull`](commands/pull.md) follows. Give one of them, not both. `pull` moves `ref` to the latest commit of that branch, or to the commit of that tag. With neither key, `pull` follows the repository's default branch. The name must be a branch or tag name that git allows, and it can never be a git option.

These two keys never change what a normal deploy writes: only `ref` does. `owpp deploy --dry-run --latest` and `owpp build --latest` follow them, as `pull` does.

#### A whole plugin from git

If the folder at `path` is an owpp plugin (it has a `plugin.yaml`, like the [examples](../examples/plugins)), you can take all of it. Set `plugin: true`:

```yaml
protocol: "0.7"
source:
  git: https://github.com/zmnatz/open-webui-plugin-protocol.git
  path: examples/plugins/excalidraw
  plugin: true
# then: owpp pull excalidraw, which adds ref:
```

owpp takes the folder at the pinned commit and writes it to [`.owpp/modules/<id>/`](bundling.md#the-owpp-folder). Then it bundles that folder like a local plugin, with the upstream `plugin.yaml`. The name of your local folder is the plugin id. Besides `protocol:`, `source:` and `x-` keys, your local manifest can set only these:

| Key | Effect |
| --- | --- |
| `function: {valves, global}` | owpp merges `valves` into the upstream valves, key by key. `global` replaces the upstream value. |
| `tool: {id, access, valves}` | owpp merges `valves` key by key. `id` and `access` replace the upstream values. |
| a `config.yaml` file | owpp uses it instead of the upstream file. |

owpp refuses anything else, `skills:` included: it installs the skills as the upstream wrote them. Also:

- The versions are the upstream's. `owpp version` refuses to change them, and `owpp pull` moves the commit without a new version.
- owpp checks the upstream `protocol:` as it checks a local one.
- The upstream plugin can take files from git itself, and owpp fetches them too. It cannot take a whole plugin.
- When owpp bundles the plugin, it runs nothing in the folder: no build script and no `package.json` script. The upstream `tests/` run only with [`owpp test --upstream`](commands/test.md).

### `include:`

`include:` lists the libraries that owpp puts into the function bundle. You can ask for `core`, `routes`, `jobs`, `events`, `chat_data`, `shared_assets` and `live_reload`, for example `include: [routes, chat_data]`.

The contents of the plugin turn on some libraries without `include:`, for example a `static/` folder or a `jobs:` section. A library can also add the libraries that it is built on. [Libraries](libraries.md) shows what turns on each library and what it adds.

### `requires:`

```yaml
requires:
  iframe_sandbox_allow_same_origin: true
```

`requires:` names instance settings that the plugin needs but cannot set itself. Before `owpp deploy` writes anything, it reads the instance's admin config. If a setting is missing, the deploy report shows a **warning**. The deploy never changes the setting, and a missing setting never stops the deploy.

`iframe_sandbox_allow_same_origin: true` means that Open-WebUI's **iframe Sandbox Allow Same Origin** must be on. Without it, a sandboxed artifact sends no session to a plugin page. For the reason, the risk and the setup, see [pages in the Artifacts panel](libraries.md#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin).

owpp refuses an unknown requirement name, and a value that is not `true` or `false`.

### `jobs:`

```yaml
jobs:
  sync_every_minutes: ${MCPO_SYNC_MINUTES:-60}   # a number, or an environment template
  adopt_markers: [mcpo-sync]                     # optional: an earlier sync's markers
```

`jobs:` configures `PluginScheduledSync`, from the [`jobs` library](libraries.md#jobs), which this key turns on. The library adds the `ENABLE` and `SYNC_INTERVAL_MINUTES` valves to the function's `Valves`. `sync_every_minutes` is the default interval (60 if you do not set it). With `0`, the sync does not repeat: it runs only at startup, on enable and on a valve change.

Use `adopt_markers` when you **move from another sync**. A sync marks what it writes with its function id (`managed_by`), and it replaces or prunes only entries with that mark. Entries that an earlier sync wrote with a different marker stay behind. If you list that marker here, the sync treats those entries as its own: `plugin_sync_markers()` returns the function id and the listed markers.

**Caution:** List only the markers of the sync that this one replaces. The sync can delete entries that have a listed marker.

The value is a list of exact markers, which `owpp check` validates. Without the key, the sync adopts nothing. After the sync takes over the old entries, you can remove the key or keep it. It does nothing when no entry has the old mark.

The key is in `plugin.yaml`, not in a valve, because the deployment decides in git which sync this one replaces. An admin can change a valve in the UI. A marker typed there by mistake can make the sync prune the entries of another sync.

### Environment templates

Some values are data that the plugin reads: `jobs.sync_every_minutes`, and any value in `config.yaml`. Such a value can be `${NAME}` or `${NAME:-default}` instead of a literal. Write it in block style (`key: ${NAME:-60}`), because a `}` ends an inline `{...}` mapping.

- **The plugin reads the variable inside Open-WebUI**, from the container's environment, never when `owpp` bundles or deploys. Set the variable on the Open-WebUI container.
- owpp embeds the template as written. Thus a bundle depends only on the plugin folder. Each machine makes the same bundle, and no variable from CI gets into the code that Open-WebUI stores.
- A value that is one template has a type: `${N:-60}` is the number 60, and `${FLAG:-true}` is a boolean. A template inside a longer string is text. `$${` writes a literal `${`.
- An unset or empty variable uses the default. Without a default, the value is null (empty inside a longer string), and the Open-WebUI log shows a warning.
- The default of the `jobs` interval must be a whole number. If the variable is not a whole number of minutes, the interval is 60, with a warning.
- **Use a template to keep a secret out of git.** In `config.yaml`, write `api_key: ${MY_PLUGIN_API_KEY}`, never the key.
- `owpp bundle` and `deploy` check the syntax, and refuse `${}`, `${N:60}` and similar.
- **`owpp check` lists the variables that a plugin reads**, with their defaults (`env   MCPO_SYNC_MINUTES (default 60)`).
- Templates do not apply to `function.valves`. `owpp deploy` sets those through the API, with the literal value.

### `static:` and the `static/` and `templates/` folders

```yaml
static:
  prefix: /my_plugin        # default: /<id>
  access: admin             # user (default), admin or public
```

The folders and the key are optional. The `static:` key needs a `static/` folder.

**`static/`** holds files that Open-WebUI serves unchanged, at `<prefix>/<path>`. `access` says who can fetch them:

- `user` (the default): signed-in users;
- `admin`: admins only;
- `public`: everyone, signed in or not.

owpp accepts exactly these words, and refuses any other value (`none`, `Public`, `true`, ...). `owpp check` shows a public folder as a `note`.

**`templates/`** holds files that the plugin renders itself, such as a page that it fills in for the signed-in user. owpp embeds them, and nothing serves them, so they need no key. Read one with `plugin_template_text()`. See [libraries: static](libraries.md#static) and [templates](libraries.md#templates).

`public/` and `public:` do not exist now. The folder is `static/`, and the files that `dynamic:` listed go in `templates/`. owpp refuses the old names, with a message that says where everything went. If owpp ignored `public: {access: admin}`, every signed-in user could open the folder.

To set the level of a route, put a marker on its handler: see [libraries: routes](libraries.md#routes). A tool's `access: public` is a different setting: it controls who can use the installed tool.

### `assets:` and the `assets/` folder

```yaml
assets:
  order: 0     # lower composes first; in custom.css later plugins win a conflict (default 0)
  wrap: true   # run loader.js in its own strict-mode function with a try/catch (default true); write only its body
```

The key is optional, and it needs an `assets/` folder. The folder turns on the [`assets` library](libraries.md#assets):

- `assets/loader.js` becomes this plugin's fragment of `/static/loader.js`.
- `assets/custom.css` becomes this plugin's fragment of `/static/custom.css`.

`assets/` can hold only these two files, because the [Shared Assets Protocol](https://github.com/Classic298/open-webui-plugins/tree/main/shared-assets-protocol) has no others. A `function.py` must define `class Event(PluginAssets)`. Without a `function.py`, owpp generates that class. A plugin that also has a tool or skills needs the `function.py`.

### `config.yaml`

`config.yaml` holds structured settings that ship with the plugin. The function reads them with `plugin_config()`. See [libraries: config](libraries.md#config).

## Example: a function with a tool and a page

```yaml
protocol: "0.7"
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

The page is in `templates/viewer.html`, which needs no manifest entry.
