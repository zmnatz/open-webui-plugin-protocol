# The mock

`owpp test` runs each plugin against a **mock Open-WebUI**: an in-memory stand-in for the `open_webui.*` modules that plugins and the owpp libraries import, written against Open-WebUI v0.13. The `owui` fixture is one, fresh for each test. This page lists everything it does; [testing each kind of plugin](kinds.md) shows the calls in use.

## Loading and lifecycle

| Call | What happens |
| --- | --- |
| `owui.load(folder, valves=None, active=True, sources=None)` | Bundles the folder, stores it as a function and loads it as `function_<id>_<hex>`. The class is instantiated with the stored valves, and the runtime installs the tool and skills. Loading the same id again is an update. A `source:` plugin's files are fetched from git at the pinned commit, as the deploy does, once per test run. `sources={"tool.py": "..."}` stands in for them instead, so no network is needed. For a [whole plugin from git](../plugin-format.md#a-whole-plugin-from-git), `sources` holds the upstream folder's files, `plugin.yaml` included. |
| `owui.startup()` | `system.startup.completed`. |
| `owui.enable(id)` / `owui.disable(id)` | `function.enable_started` / `function.disable_started`, the flag change, then `function.enabled` / `function.disabled`. |
| `owui.set_valves(id, **valves)` | The admin saved the valves: they are stored, applied, and `function.valves_updated` is sent. |
| `owui.update(id)` | Bundles the folder again, reloads the function and sends `function.updated`. |
| `owui.delete(id)` | Removes the function and sends `function.deleted`. |
| `owui.emit(name, subject=None, data=None)` | Any event. It goes to every enabled Event function (and to the subject of a `*_started` event), with its stored valves applied, then to the event sinks. |

## Calling the plugin

| Call | What happens |
| --- | --- |
| `plugin.inlet(body, user=, chat_id=, model=)`, `plugin.outlet(...)` | A chat request or reply passes through a filter. `model` is the id of the model the chat is with, given to the filter as `__model__` (`{"id", "name"}`; `"mock-model"` by default). |
| `plugin.call("method", *args, user=, chat_id=, **kwargs)` | Calls any method of the function's instance. The `__user__`, `__metadata__`, `__request__`, `__id__`, `__event_emitter__`, `__chat_id__`, `__app__` and `__model__` arguments it accepts are filled in. |
| `owui.tool(id)` | The installed tool, loaded from its stored code with its stored valves. `.call("method", ..., user=, chat_id=)` calls a method as the model would, and `.specs` lists what the model is told. |
| `owui.client(user=None, **kw)` | A Starlette `TestClient` for the app, signed in as `user` or not signed in at all. Pass `follow_redirects=False` to see a sign-in redirect. |
| `owui.run(coroutine)` | Runs async code on the mock's event loop, then lets the background tasks it started run until they finish or wait. |
| `plugin.module`, `plugin.instance`, `plugin.valves`, `plugin.row` | The loaded module (for its helper functions), the instance, its valves, and its row in the functions table. |

## State to set up and assert on

| | |
| --- | --- |
| `owui.add_user(name, role="user")` | A user with a `token`. `owui.admin` owns the loaded functions. |
| `owui.add_chat(user, title=, messages=, meta=, updated_at=, files=[file ids])` | A saved chat, in a real SQLite database with Open-WebUI's `chat` and `chat_file` tables, so the `chat_data` library's SQL runs for real. `owui.chat(id)` reads it back. |
| `owui.grant_chat(chat_id, user, "read" \| "write")` | Gives a user other than the owner access to the chat. |
| `owui.add_note(user, ...)`, `owui.add_file(user, ...)` | Notes (timestamps in nanoseconds, as Open-WebUI stores them) and files. |
| `owui.functions`, `function_valves`, `tools`, `tool_valves`, `skills`, `models`, `users`, `config` | The tables, as dicts. `models` are model configs (`Models`, with v0.13.4's `ModelForm`, `ModelMeta` and `ModelParams`); `config` is what `Config.get` and `Config.upsert` read and write, the OpenAI connections (`openai.api_base_urls`, ...) included. |
| `owui.emitted` | `[(event, data)]` sent on the socket (`sio.emit`). |
| `owui.chat_events` | `[(chat_id, event)]` sent through `__event_emitter__`. |
| `owui.data_dir` | A temporary `DATA_DIR`, with `uploads/`, `cache/` and `build/` in it: `open_webui.config`'s `DATA_DIR`, `UPLOAD_DIR` and `CACHE_DIR`, and `open_webui.env`'s `FRONTEND_BUILD_DIR`. Removed when the mock closes. |
| `owui.app`, `owui.static_dir`, `owui.event_sinks` | The FastAPI app, with Open-WebUI's `/static` mount and its catch-all web app at `/`. Also `STATIC_DIR` and `EVENT_SINKS`. |

Signing in works like this: a request carries `Authorization: Bearer <user.token>` or a `token` cookie, and `get_current_user` returns that user. Chat access belongs to the owner, plus anyone given `grant_chat`.

## In an editor

owpp ships type stubs for `open_webui`, written from the mock: `open_webui-stubs`, installed with it. With owpp in the environment, an editor or a type checker resolves `from open_webui.models.chats import Chats` to what the mock has, which is what a test can reach. They are partial stubs: with the real Open-WebUI installed too, a module the mock does not have still resolves from it. In this repository, a test fails when an example imports an `open_webui` name the mock lacks, and another when the stubs are stale: rewrite them with `python -m owpp.testing.stubs` after changing the mock.

## What it is not

The mock implements what plugins call, written against Open-WebUI v0.13. It does not run Open-WebUI. Behaviour that only the real server has is out of reach:

- the chat pipeline that decides which filters and tools run;
- OIDC, LDAP and trusted-header sign-in;
- Redis, multiple workers, and `live_reload` across containers;
- permission groups and the real access-control rules.

**What it does not implement still imports.** Third-party plugins import parts of Open-WebUI the mock has no use for (`open_webui.models.messages`, `open_webui.models.users.User`, ...). Any `open_webui.*` module or name the mock lacks imports as a stand-in, so the plugin loads. Calling or using one raises `NotImplementedError` naming it ("the mock Open-WebUI has no open_webui.models.messages.Messages; add it to src/owpp/testing/mock.py"), so a test reaches it only by exercising code that really needs it.

So keep the [live checks](live.md) in each plugin's README under `## Test`, and treat a passing `owpp test` as "the plugin's own logic works", not "it works in Open-WebUI". When a plugin needs an Open-WebUI call the mock does not have, add it to `src/owpp/testing/mock.py` in this repository, with a test in `tests/test_mock.py`, and rewrite the stubs ([contributing](../contributing.md)), or open an issue naming the call.
