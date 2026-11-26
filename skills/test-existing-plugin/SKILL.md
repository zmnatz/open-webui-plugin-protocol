---
name: test-existing-plugin
description: Tests for an Open-WebUI function or owpp plugin that already works, against owpp's mock Open-WebUI (and live tests, over the API and in the browser with Playwright, on a real Open-WebUI with aimock, run by owpp live). Use when asked for tests, coverage, live or browser tests, or screenshots of a function pasted into Open-WebUI, a .py file, someone else's repository, or a plugin folder without tests.
---

# Tests for a plugin that already works

The code works today, so its tests are **characterization tests**: each one pins what the code does now, not what it ought to do. A test that disagrees with the code is a **finding**: report it to the user, and change the code only when they ask.

Run owpp as `uvx owpp <command>`, and its tests as `uvx --from 'owpp[test]' owpp test <id>` (in the owpp repository itself: `uv run owpp`). Every command takes `--dir`, the plugins folder (default `./plugins`). The testing guide, for each call named here: https://zmnatz.github.io/open-webui-plugin-protocol/testing/

## 1. Bring it in with `owpp import`

- **A function on Open-WebUI**: `owpp import --instance <id>`, with `OPEN_WEBUI_URL` and the deploy's credentials in the environment (ask the user to set them; keep them out of files and commands). It keeps the function's id, so a deploy updates that function rather than adding a second.
- **A `.py` file** (a docstring header of `title:`, `version:`, ..., then the code): `owpp import <file>`. Give `--id <the id it has in Open-WebUI>` when it is already deployed there.
- **Someone's repository**: `owpp import <URL of the folder or file>`. It finds the function, the tool and the skills there and pins them at a commit; it says what it left private.
- **A plugin folder that exists** (it has a `plugin.yaml`): test it where it is.

`owpp import` writes `plugin.yaml` (the header moves there), `function.py`, a README and a first test, and runs `owpp check`. Its notes (header lines dropped, a tool left private) go in your report. Reference: https://zmnatz.github.io/open-webui-plugin-protocol/commands/import/

Then run `owpp check <id> --strict`. A `FAIL` (an undefined name, two function classes) is also broken in Open-WebUI: it is a finding. A `warn` in someone else's code is reported and left alone.

Done when `owpp check <id>` reports no `FAIL`, or each one is reported to the user.

## 2. List the behaviours

Read the whole of the code, and write down, one line each:

- **each method Open-WebUI calls** on the class: a `Filter`'s `inlet`, `outlet` and `stream`; an `Action`'s `action`; a `Pipe`'s `pipes` and `pipe`; an `Event`'s handlers; a tool's public methods;
- **each valve**, and what changes when it is set;
- **each branch**: every early `return`, `except`, and check on the user's role, the model or the body's shape, both what it does and when it leaves things alone;
- **each thing outside it** that it calls: an `open_webui` model, an HTTP service, a model.

Done when every method, valve and branch in the code has a line.

## 3. Write a test for each line

Tests go in `plugins/<id>/tests/test_<id>.py`, using the `owui` and `plugin` fixtures (the plugin loaded into a fresh mock, enabled, with its default valves). Call it the way Open-WebUI does, so its real code runs:

| It is | Call it with |
| --- | --- |
| a filter | `plugin.inlet(body, user=, chat_id=, model=)`, `plugin.outlet(...)`, `plugin.call("stream", chunk)` |
| an action | `plugin.call("action", body, user=)`; several buttons: `__id__="<button>"` |
| a pipe | `plugin.call("pipes")`, `plugin.call("pipe", body, user=)` |
| an event | `owui.startup()`, `owui.enable(id)`, `owui.emit("<event>", ...)` |
| a page | `owui.client(user).get(path)` |
| a tool it installs | `owui.tool("<tool id>").call("<method>", ...)` |

Set valves with `owui.set_valves(id, NAME=value)`, add people with `owui.add_user("Bob")`, and assert on what comes back, `owui.chat_events` (what it sent through `__event_emitter__`), and the tables (`owui.users`, `owui.functions`, `owui.tools`, `owui.models`). Recipes for each kind: https://zmnatz.github.io/open-webui-plugin-protocol/testing/kinds/

