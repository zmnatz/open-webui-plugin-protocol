---
name: owpp
description: Open-WebUI plugins kept in git with owpp, the Open-WebUI plugin protocol CLI. Use when creating, changing, testing, versioning or deploying an Open-WebUI function, tool or skill; when a repository has plugin folders with a plugin.yaml; when moving a plugin taken from another git repository to a newer commit; or when the user mentions owpp.
---

# Open-WebUI plugins with owpp

A **plugin** is a folder, `plugins/<id>/`, with a `plugin.yaml`: a function (the parent) and, optionally, a tool and skills that the function installs when it is enabled and removes when it is disabled. `owpp` bundles the folder into the single file Open-WebUI stores, tests it against a mock Open-WebUI, and deploys it.

Run it as `uvx owpp <command>` (in scripts and CI, pinned: `uvx owpp@0.2.1`). `uvx owpp <command> --help` is the reference for every flag. The full documentation is at https://zmnatz.github.io/open-webui-plugin-protocol/, and its whole text, for reading in one go, at https://zmnatz.github.io/open-webui-plugin-protocol/llms-full.txt.

Every command takes `--dir`: the plugins folder, default `./plugins`.

## Pick the branch

| The task | Go to |
| --- | --- |
| A new plugin | [Create](#create) |
| Change a plugin that exists | [Change](#change) |
| A plugin that takes its code from another git repository, or moving it to a newer commit | [From git](#from-git) |
| Put plugins on an Open-WebUI instance | [Deploy](#deploy) |
| Functions someone pasted into Open-WebUI by hand | https://zmnatz.github.io/open-webui-plugin-protocol/adopting/ |

## Create

1. **Pick the type.** It decides the function's one class:
   - **filter**: changes chat requests or replies (`inlet`, `request`, `stream`, `outlet`);
   - **action**: a button under a message;
   - **pipe**: appears as a model;
   - **event**: reacts to Open-WebUI itself (startup, saved settings), runs on a schedule, or serves its own pages;
   - **installer**: no code of its own, only a tool and/or skills, which the generated function installs.
   - Code from another repository: [from git](#from-git).
2. **Describe it in a spec and create it**: write the spec ([references/spec.md](references/spec.md)) to a file, then `uvx owpp create --spec <file>`. It writes the folder, with stubs, tests, a README and a CHANGELOG, and runs `owpp check --strict` on it. (`owpp create` with no `--spec` is a wizard for a person at a terminal: it waits for typed answers.)
3. **Fill in the stubs**: the work goes in `function.py`, `tool.py`, `skills/<name>/SKILL.md` and the pages, following [the rules](#the-rules-owpp-and-open-webui-hold-the-code-to). Add a test for each behaviour, in the plugin's `tests/`.

Done when `uvx owpp check <id> --strict` reports no `FAIL` and no `warn`, and `uvx --from 'owpp[test]' owpp test <id>` passes.

## Change

1. Make the change, and its test.
2. **Give it a new version**: `uvx owpp version <id> patch|minor|major -m "<what changed, for the people who use it>"`. Its tool's version: `--tool`; a skill's: `--skill <name>`. `uvx owpp version` lists them all.

Done when `owpp check <id> --strict` and `owpp test <id>` pass, and `uvx owpp check --since origin/main` (or the branch the change will merge into) reports no `FAIL`: it fails on anything that changed without a new version, and says which `owpp version` command to run.

## From git

A plugin may take its function, tool or skills from another repository, pinned to a full 40-character commit SHA in `plugin.yaml`'s `source:` (with the files named by `file:` and `dir:` entries). That code runs with admin rights in Open-WebUI, so the commit only ever moves in a reviewed change.

- **To add one**, write a spec with a `source:` ([references/spec.md](references/spec.md#from-git)). Resolve a branch or tag to its SHA first: `git ls-remote <url> <branch>`; put the branch in `track:`.
- **To take a whole owpp plugin** (a folder with a `plugin.yaml`, such as this repository's examples), write `plugin.yaml` by hand with `source: {git, path, plugin: true}` and no `ref:`, then run `uvx owpp pull <id>` to pin it. The local manifest may only set `function: {valves, global}` and `tool: {id, access, valves}`; skills are the upstream's.
- **To move it to the latest commit**: `uvx owpp pull <id>`. It rewrites `ref:`, bumps the plugin's version and adds a changelog entry, and lists the upstream files that changed, with a compare link. Show the user that list and link: they review the upstream diff before the change is committed. `uvx owpp deploy --dry-run --latest` shows what the upgrade would change on the instance first, writing nothing.

Done when the user has seen the files that changed, and `owpp check <id> --strict` passes.

## Deploy

1. **Credentials** come from the environment: `OPEN_WEBUI_URL`, then one of `OPEN_WEBUI_API_KEY`; `OPEN_WEBUI_USERNAME` and `OPEN_WEBUI_PASSWORD`; `OPEN_WEBUI_OIDC_TOKEN`; or none, where the instance signs in without them. The account must be an admin. Leave them in the environment: ask the user to set them, and keep them out of files, commands and messages.
2. **Dry run**: `uvx owpp deploy --dry-run` (add `--only <id>` for one plugin). Read the report to the user: what is created or updated, each version change, and every warning.
3. **Deploy** only once the user says to: `uvx owpp deploy` (with the same `--only`).
   - A **downgrade warning** (the instance runs a newer version than the repository) means the wrong branch, most of the time: stop and ask. `--force` is for a rollback the user asks for by name.
   - `--latest` goes with `--dry-run` only: the latest upstream commits reach an instance through `owpp pull` and a reviewed commit.

Done when the deploy's report lists every plugin as the user expected, and the README's `## Test` steps are handed to the user for the checks on the live instance.

## The rules owpp and Open-WebUI hold the code to

- **One function class** at the top level of `function.py`: `Filter`, `Action`, `Event` or `Pipe`. The header (`title`, `version`, `description`, ...) lives under `function:` in `plugin.yaml`, one line per value, never in a docstring of `function.py`.
- **Ids** are `[a-z_][a-z0-9_]*`: the folder name is the function id, so no hyphens.
- **Libraries are globals.** `include: [routes, jobs, events, chat_data]` in `plugin.yaml` inserts the library's code into the bundle, so its names (`plugin_mount`, `PluginAdmin`, `on`, `PluginEvents`, `plugin_chat_read`, `plugin_template_text`, ...) are used directly, with no import. `static/`, `templates/`, `assets/` and `config.yaml` bring theirs in by being there. Library reference: https://zmnatz.github.io/open-webui-plugin-protocol/libraries/
- **Open-WebUI's own modules** (`open_webui.*`) are imported inside the function that uses them, so the plugin also loads in the mock.
- **Valves** are `UPPER_SNAKE`, each a `Field(default=..., description="...")`. A valve's description is what the admin sees.
- **Tool methods** are what the model sees: a type hint on every parameter, a docstring that says when to call it, and one `:param name:` line per parameter. Helpers start with `_`.
- **Routes** are mounted with `plugin_mount(app, router, prefix)` only; it puts the sign-in guard on them. A route that needs more than a signed-in user is marked on its handler (`user: PluginAdmin`, `chat_id: WritableChat`). Public (`access="public"`) is per mount, and only for what must serve people who are not signed in.
- **Event handlers** use `@on("event.name", own=True)` on a `class Event(PluginEvents)`.
- **HTML lives in files**: `static/` for files served as they are, `templates/` for pages the function fills in (`plugin_template_text("page.html")`).
- **Tests** live in the plugin's `tests/` and use the `owui` and `plugin` fixtures. Each test's docstring says what it checks, then `By hand:` the steps to see the same on a live Open-WebUI. Mock reference: https://zmnatz.github.io/open-webui-plugin-protocol/testing/
- **Vendored code** (the libraries owpp inserts, and code from a `source:`) is used as it is: changes go in the plugin's own files.
