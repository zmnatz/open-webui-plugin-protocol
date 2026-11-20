# Environment variables

These are the environment variables `owpp` reads. Where a variable has a flag, the flag wins over it, and the variable wins over the default. An empty variable counts as unset, so an action input left empty gets the default.

The instance and the credentials come only from the environment, never from flags, so they stay out of shell history and process lists. In CI, the [GitHub Action](tooling.md#github-action) sets them from its inputs, with secrets for the credentials:

| Action input | Sets |
| --- | --- |
| `url` | [`OPEN_WEBUI_URL`](#open_webui_url) |
| `api-key` | [`OPEN_WEBUI_API_KEY`](#open_webui_api_key) |
| `username`, `password` | [`OPEN_WEBUI_USERNAME`](#open_webui_username), [`OPEN_WEBUI_PASSWORD`](#open_webui_password) |
| `oidc-token`, `oauth-provider` | [`OPEN_WEBUI_OIDC_TOKEN`](#open_webui_oidc_token), [`OPEN_WEBUI_OAUTH_PROVIDER`](#open_webui_oauth_provider) |
| `plugins-dir` | [`OWPP_PLUGINS_DIR`](#owpp_plugins_dir) |
| `managed-by` | [`OWPP_MANAGED_BY`](#owpp_managed_by) |

The action has no input for the [certificate variables](#tls).

The variables a plugin's own `${NAME:-default}` templates name are not read by `owpp`: they are set on the Open-WebUI container and read when the plugin loads there (see [environment templates](plugin-format.md#environment-templates)).

## The plugins folder

### `OWPP_PLUGINS_DIR`

The plugins folder, relative to the current directory unless it is absolute.

- **Default**: `./plugins`.
- **Read by**: every command, as the default of `--dir`, which wins over it.
- When the folder does not exist, `list`, `check`, `bundle`, `test`, `pull` and `migrate` stop with `no plugins folder at <folder> (pass --dir, or set OWPP_PLUGINS_DIR)`. `create` and `init` make it.

## The instance

### `OPEN_WEBUI_URL`

The base URL of the Open-WebUI instance, the address you open it at (`https://chat.example.com`, without `/api`). A trailing `/` is dropped.

- **Default**: none. Required: without it the deploy stops with `error: OPEN_WEBUI_URL is not set (the base URL of your Open-WebUI, e.g. https://chat.example.com)`.
- **Read by**: [`owpp deploy`](commands/deploy.md).

## Signing in

The deploy signs in as an admin with the first of these that is set, and ignores the rest: [`OPEN_WEBUI_API_KEY`](#open_webui_api_key); [`OPEN_WEBUI_USERNAME`](#open_webui_username) and [`OPEN_WEBUI_PASSWORD`](#open_webui_password); [`OPEN_WEBUI_OIDC_TOKEN`](#open_webui_oidc_token); or nothing. What each needs on the instance: [signing in](commands/deploy.md#signing-in).

All of them are read by [`owpp deploy`](commands/deploy.md) only. [`owpp test --upstream`](commands/test.md) removes every variable whose name starts with `OPEN_WEBUI_` from its environment before it runs another repository's tests, so that code has nothing to sign in with.

### `OPEN_WEBUI_API_KEY`

An admin's API key, used as it is.

- **Default**: none.
- **Read by**: `owpp deploy`.
- It comes first: when it is set, the other sign-in variables are not read. A wrong key is found when the deploy lists the functions, before it writes anything.

### `OPEN_WEBUI_USERNAME`

An admin's user name: the email of an Open-WebUI account, or an LDAP user name. The deploy signs in as an Open-WebUI account and, if that fails, as an LDAP user.

- **Default**: none.
- **Read by**: `owpp deploy`, when [`OPEN_WEBUI_API_KEY`](#open_webui_api_key) is not set.
- It goes with [`OPEN_WEBUI_PASSWORD`](#open_webui_password): setting one without the other stops the deploy with `OPEN_WEBUI_USERNAME and OPEN_WEBUI_PASSWORD go together: set both`. With both set, [`OPEN_WEBUI_OIDC_TOKEN`](#open_webui_oidc_token) is not read.

### `OPEN_WEBUI_PASSWORD`

The password of [`OPEN_WEBUI_USERNAME`](#open_webui_username).

- **Default**: none.
- **Read by**: `owpp deploy`, when [`OPEN_WEBUI_API_KEY`](#open_webui_api_key) is not set.
- It goes with `OPEN_WEBUI_USERNAME`: set both or neither.

### `OPEN_WEBUI_OIDC_TOKEN`

An OIDC access token, which the deploy exchanges for an Open-WebUI session with the provider [`OPEN_WEBUI_OAUTH_PROVIDER`](#open_webui_oauth_provider) names. The instance must set `ENABLE_OAUTH_TOKEN_EXCHANGE=true`.

- **Default**: none.
- **Read by**: `owpp deploy`, when neither [`OPEN_WEBUI_API_KEY`](#open_webui_api_key) nor [`OPEN_WEBUI_USERNAME`](#open_webui_username) and [`OPEN_WEBUI_PASSWORD`](#open_webui_password) are set.

### `OPEN_WEBUI_OAUTH_PROVIDER`

The name of the Open-WebUI OAuth provider the [`OPEN_WEBUI_OIDC_TOKEN`](#open_webui_oidc_token) is from. It is trimmed and lowercased, and must be lowercase letters, digits, `_` and `-`, not starting with a digit; otherwise the deploy stops with `OPEN_WEBUI_OAUTH_PROVIDER '<name>' is not a provider name`.

- **Default**: `oidc`.
- **Read by**: `owpp deploy`, and used only with `OPEN_WEBUI_OIDC_TOKEN`.

## The ownership marker

### `OWPP_MANAGED_BY`

The [ownership marker](commands/deploy.md#the-ownership-marker) the deploy writes on every function, and the only thing pruning acts on. Never change it for an instance that already has functions deployed: see [keep your existing marker](adopting.md#keep-your-existing-marker).

- **Default**: `open-webui-plugin-protocol`.
- **Read by**: `owpp deploy`, as the default of `--managed-by`, which wins over it.

## TLS

Each of these is a path to a PEM file (`~` is expanded) or the PEM text itself, as a CI secret holds it. A path that is not a file stops the deploy with `<variable>: no file <path> (give a path to a PEM file, or the PEM itself)`. With none of them set, the deploy uses Python's defaults: the system's CAs, and no client certificate.

### `OPEN_WEBUI_CA_CERT`

CA certificates to trust besides the system's: a private CA, or a self-signed Open-WebUI.

- **Default**: none.
- **Read by**: `owpp deploy`, as the default of `--ca-cert`, which wins over it.

### `OPEN_WEBUI_CLIENT_CERT`

A client certificate to present, for a server or proxy that requires mutual TLS. It may hold the private key too.

- **Default**: none.
- **Read by**: `owpp deploy`, as the default of `--client-cert`, which wins over it.

### `OPEN_WEBUI_CLIENT_KEY`

The private key of [`OPEN_WEBUI_CLIENT_CERT`](#open_webui_client_cert), when it is not in the same PEM.

- **Default**: none.
- **Read by**: `owpp deploy`, as the default of `--client-key`, which wins over it.
- It needs a client certificate: without one the deploy stops with `OPEN_WEBUI_CLIENT_KEY needs OPEN_WEBUI_CLIENT_CERT`.

## Set by other tools

`owpp` also reads these, which you do not set yourself.

### `GITHUB_STEP_SUMMARY`

Set by GitHub Actions to the file of the job summary. When it is set, `owpp deploy` appends its report to that file, so the report shows on the run's page.

### `PYTEST_DISABLE_PLUGIN_AUTOLOAD`

pytest's own switch for not loading installed plugins. When it is set, [`owpp test`](commands/test.md) loads its own pytest plugin by name (`-p owpp.testing.pytest_plugin`), so the `owui` and `plugin` fixtures are still there.
