# Adopting the protocol

## A new repository

1. Make the repository and a first plugin with the [wizard](creating.md), or with `owpp init`.
2. Run `uvx owpp check`.
3. Set the instance and the credentials in [environment variables](environment-variables.md#the-instance), then do a dry run of the deploy.
4. Add the [GitHub Action](tooling.md#github-action).

```sh
mkdir my-plugins && cd my-plugins && git init
uvx owpp create hello                # the wizard (docs/creating.md), or: uvx owpp init hello --type event
uvx owpp check
OPEN_WEBUI_URL=https://chat.example.com OPEN_WEBUI_API_KEY=sk-... uvx owpp deploy --dry-run
```

To let an editor find what a plugin imports, install owpp as a development dependency of the repository: `uv add --dev 'owpp[test]'`. The plugin's tests need it too. It gives the editor `owpp.lib` (the [libraries](libraries.md)). It also gives type stubs for the parts of `open_webui` that the [mock](testing/mock.md#in-an-editor) has.

## Existing functions pasted into the UI

1. **Import each function from the instance:** run `uvx owpp import --instance <id>` ([owpp import](commands/import.md)). To import from a `.py` file, run `uvx owpp import shout.py`.
2. **Keep the id that the function has in Open-WebUI.** With a different id, the deploy creates a second copy. If the id has hyphens, set a new one with `--id`, because ids cannot contain hyphens.
3. **Test the function as it is:** write its tests in `plugins/<id>/tests/` ([writing a test](testing/writing.md)). An agent can do this with the [`test-existing-plugin` skill](ai-agents.md#the-test-existing-plugin-skill).
4. Run `uvx --from 'owpp[test]' owpp test <id>`.
5. **Deploy.** The first deploy **updates** the function with the same id and marks it as managed. The code stays the same, and the deploy keeps its valves and its active and global state.
6. **Replace copied helpers with libraries** (`routes`, `jobs`, `chat_data`, `static`, `templates`), one at a time. `owpp check` reports all names that are still undefined.
7. **Add the `protocol:` key** if the manifest has none: run `uvx owpp migrate`, or add `protocol: "0.7"` yourself. A manifest from `owpp import` already has the key.

`owpp import` reads the function as Open-WebUI stores it. It moves the docstring header into `plugin.yaml` under `function:`, and writes the rest as `plugins/<id>/function.py`. It also writes a README, a CHANGELOG and a first test. A function that an owpp repository deployed comes back as the plugin it was made from, with its tool, skills and `requires:` ([what owpp put into it](commands/import.md#what-owpp-put-into-it-taken-back-out)).

owpp reads a manifest with no `protocol:` key as 0.1. `owpp check` gives a warning for it, and `owpp check --strict` fails ([the protocol key](plugin-format.md#protocol)).

## Third-party functions

Caution: review the upstream diff before you commit an upgrade. This code runs with admin rights.

1. Run `uvx owpp import <URL of its folder or file>` ([owpp import](commands/import.md)). It finds the function, the tool and the skills in the folder, pins them at a commit and writes the `plugin.yaml`.
2. To upgrade, run `owpp pull`. It moves the commit, and lists the files that changed with a compare link.
3. Review the change and commit it.

You import an owpp plugin from someone else in the same way, from the URL of its folder. [The examples](../examples/plugins) are plugins of this type. owpp takes the [whole plugin from git](plugin-format.md#a-whole-plugin-from-git), with its own `plugin.yaml` as the manifest.

## Keep your existing marker

Before this protocol had its own repository, its deploy script was inside other repositories. If you deployed with that script, your functions have the marker of that repository.

Caution: give the deploy that old marker. If you do not, all your functions look hand-made, and the deploy does not prune them.

1. Set the marker with `OWPP_MANAGED_BY`, or with `managed-by:` in the action ([`OWPP_MANAGED_BY`](environment-variables.md#owpp_managed_by)).
2. Deploy.

```sh
OWPP_MANAGED_BY='git:owner/repo:path' uvx owpp deploy
```

The first deploy with this package updates each function one time, because the note in the description now has a generic text. This is the expected result.
