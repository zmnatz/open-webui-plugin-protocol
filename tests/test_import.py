"""`owpp import`: code that already exists (a file, a function on Open-WebUI, a folder in a git
repository) becomes a plugin folder with a plugin.yaml, ready to test."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import FakeRepo, write_tree

from owpp.bundle import bundle_function, load_function_files
from owpp.cli import main
from owpp.embedding import runtime_start
from owpp.errors import OwppError
from owpp.importer import import_code, import_file, import_git, import_instance, parse_git_url
from owpp.libraries import BY_NAME
from owpp.manifest import read_manifest
from owpp.sources import Sources
from owpp.unbundle import _protocol_body, unbundle

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


def their_repo(files=None) -> FakeRepo:
    """A repository with REPO's files at SHA, which is branch main, tag v1 and HEAD."""
    return FakeRepo(
        GIT,
        REPO if files is None else files,
        sha=SHA,
        branches={"main": SHA},
        tags={"v1": SHA},
        head=SHA,
    )


def run_import(directory, url, files=None, **kw):
    return import_git(directory, url, sources=their_repo(files).sources(), **kw)


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
        plugins = tmp_path / "plugins"
        imported = run_import(plugins, "https://github.com/someone/their-plugins/tree/main/viz")
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
        repo = their_repo()
        plugins = tmp_path / "plugins"
        url = "https://github.com/someone/their-plugins/tree/main/viz"
        import_git(plugins, url, sources=repo.sources())
        with repo.sources() as sources:
            (fn,) = load_function_files(plugins, sources)
        assert fn.type == "filter" and SHOUT_CODE.strip() in fn.content
        assert "class Tools" in fn.content and "visualize" in fn.content

    def test_public_makes_the_tool_and_skills_public(self, tmp_path):
        imported = run_import(
            tmp_path / "p", "https://github.com/someone/their-plugins/tree/main/viz", public=True
        )
        manifest = read_manifest(imported.folder)
        assert manifest["tool"]["access"] == "public"
        assert manifest["skills"]["visualize"]["access"] == "public"
        assert not any("private" in n for n in imported.notes)

    def test_a_file_url_takes_that_function_and_whatever_is_beside_it(self, tmp_path):
        imported = run_import(
            tmp_path / "p",
            "https://github.com/someone/their-plugins/blob/v1/viz/shout.py",
            {**REPO, "viz/older.py": SHOUT},
        )
        manifest = read_manifest(imported.folder)
        assert imported.folder.name == "shout"
        assert manifest["source"]["tag"] == "v1"
        assert manifest["function"]["file"] == "shout.py"
        assert manifest["tool"]["file"] == "tool.py"

    def test_two_functions_in_one_folder_are_refused_by_name(self, tmp_path):
        url = "https://github.com/someone/their-plugins/tree/main/viz"
        with pytest.raises(OwppError, match=r"two functions in viz: older\.py, shout\.py"):
            run_import(tmp_path / "p", url, {**REPO, "viz/older.py": SHOUT})

    def test_only_a_tool_and_skills_is_an_installer(self, tmp_path):
        files = {k: v for k, v in REPO.items() if k != "viz/shout.py"}
        url = "https://github.com/someone/their-plugins/tree/main/viz"
        imported = run_import(tmp_path / "p", url, files)
        manifest = read_manifest(imported.folder)
        assert "file" not in manifest["function"] and manifest["function"]["global"] is True
        assert manifest["tool"]["file"] == "tool.py"

    def test_a_whole_owpp_plugin_is_taken_whole(self, tmp_path):
        files = {"viz/plugin.yaml": 'protocol: "0.5"\nfunction: {title: Viz}\n', **REPO}
        url = "https://github.com/someone/their-plugins/tree/main/viz"
        imported = run_import(tmp_path / "p", url, files)
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
            run_import(tmp_path / "p", "https://github.com/someone/their-plugins/tree/main/other")

    def test_a_branch_that_is_not_there_is_refused(self, tmp_path):
        with pytest.raises(OwppError, match="no branch or tag nope"):
            run_import(tmp_path / "p", "https://github.com/someone/their-plugins/tree/nope/viz")

    def test_the_repository_root_is_read_whole(self, tmp_path):
        files = {"shout.py": SHOUT, "README.md": "hi\n"}
        repo = their_repo(files)
        url = "https://github.com/someone/their-plugins"
        imported = import_git(tmp_path / "p", url, sources=repo.sources())
        assert repo.fetched[-1][2] == ["./"]
        assert imported.folder.name == "their_plugins"
        manifest = read_manifest(imported.folder)
        assert "branch" not in manifest["source"] and manifest["source"]["path"] == ""


# ---- from Open-WebUI, and the command ----------------------------------------------------


class TestFromOpenWebUI:
    def test_a_function_on_the_instance_becomes_a_plugin_its_deploy_leaves_unchanged(
        self, tmp_path, open_webui
    ):
        """The id is the instance's, so the deploy updates that function, with the same code."""
        server = open_webui(live=[{"id": "shout", "name": "Shout", "content": SHOUT}])
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

    def test_a_function_that_is_not_there_is_an_error(self, tmp_path, open_webui):
        server = open_webui()
        with pytest.raises(OwppError, match="HTTP 401"):
            import_instance(tmp_path / "plugins", server.instance(), "nope")


