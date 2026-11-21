# On a real Open-WebUI

The mock runs the plugin's code, not Open-WebUI. What only Open-WebUI does (the chat pipeline that decides which filters and tools run, grants, sign-in providers, the browser) is checked on a real instance.

## By hand

Every test's docstring ends with **By hand**: the steps to see the same behaviour on a live Open-WebUI ([describe every test](writing.md#describe-every-test)). The README's `## Test` list gathers them. Before a release, or after a change to how the plugin meets Open-WebUI:

1. Deploy to a test instance, never the one people use: `owpp deploy --only <id> --dry-run`, then without `--dry-run` ([deploy](../commands/deploy.md)).
2. Follow the README's `## Test` steps, as an admin and as a user who is not one.
3. Say in the pull request which steps you did ([reviewing a change](../reviewing.md)).

## The live suite

This repository also runs its examples on a real Open-WebUI, automatically. It starts the same stack as the [screenshots](../screenshots.md) (Open-WebUI v0.13.4 as the `-slim` image, the [scripted model](#the-scripted-model) and mcpo, in Docker), deploys `examples/plugins` with `owpp deploy`, then runs the tests in `tools/live/`: the screenshots show what happens, the live suite asserts it.

```sh
uv run --group screenshots python tools/screenshots/run.py --live
```

It needs Docker, reachable by your user ([taking screenshots](../screenshots.md#taking-them) says how without the `docker` group), and no browser. On GitHub, `.github/workflows/live.yml` runs it by hand (**Actions > live > Run workflow**), on release tags, and on pull requests labelled `e2e`. It is not part of the normal test run: `uv run pytest` never collects it. It runs against v0.13.4 only.

| Test | What it shows on a real Open-WebUI |
| --- | --- |
| `test_the_deployed_functions_are_installed_and_active` | `owpp deploy` leaves the examples installed and active. |
| `test_a_public_tool_is_readable_by_a_user_who_is_not_the_owner` | `access: public` really shares a tool. The mock once agreed with a grant Open-WebUI ignores. |
| `test_the_scripted_model_answers_a_chat` | A chat reaches the model and its reply comes back. |
| `test_a_deployed_tool_is_offered_to_the_model_and_the_model_calls_it` | `tool_ids` puts the deployed tool's functions in front of the model, and the model's call comes back. |
| `test_an_outlet_turns_unfinished_reasoning_into_the_answer` | `clear_thinking_tags`'s outlet runs through `/api/chat/completed` and changes the reply. |
| `test_an_inlet_can_send_a_message_with_an_image_to_another_model` | `vision_router`'s inlet changes which model a request goes to, set by a valve. |

To add one, write a `test_*.py` in `tools/live/` with the `api` (admin) and `user_api` fixtures. Each call returns `(status, body)`, with the body on an error too, so put it in the assertion message: Open-WebUI says what went wrong in `detail`.

A plugins repository can run its own the same way: `tools/screenshots/` (`compose.yaml`, `fake_llm.py`, `run.py`) and `tools/live/` are small enough to copy.

### What the first runs found

None of these could the mock have shown:

- **A model needs a read grant before a user can use it.** Without one, a user who is not an admin gets "Model not found", including for a model a filter sends the request to.
- **Over the API, a tool call comes back to the caller.** With no saved chat, Open-WebUI returns the model's tool call (`finish_reason: "tool_calls"`) rather than running the tool; the browser's chat runs it.
- **`/api/chat/completed` needs a chat the user owns**, or it answers 404. In v0.13 it is kept for older clients: outlets also run inside the chat completion.

## The scripted model

`tools/screenshots/fake_llm.py` is a small OpenAI-compatible server, standing in for a real model in both the live suite and the screenshots. When Open-WebUI offers it a tool it has a script for, it calls that tool with fixed arguments, then replies with fixed text. So "ask the model to draw something" gives the same drawing every time, with no API key and no real model. It also:

- lists a second model, `screenshot-vision`, which answers that a picture reached it ([`vision_router`](../examples/vision_router.md));
- answers a message containing `[reasoning only]` with reasoning and no answer ([`clear_thinking_tags`](../examples/clear_thinking_tags.md));
- answers `/model/info` as a LiteLLM gateway would ([`litellm_model_sync`](../examples/litellm_model_sync.md)). That sync is what gives the models the read grant a user who is not an admin needs to use them;
- records every chat request it gets, at `GET http://127.0.0.1:9000/requests`, so a test can see what Open-WebUI sent.

When an example needs a reply it does not give, add one there: a trigger phrase, a model, or an entry in its `/model/info`.
