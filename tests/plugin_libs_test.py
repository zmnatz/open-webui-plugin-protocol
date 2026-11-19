"""Tests for the built-in libraries in src/owpp/runtime/lib/ (routes, jobs) with
Open-WebUI stubbed out. Run by pytest."""

import asyncio
import json
import pathlib
import sys
import types
import unittest

LIB = pathlib.Path(__file__).resolve().parent.parent / "src" / "owpp" / "runtime" / "lib"
HEX = "0123456789abcdef0123456789abcdef"


def load(name, module_name):
    text = (LIB / f"{name}.py").read_text()
    text = text.replace("__JOBS_DATA__", json.dumps(json.dumps({"sync_every_minutes": 60})))
    if name in ("plugin_routes", "plugin_jobs", "plugin_static"):
        text = (
            (LIB / "plugin_core.py").read_text() + "\n" + text
        )  # the bundler adds core ahead of these
    if name == "plugin_jobs":  # and the events library, which the sync mixin is built on
        text = (LIB / "plugin_events.py").read_text() + "\n" + text
    module = types.ModuleType(module_name)
    sys.modules[module_name] = module
    exec(compile(text, str(LIB / f"{name}.py"), "exec"), module.__dict__)
    return module


class Route:
    def __init__(self, path, endpoint=None, name=None):
        self.path, self.endpoint, self.name = path, endpoint, name


def endpoint(module_name):
    fn = lambda: None  # noqa: E731
    fn.__module__ = module_name
    return fn


class App:
    def __init__(self, routes):
        self.router = types.SimpleNamespace(routes=routes)

    def include_router(self, router, **kwargs):
        self.included = kwargs
        self.router.routes.extend(router.routes)


class RoutesLib(unittest.TestCase):
    def setUp(self):
        self.lib = load("plugin_routes", f"function_demo_{HEX}")

    def test_replaces_only_this_functions_routes_under_the_prefix_and_goes_before_the_spa(self):
        mine_old = Route(
            "/demo/api/x", endpoint(f"function_demo_{'f' * 32}")
        )  # earlier load, other hex
        theirs = Route("/demo/api/y", endpoint("function_other_" + HEX))
        owui = Route("/demo/z", endpoint("open_webui.routers.x"))
        spa = Route("/", None, name="spa-static-files")
        app = App([mine_old, theirs, owui, spa])
        fresh = types.SimpleNamespace(
            routes=[
                Route("/demo/api/x", endpoint(f"function_demo_{HEX}")),
                Route("/demo", endpoint(f"function_demo_{HEX}")),
            ]
        )
        added = self.lib.plugin_mount(app, fresh, "/demo")
        self.assertEqual(added, 2)
        routes = app.router.routes
        self.assertNotIn(mine_old, routes)
        self.assertIn(theirs, routes)
        self.assertIn(owui, routes)
        self.assertIs(routes[-1], spa)  # ours sit just before it
        self.assertEqual([r.path for r in routes[-3:-1]], ["/demo/api/x", "/demo"])

    def test_refuses_the_root_prefix(self):
        with self.assertRaises(ValueError):
            self.lib.plugin_mount(App([]), types.SimpleNamespace(routes=[]), "/")

    def test_require_active_404s_when_disabled_or_gone(self):
        class HTTPException(Exception):
            def __init__(self, status_code):
                self.status_code = status_code

        state = {"fn": types.SimpleNamespace(is_active=True)}

        class Functions:
            @staticmethod
            async def get_function_by_id(i):
                return state["fn"]

        saved = {
            k: sys.modules.get(k)
            for k in ("fastapi", "open_webui", "open_webui.models", "open_webui.models.functions")
        }
        for name, attrs in {
            "fastapi": {"HTTPException": HTTPException},
            "open_webui": {},
            "open_webui.models": {},
            "open_webui.models.functions": {"Functions": Functions},
        }.items():
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            sys.modules[name] = m
        try:
            asyncio.run(self.lib.plugin_require_active())
            state["fn"] = types.SimpleNamespace(is_active=False)
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(self.lib.plugin_require_active())
            self.assertEqual(caught.exception.status_code, 404)
            state["fn"] = None
            with self.assertRaises(HTTPException):
                asyncio.run(self.lib.plugin_require_active("demo"))
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v


