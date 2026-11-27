# Adopting the protocol

## A new repository

```sh
mkdir my-plugins && cd my-plugins && git init
uvx owpp create hello                # the wizard (docs/creating.md), or: uvx owpp init hello --type event
uvx owpp check
OPEN_WEBUI_URL=https://chat.example.com OPEN_WEBUI_API_KEY=sk-... uvx owpp deploy --dry-run
```

The deploy reads the instance and the credentials from [environment variables](environment-variables.md#the-instance). Then add the [GitHub Action](tooling.md#github-action).

For an editor to resolve what a plugin imports, install owpp into the repository's environment as a development dependency, as for running its tests: `uv add --dev 'owpp[test]'`. That gives it `owpp.lib` (the [libraries](libraries.md)) and type stubs for the parts of `open_webui` the [mock](testing/mock.md#in-an-editor) has.

## Existing functions pasted into the UI

1. **Import each one from the instance**: `uvx owpp import --instance <id>` ([owpp import](commands/import.md)). It reads the function as Open-WebUI stores it, moves its docstring header into `plugin.yaml` under `function:` and writes the rest as `plugins/<id>/function.py`, with a README, a CHANGELOG and a first test. From a `.py` file instead: `uvx owpp import shout.py`. A function an owpp repository deployed comes back as the plugin it was made from, its tool, skills and `requires:` included ([what owpp put into it](commands/import.md#what-owpp-put-into-it-taken-back-out)).
2. The id stays the one the function has in Open-WebUI; with another, the deploy would create a second copy. (Ids cannot contain hyphens: `--id` sets one.)
3. **Test it as it is**: write its tests in `plugins/<id>/tests/` and run `uvx --from 'owpp[test]' owpp test <id>` ([writing a test](testing/writing.md)). An agent does this with the [`test-existing-plugin` skill](ai-agents.md#the-test-existing-plugin-skill).
4. The first deploy **updates** a same-id function and marks it as managed, with the code it had. Its valves and active/global state are kept.
5. Replace copied helpers with libraries (`routes`, `jobs`, `chat_data`, `static`, `templates`) as you go; `owpp check` reports anything left undefined.
6. A manifest from before `owpp import` may have no `protocol:` key: `uvx owpp migrate` records `protocol: "0.7"` (or add the line yourself). A manifest with no key is treated as 0.1, which `owpp check` warns about and `owpp check --strict` fails on; see [the protocol key](plugin-format.md#protocol).

## Third-party functions

`uvx owpp import <URL of its folder or file>` takes it from its git repository, pinned at a commit rather than copied: it finds the function, the tool and the skills in the folder and writes the `plugin.yaml` for them ([owpp import](commands/import.md)). Upgrades are then a reviewed change of the commit, which `owpp pull` makes (it lists the files that changed, with a compare link). Review the upstream diff before committing it; this code runs with admin rights.

Someone's owpp plugin (one of [the examples](../examples/plugins), say) is imported the same way, from the URL of its folder: it is taken [whole from git](plugin-format.md#a-whole-plugin-from-git), with its own `plugin.yaml` as the manifest.

## Keep your existing marker

If you used this protocol before it had its own repository (the deploy script inside another repo), your functions carry that repo's marker. Pass it, or every function will look hand-made and stop being pruned:

```sh
OWPP_MANAGED_BY='git:owner/repo:path' uvx owpp deploy
```

or `managed-by:` in the action ([`OWPP_MANAGED_BY`](environment-variables.md#owpp_managed_by)). The description note changed to a generic wording, so the first deploy with this package updates each function once; that is expected.
