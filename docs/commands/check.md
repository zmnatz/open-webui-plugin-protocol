# owpp check

```
owpp check [id ...] [--strict] [--since ref] [--dir FOLDER]
```

Bundles each plugin exactly as [`owpp deploy`](deploy.md) would, then, for the function and each tool it embeds, compiles it and lists names that are used but never defined or imported (a typo, or a library the plugin forgot to `include`). With no ids it checks every plugin. It fetches remote sources, so it checks the real upstream code. The [GitHub Action](../tooling.md#github-action) runs it before every deploy.

```
$ owpp check
ok    excalidraw (99239 chars)
ok    tool excalidraw (31664 chars)
env   EXCALIDRAW_ASSETS_URL (default empty)
ok    mcpo_sync (24227 chars)
warn  mcpo_sync/function.py:40: valve TIMEOUT has no description: the admin UI shows it
env   MCPO_SYNC_MINUTES (default 60)
1 warning(s)
```

Each line starts with what it is:

- **`ok`** or **`FAIL`**: a bundle that compiles with every name defined, or what is wrong with it.
- **`warn`**: something the people using the plugin see:
  - a valve with no `description` (the admin UI lists each valve with it),
  - a tool method with no docstring, a parameter with no type hint, or a parameter the docstring does not describe with `:param name:` (Open-WebUI builds the spec the model reads from those). Injected parameters such as `__user__` and `__metadata__` are ignored.
  - a name the plugin defines that is also a library's in its bundle (bundled, the two are one module, so the plugin's replaces the library's),
  - a `from __future__` line in `shared.py` that `function.py` or `tool.py` lacks, or the other way round (they all move to the top of the bundle, so they apply to every file in it).
  - a `CHANGELOG.md` with no `## <version>` entry for the function's current version ([versions](version.md#changelogmd)),
  - a `plugin.yaml` with no `protocol:` key ([upgrading](../upgrading.md)).

  Warnings about code read the plugin's own source (`function.py`, `tool.py`, `shared.py`, or a loose `<id>.py`) with real file and line numbers, and skip a plugin that takes its code from a pinned `source:`, which is not yours to lint. They do not change the exit status; **`--strict` makes them fail**, for CI.
- **`note`**: worth knowing, never a failure: a manifest on an older [protocol version](../plugin-format.md#protocol), pointing at [`owpp migrate`](migrate.md), and every place the plugin serves people who are not signed in (a `public` mount, or `static: {access: public}`).
- **`env`**: an environment variable the plugin reads from its `jobs:` and `config.yaml`, with its default.

It exits 1 when a bundle fails, when `--since` finds a change without a new version, or, with `--strict`, on any warning. An id that is not in the plugins folder fails with `no plugin <id> in <folder>`.

## Options

| Option | Meaning |
| --- | --- |
| `id ...` | The plugins to check. Default: all. |
| `--strict` | Fail on warnings too. |
| `--since ref` | Also fail when a plugin changed since this git ref (for example `origin/main`) but its version did not. See [below](#a-change-needs-a-new-version). |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## A change needs a new version

```sh
owpp check --since origin/main
FAIL  viz: changed since origin/main but its version is still 1.0.0 (run `owpp version viz patch`)
FAIL  tool viz: changed since origin/main but its version is still 1.0.0 (run `owpp version viz patch --tool`)
```

It bundles every plugin as it was at that git ref (with `git archive`) and as it is now, and fails for what changed without a new version:

- a **tool or skill that has a version** must bump its own when it changes;
- the **plugin** (the function's version) must bump when its own code changed, when a tool or skill without a version changed, was added or was removed, or when the commit of its `source:` moved ([`owpp pull`](pull.md) bumps it for you).

A plugin that did not exist at that ref needs nothing. Code taken verbatim from a `source:` (an upstream function, tool or skills) is the upstream's to version: its changes count as the plugin's. It needs the `git` CLI. In CI, check out with `fetch-depth: 0` and pass the base branch, for example `since: origin/${{ github.base_ref }}` on a pull request. [`owpp version`](version.md) gives a plugin its new version.

## Examples

```sh
owpp check                          # every plugin
owpp check my_plugin --strict       # one, failing on warnings
owpp check --strict --since origin/main
```

## Related

- [`owpp version`](version.md): give a changed plugin a new version.
- [`owpp test`](test.md): run its unit tests.
- [`owpp bundle`](bundle.md): read the bundle it checked.
- [Authoring a plugin](../authoring.md): what makes a plugin pass.
