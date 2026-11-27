# owpp create

```
owpp create [id] [--spec FILE] [--dir FOLDER]
```

`owpp create` is a wizard that writes a new plugin in the plugins folder. It asks where the code of the plugin is:

- **Written here**: a filter, action, event or pipe with the options of that type. It can have a tool, skills, a page and libraries.
- **In a git repository**: the plugin takes a function, a tool or skills from it, pinned to a commit. For a branch or tag, the wizard looks up the commit SHA.

In both cases, the plugin can be an *installer* of a tool and skills, with no code of its own.

The wizard shows the files, and writes them only if you accept them. Then it runs [`owpp check --strict`](check.md) on the new plugin.

If you accept each default, the result is almost the same as the plugin that [`owpp init`](init.md) writes. Only two lines in `plugin.yaml` differ: `author` comes from `git config user.name`, and the wizard adds `required_open_webui_version`.

For every question and what it writes, see [creating a plugin](../creating.md).

With `--spec`, the command asks nothing. A YAML or JSON file gives the answers (`-` reads them from stdin). Use this in scripts and with [AI agents](../ai-agents.md). For the format, see [from a spec](../creating.md#from-a-spec).

## Options

| Option | Meaning |
| --- | --- |
| `id` | The plugin id. If you do not give it, the wizard asks. With `--spec`, this id replaces the id in the file. |
| `--spec FILE` | Ask nothing: create the plugin that a YAML or JSON file describes (`-` reads stdin). |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

## Examples

```sh
uvx owpp create                      # the wizard
uvx owpp create notes                # the wizard, for a plugin called notes
uvx owpp create --spec notes.yaml    # no questions
cat notes.yaml | uvx owpp create --spec -
```

## Related

- [Creating a plugin](../creating.md): every option of the wizard.
- [`owpp init`](init.md): the smallest plugin of a type, with no questions.
- [With an AI agent](../ai-agents.md): `--spec` from an agent.
