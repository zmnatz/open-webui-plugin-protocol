# The test harness

`owpp test` runs each plugin against the **test harness**: the real Open-WebUI, in the test process. Its app, routers, models, event sinks and plugin loader run as they do on an instance. The harness uses the Open-WebUI version that `owpp live` uses (v0.13.5). [ADR 0004](../adr/0004-unit-tests-run-the-real-open-webui.md) gives the reasons.

The `owui` fixture is the harness for one test. This page lists what the harness does. [Testing each kind of plugin](kinds.md) shows how to use the calls.

## How it runs

- **One Open-WebUI in each test process.** The first test imports Open-WebUI and runs its startup. The import takes some seconds.
- **The same start for each test.** Before each test, the harness puts the database, the app's routes and state, and the data folder back as they were after the startup.
- **Open-WebUI's own code.** The first run downloads the pinned Open-WebUI wheel to a cache and checks its hash. The cache is [`OWPP_CACHE_DIR`](../environment-variables.md#owpp_cache_dir). The wheel is not installed. The `test` extra installs the packages of Open-WebUI's slim image.
- **Open-WebUI's Python.** Open-WebUI v0.13.5 runs on Python 3.12. Run the tests with `uvx --python 3.12 --from 'owpp[test]' owpp test`.

## Loading and lifecycle