class JobsLib(unittest.TestCase):
    def setUp(self):
        self.name = f"function_jobs_{HEX}"
        self.lib = load("plugin_jobs", self.name)
        self.active = {"on": True}
        active = self.active

        class Functions:
            @staticmethod
            async def get_function_by_id(i):
                return types.SimpleNamespace(is_active=active["on"])

        self.saved = {
            k: sys.modules.get(k)
            for k in ("open_webui", "open_webui.models", "open_webui.models.functions")
        }
        for name, attrs in {
            "open_webui": {},
            "open_webui.models": {},
            "open_webui.models.functions": {"Functions": Functions},
        }.items():
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            sys.modules[name] = m

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        for k in [k for k in sys.modules if k.startswith("_plugin_jobs_")]:
            del sys.modules[k]

    def test_claim_is_granted_once_per_ttl_and_can_be_undone(self):
        async def run():
            self.assertTrue(await self.lib.plugin_claim("k", 60))
            self.assertFalse(await self.lib.plugin_claim("k", 60))
            await self.lib.plugin_unclaim("k")
            self.assertTrue(await self.lib.plugin_claim("k", 60))

        asyncio.run(run())

    def test_spawn_runs_one_job_at_a_time_and_reports_the_skipped_one(self):
        log = []

        async def run():
            gate = asyncio.Event()

            async def slow():
                log.append("slow start")
                await gate.wait()
                log.append("slow end")

            async def other():
                log.append("other")

            first = self.lib.plugin_spawn("a", slow)
            await asyncio.sleep(0.01)
            second = self.lib.plugin_spawn("b", other, on_skip=lambda: log.append("skipped"))
            await second
            gate.set()
            await first

        asyncio.run(run())
        self.assertEqual(log, ["slow start", "skipped", "slow end"])

    def test_every_repeats_replaces_an_earlier_loop_and_stops_when_disabled(self):
        runs = []

        async def run():
            async def job():
                runs.append(1)

            # claim ttl is 90% of the period, so use a period the sleep outlasts
            self.lib.plugin_every("tick", 1.2, job, first_after=0.01)
            await asyncio.sleep(0.05)
            self.assertEqual(len(runs), 1)
            replaced = self.lib.plugin_every("tick", 1.2, job, first_after=10)
            await asyncio.sleep(0.05)
            self.assertEqual(len(self.lib._jobs_state().loops), 1)  # not doubled
            replaced.cancel()
            self.lib._jobs_state().claims.clear()
            self.active["on"] = False
            task = self.lib.plugin_every("tick", 0.05, job, first_after=0.01)
            await asyncio.wait_for(task, 1)  # ends by itself: the function is disabled

        asyncio.run(run())
        self.assertEqual(len(runs), 1)

    def test_a_failing_job_does_not_stop_the_loop(self):
        runs = []

        async def run():
            async def job():
                runs.append(1)
                raise RuntimeError("boom")

            async def always(key, ttl):  # the real claim lasts at least a second
                return True

            self.lib.plugin_claim = always
            self.lib.plugin_every("tick", 0.05, job, first_after=0.01)
            await asyncio.sleep(0.25)
            self.lib.plugin_stop_jobs()

        asyncio.run(run())
        self.assertGreaterEqual(len(runs), 2)

    def test_sync_runs_on_startup_and_on_this_functions_enable_and_valves_only(self):
        lib, calls = self.lib, []
        lib.plugin_every = lambda *args, **kwargs: None
        lib.plugin_stop_jobs = lambda: None

        class Ev(lib.PluginScheduledSync):
            def __init__(self):
                self.valves = types.SimpleNamespace(ENABLE=True, SYNC_INTERVAL_MINUTES=0)

            async def sync(self):
                calls.append(1)

        async def fire(name, event):
            await Ev().event(event, name, "me")

        for name, event, runs in (
            ("system.startup.completed", {}, True),
            ("function.enable_started", {"subject": {"id": "me"}}, True),
            ("function.valves_updated", {}, True),  # no subject: all functions
            ("function.valves_updated", {"subject": {"id": "other"}}, False),
            ("function.enable_started", {"subject": {"id": "other"}}, False),
            ("chat.created", {}, False),
        ):
            before = len(calls)
            asyncio.run(fire(name, event))
            self.assertEqual(len(calls) - before, 1 if runs else 0, (name, event))

    def test_the_sync_mixin_is_an_events_class_so_on_handlers_work_beside_it(self):
        lib, seen = self.lib, []
        lib.plugin_every = lambda *args, **kwargs: None
        lib.plugin_stop_jobs = lambda: None

        class Ev(lib.PluginScheduledSync):
            def __init__(self):
                self.valves = types.SimpleNamespace(ENABLE=True, SYNC_INTERVAL_MINUTES=0)

            async def sync(self):
                seen.append("sync")

            @lib.on("chat.created")
            def mine(self):
                seen.append("mine")

        self.assertTrue(issubclass(Ev, lib.PluginEvents))
        asyncio.run(Ev().event({}, "chat.created", "me"))
        asyncio.run(Ev().event({}, "system.startup.completed", "me"))
        self.assertEqual(seen, ["mine", "sync"])

    def test_scheduled_sync_mixin_syncs_on_lifecycle_events_and_stops_when_disabled(self):
        calls, spawned = [], []
        lib = self.lib
        lib.plugin_every = lambda name, seconds, factory, first_after=None: spawned.append(
            (name, seconds)
        )
        lib.plugin_stop_jobs = lambda: spawned.append("stopped")

        class Ev(lib.PluginScheduledSync):
            def __init__(self, enable=True, minutes=60):
                self.valves = types.SimpleNamespace(ENABLE=enable, SYNC_INTERVAL_MINUTES=minutes)

            async def sync(self):
                calls.append(1)

        async def run():
            await Ev().event({}, "system.startup.completed", "me")
            await Ev().event({}, "chat.created", "me")  # not a sync event
            await Ev(minutes=0).event({}, "function.enable_started", "me")
            await Ev(enable=False).event({}, "system.startup.completed", "me")

        asyncio.run(run())
        self.assertEqual(len(calls), 2)
        self.assertEqual(spawned, [("sync", 3600), "stopped", "stopped"])

    def test_stored_valves_are_read_fresh_and_unknown_keys_ignored(self):
        stored = {"A": 2, "junk": 1}

        class Functions:
            @staticmethod
            async def get_function_valves_by_id(i):
                return stored

        sys.modules["open_webui.models.functions"].Functions = Functions

        class Valves:
            def __init__(self, A=1, **ignored):
                self.A = A

        self.assertEqual(asyncio.run(self.lib.plugin_stored_valves(Valves)).A, 2)
        stored.clear()
        self.assertEqual(asyncio.run(self.lib.plugin_stored_valves(Valves)).A, 1)


