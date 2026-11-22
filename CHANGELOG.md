# Changelog

## Unreleased

- Protocol 0.5: a plugin's files import what they use, and the bundler refuses one that does not. `owpp migrate` writes the imports into a 0.3 plugin; a plugin taking 0.3-style code from git is refused until `owpp pull` moves it to a migrated commit ([upgrading](docs/upgrading.md#04-05)).
- A plugin's files are ordinary Python: each imports what it uses, including its shared code (`from shared import NAME`) and the libraries (`from owpp.lib import PluginAdmin, plugin_mount`), so it reads, lints and type-checks on its own. The bundler removes those imports, says which library a name needs in `include:`, and refuses the forms that would break once bundled ([bundling](docs/bundling.md#imports-between-the-files)).
- `owpp create` writes plugins that import the library names they use.
- `{{file:NAME}}` is deprecated, and `owpp check` warns about it: use `templates/` and `plugin_template_text()`. A tool can now read the templates too, with `include: [templates]` under `tool:`; `owpp create` writes a rich-UI tool that way.
- owpp ships type stubs for `open_webui`, written from the mock, so an editor resolves what a plugin imports from Open-WebUI ([the mock](docs/testing/mock.md#in-an-editor)).
- `owpp.testing.plugin_source(path)` imports a plugin's files as modules for tests of their logic, each plugin with its own `shared.py` and libraries ([writing a test](docs/testing/writing.md#testing-logic-directly)).
- `owpp check` warns about a plugin name that replaces a library name in its bundle, and about `from __future__` lines that differ between `shared.py` and the files it goes in front of.
- The runtime's `_plugin_ensure()` is now `plugin_ensure()`, imported from `owpp.lib`.
- `include: [static]` brings in `routes`, which it mounts its files with.

## 0.4.1 (2026-11-21)

- Project: releases follow gitflow. Changes merge into `develop`; a release is started from the Actions tab, and merging it into `main` tags it, publishes it and merges `main` back into `develop`. `main` and the docs site are now always the latest release ([contributing](docs/contributing.md#releasing)).

## 0.4.0 (2026-11-21)

- The live suite deploys the examples to a real Open-WebUI v0.13.4 (`-slim`), with [aimock](https://github.com/CopilotKit/aimock) as its models, and checks what the mock cannot, on every pull request ([the live suite](docs/testing/live.md#the-live-suite)).
- `tools/screenshots/run.py --up` starts the same Open-WebUI and leaves it running, to try a plugin by hand with no real model and nothing leaving the machine ([trying things out in isolation](docs/testing/live.md#trying-things-out-in-isolation)).
- The mock passes filters `__model__` (`plugin.inlet(..., model=)`, default `"mock-model"`) and has `open_webui.utils.misc.get_last_user_message_item` ([the mock](docs/testing/mock.md)).
- Two filter examples: [`clear_thinking_tags`](examples/plugins/clear_thinking_tags), an outlet adapted from Haervwe's Clear thinking tags, and [`vision_router`](examples/plugins/vision_router), an inlet adapted from open-webui's Dynamic Vision Router.
- Docs: a Testing section (writing a test, recipes for each kind of plugin, the mock, a real Open-WebUI, CI), and the owpp agent skill's [testing steps](skills/owpp/references/testing.md).
- Manifests stay `protocol: "0.3"`, and bundles are the same as 0.3.1's: nothing to migrate ([upgrading](docs/upgrading.md#03-04)).

## 0.3.1 (2026-11-20)

- `owpp build` bundles the plugins into a folder that `owpp deploy --from` deploys elsewhere, with no checkout or git sources ([`owpp build`](docs/commands/build.md)).
- `owpp deploy --no-prune` (the action's `no-prune`) deploys every plugin and deletes nothing.
- Docs: the home page's reading order is a short "Where to start" table.
- Python API (breaking): `owpp.deploy.Options` is gone, split into `Instance` (the instance URL, credentials and TLS) and `Choices` (what to deploy); use `instance_from_env()`/`choices_from_env()` instead of `options_from_env()`, and pass the new inputs to `plugins_for()`, `deploy()`, `iframe_sandbox_warning()` and `run_deploy()` — the CLI and the GitHub Action are unchanged.

## 0.3.0 (2026-11-20)

- Protocol 0.3: `source: track:` is now `branch:` or `tag:`, which `owpp migrate` rewrites by asking the repository ([upgrading](docs/upgrading.md)).
- `owpp sync` is now `owpp pull`, and deploy's `--sync` (the action's `sync` input) is now `--latest` (`latest`) ([upgrading](docs/upgrading.md)).
- Docs: a page for each command, an [environment variables](docs/environment-variables.md) reference, [troubleshooting](docs/troubleshooting.md) and [FAQ](docs/faq.md) pages, a "Why this" section on the home page, and changelog, contributing and license pages under Project.

## 0.2.1 (2026-11-19)

- `source: {plugin: true}` takes a whole owpp plugin folder from git, such as one of the examples, and bundles it with the owpp reading it ([a whole plugin from git](docs/plugin-format.md#a-whole-plugin-from-git)).
- `ref:` can be left out of a `source:` until `owpp sync` adds it; `owpp check` and `owpp deploy` refuse an unpinned source.
- `owpp test --upstream` also runs the tests of plugins taken whole from git, with the `OPEN_WEBUI_*` variables removed.
- Docs: an [upgrading](docs/upgrading.md) page, and one-sentence changelog entries.

## 0.2.0 (2026-11-19)

- `plugin.yaml` declares its format version with `protocol: "0.2"`; newer versions are refused, and a missing key is read as 0.1 with a warning.
- `owpp migrate [id ...] [--dry-run]` brings manifests up to the current protocol, keeping comments and layout.
- Fixed: saving a parent function's valves (`INSTALL_TOOLS`, `INSTALL_SKILLS`, `TOOL_VALVES`) now applies them right away.
- `requires: {iframe_sandbox_allow_same_origin: true}` makes `owpp deploy` warn when the instance is missing that setting.
- `owpp create [id]` is a wizard that scaffolds any kind of plugin, local or from a pinned git `source:`, with tests and a README.
- `owpp sync [id ...] [--dry-run]` moves a git-sourced plugin's pinned commit to the latest on its branch (`source: track:`) and lists the files that changed.
- `owpp deploy` reports version changes for each function, tool and skill, and records a git-sourced plugin's commit in the function's meta.
- `owpp version` lists and bumps plugin versions with a `CHANGELOG.md` entry, and `owpp check --since <ref>` fails on changes with no new version.
- `owpp deploy` refuses to go back a version unless given `--force`.
- Docs: new Install and Getting started pages.
- Docs: the audit trail and decisions pages are gone, and their known limits moved to [status and limits](docs/README.md#status-and-limits).
- `owpp deploy` can sign in with a username and password, an OIDC token or trusted headers instead of an API key.
- For AI agents: an [`owpp` agent skill](skills/owpp/SKILL.md), `owpp create --spec <file>`, and `llms.txt` on the docs site.
- `owpp deploy` takes CA and client TLS certificates (`--ca-cert`, `--client-cert`, `--client-key`).
- `owpp init` now writes what `owpp create` writes with every answer left at its default.
- Fixed: `owpp check` no longer reports a name as undefined when it is only used after `"name" in globals()`.

## 0.1.0 (2026-11-19)

The first standalone release, extracted from a working deployment and published to [PyPI](https://pypi.org/project/owpp/) as `owpp`.

- Plugin folders with a `plugin.yaml` manifest: a parent function plus an optional tool and skills.
- A bundler that turns a plugin folder into one file per function and tool, with git sources pinned by full SHA.
- A runtime with which the function installs, updates and removes its tool and skills.
- Libraries: `assets`, `config`, `core`, `routes`, `jobs`, `chat_data`, `static`, `templates` and the vendored Shared Assets Protocol.
- A `jobs:` manifest section for scheduled syncs, with their interval declared in `plugin.yaml`.
- `${NAME:-default}` environment templates in `jobs:` and `config.yaml`, resolved when the plugin loads, never when bundling.
- `plugin_token` / `plugin_check_token`: signed, expiring tokens for routes that cannot carry a session.
- A page opened with no session tries the no-input sign-ins, then sends the browser to Open-WebUI's login page.
- `owpp check` warns about undocumented valves and tool methods, and `--strict` fails on warnings.
- `SECURITY.md` describes the trust model and how to report a vulnerability.
- Routes need a signed-in user by default, and `access="public"` opts a single mount out.
- Event handlers by decorator: `@on("event.name")` on a `PluginEvents` class.
- A function's type is read from its top-level class, and `global` applies only to filters and actions.
- The `owpp` CLI with `list`, `check`, `bundle`, `deploy` and `init`.
- A composite GitHub Action that runs `owpp`.
- Excalidraw can load its editor from a host you run (`EXCALIDRAW_ASSETS_URL`).
- `owpp test` runs each plugin's tests against a mock Open-WebUI (`owpp[test]`).
- `owpp init` scaffolds a plugin with a passing test.
- Six example plugins, each with unit tests whose docstrings say how to repeat them by hand.
- A documentation site, published to GitHub Pages.
- Screenshots of the examples on a real Open-WebUI, taken by `tools/screenshots/run.py`.
- Known limitation: the Excalidraw editor needs Open-WebUI's **iframe Sandbox Allow Same Origin** setting (issue #6).
- `access: public` on a tool or skill grants it to every signed-in user.
- `global: false` keeps a per-user toggle filter out of global.
- The mock Open-WebUI fetches a `source:` plugin's pinned files when a test gives no `sources=`.
- `jobs: adopt_markers` lets a sync take over the entries of an earlier sync.
