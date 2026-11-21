# Testing each kind of plugin

Recipes for what each kind of plugin does, with the calls that test it. Each is taken from a test that runs: the scaffolds [`owpp create`](../commands/create.md) writes, or the [examples](../examples/index.md). Every call is in [the mock](mock.md)'s reference.

## Filters

A filter is called with a chat request (`inlet`, `request`) or a reply (`outlet`), or a chunk of one (`stream`). Call it as Open-WebUI would, and assert on what it returns:

```python
def test_a_message_with_an_image_goes_to_the_vision_model(owui, plugin):
    """With `vision_model_id` set, a user's message with an image is sent to that model instead.

    By hand: set vision_model_id to a model that can see images, and choose another model in a
    chat as a user who is not an admin. Send a picture: the reply comes from the vision model.
    """
    owui.set_valves("vision_router", vision_model_id="vision-model")
    bob = owui.add_user("Bob")
    body = plugin.inlet(chat(IMAGE), user=bob, model="chat-model")  # chat(): a request body
    assert body["model"] == "vision-model"
```

- `plugin.inlet(body, user=, chat_id=, model=)` and `plugin.outlet(...)` fill in `__user__`, `__metadata__`, `__event_emitter__`, `__model__` and the rest, for the arguments the method takes. `plugin.call("request", body, ...)` and `plugin.call("stream", chunk)` reach the other two.
- **A reply** is what Open-WebUI 0.12+ hands an outlet: the last message has `content` and an `output` list, which the chat renders from. Change both. [`clear_thinking_tags`'s tests](https://github.com/zmnatz/open-webui-plugin-protocol/tree/main/examples/plugins/clear_thinking_tags/tests) build one.
- **Status lines and other events** the filter sends through `__event_emitter__` land in `owui.chat_events`, as `(chat_id, event)`.
- **Who it applies to** is the filter's business only once it is called: which filters run for a chat (global, per model, toggled by the user) is Open-WebUI's chat pipeline, which the mock does not have. Check that [by hand](live.md).

Examples: [`vision_router`](../examples/vision_router.md) (inlet), [`clear_thinking_tags`](../examples/clear_thinking_tags.md) (outlet), [`excalidraw`](../examples/excalidraw.md) (an outlet that adds to the reply).

## Actions

```python
def test_the_action_runs(owui, plugin):
    """The action runs on a message without failing.

    By hand: under a reply, click the action's button: no error toast appears.
    """
    user = owui.add_user("Ada")
    assert plugin.call("action", {"messages": []}, user=user) is None
```

With several buttons, `plugin.instance.actions` lists them, and the button pressed reaches the action as `__id__`: pass it, `plugin.call("action", body, user=user, __id__="summarise")`. An action that returns a page (an `HTMLResponse` with `content-disposition: inline`) is shown above the message: assert on `page.headers` and `page.body`.

## Pipes

```python
def test_it_answers_as_a_model(owui, plugin):
    """By hand: choose the pipe's model in a chat and say hello: it answers."""
    user = owui.add_user("Ada")
    assert plugin.call("pipes") == [{"id": "hello", "name": "Hello"}]
    assert plugin.call("pipe", {"messages": []}, user=user) == "Hello from Hello"
```

A pipe that streams returns an async generator; read it inside `owui.run(...)`, which runs code on the mock's event loop:

```python
chunks = plugin.call("pipe", {"messages": [], "stream": True}, user=user)


async def read():
    return "".join([chunk async for chunk in chunks])


assert owui.run(read()) == "Hello from Hello"
```

## Tools

A tool is installed by its function, so it is reached through `owui.tool(id)`, loaded from the stored code with its stored valves, as Open-WebUI would load it:

```python
def test_show_creates_the_drawing_and_hands_the_filter_an_artifact(owui, plugin):
    """By hand: in a new chat with the tool on, ask "draw a rectangle". The editor opens with one
    rectangle in it."""
    ada = owui.add_user("Ada")
    chat = owui.add_chat(ada)
    result = owui.tool("excalidraw").call(
        "show_excalidraw", elements=[RECT], chat_id=chat, user=ada
    )
    assert f'src="/excalidraw/view/{chat}"' in result["excalidraw_artifact"]
    assert owui.chat(chat).meta["excalidraw"]["elements"] == [RECT]
```

- `.call(method, ..., user=, chat_id=)` calls a method as the model would.
- `.specs` is what the model is told: each method's name, description and parameters. Test it when the docstrings are the instructions the model follows.
- That the model actually calls the tool is Open-WebUI's and the model's part. This repository's [live suite](live.md#the-live-suite) checks it, with aimock as the model.

Example: [`excalidraw`](../examples/excalidraw.md) (`tests/test_excalidraw_tool.py`).

## Events and scheduled jobs

An event function reacts to Open-WebUI. Send the event, then assert on what it changed:

```python
def test_saving_the_valves_syncs_every_mcpo_server_as_a_tool_server(owui, plugin, mcpo):
    """By hand: set MCPO_BASE_URL and MCPO_API_KEY and save: Admin Settings > External Tools
    lists one connection per mcpo server."""
    owui.set_valves("mcpo_sync", MCPO_BASE_URL=mcpo["url"], MCPO_API_KEY="mcpo-key")
    assert sorted(synced(owui)) == ["mcpo-filesystem", "mcpo-other", "mcpo-time"]
```

| Event | Sent by |
| --- | --- |
| `system.startup.completed` | `owui.startup()` |
| `function.valves_updated` | `owui.set_valves(id, ...)`, the admin saving the valves |
| `function.enabled`, `function.disabled` and their `*_started` | `owui.enable(id)`, `owui.disable(id)` |
| `function.updated`, `function.deleted` | `owui.update(id)`, `owui.delete(id)` |
| anything else (`config.banners.updated`, ...) | `owui.emit(name, subject=None, data=None)` |

What it sends on the socket is in `owui.emitted`. Background work it starts runs until it finishes or waits before the call returns. A **scheduled sync** (the `jobs` library's `PluginScheduledSync`) runs at startup and when its valves are saved, so those two calls test it; its repeat on a timer is the library's, tested in this repository.

Examples: [`mcpo_sync`](../examples/mcpo_sync.md), [`litellm_model_sync`](../examples/litellm_model_sync.md), [`page_banners`](../examples/page_banners.md).

## Pages and routes

A page is served by the app, so it is requested through `owui.client(user)`, which goes through the `routes` library's sign-in guard:

```python
def test_only_admins_see_it(owui, plugin):
    """By hand: open /stale-data in a private window, as a user (403), and as an admin."""
    owui.startup()
    assert owui.client().get("/stale-data").status_code == 401
    assert owui.client(owui.add_user("Ada")).get("/stale-data").status_code == 403
    assert owui.client(owui.admin).get("/stale-data").status_code == 200
```

Test each level a route allows and the one just below it: signed out, a user, an admin, and the owner of a chat against someone else (`owui.add_chat`, `owui.grant_chat`). Disable the function (`owui.disable(id)`) and the page answers 404. `follow_redirects=False` shows a sign-in redirect.

Example: [`stale_data`](../examples/stale_data.md).

## Installers and skills

What a function installs is in the tables once it is loaded. Test that it is there, that it goes with the function, and that it comes back:

```python
def test_the_tool_goes_with_the_function_and_comes_back_with_it(owui, plugin):
    """By hand: switch the function off: its tool is gone from Workspace > Tools. Switch it on:
    it is back. Delete the function: it is gone."""
    owui.disable("excalidraw")
    assert "excalidraw" not in owui.tools
    owui.enable("excalidraw")
    assert "excalidraw" in owui.tools
    owui.delete("excalidraw")
    assert "excalidraw" not in owui.tools
```

`owui.skills` holds the skills, and the grants are on each row (`access: public` puts a read grant for every user there).

## Code from git

A plugin whose tool, function or skills come from a `source:` is loaded with the files fetched from the pinned commit, which needs the network. To test offline, and to test only this folder's part, load it with stand-ins:

```python
@pytest.fixture
def plugin(owui, plugin_dir):
    return owui.load(plugin_dir, sources={"tool.py": TOOL, "SKILL.md": SKILL})
```

The upstream's own tests, for a [plugin taken whole from git](../plugin-format.md#a-whole-plugin-from-git), run with `owpp test --upstream`. Example: [`inline_visualizer`](../examples/inline_visualizer.md).

## Plugins that call other services

Point the plugin at a small HTTP server on `127.0.0.1`, started by a fixture, and clear the proxy variables so the request is not proxied. [`mcpo_sync`'s tests](https://github.com/zmnatz/open-webui-plugin-protocol/tree/main/examples/plugins/mcpo_sync/tests) run a stand-in mcpo proxy this way, and [`litellm_model_sync`'s](https://github.com/zmnatz/open-webui-plugin-protocol/tree/main/examples/plugins/litellm_model_sync/tests) a stand-in LiteLLM gateway.
