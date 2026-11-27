"""Versions: `owpp version`, `owpp check --since`, CHANGELOG.md, and deploy's downgrade guard."""

from __future__ import annotations

import subprocess

import pytest

from owpp.check import check_plugins, failed
from owpp.cli import main
from owpp.create import PluginSpec, SkillSpec, ToolSpec, write_plugin
from owpp.deploy import deploy, render_report
from owpp.errors import OwppError
from owpp.manifest import read_manifest
from owpp.versioning import (
    bump,
    changelog_problem,
    is_older,
    next_version,
    set_block_version,
    set_front_matter_version,
    set_header_version,
)

TODAY = "2026-11-20"


class TestNumbers:
    @pytest.mark.parametrize(
        "current, how, new",
        [
            ("1.2.3", "patch", "1.2.4"),
            ("1.2.3", "minor", "1.3.0"),
            ("1.2.3", "major", "2.0.0"),
            ("1.2.3", "4.0.0", "4.0.0"),
            ("", "patch", "0.1.0"),
        ],
    )
    def test_next_version(self, current, how, new):
        assert next_version(current, how) == new

    def test_a_version_that_is_not_x_y_z_needs_the_new_one_given(self):
        with pytest.raises(OwppError, match="give the new one"):
            next_version("2024.1", "patch")
        assert next_version("2024.1", "2024.2.0") == "2024.2.0"
        with pytest.raises(OwppError, match="patch, minor or major"):
            next_version("1.0.0", "huge")

    def test_older_compares_numbers_not_text(self):
        assert is_older("1.9.0", "1.10.0")
        assert not is_older("1.10.0", "1.9.0")
        assert not is_older("1.0", "1.0.0")
        assert not is_older("beta", "1.0.0")  # cannot be ordered: never a downgrade


class TestWritingVersions:
    def test_plugin_yaml_keeps_its_comments(self):
        text = (
            "# Manifest\nfunction:\n  title: Viz # shown in Open-WebUI\n"
            '  version: "1.0.0" # bump me\n  license: MIT\ntool:\n  id: viz\n  version: 2.0.0\n'
        )
        new, old = set_block_version(text, "function", "1.1.0")
        assert old == "1.0.0"
        assert new == text.replace('"1.0.0" # bump me', '"1.1.0" # bump me')  # quotes kept
        new, old = set_block_version(text, "tool", "2.1.0")
        assert (old, new.count("2.1.0"), new.count("1.0.0")) == ("2.0.0", 1, 1)

    def test_a_missing_version_goes_after_the_title(self):
        new, old = set_block_version(
            "function:\n  title: Viz\n  license: MIT\n", "function", "0.1.0"
        )
        assert old == "" and new == "function:\n  title: Viz\n  version: 0.1.0\n  license: MIT\n"

    def test_a_one_line_mapping_and_crlf_are_written_in_place(self):
        new, old = set_block_version("function: {title: Viz}\r\n", "function", "0.1.0")
        assert old == "" and new == "function: {title: Viz, version: 0.1.0}\r\n"
        new, old = set_block_version("function:\r\n  version: 1.0.0\r\n", "function", "1.0.1")
        assert old == "1.0.0" and new == "function:\r\n  version: 1.0.1\r\n"

    def test_code_taken_verbatim_keeps_the_upstreams_version(self):
        with pytest.raises(OwppError, match="verbatim"):
            set_block_version("tool:\n  id: t\n  file: tool.py\n", "tool", "1.0.0")

    def test_skill_front_matter(self):
        new, old = set_front_matter_version("---\nname: draw\ndescription: x\n---\nbody\n", "1.0.0")
        assert old == "" and new == "---\nname: draw\nversion: 1.0.0\ndescription: x\n---\nbody\n"
        assert set_front_matter_version(new, "1.1.0")[0].count("version: 1.1.0") == 1

    def test_a_loose_functions_header(self):
        new, old = set_header_version(
            '"""\ntitle: X\nversion: 1.0.0\n"""\nclass Filter: pass\n', "2.0.0"
        )
        assert old == "1.0.0" and "version: 2.0.0" in new and "1.0.0" not in new


