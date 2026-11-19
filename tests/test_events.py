"""@on(...) event handlers: how they dispatch at runtime, and what `owpp check` refuses."""

from __future__ import annotations

import asyncio
import logging
import sys
import types

import pytest
from conftest import write_tree

from owpp.bundle import bundle_function, load_function_files
from owpp.errors import OwppError

HEX = "0" * 32


def load(tmp_path, code, include="[events]", name="demo"):
    folder = tmp_path / name
    write_tree(
        folder,
        {"plugin.yaml": f"function:\n  title: T\ninclude: {include}\n", "function.py": code},
    )
    namespace: dict = {"__name__": f"function_{name}_{HEX}"}
    exec(compile(bundle_function(folder), f"{name}.py", "exec"), namespace)
    return namespace


def fire(event_class, name, event=None, **extra):
    asyncio.run(event_class().event(event, __event_name__=name, **extra))


def about(function_id):
    return {"subject": {"id": function_id}}


class TestDispatch:
    CODE = """
calls = []

class Event(PluginEvents):
    @on("system.startup.completed")
    async def started(self):
        calls.append("started")

    @on("function.updated", "function.valves_updated")
    def changed(self):
        calls.append("changed")

    @on("function.deleted")
    def other(self):
        calls.append("deleted")
"""

    def test_each_event_goes_to_its_handler_only(self, tmp_path):
        ns = load(tmp_path, self.CODE)
        fire(ns["Event"], "system.startup.completed")
        fire(ns["Event"], "function.valves_updated")
        fire(ns["Event"], "function.updated")
        fire(ns["Event"], "chat.created")  # nobody listens
        assert ns["calls"] == ["started", "changed", "changed"]

    def test_handlers_may_be_sync_or_async(self, tmp_path):
        ns = load(tmp_path, self.CODE)
        fire(ns["Event"], "system.startup.completed")  # async
        fire(ns["Event"], "function.deleted")  # sync
        assert ns["calls"] == ["started", "deleted"]

    def test_an_unhandled_event_is_not_an_error(self, tmp_path):
        ns = load(tmp_path, self.CODE)
        fire(ns["Event"], "something.else.entirely")
        assert ns["calls"] == []

    def test_a_handler_takes_the_arguments_it_names(self, tmp_path, monkeypatch):
        main = types.ModuleType("open_webui.main")
        main.app = "the-app"
        monkeypatch.setitem(sys.modules, "open_webui", types.ModuleType("open_webui"))
        monkeypatch.setitem(sys.modules, "open_webui.main", main)
        ns = load(
            tmp_path,
            """
seen = {}

class Event(PluginEvents):
    @on("function.updated")
    def nothing(self):
        seen["nothing"] = True

    @on("function.updated")
    def some(self, event, name):
        seen["some"] = (event, name)

    @on("function.updated")
    async def all(self, event, name, id, app, request):
        seen["all"] = (event, name, id, app, request)
""",
        )
        fire(ns["Event"], "function.updated", {"k": 1}, __id__="demo", __request__=None)
        assert ns["seen"]["nothing"] is True
        assert ns["seen"]["some"] == ({"k": 1}, "function.updated")
        assert ns["seen"]["all"] == ({"k": 1}, "function.updated", "demo", "the-app", None)

    def test_the_app_comes_from_the_argument_then_the_request(self, tmp_path):
        ns = load(
            tmp_path,
            "got = []\n\nclass Event(PluginEvents):\n    @on('function.updated')\n    def h(self, app):\n        got.append(app)\n",
        )
        fire(ns["Event"], "function.updated", __app__="from-arg")
        fire(ns["Event"], "function.updated", __request__=types.SimpleNamespace(app="from-request"))
        assert ns["got"] == ["from-arg", "from-request"]

    def test_the_function_id_defaults_to_the_one_in_the_module_name(self, tmp_path):
        ns = load(
            tmp_path,
            "got = []\n\nclass Event(PluginEvents):\n    @on('function.updated')\n    def h(self, id):\n        got.append(id)\n",
        )
        fire(ns["Event"], "function.updated")
        assert ns["got"] == ["demo"]


