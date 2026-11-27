"""`owpp create`: the plugin it writes (owpp.create) and the wizard that asks for it (owpp.wizard)."""

from __future__ import annotations

import ast
import io
import subprocess
import sys

import pytest
from conftest import FILTER, FakeRepo, fake_sources

from owpp.bundle import load_function_files
from owpp.cli import check_bundle, main
from owpp.create import (
    CODE_TYPES,
    FILTER_HOOKS,
    PluginSpec,
    SkillSpec,
    SourceSpec,
    ToolSpec,
    render,
    spec_from_data,
    write_plugin,
)
from owpp.errors import OwppError
from owpp.imports import missing_lib_imports
from owpp.libraries import exports
from owpp.lint import lint_plugin
from owpp.manifest import read_manifest
from owpp.sources import Sources
from owpp.wizard import Prompter, run_wizard

SHA = "917c88f3029c0c6500139ba7b7b061f358d8aaea"
GIT = "https://github.com/owner/repo.git"


def tool(tool_id: str) -> ToolSpec:
    return ToolSpec(
        tool_id, "Lookup", "Looks things up.", ["lookup", "ping"], rich_ui=True, chat_data=True
    )


# Every part the wizard can add, in at least one plugin of each type, all written here.
SPECS = [PluginSpec(id=f"min_{t}", type=t) for t in CODE_TYPES] + [
    PluginSpec(
        id="full_filter",
        type="filter",
        icon_url="https://example.com/icon.svg",
        requirements="httpx",
        required_open_webui_version="0.10.0",
        priority=True,
        hooks=list(FILTER_HOOKS),
        toggle=True,
        file_handler=True,
        tool=tool("full_filter_tool"),
        skills=[SkillSpec("take-notes", "Take notes in the chat.")],
        page="rendered",
        page_access="admin",
        chat_data=True,
        config=True,
    ),
    PluginSpec(
        id="full_action",
        type="action",
        global_=True,
        priority=True,
        buttons=[("summarize", "Summarize"), ("translate", "Translate")],
        rich_ui=True,
        page="static",
        page_access="public",
        tool=tool("full_action_tool"),
    ),
    PluginSpec(
        id="full_pipe",
        type="pipe",
        models=[("fast", "Fast"), ("slow", "Slow")],
        stream=True,
        page="rendered",
        page_access="user",
        config=True,
        skills=[SkillSpec("pipe-help", "Help with the pipe.", public=False)],
    ),
    PluginSpec(
        id="full_event",
        type="event",
        events=["system.startup.completed", "function.valves_updated", "user.created"],
        sync=True,
        sync_minutes=15,
        assets=True,
        live_reload=True,
        page="rendered",
        page_access="public",
        chat_data=True,
        config=True,
        tool=tool("full_event_tool"),
    ),
    PluginSpec(id="event_page", type="event", page="static", page_access="admin"),
    PluginSpec(id="event_assets", type="event", assets=True, events=[]),
    PluginSpec(
        id="installs_tool", type="installer", tool=ToolSpec("installs_tool", methods=["run"])
    ),
    PluginSpec(
        id="installs_skills", type="installer", skills=[SkillSpec("a-skill"), SkillSpec("b")]
    ),
]

# From a git repository: these fetch at deploy time, so they are bundled here with stand-ins.
GIT_SPECS = [
    PluginSpec(
        id="git_installer",
        type="installer",
        source=SourceSpec(GIT, SHA, "plugins/viz"),
        tool=ToolSpec("viz", file="tool.py"),
        skills=[
            SkillSpec("visualize", path="skills/visualize"),
            SkillSpec("draw", path="draw/SKILL.md", is_dir=False, public=False),
        ],
    ),
    PluginSpec(
        id="git_function",
        type="upstream",
        global_=True,
        source=SourceSpec(GIT, SHA, "", function_file="src/function.py"),
    ),
]


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    directory = tmp_path_factory.mktemp("plugins")
    for spec in SPECS:
        write_plugin(directory, spec)
    return directory


@pytest.fixture(scope="module")
def from_git(tmp_path_factory):
    directory = tmp_path_factory.mktemp("from_git")
    for spec in GIT_SPECS:
        write_plugin(directory, spec)
    return directory


