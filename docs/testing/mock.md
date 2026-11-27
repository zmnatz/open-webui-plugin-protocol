# The mock

`owpp test` runs each plugin against a **mock Open-WebUI**. The mock holds its data in memory and stands in for the `open_webui.*` modules that plugins and the owpp libraries import. It follows Open-WebUI v0.13.

The `owui` fixture is a mock, new for each test. This page lists what the mock does. [Testing each kind of plugin](kinds.md) shows how to use the calls.

## Loading and lifecycle

| Call | What happens |
| --- | --- |
| `owui.load(folder, id=None, valves=None, active=True, sources=None, content=None)` | Bundles the folder, stores it as a function and loads it. [Details](#loading-a-folder) follow. |
| `owui.startup()` | Sends `system.startup.completed`. |
| `owui.enable(id)` / `owui.disable(id)` | Sends `function.enable_started` / `function.disable_started`, changes the flag, then sends `function.enabled` / `function.disabled`. |
| `owui.set_valves(id, **valves)` | Does what a save of the valves by an admin does: stores them, applies them and sends `function.valves_updated`. |
| `owui.update(id)` | Bundles the folder again, loads the function again and sends `function.updated`. |
| `owui.delete(id)` | Removes the function and sends `function.deleted`. |
| `owui.emit(name, subject=None, data=None)` | Sends any event. [Details](#sending-an-event) follow. |

### Loading a folder

`owui.load()` does this:

- It stores the function with the `meta` that a [deploy writes](../commands/deploy.md#the-ownership-marker), under the default marker. `meta.manifest` holds the header.
- It rewrites the imports in the stored code as Open-WebUI does on a save (`from utils` becomes `from open_webui.utils`).
- It loads the function as the module `function_<id>_<hex>`.
- It makes an instance of the class with the stored valves. The runtime then installs the tool and the skills.
- A second load of the same id is an update.

Its arguments:

| Argument | Meaning |
| --- | --- |
| `id` | The function's id. Default: the name of the folder. |
| `valves` | The stored valves. Default: the valves in the manifest. |
| `active` | If a new function starts enabled. An update does not change this. |
| `sources` | Files that stand in for the files from git, so the load needs no network: `{"tool.py": "..."}`. For a [whole plugin from git](../plugin-format.md#a-whole-plugin-from-git), give the files of the upstream folder, `plugin.yaml` included. |
| `content` | Code to store in place of the bundle. |

Without `sources`, the files of a `source:` plugin come from git at the pinned commit, as in a deploy:

- With the `owui` fixture, owpp fetches each file once in each test run.
- A `MockOpenWebUI` that you make yourself fetches its own copies.
- To share the copies between mocks, give each one the same `owpp.sources.Sources`: `MockOpenWebUI(sources=...)`. Then close that `Sources` yourself.

### Sending an event

`owui.emit()` sends the event to every enabled Event function, with its stored valves applied. For a `*_started` event, the function that is the subject also gets the event. Then the event goes to the event sinks.

`subject` is the id of a function. For an event about something else, `subject` is the subject itself: `owui.emit("user.deleted", {"type": "user", "id": ada.id})`.

## Calling the plugin

| Call | What happens |
| --- | --- |
| `plugin.inlet(body, user=, chat_id=, model=)`, `plugin.outlet(...)` | A chat request or reply goes through a filter. `model` is the id of the chat's model. The filter gets it as `__model__` (`{"id", "name"}`). Default: `"mock-model"`. |
| `plugin.call("method", *args, user=, chat_id=, **kwargs)` | Calls any method of the function's instance. It supplies these arguments if the method accepts them: `__user__`, `__metadata__`, `__request__`, `__id__`, `__event_emitter__`, `__chat_id__`, `__app__` and `__model__`. |
| `owui.tool(id)` | The installed tool, loaded from its stored code with its stored valves. `.call("method", ..., user=, chat_id=)` calls a method as the model does. `.specs` lists the information that the model gets. |
| `owui.client(user=None, **kw)` | A Starlette `TestClient` for the app, signed in as `user`, or signed out. To see a redirect to the sign-in page, pass `follow_redirects=False`. |
| `owui.run(coroutine)` | Runs async code on the mock's event loop. Then the background tasks that the code started run until they finish or wait. |
| `plugin.module`, `plugin.instance`, `plugin.valves`, `plugin.row` | The loaded module (for its helper functions), the instance, its valves, and its row in the functions table. |

## State to set up and assert on

| | |
| --- | --- |
| `owui.add_user(name, role="user")` | A user with a `token`. `owui.admin` owns the loaded functions. |
| `owui.add_chat(user, title=, messages=, meta=, updated_at=, files=[file ids])` | A saved chat in a real SQLite database with Open-WebUI's `chat` and `chat_file` tables. So the SQL of the `chat_data` library runs. `owui.chat(id)` reads the chat. |
| `owui.grant_chat(chat_id, user, "read" \| "write")` | Gives access to the chat to a user who is not its owner. |
| `owui.add_note(user, ...)`, `owui.add_file(user, ...)` | Notes and files. As in Open-WebUI, the timestamps of notes are in nanoseconds. |
| `owui.functions`, `function_valves`, `tools`, `tool_valves`, `skills`, `models`, `users`, `config` | The tables, as dicts. `models` holds model configs (`Models`, with `ModelForm`, `ModelMeta` and `ModelParams` of v0.13.4, the same in v0.13.5). `Config.get` and `Config.upsert` read and write `config`, which includes the OpenAI connections (`openai.api_base_urls`, ...). |
| `owui.emitted` | `[(event, data)]` sent on the socket (`sio.emit`). |
| `owui.chat_events` | `[(chat_id, event)]` sent through `__event_emitter__`. |
| `owui.model_reply`, `owui.completions` | For a plugin that calls a model (`generate_chat_completion`): the answer of the model, and every request that the model got. As with no pipelines, `process_pipeline_inlet_filter` returns the request unchanged. `get_task_model_generation_config` uses the task model that you name. |
| `owui.data_dir` | A temporary `DATA_DIR` with `uploads/`, `cache/` and `build/`. It supplies `DATA_DIR`, `UPLOAD_DIR` and `CACHE_DIR` of `open_webui.config`, and `FRONTEND_BUILD_DIR` of `open_webui.env`. The mock removes it when the mock closes. |
| `owui.app`, `owui.static_dir`, `owui.event_sinks` | The FastAPI app, with Open-WebUI's `/static` mount and its catch-all web app at `/`. Also `STATIC_DIR` and `EVENT_SINKS`. |

To sign in, a request has `Authorization: Bearer <user.token>` or a `token` cookie, and `get_current_user` returns that user. The owner of a chat has access to it. Other users have access only after `grant_chat`.

## In an editor

owpp includes type stubs for `open_webui`, generated from the mock. They are the `open_webui-stubs` package, which installs with owpp.

If owpp is in the environment, an editor or a type checker resolves `from open_webui.models.chats import Chats` to the mock's version. That is the version that a test can reach. The stubs are partial: if the real Open-WebUI is also installed, a module that the mock does not have resolves from Open-WebUI.

In this repository, a test fails when an example's own code imports an `open_webui` name that the mock does not have. A different test fails when the stubs are out of date. After you change the mock, run `python -m owpp.testing.stubs` to write the stubs again.

## What it is not

The mock has the parts of Open-WebUI v0.13 that plugins call. It does not run Open-WebUI. These behaviours of the real server are not in the mock:

- the chat pipeline that decides which filters and tools run;
- OIDC, LDAP and trusted-header sign-in;
- Redis, multiple workers, and `live_reload` across containers;
- permission groups and the real access control rules.

**An import still works if the mock does not implement it.** Third-party plugins import parts of Open-WebUI that the mock does not use (`open_webui.models.messages`, `open_webui.models.users.User`, ...). For each such `open_webui.*` module or name, the import gives a stand-in, so the plugin loads.

If code calls or uses the stand-in, it raises `NotImplementedError` with the name: "the mock Open-WebUI has no open_webui.models.messages.Messages; add it to src/owpp/testing/mock.py". So a test fails only when it runs code that needs the missing part.

A passing `owpp test` tells you that the plugin's own logic works. It does not tell you that the plugin works in Open-WebUI. Keep the [live checks](live.md) in each plugin's README under `## Test`.

If a plugin needs an Open-WebUI call that the mock does not have, [open an issue](https://github.com/zmnatz/open-webui-plugin-protocol/issues) that names the call. Or add the call in this repository ([contributing](../contributing.md)):

1. Add the call to `src/owpp/testing/mock.py`.
2. Add a test for it to `tests/test_mock.py`.
3. Run `python -m owpp.testing.stubs`.
