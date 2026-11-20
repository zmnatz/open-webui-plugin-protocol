# owpp bundle

```
owpp bundle <id> [out.py] [--dir FOLDER]
```

Prints the code that [`owpp deploy`](deploy.md) would store for one plugin: the single file Open-WebUI keeps, with its libraries, runtime and embedded tools and skills. With `out.py`, it writes the file instead. Use it to read or diff what is deployed; [bundling](../bundling.md) says what goes in, in which order.

An id that is not in the plugins folder fails with `no plugin "<id>" in <folder>`.

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

- [`owpp check`](check.md): bundles and compiles every plugin.
- [Bundling](../bundling.md): what ends up in the file.