class ChatDataLib(unittest.TestCase):
    def setUp(self):
        self.lib = load("plugin_chat_data", f"function_chat_{HEX}")

    def tearDown(self):
        sys.modules.pop("_plugin_chat_data", None)

    def test_a_temporary_chat_keeps_values_in_memory_per_key(self):
        async def run():
            self.assertIsNone(await self.lib.plugin_chat_read("local:1", "a"))
            await self.lib.plugin_chat_write("local:1", {"n": 1}, "a")
            await self.lib.plugin_chat_write("local:1", {"n": 2}, "b")
            self.assertEqual(await self.lib.plugin_chat_read("local:1", "a"), {"n": 1})
            self.assertEqual(await self.lib.plugin_chat_read("local:1", "b"), {"n": 2})
            self.assertIsNone(await self.lib.plugin_chat_read("local:2", "a"))

        asyncio.run(run())

    def test_two_copies_of_the_library_share_one_store(self):
        other = load("plugin_chat_data", f"tool_chat_{HEX}")  # e.g. the tool's bundle
        asyncio.run(self.lib.plugin_chat_write("local:1", [1], "k"))
        self.assertEqual(asyncio.run(other.plugin_chat_read("local:1", "k")), [1])

    def test_update_is_serialised_and_none_keeps_the_value(self):
        async def run():
            def bump(current, is_new):
                return {"n": (current or {"n": 0})["n"] + 1}

            async def slow(current, is_new):
                await asyncio.sleep(0.01)
                return bump(current, is_new)

            await asyncio.gather(
                *[self.lib.plugin_chat_update("local:1", slow, "k") for _ in range(5)]
            )
            self.assertEqual(await self.lib.plugin_chat_read("local:1", "k"), {"n": 5})
            self.assertEqual(
                await self.lib.plugin_chat_update("local:1", lambda c, n: None, "k"), {"n": 5}
            )
            self.assertEqual(
                await self.lib.plugin_chat_update(
                    "local:9", lambda c, n: None, "k", default={"d": 1}
                ),
                {"d": 1},
            )
            seen = []
            await self.lib.plugin_chat_update(
                "local:9", lambda c, n: seen.append((c, n)), "k", default={"d": 1}
            )
            self.assertEqual(seen, [({"d": 1}, True)])

        asyncio.run(run())

    def test_keys_must_be_plain_identifiers(self):
        for bad in ("", "a-b", "a'b", "a.b", "1a", None, "x" * 65):
            with self.assertRaises(ValueError, msg=repr(bad)):
                asyncio.run(self.lib.plugin_chat_read("local:1", bad))
        asyncio.run(self.lib.plugin_chat_read("local:1", "ok_1"))

    def _stub_db(self, dialect, rows, rowcount=1):
        executed = []

        class Result:
            def __init__(self, row=None):
                self.row, self.rowcount = row, rowcount

            def one_or_none(self):
                return self.row

        class Session:
            def get_bind(self):
                return types.SimpleNamespace(dialect=types.SimpleNamespace(name=dialect))

            async def execute(self, statement, params=None):
                executed.append((str(statement), params))
                return Result(rows.pop(0) if rows else None)

            async def commit(self):
                executed.append(("commit", None))

        class Ctx:
            async def __aenter__(self):
                return Session()

            async def __aexit__(self, *a):
                return False

        class Select:
            def filter_by(self, **kw):
                return "SELECT"

        chat = types.SimpleNamespace(__tablename__="chat", meta="meta_col")
        mods = {
            "open_webui": {},
            "open_webui.internal": {},
            "open_webui.internal.db": {"get_async_db_context": lambda: Ctx()},
            "open_webui.models": {},
            "open_webui.models.chats": {"Chat": chat},
            "sqlalchemy": {
                "select": lambda *a: Select(),
                "text": lambda s: s,
                "update": lambda *a: Select(),
            },
        }
        saved = {k: sys.modules.get(k) for k in mods}
        for name, attrs in mods.items():
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            sys.modules[name] = m

        def restore():
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

        self.addCleanup(restore)
        return executed

    def test_read_returns_the_key_from_meta_and_raises_when_the_chat_is_missing(self):
        self._stub_db("sqlite", [({"k": {"v": 1}, "other": 2},), ('{"k": 3}',), None])
        self.assertEqual(asyncio.run(self.lib.plugin_chat_read("c1", "k")), {"v": 1})
        self.assertEqual(
            asyncio.run(self.lib.plugin_chat_read("c1", "k")), 3
        )  # meta stored as a string
        with self.assertRaises(self.lib.ChatNotSaved):
            asyncio.run(self.lib.plugin_chat_read("c1", "k"))

    def test_write_sets_only_its_key_per_dialect_and_reports_a_missing_chat(self):
        ran = self._stub_db("sqlite", [])
        asyncio.run(self.lib.plugin_chat_write("c1", {"v": 1}, "k"))
        sql, params = ran[0]
        self.assertIn("json_set(COALESCE(meta, '{}'), '$.k', json(:v))", sql)
        self.assertEqual(params, {"v": '{"v": 1}', "id": "c1"})
        self.assertNotIn("updated_at", sql)
        ran = self._stub_db("postgresql", [])
        asyncio.run(self.lib.plugin_chat_write("c1", {"v": 1}, "k"))
        self.assertIn("jsonb_build_object('k'", ran[0][0])
        self._stub_db("sqlite", [], rowcount=0)
        with self.assertRaises(self.lib.ChatNotSaved):
            asyncio.run(self.lib.plugin_chat_write("c1", {"v": 1}, "k"))


