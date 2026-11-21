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

It needs Docker, and internet access (the Excalidraw editor loads from esm.sh). A full run takes about two minutes once the images are pulled. Commit the changed PNGs and `screenshots.json` with the change they show. `.github/workflows/screenshots.yml` does the same on GitHub when run by hand (**Actions > screenshots > Run workflow**) and uploads the result as an artifact.

## What happens

`tools/screenshots/run.py`:

1. Starts `tools/screenshots/compose.yaml`. It holds Open-WebUI at the version the protocol targets (v0.13.4, the `-slim` image), a scripted model and [mcpo](https://github.com/open-webui/mcpo) with two servers. Nothing is kept between runs.
2. Signs up the admin (the first account always is) and adds a user, both throwaway.
3. Deploys `examples/plugins` with `owpp deploy`, exactly as a plugin repository would.
4. Runs the scripts in `tools/screenshots/shots_*.py` with pytest and Playwright. Each signs in on Open-WebUI's own login page, does what a person would, and saves a screenshot at each step worth seeing.
5. Removes the containers.

**The scripted model** (`tools/screenshots/fake_llm.py`) is a small OpenAI-compatible server. When Open-WebUI offers it a tool it has a script for, it calls that tool with fixed arguments, then replies with fixed text. So "ask the model to draw something" gives the same drawing every time, with no API key and no real model.

## Live assertions

`run.py --live` starts the same stack and deploys the same examples, then runs the assertions in `tools/live/` instead of a browser: the functions are installed and active, a user can see a public tool, the scripted model answers a chat and calls the deployed tool, and an outlet really changes what a reply becomes (`clear_thinking_tags`, adapted from Clear thinking tags by Haervwe, MIT) and an inlet reroutes a message with an image to another model by a valve (`vision_router`, adapted from Dynamic Vision Router by open-webui and atgehrhardt, Open WebUI License); the licences are in `NOTICE.md`. The scripted model records its requests at `GET :9000/requests`, which the vision router test reads. `.github/workflows/live.yml` runs it only on request: by hand (**Actions > live > Run workflow**), on release tags, and on a pull request labelled `e2e`. It is an end-to-end check, not part of the normal test run (`uv run pytest` never collects it). It tests only the targeted Open-WebUI version. Add an assertion as a `test_*.py` in `tools/live/`, using the `api` and `user_api` fixtures (each returns `(status, body)`).

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
