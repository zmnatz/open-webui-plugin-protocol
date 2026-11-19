# Testing plugins

Each plugin can carry its own unit tests in a `tests/` folder. `owpp test` runs them with pytest against a **mock Open-WebUI**: an in-memory stand-in for the `open_webui.*` modules that plugins and the owpp libraries import. Each plugin is bundled exactly as `owpp deploy` would bundle it, then loaded the way Open-WebUI loads a function. Lifecycle events, chat filter calls, tool calls and HTTP requests all go through the plugin's real code.

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

`owpp test` needs the `test` extra: pytest plus the packages Open-WebUI itself ships that plugins import at the top level (FastAPI, httpx, SQLAlchemy, aiohttp). `owpp init` scaffolds a `tests/test_<id>.py` that passes. The bundler ignores `tests/`, so tests are never deployed.

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

Outside pytest, use `with MockOpenWebUI() as owui:` from `owpp.testing`.

## Describe every test

Each test starts with a docstring that a person can read without reading the code:

1. **What it checks**, in one or two sentences, in the plugin's terms (pages, valves, chats), not the mock's.
2. **`By hand:`** the steps to see the same thing on a live Open-WebUI: where to click, what to set, what you should see. A reviewer can repeat them before a release, and they are the source for the README's `## Test` list.

When a test cannot be repeated by hand, its `By hand:` says so and why (for example, "not repeatable: Open-WebUI always loads a function under its own function id"). When it checks files rather than behaviour, it says which files to compare. The [test catalogue](reference/test-catalogue.md) on the documentation site is built from these docstrings, so a missing one shows up there as a gap.

## The mock

### Loading and lifecycle

| Call | What happens |
| --- | --- |
| `owui.load(folder, valves=None, active=True, sources=None)` | Bundles the folder, stores it as a function and loads it as `function_<id>_<hex>`. The class is instantiated with the stored valves, and the runtime installs the tool and skills. Loading the same id again is an update. `sources={"tool.py": "..."}` stands in for the files a `source:` plugin fetches from git, so no network is needed. |
| `owui.startup()` | `system.startup.completed`. |
| `owui.enable(id)` / `owui.disable(id)` | `function.enable_started` / `function.disable_started`, the flag change, then `function.enabled` / `function.disabled`. |
| `owui.set_valves(id, **valves)` | The admin saved the valves: they are stored, applied, and `function.valves_updated` is sent. |
| `owui.update(id)` | Bundles the folder again, reloads the function and sends `function.updated`. |
| `owui.delete(id)` | Removes the function and sends `function.deleted`. |
| `owui.emit(name, subject=None, data=None)` | Any event. It goes to every enabled Event function (and to the subject of a `*_started` event), with its stored valves applied, then to the event sinks. |

### Calling the plugin

| Call | What happens |
| --- | --- |
| `plugin.inlet(body, user=, chat_id=)`, `plugin.outlet(...)` | A chat request or reply passes through a filter. |
| `plugin.call("method", *args, user=, chat_id=, **kwargs)` | Calls any method of the function's instance. The `__user__`, `__metadata__`, `__request__`, `__id__`, `__event_emitter__`, `__chat_id__` and `__app__` arguments it accepts are filled in. |
| `owui.tool(id)` | The installed tool, loaded from its stored code with its stored valves. `.call("method", ..., user=, chat_id=)` calls a method as the model would, and `.specs` lists what the model is told. |
| `owui.client(user=None, **kw)` | A Starlette `TestClient` for the app, signed in as `user` or not signed in at all. Pass `follow_redirects=False` to see a sign-in redirect. |
| `owui.run(coroutine)` | Runs async code on the mock's event loop, then lets the background tasks it started run until they finish or wait. |
| `plugin.module`, `plugin.instance`, `plugin.valves`, `plugin.row` | The loaded module (for its helper functions), the instance, its valves, and its row in the functions table. |

### State to set up and assert on

| | |
| --- | --- |
| `owui.add_user(name, role="user")` | A user with a `token`. `owui.admin` owns the loaded functions. |
| `owui.add_chat(user, title=, messages=, meta=, updated_at=, files=[file ids])` | A saved chat, in a real SQLite database with Open-WebUI's `chat` and `chat_file` tables, so the `chat_data` library's SQL runs for real. `owui.chat(id)` reads it back. |
| `owui.grant_chat(chat_id, user, "read" \| "write")` | Gives a user other than the owner access to the chat. |
| `owui.add_note(user, ...)`, `owui.add_file(user, ...)` | Notes (timestamps in nanoseconds, as Open-WebUI stores them) and files. |
| `owui.functions`, `function_valves`, `tools`, `tool_valves`, `skills`, `models`, `users`, `config` | The tables, as dicts. `models` are model configs (`Models`, with v0.13.4's `ModelForm`, `ModelMeta` and `ModelParams`); `config` is what `Config.get` and `Config.upsert` read and write, the OpenAI connections (`openai.api_base_urls`, ...) included. |
| `owui.emitted` | `[(event, data)]` sent on the socket (`sio.emit`). |
| `owui.chat_events` | `[(chat_id, event)]` sent through `__event_emitter__`. |
| `owui.app`, `owui.static_dir`, `owui.event_sinks` | The FastAPI app, with Open-WebUI's `/static` mount and its catch-all web app at `/`. Also `STATIC_DIR` and `EVENT_SINKS`. |

Signing in works like this: a request carries `Authorization: Bearer <user.token>` or a `token` cookie, and `get_current_user` returns that user. Chat access belongs to the owner, plus anyone given `grant_chat`.

## What it is not

The mock implements what plugins call, written against Open-WebUI v0.13. It does not run Open-WebUI. Behaviour that only the real server has is out of reach:

- the chat pipeline that decides which filters and tools run;
- OIDC, LDAP and trusted-header sign-in;
- Redis, multiple workers, and `live_reload` across containers;
- permission groups and the real access-control rules.

So keep the live checks in each plugin's README under `## Test`, and treat a passing `owpp test` as "the plugin's own logic works", not "it works in Open-WebUI". When a plugin needs an Open-WebUI call the mock does not have, add it to `src/owpp/testing/mock.py`.

## Tips

- Test through the mock, not the module: `owui.client(...).get(...)` exercises the `routes` library's guards, and `owui.disable(...)` exercises the runtime. A direct call to a helper skips both.
- Valves the plugin reads with `plugin_stored_valves(..., ttl=)` are cached. Clear `plugin.module._core_valves_cache` to make the cache expire.
- A plugin that calls out over HTTP can be pointed at a small server on `127.0.0.1` (see `examples/plugins/mcpo_sync/tests/`). Clear the proxy variables so the request is not proxied.
- To change a file such as `config.yaml` for one test, copy the folder to `tmp_path` first and load the copy.
- `owpp test` runs pytest with `--import-mode=importlib`, so two plugins can both have a `tests/test_function.py`. A plain `pytest` run (this repository's own) needs unique test file names.
