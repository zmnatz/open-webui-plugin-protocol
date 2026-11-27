# owpp version

```
owpp version [id] [patch|minor|major|X.Y.Z] [--tool | --skill name] [-m text] [--dir FOLDER]
```

`owpp version` shows the versions of the plugins, or gives a plugin a new version.

## Versions

A plugin has three kinds of version, each where Open-WebUI reads it:

| Version | Where it is |
| --- | --- |
| The **function's** | `version:` under `function:` in `plugin.yaml`. It is the version of the plugin, and Open-WebUI shows it. |
| The **tool's** | `version:` under `tool:` in `plugin.yaml`. |
| Each **skill's** (optional) | `version:` in the front matter of its `SKILL.md`. |

A loose `<id>.py` has its version in its docstring header.

[`owpp check --since`](check.md#a-change-needs-a-new-version) fails on a change without a new version. [`owpp deploy`](deploy.md#deploying-an-older-version) refuses to put an older version over a newer one, unless you give `--force`.

## Showing them

```
$ owpp version
excalidraw                  3.1.0
  tool excalidraw           (no version)
inline_visualizer           1.0.0
  tool inline_visualizer    (the upstream's)
  skill visualize           (the upstream's)
```

The command reads the versions from the files, so it fetches nothing from git. It shows `(the upstream's)` for code that a plugin takes verbatim from a `source:`. A tool with `from: function` shows the same text, although its version is the function's.

## A new version

To give a plugin a new version, give its id and the version. `patch`, `minor` and `major` raise that part, and `X.Y.Z` sets the version.

The command changes only the `version:` line, and keeps comments and layout. If there is no such line, it adds one, after `title:` in `plugin.yaml` or after `name:` in a `SKILL.md`. If there is no version yet, `patch`, `minor` and `major` give 0.1.0. If the current version is not `X.Y.Z`, give the new one as `X.Y.Z`.

The command refuses to change these versions:

- Code that a plugin takes verbatim from a `source:`, which keeps the upstream's version.
- Any version of a plugin taken whole from git.
- A tool with `from: function`, whose version is the function's.

### `CHANGELOG.md`

A new function version adds a `## <version> (<date>)` entry at the top of the plugin's `CHANGELOG.md`. If the file does not exist, the command makes it. The entry holds the `-m` text, or a placeholder line for you to replace. A loose `<id>.py` gets no entry.

[`owpp create`](create.md) writes a `CHANGELOG.md` for each new plugin. If the file has no `## <version>` entry for the function's current version, [`owpp check`](check.md) warns. Thus `--strict` fails.

## Options

| Option | Meaning |
| --- | --- |
| `id` | The plugin. Default: show every plugin. |
| `patch`, `minor`, `major`, `X.Y.Z` | The new version. Default: show the versions. |
| `--tool` | Change the tool's version instead of the function's. |
| `--skill name` | Change the version of that skill, or add one. |
| `-m`, `--message` | The text of the `CHANGELOG.md` entry, for the function's version. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

Use `--tool`, `--skill` and `-m` only with a new version.

## Examples

```sh
owpp version                      # every plugin's versions: its own, its tool's, each skill's
owpp version viz                  # one plugin's
owpp version viz patch            # a new version: 1.0.0 -> 1.0.1, and a CHANGELOG.md entry
owpp version viz minor -m "Faster lookups."
owpp version viz 2.0.0
owpp version viz patch --tool     # the tool's version
owpp version viz patch --skill draw   # that skill's (added if it had none)
```

## Related

- [`owpp check --since`](check.md#a-change-needs-a-new-version): fails on a change without a new version.
- [`owpp pull`](pull.md): gives a new version when it moves a pinned commit.
- [`owpp deploy`](deploy.md#deploying-an-older-version): refuses to go back a version.
