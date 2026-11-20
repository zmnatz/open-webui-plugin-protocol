# owpp test

```
owpp test [id ...] [--upstream] [--dir FOLDER] [-- pytest args]
```

Runs each plugin's `tests/` folder with pytest, against a mock Open-WebUI. With no ids it runs every plugin that has one. Arguments after `--` go to pytest. Each plugin is bundled exactly as [`owpp deploy`](deploy.md) would bundle it, then loaded the way Open-WebUI loads a function. How to write the tests, the fixtures and what the mock does: [testing plugins](../testing.md).

It needs the `test` extra (pytest, and the packages Open-WebUI ships that plugins import): `uvx --from 'owpp[test]' owpp test`. Without it, it stops with ``error: owpp test needs pytest: run it as `uvx --from 'owpp[test]' owpp test`, or `pip install 'owpp[test]'` ``.

A plugin [taken whole from git](../plugin-format.md#a-whole-plugin-from-git) has the upstream's tests, which are not run by default. With `--upstream` it also runs them, from the pinned commit, against the plugin as built with your overrides. That runs the other repository's code, so it is opt-in and the `OPEN_WEBUI_*` [variables](../environment-variables.md#signing-in) are removed from the environment first.

## Options

| Option | Meaning |
| --- | --- |
| `id ...` | The plugins to test. Default: every plugin with a `tests/` folder. |
| `--upstream` | Also run the tests of plugins taken whole from git, from the pinned commit. |
| `-- pytest args` | Everything after `--` goes to pytest. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
uvx --from 'owpp[test]' owpp test               # every plugin with a tests/ folder
uvx --from 'owpp[test]' owpp test excalidraw    # just these
owpp test excalidraw -- -k token -x             # after --: arguments for pytest
owpp test --upstream                            # the upstream's tests too
```

## Related

- [Testing plugins](../testing.md): writing tests, the fixtures, the mock.
- [`owpp check`](check.md): bundle and compile, without running anything.
- [`owpp init`](init.md) and [`owpp create`](create.md): both write a first test that passes.