@pytest.fixture
def plugin(tmp_path):
    spec = PluginSpec(
        id="viz",
        type="filter",
        version="1.0.0",
        tool=ToolSpec("viz", methods=["lookup"]),
        skills=[SkillSpec("draw", "Draw.")],
    )
    write_plugin(tmp_path, spec, today="2026-11-01")
    text = (tmp_path / "viz" / "plugin.yaml").read_text()
    (tmp_path / "viz" / "plugin.yaml").write_text(
        text.replace("  title: Viz\ntool:", "  title: Viz\ntool:").replace(
            "tool:\n  id: viz\n  title: Viz\n", "tool:\n  id: viz\n  title: Viz\n  version: 1.0.0\n"
        )
    )
    return tmp_path


class TestBump:
    def test_it_bumps_the_function_and_adds_a_changelog_entry(self, plugin):
        (b,) = bump(plugin, "viz", "minor", message="Lookups are faster.", today=TODAY)
        assert (b.what, b.old, b.new) == ("function", "1.0.0", "1.1.0")
        assert read_manifest(plugin / "viz")["function"]["version"] == "1.1.0"
        log = (plugin / "viz" / "CHANGELOG.md").read_text()
        assert log.index("## 1.1.0 (2026-11-20)\n\n- Lookups are faster.") < log.index("## 1.0.0")

    def test_a_one_line_function_mapping_is_bumped(self, tmp_path):
        """It used to say the plugin had no `function:` section."""
        (tmp_path / "viz").mkdir()
        (tmp_path / "viz" / "plugin.yaml").write_text("function: {title: Viz, version: 1.0.0}\n")
        (b,) = bump(tmp_path, "viz", "patch", changelog=False)
        assert (b.old, b.new) == ("1.0.0", "1.0.1")
        text = (tmp_path / "viz" / "plugin.yaml").read_text()
        assert text == "function: {title: Viz, version: 1.0.1}\n"

    def test_the_tool_and_a_skill(self, plugin):
        (b,) = bump(plugin, "viz", tool=True)
        assert (b.what, b.new) == ("tool viz", "1.0.1")
        assert read_manifest(plugin / "viz")["tool"]["version"] == "1.0.1"
        (b,) = bump(plugin, "viz", skill="draw")
        assert b.new == "0.1.0"
        assert "version: 0.1.0" in (plugin / "viz" / "skills" / "draw" / "SKILL.md").read_text()

    def test_the_command_shows_versions(self, plugin, capsys):
        assert main(["version", "--dir", str(plugin)], env={}) == 0
        assert capsys.readouterr().out.splitlines() == [
            f"{'viz':<28}1.0.0",
            f"{'  tool viz':<28}1.0.0",
            f"{'  skill draw':<28}(no version)",
        ]
        before = (plugin / "viz" / "plugin.yaml").read_text()
        assert main(["version", "viz", "--dir", str(plugin)], env={}) == 0  # shows, changes nothing
        assert (plugin / "viz" / "plugin.yaml").read_text() == before

    def test_the_command_gives_a_new_version(self, plugin, capsys):
        assert main(["version", "viz", "patch", "--dir", str(plugin)], env={}) == 0
        out = capsys.readouterr().out
        assert "function: 1.0.0 -> 1.0.1" in out and "say what changed" in out
        assert main(["version", "viz", "2.0.0", "--tool", "--dir", str(plugin)], env={}) == 0
        assert read_manifest(plugin / "viz")["tool"]["version"] == "2.0.0"
        with pytest.raises(OwppError, match="no skill nope"):
            main(["version", "viz", "patch", "--skill", "nope", "--dir", str(plugin)], env={})
        assert main(["version", "viz", "--tool", "--dir", str(plugin)], env={}) == 1  # no new one


class TestChangelog:
    def test_check_warns_when_the_version_has_no_entry(self, plugin):
        assert not failed(check_plugins(plugin), strict=True)
        bump(plugin, "viz", changelog=False)
        assert changelog_problem(plugin / "viz", "1.0.1") is not None
        found = list(check_plugins(plugin))
        assert not failed(found) and failed(found, strict=True)  # a warning
        (warning,) = [f for f in found if f.kind == "warn"]
        assert warning.message.startswith("viz/CHANGELOG.md has no `## 1.0.1` entry")


