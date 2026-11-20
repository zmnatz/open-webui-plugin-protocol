# Troubleshooting

Each entry starts with what owpp prints, then explains the cause and the fix, and links to the page that covers it in full. Text in `<angle brackets>` stands for your own values.

## Signing in

The deploy signs in before it writes anything, so none of these change the instance. Which credentials it tries, in which order, and what each needs on the instance: [signing in](commands/deploy.md#signing-in).

### No credentials

```
error: no credentials, and Open-WebUI did not sign in without them (HTTP <status>: <reason>). Set OPEN_WEBUI_API_KEY (an admin's API key), OPEN_WEBUI_USERNAME and OPEN_WEBUI_PASSWORD, or OPEN_WEBUI_OIDC_TOKEN
```

None of the [credential variables](environment-variables.md#signing-in) is set, so the deploy tried to sign in with nothing, which works only when the instance has sign-in switched off or sits behind a trusted-header proxy. Set one of the variables named. In the GitHub Action, pass `api-key:` from a secret; a secret that is not defined in the repository arrives empty.

### A wrong user name or password

```
error: could not sign in as <user>: with a password (HTTP <status>: <reason>), with LDAP (HTTP <status>: <reason>)
```

The account was tried as an Open-WebUI account and then as an LDAP user, and both refused. The text in brackets is what Open-WebUI answered each time. The user name of an Open-WebUI account is its email. Setting only one of [`OPEN_WEBUI_USERNAME`](environment-variables.md#open_webui_username) and [`OPEN_WEBUI_PASSWORD`](environment-variables.md#open_webui_password) fails earlier, with `OPEN_WEBUI_USERNAME and OPEN_WEBUI_PASSWORD go together: set both`.

### An OIDC token that is not exchanged

```
error: could not exchange the OIDC token with provider oidc (HTTP <status>: <reason>). The instance must set ENABLE_OAUTH_TOKEN_EXCHANGE=true and have that provider configured; set OPEN_WEBUI_OAUTH_PROVIDER if it is not called oidc
```

The instance does not allow token exchange, or its OAuth provider has another name. Do what the message says.

### Signed in, but not as an admin

```
error: signed in with user <user> as <email>, who is not an admin (role user)
```

The credentials work but the account cannot manage functions. Use an admin's credentials, or give that account the admin role.

### A bad or disabled API key

```
error: GET /api/v1/functions/list -> HTTP 401: <Open-WebUI's answer>
```

An API key is used as it is, so a wrong one is only found when the deploy lists the functions, which is still before anything is written. Check the key, and that **Enable API Keys** is on under Admin Panel > Settings > General.

## Reaching the instance

### `OPEN_WEBUI_URL` is not set

```
error: OPEN_WEBUI_URL is not set (the base URL of your Open-WebUI, e.g. https://chat.example.com)
```

Set [`OPEN_WEBUI_URL`](environment-variables.md#open_webui_url) to the address you open Open-WebUI at, without `/api`.

### The instance does not answer

```
error: <url>/health did not answer in time
```

The deploy waits for `GET /health` for about three minutes, since the instance may be restarting. Check the URL, and that the machine running the deploy can reach it. If a redeploy of Open-WebUI takes longer, rerun the deploy.

### A certificate is not trusted

An example, for a self-signed certificate:

```
error: <url>: TLS failed (certificate verify failed: self-signed certificate: give the CA that signed its certificate with OPEN_WEBUI_CA_CERT (or --ca-cert))
```

The instance's certificate is signed by a CA the system does not trust (a private CA, or a self-signed certificate). Pass that CA's PEM as the message says. When the server or a proxy wants a client certificate, the hint names `OPEN_WEBUI_CLIENT_CERT (or --client-cert)` instead. Both take a path or the PEM text: see [`OPEN_WEBUI_CA_CERT`](environment-variables.md#open_webui_ca_cert) and [`OPEN_WEBUI_CLIENT_CERT`](environment-variables.md#open_webui_client_cert).

## Code taken from git

A plugin's [`source:`](plugin-format.md#source) is checked before anything is fetched, and fetched by `check`, `test`, `bundle` and `deploy` alike.

### No pinned commit

```
error: <id>/plugin.yaml: source has no `ref:`; run `owpp pull <id>` to pin it to the latest commit
```

A `source:` can be written without a `ref:`, but nothing bundles it until it has one. Run the command it names, review the commit it pins, and commit `plugin.yaml`.

### A branch or tag instead of a commit

```
error: <id>/plugin.yaml: source.ref must be a full 40-character commit SHA, not a branch or tag (those can change under you)
```

A branch or a tag can move, and the code runs inside Open-WebUI with admin rights, so `ref:` takes only a full commit SHA. A short SHA is refused too. To follow a branch or a tag, name it in `branch:` or `tag:` and let [`owpp pull`](commands/pull.md) move `ref:` for you.

### The repository cannot be fetched

```
error: git fetch <git url> <sha> failed: fatal: remote error: upload-pack: not our ref <sha>
```

Everything after `failed:` is git's own message. `not our ref` means the commit is not in that repository (a typo, or a commit only on a fork). An authentication or `could not resolve host` message means the repository is private or unreachable from where owpp runs: owpp fetches with your `git` and its credentials, and never prompts for a password. A URL that is not `https://`, `ssh://` or `user@host:path` is refused before fetching, with `source.git must be an https://, ssh:// or user@host:path git URL`. Without git installed: `` the git CLI is required to read a plugin's `source:` ``.

### A path that is not at that commit

```
error: <path> not found in <git url> at <sha>
error: no files under <path>/ in <git url> at <sha>
```

The file, or the folder of a `dir:` or a [whole plugin](plugin-format.md#a-whole-plugin-from-git), is not in the repository at the pinned commit. Check `path:` against the repository at that commit, not at its latest one. [`owpp pull`](commands/pull.md) reports the same thing as `FAIL  <id>: ...` when a file the plugin takes is gone at the new commit, and leaves the pin where it was.

## [`owpp check`](commands/check.md)

### Undefined names

```
FAIL  <id>: undefined names: plugin_chat_is_temp
```

The bundle uses a name that is never defined or imported. Usually it is a library function and the plugin does not list that library under [`include:`](plugin-format.md#include): [libraries](libraries.md) says which library provides each `plugin_` name (`plugin_chat_is_temp` is [`chat_data`](libraries.md#chat_data)). Otherwise it is a typo, or an import missing from the file that uses it. A line naming `tool <id>` instead of the plugin is about the tool's bundle.

### A version that was not bumped

```
FAIL  <id>: changed since origin/main but its version is still 1.0.0 (run `owpp version <id> patch`)
FAIL  tool <id>: changed since origin/main but its version is still 1.0.0 (run `owpp version <id> patch --tool`)
```

[`owpp check --since <ref>`](commands/check.md) (the action's `since:` input) found a plugin, tool or skill whose code changed since that ref while its version stayed the same. Run the command in brackets and say what changed in the `CHANGELOG.md` entry it adds. Which changes count against which version: [versions](commands/version.md#versions). If the plugin has a `CHANGELOG.md` but no entry for its current version, `check` warns `` warn  <id>/CHANGELOG.md has no `## <version>` entry for the current version ``, which fails under `--strict`.

A deploy's report shows the same thing as `code changed, still 1.0.0`.

## Deploying

### Pruning refused

```
error: refusing to delete 3 of 4 git-controlled functions (a, b, c); check the folder names in the plugins folder (the id is the folder name), or re-run with --force-prune
```

The deploy deletes every function carrying its [ownership marker](commands/deploy.md#the-ownership-marker) whose plugin folder is gone, but refuses to delete more than half of them in one run, before writing anything. That usually means the folders were renamed (a function's id is its folder name), or the deploy points at the wrong folder: check `--dir` (`plugins-dir:` in the action). If the plugins really were retired, re-run with `--force-prune`. `--only` never prunes.

### Functions that are never updated or pruned

There is no error: a function keeps old code, or stays after its folder is deleted. It does not carry the marker this deploy uses, so owpp treats it as made by hand. That happens when the marker changed (another `--managed-by` or [`OWPP_MANAGED_BY`](environment-variables.md#owpp_managed_by)), or when the function was made in the UI or by another repository's deploy. Use the marker the existing functions have: see [keep your existing marker](adopting.md#keep-your-existing-marker).

### An older version than the instance's

```
error: refusing to deploy older versions over newer ones on the instance: <id> (function 1.2.0 -> 1.1.0). Check you are deploying the right branch, or re-run with --force
```

The instance runs a newer version than the repository, usually because the deploy ran from an old branch. Deploy from the right branch, or pass `--force` for a deliberate rollback: see [deploying an older version](commands/deploy.md#deploying-an-older-version).

### A page in the Artifacts panel answers 401

The deploy's report warns, and deploys anyway:

```
Warning: `<id>` need Open-WebUI's iframe Sandbox Allow Same Origin, and it is not on in this instance's default interface settings. Set it with DEFAULT_INTERFACE_SETTINGS='{"iframeSandboxAllowSameOrigin": true}' or under Admin Settings > General > Default Interface Settings (each user can also turn it on in Settings > Interface). Deploying anyway.
```

The plugin declares [`requires: iframe_sandbox_allow_same_origin`](plugin-format.md#requires). Without that setting the Artifacts panel sends no session, so the plugin's page cannot tell who is signed in and answers 401. Turning it on lets any artifact's script reach Open-WebUI, which is a real trade-off: read [why pages in the Artifacts panel need it](libraries.md#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin) before you do. When the admin config cannot be read, the warning says `its default interface settings could not be read (...)` instead.