For each line:

1. **Predict** what the code does from reading it, and write that as the expected value: a literal worked out by hand, never one computed the way the code computes it.
2. **Run it**: `owpp test <id> -- -k <name>`. When it fails, either the prediction misread the code (fix the test) or the code does something its author would not want (a finding: keep the assertion of what the code does, mark it `# finding: <what>` and tell the user).
3. **See it bite**: change the expected value, see it go red, put it back. A test that cannot go red checks nothing.

Each test is named as a sentence about the plugin and has the docstring owpp's tests carry (what it checks, then `By hand:`): https://zmnatz.github.io/open-webui-plugin-protocol/testing/writing/#describe-every-test

Code written outside owpp meets the mock's limits (an older Open-WebUI's API, a name the mock lacks, a service it calls): https://zmnatz.github.io/open-webui-plugin-protocol/testing/kinds/#a-function-written-elsewhere. A failure from the older API is a finding; behaviour out of the mock's reach goes in By hand.

Done when every line of the list has a test with both docstring paragraphs, `owpp test <id>` passes, and every finding is in your report.

## 4. Write the README's `## Test`

In `plugins/<id>/README.md` (make one if there is none): the `owpp check <id> --strict` and `owpp test <id>` commands, then the By hand steps as a list of live checks.

Done when each By hand step is in the list.

## 5. Live tests, on a real Open-WebUI

For each By hand step that depends on what only Open-WebUI does, write a live test that asserts it on a throwaway Open-WebUI v0.13.5 in Docker, with aimock answering as its models. `owpp live` (the owpp-live package) starts it, deploys the plugins and runs the tests: https://zmnatz.github.io/open-webui-plugin-protocol/testing/live/#live-tests-in-your-repository

- **Where**: in a plugins repository, `live/test_<id>.py` beside `plugins/`. In the owpp repository, for one of its examples, `tools/live/` (and follow `docs/agents/examples.md`, steps 3 to 5).
- **Over the API** (which model a request goes to, what reaches the model, a grant): the `api` and `user_api` fixtures (each call returns `(status, body)`), and `aimock.requests()` for what Open-WebUI sent the model.
- **In the browser** (the chat page running a tool the model calls, a button under a reply, the Artifacts panel, a page the plugin serves): the `admin`, `user` or `signed_out` Playwright page, with `send(page, text)` and `url()` from `owpp_live`. Wait for what the page shows (`page.get_by_text(...).wait_for(timeout=60_000)`), then assert on it and on `aimock.requests()`. Leave apostrophes out of what `send` types: the input makes them curly.
- **The model's answers**: `live/aimock/models.json` (in the owpp repository, `tools/screenshots/aimock/models.json`), more specific fixtures first. Without one, the model is `owpp-live-model`, which answers every message the same way.
- **A service the plugin calls**: a stand-in in `live/compose.yaml`, layered on owpp's stack: https://zmnatz.github.io/open-webui-plugin-protocol/commands/live/#your-own-services-and-settings

Run them with `uvx --from owpp-live owpp live` (in the owpp repository, `uv run python tools/screenshots/run.py --live`), with `-- -k <name>` for some. It needs Docker, reachable by the user running you: when `docker ps` says "permission denied", give the user the command to run, and work from the output they paste back. Install Chromium once, for the browser: `uvx --from owpp-live playwright install chromium`. See each test bite, as in step 3. A failure that the mock's tests did not show is a finding.

**Screenshots**, in the owpp repository only (`docs/screenshots.md#adding-one`): each script follows one test's By hand steps in the browser, and its `shot(..., illustrates=[...])` names the tests from step 3 that it shows.

Done when `owpp live` passes with a test for each By hand step that needs the real Open-WebUI, or the user has the command to run where you cannot, and in the owpp repository the screenshots run passes with its new PNGs and `docs/screenshots/screenshots.json` in the change.

## Report

Tell the user the tests written (one line per behaviour, the live ones marked), each finding with the test that shows it, and what is left to check by hand.
