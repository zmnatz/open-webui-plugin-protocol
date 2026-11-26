# Adding or changing an example plugin

The examples in `examples/plugins/` are the protocol's showcase: each is a working plugin written to the plugin format, with tests, a README, screenshots from a real Open-WebUI, and a page on the docs site built from those (`tools/build_docs.py`). This is the whole process; a change to an existing example takes the steps its change touches.

## 1. Take the code, and credit it

An example may be adapted from someone else's function. Adapt it to the plugin format and keep what it does: the header moves to `plugin.yaml`, the code follows the [rules](../../skills/owpp/SKILL.md#the-rules-owpp-and-open-webui-hold-the-code-to), and its behaviour stays the same. Then **attribute** it in all five places:

- a comment at the top of `function.py`: the original's title, its authors, the copyright line, the source URL **pinned to a commit**, and the list of what changed;
- `plugin.yaml`: the original's `author`, `author_url`, `version` and `license`, and "Adapted from <title> by <author>." at the end of `description`;
- the README's first line, in bold: "Adapted from [<title>](<url>) by <author>", the licence, and what changed;
- `NOTICE.md`: what was adapted, from where, and the licence. MIT and BSD need their full text there with the copyright line. A repository with no licence file of its own falls under its parent project's (open-webui/functions: the Open WebUI License);
- the main `README.md`'s Licence line, and its Examples list.

Read the licence before taking code. With none at all, take only the idea and write the code here, and say so in the same five places.

Done when all five places name the author and the licence.

## 2. Test it

Follow [the owpp skill's testing steps](../../skills/owpp/references/testing.md): every valve and every branch has a test, each with a docstring that says what it checks and then **By hand**. The test names matter twice over: the screenshots link to them, and the [test catalogue](../testing/writing.md#describe-every-test) is built from the docstrings.

Done when `uv run owpp test --dir examples/plugins <id>` and `uv run owpp check --strict --dir examples/plugins <id>` pass, and `uv run ruff check .` and `uv run ruff format --check .` (what CI runs) pass over the adapted code too. Every `open_webui` name the plugin imports must exist in the mock, which `tests/test_stubs.py` checks: add any that is missing to `src/owpp/testing/mock.py` (with a test in `tests/test_mock.py`), then regenerate the editor stubs with `uv run python -m owpp.testing.stubs` and commit `src/open_webui-stubs/`.

## 3. Photograph it

Add `tools/screenshots/shots_<id>.py` ([adding one](../screenshots.md#adding-one)). Each test follows By hand steps in the browser, as the user or the admin, and calls `shot(...)` with `illustrates=[...]` naming the plugin tests it shows. Show the change: a before-and-after pair when the plugin changes something on screen (turn the function off for the before, and back on). Set up through the `api` fixture, and put back every valve and toggle you change.

The model is [aimock](../testing/live.md#the-model-aimock), answering from `tools/screenshots/aimock/models.json`. When the example needs a reply it does not give, add a fixture there, above the catch-all. A new model must also go in `tools/screenshots/gateway/` (`v1/models` and `model/info`): the LiteLLM sync gives it the read grant a user who is not an admin needs.

## 4. Check it live

When the plugin depends on something only the real Open-WebUI does (which model a request goes to, what reaches the model, a grant), add a test to `tools/live/test_live.py` ([the live suite](../testing/live.md#the-live-suite)). Its tests can read what Open-WebUI sent the model from aimock's journal.

## 5. Run it

```sh
uv run --group screenshots python tools/screenshots/run.py -- -k <id>   # its screenshots
uv run --group screenshots python tools/screenshots/run.py --live       # the live suite
```

Both start Open-WebUI in Docker; `run.py --up` starts it and leaves it running, to try something by hand ([trying things out in isolation](../testing/live.md#trying-things-out-in-isolation)). When `docker ps` says "permission denied", the user running the agent is not in the `docker` group: hand the user the command to run in their own terminal (`sudo -u "$USER" -g docker env "PATH=$PATH" uv run ...`), and work from the output they paste back. Each failure prints Open-WebUI's response body; its `detail` says what went wrong.

Done when the live suite passes and the new PNGs and `docs/screenshots/screenshots.json` are in the commit.

## 6. Document it

- The example's README: what it does, its valves, `## Test` from the By hand steps, `## Deploy`.
- `CHANGELOG.md` under Unreleased.
- Add the example to the Examples menu in `zensical.toml` (`{ "Title" = "examples/<id>.md" }`): its page is built either way, but only the menu leads to it.
- `uv run --group docs python tools/build_docs.py` builds the docs site with the new page and its screenshots; a broken link, or an example the menu leaves out, fails it. The button to the example's built function is added by the same build; nothing to write.

Done when the docs build passes, and `uv run pytest` passes.
