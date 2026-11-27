# Changelog

## Unreleased

- **Breaking:** `owpp test` runs each plugin against the real Open-WebUI v0.13.5, in the test process, in place of the mock ([the test harness](docs/testing/harness.md), [ADR 0004](docs/adr/0004-unit-tests-run-the-real-open-webui.md), [#126](https://github.com/zmnatz/open-webui-plugin-protocol/issues/126)). owpp now runs on Python 3.12, the Python of that Open-WebUI. `owpp test -- -n auto` runs the tests in parallel, and `@pytest.mark.fresh_open_webui` (or `OWPP_FRESH_OPEN_WEBUI=1`) gives a test a new Open-WebUI. The `test` extra installs Open-WebUI's slim packages at its versions, and the first run downloads Open-WebUI's code to `OWPP_CACHE_DIR`. `MockOpenWebUI`, `Record` and the `open_webui` type stubs are gone: `Harness` takes their place, `grants(row)` reads access grants, `owui.set_tool_valves()` saves a tool's valves, the model is aimock (run with Bun, Node or Docker, whichever is installed; `owui.serve_model()` adds model ids), and `owpp test --editor` gives the folder an editor needs. The rows of `owui.tools`, `owui.models` and the other tables are copies now. [Upgrading](docs/upgrading.md#07-08) lists what a test may need to change.

## 0.7.2 (2026-11-27)

- The documentation site now uses Simplified Technical English: short active sentences, numbered steps, and one full explanation of each thing ([#123](https://github.com/zmnatz/open-webui-plugin-protocol/pull/123)).
- `AGENTS.md` and the contributing guide now give the same writing rules for new docs ([#122](https://github.com/zmnatz/open-webui-plugin-protocol/pull/122)).
- The mock Open-WebUI stores a function as a deploy leaves it: the deploy's `meta` (`managed_by`, the description with its note, `sources`, `requires`) beside `manifest`, and the code with its imports rewritten as Open-WebUI rewrites them; its `replace_imports` rewrites them too. A test that expects `meta.description` to be the header's alone reads `meta.manifest["description"]` instead ([the mock](docs/testing/harness.md)).

## 0.7.1 (2026-11-27)

- `owpp check` finds undefined names scope by scope, as Python does: a name defined only inside another function or class is now reported, and names bound by `match` patterns no longer are.
- `MockOpenWebUI(sources=...)` takes the `Sources` it reads a `source:` plugin's files through. The `owui` fixture still fetches each file once per test run; a mock you make yourself without one now fetches for itself rather than sharing with the run ([the mock](docs/testing/harness.md)).
- `owpp import` writes only the `jobs:` settings that differ from their defaults, as it already did for `static:` and `assets:` ([owpp import](docs/commands/import.md), [#97](https://github.com/zmnatz/open-webui-plugin-protocol/issues/97)).
- `owpp import --instance` takes `--ca-cert`, `--client-cert` and `--client-key`, as `owpp deploy` does ([owpp import](docs/commands/import.md), [#96](https://github.com/zmnatz/open-webui-plugin-protocol/issues/96)).

## 0.7.0 (2026-11-27)

The headline is **live tests**: a plugins repository tests its plugins on a real, throwaway Open-WebUI, over its API and in the browser, with one command, and an agent can write those tests for a plugin that already works.

- **Live tests in your repository: `owpp live`** ([owpp live](docs/commands/live.md), [#84](https://github.com/zmnatz/open-webui-plugin-protocol/issues/84), [ADR 0003](docs/adr/0003-owpp-live-in-owpp.md)). It starts a throwaway Open-WebUI v0.13.5 in Docker with aimock as its models, deploys the plugins, runs the repository's live tests in `live/` and removes it all again; `--up` leaves it running to try things. A `live/compose.yaml` is layered on owpp's stack for a repository's own services and settings, and `live/aimock/` holds what the model answers. Its pytest fixtures: `api`, `user_api`, `aimock` (what Open-WebUI sent the model), and Playwright pages signed in as the admin and a user, or signed out ([live tests in your repository](docs/testing/live.md#live-tests-in-your-repository)). Run it as `uvx owpp live`, or `uvx --from 'owpp[live]' owpp live` for tests in the browser (the `live` extra adds Playwright).
- **`owpp import`** makes a plugin folder from code that already exists ([owpp import](docs/commands/import.md), [#82](https://github.com/zmnatz/open-webui-plugin-protocol/issues/82)). From a git repository (a GitHub or GitLab page of a folder or file, or a clone URL), it finds the function, the tool and the skills in the folder, or takes a whole owpp plugin, and pins them at the branch's current commit, never copying them. From a `.py` file, or a function on Open-WebUI (`--instance <id>`, signed in as the deploy is), it moves the docstring header into `plugin.yaml`, so the bundle is the same code again. What owpp put into a function it deployed comes back out as what it was made from (`include:`, `templates/`, `config.yaml`, the tool and the skills, and `requires:`, which the deploy now records in `meta.requires`), and so do the Shared Assets Protocol's blocks when they are byte-identical to owpp's copy ([what owpp put into it](docs/commands/import.md#what-owpp-put-into-it-taken-back-out)). It then runs `owpp check`. This is how a function written for Open-WebUI is now tested as it is ([#52](https://github.com/zmnatz/open-webui-plugin-protocol/issues/52)).
- **A second agent skill,** [`test-existing-plugin`](skills/test-existing-plugin/SKILL.md): tests for a function or plugin that already works, against the mock, with what looks wrong reported rather than fixed, its live tests with `owpp live`, and in this repository its screenshots ([with an AI agent](docs/ai-agents.md#the-test-existing-plugin-skill)).
- [A plugin that already works](docs/testing/existing-plugins.md): the `test-existing-plugin` skill tried on Classic298's Better Banners and on the Excalidraw example, with bugs planted in each to see what the tests catch (14 of 16, 16 of 19). Both are in [`examples/existing-plugins/`](examples/existing-plugins/), runnable. The skill now asks for a test of hostile markup in every field a plugin shows, and for valve values no constant in the code has.
- **Protocol 0.7**, to match the release: no key changes, so a 0.5 manifest means the same and `owpp migrate` only records the number. owpp 0.6 refuses a 0.7 manifest, so move every pin before migrating ([upgrading](docs/upgrading.md#06-07)).
- The live suite runs on `owpp live`, and drives Open-WebUI's chat page with Playwright too ([tests in the browser](docs/testing/live.md#tests-in-the-browser)). Its first browser test shows the chat page running the tool a model calls, which the API hands back instead.
- [Excalidraw](examples/plugins/excalidraw) 3.1.1: its scene API no longer sends `Access-Control-Allow-Origin: *`, and the editor saves as JSON instead of the text/plain that only avoided a CORS preflight. Both were for an editor running at another origin, but it needs iframe Sandbox Allow Same Origin and so runs at Open-WebUI's own; found by the experiment above. Its test of `SESSION_TOKEN_HOURS` sets 2 hours, not 1, so code that ignored the valve for a fixed hour fails it.
- `owui.load()` refuses a loose `<id>.py` with the `owpp import` that makes a plugin of it, instead of `NotADirectoryError`.
- Fixed: the `open_webui` stubs no longer depend on the Python that writes them (3.15's `json.loads` has an `array_hook`).

## 0.6.3 (2026-11-26)

- Docs: the published docs site counts visits with Google Analytics.
- Docs: each example's page has a **Get the built function** button: a popup with the one file `owpp deploy` stores, a copy button, and a link to the file, an address Open-WebUI's **Import from URL** takes (`.../examples/downloads/<id>.py` on the docs site, as of the latest release).

## 0.6.2 (2026-11-25)

- Open-WebUI v0.13.5: the live suite and the screenshots run on it (`ghcr.io/open-webui/open-webui:v0.13.5-slim`), every example passes there, and the screenshots are retaken. The screenshot scripts type a message with `send()`, which checks the chat input holds all of it: v0.13.5's input takes typing while it loads and can lose what was typed.
- [`theme_designer_pro`](examples/plugins/theme_designer_pro) follows upstream Theme Designer Pro 1.23.0 (commit `34345ea`): its palette sets Open-WebUI v0.13.5's base colours and steps aside for a user's own; the Surfaces tab replaces the Sidebar Transparency and Overlay Transparency valves; Allow Personal Themes and Auto Sync start on. On top of it, one change for v0.13.5, which dropped Open-WebUI's own OLED Dark theme: the designer's OLED mode is kept under a key of its own, so it lasts past the next page load. The change is `adapt/open-webui-0.13.5.patch`, for the next copy taken from upstream ([what changed for v0.13.5](examples/plugins/theme_designer_pro/README.md#what-changed-for-open-webui-v0135)).

## 0.6.1 (2026-11-22)

- Fixed: the `assets` library fills `asset_vars()` placeholders in one pass, so a value that holds another placeholder's text (a valve someone typed) is served as written instead of being filled again ([#69](https://github.com/zmnatz/open-webui-plugin-protocol/issues/69), [libraries](docs/libraries.md#assets)).
- Fixed: `owpp check` and the bundler refuse a function that changes the app's route list itself (`app.routes.insert(...)`, `app.routes[:] = ...`, `del app.routes[0]`, ...), which added routes past the sign-in guard as surely as `include_router` ([#68](https://github.com/zmnatz/open-webui-plugin-protocol/issues/68), [libraries](docs/libraries.md#routes)).
- Docs: Theme Designer Pro is in the Examples menu, and the docs build fails on an example the menu leaves out.

## 0.6.0 (2026-11-22)

- A tool embeds only the templates it lists, with `tool: templates: [launcher/]`, so a function's large page is not copied into its tool ([plugin format](docs/plugin-format.md#tool)).
- The mock sends events about users and models (`owui.emit("user.deleted", {"type": "user", "id": ...})`), has `decode_token`, and answers a plugin that asks a model itself: `owui.model_reply`, with what it was asked in `owui.completions` ([the mock](docs/testing/harness.md)).
- A new example, [`theme_designer_pro`](examples/plugins/theme_designer_pro), adapted from G30's Theme Designer Pro: a 1.3 MB event function broken into templates, routes behind the sign-in guard, `@on` handlers, a tool and a skill, with what changed explained for its author.

## 0.5.0 (2026-11-22)

- Protocol 0.5: a plugin's files import what they use, and the bundler refuses one that does not. `owpp migrate` writes the imports into a 0.3 plugin; a plugin taking 0.3-style code from git is refused until `owpp pull` moves it to a migrated commit ([upgrading](docs/upgrading.md#04-05)).
- A plugin's files are ordinary Python: each imports what it uses, including its shared code (`from shared import NAME`) and the libraries (`from owpp.lib import PluginAdmin, plugin_mount`), so it reads, lints and type-checks on its own. The bundler removes those imports, says which library a name needs in `include:`, and refuses the forms that would break once bundled ([bundling](docs/bundling.md#imports-between-the-files)).
- `owpp create` writes plugins that import the library names they use.
- `{{file:NAME}}` is deprecated, and `owpp check` warns about it: use `templates/` and `plugin_template_text()`. A tool can now read the templates too, with `include: [templates]` under `tool:`; `owpp create` writes a rich-UI tool that way.
- owpp ships type stubs for `open_webui`, written from the mock, so an editor resolves what a plugin imports from Open-WebUI ([the mock](docs/testing/harness.md)).
- `owpp.testing.plugin_source(path)` imports a plugin's files as modules for tests of their logic, each plugin with its own `shared.py` and libraries ([writing a test](docs/testing/writing.md#testing-logic-directly)).
- `owpp check` warns about a plugin name that replaces a library name in its bundle, and about `from __future__` lines that differ between `shared.py` and the files it goes in front of.
- The runtime's `_plugin_ensure()` is now `plugin_ensure()`, imported from `owpp.lib`.
- `include: [static]` brings in `routes`, which it mounts its files with.

## 0.4.1 (2026-11-21)

- Project: releases follow gitflow. Changes merge into `develop`; a release is started from the Actions tab, and merging it into `main` tags it, publishes it and merges `main` back into `develop`. `main` and the docs site are now always the latest release ([contributing](docs/contributing.md#releasing)).

## 0.4.0 (2026-11-21)

- The live suite deploys the examples to a real Open-WebUI v0.13.4 (`-slim`), with [aimock](https://github.com/CopilotKit/aimock) as its models, and checks what the mock cannot, on every pull request ([the live suite](docs/testing/live.md#this-repositorys-live-suite)).
- `tools/screenshots/run.py --up` starts the same Open-WebUI and leaves it running, to try a plugin by hand with no real model and nothing leaving the machine ([trying things out in isolation](docs/testing/live.md#trying-things-out)).
- The mock passes filters `__model__` (`plugin.inlet(..., model=)`, default `"mock-model"`) and has `open_webui.utils.misc.get_last_user_message_item` ([the mock](docs/testing/harness.md)).
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
