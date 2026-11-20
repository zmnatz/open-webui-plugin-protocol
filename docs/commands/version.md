# owpp version

```
owpp version [id] [patch|minor|major|X.Y.Z] [--tool | --skill name] [-m text] [--dir FOLDER]
```

Shows the plugins' versions, or gives one a new version.

## Versions

A plugin has up to three versions, each where Open-WebUI reads it: the **function's** (`version:` under `function:` in `plugin.yaml`, the plugin's version, which Open-WebUI shows), the **tool's** (`version:` under `tool:`), and each **skill's** (`version:` in its SKILL.md front matter, optional). A loose `<id>.py` has its version in its docstring header.

[`owpp check --since`](check.md#a-change-needs-a-new-version) fails on a change without a new version, and [`owpp deploy`](deploy.md#deploying-an-older-version) refuses to put an older version over a newer one.

## Showing them

```
$ owpp version
excalidraw                  3.1.0
  tool excalidraw           (no version)
inline_visualizer           1.0.0
  tool inline_visualizer    (the upstream's)
  skill visualize           (the upstream's)
```

Shown versions are read from the files, so a plugin taken from git needs no fetch: what it takes verbatim shows as the upstream's.

## A new version

With a new version, it rewrites the one `version:` line, keeping comments and layout (and adds it, after `title:`, when there is none; no version bumps to 0.1.0). `patch`, `minor` and `major` bump that part; `X.Y.Z` sets it. Code taken verbatim from a `source:` keeps the upstream's version, so `owpp version` refuses to change it.

### `CHANGELOG.md`

A function bump adds a `## <version> (<date>)` entry to the top of the plugin's `CHANGELOG.md`, which it creates if needed: the `-m` text, or a line to replace. [`owpp create`](create.md) writes one. When a plugin has one, [`owpp check`](check.md) warns if it has no `## <version>` entry for the function's current version (so `--strict` fails on it).

## Options

| Option | Meaning |
| --- | --- |
| `id` | The plugin. Default: every plugin, shown. |
| `patch`, `minor`, `major`, `X.Y.Z` | The new version. Default: show the versions. |
| `--tool` | Change the tool's version instead of the function's. |
| `--skill name` | Change that skill's version (added if it had none). |
| `-m`, `--message` | The `CHANGELOG.md` entry, for the plugin's own version. |
| `--dir FOLDER` | The plugins folder. Default `$OWPP_PLUGINS_DIR`, else `./plugins`. |

`--tool`, `--skill` and `-m` go with a new version only.

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
- [`owpp pull`](pull.md): bumps the version when it moves a pinned commit.
- [`owpp deploy`](deploy.md#deploying-an-older-version): refuses to go back a version.