class StaticLib(unittest.TestCase):
    """The static library with fastapi stubbed (it is only importable in Open-WebUI)."""

    FILES = {
        "app.js": {"content": "console.log(1)\n"},
        "img/b.bin": {"content": "/wA=", "encoding": "base64"},
    }
    ACCESS = "user"

    def setUp(self):
        import json

        class Request:
            def __init__(self, headers=None):
                self.headers = headers or {}

        class Response:
            def __init__(self, content=b"", status_code=200, media_type=None, headers=None):
                self.content, self.status_code, self.media_type, self.headers = (
                    content,
                    status_code,
                    media_type,
                    headers,
                )

        class APIRouter:
            def __init__(self):
                self.routes = []

            def add_api_route(
                self, path, endpoint, methods=None, include_in_schema=True, dependencies=()
            ):
                self.routes.append(
                    types.SimpleNamespace(
                        path=path, endpoint=endpoint, dependencies=list(dependencies)
                    )
                )

        self.Request = Request
        saved = {
            k: sys.modules.get(k)
            for k in ("fastapi", "fastapi.responses", "open_webui", "open_webui.main")
        }
        fastapi = types.ModuleType("fastapi")
        fastapi.APIRouter, fastapi.Request = APIRouter, Request
        fastapi.Response = Response
        fastapi.Depends = lambda dep: ("Depends", dep)
        fastapi.HTTPException = Exception
        responses = types.ModuleType("fastapi.responses")
        responses.Response = Response
        self.app = types.SimpleNamespace(
            router=types.SimpleNamespace(routes=[]),
            include_router=lambda r, **kw: (
                setattr(self, "included", kw),
                self.app.router.routes.extend(r.routes),
            ),
        )
        main = types.ModuleType("open_webui.main")
        main.app = self.app
        for name, m in {
            "fastapi": fastapi,
            "fastapi.responses": responses,
            "open_webui": types.ModuleType("open_webui"),
            "open_webui.main": main,
        }.items():
            sys.modules[name] = m

        def restore():
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

        self.addCleanup(restore)
        data = {"prefix": "/demo", "access": self.ACCESS, "files": self.FILES}
        routes_src = (LIB / "plugin_routes.py").read_text()
        static_src = (
            (LIB / "plugin_static.py")
            .read_text()
            .replace("__STATIC_DATA__", json.dumps(json.dumps(data)))
        )
        self.module = types.ModuleType(f"function_demo_{HEX}")
        sys.modules[self.module.__name__] = self.module
        exec(
            compile((LIB / "plugin_core.py").read_text(), "plugin_core.py", "exec"),
            self.module.__dict__,
        )
        exec(compile(routes_src, "plugin_routes.py", "exec"), self.module.__dict__)
        exec(
            compile(static_src, "plugin_static.py", "exec"), self.module.__dict__
        )  # mounts on load

    def test_index_html_is_served_at_the_prefix_root_and_the_bare_prefix_redirects(self):
        added = []
        router = types.SimpleNamespace(
            add_api_route=lambda path, endpoint, **kw: added.append((path, endpoint))
        )
        self.module._STATIC["files"]["index.html"] = {"content": "<p>home</p>\n"}
        n = self.module.plugin_static_serve(router)
        paths = [p for p, _ in added]
        self.assertEqual(n, len(added))
        self.assertIn("/demo/index.html", paths)
        self.assertIn("/demo/", paths)
        self.assertIn("/demo", paths)
        redirect = dict(added)["/demo"]
        response = asyncio.run(redirect())
        self.assertEqual((response.status_code, response.headers["Location"]), (307, "/demo/"))

    def test_every_file_gets_a_route(self):
        paths = sorted(r.path for r in self.app.router.routes)
        self.assertEqual(paths, ["/demo/app.js", "/demo/img/b.bin"])

    def test_the_mount_carries_the_guard_of_the_declared_access(self):
        (dependency,) = self.included["dependencies"]
        self.assertEqual(dependency[1].__name__, "guard")  # a signed-in user: the default

    def test_serves_content_with_a_type_and_etag_and_answers_304(self):
        route = next(r for r in self.app.router.routes if r.path == "/demo/app.js")
        res = asyncio.run(route.endpoint(self.Request()))
        self.assertEqual((res.status_code, res.content), (200, b"console.log(1)\n"))
        self.assertIn("javascript", res.media_type)
        self.assertIn("utf-8", res.media_type)
        self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")
        again = asyncio.run(route.endpoint(self.Request({"if-none-match": res.headers["ETag"]})))
        self.assertEqual(again.status_code, 304)
        binary = asyncio.run(
            next(r for r in self.app.router.routes if r.path.endswith("b.bin")).endpoint(
                self.Request()
            )
        )
        self.assertEqual(binary.media_type, "application/octet-stream")

    def test_mounting_again_replaces_the_routes_and_leaves_other_mounts_alone(self):
        other = types.SimpleNamespace(
            path="/demo/view/1", endpoint=self.module.plugin_static_files, name=None
        )  # the function's own route
        self.app.router.routes.append(other)
        self.module.plugin_static_ensure()
        paths = [r.path for r in self.app.router.routes]
        self.assertEqual(
            sorted(paths), ["/demo/app.js", "/demo/img/b.bin", "/demo/view/1"]
        )  # not doubled, other kept


