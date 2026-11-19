# Changelog

## Unreleased

- `owpp test [id ...]`: runs each plugin's `tests/` folder with pytest against a mock Open-WebUI (`owpp.testing.MockOpenWebUI`, `docs/testing.md`). The mock covers the function, tool and skill tables, users and auth, chats in SQLite, config, the socket, event sinks and the FastAPI app. The `owui`, `plugin_dir` and `plugin` pytest fixtures are registered wherever owpp is installed. The extra `owpp[test]` brings pytest and the packages Open-WebUI ships.
- `owpp init` scaffolds a `tests/test_<id>.py` that passes.
- Every example plugin has unit tests in its own `tests/` folder. The example tests that lived in `tests/test_examples.py` moved there.
- Every example plugin test has a docstring: what it checks, then `By hand:` steps to repeat it on a live Open-WebUI. `owpp init` scaffolds tests that do the same, and `tests/test_test_docs.py` enforces it.
- A documentation site (Zensical, `zensical.toml`, built by `tools/build_docs.py`), published to GitHub Pages by `.github/workflows/docs.yml`. It adds pages for review: a test catalogue built from the test docstrings, an audit trail built from `git log`, and how to review and make a change.

- Screenshots on a real Open-WebUI: `tools/screenshots/run.py` starts Open-WebUI v0.13.4, a scripted model and mcpo in Docker, deploys `examples/plugins` with `owpp deploy`, and follows the plugins' By hand steps with Playwright (`docs/screenshots.md`). The screenshots are in `docs/screenshots/`, and the site shows them in the test catalogue, on each example's page and on a page of their own. `.github/workflows/screenshots.yml` takes them on GitHub when run by hand.
- Excalidraw: fixed. With `EXCALIDRAW_ASSETS_URL` unset (the default), the editor never loaded. A comment in `templates/viewer.html` named the block markers, so dropping the self-hosted block also cut out the esm.sh imports (`convertToExcalidrawElements is not defined`). A new test checks that the page's script imports what it uses, in both modes.
- Excalidraw: documented that the editor needs **iframe Sandbox Allow Same Origin** in Open-WebUI. Without it, the sandboxed panel sends no session and the page answers 401. The README also says what turning it on costs. A design that does not need it is issue #6.
- mcpo Sync, Stale Data: the README live checks name the v0.13.4 menus (Admin Settings > Integrations > External Tool Servers), and a signed-out visit to the dashboard goes to the sign-in page, not a 404.

## 0.1.0 (2026-11-18)

First standalone release, extracted from a working deployment.

- Plugin folders with a `plugin.yaml` manifest: a function (the parent) plus an optional tool and skills, `shared.py`, `public/`.
- Bundler: fixed order (header, libraries, `shared.py`, code, runtime), `{{file:}}`, `from __future__` hoisting, git sources pinned by full SHA, skills as whole folders.
- Runtime: the function installs, updates and removes its tool and skills; parent valves `INSTALL_TOOLS`, `INSTALL_SKILLS`, `TOOL_VALVES`.
- Libraries: `assets` (`assets/loader.js` and `assets/custom.css` published through the Shared Assets Protocol, with `class Event(PluginAssets)`), `config` (a `config.yaml` parsed at bundle time), `core`, `routes`, `jobs` (with `PluginScheduledSync`), `chat_data`, `static` (files served as they are), `templates` (files the function renders, never served), and the vendored Shared Assets Protocol.
- The `jobs:` manifest section: the sync mixin adds its `ENABLE` and `SYNC_INTERVAL_MINUTES` valves itself, and the interval's default is declared in `plugin.yaml`.
- Environment templates, `${NAME:-default}`, in `jobs:` and `config.yaml`: embedded as written and resolved from the Open-WebUI container's environment when the plugin loads, never when bundling (so a bundle never depends on the machine that built it). `owpp check` lists the variables a plugin reads.
- `plugin_token` / `plugin_check_token`: signed, expiring tokens scoped to the function, for a route that cannot carry a session. A `plugin_mount` name is the mount's identity, so a moved mount replaces its old self. The events mixin creates `self.valves` itself.
- A page opened with no session is not just refused: the no-input sign-ins (trusted headers, auth off) are tried in-process, then the browser goes to Open-WebUI's login page and back; iframes and API calls get a plain 401.
- `owpp check` warns about a valve with no description and about tool methods with no docstring, type hints or `:param` lines; `--strict` fails on warnings.
- `SECURITY.md`: the trust model, what `owpp` limits, the known limits, how to report.
- Signed in by default, public only on purpose: every route needs a signed-in user, marked on the route, on the mount (`access=`) or, for `static/` files, with `static: {access: user | admin | public}`, and enforced by `plugin_mount`. `access="public"` (exactly that word, per mount) serves people who are not signed in, and `owpp check` notes every one. `static/` and `templates/` replace `public/` and its `dynamic:` list; the old names are refused with a message saying where things went. Unknown top-level keys in `plugin.yaml` are refused. A single route is marked with `user: PluginAdmin` or `user: PluginUser` (tighten only), or by its chat with `chat_id: WritableChat` / `ReadableChat`. `guard=` replaces the check for a sandboxed API. Code that mounts straight onto the app is refused.
- Event handlers by decorator: `@on("event.name", own=True)` on a `PluginEvents` class, with event names checked by `owpp check`. `PluginScheduledSync` and `PluginAssets` are built on it.
- Function types read from the top-level class; `global` only for filters and actions.
- `owpp` CLI (a Python package, `uvx owpp`): `list`, `check`, `bundle`, `deploy`, `init`. Configurable plugins folder and ownership marker; `--only` deploys without pruning.
- Composite GitHub Action (runs `owpp` from its own checkout with uv).
- Excalidraw can load its editor from a host you run (`EXCALIDRAW_ASSETS_URL`, built by `self-host/build.sh`), so the page needs nothing from the internet.
- Examples: `excalidraw`, `mcpo_sync`, `stale_data`, `inline_visualizer`, `page_banners`.
- Decisions and assumptions: `docs/decisions.md`.
