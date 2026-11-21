# owpp migrate

```
owpp migrate [id ...] [--dry-run] [--dir FOLDER]
```

Brings each `plugin.yaml` written for an older [protocol version](../plugin-format.md#protocol) up to the current one. It rewrites only what each version step changes, keeps comments and layout, and lists every `plugin.yaml` it writes, so the change is there to review and commit. A manifest already at the current version is left alone.

```
$ owpp migrate --dry-run
new   hello: would migrate 0.1 -> 0.2
ok    notes: protocol 0.2
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
uvx owpp@0.4.0 migrate --dry-run
uvx owpp@0.4.0 migrate
uvx owpp@0.4.0 migrate hello
```

## Related

- [Upgrading owpp](../upgrading.md): the whole upgrade, step by step.
- [Plugin format: `protocol:`](../plugin-format.md#protocol).
- [`owpp check`](check.md): warns about a manifest that needs migrating.