class StaticLibAdminOnly(StaticLib):
    ACCESS = "admin"

    def test_the_mount_carries_the_guard_of_the_declared_access(self):
        (dependency,) = self.included["dependencies"]
        self.assertEqual(dependency[1].__name__, "guard")  # still a signed-in-admin guard


class StaticLibPublic(StaticLib):
    ACCESS = "public"

    def test_the_mount_carries_the_guard_of_the_declared_access(self):
        (dependency,) = self.included["dependencies"]
        self.assertEqual(dependency[1].__name__, "open_guard")  # only that the function is enabled


class TemplatesLib(unittest.TestCase):
    FILES = {
        "page.html": {"content": "<p>__TOKEN__</p>\n"},
        "img/b.bin": {"content": "/wA=", "encoding": "base64"},
    }

    def setUp(self):
        import json

        src = (LIB / "plugin_templates.py").read_text()
        src = src.replace("__TEMPLATES_DATA__", json.dumps(json.dumps(self.FILES)))
        self.module = types.ModuleType("templates_demo")
        exec(compile(src, "plugin_templates.py", "exec"), self.module.__dict__)

    def test_text_for_a_template_and_bytes_for_a_binary_one(self):
        self.assertEqual(self.module.plugin_template_text("page.html"), "<p>__TOKEN__</p>\n")
        self.assertEqual(self.module.plugin_template_bytes("img/b.bin"), b"\xff\x00")
        self.assertEqual(self.module.plugin_template_files(), ["img/b.bin", "page.html"])

    def test_a_missing_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            self.module.plugin_template_text("nope.html")

    def test_nothing_is_served(self):
        self.assertFalse(hasattr(self.module, "plugin_mount"))
        self.assertFalse(hasattr(self.module, "plugin_static_serve"))


