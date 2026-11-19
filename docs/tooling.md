# Tooling: test and deploy

`owpp` is a Python package (3.10 or newer) with one dependency, PyYAML. The easiest way to run it is [uv](https://docs.astral.sh/uv/), which fetches a Python for you. Remote sources need the `git` CLI.

## Install

Nothing to install; run it from the repository that holds your plugins:

```sh
uvx owpp list
```

Pin the version (`uvx owpp@0.2.0 list`, or `uv tool install owpp==0.2.0`): the runtime and libraries are copied into what you deploy, so an upgrade changes your deployed code. To run an unreleased commit: `uvx --from git+https://github.com/zmnatz/open-webui-plugin-protocol@<sha> owpp list`. `pipx install owpp` and `pip install owpp` work too, and `python -m owpp` is the same command.

## The CLI: `owpp`

```
owpp list                           plugins with their function type
owpp check [id ...] [--strict]      bundle, compile, report undefined names; warn about valves and tools
owpp bundle <id> [out.py]           print (or write) the code that would be deployed
owpp deploy [--only id,id] [--dry-run] [--force-prune] [--managed-by marker]
owpp test [id ...] [-- pytest args]
owpp create [id]
owpp init <id> [--type event|filter|action|pipe]
```

Every command takes `--dir <folder>`: the plugins folder, default `$OWPP_PLUGINS_DIR`, else `./plugins`.

- **`check`** bundles each plugin exactly as `deploy` would, then for the function and each tool it embeds: compiles it and lists names that are used but never defined or imported (a typo, or a library the plugin forgot to `include`). With no ids it checks every plugin. It fetches remote sources, so it checks the real upstream code. It also prints the environment variables a plugin reads from its `jobs:` and `config.yaml` (`env   NAME (default 60)`), and **warns** (`warn  p/tool.py:12: ...`) about things the people using the plugin see:

  - a valve with no `description` (the admin UI lists each valve with it),
  - a tool method with no docstring, a parameter with no type hint, or a parameter the docstring does not describe with `:param name:` (Open-WebUI builds the spec the model reads from those). Injected parameters such as `__user__` and `__metadata__` are ignored.

  Warnings read the plugin's own source (`function.py`, `tool.py`, `shared.py`, or a loose `<id>.py`) with real file and line numbers, and skip a plugin that takes its code from a pinned `source:`, which is not yours to lint. They do not change the exit status; **`--strict` makes them fail**, for CI.
- **`bundle`** writes the deployed code, to read or diff.
- **`test`** runs each plugin's `tests/` folder with pytest, against a mock Open-WebUI. With no ids it runs every plugin that has one. Arguments after `--` go to pytest. It needs the `test` extra: `uvx --from 'owpp[test]' owpp test`. See [testing](testing.md).
- **`create`** is a wizard: it asks, one stage at a time, what the plugin is (its header, function type and that type's options, valves and user valves, a tool, skills, a page, libraries), shows the files and writes them only when you say yes, then runs `check --strict` on the result. Every question has a default, so pressing Enter all the way makes what `init` makes. See [authoring](authoring.md#start-with-owpp-create).
- **`init`** scaffolds `plugin.yaml`, `function.py`, `tests/test_<id>.py` and a README with Test and Deploy sections. For every type, the scaffold passes both `check` and `test`.
- **`deploy`** deploys to a running Open-WebUI. With `--only` it deploys just those ids and **never prunes**, so deploying one plugin cannot delete another.

## Deploy settings

| Setting | Meaning |
| --- | --- |
| `OPEN_WEBUI_URL` | Required. Base URL of the Open-WebUI instance. |
| `OPEN_WEBUI_API_KEY` | Required. An admin API key (Settings > Account > API keys; the admin setting "Enable API Keys" must be on). Use a dedicated admin user. |
| `--dir`, `OWPP_PLUGINS_DIR` | The plugins folder (`FUNCTIONS_DIR` is accepted too). |
| `--managed-by`, `OWPP_MANAGED_BY` | The ownership marker, default `open-webui-plugin-protocol`. See below. |
| `--dry-run` | List what would change; write nothing. |
| `--only a,b` | Deploy just these ids; no pruning. |
| `--force-prune` | Allow deleting more than half of the managed functions at once. |

### The ownership marker

Every function the deploy writes gets `meta.managed_by = <marker>` and a note in its description. The marker is the **only** thing pruning acts on: a function with this marker whose plugin folder is gone is deleted, and a function without it (made by hand in the UI, or by another deployment with a different marker) is never touched.

- Use one marker per source of truth. Two repositories deploying to one instance need different markers, or each will prune the other's functions.
- **Never change the marker of a deployment that already has functions.** They would look hand-made: not updated cleanly, and never pruned. See [adopting](adopting.md#keep-your-existing-marker).

### What a deploy does

1. Waits for `GET /health` (the instance may be restarting).
2. Lists functions (`GET /api/v1/functions/list`), which is also the credential check: a bad key fails here, before anything is written.
3. Fetches git sources and bundles every plugin.
4. Creates, updates or leaves each function alone (see [bundling](bundling.md#what-the-deploy-script-does-with-a-bundle)), then applies manifest valves and activates and globalises as declared.
5. Prunes: managed functions whose folder is gone. Deleting more than half of them in one run is refused without `--force-prune`, so a renamed folder cannot wipe them all.

The report names each function with its type, for example ``- event function `mcpo_sync` (mcpo_sync/): unchanged``. In GitHub Actions it is also written to the job summary.

The deploy only ever creates, updates and prunes **functions**. Tools and skills are installed by the runtime inside Open-WebUI, driven by the function.

## GitHub Action

```yaml
# .github/workflows/deploy-plugins.yml in your repository
on:
  push:
    branches: [main]
    paths: ["plugins/**"]
  workflow_dispatch:
jobs:
  deploy:
    runs-on: ubuntu-latest
    concurrency: deploy-plugins
    steps:
      - uses: actions/checkout@v5
      - uses: zmnatz/open-webui-plugin-protocol@v0.2.0
        with:
          url: https://chat.example.com
          api-key: ${{ secrets.OPEN_WEBUI_API_KEY }}
          plugins-dir: plugins
          # managed-by: git:you/your-repo
          # dry-run: "true"
```

The action runs `owpp` from its own checkout, so the version you deploy with is the ref you pin in `uses:`. It sets up uv itself. It checks every plugin (`owpp check`), then deploys. A failure turns the job red. Keep a `concurrency` group so two deploys never overlap.

## Tests (this repository)

`uv run pytest` runs everything:

| What | Where |
| --- | --- |
| Bundler, manifest rules, function types, libraries included | `tests/test_bundle.py` |
| Git sources (pinned commits, fetching, refusing unsafe URLs) | `tests/test_sources.py` |
| Deploy against a stand-in Open-WebUI API: create, update, global, prune, valves, `--only` | `tests/test_deploy.py` |
| CLI commands, `check`, `init` scaffolds | `tests/test_cli.py` |
| `owpp create`: every combination it writes bundles, passes `check --strict` and its own tests; the wizard, driven by scripted answers | `tests/test_create.py` |
| Every example plugin bundles, compiles, has unit tests and documents Test and Deploy | `tests/test_bundle.py`, "TestExamples" |
| Each example plugin's behaviour, against the mock Open-WebUI | `examples/plugins/<id>/tests/` |
| Runtime install/update/remove, valves, markers | `tests/plugin_runtime_test.py` |
| Libraries (core, routes, jobs, chat_data, public) against stubbed Open-WebUI modules | `tests/plugin_libs_test.py` |

Git sources are faked in the tests (no network); `owpp check` compiles the real fetched code.

### Testing your own plugins

- Run `owpp check` in CI (the action does).
- Put unit tests in each plugin's `tests/` folder and run them with `owpp test`. They run against a mock Open-WebUI (see [testing](testing.md)): `owui.load(...)`, `owui.startup()`, `owui.client(user).get(...)`, `owui.tool(id).call(...)`. In CI: `uvx --from 'owpp[test]' owpp test`.
- Anything that needs Open-WebUI imports it inside the function that uses it, so the module loads under the mock (or any stub).
- Write the live checks in each plugin's README, under `## Test`. The mock is not Open-WebUI.
