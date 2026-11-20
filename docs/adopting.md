# Adopting the protocol

## A new repository

```sh
mkdir my-plugins && cd my-plugins && git init
uvx owpp create hello                # the wizard (docs/creating.md), or: uvx owpp init hello --type event
uvx owpp check
OPEN_WEBUI_URL=https://chat.example.com OPEN_WEBUI_API_KEY=sk-... uvx owpp deploy --dry-run
```

Then add the [GitHub Action](tooling.md#github-action).

## Existing functions pasted into the UI

1. Make a folder per function: `plugins/<id>/function.py`, with the docstring header moved into `plugin.yaml` under `function:` (or keep a flat `plugins/<id>.py` with its header).
2. The id must equal the id the function already has in Open-WebUI, or the deploy will create a second copy. Ids cannot contain hyphens.
3. The first deploy **updates** a same-id function and marks it as managed. Its valves and active/global state are kept.
4. Replace copied helpers with libraries (`routes`, `jobs`, `chat_data`, `static`, `templates`) as you go; `owpp check` reports anything left undefined.
5. Run `uvx owpp migrate` to record `protocol: "0.2"` in each manifest (or add the line yourself). A manifest with no key is treated as 0.1, which `owpp check` warns about and `owpp check --strict` fails on; see [the protocol key](plugin-format.md#protocol).

## Third-party functions

Prefer a pinned `source:` (git URL plus a full commit SHA) over copying the file in: upgrades become a reviewed change of the SHA, which `owpp sync` makes (it lists the files that changed, with a compare link). Review the upstream diff before committing it; this code runs with admin rights.

## Keep your existing marker

If you used this protocol before it had its own repository (the deploy script inside another repo), your functions carry that repo's marker. Pass it, or every function will look hand-made and stop being pruned:

```sh
OWPP_MANAGED_BY='git:owner/repo:path' uvx owpp deploy
```

or `managed-by:` in the action. The description note changed to a generic wording, so the first deploy with this package updates each function once; that is expected.
