"""The sync mixin supplies its own valves, and the default interval is declared in plugin.yaml."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from conftest import write_tree
from pydantic import ValidationError

from owpp.bundle import bundle_function, load_function_files
from owpp.errors import OwppError

HEX = "0" * 32


def load(tmp_path, code, manifest="function:\n  title: T\njobs: {}\n", name="demo"):
    folder = tmp_path / name
    write_tree(folder, {"plugin.yaml": manifest, "function.py": code})
    module = types.ModuleType(f"function_{name}_{HEX}")
    sys.modules[module.__name__] = module  # pydantic resolves annotations through it
    try:
        exec(compile(bundle_function(folder), f"{name}.py", "exec"), module.__dict__)
    finally:
        sys.modules.pop(module.__name__, None)
    return module.__dict__


SIMPLE = """
class Event(PluginScheduledSync):
    def __init__(self):
        self.valves = self.Valves()

    async def sync(self):
        pass
"""

OWN_VALVES = """
from pydantic import BaseModel, Field

class Event(PluginScheduledSync):
    class Valves(BaseModel):
        URL: str = Field(default="http://x", description="Where.")
        RETRIES: int = Field(default=3, description="How many.")

    def __init__(self):
        self.valves = self.Valves()

    async def sync(self):
        pass
"""


class TestTheLibrarySuppliesTheValves:
    def test_a_class_with_no_valves_of_its_own_gets_both(self, tmp_path):
        valves = load(tmp_path, SIMPLE)["Event"].Valves()
        assert (valves.ENABLE, valves.SYNC_INTERVAL_MINUTES) == (True, 60)

    def test_they_are_added_after_the_functions_own(self, tmp_path):
        valves = load(tmp_path, OWN_VALVES)["Event"].Valves
        assert list(valves.model_fields) == ["URL", "RETRIES", "ENABLE", "SYNC_INTERVAL_MINUTES"]
        assert valves().URL == "http://x"  # the function's own are untouched

    def test_they_have_descriptions_for_the_admin_ui(self, tmp_path):
        properties = load(tmp_path, SIMPLE)["Event"].Valves.model_json_schema()["properties"]
        assert "Turn this sync on or off" in properties["ENABLE"]["description"]
        assert "0 syncs only at startup" in properties["SYNC_INTERVAL_MINUTES"]["description"]

    def test_they_are_validated_like_any_valve(self, tmp_path):
        valves = load(tmp_path, SIMPLE)["Event"].Valves
        assert valves(SYNC_INTERVAL_MINUTES="30").SYNC_INTERVAL_MINUTES == 30
        with pytest.raises(ValidationError):
            valves(SYNC_INTERVAL_MINUTES="soon")

    def test_a_valve_the_function_defines_itself_wins(self, tmp_path):
        code = OWN_VALVES.replace(
            "        RETRIES: int",
            '        SYNC_INTERVAL_MINUTES: int = Field(default=5, description="Mine.")\n        RETRIES: int',
        )
        valves = load(tmp_path, code)["Event"].Valves
        assert valves().SYNC_INTERVAL_MINUTES == 5
        assert (
            valves.model_json_schema()["properties"]["SYNC_INTERVAL_MINUTES"]["description"]
            == "Mine."
        )
        assert "ENABLE" in valves.model_fields  # the other one is still supplied

    def test_a_function_that_defines_both_gets_its_own_class_back(self, tmp_path):
        code = OWN_VALVES.replace(
            "        RETRIES: int",
            "        ENABLE: bool = Field(default=False)\n        SYNC_INTERVAL_MINUTES: int = Field(default=1)\n        RETRIES: int",
        )
        ns = load(tmp_path, code)
        assert list(ns["Event"].Valves.model_fields) == [
            "URL",
            "ENABLE",
            "SYNC_INTERVAL_MINUTES",
            "RETRIES",
        ]
        assert ns["Event"].Valves().ENABLE is False

    def test_a_subclass_of_a_sync_class_keeps_working(self, tmp_path):
        ns = load(tmp_path, SIMPLE + "\nclass Other(Event):\n    pass\n")
        assert ns["Other"].Valves().SYNC_INTERVAL_MINUTES == 60

    def test_it_works_beside_the_assets_mixin(self, tmp_path):
        folder = tmp_path / "p"
        write_tree(
            folder,
            {
                "plugin.yaml": "function:\n  title: T\njobs: {sync_every_minutes: 9}\n",
                "assets/custom.css": "a{}\n",
                "function.py": SIMPLE.replace(
                    "PluginScheduledSync", "PluginAssets, PluginScheduledSync"
                ),
            },
        )
        module = types.ModuleType("function_p_" + HEX)
        sys.modules[module.__name__] = module
        try:
            exec(compile(bundle_function(folder), "p.py", "exec"), module.__dict__)
        finally:
            sys.modules.pop(module.__name__, None)
        assert module.Event.Valves().SYNC_INTERVAL_MINUTES == 9


class TestTheIntervalIsDeclaredInTheManifest:
    @pytest.mark.parametrize("minutes", [0, 1, 15, 1440])
    def test_it_is_the_valves_default(self, tmp_path, minutes):
        manifest = f"function:\n  title: T\njobs:\n  sync_every_minutes: {minutes}\n"
        assert minutes == load(tmp_path, SIMPLE, manifest)["Event"].Valves().SYNC_INTERVAL_MINUTES

    def test_the_default_is_an_hour(self, tmp_path):
        assert (
            load(tmp_path, SIMPLE, "function:\n  title: T\ninclude: [jobs]\n")["Event"]
            .Valves()
            .SYNC_INTERVAL_MINUTES
            == 60
        )

    def test_the_key_brings_the_library_in_by_itself(self, tmp_path):
        folder = tmp_path / "p"
        write_tree(
            folder,
            {
                "plugin.yaml": "function:\n  title: T\njobs: {sync_every_minutes: 5}\n",
                "function.py": SIMPLE,
            },
        )
        (fn,) = load_function_files(tmp_path)
        c = fn.content
        for end in (
            "end plugin core library",
            "end plugin events library",
            "end plugin jobs library",
        ):
            assert c.count(end) == 1, end

    @pytest.mark.parametrize(
        ("value", "message"),
        [
            ("-1", "0 or more"),
            ("soon", "whole number of minutes"),
            ("1.5", "whole number of minutes"),
            ("true", "whole number of minutes"),
            ("[5]", "whole number of minutes"),
        ],
    )
    def test_a_bad_interval_is_refused_when_bundling(self, tmp_path, value, message):
        folder = tmp_path / "p"
        write_tree(
            folder,
            {
                "plugin.yaml": f"function:\n  title: T\njobs: {{sync_every_minutes: {value}}}\n",
                "function.py": SIMPLE,
            },
        )
        with pytest.raises(OwppError, match=message):
            load_function_files(tmp_path)

    def test_other_shapes_are_refused(self, tmp_path):
        for manifest, message in (
            ("function:\n  title: T\njobs: [5]\n", "must be a mapping"),
            ("function:\n  title: T\njobs: {every: 5}\n", "unknown key every"),
        ):
            folder = tmp_path / "x" / "p"
            write_tree(folder, {"plugin.yaml": manifest, "function.py": SIMPLE})
            with pytest.raises(OwppError, match=message):
                load_function_files(tmp_path / "x")


class TestTheSyncStillBehaves:
    def test_enable_off_from_the_valves_stops_the_jobs_and_skips_the_sync(self, tmp_path):
        ns = load(
            tmp_path,
            SIMPLE.replace("        pass", "        calls.append('sync')").replace(
                "class Event", "calls = []\n\nclass Event", 1
            ),
        )
        calls = ns["calls"]
        stopped = []
        ns["plugin_every"] = lambda *a, **k: None
        ns["plugin_stop_jobs"] = lambda: stopped.append(1)

        event = ns["Event"]()
        asyncio.run(event.event({}, "system.startup.completed", "demo"))
        assert calls == ["sync"]
        event.valves = ns["Event"].Valves(ENABLE=False)
        asyncio.run(event.event({}, "system.startup.completed", "demo"))
        assert calls == ["sync"] and stopped  # nothing more ran, and the jobs were stopped

    def test_the_interval_valve_schedules_the_repeat(self, tmp_path):
        ns = load(tmp_path, SIMPLE, "function:\n  title: T\njobs: {sync_every_minutes: 7}\n")
        scheduled = []
        ns["plugin_every"] = lambda name, seconds, factory, first_after=None: scheduled.append(
            (name, seconds)
        )
        ns["plugin_stop_jobs"] = lambda: scheduled.append("stopped")
        event = ns["Event"]()
        asyncio.run(event.event({}, "system.startup.completed", "demo"))
        assert scheduled == [("sync", 420)]
        event.valves = ns["Event"].Valves(SYNC_INTERVAL_MINUTES=0)
        asyncio.run(event.event({}, "function.valves_updated", "demo"))
        assert scheduled[-1] == "stopped"  # 0: only on startup, enable and valve changes
