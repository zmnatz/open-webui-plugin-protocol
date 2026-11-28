"""`owpp build` and `owpp deploy --from`: bundle in one place, deploy that build in another."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest
from conftest import FILTER, FakeRepo, embedded, fake_fetcher, write_tree

from owpp import __version__
from owpp.build import Build, read_build, write_build
from owpp.cli import main
from owpp.deploy import build_plugins, deploy, plugins_for
from owpp.errors import OwppError
from owpp.sources import Sources

SHA = "a" * 40
GIT = "https://example.com/owner/repo.git"
SOURCED = f"""protocol: "0.3"
source: {{git: {GIT}, ref: {SHA}, path: up}}
function:
  title: Up
  global: true
tool: {{id: up_tool, file: tool.py}}
requires: {{iframe_sandbox_allow_same_origin: true}}
"""


def no_git(git, ref, paths):
    raise AssertionError(f"the deploy fetched {git} {paths}: a build needs no sources")


@pytest.fixture
def plugins(tmp_path):
    """A plugins folder: a loose filter, and a plugin that takes its tool from git."""
    return write_tree(
        tmp_path / "plugins",
        {
            "demo.py": FILTER,
            "up/plugin.yaml": SOURCED,
            "up/function.py": "class Filter:\n    pass\n",
        },
    )


def built(plugins, out, ids=None):
    write_build(build_plugins(plugins, Sources(fake_fetcher()), ids), out)
    return out


class TestBuild:
    def test_it_writes_each_bundle_what_the_deploy_needs_and_an_index(self, plugins, tmp_path):
        out = built(plugins, tmp_path / "dist")
        assert sorted(p.name for p in out.iterdir()) == [
            "build.json",
            "demo.json",
            "demo.py",
            "up.json",
            "up.py",
        ]
        index = json.loads((out / "build.json").read_text())
        assert index == {
            "format": 2,
            "owpp": __version__,
            "complete": True,
            "plugins": ["demo", "up"],
            "latest": {},
        }
        data = json.loads((out / "up.json").read_text())
        assert data["want_global"] is True and data["type"] == "filter"
        meta = data["meta"]
        assert meta["sources"] == {f"{GIT} up": SHA}
        assert meta["requires"] == {"iframe_sandbox_allow_same_origin": True}
        assert [t["id"] for t in embedded((out / "up.py").read_text())["tools"]] == ["up_tool"]

    def test_reading_it_back_gives_the_same_functions_without_the_sources(self, plugins, tmp_path):
        made = build_plugins(plugins, Sources(fake_fetcher()))
        write_build(made, tmp_path / "dist")
        back = read_build(tmp_path / "dist")
        strip = lambda f: {k: v for k, v in asdict(f).items() if k != "root"}  # noqa: E731
        assert [strip(f) for f in back.files] == [strip(f) for f in made.files]
        assert back.complete and back.latest == {}

    def test_a_build_of_some_plugins_is_partial(self, plugins, tmp_path):
        assert read_build(built(plugins, tmp_path / "dist", ["up"])).complete is False
        with pytest.raises(OwppError, match="no plugin nope"):
            build_plugins(plugins, Sources(fake_fetcher()), ["nope"])

    def test_it_replaces_an_earlier_build_but_not_a_folder_of_other_files(self, plugins, tmp_path):
        out = built(plugins, tmp_path / "dist")
        built(plugins, out, ["demo"])
        assert sorted(p.name for p in out.iterdir()) == ["build.json", "demo.json", "demo.py"]
        write_tree(tmp_path / "mine", {"notes.txt": "keep me\n"})
        with pytest.raises(OwppError, match="not an owpp build; build into an empty folder"):
            built(plugins, tmp_path / "mine")
        assert (tmp_path / "mine" / "notes.txt").read_text() == "keep me\n"

    def test_the_command(self, plugins, tmp_path, capsys):
        out = tmp_path / "dist"
        argv = ["build", "--dir", str(plugins), "--out", str(out)]
        assert main(argv, env={}, sources=lambda: Sources(fake_fetcher())) == 0
        printed = capsys.readouterr().out
        assert f"built {out / 'up.py'}" in printed
        assert f"2 function(s) in {out}: every plugin" in printed


class TestRoot:
    """FunctionFile.root is the plugin folder in the plugins folder, or None: never a temporary
    copy, which is gone after the build or when its Sources closes."""

    def roots(self, tmp_path, latest):
        directory = write_tree(
            tmp_path / "plugins",
            {
                "loose.py": FILTER,
                "local/plugin.yaml": "function: {title: Local}\n",
                "local/function.py": "class Filter:\n    pass\n",
                "whole/plugin.yaml": f"source: {{git: {GIT}, ref: {SHA}, path: up, plugin: true}}\n",
            },
        )
        upstream = {
            "up/plugin.yaml": "function: {title: Whole}\n",
            "up/function.py": "class Filter:\n    pass\n",
        }
        with FakeRepo(GIT, upstream, head=SHA).sources() as sources:
            made = build_plugins(directory, sources, latest=latest)
        return directory, {f.id: f.root for f in made.files}

    def test_at_the_pinned_commits_only_a_folder_of_the_repository_is_a_root(self, tmp_path):
        directory, roots = self.roots(tmp_path, latest=False)
        assert roots == {"local": directory / "local", "loose": None, "whole": None}

    def test_at_the_latest_commits_there_is_no_root(self, tmp_path):
        _, roots = self.roots(tmp_path, latest=True)
        assert roots == {"local": None, "loose": None, "whole": None}


class TestReadingABuild:
    def test_a_build_by_another_owpp_version_is_refused(self, plugins, tmp_path):
        out = built(plugins, tmp_path / "dist")
        index = json.loads((out / "build.json").read_text()) | {"owpp": "0.0.1"}
        (out / "build.json").write_text(json.dumps(index))
        with pytest.raises(OwppError, match="built by owpp 0.0.1.*same version"):
            read_build(out)

    def test_a_bundle_changed_after_the_build_is_refused(self, plugins, tmp_path):
        out = built(plugins, tmp_path / "dist")
        (out / "demo.py").write_text((out / "demo.py").read_text() + "\n# edited\n")
        with pytest.raises(OwppError, match="demo.py does not match the build"):
            read_build(out)

    def test_a_folder_that_is_not_a_build_is_refused(self, tmp_path):
        with pytest.raises(OwppError, match="not an owpp build.*owpp build"):
            read_build(tmp_path)


class TestDeployFrom:
    def test_it_deploys_the_build_as_the_folder_would_and_reads_no_git(
        self, plugins, tmp_path, open_webui
    ):
        # Two instances side by side: the fake, since a process has one real Open-WebUI.
        out = built(plugins, tmp_path / "dist")
        from_folder, from_build = open_webui(), open_webui()
        deploy(*from_folder.options(plugins, sources=Sources(fake_fetcher())))
        res = deploy(
            *from_build.options(tmp_path / "elsewhere", from_dir=out, sources=Sources(no_git))
        )
        assert sorted(r.id for r in res) == ["demo", "up"]
        assert from_build.state.keys() == from_folder.state.keys()
        for fn_id, live in from_folder.state.items():
            assert from_build.state[fn_id]["content"] == live["content"]
            assert from_build.state[fn_id]["meta"] == live["meta"]

    def test_a_complete_build_prunes_and_a_partial_one_never_does(
        self, plugins, tmp_path, real_open_webui, git_fn
    ):
        m = real_open_webui(live=[git_fn("demo", FILTER), git_fn("retired", FILTER)])
        partial = built(plugins, tmp_path / "some", ["demo"])
        deploy(*m.options(tmp_path, from_dir=partial, sources=Sources(no_git)))
        assert "retired" in m.state
        complete = built(plugins, tmp_path / "all")
        res = deploy(*m.options(tmp_path, from_dir=complete, sources=Sources(no_git)))
        assert any(r.id == "retired" and r.action == "deleted" for r in res)
        assert "retired" not in m.state

    def test_only_narrows_the_build(self, plugins, tmp_path, real_open_webui):
        m = real_open_webui()
        out = built(plugins, tmp_path / "dist")
        res = deploy(*m.options(tmp_path, from_dir=out, only=["demo"], sources=Sources(no_git)))
        assert [r.id for r in res] == ["demo"]

    def test_a_build_at_the_latest_commits_deploys_only_as_a_dry_run(
        self, plugins, tmp_path, real_open_webui
    ):
        out = tmp_path / "dist"
        write_build(Build(read_build(built(plugins, out)).files, latest={"x": "y"}), out)
        m = real_open_webui()
        with pytest.raises(OwppError, match="only deploys as a dry run"):
            deploy(*m.options(tmp_path, from_dir=out, sources=Sources(no_git)))
        assert m.calls == []
        res = deploy(*m.options(tmp_path, from_dir=out, dry_run=True, sources=Sources(no_git)))
        assert all(r.action.startswith("would create") for r in res) and m.state == {}

    def test_latest_needs_the_sources(self, plugins, tmp_path, real_open_webui):
        out = built(plugins, tmp_path / "dist")
        opts = real_open_webui().options(tmp_path, from_dir=out, dry_run=True, latest=True)
        with pytest.raises(OwppError, match="--latest needs the sources.*owpp build --latest"):
            plugins_for(opts.choices)


class TestNoPrune:
    def test_it_deletes_nothing_and_lists_what_a_full_deploy_would(
        self, real_open_webui, functions_dir, git_fn
    ):
        m = real_open_webui(live=[git_fn("demo", FILTER), git_fn("a", FILTER), git_fn("b", FILTER)])
        res = deploy(*m.options(functions_dir({"demo.py": FILTER}), no_prune=True))
        assert {r.id: r.action for r in res if r.id != "demo"} == {
            "a": "not deleted (--no-prune)",
            "b": "not deleted (--no-prune)",
        }
        assert sorted(m.state) == ["a", "b", "demo"]  # nor refused as a mass delete
        assert not any("DELETE" in c for c in m.calls)

    def test_the_flags(self, plugins, tmp_path, monkeypatch):
        seen = {}
        monkeypatch.setattr("owpp.cli.run_deploy", lambda i, c, env: seen.update(o=c) or 0)
        out = tmp_path / "dist"
        env = {"OPEN_WEBUI_URL": "http://x"}
        assert main(["deploy", "--from", str(out), "--no-prune"], env=env) == 0
        assert seen["o"].from_dir == out.resolve() and seen["o"].no_prune is True
