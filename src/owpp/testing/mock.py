"""A mock Open-WebUI, in memory, for testing plugins without running Open-WebUI.

It stands in for the `open_webui.*` modules a plugin and the owpp libraries import (the
function, tool and skill tables, users, chats in a real SQLite database, the config table,
auth, the socket, event sinks, the FastAPI app) and loads a plugin the way Open-WebUI does:
the deployed bundle, executed as `function_<id>_<hex>`, its class instantiated with the
stored valves. Lifecycle events, chat filter calls, tool calls and HTTP requests then go
through the plugin's real code.

    with MockOpenWebUI() as owui:
        plugin = owui.load("plugins/excalidraw")
        owui.startup()
        user = owui.add_user("Ada")
        chat = owui.add_chat(user)
        owui.tool("excalidraw").call("show_excalidraw", chat_id=chat, user=user)
        assert owui.client(user).get(f"/excalidraw/view/{chat}").status_code == 200

What is real: FastAPI, Starlette, pydantic, SQLAlchemy (an in-memory SQLite database with
Open-WebUI's `chat` and `chat_file` tables). What is not: everything Open-WebUI itself does
beyond what plugins call. It is a stand-in written against Open-WebUI v0.13; when a plugin
needs a call it does not have, add it here.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import secrets
import shutil
import sys
import tempfile
import time
import types
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from ..bundle import bundle_function, function_type, parse_frontmatter
from ..manifest import read_manifest

# Modules a test run leaves behind and the mock removes on close: Open-WebUI's, the loaded
# plugins', and the state the libraries keep in sys.modules so it survives a reload.
_OWNED_PREFIXES = ("open_webui", "function_", "tool_", "_plugin", "_owpp_src_")


class Record(types.SimpleNamespace):
    """A row: attribute access like Open-WebUI's pydantic models, and model_dump()."""

    def model_dump(self, **_: Any) -> dict:
        def dump(value: Any) -> Any:
            if isinstance(value, Record):
                return value.model_dump()
            if isinstance(value, dict):
                return {k: dump(v) for k, v in value.items()}
            if isinstance(value, list):
                return [dump(v) for v in value]
            return value

        return {k: dump(v) for k, v in vars(self).items()}

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


# The model a filter is told the chat is with (`__model__`), unless a test names another.
MOCK_MODEL = "mock-model"


def get_last_user_message_item(messages: list[dict]) -> dict | None:
    """open_webui.utils.misc's: the last message from the user, or None."""
    return next((m for m in reversed(messages) if m.get("role") == "user"), None)


def _now() -> int:
    return int(time.time())


def _hex() -> str:
    return uuid.uuid4().hex


# ---- the database: Open-WebUI's chat tables, in SQLite ----------------------------------


def _tables():
    from sqlalchemy import JSON, BigInteger, Boolean, Column, String, Text
    from sqlalchemy.orm import declarative_base

    base = declarative_base()

    class Chat(base):
        __tablename__ = "chat"
        id = Column(String, primary_key=True)
        user_id = Column(String)
        title = Column(Text)
        chat = Column(JSON)
        created_at = Column(BigInteger)
        updated_at = Column(BigInteger)
        share_id = Column(Text, nullable=True)
        archived = Column(Boolean, default=False)
        pinned = Column(Boolean, default=False, nullable=True)
        meta = Column(JSON, default={})
        folder_id = Column(Text, nullable=True)

    class ChatFile(base):
        __tablename__ = "chat_file"
        id = Column(Text, primary_key=True)
        user_id = Column(Text)
        chat_id = Column(Text)
        message_id = Column(Text, nullable=True)
        file_id = Column(Text)
        created_at = Column(BigInteger)
        updated_at = Column(BigInteger)

    return base, Chat, ChatFile


class _AsyncSession:
    """Enough of SQLAlchemy's AsyncSession over a plain Session: the libraries await
    execute() and commit(), and ask get_bind() for the dialect."""

    def __init__(self, session):
        self._session = session

    async def execute(self, *args, **kwargs):
        return self._session.execute(*args, **kwargs)

    async def scalar(self, *args, **kwargs):
        return self._session.scalar(*args, **kwargs)

    async def commit(self):
        self._session.commit()

    async def rollback(self):
        self._session.rollback()

    async def flush(self):
        self._session.flush()

    async def refresh(self, obj):
        self._session.refresh(obj)

    async def delete(self, obj):
        self._session.delete(obj)

    def add(self, obj):
        self._session.add(obj)

    def get_bind(self, *args, **kwargs):
        return self._session.get_bind(*args, **kwargs)


# ---- the plugins it has loaded ----------------------------------------------------------


class _MissingName:
    """Stands in for a name from an `open_webui.*` module the mock does not implement: the
    import works, so third-party code loads, and using the name says what to add."""

    def __init__(self, module: str, name: str):
        self._where = f"{module}.{name}"

    def _missing(self, *args, **kwargs):
        raise NotImplementedError(
            f"the mock Open-WebUI has no {self._where}; add it to src/owpp/testing/mock.py"
        )

    __call__ = __fspath__ = __iter__ = __len__ = __getitem__ = __enter__ = __aenter__ = _missing

    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        self._missing()

    def __mro_entries__(self, bases):  # `class X(Missing)` at import: a plain base instead
        return (object,)


class _MissingModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _MissingName(self.__name__, name)


