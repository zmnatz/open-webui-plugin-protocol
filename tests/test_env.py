"""${NAME:-default} templates: resolved from the container's environment when the plugin loads,
never when it is bundled."""

from __future__ import annotations

import logging
import sys
import types

import pytest
from conftest import write_plugin

from owpp import envtemplate
from owpp.bundle import bundle_function, env_references, load_function_files
from owpp.cli import main
from owpp.errors import OwppError

HEX = "0" * 32
CORE = None


def core():
    """The core library, run on its own."""
    from owpp.libraries import LIB_DIR

    namespace: dict = {"__name__": "function_demo_" + HEX}
    exec(compile((LIB_DIR / "plugin_core.py").read_text(), "core.py", "exec"), namespace)
    return namespace


@pytest.fixture
def env(monkeypatch):
    for name in ("N", "FLAG", "HOST", "EMPTY", "MISSING"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class TestTheResolver:
    def test_a_whole_template_is_typed_like_a_yaml_scalar(self, env):
        resolve = core()["plugin_env"]
        for text, expected in [
            ("60", 60),
            ("-5", -5),
            ("+7", 7),
            ("1.5", 1.5),
            (".5", 0.5),
            ("1e3", 1000.0),
            ("true", True),
            ("True", True),
            ("false", False),
            ("FALSE", False),
            ("null", None),
            ("~", None),
            ("soon", "soon"),
            ("yes", "yes"),
            ("12:30", "12:30"),
            ("0x10", "0x10"),
        ]:
            env.setenv("N", text)
            result = resolve("${N}")
            assert result == expected and type(result) is type(expected), (text, result)

    def test_the_default_applies_when_unset_or_empty(self, env):
        resolve = core()["plugin_env"]
        assert resolve("${N:-60}") == 60
        env.setenv("N", "")
        assert resolve("${N:-60}") == 60  # like the shell's :-
        env.setenv("N", "30")
        assert resolve("${N:-60}") == 30

    def test_the_default_is_typed_too(self, env):
        resolve = core()["plugin_env"]
        assert (
            resolve("${N:-true}") is True
            and resolve("${N:-1.5}") == 1.5
            and resolve("${N:-http://x}") == "http://x"
        )

    def test_unset_with_no_default_is_none_and_warns(self, env, caplog):
        resolve = core()["plugin_env"]
        with caplog.at_level(logging.WARNING):
            assert resolve("${MISSING}") is None
        assert "MISSING is not set and has no default" in caplog.text

    def test_a_template_inside_a_longer_string_is_text(self, env, caplog):
        resolve = core()["plugin_env"]
        env.setenv("HOST", "mcpo")
        assert resolve("http://${HOST}:${N:-8000}/x") == "http://mcpo:8000/x"
        with caplog.at_level(logging.WARNING):
            assert resolve("a-${MISSING}-b") == "a--b"
        assert "MISSING" in caplog.text

    def test_it_reaches_into_dicts_and_lists_and_leaves_everything_else_alone(self, env):
        resolve = core()["plugin_env"]
        env.setenv("N", "3")
        data = {"${N}": ["${N}", {"k": "${N:-9}"}, 5, None, True, 1.5], "plain": "text"}
        assert resolve(data) == {
            "${N}": [3, {"k": 3}, 5, None, True, 1.5],
            "plain": "text",
        }  # keys are not templates

    def test_a_doubled_dollar_writes_a_literal_template(self, env):
        resolve = core()["plugin_env"]
        env.setenv("N", "3")
        assert resolve("$${N}") == "${N}"
        assert resolve("cost $${N} or ${N}") == "cost ${N} or 3"

    def test_a_value_that_is_not_a_template_is_untouched(self, env):
        resolve = core()["plugin_env"]
        for text in ("$HOME", "{N}", "${", "${N", "${1X}", "${}", "$ {N}"):
            assert resolve(text) == text

    def test_the_pattern_matches_the_one_the_bundler_validates_with(self):
        assert core()["_ENV_TEMPLATE"].pattern == envtemplate.TEMPLATE.pattern


class TestTheBundlerNeverReadsTheEnvironment:
    CODE = "class Event(PluginScheduledSync):\n    async def sync(self):\n        pass\n"

    def plugin(self, tmp_path, jobs="${N:-60}", config="flag: ${FLAG:-true}\n"):
        write_plugin(
            tmp_path / "p",
            {
                "plugin.yaml": f"function:\n  title: T\njobs:\n  sync_every_minutes: {jobs}\n",
                "config.yaml": config,
                "function.py": self.CODE,
            },
        )
        return tmp_path / "p"

    def test_the_bundle_is_the_same_whatever_the_machine_that_builds_it_has_set(
        self, tmp_path, env
    ):
        folder = self.plugin(tmp_path)
        before = bundle_function(folder)
        env.setenv("N", "999777")
        env.setenv("FLAG", "false")
        env.setenv("HOST", "leaked.example")
        after = bundle_function(folder)
        assert before == after  # a bundle depends on the folder, not on where it was built
        assert "999777" not in after and "leaked.example" not in after
        assert "${N:-60}" in after and "${FLAG:-true}" in after  # embedded as written

    def test_templates_are_resolved_by_the_running_plugin(self, tmp_path, env):
        folder = self.plugin(tmp_path)

        def run():
            module = types.ModuleType("function_p_" + HEX)
            sys.modules[module.__name__] = module
            try:
                exec(compile(bundle_function(folder), "p.py", "exec"), module.__dict__)
            finally:
                sys.modules.pop(module.__name__, None)
            return module

        assert run().Event.Valves().SYNC_INTERVAL_MINUTES == 60  # the container has nothing set
        env.setenv("N", "15")
        assert run().Event.Valves().SYNC_INTERVAL_MINUTES == 15
        env.setenv("N", "0")
        assert run().Event.Valves().SYNC_INTERVAL_MINUTES == 0
        assert run().plugin_config()["flag"] is True
        env.setenv("FLAG", "false")
        assert run().plugin_config()["flag"] is False

    @pytest.mark.parametrize("bad", ["soon", "-3", "1.5", "false"])
    def test_a_bad_interval_from_the_environment_falls_back_with_a_warning(
        self, tmp_path, env, caplog, bad
    ):
        folder = self.plugin(tmp_path)
        env.setenv("N", bad)
        module = types.ModuleType("function_p_" + HEX)
        sys.modules[module.__name__] = module
        try:
            with caplog.at_level(logging.WARNING):
                exec(compile(bundle_function(folder), "p.py", "exec"), module.__dict__)
        finally:
            sys.modules.pop(module.__name__, None)
        assert module.Event.Valves().SYNC_INTERVAL_MINUTES == 60
        assert "is not a whole number of minutes, using 60" in caplog.text

    def test_a_template_with_no_default_and_nothing_set_falls_back_to_an_hour(self, tmp_path, env):
        folder = self.plugin(tmp_path, jobs="${MISSING}")
        module = types.ModuleType("function_p_" + HEX)
        sys.modules[module.__name__] = module
        try:
            exec(compile(bundle_function(folder), "p.py", "exec"), module.__dict__)
        finally:
            sys.modules.pop(module.__name__, None)
        assert module.Event.Valves().SYNC_INTERVAL_MINUTES == 60

    def test_defaults_written_in_code_are_not_templates(self, tmp_path, env):
        folder = self.plugin(tmp_path)
        module = types.ModuleType("function_p_" + HEX)
        sys.modules[module.__name__] = module
        try:
            exec(compile(bundle_function(folder), "p.py", "exec"), module.__dict__)
        finally:
            sys.modules.pop(module.__name__, None)
        assert (
            module.plugin_config({"literal": "${N}"})["literal"] == "${N}"
        )  # only the file's values are


class TestMalformedTemplatesAreRefusedWhenBundling:
    @pytest.mark.parametrize("value", ["${}", "${1X}", "${N", "${N:60}", "${ N }", "x ${N-60}"])
    def test_config_values(self, tmp_path, value):
        write_plugin(
            tmp_path / "p",
            {
                "plugin.yaml": "function:\n  title: T\n",
                "config.yaml": f'a: "{value}"\n',
                "function.py": "class Event:\n    pass\n",
            },
        )
        with pytest.raises(OwppError, match="is not a template"):
            load_function_files(tmp_path)

    def test_an_escaped_one_is_fine(self, tmp_path):
        write_plugin(
            tmp_path / "p",
            {
                "plugin.yaml": "function:\n  title: T\n",
                "config.yaml": 'a: "cost $${N}"\n',
                "function.py": "class Event:\n    pass\n",
            },
        )
        assert load_function_files(tmp_path)[0].type == "event"

    @pytest.mark.parametrize(
        "jobs", ["${N:-soon}", "${N:--5}", "${N:-1.5}", "every ${N} minutes", "${N}${M}", "a"]
    )
    def test_the_jobs_interval(self, tmp_path, jobs):
        write_plugin(
            tmp_path / "p",
            {
                "plugin.yaml": f'function:\n  title: T\njobs:\n  sync_every_minutes: "{jobs}"\n',
                "function.py": "class Event(PluginScheduledSync):\n    async def sync(self):\n        pass\n",
            },
        )
        with pytest.raises(OwppError, match="whole number of minutes, or a template"):
            load_function_files(tmp_path)

    def test_valid_interval_templates(self, tmp_path):
        for jobs in ("${N}", "${N:-60}", "${MCPO_SYNC_MINUTES:-0}"):
            folder = (
                tmp_path
                / jobs.replace("$", "").replace("{", "").replace("}", "").replace(":", "_")
                / "p"
            )
            write_plugin(
                folder,
                {
                    "plugin.yaml": f"function:\n  title: T\njobs:\n  sync_every_minutes: {jobs}\n",
                    "function.py": "class Event(PluginScheduledSync):\n    async def sync(self):\n        pass\n",
                },
            )
            assert load_function_files(folder.parent)[0].type == "event"


class TestWhichVariablesAPluginReads:
    def test_they_are_listed_with_their_defaults(self, tmp_path):
        write_plugin(
            tmp_path / "p",
            {
                "plugin.yaml": "function:\n  title: T\njobs:\n  sync_every_minutes: ${N:-60}\n",
                "config.yaml": "a: ${FLAG:-true}\nb: http://${HOST}:${N:-8000}\nc: ${FLAG:-false}\nd: $${NOT_ONE}\n",
                "function.py": "class Event(PluginScheduledSync):\n    async def sync(self):\n        pass\n",
            },
        )
        assert env_references(tmp_path / "p") == [("N", "60"), ("FLAG", "true"), ("HOST", None)]

    def test_owpp_check_prints_them_and_does_not_fail_on_them(self, tmp_path, capsys):
        write_plugin(
            tmp_path / "p",
            {
                "plugin.yaml": "function:\n  title: T\n",
                "config.yaml": "a: ${FLAG:-true}\nb: ${HOST}\n",
                "function.py": "class Event:\n    pass\n",
            },
        )
        assert main(["check", "--dir", str(tmp_path)], env={}) == 0
        out = capsys.readouterr().out
        assert "env   FLAG (default true)" in out and "env   HOST (no default)" in out

    def test_a_plugin_with_none_prints_nothing(self, tmp_path, capsys):
        write_plugin(
            tmp_path / "p",
            {"plugin.yaml": "function:\n  title: T\n", "function.py": "class Event:\n    pass\n"},
        )
        main(["check", "--dir", str(tmp_path)], env={})
        assert "env " not in capsys.readouterr().out
