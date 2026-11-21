"""tools/release.py, which the release workflow runs to prepare a release or hotfix branch."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("release", ROOT / "tools" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
spec = importlib.util.spec_from_file_location("release_notes", ROOT / "tools" / "release_notes.py")
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

## Unreleased

- Something new.

## 0.4.0 (2026-11-21)

- Older.
"""


def a_repo(tmp_path: Path, changelog: str = CHANGELOG) -> Path:
    (tmp_path / "src" / "owpp").mkdir(parents=True)
    (tmp_path / "src" / "owpp" / "__init__.py").write_text('"""owpp."""\n\n__version__ = "0.4.0"\n')
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    (tmp_path / "README.md").write_text(
        "- uses: zmnatz/open-webui-plugin-protocol@v0.4.0\n\n0.4.0, written against Open-WebUI.\n"
    )
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "install.md").write_text(
        "uvx owpp@0.4.0 list\npip install owpp==0.4.0  # or 'owpp[test]==0.4.0'\n"
        "Since owpp 0.4.0, and not owpp@0.4.01.\n"
    )
    (tmp_path / "docs" / "adr" / "0001.md").write_text("Until owpp@0.4.0.\n")
    return tmp_path


@pytest.mark.parametrize(
    "how, new",
    [("patch", "0.4.1"), ("minor", "0.5.0"), ("major", "1.0.0"), ("0.6.0", "0.6.0")],
)
def test_next_version(how, new):
    assert release.next_version("0.4.0", how) == new


@pytest.mark.parametrize("how", ["0.4.0", "0.3.9", "huge", "1.0"])
def test_the_new_version_must_be_after_the_current_one(how):
    with pytest.raises(SystemExit):
        release.next_version("0.4.0", how)


def test_a_release_dates_the_changelog_and_moves_every_pin(tmp_path):
    root = a_repo(tmp_path)
    assert release.prepare(root, "minor", "2026-12-01") == "0.5.0"
    assert release.package_version(root) == "0.5.0"
    changelog = (root / "CHANGELOG.md").read_text()
    assert changelog == CHANGELOG.replace("## Unreleased", "## 0.5.0 (2026-12-01)")
    assert release_notes.notes("v0.5.0", changelog, "0.5.0") == "- Something new.\n"
    assert (root / "README.md").read_text() == (
        "- uses: zmnatz/open-webui-plugin-protocol@v0.5.0\n\n0.5.0, written against Open-WebUI.\n"
    )
    assert (root / "docs" / "install.md").read_text() == (
        "uvx owpp@0.5.0 list\npip install owpp==0.5.0  # or 'owpp[test]==0.5.0'\n"
        "Since owpp 0.4.0, and not owpp@0.4.01.\n"  # prose and other versions are left alone
    )
    assert (root / "docs" / "adr" / "0001.md").read_text() == "Until owpp@0.4.0.\n"


@pytest.mark.parametrize(
    "changelog, problem",
    [
        ("# Changelog\n\n## 0.4.0 (2026-11-21)\n\n- Older.\n", "no `## Unreleased`"),
        ("# Changelog\n\n## Unreleased\n\n## 0.4.0 (2026-11-21)\n", "empty"),
    ],
)
def test_a_release_needs_unreleased_entries(tmp_path, changelog, problem):
    root = a_repo(tmp_path, changelog)
    with pytest.raises(SystemExit, match=problem):
        release.prepare(root, "minor", "2026-12-01")
    assert release.package_version(root) == "0.4.0"  # nothing written


def test_a_hotfix_adds_a_dated_section_for_the_fix(tmp_path):
    root = a_repo(tmp_path, "# Changelog\n\n## 0.4.0 (2026-11-21)\n\n- Older.\n")
    assert release.prepare(root, "patch", "2026-12-01", hotfix=True) == "0.4.1"
    changelog = (root / "CHANGELOG.md").read_text()
    assert (
        changelog == "# Changelog\n\n## 0.4.1 (2026-12-01)\n\n## 0.4.0 (2026-11-21)\n\n- Older.\n"
    )
    with pytest.raises(SystemExit, match="no dated"):  # CI fails until the fix's entry is written
        release_notes.notes("v0.4.1", changelog, "0.4.1")


def test_this_repository_prepares_cleanly(tmp_path):
    for path in ["src/owpp/__init__.py", "CHANGELOG.md", "README.md", "docs", "skills"]:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        copy = shutil.copytree if (ROOT / path).is_dir() else shutil.copy
        copy(ROOT / path, tmp_path / path)
    old = release.package_version(ROOT)
    new = release.prepare(tmp_path, "patch", "2026-12-01", hotfix=True)
    for path in release.pinned_files(tmp_path):
        text = path.read_text()
        for pin in [f"owpp@{old}", f"owpp=={old}", f"open-webui-plugin-protocol@v{old}"]:
            assert pin not in text, f"{path.relative_to(tmp_path)} still pins {old}"
    assert f"owpp@{new}" in (tmp_path / "docs" / "install.md").read_text()
