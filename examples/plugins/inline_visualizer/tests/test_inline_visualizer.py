"""Inline Visualizer against a mock Open-WebUI. The tool and skill come from a pinned git
commit at deploy time; here stand-ins take their place (`sources=`), so the test needs no
network. What is tested is this folder's part: that the generated function installs them,
keeps them current and removes them. Run with `owpp test inline_visualizer`."""

import pytest

TOOL = '''"""
title: Inline Visualizer
description: Render HTML and SVG inline.
"""
from pydantic import BaseModel


class Tools:
    class Valves(BaseModel):
        theme: str = "auto"

    def __init__(self):
        self.valves = self.Valves()

    async def render(self, html: str) -> str:
        """
        Render HTML inline.

        :param html: The HTML to render.
        """
        return f"rendered {len(html)} characters with theme {self.valves.theme}"
'''

SKILL = "---\nname: visualize\ndescription: Draw diagrams and charts inline.\n---\nUse the render tool.\n"


@pytest.fixture
def plugin(owui, plugin_dir):
    return owui.load(plugin_dir, sources={"tool.py": TOOL, "SKILL.md": SKILL})


def test_it_is_a_global_filter_that_only_installs_things(plugin):
    """It is a global filter, whose only job is to install the tool and the skill.

    By hand: Admin Panel > Functions shows Inline Visualizer as a filter with Global on.
    """
    assert plugin.type == "filter" and plugin.row.is_global


def test_loading_it_installs_the_tool_and_the_skill_for_everyone(owui, plugin):
    """Loading it installs the upstream tool (marked as the function's own) and the visualize skill
    (tagged plugin:inline_visualizer, holding its SKILL.md), both readable by everyone.

    By hand: enable the function. Workspace > Tools lists Inline Visualizer and Workspace >
    Skills lists visualize, and a user who is not an admin sees both.
    """
    public = [{"principal_type": "anyone", "principal_id": "*", "permission": "read"}]
    tool = owui.tools["inline_visualizer"]
    assert tool.meta.manifest["parent_function_id"] == "inline_visualizer"
    assert tool.access_grants == public
    skill = owui.skills["visualize"]
    assert skill.description == "Draw diagrams and charts inline."
    assert skill.meta.tags == ["plugin:inline_visualizer"]
    assert [f["path"] for f in skill.data["files"]] == ["SKILL.md"]
    assert skill.access_grants == public


def test_the_installed_tool_is_the_upstream_code(owui, plugin):
    """The installed tool is the upstream code: the model sees its render method, and it runs with
    its default valves.

    By hand: in a chat with the tool on, ask the model to render a small HTML snippet. It calls
    render and the result shows inline.
    """
    tool = owui.tool("inline_visualizer")
    assert [s["name"] for s in tool.specs] == ["render"]
    assert tool.call("render", html="<b>hi</b>") == "rendered 9 characters with theme auto"


def test_disabling_removes_both_and_enabling_reinstalls_them(owui, plugin):
    """Disabling the function removes the tool and the skill; enabling it puts both back.

    By hand: switch the function off: Inline Visualizer is gone from Workspace > Tools and
    visualize from Workspace > Skills. Switch it on: both are back.
    """
    owui.disable("inline_visualizer")
    assert owui.tools == {} and owui.skills == {}
    owui.enable("inline_visualizer")
    assert set(owui.tools) == {"inline_visualizer"} and set(owui.skills) == {"visualize"}


def test_a_new_upstream_commit_updates_them_in_place(owui, plugin, plugin_dir):
    """When a new upstream commit is deployed, the tool and the skill are updated in place, and
    valves an admin set on the tool are kept.

    By hand: set one of the Inline Visualizer tool's valves, change the pinned commit in
    plugin.yaml and deploy. The tool's code is the new commit's, and your valve is still set.
    """
    owui.tool_valves["inline_visualizer"] = {"theme": "dark"}  # an admin's choice
    newer = TOOL.replace("rendered", "drew")
    owui.load(plugin_dir, sources={"tool.py": newer, "SKILL.md": SKILL.replace("charts", "maps")})
    owui.emit("function.updated", "inline_visualizer")
    assert owui.tool("inline_visualizer").call("render", html="x") == "drew 1 characters with theme dark"
    assert owui.skills["visualize"].description == "Draw diagrams and maps inline."


def test_switching_tools_off_in_the_valves_removes_only_the_tool(owui, plugin):
    """With the function's INSTALL_TOOLS valve off, the tool is removed and the skill stays.

    By hand: turn INSTALL_TOOLS off in the function's valves and save. Inline Visualizer is gone
    from Workspace > Tools; visualize is still under Workspace > Skills.
    """
    owui.set_valves("inline_visualizer", INSTALL_TOOLS=False)
    owui.emit("function.updated", "inline_visualizer")
    assert owui.tools == {} and set(owui.skills) == {"visualize"}