class TestOwn:
    CODE = """
calls = []

class Event(PluginEvents):
    @on("function.updated", "system.startup.completed", own=True)
    def mine(self):
        calls.append("own")

    @on("function.updated")
    def anyones(self):
        calls.append("any")
"""

    def test_own_ignores_events_about_other_functions(self, tmp_path):
        ns = load(tmp_path, self.CODE)
        fire(ns["Event"], "function.updated", about("someone_else"))
        assert ns["calls"] == ["any"]

    def test_own_still_runs_for_this_function_and_for_events_with_no_subject(self, tmp_path):
        ns = load(tmp_path, self.CODE)
        fire(ns["Event"], "function.updated", about("demo"))
        fire(ns["Event"], "system.startup.completed")  # startup has no subject
        fire(ns["Event"], "function.updated")
        assert ns["calls"] == ["own", "any", "own", "own", "any"]

    def test_an_explicit_id_wins_over_the_module_name(self, tmp_path):
        ns = load(tmp_path, self.CODE)
        fire(ns["Event"], "function.updated", about("renamed"), __id__="renamed")
        assert ns["calls"] == ["own", "any"]


class TestHandlersAndClasses:
    def test_several_handlers_for_one_event_all_run_in_order(self, tmp_path):
        ns = load(
            tmp_path,
            "calls = []\n\nclass Event(PluginEvents):\n"
            "    @on('function.updated')\n    def a(self):\n        calls.append('a')\n"
            "    @on('function.updated')\n    def b(self):\n        calls.append('b')\n",
        )
        fire(ns["Event"], "function.updated")
        assert ns["calls"] == ["a", "b"]

    def test_stacked_decorators_register_each(self, tmp_path):
        ns = load(
            tmp_path,
            "calls = []\n\nclass Event(PluginEvents):\n"
            "    @on('function.updated')\n    @on('function.deleted', own=True)\n    def h(self, name):\n        calls.append(name)\n",
        )
        fire(ns["Event"], "function.updated")
        fire(ns["Event"], "function.deleted", about("other"))  # own: skipped
        fire(ns["Event"], "function.deleted", about("demo"))
        assert ns["calls"] == ["function.updated", "function.deleted"]

    def test_a_subclass_inherits_and_adds_handlers(self, tmp_path):
        ns = load(
            tmp_path,
            "calls = []\n\nclass Base(PluginEvents):\n    @on('function.updated')\n    def a(self):\n        calls.append('base')\n"
            "class Event(Base):\n    @on('function.updated')\n    def b(self):\n        calls.append('sub')\n",
        )
        fire(ns["Event"], "function.updated")
        assert ns["calls"] == ["base", "sub"]

    def test_on_needs_event_names_as_strings(self, tmp_path):
        ns = load(tmp_path, "class Event(PluginEvents):\n    pass\n")
        for args in ((), (1,), ("ok", None)):
            with pytest.raises(TypeError):
                ns["on"](*args)


class TestOneHandlerFailing:
    CODE = """
calls = []

class Parent:
    async def event(self, event=None, **kwargs):
        calls.append("parent")

class Event(PluginEvents, Parent):
    @on("function.updated")
    def broken(self):
        raise RuntimeError("boom")

    @on("function.updated")
    def fine(self):
        calls.append("fine")
"""

    def test_it_does_not_stop_the_other_handlers_or_the_next_mixin(self, tmp_path, caplog):
        ns = load(tmp_path, self.CODE)
        with caplog.at_level(logging.ERROR):
            fire(ns["Event"], "function.updated")
        assert ns["calls"] == ["fine", "parent"]
        assert any(
            "handler broken for function.updated failed" in r.getMessage() for r in caplog.records
        )


class TestChaining:
    def test_it_passes_the_event_on_to_the_next_mixin(self, tmp_path):
        ns = load(
            tmp_path,
            """
seen = []

class Parent:
    async def event(self, event=None, __event_name__=None, __id__=None, __app__=None, **kwargs):
        seen.append((event, __event_name__, __id__, __app__, sorted(kwargs)))

class Event(PluginEvents, Parent):
    pass
""",
        )
        fire(
            ns["Event"], "function.updated", {"x": 1}, __id__="d", __app__="app", __request__="req"
        )
        assert ns["seen"] == [({"x": 1}, "function.updated", "d", "app", ["__request__"])]

    def test_it_works_with_nothing_after_it(self, tmp_path):
        ns = load(tmp_path, "class Event(PluginEvents):\n    pass\n")
        fire(ns["Event"], "function.updated")  # no error

    def test_a_subclass_that_overrides_event_calls_super(self, tmp_path):
        ns = load(
            tmp_path,
            """
calls = []

class Event(PluginEvents):
    @on("function.updated")
    def h(self):
        calls.append("handler")

    async def event(self, event=None, __event_name__=None, **kwargs):
        calls.append("mine")
        await super().event(event, __event_name__=__event_name__, **kwargs)
""",
        )
        fire(ns["Event"], "function.updated")
        assert ns["calls"] == ["mine", "handler"]


