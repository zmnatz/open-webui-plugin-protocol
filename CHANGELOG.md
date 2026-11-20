# Changelog

## Unreleased

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
