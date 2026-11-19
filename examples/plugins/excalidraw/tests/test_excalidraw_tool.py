"""The Excalidraw tool and the plugin runtime that installs it, against a mock Open-WebUI.

Run with `owpp test excalidraw`. The `owui` and `plugin` fixtures come with owpp
(docs/testing.md): `plugin` is this folder, bundled as the deploy would and loaded.
"""

import json

import pytest

RECT = {"type": "rectangle", "id": "a", "x": 0, "y": 0, "width": 160, "height": 80}


@pytest.fixture
def ada(owui):
    return owui.add_user("Ada")


@pytest.fixture
def tool(owui, plugin):
    return owui.tool("excalidraw")


# ---- installed by its function ---------------------------------------------------------


def test_loading_the_function_installs_the_tool_for_everyone(owui, plugin):
    tool = owui.tools["excalidraw"]
    assert tool.name == "Excalidraw"
    assert tool.meta.manifest["parent_function_id"] == "excalidraw"
    assert tool.access_grants == [
        {"principal_type": "anyone", "principal_id": "*", "permission": "read"}
    ]


def test_the_tool_goes_with_the_function_and_comes_back_with_it(owui, plugin):
    owui.disable("excalidraw")
    assert "excalidraw" not in owui.tools
    owui.enable("excalidraw")
    assert "excalidraw" in owui.tools
    owui.delete("excalidraw")
    assert "excalidraw" not in owui.tools


def test_a_hand_made_tool_with_the_same_id_is_left_alone(owui, plugin_dir):
    from owpp.testing import Record

    owui.tools["excalidraw"] = Record(
        id="excalidraw", content="class Tools: pass\n", meta=Record(manifest={})
    )
    owui.load(plugin_dir)
    assert owui.tools["excalidraw"].content == "class Tools: pass\n"
    owui.disable("excalidraw")
    assert "excalidraw" in owui.tools  # not this plugin's, so not removed either


def test_every_method_the_model_sees_explains_the_element_format(tool):
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
    chat = owui.add_chat(ada)
    result = tool.call("show_excalidraw", elements=[RECT], chat_id=chat, user=ada)
    assert result["version"] == 1
    assert f'src="/excalidraw/view/{chat}"' in result["excalidraw_artifact"]
    assert scene(owui, chat)["elements"] == [RECT]
    assert scene(owui, chat)["writer"] == "tool"


def test_show_again_without_elements_changes_nothing(owui, tool, ada):
    chat = owui.add_chat(ada)
    tool.call("show_excalidraw", elements=[RECT], chat_id=chat)
    assert tool.call("show_excalidraw", chat_id=chat)["version"] == 1


def test_the_drawing_is_kept_beside_the_chats_other_metadata(owui, tool, ada):
    chat = owui.add_chat(ada, meta={"tags": ["work"]})
    tool.call("show_excalidraw", elements=[RECT], chat_id=chat)
    assert owui.chat(chat).meta["tags"] == ["work"]


def test_upsert_merges_by_id_and_gives_new_elements_an_id(owui, tool, ada):
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
    chat = owui.add_chat(ada)
    tool.call("upsert_excalidraw_elements", elements=json.dumps(RECT), chat_id=chat)
    assert scene(owui, chat)["elements"] == [RECT]


def test_replace_discards_everything_and_delete_takes_bound_text_with_its_shape(owui, tool, ada):
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
        {"id": "r", "type": "arrow", "x": 0, "y": 0, "points": [[0, 0], [1, 0]], "start": {"id": "a"}},
    ]


def test_a_temporary_chat_keeps_its_drawing_in_memory(owui, tool):
    tool.call("show_excalidraw", elements=[RECT], chat_id="local:abc")
    assert json.loads(tool.call("read_excalidraw", chat_id="local:abc"))["elements"] == [RECT]


def test_without_a_saved_chat_the_model_is_told_what_to_do(tool):
    with pytest.raises(RuntimeError, match="send a message first"):
        tool.call("show_excalidraw", chat_id=None)
    with pytest.raises(RuntimeError, match="not saved yet"):
        tool.call("show_excalidraw", chat_id="no-such-chat")
