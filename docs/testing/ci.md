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
      - run: uvx owpp@0.3.1 check --strict
      - run: uvx --from 'owpp[test]==0.3.1' owpp test
      - run: uvx owpp@0.3.1 check --since origin/${{ github.base_ref }}
```

| Step | Fails when |
| --- | --- |
| [`owpp check --strict`](../commands/check.md) | A bundle does not build or compile, a name is undefined, a manifest is wrong, or anything warns. |
| [`owpp test`](../commands/test.md) | A plugin's tests fail against the mock. A plugin with code from git fetches it, so the job needs the network (or the tests [load stand-ins](kinds.md#code-from-git)). |
| [`owpp check --since`](../commands/check.md#a-change-needs-a-new-version) | A plugin changed but its version did not; it names the `owpp version` command to run. |

Pin the same owpp version here as in the deploy (`uses: zmnatz/open-webui-plugin-protocol@v0.3.1`), so the tests bundle what the deploy will. The [GitHub Action](../tooling.md#github-action) runs `owpp check` before it deploys, but not the tests.

## A live check

The mock is not Open-WebUI. A job that starts Open-WebUI in Docker (the `-slim` image, `ghcr.io/open-webui/open-webui:v0.13.4-slim`: it leaves out the bundled ML models, which a test has no use for), with [aimock](live.md#the-model-aimock) as its models, deploys with `owpp deploy` and runs a few assertions over its API catches what the mock cannot; this repository's [live suite](live.md#the-live-suite) is one. It runs on every pull request in about the time of the unit tests: the images come to about 290 MB, cached between runs with `actions/cache` keyed on the compose file (`.github/workflows/live.yml`).