# ---- check --since, against a real git repository ------------------------------------


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(plugin):
    """The plugins folder `plugin` made, inside a git repository, committed."""
    git(plugin, "init", "-q", "-b", "main")
    git(plugin, "add", "-A")
    git(plugin, "commit", "-qm", "first")
    return plugin


def since(repo):
    """Whether a check since main fails (1 or 0, as `owpp check` exits), and its lines."""
    found = list(check_plugins(repo, since="main"))
    return int(failed(found)), "\n".join(map(str, found))


class TestCheckSince:
    def test_nothing_changed_is_fine(self, repo):
        assert since(repo)[0] == 0

    def test_code_changed_without_a_new_version_fails(self, repo):
        fn = repo / "viz" / "function.py"
        fn.write_text(fn.read_text() + "\nX = 1\n")
        code, out = since(repo)
        assert code == 1
        assert (
            "FAIL  viz: changed since main but its version is still 1.0.0 (run `owpp version viz patch`)"
            in out
        )
        bump(repo, "viz")
        assert since(repo)[0] == 0

    def test_a_versioned_tool_needs_its_own_bump(self, repo):
        tool = repo / "viz" / "tool.py"
        tool.write_text(tool.read_text().replace("What lookup does", "What lookup really does"))
        code, out = since(repo)
        assert (
            code == 1 and "FAIL  tool viz: changed since main but its version is still 1.0.0" in out
        )
        assert "FAIL  viz:" not in out  # the function's own code did not change
        bump(repo, "viz", tool=True)
        assert since(repo)[0] == 0

    def test_an_unversioned_skill_is_the_plugins_change(self, repo):
        skill = repo / "viz" / "skills" / "draw" / "SKILL.md"
        skill.write_text(skill.read_text() + "\nMore.\n")
        code, out = since(repo)
        assert code == 1 and "FAIL  viz: changed since main" in out
        bump(repo, "viz", skill="draw")  # now it has its own version: that is enough
        assert since(repo)[0] == 0

    def test_a_plugin_new_since_then_needs_nothing(self, repo):
        write_plugin(repo, PluginSpec(id="fresh"))
        assert since(repo)[0] == 0

    def test_a_ref_that_is_not_one_is_an_error(self, repo):
        with pytest.raises(OwppError):
            list(check_plugins(repo, since="nope"))


# ---- deploy: never back a version without --force ------------------------------------


class TestDowngrade:
    def test_a_dry_run_warns_and_a_deploy_refuses(self, open_webui, plugin):
        m = open_webui()
        deploy(*m.options(plugin))  # 1.0.0 is live
        bump(plugin, "viz", "0.9.0")
        res = deploy(*m.options(plugin, dry_run=True))
        assert "function: 1.0.0 -> 0.9.0, OLDER than the live version" in res[0].details
        report = render_report(res, True)
        assert (
            "Warning: 1 function(s) would go back a version: `viz` (function 1.0.0 -> 0.9.0)"
            in report
        )
        assert "refuses this without --force" in report
        writes = len(m.calls)
        with pytest.raises(OwppError, match="refusing to deploy older versions.*--force"):
            deploy(*m.options(plugin))
        assert not any("/update" in c for c in m.calls[writes:])

    def test_force_deploys_it(self, open_webui, plugin):
        m = open_webui()
        deploy(*m.options(plugin))
        bump(plugin, "viz", "0.9.0")
        res = deploy(*m.options(plugin, force=True))
        assert res[0].action.startswith("updated") and res[0].downgrades == [
            "function 1.0.0 -> 0.9.0"
        ]
        assert "Deployed with --force." in render_report(res, False)

    def test_an_older_tool_counts_too(self, open_webui, plugin):
        m = open_webui()
        deploy(*m.options(plugin))
        bump(plugin, "viz", "0.5.0", tool=True)
        with pytest.raises(OwppError, match=r"viz \(tool `viz` 1.0.0 -> 0.5.0\)"):
            deploy(*m.options(plugin))
