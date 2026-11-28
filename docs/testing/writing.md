# Writing a test

## A first test

```python
# plugins/stale_data/tests/test_stale_data.py
def test_only_admins_see_it(owui, plugin):
    """Signed out, a client gets 401; a user who is not an admin gets 403; an admin gets the
    dashboard.

    By hand: open /stale-data in a private window (the sign-in page), as a user (403), and as
    an admin (the dashboard).
    """
    # `plugin` is deployed and switched on: function.enable_started mounted its page
    ada = owui.add_user("Ada")
    assert owui.client().get("/stale-data").status_code == 401
    assert owui.client(ada).get("/stale-data").status_code == 403
    assert owui.client(owui.admin).get("/stale-data").status_code == 200
```

The pytest fixtures come with owpp. They are in a pytest plugin that is active wherever owpp is installed:

| Fixture | What it is |
| --- | --- |
| `owui` | The [test harness](harness.md) for this test: the real Open-WebUI, as it was after its startup. Before the next test, owpp puts it back as it was. |
| `plugin_dir` | The folder of the plugin that contains the test file (the nearest folder above the file with a `plugin.yaml`). |
| `plugin` | That plugin, bundled and deployed into `owui`: switched on, with the valves from the manifest. `system.startup.completed` has not been sent yet. |

Outside pytest, use `with Harness() as owui:` from `owpp.testing`. You can replace `plugin` with a fixture of your own, for example to load other valves or [stand-ins for code from git](kinds.md#code-from-git).

## Describe every test

Start each test with a docstring that a person can understand without the code. The docstring has two parts:

1. **What it checks**, in one or two sentences. Use the plugin's terms (pages, valves, chats), not the terms of the harness.
2. **`By hand:`** and then the steps that show the same behaviour on a live Open-WebUI. Say where to click, what to set and what you see.

A reviewer can repeat the **By hand** steps before a release. The README's `## Test` list also comes from them.

Some tests do not have steps that you can repeat:

- If you cannot repeat a test by hand, write this after `By hand:`, with the reason. For example: "not repeatable: Open-WebUI always loads a function under its own function id".
- If a test examines files and not behaviour, write which files to compare.

The documentation site builds its [test catalogue](../reference/test-catalogue.md) from these docstrings. The catalogue shows a missing docstring as a gap.

Give each test a name that is a sentence about the plugin: `test_a_message_without_an_image_stays_with_its_model`, not `test_inlet_2`. The catalogue and the [screenshots](../screenshots.md) refer to tests by name.

## Working through a plugin

1. List the behaviours: one for each sentence of the README, each valve and each branch in the code. Each early `return` is a branch. For each behaviour, write what it does and when it changes nothing.
2. Write the test for one behaviour before the code that makes it pass.
3. Run `owpp test <id> -- -k <name>` and make sure that the test fails. A test that never failed possibly tests nothing.
4. Make the test pass, with calls through the harness.
5. Do steps 2 to 4 for each behaviour.
6. Write the README's `## Test` list. First give what `owpp check`, `owpp bundle` and `owpp test` cover. Then give the live checks from the **By hand** steps.

In step 4, a direct call to a helper function skips all that these calls do:

- `owui.client(...).get(...)` uses the guards of the `routes` library.
- `owui.disable(...)` uses the runtime.
- `plugin.inlet(...)` supplies the arguments that Open-WebUI supplies.

The work is complete when all of these are true:

- Every valve and every branch has a test with both docstring parts.
- `owpp test <id>` passes.
- `owpp check <id> --strict` reports no failure and no warning.

## Testing logic directly

Some helpers do not use Open-WebUI, for example code that parses, merges or builds a page. To test such a helper, import the plugin's files as an editor reads them.

A plain import of `from shared import ...` or `from owpp.lib import ...` does not work. Each plugin has its own `shared.py` and its own library data. Use `plugin_source`:

```python
from owpp.testing import plugin_source


def test_a_title_is_trimmed(plugin_dir):
    src = plugin_source(plugin_dir)
    assert src.shared.clean_title("  Notes ") == "Notes"
```

`plugin_source` returns the modules `.shared`, `.function` and `.tool`. A module is `None` if the plugin does not have that file.

- Each file gets the plugin's own `shared.py`.
- Each file gets the libraries as its bundle has them, with the plugin's templates and `config.yaml`.
- As in Open-WebUI, `shared.py` is imported once for each bundle. `.shared` is the function's copy (the tool's copy if there is no function). `.tool_shared` is the tool's copy.
- If a file imports `open_webui` at its top, open a harness first: take the `owui` fixture.

Use `owui.load()` to test code that runs inside Open-WebUI (the function's class, routes, events and the tool). It tests the bundle that the deploy sends.

## Tips

- To change a file such as `config.yaml` for one test, copy the plugin folder to `tmp_path`. Then change the file and load the copy.
- `owpp test` runs pytest with `--import-mode=importlib`, so two plugins can each have a `tests/test_function.py`. A plain `pytest` run, such as this repository's own, needs unique names for test files.
- `plugin_stored_valves(..., ttl=)` keeps the valves in a cache. To make the next call read the valves again, clear `plugin.module._core_valves_cache`.