class TestWhatItWrites:
    def test_every_plugin_bundles_compiles_and_has_no_warnings(self, written):
        functions = {f.id: f for f in load_function_files(written)}
        assert sorted(functions) == sorted(s.id for s in SPECS)
        for spec in SPECS:
            fn = functions[spec.id]
            assert fn.type == ("filter" if spec.type == "installer" else spec.type)
            assert check_bundle(fn.content, f"{spec.id}.py") is None, spec.id
            assert lint_plugin(written / spec.id, spec.id) == [], spec.id

    def test_every_generated_file_imports_the_library_names_it_uses(self, written):
        """So the plugin reads, lints and type-checks as ordinary Python, like a hand-written one."""
        files = [p for p in written.glob("*/*.py") if p.name in ("function.py", "tool.py")]
        assert files
        for path in files:
            assert missing_lib_imports(path.read_text(), exports()) == [], path

    def test_every_generated_file_passes_ruff(self, written):
        """Unused and missing imports, and import order: what an editor would flag."""
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--no-cache",
                "--isolated",
                "--line-length",
                "100",
                "--select",
                "F,I",
                "--config",
                "lint.isort.known-local-folder=['shared']",
                str(written),
            ],
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stdout

    def test_every_generated_manifest_records_the_protocol(self, written, from_git):
        for directory in (written, from_git):
            for folder in directory.iterdir():
                assert read_manifest(folder)["protocol"] == "0.7", folder

    def test_owpp_check_strict_passes(self, written, capsys):
        assert main(["check", "--strict", "--dir", str(written)], env={}) == 0
        out = capsys.readouterr().out
        assert "env   FULL_EVENT_SYNC_MINUTES (default 15)" in out
        assert 'access="public"' in out and "static: access: public" in out

    def test_every_plugin_passes_its_own_tests(self, written):
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "owpp",
                "test",
                "--dir",
                str(written),
                "--",
                "-p",
                "no:cacheprovider",
            ],
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert " failed" not in done.stdout

    def test_the_manifest_says_what_was_asked(self, written):
        m = read_manifest(written / "full_filter")
        assert m["function"]["global"] is False  # a toggle is never global
        assert m["function"]["icon_url"] == "https://example.com/icon.svg"
        assert m["tool"] == {
            "id": "full_filter_tool",
            "title": "Lookup",
            "description": "Looks things up.",
            "include": ["chat_data", "templates"],  # templates: its rich UI page
            "access": "public",
        }
        assert m["include"] == ["routes", "chat_data"]
        assert read_manifest(written / "full_event")["jobs"] == {
            "sync_every_minutes": "${FULL_EVENT_SYNC_MINUTES:-15}"
        }
        assert read_manifest(written / "full_action")["static"] == {"access": "public"}
        assert read_manifest(written / "min_event")["include"] == ["events"]

    def test_valves_are_left_to_fill_in(self, written):
        code = (written / "full_filter" / "function.py").read_text()
        assert "plugin/development/valves" in code  # where the widgets are documented
        assert "priority: int" in code and "ENABLE: bool" in code
        assert "class UserValves(BaseModel):" in code
        assert "self.toggle = True" in code and "self.file_handler = True" in code

    def test_an_installer_has_no_function_code(self, written):
        folder = written / "installs_tool"
        assert not (folder / "function.py").exists() and (folder / "tool.py").is_file()
        assert read_manifest(folder)["function"]["global"] is True
        folder = written / "installs_skills"
        assert sorted(p.name for p in (folder / "skills").iterdir()) == ["a-skill", "b"]

    def test_skills_follow_open_webuis_layout(self, written):
        text = (written / "full_filter" / "skills" / "take-notes" / "SKILL.md").read_text()
        assert text.startswith(
            '---\nname: take-notes\ndescription: "Take notes in the chat."\naccess: public\n---\n'
        )
        for section in ("When to Use", "Prerequisites", "Procedure", "Pitfalls", "Verification"):
            assert f"\n## {section}\n" in text

    def test_the_readme_has_test_and_deploy(self, written, from_git):
        for d, specs in ((written, SPECS), (from_git, GIT_SPECS)):
            for spec in specs:
                readme = (d / spec.id / "README.md").read_text()
                assert "\n## Test\n" in readme and "\n## Deploy\n" in readme
                assert f"owpp test {spec.id}" in readme

    def test_it_refuses_a_folder_that_exists(self, written):
        with pytest.raises(OwppError, match="already exists"):
            write_plugin(written, PluginSpec(id="min_event"))


