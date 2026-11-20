"""`owpp pull`: moving a plugin's pinned commit to the latest one of the branch it follows."""

from __future__ import annotations

import pytest
from conftest import write_tree

from owpp.cli import main
from owpp.errors import OwppError
from owpp.manifest import read_manifest
from owpp.pull import compare_url, pull
from owpp.sources import Sources
from owpp.sources._git import pick_sha

GIT = "https://github.com/owner/repo.git"
OLD = "a1" * 20
NEW = "b2" * 20

MANIFEST = f"""# Pinned: review the upstream diff before moving it.
protocol: "0.3"
source:
  git: {GIT}
  ref: {OLD} # reviewed 2026-11-01
  path: viz
{{follow}}function:
  title: Viz
  global: true
tool:
  id: viz
  file: tool.py
skills:
  draw:
    dir: skills/draw
"""

# What the repository holds at each commit, under the plugin's `path`.
REPO = {
    OLD: {
        "viz/tool.py": "class Tools:\n    pass\n",
        "viz/skills/draw/SKILL.md": "---\nname: draw\n---\nold\n",
        "viz/skills/draw/old.md": "gone later\n",
    },
    NEW: {
        "viz/tool.py": "class Tools:\n    x = 1\n",
        "viz/skills/draw/SKILL.md": "---\nname: draw\n---\nold\n",
        "viz/skills/draw/new.md": "added\n",
    },
}


def fetcher(git, ref, paths):
    files = REPO[ref]
    out = {}
    for path in paths:
        if path.endswith("/"):
            out |= {k: v for k, v in files.items() if k.startswith(path)}
        elif path in files:
            out[path] = files[path]
    return out


@pytest.fixture
def plugins(tmp_path):
    def make(follow: str = "", **extra: str):
        line = f"  {follow}\n" if follow else ""
        return write_tree(
            tmp_path, {"viz/plugin.yaml": MANIFEST.replace("{follow}", line), **extra}
        )

    return make


def run(directory, ids=None, dry_run=False, latest=NEW, bump_by="patch"):
    lines: list[str] = []
    looked_up: list[tuple[str, str]] = []

    def resolve(git, ref):
        looked_up.append((git, ref))
        return latest

    code = pull(
        directory,
        ids,
        dry_run=dry_run,
        sources=Sources(fetcher, lookup=resolve),
        out=lines.append,
        bump_by=bump_by,
        today="2026-11-20",
    )
    return code, "\n".join(lines), looked_up


