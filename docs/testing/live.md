# On a real Open-WebUI

The mock runs the plugin's code, not Open-WebUI. What only Open-WebUI does (the chat pipeline that decides which filters and tools run, grants, sign-in providers, the browser) is checked on a real instance.

## By hand

Every test's docstring ends with **By hand**: the steps to see the same behaviour on a live Open-WebUI ([describe every test](writing.md#describe-every-test)). The README's `## Test` list gathers them. Before a release, or after a change to how the plugin meets Open-WebUI:

1. Deploy to a test instance, never the one people use: `owpp deploy --only <id> --dry-run`, then without `--dry-run` ([deploy](../commands/deploy.md)).
2. Follow the README's `## Test` steps, as an admin and as a user who is not one.
3. Say in the pull request which steps you did ([reviewing a change](../reviewing.md)).

## The live suite

This repository also runs its examples on a real Open-WebUI, automatically. It starts the same stack as the [screenshots](../screenshots.md) (Open-WebUI v0.13.5 as the `-slim` image, [aimock](#the-model-aimock) as its models, and [fixed files](#everything-else-fixed-files) for the services the examples call, in Docker), deploys `examples/plugins` with `owpp deploy`, then runs the tests in `tools/live/`: the screenshots show what happens, the live suite asserts it.

```sh
uv run --group screenshots python tools/screenshots/run.py --live
```

It needs Docker, reachable by your user ([taking screenshots](../screenshots.md#taking-them) says how without the `docker` group), and no browser. On GitHub, `.github/workflows/live.yml` runs it on every pull request and every push to `main` and `develop`, as `ci` runs the unit tests, with the stack's images cached between runs. `uv run pytest` never collects it: it needs Docker. It runs against v0.13.5 only.

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

To add one, write a `test_*.py` in `tools/live/` with the `api` (admin) and `user_api` fixtures. Each call returns `(status, body)`, with the body on an error too, so put it in the assertion message: Open-WebUI says what went wrong in `detail`. To see what Open-WebUI sent the model, read aimock's journal (`_requests()` in `test_live.py`).

A plugins repository can run its own the same way: see [an isolated Open-WebUI of your own](#an-isolated-open-webui-of-your-own).

### What the first runs found

None of these could the mock have shown:

- **A model needs a read grant before a user can use it.** Without one, a user who is not an admin gets "Model not found", including for a model a filter sends the request to.
- **Over the API, a tool call comes back to the caller.** With no saved chat, Open-WebUI returns the model's tool call (`finish_reason: "tool_calls"`) rather than running the tool; the browser's chat runs it.
- **`/api/chat/completed` needs a chat the user owns**, or it answers 404. In v0.13 it is kept for older clients: outlets also run inside the chat completion.

## The model: aimock

The stack has no real model and needs no API key. Its models are [aimock](https://github.com/CopilotKit/aimock) (CopilotKit, MIT, pinned in `compose.yaml`): an OpenAI-compatible server that answers from **fixtures**, the same way every run. Each fixture says what to match (the model asked for, the last user message, a tool offered, a tool's result) and what to answer (text, tool calls, reasoning). The first fixture that matches wins. They are in `tools/screenshots/aimock/models.json`:

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

aimock lists as its models (`/v1/models`) the models its fixtures name, so every fixture names one. It keeps a **journal** of every request, at `GET http://127.0.0.1:4010/__aimock/journal`, which is how a test sees what Open-WebUI sent: the messages after the filters ran, the tools offered, the model.

Open-WebUI has a second OpenAI connection, `gateway`, which only describes the same models ([fixed files](#everything-else-fixed-files)). It keeps the first connection's entry for a model both list, so the chats go to aimock.

When an example needs a reply the fixtures do not give, add a fixture, more specific ones first. Every field a fixture can match on and answer with: [aimock's fixture reference](https://aimock.copilotkit.dev/fixtures/).

## Everything else: fixed files

What the examples call besides a model answers with fixed files, from one `nginx` (the `static` service, `tools/screenshots/nginx.conf`), so the stack runs no code of anyone's but Open-WebUI's and aimock's:

| Stands in for | Reached as | Files | For |
| --- | --- | --- | --- |
| A LiteLLM gateway | `http://gateway/v1` (Open-WebUI's second OpenAI connection) | `gateway/v1/models`, `gateway/model/info` | [`litellm_model_sync`](../examples/litellm_model_sync.md). aimock has no `/model/info`. |
| mcpo | `http://mcpo:8000`, with `Authorization: Bearer mcpo-key` | `mcpo/openapi.json` (lists `time` and `fetch`), `mcpo/<server>/openapi.json` | [`mcpo_sync`](../examples/mcpo_sync.md) |

The LiteLLM sync is also what gives each model the read grant a user who is not an admin needs, so **a model aimock answers as must be in the gateway's files too**. `tests/test_live_stack.py` checks that, and that every server mcpo's root lists has its own document.

## Trying things out in isolation

The same stack is a throwaway Open-WebUI to try a plugin on, by hand, with nothing leaving the machine: no real model, no API key, `OFFLINE_MODE` on, and nothing kept once it stops.

```sh
uv run --group screenshots python tools/screenshots/run.py --up
```

It starts the stack, signs up an admin and a user, deploys `examples/plugins` with `owpp deploy`, prints the address and both accounts, and leaves it running. Then:

- **Sign in** at http://127.0.0.1:3000 as either account, and follow a plugin's By hand steps.
- **Deploy a change**: `run.py --up` prints the two variables to set, the address and the admin's token. With them set, `uv run owpp deploy --dir examples/plugins --only <id>`.
- **Make the model say something new**: add a fixture to `tools/screenshots/aimock/models.json`, above the catch-all at the end, and restart aimock alone: `docker compose -f tools/screenshots/compose.yaml restart aimock`. (aimock's `POST /__aimock/fixtures` adds fixtures without a restart, but after the file's, so the catch-all answers first for `screenshot-model`.)
- **See what Open-WebUI sent the model**: `curl 'http://127.0.0.1:4010/__aimock/journal?path=/v1/chat/completions'`. This is the quickest way to check an inlet: the messages there are the ones after every filter ran.
- **Stop it**: `docker compose -f tools/screenshots/compose.yaml down --volumes`.

### An isolated Open-WebUI of your own

A plugins repository can do the same with four files: a `compose.yaml` with Open-WebUI (the `-slim` image), aimock and its fixtures, and a script that signs up an admin and runs `owpp deploy`. This repository's `tools/screenshots/compose.yaml`, `aimock/models.json` and `run.py` are a starting point; drop the `static` service unless a plugin calls one of the services it stands in for.
