# Getting started

This page takes you from an empty repository to a plugin that runs in Open-WebUI, deployed from git. It takes approximately fifteen minutes. You need [uv](install.md#requirements) and `git`.

## 1. A repository for your plugins

Make a git repository:

```sh
mkdir my-plugins && cd my-plugins && git init
```

The plugins go in `plugins/`, one folder for each plugin. You do not need to make the folder: `owpp` makes it.

## 2. Create a plugin

Start the wizard:

```sh
uvx owpp create
```

The [wizard](creating.md) asks what the plugin is, one stage at a time. Then it writes `plugins/<id>/`: the manifest, stubs for the code, tests, a README and a CHANGELOG. Each question has a default. If you push Enter for each question, you get a small event plugin. The wizard writes nothing until the last stage.

```
plugins/hello/
  plugin.yaml          the manifest: the function's header, its tool, skills and libraries
  function.py          the function, with every hook a stub to fill in
  tests/test_hello.py  tests that pass against a mock Open-WebUI
  README.md            what it does, and how to test and deploy it
  CHANGELOG.md         one entry per version
```

If you already have functions in Open-WebUI, see [adopting](adopting.md) to move them into this layout.

## 3. Check and test it

1. Run `uvx owpp check --strict`. It bundles the plugin as a deploy does, then compiles and lints it.
2. Run `uvx --from 'owpp[test]' owpp test`. It runs the plugin's tests against a mock Open-WebUI.
3. Optional: run `uvx owpp bundle hello`. It prints the single file that Open-WebUI will store.

```sh
uvx owpp check --strict                    # bundle it exactly as a deploy would, compile, lint
uvx --from 'owpp[test]' owpp test          # its tests, against a mock Open-WebUI
uvx owpp bundle hello                      # print the single file Open-WebUI will store
```

Now write the plugin. The [authoring guide](authoring.md) has the conventions. [Libraries](libraries.md) has routes, jobs, per-chat data, pages and more. Run `check` and `test` after each change.

## 4. Connect to Open-WebUI

The deploy uses Open-WebUI's admin API, so it must sign in as an admin. [Signing in](commands/deploy.md#signing-in) gives each method and what the instance needs for it.

Caution: do not put credentials in git. Anyone who can read the repository can then deploy code with admin rights.

1. Set `OPEN_WEBUI_URL` to the address of the instance.
2. Set the variables of one sign-in method: an API key, an admin's email (or LDAP user) and password, or an OIDC token.
3. If the instance has no sign-in, or a proxy adds the trusted email header, set no credentials.

```sh
export OPEN_WEBUI_URL=https://chat.example.com

# an API key: Admin Panel > Settings > General > Enable API Keys, then
# Settings > Account > API keys > Create new secret key
export OPEN_WEBUI_API_KEY=sk-...

# or an admin's email (or LDAP user) and password
export OPEN_WEBUI_USERNAME=admin@example.com OPEN_WEBUI_PASSWORD=...

# or an OIDC token (the instance must set ENABLE_OAUTH_TOKEN_EXCHANGE=true)
export OPEN_WEBUI_OIDC_TOKEN=... OPEN_WEBUI_OAUTH_PROVIDER=oidc
```

If possible, use an admin account that only deploys. [Environment variables](environment-variables.md) gives each variable.

## 5. Deploy

1. Run `uvx owpp deploy --dry-run`. It shows what will change, with the versions, and writes nothing.
2. Read the report.
3. Run `uvx owpp deploy`. It creates or updates the functions.
4. In Open-WebUI, open **Admin Panel > Functions** and find your plugin.
5. Do the checks that the plugin's README gives.

```sh
uvx owpp deploy --dry-run       # what would change, with versions; writes nothing
uvx owpp deploy                 # create or update the functions
```

The deploy creates each function and activates it. It makes a new filter global, unless the manifest says `global: false`. It marks the functions it deploys, and it updates or deletes only those. It never touches a function made by hand.

## 6. Deploy from CI

1. Commit the repository.
2. Add the credential to the repository as a secret, for example `OPEN_WEBUI_API_KEY`.
3. Add the workflow below. It deploys on each push to `main`.

The secret goes into an input of the action: `api-key`, `username` and `password`, or `oidc-token`. Each input sets one of the [environment variables](environment-variables.md#signing-in) of step 4.

```yaml
# .github/workflows/deploy-plugins.yml
on:
  push: { branches: [main], paths: ["plugins/**"] }
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
```

The action runs `owpp check`, then it deploys and writes the report to the job summary. [Tooling](tooling.md#github-action) gives all its inputs.

## 7. Change it

Each change gets a new version.

1. Run `uvx owpp version hello minor -m "<what changed>"`. It changes `plugin.yaml` and `CHANGELOG.md`.
2. Run `uvx owpp check --since origin/main`. It fails if a plugin changed but its version did not.

```sh
uvx owpp version hello minor -m "Says hello in French too."   # plugin.yaml and CHANGELOG.md
uvx owpp check --since origin/main                             # fails on a change without a new version
```

A deploy refuses to put an older version over a newer version on the instance, unless you give `--force`. See [deploying an older version](commands/deploy.md#deploying-an-older-version).

A plugin can take its code from another repository, pinned to a commit. For that plugin, `owpp pull` moves the pin to the latest commit, for you to review. `owpp deploy --dry-run --latest` shows what that upgrade will change on the instance. See [`owpp pull`](commands/pull.md).

## Where next

| To | Read |
| --- | --- |
| Pick the correct type of plugin, and see all the options of the wizard | [Creating a plugin](creating.md) |
| Write it well: conventions and a checklist | [Authoring a plugin](authoring.md) |
| Know every key of `plugin.yaml` | [Plugin format](plugin-format.md) |
| See plugins that work | [Examples](../examples/plugins) |
| Know what you trust | [Security](../SECURITY.md) |
