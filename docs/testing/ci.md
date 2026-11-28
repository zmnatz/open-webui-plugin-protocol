# In CI

Check and test every pull request. Then a change that breaks a plugin, or that has no new version, does not reach the deploy:

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
      - uses: actions/cache@v4 # the Open-WebUI code that the tests run
        with:
          path: ~/.cache/owpp
          key: owpp-open-webui-v0.13.5
      - uses: actions/cache@v4 # the pinned files from git
        with:
          path: .owpp/store
          key: owpp-store-${{ hashFiles('plugins/**/plugin.yaml') }}
      - run: uvx owpp@0.7.2 check --strict
      - run: uvx --python 3.12 --from 'owpp[test]==0.7.2' owpp test
      - run: uvx owpp@0.7.2 check --since origin/${{ github.base_ref }}
```

| Step | Fails when |
| --- | --- |
| [`owpp check --strict`](../commands/check.md) | A bundle fails or does not compile, a name is undefined, a manifest is wrong, or there is a warning. |
| [`owpp test`](../commands/test.md) | The tests of a plugin fail on the [test harness](harness.md). A test that asks a model runs [aimock](harness.md#the-model-aimock) with Node or Docker, which GitHub's runners have. A plugin with code from git needs that code. The job needs the network unless [the cache](#caching-the-git-sources) holds it. Tests that [load stand-ins](kinds.md#code-from-git) need neither. |
| [`owpp check --since`](../commands/check.md#a-change-needs-a-new-version) | A plugin changed, but its version did not. The message names the `owpp version` command to run. |

Pin the same owpp version here as in the deploy (`uses: zmnatz/open-webui-plugin-protocol@v0.7.2`). Then the tests use the same bundle as the deploy. The [GitHub Action](../tooling.md#github-action) runs `owpp check` before it deploys, but it does not run the tests.

## Caching the git sources

The second cache in the example keeps [`.owpp/store/`](../bundling.md#the-owpp-folder). Then a run fetches from git only after a pin changes. Cache `store/` only, because owpp writes `modules/` again from it.

The [GitHub Action](../tooling.md#github-action) keeps the same cache with `cache: "true"`. It is off by default.

**Caution:** A deploy trusts the files in this cache. Any workflow of your repository can write the cache, and owpp cannot tell if the files came from git. Turn the cache on for a deploy only when you trust each workflow. This includes the code that each workflow runs, for example [upstream tests](../commands/test.md#upstream-tests).

## A live check

The test harness runs Open-WebUI's code, with aimock as its model, but not a real model or a browser ([what the harness fakes](harness.md#what-the-harness-fakes)). A second workflow can run your [live tests](live.md#live-tests-in-your-repository) with [`owpp live`](../commands/live.md), which finds the problems that only these show. GitHub's runners have Docker:

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
      - run: uvx --from 'owpp[live]==0.7.2' playwright install --with-deps chromium # for tests in the browser
      - run: uvx --from 'owpp[live]==0.7.2' owpp live
```

Pin the same owpp version as in the other workflows.

The Open-WebUI image is the `-slim` one (`ghcr.io/open-webui/open-webui:v0.13.5-slim`). It does not include the ML models of the full image, which a test does not need. The images are about 290 MB in total.

This repository's [live suite](live.md#this-repositorys-live-suite) runs in the same way. It takes about as long as the unit tests, because `actions/cache` keeps the images between runs. The cache key comes from the compose files (`.github/workflows/live.yml`).