class _MissingFinder:
    """While the mock is installed, any other `open_webui.*` module imports as a stand-in."""

    def find_spec(self, fullname, path=None, target=None):
        import importlib.machinery

        if fullname == "open_webui" or fullname.startswith("open_webui."):
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        module = _MissingModule(spec.name)
        module.__path__ = []
        return module

    def exec_module(self, module):
        pass


_MISSING_FINDER = _MissingFinder()

# What `load()` without `sources=` reads git sources through, once per test session: each pinned
# file is fetched once. The pytest plugin closes it when the session ends.
_SESSION = None


def session_sources():
    """The test session's Sources (made on first use)."""
    global _SESSION
    from ..sources import Sources

    if _SESSION is None or _SESSION.closed:
        _SESSION = Sources()
    return _SESSION


def close_session_sources() -> None:
    if _SESSION is not None:
        _SESSION.close()


def _stand_ins(folder: Path, files: dict[str, Any]):
    """Sources whose git holds `files` ({path inside the source's `path`: text}) at the pinned
    commit of `folder`'s `source:`. Anything else, such as what a whole plugin's upstream takes
    from git itself, is fetched from git as the session does."""
    from ..manifest import get, text_of
    from ..sources import Sources

    src = read_manifest(folder).get("source")
    git, ref = text_of(get(src, "git")), text_of(get(src, "ref"))
    base = "/".join(p for p in text_of(get(src, "path")).split("/") if p)
    held = {f"{base}/{k}" if base else k: v for k, v in files.items()}

    def fetcher(g: str, r: str, paths: list[str]) -> dict[str, Any]:
        if (g, r) != (git, ref):
            return session_sources()._fetcher(g, r, paths)
        out = {}
        for path in paths:
            if path.endswith("/"):
                out |= {k: v for k, v in held.items() if k.startswith(path)}
            elif path in held:
                out[path] = held[path]
        return out

    return Sources(fetcher)


class LoadedPlugin:
    """A function as Open-WebUI holds it: its module and the instance of its class."""

    def __init__(self, owui: MockOpenWebUI, id: str, folder: Path | None, module, instance):
        self.owui, self.id, self.folder = owui, id, folder
        self.module, self.instance = module, instance

    @property
    def type(self) -> str:
        return self.owui.functions[self.id].type

    @property
    def row(self) -> Record:
        """The function's row in the functions table."""
        return self.owui.functions[self.id]

    @property
    def valves(self):
        return getattr(self.instance, "valves", None)

    def call(
        self,
        method: str,
        *args,
        user: Record | None = None,
        chat_id: str | None = None,
        model: str = MOCK_MODEL,
        **kwargs,
    ):
        """Call a method of the instance the way Open-WebUI does, adding the `__name__`
        arguments it takes (`__user__`, `__metadata__`, `__request__`, `__id__`,
        `__event_emitter__`, `__chat_id__`, `__app__`, and `__model__`, the model `model`
        names)."""
        fn = getattr(self.instance, method)
        return self.owui._invoke(
            fn, args, kwargs, user=user, chat_id=chat_id, own_id=self.id, model=model
        )

    def inlet(
        self,
        body: dict,
        user: Record | None = None,
        chat_id: str | None = None,
        model: str = MOCK_MODEL,
    ) -> dict:
        """A chat request with `model` passing through this filter on its way to the model."""
        return self.call("inlet", body, user=user, chat_id=chat_id, model=model)

    def outlet(
        self,
        body: dict,
        user: Record | None = None,
        chat_id: str | None = None,
        model: str = MOCK_MODEL,
    ) -> dict:
        """A finished reply from `model` passing through this filter."""
        return self.call("outlet", body, user=user, chat_id=chat_id, model=model)


class LoadedTool:
    """A tool as Open-WebUI runs it: the module made from the stored tool's code."""

    def __init__(self, owui: MockOpenWebUI, id: str, module, instance):
        self.owui, self.id, self.module, self.instance = owui, id, module, instance

    @property
    def row(self) -> Record:
        return self.owui.tools[self.id]

    @property
    def specs(self) -> list[dict]:
        """What the model is told about the tool's methods."""
        return _tool_specs(self.instance)

    def call(
        self, method: str, *args, user: Record | None = None, chat_id: str | None = None, **kwargs
    ):
        """Call a tool method as the model would, with `__user__`, `__metadata__` and the
        other injected arguments it asks for."""
        fn = getattr(self.instance, method)
        return self.owui._invoke(fn, args, kwargs, user=user, chat_id=chat_id, own_id=self.id)


def _tool_specs(instance) -> list[dict]:
    specs = []
    for name, fn in inspect.getmembers(instance, callable):
        if name.startswith("_") or inspect.isclass(fn):
            continue
        doc = inspect.getdoc(fn) or ""
        params = {
            p: {"description": ""}
            for p in inspect.signature(fn).parameters
            if not (p.startswith("__") and p.endswith("__"))
        }
        specs.append(
            {
                "name": name,
                "description": doc.split(":param", 1)[0].strip(),
                "parameters": {"type": "object", "properties": params},
            }
        )
    return specs


# ---- the mock ---------------------------------------------------------------------------


