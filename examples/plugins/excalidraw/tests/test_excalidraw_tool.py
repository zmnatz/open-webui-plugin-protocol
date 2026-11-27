"""The Excalidraw tool and the plugin runtime that installs it, on the test harness.

Run with `owpp test excalidraw`. The `owui` and `plugin` fixtures come with owpp
(docs/testing.md): `plugin` is this folder, bundled as the deploy would and loaded.
"""

import json

import pytest

from owpp.testing import grants

RECT = {"type": "rectangle", "id": "a", "x": 0, "y": 0, "width": 160, "height": 80}


@pytest.fixture
def ada(owui):
    return owui.add_user("Ada")


@pytest.fixture
def tool(owui, plugin):
    return owui.tool("excalidraw")


def share(owui, tool_id: str, access_grants: list[dict]) -> None:
    """An admin changes who the tool is shared with (Workspace > Tools > Access)."""
    res = owui.client(owui.admin).post(
        f"/api/v1/tools/id/{tool_id}/access/update", json={"access_grants": access_grants}
    )
    assert res.status_code == 200, res.text


# ---- installed by its function ---------------------------------------------------------


def test_loading_the_function_installs_the_tool_for_everyone(owui, plugin):
    """Loading the function installs an Excalidraw tool, marked as the function's own and readable
    by everyone.

    By hand: after installing the function, Workspace > Tools lists Excalidraw, and a user who
    is not an admin can turn it on in a chat.
    """
    tool = owui.tools["excalidraw"]
    assert tool.name == "Excalidraw"
    assert tool.meta.manifest["parent_function_id"] == "excalidraw"
    assert grants(tool) == [{"principal_type": "user", "principal_id": "*", "permission": "read"}]


def test_a_tool_an_earlier_runtime_shared_with_anyone_is_shared_with_every_user(owui, plugin):
    """Runtimes before this one granted a public tool to Open-WebUI's no-auth `anyone`
    audience, which it ignores for tools, so only admins could use it. The next sync swaps
    exactly that grant for every signed-in user, and keeps grants an admin added.

    By hand: on an instance deployed with an earlier owpp, sign in as a user who is not an
    admin; Excalidraw is missing from the tools. Deploy this version. The user
    now sees it, and any group an admin shared it with still has it.
    """
    from open_webui.models.access_grants import AccessGrants

    group = {"principal_type": "group", "principal_id": "designers", "permission": "write"}
    anyone = {"principal_type": "anyone", "principal_id": "*", "permission": "read"}
    owui.run(AccessGrants.set_access_grants("tool", "excalidraw", [anyone, group]))
    owui.update("excalidraw")  # the deploy of this version
    assert grants(owui.tools["excalidraw"]) == [
        group,
        {"principal_type": "user", "principal_id": "*", "permission": "read"},
    ]


def test_grants_an_admin_set_are_left_alone(owui, plugin):
    """Once the tool is installed, its sharing is the admin's: a later sync changes nothing.

    By hand: share the Excalidraw tool with one group only, then deploy again. It is still
    shared with just that group.
    """
    only = [{"principal_type": "group", "principal_id": "designers", "permission": "read"}]
    share(owui, "excalidraw", only)
    owui.update("excalidraw")
    assert grants(owui.tools["excalidraw"]) == only


def test_the_tool_goes_with_the_function_and_comes_back_with_it(owui, plugin):
    """Disabling the function removes the tool, enabling puts it back, and deleting the function
    removes it.

    By hand: under Admin Panel > Functions switch Excalidraw off: it is gone from Workspace >
    Tools. Switch it on: it is back. Delete the function: it is gone.
    """
    owui.disable("excalidraw")
    assert "excalidraw" not in owui.tools
    owui.enable("excalidraw")
    assert "excalidraw" in owui.tools
    owui.delete("excalidraw")
    assert "excalidraw" not in owui.tools