class TestFromGit:
    def test_the_manifest_pins_the_repository(self, from_git):
        m = read_manifest(from_git / "git_installer")
        assert m["source"] == {"git": GIT, "ref": SHA, "path": "plugins/viz"}
        assert m["tool"] == {"id": "viz", "file": "tool.py", "access": "public"}
        assert m["skills"] == {
            "visualize": {"dir": "skills/visualize", "access": "public"},
            "draw": {"file": "draw/SKILL.md"},
        }
        assert m["function"]["global"] is True
        m = read_manifest(from_git / "git_function")
        assert m["function"] == {"file": "src/function.py", "global": True}
        assert "tool" not in m and "skills" not in m

    def test_it_writes_no_code_of_its_own(self, from_git):
        for spec in GIT_SPECS:
            names = {p.name for p in (from_git / spec.id).iterdir()}
            # An installer's version is ours, so it has a changelog; an upstream function's is not.
            changelog = {"CHANGELOG.md"} if spec.type == "installer" else set()
            assert names == {"plugin.yaml", "README.md", "tests"} | changelog
            readme = (from_git / spec.id / "README.md").read_text()
            assert SHA in readme and "To upgrade" in readme

    def test_it_bundles_from_the_pinned_files(self, from_git):
        # The upstream function is global, so it must be a filter (or an action).
        sources = fake_sources({"src/function.py": "class Filter:\n    pass\n"})
        functions = {f.id: f for f in load_function_files(from_git, sources)}
        for spec in GIT_SPECS:
            assert check_bundle(functions[spec.id].content) is None, spec.id

    def test_its_tests_are_python(self, from_git):
        for spec in GIT_SPECS:
            ast.parse((from_git / spec.id / "tests" / f"test_{spec.id}.py").read_text())


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "spec, message",
        [
            (PluginSpec(id="my-plugin"), "not a valid id"),
            (PluginSpec(id="p", type="model"), "type must be"),
            (PluginSpec(id="p", type="event", global_=True), "filters and actions only"),
            (PluginSpec(id="p", type="action", toggle=True), "never global"),
            (PluginSpec(id="p", type="filter", assets=True), "Event function"),
            (PluginSpec(id="p", live_reload=True), "live_reload"),
            (PluginSpec(id="p", type="filter", hooks=[]), "at least one"),
            (PluginSpec(id="p", events=["function.valve_updated"]), "did you mean"),
            (PluginSpec(id="p", type="action", buttons=[("a.b", "A")]), "no dots"),
            (PluginSpec(id="p", tool=ToolSpec("t")), "at least one method"),
            (PluginSpec(id="p", tool=ToolSpec("t", methods=["a", "a"])), "declared twice"),
            (PluginSpec(id="p", skills=[SkillSpec("Notes")]), "not a valid skill name"),
            (PluginSpec(id="p", description="two\nlines"), "one line"),
            (PluginSpec(id="p", type="installer"), "at least one"),
            (
                PluginSpec(id="p", type="installer", tool=ToolSpec("t", ["a"]), page="static"),
                "written here",
            ),
            (PluginSpec(id="p", type="upstream"), "source repository"),
            (
                PluginSpec(
                    id="p", type="filter", source=SourceSpec(GIT, SHA), tool=ToolSpec("t", ["a"])
                ),
                "installer or takes its function",
            ),
            (
                PluginSpec(
                    id="p",
                    type="installer",
                    source=SourceSpec(GIT, "main"),
                    tool=ToolSpec("t", file="t.py"),
                ),
                "40-character",
            ),
            (
                PluginSpec(
                    id="p",
                    type="installer",
                    source=SourceSpec("/local/repo", SHA),
                    tool=ToolSpec("t", file="t.py"),
                ),
                "git URL",
            ),
            (
                PluginSpec(
                    id="p",
                    type="installer",
                    source=SourceSpec(GIT, SHA),
                    tool=ToolSpec("t", file="../t.py"),
                ),
                "without . or ..",
            ),
            (PluginSpec(id="p", type="installer", tool=ToolSpec("t", file="t.py")), "source"),
        ],
    )
    def test_a_spec_that_would_not_work(self, spec, message):
        with pytest.raises(OwppError, match=message):
            render(spec)


# ---- the wizard ------------------------------------------------------------------------


