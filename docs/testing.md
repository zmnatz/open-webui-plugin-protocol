# Testing plugins

Test a plugin in three layers. Each layer finds problems that the layer before it cannot find.

| Layer | Command | What it catches | Needs |
| --- | --- | --- | --- |
| **Check** | [`owpp check --strict`](commands/check.md) | The bundle fails or does not compile. A name is used but never defined. A manifest is wrong. With `--since`, a change has no new version. | Nothing |
| **Unit tests** | [`owpp test`](commands/test.md) | The plugin's own logic is wrong. Examples: what a filter does to a chat, what a tool answers, who can open a page, what the plugin installs. The tests run against a [mock Open-WebUI](testing/mock.md). | The `test` extra |
| **On a real Open-WebUI** | [`owpp live`](commands/live.md) for the live tests. By hand, each test's **By hand** steps and the README's `## Test` list. | Open-WebUI does something that [the mock does not](testing/mock.md#what-it-is-not), such as the chat pipeline, sign-in or the browser. | Docker (`owpp live`), or an instance |

CI runs the first two layers on every change. If you set up a [live check](testing/ci.md#a-live-check), CI also runs the live tests. Do the **By hand** steps before a release. Also do them when a change affects how the plugin works with Open-WebUI.

## In this section

| Page | For |
| --- | --- |
| [Writing a test](testing/writing.md) | A first test, the pytest fixtures, the docstring that every test has, and the order of work. |
| [Testing each kind of plugin](testing/kinds.md) | Recipes for filters, actions, pipes, tools, events, scheduled jobs, pages, installers and skills. Also for outside code, code from git and other services. |
| [The mock](testing/mock.md) | Every call and table of the mock Open-WebUI, and what the mock is not. |
| [On a real Open-WebUI](testing/live.md) | Tests by hand, live tests in your repository, a throwaway Open-WebUI for experiments, and this repository's live suite. |
| [A plugin that already works](testing/existing-plugins.md) | Tests that an agent wrote for existing code: two examples, and the number of planted bugs that their tests caught. |
| [In CI](testing/ci.md) | A workflow that checks and tests every pull request. |

## Running the tests

Each plugin keeps its tests in a `tests/` folder:

```
plugins/excalidraw/
  plugin.yaml
  function.py
  tests/
    test_excalidraw_tool.py
    test_excalidraw_filter.py
```

```sh
uvx --from 'owpp[test]' owpp test               # every plugin with a tests/ folder
uvx --from 'owpp[test]' owpp test excalidraw    # just these
owpp test excalidraw -- -k token -x             # after --: arguments for pytest
```

`owpp test` runs the tests with pytest, against the mock. It needs the `test` extra. The extra has pytest, and the packages from Open-WebUI that plugins import at the top level (FastAPI, httpx, SQLAlchemy, aiohttp).

`owpp create` and `owpp init` write a `tests/test_<id>.py` that passes. The bundler ignores `tests/`, so a deploy never includes your tests.

To see how the command loads each plugin, and every flag, read [`owpp test`](commands/test.md).
