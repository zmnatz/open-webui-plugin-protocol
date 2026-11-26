# Getting started

From an empty repository to a plugin running in Open-WebUI, deployed from git. It takes about fifteen minutes. You need [uv](install.md#requirements) and `git`.

## 1. A repository for your plugins

```sh
mkdir my-plugins && cd my-plugins && git init
```

Plugins live in `plugins/`, one folder each. Nothing else is needed: `owpp` creates the folder.

## 2. Create a plugin

```sh
uvx owpp create
```

A [wizard](creating.md) asks what the plugin is, one stage at a time, and writes `plugins/<id>/`: the manifest, stubs for the code, tests, a README and a CHANGELOG. Every question has a default, so pressing Enter all the way gives you a small event plugin. Nothing is written until the last stage.

```
plugins/hello/
  plugin.yaml          the manifest: the function's header, its tool, skills and libraries
  function.py          the function, with every hook a stub to fill in
  tests/test_hello.py  tests that pass against a mock Open-WebUI
  README.md            what it does, and how to test and deploy it
  CHANGELOG.md         one entry per version
```

Already have functions pasted into Open-WebUI? See [adopting](adopting.md) to move them into this layout.

## 3. Check and test it

```sh
uvx owpp check --strict                    # bundle it exactly as a deploy would, compile, lint
uvx --from 'owpp[test]' owpp test          # its tests, against a mock Open-WebUI
uvx owpp bundle hello                      # print the single file Open-WebUI will store
```

Now write the plugin itself: the [authoring guide](authoring.md) has the conventions, and [libraries](libraries.md) has routes, jobs, per-chat data, pages and the rest. Run `check` and `test` as you go.

## 4. Connect to Open-WebUI

The deploy talks to Open-WebUI's admin API as an admin. Give it the URL, and one way to sign in:

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

With none of them, it tries to sign in without credentials, which works where sign-in is switched off or a proxy adds the trusted email header. See [signing in](commands/deploy.md#signing-in), and each variable in [environment variables](environment-variables.md). Use a dedicated admin account for deploys if you can, and keep credentials out of git: environment variables here, secrets in CI.

## 5. Deploy

```sh
uvx owpp deploy --dry-run       # what would change, with versions; writes nothing
uvx owpp deploy                 # create or update the functions
```

The deploy creates each function, activates it, and makes a new filter global. It only ever updates or deletes functions it deployed itself (it marks them), never ones made by hand. Then in Open-WebUI, under **Admin Panel > Functions**, your plugin is listed. Its README says what to check by hand.

## 6. Deploy from CI

Commit the repository, add the credential as a secret (here a secret named `OPEN_WEBUI_API_KEY` for the `api-key` input; or `username` and `password`, or `oidc-token`; the inputs set the [environment variables](environment-variables.md#signing-in) of step 4), and deploy on every push to `main`:

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
      - uses: zmnatz/open-webui-plugin-protocol@v0.6.3
        with:
          url: https://chat.example.com
          api-key: ${{ secrets.OPEN_WEBUI_API_KEY }}
```

The action runs `owpp check`, then deploys, and writes the report to the job summary. See [tooling](tooling.md#github-action) for its inputs.

## 7. Change it

Every change is a new version:

```sh
uvx owpp version hello minor -m "Says hello in French too."   # plugin.yaml and CHANGELOG.md
uvx owpp check --since origin/main                             # fails on a change without a new version
```

A deploy refuses to put an older version over a newer one on the instance, unless given `--force`. See [deploying an older version](commands/deploy.md#deploying-an-older-version).

For a plugin that takes its code from another repository, pinned to a commit, `owpp pull` moves it to the latest commit for you to review, and `owpp deploy --dry-run --latest` shows what that upgrade would change on the instance. See [`owpp pull`](commands/pull.md).

## Where next

| To | Read |
| --- | --- |
| Pick the right kind of plugin, and see every option the wizard has | [Creating a plugin](creating.md) |
| Write it well: conventions and a checklist | [Authoring a plugin](authoring.md) |
| Know every key of `plugin.yaml` | [Plugin format](plugin-format.md) |
| See working plugins | [Examples](../examples/plugins) |
| Know what you are trusting | [Security](../SECURITY.md) |
