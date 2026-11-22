# owpp deploy

```
owpp deploy [--from FOLDER] [--only id,id] [--dry-run [--latest]] [--force]
            [--no-prune | --force-prune]
            [--managed-by marker] [--ca-cert PEM] [--client-cert PEM] [--client-key PEM]
            [--dir FOLDER]
```

Deploys the plugins to a running Open-WebUI: creates, updates or leaves alone one function per plugin, and prunes the functions it deployed whose plugin folder is gone. It only ever writes **functions**; tools and skills are installed by the [runtime](../runtime.md) inside Open-WebUI, driven by the function. With `--only` it deploys just those ids and **never prunes**, so deploying one plugin cannot delete another. With `--no-prune` it deploys every plugin and deletes nothing. With `--dry-run` it writes nothing and [reports](#the-report-what-changes-in-versions) what would change. With `--from` it deploys a [build](#deploying-a-build) made elsewhere instead of the plugins folder.

## Options

| Option | Meaning |
| --- | --- |
| `--from FOLDER` | Deploy the build in this folder ([`owpp build`](build.md)) instead of bundling the plugins folder: no checkout, `git` or source repositories needed. See [deploying a build](#deploying-a-build). |
| `--only id,id` | Deploy just these ids; no pruning. |
| `--dry-run` | List what would change, with versions; write nothing. |
| `--latest` | With `--dry-run`: report against the latest commit each git-sourced plugin follows, as [`owpp pull`](pull.md) would move it, without changing `plugin.yaml`. Refused without `--dry-run`. |
| `--force` | Deploy even where the instance runs a newer version than the repository: see [deploying an older version](#deploying-an-older-version). |
| `--no-prune` | Create and update, but delete nothing: the report lists the functions a full deploy would delete, as `not deleted (--no-prune)`. |
| `--force-prune` | Allow deleting more than half of the managed functions at once. |
| `--managed-by marker` | The [ownership marker](#the-ownership-marker). Default [`$OWPP_MANAGED_BY`](../environment-variables.md#owpp_managed_by), else `open-webui-plugin-protocol`. |
| `--ca-cert PEM` | A PEM of CA certificates to trust besides the system's (a private CA, or a self-signed Open-WebUI). Default [`$OPEN_WEBUI_CA_CERT`](../environment-variables.md#open_webui_ca_cert). |
| `--client-cert PEM` | A client certificate to present, for a server or proxy that requires mutual TLS. Default [`$OPEN_WEBUI_CLIENT_CERT`](../environment-variables.md#open_webui_client_cert). |
| `--client-key PEM` | Its private key, when not in the same PEM. Default [`$OPEN_WEBUI_CLIENT_KEY`](../environment-variables.md#open_webui_client_key). |
| `--dir FOLDER` | The plugins folder. Default [`$OWPP_PLUGINS_DIR`](../environment-variables.md#owpp_plugins_dir), else `./plugins`. |

The certificate options and their variables take a path, or the PEM text itself.

## Deploy settings

The instance and the credentials come only from the environment, never from flags: [`OPEN_WEBUI_URL`](../environment-variables.md#open_webui_url) (required), and the sign-in variables below. Every variable, its default and how it interacts with the others: [environment variables](../environment-variables.md). In CI, the [action's](../tooling.md#github-action) inputs set them.

## Signing in

The deploy needs an **admin** of the instance. It uses the first of these that is set:

| Set | What it does | The instance needs |
| --- | --- | --- |
| [`OPEN_WEBUI_API_KEY`](../environment-variables.md#open_webui_api_key) | Uses the key as it is. | API keys on (Admin Panel > Settings > General > Enable API Keys), and a key from Settings > Account > API keys. |
| [`OPEN_WEBUI_USERNAME`](../environment-variables.md#open_webui_username) and [`OPEN_WEBUI_PASSWORD`](../environment-variables.md#open_webui_password) | Signs in with them as an Open-WebUI account (the user name is the email, `POST /api/v1/auths/signin`), and if that fails, as an LDAP user (`POST /api/v1/auths/ldap`). | Password sign-in on; LDAP configured for an LDAP user. |
| [`OPEN_WEBUI_OIDC_TOKEN`](../environment-variables.md#open_webui_oidc_token) | Exchanges the token for a session (`POST /api/v1/auths/oauth/<provider>/token/exchange`, the provider from [`OPEN_WEBUI_OAUTH_PROVIDER`](../environment-variables.md#open_webui_oauth_provider), default `oidc`). | `ENABLE_OAUTH_TOKEN_EXCHANGE=true`, and that OAuth provider configured. |
| nothing | Signs in with no credentials, as the browser would. | Sign-in switched off (`WEBUI_AUTH=False`), or a proxy in front of it that adds the trusted email header (`WEBUI_AUTH_TRUSTED_EMAIL_HEADER`). |

The session it gets is used for that run only, and the account must be an admin: otherwise the deploy stops before writing anything, saying who it signed in as. When it cannot sign in, the error says what it tried and why it failed.

## The ownership marker

Every function the deploy writes gets `meta.managed_by = <marker>` (`--managed-by`, else [`OWPP_MANAGED_BY`](../environment-variables.md#owpp_managed_by)) and a note in its description. The marker is the **only** thing pruning acts on: a function with this marker whose plugin folder is gone is deleted, and a function without it (made by hand in the UI, or by another deployment with a different marker) is never touched.

- Use one marker per source of truth. Two repositories deploying to one instance need different markers, or each will prune the other's functions.
- **Never change the marker of a deployment that already has functions.** They would look hand-made: not updated cleanly, and never pruned. See [adopting](../adopting.md#keep-your-existing-marker).

## What a deploy does

1. Waits for `GET /health` (the instance may be restarting).
2. Lists functions (`GET /api/v1/functions/list`), which is also the credential check: a bad key fails here, before anything is written.
3. If a plugin declares a [`requires:`](../plugin-format.md#requires) setting, reads the instance's admin config. A setting that is missing — or that cannot be read — is a **warning in the report**, never a refusal: the deploy does not change instance settings.
4. Fetches git sources and bundles every plugin.
5. Creates, updates or leaves each function alone (see [bundling](../bundling.md#what-the-deploy-script-does-with-a-bundle)), then applies manifest valves and activates and globalises as declared.
6. Prunes: managed functions whose folder is gone. Deleting more than half of them in one run is refused without `--force-prune`, so a renamed folder cannot wipe them all.

The report names each function with its type, for example ``- event function `mcpo_sync` (mcpo_sync/): unchanged``. In GitHub Actions it is also written to the job summary.

## The report: what changes, in versions

Under each function, the report lists what deploying it changes, compared with what the instance runs now:

```
Dry run at the latest commits: Open-WebUI functions

- filter function `inline_visualizer` (inline_visualizer/): would update
  - tool `inline_visualizer`: changed, still 2.2.3
  - skill `visualize`: changed, still (no version)
  - source https://github.com/Classic298/open-webui-plugins.git inline-visualizer-v2: f668387 -> 917c88f (latest of the default branch; plugin.yaml pins f668387)
- event function `stale_data` (stale_data/): unchanged (1.3.0)
```

- **function**: its `version:` header, `1.0.0 -> 1.1.0`, or `new (1.0.0)`. `code changed, still 1.0.0` means its own code changed and its version did not: bump it with [`owpp version`](version.md).
- **tool** and **skill**: each one the function installs, read from the code it embeds, so this is what the runtime will install once the new code is deployed. A tool's version is its header's, a skill's is its SKILL.md's `version`, if it has one. Only tools and skills that are new, removed or changed are listed.
- **source**: the commit of the git repository a plugin takes code from. The deploy records it in the function's meta (`meta.sources`), so the next report can say what it moves from. (A git-sourced function deployed before this was recorded updates once, to record it.)

`owpp deploy --dry-run --latest` is the same report at the commits `owpp pull` would move to: which versions an upgrade brings to the live instance, before anything is changed. Without `--dry-run`, `--latest` is refused: ``error: --latest only goes with --dry-run: to deploy the latest commits, run `owpp pull`, review and commit the change, then deploy``. The same report in CI, on a schedule:

```yaml
- uses: zmnatz/open-webui-plugin-protocol@v0.6.1
  with:
    url: https://chat.example.com
    api-key: ${{ secrets.OPEN_WEBUI_API_KEY }}
    dry-run: "true"
    latest: "true"   # the report goes to the job summary
```

## Deploying an older version

Before it writes anything, a deploy compares each function, tool and skill version in the repository with the one the instance runs. If any would go **back** a version (`1.2.0` live, `1.1.0` here), the dry run says so:

```
- filter function `viz` (viz/): would update
  - function: 1.2.0 -> 1.1.0, OLDER than the live version

Warning: 1 function(s) would go back a version: `viz` (function 1.2.0 -> 1.1.0). The instance has newer versions than this repository: check the branch. A deploy refuses this without --force.
```

and a deploy refuses, writing nothing, unless it is given **`--force`** (action input `force: "true"`), for a deliberate rollback. Versions are compared as numbers (`1.10.0` is newer than `1.9.0`); a version that is not dotted numbers is never counted as older. [Versions](version.md) says which versions a plugin has.

## Deploying a build

`owpp deploy --from dist` deploys what [`owpp build`](build.md) wrote, exactly: it bundles nothing and fetches nothing, so the machine that deploys needs only owpp and the instance. Everything else is the same deploy: signing in, the report, the refusals, valves, `global`, and the iframe warning, from the `requires:` the build recorded. A partial build never prunes, a `--latest` build deploys only as a dry run, and a build from another owpp version is refused: [what a build holds](build.md). `--from` with `--latest` is refused, because a build has no sources to look up.

## Examples

```sh
export OPEN_WEBUI_URL=https://chat.example.com OPEN_WEBUI_API_KEY=sk-...
owpp deploy --dry-run                       # what would change; writes nothing
owpp deploy --only my_plugin --dry-run      # one plugin
owpp deploy --only my_plugin                # deploy it, prune nothing
owpp deploy --dry-run --latest              # what `owpp pull` would bring
owpp deploy --managed-by git:you/your-repo  # a second repository on the same instance
```

## Related

- [`owpp check`](check.md): what the action runs before it deploys.
- [`owpp pull`](pull.md): move pinned commits before a deploy.
- [`owpp version`](version.md): give a change a new version.
- [Tooling and CI](../tooling.md#github-action): deploying from GitHub Actions.
- [Adopting](../adopting.md): taking over functions already on an instance.
