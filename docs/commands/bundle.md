# owpp bundle

```
owpp bundle <id> [out.py] [--dir FOLDER]
```

`owpp bundle` prints the code that [`owpp deploy`](deploy.md) stores for one plugin. This bundle is the single file that Open-WebUI keeps. It holds the function with its libraries and, if the plugin has them, its tool, its skills and the runtime.

With `out.py`, the command writes the bundle to that file instead. Use the command to read the code before you deploy it, or to compare two versions of it. For the contents of a bundle and their order, see [bundling](../bundling.md).

If the id is not in the plugins folder, the command fails with `no plugin "<id>" in <folder>`.

## Options

| Option | Meaning |
| --- | --- |
| `<id>` | The plugin. |
| `out.py` | Write the bundle to this file instead of printing it. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
owpp bundle excalidraw | less
owpp bundle excalidraw build/excalidraw.py
```

## Related

- [`owpp check`](check.md): bundle and compile every plugin.
- [Bundling](../bundling.md): what the file contains.