class PluginConfigTests(unittest.TestCase):
    def load(self, data):
        # the bundler adds core (plugin_env) ahead of the config library
        src = (LIB / "plugin_core.py").read_text() + "\n" + (LIB / "plugin_config.py").read_text()
        src = src.replace("__CONFIG_DATA__", json.dumps(json.dumps(data)))
        module = types.ModuleType("config_demo")
        exec(compile(src, "plugin_config.py", "exec"), module.__dict__)
        return module

    def test_mappings_merge_and_everything_else_is_replaced(self):
        module = self.load({"a": {"x": 1}, "list": [3], "n": 2})
        merged = module.plugin_config({"a": {"y": 2}, "list": [1, 2], "n": 1, "kept": True})
        self.assertEqual(merged, {"a": {"y": 2, "x": 1}, "list": [3], "n": 2, "kept": True})

    def test_a_scalar_over_a_mapping_and_the_reverse_replace(self):
        module = self.load({"a": 5, "b": {"x": 1}})
        self.assertEqual(module.plugin_config({"a": {"y": 2}, "b": 7}), {"a": 5, "b": {"x": 1}})

    def test_neither_the_defaults_nor_the_embedded_data_are_shared_with_callers(self):
        module = self.load({"a": {"x": [1]}})
        defaults = {"d": {"k": 1}}
        first = module.plugin_config(defaults)
        first["a"]["x"].append(2)
        first["d"]["k"] = 9
        self.assertEqual(defaults, {"d": {"k": 1}})
        self.assertEqual(module.plugin_config(defaults), {"a": {"x": [1]}, "d": {"k": 1}})

    def test_no_defaults_is_just_the_file(self):
        self.assertEqual(self.load({"a": 1}).plugin_config(), {"a": 1})


if __name__ == "__main__":
    unittest.main()
