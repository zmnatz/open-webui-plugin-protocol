"""`owpp create`: the plugin it writes (owpp.create) and the wizard that asks for it (owpp.wizard)."""

from __future__ import annotations

import io
import subprocess
import sys

import pytest

from owpp.bundle import load_function_files
from owpp.cli import check_bundle, main
from owpp.create import (
    FILTER_HOOKS,
    TYPES,
    PluginSpec,
    SkillSpec,
    ToolMethod,
    ToolSpec,
    Valve,
    parse_default,
    render,
    write_plugin,
)
from owpp.errors import OwppError
from owpp.lint import lint_plugin
from owpp.manifest import read_manifest
from owpp.wizard import Prompter, run_wizard

VALVES = [
    Valve("API_URL", "str", "http://api", "Where the API is."),
    Valve("API_KEY", "password", None, "The API key."),
    Valve("MODE", "select", None, "How it runs.", ["fast", "slow"]),
    Valve("TAGS", "multiselect", ["a"], "Which tags.", ["a", "b"]),
    Valve("TEMPERATURE", "range", 0.5, "How creative.", minimum=0, maximum=1, step=0.1),
    Valve("LIMIT", "int", 3, "How many."),
    Valve("RATIO", "float", 1.5, "A ratio."),
    Valve("VERBOSE", "bool", False, "Log more."),
]
USER_VALVES = [Valve("STYLE", "select", None, "Your style.", ["short", "long"])]


def tool(tool_id: str) -> ToolSpec:
    return ToolSpec(
        tool_id,
        "Lookup",
        "Looks things up.",
        [
            ToolMethod("lookup", "Look something up.", [("query", "str"), ("limit", "int")]),
            ToolMethod("tags", "List tags.", [("names", "list[str]"), ("all", "bool")]),
            ToolMethod("ping", "Check it is up.", []),
        ],
        public=True,
        rich_ui=True,
        chat_data=True,
    )


