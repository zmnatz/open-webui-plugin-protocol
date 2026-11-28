# The test harness

`owpp test` runs each plugin against the **test harness**: the real Open-WebUI, in the test process. Its app, routers, models, event sinks and plugin loader run as they do on an instance. The harness uses the Open-WebUI version that `owpp live` uses (v0.13.5). [ADR 0004](../adr/0004-unit-tests-run-the-real-open-webui.md) gives the reasons.

The `owui` fixture is the harness for one test. This page lists what the harness does. [Testing each kind of plugin](kinds.md) shows how to use the calls.

## owpp mirrors Open-WebUI

owpp follows the Open-WebUI version that it pins, and does not keep a copy of it:

- **The same Python.** owpp runs on the Python of Open-WebUI's image: Python 3.12 for v0.13.5. uv picks it for you.
- **The same packages.** The `test` extra installs the packages of Open-WebUI's slim image, at Open-WebUI's versions.
- **The same code.** The harness runs Open-WebUI's own code, and its model is aimock, as on the stack of `owpp live`.
- **The same settings.** The harness reads Open-WebUI's settings from the compose file of `owpp live`, so the unit tests and the live tests run the same Open-WebUI. For example, every user may use the models, and Open-WebUI makes no titles, tags or follow-up suggestions.

Where the harness still does part of Open-WebUI's work itself, a test checks it against Open-WebUI: the arguments of a direct `plugin.call`, and the session token of a user. A new Open-WebUI that changes them fails those tests.

When owpp moves to a new Open-WebUI, all three move with it. A test can then fail because Open-WebUI changed. That is the purpose: the test shows what the new Open-WebUI does. Change the plugin or the test to agree with it.

## How it runs

- **One Open-WebUI in each test process.** The first test imports Open-WebUI and runs its startup. The import takes some seconds.
- **The same start for each test.** Before each test, the harness puts the database, the app's routes and state, and the data folder back as they were after the startup.
- **Open-WebUI's own code.** The first run downloads the pinned Open-WebUI wheel to a cache and checks its hash. The cache is [`OWPP_CACHE_DIR`](../environment-variables.md#owpp_cache_dir). The wheel is not installed. The `test` extra installs the packages of Open-WebUI's slim image.
- **In parallel, if you want.** `owpp test -- -n auto` runs the tests in parallel (pytest-xdist, in the `test` extra). Each worker starts its own Open-WebUI, which takes some seconds. So use it when a repository has many tests.

## A new Open-WebUI for a test

The harness puts Open-WebUI back as it was after its startup. It does not undo a change that a plugin makes to Open-WebUI's own modules (for example, a function that it replaces). If a test needs a new Open-WebUI, ask for one. A new Open-WebUI takes some seconds, so this is off by default.

- **For one test:** mark the test with `@pytest.mark.fresh_open_webui`.
- **For every test:** set [`OWPP_FRESH_OPEN_WEBUI`](../environment-variables.md#owpp_fresh_open_webui) to `1`.
- **Outside pytest:** use `Harness(fresh=True)`.

The harness then stops Open-WebUI, removes its modules, and imports and starts it again, with a new data folder.

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
| `owui.send(user, message, model="mock-model", **body)` | Sends a chat request as the browser does (`POST /api/chat/completions`). Open-WebUI's chat pipeline runs: the filters that it picks for the chat (global filters, the model's filters, those in `filter_ids`), the tools in `tool_ids`, the model, and the outlets. `message` is the user's text, or the whole `messages` list. It returns the response. |
| `plugin.inlet(body, user=, chat_id=, model=)`, `plugin.outlet(...)` | One filter, run with Open-WebUI's own code (`process_filter_function`): the stored valves, the user's valves in `__user__["valves"]`, and the arguments that the handler takes. `model` is the id of the chat's model. Default: `"mock-model"`. |
| `plugin.call("method", *args, user=, chat_id=, **kwargs)` | Calls any method of the function's instance directly, with the stored valves applied. It supplies the arguments that Open-WebUI's chat middleware gives, if the method takes them: `__user__`, `__metadata__`, `__model__`, `__event_emitter__`, `__event_call__`, `__oauth_token__`, `__request__`, `__chat_id__` and `__message_id__`. It also supplies `__id__`, and `__app__`, as Open-WebUI gives it to an event handler. |
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
| `owui.chat_events` | `[(chat_id, event)]` sent through `__event_emitter__` or `__event_call__` in a call that the test made. |
| `owui.event_call_reply` | What `__event_call__` answers: what the user would reply. Default: `None`. |
| `owui.model_reply`, `owui.serve_model(id)`, `owui.completions` | For a plugin that asks a model: the answer of [the model](#the-model-aimock), another model id that it answers as, and every request that Open-WebUI sent it. |
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

## The model: aimock

Open-WebUI's model is [aimock](live.md#the-model-aimock), as on the stack of `owpp live`, at the same version. Open-WebUI reaches it over the OpenAI API, through its own chat completion code. Every user may use its models, as on that stack.

- **`owui.model_reply = "..."`** is the answer. aimock gives it as `mock-model`, streamed or not. Default: "Hello! I am the harness's model."
- **`owui.serve_model("theme-model")`** makes aimock also answer as `theme-model`. Open-WebUI then lists that model.
- **`owui.completions`** is aimock's journal: each request as Open-WebUI sent it to the model. Open-WebUI removes `metadata` before it sends a request, so the journal does not have it.

aimock starts the first time a test sets `model_reply` or calls `serve_model`. A test run that does neither does not start it. To run aimock, the harness uses the first of these that is installed:

1. Bun (`bunx`).
2. Node 20 or newer (`npx`).
3. Docker.

The first start downloads aimock.

## What the harness fakes

The harness changes these parts of Open-WebUI, so that a test can control them and see what they did:

- **The socket.** `sio.emit` records to `owui.emitted`. No browser is connected.
- **`__event_emitter__` and `__event_call__`.** In a call that the test makes, they record to `owui.chat_events`. `__event_call__` answers `owui.event_call_reply`.
- **Requirements.** Open-WebUI does not install a plugin's `requirements:` with pip. The harness records them in `owui.requirements`.

These parts of a real instance are not in the harness:

- a real model (aimock answers from fixtures);
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
