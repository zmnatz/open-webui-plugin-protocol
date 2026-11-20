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
owpp check [id ...] [--strict] [--since ref]   bundle, compile, report undefined names; warn about valves and tools
owpp bundle <id> [out.py]           print (or write) the code that would be deployed
owpp deploy [--only id,id] [--dry-run [--sync]] [--force] [--force-prune] [--managed-by marker]
owpp test [id ...] [-- pytest args]
owpp sync [id ...] [--dry-run] [--bump patch|minor|major|none]
owpp version [id] [patch|minor|major|X.Y.Z] [--tool | --skill name] [-m text]
owpp migrate [id ...] [--dry-run]      bring plugin.yaml to the current protocol version
owpp create [id]
owpp init <id> [--type event|filter|action|pipe]
```

Every command takes `--dir <folder>`: the plugins folder, default `$OWPP_PLUGINS_DIR`, else `./plugins`.

- **`check`** bundles each plugin exactly as `deploy` would, then for the function and each tool it embeds: compiles it and lists names that are used but never defined or imported (a typo, or a library the plugin forgot to `include`). With no ids it checks every plugin. It fetches remote sources, so it checks the real upstream code. It also prints the environment variables a plugin reads from its `jobs:` and `config.yaml` (`env   NAME (default 60)`), and **warns** (`warn  p/tool.py:12: ...`) about things the people using the plugin see:

  - a valve with no `description` (the admin UI lists each valve with it),
  - a tool method with no docstring, a parameter with no type hint, or a parameter the docstring does not describe with `:param name:` (Open-WebUI builds the spec the model reads from those). Injected parameters such as `__user__` and `__metadata__` are ignored.

  Warnings read the plugin's own source (`function.py`, `tool.py`, `shared.py`, or a loose `<id>.py`) with real file and line numbers, and skip a plugin that takes its code from a pinned `source:`, which is not yours to lint. They do not change the exit status; **`--strict` makes them fail**, for CI.
- **`migrate`** brings each `plugin.yaml` written for an older [protocol version](plugin-format.md#protocol) up to the current one. It rewrites only what the version step changes, keeps comments and layout, and points at each file it writes so the change is there to review and commit. With `--dry-run` it says what would change and writes nothing. With ids, it migrates just those plugins; a manifest already at the current version is left alone. `owpp check` warns about a missing `protocol:` key and notes an older one, pointing at this command.
- **`bundle`** writes the deployed code, to read or diff.
- **`test`** runs each plugin's `tests/` folder with pytest, against a mock Open-WebUI. With no ids it runs every plugin that has one. Arguments after `--` go to pytest. It needs the `test` extra: `uvx --from 'owpp[test]' owpp test`. See [testing](testing.md).
- **`version`** shows the plugins' versions or gives one a new version, and **`check --since <ref>`** fails on a change without one: see [versions](#versions).
- **`sync`** moves the pinned commit of each plugin taken from git to the latest one: see [below](#owpp-sync-moving-a-pinned-commit).
- **`create`** is a wizard that scaffolds a plugin: written here (a filter, action, event or pipe with that type's options, a tool, skills, a page and libraries, or an *installer* of a tool and skills with no code of its own), or taken from a git repository pinned to a commit (a branch or tag is resolved to its SHA). It shows the files and writes them only when you say yes, then runs `check --strict` on the result. Pressing Enter all the way makes what `init` makes. See [creating a plugin](creating.md).
- **`init`** scaffolds `plugin.yaml`, `function.py`, `tests/test_<id>.py` and a README with Test and Deploy sections. For every type, the scaffold passes both `check` and `test`.
- **`deploy`** deploys to a running Open-WebUI. With `--only` it deploys just those ids and **never prunes**, so deploying one plugin cannot delete another.

## Deploy settings

| Setting | Meaning |
| --- | --- |
| `OPEN_WEBUI_URL` | Required. Base URL of the Open-WebUI instance. |
| `OPEN_WEBUI_API_KEY` | An admin API key (Settings > Account > API keys; the admin setting "Enable API Keys" must be on). Optional: see [signing in](#signing-in). |
| `OPEN_WEBUI_USERNAME`, `OPEN_WEBUI_PASSWORD` | Without an API key: an admin's email and password, or LDAP user name and password. |
| `--ca-cert`, `OPEN_WEBUI_CA_CERT` | A PEM of CA certificates to trust besides the system's (a private CA, or a self-signed Open-WebUI): a path, or the PEM text. |
| `--client-cert`, `--client-key`, `OPEN_WEBUI_CLIENT_CERT`, `OPEN_WEBUI_CLIENT_KEY` | A client certificate (and its key, when not in the same PEM) for a server or proxy that requires mutual TLS: paths, or the PEM text. |
| `OPEN_WEBUI_OIDC_TOKEN`, `OPEN_WEBUI_OAUTH_PROVIDER` | Without either: an OIDC access token, exchanged for a session, and the Open-WebUI OAuth provider it is from (default `oidc`). |
| `--dir`, `OWPP_PLUGINS_DIR` | The plugins folder (`FUNCTIONS_DIR` is accepted too). |
| `--managed-by`, `OWPP_MANAGED_BY` | The ownership marker, default `open-webui-plugin-protocol`. See below. |
| `--dry-run` | List what would change, with versions; write nothing. |
| `--sync` | With `--dry-run`: report against the latest commit each git-sourced plugin tracks, as [`owpp sync`](#owpp-sync-moving-a-pinned-commit) would move it, without changing `plugin.yaml`. Refused without `--dry-run`. |
| `--only a,b` | Deploy just these ids; no pruning. |
| `--force` | Deploy even where the instance runs a newer version than the repository: see [versions](#versions). |
| `--force-prune` | Allow deleting more than half of the managed functions at once. |

### Signing in

The deploy needs an **admin** of the instance. It uses the first of these that is set:

| Set | What it does | The instance needs |
| --- | --- | --- |
| `OPEN_WEBUI_API_KEY` | Uses the key as it is. | API keys on (Admin Panel > Settings > General > Enable API Keys), and a key from Settings > Account > API keys. |
| `OPEN_WEBUI_USERNAME` and `OPEN_WEBUI_PASSWORD` | Signs in with them as an Open-WebUI account (the user name is the email, `POST /api/v1/auths/signin`), and if that fails, as an LDAP user (`POST /api/v1/auths/ldap`). | Password sign-in on; LDAP configured for an LDAP user. |
| `OPEN_WEBUI_OIDC_TOKEN` | Exchanges the token for a session (`POST /api/v1/auths/oauth/<provider>/token/exchange`, the provider from `OPEN_WEBUI_OAUTH_PROVIDER`, default `oidc`). | `ENABLE_OAUTH_TOKEN_EXCHANGE=true`, and that OAuth provider configured. |
| nothing | Signs in with no credentials, as the browser would. | Sign-in switched off (`WEBUI_AUTH=False`), or a proxy in front of it that adds the trusted email header (`WEBUI_AUTH_TRUSTED_EMAIL_HEADER`). |

The session it gets is used for that run only, and the account must be an admin: otherwise the deploy stops before writing anything, saying who it signed in as. When it cannot sign in, the error says what it tried and why it failed. Credentials come only from the environment (in CI, from secrets through the action's inputs), never from command-line flags, so they stay out of shell history and process lists.

### The ownership marker

Every function the deploy writes gets `meta.managed_by = <marker>` and a note in its description. The marker is the **only** thing pruning acts on: a function with this marker whose plugin folder is gone is deleted, and a function without it (made by hand in the UI, or by another deployment with a different marker) is never touched.

- Use one marker per source of truth. Two repositories deploying to one instance need different markers, or each will prune the other's functions.
- **Never change the marker of a deployment that already has functions.** They would look hand-made: not updated cleanly, and never pruned. See [adopting](adopting.md#keep-your-existing-marker).

### What a deploy does

1. Waits for `GET /health` (the instance may be restarting).
2. Lists functions (`GET /api/v1/functions/list`), which is also the credential check: a bad key fails here, before anything is written.
3. If a plugin declares a [`requires:`](plugin-format.md#requires) setting, reads the instance's admin config. A setting that is missing — or that cannot be read — is a **warning in the report**, never a refusal: the deploy does not change instance settings.
4. Fetches git sources and bundles every plugin.
5. Creates, updates or leaves each function alone (see [bundling](bundling.md#what-the-deploy-script-does-with-a-bundle)), then applies manifest valves and activates and globalises as declared.
6. Prunes: managed functions whose folder is gone. Deleting more than half of them in one run is refused without `--force-prune`, so a renamed folder cannot wipe them all.

The report names each function with its type, for example ``- event function `mcpo_sync` (mcpo_sync/): unchanged``. In GitHub Actions it is also written to the job summary.

### The report: what changes, in versions

Under each function, the report lists what deploying it changes, compared with what the instance runs now:

```
Dry run at the latest commits: Open-WebUI functions

