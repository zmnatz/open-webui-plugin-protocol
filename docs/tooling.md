# Tooling and CI

`owpp` is the command-line tool: it checks, bundles, tests, versions and deploys the plugins in a repository. [Install](install.md) says how to run it (`uvx owpp <command>`, pinned in scripts and CI). `owpp <command> --help` lists a command's flags; each command has its own page:

| Command | What it does |
| --- | --- |
| [`owpp list`](commands/list.md) | Plugins with their function type. |
| [`owpp check`](commands/check.md) | Bundle and compile every plugin, report undefined names, warn about valves and tools; `--since` fails on a change without a new version. |
| [`owpp bundle`](commands/bundle.md) | Print (or write) the code that would be deployed. |
| [`owpp build`](commands/build.md) | Bundle the plugins into a folder that `owpp deploy --from` deploys elsewhere. |
| [`owpp deploy`](commands/deploy.md) | Deploy the plugins to an Open-WebUI instance: settings, signing in, the ownership marker, the report. |
| [`owpp test`](commands/test.md) | Run each plugin's `tests/` against a mock Open-WebUI. |
| [`owpp pull`](commands/pull.md) | Move plugins taken from git to the latest commit they follow. |
| [`owpp version`](commands/version.md) | Show the plugins' versions, or give one a new version. |
| [`owpp migrate`](commands/migrate.md) | Bring `plugin.yaml` to the current protocol version. |
| [`owpp create`](commands/create.md) | A wizard: asks what the plugin is, then writes it. |
| [`owpp init`](commands/init.md) | Scaffold the smallest plugin of a type. |

Every command takes `--dir <folder>`: the plugins folder, default [`$OWPP_PLUGINS_DIR`](environment-variables.md#owpp_plugins_dir), else `./plugins`. The variables each command reads: [environment variables](environment-variables.md). `owpp --version` prints the version.

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
      - uses: zmnatz/open-webui-plugin-protocol@v0.3.0
        with:
          url: https://chat.example.com
          api-key: ${{ secrets.OPEN_WEBUI_API_KEY }}
          plugins-dir: plugins
          # managed-by: git:you/your-repo
          # dry-run: "true"
```

The action runs `owpp` from its own checkout, so the version you deploy with is the ref you pin in `uses:`. It sets up uv itself. It checks every plugin (`owpp check`), then deploys. A failure turns the job red. Keep a `concurrency` group so two deploys never overlap.

| Input | What it sets |
| --- | --- |
| `url` | Required. [`OPEN_WEBUI_URL`](environment-variables.md#open_webui_url). |
| `api-key`, `username`, `password`, `oidc-token`, `oauth-provider` | How the deploy [signs in](commands/deploy.md#signing-in): the [sign-in variables](environment-variables.md#signing-in) (store them as secrets). |
| `plugins-dir` | The plugins folder, relative to the repository root (default `plugins`): [`OWPP_PLUGINS_DIR`](environment-variables.md#owpp_plugins_dir). |
| `managed-by` | The [ownership marker](commands/deploy.md#the-ownership-marker) (default `open-webui-plugin-protocol`): [`OWPP_MANAGED_BY`](environment-variables.md#owpp_managed_by). |
| `only`, `dry-run`, `latest`, `force`, `no-prune` | [`owpp deploy`](commands/deploy.md)'s `--only`, `--dry-run`, `--latest`, `--force` and `--no-prune` (`"true"` to turn one on). |
| `from` | A folder [`owpp build`](commands/build.md) wrote, to deploy instead of the plugins folder ([deploying a build](commands/deploy.md#deploying-a-build)); it skips `owpp check`, which runs where the build is made. |
| `check` | `"false"` skips `owpp check` before deploying (default `"true"`). |
| `since` | [`owpp check --since`](commands/check.md#a-change-needs-a-new-version) this git ref. Needs that ref fetched (`actions/checkout` with `fetch-depth: 0`). |

More CI: [building in one job and deploying in another](commands/build.md#examples), a scheduled [dry run at the latest commits](commands/deploy.md#the-report-what-changes-in-versions), and a [pull request for each upgrade](commands/pull.md#a-pull-request-for-each-upgrade).

## Tests (this repository)

`uv run pytest` runs everything:

| What | Where |
| --- | --- |
| Bundler, manifest rules, function types, libraries included | `tests/test_bundle.py` |
| Git sources (pinned commits, fetching, refusing unsafe URLs) | `tests/test_sources.py` |
| Deploy against a stand-in Open-WebUI API: create, update, global, prune, valves, `--only` | `tests/test_deploy.py` |
| CLI commands, `check`, `init` scaffolds | `tests/test_cli.py` |
| Every command has a page in `docs/commands/` that documents each of its flags | `tests/test_command_docs.py` |
| Every environment variable owpp reads has an entry in `docs/environment-variables.md` | `tests/test_env_docs.py` |
| `owpp pull`: moving a pinned commit, the files it lists, refusing what it cannot check | `tests/test_pull.py` |
| `owpp create`: every combination it writes bundles, passes `check --strict` and its own tests; the wizard, driven by scripted answers | `tests/test_create.py` |
| Every example plugin bundles, compiles, has unit tests and documents Test and Deploy | `tests/test_bundle.py`, "TestExamples" |
| Each example plugin's behaviour, against the mock Open-WebUI | `examples/plugins/<id>/tests/` |
| Runtime install/update/remove, valves, markers | `tests/plugin_runtime_test.py` |
| Libraries (core, routes, jobs, chat_data, public) against stubbed Open-WebUI modules | `tests/plugin_libs_test.py` |

Git sources are faked in the tests (no network); `owpp check` compiles the real fetched code.

### Testing your own plugins

- Run [`owpp check`](commands/check.md) in CI (the action does).
- Put unit tests in each plugin's `tests/` folder and run them with [`owpp test`](commands/test.md). They run against a mock Open-WebUI (see [testing](testing.md)): `owui.load(...)`, `owui.startup()`, `owui.client(user).get(...)`, `owui.tool(id).call(...)`. In CI: `uvx --from 'owpp[test]' owpp test`.
- Anything that needs Open-WebUI imports it inside the function that uses it, so the module loads under the mock (or any stub).
- Write the live checks in each plugin's README, under `## Test`. The mock is not Open-WebUI.
