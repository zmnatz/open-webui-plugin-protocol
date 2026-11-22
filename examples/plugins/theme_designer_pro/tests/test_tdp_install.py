"""What Theme Designer Pro installs when it is enabled: the Launcher tool and the
theme-designer-pro skill, for every signed-in user, removed again when it is disabled. Run with
`owpp test theme_designer_pro`."""

TOOL = "theme_designer_pro_launcher"
SKILL = "theme-designer-pro"


def test_enabling_it_installs_the_launcher_and_the_skill_for_everyone(owui, tdp):
    """The function installs the Launcher and the skill, with all of the skill's files (it
    points to its references and templates), readable by every signed-in user.

    By hand: enable the function. Workspace > Tools has Theme Designer Pro Launcher and
    Workspace > Skills has theme-designer-pro, both shown to a user who is not an admin.
    """
    assert TOOL in owui.tools and SKILL in owui.skills
    files = sorted(f["path"] if isinstance(f, dict) else f for f in owui.skills[SKILL].data["files"])
    assert len(files) == 7 and any("templates/animation.js" in str(f) for f in files)
    assert owui.tools[TOOL].access_grants and owui.skills[SKILL].access_grants


def test_disabling_it_removes_the_launcher_and_the_skill(owui, tdp):
    """Disabling the function removes what it installed.

    By hand: disable the function: the Launcher and the skill are gone from Workspace.
    """
    owui.disable("theme_designer_pro")
    assert TOOL not in owui.tools and SKILL not in owui.skills


def test_the_launcher_carries_only_its_own_templates(owui, tdp):
    """The Launcher's bundle has its card and frame (`tool: templates: [launcher/]`), and not
    the 1 MB designer page, which only the function serves.

    By hand: Workspace > Tools > Theme Designer Pro Launcher: its code is about 80 KB.
    """
    code = owui.tools[TOOL].content
    assert "tdp-data" in code and "Theme Designer Pro | v" not in code
    assert len(code) < 150_000
