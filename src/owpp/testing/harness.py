"""The test harness: the real Open-WebUI, in the test process (ADR 0004).

    with Harness() as owui:
        plugin = owui.load("plugins/excalidraw")
        owui.startup()
        user = owui.add_user("Ada")
        chat = owui.add_chat(user)
        owui.tool("excalidraw").call("show_excalidraw", chat_id=chat, user=user)
        assert owui.client(user).get(f"/excalidraw/view/{chat}").status_code == 200

Open-WebUI's code is the pinned wheel (owpp.testing.wheel), imported once in each process with a
data folder of its own: its app, routers, models, event sinks and plugin loader all run as they do
in a deploy. A plugin is deployed through owpp's Open-WebUI adapter, over Open-WebUI's own HTTP
API, as `owpp deploy` does. Each Harness starts from the database and app state Open-WebUI had
just after its startup.

Open-WebUI's model is aimock (owpp.testing.aimock), as on `owpp live`'s stack: it answers
`model_reply` as `mock-model` and each `serve_model` id, and `completions` is its journal.

What the harness fakes, so a test can control and see it:
  - the socket: `sio.emit` records to `emitted` (there are no browsers to send to);
  - `__event_emitter__`, for calls the test makes: records to `chat_events`;
  - a plugin's `requirements:` are recorded in `requirements`, not installed with pip.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import MutableMapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..bundle import bundle_function, parse_frontmatter
from ..manifest import read_manifest
from ..openwebui import HttpResponse, OpenWebUI
from ..sources import Sources
from . import pin

# The state the owpp libraries keep in sys.modules (so it survives a reload), and the modules
# Open-WebUI makes for the functions and tools it loads: removed between tests.
_PLUGIN_MODULE_PREFIXES = ("function_", "tool_", "_plugin", "_owpp_src_")
PASSWORD = "owpp-test-harness"
DEFAULT_REPLY = "Hello! I am the harness's model."
BASE_URL = "http://testserver"
SECRET_KEY = "owpp-test-harness-secret-key-not-for-production"


def _check_python() -> None:
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    if running != pin.PYTHON:
        raise RuntimeError(
            f"the test harness runs Open-WebUI v{pin.VERSION}, which runs on Python {pin.PYTHON}; "
            f"this is Python {running}. Run the tests on {pin.PYTHON}, for example "
            f"`uvx --python {pin.PYTHON} --from 'owpp[test]' owpp test`"
        )


class User(SimpleNamespace):
    """A user the test added: Open-WebUI's UserModel fields, and the session `token` that signs
    them in (`client(user)` sends it). `model` is the UserModel itself."""

    def model_dump(self, **kwargs: Any) -> dict:
        return self.model.model_dump(**kwargs)


# ---- the Open-WebUI of this process ------------------------------------------------------


class _Runtime:
    """Open-WebUI, imported and started once in each process, and what is needed to put it back
    as it was after its startup."""

    def __init__(self) -> None:
        _check_python()
        from .wheel import open_webui_dir

        self.data_dir = Path(tempfile.mkdtemp(prefix="owpp-open-webui-")).resolve()
        self.static_dir = self.data_dir / "static"
        # Open-WebUI's web app, as far as a plugin sees it: its index.html, served at every path
        # nothing else answers. Put back before each test, as a plugin may write to it.
        self.frontend_dir = frontend = self.data_dir / "build"
        (frontend / "static").mkdir(parents=True)
        self.static_dir.mkdir()
        self._index = (open_webui_dir() / "open_webui" / "frontend" / "index.html").read_bytes()
        (frontend / "index.html").write_bytes(self._index)
        # Open-WebUI's model is aimock (owpp.testing.aimock), as on `owpp live`'s stack: its
        # connection is Open-WebUI's default, read from the environment, and every user may use
        # its models. aimock starts when a test first uses the model.
        from .aimock import Aimock, free_port

        self.loop = asyncio.new_event_loop()
        self._tasks: set = set()
        self.recorder: Harness | None = None
        self.model = Aimock(free_port())
        self._environ = dict(os.environ)  # put back by shut_down(): Open-WebUI writes to it too
        # The settings of owpp live's Open-WebUI (its compose file), so the unit tests and the
        # live tests run the same Open-WebUI; then what only this process has.
        os.environ.update(_live_settings())
        os.environ.update(
            OPENAI_API_BASE_URLS=f"{self.model.url}/v1",
            OPENAI_API_KEYS="owpp-test-harness",
            DATA_DIR=str(self.data_dir),
            STATIC_DIR=str(self.static_dir),
            FRONTEND_BUILD_DIR=str(frontend),
            USE_SLIM_DOCKER="true",
            # As `open-webui serve` (the pip install) sets it: its version comes from the
            # wheel's metadata, not 0.0.0.
            FROM_INIT_PY="true",
            WEBUI_SECRET_KEY=SECRET_KEY,
        )
        os.environ.setdefault("GLOBAL_LOG_LEVEL", "WARNING")  # Open-WebUI's, unless set
        if str(open_webui_dir()) not in sys.path:
            sys.path.insert(0, str(open_webui_dir()))
        with contextlib.redirect_stdout(sys.stderr):  # the banner and the migrations' prints
            from open_webui.main import app

        import open_webui.utils.plugin as plugin
        from open_webui.socket.main import sio

        self.app = app
        self._fake(sio, plugin)

        self._lifespan = app.router.lifespan_context(app)
        self.loop.run_until_complete(self._lifespan.__aenter__())
        self.loop.run_until_complete(self.settle())
        self._snapshot()

    async def refresh_models(self) -> None:
        """Open-WebUI reads its connections' model lists again, as when the model list is
        opened (`app.state.MODELS`)."""
        from open_webui.utils.models import get_all_models
        from starlette.requests import Request

        request = Request(
            {
                "type": "http",
                "app": self.app,
                "method": "GET",
                "path": "/internal",
                "headers": [],
                "query_string": b"",
            }
        )
        await get_all_models(request, refresh=True)

    def _fake(self, sio, plugin) -> None:
        runtime = self

        async def emit(event, data=None, room=None, to=None, **kwargs):
            if runtime.recorder is not None:
                runtime.recorder.emitted.append((event, data))

        sio.emit = emit

        def install_frontmatter_requirements(requirements: str):
            if requirements and runtime.recorder is not None:
                runtime.recorder.requirements.append(requirements)

        _replace(plugin.install_frontmatter_requirements, install_frontmatter_requirements)

        # Open-WebUI's API answers a plugin that fails to load with a bare 400: keep the
        # ModuleNotFoundError of one that imports a package the slim set lacks, for load().
        for name in ("load_function_module_by_id", "load_tool_module_by_id"):
            _replace(getattr(plugin, name), _noting_missing_packages(getattr(plugin, name), self))

    # ---- putting it back ---------------------------------------------------------------

    def _tables(self):
        from open_webui.internal.db import engine
        from sqlalchemy import MetaData

        if not hasattr(self, "_sorted_tables"):
            meta = MetaData()
            meta.reflect(engine)
            self._sorted_tables = meta.sorted_tables
        return engine, self._sorted_tables

    def _snapshot(self) -> None:
        engine, tables = self._tables()
        with engine.connect() as conn:
            self._rows = {
                t.name: [dict(r) for r in conn.execute(t.select()).mappings()] for t in tables
            }
        self._state = dict(self.app.state._state)
        self._routes = list(self.app.router.routes)
        self._modules = set(sys.modules)
        self._tasks = {t for t in asyncio.all_tasks(self.loop) if not t.done()}  # its own
        self._files = {p for p in self.data_dir.rglob("*") if not p.name.startswith("webui.db")}

    def shut_down(self) -> None:
        """Stop this Open-WebUI and take it out of the process: its startup undone, its loop
        closed, aimock stopped, and every `open_webui` and plugin module removed, so the next
        import is a new Open-WebUI."""
        from open_webui.internal.db import async_engine, engine

        self.stop_tasks()
        with contextlib.suppress(Exception):
            self.loop.run_until_complete(self._lifespan.__aexit__(None, None, None))
        self.stop_tasks()
        self.loop.run_until_complete(async_engine.dispose())
        engine.dispose()
        self.loop.close()
        self.model.stop()
        for name in list(sys.modules):
            if name.split(".")[0] == "open_webui" or name.startswith(_PLUGIN_MODULE_PREFIXES):
                del sys.modules[name]
        for key in [k for k in os.environ if k not in self._environ]:
            del os.environ[key]
        os.environ.update(self._environ)
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def stop_tasks(self) -> None:
        """Cancel the tasks a test left running (a repeating job, a page's stream)."""
        pending = [t for t in asyncio.all_tasks(self.loop) if not t.done() and t not in self._tasks]
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

    def reset(self) -> None:
        """Put Open-WebUI back as it was just after its startup."""
        self.stop_tasks()
        from open_webui.internal.db import async_engine

        # A cancelled task can leave a connection in the middle of a transaction: close them all.
        self.loop.run_until_complete(async_engine.dispose())
        engine, tables = self._tables()
        with engine.begin() as conn:
            for table in reversed(tables):
                conn.execute(table.delete())
            for table in tables:
                rows = self._rows.get(table.name)
                if rows:
                    conn.execute(table.insert(), rows)
        engine.dispose()
        state = self.app.state._state
        state.clear()
        state.update(
            {k: (type(v)(v) if type(v) in (dict, list, set) else v) for k, v in self._state.items()}
        )
        self.app.router.routes[:] = self._routes
        self.app.openapi_schema = None
        for name in [m for m in sys.modules if m not in self._modules]:
            if name.startswith(_PLUGIN_MODULE_PREFIXES):
                del sys.modules[name]
        (self.frontend_dir / "index.html").write_bytes(self._index)
        for path in sorted(self.data_dir.rglob("*"), reverse=True):
            if path.name.startswith("webui.db") or path in self._files:
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    # ---- running async code ------------------------------------------------------------

    def run(self, awaitable):
        async def settled():
            result = await awaitable
            await self.settle()
            return result

        return self.loop.run_until_complete(settled())

    async def settle(self, idle: float = 0.05, budget: float = 10.0) -> None:
        """Let the tasks that were started (an event dispatch, a runtime sync, a request to a
        server the test runs) run until they finish or wait. A task that sleeps (a repeating
        job) counts as waiting, and so does one whose await has not moved for `idle` seconds
        (a page's stream waiting for news). Open-WebUI's own background tasks are left alone."""
        me = asyncio.current_task()
        loop = asyncio.get_running_loop()
        start = changed = loop.time()
        last = None
        while True:
            for _ in range(3):
                await asyncio.sleep(0)
            busy = {
                t: _awaiting(t)
                for t in asyncio.all_tasks()
                if t is not me and not t.done() and t not in self._tasks
            }
            busy = {t: at for t, at in busy.items() if at is not _SLEEPING}
            now = loop.time()
            if not busy or now - start > budget:
                return
            if busy != last:
                last, changed = busy, now
            elif now - changed > idle:
                return
            await asyncio.sleep(0.001)


_SLEEPING = object()


def _awaiting(task: asyncio.Task):
    """What the task waits on: _SLEEPING in asyncio.sleep, else the innermost awaitable."""
    coro = task.get_coro()
    at = coro
    while True:
        code = getattr(at, "cr_code", None) or getattr(at, "gi_code", None)
        if code is not None and code.co_name == "sleep" and "asyncio" in code.co_filename:
            return _SLEEPING
        inner = getattr(at, "cr_await", None) or getattr(at, "gi_yieldfrom", None)
        if inner is None:
            return id(at)
        at = inner


def _live_settings() -> dict[str, str]:
    """The environment of the `open-webui` service in owpp live's compose file, but for what
    names that stack's own addresses and secret."""
    import yaml

    from ..live.stack import COMPOSE

    service = yaml.safe_load(COMPOSE.read_text())["services"]["open-webui"]
    own = {"OPENAI_API_BASE_URLS", "OPENAI_API_KEYS", "WEBUI_SECRET_KEY"}
    return {k: str(v) for k, v in (service.get("environment") or {}).items() if k not in own}


def _replace(original, new) -> None:
    """Put `new` in place of `original` in every Open-WebUI module that holds it."""
    for module in list(sys.modules.values()):
        if getattr(module, "__name__", "").startswith("open_webui"):
            for attr, value in list(vars(module).items()):
                if value is original:
                    setattr(module, attr, new)


def _noting_missing_packages(load, runtime: _Runtime):
    async def noting(*args, **kwargs):
        try:
            return await load(*args, **kwargs)
        except ModuleNotFoundError as error:
            if runtime.recorder is not None:
                runtime.recorder._missing = error
            raise

    return noting


_RUNTIME: _Runtime | None = None


def runtime(fresh: bool = False) -> _Runtime:
    """The Open-WebUI of this process, started on first use. `fresh` shuts it down and starts a
    new one: imported again, with a new data folder, and its startup run again."""
    global _RUNTIME
    if fresh and _RUNTIME is not None:
        _RUNTIME.shut_down()
        _RUNTIME = None
    if _RUNTIME is None:
        _RUNTIME = _Runtime()
    return _RUNTIME


# ---- HTTP into the app, on the harness's loop -----------------------------------------------


def _transport(rt: _Runtime):
    import httpx

    asgi = httpx.ASGITransport(app=rt.app)

    class Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            async def send():
                request.stream = httpx.ByteStream(request.read())
                response = await asgi.handle_async_request(request)
                body = b"".join([chunk async for chunk in response.aiter_raw()])
                await rt.settle()
                return httpx.Response(
                    response.status_code, headers=response.headers, content=body, request=request
                )

            return rt.loop.run_until_complete(send())

    return Transport()


# ---- what the test loaded -------------------------------------------------------------------


class LoadedPlugin:
    """A function Open-WebUI holds: its row, and the module and instance Open-WebUI loaded."""

    def __init__(self, owui: Harness, id: str, folder: Path | None):
        self.owui, self.id, self.folder = owui, id, folder

    @property
    def row(self):
        """The function's row (FunctionModel)."""
        from open_webui.models.functions import Functions

        return self.owui.run(Functions.get_function_by_id(self.id))

    @property
    def type(self) -> str:
        return self.row.type

    @property
    def instance(self):
        """The instance of the function's class, as Open-WebUI keeps it in its cache."""
        from open_webui.utils.plugin import get_function_module_from_cache

        return self.owui.run(get_function_module_from_cache(self.owui.request(), self.id))[0]

    @property
    def module(self):
        """The loaded module, for its helper functions."""
        _ = self.instance  # loaded, if it was not
        return sys.modules[f"function_{self.id}"]

    @property
    def valves(self):
        return getattr(self.instance, "valves", None)

    def call(
        self,
        method: str,
        *args,
        user: User | None = None,
        chat_id: str | None = None,
        model: str = "mock-model",
        **kwargs,
    ):
        """Call a method of the instance directly, with the stored valves applied and the
        `__name__` arguments it takes: those Open-WebUI's chat middleware passes (`__user__`,
        `__metadata__`, `__model__` as Open-WebUI lists `model`, `__event_emitter__`,
        `__event_call__`, `__oauth_token__`, `__request__`, `__chat_id__`, `__message_id__`),
        `__id__`, and `__app__`, as Open-WebUI's event dispatch passes it. For the whole chat
        pipeline, use `owui.send()`."""
        from open_webui.models.functions import Functions

        instance = self.instance
        if hasattr(instance, "Valves"):
            valves = self.owui.run(Functions.get_function_valves_by_id(self.id))
            instance.valves = instance.Valves(**(valves or {}))
        fn = getattr(instance, method)
        return self.owui._invoke(
            fn, args, kwargs, user=user, chat_id=chat_id, own_id=self.id, model=model
        )

    def inlet(
        self,
        body: dict,
        user: User | None = None,
        chat_id: str | None = None,
        model: str = "mock-model",
    ) -> dict:
        """A chat request with `model` passing through this filter on its way to the model, as
        Open-WebUI runs one filter (its `process_filter_function`: the stored valves, the user's
        valves, and the arguments the handler takes)."""
        return self._filter("inlet", body, user, chat_id, model)

    def outlet(
        self,
        body: dict,
        user: User | None = None,
        chat_id: str | None = None,
        model: str = "mock-model",
    ) -> dict:
        """A finished reply from `model` passing through this filter, as Open-WebUI runs it."""
        return self._filter("outlet", body, user, chat_id, model)

    def _filter(self, filter_type, body, user, chat_id, model) -> dict:
        from open_webui.models.functions import Functions
        from open_webui.utils.filter import process_filter_function

        owui = self.owui
        row = owui.run(Functions.get_function_by_id(self.id))
        extra = owui._chat_params(user, chat_id, model)

        async def go():
            form, _, _ = await process_filter_function(
                extra["__request__"], row, filter_type, body, extra, None, None, [self.id]
            )
            return form

        with owui._missing_packages():
            return owui.run(go())


class LoadedTool:
    """A tool as Open-WebUI runs it: the instance its loader made from the stored code."""

    def __init__(self, owui: Harness, id: str, instance):
        self.owui, self.id, self.instance = owui, id, instance

    @property
    def module(self):
        return sys.modules[f"tool_{self.id}"]

    @property
    def row(self):
        return self.owui.tools[self.id]

    @property
    def specs(self) -> list[dict]:
        """What the model is told about the tool's methods (Open-WebUI's get_tool_specs)."""
        from open_webui.utils.tools import get_tool_specs

        return get_tool_specs(self.instance)

    def call(
        self, method: str, *args, user: User | None = None, chat_id: str | None = None, **kwargs
    ):
        """Call a tool method as the model would, with `__user__`, `__metadata__` and the other
        injected arguments it asks for."""
        fn = getattr(self.instance, method)
        return self.owui._invoke(fn, args, kwargs, user=user, chat_id=chat_id, own_id=self.id)


class _Config(MutableMapping):
    """The config table, read and written through Open-WebUI's Config model."""

    def __init__(self, owui: Harness):
        self._owui = owui

    def _all(self) -> dict:
        from open_webui.internal.db import engine
        from sqlalchemy import text

        with engine.connect() as conn:
            rows = conn.execute(text("SELECT key FROM config")).all()
        from open_webui.models.config import Config

        return {k: self._owui.run(Config.get(k)) for (k,) in rows}

    def __getitem__(self, key):
        from open_webui.models.config import Config

        missing = object()
        value = self._owui.run(Config.get(key, missing))
        if value is missing:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        from open_webui.models.config import Config

        self._owui.run(Config.upsert({key: value}))

    def __delitem__(self, key):
        from open_webui.models.config import Config

        self._owui.run(Config.delete(key))

    def __iter__(self):
        return iter(self._all())

    def __len__(self):
        return len(self._all())

    def update(self, *args, **kwargs):  # one upsert
        from open_webui.models.config import Config

        self._owui.run(Config.upsert(dict(*args, **kwargs)))


# ---- the harness -----------------------------------------------------------------------------


class Harness:
    """The real Open-WebUI, from the state it had just after its startup, for one test. Use it as
    a context manager.

    To set up and assert on:
      functions, function_valves, tools, tool_valves, skills, models, users: {id: row}, read from
        the database each time (change them through `run()` and Open-WebUI's models);
      config: the config table, read and written through `Config`;
      admin: the admin that deploys the loaded functions;
      emitted, chat_events, completions, model_reply, requirements: what the fakes saw.

    `fresh=True` starts a new Open-WebUI for this harness (see __init__).

    `sources` is what `load()` reads a `source:` plugin's files from git through; it is the
    caller's to close. A harness given none makes its own, and closes it when it closes.
    """

    def __init__(self, sources: Sources | None = None, fresh: bool = False):
        """`fresh`: a new Open-WebUI, imported and started again, in place of the one this
        process has, put back to just after its startup. Slower (some seconds); for a test
        that needs Open-WebUI's modules or its startup new."""
        if runtime().recorder is not None and fresh:
            raise RuntimeError("another Harness is open in this process; close it first")
        self._rt = runtime(fresh=fresh)
        self._own_sources = sources is None
        self.sources = Sources() if sources is None else sources
        self.app = self._rt.app
        self.data_dir = self._rt.data_dir
        self.static_dir = self._rt.static_dir
        self.emitted: list[tuple[str, Any]] = []
        self.chat_events: list[tuple[str | None, dict]] = []
        # aimock needs some answer: a test sets its own with `model_reply`.
        self._model_reply: str = DEFAULT_REPLY
        self.requirements: list[str] = []
        self.served_models: list[str] = []
        self.event_call_reply: Any = None
        self._serving = False  # aimock has this harness's fixtures
        self.plugins: dict[str, LoadedPlugin] = {}
        self._missing: ModuleNotFoundError | None = None
        self._open = False
        self.__enter__()
        try:
            self.admin = self.add_user("Admin", role="admin")
        except BaseException:
            self.close()
            raise
        self.api = OpenWebUI(BASE_URL, self._fetch, self.admin.token)

    # ---- open / close --------------------------------------------------------------------

    def __enter__(self) -> Harness:
        if not self._open:
            if self._rt.recorder is not None and self._rt.recorder is not self:
                raise RuntimeError("another Harness is open in this process; close it first")
            self._rt.reset()
            if self._rt.model.running:
                self._rt.model.set_fixtures([])
            self._rt.recorder = self
            self._open = True
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if not self._open:
            return
        self._open = False
        self._rt.stop_tasks()  # the next harness resets the rest
        self._rt.recorder = None
        if self._own_sources:
            self.sources.close()

    @property
    def loop(self):
        return self._rt.loop

    def run(self, awaitable):
        """Run a coroutine on Open-WebUI's loop, then let the background tasks it started run
        until they finish or wait."""
        return self._rt.run(awaitable)

    # ---- HTTP ----------------------------------------------------------------------------

    def _fetch(self, method, url, headers=None, body=None) -> HttpResponse:
        with self.client() as client:
            res = client.request(method, url, headers=headers, content=body)
        return HttpResponse(res.status_code, res.text)

    def client(self, user: User | None = None, **kwargs):
        """An httpx client for the app, signed in as `user` (a bearer token) or as nobody.
        kwargs go to httpx.Client (follow_redirects=False to see a redirect)."""
        import httpx

        kwargs.setdefault("follow_redirects", True)
        client = httpx.Client(transport=_transport(self._rt), base_url=BASE_URL, **kwargs)
        if user is not None:
            client.headers["Authorization"] = f"Bearer {user.token}"
        return client

    def request(self, user: User | None = None):
        """A request such as Open-WebUI passes as `__request__`."""
        from starlette.requests import Request

        headers = [(b"authorization", f"Bearer {user.token}".encode())] if user else []
        return Request(
            {
                "type": "http",
                "app": self.app,
                "method": "POST",
                "path": "/api/chat/completions",
                "headers": headers,
                "query_string": b"",
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 12345),
            }
        )

    # ---- users and data --------------------------------------------------------------------

    def add_user(self, name: str = "User", role: str = "user", email: str | None = None) -> User:
        """A user with a sign-in record (password PASSWORD), and the session `token` that
        Open-WebUI's own sign-in issues them (`create_session_response`)."""
        from open_webui.models.auths import Auths
        from open_webui.utils.auth import create_session_response

        email = email or f"{name.lower().replace(' ', '.')}.{uuid.uuid4().hex[:6]}@example.com"
        model = self.run(Auths.insert_new_auth(email, _password_hash(self), name, role=role))
        auth = self.run(Auths.get_auth_by_id(model.id))
        session = self.run(create_session_response(self.request(), model, auth=auth))
        return User(**dict(model), token=session["token"], model=model)

    def add_chat(
        self,
        user: User,
        id: str | None = None,
        title: str = "New Chat",
        messages: list[dict] | None = None,
        meta: dict | None = None,
        created_at: int | None = None,
        updated_at: int | None = None,
        files: list[str] = (),
        **fields,
    ) -> str:
        """A saved chat owned by `user`; returns its id. `files` links file ids to it."""
        from open_webui.models.chats import ChatForm, Chats

        chat_id = id or str(uuid.uuid4())
        history, parent = {}, None
        for message in messages or []:
            mid = message.get("id") or str(uuid.uuid4())
            history[mid] = {"parentId": parent, "childrenIds": [], **message, "id": mid}
            if parent:
                history[parent]["childrenIds"].append(mid)
            parent = mid
        chat = {
            "title": title,
            "history": {"messages": history, "currentId": parent},
            "messages": list(history.values()),
        }
        self.run(Chats.insert_new_chat(chat_id, user.id, ChatForm(chat=chat)))
        changes = {
            k: v
            for k, v in {
                "meta": meta,
                "created_at": created_at or updated_at,
                "updated_at": updated_at,
                **fields,
            }.items()
            if v is not None
        }
        if changes:
            self._update_row("chat", chat_id, changes)
        if files:
            self.run(Chats.insert_chat_files(chat_id, parent or "", list(files), user.id))
        return chat_id

    def chat(self, chat_id: str):
        """The chat, as Open-WebUI's Chats model returns it."""
        from open_webui.models.chats import Chats

        return self.run(Chats.get_chat_by_id(chat_id))

    def grant_chat(self, chat_id: str, user: User, permission: str = "read") -> None:
        """Let a user other than the owner read (or write) a chat, as Open-WebUI lets them: the
        chat goes into a folder of its owner's, shared to continue in, and the user is granted
        `permission` on the folder."""
        from open_webui.models.access_grants import AccessGrants
        from open_webui.models.folders import FolderForm, Folders

        chat = self.chat(chat_id)
        folder_id = chat.folder_id
        if folder_id is None:
            folder = self.run(
                Folders.insert_new_folder(
                    chat.user_id,
                    FolderForm(name=f"Shared {chat_id}", data={"share_mode": "continue"}),
                )
            )
            folder_id = folder.id
            self._update_row("chat", chat_id, {"folder_id": folder_id})
        self.run(AccessGrants.grant_access("folder", folder_id, "user", user.id, permission))

    def add_note(self, user: User, title: str = "Note", markdown: str = "", **fields) -> str:
        from open_webui.models.notes import NoteForm, Notes

        note = self.run(
            Notes.insert_new_note(
                user.id, NoteForm(title=title, data={"content": {"md": markdown}})
            )
        )
        if fields:
            self._update_row("note", note.id, fields)
        return note.id

    def add_file(self, user: User, filename: str = "file.txt", size: int = 0, **fields) -> str:
        from open_webui.models.files import FileForm, Files

        fid = fields.pop("id", None) or str(uuid.uuid4())
        form = FileForm(
            id=fid,
            filename=filename,
            path=fields.pop("path", str(self.data_dir / "uploads" / f"{fid}_{filename}")),
            hash=fields.pop("hash", None),
            meta={"size": size, "content_type": fields.pop("content_type", "text/plain")},
        )
        self.run(Files.insert_new_file(user.id, form))
        if fields:
            self._update_row("file", fid, fields)
        return fid

    def _update_row(self, table: str, id: str, values: dict) -> None:
        from open_webui.internal.db import engine
        from sqlalchemy import MetaData, Table

        t = Table(table, MetaData(), autoload_with=engine)
        with engine.begin() as conn:
            conn.execute(t.update().where(t.c.id == id).values(**values))

    # ---- the tables ------------------------------------------------------------------------

    @property
    def functions(self) -> dict:
        from open_webui.models.functions import Functions

        return {f.id: f for f in self.run(Functions.get_functions())}

    @property
    def function_valves(self) -> dict:
        from open_webui.models.functions import Functions

        return {i: self.run(Functions.get_function_valves_by_id(i)) or {} for i in self.functions}

    @property
    def tools(self) -> dict:
        from open_webui.models.tools import Tools

        return {t.id: t for t in self.run(Tools.get_tools())}

    @property
    def tool_valves(self) -> dict:
        from open_webui.models.tools import Tools

        out = {}
        for i in self.tools:
            valves = self.run(Tools.get_tool_valves_by_id(i))
            if valves is not None:
                out[i] = valves
        return out

    @property
    def skills(self) -> dict:
        from open_webui.models.skills import Skills

        return {s.id: s for s in self.run(Skills.get_skills())}

    @property
    def models(self) -> dict:
        from open_webui.models.models import Models

        return {m.id: m for m in self.run(Models.get_all_models())}

    @property
    def users(self) -> dict:
        from open_webui.models.users import Users

        return {u.id: u for u in self.run(Users.get_users())["users"]}

    @property
    def config(self) -> _Config:
        return _Config(self)

    # ---- loading plugins --------------------------------------------------------------------

    def load(
        self,
        folder: Path | str,
        id: str | None = None,
        valves: dict | None = None,
        active: bool = True,
        sources: dict[str, str] | None = None,
        content: str | None = None,
    ) -> LoadedPlugin:
        """Bundle a plugin folder as `owpp deploy` would and deploy it over Open-WebUI's API:
        the function is created (or updated, if the id is there), its valves saved (default: the
        manifest's), and it is switched on if `active`. A `source:` plugin's files are fetched
        from git at the pinned commit through the harness's Sources (each file once). `sources`
        stands in for them instead, so a test needs no network:
        {path inside the source's `path`: text}, e.g. {"tool.py": "class Tools: ..."}. For a
        plugin taken whole from git, they are the upstream folder's files, plugin.yaml included."""
        from ..bundle import function_meta

        folder = Path(folder)
        if folder.is_file():
            raise ValueError(
                f"{folder}: load() takes a plugin folder (one with a plugin.yaml). "
                f"`owpp import {folder.as_posix()}` makes one of this file, header and all"
            )
        id = id or folder.name
        key = (_folder_key(folder), tuple(sorted((sources or {}).items())), content)
        if key not in _BUNDLES:
            reader = self.sources if sources is None else _stand_ins(folder, sources, self.sources)
            resolved = reader.resolve(folder)
            code = bundle_function(resolved) if content is None else content
            if code is None:
                raise ValueError(f"{folder}: no function to load")
            fn = resolved.manifest.get("function") or {}
            _BUNDLES[key] = (code, function_meta(code, resolved), fn)
        content, meta, fn = _BUNDLES[key]
        if valves is None:
            valves = fn.get("valves") or {}
        name = parse_frontmatter(content).get("title") or id
        existing = id in self.functions
        with self._missing_packages():
            if existing:
                self.api.update_function(id, name, content, meta)
            else:
                self.api.create_function(id, name, content, meta)
        if valves:
            current = self.run(_function_valves(id)) or {}
            self.api.update_valves(id, {**current, **valves})
        row = self.functions[id]
        if not existing:
            if fn.get("global") and not row.is_global:
                self.api.toggle_global(id)
            if active and not row.is_active:
                with self._missing_packages():
                    self.api.toggle(id)
        plugin = LoadedPlugin(self, id, folder)
        self.plugins[id] = plugin
        return plugin

    def tool(self, tool_id: str) -> LoadedTool:
        """The installed tool, loaded from its stored code as Open-WebUI does when a chat uses it,
        with its stored valves."""
        from open_webui.models.tools import Tools
        from open_webui.utils.plugin import get_tool_module_from_cache

        if tool_id not in self.tools:
            raise KeyError(f"no tool {tool_id!r} is installed (installed: {sorted(self.tools)})")
        with self._missing_packages():
            instance = self.run(get_tool_module_from_cache(self.request(), tool_id))[0]
        if hasattr(instance, "Valves"):
            valves = self.run(Tools.get_tool_valves_by_id(tool_id))
            instance.valves = instance.Valves(**(valves or {}))
        return LoadedTool(self, tool_id, instance)

    # ---- events -----------------------------------------------------------------------------

    def emit(self, name: str, subject: str | dict | None = None, data: dict | None = None) -> None:
        """Publish an Open-WebUI event through its event sinks, as Open-WebUI does. `subject` is
        a function's id, or the subject itself for an event about something else
        (`{"type": "user", "id": ...}`). For a `*_started` event about a function, that function
        gets it too, as Open-WebUI does before it switches one on."""
        from open_webui.events import build_event, dispatch_event_functions, publish_event

        if isinstance(subject, dict):
            subject_id, subject_type = subject.get("id"), subject.get("type")
        else:
            subject_id, subject_type = subject, "function" if subject else None
        request = self.request(self.admin)
        if name.endswith("_started") and subject_type == "function":
            event = build_event(
                request,
                name,
                actor=self.admin.model,
                subject_id=subject_id,
                subject_type=subject_type,
                data=data,
            )
            self.run(dispatch_event_functions(request, event, extra_function_ids=[subject_id]))
            return
        self.run(
            publish_event(
                request,
                name,
                actor=self.admin.model,
                subject_id=subject_id,
                subject_type=subject_type,
                data=data,
                source="system",
            )
        )

    def startup(self) -> None:
        """Open-WebUI finished starting: `system.startup.completed`."""
        self.emit("system.startup.completed")

    def enable(self, function_id: str) -> None:
        if not self.functions[function_id].is_active:
            self.api.toggle(function_id)

    def disable(self, function_id: str) -> None:
        if self.functions[function_id].is_active:
            self.api.toggle(function_id)

    def set_valves(self, function_id: str, **valves) -> None:
        """An admin saved the function's valves."""
        current = self.run(_function_valves(function_id)) or {}
        self.api.update_valves(function_id, {**current, **valves})

    # ---- the model (aimock) ----------------------------------------------------------------

    @property
    def model_reply(self) -> str:
        """What the model answers, as every model it serves (`mock-model`, and `serve_model`'s)."""
        return self._model_reply

    @model_reply.setter
    def model_reply(self, text: str) -> None:
        self._model_reply = text
        self._serve()

    def serve_model(self, model_id: str) -> None:
        """The model also answers as `model_id`, and Open-WebUI lists it, as after an admin adds
        a connection that serves it. `mock-model` is always served."""
        if model_id not in self.served_models:
            self.served_models.append(model_id)
        self._serve()

    def send(
        self, user: User, message: str | list[dict], model: str = "mock-model", **body
    ) -> dict:
        """Send a chat request as the user's browser does (`POST /api/chat/completions`), so
        Open-WebUI's own chat pipeline runs: the filters it picks for the chat (global ones, the
        model's, those in `filter_ids`), the tools in `tool_ids`, the model (aimock), and the
        outlets. `message` is the user's message, or the whole `messages` list. Other keys of
        the request go in `body` (`chat_id`, `tool_ids`, `stream`, ...). Returns the response."""
        if not self._serving:
            self._serve()
        messages = [{"role": "user", "content": message}] if isinstance(message, str) else message
        request = {"model": model, "messages": messages, "stream": False, **body}
        with self._missing_packages(), self.client(user) as client:
            response = client.post("/api/chat/completions", json=request)
        if response.status_code != 200:
            raise RuntimeError(
                f"POST /api/chat/completions: HTTP {response.status_code}: {response.text}"
            )
        return response.json() if not request.get("stream") else response.text

    @property
    def completions(self) -> list[dict]:
        """Each chat request the model got, as Open-WebUI sent it (aimock's journal)."""
        return self._rt.model.requests() if self._rt.model.running else []

    def _serve(self) -> None:
        """aimock answers `model_reply` as each served model; Open-WebUI reads the list again."""
        self._serving = True
        self._rt.model.start()
        models = ["mock-model", *(m for m in self.served_models if m != "mock-model")]
        self._rt.model.set_fixtures(
            [{"match": {"model": m}, "response": {"content": self._model_reply}} for m in models]
        )
        self.run(self._rt.refresh_models())

    def set_tool_valves(self, tool_id: str, **valves) -> None:
        """An admin saved the tool's valves (Workspace > Tools > Valves)."""
        current = self.tool_valves.get(tool_id, {})
        res = self.api.request(
            "POST", f"/api/v1/tools/id/{tool_id}/valves/update", {**current, **valves}
        )
        if res[0] != 200:
            raise RuntimeError(f"saving the valves of tool {tool_id}: HTTP {res[0]}: {res[1]}")

    def update(self, function_id: str, folder: Path | str | None = None) -> LoadedPlugin:
        """A new version was deployed: bundle the folder again and update the function."""
        folder = Path(folder or self.plugins[function_id].folder)
        return self.load(folder, id=function_id)

    def delete(self, function_id: str) -> None:
        self.api.delete_function(function_id)
        self.plugins.pop(function_id, None)

    # ---- calling plugin code ----------------------------------------------------------------

    def _chat_params(self, user, chat_id, model) -> dict:
        """The arguments Open-WebUI's chat middleware gives plugins (utils/middleware.py,
        `extra_params`): `__model__` is the model as Open-WebUI lists it, if it does."""
        listed = (getattr(self.app.state, "MODELS", None) or {}).get(model) if model else None
        metadata = {
            "chat_id": chat_id,
            "message_id": None,
            "session_id": None,
            "user_id": user.id if user else None,
            "model": listed,
        }
        return {
            "__event_emitter__": self._emitter(chat_id),
            "__event_call__": self._caller(chat_id),
            "__user__": user.model.model_dump() if user else {},
            "__metadata__": metadata,
            "__oauth_token__": None,
            "__request__": self.request(user),
            "__model__": listed or ({"id": model, "name": model} if model else None),
            "__chat_id__": chat_id,
            "__message_id__": None,
        }

    def _invoke(self, fn, args, kwargs, user, chat_id, own_id, model=None):
        accepted = inspect.signature(fn).parameters
        extra = {**self._chat_params(user, chat_id, model), "__id__": own_id, "__app__": self.app}
        for name, value in extra.items():
            if name in accepted and name not in kwargs:
                kwargs[name] = value

        async def go():
            result = fn(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        with self._missing_packages():
            return self.run(go())

    @contextlib.contextmanager
    def _missing_packages(self):
        """Name a package Open-WebUI's slim set lacks, with the version Open-WebUI pins, when
        the plugin's code (run here, or loaded by Open-WebUI behind its API) imports it."""
        self._missing = None
        try:
            yield
        except Exception as error:
            missing = error if isinstance(error, ModuleNotFoundError) else self._missing
            if missing is None:
                raise
            raise _explained(missing) from error

    def _caller(self, chat_id):
        """`__event_call__`: a question to the user's browser. It is recorded in `chat_events`,
        and answered with `event_call_reply`."""

        async def call(event: dict):
            self.chat_events.append((chat_id, event))
            return self.event_call_reply

        return call

    def _emitter(self, chat_id):
        async def emit(event: dict):
            self.chat_events.append((chat_id, event))

        return emit


# ---- helpers ---------------------------------------------------------------------------------

# What load() bundled in this process, by the folder's files (path, size, mtime) and the stand-ins
# it was given: a test that changes a file of the folder gets a new bundle.
_BUNDLES: dict = {}


def _folder_key(folder: Path) -> tuple:
    root = folder.resolve()
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            stat = path.stat()
            files.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
    return (str(root), tuple(files))


def grants(row) -> list[dict]:
    """A tool's, skill's or model's access grants as an admin sets them:
    [{"principal_type", "principal_id", "permission"}], in the order Open-WebUI keeps them."""
    keys = ("principal_type", "principal_id", "permission")
    return [{k: getattr(g, k) for k in keys} for g in row.access_grants or []]


_HASH: str | None = None


def _password_hash(owui: Harness) -> str:
    """One bcrypt hash of PASSWORD for every user of the run: hashing is slow on purpose."""
    global _HASH
    if _HASH is None:
        from open_webui.utils.auth import get_password_hash

        _HASH = owui.run(get_password_hash(PASSWORD))
    return _HASH


async def _function_valves(function_id: str) -> dict | None:
    from open_webui.models.functions import Functions

    return await Functions.get_function_valves_by_id(function_id)


def _explained(error: ModuleNotFoundError) -> ModuleNotFoundError:
    top = (error.name or "").split(".")[0]
    known = pin.FULL_REQUIREMENTS.get(_normal(top)) if top else None
    hint = (
        f"add `{_normal(top)}=={known}` (Open-WebUI v{pin.VERSION}'s pin) to your test dependencies"
        if known
        else "add the package that provides it to your test dependencies"
    )
    return ModuleNotFoundError(
        f"{error}: owpp[test] installs the packages of Open-WebUI's slim image, which do not "
        f"include it; {hint}",
        name=error.name,
    )


def _normal(name: str) -> str:
    return name.lower().replace("_", "-")


def _stand_ins(folder: Path, files: dict[str, Any], behind: Sources) -> Sources:
    """Sources whose git holds `files` ({path inside the source's `path`: text}) at the pinned
    commit of `folder`'s `source:`. Anything else is fetched as `behind` does."""
    from ..manifest import get, text_of

    src = read_manifest(folder).get("source")
    git, ref = text_of(get(src, "git")), text_of(get(src, "ref"))
    base = "/".join(p for p in text_of(get(src, "path")).split("/") if p)
    held = {f"{base}/{k}" if base else k: v for k, v in files.items()}

    def fetcher(g: str, r: str, paths: list[str]) -> dict[str, Any]:
        if (g, r) != (git, ref):
            return behind.fetcher(g, r, paths)
        out = {}
        for path in paths:
            if path.endswith("/"):
                out |= {k: v for k, v in held.items() if k.startswith(path)}
            elif path in held:
                out[path] = held[path]
        return out

    return Sources(fetcher)


__all__ = ["Harness", "LoadedPlugin", "LoadedTool", "User", "grants"]
