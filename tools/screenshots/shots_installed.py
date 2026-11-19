"""What the deploy and the plugins' functions put into Open-WebUI: functions, tools, skills, and
the tool servers mcpo Sync writes."""

from __future__ import annotations

from conftest import URL


def test_the_deployed_functions(admin, shot):
    """By hand: after `owpp deploy`, open Admin Panel > Functions. Every plugin is there, on,
    with the note that edits are overwritten by the next deploy."""
    admin.goto(f"{URL}/admin/functions")
    admin.get_by_text("Stale Data Dashboard").wait_for()
    shot(
        admin,
        "deploy",
        "functions",
        "The example plugins after `owpp deploy`: one function each, switched on, each marked as "
        "controlled by git.",
    )


def test_the_tools_the_functions_installed(admin, shot):
    """By hand: open Workspace > Tools. The Excalidraw and Inline Visualizer tools are there,
    installed by their functions, not by hand."""
    admin.goto(f"{URL}/workspace/tools")
    admin.get_by_text("Inline Visualizer").first.wait_for()
    shot(
        admin,
        "inline_visualizer",
        "tools",
        "Workspace > Tools: the tools the Excalidraw and Inline Visualizer functions installed.",
        illustrates=[
            "test_loading_it_installs_the_tool_and_the_skill_for_everyone",
            "test_loading_the_function_installs_the_tool_for_everyone",
        ],
    )


def test_the_skill_the_function_installed(admin, shot):
    """By hand: open Workspace > Skills. The visualize skill is there."""
    admin.goto(f"{URL}/workspace/skills")
    admin.get_by_text("visualize").first.wait_for()
    shot(
        admin,
        "inline_visualizer",
        "skills",
        "Workspace > Skills: the visualize skill, fetched from upstream at the pinned commit.",
        illustrates=["test_loading_it_installs_the_tool_and_the_skill_for_everyone"],
    )


def test_disabling_the_function_removes_them(admin, api, shot):
    """By hand: switch Inline Visualizer off under Admin Panel > Functions, then open
    Workspace > Tools. Its tool is gone; switch the function on again and it is back."""
    api("POST", "/api/v1/functions/id/inline_visualizer/toggle")  # off
    try:
        admin.goto(f"{URL}/workspace/tools")
        admin.get_by_text("Excalidraw").first.wait_for()
        admin.wait_for_timeout(1000)
        assert admin.get_by_text("Inline Visualizer").count() == 0
        shot(
            admin,
            "inline_visualizer",
            "disabled",
            "With the function switched off, its tool is gone from Workspace > Tools.",
            illustrates=["test_disabling_removes_both_and_enabling_reinstalls_them"],
        )
    finally:
        api("POST", "/api/v1/functions/id/inline_visualizer/toggle")  # on again


def test_the_tool_servers_mcpo_sync_wrote(admin, shot):
    """By hand: open Admin Settings > Integrations. Under External Tool Servers, one entry per
    mcpo server, named as config.yaml says (time is "Clock")."""
    admin.goto(f"{URL}/admin/settings")
    admin.get_by_text("Integrations", exact=True).click()
    admin.get_by_text("Clock").wait_for()
    shot(
        admin,
        "mcpo_sync",
        "tool-servers",
        "Admin Settings > Integrations: the mcpo servers, synced as tool servers. config.yaml "
        'renames "time" to Clock; "fetch" keeps the default name.',
        illustrates=[
            "test_saving_the_valves_syncs_every_mcpo_server_as_a_tool_server",
            "test_it_applies_the_config_it_ships",
        ],
    )
