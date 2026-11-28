# owpp check

```
owpp check [id ...] [--strict] [--since ref] [--dir FOLDER]
```

`owpp check` bundles each plugin exactly as [`owpp deploy`](deploy.md) does. Then it compiles the function and each tool that the function embeds. It lists each name that the code uses, but that is not defined or imported where Python looks for it. The cause can be a typo, or a library that the plugin does not `include`. A variable of a different function does not count.

With no ids, the command checks every plugin. It reads the files that a `source:` takes from git, so it checks the real upstream code. [`.owpp/`](../bundling.md#the-owpp-folder) keeps those files.

The [GitHub Action](../tooling.md#github-action) runs this check before it deploys the plugins folder. It skips the check with `check: "false"`, and when it deploys a build (`from:`).

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

## What each line means

The first word of a line gives its kind:

| Line | Meaning |
| --- | --- |
| `ok` | The bundle compiles, and every name in it is defined. |
| `FAIL` | Something is wrong with a bundle, or a change has no new version. |
| `warn` | A problem to correct. It makes the check fail only with `--strict`. |
| `note` | Information for you. It never makes the check fail. |
| `env` | An environment variable that the `jobs:` or `config.yaml` of a plugin reads, with its default. |

The check warns about these:

- A valve with no `description`. The admin UI shows each valve with its description.
- A tool method with no docstring, a parameter with no type hint, or a parameter with no `:param name:` line in the docstring. Open-WebUI builds the tool spec for the model from these. The check ignores injected parameters such as `__user__` and `__metadata__`.
- A name that the plugin defines and that a library in its bundle also defines. The bundle is one module, so the plugin's definition replaces the library's.
- In a plugin with a `shared.py`, a `from __future__` line that is not in all of `shared.py`, `function.py` and `tool.py`. In a bundle, these lines move to the top, so they apply to the other files too.
- A deprecated `{{file:NAME}}` ([bundling](../bundling.md#filename-deprecated)).
- A `CHANGELOG.md` with no entry for the current version of the function ([`CHANGELOG.md`](version.md#changelogmd)).
- A `plugin.yaml` with no `protocol:` key ([upgrading](../upgrading.md)).

The warnings about code come from the plugin's own files: `function.py`, `tool.py`, `shared.py`, or a loose `<id>.py`. They give the real file and line. A plugin with a `source:` gets no warnings about code, because upstream code is not yours to correct.

The check writes a `note` for these:

- A manifest with an older [protocol version](../plugin-format.md#protocol). The note names [`owpp migrate`](migrate.md).
- A place where the plugin serves people who are not signed in: a `public` mount, or `static: {access: public}`.
- A mount whose access the code computes, so the check cannot tell if it is public.

## Exit status

The command exits 1 in these cases:

- A bundle fails, or the command cannot bundle a plugin.
- `--since` finds a change without a new version.
- You give `--strict`, and there is a warning.
- An id is not in the plugins folder. The error is `no plugin <id> in <folder>`.

## Options

| Option | Meaning |
| --- | --- |
| `id ...` | The plugins to check. Default: all. |
| `--strict` | Fail on warnings too, for example in CI. |
| `--since ref` | Also fail when a plugin changed since this git ref (for example `origin/main`), but its version did not. See [below](#a-change-needs-a-new-version). |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## A change needs a new version

```sh
owpp check --since origin/main
FAIL  viz: changed since origin/main but its version is still 1.0.0 (run `owpp version viz patch`)
FAIL  tool viz: changed since origin/main but its version is still 1.0.0 (run `owpp version viz patch --tool`)
```

The check bundles every plugin as it was at that git ref (with `git archive`) and as it is now. It compares the code of the two bundles as the deploy compares code (see [what a deploy does](deploy.md#what-a-deploy-does)). It does not compare the meta. It fails for each change that has no new version:

- A **tool or skill that has a version** must get a new one when it changes.
- The **plugin** (the function's version) must get a new one in these cases:
    - Its own code changed.
    - A tool or skill was added or removed.
    - A tool or skill without a version changed.
    - The commit of its `source:` moved. [`owpp pull`](pull.md) gives the new version for you.

A plugin that did not exist at that ref needs nothing.

The upstream sets the version of code that a plugin takes verbatim from a `source:`. In a plugin with a `source:`, these parts are verbatim:

- The function or the tool, when its section has `file:`.
- A skill, when its [`skills:`](../plugin-format.md#skills) entry has `file:` or `dir:`.
- Every part of a [whole plugin from git](../plugin-format.md#a-whole-plugin-from-git).

The check treats the parts as follows:

- A change to a verbatim tool or skill counts as a change of the plugin.
- If the function is verbatim, the plugin needs no new version.
- All other tools and skills follow the rules above.

The check needs the `git` CLI. To use it in CI:

1. Check out the repository with `fetch-depth: 0`.
2. Pass the base branch, for example `since: origin/${{ github.base_ref }}` on a pull request.

To give a plugin its new version, use [`owpp version`](version.md).

## Examples

```sh
owpp check                          # every plugin
owpp check my_plugin --strict       # one, failing on warnings
owpp check --strict --since origin/main
```

## Related

- [`owpp version`](version.md): give a changed plugin a new version.
- [`owpp test`](test.md): run the unit tests of the plugins.
- [`owpp bundle`](bundle.md): read the bundle that the check compiled.
- [Authoring a plugin](../authoring.md): what makes a plugin pass.