| Call | What happens |
| --- | --- |
| `owui.load(folder, id=None, valves=None, active=True, sources=None, content=None)` | Bundles the folder and deploys it. [Details](#loading-a-folder) follow. |
| `owui.startup()` | Sends `system.startup.completed`. |
| `owui.enable(id)` / `owui.disable(id)` | Switches the function on or off through Open-WebUI's API, as an admin does. Open-WebUI sends the events. |
| `owui.set_valves(id, **valves)` | Saves the function's valves through Open-WebUI's API, as an admin does. Open-WebUI sends `function.valves_updated`. |
| `owui.set_tool_valves(id, **valves)` | Saves a tool's valves through Open-WebUI's API. |
| `owui.update(id)` | Bundles the folder again and deploys it again. Open-WebUI sends `function.updated`. |
| `owui.delete(id)` | Deletes the function through Open-WebUI's API. |
| `owui.emit(name, subject=None, data=None)` | Sends any event through Open-WebUI's event sinks. [Details](#sending-an-event) follow. |

### Loading a folder

`owui.load()` deploys a plugin as [`owpp deploy`](../commands/deploy.md) does, through Open-WebUI's HTTP API:

1. It bundles the folder.
2. It creates the function, or updates the function if the id is already there.
3. It saves the valves.
4. If the manifest says `global: true`, it makes the function global.
5. If `active` is true, it switches the function on. Open-WebUI sends `function.enable_started`. Then the runtime installs the tool and the skills.

Its arguments:

| Argument | Meaning |
| --- | --- |
| `id` | The function's id. Default: the name of the folder. |
| `valves` | The valves to save. Default: the valves in the manifest. |
| `active` | If a new function is switched on. An update does not change this. |
| `sources` | Files that stand in for the files from git, so the load needs no network: `{"tool.py": "..."}`. For a [whole plugin from git](../plugin-format.md#a-whole-plugin-from-git), give the files of the upstream folder, `plugin.yaml` included. |
| `content` | Code to deploy in place of the bundle. |

Without `sources`, the files of a `source:` plugin come from git at the pinned commit, as in a deploy:

- With the `owui` fixture, owpp fetches each file once in each test run.
- A `Harness` that you make yourself fetches its own copies.
- To share the copies between harnesses, give each one the same `owpp.sources.Sources`: `Harness(sources=...)`. Then close that `Sources` yourself.

If Open-WebUI refuses the deploy, `load()` raises `OwppError` with the HTTP status and Open-WebUI's message. An example is a valve out of range: `HTTP 400`.

### Sending an event

`owui.emit()` sends the event as Open-WebUI does. Every Event function that is switched on gets the event, with its stored valves applied. For a `*_started` event about a function, that function also gets the event.

`subject` is the id of a function. For an event about something else, `subject` is the subject itself: `owui.emit("user.deleted", {"type": "user", "id": ada.id})`.

Open-WebUI catches an error in an Event function and logs it. So a test sees the error in the log (`caplog`), not as an exception.

## Calling the plugin

| Call | What happens |
| --- | --- |
| `plugin.inlet(body, user=, chat_id=, model=)`, `plugin.outlet(...)` | A chat request or reply goes through a filter. `model` is the id of the chat's model. The filter gets it as `__model__` (`{"id", "name"}`). Default: `"mock-model"`. |
| `plugin.call("method", *args, user=, chat_id=, **kwargs)` | Calls any method of the function's instance, with the stored valves applied. It supplies these arguments if the method accepts them: `__user__`, `__metadata__`, `__request__`, `__id__`, `__event_emitter__`, `__chat_id__`, `__app__` and `__model__`. |
| `owui.tool(id)` | The installed tool, loaded by Open-WebUI's loader with its stored valves. `.call("method", ..., user=, chat_id=)` calls a method as the model does. `.specs` is what Open-WebUI tells the model about the tool. |
| `owui.client(user=None, **kw)` | An `httpx.Client` for the app, signed in as `user`, or signed out. It follows redirects. To see a redirect, pass `follow_redirects=False`. |
| `owui.run(coroutine)` | Runs async code on Open-WebUI's event loop. Then the tasks that the code started run until they finish or wait. |
| `plugin.module`, `plugin.instance`, `plugin.valves`, `plugin.row` | The loaded module (for its helper functions), the instance that Open-WebUI keeps in its cache, its valves, and its row (`FunctionModel`). |

## State to set up and assert on

| | |
| --- | --- |
| `owui.add_user(name, role="user")` | A user with a sign-in record and a session `token`. `owui.admin` deploys the loaded functions. |
| `owui.add_chat(user, title=, messages=, meta=, updated_at=, files=[file ids])` | A saved chat, through Open-WebUI's `Chats` model. `owui.chat(id)` reads the chat. |
| `owui.grant_chat(chat_id, user, "read" \| "write")` | Gives access to the chat to a user who is not its owner, as Open-WebUI does: the chat goes into a folder of its owner, and the user gets the permission on the folder. |
| `owui.add_note(user, ...)`, `owui.add_file(user, ...)` | Notes and files, through Open-WebUI's models. |
| `owui.functions`, `function_valves`, `tools`, `tool_valves`, `skills`, `models`, `users` | The rows, by id. The harness reads them from the database each time. |
| `owui.config` | The config table, by key. A change is saved with Open-WebUI's `Config.upsert`. |
| `owui.emitted` | `[(event, data)]` sent on the socket (`sio.emit`). |
| `owui.chat_events` | `[(chat_id, event)]` sent through `__event_emitter__` in a call that the test made. |
| `owui.model_reply`, `owui.completions` | For a plugin that calls a model (`generate_chat_completion`): the answer of the model, and every request that the model got. |
| `owui.requirements` | The `requirements:` of each plugin that Open-WebUI loaded. The harness does not install them. |
| `owui.data_dir`, `owui.static_dir`, `owui.app` | Open-WebUI's `DATA_DIR` and `STATIC_DIR`, and its FastAPI app. |

`grants(row)`, from `owpp.testing`, gives the access grants of a tool, a skill or a model as an admin sets them: `[{"principal_type", "principal_id", "permission"}]`.

**The rows are copies.** A change to a row in a test does not go into the database. To change a row, use Open-WebUI's models inside `owui.run(...)`, or its API through `owui.client(owui.admin)`:

```python
from open_webui.models.models import Models

owui.run(Models.delete_model_by_id("gw.embed"))
owui.client(owui.admin).post(
    "/api/v1/tools/id/excalidraw/access/update", json={"access_grants": []}
)
```

## What the harness fakes

The harness changes these parts of Open-WebUI, so that a test can control them and see what they did:

- **The model.** `generate_chat_completion` answers `owui.model_reply` and records each request in `owui.completions`.
- **The socket.** `sio.emit` records to `owui.emitted`. No browser is connected.
- **`__event_emitter__`.** In a call that the test makes, it records to `owui.chat_events`.
- **Requirements.** Open-WebUI does not install a plugin's `requirements:` with pip. The harness records them in `owui.requirements`.

These parts of a real instance are not in the harness:

- the chat pipeline that decides which filters and tools run for a chat;
- a real model;
- OIDC, LDAP and trusted-header sign-in;
- Redis, multiple workers, and `live_reload` across containers;
- the web app in a browser. The harness serves only Open-WebUI's `index.html`.

Test these [on a real Open-WebUI](live.md). Keep the live checks in each plugin's README under `## Test`.

## A package that the slim image does not have

The `test` extra installs the packages of Open-WebUI's slim image. A plugin can import a package that only the full image has. Then the load stops with a `ModuleNotFoundError` that names the package and the version that Open-WebUI pins. An example is `add sentence-transformers==5.5.1 (Open-WebUI v0.13.5's pin) to your test dependencies`.

To use such a package in the tests:

1. Add the package, at that version, to the test dependencies of your repository.
2. Run the tests again.

## In an editor

An editor finds `open_webui` in the cached wheel. To get its folder:

```sh
uvx --from 'owpp[test]' owpp test --editor
```

Add the folder to the search path of your editor. For Pyright or Pylance, add it to `extraPaths`. For other tools, add it to `PYTHONPATH`.
