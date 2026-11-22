"""A plugin folder from a description of it: what `owpp create` (the wizard) and `owpp init` write.

`PluginSpec` says what the plugin is; `render()` turns it into the files of a plugin folder, and
`write_plugin()` writes them. It is a scaffold: every hook, handler and tool method is a stub to
fill in. Nothing here asks questions, so every combination can be tested: each one bundles,
compiles, passes `owpp check --strict` and passes its own generated tests.

A plugin is one of three kinds:

- **code written here**: a function of one of Open-WebUI's types (`filter`, `action`, `event`,
  `pipe`), with an optional tool, skills, a page and libraries;
- an **installer**: no function code at all, only a tool and/or skills, which the generated
  parent function installs when it is enabled and removes when it is disabled (the protocol's
  deployment mechanism for tools and skills);
- **from git**: a `source:` repository pinned to a commit, from which it takes the function
  (`upstream`) or, as an installer, just a tool and skills.

What the generated code uses follows Open-WebUI's plugin docs
(https://docs.openwebui.com/features/extensibility/) and this repository's conventions
(docs/authoring.md): the header in plugin.yaml, valves with descriptions, `@on` handlers, the
libraries rather than copies of them, HTML in files rather than in Python strings.
"""

from __future__ import annotations

import ast
import datetime as _dt
import json
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

from .bundle import VALID_ID, VALID_SKILL_ID
from .errors import OwppError
from .events import problem_with
from .imports import add_lib_imports
from .libraries import exports
from .protocol import VERSION as PROTOCOL_VERSION
from .sources import GIT_URL, SHA40, TRACK
from .versioning import changelog_text

CLASS = {"event": "Event", "filter": "Filter", "action": "Action", "pipe": "Pipe"}
CODE_TYPES = tuple(CLASS)
# installer: the function is generated, and only installs the tool and skills.
# upstream: the function is taken from the source repository, verbatim.
TYPES = (*CODE_TYPES, "installer", "upstream")
FILTER_HOOKS = ("inlet", "request", "stream", "outlet")
ACCESS = ("user", "admin", "public")
PAGES = ("", "static", "rendered")
VALID_SKILL = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")  # Open-WebUI's skill name standard
VALID_SUB_ID = re.compile(r"[a-z_][a-z0-9_]*")  # an action button, a pipe model, a method
VERSION = re.compile(r"\d+\.\d+\.\d+")
VALVES_DOCS = "https://docs.openwebui.com/features/extensibility/plugin/development/valves"
# Events that are about one function: a handler for them takes only this function's (own=True).
_OWN_PREFIXES = ("function.",)
# Startup, enable, update and saved valves: when an Event function (re)mounts its routes.
MOUNT_EVENTS = (
    "system.startup.completed",
    "function.enable_started",
    "function.updated",
    "function.valves_updated",
)


@dataclass
class ToolSpec:
    """A tool. Written here: `methods` are the stubs in tool.py. From git: `file` is its path in
    the source repository."""

    id: str
    title: str = ""
    description: str = ""
    methods: list[str] = field(default_factory=list)
    public: bool = True
    rich_ui: bool = False  # a method that returns an HTMLResponse, shown in the chat
    chat_data: bool = False
    file: str = ""

    def __post_init__(self) -> None:
        self.title = self.title or title_of(self.id)


@dataclass
class SkillSpec:
    """A skill. Written here: skills/<id>/SKILL.md. From git: `path` in the source repository,
    a SKILL.md (`is_dir` False) or a folder holding one."""

    id: str
    description: str = ""
    public: bool = True
    path: str = ""
    is_dir: bool = True


@dataclass
class SourceSpec:
    """A git repository, pinned to a full commit SHA, and the folder in it the paths are under."""

    git: str
    ref: str
    path: str = ""
    function_file: str = ""  # the function itself, taken verbatim (type "upstream")
    branch: str = (
        ""  # what `owpp pull` follows: a branch, or a tag, or neither (the default branch)
    )
    tag: str = ""


@dataclass
class PluginSpec:
    id: str
    type: str = "event"
    title: str = ""
    author: str = "you"
    version: str = "0.1.0"
    license: str = "MIT"
    description: str = ""
    required_open_webui_version: str = ""
    icon_url: str = ""
    requirements: str = ""
    global_: bool | None = None  # plugin.yaml's `global:` (filters, actions, upstream)
    priority: bool = False  # filters and actions: a `priority` valve (lower runs first)
    # filter
    hooks: list[str] = field(default_factory=lambda: ["inlet", "outlet"])
    toggle: bool = False
    file_handler: bool = False
    # action
    buttons: list[tuple[str, str]] = field(default_factory=list)  # (id, name): several buttons
    rich_ui: bool = False  # the action returns an HTMLResponse, shown above the message
    # pipe
    models: list[tuple[str, str]] = field(default_factory=list)  # (id, name); empty: one
    stream: bool = False
    # event
    events: list[str] = field(default_factory=lambda: ["system.startup.completed"])
    sync: bool = False
    sync_minutes: int = 60
    # parts and libraries
    tool: ToolSpec | None = None
    skills: list[SkillSpec] = field(default_factory=list)
    source: SourceSpec | None = None
    page: str = ""  # "", "static" (static/index.html) or "rendered" (templates/page.html)
    page_access: str = "user"
    chat_data: bool = False
    config: bool = False
    assets: bool = False
    live_reload: bool = False

    def __post_init__(self) -> None:
        self.title = self.title or title_of(self.id)
        if self.type == "installer" and not self.description:
            self.description = f"Installs {self.title}; disabling this function removes it."
        self.description = self.description or f"What {self.title} does, on one line."

    @property
    def cls(self) -> str:
        return CLASS[self.type]

    @property
    def has_code(self) -> bool:
        """A function.py written here."""
        return self.type in CODE_TYPES

    @property
    def env_prefix(self) -> str:
        return self.id.upper().lstrip("_")

    @property
    def pipe_models(self) -> list[tuple[str, str]]:
        return self.models or [("default", self.title)]

    @property
    def has_enable(self) -> bool:
        """The ENABLE valve: the sync mixin adds its own."""
        return not (self.type == "event" and self.sync)


