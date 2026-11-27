# owpp import

```
owpp import <url|file> [--id ID] [--path FOLDER] [--ref BRANCH|TAG] [--public] [--dir FOLDER]
owpp import --instance ID [--id ID] [--dir FOLDER]
```

Makes a plugin folder from code that already exists, then runs [`owpp check`](check.md) on it. What it writes is a plugin like any other, with a `plugin.yaml`, so it is tested with [`owpp test`](test.md) and deployed with [`owpp deploy`](deploy.md). It refuses a folder that exists.

## From a git repository

```sh
owpp import https://github.com/owner/repo/tree/main/inline-visualizer-v2   # a folder
owpp import https://github.com/owner/repo/blob/main/functions/shout.py     # one function, and what is beside it
owpp import https://github.com/owner/repo.git --path functions --ref v1.2  # a clone URL
```

The code is **pinned, not copied**: `plugin.yaml` gets a [`source:`](../plugin-format.md#source) at the commit the branch (or tag, or the default branch) points at now, and records the branch so [`owpp pull`](pull.md) follows it. In the folder it finds:

| What | How it is recognised | In `plugin.yaml` |
| --- | --- | --- |
| a whole owpp plugin | a `plugin.yaml` | `source: {plugin: true}`, and nothing else |
| the function | a `.py` with a docstring header and one of `class Filter`, `Action`, `Pipe` or `Event` | `function: {file}` (type upstream: its header, version and all, are the upstream's) |
| a tool | a `.py` with `class Tools` | `tool: {id, file}` |
| skills | each `SKILL.md`, alone or in a folder of its own | `skills: {<name>: {dir}}` or `{file}` |

Only the folder's own `.py` files are read for the function and the tool, not its subfolders. Two functions in one folder are refused: import the one you want by the URL of its file. With a tool or skills and no function, the plugin is an installer: owpp generates the function that installs them. The README, CHANGELOG and tests are [`owpp create`](create.md)'s for a plugin from git, and its tests fetch the pinned files.

**The tool and skills are private** (admins only) unless `--public` is given, and nothing is required of the instance (`requires:`): a GitHub page cannot say who should use a tool, so the report lists what was left at its narrowest for you to decide.

The URL is a GitHub or GitLab page (`.../tree/<branch>/<folder>`, `.../blob/<branch>/<folder>/<file>`, or the repository), or a clone URL (https, ssh or `user@host:path`) with `--path` and `--ref`. The branch is the first part after `tree/` or `blob/`: a branch with a slash in its name needs the clone URL and `--ref`.

## From a file, or a function on Open-WebUI

```sh
owpp import shout.py              # a .py, as Open-WebUI stores a function
owpp import --instance shout      # the function with id shout, read from OPEN_WEBUI_URL
```

The docstring header moves into `plugin.yaml` under `function:`, one key per line, and the rest of the file is `function.py`. Bundled, it is the same code again: the deploy stores what you imported. A header line that is not `key: value` (or has no value) is dropped and listed in the report. It also writes a README, a CHANGELOG (with an entry for the header's version) and a first test that loads it, for the rest of its tests to go beside ([writing a test](../testing/writing.md)).

### What owpp put into it, taken back out

A function owpp deployed is its bundle: owpp's [libraries](../libraries.md), the files they carry, and for a plugin with a tool or skills the [runtime](../runtime.md) that installs them. Imported, each goes back to what it was made from, so `function.py` is the plugin's own code and bundling the import gives the same function again:

| In the bundle | In the folder it writes |
| --- | --- |
| a library (`# end plugin ... library`) | a name in `include:` (one that `templates/`, `static/`, `config.yaml` or another library turns on is left out) |
| its data | `templates/`, `static/`, `assets/`, `config.yaml`, and the `jobs:`, `static:` and `assets:` settings that are not the defaults |
| the runtime's tool | `tool.py` and `tool:` (its header keys, `include:`, `access:`, `valves:`) |
| the runtime's skills | `skills/<id>/`, with `access: public` in a public skill's `SKILL.md` |
| `meta.requires` (with `--instance`) | `requires:` |

The code that used those libraries gets the `from owpp.lib import` line it needs. A library is recognised where the bundler puts it, after the docstring header, by its first lines and its `# end` line, so a bundle from another version of owpp imports too; a block it cannot recognise stays, and the report names it, to delete and add to `include:` by hand. `requires:` comes back only from a function deployed by an owpp that records it in `meta.requires`; otherwise the report says to add it back if the plugin had one. Code the function and the tool shared (`shared.py`) is in both files: it can go back into a `shared.py` by hand.

The [Shared Assets Protocol](https://github.com/Classic298/open-webui-plugins/tree/main/shared-assets-protocol)'s two blocks (the shared asset block and live reload), anywhere in a function, become `include: [shared_assets]` and `live_reload` when they are byte-identical to owpp's copy, as the protocol asks of every copy. Left in, they would fail `owpp check`, which refuses a function's own code that changes `app.routes`. A copy that differs is the plugin's own code and stays, and the report says so: `owpp check` refuses it, so import that plugin from git (which takes its code as it is), or replace the block with `include:`.

`--instance` signs in as [`owpp deploy`](deploy.md#signing-in) does, from the same [environment variables](../environment-variables.md#signing-in), and keeps the function's id. The first deploy then updates that function (and marks it as managed) instead of adding a second copy. Its valves are not copied, since they may hold keys or passwords: the deploy keeps the instance's, and defaults go under `function: valves:`.

## Options

| Option | Meaning |
| --- | --- |
| `url\|file` | A git URL, or a `.py` file. A folder on disk is refused: give its repository's URL, so the code is pinned. |
| `--instance ID` | Import the function with this id from the instance at `OPEN_WEBUI_URL`. |
| `--id ID` | The plugin's id. Default: the file's name, the folder's (the repository's, for its root), or the instance's id. Hyphens become underscores. |
| `--path FOLDER` | With a clone URL: the folder in the repository. |
| `--ref BRANCH\|TAG` | With a clone URL: the branch or tag to pin and follow. Default: the default branch. |
| `--public` | Give every user the tool and skills it installs (`access: public`). |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |
