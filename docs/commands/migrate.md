# owpp migrate

```
owpp migrate [id ...] [--dry-run] [--dir FOLDER]
```

`owpp migrate` upgrades each plugin from an older [protocol version](../plugin-format.md#protocol) to the current one. Each version step changes only what it must, and keeps comments and layout. The command lists every file that it writes, so that you can review and commit the change. It does not change a plugin that has the current version.

Most steps change only `plugin.yaml`. The 0.3 -> 0.5 step also rewrites `function.py`, `tool.py` and `shared.py`, so that each file imports what it uses ([upgrading](../upgrading.md#04-05)). The command does not change code taken from git (`source:`).

```
$ owpp migrate --dry-run
new   hello: would migrate 0.3 -> 0.5 -> 0.7
        would write plugin.yaml
        would write function.py
          +from owpp.lib import PluginEvents, on
ok    notes: protocol 0.7
```

The command exits 1 if it leaves work for you:

- It cannot find where a name comes from. It lists the name under the plugin, with its file and line. Import that name yourself.
- It cannot tell if a `track:` from protocol 0.2 is a branch or a tag. It reports `FAIL` and does not change the plugin. Replace `track:` with `branch:` or `tag:`, and set `protocol: "0.3"`. Then run the command again.

For when to run the command, and for the other steps of an upgrade, see [upgrading owpp](../upgrading.md).

## Options

| Option | Meaning |
| --- | --- |
| `id ...` | The plugins to migrate. Default: all. |
| `--dry-run` | Show what changes, and write nothing. |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
uvx owpp@0.7.1 migrate --dry-run
uvx owpp@0.7.1 migrate
uvx owpp@0.7.1 migrate hello
```

## Related

- [Upgrading owpp](../upgrading.md): the whole upgrade, step by step.
- [Plugin format: `protocol:`](../plugin-format.md#protocol).
- [`owpp check`](check.md): tells you which manifests need this command.