def title_of(plugin_id: str) -> str:
    return re.sub(r"\b\w", lambda m: m.group().upper(), plugin_id.replace("_", " ").strip())


# ---- checking a spec ------------------------------------------------------------


def _one_line(label: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise OwppError(f"{label} must fit on one line (it goes into the header)")


def _check_repo_path(label: str, value: str) -> None:
    parts = [p for p in value.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise OwppError(f"{label} must be a path inside the repository, without . or ..")


def validate(spec: PluginSpec) -> None:
    """Refuse what would not bundle, or would not work in Open-WebUI. Raises OwppError."""
    if not VALID_ID.fullmatch(spec.id):
        raise OwppError(
            f'"{spec.id}" is not a valid id: lowercase letters, digits and _ (no hyphens)'
        )
    if spec.type not in TYPES:
        raise OwppError(f"the type must be one of {', '.join(TYPES)}")
    for key in ("title", "author", "version", "license", "description"):
        _one_line(key, getattr(spec, key))
    for key in ("required_open_webui_version", "icon_url", "requirements"):
        _one_line(key, getattr(spec, key))
    if spec.global_ is not None and spec.type not in ("filter", "action", "upstream"):
        raise OwppError("global applies to filters and actions only")
    if spec.toggle and (spec.type != "filter" or spec.global_):
        raise OwppError("a toggle is a filter that each user switches on, so it is never global")
    if not spec.has_code and (
        spec.page or spec.chat_data or spec.config or spec.assets or spec.live_reload
    ):
        raise OwppError(
            "a page, chat_data, config.yaml and assets/ need a function written here, "
            "not a generated or upstream one"
        )
    if spec.assets and spec.type != "event":
        raise OwppError("assets/ is published by an Event function (class Event(PluginAssets))")
    if spec.live_reload and not spec.assets:
        raise OwppError("live_reload is for a plugin with assets/")
    if spec.page not in PAGES:
        raise OwppError(f"page must be one of {', '.join(p or '(none)' for p in PAGES)}")
    if spec.page_access not in ACCESS:
        raise OwppError(f"page access must be one of {', '.join(ACCESS)}")
    for h in spec.hooks:
        if h not in FILTER_HOOKS:
            raise OwppError(f"unknown filter hook {h} (known: {', '.join(FILTER_HOOKS)})")
    if spec.type == "filter" and not spec.hooks:
        raise OwppError("a filter needs at least one of inlet, request, stream, outlet")
    for name in spec.events:
        problem = problem_with(name)
        if problem:
            raise OwppError(problem)
    for label, items in (("button", spec.buttons), ("model", spec.models)):
        seen = set()
        for sub_id, _ in items:
            if not VALID_SUB_ID.fullmatch(sub_id):
                raise OwppError(f'"{sub_id}" is not a valid {label} id: a-z, 0-9 and _, no dots')
            if sub_id in seen:
                raise OwppError(f"the {label} id {sub_id} is used twice")
            seen.add(sub_id)
    _validate_source(spec)
    if spec.type == "installer" and not (spec.tool or spec.skills):
        raise OwppError("an installer installs a tool or skills: add at least one")
    if spec.tool:
        _validate_tool(spec, spec.tool)
    seen = set()
    for s in spec.skills:
        if spec.source:
            if not VALID_SKILL_ID.fullmatch(s.id):
                raise OwppError(f'"{s.id}" is not a valid skill id: a-z, 0-9, _ and -')
            _check_repo_path(f"the path of skill {s.id}", s.path)
        elif not VALID_SKILL.fullmatch(s.id):
            raise OwppError(
                f'"{s.id}" is not a valid skill name: lowercase letters, digits and hyphens, '
                "at most 64"
            )
        if s.id in seen:
            raise OwppError(f"the skill {s.id} is declared twice")
        seen.add(s.id)
        if len(s.description) > 1024:
            raise OwppError(f"the description of skill {s.id} is over 1024 characters")


def _validate_source(spec: PluginSpec) -> None:
    src = spec.source
    if spec.type == "upstream" and not (src and src.function_file):
        raise OwppError("an upstream function needs a source repository and its function file")
    if not src:
        return
    if spec.type not in ("installer", "upstream"):
        raise OwppError("a plugin from git is an installer or takes its function from the repo")
    if src.function_file and spec.type != "upstream":
        raise OwppError("with the function taken from the repository, the type is upstream")
    if not GIT_URL.fullmatch(src.git):
        raise OwppError("the repository must be an https://, ssh:// or user@host:path git URL")
    if not SHA40.fullmatch(src.ref):
        raise OwppError("the commit must be a full 40-character SHA (a branch or tag can move)")
    if src.branch and src.tag:
        raise OwppError("follow a branch or a tag, not both")
    for kind, name in (("branch", src.branch), ("tag", src.tag)):
        if name and not TRACK.fullmatch(name):
            raise OwppError(f"{kind} must be a branch or tag name")
    if src.path:
        _check_repo_path("the folder in the repository", src.path)
    if src.function_file:
        _check_repo_path("the function file", src.function_file)
    if spec.tool and not spec.tool.file:
        raise OwppError("a tool from the repository needs its file")


def _validate_tool(spec: PluginSpec, tool: ToolSpec) -> None:
    if not VALID_ID.fullmatch(tool.id):
        raise OwppError(f'"{tool.id}" is not a valid tool id')
    _one_line("the tool's title", tool.title)
    _one_line("the tool's description", tool.description)
    if tool.file:
        if not spec.source:
            raise OwppError("a tool file is taken from a source repository")
        _check_repo_path("the tool file", tool.file)
        return
    if not tool.methods and not tool.rich_ui:
        raise OwppError("a tool needs at least one method")
    seen = set()
    for m in tool.methods:
        if not VALID_SUB_ID.fullmatch(m):
            raise OwppError(f'"{m}" is not a valid method name (a-z, 0-9, _)')
        if m in seen:
            raise OwppError(f"the tool method {m} is declared twice")
        seen.add(m)


# ---- code -------------------------------------------------------------------------


def _py(value: object) -> str:
    """A Python literal (JSON's are Python's for str, numbers and lists of them)."""
    if isinstance(value, bool):
        return "True" if value else "False"
    return json.dumps(value, ensure_ascii=False)


def _valve(name: str, annotation: str, default: object, description: str) -> list[str]:
    return [
        f"        {name}: {annotation} = Field(",
        f"            default={_py(default)},",
        f"            description={_py(description)},",
        "        )",
    ]


def _valves_class(spec: PluginSpec) -> list[str]:
    lines = [
        "    class Valves(BaseModel):",
        "        # Settings an admin changes under Admin Panel > Functions, each with a description:",
        '        #   API_URL: str = Field(default="", description="Where the API is.")',
        f"        # Dropdowns, sliders and masked fields: {VALVES_DOCS}",
    ]
    if spec.type == "event" and spec.sync:
        lines.append("        # The sync adds ENABLE and SYNC_INTERVAL_MINUTES itself.")
    if spec.priority:
        lines += _valve(
            "priority",
            "int",
            0,
            "Order among the filters and actions of a model: lower runs first.",
        )
    if spec.has_enable:
        lines += _valve("ENABLE", "bool", True, f"Turn {spec.title} on or off.")
    if not (spec.priority or spec.has_enable):
        lines.append("        pass")
    if spec.type in ("filter", "action", "pipe"):
        lines += [
            "",
            "    class UserValves(BaseModel):",
            "        # Settings each user sets in a chat (Controls > Valves); they arrive as",
            '        # __user__["valves"].',
            "        pass",
        ]
    return lines


def _status(text: str, done: bool, indent: str) -> list[str]:
    data = f'{{"description": {text}, "done": {_py(done)}}}'
    return [
        f"{indent}if __event_emitter__:",
        f'{indent}    await __event_emitter__({{"type": "status", "data": {data}}})',
    ]


def _filter_body(spec: PluginSpec) -> list[str]:
    out: list[str] = []
    off = "        if not self.valves.ENABLE:\n            return {0}"
    if "inlet" in spec.hooks:
        out += [
            "    async def inlet(self, body: dict, __user__: dict = None) -> dict:",
            '        """Once per user turn, before the request is sent to the model. Change',
            '        body["messages"] here. Always return body: returning None breaks the chain."""',
            off.format("body"),
        ]
        if spec.file_handler:
            out.append(
                '        # file_handler: body["files"] is yours to handle; Open-WebUI drops it after inlet.'
            )
        out += ["        return body", ""]
    if "request" in spec.hooks:
        out += [
            "    async def request(self, body: dict, __user__: dict = None) -> dict:",
            '        """Before every call to the model, each step of a tool loop included, so it',
            '        must give the same result when it runs twice. Needs a recent Open-WebUI."""',
            off.format("body"),
            "        return body",
            "",
        ]
    if "stream" in spec.hooks:
        out += [
            "    async def stream(self, event: dict) -> dict:",
            '        """Each chunk of a streamed reply, as it arrives. Return the chunk."""',
            off.format("event"),
            "        return event",
            "",
        ]
    if "outlet" in spec.hooks:
        out += [
            "    async def outlet(self, body: dict, __user__: dict = None) -> dict:",
            '        """The finished reply, before it is saved. Return body."""',
            off.format("body"),
            "        return body",
            "",
        ]
    return out


def _action_body(spec: PluginSpec) -> list[str]:
    out = [
        "    async def action(",
        "        self,",
        "        body: dict,",
        "        __user__: dict = None,",
        "        __event_emitter__=None,",
        "        __event_call__=None,",
        "        __id__: str = None,",
        "    ):",
        '        """The user pressed the button under a message. body["id"] is that message, and',
        '        body["messages"] the chat. To change the message, return',
        '        {"messages": [{"id": body["id"], "content": "..."}]}.',
        '        __event_call__ asks the user: {"type": "confirmation" or "input", "data": {...}}."""',
        "        if not self.valves.ENABLE:",
        "            return None",
        *_status('f"{TITLE}: working"', False, "        "),
    ]
    if spec.buttons:
        out.append("        # __id__ is the button that was pressed (an id from `actions`).")
        for i, (sub, name) in enumerate(spec.buttons):
            out += [
                f"        {'if' if i == 0 else 'elif'} __id__ == {_py(sub)}:",
                f'            log.info("%s: {name}", TITLE)',
            ]
    out += _status('f"{TITLE}: done"', True, "        ")
    if spec.rich_ui:
        out += [
            "        # Shown above the message, in a sandboxed frame (templates/embed.html).",
            '        return HTMLResponse(EMBED.replace("__TITLE__", TITLE), headers={"Content-Disposition": "inline"})',
        ]
    else:
        out.append("        return None")
    return [*out, ""]


def _models_literal(spec: PluginSpec) -> str:
    return ", ".join(
        f'{{"id": {_py(i)}, "name": {"TITLE" if n == spec.title else _py(n)}}}'
        for i, n in spec.pipe_models
    )


def _pipe_body(spec: PluginSpec) -> list[str]:
    out = [
        "    def pipes(self):",
        '        """The models this pipe adds. Each appears as "<function id>.<id>"."""',
        f"        return [{_models_literal(spec)}]",
        "",
        "    async def pipe(self, body: dict, __user__: dict = None, __event_emitter__=None):",
        '        """Answers a chat sent to one of the models. body["model"] says which, and',
        '        body["messages"] holds the chat. Return a str, or a generator of chunks."""',
        '        answer = "Hello from " + TITLE',
    ]
    if spec.stream:
        out += ['        if body.get("stream"):', "            return self._chunks(answer)"]
    out += ["        return answer", ""]
    if spec.stream:
        out += [
            "    async def _chunks(self, text: str):",
            '        """The answer, a word at a time."""',
            '        for i, word in enumerate(text.split(" ")):',
            '            yield word if i == 0 else " " + word',
            "",
        ]
    return out


def _event_body(spec: PluginSpec) -> list[str]:
    out: list[str] = []
    if spec.sync:
        out += [
            "    async def sync(self):",
            '        """Runs on startup, when the function is enabled or its valves are saved,',
            "        and every SYNC_INTERVAL_MINUTES. Mark what it writes with plugin_function_id()",
            '        and touch only that (plugin_sync_markers())."""',
            '        log.info("%s: sync", TITLE)',
            "",
        ]
    for name in spec.events:
        own = ", own=True" if name.startswith(_OWN_PREFIXES) else ""
        method = "on_" + re.sub(r"\W", "_", name)
        out += [
            f"    @on({_py(name)}{own})",
            f"    async def {method}(self, event):",
            f'        """{name}: what {spec.title} does then."""',
            "        if not self.valves.ENABLE:",
            "            return",
            f'        log.info("%s: {name}", TITLE)',
            "",
        ]
    if spec.page == "rendered":
        events = ", ".join(_py(e) for e in MOUNT_EVENTS)
        out += [
            f"    @on({events}, own=True)",
            "    async def mount(self, app):",
            '        """Mount (or mount again) the page."""',
            "        _mount(app)",
            "",
        ]
    if spec.assets:
        out += [
            "    def asset_vars(self) -> dict:",
            '        """Fills __NAME__ placeholders in assets/loader.js and assets/custom.css."""',
            '        return {"TITLE": TITLE}',
            "",
        ]
    return out


def _event_bases(spec: PluginSpec) -> list[str]:
    bases = []
    if spec.assets:
        bases.append("PluginAssets")
    if spec.sync:
        bases.append("PluginScheduledSync")
    return bases or ["PluginEvents"]


def render_function(spec: PluginSpec) -> str:
    imports = ["import logging", ""]
    if spec.page == "rendered":
        imports.append("from fastapi import APIRouter")
    if spec.page == "rendered" or spec.rich_ui:
        imports.append("from fastapi.responses import HTMLResponse")
    imports.append("from pydantic import BaseModel, Field")
    lines = [
        f"# {spec.title}: an Open-WebUI {spec.type} function. The header is generated from plugin.yaml.",
        "",
        *imports,
        "",
        "log = logging.getLogger(__name__)",
        f"TITLE = {_py(spec.title)}",
    ]
    if spec.page == "rendered":
        lines += [
            f"PREFIX = {_py('/' + spec.id)}  # where the page is served",
            'PAGE = plugin_template_text("page.html")  # templates/page.html, filled in per request',
        ]
    if spec.rich_ui and spec.type == "action":
        lines.append('EMBED = plugin_template_text("embed.html")  # templates/embed.html')
    if spec.chat_data:
        lines.append(
            f"CHAT_KEY = {_py(spec.id)}  # plugin_chat_read(chat_id, CHAT_KEY), plugin_chat_write(chat_id, value, CHAT_KEY)"
        )
    lines.append("")
    if spec.config:
        lines += [
            "",
            "def _settings() -> dict:",
            '    """config.yaml laid over these defaults."""',
            '    return plugin_config({"greeting": "Hello"})',
            "",
        ]
    if spec.page == "rendered":
        marker = {"user": "user: PluginUser", "admin": "user: PluginAdmin", "public": ""}[
            spec.page_access
        ]
        who = {
            "user": "any signed-in user",
            "admin": "admins only",
            "public": "anyone, signed in or not",
        }[spec.page_access]
        access = ', access="public"' if spec.page_access == "public" else ""
        lines += [
            "",
            f"async def _page({marker}) -> HTMLResponse:",
            f'    """The page at PREFIX/, for {who}."""',
            '    return HTMLResponse(PAGE.replace("__TITLE__", TITLE))',
            "",
            "",
            "def _mount(app) -> None:",
            '    """Serve the page. Mounting again replaces the earlier mount."""',
            "    if app is None:",
            "        return",
            "    router = APIRouter()",
            '    router.add_api_route(PREFIX + "/", _page, methods=["GET"], include_in_schema=False)',
            f'    plugin_mount(app, router, PREFIX, name="page"{access})',
            "",
        ]
    bases = f"({', '.join(_event_bases(spec))})" if spec.type == "event" else ""
    lines += ["", f"class {spec.cls}{bases}:"]
    if spec.type == "action" and spec.buttons:
        buttons = ", ".join(f'{{"id": {_py(i)}, "name": {_py(n)}}}' for i, n in spec.buttons)
        lines += [
            "    # One button per entry, under each message.",
            f"    actions = [{buttons}]",
            "",
        ]
    lines += [*_valves_class(spec), ""]
    if spec.type != "event":  # an events class makes self.valves itself
        lines += ["    def __init__(self):", "        self.valves = self.Valves()"]
        if spec.toggle:
            lines.append(
                "        self.toggle = True  # a switch in the chat's + menu; inlet runs only when it is on"
            )
            if spec.icon_url:
                lines.append(f"        self.icon = {_py(spec.icon_url)}")
        if spec.file_handler:
            lines.append(
                "        self.file_handler = True  # this filter handles the attached files itself"
            )
        if spec.page == "rendered":
            lines.append("        _mount(plugin_app())  # the page, once Open-WebUI's app exists")
        lines.append("")
    lines += {
        "filter": _filter_body,
        "action": _action_body,
        "pipe": _pipe_body,
        "event": _event_body,
    }[spec.type](spec)
    while lines and lines[-1] == "":
        lines.pop()
    text = "\n".join(lines) + "\n"
    if not any(isinstance(n, ast.Name) and n.id == "Field" for n in ast.walk(ast.parse(text))):
        text = text.replace(
            "from pydantic import BaseModel, Field\n", "from pydantic import BaseModel\n"
        )
    return add_lib_imports(text, exports())


def render_tool(spec: PluginSpec) -> str:
    tool = spec.tool
    assert tool is not None
    imports = []
    if tool.rich_ui:
        imports.append("from fastapi.responses import HTMLResponse")
    imports.append("from pydantic import BaseModel")
    lines = [
        f"# {tool.title}: the tool the model calls. Its header is generated from plugin.yaml (tool:).",
        "# Every method without a leading _ is offered to the model: its type hints and docstring",
        "# (the text, then one :param line per parameter) are the spec the model reads.",
        "",
        *imports,
        "",
    ]
    if tool.rich_ui:
        lines += ['EMBED = plugin_template_text("tool.html")  # templates/tool.html', ""]
    lines += [
        "",
        "class Tools:",
        "    class Valves(BaseModel):",
        "        # Set by an admin, or the tool's owner, under Workspace > Tools.",
        "        pass",
        "",
        "    def __init__(self):",
        "        self.valves = self.Valves()",
        "",
    ]
    for m in tool.methods:
        lines += [
            f"    async def {m}(self, query: str, __user__: dict = None, __event_emitter__=None) -> dict:",
            '        """',
            f"        What {m} does, and when the model should call it.",
            "",
            "        :param query: Describe query for the model.",
            '        """',
            *_status(_py(f"{m}: working"), False, "        "),
            '        result = {"query": query}',
            *_status(_py(f"{m}: done"), True, "        "),
            "        return result",
            "",
        ]
    if tool.rich_ui:
        lines += [
            f"    async def show_{tool.id}(self, __user__: dict = None) -> HTMLResponse:",
            '        """',
            f"        Show {tool.title} to the user, as a page inside the chat.",
            '        """',
            "        # A sandboxed frame at the tool call. Return (HTMLResponse, text) to tell the",
            "        # model something about what it shows.",
            '        return HTMLResponse(EMBED, headers={"Content-Disposition": "inline"})',
            "",
        ]
    while lines[-1] == "":
        lines.pop()
    return add_lib_imports("\n".join(lines) + "\n", exports())


def _yaml(value: str) -> str:
    """A header value: plain text, unless YAML would read it as something else."""
    plain = re.fullmatch(r"[A-Za-z0-9][^#:{}\[\],&*!|>'\"%@`]*", value) and not value.endswith(" ")
    looks_typed = value.lower() in ("true", "false", "null", "~") or re.fullmatch(
        r"[-+0-9.eExXoO_]+", value
    )
    if VERSION.fullmatch(value):  # 0.1.0 is text to YAML already
        looks_typed = False
    return value if plain and not looks_typed else json.dumps(value, ensure_ascii=False)


def render_manifest(spec: PluginSpec) -> str:
    out = [
        "# Manifest (docs/plugin-format.md). The function: keys become the docstring header.",
        f'protocol: "{PROTOCOL_VERSION}"',
    ]
    src = spec.source
    if src:
        out += [
            "source:",
            f"  git: {_yaml(src.git)}",
            f"  ref: {src.ref}",
            *([f"  branch: {src.branch}"] if src.branch else []),
            *([f"  tag: {src.tag}"] if src.tag else []),
            f"  path: {_yaml(src.path) if src.path else _py('')}",
        ]
    out.append("function:")
    if spec.type == "upstream":
        assert src is not None
        out.append(f"  file: {_yaml(src.function_file)} # taken verbatim, its header included")
    else:
        header = [
            ("title", spec.title),
            ("author", spec.author),
            ("version", spec.version),
            ("required_open_webui_version", spec.required_open_webui_version),
            ("license", spec.license),
            ("icon_url", spec.icon_url),
            ("requirements", spec.requirements),
            ("description", spec.description),
        ]
        out += [f"  {k}: {_yaml(v)}" for k, v in header if v]
    if spec.type == "installer":
        out.append("  global: true # Open-WebUI loads it at startup, so it installs the rest")
    elif spec.global_ is not None or spec.toggle:  # a toggle is switched on by each user
        out.append(f"  global: {_py(bool(spec.global_)).lower()}")
    elif spec.type in ("filter", "action", "upstream"):
        out.append(
            "  # global: true   # active and global on every deploy; false: never (a user toggle)"
        )
    if spec.tool:
        t = spec.tool
        out += ["tool:", f"  id: {t.id}"]
        if t.file:
            out.append(f"  file: {_yaml(t.file)}")
        else:
            out.append(f"  title: {_yaml(t.title)}")
            if t.description:
                out.append(f"  description: {_yaml(t.description)}")
        tool_include = [
            n
            for n, on in (("chat_data", t.chat_data), ("templates", t.rich_ui and not t.file))
            if on
        ]
        if tool_include:
            out.append(f"  include: [{', '.join(tool_include)}]")
        if t.public:
            out.append(
                "  access: public # every signed-in user may use it; later UI changes are kept"
            )
    if src and spec.skills:
        out.append("skills:")
        for s in spec.skills:
            out += [f"  {s.id}:", f"    {'dir' if s.is_dir else 'file'}: {_yaml(s.path)}"]
            if s.public:
                out.append("    access: public")
    if spec.has_code:
        include = []
        if spec.type == "event" and _event_bases(spec) == ["PluginEvents"]:
            include.append("events")
        if spec.page == "rendered":
            include.append("routes")
        if spec.chat_data:
            include.append("chat_data")
        if spec.live_reload:
            include.append("live_reload")
        if include:
            out.append(f"include: [{', '.join(include)}]")
        else:
            out.append(
                "# include: [routes]   # libraries: core, routes, jobs, events, chat_data, shared_assets, live_reload"
            )
    if spec.sync:
        out += [
            "jobs:",
            f"  sync_every_minutes: ${{{spec.env_prefix}_SYNC_MINUTES:-{spec.sync_minutes}}} # 0: only on startup, enable and saved valves",
        ]
    if spec.page == "static" and spec.page_access != "user":
        out += ["static:", f"  access: {spec.page_access}"]
    parts = []
    if spec.type == "installer" and not src:
        parts.append("no function.py: the generated function installs the tool and skills")
    if spec.page == "static":
        parts.append(f"static/ is served at /{spec.id}/")
    if spec.page == "rendered" or (spec.rich_ui and spec.type == "action"):
        parts.append("templates/ is rendered by the function")
    if spec.config:
        parts.append("config.yaml is read with plugin_config()")
    if spec.assets:
        parts.append("assets/ is published by class Event(PluginAssets)")
    if spec.skills and not src:
        parts.append("skills/ are installed with the function")
    if parts:
        out.append("# " + "; ".join(parts) + ".")
    return "\n".join(out) + "\n"


def _test(name: str, args: str, what: str, by_hand: str, body: list[str]) -> list[str]:
    return [
        "",
        "",
        f"def {name}({args}):",
        f'    """{what}',
        "",
        f"    By hand: {by_hand}",
        '    """',
        *body,
    ]


def render_tests(spec: PluginSpec) -> str:
    out = [
        f'"""{spec.title} against a mock Open-WebUI: `owpp test {spec.id}` (docs/testing.md).',
        "",
        "`plugin` is this folder, bundled as the deploy would and loaded into `owui`, the mock.",
    ]
    if spec.source:
        out += [
            "Its files are fetched from the pinned commit, so these tests need the network; to run",
            'them offline, load it with stand-ins: owui.load(plugin_dir, sources={"tool.py": "..."}).',
        ]
    out += ['"""', "", f"TITLE = {_py(spec.title)}"]
    if spec.has_code:
        out += _test(
            "test_it_loads_with_its_default_valves",
            "plugin",
            "It loads, and its valves start at their defaults.",
            "install it, then open its valves under Admin Panel > Functions: ENABLE is on.",
            ["    assert plugin.valves.ENABLE is True"],
        )
        out += _type_tests(spec)
    elif spec.type == "installer":
        out += _test(
            "test_it_is_a_global_filter_that_only_installs_things",
            "plugin",
            "It is a global filter, whose only job is to install the tool and skills.",
            f"Admin Panel > Functions shows {spec.title} as a filter with Global on.",
            ['    assert plugin.type == "filter" and plugin.row.is_global'],
        )
    else:
        out += _test(
            "test_the_upstream_function_loads",
            "plugin",
            "The function taken from the repository loads, as one of Open-WebUI's types.",
            f"after deploy, Admin Panel > Functions lists {spec.title}.",
            ['    assert plugin.type in ("filter", "action", "event", "pipe")'],
        )
    if spec.tool:
        t = spec.tool
        body = [f"    assert {_py(t.id)} in owui.tools"]
        if not t.file:
            names = sorted(t.methods + ([f"show_{t.id}"] if t.rich_ui else []))
            body.append(
                f'    assert sorted(s["name"] for s in owui.tool({_py(t.id)}).specs) == {_py(names)}'
            )
        out += _test(
            "test_it_installs_its_tool",
            "owui, plugin",
            f"Enabling the function installs the {t.title} tool.",
            f"enable the function, then find {t.title} under Workspace > Tools.",
            body,
        )
        for m in t.methods:
            out += _test(
                f"test_the_tool_answers_{m}",
                "owui, plugin",
                f"The model can call {m}, and gets an answer back.",
                f"with {t.title} on in a chat, ask for something that needs {m}.",
                [
                    '    user = owui.add_user("Ada")',
                    f'    assert owui.tool({_py(t.id)}).call({_py(m)}, query="x", user=user) == {{"query": "x"}}',
                ],
            )
        if t.rich_ui:
            out += _test(
                "test_the_tool_shows_a_page_in_the_chat",
                "owui, plugin",
                "Its page is returned inline, for Open-WebUI to show at the tool call.",
                f"ask the model to show {t.title}: a page appears in the chat.",
                [
                    '    user = owui.add_user("Ada")',
                    f"    page = owui.tool({_py(t.id)}).call({_py('show_' + t.id)}, user=user)",
                    '    assert page.headers["content-disposition"] == "inline"',
                ],
            )
    if spec.skills:
        ids = sorted(s.id for s in spec.skills)
        out += _test(
            "test_it_installs_its_skills",
            "owui, plugin",
            "Enabling the function installs its skills.",
            "enable the function, then find them under Workspace > Skills.",
            [f"    assert {_py(ids)} == sorted(s for s in owui.skills if s in {_py(ids)})"],
        )
    if spec.page:
        out += _page_test(spec)
    if spec.config:
        out += _test(
            "test_it_reads_its_config",
            "plugin",
            "It reads config.yaml, with the defaults for what the file leaves out.",
            "not repeatable on a live Open-WebUI; compare config.yaml with what it does.",
            ['    assert plugin.module._settings()["greeting"] == "Hello"'],
        )
    return "\n".join(out) + "\n"


def _page_test(spec: PluginSpec) -> list[str]:
    url = f"/{spec.id}/"
    body = ["    owui.startup()"] if spec.type == "event" else []
    if spec.page_access == "public":
        body.append(f'    assert owui.client().get("{url}").status_code == 200')
        by_hand = f"open {url} in a private window: the page loads."
    elif spec.page_access == "admin":
        body += [
            f'    assert owui.client(owui.add_user("Ada")).get("{url}").status_code == 403',
            f'    assert owui.client(owui.admin).get("{url}").status_code == 200',
        ]
        by_hand = f"open {url} as a user (403), then as an admin (the page)."
    else:
        body += [
            f'    assert owui.client().get("{url}").status_code == 401',
            f'    assert owui.client(owui.add_user("Ada")).get("{url}").status_code == 200',
        ]
        by_hand = f"open {url} signed in: the page loads."
    who = {"user": "signed-in users", "admin": "admins", "public": "anyone"}[spec.page_access]
    return _test(
        "test_it_serves_its_page",
        "owui, plugin",
        f"Its page is served at {url}, to {who}.",
        by_hand,
        body,
    )


def _type_tests(spec: PluginSpec) -> list[str]:
    if spec.type == "event":
        body = ["    owui.startup()  # every enabled Event function gets system.startup.completed"]
        if spec.sync:
            body.append(f"    assert plugin.valves.SYNC_INTERVAL_MINUTES == {spec.sync_minutes}")
        return _test(
            "test_it_starts_with_open_webui",
            "owui, plugin",
            "It runs its startup work when Open-WebUI starts.",
            "restart Open-WebUI and look for the function's startup lines in the log.",
            body,
        )
    if spec.type == "filter":
        body = [
            '    user = owui.add_user("Ada")',
            '    body = {"messages": [{"role": "user", "content": "hi"}]}',
        ]
        for hook in spec.hooks:
            if hook in ("inlet", "outlet"):
                body.append(f"    assert plugin.{hook}(body, user=user) == body")
            elif hook == "request":
                body.append('    assert plugin.call("request", body, user=user) == body')
            else:
                body += [
                    '    chunk = {"choices": [{"delta": {"content": "hi"}}]}',
                    '    assert plugin.call("stream", chunk) == chunk',
                ]
        return _test(
            "test_a_chat_passes_through_unchanged",
            "owui, plugin",
            "A chat request and its reply pass through the filter unchanged.",
            'turn the filter on for a model, send "hi": the answer is what it would be without it.',
            body,
        )
    if spec.type == "action":
        body = ['    user = owui.add_user("Ada")']
        if spec.buttons:
            body.append(
                f'    assert [a["id"] for a in plugin.instance.actions] == {_py([b for b, _ in spec.buttons])}'
            )
        if spec.rich_ui:
            body += [
                '    page = plugin.call("action", {"messages": []}, user=user)',
                '    assert page.headers["content-disposition"] == "inline"',
                "    assert TITLE in page.body.decode()",
            ]
        else:
            body.append('    assert plugin.call("action", {"messages": []}, user=user) is None')
        return _test(
            "test_the_action_runs",
            "owui, plugin",
            "The action runs on a message without failing.",
            "under a reply, click the action's button: no error toast appears.",
            body,
        )
    body = [
        '    user = owui.add_user("Ada")',
        f'    assert plugin.call("pipes") == [{_models_literal(spec)}]',
        '    assert plugin.call("pipe", {"messages": []}, user=user) == "Hello from " + TITLE',
    ]
    if spec.stream:
        body += [
            '    chunks = plugin.call("pipe", {"messages": [], "stream": True}, user=user)',
            "",
            "    async def read():",
            '        return "".join([c async for c in chunks])',
            "",
            '    assert owui.run(read()) == "Hello from " + TITLE',
        ]
    return _test(
        "test_it_answers",
        "owui, plugin",
        "It offers its models, and they answer.",
        'pick one of its models in a new chat and send anything: it answers "Hello from <title>".',
        body,
    )


def render_skill(spec: PluginSpec, skill: SkillSpec) -> str:
    description = skill.description or f"What the {skill.id} skill is for, and when to use it."
    title = title_of(skill.id.replace("-", "_"))
    access = "access: public\n" if skill.public else ""
    sections = {
        "When to Use": "The requests this skill is for, and the ones it is not.",
        "Prerequisites": f"What must be set up first (for example, the {spec.title} tool turned on).",
        "How to Run": "The tool calls or commands, in order.",
        "Quick Reference": "The few facts needed most often.",
        "Procedure": "1. The first step.\n2. The next one.",
        "Pitfalls": "What goes wrong, and how to tell.",
        "Verification": "How to confirm it worked.",
    }
    body = "\n\n".join(f"## {k}\n\n{v}" for k, v in sections.items())
    return (
        f"---\nname: {skill.id}\ndescription: {json.dumps(description, ensure_ascii=False)}\n{access}---\n\n"
        f"# {title}\n\n{body}\n"
    )


def render_readme(spec: PluginSpec) -> str:
    sections = [f"# {spec.title}", "", spec.description]
    parts = []
    if spec.tool:
        parts.append(f"the **{spec.tool.title}** tool")
    if spec.skills:
        parts.append("the skill(s) " + ", ".join(f"`{s.id}`" for s in spec.skills))
    if parts:
        sections += [
            "",
            f"Enabling the function installs {' and '.join(parts)}; disabling it removes them.",
        ]
    src = spec.source
    if src:
        sections += [
            "",
            "## Source",
            "",
            f"From {src.git}{f' (`{src.path}`)' if src.path else ''}, pinned to commit `{src.ref}`.",
            f"To upgrade: `owpp pull {spec.id}` moves `ref` in plugin.yaml to the latest commit of "
            + (
                f"branch `{src.branch}`"
                if src.branch
                else f"tag `{src.tag}`"
                if src.tag
                else "the default branch"
            )
            + " and lists the files that changed.",
            "Review the upstream diff before committing it: this code runs with admin rights in Open-WebUI.",
        ]
    settings = []
    if spec.has_code:
        names = (["priority"] if spec.priority else []) + ["ENABLE"]
        if spec.sync:
            names.append("SYNC_INTERVAL_MINUTES")
            settings.append(
                f"Environment (on the Open-WebUI container): `{spec.env_prefix}_SYNC_MINUTES`, the default sync interval."
            )
        settings.insert(0, f"Valves: {', '.join(f'`{v}`' for v in names)}.")
    elif spec.type == "installer":
        settings.append(
            "Valves: `INSTALL_TOOLS` and `INSTALL_SKILLS` (off removes that part), `TOOL_VALVES` "
            "(valves to set on the tool). See docs/runtime.md."
        )
    if spec.config:
        settings.append(
            f"`config.yaml`: `greeting` (environment: `{spec.env_prefix}_GREETING`, default Hello)."
        )
    if spec.toggle:
        settings.append(
            "A toggle: each user turns it on in a chat's + menu, so it is never made global."
        )
    if settings:
        sections += ["", *settings]
    live = {
        "event": "Restart Open-WebUI (or enable the function) and look for its lines in the log.",
        "filter": "Turn it on for a model (or make it global) and send a message.",
        "action": "Under a reply, press its button.",
        "pipe": "Pick its model in a new chat and send a message.",
        "installer": "Enable the function: Workspace lists what it installs; disable it: they are gone.",
        "upstream": "Use it as its upstream documentation describes.",
    }[spec.type]
    kind = {
        "installer": "filter (generated: it only installs the rest)",
        "upstream": "the one in the upstream file",
    }
    sections += [
        "",
        "## Test",
        "",
        f"- `owpp check {spec.id}` bundles it exactly as the deploy does, compiles it and lists undefined names.",
        f"- `owpp test {spec.id}` runs `tests/` against a mock Open-WebUI (docs/testing.md).",
        f"- On a live Open-WebUI: {live}",
        "",
        "## Deploy",
        "",
        f"- Function type: **{kind.get(spec.type, spec.type)}**.",
        f"- `owpp deploy --only {spec.id} --dry-run`, then without `--dry-run`.",
    ]
    if spec.type != "upstream":
        sections.append(
            f"- A change is a new version: `owpp version {spec.id} patch` (and say what changed in "
            "CHANGELOG.md); `owpp check --since origin/main` fails on a change without one."
        )
    if spec.type == "filter" and spec.global_ is None and not spec.toggle:
        sections.append(
            "- A new filter is made global on its first deploy; set `global:` in plugin.yaml to change that."
        )
    if spec.type == "filter" and spec.toggle:
        sections.append(
            "- After deploy: attach it to the models that should offer the toggle (Workspace > Models > Filters)."
        )
    if spec.page:
        sections.append(f"- Its page is at `/{spec.id}/` on the Open-WebUI host.")
    return "\n".join(sections) + "\n"


_PAGE_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>__TITLE__</title>
  </head>
  <body>
    <h1>__TITLE__</h1>
    <p>{note}</p>
  </body>
</html>
"""


def render(spec: PluginSpec, today: str | None = None) -> dict[str, str]:
    """The plugin folder's files, {path: text}. `today` dates the first CHANGELOG.md entry."""
    validate(spec)
    files = {"plugin.yaml": render_manifest(spec)}
    if spec.type != "upstream":  # an upstream function's versions are the upstream's
        files["CHANGELOG.md"] = changelog_text(
            spec.title, spec.version, ["First version."], today or _dt.date.today().isoformat()
        )
    if spec.has_code:
        files["function.py"] = render_function(spec)
    files["README.md"] = render_readme(spec)
    files[f"tests/test_{spec.id}.py"] = render_tests(spec)
    if spec.tool and not spec.tool.file:
        files["tool.py"] = render_tool(spec)
        if spec.tool.rich_ui:
            files["templates/tool.html"] = _PAGE_HTML.replace("__TITLE__", spec.tool.title).format(
                note="Shown in the chat by the tool, which reads it with plugin_template_text()."
            )
    if not spec.source:
        for s in spec.skills:
            files[f"skills/{s.id}/SKILL.md"] = render_skill(spec, s)
    if spec.page == "static":
        files["static/index.html"] = _PAGE_HTML.replace("__TITLE__", spec.title).format(
            note="Served as it is; add scripts and styles beside it in static/."
        )
    if spec.page == "rendered":
        files["templates/page.html"] = _PAGE_HTML.format(
            note="Rendered by the function for each request; never served as it is."
        )
    if spec.rich_ui and spec.type == "action":
        files["templates/embed.html"] = _PAGE_HTML.format(note="Shown above the message.")
    if spec.config:
        files["config.yaml"] = (
            "# Settings that ship with the plugin, read with plugin_config() (docs/libraries.md#config).\n"
            "# A value may be ${NAME:-default}, read from the Open-WebUI container's environment;\n"
            "# a secret goes in that way, never as text.\n"
            f"greeting: ${{{spec.env_prefix}_GREETING:-Hello}}\n"
        )
    if spec.assets:
        files["assets/loader.js"] = (
            "// This plugin's part of /static/loader.js, run on every page. Write only the body:\n"
            "// it is wrapped in its own function with a try/catch. __TITLE__ comes from asset_vars().\n"
            'console.debug("__TITLE__ loaded");\n'
        )
        files["assets/custom.css"] = (
            "/* This plugin's part of /static/custom.css, on every page. */\n"
        )
    return files


def spec_from_data(data: object, plugin_id: str = "") -> PluginSpec:
    """A PluginSpec from plain data (a YAML or JSON document): the keys of PluginSpec, with
    `tool`, `skills` and `source` as mappings of ToolSpec, SkillSpec and SourceSpec, and
    `buttons` and `models` as lists of {id, name}. `global` may be written for `global_`.
    Unknown keys are refused, so a typo is not silently a default."""
    if not isinstance(data, dict):
        raise OwppError("a plugin spec is a mapping (see docs/creating.md#from-a-spec)")
    data = dict(data)
    if "global" in data:
        data["global_"] = data.pop("global")
    if plugin_id:
        data["id"] = plugin_id
    if not data.get("id"):
        raise OwppError("the spec needs an id (or give it on the command line)")

    def build(cls, value, label):
        if not isinstance(value, dict):
            raise OwppError(f"{label} must be a mapping")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(value) - known)
        if unknown:
            shown = ", ".join(sorted(k.rstrip("_") for k in known))
            raise OwppError(f"{label}: unknown key {', '.join(unknown)} (known: {shown})")
        return cls(**value)

    def pairs(value, label):
        out = []
        for item in value or []:
            if isinstance(item, dict) and set(item) <= {"id", "name"} and "id" in item:
                out.append((str(item["id"]), str(item.get("name") or title_of(str(item["id"])))))
            elif isinstance(item, str):
                out.append((item, title_of(item)))
            else:
                raise OwppError(f"{label}: each entry is an id or {{id, name}}")
        return out

    if data.get("tool") is not None:
        data["tool"] = build(ToolSpec, data["tool"], "tool")
    if data.get("source") is not None:
        data["source"] = build(SourceSpec, data["source"], "source")
    data["skills"] = [
        build(SkillSpec, s if isinstance(s, dict) else {"id": s}, "skills")
        for s in data.get("skills") or []
    ]
    for key in ("buttons", "models"):
        if key in data:
            data[key] = pairs(data[key], key)
    return build(PluginSpec, data, "the spec")


def write_plugin(directory: Path | str, spec: PluginSpec, today: str | None = None) -> Path:
    """Write the plugin folder `<directory>/<id>/`. Refuses a folder that exists."""
    files = render(spec, today)
    folder = Path(directory) / spec.id
    if folder.exists():
        raise OwppError(f"{folder} already exists")
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return folder