def test_a_hand_made_tool_with_the_same_id_is_left_alone(owui, plugin_dir):
    """A tool with the id excalidraw that someone made by hand is neither overwritten when the
    function loads nor removed when it is disabled.

    By hand: with the function deleted, create a tool with the id excalidraw under Workspace >
    Tools, then install the function. Your tool's code is unchanged. Disable the function: your
    tool is still there.
    """
    form = {"id": "excalidraw", "name": "Mine", "content": "class Tools: pass\n", "meta": {}}
    res = owui.client(owui.admin).post("/api/v1/tools/create", json=form)
    assert res.status_code == 200, res.text
    owui.load(plugin_dir)
    assert owui.tools["excalidraw"].content == "class Tools: pass\n"
    owui.disable("excalidraw")
    assert "excalidraw" in owui.tools  # not this plugin's, so not removed either


def test_every_method_the_model_sees_explains_the_element_format(tool):
    """The model is offered the five drawing methods. Those that take elements explain the skeleton
    format, and arguments Open-WebUI fills in, such as __metadata__, are not shown as
    parameters.

    By hand: open the tool under Workspace > Tools and read the docstrings of these five
    methods. What the model is actually sent is only visible in this test.
    """
    specs = {s["name"]: s for s in tool.specs}
    assert set(specs) == {
        "show_excalidraw",
        "read_excalidraw",
        "upsert_excalidraw_elements",
        "replace_excalidraw_elements",
        "delete_excalidraw_elements",
    }
    for name in ("show_excalidraw", "upsert_excalidraw_elements", "replace_excalidraw_elements"):
        assert "skeleton format" in specs[name]["description"], name
    assert "__metadata__" not in specs["show_excalidraw"]["parameters"]["properties"]


# ---- the drawing ---------------------------------------------------------------------


def scene(owui, chat_id):
    return owui.chat(chat_id).meta["excalidraw"]


def test_show_creates_the_drawing_and_hands_the_filter_an_artifact(owui, tool, ada):
    """show_excalidraw stores the elements in the chat (version 1, written by the tool) and returns
    an artifact whose iframe opens /excalidraw/view/<chat id>.

    By hand: in a new chat with the tool on, ask "draw a rectangle". The editor opens at this
    chat's /excalidraw/view/ URL with one rectangle in it.
    """
    chat = owui.add_chat(ada)
    result = tool.call("show_excalidraw", elements=[RECT], chat_id=chat, user=ada)
    assert result["version"] == 1
    assert f'src="/excalidraw/view/{chat}"' in result["excalidraw_artifact"]
    assert scene(owui, chat)["elements"] == [RECT]
    assert scene(owui, chat)["writer"] == "tool"


def test_show_again_without_elements_changes_nothing(owui, tool, ada):
    """Calling show_excalidraw again with no elements only shows the drawing; the version stays the
    same.

    By hand: after the first drawing, ask "show the drawing again". It is the same drawing.
    """
    chat = owui.add_chat(ada)
    tool.call("show_excalidraw", elements=[RECT], chat_id=chat)
    assert tool.call("show_excalidraw", chat_id=chat)["version"] == 1


def test_the_drawing_is_kept_beside_the_chats_other_metadata(owui, tool, ada):
    """The drawing is stored alongside the chat's other metadata, such as its tags, and they are
    kept.

    By hand: tag a chat, then have the model draw in it. The tag is still there.
    """
    chat = owui.add_chat(ada, meta={"tags": ["work"]})
    tool.call("show_excalidraw", elements=[RECT], chat_id=chat)
    assert owui.chat(chat).meta["tags"] == ["work"]


def test_upsert_merges_by_id_and_gives_new_elements_an_id(owui, tool, ada):
    """upsert_excalidraw_elements updates the elements whose id matches and adds the rest, giving
    each new one an id.

    By hand: after a rectangle, ask the model to "move the rectangle right and add the text hi".
    The rectangle moves (there is not a second one) and the text appears.
    """
    chat = owui.add_chat(ada)
    tool.call("show_excalidraw", elements=[RECT], chat_id=chat)
    tool.call(
        "upsert_excalidraw_elements",
        elements=[{**RECT, "x": 50}, {"type": "text", "x": 0, "y": 0, "text": "hi"}],
        chat_id=chat,
    )
    elements = scene(owui, chat)["elements"]
    assert elements[0] == {**RECT, "x": 50}
    assert elements[1]["text"] == "hi" and elements[1]["id"]


