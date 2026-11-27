# On a real Open-WebUI

The [test harness](harness.md) runs Open-WebUI's code, but [it fakes some parts](harness.md#what-the-harness-fakes). Test those parts on a real Open-WebUI. Examples are a real model, sign-in providers, several workers and the browser. You can do this by hand, or with live tests that [`owpp live`](../commands/live.md) runs on a throwaway Open-WebUI.

## By hand

The docstring of every test ends with **By hand** steps, which show the same behaviour on a live Open-WebUI ([describe every test](writing.md#describe-every-test)). The README's `## Test` list collects them. Do them before a release, and after a change to how the plugin works with Open-WebUI.

**Caution:** Do not deploy to the instance that people use. A plugin runs inside Open-WebUI with admin rights.

1. Deploy the plugin to a test instance, in one of these ways:
    - Start a throwaway one with [`owpp live --up`](#trying-things-out), which deploys the plugins.
    - On your own test instance, run `owpp deploy --only <id> --dry-run` ([deploy](../commands/deploy.md)). Read the list of changes. Then run the same command without `--dry-run`.
2. Do the steps in the README's `## Test` list as an admin.
3. Do them again as a user who is not an admin.
4. In the pull request, write which steps you did ([reviewing a change](../reviewing.md)).

## Live tests in your repository

You can change a **By hand** step that depends on Open-WebUI into a test that runs on every pull request. Put the live tests in one folder of the plugins repository, `live/`, beside `plugins/`:

```
plugins/
live/
  test_live.py      # the tests: pytest, with owpp live's fixtures
  compose.yaml      # optional: services and settings, layered on owpp's
  aimock/           # optional: what the model answers, in place of owpp's fixtures
    models.json
```

```sh
uvx --from 'owpp[live]' playwright install chromium   # once, for tests in the browser
uvx --from 'owpp[live]' owpp live
```

`owpp live` starts a throwaway Open-WebUI in Docker, with [aimock](#the-model-aimock) as its models. It deploys `plugins/`, runs the tests in `live/` and removes everything. For what it starts and what it needs, see [`owpp live`](../commands/live.md).

This first example tests over the API and in the browser:

```python
"""Shout on a real Open-WebUI."""

from owpp.live import send, url


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

Give each test the same docstring as every owpp test, with its **By hand** steps. A test can pass on the harness but fail here. That is a finding about the plugin, the harness, or both.

### The fixtures

`owpp live` loads these pytest fixtures into its pytest run, with `PYTEST_PLUGINS=owpp.live.fixtures`. Other pytest runs do not have them.

| Fixture | Is |
| --- | --- |
| `api`, `user_api` | Open-WebUI's HTTP API as the admin, or as a user who is not an admin. `api("GET", path)` and `api("POST", path, body)` return `(status, body)`, also for an error. Put the body in the assertion message: Open-WebUI gives the cause in `detail`. |
| `aimock` | `aimock.requests()` returns every chat request that Open-WebUI sent to the model, from aimock's journal, newest last. The messages in them are the messages after all filters ran. |
| `admin`, `user`, `signed_out` | A [Playwright](https://playwright.dev/python/) page, signed in as the admin or the user, or with no session. |
| `admin_account`, `user_account` | The accounts: `name`, `email`, `password`, `token`. |

Each account signs in once in each run, on Open-WebUI's login page, because Open-WebUI refuses more than a few sign-ins a minute. Every test gets a new browser context from that session. So a test does not see what an earlier test left in `localStorage`.

`owpp.live` also has two functions:

- `url()` is the address of Open-WebUI, for `page.goto`.
- `send(page, text)` types a message into the chat. It sends the message after the input holds all of the text.

The fixtures read [the variables that `owpp live` sets](../environment-variables.md#set-by-owpp-live-for-the-live-tests). If the account variables are missing, a test that uses an account, the API or a page stops the run. The message tells you to start `owpp live`.

### Tests in the browser

Use the browser to test what only the chat page or the browser does:

- a tool that the chat page runs for the model;
- a button under a reply;
- the Artifacts panel;
- a page that a plugin serves.

In each test:

1. Wait for the page to show the result (`page.get_by_text(...).wait_for(timeout=60_000)`).
2. Assert on the page and on `aimock.requests()`.

Do not put apostrophes in the text that you give to `send`. The chat input changes `'` into `’`, so `send` never finds your text there and the test fails.

When a test with a page fails, owpp keeps information in `live/failures/`. It keeps a PNG and the text of each page, and the last requests to aimock. Add the folder to `.gitignore`.

### Your own services, and grants

If a plugin calls a different service, add a stand-in in your repository's `live/compose.yaml`. owpp adds this file on top of its own: [your own services and settings](../commands/live.md#your-own-services-and-settings). You can also change Open-WebUI's settings in the same file.

owpp's stack lets every user use every model, so the user account can chat immediately. To test a plugin that gives or needs model grants, set `BYPASS_MODEL_ACCESS_CONTROL: "false"` there, as on a real instance.

### Trying things out

`owpp live --up` starts the same stack, deploys the plugins and does not stop the stack. You get a throwaway Open-WebUI where you can try a plugin by hand. It uses no real model and no API key, `OFFLINE_MODE` is on, and nothing is kept after it stops. The command prints the address and both accounts.

Then do what you need:

- **Sign in** at http://127.0.0.1:3000 with one of the accounts, and do the **By hand** steps of a plugin.
- **Run the tests:** export the variables that the command printed. Then run `uvx --from 'owpp[live]' pytest live/` as often as you want.
- **Deploy a change:** set the two `OPEN_WEBUI_*` variables that the command printed. Then run `owpp deploy --only <id>`.
- **Add a model answer:** add an aimock fixture to `live/aimock/models.json`, above the fixture that matches everything. Then run `docker restart owpp-live-aimock-1`.
- **See what Open-WebUI sent to the model:** run `curl 'http://127.0.0.1:4010/__aimock/journal?path=/v1/chat/completions'`. This is the quickest way to test an inlet.
- **Stop the stack:** run `owpp live --down`.

To run the live tests in CI, see [a live check](ci.md#a-live-check).

## The model: aimock

The stack has no real model and needs no API key. Its models come from [aimock](https://github.com/CopilotKit/aimock) (CopilotKit, MIT, pinned in owpp's `src/owpp/live/compose.yaml`). aimock is an OpenAI-compatible server that answers from **fixtures**, with the same result in every run.

Each aimock fixture says what to match and what to answer:

- It matches on, for example, the requested model, the last user message, an offered tool or the result of a tool.
- It answers with text, tool calls or reasoning.

aimock uses the first fixture that matches.

owpp's own fixtures give one model, `owpp-live-model`. It answers every message with "Hello! I am owpp's live model: I answer the same way every time."

owpp's stack turns off Open-WebUI's title, tag and follow-up tasks (`ENABLE_TITLE_GENERATION`, `ENABLE_TAGS_GENERATION`, `ENABLE_FOLLOW_UP_GENERATION`). So no fixture has to copy the prompts of those tasks, and aimock's journal holds only the requests of the chat. A chat keeps the title "New Chat". To test a task, turn it on again in your repository's `live/compose.yaml`.

A repository's `live/aimock/` folder replaces these fixtures: the models in its fixtures are the models of the stack. aimock lists as its models (`/v1/models`) the models that its fixtures name. So name a model in every fixture, and put the more specific fixtures first:

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

aimock keeps a **journal** of every request, at `GET http://127.0.0.1:4010/__aimock/journal`. The `aimock` pytest fixture reads this journal. For every field that a fixture can match and answer with, see [aimock's fixture reference](https://aimock.copilotkit.dev/fixtures/).

## This repository's live suite

This repository tests its examples with `owpp live`. The workflow `.github/workflows/live.yml` runs on every pull request, every push to `main` and `develop`, and every `v*` tag.

The suite has these parts:

- The tests are in `tools/live/`.
- The stack is owpp's stack, with `tools/screenshots/compose.yaml` on top of it. That file adds [fixed files](#everything-else-fixed-files) for the services that the examples call, and the settings that they need.
- The aimock fixtures are in `tools/screenshots/aimock/`.

The [screenshots](../screenshots.md) use the same stack. The screenshots show what happens, and the live suite asserts it.

```sh
uv run python tools/screenshots/run.py --live
```

`run.py` is `owpp live` with these parts. Its `--up` and `--keep` flags work as in `owpp live`. It needs Docker and Chromium (`uv run playwright install chromium`). To run it without the `docker` group, see [taking screenshots](../screenshots.md#taking-them). `uv run pytest` does not collect these tests. The suite runs on v0.13.5 only.

| Test | What it shows on a real Open-WebUI |
| --- | --- |
| `test_the_deployed_functions_are_installed_and_active` | `owpp deploy` leaves the examples installed and active. |
| `test_a_public_tool_is_readable_by_a_user_who_is_not_the_owner` | `access: public` shares a tool. The old mock once accepted a grant that Open-WebUI ignores. |
| `test_the_scripted_model_answers_a_chat` | A chat reaches the model, and the reply comes back. |
| `test_a_deployed_tool_is_offered_to_the_model_and_the_model_calls_it` | With `tool_ids`, the model gets the functions of the deployed tool, and the model's call comes back. |
| `test_an_outlet_turns_unfinished_reasoning_into_the_answer` | The outlet of `clear_thinking_tags` runs through `/api/chat/completed` and changes the reply. |
| `test_an_inlet_can_send_a_message_with_an_image_to_another_model` | The inlet of `vision_router` changes the model that gets a request. A valve sets the model. |
| `test_theme_designer_pros_routes_are_reached_ahead_of_open_webuis_own` | `plugin_mount` puts routes under `/api/v1`, where Open-WebUI's API and web app also answer. Requests reach these routes, also from a person who is signed out. |
| `test_theme_designer_pros_designer_is_for_admins` | A route marked `PluginAdmin` refuses a user who is not an admin, on the real server. |
| `test_theme_designer_pros_save_reaches_a_signed_out_page` | A page with no session immediately gets what `theme_designer_pro` saves. |
| `test_theme_designer_pros_launcher_and_skill_reach_a_user` | A user who is not an admin gets a tool and a skill that an event function installs. |
| `test_the_chat_page_runs_the_tool_the_model_calls_and_answers_with_its_result` | In the browser, the chat page runs the tool that the model calls, and the model answers with the result. (The API returns the call to the caller.) |

To add a test:

1. Use [the fixtures](#the-fixtures).
2. For a test of the API, write it in a file in `tools/live/`.
3. For a test in the browser, write it in `test_in_the_browser.py`, or in a file beside it.

A test and a screenshot script often follow the same **By hand** steps. The test asserts the steps on every pull request. The script takes pictures of them during a screenshot run.

### What the first runs found

The mock that the unit tests used then showed none of these:

- **A user needs a read grant to use a model.** Without the grant, a user who is not an admin gets "Model not found". This is also true for a model that a filter sends the request to. This repository's stack keeps this rule (`BYPASS_MODEL_ACCESS_CONTROL: "false"`), but owpp's stack lets every user use every model.
- **The API returns a tool call to the caller.** With no saved chat, Open-WebUI returns the model's tool call (`finish_reason: "tool_calls"`) and does not run the tool. The chat page in the browser runs it.
- **`/api/chat/completed` answers 404** unless the user owns the chat. v0.13 keeps this endpoint for older clients: outlets also run inside the chat completion.
- **The chat input changes apostrophes**, which affects [tests in the browser](#tests-in-the-browser).

### Its fixtures

`tools/screenshots/aimock/models.json`:

| Fixture matches | It answers | For |
| --- | --- | --- |
| `model: screenshot-vision` | "I am the vision model: ..." | [`vision_router`](../examples/vision_router.md): the reply shows which model got the picture. |
| a last user message that contains `[reasoning only]` | reasoning and no answer | [`clear_thinking_tags`](../examples/clear_thinking_tags.md) |
| `show_excalidraw` offered, and its result in the request | "Here is the diagram: ..." | [`excalidraw`](../examples/excalidraw.md): the answer after the tool runs. |
| `show_excalidraw` offered | a call to it, with a fixed drawing | `excalidraw`: "draw something" gives the same drawing every time. |
| `create_theme` offered, and its result in the request | "Here is Teal Lagoon: ..." | [`theme_designer_pro`](../examples/theme_designer_pro.md): the answer under the Launcher's card. |
| `create_theme` offered | a call to it: Teal Lagoon, hue 195 | `theme_designer_pro`: the same theme card every time. |
| all other requests for `screenshot-model` | "Hello! I am the screenshot model: ..." | all other chats |

Open-WebUI has a second OpenAI connection here, `gateway`, which only describes the same models ([fixed files](#everything-else-fixed-files)). If both connections list a model, Open-WebUI keeps the entry of the first connection. So the chats go to aimock.

### Everything else: fixed files

The examples also call services that are not models. One `nginx` server answers these calls with fixed files (the `static` service in `tools/screenshots/compose.yaml`, with `tools/screenshots/nginx.conf`). So the stand-ins need no server code of their own.

| Stands in for | Reached as | Files | For |
| --- | --- | --- | --- |
| A LiteLLM gateway | `http://gateway/v1` (Open-WebUI's second OpenAI connection) | `gateway/v1/models`, `gateway/model/info` | [`litellm_model_sync`](../examples/litellm_model_sync.md). aimock has no `/model/info`. |
| mcpo | `http://mcpo:8000`, with `Authorization: Bearer mcpo-key` | `mcpo/openapi.json` (lists `time` and `fetch`), `mcpo/<server>/openapi.json` | [`mcpo_sync`](../examples/mcpo_sync.md) |

The LiteLLM sync gives each model the read grant that a user who is not an admin needs. So **when aimock answers as a model, also add the model to the gateway's files**. `tests/test_live_stack.py` checks this. It also checks that every server in mcpo's root document has its own document.

To try the examples by hand:

1. Run `uv run python tools/screenshots/run.py --up`.
2. Continue as in [trying things out](#trying-things-out). Here, the aimock fixtures are in `tools/screenshots/aimock/models.json`.
3. To deploy a change, use `uv run owpp deploy --dir examples/plugins --only <id>`.