class MockOpenWebUI:
    """An Open-WebUI instance in memory. Use it as a context manager: entering puts its
    `open_webui.*` modules into sys.modules, leaving removes them and everything the loaded
    plugins left there.

    State, to set up and to assert on:
      functions, function_valves, tools, tool_valves, skills: {id: Record} / {id: dict}
      users: {id: Record}; admin: the user that owns the loaded functions
      config: the config table (`Config.get` / `Config.upsert`), {key: value}
      emitted: [(event, data)] sent on the socket (`sio.emit`)
      chat_events: [(chat_id, event)] sent through `__event_emitter__`
      app: the FastAPI app; event_sinks: Open-WebUI's EVENT_SINKS
    """

    def __init__(self, static_dir: Path | str | None = None, secret_key: str = "mock-secret"):
        from fastapi import FastAPI
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool
        from starlette.responses import HTMLResponse
        from starlette.routing import Mount
        from starlette.staticfiles import StaticFiles

        self._own_static = static_dir is None
        self.static_dir = Path(static_dir or tempfile.mkdtemp(prefix="owpp-static-"))
        # DATA_DIR and what Open-WebUI keeps under it (uploads, cache), and a stand-in for
        # its frontend build, for plugins that read them from open_webui.config /
        # open_webui.env. Removed on close.
        self.data_dir = Path(tempfile.mkdtemp(prefix="owpp-data-"))
        for sub in ("uploads", "cache", "build"):
            (self.data_dir / sub).mkdir()
        self.static_dir.mkdir(parents=True, exist_ok=True)
        self.secret_key = secret_key

        self.functions: dict[str, Record] = {}
        self.function_valves: dict[str, dict] = {}
        self.tools: dict[str, Record] = {}
        self.tool_valves: dict[str, dict] = {}
        self.skills: dict[str, Record] = {}
        self.users: dict[str, Record] = {}
        self.models: dict[str, Record] = {}  # model configs (Models), by id
        self.notes: dict[str, Record] = {}
        self.files: dict[str, Record] = {}
        self.config: dict[str, Any] = {}
        self.chat_access: dict[tuple[str, str], str] = {}  # (chat_id, user_id) -> "read" | "write"
        self.emitted: list[tuple[str, Any]] = []
        self.chat_events: list[tuple[str | None, dict]] = []
        # generate_chat_completion: what a plugin asked a model, and what the model answers
        self.completions: list[dict] = []
        self.model_reply: str = ""
        self.event_sinks: list = []
        self.plugins: dict[str, LoadedPlugin] = {}
        self._tool_modules: dict[str, tuple[str, LoadedTool]] = {}

        self.app = FastAPI()
        # Open-WebUI serves its static files at /static and the web app from a catch-all
        # mount at "/" last of all; plugin routes must land ahead of both.
        self.app.router.routes.append(
            Mount(
                "/static",
                app=StaticFiles(directory=self.static_dir, check_dir=False),
                name="static",
            )
        )

        async def spa(scope, receive, send):
            await HTMLResponse("<!doctype html><title>Open WebUI</title>")(scope, receive, send)

        self.app.router.routes.append(Mount("/", app=spa, name="spa-static-files"))

        base, self.Chat, self.ChatFile = _tables()
        self.engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        base.metadata.create_all(self.engine)

        self.loop = asyncio.new_event_loop()
        self._saved_modules: dict[str, Any] | None = None
        self.admin = self.add_user("Admin", role="admin")

    # ---- install / close -----------------------------------------------------------

    def __enter__(self) -> MockOpenWebUI:
        self.install()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def install(self) -> None:
        """Put the mock's `open_webui.*` modules into sys.modules."""
        if self._saved_modules is not None:
            return
        self._saved_modules = {
            k: v for k, v in sys.modules.items() if k.startswith(_OWNED_PREFIXES)
        }
        for name in list(self._saved_modules):
            del sys.modules[name]
        sys.modules.update(self._modules())
        if _MISSING_FINDER not in sys.meta_path:
            sys.meta_path.append(_MISSING_FINDER)  # last: only what nothing else provides

    def close(self) -> None:
        """Stop the plugins' background tasks and take the mock out of sys.modules."""
        if self.loop.is_closed():
            return
        pending = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        self.loop.close()
        if self._saved_modules is not None:
            for name in [k for k in sys.modules if k.startswith(_OWNED_PREFIXES)]:
                del sys.modules[name]
            sys.modules.update(self._saved_modules)
            self._saved_modules = None
            if _MISSING_FINDER in sys.meta_path:
                sys.meta_path.remove(_MISSING_FINDER)
        self.engine.dispose()
        if self._own_static:
            shutil.rmtree(self.static_dir, ignore_errors=True)
        shutil.rmtree(self.data_dir, ignore_errors=True)

    # ---- running async code --------------------------------------------------------

    def run(self, awaitable):
        """Run a coroutine on the mock's event loop, then let the background tasks it
        started (a runtime sync, a spawned job) run until they finish or wait. A task
        that sleeps (a repeating job) stays pending until close()."""
        self.install()

        async def settled():
            result = await awaitable
            await self._settle()
            return result

        return self.loop.run_until_complete(settled())

    async def _settle(self, quiet_rounds: int = 5) -> None:
        me = asyncio.current_task()
        quiet = 0
        while quiet < quiet_rounds:
            before = {t for t in asyncio.all_tasks() if t is not me and not t.done()}
            await asyncio.sleep(0)
            after = {t for t in asyncio.all_tasks() if t is not me and not t.done()}
            quiet = quiet + 1 if after == before else 0

    def _invoke(self, fn, args, kwargs, user, chat_id, own_id, model=None):
        accepted = inspect.signature(fn).parameters
        extra = {
            # Open-WebUI passes the whole model; plugins mostly read its id and name.
            "__model__": {"id": model, "name": model} if model else None,
            "__user__": self.user_dict(user) if user else None,
            "__metadata__": {
                "chat_id": chat_id,
                "user_id": user.id if user else None,
                "message_id": None,
                "session_id": None,
            },
            "__chat_id__": chat_id,
            "__request__": self.request(user),
            "__app__": self.app,
            "__id__": own_id,
            "__event_emitter__": self._emitter(chat_id),
        }
        for name, value in extra.items():
            if name in accepted and name not in kwargs:
                kwargs[name] = value

        async def go():
            result = fn(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        return self.run(go())

    def _emitter(self, chat_id):
        async def emit(event: dict):
            self.chat_events.append((chat_id, event))

        return emit

    # ---- users and data -------------------------------------------------------------

    def add_user(self, name: str = "User", role: str = "user", email: str | None = None) -> Record:
        """A user, with a `token` that signs them in (`client(user)` sends it)."""
        uid = str(uuid.uuid4())
        user = Record(
            id=uid,
            name=name,
            email=email or f"{name.lower().replace(' ', '.')}@example.com",
            role=role,
            token=f"sk-mock-{secrets.token_hex(8)}",
            profile_image_url="",
            created_at=_now(),
            updated_at=_now(),
        )
        self.users[uid] = user
        return user

    def user_dict(self, user: Record) -> dict:
        """The `__user__` a function or tool is given."""
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "valves": {},
        }

    def add_chat(
        self,
        user: Record,
        id: str | None = None,
        title: str = "New Chat",
        messages: list[dict] | None = None,
        meta: dict | None = None,
        created_at: int | None = None,
        updated_at: int | None = None,
        files: list[str] = (),
        **fields,
    ) -> str:
        """A saved chat owned by `user`; returns its id. `files` links file ids to it
        (the chat_file table)."""
        from sqlalchemy.orm import Session

        chat_id = id or str(uuid.uuid4())
        history = {m.get("id", str(i)): m for i, m in enumerate(messages or [])}
        now = _now()
        with Session(self.engine) as s:
            s.add(
                self.Chat(
                    id=chat_id,
                    user_id=user.id,
                    title=title,
                    chat={"title": title, "history": {"messages": history}},
                    meta=meta or {},
                    created_at=created_at or updated_at or now,
                    updated_at=updated_at or now,
                    **fields,
                )
            )
            for file_id in files:
                s.add(
                    self.ChatFile(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        chat_id=chat_id,
                        file_id=file_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
            s.commit()
        return chat_id

    def chat(self, chat_id: str) -> Record | None:
        """The chat's row, as Open-WebUI's Chats model returns it."""
        from sqlalchemy.orm import Session

        with Session(self.engine) as s:
            row = s.get(self.Chat, chat_id)
            return None if row is None else self._chat_record(row)

    def grant_chat(self, chat_id: str, user: Record, permission: str = "read") -> None:
        """Let a user other than the owner read (or write) a chat."""
        self.chat_access[(chat_id, user.id)] = permission

    def add_note(self, user: Record, title: str = "Note", markdown: str = "", **fields) -> str:
        nid = fields.pop("id", None) or str(uuid.uuid4())
        now = time.time_ns()  # notes store nanoseconds
        self.notes[nid] = Record(
            id=nid,
            user_id=user.id,
            title=title,
            data={"content": {"md": markdown}},
            is_pinned=False,
            access_grants=[],
            created_at=fields.pop("created_at", now),
            updated_at=fields.pop("updated_at", now),
            **fields,
        )
        return nid

    def add_file(self, user: Record, filename: str = "file.txt", size: int = 0, **fields) -> str:
        fid = fields.pop("id", None) or str(uuid.uuid4())
        self.files[fid] = Record(
            id=fid,
            user_id=user.id,
            filename=filename,
            path=fields.pop("path", f"/app/backend/data/uploads/{fid}_{filename}"),
            hash=fields.pop("hash", None),
            meta={"size": size, "content_type": fields.pop("content_type", "text/plain")},
            created_at=fields.pop("created_at", _now()),
            updated_at=_now(),
            **fields,
        )
        return fid

    def _chat_record(self, row) -> Record:
        return Record(
            **{c.name: getattr(row, c.name) for c in row.__table__.columns},
        )

    # ---- loading plugins ------------------------------------------------------------

    def load(
        self,
        folder: Path | str,
        id: str | None = None,
        valves: dict | None = None,
        active: bool = True,
        sources: dict[str, str] | None = None,
        content: str | None = None,
    ) -> LoadedPlugin:
        """Bundle a plugin folder as `owpp deploy` would, store it as a function, and load
        it as Open-WebUI does. `valves` are the stored valves (default: the manifest's).
        A `source:` plugin's files are fetched from git at the pinned commit, as the deploy
        does (once per run). `sources` stands in for them instead, so a test needs no network:
        {path inside the source's `path`: text}, e.g. {"tool.py": "class Tools: ..."}.
        For a plugin taken whole from git (`source: {plugin: true}`), they are the upstream
        folder's files, plugin.yaml included, and the upstream folder is what is bundled.
        Loading the same id again is an update."""
        folder = Path(folder)
        id = id or folder.name
        # From git at the pinned commit (once per session), or from the stand-ins.
        reader = session_sources() if sources is None else _stand_ins(folder, sources)
        plugin = reader.resolve(folder)
        manifest = plugin.manifest
        fn = manifest.get("function") or {}
        if content is None:
            content = bundle_function(plugin)
        if content is None:
            raise ValueError(f"{folder}: no function to load")
        if valves is None:
            valves = fn.get("valves") or {}
        types_ = function_type(content)
        frontmatter = parse_frontmatter(content)
        existing = self.functions.get(id)
        self.functions[id] = Record(
            id=id,
            user_id=self.admin.id,
            name=frontmatter.get("title") or id,
            type=types_[0] if types_ else "filter",
            content=content,
            meta=Record(description=frontmatter.get("description"), manifest=frontmatter),
            is_active=active if existing is None else existing.is_active,
            is_global=bool(fn.get("global")) if existing is None else existing.is_global,
            created_at=_now() if existing is None else existing.created_at,
            updated_at=_now(),
        )
        self.function_valves[id] = {**self.function_valves.get(id, {}), **valves}
        plugin = self.run(self._load_function(id))
        plugin.folder = folder
        return plugin

    async def _load_function(self, function_id: str) -> LoadedPlugin:
        row = self.functions[function_id]
        module = types.ModuleType(f"function_{function_id}_{_hex()}")
        module.__file__ = f"<function {function_id}>"
        sys.modules[module.__name__] = module
        exec(compile(row.content, module.__file__, "exec"), module.__dict__)
        cls = next(
            getattr(module, c) for c in ("Pipe", "Filter", "Action", "Event") if hasattr(module, c)
        )
        instance = cls()
        self._apply_valves(instance, self.function_valves.get(function_id))
        old = self.plugins.get(function_id)
        plugin = LoadedPlugin(self, function_id, old.folder if old else None, module, instance)
        self.plugins[function_id] = plugin
        return plugin

    @staticmethod
    def _apply_valves(instance, stored: dict | None) -> None:
        if hasattr(instance, "Valves"):
            instance.valves = instance.Valves(**(stored or {}))

    def tool(self, tool_id: str) -> LoadedTool:
        """The installed tool, loaded from its stored code as Open-WebUI does when a chat
        uses it (reloaded when the code changed), with its stored valves."""
        row = self.tools.get(tool_id)
        if row is None:
            raise KeyError(f"no tool {tool_id!r} is installed (installed: {sorted(self.tools)})")
        cached = self._tool_modules.get(tool_id)
        if cached is None or cached[0] != row.content:
            module = self.run(self._exec_tool(tool_id, row.content))
            cached = (row.content, LoadedTool(self, tool_id, module, module.Tools()))
            self._tool_modules[tool_id] = cached
        loaded = cached[1]
        self._apply_valves(loaded.instance, self.tool_valves.get(tool_id))
        return loaded

    async def _exec_tool(self, tool_id: str, content: str):
        module = types.ModuleType(f"tool_{tool_id}_{_hex()}")
        module.__file__ = f"<tool {tool_id}>"
        sys.modules[module.__name__] = module
        exec(compile(content, module.__file__, "exec"), module.__dict__)
        return module

    # ---- events ---------------------------------------------------------------------

    def emit(self, name: str, subject: str | dict | None = None, data: dict | None = None) -> None:
        """Send an Open-WebUI event: to every loaded Event function that is enabled (and to
        the subject of a `*_started` event, which is not yet), with its stored valves
        applied, then to the event sinks. `subject` is a function's id, or the subject itself
        for an event about something else (`{"type": "user", "id": ...}`)."""
        self.run(self._emit(name, subject, data))

    async def _emit(self, name: str, subject: str | dict | None, data: dict | None) -> None:
        if isinstance(subject, dict):
            subject_of = dict(subject)
            function_id = subject_of.get("id") if subject_of.get("type") == "function" else None
        else:
            subject_of = {"type": "function", "id": subject} if subject else None
            function_id = subject
        event = {
            "event": name,
            "subject": subject_of,
            "data": data or {},
            "timestamp": _now(),
        }
        for plugin in list(self.plugins.values()):
            row = self.functions.get(plugin.id)
            if row is None or not hasattr(plugin.instance, "event"):
                continue
            starting = name.endswith("_started") and function_id == plugin.id
            if not (row.is_active or starting):
                continue
            self._apply_valves(plugin.instance, self.function_valves.get(plugin.id))
            await plugin.instance.event(
                event,
                __event_name__=name,
                __id__=plugin.id,
                __app__=self.app,
                __request__=None,
            )
        for sink in list(self.event_sinks):
            await sink.handle_event(self.request(), event)

    def startup(self) -> None:
        """Open-WebUI finished starting."""
        self.emit("system.startup.completed")

    def enable(self, function_id: str) -> None:
        self.emit("function.enable_started", function_id)
        self.functions[function_id].is_active = True
        self.emit("function.enabled", function_id)

    def disable(self, function_id: str) -> None:
        self.emit("function.disable_started", function_id)
        self.functions[function_id].is_active = False
        self.emit("function.disabled", function_id)

    def set_valves(self, function_id: str, **valves) -> None:
        """An admin saved the function's valves."""
        self.function_valves[function_id] = {**self.function_valves.get(function_id, {}), **valves}
        plugin = self.plugins.get(function_id)
        if plugin is not None:
            self._apply_valves(plugin.instance, self.function_valves[function_id])
        self.emit("function.valves_updated", function_id)

    def update(self, function_id: str, folder: Path | str | None = None) -> LoadedPlugin:
        """A new version was deployed: bundle the folder again and reload the function."""
        folder = Path(folder or self.plugins[function_id].folder)
        plugin = self.load(folder, id=function_id)
        self.emit("function.updated", function_id)
        return plugin

    def delete(self, function_id: str) -> None:
        self.functions.pop(function_id, None)
        self.function_valves.pop(function_id, None)
        self.plugins.pop(function_id, None)
        self.emit("function.deleted", function_id)

    # ---- HTTP -----------------------------------------------------------------------

    def client(self, user: Record | None = None, **kwargs):
        """A Starlette TestClient for the app, signed in as `user` (a bearer token) or as
        nobody. kwargs go to TestClient (follow_redirects=False to see a redirect)."""
        from starlette.testclient import TestClient

        client = TestClient(self.app, **kwargs)
        if user is not None:
            client.headers["Authorization"] = f"Bearer {user.token}"
        return client

    def request(self, user: Record | None = None):
        """A request object such as Open-WebUI passes as `__request__`."""
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
            }
        )

    # ---- the open_webui modules -------------------------------------------------------

    def _modules(self) -> dict[str, types.ModuleType]:
        mock = self
        from fastapi import HTTPException
        from sqlalchemy.orm import Session

        def module(name: str, **attrs) -> types.ModuleType:
            # A name the mock does not implement still imports, as a stand-in (_MissingName).
            m = _MissingModule(name)
            m.__path__ = []  # a package, so the modules it does not have import as stand-ins
            m.__dict__.update(attrs)
            return m

        # models.functions
        class Functions:
            @staticmethod
            async def get_function_by_id(id):
                return mock.functions.get(id)

            @staticmethod
            async def get_functions(active_only=False, include_valves=False):
                return [f for f in mock.functions.values() if f.is_active or not active_only]

            @staticmethod
            async def get_functions_by_type(type, active_only=False):
                return [
                    f
                    for f in mock.functions.values()
                    if f.type == type and (f.is_active or not active_only)
                ]

            @staticmethod
            async def get_function_valves_by_id(id):
                return dict(mock.function_valves.get(id) or {})

            @staticmethod
            async def update_function_valves_by_id(id, valves):
                mock.function_valves[id] = dict(valves)
                return mock.functions.get(id)

        # models.tools
        class ToolMeta(Record):
            pass

        class ToolForm(Record):
            pass

        class Tools:
            @staticmethod
            async def get_tool_by_id(id):
                return mock.tools.get(id)

            @staticmethod
            async def get_tools():
                return list(mock.tools.values())

            @staticmethod
            async def insert_new_tool(user_id, form, specs, module=None):
                mock.tools[form.id] = Record(
                    id=form.id,
                    user_id=user_id,
                    name=form.name,
                    content=form.content,
                    specs=specs,
                    meta=form.meta,
                    access_grants=list(getattr(form, "access_grants", []) or []),
                    created_at=_now(),
                    updated_at=_now(),
                )
                return mock.tools[form.id]

            @staticmethod
            async def update_tool_by_id(id, updated, user_id=None, module=None):
                tool = mock.tools[id]
                for key, value in updated.items():
                    setattr(tool, key, ToolMeta(**value) if key == "meta" else value)
                tool.updated_at = _now()
                return tool

            @staticmethod
            async def get_tool_valves_by_id(id):
                return dict(mock.tool_valves[id]) if id in mock.tool_valves else None

            @staticmethod
            async def update_tool_valves_by_id(id, valves):
                mock.tool_valves[id] = dict(valves)

            @staticmethod
            async def delete_tool_by_id(id):
                mock._tool_modules.pop(id, None)
                return mock.tools.pop(id, None) is not None

        # models.skills
        class SkillMeta(Record):
            pass

        class SkillForm(Record):
            pass

        class Skills:
            @staticmethod
            async def get_skill_by_id(id):
                return mock.skills.get(id)

            @staticmethod
            async def insert_new_skill(user_id, form):
                mock.skills[form.id] = Record(
                    id=form.id,
                    user_id=user_id,
                    name=form.name,
                    description=form.description,
                    data={"files": list(form.files)},
                    meta=form.meta,
                    is_active=getattr(form, "is_active", True),
                    access_grants=list(getattr(form, "access_grants", []) or []),
                    version_id=_hex(),
                )
                return mock.skills[form.id]

            @staticmethod
            async def update_skill_by_id(id, data, user_id=None):
                skill = mock.skills[id]
                if data.get("expected_version_id") not in (None, skill.version_id):
                    raise ValueError("the skill changed since it was read")
                for key in ("name", "description"):
                    if key in data:
                        setattr(skill, key, data[key])
                if "files" in data:
                    skill.data = {**(skill.data or {}), "files": list(data["files"])}
                if "meta" in data:
                    skill.meta = SkillMeta(**data["meta"])
                skill.version_id = _hex()
                return skill

            @staticmethod
            async def delete_skill_by_id(id):
                return mock.skills.pop(id, None) is not None

        # models.chats
        class AccessGrants:
            """Grants live on the tool and skill records, as their `access_grants` lists."""

            @staticmethod
            async def set_access_grants(resource_type, resource_id, access_grants, db=None):
                table = {"tool": mock.tools, "skill": mock.skills}[resource_type]
                if resource_id in table:
                    table[resource_id].access_grants = [dict(g) for g in access_grants or []]
                return list(access_grants or [])

        class Chats:
            @staticmethod
            async def get_chat_by_id(id):
                return mock.chat(id)

            @staticmethod
            async def get_chats(skip=0, limit=50):
                with Session(mock.engine) as s:
                    rows = (
                        s.query(mock.Chat)
                        .order_by(mock.Chat.updated_at.desc(), mock.Chat.id)
                        .offset(skip)
                        .limit(limit)
                        .all()
                    )
                    return [mock._chat_record(r) for r in rows]

            @staticmethod
            async def get_chats_by_user_id(user_id, skip=0, limit=50):
                return [c for c in await Chats.get_chats(0, 10**9) if c.user_id == user_id][
                    skip : skip + limit
                ]

            @staticmethod
            async def has_chat_access(chat_id, user, permission="read"):
                chat = mock.chat(chat_id)
                if chat is None:
                    return False
                if chat.user_id == user.id:
                    return True
                granted = mock.chat_access.get((chat_id, user.id))
                return granted == "write" or (granted == "read" and permission == "read")

        class Notes:
            @staticmethod
            async def get_notes(skip=0, limit=50):
                return list(mock.notes.values())[skip : skip + limit]

        class Files:
            @staticmethod
            async def get_files():
                return list(mock.files.values())

            @staticmethod
            async def get_file_by_id(id):
                return mock.files.get(id)

        class Users:
            @staticmethod
            async def get_user_by_id(id):
                return mock.users.get(id)

            @staticmethod
            async def get_super_admin_user():
                return next((u for u in mock.users.values() if u.role == "admin"), None)

            @staticmethod
            async def get_users(filter=None, skip=0, limit=50):
                ids = (filter or {}).get("user_ids")
                users = [u for u in mock.users.values() if ids is None or u.id in ids]
                return {"users": users[skip : skip + limit], "total": len(users)}

        from pydantic import BaseModel as _BaseModel
        from pydantic import ConfigDict as _ConfigDict
        from pydantic import Field as _Field
        from pydantic import model_validator as _model_validator

        class ModelParams(_BaseModel):
            """v0.13.4: any inference parameter, plus model_controls (left out when empty)."""

            model_config = _ConfigDict(extra="allow")
            model_controls: dict = _Field(default_factory=dict, exclude_if=lambda value: not value)

        class ModelMeta(_BaseModel):
            """v0.13.4's fields, any others kept, and tags normalised to [{"name": ...}]."""

            model_config = _ConfigDict(extra="allow")
            profile_image_url: str | None = None
            background_image_url: str | None = None
            description: str | None = None
            i18n: dict | None = None
            capabilities: dict | None = None
            knowledge: list | None = None
            subagents: dict | None = None
            voice: dict | None = None
            voice_avatar: dict | None = None

            @_model_validator(mode="before")
            @classmethod
            def _tags(cls, data):
                if isinstance(data, dict) and "tags" in data:
                    tags = data["tags"] if isinstance(data["tags"], list) else []
                    names = [(t.get("name") if isinstance(t, dict) else t) for t in tags]
                    data = {
                        **data,
                        "tags": [
                            {"name": n.strip()} for n in names if isinstance(n, str) and n.strip()
                        ],
                    }
                return data

        class ModelForm(_BaseModel):
            model_config = _ConfigDict(extra="ignore")
            id: str
            base_model_id: str | None = None
            name: str
            meta: ModelMeta
            params: ModelParams
            access_grants: list[dict] | None = None
            is_active: bool = True

        def _model_row(form, user_id, created_at=None):
            return Record(
                id=form.id,
                user_id=user_id,
                base_model_id=form.base_model_id,
                name=form.name,
                meta=ModelMeta.model_validate(form.meta.model_dump()),
                params=ModelParams.model_validate(form.params.model_dump()),
                access_grants=[dict(g) for g in form.access_grants or []],
                is_active=form.is_active,
                created_at=created_at or _now(),
                updated_at=_now(),
            )

        class Models:
            @staticmethod
            async def get_all_models():
                return list(mock.models.values())

            @staticmethod
            async def get_model_by_id(id):
                return mock.models.get(id)

            @staticmethod
            async def insert_new_model(form_data, user_id):
                mock.models[form_data.id] = _model_row(form_data, user_id)
                return mock.models[form_data.id]

            @staticmethod
            async def update_model_by_id(id, model, user_id=None):
                current = mock.models.get(id)
                if current is None:
                    return None
                mock.models[id] = _model_row(model, user_id or current.user_id, current.created_at)
                return mock.models[id]

            @staticmethod
            async def delete_model_by_id(id):
                return mock.models.pop(id, None) is not None

        class Config:
            @staticmethod
            async def get(key, default=None):
                return mock.config.get(key, default)

            @staticmethod
            async def upsert(values):
                mock.config.update(values)

        @asynccontextmanager
        async def get_async_db_context(db=None):
            with Session(mock.engine) as session:
                yield _AsyncSession(session)

        # utils
        async def get_current_user(request, response=None, background_tasks=None, auth_token=None):
            token = getattr(auth_token, "credentials", None) or request.cookies.get("token")
            for user in mock.users.values():
                if token and token == user.token:
                    return user
            raise HTTPException(status_code=401, detail="Not authenticated")

        def decode_token(token):
            """A session token's claims ({"id": ...}), or None: Open-WebUI checks only the
            signature and the expiry here, without reading the database."""
            for user in mock.users.values():
                if token and token == user.token:
                    return {"id": user.id}
            return None

        # The chat pipeline, as far as a plugin asking a model needs it: no pipelines (their
        # inlet hands the request back), the task model as named, and a model that answers
        # `mock.model_reply` and keeps what it was asked in `mock.completions`.
        async def process_pipeline_inlet_filter(request, payload, user, models):
            return payload

        async def get_task_model_generation_config(task_model_id, models):
            return task_model_id, None

        def apply_task_model_params(payload, models, model_id, params):
            return {**payload, **(params or {})}

        async def generate_chat_completion(request, form_data, user=None, **kwargs):
            mock.completions.append(form_data)
            return {
                "model": form_data.get("model"),
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": mock.model_reply}}
                ],
            }

        def replace_imports(content):
            return content

        async def load_tool_module_by_id(tool_id, content=None):
            if content is None:
                content = mock.tools[tool_id].content
            module = await mock._exec_tool(tool_id, content)
            return module.Tools(), parse_frontmatter(content), {}

        async def load_function_module_by_id(function_id, content=None):
            row = mock.functions[function_id]
            if content is not None:
                row.content = content
            plugin = await mock._load_function(function_id)
            return plugin.instance, row.type, parse_frontmatter(row.content)

        def get_functions_cache(request):
            return {}

        async def get_function_module_from_cache(request, function_id, load_from_db=True):
            return await load_function_module_by_id(function_id)

        def get_tool_specs(module):
            return _tool_specs(module)

        class JSONCodec:
            dumps = staticmethod(json.dumps)
            loads = staticmethod(json.loads)

        async def emit(event, data=None, room=None, to=None, **kwargs):
            mock.emitted.append((event, data))

        sio = types.SimpleNamespace(emit=emit)

        packages = (
            "open_webui",
            "open_webui.models",
            "open_webui.utils",
            "open_webui.internal",
            "open_webui.routers",
            "open_webui.socket",
        )
        modules = {name: module(name, __path__=[]) for name in packages}
        modules.update(
            {
                "open_webui.main": module("open_webui.main", app=self.app),
                "open_webui.config": module(
                    "open_webui.config",
                    DATA_DIR=str(self.data_dir),
                    UPLOAD_DIR=str(self.data_dir / "uploads"),
                    CACHE_DIR=str(self.data_dir / "cache"),
                    STATIC_DIR=str(self.static_dir),
                    STORAGE_PROVIDER="",
                ),
                "open_webui.env": module(
                    "open_webui.env",
                    WEBUI_SECRET_KEY=self.secret_key,
                    DATA_DIR=str(self.data_dir),
                    FRONTEND_BUILD_DIR=str(self.data_dir / "build"),
                    STATIC_DIR=str(self.static_dir),
                    REDIS_KEY_PREFIX="open-webui",
                    REDIS_URL="",
                ),
                "open_webui.events": module("open_webui.events", EVENT_SINKS=self.event_sinks),
                "open_webui.internal.db": module(
                    "open_webui.internal.db", get_async_db_context=get_async_db_context
                ),
                "open_webui.models.functions": module(
                    "open_webui.models.functions", Functions=Functions
                ),
                "open_webui.models.tools": module(
                    "open_webui.models.tools", Tools=Tools, ToolForm=ToolForm, ToolMeta=ToolMeta
                ),
                "open_webui.models.skills": module(
                    "open_webui.models.skills",
                    Skills=Skills,
                    SkillForm=SkillForm,
                    SkillMeta=SkillMeta,
                ),
                "open_webui.models.chats": module(
                    "open_webui.models.chats", Chats=Chats, Chat=self.Chat, ChatFile=self.ChatFile
                ),
                "open_webui.models.notes": module("open_webui.models.notes", Notes=Notes),
                "open_webui.models.files": module("open_webui.models.files", Files=Files),
                "open_webui.models.users": module("open_webui.models.users", Users=Users),
                "open_webui.models.models": module(
                    "open_webui.models.models",
                    Models=Models,
                    ModelForm=ModelForm,
                    ModelMeta=ModelMeta,
                    ModelParams=ModelParams,
                ),
                "open_webui.models.config": module("open_webui.models.config", Config=Config),
                "open_webui.models.access_grants": module(
                    "open_webui.models.access_grants",
                    AccessGrants=AccessGrants,
                    PRINCIPAL_TYPE_USER="user",
                    PRINCIPAL_TYPE_GROUP="group",
                    PRINCIPAL_TYPE_ANYONE="anyone",
                    WILDCARD_PRINCIPAL_ID="*",
                ),
                "open_webui.routers.pipelines": module(
                    "open_webui.routers.pipelines",
                    process_pipeline_inlet_filter=process_pipeline_inlet_filter,
                ),
                "open_webui.routers.tasks": module(
                    "open_webui.routers.tasks",
                    get_task_model_generation_config=get_task_model_generation_config,
                    apply_task_model_params=apply_task_model_params,
                ),
                "open_webui.utils.chat": module(
                    "open_webui.utils.chat", generate_chat_completion=generate_chat_completion
                ),
                "open_webui.utils.auth": module(
                    "open_webui.utils.auth",
                    get_current_user=get_current_user,
                    decode_token=decode_token,
                ),
                "open_webui.utils.plugin": module(
                    "open_webui.utils.plugin",
                    replace_imports=replace_imports,
                    load_tool_module_by_id=load_tool_module_by_id,
                    load_function_module_by_id=load_function_module_by_id,
                    get_functions_cache=get_functions_cache,
                    get_function_module_from_cache=get_function_module_from_cache,
                ),
                "open_webui.utils.tools": module(
                    "open_webui.utils.tools", get_tool_specs=get_tool_specs
                ),
                "open_webui.utils.misc": module(
                    "open_webui.utils.misc",
                    get_last_user_message_item=get_last_user_message_item,
                ),
                "open_webui.utils.json_codec": module(
                    "open_webui.utils.json_codec", JSONCodec=JSONCodec
                ),
                "open_webui.socket.main": module("open_webui.socket.main", sio=sio),
            }
        )
        for name, mod in modules.items():  # `import open_webui.models.chats` walks the parents
            parent, _, child = name.rpartition(".")
            if parent in modules:
                setattr(modules[parent], child, mod)
        return modules