class TestSync:
    def test_it_moves_the_ref_and_lists_what_changed(self, plugins):
        d = plugins()
        code, out, looked_up = run(d)
        assert code == 0
        assert looked_up == [(GIT, "HEAD")]  # no branch: or tag: the default branch
        assert f"new   viz: moved {OLD[:7]} -> {NEW[:7]} (default branch)" in out
        words = " ".join(out.split())
        assert "changed viz/tool.py" in words
        assert "added viz/skills/draw/new.md" in words
        assert "removed viz/skills/draw/old.md" in words
        assert "SKILL.md" not in words  # unchanged
        assert f"https://github.com/owner/repo/compare/{OLD}...{NEW}" in out
        text = (d / "viz" / "plugin.yaml").read_text()
        assert read_manifest(d / "viz")["source"]["ref"] == NEW
        # The ref moved and, since files it takes changed, the plugin's version (it had none):
        # the comments stay.
        assert text == MANIFEST.replace("{follow}", "").replace(OLD, NEW).replace(
            "  title: Viz\n", "  title: Viz\n  version: 0.1.0\n"
        )
        assert "bumped the version (none) -> 0.1.0" in out
        changelog = (d / "viz" / "CHANGELOG.md").read_text()
        assert f"## 0.1.0 (2026-11-20)\n\n- Upstream {GIT} viz: {OLD[:7]} -> {NEW[:7]}" in changelog

    def test_bump_none_moves_only_the_ref(self, plugins):
        d = plugins()
        code, out, _ = run(d, bump_by="none")
        assert code == 0 and "bumped" not in out
        assert (d / "viz" / "plugin.yaml").read_text() == MANIFEST.replace("{follow}", "").replace(
            OLD, NEW
        )
        assert not (d / "viz" / "CHANGELOG.md").exists()

    def test_a_dry_run_says_it_would_bump(self, plugins):
        _, out, _ = run(plugins(), dry_run=True)
        assert "would bump the version (none) -> 0.1.0" in out

    @pytest.mark.parametrize(
        ("follow", "looked", "shown"),
        [
            ("branch: release/v2", "refs/heads/release/v2", "(branch release/v2)"),
            ("tag: v2.1", "refs/tags/v2.1", "(tag v2.1)"),
        ],
    )
    def test_it_follows_exactly_the_branch_or_the_tag(self, plugins, follow, looked, shown):
        _, out, looked_up = run(plugins(follow))
        assert looked_up == [(GIT, looked)] and shown in out

    def test_a_0_2_manifest_still_follows_its_track(self, plugins):
        d = plugins("track: release/v2")
        text = (d / "viz" / "plugin.yaml").read_text().replace('"0.3"', '"0.2"')
        (d / "viz" / "plugin.yaml").write_text(text)
        _, out, looked_up = run(d)
        assert looked_up == [(GIT, "release/v2")] and "(release/v2)" in out

    @pytest.mark.parametrize(
        ("follow", "message"),
        [
            ("track: main", "source.track is gone in protocol 0.3: it is `branch:` or `tag:` now"),
            ("branch: main\n  tag: v1", "follow a `branch:` or a `tag:`, not both"),
            ("branch: --upload-pack=x", "source.branch must be a branch or tag name"),
        ],
    )
    def test_refuses_track_both_keys_and_an_option(self, plugins, follow, message):
        with pytest.raises(OwppError, match=message):
            run(plugins(follow))

    def test_dry_run_writes_nothing(self, plugins):
        d = plugins()
        before = (d / "viz" / "plugin.yaml").read_text()
        code, out, _ = run(d, dry_run=True)
        assert code == 0 and "would move" in out
        assert (d / "viz" / "plugin.yaml").read_text() == before

    def test_up_to_date_is_left_alone(self, plugins):
        d = plugins()
        code, out, _ = run(d, latest=OLD)
        assert code == 0 and f"ok    viz: up to date (default branch), {OLD[:7]}" in out
        assert read_manifest(d / "viz")["source"]["ref"] == OLD

    def test_a_ref_it_cannot_look_up_fails_and_writes_nothing(self, plugins):
        d = plugins()
        code, out, _ = run(d, latest=None)
        assert code == 1 and "FAIL  viz: could not look up the default branch of" in out
        assert read_manifest(d / "viz")["source"]["ref"] == OLD

    def test_a_file_gone_at_the_new_commit_fails_and_writes_nothing(self, plugins, monkeypatch):
        monkeypatch.setitem(REPO, NEW, {"viz/skills/draw/SKILL.md": "x\n"})
        d = plugins()
        code, out, _ = run(d)
        assert code == 1 and "FAIL  viz:" in out and "tool.py not found" in out
        assert read_manifest(d / "viz")["source"]["ref"] == OLD

    def test_it_skips_plugins_written_here_and_checks_the_ids(self, plugins):
        d = plugins(**{"own/plugin.yaml": "function:\n  title: Own\n", "own/function.py": ""})
        code, out, _ = run(d)
        assert code == 0 and " own:" not in out
        code, out, _ = run(d, ids=["own"])
        assert code == 1 and "no plugin takes its code from git" in out
        with pytest.raises(OwppError, match="no plugin nope"):
            run(d, ids=["nope"])

    def test_the_command(self, plugins, monkeypatch, capsys):
        d = plugins()
        monkeypatch.setattr("owpp.cli.Sources", lambda: Sources(fetcher, lookup=lambda g, r: OLD))
        assert main(["pull", "--dir", str(d)], env={}) == 0
        assert "up to date" in capsys.readouterr().out


class TestPieces:
    def test_a_branch_or_a_tag_is_looked_up_exactly_and_told_apart(self):
        from owpp.sources._git import kind_in

        out = f"{'a' * 40}\trefs/heads/v1\n{'b' * 40}\trefs/tags/v1\n{'c' * 40}\trefs/tags/v1^{{}}"
        assert pick_sha(out, "refs/heads/v1") == "a" * 40
        assert pick_sha(out, "refs/tags/v1") == "c" * 40  # the commit an annotated tag points at
        assert pick_sha(out, "refs/heads/nope") is None
        assert kind_in(out, "v1") == "tag"  # both: the tag, as git reads the name
        assert kind_in(f"{'a' * 40}\trefs/heads/main\n", "main") == "branch"
        assert kind_in("", "main") is None

    def test_ls_remote_output_is_read_as_git_does(self):
        out = "\n".join(
            [
                f"{'a' * 40}\tHEAD",
                f"{'b' * 40}\trefs/heads/main",
                f"{'c' * 40}\trefs/tags/v1",
                f"{'d' * 40}\trefs/tags/v1^{{}}",  # the commit an annotated tag points at
                f"{'e' * 40}\trefs/heads/v1",
                f"{'f' * 40}\trefs/remotes/x/main",
            ]
        )
        assert pick_sha(out, "HEAD") == "a" * 40
        assert pick_sha(out, "main") == "b" * 40
        assert pick_sha(out, "v1") == "d" * 40  # the peeled tag, over the branch
        assert pick_sha(out, "other") is None

    def test_compare_links_for_github(self):
        assert compare_url("git@github.com:o/r.git", OLD, NEW).startswith(
            "https://github.com/o/r/compare/"
        )
        assert compare_url("https://gitlab.example.com/o/r.git", OLD, NEW) == ""
