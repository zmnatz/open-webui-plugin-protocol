# Screenshots on a real Open-WebUI

The unit tests run against a [mock](testing.md#what-it-is-not). The screenshots are the other half: the example plugins deployed to a real Open-WebUI, with a browser following their **By hand** steps. They show a reviewer what each check looks like, and they catch what the mock cannot. The first run found two bugs that every unit test had passed (see [what it found](#what-it-found)).

They are in `docs/screenshots/`, with `screenshots.json` saying which plugin tests each one illustrates. The [test catalogue](reference/test-catalogue.md) shows each one under those tests, each example's page has its own, and [all screenshots](reference/screenshots.md) lists them with the Open-WebUI version and commit they were taken from.

## Taking them

```sh
uv sync --group screenshots                            # Python 3.11+
uv run --group screenshots playwright install chromium
uv run --group screenshots python tools/screenshots/run.py             # all of them
uv run --group screenshots python tools/screenshots/run.py -- -k banner  # some of them
uv run --group screenshots python tools/screenshots/run.py --keep      # leave it running
```

It needs Docker, which your user must be able to reach (in the `docker` group; without it, `sudo -u "$USER" -g docker env "PATH=$PATH" uv run ...` runs it as you), and internet access (the Excalidraw editor loads from esm.sh). A full run takes about two minutes once the images are pulled. Commit the changed PNGs and `screenshots.json` with the change they show. To check rather than photograph, see [the live suite](#the-live-suite). `.github/workflows/screenshots.yml` does the same on GitHub when run by hand (**Actions > screenshots > Run workflow**) and uploads the result as an artifact.

## What happens

`tools/screenshots/run.py`:

1. Starts `tools/screenshots/compose.yaml`. It holds Open-WebUI at the version the protocol targets (v0.13.4, the `-slim` image), a scripted model and [mcpo](https://github.com/open-webui/mcpo) with two servers. Nothing is kept between runs.
2. Signs up the admin (the first account always is) and adds a user, both throwaway.
3. Deploys `examples/plugins` with `owpp deploy`, exactly as a plugin repository would.
4. Runs the scripts in `tools/screenshots/shots_*.py` with pytest and Playwright. Each signs in on Open-WebUI's own login page, does what a person would, and saves a screenshot at each step worth seeing.
5. Removes the containers.

**The scripted model** (`tools/screenshots/fake_llm.py`) is a small OpenAI-compatible server. When Open-WebUI offers it a tool it has a script for, it calls that tool with fixed arguments, then replies with fixed text. So "ask the model to draw something" gives the same drawing every time, with no API key and no real model. It also:

- lists a second model, `screenshot-vision`, which answers that a picture reached it ([`vision_router`](../examples/plugins/vision_router));
- answers a message containing `[reasoning only]` with reasoning and no answer ([`clear_thinking_tags`](../examples/plugins/clear_thinking_tags));
- answers `/model/info` as a LiteLLM gateway would ([`litellm_model_sync`](../examples/plugins/litellm_model_sync)). That sync is what gives the models the read grant a user who is not an admin needs to use them;
- records every chat request it gets, at `GET http://127.0.0.1:9000/requests`, so a test can see what Open-WebUI sent.

## The live suite

The screenshots show what happens; the live suite asserts it. It is the end-to-end check: the same stack and the same deploy, then the tests in `tools/live/` instead of a browser.

```sh
uv run --group screenshots python tools/screenshots/run.py --live
```

It needs Docker and no browser. On GitHub, `.github/workflows/live.yml` runs it by hand (**Actions > live > Run workflow**), on release tags, and on pull requests labelled `e2e`. It is not part of the normal test run: `uv run pytest` never collects it. It runs against v0.13.4 only.

| Test | What it shows on a real Open-WebUI |
| --- | --- |
| `test_the_deployed_functions_are_installed_and_active` | `owpp deploy` leaves the examples installed and active. |
| `test_a_public_tool_is_readable_by_a_user_who_is_not_the_owner` | `access: public` really shares a tool. The mock once agreed with a grant Open-WebUI ignores. |
| `test_the_scripted_model_answers_a_chat` | A chat reaches the model and its reply comes back. |
| `test_a_deployed_tool_is_offered_to_the_model_and_the_model_calls_it` | `tool_ids` puts the deployed tool's functions in front of the model, and the model's call comes back. |
| `test_an_outlet_turns_unfinished_reasoning_into_the_answer` | `clear_thinking_tags`'s outlet runs through `/api/chat/completed` and changes the reply. |
| `test_an_inlet_can_send_a_message_with_an_image_to_another_model` | `vision_router`'s inlet changes which model a request goes to, set by a valve. |

To add one, write a `test_*.py` in `tools/live/` with the `api` (admin) and `user_api` fixtures. Each call returns `(status, body)`, with the body on an error too, so put it in the assertion message: Open-WebUI says what went wrong in `detail`.

**What the first runs found**, none of which the mock could have shown:

- **A model needs a read grant before a user can use it.** Without one, a user who is not an admin gets "Model not found", including for a model a filter sends the request to.
- **Over the API, a tool call comes back to the caller.** With no saved chat, Open-WebUI returns the model's tool call (`finish_reason: "tool_calls"`) rather than running the tool; the browser's chat runs it.
- **`/api/chat/completed` needs a chat the user owns**, or it answers 404. In v0.13 it is kept for older clients: outlets also run inside the chat completion.

## Adding one

In the right `shots_*.py` (or a new one), write a test as a person would do it, and call `shot`:

```python
def test_the_dashboard_lists_what_is_old(admin, shot):
    """By hand: as an admin, open /stale-data. ..."""
    admin.goto(f"{URL}/stale-data")
    admin.get_by_text("Q3 roadmap draft").wait_for()
    shot(
        admin,
        "stale_data",
        "dashboard",
        "What the caption says.",
        illustrates=["test_it_lists_what_is_older_than_the_threshold_and_not_the_rest"],
    )
```

| Fixture | What it is |
| --- | --- |
| `admin`, `user`, `signed_out` | A browser page signed in as the admin, as the user, or not at all. |
| `api`, `user_api` | Open-WebUI's HTTP API as that account, for setting things up: data to show, a valve to change. What is photographed goes through the browser. |
| `shot(page, plugin, name, caption, illustrates=[...])` | Saves `docs/screenshots/<plugin>/<name>.png` and records it. `illustrates` names plugin tests, which then show the picture in the catalogue. |

Put back whatever a script changes (valves, a function switched off), so the order the scripts run in does not matter.

## What it found

The first run, on 2026-11-19, found two things wrong with Excalidraw that no unit test could see:

- **The editor never loaded from esm.sh.** A comment in `templates/viewer.html` mentioned the `esm.sh` and `hosted` block markers by name. The code that keeps one block and drops the other matched the marker in the comment, and cut out the editor's imports with it. The page then failed with `convertToExcalidrawElements is not defined`. The unit tests only checked the page's head, and that no marker was left, which was true because too much had been removed. Fixed, with a test that the script imports everything it uses.
- **On a default Open-WebUI, the editor answers 401.** The Artifacts panel sends no session cookie unless **iframe Sandbox Allow Same Origin** is on, and Open-WebUI has it off by default. Turning it on lets any artifact's script reach Open-WebUI's origin, so the requirement is kept and documented rather than worked around ([why, and what it costs](libraries.md#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin); [issue #6](https://github.com/zmnatz/open-webui-plugin-protocol/issues/6)).