# Every part the wizard can add, in at least one plugin of each type.
SPECS = [PluginSpec(id=f"min_{t}", type=t) for t in TYPES] + [
    PluginSpec(
        id="full_filter",
        type="filter",
        icon_url="https://example.com/icon.svg",
        requirements="httpx",
        required_open_webui_version="0.10.0",
        valves=VALVES,
        user_valves=USER_VALVES,
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
        valves=VALVES,
        user_valves=USER_VALVES,
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
        valves=VALVES,
        user_valves=USER_VALVES,
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
        valves=VALVES,
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
]


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    directory = tmp_path_factory.mktemp("plugins")
    for spec in SPECS:
        write_plugin(directory, spec)
    return directory


class TestWhatItWrites:
    def test_every_plugin_bundles_compiles_and_has_no_warnings(self, written):
        functions = {f.id: f for f in load_function_files(written)}
        assert sorted(functions) == sorted(s.id for s in SPECS)
        for spec in SPECS:
            fn = functions[spec.id]
            assert fn.type == spec.type
            assert check_bundle(fn.content, f"{spec.id}.py") is None, spec.id
            assert lint_plugin(written / spec.id, spec.id) == [], spec.id

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
            "include": ["chat_data"],
            "access": "public",
        }
        assert m["include"] == ["routes", "chat_data"]
        assert read_manifest(written / "full_event")["jobs"] == {
            "sync_every_minutes": "${FULL_EVENT_SYNC_MINUTES:-15}"
        }
        assert read_manifest(written / "full_action")["static"] == {"access": "public"}
        assert read_manifest(written / "min_event")["include"] == ["events"]

    def test_the_valves_are_the_widgets_open_webui_documents(self, written):
        code = (written / "full_filter" / "function.py").read_text()
        assert 'json_schema_extra={"input": {"type": "password"}}' in code
        assert 'MODE: Literal["fast", "slow"]' in code
        assert '"type": "multiselect", "options": ["a", "b"]' in code
        assert '"type": "range", "step": 0.1' in code and "ge=0" in code and "le=1" in code
        assert "class UserValves(BaseModel):" in code
        assert "self.toggle = True" in code and "self.file_handler = True" in code

    def test_skills_follow_open_webuis_layout(self, written):
        text = (written / "full_filter" / "skills" / "take-notes" / "SKILL.md").read_text()
        assert text.startswith(
            '---\nname: take-notes\ndescription: "Take notes in the chat."\naccess: public\n---\n'
        )
        for section in ("When to Use", "Prerequisites", "Procedure", "Pitfalls", "Verification"):
            assert f"\n## {section}\n" in text

    def test_the_readme_has_test_and_deploy(self, written):
        for spec in SPECS:
            readme = (written / spec.id / "README.md").read_text()
            assert "\n## Test\n" in readme and "\n## Deploy\n" in readme
            assert f"owpp test {spec.id}" in readme

    def test_it_refuses_a_folder_that_exists(self, written):
        with pytest.raises(OwppError, match="already exists"):
            write_plugin(written, PluginSpec(id="min_event"))


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "spec, message",
        [
            (PluginSpec(id="my-plugin"), "not a valid id"),
            (PluginSpec(id="p", type="model"), "type must be"),
            (PluginSpec(id="p", type="event", global_=True), "filters and actions only"),
            (PluginSpec(id="p", type="action", toggle=True), "never global"),
            (PluginSpec(id="p", type="event", user_valves=[Valve("X")]), "no user valves"),
            (PluginSpec(id="p", type="filter", assets=True), "Event function"),
            (PluginSpec(id="p", live_reload=True), "live_reload"),
            (PluginSpec(id="p", type="filter", hooks=[]), "at least one"),
            (PluginSpec(id="p", events=["function.valve_updated"]), "did you mean"),
            (PluginSpec(id="p", valves=[Valve("ENABLE", "bool")]), "added by the wizard"),
            (PluginSpec(id="p", valves=[Valve("A"), Valve("A")]), "declared twice"),
            (PluginSpec(id="p", valves=[Valve("M", "select")]), "needs options"),
            (PluginSpec(id="p", type="action", buttons=[("a.b", "A")]), "no dots"),
            (PluginSpec(id="p", tool=ToolSpec("t")), "at least one method"),
            (
                PluginSpec(
                    id="p", tool=ToolSpec("t", methods=[ToolMethod("f", "", [("x", "dict")])])
                ),
                "parameter types",
            ),
            (PluginSpec(id="p", skills=[SkillSpec("Notes")]), "not a valid skill name"),
            (PluginSpec(id="p", description="two\nlines"), "one line"),
        ],
    )
    def test_a_spec_that_would_not_work(self, spec, message):
        with pytest.raises(OwppError, match=message):
            render(spec)

    def test_defaults_are_read_as_the_valves_type(self):
        assert parse_default("bool", "") is True
        assert parse_default("bool", "no") is False
        assert parse_default("int", "4") == 4
        assert parse_default("range", "0.25") == 0.25
        assert parse_default("select", "", ["a", "b"]) == "a"
        assert parse_default("multiselect", "a, b", ["a", "b"]) == ["a", "b"]
        with pytest.raises(OwppError):
            parse_default("int", "four")
        with pytest.raises(OwppError):
            parse_default("select", "c", ["a", "b"])


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


def wizard(directory, answers, preset_id=""):
    read = scripted(answers)
    out = io.StringIO()
    code = run_wizard(
        directory,
        preset_id,
        Prompter(read, out),
        check=lambda d, i: main(["check", i, "--strict", "--dir", str(d)], env={}),
    )
    return code, out.getvalue(), read


HEADER_DEFAULTS = [""] * 7  # description, author, version, license, Open-WebUI, icon, pip


