# owpp init

```
owpp init <id> [--type event|filter|action|pipe] [--dir FOLDER]
```

`owpp init` writes the smallest plugin of a type in `<plugins folder>/<id>/`. The folder gets these files:

- `plugin.yaml`
- `function.py`
- `tests/test_<id>.py`
- `README.md`, with Test and Deploy sections
- `CHANGELOG.md`

The command refuses a folder that already exists. For every type, the new plugin passes both [`owpp check`](check.md) and [`owpp test`](test.md).

[`owpp create`](create.md) writes almost the same plugin if you accept each default. The [differences](create.md) are two lines in `plugin.yaml`.

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

- [`owpp create`](create.md): also a tool, skills, a page or code from git.
- [Getting started](../getting-started.md): from a new plugin to a deployed one.
