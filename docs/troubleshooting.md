# Troubleshooting

Each entry starts with what owpp prints. Then it gives the cause and the fix, with a link to the page that has the full details. Text in `<angle brackets>` stands for your own values.

## Signing in

The deploy signs in before it writes anything, so none of these errors changes the instance. For the credentials that it tries, their order, and what each needs on the instance, see [signing in](commands/deploy.md#signing-in).

### No credentials

```
error: no credentials, and Open-WebUI did not sign in without them (HTTP <status>: <reason>). Set OPEN_WEBUI_API_KEY (an admin's API key), OPEN_WEBUI_USERNAME and OPEN_WEBUI_PASSWORD, or OPEN_WEBUI_OIDC_TOKEN
```

No [credential variable](environment-variables.md#signing-in) is set, so the deploy tried to sign in without credentials. That works only if sign-in is off on the instance, or if a trusted-header proxy is in front of it.

Set one of the variables that the message names. In the GitHub Action, pass `api-key:` from a secret. A secret that the repository does not define arrives empty.

### A wrong user name or password

```
error: could not sign in as <user>: with a password (HTTP <status>: <reason>), with LDAP (HTTP <status>: <reason>)
```

owpp tried the account as an Open-WebUI account, then as an LDAP user, and Open-WebUI refused both. The text in brackets is its answer each time.

Check the user name and the password. The user name of an Open-WebUI account is its email. If you set only one of [`OPEN_WEBUI_USERNAME`](environment-variables.md#open_webui_username) and [`OPEN_WEBUI_PASSWORD`](environment-variables.md#open_webui_password), owpp stops earlier, with `OPEN_WEBUI_USERNAME and OPEN_WEBUI_PASSWORD go together: set both`.

### An OIDC token that is not exchanged

```
error: could not exchange the OIDC token with provider oidc (HTTP <status>: <reason>). The instance must set ENABLE_OAUTH_TOKEN_EXCHANGE=true and have that provider configured; set OPEN_WEBUI_OAUTH_PROVIDER if it is not called oidc
```

The instance does not allow token exchange, or its OAuth provider has a different name.

1. Set `ENABLE_OAUTH_TOKEN_EXCHANGE=true` on the instance.
2. Make sure that the instance has the OAuth provider configured.
3. If the provider is not called `oidc`, set [`OPEN_WEBUI_OAUTH_PROVIDER`](environment-variables.md#open_webui_oauth_provider).

### Signed in, but not as an admin

```
error: signed in with user <user> as <email>, who is not an admin (role user)
```

The credentials work, but the account cannot manage functions. Use the credentials of an admin, or give this account the admin role.

### A bad or disabled API key

```
error: GET /api/v1/functions/list -> HTTP 401: <Open-WebUI's answer>
```

owpp uses an API key unchanged. The deploy finds a wrong key only when it lists the functions, which is before it writes anything.

1. Check the key.
2. Make sure that **Enable API Keys** is on under Admin Panel > Settings > General.

## Reaching the instance

### `OPEN_WEBUI_URL` is not set

```
error: OPEN_WEBUI_URL is not set (the base URL of your Open-WebUI, e.g. https://chat.example.com)
```

Set [`OPEN_WEBUI_URL`](environment-variables.md#open_webui_url) to the address where you open Open-WebUI, without `/api`.

### The instance does not answer

```
error: <url>/health did not answer in time
```

The instance can be in a restart, so the deploy tries `GET /health` six times, 30 seconds apart.

1. Check the URL.
2. Make sure that the machine that runs the deploy can reach it.
3. If a redeploy of Open-WebUI takes longer, run the deploy again.

### A certificate is not trusted

An example, for a self-signed certificate:

```
error: <url>: TLS failed (self-signed certificate: give the CA that signed its certificate with OPEN_WEBUI_CA_CERT (or --ca-cert))
```

The system does not trust the CA that signed the instance's certificate (a private CA, or a self-signed certificate). Give the PEM of that CA with [`OPEN_WEBUI_CA_CERT`](environment-variables.md#open_webui_ca_cert) or `--ca-cert`.

If the server or a proxy wants a client certificate, the hint names `OPEN_WEBUI_CLIENT_CERT (or --client-cert)` instead: see [`OPEN_WEBUI_CLIENT_CERT`](environment-variables.md#open_webui_client_cert).

## Code taken from git

owpp checks a plugin's [`source:`](plugin-format.md#source) before it fetches anything. Every command that bundles the plugin fetches the code, for example `check`, `test`, `bundle` and `deploy`.

### No pinned commit

```
error: <id>/plugin.yaml: source has no `ref:`; run `owpp pull <id>` to pin it to the latest commit
```

You can write a `source:` without a `ref:`, but owpp cannot bundle the plugin until it has one.

1. Run the command that the message names.
2. Review the commit that it pins.
3. Commit `plugin.yaml`.

### A branch or tag instead of a commit

```
error: <id>/plugin.yaml: source.ref must be a full 40-character commit SHA, not a branch or tag (those can change under you)
```

`ref:` takes only a full commit SHA, so owpp also refuses a short SHA. For the reason, see [git sources](bundling.md#git-sources). To follow a branch or a tag:

1. Put its name in `branch:` or `tag:`.
2. Run [`owpp pull <id>`](commands/pull.md), which moves `ref:` for you.

### The repository cannot be fetched

```
error: git fetch <git url> <sha> failed: fatal: remote error: upload-pack: not our ref <sha>
```

The text after `failed:` is git's own message:

- `not our ref`: the commit is not in that repository. It can be a typing mistake, or a commit that is only on a fork.
- An authentication message, or `could not resolve host`: the repository is private, or the machine that runs owpp cannot reach it. owpp fetches with your `git` and its credentials, and never asks for a password.

Two related errors come without a fetch:

- If the URL is not `https://`, `ssh://` or `user@host:path`, owpp prints `source.git must be an https://, ssh:// or user@host:path git URL`.
- If git is not installed, owpp prints `` the git CLI is required to read a plugin's `source:` ``.

### A path that is not at that commit

```
error: <path> not found in <git url> at <sha>
error: no files under <path>/ in <git url> at <sha>
```

The repository does not have the file, or the folder of a `dir:` or of a [whole plugin](plugin-format.md#a-whole-plugin-from-git), at the pinned commit. Compare `path:` with the repository at that commit, not at its latest commit.

If a file that the plugin takes is gone at a new commit, [`owpp pull`](commands/pull.md) reports `FAIL  <id>: ...` and does not move the pin.

## [`owpp check`](commands/check.md)

### Undefined names

```
FAIL  <id>: undefined names: plugin_chat_is_temp
```

The bundle uses a name that nothing defines or imports. A line that names `tool <id>` instead of the plugin is about the bundle of that tool. The cause is one of these:

- A typing mistake.
- A missing import, for example `import json`.
- A library function in a function taken with `file:` from git, without its library. Add the library to [`include:`](plugin-format.md#include). [Libraries](libraries.md) says which library provides each `plugin_` name (`plugin_chat_is_temp` is in [`chat_data`](libraries.md#chat_data)).
- A library function in a single `<id>.py`, which cannot have `include:`. Make it a plugin folder, for example with [`owpp import`](commands/import.md).

### A library that is not in the bundle

```
error: <folder>/function.py:<line>: <name> is from the <library> library, which this bundle does not have: add it to include in <folder>/plugin.yaml
```

The file imports a library name, but the bundle does not have that library. Add the library to [`include:`](plugin-format.md#include). For `tool.py`, the message names `tool.include`.

If a file uses a library name without an import, the message says `<name> is used without importing it`, and gives the import line to add.

### A version that was not bumped

```
FAIL  <id>: changed since origin/main but its version is still 1.0.0 (run `owpp version <id> patch`)
FAIL  tool <id>: changed since origin/main but its version is still 1.0.0 (run `owpp version <id> patch --tool`)
```

[`owpp check --since <ref>`](commands/check.md) (the action's `since:` input) found a change in a plugin, tool or skill since that ref, but its version is the same. For the version that each change needs, see [a change needs a new version](commands/check.md#a-change-needs-a-new-version).

1. Run the command in brackets.
2. If the command added a `CHANGELOG.md` entry, write what changed in it.

If a plugin has a `CHANGELOG.md` with no entry for its current version, `check` warns `` warn  <id>/CHANGELOG.md has no `## <version>` entry for the current version ``. With `--strict`, this warning fails the check.

A deploy report shows a changed function that has the same version as `code changed, still 1.0.0`.

## Deploying

### Pruning refused

```
error: refusing to delete 3 of 4 git-controlled functions (a, b, c); check the folder names in the plugins folder (the id is the folder name), or re-run with --force-prune
```

The deploy deletes each function that has its [ownership marker](commands/deploy.md#the-ownership-marker) but no plugin folder. If that is more than one function, and more than half of the marked functions, it refuses before it writes anything. `--only` never prunes.

The usual causes are renamed folders (a function's id is its folder name), or a deploy of the wrong folder.

1. Check the folder names.
2. Check `--dir` (`plugins-dir:` in the action).

**Caution:** `--force-prune` deletes every function that the message names. Use it only if you retired those plugins.

3. If you did retire them, run the deploy again with `--force-prune`.

The GitHub Action has no input for `--force-prune`, so run `owpp deploy` yourself.

### Functions that are never pruned

There is no error: a function stays on the instance after you delete its folder. The cause is one of these:

- The deploy used `--only` or `--no-prune`, or it deployed a partial [build](commands/build.md). These never delete.
- The function does not have the marker that this deploy uses, so owpp treats it as made by hand. Perhaps the marker changed (a different `--managed-by` or [`OWPP_MANAGED_BY`](environment-variables.md#owpp_managed_by)). Or someone made the function in the UI, or another repository deployed it.

If the marker changed, use the marker that the existing functions have ([keep your existing marker](adopting.md#keep-your-existing-marker)).

**Caution:** A missing marker does not protect a function from an update. If a plugin folder has the same id, the deploy replaces the function's code and writes its own marker.

### An older version than the instance's

```
error: refusing to deploy older versions over newer ones on the instance: <id> (function 1.2.0 -> 1.1.0). Check you are deploying the right branch, or re-run with --force
```

The instance runs a newer version than the repository. The usual cause is a deploy from an old branch.

1. Deploy from the correct branch.

**Caution:** `--force` replaces the newer code on the instance with older code.

2. For a deliberate rollback, use `--force`: see [deploying an older version](commands/deploy.md#deploying-an-older-version).

### A page in the Artifacts panel answers 401

The deploy report shows a warning, and the deploy continues:

```
Warning: `<id>` need Open-WebUI's iframe Sandbox Allow Same Origin, and it is not on in this instance's default interface settings. Set it with DEFAULT_INTERFACE_SETTINGS='{"iframeSandboxAllowSameOrigin": true}' or under Admin Settings > General > Default Interface Settings (each user can also turn it on in Settings > Interface). Deploying anyway.
```

The plugin declares [`requires: iframe_sandbox_allow_same_origin`](plugin-format.md#requires). Without that setting, the Artifacts panel sends no session. Thus the plugin's page cannot know who is signed in, and answers 401. If owpp cannot read the admin config, the warning says `its default interface settings could not be read (...)` instead.

**Warning:** With the setting on, the script in any artifact can act in Open-WebUI as the user. Before you turn it on, read [why pages in the Artifacts panel need it](libraries.md#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin).

To turn the setting on, do what the warning says.
