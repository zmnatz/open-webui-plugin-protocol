# On a real Open-WebUI

The mock runs the plugin's code, not Open-WebUI. What only Open-WebUI does (the chat pipeline that decides which filters and tools run, grants, sign-in providers, the browser) is checked on a real instance: by hand, or with live tests that [`owpp live`](../commands/live.md) runs on a throwaway one.

## By hand

Every test's docstring ends with **By hand**: the steps to see the same behaviour on a live Open-WebUI ([describe every test](writing.md#describe-every-test)). The README's `## Test` list gathers them. Before a release, or after a change to how the plugin meets Open-WebUI:

1. Deploy to a test instance, never the one people use: `owpp deploy --only <id> --dry-run`, then without `--dry-run` ([deploy](../commands/deploy.md)), or start one with [`owpp live --up`](#trying-things-out).
2. Follow the README's `## Test` steps, as an admin and as a user who is not one.
3. Say in the pull request which steps you did ([reviewing a change](../reviewing.md)).

## Live tests in your repository

A By hand step that depends on what only Open-WebUI does can be a test instead, run on every pull request. Live tests live in one folder of the plugins repository, `live/` beside `plugins/`:

```
plugins/
live/
  test_live.py      # the tests: pytest, with owpp-live's fixtures
  compose.yaml      # optional: services and settings, layered on owpp's
  aimock/           # optional: what the model answers, in place of owpp's fixtures
    models.json
```

```sh
uvx --from owpp-live playwright install chromium   # once, for tests in the browser
uvx --from owpp-live owpp live
```

[`owpp live`](../commands/live.md) (the **owpp-live** package, released with owpp) starts Open-WebUI v0.13.5 (the `-slim` image) and [aimock](#the-model-aimock) as its models in Docker, signs up an admin and a user, deploys `plugins/` with `owpp deploy`, runs `live/` with pytest and removes it all again. It needs Docker, reachable by your user. A first test, over the API and in the browser:

```python
"""Shout on a real Open-WebUI."""

from owpp_live import send, url


def test_it_is_deployed_and_active(api):
    """By hand: Admin Panel > Functions lists Shout, switched on."""
    status, function = api("GET", "/api/v1/functions/id/shout")
    assert status == 200, function
    assert function["is_active"]


def test_the_inlet_shouts_before_the_model_sees_the_message(user_api, aimock):
    """By hand: send "hello"; the model was asked "HELLO"."""
    status, reply = user_api(
        "POST",
        "/api/chat/completions",
        {
            "model": "owpp-live-model",
            "stream": False,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert status == 200, reply
    assert any("HELLO" in str(r["messages"]) for r in aimock.requests())


def test_a_user_sees_the_reply_in_the_chat(user):
    """By hand: in a new chat, send a message; the model's reply shows under it."""
    user.goto(f"{url()}/?models=owpp-live-model")
    send(user, "Hello there")
    user.get_by_text("I answer the same way every time").first.wait_for(timeout=60_000)
```

Each test keeps the docstring every owpp test has, with its **By hand** steps. A test that fails here and passes against the mock is a finding about Open-WebUI, the mock, or both.

### The fixtures

owpp-live's pytest plugin gives every test in a run it is installed in:

| Fixture | Is |
| --- | --- |
| `api`, `user_api` | Open-WebUI's HTTP API as the admin, or as a user who is not one. `api("GET", path)` and `api("POST", path, body)` return `(status, body)`, with the body on an error too, so put it in the assertion message: Open-WebUI says what went wrong in `detail`. |
| `aimock` | `aimock.requests()`: every chat request Open-WebUI sent the model, from aimock's journal, newest last. The messages there are the ones after every filter ran. |
| `admin`, `user`, `signed_out` | A [Playwright](https://playwright.dev/python/) page signed in on Open-WebUI's own login page as the admin or the user, or with no session. |
| `admin_account`, `user_account` | The accounts: `name`, `email`, `password`, `token`. |

From `owpp_live`: `url()` is Open-WebUI's address, for a page to `goto`, and `send(page, text)` types a message into the chat and sends it, once the input holds all of it. The fixtures read [the variables `owpp live` sets](../environment-variables.md#set-by-owpp-live-for-the-live-tests); without them, a test that uses one stops the run and says to start `owpp live`.

### Tests in the browser

What only the chat page does (running the tool a model calls, a button under a reply, the Artifacts panel, a page a plugin serves) is tested in the browser. Wait for what the page shows (`page.get_by_text(...).wait_for(timeout=60_000)`), then assert on it and on `aimock.requests()`. Leave apostrophes out of what `send` types: the input turns `'` into `’`, and `send` then never sees the text it typed.

When a test with a page fails, what each page showed (a PNG and its text) and what aimock was last asked are kept in `live/failures/`, which belongs in `.gitignore`.

### Your own services, and grants

A plugin that calls another service gets a stand-in from the repository's own `live/compose.yaml`, layered on owpp's: [your own services and settings](../commands/live.md#your-own-services-and-settings). The same file changes Open-WebUI's settings. owpp's stack lets every user use every model, so the user account can chat at once; to test a plugin that gives or needs model grants, set `BYPASS_MODEL_ACCESS_CONTROL: "false"` there, as a real instance has it.

### Trying things out

`owpp live --up` starts the same stack and leaves it running: a throwaway Open-WebUI to try a plugin on by hand, with nothing leaving the machine (no real model, no API key, `OFFLINE_MODE` on, nothing kept once it stops). It prints the address and both accounts. Then:

- **Sign in** at http://127.0.0.1:3000 as either account, and follow a plugin's By hand steps.
- **Run the tests against it**, again and again: export the variables it printed, then `uvx --from owpp-live pytest live/`.
- **Deploy a change**: with the two variables it printed for that, `owpp deploy --only <id>`.
- **Make the model say something new**: add a fixture to `live/aimock/models.json`, above the catch-all, and restart aimock: `docker restart owpp-live-aimock-1`.
- **See what Open-WebUI sent the model**: `curl 'http://127.0.0.1:4010/__aimock/journal?path=/v1/chat/completions'`. This is the quickest way to check an inlet.
- **Stop it**: `owpp live --down`.

In CI: [a live check](ci.md#a-live-check).

## The model: aimock

The stack has no real model and needs no API key. Its models are [aimock](https://github.com/CopilotKit/aimock) (CopilotKit, MIT, pinned in owpp-live's `compose.yaml`): an OpenAI-compatible server that answers from **fixtures**, the same way every run. Each fixture says what to match (the model asked for, the last user message, a tool offered, a tool's result) and what to answer (text, tool calls, reasoning). The first fixture that matches wins.

owpp's own fixtures give one model, `owpp-live-model`, which answers every message with "Hello! I am owpp's live model: I answer the same way every time." (and fixed JSON for Open-WebUI's title and tag tasks). A repository's `live/aimock/` replaces them: its fixtures are the stack's models. aimock lists as its models (`/v1/models`) the models its fixtures name, so every fixture names one, and the more specific ones go first:

```json
{
  "fixtures": [
    {
      "match": { "model": "my-model", "toolName": "lookup" },
      "response": { "toolCalls": [{ "name": "lookup", "arguments": { "q": "weather" } }] }
    },
    { "match": { "model": "my-model" }, "response": { "content": "Hello from my model." } }
  ]
}
```

aimock keeps a **journal** of every request, at `GET http://127.0.0.1:4010/__aimock/journal`, which is what the `aimock` fixture reads. Every field a fixture can match on and answer with: [aimock's fixture reference](https://aimock.copilotkit.dev/fixtures/).

## This repository's live suite

This repository runs its examples with `owpp live`, on every pull request and every push to `main` and `develop` (`.github/workflows/live.yml`, with the stack's images cached between runs). Its tests are in `tools/live/`, and its stack is owpp's with `tools/screenshots/compose.yaml` layered on it ([fixed files](#everything-else-fixed-files) for the services the examples call, and the settings they need) and `tools/screenshots/aimock/` as its fixtures. The [screenshots](../screenshots.md) run on the same stack: the screenshots show what happens, the live suite asserts it.

```sh
uv run python tools/screenshots/run.py --live
```

`run.py` is `owpp live` with those pieces (`--up` and `--keep` work as there). It needs Docker ([taking screenshots](../screenshots.md#taking-them) says how without the `docker` group) and Chromium (`uv run playwright install chromium`). `uv run pytest` never collects it. It runs against v0.13.5 only.

| Test | What it shows on a real Open-WebUI |
| --- | --- |
| `test_the_deployed_functions_are_installed_and_active` | `owpp deploy` leaves the examples installed and active. |
| `test_a_public_tool_is_readable_by_a_user_who_is_not_the_owner` | `access: public` really shares a tool. The mock once agreed with a grant Open-WebUI ignores. |
| `test_the_scripted_model_answers_a_chat` | A chat reaches the model and its reply comes back. |
| `test_a_deployed_tool_is_offered_to_the_model_and_the_model_calls_it` | `tool_ids` puts the deployed tool's functions in front of the model, and the model's call comes back. |
| `test_an_outlet_turns_unfinished_reasoning_into_the_answer` | `clear_thinking_tags`'s outlet runs through `/api/chat/completed` and changes the reply. |
| `test_an_inlet_can_send_a_message_with_an_image_to_another_model` | `vision_router`'s inlet changes which model a request goes to, set by a valve. |
| `test_theme_designer_pros_routes_are_reached_ahead_of_open_webuis_own` | Routes `plugin_mount` puts under `/api/v1`, where Open-WebUI's own API and its web app's catch-all also answer, are reached, by someone signed out too. |
| `test_theme_designer_pros_designer_is_for_admins` | A route marked `PluginAdmin` refuses a user who is not an admin on the real server. |
| `test_theme_designer_pros_save_reaches_a_signed_out_page` | `theme_designer_pro`'s save is served at once to a page with no session. |
| `test_theme_designer_pros_launcher_and_skill_reach_a_user` | A tool and a skill an event function installs are given to a user who is not an admin. |
| `test_the_chat_page_runs_the_tool_the_model_calls_and_answers_with_its_result` | In the browser, the chat page runs the tool the model calls (the API hands the call back instead), and the model answers with its result. |

To add one, write a test in `tools/live/` with [the fixtures](#the-fixtures), in the browser in `test_in_the_browser.py` or a file beside it. A test and a screenshot script often follow the same By hand steps: the test asserts them on every pull request, the script photographs them when the screenshots are taken.

### What the first runs found

None of these could the mock have shown:

- **A model needs a read grant before a user can use it.** Without one, a user who is not an admin gets "Model not found", including for a model a filter sends the request to. (This repository's stack keeps that, with `BYPASS_MODEL_ACCESS_CONTROL: "false"`; owpp's lets every user use every model.)
- **Over the API, a tool call comes back to the caller.** With no saved chat, Open-WebUI returns the model's tool call (`finish_reason: "tool_calls"`) rather than running the tool; the browser's chat runs it.
- **`/api/chat/completed` needs a chat the user owns**, or it answers 404. In v0.13 it is kept for older clients: outlets also run inside the chat completion.
- **The chat input turns `'` into `’`**, so a test that types an apostrophe never sees its own message there.

### Its fixtures

`tools/screenshots/aimock/models.json`:

| Fixture matches | It answers | For |
| --- | --- | --- |
| `model: screenshot-vision` | "I am the vision model: ..." | [`vision_router`](../examples/vision_router.md): the reply shows where the picture went. |
| a last user message containing `[reasoning only]` | reasoning and no answer | [`clear_thinking_tags`](../examples/clear_thinking_tags.md) |
| `show_excalidraw` offered, and its result in the request | "Here is the diagram: ..." | [`excalidraw`](../examples/excalidraw.md): the answer once the tool has run. |
| `show_excalidraw` offered | a call to it, with a fixed drawing | `excalidraw`: so "draw something" gives the same drawing every time. |
| `create_theme` offered, and its result in the request | "Here is Teal Lagoon: ..." | [`theme_designer_pro`](../examples/theme_designer_pro.md): the answer under the Launcher's card. |
| `create_theme` offered | a call to it: Teal Lagoon, hue 195 | `theme_designer_pro`: the same theme card every time. |
| Open-WebUI's title and tag tasks | fixed JSON | stable chat titles in the screenshots |
| anything else for `screenshot-model` | "Hello! I am the screenshot model: ..." | every other chat |

Open-WebUI has a second OpenAI connection here, `gateway`, which only describes the same models ([fixed files](#everything-else-fixed-files)). It keeps the first connection's entry for a model both list, so the chats go to aimock.

### Everything else: fixed files

What the examples call besides a model answers with fixed files, from one `nginx` (the `static` service in `tools/screenshots/compose.yaml`, with `tools/screenshots/nginx.conf`), so the stack runs no code of anyone's but Open-WebUI's and aimock's:

| Stands in for | Reached as | Files | For |
| --- | --- | --- | --- |
| A LiteLLM gateway | `http://gateway/v1` (Open-WebUI's second OpenAI connection) | `gateway/v1/models`, `gateway/model/info` | [`litellm_model_sync`](../examples/litellm_model_sync.md). aimock has no `/model/info`. |
| mcpo | `http://mcpo:8000`, with `Authorization: Bearer mcpo-key` | `mcpo/openapi.json` (lists `time` and `fetch`), `mcpo/<server>/openapi.json` | [`mcpo_sync`](../examples/mcpo_sync.md) |

The LiteLLM sync is also what gives each model the read grant a user who is not an admin needs, so **a model aimock answers as must be in the gateway's files too**. `tests/test_live_stack.py` checks that, and that every server mcpo's root lists has its own document.

To try the examples by hand: `uv run python tools/screenshots/run.py --up`, then as in [trying things out](#trying-things-out) (with `tools/screenshots/aimock/models.json` for new fixtures, and `uv run owpp deploy --dir examples/plugins --only <id>` for a change).
