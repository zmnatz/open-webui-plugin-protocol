# Environment variables

These are the environment variables that `owpp` reads. If a variable has a flag, the flag wins over the variable, and the variable wins over the default. An empty variable counts as unset, so an empty action input gets the default.

The instance URL and the credentials come only from the environment, never from flags. Thus they stay out of shell history and process lists. In CI, the [GitHub Action](tooling.md#github-action) sets them from its inputs. Use secrets for the credentials.

| Action input | Sets |
| --- | --- |
| `url` | [`OPEN_WEBUI_URL`](#open_webui_url) |
| `api-key` | [`OPEN_WEBUI_API_KEY`](#open_webui_api_key) |
| `username`, `password` | [`OPEN_WEBUI_USERNAME`](#open_webui_username), [`OPEN_WEBUI_PASSWORD`](#open_webui_password) |
| `oidc-token`, `oauth-provider` | [`OPEN_WEBUI_OIDC_TOKEN`](#open_webui_oidc_token), [`OPEN_WEBUI_OAUTH_PROVIDER`](#open_webui_oauth_provider) |
| `plugins-dir` | [`OWPP_PLUGINS_DIR`](#owpp_plugins_dir) |
| `managed-by` | [`OWPP_MANAGED_BY`](#owpp_managed_by) |

The action has no input for the [certificate variables](#tls).

A plugin can name its own variables in `${NAME:-default}` templates. `owpp` does not read them. Set them on the Open-WebUI container, where the plugin reads them when it runs ([environment templates](plugin-format.md#environment-templates)).

## The plugins folder

### `OWPP_PLUGINS_DIR`

The plugins folder. A relative path starts at the current directory.

- **Default**: `./plugins`.
- **Read by**: every command, as the default of `--dir`.
- If the folder does not exist, some commands stop with `no plugins folder at <folder> (pass --dir, or set OWPP_PLUGINS_DIR)`. These are `list`, `check`, `bundle`, `build`, `test`, `pull`, `migrate` and `live` (except `live --down`).
- `create`, `init` and `import` make the folder.

## The instance

### `OPEN_WEBUI_URL`

The base URL of the Open-WebUI instance: the address where you open it (`https://chat.example.com`, without `/api`). owpp removes a trailing `/`.

- **Default**: none.
- **Read by**: [`owpp deploy`](commands/deploy.md) and [`owpp import --instance`](commands/import.md).
- **Required** for both. Without it, the deploy stops with `error: OPEN_WEBUI_URL is not set (the base URL of your Open-WebUI, e.g. https://chat.example.com)`.

## Signing in

`owpp deploy` and `owpp import --instance` sign in as an admin. [Signing in](commands/deploy.md#signing-in) says which of these variables they use, in which order, and what each one needs on the instance.

Only these two commands read these variables. Before [`owpp test --upstream`](commands/test.md) runs the tests of another repository, it removes every variable whose name starts with `OPEN_WEBUI_`. Thus that code has nothing to sign in with.

### `OPEN_WEBUI_API_KEY`

An admin's API key. owpp uses it unchanged.

- **Default**: none.
- **Read by**: `owpp deploy` and `owpp import --instance`.
- It comes first: if it is set, owpp ignores the other sign-in variables.
- The deploy finds a wrong key when it lists the functions, before it writes anything.

### `OPEN_WEBUI_USERNAME`

An admin's user name: the email of an Open-WebUI account, or an LDAP user name. owpp signs in with it as an Open-WebUI account. If that fails, it signs in as an LDAP user.

- **Default**: none.
- **Read by**: `owpp deploy` and `owpp import --instance`, when [`OPEN_WEBUI_API_KEY`](#open_webui_api_key) is not set.
- Set it together with [`OPEN_WEBUI_PASSWORD`](#open_webui_password). If you set only one of them, owpp stops with `OPEN_WEBUI_USERNAME and OPEN_WEBUI_PASSWORD go together: set both`.
- If both are set, owpp ignores [`OPEN_WEBUI_OIDC_TOKEN`](#open_webui_oidc_token).

### `OPEN_WEBUI_PASSWORD`

The password of [`OPEN_WEBUI_USERNAME`](#open_webui_username).

- **Default**: none.
- **Read by**: `owpp deploy` and `owpp import --instance`, when [`OPEN_WEBUI_API_KEY`](#open_webui_api_key) is not set.
- Set it together with `OPEN_WEBUI_USERNAME`: set both or neither.

### `OPEN_WEBUI_OIDC_TOKEN`

An OIDC access token. owpp exchanges it for an Open-WebUI session, with the provider that [`OPEN_WEBUI_OAUTH_PROVIDER`](#open_webui_oauth_provider) names. The instance must set `ENABLE_OAUTH_TOKEN_EXCHANGE=true`.

- **Default**: none.
- **Read by**: `owpp deploy` and `owpp import --instance`, when [`OPEN_WEBUI_API_KEY`](#open_webui_api_key), [`OPEN_WEBUI_USERNAME`](#open_webui_username) and [`OPEN_WEBUI_PASSWORD`](#open_webui_password) are not set.

### `OPEN_WEBUI_OAUTH_PROVIDER`

The name of the Open-WebUI OAuth provider that issued the [`OPEN_WEBUI_OIDC_TOKEN`](#open_webui_oidc_token). owpp trims the name and makes it lowercase. The name can contain lowercase letters, digits, `_` and `-`, and cannot start with a digit. Otherwise, owpp stops with `OPEN_WEBUI_OAUTH_PROVIDER '<name>' is not a provider name`.

- **Default**: `oidc`.
- **Read by**: `owpp deploy` and `owpp import --instance`, only with `OPEN_WEBUI_OIDC_TOKEN`.

## The ownership marker

### `OWPP_MANAGED_BY`

The [ownership marker](commands/deploy.md#the-ownership-marker) that the deploy writes on every function. Pruning acts only on functions that have it.

**Caution:** Do not change the marker for an instance that already has deployed functions. The deploy then does not prune the old functions ([keep your existing marker](adopting.md#keep-your-existing-marker)).

- **Default**: `open-webui-plugin-protocol`.
- **Read by**: `owpp deploy`, as the default of `--managed-by`.

## TLS

Each of these variables holds a path to a PEM file (owpp expands `~`), or the PEM text itself, as a CI secret holds it. [`owpp deploy`](commands/deploy.md) and [`owpp import --instance`](commands/import.md) read them.

The value must be PEM text, or a path to a PEM file. If it is neither, the command stops with `<variable>: no file <path> (give a path to a PEM file, or the PEM itself)`. If none of the variables is set, both commands use Python's defaults: the system's CAs, and no client certificate.

### `OPEN_WEBUI_CA_CERT`

CA certificates to trust in addition to the system's: a private CA, or a self-signed Open-WebUI.

- **Default**: none.
- **Read by**: `owpp deploy` and `owpp import --instance`, as the default of `--ca-cert`.

### `OPEN_WEBUI_CLIENT_CERT`

A client certificate that owpp presents to a server or proxy that requires mutual TLS. It can also hold the private key.

- **Default**: none.
- **Read by**: `owpp deploy` and `owpp import --instance`, as the default of `--client-cert`.

### `OPEN_WEBUI_CLIENT_KEY`

The private key of [`OPEN_WEBUI_CLIENT_CERT`](#open_webui_client_cert), if it is not in the same PEM.

- **Default**: none.
- **Read by**: `owpp deploy` and `owpp import --instance`, as the default of `--client-key`.
- It needs a client certificate. Without one, the command stops with `OPEN_WEBUI_CLIENT_KEY needs OPEN_WEBUI_CLIENT_CERT`.

## The test harness

### `OWPP_CACHE_DIR`

The folder where [`owpp test`](commands/test.md) keeps the Open-WebUI code that the [test harness](testing/harness.md) runs. The first run downloads it there. Later runs use it again.

- **Default**: `$XDG_CACHE_HOME/owpp`, or `~/.cache/owpp` if `XDG_CACHE_HOME` is not set.
- **Read by**: `owpp test`, and any pytest run that uses the `owui` fixture.

### `OWPP_FRESH_OPEN_WEBUI`

If set, each test gets a new Open-WebUI: the harness imports and starts it again ([a new Open-WebUI for a test](testing/harness.md#a-new-open-webui-for-a-test)). This makes each test some seconds slower.

- **Default**: not set. Each test gets the same Open-WebUI, put back as it was after its startup.
- **Read by**: the `owui` fixture.

## Set by owpp live, for the live tests

[`owpp live`](commands/live.md) sets these variables for the pytest run that it starts. With `--up`, it prints them, so you can run the tests yourself against the stack that stays up. The [fixtures](testing/live.md#the-fixtures) of owpp live read them. If an account variable is missing, a test that needs that account stops the run, and says to start `owpp live`.

### `OWPP_LIVE_URL`

The address of the throwaway Open-WebUI: `http://127.0.0.1:3000`, unless you give `--port`. `owpp.live.url()` returns it, for a page to `goto`.

### `OWPP_LIVE_AIMOCK_URL`

The address of aimock: `http://127.0.0.1:4010`, unless you give `--aimock-port`. The `aimock` fixture reads aimock's journal there.

### `OWPP_LIVE_ADMIN`

The admin account that `owpp live` signed up, as JSON: `name`, `email`, `password` and `token`. The `api` fixture and the `admin` page use it.

### `OWPP_LIVE_USER`

The same data for the account that is not an admin. The `user_api` fixture and the `user` page use it.

### `OWPP_LIVE_FAILURES`

The folder where a failed test with a page saves what it saw: `failures/` in the tests folder.

### `PYTEST_PLUGINS`

A pytest variable: the plugins that pytest loads. `owpp live` adds `owpp.live.fixtures` after the plugins that are already in it, so the run has [the fixtures](testing/live.md#the-fixtures). No other pytest run has them.

## Set by other tools

`owpp` also reads these variables. You do not set them for owpp.

### `GITHUB_STEP_SUMMARY`

GitHub Actions sets it to the file of the job summary. If it is set, `owpp deploy` appends its report to that file, so the report shows on the page of the run.

### `XDG_CACHE_HOME`

The user's cache folder, on Linux and other systems that follow the XDG rules. If [`OWPP_CACHE_DIR`](#owpp_cache_dir) is not set, owpp keeps its cache in `owpp/` there.

### `PYTEST_DISABLE_PLUGIN_AUTOLOAD`

A pytest variable that stops pytest from loading installed plugins. If it is set, [`owpp test`](commands/test.md) loads its own pytest plugin by name (`-p owpp.testing.pytest_plugin`). Thus the `owui` and `plugin` fixtures stay available.
