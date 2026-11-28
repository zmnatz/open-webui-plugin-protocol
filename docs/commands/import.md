# owpp import

```
owpp import <url|file> [--id ID] [--path FOLDER] [--ref BRANCH|TAG|SHA] [--public] [--dir FOLDER]
owpp import --instance ID [--id ID] [--dir FOLDER]
            [--ca-cert PEM] [--client-cert PEM] [--client-key PEM]
```

`owpp import` makes a plugin folder from code that already exists. Then it runs [`owpp check`](check.md) on the folder. The result is a normal plugin with a `plugin.yaml`. Test it with [`owpp test`](test.md) and deploy it with [`owpp deploy`](deploy.md). The command refuses a folder that already exists.

## From a git repository

```sh
owpp import https://github.com/owner/repo/tree/main/inline-visualizer-v2   # a folder
owpp import https://github.com/owner/repo/blob/main/functions/shout.py     # one function, and what is beside it
owpp import https://github.com/owner/repo.git --path functions --ref v1.2  # a clone URL
```

The code is **pinned, not copied**. `plugin.yaml` gets a [`source:`](../plugin-format.md#source) at one commit: the one that you give, else the current commit of the branch, tag or default branch. If the URL or `--ref` names a branch or tag, `source:` records it, and [`owpp pull`](pull.md) follows it.

The URL or `--ref` can also give a full commit SHA (40 lowercase hex characters). Then `source:` pins that commit and has no `branch:` or `tag:`. The command refuses a short SHA, because it reads a short SHA as a branch or tag name.

**Caution:** [`owpp pull`](pull.md) moves a pin without `branch:` or `tag:` to the latest commit of the [default branch](../plugin-format.md#source).

The command looks for these in the folder:

| What | How it is recognised | In `plugin.yaml` |
| --- | --- | --- |
| a whole owpp plugin | a `plugin.yaml` | `source: {plugin: true}`, and no `function:`, `tool:` or `skills:` |
| the function | a `.py` with a docstring header and one of `class Filter`, `Action`, `Pipe` or `Event` | `function: {file}` (type upstream: its header, version included, is the upstream's) |
| a tool | a `.py` with `class Tools` | `tool: {id, file}` |
| skills | each `SKILL.md`, alone or in a folder of its own | `skills: {<name>: {dir}}` or `{file}` |

For the function and the tool, the command reads only the `.py` files in the folder itself, not in its subfolders. It also looks for skills in subfolders. It refuses two functions or two tools in one folder. To choose one function, give the URL of its file.

If there is a tool or a skill but no function, the plugin is an installer: owpp generates the function that installs them. Except for a whole owpp plugin, the folder also gets a README, a CHANGELOG and tests. These are the files that [`owpp create`](create.md) writes for a plugin from git. The tests fetch the pinned files.

**The tool and skills are private** (admins only), unless you give `--public`. A git page cannot say who can use a tool, so the report tells you to decide. The command also adds no `requires:`.

The URL can have one of these forms:

- A GitHub or GitLab page: `.../tree/<branch>/<folder>` or `.../blob/<branch>/<folder>/<file>`.
- A repository: its GitHub page, or a clone URL (https, ssh or `user@host:path`). Give the folder with `--path`, and the branch, tag or commit SHA with `--ref`.

The command reads the first part after `tree/` or `blob/` as the branch, tag or commit SHA. For a branch with a slash in its name, use the clone URL and `--ref`.

## From a file, or a function on Open-WebUI

```sh
owpp import shout.py              # a .py, as Open-WebUI stores a function
owpp import --instance shout      # the function with id shout, read from OPEN_WEBUI_URL
```

The keys of the docstring header move into `plugin.yaml` under `function:`, one on each line. The rest of the file becomes `function.py`. The bundle of the plugin is the same code again, so the deploy stores what you imported.

The command drops each header line that is not `key: value`, or that has no value, and lists it in the report. It stops if the header has a `file:` or `valves:` key, because these keys mean something else in `plugin.yaml`.

The folder also gets a README and a first test that loads the function. If the header has a version, it gets a CHANGELOG with an entry for that version. Add your other tests beside the first one ([writing a test](../testing/writing.md)).

### What owpp put into it, taken back out

A function that owpp deployed is a bundle. It holds owpp's [libraries](../libraries.md), the files that they carry and, with a tool or skills, the [runtime](../runtime.md). The import does the **Unbundling**: each part goes back to what it was made from. Thus `function.py` holds the plugin's own code, and the bundle of the new plugin gives the same function again.

| In the bundle | In the new folder |
| --- | --- |
| a library (`# end plugin ... library`) | a name in `include:` (not for a library that the plugin's files or another library turn on) |
| the data of a library | `templates/`, `static/`, `assets/`, `config.yaml`, and the `jobs:`, `static:` and `assets:` settings that are not the defaults |
| the runtime's tool | `tool.py` and `tool:` (its header keys, `include:`, `access:`, `valves:`) |
| the runtime's skills | `skills/<id>/`, with `access: public` in the `SKILL.md` of a public skill |
| `meta.requires` (with `--instance`) | `requires:` |

The code that used those libraries gets the `from owpp.lib import` line that it needs.

The import recognises a library where the bundler puts it, after the docstring header, by its first lines and its `# end` line. Thus it also reads many bundles from other owpp versions. A block that it does not recognise stays, and the report names it. Delete that block, and add the library to `include:`.

`requires:` comes back only if the owpp that deployed the function recorded `meta.requires`. If not, the report tells you to add it again. Code that the function and the tool shared (`shared.py`) is in both `function.py` and `tool.py`. You can move it into a `shared.py` again.

The [Shared Assets Protocol](https://github.com/Classic298/open-webui-plugins/tree/main/shared-assets-protocol) has two blocks: the shared asset block and live reload. If a block is byte-identical to owpp's copy, as the protocol requires, it becomes `include: [shared_assets]` or `live_reload`. This applies anywhere in the function. Without this step, [`owpp check`](check.md) refuses the code, because the function's own code must not change `app.routes`.

A copy that differs is the plugin's own code. It stays, and the report says so. `owpp check` refuses it. Import that plugin from git, which takes the code as it is, or replace the block with `include:`.

### From an instance

`--instance` signs in as [`owpp deploy`](deploy.md#signing-in) does. It uses the same [environment variables](../environment-variables.md#signing-in), [TLS](../environment-variables.md#tls) variables and flags. The plugin keeps the function's id, unless you give `--id`. With the same id, the first deploy updates that function and marks it as managed. It does not add a second copy.

The import does not copy the valves, because they can hold keys or passwords. The deploy keeps the values on the instance. Put defaults under `function: valves:`.

## Options

| Option | Meaning |
| --- | --- |
| `url\|file` | A git URL, or a `.py` file. The command refuses a folder on disk. Give the URL of its repository, so that the code is pinned. |
| `--instance ID` | Import the function with this id from the instance at `OPEN_WEBUI_URL`. |
| `--ca-cert PEM` | With `--instance`: as for [`owpp deploy`](deploy.md#options). |
| `--client-cert PEM` | With `--instance`: as for [`owpp deploy`](deploy.md#options). |
| `--client-key PEM` | With `--instance`: as for [`owpp deploy`](deploy.md#options). |
| `--id ID` | The plugin's id. Default: the instance's id, or a name from the file or folder (the repository's name for its root). In a name, hyphens become underscores. |
| `--path FOLDER` | With a clone URL: the folder in the repository. |
| `--ref BRANCH\|TAG\|SHA` | With a clone URL: the branch or tag to pin and follow, or a full commit SHA to pin. Default: the default branch. |
| `--public` | With a git URL: give every user the tool and skills that the plugin installs (`access: public`). |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |
