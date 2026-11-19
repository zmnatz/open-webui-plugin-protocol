"""A plugin folder from a description of it: what `owpp create` (the wizard) and `owpp init` write.

`PluginSpec` says what the plugin is (its header, function type, valves, tool, skills, pages and
libraries); `render()` turns it into the files of a plugin folder, and `write_plugin()` writes them.
Nothing here asks questions, so every combination can be tested: each one bundles, compiles,
passes `owpp check --strict` and passes its own generated tests.

What the generated code uses follows Open-WebUI's plugin docs
(https://docs.openwebui.com/features/extensibility/) and this repository's conventions
(docs/authoring.md): the header in plugin.yaml, valves with descriptions, `@on` handlers, the
libraries rather than copies of them, HTML in files rather than in Python strings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bundle import VALID_ID
from .errors import OwppError
from .events import problem_with

CLASS = {"event": "Event", "filter": "Filter", "action": "Action", "pipe": "Pipe"}
TYPES = tuple(CLASS)
FILTER_HOOKS = ("inlet", "request", "stream", "outlet")
VALVE_KINDS = ("str", "int", "float", "bool", "password", "select", "multiselect", "range")
PARAM_TYPES = ("str", "int", "float", "bool", "list[str]")
ACCESS = ("user", "admin", "public")
PAGES = ("", "static", "rendered")
VALID_VALVE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
VALID_SKILL = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")  # Open-WebUI's skill name standard
VALID_SUB_ID = re.compile(r"[a-z_][a-z0-9_]*")  # an action button or a pipe model: no dots
VERSION = re.compile(r"\d+\.\d+\.\d+")
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
class Valve:
    """One setting. `kind` is how Open-WebUI shows it: a text box (str, int, float), a switch
    (bool), a masked text box (password), a dropdown (select), checkboxes (multiselect) or a
    slider (range, between `minimum` and `maximum`)."""

    name: str
    kind: str = "str"
    default: Any = None
    description: str = ""
    options: list[str] = field(default_factory=list)
    minimum: float = 0
    maximum: float = 1
    step: float = 0.1


@dataclass
class ToolMethod:
    """A method the model may call: its description and its parameters, (name, type)."""

    name: str
    description: str = ""
    params: list[tuple[str, str]] = field(default_factory=lambda: [("query", "str")])


@dataclass
class ToolSpec:
    id: str
    title: str = ""
    description: str = ""
    methods: list[ToolMethod] = field(default_factory=list)
    public: bool = True
    rich_ui: bool = False  # a method that returns an HTMLResponse, shown in the chat
    chat_data: bool = False


@dataclass
class SkillSpec:
    id: str
    description: str = ""
    public: bool = True


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
    global_: bool | None = None  # filters and actions: plugin.yaml's `global:`
    valves: list[Valve] = field(default_factory=list)
    user_valves: list[Valve] = field(default_factory=list)
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
    page: str = ""  # "", "static" (static/index.html) or "rendered" (templates/page.html)
    page_access: str = "user"
    chat_data: bool = False
    config: bool = False
    assets: bool = False
    live_reload: bool = False

    def __post_init__(self) -> None:
        self.title = self.title or title_of(self.id)
        self.description = self.description or f"What {self.title} does, on one line."

    @property
    def cls(self) -> str:
        return CLASS[self.type]

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


def validate(spec: PluginSpec) -> None:
    """Refuse what would not bundle, or would not work in Open-WebUI. Raises OwppError."""
    if not VALID_ID.fullmatch(spec.id):
        raise OwppError(
            f'"{spec.id}" is not a valid id: lowercase letters, digits and _ (no hyphens)'
        )
    if spec.type not in CLASS:
        raise OwppError(f"the type must be one of {', '.join(CLASS)}")
    for key in ("title", "author", "version", "license", "description"):
        _one_line(key, getattr(spec, key))
    for key in ("required_open_webui_version", "icon_url", "requirements"):
        _one_line(key, getattr(spec, key))
    if spec.global_ is not None and spec.type not in ("filter", "action"):
        raise OwppError("global applies to filters and actions only")
    if spec.toggle and (spec.type != "filter" or spec.global_):
        raise OwppError("a toggle is a filter that each user switches on, so it is never global")
    if spec.type == "event" and spec.user_valves:
        raise OwppError("an Event function has no user valves (it runs without a user)")
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
    names = set()
    for v in [*spec.valves, *spec.user_valves]:
        _check_valve(v)
    for v in spec.valves:
        if v.name in names:
            raise OwppError(f"the valve {v.name} is declared twice")
        names.add(v.name)
    reserved = {"ENABLE", "priority"} | ({"SYNC_INTERVAL_MINUTES"} if spec.sync else set())
    clash = names & reserved
    if clash:
        raise OwppError(f"{', '.join(sorted(clash))} is added by the wizard; pick another name")
    for label, items in (("button", spec.buttons), ("model", spec.models)):
        seen = set()
        for sub_id, _ in items:
            if not VALID_SUB_ID.fullmatch(sub_id):
                raise OwppError(f'"{sub_id}" is not a valid {label} id: a-z, 0-9 and _, no dots')
            if sub_id in seen:
                raise OwppError(f"the {label} id {sub_id} is used twice")
            seen.add(sub_id)
    if spec.tool:
        if not VALID_ID.fullmatch(spec.tool.id):
            raise OwppError(f'"{spec.tool.id}" is not a valid tool id')
        if not spec.tool.methods and not spec.tool.rich_ui:
            raise OwppError("a tool needs at least one method")
        seen = set()
        for m in spec.tool.methods:
            if not VALID_SUB_ID.fullmatch(m.name):
                raise OwppError(f'"{m.name}" is not a valid method name (a-z, 0-9, _)')
            if m.name in seen:
                raise OwppError(f"the tool method {m.name} is declared twice")
            seen.add(m.name)
            for p, t in m.params:
                if not VALID_SUB_ID.fullmatch(p):
                    raise OwppError(f'"{p}" is not a valid parameter name')
                if t not in PARAM_TYPES:
                    raise OwppError(f"parameter types are {', '.join(PARAM_TYPES)}, not {t}")
    seen = set()
    for s in spec.skills:
        if not VALID_SKILL.fullmatch(s.id):
            raise OwppError(
                f'"{s.id}" is not a valid skill name: lowercase letters, digits and hyphens, '
                "at most 64"
            )
        if s.id in seen:
            raise OwppError(f"the skill {s.id} is declared twice")
        seen.add(s.id)
        if len(s.description) > 1024:
            raise OwppError(f"the description of skill {s.id} is over 1024 characters")


def _check_valve(v: Valve) -> None:
    if not VALID_VALVE.fullmatch(v.name):
        raise OwppError(f'"{v.name}" is not a valid valve name')
    if v.kind not in VALVE_KINDS:
        raise OwppError(f"valve kinds are {', '.join(VALVE_KINDS)}, not {v.kind}")
    if v.kind in ("select", "multiselect") and not v.options:
        raise OwppError(f"the valve {v.name} needs options")
    if v.kind == "range" and not v.minimum < v.maximum:
        raise OwppError(f"the valve {v.name} needs a minimum below its maximum")


def parse_default(kind: str, text: str, options: list[str] | None = None) -> Any:
    """A valve's default from what someone typed, as the valve's type."""
    text = text.strip()
    if kind == "bool":
        if text.lower() in ("", "true", "yes", "y", "on", "1"):
            return True
        if text.lower() in ("false", "no", "n", "off", "0"):
            return False
        raise OwppError(f"{text!r} is not true or false")
    if kind == "int":
        try:
            return int(text or 0)
        except ValueError:
            raise OwppError(f"{text!r} is not a whole number") from None
    if kind in ("float", "range"):
        try:
            return float(text or 0)
        except ValueError:
            raise OwppError(f"{text!r} is not a number") from None
    if kind == "select":
        if text and options and text not in options:
            raise OwppError(f"{text!r} is not one of {', '.join(options)}")
        return text or (options[0] if options else "")
    if kind == "multiselect":
        chosen = [s.strip() for s in text.split(",") if s.strip()]
        bad = [c for c in chosen if options and c not in options]
        if bad:
            raise OwppError(f"{', '.join(bad)} is not one of {', '.join(options or [])}")
        return chosen
    return text


# ---- code -------------------------------------------------------------------------


def _py(value: Any) -> str:
    """A Python literal (JSON's are Python's for str, numbers and lists of them)."""
    if isinstance(value, bool):
        return "True" if value else "False"
    return json.dumps(value, ensure_ascii=False)


def _valve_default(v: Valve) -> Any:
    if v.default is not None:
        return v.default
    return {
        "str": "",
        "password": "",
        "int": 0,
        "float": 0.0,
        "bool": False,
        "select": v.options[0] if v.options else "",
        "multiselect": [],
        "range": v.minimum,
    }[v.kind]


def _valve_lines(v: Valve, indent: str) -> list[str]:
    default = _valve_default(v)
    description = v.description or f"What {v.name} changes."
    annotation = {
        "str": "str",
        "password": "str",
        "int": "int",
        "float": "float",
        "bool": "bool",
        "select": "Literal[" + ", ".join(_py(o) for o in v.options) + "]",
        "multiselect": "list[str]",
        "range": "float",
    }[v.kind]
    args = [f"default={_py(default)}"]
    if v.kind == "range":
        args += [f"ge={_py(v.minimum)}", f"le={_py(v.maximum)}"]
    args.append(f"description={_py(description)}")
    if v.kind == "password":  # masked in the UI only; ENABLE_VALVE_ENCRYPTION encrypts it at rest
        args.append('json_schema_extra={"input": {"type": "password"}}')
    elif v.kind == "multiselect":
        args.append(
            'json_schema_extra={"input": {"type": "multiselect", "options": '
            + _py(v.options)
            + "}}"
        )
    elif v.kind == "range":
        args.append(f'json_schema_extra={{"input": {{"type": "range", "step": {_py(v.step)}}}}}')
    inner = indent + "    "
    return (
        [f"{indent}{v.name}: {annotation} = Field("]
        + [f"{inner}{a}," for a in args]
        + [f"{indent})"]
    )


def _valves_class(name: str, valves: list[Valve], indent: str, comment: str) -> list[str]:
    lines = [f"{indent}class {name}(BaseModel):", f"{indent}    # {comment}"]
    if not valves:
        return [*lines, f"{indent}    pass"]
    for v in valves:
        lines += _valve_lines(v, indent + "    ")
    return lines


def _function_valves(spec: PluginSpec) -> list[Valve]:
    valves = []
    if spec.priority:
        valves.append(
            Valve(
                "priority",
                "int",
                0,
                "Order among the filters and actions of a model: lower runs first.",
            )
        )
    if spec.has_enable:
        valves.append(Valve("ENABLE", "bool", True, f"Turn {spec.title} on or off."))
    return valves + spec.valves


def _uses_literal(valves: list[Valve]) -> bool:
    return any(v.kind == "select" for v in valves)


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
        if spec.user_valves:
            out.append(
                '        user_valves = (__user__ or {}).get("valves")  # this user\'s UserValves'
            )
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


def _pipe_body(spec: PluginSpec) -> list[str]:
    models = ", ".join(
        f'{{"id": {_py(i)}, "name": {"TITLE" if n == spec.title else _py(n)}}}'
        for i, n in spec.pipe_models
    )
    out = [
        "    def pipes(self):",
        '        """The models this pipe adds. Each appears as "<function id>.<id>"."""',
        f"        return [{models}]",
        "",
        "    async def pipe(self, body: dict, __user__: dict = None, __event_emitter__=None):",
        '        """Answers a chat sent to one of the models. body["model"] says which, and',
        '        body["messages"] holds the chat. Return a str, or a generator of chunks."""',
        '        answer = "Hello from " + TITLE',
    ]
    if spec.stream:
        out += [
            '        if body.get("stream"):',
            "            return self._chunks(answer)",
        ]
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
        ]
        out += ["        if not self.valves.ENABLE:", "            return"]
        out += [f'        log.info("%s: {name}", TITLE)', ""]
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
    valves = _function_valves(spec)
    imports = ["import logging"]
    if _uses_literal(valves + spec.user_valves):
        imports.append("from typing import Literal")
    imports.append("")
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
    comment = (
        "Set by an admin under Admin Panel > Functions > the gear."
        if not (spec.type == "event" and spec.sync)
        else "Set by an admin. The sync adds ENABLE and SYNC_INTERVAL_MINUTES itself."
    )
    lines += _valves_class("Valves", valves, "    ", comment)
    if spec.user_valves:
        lines += [""] + _valves_class(
            "UserValves",
            spec.user_valves,
            "    ",
            'Each user sets these in a chat: Controls > Valves. They arrive as __user__["valves"].',
        )
    lines.append("")
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
    return "\n".join(lines) + "\n"


