# Open-WebUI plugin protocol

Write, test and deploy [Open-WebUI](https://github.com/open-webui/open-webui) plugins from a git repository.

A **plugin** is a folder: a function (the parent), plus an optional tool and skills that are installed when the function is enabled and removed when it is disabled. Shared libraries cover what every plugin ends up re-implementing: HTTP routes that survive reloads, scheduled jobs that run on one worker, data stored with a chat, static files. A CLI (`owpp`) checks, bundles and deploys them, from a laptop or a GitHub Action.

```
plugins/excalidraw/
  plugin.yaml          function + tool + libraries, in one manifest
  function.py          class Filter: serves the editor, adds it to replies
  tool.py              class Tools: lets the model read and change the drawing
  shared.py            code both need
  templates/viewer.html   the page, kept out of Python strings
  README.md            what it is, how to test it, how to deploy it
```

```yaml
# plugin.yaml
protocol: "0.2"
function:
  title: Excalidraw
  version: 3.1.0
  global: true
tool:
  id: excalidraw
  include: [chat_data]
  access: public
include: [routes, chat_data]
```

```sh
uvx owpp list
#  excalidraw              filter (global)
#  mcpo_sync               event
uvx owpp check                       # bundle, compile, report undefined names
uvx owpp version                     # every plugin's versions (and its tool's and skills')
uvx owpp version excalidraw minor    # a new version, with a CHANGELOG.md entry
uvx --from 'owpp[test]' owpp test    # each plugin's tests/, against a mock Open-WebUI
uvx owpp deploy --only excalidraw --dry-run
uvx owpp pull                        # move plugins taken from git to their latest commit, for review
uvx owpp deploy --dry-run --latest     # what that would change on the live instance, by version
```

## Why

Open-WebUI stores each function and tool as **one code blob**, edited in the admin UI. That makes it hard to review changes, share code between plugins, keep a tool in step with the function it belongs to, or pin third-party code. This project:

- **bundles a folder into the single file Open-WebUI stores**, in a fixed order, with vendored libraries and code pulled from any git repo at a pinned commit;
- **makes the function the parent**: its tool and skills come and go with it;
- **deploys from git**, updating only what it created (an ownership marker), never hand-made functions.

## Install

Requires [uv](https://docs.astral.sh/uv/) (it brings its own Python) and `git` (for remote sources). Nothing to install: `uvx` runs `owpp` straight from PyPI. To have it on your `PATH`, `uv tool install owpp` (or `pipx install owpp`). See [install](docs/install.md) and [getting started](docs/getting-started.md).

```sh
uvx owpp create                      # a wizard: asks what the plugin is, writes plugins/<id>/
uvx owpp check
OPEN_WEBUI_URL=https://chat.example.com OPEN_WEBUI_API_KEY=sk-... uvx owpp deploy --dry-run
# or OPEN_WEBUI_USERNAME + OPEN_WEBUI_PASSWORD, OPEN_WEBUI_OIDC_TOKEN, or nothing: docs/commands/deploy.md#signing-in
```

## Deploy from GitHub Actions

```yaml
- uses: actions/checkout@v5
- uses: zmnatz/open-webui-plugin-protocol@v0.2.1
  with:
    url: https://chat.example.com
    api-key: ${{ secrets.OPEN_WEBUI_API_KEY }}
    plugins-dir: plugins
```

## Documentation

Published at **https://zmnatz.github.io/open-webui-plugin-protocol/**, built from `docs/` (`uv run --group docs python tools/build_docs.py serve` to preview it).

| | |
| --- | --- |
| [Install](docs/install.md) | requirements, uvx, pinning, the test extra |
| [Getting started](docs/getting-started.md) | from an empty repository to a plugin deployed from CI |
| [With an AI agent](docs/ai-agents.md) | the owpp agent skill, `owpp create --spec`, llms.txt |
| [Overview](docs/README.md) | concepts, guarantees, status |
| [Creating a plugin](docs/creating.md) | the `owpp create` wizard: code written here, installers, plugins from git |
| [Authoring guide](docs/authoring.md) | function types, conventions, checklist |
| [Plugin format](docs/plugin-format.md) | `plugin.yaml` reference |
| [Bundling](docs/bundling.md) | exactly what gets deployed; git sources |
| [Runtime](docs/runtime.md) | install/remove of tools and skills, parent valves |
| [Libraries](docs/libraries.md) | `core`, `routes`, `jobs`, `events`, `chat_data`, `static`, `templates`, `assets`, Shared Assets |
| [Testing](docs/testing.md) | unit tests per plugin, the mock Open-WebUI, `owpp test` |
| [Tooling](docs/tooling.md) | the CLI, a page per command (deploy settings, signing in, `pull`, versions), GitHub Action, tests |
| [Adopting](docs/adopting.md) | new repositories, migrating existing functions |
| [Upgrading](docs/upgrading.md) | moving to a new owpp, `owpp migrate`, what changed in 0.2 |
| [Security](SECURITY.md) | the trust model, what `owpp` limits, known limits, how to report |

## Examples

[`examples/plugins/`](examples/plugins): `excalidraw` (filter + tool + page), `mcpo_sync` (scheduled event), `stale_data` (admin dashboard), `inline_visualizer` (third-party tool and skill from a pinned commit), `page_banners` (a variant of Better Banners: its script and stylesheet are files in `assets/`), `litellm_model_sync` (scheduled event that writes Open-WebUI's model configs from a LiteLLM gateway).

## Status

0.2.1, written against Open-WebUI v0.13.4. The bundler, runtime and libraries are tested against stubbed Open-WebUI modules, and each example plugin has unit tests run against a mock Open-WebUI (`owpp test`). The examples have been deployed and photographed on a real Open-WebUI v0.13.4 ([screenshots](docs/screenshots.md)), but that run is started by hand, not part of CI. See [status and limits](docs/README.md#status-and-limits).

## Development

```sh
uv sync
uv run pytest                        # owpp's tests and every example plugin's tests/
uv run owpp test --dir examples/plugins
uv run ruff check . && uv run ruff format --check .
uv run owpp check --dir examples/plugins
```

## Licence

MIT ([LICENSE](LICENSE)). Vendored third-party code (Classic298's Shared Assets Protocol, BSD-3-Clause): [NOTICE.md](NOTICE.md).

This project contains no Open WebUI code: it talks to Open WebUI's API and produces plugins that run inside it. It is an independent project, **not affiliated with or endorsed by Open WebUI Inc.**; "Open WebUI" is used only to say what it works with. Open WebUI itself is under the [Open WebUI License](https://github.com/open-webui/open-webui/blob/main/LICENSE).
