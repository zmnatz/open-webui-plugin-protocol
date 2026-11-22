# owpp migrate

```
owpp migrate [id ...] [--dry-run] [--dir FOLDER]
```

Brings each plugin written for an older [protocol version](../plugin-format.md#protocol) up to the current one. It rewrites only what each version step changes, keeps comments and layout, and lists every file it writes, so the change is there to review and commit. A plugin already at the current version is left alone.

Most steps change only `plugin.yaml`. 0.3 -> 0.5 also rewrites the plugin's `function.py`, `tool.py` and `shared.py`, so that each imports what it uses ([upgrading](../upgrading.md#04-05)). A name it cannot place is listed under the plugin, with its file and line, and the command exits 1: import it yourself. Code taken from git (`source:`) is not touched.

```
$ owpp migrate --dry-run
new   hello: would migrate 0.3 -> 0.5
        would write plugin.yaml
        would write function.py
          +from owpp.lib import PluginEvents, on
ok    notes: protocol 0.5
```

[`owpp check`](check.md) warns about a manifest with no `protocol:` key and notes an older one, pointing at this command. When to run it, and the rest of an upgrade: [upgrading owpp](../upgrading.md).

## Options

| Option | Meaning |
| --- | --- |
| `id ...` | The plugins to migrate. Default: all. |
| `--dry-run` | Say what would change; write nothing. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
uvx owpp@0.5.0 migrate --dry-run
uvx owpp@0.5.0 migrate
uvx owpp@0.5.0 migrate hello
```

## Related

- [Upgrading owpp](../upgrading.md): the whole upgrade, step by step.
- [Plugin format: `protocol:`](../plugin-format.md#protocol).
- [`owpp check`](check.md): warns about a manifest that needs migrating.
