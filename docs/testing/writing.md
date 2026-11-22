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
    owui.startup()  # system.startup.completed: it mounts its page
    ada = owui.add_user("Ada")
    assert owui.client().get("/stale-data").status_code == 401
    assert owui.client(ada).get("/stale-data").status_code == 403
    assert owui.client(owui.admin).get("/stale-data").status_code == 200
```

The fixtures come with owpp (a pytest plugin, registered whenever owpp is installed):

| Fixture | What it is |
| --- | --- |
| `owui` | A fresh `MockOpenWebUI` for this test. It is installed into `sys.modules` and taken out again afterwards, along with everything the plugin left there. |
| `plugin_dir` | The folder of the plugin the test file is in (the nearest `plugin.yaml` above it). |
| `plugin` | That plugin, bundled and loaded into `owui`: enabled, with the manifest's valves. Startup has not run yet. |

Outside pytest, use `with MockOpenWebUI() as owui:` from `owpp.testing`. A fixture of your own can replace `plugin`, to load with other valves or with [stand-ins for code from git](kinds.md#code-from-git).

## Describe every test

Each test starts with a docstring that a person can read without reading the code:

1. **What it checks**, in one or two sentences, in the plugin's terms (pages, valves, chats), not the mock's.
2. **`By hand:`** the steps to see the same thing on a live Open-WebUI: where to click, what to set, what you should see. A reviewer can repeat them before a release, and they are the source for the README's `## Test` list.

When a test cannot be repeated by hand, its `By hand:` says so and why (for example, "not repeatable: Open-WebUI always loads a function under its own function id"). When it checks files rather than behaviour, it says which files to compare. The [test catalogue](../reference/test-catalogue.md) on the documentation site is built from these docstrings, so a missing one shows up there as a gap.

Name the test as a sentence about the plugin: `test_a_message_without_an_image_stays_with_its_model`, not `test_inlet_2`. The catalogue and the [screenshots](../screenshots.md) refer to tests by name.

## Working through a plugin

1. **List the behaviours**: one per sentence of the README, one per valve, one per branch in the code (each early `return` is one): what it does, and when it leaves things alone.
2. **Write each test first, and see it fail**: `owpp test <id> -- -k <name>`. A test that has never failed may not be testing anything.
3. **Make it pass, through the mock**: `owui.client(...).get(...)` exercises the `routes` library's guards, `owui.disable(...)` exercises the runtime, `plugin.inlet(...)` fills in the arguments Open-WebUI would. A direct call to a helper skips all of them.
4. **Write the README's `## Test` list** from the By hand steps: what `owpp check`, `owpp bundle` and `owpp test` cover, then the live checks.

Done when every valve and every branch has a test with both paragraphs, `owpp test <id>` passes and `owpp check <id> --strict` reports nothing.

## Testing logic directly

A helper with no Open-WebUI in it (parsing, merging, building a page) can be tested by importing the plugin's files, the way an editor reads them. `from shared import ...` and `from owpp.lib import ...` would not work with a plain import, because every plugin has its own `shared.py` and its own library data, so use `plugin_source`:

```python
from owpp.testing import plugin_source


def test_a_title_is_trimmed(plugin_dir):
    src = plugin_source(plugin_dir)
    assert src.shared.clean_title("  Notes ") == "Notes"
```

It returns `.shared`, `.function` and `.tool` as modules (`None` for a file the plugin does not have). Each file gets the plugin's own `shared.py`, and libraries built the way its bundle has them, with its templates and `config.yaml`. `shared.py` is imported once for each bundle, like in Open-WebUI: `.tool_shared` is the tool's copy. A file that imports `open_webui` at its top needs the mock installed first (take the `owui` fixture). Anything that runs inside Open-WebUI (the function's class, routes, events, the tool) still goes through `owui.load()`, which tests the bundle that is deployed.

## Tips

- To change a file such as `config.yaml` for one test, copy the folder to `tmp_path` first and load the copy.
- `owpp test` runs pytest with `--import-mode=importlib`, so two plugins can both have a `tests/test_function.py`. A plain `pytest` run (this repository's own) needs unique test file names.
- Valves the plugin reads with `plugin_stored_valves(..., ttl=)` are cached. Clear `plugin.module._core_valves_cache` to make the cache expire.