class TestWhatOwppCheckRefuses:
    def bundle(self, tmp_path, code, include="[events]"):
        folder = tmp_path / "p"
        write_tree(
            folder,
            {"plugin.yaml": f"function:\n  title: T\ninclude: {include}\n", "function.py": code},
        )
        return load_function_files(tmp_path)

    @pytest.mark.parametrize(
        ("name", "suggestion"),
        [
            ("function.valve_updated", "function.valves_updated"),
            ("system.startup.complete", "system.startup.completed"),
            ("function.enabled_started", "function.enable_started"),
            ("config.banner.updated", "config.banners.updated"),
        ],
    )
    def test_a_typo_of_a_known_event_is_refused_with_a_suggestion(self, tmp_path, name, suggestion):
        code = f"class Event(PluginEvents):\n    @on({name!r})\n    def h(self):\n        pass\n"
        with pytest.raises(OwppError, match=f"did you mean '{suggestion}'"):
            self.bundle(tmp_path, code)

    @pytest.mark.parametrize(
        "name",
        ["Function.updated", "startup", "function updated", "function.", ".updated", "function..x"],
    )
    def test_a_malformed_name_is_refused(self, tmp_path, name):
        code = f"class Event(PluginEvents):\n    @on({name!r})\n    def h(self):\n        pass\n"
        with pytest.raises(OwppError, match="is not an event name"):
            self.bundle(tmp_path, code)

    @pytest.mark.parametrize(
        "name", ["function.created", "chat.deleted", "model.created", "config.models.updated"]
    )
    def test_a_plausible_event_we_do_not_list_is_accepted(self, tmp_path, name):
        code = f"class Event(PluginEvents):\n    @on({name!r})\n    def h(self):\n        pass\n"
        assert self.bundle(tmp_path, code)[0].type == "event"

    def test_a_module_level_string_constant_is_resolved_and_checked(self, tmp_path):
        ok = "UPDATED = 'function.updated'\n\nclass Event(PluginEvents):\n    @on(UPDATED)\n    def h(self):\n        pass\n"
        assert self.bundle(tmp_path, ok)[0].type == "event"
        typo = "UPDATED = 'function.updatd'\n\nclass Event(PluginEvents):\n    @on(UPDATED)\n    def h(self):\n        pass\n"
        with pytest.raises(OwppError, match="did you mean 'function.updated'"):
            self.bundle(tmp_path / "x", typo)

    def test_a_name_that_cannot_be_read_is_refused(self, tmp_path):
        code = "class Event(PluginEvents):\n    @on(name_from_somewhere())\n    def h(self):\n        pass\n"
        with pytest.raises(OwppError, match="written as strings or module-level string constants"):
            self.bundle(tmp_path, code)

    def test_on_with_no_name_is_refused(self, tmp_path):
        with pytest.raises(OwppError, match="needs an event name"):
            self.bundle(
                tmp_path, "class Event(PluginEvents):\n    @on()\n    def h(self):\n        pass\n"
            )

    def test_handlers_on_a_class_that_does_not_inherit_the_mixin_are_refused(self, tmp_path):
        code = "class Event:\n    @on('function.updated')\n    def h(self):\n        pass\n"
        with pytest.raises(
            OwppError, match=r"does not inherit PluginEvents.*class Event\(PluginEvents\)"
        ):
            self.bundle(tmp_path, code)

    def test_the_mixin_may_be_one_of_several_bases(self, tmp_path):
        code = "class Event(PluginEvents, object):\n    @on('function.updated')\n    def h(self):\n        pass\n"
        assert self.bundle(tmp_path, code)[0].type == "event"

    def test_the_library_brings_core_in_for_function_id_and_app(self, tmp_path):
        (fn,) = self.bundle(tmp_path, "class Event(PluginEvents):\n    pass\n")
        c = fn.content
        assert c.count("end plugin core library") == 1 and c.count("end plugin events library") == 1
        assert c.index("end plugin core library") < c.index("class PluginEvents:")


