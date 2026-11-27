# owpp test

```
owpp test [id ...] [--upstream] [--dir FOLDER] [-- pytest args]
owpp test --editor
```

`owpp test` runs the `tests/` folder of each plugin with pytest, against the real Open-WebUI in the test process: the [test harness](../testing/harness.md). With no ids, it tests every plugin that has such a folder. Arguments after `--` go to pytest.

The test fixtures bundle a plugin exactly as [`owpp deploy`](deploy.md) does. Then they deploy it through Open-WebUI's API. For the tests and the fixtures, see [testing plugins](../testing.md).

The command needs the `test` extra: pytest, and the packages of Open-WebUI's slim image. It also needs Open-WebUI's Python (3.12 for Open-WebUI v0.13.5). Run it as `uvx --python 3.12 --from 'owpp[test]' owpp test`.

- On a different Python, the command stops and gives that command.
- If a package is missing, the command stops and names it, for example ``error: owpp test needs pytest: run it as `uvx --python 3.12 --from 'owpp[test]' owpp test`, or `pip install 'owpp[test]'` ``.
- The first run downloads Open-WebUI's code to [`OWPP_CACHE_DIR`](../environment-variables.md#owpp_cache_dir).

## Upstream tests

A plugin [taken whole from git](../plugin-format.md#a-whole-plugin-from-git) has the upstream's tests. By default, `owpp test` does not run them. With `--upstream`, it also runs them from the pinned commit, against your bundle of the plugin, with your overrides.

**Caution:** Read the upstream tests before you use `--upstream`. They run code from a different repository on your machine. The command first removes the `OPEN_WEBUI_*` [variables](../environment-variables.md#signing-in) from their environment.

## Options

| Option | Meaning |
| --- | --- |
| `id ...` | The plugins to test. Default: every plugin with a `tests/` folder. |
| `--upstream` | Also run the tests of plugins taken whole from git, from the pinned commit. |
| `-- pytest args` | Everything after `--` goes to pytest. |
| `--editor` | Print the folder of the Open-WebUI code that the tests run, and stop. Add it to the search path of your editor ([in an editor](../testing/harness.md#in-an-editor)). It downloads the code if it is not in the cache. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
uvx --python 3.12 --from 'owpp[test]' owpp test               # every plugin with a tests/ folder
uvx --python 3.12 --from 'owpp[test]' owpp test excalidraw    # just these
owpp test excalidraw -- -k token -x                           # after --: arguments for pytest
owpp test --upstream                                          # the upstream's tests too
owpp test --editor                                            # where an editor finds open_webui
```

## Related

- [Testing plugins](../testing.md): how to write tests, the fixtures, the [test harness](../testing/harness.md).
- [`owpp check`](check.md): bundle and compile, and run nothing.
- [`owpp init`](init.md) and [`owpp create`](create.md): both write a first test that passes.