def scripted(answers: list[str]):
    """A reader that answers the wizard's questions in order, then ends the input."""
    queue = list(answers)
    asked: list[str] = []

    def read(prompt: str) -> str:
        asked.append(prompt)
        if not queue:
            raise EOFError
        return queue.pop(0)

    read.asked = asked  # type: ignore[attr-defined]
    read.left = queue  # type: ignore[attr-defined]
    return read


def git_repo() -> FakeRepo:
    """The repository the wizard is pointed at: branch main and tag v1.2, both at SHA."""
    return FakeRepo(GIT, sha=SHA, branches={"main": SHA}, tags={"v1.2": SHA})


def wizard(
    directory,
    answers,
    preset_id="",
    repo=None,
    check=True,
):
    read = scripted(answers)
    out = io.StringIO()
    code = run_wizard(
        directory,
        preset_id,
        Prompter(read, out),
        check=(lambda d, i: main(["check", i, "--strict", "--dir", str(d)], env={}))
        if check
        else None,
        sources=(repo or git_repo()).sources(),
    )
    return code, out.getvalue(), read


HEADER = [""] * 5  # description, author, version, license, Open-WebUI
# Enter at every question of the event path: ready, id, title, where, type, the header, the
# event's three, tool, skills, the four of pages and libraries.
ALL_DEFAULTS = ["", "", "", "", "", *HEADER, "", "", "", "", "", "", "", "", ""]