- filter function `inline_visualizer` (inline_visualizer/): would update
  - tool `inline_visualizer`: changed, still 2.2.3
  - skill `visualize`: changed, still (no version)
  - source https://github.com/Classic298/open-webui-plugins.git inline-visualizer-v2: f668387 -> 917c88f (latest of the default branch; plugin.yaml pins f668387)
- event function `stale_data` (stale_data/): unchanged (1.3.0)
```

- **function**: its `version:` header, `1.0.0 -> 1.1.0`, or `new (1.0.0)`. `code changed, still 1.0.0` means its own code changed and its version did not: bump it.
- **tool** and **skill**: each one the function installs, read from the code it embeds, so this is what the runtime will install once the new code is deployed. A tool's version is its header's, a skill's is its SKILL.md's `version`, if it has one. Only tools and skills that are new, removed or changed are listed.
- **source**: the commit of the git repository a plugin takes code from. The deploy records it in the function's meta (`meta.sources`), so the next report can say what it moves from. (A git-sourced function deployed before this was recorded updates once, to record it.)

`owpp deploy --dry-run --sync` is the same report at the commits `owpp sync` would move to: which versions an upgrade brings to the live instance, before anything is changed. The same in CI, on a schedule:

```yaml
- uses: zmnatz/open-webui-plugin-protocol@v0.2.0
  with:
    url: https://chat.example.com
    api-key: ${{ secrets.OPEN_WEBUI_API_KEY }}
    dry-run: "true"
    sync: "true"     # the report goes to the job summary