_SAMPLE = {"str": '"x"', "int": "1", "float": "1.5", "bool": "True", "list[str]": '["x"]'}


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
        lines += ['EMBED = r"""{{file:embed.html}}"""  # embed.html, put here when bundled', ""]
    lines += [
        "",
        "class Tools:",
        *_valves_class(
            "Valves", [], "    ", "Set by an admin, or the tool's owner, under Workspace > Tools."
        ),
        "",
        "    def __init__(self):",
        "        self.valves = self.Valves()",
        "",
    ]
    for m in tool.methods:
        params = "".join(f", {p}: {t}" for p, t in m.params)
        result = "{" + ", ".join(f"{_py(p)}: {p}" for p, _ in m.params) + "}"
        lines += [
            f"    async def {m.name}(self{params}, __user__: dict = None, __event_emitter__=None) -> dict:",
            '        """',
            f"        {m.description or f'What {m.name} does, and when the model should call it.'}",
            "",
            *[f"        :param {p}: Describe {p} for the model." for p, _ in m.params],
            '        """',
            *_status(_py(f"{m.name}: working"), False, "        "),
            f"        result = {result}",
            *_status(_py(f"{m.name}: done"), True, "        "),
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
    return "\n".join(lines) + "\n"


def render_manifest(spec: PluginSpec) -> str:
    out = [
        "# Manifest (docs/plugin-format.md). The function: keys become the docstring header.",
        "function:",
    ]
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
    if spec.global_ is not None or spec.toggle:  # a toggle is switched on by each user
        out.append(f"  global: {_py(bool(spec.global_)).lower()}")
    elif spec.type in ("filter", "action"):
        out.append(
            "  # global: true   # active and global on every deploy; false: never (a user toggle)"
        )
    if spec.tool:
        t = spec.tool
        out += ["tool:", f"  id: {t.id}", f"  title: {_yaml(t.title)}"]
        if t.description:
            out.append(f"  description: {_yaml(t.description)}")
        if t.chat_data:
            out.append("  include: [chat_data]")
        if t.public:
            out.append(
                "  access: public # every signed-in user may use it; later UI changes are kept"
            )
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
    if spec.page == "static":
        parts.append(f"static/ is served at /{spec.id}/")
    if spec.page == "rendered" or (spec.rich_ui and spec.type == "action"):
        parts.append("templates/ is rendered by the function")
    if spec.config:
        parts.append("config.yaml is read with plugin_config()")
    if spec.assets:
        parts.append("assets/ is published by class Event(PluginAssets)")
    if spec.skills:
        parts.append("skills/ are installed with the function")
    if parts:
        out.append("# " + "; ".join(parts) + ".")
    return "\n".join(out) + "\n"


def _yaml(value: str) -> str:
    """A header value: plain text, unless YAML would read it as something else."""
    plain = re.fullmatch(r"[A-Za-z0-9][^#:{}\[\],&*!|>'\"%@`]*", value) and not value.endswith(" ")
    looks_typed = value.lower() in ("true", "false", "null", "~") or re.fullmatch(
        r"[-+0-9.eExXoO_]+", value
    )
    if VERSION.fullmatch(value):  # 0.1.0 is text to YAML already
        looks_typed = False
    return value if plain and not looks_typed else json.dumps(value, ensure_ascii=False)


def render_tests(spec: PluginSpec) -> str:
    out = [
        f'"""{spec.title} against a mock Open-WebUI: `owpp test {spec.id}` (docs/testing.md).',
        "",
        '`plugin` is this folder, bundled as the deploy would and loaded into `owui`, the mock."""',
        "",
        f"TITLE = {_py(spec.title)}",
        "",
        "",
        "def test_it_loads_with_its_default_valves(plugin):",
        '    """It loads, and its valves start at their defaults.',
        "",
        "    By hand: install it, then open its valves under Admin Panel > Functions: ENABLE is on.",
        '    """',
        "    assert plugin.valves.ENABLE is True",
    ]
    for v in spec.valves:
        out.append(f"    assert plugin.valves.{v.name} == {_py(_valve_default(v))}")
    out += ["", ""]
    out += _type_tests(spec)
    if spec.tool:
        t = spec.tool
        names = sorted([m.name for m in t.methods] + ([f"show_{t.id}"] if t.rich_ui else []))
        out += [
            "",
            "",
            "def test_it_installs_its_tool(owui, plugin):",
            f'    """Enabling the function installs the {t.title} tool, with what the model is told.',
            "",
            f"    By hand: enable the function, then find {t.title} under Workspace > Tools.",
            '    """',
            f"    tool = owui.tool({_py(t.id)})",
            f'    assert sorted(s["name"] for s in tool.specs) == {_py(names)}',
        ]
        user_line = '    user = owui.add_user("Ada")'
        for m in t.methods:
            args = ", ".join(f"{p}={_SAMPLE[ty]}" for p, ty in m.params)
            expected = "{" + ", ".join(f"{_py(p)}: {_SAMPLE[ty]}" for p, ty in m.params) + "}"
            out += [
                "",
                "",
                f"def test_the_tool_answers_{m.name}(owui, plugin):",
                f'    """The model can call {m.name}, and gets an answer back.',
                "",
                f"    By hand: with {t.title} on in a chat, ask for something that needs {m.name}.",
                '    """',
                user_line,
                f"    result = owui.tool({_py(t.id)}).call({_py(m.name)}{', ' + args if args else ''}, user=user)",
                f"    assert result == {expected}",
            ]
        if t.rich_ui:
            out += [
                "",
                "",
                "def test_the_tool_shows_a_page_in_the_chat(owui, plugin):",
                '    """Its page is returned inline, for Open-WebUI to show at the tool call.',
                "",
                f"    By hand: ask the model to show {t.title}: a page appears in the chat.",
                '    """',
                user_line,
                f"    page = owui.tool({_py(t.id)}).call({_py('show_' + t.id)}, user=user)",
                '    assert page.headers["content-disposition"] == "inline"',
            ]
    if spec.skills:
        ids = sorted(s.id for s in spec.skills)
        out += [
            "",
            "",
            "def test_it_installs_its_skills(owui, plugin):",
            '    """Enabling the function installs its skills.',
            "",
            "    By hand: enable the function, then find them under Workspace > Skills.",
            '    """',
            f"    assert {_py(ids)} == sorted(s for s in owui.skills if s in {_py(ids)})",
        ]
    if spec.page:
        url = f"/{spec.id}/"
        start = "    owui.startup()\n" if spec.type == "event" else ""
        if spec.page_access == "public":
            check = f'    assert owui.client().get("{url}").status_code == 200'
            by_hand = f"open {url} in a private window: the page loads"
        elif spec.page_access == "admin":
            check = (
                f'    assert owui.client(owui.add_user("Ada")).get("{url}").status_code == 403\n'
                f'    assert owui.client(owui.admin).get("{url}").status_code == 200'
            )
            by_hand = f"open {url} as a user (403), then as an admin (the page)"
        else:
            check = (
                f'    assert owui.client().get("{url}").status_code == 401\n'
                f'    assert owui.client(owui.add_user("Ada")).get("{url}").status_code == 200'
            )
            by_hand = f"open {url} signed in: the page loads"
        out += [
            "",
            "",
            "def test_it_serves_its_page(owui, plugin):",
            f'    """Its page is served at {url}, to {spec.page_access if spec.page_access != "user" else "signed-in"} users.',
            "",
            f"    By hand: {by_hand}.",
            '    """',
            start + check,
        ]
    if spec.config:
        out += [
            "",
            "",
            "def test_it_reads_its_config(plugin):",
            '    """It reads config.yaml, with the defaults for what the file leaves out.',
            "",
            "    By hand: not repeatable on a live Open-WebUI; compare config.yaml with what it does.",
            '    """',
            '    assert plugin.module._settings()["greeting"] == "Hello"',
        ]
    return "\n".join(out) + "\n"


def _type_tests(spec: PluginSpec) -> list[str]:
    if spec.type == "event":
        lines = [
            "def test_it_starts_with_open_webui(owui, plugin):",
            '    """It runs its startup work when Open-WebUI starts.',
            "",
            "    By hand: restart Open-WebUI and look for the function's startup lines in the log.",
            '    """',
            "    owui.startup()  # every enabled Event function gets system.startup.completed",
        ]
        if spec.sync:
            lines.append(f"    assert plugin.valves.SYNC_INTERVAL_MINUTES == {spec.sync_minutes}")
        return lines
    if spec.type == "filter":
        lines = [
            "def test_a_chat_passes_through_unchanged(owui, plugin):",
            '    """A chat request and its reply pass through the filter unchanged.',
            "",
            '    By hand: turn the filter on for a model, send "hi": the answer is what it would be without it.',
            '    """',
            '    user = owui.add_user("Ada")',
            '    body = {"messages": [{"role": "user", "content": "hi"}]}',
        ]
        for hook in spec.hooks:
            if hook == "inlet":
                lines.append("    assert plugin.inlet(body, user=user) == body")
            elif hook == "outlet":
                lines.append("    assert plugin.outlet(body, user=user) == body")
            elif hook == "request":
                lines.append('    assert plugin.call("request", body, user=user) == body')
            else:
                lines += [
                    '    chunk = {"choices": [{"delta": {"content": "hi"}}]}',
                    '    assert plugin.call("stream", chunk) == chunk',
                ]
        return lines
    if spec.type == "action":
        lines = [
            "def test_the_action_runs(owui, plugin):",
            '    """The action runs on a message without failing.',
            "",
            "    By hand: under a reply, click the action's button: no error toast appears.",
            '    """',
            '    user = owui.add_user("Ada")',
        ]
        if spec.buttons:
            lines.append(
                f'    assert [a["id"] for a in plugin.instance.actions] == {_py([b for b, _ in spec.buttons])}'
            )
        if spec.rich_ui:
            lines += [
                '    page = plugin.call("action", {"messages": []}, user=user)',
                '    assert page.headers["content-disposition"] == "inline"',
                "    assert TITLE in page.body.decode()",
            ]
        else:
            lines.append('    assert plugin.call("action", {"messages": []}, user=user) is None')
        return lines
    models = ", ".join(
        f'{{"id": {_py(i)}, "name": {"TITLE" if n == spec.title else _py(n)}}}'
        for i, n in spec.pipe_models
    )
    lines = [
        "def test_it_answers(owui, plugin):",
        '    """It offers its models, and they answer.',
        "",
        "    By hand: pick one of its models in a new chat and send anything: it answers",
        '    "Hello from <title>".',
        '    """',
        '    user = owui.add_user("Ada")',
        f'    assert plugin.call("pipes") == [{models}]',
        '    assert plugin.call("pipe", {"messages": []}, user=user) == "Hello from " + TITLE',
    ]
    if spec.stream:
        lines += [
            '    chunks = plugin.call("pipe", {"messages": [], "stream": True}, user=user)',
            "",
            "    async def read():",
            '        return "".join([c async for c in chunks])',
            "",
            '    assert owui.run(read()) == "Hello from " + TITLE',
        ]
    return lines


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
    valves = [v.name for v in _function_valves(spec)] + (
        ["ENABLE", "SYNC_INTERVAL_MINUTES"] if spec.sync else []
    )
    settings = [f"Valves: {', '.join(f'`{v}`' for v in valves)}."]
    if spec.user_valves:
        settings.append(
            f"User valves (each user, in a chat under Controls > Valves): {', '.join(f'`{v.name}`' for v in spec.user_valves)}."
        )
    if spec.sync:
        settings.append(
            f"Environment (on the Open-WebUI container): `{spec.env_prefix}_SYNC_MINUTES`, the default sync interval (60)."
        )
    if spec.config:
        settings.append(
            f"`config.yaml`: `greeting` (environment: `{spec.env_prefix}_GREETING`, default Hello)."
        )
    if spec.toggle:
        settings.append(
            "A toggle: each user turns it on in a chat's + menu, so it is never made global."
        )
    parts = []
    if spec.tool:
        parts.append(f"the **{spec.tool.title}** tool (`tool.py`)")
    if spec.skills:
        parts.append("the skill(s) " + ", ".join(f"`{s.id}`" for s in spec.skills))
    installs = (
        f"\n\nEnabling the function installs {' and '.join(parts)}; disabling it removes them."
        if parts
        else ""
    )
    live = {
        "event": "Restart Open-WebUI (or enable the function) and look for its lines in the log.",
        "filter": "Turn it on for a model (or make it global) and send a message.",
        "action": "Under a reply, press its button.",
        "pipe": "Pick its model in a new chat and send a message.",
    }[spec.type]
    deploy_notes = []
    if spec.type == "filter" and spec.global_ is None and not spec.toggle:
        deploy_notes.append(
            "- A new filter is made global on its first deploy; set `global:` in plugin.yaml to change that."
        )
    if spec.type == "filter" and spec.toggle:
        deploy_notes.append(
            "- After deploy: attach it to the models that should offer the toggle (Workspace > Models > Filters)."
        )
    if spec.page:
        deploy_notes.append(f"- Its page is at `/{spec.id}/` on the Open-WebUI host.")
    return (
        f"""# {spec.title}

{spec.description}{installs}

{chr(10).join(settings)}

## Test

- `owpp check {spec.id}` bundles it exactly as the deploy does, compiles it and lists undefined names.
- `owpp test {spec.id}` runs `tests/` against a mock Open-WebUI (docs/testing.md).
- On a live Open-WebUI: {live}

## Deploy

- Function type: **{spec.type}**.
- `owpp deploy --only {spec.id} --dry-run`, then without `--dry-run`.
{chr(10).join(deploy_notes)}""".rstrip()
        + "\n"
    )


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


def render(spec: PluginSpec) -> dict[str, str]:
    """The plugin folder's files, {path: text}."""
    validate(spec)
    files = {
        "plugin.yaml": render_manifest(spec),
        "function.py": render_function(spec),
        "README.md": render_readme(spec),
        f"tests/test_{spec.id}.py": render_tests(spec),
    }
    if spec.tool:
        files["tool.py"] = render_tool(spec)
        if spec.tool.rich_ui:
            files["embed.html"] = _PAGE_HTML.replace("__TITLE__", spec.tool.title).format(
                note="Shown in the chat by the tool. It is put into tool.py when bundled."
            )
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


def write_plugin(directory: Path | str, spec: PluginSpec) -> Path:
    """Write the plugin folder `<directory>/<id>/`. Refuses a folder that exists."""
    files = render(spec)
    folder = Path(directory) / spec.id
    if folder.exists():
        raise OwppError(f"{folder} already exists")
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return folder
