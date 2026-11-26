"""The agent skills (skills/): well formed, and the owpp skill's spec examples still work."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from owpp.create import render, spec_from_data
from owpp.manifest import parse_yaml

SKILLS = Path(__file__).resolve().parent.parent / "skills"
SKILL = SKILLS / "owpp"
EVERY_SKILL = sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))


def test_there_are_the_skills_the_docs_name():
    assert EVERY_SKILL == ["owpp", "test-existing-plugin"]


@pytest.mark.parametrize("name", EVERY_SKILL)
def test_the_skill_has_the_front_matter_skill_tools_read(name):
    """name matches the folder, and the description (what triggers it) fits the limits."""
    text = (SKILLS / name / "SKILL.md").read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md starts with YAML front matter"
    fm = parse_yaml(m.group(1))
    assert fm["name"] == name
    assert 0 < len(fm["description"]) <= 1024


@pytest.mark.parametrize("name", EVERY_SKILL)
def test_its_links_to_its_own_files_resolve(name):
    """A skill is installed on its own, so it links only to files inside its own folder."""
    folder = (SKILLS / name).resolve()
    for page in folder.rglob("*.md"):
        for target in re.findall(r"\]\(([^)#:]+)(?:#[^)]*)?\)", page.read_text()):
            path = (page.parent / target).resolve()
            assert path.exists() and path.is_relative_to(folder), f"{page.name}: {target}"


def examples():
    text = (SKILL / "references" / "spec.md").read_text()
    head, parts, from_git = re.findall(r"```yaml\n(.*?)```", text, re.S)
    return {"a plugin written here": head + parts, "a plugin from git": from_git}


@pytest.mark.parametrize("name", list(examples()))
def test_the_spec_examples_make_a_plugin(name):
    """Every key the reference shows is one owpp create --spec takes, and together they make a
    plugin (an event, the one type every key in the example applies to)."""
    data = parse_yaml(examples()[name])
    if name == "a plugin written here":
        data["type"] = "event"  # assets and live_reload are for events
    files = render(spec_from_data(data))
    assert "plugin.yaml" in files and "README.md" in files
