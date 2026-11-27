# Tooling and CI

`owpp` is the command-line tool. It checks, bundles, tests, versions and deploys the plugins in a repository. [Install](install.md) says how to run it (`uvx owpp <command>`, with a pinned version in scripts and CI). `owpp <command> --help` lists the flags of a command. Each command also has its own page:

| Command | What it does |
| --- | --- |
| [`owpp list`](commands/list.md) | Lists the plugins with their function type. |
| [`owpp check`](commands/check.md) | Bundles and compiles every plugin, reports undefined names, and warns about valves and tools. `--since` fails on a change without a new version. |
| [`owpp bundle`](commands/bundle.md) | Prints (or writes) the code that a deploy stores. |
| [`owpp build`](commands/build.md) | Bundles the plugins into a folder that `owpp deploy --from` deploys elsewhere. |
| [`owpp deploy`](commands/deploy.md) | Deploys the plugins to an Open-WebUI instance. Its page covers the settings, sign-in, the ownership marker and the report. |
| [`owpp test`](commands/test.md) | Runs each plugin's `tests/` against a mock Open-WebUI. |
| [`owpp pull`](commands/pull.md) | Moves plugins taken from git to the latest commit that they follow. |
| [`owpp version`](commands/version.md) | Shows the plugins' versions, or gives one a new version. |
| [`owpp migrate`](commands/migrate.md) | Brings plugins to the current protocol version. |
| [`owpp import`](commands/import.md) | Makes a plugin folder from code that exists: a git repository (pinned), a `.py` file, or a function on Open-WebUI. |
| [`owpp live`](commands/live.md) | Deploys the plugins to a throwaway Open-WebUI in Docker, with aimock as its models, and runs the repository's live tests. |
| [`owpp create`](commands/create.md) | A wizard: it asks what the plugin is, then writes it. |
| [`owpp init`](commands/init.md) | Writes the smallest plugin of a type. |

Every command takes `--dir <folder>`, the plugins folder. The default is [`$OWPP_PLUGINS_DIR`](environment-variables.md#owpp_plugins_dir), else `./plugins`. For the variables that the commands read, see [environment variables](environment-variables.md). `owpp --version` prints the version.

## GitHub Action

The action checks every plugin (`owpp check`), then deploys. A failure makes the job fail. The action sets up uv itself. It runs `owpp` from its own checkout, so the ref that you pin in `uses:` is the version that you deploy with.

Keep a `concurrency` group in the workflow, so that two deploys never run at the same time.

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
      - uses: zmnatz/open-webui-plugin-protocol@v0.7.2
        with:
          url: https://chat.example.com
          api-key: ${{ secrets.OPEN_WEBUI_API_KEY }}
          plugins-dir: plugins
          # managed-by: git:you/your-repo
          # dry-run: "true"
```

| Input | What it sets |
| --- | --- |
| `url` | Required. [`OPEN_WEBUI_URL`](environment-variables.md#open_webui_url). |
| `api-key`, `username`, `password`, `oidc-token`, `oauth-provider` | How the deploy [signs in](commands/deploy.md#signing-in): the [sign-in variables](environment-variables.md#signing-in). Store credentials as secrets. |
| `plugins-dir` | The plugins folder, relative to the repository root (default `plugins`): [`OWPP_PLUGINS_DIR`](environment-variables.md#owpp_plugins_dir). |
| `managed-by` | The [ownership marker](commands/deploy.md#the-ownership-marker) (default `open-webui-plugin-protocol`): [`OWPP_MANAGED_BY`](environment-variables.md#owpp_managed_by). |
| `only` | [`owpp deploy --only`](commands/deploy.md): plugin ids, separated by commas. |
| `dry-run`, `latest`, `force`, `no-prune` | [`owpp deploy`](commands/deploy.md)'s `--dry-run`, `--latest`, `--force` and `--no-prune`. Set `"true"` to turn one on. `latest` works only with `dry-run`. |
| `from` | A folder that [`owpp build`](commands/build.md) wrote. The action deploys it instead of the plugins folder ([deploying a build](commands/deploy.md#deploying-a-build)). It skips `owpp check`: run that where you make the build. |
| `check` | `"false"` skips `owpp check` before the deploy (default `"true"`). |
| `since` | A git ref for [`owpp check --since`](commands/check.md#a-change-needs-a-new-version). The checkout must have that ref (`actions/checkout` with `fetch-depth: 0`). |

More CI examples:

- [Build in one job and deploy in another](commands/build.md#examples).
- [Run a scheduled dry run at the latest commits](commands/deploy.md#the-report-what-changes-in-versions).
- [Open a pull request for each upgrade](commands/pull.md#a-pull-request-for-each-upgrade).

## Tests (this repository)

`uv run pytest` runs all the tests: those of owpp in `tests/`, and those of each example plugin in `examples/plugins/<id>/tests/`. The [test catalogue](reference/test-catalogue.md#the-librarys-own-tests) says what each file in `tests/` covers.

In these tests, stand-ins take the place of git sources, so they need no network. `owpp check` compiles the real code that it fetches.

### Testing your own plugins

See [testing plugins](testing.md): how to write tests, the mock, live checks, and [a CI workflow](testing/ci.md).
