# In CI

Check and test every pull request, so a change that breaks a plugin, or one with no new version, never reaches the deploy:

```yaml
# .github/workflows/plugins.yml in your repository
on:
  pull_request:
    paths: ["plugins/**"]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0 # --since needs the branch it compares with
      - uses: astral-sh/setup-uv@v6
      - run: uvx owpp@0.7.1 check --strict
      - run: uvx --from 'owpp[test]==0.7.1' owpp test
      - run: uvx owpp@0.7.1 check --since origin/${{ github.base_ref }}
```

| Step | Fails when |
| --- | --- |
| [`owpp check --strict`](../commands/check.md) | A bundle does not build or compile, a name is undefined, a manifest is wrong, or anything warns. |
| [`owpp test`](../commands/test.md) | A plugin's tests fail against the mock. A plugin with code from git fetches it, so the job needs the network (or the tests [load stand-ins](kinds.md#code-from-git)). |
| [`owpp check --since`](../commands/check.md#a-change-needs-a-new-version) | A plugin changed but its version did not; it names the `owpp version` command to run. |

Pin the same owpp version here as in the deploy (`uses: zmnatz/open-webui-plugin-protocol@v0.7.1`), so the tests bundle what the deploy will. The [GitHub Action](../tooling.md#github-action) runs `owpp check` before it deploys, but not the tests.

## A live check

The mock is not Open-WebUI. [`owpp live`](../commands/live.md) starts a throwaway Open-WebUI in Docker (the `-slim` image, `ghcr.io/open-webui/open-webui:v0.13.5-slim`: it leaves out the bundled ML models, which a test has no use for), with [aimock](live.md#the-model-aimock) as its models, deploys the plugins and runs the repository's [live tests](live.md#live-tests-in-your-repository), which catch what the mock cannot. GitHub's runners have Docker:

```yaml
# .github/workflows/live.yml in your repository
on:
  pull_request:
    paths: ["plugins/**", "live/**"]
jobs:
  live:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uvx --from 'owpp[live]==0.7.1' playwright install --with-deps chromium # for tests in the browser
      - run: uvx --from 'owpp[live]==0.7.1' owpp live
```

Pin owpp at the same version as elsewhere. The images come to about 290 MB. This repository's [live suite](live.md#this-repositorys-live-suite) runs the same way in about the time of the unit tests, with the images cached between runs with `actions/cache`, keyed on the compose files (`.github/workflows/live.yml`).
