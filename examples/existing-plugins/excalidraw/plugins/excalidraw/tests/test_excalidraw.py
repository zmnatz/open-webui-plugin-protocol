"""Excalidraw against a mock Open-WebUI: `owpp test excalidraw` (docs/testing.md).

The function is a global filter that installs the `excalidraw` tool, serves the editor page
and its scene API under /excalidraw, and adds the editor to a reply as an artifact. What the
chat page and the Artifacts panel do with it is in the live tests (live/).
"""

import json
import re

import pytest

ID = "excalidraw"
RECT = {"type": "rectangle", "id": "a", "x": 0, "y": 0, "width": 160, "height": 80}
DB = {"type": "rectangle", "id": "b", "x": 300, "y": 0, "width": 160, "height": 80}
STATUS = (
    "The editor opens in the Artifacts side panel when your reply finishes. Do not paste a "
    "link, iframe or code for it."
)


def iframe(chat_id_in_url: str) -> str:
    return (
        f'<iframe src="/excalidraw/view/{chat_id_in_url}" title="Excalidraw" '
        'style="position:fixed;inset:0;width:100%;height:100%;border:0" '
        'allow="clipboard-read; clipboard-write"></iframe>'
    )


@pytest.fixture
def ada(owui):
    return owui.add_user("Ada")


@pytest.fixture
def chat(owui, ada):
    return owui.add_chat(ada)


def tool(owui):
    return owui.tool(ID)


def scene(owui, chat_id):
    return owui.chat(chat_id).meta["excalidraw"]


def token_for(owui, user, chat_id) -> str:
    page = owui.client(user).get(f"/excalidraw/view/{chat_id}")
    assert page.status_code == 200, page.text
    return re.search(r'const token = "([^"]+)";', page.text).group(1)


# ---- the tool, installed by the function ---------------------------------------------------


def test_the_function_is_global_and_installs_a_tool_everyone_can_use(owui, plugin):
    """By hand: after deploy, Admin Panel > Functions shows Excalidraw on and global, and
    Workspace > Tools lists Excalidraw for a user who is not an admin.
    """
    assert plugin.type == "filter"
    row = owui.functions[ID]
    assert (row.is_active, row.is_global) == (True, True)
    assert owui.tools[ID].access_grants == [
        {"principal_type": "user", "principal_id": "*", "permission": "read"}
    ]


def test_disabling_the_function_removes_the_tool_and_enabling_puts_it_back(owui, plugin):
    """By hand: switch Excalidraw off: Workspace > Tools no longer lists it. Switch it on:
    it is back.
    """
    owui.disable(ID)
    assert ID not in owui.tools
    owui.enable(ID)
    assert ID in owui.tools


def test_the_model_is_told_the_element_format_for_the_three_methods_that_take_elements(
    owui, plugin
):
    """By hand: Workspace > Tools > Excalidraw: show, upsert and replace describe the
    skeleton format; read and delete do not.
    """
    specs = {s["name"]: s for s in tool(owui).specs}
    assert sorted(specs) == [
        "delete_excalidraw_elements",
        "read_excalidraw",
        "replace_excalidraw_elements",
        "show_excalidraw",
        "upsert_excalidraw_elements",
    ]
    for name in ("show_excalidraw", "upsert_excalidraw_elements", "replace_excalidraw_elements"):
        assert "Elements use Excalidraw's skeleton format." in specs[name]["description"], name
        assert "elements" in specs[name]["parameters"]["properties"], name
    for name in ("read_excalidraw", "delete_excalidraw_elements"):
        assert "skeleton format" not in specs[name]["description"], name


def test_show_in_a_new_chat_creates_the_drawing_and_hands_back_the_editor(owui, plugin, ada, chat):
    """By hand: in a new chat, ask for a diagram of an API: the reply opens the editor in
    the side panel with the API box in it.
    """
    result = tool(owui).call("show_excalidraw", elements=[RECT], chat_id=chat, user=ada)
    assert result == {
        "status": STATUS,
        "version": 1,
        "note": "Use upsert_excalidraw_elements to change it and read_excalidraw to see the user's edits.",
        "excalidraw_artifact": iframe(chat),
    }
    saved = scene(owui, chat)
    assert (saved["version"], saved["writer"], saved["elements"]) == (1, "tool", [RECT])


def test_show_with_nothing_to_draw_starts_an_empty_drawing_once(owui, plugin, ada, chat):
    """Shown again with no elements, the drawing is left as it is: no new version.

    By hand: ask to see the drawing twice: the editor shows the same drawing.
    """
    assert tool(owui).call("show_excalidraw", chat_id=chat, user=ada)["version"] == 1
    assert scene(owui, chat)["elements"] == []
    assert tool(owui).call("show_excalidraw", chat_id=chat, user=ada)["version"] == 1


