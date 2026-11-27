# Testing each kind of plugin

This page gives a recipe for what each kind of plugin does, with the calls that test it. Each recipe comes from a test that runs: in the scaffolds that [`owpp create`](../commands/create.md) writes, or in the [examples](../examples/index.md). The [mock](mock.md) page lists every call.

## Filters

Open-WebUI calls a filter with a chat request (`inlet`, `request`), a reply (`outlet`) or a chunk of a reply (`stream`). Call the filter as Open-WebUI does, and assert on the value that it returns:

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

- `plugin.inlet(body, user=, chat_id=, model=)` and `plugin.outlet(...)` supply the arguments that the method accepts: `__user__`, `__metadata__`, `__event_emitter__`, `__model__` and the others.
- To call the other two methods, use `plugin.call("request", body, ...)` and `plugin.call("stream", chunk)`.
- **A reply:** Open-WebUI 0.12 and later give an outlet a last message with `content` and an `output` list. The chat shows the reply from the list. Make your filter change both. The [`clear_thinking_tags` tests](https://github.com/zmnatz/open-webui-plugin-protocol/tree/main/examples/plugins/clear_thinking_tags/tests) build such a reply.
- **Events:** `owui.chat_events` records the status lines and other events that the filter sends through `__event_emitter__`, as `(chat_id, event)`.
- **Which chats use the filter:** Open-WebUI's chat pipeline decides which filters run for a chat. A filter can be global, set for a model or turned on by the user. The mock does not have this pipeline. Test it [on a real Open-WebUI](live.md).

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

If the action has several buttons, `plugin.instance.actions` lists them. The action gets the id of the button as `__id__`, so pass it: `plugin.call("action", body, user=user, __id__="summarise")`.

An action can return a page: an `HTMLResponse` with `content-disposition: inline`. Open-WebUI shows this page above the message. Assert on `page.headers` and `page.body`.

## Pipes

```python
def test_it_answers_as_a_model(owui, plugin):
    """By hand: choose the pipe's model in a chat and say hello: it answers."""
    user = owui.add_user("Ada")
    assert plugin.call("pipes") == [{"id": "hello", "name": "Hello"}]
    assert plugin.call("pipe", {"messages": []}, user=user) == "Hello from Hello"
```

A pipe that streams returns an async generator. Read it inside `owui.run(...)`, which runs code on the mock's event loop:

```python
chunks = plugin.call("pipe", {"messages": [], "stream": True}, user=user)


async def read():
    return "".join([chunk async for chunk in chunks])


assert owui.run(read()) == "Hello from Hello"
```

## Tools

A function installs its tool, so get the tool with `owui.tool(id)`. As Open-WebUI does, the mock loads the tool from its stored code, with its stored valves:

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

- `.call(method, ..., user=, chat_id=)` calls a method as the model does.
- `.specs` is the information that the model gets: the name, description and parameters of each method. If the model follows the docstrings as instructions, test `.specs`.
- Open-WebUI and the model decide if the model calls the tool. This repository's [live suite](live.md#this-repositorys-live-suite) tests this, with aimock as the model.

Example: [`excalidraw`](../examples/excalidraw.md) (`tests/test_excalidraw_tool.py`).

## Events and scheduled jobs

An event function reacts to events from Open-WebUI. Send the event, then assert on what the function changed:

```python
def test_saving_the_valves_syncs_every_mcpo_server_as_a_tool_server(owui, plugin, mcpo):
    """By hand: set MCPO_BASE_URL and MCPO_API_KEY and save: Admin Settings > Integrations
    lists one connection per mcpo server."""
    owui.set_valves("mcpo_sync", MCPO_BASE_URL=mcpo["url"], MCPO_API_KEY="mcpo-key")
    assert sorted(synced(owui)) == ["mcpo-filesystem", "mcpo-other", "mcpo-time"]
```

| Event | Sent by |
| --- | --- |
| `system.startup.completed` | `owui.startup()` |
| `function.valves_updated` | `owui.set_valves(id, ...)`, as when the admin saves the valves |
| `function.enabled`, `function.disabled` and their `*_started` events | `owui.enable(id)`, `owui.disable(id)` |
| `function.updated`, `function.deleted` | `owui.update(id)`, `owui.delete(id)` |
| All other events (`config.banners.updated`, ...) | `owui.emit(name, subject=None, data=None)` |

`owui.emitted` records what the function sends on the socket. Before a call returns, the background work that the function starts runs until it finishes or waits.

A **scheduled sync** (`PluginScheduledSync` from the `jobs` library) runs at startup, when an admin enables the function, and when an admin saves its valves. To test it, use `owui.startup()`, `owui.enable(id)` or `owui.set_valves(id, ...)`. The library repeats the sync on a timer, and this repository tests that timer.

Examples: [`mcpo_sync`](../examples/mcpo_sync.md), [`litellm_model_sync`](../examples/litellm_model_sync.md), [`page_banners`](../examples/page_banners.md), [`theme_designer_pro`](../examples/theme_designer_pro.md) (handlers for user events, model events and shutdown).

## Pages and routes

The app serves a page, so request it through `owui.client(user)`. The request goes through the sign-in guard of the `routes` library:

```python
def test_only_admins_see_it(owui, plugin):
    """By hand: open /stale-data in a private window, as a user (403), and as an admin."""
    owui.startup()
    assert owui.client().get("/stale-data").status_code == 401
    assert owui.client(owui.add_user("Ada")).get("/stale-data").status_code == 403
    assert owui.client(owui.admin).get("/stale-data").status_code == 200
```

- For each route, test each access level that it allows and the level below it: signed out, user, admin.
- If a route belongs to a chat, test the owner of the chat and a different user (`owui.add_chat`, `owui.grant_chat`).
- Disable the function (`owui.disable(id)`), and make sure that the page answers 404.
- To see a redirect to the sign-in page, use `owui.client(user, follow_redirects=False)`.

Example: [`stale_data`](../examples/stale_data.md).

## Installers and skills

After the function loads, the mock's tables contain what it installed. Test that each item is there, that it goes when the function goes, and that it comes back:

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

`owui.skills` contains the skills. The rows in `owui.tools` and `owui.skills` hold their grants: `access: public` puts a read grant for every user there.

## A function written elsewhere

Some functions come from outside owpp: pasted into Open-WebUI, or written for it by other people. To bring one in, use [`owpp import`](../commands/import.md) (`--instance <id>`, a file, or the URL of its repository). The command writes the plugin folder and a first test. Then use the recipes on this page for the kind of function that you have.

With such code, note these points:

- **An `open_webui` import at the top of the file** loads in the mock. The mock stands in for those modules as they are in Open-WebUI v0.13. Code written for an older Open-WebUI can fail where v0.13 also fails (for example, a model method that is now a coroutine). Report this as a finding about the function, not about the test.
- **A name that the mock does not have** imports, but raises an error when the code uses it: [what the mock is not](mock.md#what-it-is-not).
- **A service that the function calls** needs a stand-in, as for [any plugin that calls other services](#plugins-that-call-other-services).

For two examples with their tests, see [a plugin that already works](existing-plugins.md).

## Code from git

A plugin can take its tool, function or skills from a `source:`. A load then fetches the files from the pinned commit, which needs the network. To test offline, and to test only the files in your folder, load the plugin with stand-ins:

```python
@pytest.fixture
def plugin(owui, plugin_dir):
    return owui.load(plugin_dir, sources={"tool.py": TOOL, "SKILL.md": SKILL})
```

For a [plugin taken whole from git](../plugin-format.md#a-whole-plugin-from-git), `owpp test --upstream` also runs the tests of the upstream plugin. Example: [`inline_visualizer`](../examples/inline_visualizer.md).

## Plugins that call other services

1. Write a fixture that starts a small HTTP server on `127.0.0.1`.
2. In the fixture, clear the proxy variables, so that requests to the server do not go through a proxy.
3. Set the plugin to use the address of that server.

The [`mcpo_sync` tests](https://github.com/zmnatz/open-webui-plugin-protocol/tree/main/examples/plugins/mcpo_sync/tests) use this method for an mcpo proxy. The [`litellm_model_sync` tests](https://github.com/zmnatz/open-webui-plugin-protocol/tree/main/examples/plugins/litellm_model_sync/tests) use it for a LiteLLM gateway.
