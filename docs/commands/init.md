# owpp init

```
owpp init <id> [--type event|filter|action|pipe] [--dir FOLDER]
```

Scaffolds the smallest plugin of a type in `<plugins folder>/<id>/`: `plugin.yaml`, `function.py`, `tests/test_<id>.py` and a README with Test and Deploy sections (and a `CHANGELOG.md`). It is what [`owpp create`](create.md) writes when every answer is the default. For every type, the scaffold passes both [`owpp check`](check.md) and [`owpp test`](test.md).

## Options

| Option | Meaning |
| --- | --- |
| `<id>` | The plugin id, and the folder name. |
| `--type` | `event` (default), `filter`, `action` or `pipe`. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
owpp init hello
owpp init notes --type filter
```

## Related

- [`owpp create`](create.md): the same, with a tool, skills, a page or code from git.
- [Getting started](../getting-started.md): from a scaffold to a deployed plugin.