class TestWizard:
    def test_enter_all_the_way_makes_an_event_plugin_like_init(self, tmp_path, capsys):
        code, out, read = wizard(tmp_path, [*ALL_DEFAULTS, ""], preset_id="hello")
        assert code == 0, out
        assert read.left == []
        assert "Stage 9/9 · Review and write" in out and "ready to fill in" in out
        (fn,) = load_function_files(tmp_path)
        assert fn.id == "hello" and fn.type == "event"
        assert "ok    hello" in capsys.readouterr().out  # owpp check --strict ran
        assert not (tmp_path / "hello" / "tool.py").exists()

    def test_a_filter_with_everything(self, tmp_path):
        answers = [
            *["", "notes", "", "here", "filter"],
            *["Keeps notes.", "me", "", "", ""],  # header
            *["1,3,4", "y", "", "y"],  # hooks inlet, stream, outlet; toggle; file_handler; priority
            *["y", "", "lookup, save", "", "", "y", ""],  # tool: id, methods, title, public, UI
            *["y", "take-notes", "Take notes.", "", ""],  # one skill
            *["rendered", "admin", "y", ""],  # page, who, chat_data, config
            "",  # write
        ]
        code, out, read = wizard(tmp_path, answers)
        assert code == 0, out
        assert read.left == []
        folder = tmp_path / "notes"
        m = read_manifest(folder)
        assert m["function"]["description"] == "Keeps notes." and m["function"]["global"] is False
        assert m["tool"]["id"] == "notes" and m["include"] == ["routes", "chat_data"]
        code_text = (folder / "function.py").read_text()
        assert "async def stream(" in code_text and "async def request(" not in code_text
        assert "user: PluginAdmin" in code_text and "priority: int" in code_text
        tool_text = (folder / "tool.py").read_text()
        assert "async def lookup(" in tool_text and "async def save(" in tool_text
        assert (folder / "skills" / "take-notes" / "SKILL.md").is_file()

    def test_an_installer_of_a_skill(self, tmp_path):
        answers = [
            *["", "kit", "", "", "installer"],
            *["", "", "", ""],  # header: description, author, version, license
            "",  # the installer's options: a note
            "n",  # no tool
            *["deploy-kit", "", ""],  # one skill is required: no "Add?" first
            "",  # another? no
            "",  # pages and libraries: a note
            "",  # write
        ]
        code, out, read = wizard(tmp_path, answers)
        assert code == 0, out
        assert read.left == []
        assert not (tmp_path / "kit" / "function.py").exists()
        assert (tmp_path / "kit" / "skills" / "deploy-kit" / "SKILL.md").is_file()

    def test_not_sure_asks_the_authoring_guides_questions(self, tmp_path):
        answers = ["", "btn", "", "", "help", "n", "n", "y"] + [""] * 30
        code, out, read = wizard(tmp_path, answers)
        assert code == 0, out
        assert any("Is it a button" in q for q in read.asked)
        (fn,) = load_function_files(tmp_path)
        assert fn.type == "action"

    def test_from_git_it_installs_a_tool_and_skills_at_a_commit(self, tmp_path):
        repo = git_repo()
        answers = [
            *["", "viz", "", "git"],
            *[GIT, "v1.2", "plugins/viz"],  # repository, tag, folder
            *["", "", "", "", ""],  # no function; take a tool: tool.py, id viz, public
            *["y", "visualize", "", ""],  # a skill: id, folder, public
            "",  # another? no
            *["", "", "", ""],  # header
            "",  # write
        ]
        code, out, read = wizard(tmp_path, answers, repo=repo, check=False)
        assert code == 0, out
        assert read.left == [] and repo.looked_up == [(GIT, "v1.2")]
        assert "Stage 6/6 · Review and write" in out and f"v1.2 is commit {SHA}" in out
        m = read_manifest(tmp_path / "viz")
        # The tag it was given is what owpp pull follows.
        assert m["source"] == {"git": GIT, "ref": SHA, "path": "plugins/viz", "tag": "v1.2"}
        assert m["tool"] == {"id": "viz", "file": "tool.py", "access": "public"}
        assert m["skills"] == {"visualize": {"dir": "skills/visualize", "access": "public"}}

    def test_from_git_it_can_take_the_function_itself(self, tmp_path):
        answers = [
            *["", "upstream_fn", "", "git", GIT, SHA, ""],
            *["y", "", "n", ""],  # function.py; no tool; no skill
            "y",  # global
            "",  # write
        ]
        code, out, read = wizard(tmp_path, answers, check=False)
        assert code == 0, out
        assert read.left == []
        m = read_manifest(tmp_path / "upstream_fn")
        assert m["function"] == {"file": "function.py", "global": True}

    def test_a_ref_it_cannot_look_up_asks_for_the_commit(self, tmp_path):
        answers = [
            *["", "pinned", "", "git", GIT, "main", "not-a-sha", SHA, ""],
            "",  # nor can it tell what main is: a branch
            *["y", "", "n", "", "", ""],
        ]
        offline = FakeRepo(GIT)  # no branch or tag to find
        code, out, read = wizard(tmp_path, answers, repo=offline, check=False)
        assert code == 0, out
        assert "could not look up main" in out and "40 lowercase hex" in out
        source = read_manifest(tmp_path / "pinned")["source"]
        assert source["ref"] == SHA and source["branch"] == "main"

    def test_a_name_it_cannot_tell_is_asked_branch_or_tag(self, tmp_path, monkeypatch):
        answers = [
            *["", "pinned", "", "git", GIT, "stable", "", "2"],
            *["y", "", "n", "", "", ""],
        ]
        repo = FakeRepo(GIT, sha=SHA, branches={"stable": SHA})
        monkeypatch.setattr(repo, "kind", lambda git, name: None)  # the second question fails
        code, out, read = wizard(tmp_path, answers, repo=repo, check=False)
        assert code == 0, out
        assert "Is stable a branch or a tag?" in out and read.left == []
        assert read_manifest(tmp_path / "pinned")["source"]["tag"] == "stable"

    def test_owpp_create_reads_git_through_the_commands_sources(self, tmp_path, monkeypatch):
        repo = git_repo()
        repo.commits[SHA]["function.py"] = FILTER  # `owpp check` runs on what it writes
        monkeypatch.setattr("owpp.cli.Sources", repo.sources)
        answers = ["", "viz", "", "git", GIT, "main", "", "y", "", "n", "", "", ""]
        monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(answers) + "\n"))
        main(["create", "--dir", str(tmp_path)], env={})
        assert read_manifest(tmp_path / "viz")["source"]["branch"] == "main"

    def test_taking_nothing_from_git_writes_nothing(self, tmp_path):
        answers = ["", "empty", "", "git", GIT, SHA, "", "", "n", ""]
        code, out, _ = wizard(tmp_path, answers, check=False)
        assert code == 1 and "takes nothing" in out
        assert list(tmp_path.iterdir()) == []

    def test_ctrl_c_writes_nothing(self, tmp_path):
        code, out, _ = wizard(tmp_path, ["", "half"])  # input ends at the title
        assert code == 130 and "nothing was written" in out
        assert list(tmp_path.iterdir()) == []

    def test_a_bad_answer_is_asked_again(self, tmp_path):
        answers = ["", "My-Plugin", *ALL_DEFAULTS[1:], ""]
        answers[2:3] = ["my_plugin", ""]  # the id again, then the title
        code, out, _ = wizard(tmp_path, answers)
        assert code == 0, out
        assert '"My-Plugin" is not valid' in out
        assert (tmp_path / "my_plugin").is_dir()

    def test_saying_no_at_the_end_writes_nothing(self, tmp_path):
        code, out, read = wizard(tmp_path, [*ALL_DEFAULTS, "n"], preset_id="nope")
        assert code == 1 and read.left == []
        assert not (tmp_path / "nope").exists()

    def test_owpp_create_reads_the_terminal(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join([*ALL_DEFAULTS, ""]) + "\n"))
        assert main(["create", "from_cli", "--dir", str(tmp_path)], env={}) == 0
        assert (tmp_path / "from_cli" / "plugin.yaml").is_file()
        assert "ready to fill in" in capsys.readouterr().out


