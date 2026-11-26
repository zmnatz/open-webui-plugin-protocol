"""`owpp import`: code that already exists (a file, a function on Open-WebUI, a folder in a git
repository) becomes a plugin folder with a plugin.yaml, ready to test."""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import write_tree

from owpp.bundle import load_function_files
from owpp.cli import main
from owpp.errors import OwppError
from owpp.importer import import_file, import_git, import_instance, parse_git_url
from owpp.manifest import read_manifest
from owpp.sources import Sources

SHOUT = '''"""
title: Shout
author: someone
version: 0.1.0
description: Upper-cases the reply.
"""

from pydantic import BaseModel


class Filter:
    class Valves(BaseModel):
        pass

    def __init__(self):
        self.valves = self.Valves()

    def outlet(self, body: dict) -> dict:
        for message in body.get("messages", []):
            message["content"] = message["content"].upper()
        return body
'''
SHOUT_CODE = SHOUT.split('"""\n', 2)[2]


class TestFromAFile:
    def test_the_header_goes_to_plugin_yaml_and_the_bundle_is_the_file(self, tmp_path):
        file = write_tree(tmp_path, {"shout.py": SHOUT}) / "shout.py"
        plugins = tmp_path / "plugins"
        folder = import_file(plugins, file).folder
        assert folder == plugins / "shout"
        assert read_manifest(folder)["function"] == {
            "title": "Shout",
            "author": "someone",
            "version": "0.1.0",
            "description": "Upper-cases the reply.",
        }
        assert (folder / "function.py").read_text() == SHOUT_CODE
        (fn,) = load_function_files(plugins)
        assert fn.content == SHOUT

    def test_the_id_can_be_given(self, tmp_path):
        file = write_tree(tmp_path, {"Shout-It.py": SHOUT}) / "Shout-It.py"
        assert import_file(tmp_path / "plugins", file).folder.name == "shout_it"
        assert import_file(tmp_path / "plugins", file, plugin_id="loud").folder.name == "loud"

    def test_a_file_without_a_header_is_refused(self, tmp_path):
        file = write_tree(tmp_path, {"shout.py": SHOUT_CODE}) / "shout.py"
        with pytest.raises(OwppError, match="no docstring header"):
            import_file(tmp_path / "plugins", file)

    def test_an_existing_folder_is_left_alone(self, tmp_path):
        file = write_tree(tmp_path, {"shout.py": SHOUT}) / "shout.py"
        import_file(tmp_path / "plugins", file)
        with pytest.raises(OwppError, match="already exists"):
            import_file(tmp_path / "plugins", file)

    def test_what_it_writes_passes_check_strict_and_its_first_test(self, tmp_path, capsys):
        file = write_tree(tmp_path, {"shout.py": SHOUT}) / "shout.py"
        plugins = tmp_path / "plugins"
        import_file(plugins, file, today="2026-11-26")
        assert main(["check", "--strict", "--dir", str(plugins)]) == 0
        assert "warn" not in capsys.readouterr().out
        assert (
            (plugins / "shout" / "CHANGELOG.md")
            .read_text()
            .startswith("# Shout changelog\n\n## 0.1.0 (2026-11-26)\n\n- Imported from shout.py.")
        )
        done = subprocess.run(
            [sys.executable, "-m", "owpp", "test", "--dir", str(plugins)]
            + ["--", "-p", "no:cacheprovider"],
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert "1 passed" in done.stdout

    def test_header_lines_plugin_yaml_cannot_hold_are_reported(self, tmp_path):
        odd = SHOUT.replace("author: someone\n", "author: someone\nA note to myself\nicon_url:\n")
        file = write_tree(tmp_path, {"shout.py": odd}) / "shout.py"
        imported = import_file(tmp_path / "plugins", file)
        assert imported.notes == [
            "dropped a header line that is not `key: value`: 'A note to myself'",
            "dropped a header line that is not `key: value`: 'icon_url:'",
        ]
        assert "icon_url" not in read_manifest(imported.folder)["function"]


# ---- from git -------------------------------------------------------------------------

GIT = "https://github.com/someone/their-plugins.git"
SHA = "917c88f3029c0c6500139ba7b7b061f358d8aaea"
TOOL = '''"""
title: Visualizer
"""


class Tools:
    def draw(self, what: str) -> str:
        """Draw `what`.

        :param what: what to draw
        """
        return what
'''
SKILL = "---\nname: visualize\ndescription: Draws things.\n---\n\nDraw.\n"
REPO = {
    "viz/shout.py": SHOUT,
    "viz/tool.py": TOOL,
    "viz/skills/visualize/SKILL.md": SKILL,
    "viz/skills/visualize/references/a.md": "more\n",
    "viz/tests/test_viz.py": "",
    "other/README.md": "not this folder\n",
}


class Git:
    """A repository with REPO's files at SHA, on branch main and tag v1."""

    def __init__(self, files=None):
        self.files = REPO if files is None else files
        self.asked: list[tuple[str, str, list[str]]] = []

    def fetcher(self, git, ref, paths):
        self.asked.append((git, ref, paths))
        assert (git, ref) == (GIT, SHA)
        out = {}
        for path in paths:
            base = "" if path == "./" else path
            out |= {k: v for k, v in self.files.items() if k.startswith(base)}
        return out

    @staticmethod
    def lookup(git, ref):
        return SHA if ref in ("refs/heads/main", "refs/tags/v1", "HEAD") else None

    @staticmethod
    def kind_of(git, name):
        return {"main": "branch", "v1": "tag"}.get(name)

    def run(self, directory, url, **kw):
        return import_git(
            directory,
            url,
            fetcher=self.fetcher,
            lookup=self.lookup,
            kind_of=self.kind_of,
            **kw,
        )


class TestGitUrls:
    @pytest.mark.parametrize(
        "url, expected",
        [
            (
                "https://github.com/someone/their-plugins/tree/main/viz",
                (GIT, "main", "viz", ""),
            ),
            (
                "https://github.com/someone/their-plugins/blob/v1/viz/shout.py",
                (GIT, "v1", "viz", "shout.py"),
            ),
            ("https://github.com/someone/their-plugins", (GIT, "", "", "")),
            ("https://github.com/someone/their-plugins.git", (GIT, "", "", "")),
            (
                "https://gitlab.com/group/sub/repo/-/tree/main/viz",
                ("https://gitlab.com/group/sub/repo.git", "main", "viz", ""),
            ),
            (
                "git@example.org:someone/repo.git",
                ("git@example.org:someone/repo.git", "", "", ""),
            ),
        ],
    )
    def test_a_url_names_the_repository_the_branch_the_folder_and_the_file(self, url, expected):
        found = parse_git_url(url)
        assert (found.git, found.name, found.path, found.file) == expected

    def test_a_clone_url_takes_its_folder_and_branch_from_flags(self):
        found = parse_git_url(GIT, path="/viz/", name="main")
        assert (found.git, found.name, found.path, found.file) == (GIT, "main", "viz", "")

    def test_a_local_path_or_another_transport_is_refused(self):
        for url in ("/home/me/repo", "file:///home/me/repo", "ext::sh -c id"):
            with pytest.raises(OwppError, match="git URL"):
                parse_git_url(url)


class TestFromGit:
    def test_finds_the_function_the_tool_and_the_skill_and_pins_them(self, tmp_path):
        git = Git()
        plugins = tmp_path / "plugins"
        imported = git.run(plugins, "https://github.com/someone/their-plugins/tree/main/viz")
        assert imported.folder == plugins / "viz"
        manifest = read_manifest(imported.folder)
        assert manifest["source"] == {"git": GIT, "ref": SHA, "branch": "main", "path": "viz"}
        assert manifest["function"]["file"] == "shout.py"
        assert manifest["tool"] == {"id": "viz", "file": "tool.py"}
        assert manifest["skills"] == {"visualize": {"dir": "skills/visualize"}}
        assert not (imported.folder / "shout.py").exists()  # pinned, never copied
        assert any(f"pinned {GIT} at 917c88f (branch main)" in n for n in imported.notes)
        assert any("private" in n for n in imported.notes)

    def test_what_it_writes_bundles_with_everything_it_found(self, tmp_path):
        git = Git()
        plugins = tmp_path / "plugins"
        git.run(plugins, "https://github.com/someone/their-plugins/tree/main/viz")
        with Sources(git.fetcher) as sources:
            (fn,) = load_function_files(plugins, sources)
        assert fn.type == "filter" and SHOUT_CODE.strip() in fn.content
        assert "class Tools" in fn.content and "visualize" in fn.content

    def test_public_makes_the_tool_and_skills_public(self, tmp_path):
        git = Git()
        imported = git.run(
            tmp_path / "p", "https://github.com/someone/their-plugins/tree/main/viz", public=True
        )
        manifest = read_manifest(imported.folder)
        assert manifest["tool"]["access"] == "public"
        assert manifest["skills"]["visualize"]["access"] == "public"
        assert not any("private" in n for n in imported.notes)

    def test_a_file_url_takes_that_function_and_whatever_is_beside_it(self, tmp_path):
        git = Git({**REPO, "viz/older.py": SHOUT})
        imported = git.run(
            tmp_path / "p", "https://github.com/someone/their-plugins/blob/v1/viz/shout.py"
        )
        manifest = read_manifest(imported.folder)
        assert imported.folder.name == "shout"
        assert manifest["source"]["tag"] == "v1"
        assert manifest["function"]["file"] == "shout.py"
        assert manifest["tool"]["file"] == "tool.py"

    def test_two_functions_in_one_folder_are_refused_by_name(self, tmp_path):
        git = Git({**REPO, "viz/older.py": SHOUT})
        with pytest.raises(OwppError, match=r"two functions in viz: older\.py, shout\.py"):
            git.run(tmp_path / "p", "https://github.com/someone/their-plugins/tree/main/viz")

    def test_only_a_tool_and_skills_is_an_installer(self, tmp_path):
        files = {k: v for k, v in REPO.items() if k != "viz/shout.py"}
        imported = Git(files).run(
            tmp_path / "p", "https://github.com/someone/their-plugins/tree/main/viz"
        )
        manifest = read_manifest(imported.folder)
        assert "file" not in manifest["function"] and manifest["function"]["global"] is True
        assert manifest["tool"]["file"] == "tool.py"

    def test_a_whole_owpp_plugin_is_taken_whole(self, tmp_path):
        files = {"viz/plugin.yaml": 'protocol: "0.5"\nfunction: {title: Viz}\n', **REPO}
        imported = Git(files).run(
            tmp_path / "p", "https://github.com/someone/their-plugins/tree/main/viz"
        )
        manifest = read_manifest(imported.folder)
        assert manifest["source"] == {
            "git": GIT,
            "ref": SHA,
            "branch": "main",
            "path": "viz",
            "plugin": True,
        }
        assert set(manifest) == {"protocol", "source"}

    def test_a_folder_with_nothing_to_take_is_refused(self, tmp_path):
        with pytest.raises(OwppError, match="no function, tool or skill in other"):
            Git().run(tmp_path / "p", "https://github.com/someone/their-plugins/tree/main/other")

    def test_a_branch_that_is_not_there_is_refused(self, tmp_path):
        with pytest.raises(OwppError, match="no branch or tag nope"):
            Git().run(tmp_path / "p", "https://github.com/someone/their-plugins/tree/nope/viz")

    def test_the_repository_root_is_read_whole(self, tmp_path):
        files = {"shout.py": SHOUT, "README.md": "hi\n"}
        git = Git(files)
        imported = git.run(tmp_path / "p", "https://github.com/someone/their-plugins")
        assert git.asked[-1][2] == ["./"]
        assert imported.folder.name == "their_plugins"
        manifest = read_manifest(imported.folder)
        assert "branch" not in manifest["source"] and manifest["source"]["path"] == ""


# ---- from Open-WebUI, and the command ----------------------------------------------------


class TestFromOpenWebUI:
    def test_a_function_on_the_instance_becomes_a_plugin_its_deploy_leaves_unchanged(
        self, tmp_path, mock_server
    ):
        """The id is the instance's, so the deploy updates that function, with the same code."""
        server = mock_server(live=[{"id": "shout", "name": "Shout", "content": SHOUT}])
        plugins = tmp_path / "plugins"
        imported = import_instance(plugins, server.instance(), "shout")
        assert imported.folder == plugins / "shout"
        assert (imported.folder / "function.py").read_text() == SHOUT_CODE
        (fn,) = load_function_files(plugins)
        assert fn.content == SHOUT
        assert "GET /api/v1/functions/id/shout" in server.calls
        assert any("valves are not copied" in n for n in imported.notes)
        readme = (imported.folder / "README.md").read_text()
        assert server.base_url not in readme  # where it came from, without the instance's address

    def test_a_function_that_is_not_there_is_an_error(self, tmp_path, mock_server):
        server = mock_server()
        with pytest.raises(OwppError, match="HTTP 401"):
            import_instance(tmp_path / "plugins", server.instance(), "nope")


class TestTheCommand:
    def test_imports_a_file_and_checks_it(self, tmp_path, capsys):
        file = write_tree(tmp_path, {"shout.py": SHOUT}) / "shout.py"
        plugins = tmp_path / "plugins"
        assert main(["import", str(file), "--dir", str(plugins)], env={}) == 0
        out = capsys.readouterr().out
        assert f"created {plugins / 'shout'}" in out
        assert "ok    shout" in out  # owpp check ran on it
        assert "owpp test shout" in out  # what to do next

    def test_imports_from_the_instance_with_the_deploys_credentials(
        self, tmp_path, mock_server, capsys
    ):
        server = mock_server(live=[{"id": "shout", "name": "Shout", "content": SHOUT}])
        env = {"OPEN_WEBUI_URL": server.base_url, "OPEN_WEBUI_API_KEY": "sk-good"}
        plugins = tmp_path / "plugins"
        assert main(["import", "--instance", "shout", "--dir", str(plugins)], env=env) == 0
        assert (plugins / "shout" / "function.py").read_text() == SHOUT_CODE

    def test_takes_one_thing_to_import(self, tmp_path, capsys):
        assert main(["import", "--dir", str(tmp_path)], env={}) == 1
        assert "a git URL, a file, or --instance <id>" in capsys.readouterr().err

    def test_refuses_a_folder_on_disk(self, tmp_path, capsys):
        with pytest.raises(OwppError, match="a folder on disk"):
            main(["import", str(tmp_path), "--dir", str(tmp_path / "plugins")], env={})