```

The deploy only ever creates, updates and prunes **functions**. Tools and skills are installed by the runtime inside Open-WebUI, driven by the function.

## `owpp sync`: moving a pinned commit

A plugin taken from git (`source:`) is pinned to a full commit SHA, so what is deployed changes only when the SHA moves. `owpp sync` moves it:

```
$ owpp sync
new   inline_visualizer: moved f668387 -> 917c88f (default branch)
        changed inline-visualizer-v2/SKILL.md
        changed inline-visualizer-v2/tool.py
        https://github.com/Classic298/open-webui-plugins/compare/f668387...917c88f
ok    other_plugin: up to date (v2), 3c1e9a0
1 plugin(s) moved: review the upstream changes, run `owpp check` and `owpp test`, then commit plugin.yaml
```

For each plugin with a `source:` (or just the ids given), it:

1. looks up the latest commit of the branch or tag in `source: track:`, or of the repository's default branch when there is none, with `git ls-remote`;
2. fetches the files the plugin takes at the pinned commit and at the latest one, and lists which were **changed**, **added** or **removed** (under a `dir:`, file by file), with a compare link for GitHub;
3. rewrites the `ref:` line of `plugin.yaml` to the new SHA, keeping every comment and the layout;
4. when files it takes changed, bumps the plugin's version (`--bump patch`, the default; `minor`, `major`, or `none`) and adds a `CHANGELOG.md` entry naming the commits and the files. A plugin whose function is the upstream's own keeps the upstream's version.

It commits nothing and deploys nothing: the change is yours to review and commit, as before. `--dry-run` says what would move and writes nothing. A plugin whose ref cannot be looked up, or whose files are not all there at the new commit, is reported as `FAIL` and left as it was, and the command exits 1.

To get a pull request for each upgrade, run it on a schedule:

```yaml
# .github/workflows/sync-plugins.yml
on:
  schedule: [{ cron: "0 6 * * 1" }]   # Mondays
  workflow_dispatch:
