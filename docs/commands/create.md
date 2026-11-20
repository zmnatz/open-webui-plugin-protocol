# owpp create

```
owpp create [id] [--spec FILE] [--dir FOLDER]
```

A wizard that scaffolds a plugin in the plugins folder. It asks what the plugin is: written here (a filter, action, event or pipe with that type's options, a tool, skills, a page and libraries), an *installer* of a tool and skills with no code of its own, or taken from a git repository pinned to a commit (a branch or tag is resolved to its SHA). It shows the files and writes them only when you say yes, then runs [`owpp check --strict`](check.md) on the result. Pressing Enter all the way makes what [`owpp init`](init.md) makes.

Every question and what it writes: [creating a plugin](../creating.md).

With `--spec`, it asks nothing: the file says what the wizard would have asked, as YAML or JSON (`-` reads it from stdin). It is for scripts and [AI agents](../ai-agents.md); the format is in [creating a plugin](../creating.md#from-a-spec).

## Options

| Option | Meaning |
| --- | --- |
| `id` | The plugin id. Asked if left out; on the command line it wins over the spec's. |
| `--spec FILE` | Ask nothing: create the plugin a YAML or JSON file describes (`-` reads stdin). |
| `--dir FOLDER` | The plugins folder. Default `$OWPP_PLUGINS_DIR`, else `./plugins`. |

## Examples

```sh
uvx owpp create                      # the wizard
uvx owpp create notes                # the wizard, for a plugin called notes
uvx owpp create --spec notes.yaml    # no questions
cat notes.yaml | uvx owpp create --spec -
```

## Related

- [Creating a plugin](../creating.md): every option the wizard has.
- [`owpp init`](init.md): the smallest plugin of a type, with no questions.
- [With an AI agent](../ai-agents.md): `--spec` from an agent.