def test_models_may_pass_elements_as_json_text(owui, tool, ada):
    """Elements passed as a JSON string, as some models do, are accepted.

    By hand: not reliably repeatable: whether the model sends a string depends on the model.
    """
    chat = owui.add_chat(ada)
    tool.call("upsert_excalidraw_elements", elements=json.dumps(RECT), chat_id=chat)
    assert scene(owui, chat)["elements"] == [RECT]


def test_replace_discards_everything_and_delete_takes_bound_text_with_its_shape(owui, tool, ada):
    """replace_excalidraw_elements discards the drawing and stores exactly what it is given.
    Deleting a shape also deletes the text bound to it.

    By hand: ask for a box labelled B and a second box, then "delete box B". Its label goes with
    it, and the other box stays.
    """
    chat = owui.add_chat(ada)
    label = {"type": "text", "id": "t", "containerId": "b", "x": 0, "y": 0, "text": "B"}
    tool.call(
        "replace_excalidraw_elements",
        elements=[{**RECT, "id": "b"}, label, RECT],
        chat_id=chat,
    )
    assert [e["id"] for e in scene(owui, chat)["elements"]] == ["b", "t", "a"]
    tool.call("delete_excalidraw_elements", ids=["b"], chat_id=chat)
    assert [e["id"] for e in scene(owui, chat)["elements"]] == ["a"]


def test_read_shows_the_model_a_compact_drawing(owui, tool, ada):
    """read_excalidraw gives the model a compact drawing: rendering detail (roughness, seed) and
    deleted elements are left out, a shape's bound text becomes its label, and an arrow's
    binding is shown as start: {id}.

    By hand: draw a labelled box with an arrow from it, then ask the model to describe the
    drawing. It names the box by its label and says the arrow starts at it.
    """
    chat = owui.add_chat(ada)
    tool.call(
        "replace_excalidraw_elements",
        elements=[
            {**RECT, "roughness": 1, "seed": 99},
            {"type": "text", "id": "t", "containerId": "a", "x": 0, "y": 0, "text": "API"},
            {"type": "ellipse", "id": "gone", "x": 0, "y": 0, "isDeleted": True},
            {
                "type": "arrow",
                "id": "r",
                "x": 0,
                "y": 0,
                "points": [[0, 0], [1, 0]],
                "startBinding": {"elementId": "a"},
            },
        ],
        chat_id=chat,
    )
    read = json.loads(tool.call("read_excalidraw", chat_id=chat))
    assert read["version"] == 1
    assert read["elements"] == [
        {**RECT, "label": "API"},
        {
            "id": "r",
            "type": "arrow",
            "x": 0,
            "y": 0,
            "points": [[0, 0], [1, 0]],
            "start": {"id": "a"},
        },
    ]


def test_a_temporary_chat_keeps_its_drawing_in_memory(owui, tool):
    """In a temporary chat (id local:...), the drawing is kept in memory, not in the database.

    By hand: start a temporary chat, ask for a drawing, then ask the model to describe it. It
    reads back what it drew.
    """
    tool.call("show_excalidraw", elements=[RECT], chat_id="local:abc")
    assert json.loads(tool.call("read_excalidraw", chat_id="local:abc"))["elements"] == [RECT]


def test_without_a_saved_chat_the_model_is_told_what_to_do(tool):
    """With no chat id, or a chat not saved yet, the tool fails with a message that tells the model
    what to do ("send a message first", "not saved yet").

    By hand: hard to catch: it only happens before a new chat's first message is saved.
    """
    with pytest.raises(RuntimeError, match="send a message first"):
        tool.call("show_excalidraw", chat_id=None)
    with pytest.raises(RuntimeError, match="not saved yet"):
        tool.call("show_excalidraw", chat_id="no-such-chat")
