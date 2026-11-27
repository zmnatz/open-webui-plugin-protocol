# Screenshots on a real Open-WebUI

The screenshots show the example plugins on a real Open-WebUI, with a browser that follows their **By hand** steps. The unit tests run on the [test harness](testing/harness.md#what-the-harness-fakes), and the screenshots are the other half. They show a reviewer what each check looks like, and they catch what the harness cannot see, such as the page in a browser. The first run found two problems that every unit test had passed ([what it found](#what-it-found)).

The screenshots are in `docs/screenshots/`. The file `screenshots.json` there says which plugin tests each screenshot illustrates. The [test catalogue](reference/test-catalogue.md) shows each screenshot under those tests, and each example's page shows its own. [All screenshots](reference/screenshots.md) lists them with the Open-WebUI version and commit they come from.

## Taking them

You need Docker, and internet access, because the Excalidraw editor loads from esm.sh.

1. Make sure that your user can reach Docker (the `docker` group). Without the group, `sudo -u "$USER" -g docker env "PATH=$PATH" uv run ...` runs a command as you.
2. Install the tools with the first two commands below.
3. Take the screenshots with one of the `run.py` commands:

    ```sh
    uv sync --group screenshots                            # Python 3.11+
    uv run --group screenshots playwright install chromium
    uv run --group screenshots python tools/screenshots/run.py             # all of them
    uv run --group screenshots python tools/screenshots/run.py -- -k banner  # some of them
    uv run --group screenshots python tools/screenshots/run.py --keep      # leave it running
    ```

4. Commit the changed PNGs and `screenshots.json` with the change that they show.

A full run takes about two minutes after Docker has pulled the images. To check the examples without screenshots, run [the live suite](testing/live.md#this-repositorys-live-suite).

To take the screenshots on GitHub, run **Actions > screenshots > Run workflow** (`.github/workflows/screenshots.yml`). The workflow uploads the result as an artifact.

## What happens

`tools/screenshots/run.py` is [`owpp live`](commands/live.md) with this repository's files. It does these things:

1. It starts the stack of `owpp live` (Open-WebUI v0.13.5, the `-slim` image, and aimock as its models) with `tools/screenshots/compose.yaml` layered on it. That file adds [fixed files](testing/live.md#everything-else-fixed-files) in place of a LiteLLM gateway and mcpo. It also turns **iframe Sandbox Allow Same Origin** on by default (`DEFAULT_INTERFACE_SETTINGS`). The examples with pages in the Artifacts panel need it. Nothing is kept between runs.
2. It signs up a throwaway admin (the first account is always an admin) and adds a throwaway user.
3. It deploys `examples/plugins` with `owpp deploy`, as a plugin repository would.
4. It runs the scripts in `tools/screenshots/shots_*.py` with pytest and Playwright. The accounts sign in on Open-WebUI's own login page. Each script does what a person would do, and saves a screenshot at each step that is worth a look.
5. It removes the containers. With `--keep`, it leaves them running.

**The model** is [aimock](testing/live.md#the-model-aimock), which answers from the fixtures in `tools/screenshots/aimock/`. It gives the same answers on every run, with no API key and no real model.

## Adding one

1. In the applicable `shots_*.py` file (or a new one), write a test that does what a person would do.
2. Call `shot` at each step that is worth a screenshot:

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

3. Restore whatever the script changes (valves, a function that it switched off). Then the order in which the scripts run does not matter.

| Fixture | What it is |
| --- | --- |
| `admin`, `user`, `signed_out` | A browser page signed in as the admin, as the user, or not signed in. They are the [fixtures](testing/live.md#the-fixtures) of `owpp live`, which the live tests also use. |
| `api`, `user_api` | Open-WebUI's HTTP API as that account, to set things up: data to show, a valve to change. Here, a call returns only the body. Take screenshots of the browser only. |
| `shot(page, plugin, name, caption, illustrates=[...])` | Saves `docs/screenshots/<plugin>/<name>.png` and records it. `illustrates` names plugin tests, and the test catalogue shows the picture under them. |
| `send(page, text)` (imported from `conftest`) | Types a message into the chat and sends it when the input holds all of it. |

To type a chat message, use `send`, not `page.keyboard.type`. Since v0.13.5, the chat input accepts text while the page still loads, and can lose some of it. Do not put apostrophes in the message ([why](testing/live.md#tests-in-the-browser)).

## What it found

The first run, on 2026-11-19, found two problems with Excalidraw that no unit test could see:

- **The editor never loaded from esm.sh.** A comment in `templates/viewer.html` contained the names of the `esm.sh` and `hosted` block markers. The code that keeps one block and drops the other matched the marker in the comment, and also cut out the editor's imports. The page then failed with `convertToExcalidrawElements is not defined`. The unit tests checked only the page's head, and that no marker was left. That check passed because the code had removed too much. It is fixed, with a test that the script imports everything it uses.
- **On a default Open-WebUI, the editor answers 401.** The Artifacts panel sends no session cookie unless **iframe Sandbox Allow Same Origin** is on, and it is off by default. The plugin keeps this requirement and documents it ([why, and what it costs](libraries.md#pages-in-the-artifacts-panel-need-iframe-sandbox-allow-same-origin)).

The move to Open-WebUI v0.13.5 (2026-11-25) found a problem with Theme Designer Pro. Its OLED mode lasted only until the next page load. v0.13.5 then turned it into a black colour of that person's own. It is fixed ([what changed for v0.13.5](../examples/plugins/theme_designer_pro/README.md#what-changed-for-open-webui-v0135)), with a screenshot.
