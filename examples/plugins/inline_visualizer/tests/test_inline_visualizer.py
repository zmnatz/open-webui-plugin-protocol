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
    assert plugin.type == "filter" and plugin.row.is_global


def test_loading_it_installs_the_tool_and_the_skill_for_everyone(owui, plugin):
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
    tool = owui.tool("inline_visualizer")
    assert [s["name"] for s in tool.specs] == ["render"]
    assert tool.call("render", html="<b>hi</b>") == "rendered 9 characters with theme auto"


def test_disabling_removes_both_and_enabling_reinstalls_them(owui, plugin):
    owui.disable("inline_visualizer")
    assert owui.tools == {} and owui.skills == {}
    owui.enable("inline_visualizer")
    assert set(owui.tools) == {"inline_visualizer"} and set(owui.skills) == {"visualize"}


def test_a_new_upstream_commit_updates_them_in_place(owui, plugin, plugin_dir):
    owui.tool_valves["inline_visualizer"] = {"theme": "dark"}  # an admin's choice
    newer = TOOL.replace("rendered", "drew")
    owui.load(plugin_dir, sources={"tool.py": newer, "SKILL.md": SKILL.replace("charts", "maps")})
    owui.emit("function.updated", "inline_visualizer")
    assert owui.tool("inline_visualizer").call("render", html="x") == "drew 1 characters with theme dark"
    assert owui.skills["visualize"].description == "Draw diagrams and maps inline."


def test_switching_tools_off_in_the_valves_removes_only_the_tool(owui, plugin):
    owui.set_valves("inline_visualizer", INSTALL_TOOLS=False)
    owui.emit("function.updated", "inline_visualizer")
    assert owui.tools == {} and set(owui.skills) == {"visualize"}
