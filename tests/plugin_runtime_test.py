"""Tests for src/owpp/runtime/plugin_runtime.py with Open-WebUI stubbed out.

Run by pytest."""

import asyncio
import json
import pathlib
import sys
import types
import unittest

RUNTIME = (
    pathlib.Path(__file__).resolve().parent.parent
    / "src"
    / "owpp"
    / "runtime"
    / "plugin_runtime.py"
)
DATA = {
    "tools": [
        {
            "id": "demo_tool",
            "name": "Demo",
            "access": "public",
            "self": False,
            "content": "class Tools: pass\n",
            "valves": {"level": "strict"},
        },
        {
            "id": "self_tool",
            "name": "Self",
            "access": "private",
            "self": True,
            "content": None,
            "valves": {},
        },
    ],
    "skills": [
        {
            "id": "visualize",
            "name": "visualize",
            "description": "d",
            "access": "public",
            "files": [
                {"path": "references/a.md", "content": "ref\n"},
                {"path": "SKILL.md", "content": "# Body\n"},
            ],
        },
    ],
}


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self):
        return dict(self.__dict__)


class Fake:
    """In-memory stand-ins for the Open-WebUI modules the runtime imports."""

    def __init__(self):
        self.function = Obj(
            id="demo", user_id="u1", is_active=True, content="# the function file\n"
        )
        self.tools, self.skills, self.sinks = {}, {}, []
        self.function_valves, self.tool_valves = {}, {}
        self.tool_module = types.SimpleNamespace()
        fake = self

        class Functions:
            @staticmethod
            async def get_function_by_id(i):
                return fake.function if fake.function and fake.function.id == i else None

            @staticmethod
            async def get_function_valves_by_id(i):
                return fake.function_valves

        class ToolMeta(Obj):
            pass

        class ToolForm(Obj):
            pass

        class Tools:
            @staticmethod
            async def get_tool_by_id(i):
                return fake.tools.get(i)

            @staticmethod
            async def insert_new_tool(user_id, form, specs, module=None):
                fake.tools[form.id] = Obj(
                    id=form.id, content=form.content, meta=form.meta, grants=form.access_grants
                )

            @staticmethod
            async def update_tool_by_id(i, updated, user_id=None, module=None):
                t = fake.tools[i]
                t.content = updated["content"]
                t.meta = Obj(**updated["meta"])

            @staticmethod
            async def get_tool_valves_by_id(i):
                return fake.tool_valves.get(i)

            @staticmethod
            async def update_tool_valves_by_id(i, valves):
                fake.tool_valves[i] = dict(valves)

            @staticmethod
            async def delete_tool_by_id(i):
                fake.tools.pop(i, None)

        class SkillMeta(Obj):
            pass

        class SkillForm(Obj):
            pass

        class Skills:
            @staticmethod
            async def get_skill_by_id(i):
                return fake.skills.get(i)

            @staticmethod
            async def insert_new_skill(user_id, form):
                fake.skills[form.id] = Obj(
                    **form.__dict__, data={"files": [dict(f) for f in form.files]}, version_id="v1"
                )

            @staticmethod
            async def update_skill_by_id(i, updated, user_id=None):
                assert updated["expected_version_id"] == fake.skills[i].version_id
                skill = fake.skills[i]
                skill.name, skill.description = updated["name"], updated["description"]
                skill.data = {"files": updated["files"]}
                skill.version_id += "+"
                skill.meta = Obj(**updated["meta"])

            @staticmethod
            async def delete_skill_by_id(i):
                return fake.skills.pop(i, None) is not None

        async def load_tool_module_by_id(i, content=None):
            return fake.tool_module, {"description": "from header"}, None

        mods = {
            "open_webui": {},
            "open_webui.models": {},
            "open_webui.models.functions": {"Functions": Functions},
            "open_webui.models.tools": {"Tools": Tools, "ToolForm": ToolForm, "ToolMeta": ToolMeta},
            "open_webui.models.skills": {
                "Skills": Skills,
                "SkillForm": SkillForm,
                "SkillMeta": SkillMeta,
            },
            "open_webui.utils": {},
            "open_webui.utils.plugin": {
                "load_tool_module_by_id": load_tool_module_by_id,
                "replace_imports": lambda c: c,
            },
            "open_webui.utils.tools": {"get_tool_specs": lambda m: []},
            "open_webui.events": {"EVENT_SINKS": self.sinks},
        }
        self.saved = {k: sys.modules.get(k) for k in mods}
        for name, attrs in mods.items():
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            sys.modules[name] = m

    def close(self):
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        for k in [k for k in sys.modules if k.startswith("_plugin_runtime_")]:
            del sys.modules[k]


