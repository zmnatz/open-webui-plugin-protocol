# Testing plugins

A plugin is tested in three layers, each catching what the one before cannot:

| Layer | Command | What it catches | Needs |
| --- | --- | --- | --- |
| **Check** | [`owpp check --strict`](commands/check.md) | The bundle does not build or compile; a name is used but never defined; a manifest is wrong; with `--since`, a change with no new version. | Nothing |
| **Unit tests** | [`owpp test`](commands/test.md) | The plugin's own logic is wrong: what a filter does to a chat, what a tool answers, who may open a page, what is installed and removed. Run against a [mock Open-WebUI](testing/mock.md). | The `test` extra |
| **On a real Open-WebUI** | each test's **By hand** steps, the README's `## Test` list | Open-WebUI does something the mock does not: the chat pipeline, grants, sign-in, the browser. | An instance |

Every change runs the first two, in CI. The third runs before a release, and when a change touches how the plugin meets Open-WebUI.

## In this section

| Page | For |
| --- | --- |
| [Writing a test](testing/writing.md) | A first test, the fixtures, the docstring every test carries, the order to work in. |
| [Testing each kind of plugin](testing/kinds.md) | Recipes: filters, actions, pipes, tools, events and scheduled jobs, pages, installers and skills, a function written elsewhere, code from git, plugins that call other services. |
| [The mock](testing/mock.md) | Every call and table of the mock Open-WebUI, and what it is not. |
| [On a real Open-WebUI](testing/live.md) | By hand checks; this repository's live suite, the examples deployed to a real Open-WebUI with aimock as its models; and the same stack as an isolated Open-WebUI to try things on. |
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

`owpp test` runs them with pytest. Each plugin is bundled exactly as `owpp deploy` would bundle it, then loaded the way Open-WebUI loads a function, so lifecycle events, filter calls, tool calls and HTTP requests all go through the plugin's real code. It needs the `test` extra: pytest plus the packages Open-WebUI itself ships that plugins import at the top level (FastAPI, httpx, SQLAlchemy, aiohttp). `owpp create` and `owpp init` scaffold a `tests/test_<id>.py` that passes. The bundler ignores `tests/`, so tests are never deployed. Every flag: [`owpp test`](commands/test.md).
