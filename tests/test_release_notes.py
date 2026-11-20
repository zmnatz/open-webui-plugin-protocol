"""The GitHub release notes the publish workflow writes from CHANGELOG.md for a version tag."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("release_notes", ROOT / "tools" / "release_notes.py")
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

## 0.3.0 (2026-11-20)

- Something new ([upgrading](docs/upgrading.md), [a heading](#x), [elsewhere](https://e.com)).

## 0.2.1 (2026-11-19)

- Older.
"""


def test_the_notes_are_the_versions_section_with_absolute_links():
    out = release_notes.notes("v0.3.0", CHANGELOG, "0.3.0")
    assert out == (
        "- Something new ([upgrading]"
        "(https://github.com/zmnatz/open-webui-plugin-protocol/blob/v0.3.0/docs/upgrading.md), "
        "[a heading](#x), [elsewhere](https://e.com)).\n"
    )


@pytest.mark.parametrize(
    ("tag", "changelog", "message"),
    [
        ("v0.3.1", CHANGELOG, "is not v0.3.0"),
        ("v0.3.0", CHANGELOG.replace("## 0.3.0 (2026-11-20)", "## Unreleased"), "no dated"),
    ],
)
def test_no_release_for_a_tag_that_does_not_match_or_an_undated_section(tag, changelog, message):
    with pytest.raises(SystemExit, match=message):
        release_notes.notes(tag, changelog, "0.3.0")


def test_the_current_version_has_its_notes():
    """What the next tag will publish: the package's version, dated in CHANGELOG.md."""
    version = release_notes.package_version()
    assert release_notes.notes(f"v{version}", (ROOT / "CHANGELOG.md").read_text(), version)