class TestTheLibraryMixinsAreEventsClasses:
    """PluginScheduledSync and PluginAssets are built on @on, so they bring the events library in."""

    def test_jobs_brings_events_and_core_in_ahead_of_itself(self, tmp_path):
        folder = tmp_path / "p"
        write_tree(
            folder,
            {
                "plugin.yaml": "function:\n  title: T\ninclude: [jobs]\n",
                "function.py": "class Event(PluginScheduledSync):\n    pass\n",
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
        assert (
            c.index("end plugin core library")
            < c.index("end plugin events library")
            < c.index("class PluginScheduledSync(PluginEvents):")
        )

    def test_assets_brings_events_in_too(self, tmp_path):
        folder = tmp_path / "p"
        write_tree(folder, {"plugin.yaml": "function:\n  title: T\n", "assets/custom.css": "a{}\n"})
        (fn,) = load_function_files(tmp_path)
        assert fn.content.count("end plugin events library") == 1
        assert fn.content.index("end plugin events library") < fn.content.index(
            "class PluginAssets(PluginEvents):"
        )

    @pytest.mark.parametrize(
        ("base", "files"),
        [
            ("PluginScheduledSync", {"plugin.yaml": "function:\n  title: T\ninclude: [jobs]\n"}),
            (
                "PluginAssets",
                {"plugin.yaml": "function:\n  title: T\n", "assets/custom.css": "a{}\n"},
            ),
        ],
    )
    def test_on_handlers_are_accepted_on_a_class_using_either(self, tmp_path, base, files):
        code = f"class Event({base}):\n    @on('chat.created')\n    def h(self):\n        pass\n"
        write_tree(tmp_path / "p", {**files, "function.py": code})
        assert load_function_files(tmp_path)[0].type == "event"

    def test_the_mixins_compose_and_each_handler_runs_once(self, tmp_path):
        folder = tmp_path / "p"
        write_tree(
            folder,
            {
                "plugin.yaml": "function:\n  title: T\ninclude: [jobs]\n",
                "assets/custom.css": "a{}\n",
                "function.py": (
                    "calls = []\n\n"
                    "class Event(PluginAssets, PluginScheduledSync):\n"
                    "    def __init__(self):\n"
                    "        super().__init__()\n"
                    "        self.valves = type('V', (), {'ENABLE': True, 'SYNC_INTERVAL_MINUTES': 0})()\n"
                    "    async def sync(self):\n        calls.append('sync')\n"
                    "    @on('chat.created')\n    def mine(self):\n        calls.append('mine')\n"
                ),
            },
        )
        namespace: dict = {"__name__": "function_p_" + "0" * 32}
        exec(compile(bundle_function(folder), "p.py", "exec"), namespace)
        namespace["plugin_every"] = lambda *a, **k: None
        namespace["plugin_stop_jobs"] = lambda: None
        asyncio.run(namespace["Event"]().event({}, "chat.created", "p"))
        asyncio.run(namespace["Event"]().event({}, "system.startup.completed", "p"))
        assert namespace["calls"] == ["mine", "sync"]


class TestTheMixinMakesTheValves:
    VALVES = "from pydantic import BaseModel\n\nclass Valves(BaseModel):\n    N: int = 3\n\n"

    def make(self, tmp_path, body, name="demo"):
        code = f"from pydantic import BaseModel\n\nclass Event(PluginEvents):\n    class Valves(BaseModel):\n        N: int = 3\n{body}"
        return load(tmp_path, code, name=name)["Event"]

    def test_a_class_with_valves_gets_self_valves_without_an_init(self, tmp_path):
        event = self.make(tmp_path, "")()
        assert event.valves.N == 3

    def test_a_class_with_no_valves_has_none_and_that_is_fine(self, tmp_path):
        ns = load(tmp_path, "class Event(PluginEvents):\n    pass\n")
        assert not hasattr(ns["Event"](), "valves")

    def test_an_init_of_its_own_still_works_and_may_call_super(self, tmp_path):
        own = self.make(tmp_path, "\n    def __init__(self):\n        self.valves = 'mine'\n")()
        assert own.valves == "mine"
        chained = self.make(
            tmp_path / "x",
            "\n    def __init__(self):\n        super().__init__()\n        self.extra = self.valves.N + 1\n",
        )()
        assert (chained.valves.N, chained.extra) == (3, 4)

    def test_the_stored_valves_replace_it_the_way_open_webui_does(self, tmp_path):
        event = self.make(tmp_path, "")()
        event.valves = type(event).Valves(N=9)
        assert event.valves.N == 9
