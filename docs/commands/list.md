# owpp list

```
owpp list [--dir FOLDER]
```

`owpp list` shows each function in the plugins folder, one on each line. A line gives the function id and its type. It adds `(global)` for a filter or action that declares `global: true`.

```
$ owpp list
excalidraw              filter (global)
mcpo_sync               event
```

The command bundles every plugin as [`owpp deploy`](deploy.md) does, and reads the files that a `source:` takes from git. Thus a plugin that cannot be bundled also fails here.

## Options

| Option | Meaning |
| --- | --- |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
uvx owpp list
uvx owpp list --dir examples/plugins
```

## Related

- [`owpp check`](check.md): bundle and check the plugins.
- [`owpp version`](version.md): show their versions.