def test_a_full_sha_needs_no_lookup():
    """Sources asks git only for a branch or tag."""
    with Sources() as sources:
        assert sources.latest("https://example.invalid/repo.git", SHA) == SHA
        assert sources.latest("/not/a/url", "main") is None


class TestFromASpec:
    """`owpp create --spec FILE`: the same plugin the wizard makes, described as data, for
    scripts and agents that cannot answer questions."""

    def test_a_spec_file_makes_the_plugin_and_checks_it(self, tmp_path, capsys):
        spec = tmp_path / "notes.yaml"
        spec.write_text(
            "id: notes\ntype: filter\nglobal: false\nhooks: [inlet, outlet]\n"
            "tool: {id: notes, methods: [save, search]}\n"
            "skills:\n  - {id: take-notes, description: Use it to remember.}\n  - draw\n"
            "page: rendered\npage_access: admin\n"
        )
        assert main(["create", "--spec", str(spec), "--dir", str(tmp_path / "p")], env={}) == 0
        assert "ok    notes" in capsys.readouterr().out
        folder = tmp_path / "p" / "notes"
        m = read_manifest(folder)
        assert m["function"]["global"] is False and m["tool"]["id"] == "notes"
        assert sorted(p.name for p in (folder / "skills").iterdir()) == ["draw", "take-notes"]
        assert (folder / "templates" / "page.html").is_file()

    def test_json_on_stdin_and_the_id_on_the_command_line(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(
                '{"type": "action", "buttons": ["summarize", {"id": "tr", "name": "Translate"}]}'
            ),
        )
        assert main(["create", "act", "--spec", "-", "--dir", str(tmp_path)], env={}) == 0
        code = (tmp_path / "act" / "function.py").read_text()
        assert '{"id": "summarize", "name": "Summarize"}, {"id": "tr", "name": "Translate"}' in code

    def test_a_plugin_from_git(self, tmp_path):
        spec = spec_from_data(
            {
                "id": "viz",
                "type": "installer",
                "source": {"git": GIT, "ref": SHA, "path": "v2", "branch": "main"},
                "tool": {"id": "viz", "file": "tool.py"},
                "skills": [{"id": "visualize", "path": "SKILL.md", "is_dir": False}],
            }
        )
        m = read_manifest(write_plugin(tmp_path, spec))
        assert m["source"]["branch"] == "main" and m["skills"] == {
            "visualize": {"file": "SKILL.md", "access": "public"}
        }

    @pytest.mark.parametrize(
        "data, message",
        [
            ({"id": "p", "tpye": "filter"}, "unknown key tpye"),
            ({"id": "p", "tool": {"id": "t", "metods": []}}, "tool: unknown key metods"),
            ({"type": "filter"}, "needs an id"),
            ([1, 2], "is a mapping"),
            ({"id": "p", "type": "action", "buttons": [3]}, "an id or"),
        ],
    )
    def test_what_it_refuses(self, data, message):
        with pytest.raises(OwppError, match=message):
            spec_from_data(data)

    def test_a_source_follows_a_branch_or_a_tag_not_both(self, tmp_path):
        spec = spec_from_data(
            {
                "id": "p",
                "type": "installer",
                "source": {"git": GIT, "ref": SHA, "branch": "main", "tag": "v1"},
                "tool": {"id": "t", "file": "t.py"},
            }
        )
        with pytest.raises(OwppError, match="a branch or a tag, not both"):
            write_plugin(tmp_path, spec)