# ---- what owpp, or the Shared Assets Protocol, put into the code ---------------------------

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "plugins"
# Each example's parts: libraries, templates, static, assets, config, jobs, a tool, skills.
LOCAL_EXAMPLES = sorted(
    p.name
    for p in EXAMPLES.iterdir()
    if (p / "plugin.yaml").exists() and not read_manifest(p).get("source")
)


def _bundle(folder):
    with Sources() as sources:
        return bundle_function(sources.resolve(folder))


class TestWhatOwppPutIn:
    @pytest.mark.parametrize("name", LOCAL_EXAMPLES)
    def test_a_deployed_example_imports_back_to_a_plugin_whose_bundle_is_the_same(
        self, tmp_path, name
    ):
        """What `owpp import --instance` reads for a function owpp deployed is its bundle: the
        libraries, their data and the runtime (with the tool and skills) come back out as
        include:, files and tool.py, and bundling the import gives the same code again."""
        deployed = _bundle(EXAMPLES / name)
        imported = import_code(tmp_path, deployed, name, "Open-WebUI")
        assert _bundle(imported.folder) == deployed

    def test_the_tool_its_templates_and_config_come_back_as_files(self, tmp_path, open_webui):
        server = open_webui(
            live=[
                {
                    "id": "excalidraw",
                    "name": "Excalidraw",
                    "content": _bundle(EXAMPLES / "excalidraw"),
                }
            ]
        )
        folder = import_instance(tmp_path / "plugins", server.instance(), "excalidraw").folder
        manifest = read_manifest(folder)
        assert manifest["include"] == ["routes", "chat_data"]
        assert manifest["tool"]["include"] == ["chat_data"]
        assert manifest["tool"]["access"] == "public"
        assert (folder / "templates" / "viewer.html").read_text() == (
            EXAMPLES / "excalidraw" / "templates" / "viewer.html"
        ).read_text()
        assert "assets_url" in (folder / "config.yaml").read_text()
        for name in ("function.py", "tool.py"):
            code = (folder / name).read_text()
            assert "# end plugin" not in code and runtime_start(code) < 0
            assert "from owpp.lib import" in code
        lint = subprocess.run(
            [sys.executable, "-m", "owpp", "check", "--dir", str(tmp_path / "plugins"), "--strict"],
            capture_output=True,
            text=True,
        )
        assert lint.returncode == 0, lint.stdout + lint.stderr

    def test_a_public_skill_says_so_in_its_front_matter(self, tmp_path):
        """A skill declared public in plugin.yaml is, once local, public by its SKILL.md."""
        write_tree(
            tmp_path / "src",
            {
                "helper/plugin.yaml": 'protocol: "0.5"\nfunction: {title: Helper}\nskills: {draw: {file: draw.md, access: public}}\n',
                "helper/draw.md": "---\nname: draw\ndescription: Draws.\n---\n\nDraw.\n",
            },
        )
        folder = import_code(
            tmp_path / "plugins", _bundle(tmp_path / "src" / "helper"), "helper", "x"
        ).folder
        skill = (folder / "skills" / "draw" / "SKILL.md").read_text()
        assert skill == "---\nname: draw\ndescription: Draws.\naccess: public\n---\n\nDraw.\n"

    def test_a_library_from_another_owpp_version_is_still_taken_out(self, tmp_path):
        """A block is recognised by where link() put it, its first lines and its end line, not
        by its whole text, so a bundle an older owpp deployed imports too."""
        deployed = _bundle(EXAMPLES / "excalidraw")
        older = deployed.replace("def plugin_mount(", "def plugin_mount(  # older\n    ", 1)
        assert older != deployed
        own = unbundle(older)
        assert own.found == ["core", "routes", "chat_data", "templates", "config"]
        assert "# older" not in own.code

    def test_the_shared_assets_protocols_block_becomes_include(self, tmp_path):
        """A function that carries the protocol's block, byte-identical as the protocol asks, is
        given owpp's copy instead: its own code no longer changes app.routes, so it passes."""
        block = _protocol_body(BY_NAME["shared_assets"])
        imports = "import hashlib\nimport re\nfrom pathlib import Path\nfrom typing import Any\n"
        code = SHOUT.replace("from pydantic", imports + "\n" + block + "\nfrom pydantic")
        file = write_tree(tmp_path, {"shout.py": code}) / "shout.py"
        folder = import_file(tmp_path / "plugins", file).folder
        assert read_manifest(folder)["include"] == ["shared_assets"]
        assert "app.routes" not in (folder / "function.py").read_text()
        assert "end shared asset block" in _bundle(folder)

    def test_a_copy_of_the_block_that_differs_is_the_plugins_own_code(self, tmp_path):
        block = _protocol_body(BY_NAME["shared_assets"]).replace(
            "ASSET_IMPL_VERSION = 5", "ASSET_IMPL_VERSION = 4"
        )
        code = SHOUT.replace("from pydantic", block + "\nfrom pydantic")
        own = unbundle(code)
        assert own.found == [] and own.code == code

    def test_a_differing_copy_says_how_to_import_it_instead(self, tmp_path):
        block = _protocol_body(BY_NAME["shared_assets"]).replace(
            "ASSET_IMPL_VERSION = 5", "ASSET_IMPL_VERSION = 4"
        )
        code = SHOUT.replace("from pydantic", block + "\nfrom pydantic")
        imported = import_code(tmp_path, code, "shout", "x")
        assert any("not byte-identical" in n and "owpp import <URL>" in n for n in imported.notes)

    def test_a_library_it_does_not_recognise_is_named(self, tmp_path):
        """A block from another owpp whose first lines changed stays, and the notes say which,
        rather than leaving only `owpp check`'s refusal of what it does."""
        deployed = _bundle(EXAMPLES / "excalidraw")
        first = "import base64 as _base64\n"  # the routes library's first line
        older = deployed.replace("\n" + first, "\nimport base64 as _b64  # older\n" + first, 1)
        imported = import_code(tmp_path, older, "excalidraw", "x")
        assert any("still holds owpp's routes" in n for n in imported.notes)

    def test_static_binary_files_and_a_tool_that_is_the_function_round_trip(
        self, tmp_path, open_webui
    ):
        """Deployed and imported back from the instance: static/ (with its settings), binary
        files, a skill, a tool that is the function's own bundle, and requires:."""
        manifest = (
            'protocol: "0.5"\n'
            "function: {title: Demo, global: true}\n"
            "static: {prefix: /demo-files, access: admin}\n"
            "tool: {id: demo_tool, from: function, access: public}\n"
            "requires: {iframe_sandbox_allow_same_origin: true}\n"
        )
        src = write_tree(
            tmp_path / "src",
            {
                "demo/plugin.yaml": manifest,
                "demo/function.py": "class Filter:\n    pass\n\n\nclass Tools:\n    pass\n",
                "demo/static/app.js": "console.log(1)\n",
                "demo/static/img/logo.bin": bytes([0xFF, 0x00, 0x10]),
                "demo/skills/draw/SKILL.md": "---\nname: draw\ndescription: Draws.\n---\n\nDraw.\n",
                "demo/skills/draw/icon.bin": bytes([0x89, 0x50]),
            },
        )
        server = open_webui()
        env = {"OPEN_WEBUI_URL": server.serve(), "OPEN_WEBUI_API_KEY": "sk-good"}
        assert main(["deploy", "--dir", str(src)], env=env) == 0
        plugins = tmp_path / "plugins"
        assert main(["import", "--instance", "demo", "--dir", str(plugins)], env=env) == 0
        folder = plugins / "demo"
        got = read_manifest(folder)
        assert got["static"] == {"prefix": "/demo-files", "access": "admin"}
        assert got["tool"] == {"id": "demo_tool", "access": "public", "from": "function"}
        assert got["requires"] == {"iframe_sandbox_allow_same_origin": True}
        assert (folder / "static" / "img" / "logo.bin").read_bytes() == bytes([0xFF, 0x00, 0x10])
        assert (folder / "skills" / "draw" / "icon.bin").read_bytes() == bytes([0x89, 0x50])
        assert _bundle(folder) == _bundle(src / "demo")

    def test_a_function_an_older_owpp_deployed_says_requires_may_be_missing(
        self, tmp_path, open_webui
    ):
        meta = {"description": "x", "managed_by": "owpp"}  # no `requires`: deployed before it
        server = open_webui(live=[{"id": "shout", "name": "Shout", "content": SHOUT, "meta": meta}])
        imported = import_instance(tmp_path, server.instance(), "shout")
        assert any("did not record `requires:`" in n for n in imported.notes)
        assert "requires" not in read_manifest(imported.folder)


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
        self, tmp_path, open_webui, capsys
    ):
        server = open_webui(live=[{"id": "shout", "name": "Shout", "content": SHOUT}])
        env = {"OPEN_WEBUI_URL": server.serve(), "OPEN_WEBUI_API_KEY": "sk-good"}
        plugins = tmp_path / "plugins"
        assert main(["import", "--instance", "shout", "--dir", str(plugins)], env=env) == 0
        assert (plugins / "shout" / "function.py").read_text() == SHOUT_CODE

    def test_imports_from_git_through_the_commands_sources(self, tmp_path, monkeypatch):
        repo = their_repo()
        monkeypatch.setattr("owpp.cli.Sources", repo.sources)
        plugins = tmp_path / "plugins"
        assert main(["import", GIT, "--path", "viz", "--dir", str(plugins)], env={}) == 0
        assert read_manifest(plugins / "viz")["source"]["ref"] == SHA

    def test_takes_one_thing_to_import(self, tmp_path, capsys):
        assert main(["import", "--dir", str(tmp_path)], env={}) == 1
        assert "a git URL, a file, or --instance <id>" in capsys.readouterr().err

    def test_refuses_a_folder_on_disk(self, tmp_path, capsys):
        with pytest.raises(OwppError, match="a folder on disk"):
            main(["import", str(tmp_path), "--dir", str(tmp_path / "plugins")], env={})