def test_show_with_elements_on_an_existing_drawing_adds_them(owui, plugin, ada, chat):
    """By hand: ask for a second box in a chat that has a drawing: both boxes are there."""
    tool(owui).call("show_excalidraw", elements=[RECT], chat_id=chat, user=ada)
    result = tool(owui).call("show_excalidraw", elements=[DB], chat_id=chat, user=ada)
    assert result["version"] == 2
    assert scene(owui, chat)["elements"] == [RECT, DB]


def test_a_temporary_chat_is_drawn_in_memory_and_its_id_is_escaped_in_the_url(owui, plugin, ada):
    """A temporary chat (`local:...`) has no row: its drawing lives in memory.

    By hand: in a temporary chat, ask for a diagram: the editor opens; after a restart the
    drawing is gone.
    """
    result = tool(owui).call("show_excalidraw", elements=[RECT], chat_id="local:abc", user=ada)
    assert result["excalidraw_artifact"] == iframe("local%3Aabc")
    read = json.loads(tool(owui).call("read_excalidraw", chat_id="local:abc", user=ada))
    assert read == {"version": 1, "elements": [RECT]}


@pytest.mark.parametrize("chat_id", [None, "", "../etc", "a" * 129])
def test_without_a_usable_chat_id_every_method_asks_to_send_a_message_first(
    owui, plugin, ada, chat_id
):
    """By hand: call the tool before the chat has a message: the model is told to send one."""
    with pytest.raises(RuntimeError, match="No chat id: send a message first, then retry."):
        tool(owui).call("read_excalidraw", chat_id=chat_id, user=ada)


def test_read_gives_the_model_a_compact_view_of_what_the_user_sees(owui, plugin, ada):
    """Deleted elements are left out, a shape's bound text becomes its label, an arrow names
    the shapes it joins, and Excalidraw's other fields are dropped.

    By hand: draw a box with text in it and an arrow from it to another box, delete a third,
    then ask what is in the drawing: two boxes (one labelled), and the arrow between them.
    """
    elements = [
        {**RECT, "seed": 7, "roughness": 1},
        {"type": "text", "id": "t", "containerId": "a", "text": "API", "x": 5, "y": 5},
        DB,
        {
            "type": "arrow",
            "id": "r",
            "x": 160,
            "y": 40,
            "points": [[0, 0], [140, 0]],
            "startBinding": {"elementId": "a"},
            "endBinding": {"elementId": "b"},
        },
        {**RECT, "id": "gone", "isDeleted": True},
    ]
    chat_id = owui.add_chat(
        ada, meta={"excalidraw": {"version": 4, "writer": "u", "elements": elements}}
    )
    assert json.loads(tool(owui).call("read_excalidraw", chat_id=chat_id, user=ada)) == {
        "version": 4,
        "elements": [
            {**RECT, "label": "API"},
            DB,
            {
                "id": "r",
                "type": "arrow",
                "x": 160,
                "y": 40,
                "points": [[0, 0], [140, 0]],
                "start": {"id": "a"},
                "end": {"id": "b"},
            },
        ],
    }


def test_read_of_a_chat_with_no_drawing_is_empty(owui, plugin, ada, chat):
    """By hand: in a new chat, ask what is in the drawing: nothing, version 0."""
    assert json.loads(tool(owui).call("read_excalidraw", chat_id=chat, user=ada)) == {
        "version": 0,
        "elements": [],
    }


def test_upsert_changes_elements_by_id_and_keeps_the_rest(owui, plugin, ada, chat):
    """By hand: with two boxes drawn, ask to colour one red: the other is untouched."""
    tool(owui).call("show_excalidraw", elements=[RECT, DB], chat_id=chat, user=ada)
    red = {**RECT, "strokeColor": "#ff0000"}
    message = tool(owui).call("upsert_excalidraw_elements", elements=[red], chat_id=chat, user=ada)
    assert message == "Updated. The open editor will show it shortly (version 2)."
    assert scene(owui, chat)["elements"] == [red, DB]