jobs:
  sync:
    runs-on: ubuntu-latest
    permissions: { contents: write, pull-requests: write }
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uvx owpp@0.2.0 sync | tee sync.txt
      - name: Open a pull request
        env: { GH_TOKEN: "${{ github.token }}" }
        run: |
          git diff --quiet && exit 0
          branch="owpp-sync/$(date +%Y-%m-%d)"
          git switch -c "$branch"
          git -c user.name=owpp-sync -c user.email=owpp-sync@users.noreply.github.com commit -qam "Sync plugins taken from git"
          git push -q origin "$branch"
          gh pr create --title "Sync plugins taken from git" --body-file sync.txt
```

The pull request is where the upstream diff is reviewed; the deploy runs when it is merged.

## Versions

A plugin has up to three versions, each where Open-WebUI reads it: the **function's** (`version:` under `function:` in `plugin.yaml`, the plugin's version, which Open-WebUI shows), the **tool's** (`version:` under `tool:`), and each **skill's** (`version:` in its SKILL.md front matter, optional). A loose `<id>.py` has its version in its docstring header.

### `owpp version`

```sh
owpp version                      # every plugin's versions: its own, its tool's, each skill's
owpp version viz                  # one plugin's
owpp version viz patch            # a new version: 1.0.0 -> 1.0.1, and a CHANGELOG.md entry
owpp version viz minor -m "Faster lookups."
owpp version viz 2.0.0
owpp version viz patch --tool     # the tool's version
owpp version viz patch --skill draw   # that skill's (added if it had none)
```

```
$ owpp version
excalidraw                  3.1.0
  tool excalidraw           (no version)
inline_visualizer           1.0.0
  tool inline_visualizer    (the upstream's)
  skill visualize           (the upstream's)
```

Shown versions are read from the files, so a plugin taken from git needs no fetch: what it takes verbatim shows as the upstream's. With a new version, it rewrites the one `version:` line, keeping comments and layout (and adds it, after `title:`, when there is none; no version bumps to 0.1.0). A function bump adds a `## <version> (<date>)` entry to the top of the plugin's `CHANGELOG.md`, which it creates if needed: the `-m` text, or a line to replace. Code taken verbatim from a `source:` keeps the upstream's version, so `owpp version` refuses to change it.

### `CHANGELOG.md`

`owpp create` writes one. When a plugin has one, `owpp check` warns if it has no `## <version>` entry for the function's current version (so `--strict` fails on it).

### `owpp check --since <ref>`

```sh
owpp check --since origin/main
FAIL  viz: changed since origin/main but its version is still 1.0.0 (run `owpp version viz patch`)
FAIL  tool viz: changed since origin/main but its version is still 1.0.0 (run `owpp version viz patch --tool`)
```

It bundles every plugin as it was at that git ref (with `git archive`) and as it is now, and fails for what changed without a new version:

- a **tool or skill that has a version** must bump its own when it changes;
- the **plugin** (the function's version) must bump when its own code changed, when a tool or skill without a version changed, was added or was removed, or when the commit of its `source:` moved (`owpp sync` bumps it for you).

A plugin that did not exist at that ref needs nothing. Code taken verbatim from a `source:` (an upstream function, tool or skills) is the upstream's to version: its changes count as the plugin's. In CI, check out with `fetch-depth: 0` and pass the base branch, for example `since: origin/${{ github.base_ref }}` on a pull request.

### Deploying an older version

Before it writes anything, a deploy compares each function, tool and skill version in the repository with the one the instance runs. If any would go **back** a version (`1.2.0` live, `1.1.0` here), the dry run says so:

```
- filter function `viz` (viz/): would update
  - function: 1.2.0 -> 1.1.0, OLDER than the live version

Warning: 1 function(s) would go back a version: `viz` (function 1.2.0 -> 1.1.0). The instance has newer versions than this repository: check the branch. A deploy refuses this without --force.
```

and a deploy refuses, writing nothing, unless it is given **`--force`** (action input `force: "true"`), for a deliberate rollback. Versions are compared as numbers (`1.10.0` is newer than `1.9.0`); a version that is not dotted numbers is never counted as older.

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
| `owpp sync`: moving a pinned commit, the files it lists, refusing what it cannot check | `tests/test_sync.py` |
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