def load_runtime(module_name="function_demo_0123456789abcdef0123456789abcdef", data=None):
    source = RUNTIME.read_text().replace("__PLUGIN_DATA__", json.dumps(json.dumps(data or DATA)))
    module = types.ModuleType(module_name)
    sys.modules[module.__name__] = module
    exec(compile(source, str(RUNTIME), "exec"), module.__dict__)
    return module


class PluginRuntime(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.rt = load_runtime()

    def tearDown(self):
        self.fake.close()
        sys.modules.pop(self.rt.__name__, None)

    def sync(self):
        asyncio.run(self.rt._plugin_sync("demo"))

    def test_enabled_function_installs_tools_and_skills(self):
        self.sync()
        tools, skills = self.fake.tools, self.fake.skills
        self.assertEqual(set(tools), {"demo_tool", "self_tool"})
        self.assertEqual(tools["demo_tool"].content, "class Tools: pass\n")
        self.assertEqual(tools["self_tool"].content, "# the function file\n")  # from: function
        self.assertEqual(tools["demo_tool"].meta.manifest["parent_function_id"], "demo")
        self.assertEqual(len(tools["demo_tool"].grants), 1)  # public
        self.assertEqual(tools["self_tool"].grants, [])  # private
        self.assertEqual(skills["visualize"].meta.tags, ["plugin:demo"])
        # every file of the skill folder, sorted by path, SKILL.md included
        self.assertEqual(
            [f["path"] for f in skills["visualize"].data["files"]], ["SKILL.md", "references/a.md"]
        )

    def test_a_second_sync_changes_nothing_and_an_update_is_applied(self):
        self.sync()
        before = dict(self.fake.tools)
        self.sync()
        self.assertEqual(self.fake.tools, before)
        self.fake.function.content = "# edited function file\n"
        self.sync()
        self.assertEqual(self.fake.tools["self_tool"].content, "# edited function file\n")

    def test_disabling_or_deleting_the_function_removes_what_it_installed(self):
        self.sync()
        self.fake.function.is_active = False
        self.sync()
        self.assertEqual((self.fake.tools, self.fake.skills), ({}, {}))
        self.fake.function.is_active = True
        self.sync()
        self.assertEqual(len(self.fake.tools), 2)
        self.fake.function = None
        self.sync()
        self.assertEqual((self.fake.tools, self.fake.skills), ({}, {}))

    def test_things_that_are_not_this_plugins_are_left_alone(self):
        self.fake.tools["demo_tool"] = Obj(
            id="demo_tool", content="hand made", meta=Obj(manifest={})
        )
        self.fake.skills["visualize"] = Obj(
            id="visualize", name="x", description="", data={"files": []}, meta=Obj(tags=[])
        )
        self.sync()
        self.assertEqual(self.fake.tools["demo_tool"].content, "hand made")
        self.assertEqual(self.fake.skills["visualize"].data, {"files": []})
        self.fake.function.is_active = False
        self.sync()
        self.assertIn("demo_tool", self.fake.tools)
        self.assertIn("visualize", self.fake.skills)

    def test_a_changed_skill_file_is_updated_and_an_unchanged_one_is_not(self):
        self.sync()
        self.assertEqual(self.fake.skills["visualize"].version_id, "v1")
        self.sync()
        self.assertEqual(self.fake.skills["visualize"].version_id, "v1")
        self.rt._PLUGIN["skills"][0]["files"][0]["content"] = "ref changed\n"
        self.sync()
        skill = self.fake.skills["visualize"]
        self.assertEqual(skill.version_id, "v1+")
        self.assertEqual(skill.data["files"][1]["content"], "ref changed\n")

    def test_event_sink_syncs_only_for_its_own_function_and_events(self):
        async def run():
            sink = self.rt._PluginSink()
            sink.function_id = "demo"
            await sink.handle_event(None, {"event": "function.enabled", "subject": {"id": "other"}})
            self.assertEqual(self.fake.tools, {})
            await sink.handle_event(
                None, {"event": "function.valves_updated", "subject": {"id": "demo"}}
            )
            self.assertEqual(self.fake.tools, {})
            await sink.handle_event(None, {"event": "function.enabled", "subject": {"id": "demo"}})
            self.assertEqual(len(self.fake.tools), 2)

        asyncio.run(run())

    def test_starting_inside_a_loop_registers_one_sink_and_syncs(self):
        async def run():
            self.rt._plugin_start()
            self.rt._plugin_start()
            await asyncio.sleep(0.05)

        asyncio.run(run())
        self.assertEqual(len(self.fake.sinks), 1)
        self.assertEqual(len(self.fake.tools), 2)

    def test_install_toggles_remove_only_their_half(self):
        self.sync()
        self.fake.function_valves = {"INSTALL_SKILLS": False}
        self.sync()
        self.assertEqual(set(self.fake.tools), {"demo_tool", "self_tool"})
        self.assertEqual(self.fake.skills, {})
        self.fake.function_valves = {"INSTALL_TOOLS": False, "INSTALL_SKILLS": True}
        self.sync()
        self.assertEqual(self.fake.tools, {})
        self.assertEqual(set(self.fake.skills), {"visualize"})
        self.fake.function_valves = {}
        self.sync()
        self.assertEqual((len(self.fake.tools), len(self.fake.skills)), (2, 1))

    def test_declared_tool_valves_are_applied_and_other_valves_kept(self):
        self.fake.tool_valves["demo_tool"] = {"chime": True}
        self.sync()
        self.assertEqual(self.fake.tool_valves["demo_tool"], {"chime": True, "level": "strict"})
        self.assertNotIn("self_tool", self.fake.tool_valves)

    def test_tool_valves_json_overrides_the_manifest_and_bad_json_is_ignored(self):
        self.fake.function_valves = {
            "TOOL_VALVES": json.dumps({"demo_tool": {"level": "loose", "x": 1}})
        }
        self.sync()
        self.assertEqual(self.fake.tool_valves["demo_tool"], {"level": "loose", "x": 1})
        self.fake.tool_valves.clear()
        self.fake.function_valves = {"TOOL_VALVES": "{not json"}
        self.sync()
        self.assertEqual(self.fake.tool_valves["demo_tool"], {"level": "strict"})

    def test_valves_the_tool_would_reject_are_not_applied(self):
        class Valves:
            def __init__(self, **kw):
                if kw.get("level") == "strict":
                    raise ValueError("bad level")

        self.fake.tool_module = types.SimpleNamespace(Valves=Valves)
        self.sync()
        self.assertNotIn("demo_tool", self.fake.tool_valves)
        self.assertIn("demo_tool", self.fake.tools)  # still installed

    def test_a_tool_that_loads_after_its_function_was_disabled_removes_the_plugin(self):
        self.sync()
        self.fake.function.is_active = False  # disabled while Open-WebUI was down
        ids = {"tools": [{"id": "demo_tool"}, {"id": "self_tool"}], "skills": [{"id": "visualize"}]}
        tool_rt = load_runtime("tool_demo_tool_0123456789abcdef0123456789abcdef", ids)
        try:
            asyncio.run(tool_rt._plugin_check_parent())
        finally:
            sys.modules.pop(tool_rt.__name__, None)
        self.assertEqual((self.fake.tools, self.fake.skills), ({}, {}))

    def test_a_tool_whose_function_is_enabled_stays(self):
        self.sync()
        ids = {"tools": [{"id": "demo_tool"}], "skills": []}
        tool_rt = load_runtime("tool_demo_tool_0123456789abcdef0123456789abcdef", ids)
        try:
            asyncio.run(tool_rt._plugin_check_parent())
        finally:
            sys.modules.pop(tool_rt.__name__, None)
        self.assertIn("demo_tool", self.fake.tools)


if __name__ == "__main__":
    unittest.main()