def test_an_element_the_model_sends_without_an_id_gets_one(owui, plugin, ada, chat):
    """So the model can change or delete it later.

    By hand: ask for a new shape, then ask to delete it: it goes.
    """
    tool(owui).call(
        "upsert_excalidraw_elements",
        elements=[{"type": "ellipse", "x": 1, "y": 2}],
        chat_id=chat,
        user=ada,
    )
    (added,) = scene(owui, chat)["elements"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{8}", added["id"])
    assert {k: v for k, v in added.items() if k != "id"} == {"type": "ellipse", "x": 1, "y": 2}


@pytest.mark.parametrize(
    "elements",
    [json.dumps([RECT]), RECT, [json.dumps(RECT)]],
    ids=["json-text", "one-object", "list-of-json-text"],
)
def test_elements_arrive_as_a_list_one_object_or_json_text(owui, plugin, ada, chat, elements):
    """Models pass elements every one of these ways; each one is drawn.

    By hand: with a small model, ask for a box: it is drawn.
    """
    tool(owui).call("upsert_excalidraw_elements", elements=elements, chat_id=chat, user=ada)
    assert scene(owui, chat)["elements"] == [RECT]


def test_replace_discards_everything_else(owui, plugin, ada, chat):
    """By hand: ask to start over with one box: only that box is left."""
    tool(owui).call("show_excalidraw", elements=[RECT, DB], chat_id=chat, user=ada)
    message = tool(owui).call("replace_excalidraw_elements", elements=[DB], chat_id=chat, user=ada)
    assert message == "Replaced (version 2)."
    assert scene(owui, chat)["elements"] == [DB]


def test_delete_removes_the_elements_and_the_text_bound_to_them(owui, plugin, ada, chat):
    """By hand: with a labelled box, ask to delete the box: its label goes with it."""
    label = {"type": "text", "id": "t", "containerId": "a", "text": "API"}
    tool(owui).call("show_excalidraw", elements=[RECT, label, DB], chat_id=chat, user=ada)
    message = tool(owui).call("delete_excalidraw_elements", ids=["a"], chat_id=chat, user=ada)
    assert message == "Deleted (version 2)."
    assert scene(owui, chat)["elements"] == [DB]


# ---- the filter's outlet: the editor added to the reply -------------------------------------


def reply_with(output: list, earlier: list | None = None) -> dict:
    return {
        "id": "m2",
        "messages": [
            *(earlier or []),
            {"id": "m1", "role": "user", "content": "draw"},
            {"id": "m2", "role": "assistant", "content": "Here it is.", "output": output},
        ],
    }


def tool_output(result: dict | str) -> dict:
    text = result if isinstance(result, str) else json.dumps(result)
    return {"type": "function_call_output", "output": text}


def test_a_reply_after_show_gets_the_editor_as_an_html_block_for_the_panel(owui, plugin, ada):
    """The outlet adds the tool's iframe to the reply, in its text and its output, so the
    chat page opens it in the Artifacts panel.

    By hand: ask for a diagram: the reply ends with the editor, and the side panel opens.
    """
    body = reply_with([tool_output({"excalidraw_artifact": iframe("c1")})])
    out = plugin.outlet(body, user=ada)
    message = out["messages"][-1]
    block = f"\n\n```html\n{iframe('c1')}\n```"
    assert message["content"] == "Here it is." + block
    assert message["output"][-1] == {
        "type": "message",
        "id": "msg_excalidraw_artifact_1",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": block.lstrip()}],
    }


def test_the_tool_result_is_found_even_with_text_after_it(owui, plugin, ada):
    """Open-WebUI can append context to a tool's result.

    By hand: with a knowledge base on the model, ask for a diagram: the editor still opens.
    """
    text = json.dumps({"excalidraw_artifact": iframe("c1")}) + "\n\n<context>more</context>"
    out = plugin.outlet(reply_with([tool_output(text)]), user=ada)
    assert out["messages"][-1]["content"].endswith(f"```html\n{iframe('c1')}\n```")


def test_the_editor_is_added_only_once_per_chat(owui, plugin, ada):
    """The panel keeps blocks from every reply, so a later reply does not add it again.

    By hand: ask for a diagram, then ask to see it again: one editor in the panel.
    """
    earlier = [{"role": "assistant", "content": f"```html\n{iframe('c1')}\n```"}]
    body = reply_with([tool_output({"excalidraw_artifact": iframe("c1")})], earlier)
    out = plugin.outlet(body, user=ada)
    assert out["messages"][-1]["content"] == "Here it is."
    assert len(out["messages"][-1]["output"]) == 1


def test_a_reply_without_the_tool_is_left_alone(owui, plugin, ada):
    """By hand: chat without asking for a drawing: no editor."""
    body = reply_with([tool_output({"other": "result"})])
    before = json.dumps(body)
    assert json.dumps(plugin.outlet(body, user=ada)) == before
    assert plugin.outlet({"messages": []}, user=ada) == {"messages": []}


# ---- the editor page and its scene API ------------------------------------------------------


def test_the_editor_opens_only_for_someone_who_can_write_to_the_chat(owui, plugin, ada, chat):
    """Someone else's chat, even one shared read-only, is Not found, so its existence is not given away.

    By hand: open /excalidraw/view/<chat id> signed out (401), as another user (404), as a
    user the chat is shared with read-only (404), and as its owner (the editor).
    """
    bob = owui.add_user("Bob")
    url = f"/excalidraw/view/{chat}"
    assert owui.client().get(url).status_code == 401
    assert owui.client(bob).get(url).status_code == 404
    owui.grant_chat(chat, bob, "read")
    assert owui.client(bob).get(url).status_code == 404
    page = owui.client(ada).get(url)
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "https://esm.sh/@excalidraw/excalidraw@0.18.0" in page.text
    assert "__TOKEN__" not in page.text and "__VERSION__" not in page.text


def test_the_scene_api_answers_with_the_pages_token_and_says_when_nothing_changed(
    owui, plugin, ada, chat
):
    """The page polls with `since`: an unchanged drawing answers `changed: false`.

    By hand: open the editor with the network tab open: every 1.5 s a request, answered
    `{"changed": false, ...}` until something is drawn.
    """
    tool(owui).call("show_excalidraw", elements=[RECT], chat_id=chat, user=ada)
    t = token_for(owui, ada, chat)
    api = owui.client()
    first = api.get(f"/excalidraw/api/scenes/{chat}", params={"t": t})
    assert first.status_code == 200
    assert first.headers["access-control-allow-origin"] == "*"
    body = first.json()
    assert (body["changed"], body["version"], body["elements"]) == (True, 1, [RECT])
    again = api.get(f"/excalidraw/api/scenes/{chat}", params={"t": t, "since": 1})
    assert again.json() == {"changed": False, "version": 1}


def test_the_scene_api_refuses_a_missing_wrong_or_other_chats_token(owui, plugin, ada, chat):
    """By hand: change one character of `t=` in a scene request: Not found."""
    other = owui.add_chat(ada)
    t_other = token_for(owui, ada, other)
    api = owui.client()
    for params in ({}, {"t": "nope"}, {"t": t_other}):
        assert api.get(f"/excalidraw/api/scenes/{chat}", params=params).status_code == 404


def test_a_drawing_saved_from_the_editor_is_a_new_version_by_that_editor(owui, plugin, ada, chat):
    """By hand: draw a box in the editor, then ask the model what is in the drawing: the box."""
    t = token_for(owui, ada, chat)
    api = owui.client()
    response = api.post(
        f"/excalidraw/api/scenes/{chat}",
        params={"t": t},
        content=json.dumps({"client": "tab-1", "elements": [RECT]}),
        headers={"content-type": "text/plain;charset=utf-8"},
    )
    assert response.status_code == 200
    assert response.json() == {"version": 1}
    saved = scene(owui, chat)
    assert (saved["writer"], saved["elements"]) == ("tab-1", [RECT])


@pytest.mark.parametrize(
    "body",
    ["not json", json.dumps({"elements": []}), json.dumps({"client": "x", "elements": {}})],
    ids=["not-json", "no-client", "elements-not-a-list"],
)
def test_a_malformed_save_is_refused(owui, plugin, ada, chat, body):
    """By hand: not reachable from the editor; a script posting garbage gets 400."""
    t = token_for(owui, ada, chat)
    response = owui.client().post(f"/excalidraw/api/scenes/{chat}", params={"t": t}, content=body)
    assert response.status_code == 400
    assert response.json()["detail"] == "expected {client, elements}"


def test_disabled_its_pages_are_gone(owui, plugin, ada, chat):
    """By hand: switch Excalidraw off and reload an open editor: Not found."""
    owui.disable(ID)
    assert owui.client(ada).get(f"/excalidraw/view/{chat}").status_code == 404


@pytest.mark.parametrize(
    "assets_url, hosted",
    [("https://assets.example.com/excalidraw/", True), ("javascript:alert(1)", False)],
)
def test_a_self_hosted_editor_is_loaded_from_its_url_and_a_bad_one_falls_back_to_esm_sh(
    owui, plugin_dir, monkeypatch, assets_url, hosted
):
    """EXCALIDRAW_ASSETS_URL in Open-WebUI's environment is where the editor's files are;
    one that is not a plain http(s) URL or path is ignored.

    By hand: set EXCALIDRAW_ASSETS_URL to your copy and restart: the editor loads its files
    from there (network tab), none from esm.sh.
    """
    monkeypatch.setenv("EXCALIDRAW_ASSETS_URL", assets_url)
    owui.load(plugin_dir)
    ada = owui.add_user("Ada")
    page = owui.client(ada).get(f"/excalidraw/view/{owui.add_chat(ada)}").text
    if hosted:
        assert 'await import("https://assets.example.com/excalidraw/editor.js");' in page
        assert "esm.sh" not in page
    else:
        assert "https://esm.sh/@excalidraw/excalidraw@0.18.0" in page
        assert "javascript:" not in page