class TestWizard:
    def test_enter_all_the_way_makes_an_event_plugin_like_init(self, tmp_path, capsys):
        answers = ["", "", ""] + HEADER_DEFAULTS + [""] * 20
        code, out, read = wizard(tmp_path, answers, preset_id="hello")
        assert code == 0, out
        assert "Stage 10/10 · Review and write" in out and "ready to fill in" in out
        (fn,) = load_function_files(tmp_path)
        assert fn.id == "hello" and fn.type == "event"
        assert "ok    hello" in capsys.readouterr().out  # owpp check --strict ran
        assert not (tmp_path / "hello" / "tool.py").exists()

    def test_a_filter_with_everything(self, tmp_path):
        answers = [
            "",  # ready
            "notes",
            "",  # id, title
            "Keeps notes.",
            "me",
            "",
            "",
            "",
            "",
            "",  # header
            "filter",
            "1,3,4",  # hooks: inlet, stream, outlet
            "y",  # a toggle
            "",  # file_handler
            "y",  # priority
            "API_KEY",
            "5",  # password
            "",
            "The key.",
            "MODE",
            "select",
            "fast, slow",
            "",
            "How it runs.",
            "",  # valves done
            "y",
            "SHORT",
            "bool",
            "",
            "Short answers.",
            "",  # user valves
            "y",
            "",
            "",
            "",  # tool id, title, description
            "",
            "",
            "query:str, limit:int",  # method lookup
            "",  # methods done
            "",
            "y",
            "",  # public, rich UI, chat_data
            "y",
            "take-notes",
            "Take notes.",
            "",
            "",  # one skill
            "rendered",
            "admin",
            "y",
            "",  # page, chat_data, config
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
        assert "API_KEY: str" in code_text and 'MODE: Literal["fast", "slow"]' in code_text
        assert "SHORT: bool" in code_text and "user: PluginAdmin" in code_text
        assert "async def lookup(self, query: str, limit: int" in (folder / "tool.py").read_text()
        assert (folder / "skills" / "take-notes" / "SKILL.md").is_file()
        assert (folder / "templates" / "page.html").is_file()

    def test_not_sure_asks_the_authoring_guides_questions(self, tmp_path):
        answers = ["", "btn", ""] + HEADER_DEFAULTS + ["help", "n", "y"] + [""] * 30
        code, out, read = wizard(tmp_path, answers)
        assert code == 0, out
        assert "Is it a button" in "".join(read.asked)
        (fn,) = load_function_files(tmp_path)
        assert fn.type == "action"

    def test_ctrl_c_writes_nothing(self, tmp_path):
        code, out, _ = wizard(tmp_path, ["", "half"])  # input ends at the title
        assert code == 130 and "nothing was written" in out
        assert list(tmp_path.iterdir()) == []

    def test_a_bad_answer_is_asked_again(self, tmp_path):
        answers = ["", "My-Plugin", "my_plugin", ""] + HEADER_DEFAULTS + [""] * 20
        code, out, _ = wizard(tmp_path, answers)
        assert code == 0
        assert '"My-Plugin" is not valid' in out
        assert (tmp_path / "my_plugin").is_dir()

    def test_saying_no_at_the_end_writes_nothing(self, tmp_path):
        answers = ["", "", ""] + HEADER_DEFAULTS + [""] * 12 + ["n"]
        code, out, read = wizard(tmp_path, answers, preset_id="nope")
        assert code == 1 and read.left == []
        assert not (tmp_path / "nope").exists()

    def test_owpp_create_reads_the_terminal(self, tmp_path, monkeypatch, capsys):
        answers = ["", "", ""] + HEADER_DEFAULTS + [""] * 20
        monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(answers) + "\n"))
        assert main(["create", "from_cli", "--dir", str(tmp_path)], env={}) == 0
        assert (tmp_path / "from_cli" / "plugin.yaml").is_file()
        assert "ready to fill in" in capsys.readouterr().out
