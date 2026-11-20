# owpp list

```
owpp list [--dir FOLDER]
```

Lists the plugins in the plugins folder, one per line: the function id, its type, and `(global)` for a filter or action deployed as global.

```
$ owpp list
excalidraw              filter (global)
mcpo_sync               event
```

It reads every plugin the way [`owpp deploy`](deploy.md) would, git sources included, so a plugin that cannot be read fails here too.

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

- [`owpp check`](check.md): bundle and check them.
- [`owpp version`](version.md): their versions.
