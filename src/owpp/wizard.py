"""`owpp create`: a wizard that asks what a plugin is, one stage at a time, then writes it.

Each stage clears the screen (on a terminal) and shows how far along it is and roughly how long
is left. Every question has a default (Enter takes it), and nothing is written until the last
stage shows the files and you say yes. The answers become a `PluginSpec` and `owpp.create` writes
the folder, so what the wizard makes is exactly what the tests of `owpp.create` check: a plugin
that bundles, passes `owpp check --strict` and passes its own tests, ready to be filled in.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TextIO

from .bundle import VALID_ID
from .create import (
    ACCESS,
    FILTER_HOOKS,
    PARAM_TYPES,
    VALID_SKILL,
    VALID_SUB_ID,
    VALID_VALVE,
    VALVE_KINDS,
    PluginSpec,
    SkillSpec,
    ToolMethod,
    ToolSpec,
    Valve,
    parse_default,
    render,
    title_of,
    validate,
    write_plugin,
)
from .errors import OwppError
from .events import KNOWN_EVENTS, problem_with

DOCS = "https://docs.openwebui.com/features/extensibility/"
TOTAL_STAGES = 10
TOTAL_MINUTES = 12


class Cancelled(Exception):
    """Ctrl-C or end of input: stop, and write nothing."""


class Prompter:
    """The wizard's terminal: stages with progress, and questions with defaults.

    `read` returns one line of input (without the newline); `out` is where everything is
    printed. Both are replaceable, so the wizard can be driven by a test."""

    def __init__(
        self,
        read: Callable[[str], str] | None = None,
        out: TextIO | None = None,
        total_stages: int = TOTAL_STAGES,
        total_minutes: int = TOTAL_MINUTES,
    ):
        self.out = out or sys.stdout
        self._read = read or self._input
        self.tty = bool(getattr(self.out, "isatty", lambda: False)())
        self.total_stages, self.total_minutes = total_stages, total_minutes
        self.index = self.elapsed = 0
        bold, dim, reset = ("\033[1m", "\033[2m", "\033[0m") if self.tty else ("", "", "")
        blue, green, yellow = ("\033[34m", "\033[32m", "\033[33m") if self.tty else ("", "", "")
        self.c = {"b": bold, "d": dim, "r": reset, "blue": blue, "green": green, "y": yellow}

    def _input(self, prompt: str) -> str:
        if self.out is sys.stdout and sys.stdin.isatty():
            return input(prompt)  # line editing on a terminal
        self.out.write(prompt)
        self.out.flush()
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip("\r\n")

    def read(self, prompt: str) -> str:
        try:
            return self._read(prompt)
        except (EOFError, KeyboardInterrupt):
            raise Cancelled from None

    def print(self, text: str = "") -> None:
        self.out.write(text + "\n")

    def clear(self) -> None:
        if self.tty:
            self.out.write("\033[2J\033[3J\033[H")

    # -- frame ---------------------------------------------------------------------

    def banner(self, title: str, lines: Sequence[str]) -> None:
        c = self.c
        self.clear()
        self.print(f"\n{c['b']}{c['blue']}  {title}{c['r']}")
        self.print(
            f"{c['d']}  {self.total_stages} stages · about {self.total_minutes} minutes{c['r']}\n"
        )
        for line in lines:
            self.print(f"{c['d']}  {line}{c['r']}")
        self.print()
        self.pause("Ready to start? (Enter)")

    def stage(self, name: str, minutes: int = 1) -> None:
        c = self.c
        self.clear()
        self.index += 1
        remaining = max(0, self.total_minutes - self.elapsed)
        self.elapsed += minutes
        self.print(
            f"\n{c['b']}{c['blue']}▸ Stage {self.index}/{self.total_stages} · {name}{c['r']}"
            f"  {c['d']}(~{remaining} min left){c['r']}\n"
        )

    def say(self, text: str) -> None:
        self.print(f"  {text}")

    def note(self, text: str) -> None:
        self.print(f"  {self.c['d']}{text}{self.c['r']}")

    def warn(self, text: str) -> None:
        self.print(f"  {self.c['y']}⚠ {text}{self.c['r']}")

    def done(self, text: str) -> None:
        self.print(f"  {self.c['green']}✓{self.c['r']} {text}")

    def pause(self, text: str = "Press Enter to continue") -> None:
        self.read(f"  {self.c['d']}{text}{self.c['r']} ")

    # -- questions -----------------------------------------------------------------

    def ask(
        self,
        question: str,
        default: str = "",
        check: Callable[[str], Any] | None = None,
    ) -> str:
        """A line of text; Enter takes the default. `check` raises OwppError (or returns a
        message) when the answer will not do, and the question is asked again."""
        c = self.c
        shown = f" {c['d']}[{default}]{c['r']}" if default else ""
        while True:
            answer = self.read(f"  {c['b']}{question}{c['r']}{shown} ").strip() or default
            try:
                problem = check(answer) if check else None
            except OwppError as e:
                problem = str(e)
            if not problem:
                return answer
            self.warn(problem)

    def confirm(self, question: str, default: bool = False) -> bool:
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            answer = self.read(f"  {self.c['y']}?{self.c['r']} {question} {hint} ").strip().lower()
            if not answer:
                return default
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.warn("answer y or n")

    def choose(self, question: str, options: Sequence[tuple[str, str]], default: str) -> str:
        """One of `options`, (value, description), by number or by value."""
        self.say(question)
        for i, (value, text) in enumerate(options, 1):
            mark = "*" if value == default else " "
            self.print(f"   {mark}{i}. {self.c['b']}{value or '(none)'}{self.c['r']}  {text}")
        values = [v for v, _ in options]
        while True:
            answer = self.read(
                f"  {self.c['b']}Choice{self.c['r']} [{values.index(default) + 1}] "
            ).strip()
            if not answer:
                return default
            if answer.isdigit() and 1 <= int(answer) <= len(values):
                return values[int(answer) - 1]
            if answer in values:
                return answer
            self.warn(f"pick 1 to {len(values)}")

    def choose_many(
        self, question: str, options: Sequence[tuple[str, str]], defaults: Sequence[str]
    ) -> list[str]:
        """Any of `options`, as numbers or values separated by commas; Enter takes the
        defaults (marked *), `-` takes none."""
        self.say(question)
        for i, (value, text) in enumerate(options, 1):
            mark = "*" if value in defaults else " "
            self.print(f"   {mark}{i}. {self.c['b']}{value}{self.c['r']}  {text}")
        values = [v for v, _ in options]
        shown = ",".join(str(values.index(d) + 1) for d in defaults) or "-"
        while True:
            answer = self.read(
                f"  {self.c['b']}Choices{self.c['r']} (comma-separated, - for none) [{shown}] "
            ).strip()
            if not answer:
                return list(defaults)
            if answer == "-":
                return []
            picked, bad = [], []
            for part in (p.strip() for p in answer.split(",") if p.strip()):
                if part.isdigit() and 1 <= int(part) <= len(values):
                    picked.append(values[int(part) - 1])
                elif part in values:
                    picked.append(part)
                else:
                    bad.append(part)
            if not bad:
                return list(dict.fromkeys(picked))
            self.warn(f"not an option: {', '.join(bad)}")


# ---- the stages ---------------------------------------------------------------------


def _git_author() -> str:
    if not shutil.which("git"):
        return ""
    try:
        done = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _need(text: str, label: str) -> str | None:
    return None if text else f"{label} is required"


def _decide_type(p: Prompter) -> str:
    """The questions in docs/authoring.md, "Pick the function type first"."""
    if p.confirm("Is it a model people pick in the chat (its own backend)?"):
        return "pipe"
    if p.confirm("Is it a button the user presses under a message?"):
        return "action"
    if p.confirm("Does it change chat requests or replies as they pass (or add to them)?"):
        return "filter"
    p.note("Then it reacts to Open-WebUI itself (startup, settings), runs on a schedule or")
    p.note("serves its own pages: an event function.")
    return "event"


def _ask_valves(p: Prompter, label: str, taken: set[str]) -> list[Valve]:
    valves: list[Valve] = []
    while True:
        name = p.ask(
            f"{label} name (UPPER_SNAKE; Enter when done)",
            check=lambda n: (
                None
                if not n
                else f'"{n}" is not a valid name'
                if not VALID_VALVE.fullmatch(n)
                else f"{n} is already taken"
                if n in taken
                else None
            ),
        )
        if not name:
            return valves
        kind = p.choose(
            f"What kind of setting is {name}?",
            [
                ("str", "text"),
                ("int", "whole number"),
                ("float", "number"),
                ("bool", "a switch"),
                ("password", "text, masked in the UI (an API key)"),
                ("select", "one of a list: a dropdown"),
                ("multiselect", "any of a list: checkboxes"),
                ("range", "a number on a slider"),
            ],
            "str",
        )
        assert kind in VALVE_KINDS
        options: list[str] = []
        lo, hi, step = 0.0, 1.0, 0.1
        if kind in ("select", "multiselect"):
            raw = p.ask(
                "Options (comma-separated)",
                check=lambda t: (
                    None if [s for s in t.split(",") if s.strip()] else "give at least one"
                ),
            )
            options = [s.strip() for s in raw.split(",") if s.strip()]
        if kind == "range":
            lo = float(p.ask("Minimum", "0", check=lambda t: parse_default("float", t) and None))
            hi = float(
                p.ask(
                    "Maximum",
                    "1",
                    check=lambda t, lo=lo: (
                        None
                        if parse_default("float", t) > lo
                        else "the maximum must be above the minimum"
                    ),
                )
            )
            step = float(p.ask("Step", "0.1", check=lambda t: parse_default("float", t) and None))
        suggested = {
            "bool": "false",
            "select": options[0] if options else "",
            "range": str(lo),
        }.get(kind, "")
        if kind == "password":
            p.note("Leave a secret's default empty: the default is in the code, which is in git.")
        raw_default = p.ask(
            "Default",
            suggested,
            check=lambda t, kind=kind, options=options: parse_default(kind, t, options) and None,
        )
        default = parse_default(kind, raw_default, options)
        description = p.ask(
            "Description (shown next to it in the admin UI)",
            check=lambda t: _need(t, "a description"),
        )
        valves.append(Valve(name, kind, default, description, options, lo, hi, step))
        taken.add(name)
        p.done(f"{name} ({kind})")


def _ask_pairs(p: Prompter, label: str, title: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    while True:
        sub = p.ask(
            f"{label} id (a-z, 0-9, _; Enter when done)",
            check=lambda s: (
                None
                if not s or (VALID_SUB_ID.fullmatch(s) and s not in dict(pairs))
                else f'"{s}" is not a valid id, or is taken'
            ),
        )
        if not sub:
            return pairs
        pairs.append((sub, p.ask("Name shown in Open-WebUI", title_of(sub))))


def _params(text: str) -> list[tuple[str, str]]:
    out = []
    for part in (s.strip() for s in text.split(",") if s.strip()):
        name, _, kind = part.partition(":")
        name, kind = name.strip(), (kind.strip() or "str")
        if not VALID_SUB_ID.fullmatch(name):
            raise OwppError(f'"{name}" is not a valid parameter name')
        if kind not in PARAM_TYPES:
            raise OwppError(f"{kind} is not one of {', '.join(PARAM_TYPES)}")
        out.append((name, kind))
    return out


def stage_identity(p: Prompter, directory: Path, preset_id: str = "") -> dict:
    p.stage("Name the plugin")
    p.say(f"It will be a folder in {directory}. Its name is the function id in Open-WebUI,")
    p.say("so it cannot change once deployed.")
    plugin_id = p.ask(
        "Plugin id (lowercase letters, digits and _)",
        preset_id,
        check=lambda i: (
            _need(i, "an id")
            or (None if VALID_ID.fullmatch(i) else f'"{i}" is not valid: no hyphens or capitals')
            or (f"{directory / i} already exists" if (directory / i).exists() else None)
        ),
    )
    title = p.ask("Title (shown in Open-WebUI)", title_of(plugin_id))
    return {"id": plugin_id, "title": title}


def stage_header(p: Prompter, title: str) -> dict:
    p.stage("Describe it")
    p.say("These go into plugin.yaml's function: section, which becomes the header")
    p.say("Open-WebUI reads. Each answer must fit on one line.")
    one_line = lambda t: "it must fit on one line" if "\n" in t else None  # noqa: E731
    return {
        "description": p.ask(
            "One-line description", f"What {title} does, on one line.", check=one_line
        ),
        "author": p.ask("Author", _git_author() or "you"),
        "version": p.ask("Version", "0.1.0"),
        "license": p.ask("License", "MIT"),
        "required_open_webui_version": p.ask(
            "Oldest Open-WebUI it supports (Event functions need 0.10.0)", "0.10.0"
        ),
        "icon_url": p.ask("Icon URL (optional: an action's button, a toggle's chip)", ""),
        "requirements": p.ask(
            "Extra pip packages, comma-separated (optional; installed when the function is saved)",
            "",
        ),
    }


def stage_type(p: Prompter) -> str:
    p.stage("Pick the function type")
    p.say("The function is the plugin's parent: its tool and skills come and go with it.")
    kind = p.choose(
        "What kind of function?",
        [
            ("filter", "changes chat requests and replies (inlet, stream, outlet)"),
            ("action", "a button under a message"),
            ("event", "reacts to Open-WebUI events, runs on a schedule, serves pages"),
            ("pipe", "appears as a model"),
            ("help", "not sure: ask me a few questions"),
        ],
        "event",
    )
    return _decide_type(p) if kind == "help" else kind


def stage_type_options(p: Prompter, kind: str, title: str) -> dict:
    p.stage(f"{kind.capitalize()} options")
    if kind == "filter":
        hooks = p.choose_many(
            "Which hooks does it need?",
            [
                ("inlet", "the request, once per user turn"),
                ("request", "every call to the model, tool loops included (newer Open-WebUI)"),
                ("stream", "each chunk of a streamed reply"),
                ("outlet", "the finished reply"),
            ],
            ["inlet", "outlet"],
        )
        assert all(h in FILTER_HOOKS for h in hooks)
        toggle = p.confirm("A switch each user turns on in the chat (a toggle)?")
        global_ = None
        if not toggle:
            global_ = {"first": None, "always": True, "never": False}[
                p.choose(
                    "Make it global (on for every model)?",
                    [
                        ("first", "on its first deploy, then as admins leave it"),
                        ("always", "and again on every deploy"),
                        ("never", "admins attach it to models"),
                    ],
                    "first",
                )
            ]
        return {
            "hooks": hooks or ["inlet"],
            "toggle": toggle,
            "global_": global_,
            "file_handler": p.confirm("Does it handle attached files itself (file_handler)?"),
            "priority": p.confirm("A priority valve (its place among other filters)?"),
        }
    if kind == "action":
        buttons = []
        if p.confirm("More than one button (sub-actions)?"):
            buttons = _ask_pairs(p, "Button", title)
        global_ = p.confirm("Global (a button on every model's messages)?", True)
        return {
            "buttons": buttons,
            "global_": True if global_ else None,
            "rich_ui": p.confirm("Show a page (HTML) above the message when pressed?"),
            "priority": p.confirm("A priority valve (its place among other actions)?"),
        }
    if kind == "pipe":
        models = []
        if p.confirm("Several models (a manifold)?"):
            models = _ask_pairs(p, "Model", title)
        return {"models": models, "stream": p.confirm("Stream its answers?", True)}
    sync = p.confirm("Does it run a sync on a schedule (and on startup and saved valves)?")
    minutes = 60
    if sync:
        minutes = int(
            p.ask(
                "Default interval in minutes (0: only on startup and saved valves)",
                "60",
                check=lambda t: None if t.isdigit() else "a whole number",
            )
        )
    known = [(e, "") for e in KNOWN_EVENTS]
    events = p.choose_many(
        "Which Open-WebUI events should it handle (with @on)?",
        known,
        [] if sync else ["system.startup.completed"],
    )
    more = p.ask(
        "Other event names, comma-separated (optional, e.g. user.created)",
        check=lambda t: next(
            (
                problem_with(n.strip())
                for n in t.split(",")
                if n.strip() and problem_with(n.strip())
            ),
            None,
        ),
    )
    events += [n.strip() for n in more.split(",") if n.strip() and n.strip() not in events]
    p.note(f"The full list of events: {DOCS}plugin/functions/event")
    return {"sync": sync, "sync_minutes": minutes, "events": events}


def stage_valves(p: Prompter, spec: dict) -> list[Valve]:
    p.stage("Valves", 2)
    p.say("Valves are settings an admin changes in the UI without a deploy. They are")
    p.say("UPPER_SNAKE and each has a description.")
    added = ["ENABLE"] if not spec.get("sync") else ["ENABLE", "SYNC_INTERVAL_MINUTES"]
    if spec.get("priority"):
        added.append("priority")
    p.note(f"Already there: {', '.join(added)}.")
    return _ask_valves(p, "Valve", set(added))


def stage_user_valves(p: Prompter, kind: str) -> list[Valve]:
    p.stage("User valves")
    if kind == "event":
        p.say("An event function runs without a user, so it has no user valves.")
        p.pause()
        return []
    p.say("User valves are settings each user sets for themselves, in a chat.")
    if not p.confirm("Add user valves?"):
        return []
    return _ask_valves(p, "User valve", set())


def stage_tool(p: Prompter, plugin_id: str, title: str) -> ToolSpec | None:
    p.stage("Tool", 2)
    p.say("A tool is code the model can call. The function installs it when enabled and")
    p.say("removes it when disabled.")
    if not p.confirm("Add a tool?"):
        return None
    tool_id = p.ask(
        "Tool id",
        plugin_id,
        check=lambda t: None if VALID_ID.fullmatch(t) else "lowercase letters, digits and _",
    )
    tool_title = p.ask("Tool title", title)
    description = p.ask("What the tool does, in one line", f"What {tool_title} does.")
    methods: list[ToolMethod] = []
    p.say("Methods: each one is offered to the model, which reads its description.")
    while True:
        name = p.ask(
            "Method name (Enter when done)" if methods else "Method name",
            "" if methods else "lookup",
            check=lambda n: (
                None
                if not n or (VALID_SUB_ID.fullmatch(n) and n not in {m.name for m in methods})
                else f'"{n}" is not a valid name, or is taken'
            ),
        )
        if not name:
            break
        what = p.ask("When should the model call it?", f"Use {name} to ...")
        params = _params(
            p.ask(
                f"Parameters, name:type, comma-separated (types: {', '.join(PARAM_TYPES)})",
                "query:str",
                check=lambda t: _params(t) and None,
            )
        )
        methods.append(ToolMethod(name, what, params))
    return ToolSpec(
        tool_id,
        tool_title,
        description,
        methods,
        public=p.confirm("Let every signed-in user use it (access: public)?", True),
        rich_ui=p.confirm("A method that shows a page (HTML) in the chat?"),
        chat_data=p.confirm("Does the tool keep data with the chat (chat_data)?"),
    )


def stage_skills(p: Prompter) -> list[SkillSpec]:
    p.stage("Skills")
    p.say("A skill is a SKILL.md of instructions the model reads when it needs them.")
    skills: list[SkillSpec] = []
    while p.confirm("Add a skill?" if not skills else "Add another skill?"):
        name = p.ask(
            "Skill name (lowercase, hyphens)",
            check=lambda n: (
                None
                if VALID_SKILL.fullmatch(n) and n not in {s.id for s in skills}
                else "lowercase letters, digits and hyphens, at most 64, not taken"
            ),
        )
        description = p.ask(
            "When it applies, in a sentence (ending in a period)",
            check=lambda t: (
                _need(t, "a description") or ("at most 1024 characters" if len(t) > 1024 else None)
            ),
        )
        public = p.confirm("Let every signed-in user use it (access: public)?", True)
        skills.append(SkillSpec(name, description, public))
    return skills


def stage_libraries(p: Prompter, kind: str) -> dict:
    p.stage("Pages and libraries")
    page = p.choose(
        "Does it serve a page?",
        [
            ("", "no"),
            ("static", "a file, served as it is (static/index.html)"),
            ("rendered", "filled in by the function per request (templates/page.html)"),
        ],
        "",
    )
    access = "user"
    if page:
        access = p.choose(
            "Who may open it?",
            [
                ("user", "any signed-in user"),
                ("admin", "admins only"),
                ("public", "anyone, signed in or not (owpp check lists it)"),
            ],
            "user",
        )
        assert access in ACCESS
        if access == "public":
            p.warn("Public pages are reachable by anyone who can reach the URL.")
    out = {
        "page": page,
        "page_access": access,
        "chat_data": p.confirm("Does the function keep data with each chat (chat_data)?"),
        "config": p.confirm("Ship structured settings in a config.yaml?"),
        "assets": False,
        "live_reload": False,
    }
    if kind == "event":
        out["assets"] = p.confirm("Add JavaScript or CSS to every page (assets/)?")
        if out["assets"]:
            out["live_reload"] = p.confirm(
                "Reach every container within a second of a change (live_reload; Redis)?"
            )
    return out


def stage_write(p: Prompter, directory: Path, spec: PluginSpec) -> Path | None:
    p.stage("Review and write")
    files = render(spec)
    p.say(f"{spec.title} ({spec.type} function) in {directory / spec.id}:")
    for name in files:
        p.print(f"     {name}")
    p.print()
    if not p.confirm("Write these files?", True):
        return None
    folder = write_plugin(directory, spec)
    p.done(f"created {folder}")
    return folder


def _summary(p: Prompter, folder: Path, spec: PluginSpec, checked: int | None) -> None:
    c = p.c  # no clear: the check's output stays on screen above
    p.print(f"\n{c['b']}{c['green']}  ✓ {spec.title} is ready to fill in{c['r']}\n")
    p.note(f"in {folder}")
    if checked is not None:
        (p.done if checked == 0 else p.warn)(
            "owpp check --strict: " + ("clean" if checked == 0 else "see the output above")
        )
    p.print()
    p.say("Next:")
    todo = ["function.py: the work itself (every hook and handler is a stub)"]
    if spec.tool:
        todo.append("tool.py: each method's body and its description for the model")
    if spec.skills:
        todo.append("skills/*/SKILL.md: the instructions")
    if spec.page:
        todo.append(
            f"{'static/index.html' if spec.page == 'static' else 'templates/page.html'}: the page"
        )
    todo.append("README.md: what it does, and the live checks under ## Test")
    for t in todo:
        p.print(f"   • {t}")
    p.print()
    p.say("Then:")
    for cmd in (
        f"owpp check {spec.id} --strict",
        f"uvx --from 'owpp[test]' owpp test {spec.id}",
        f"owpp deploy --only {spec.id} --dry-run",
    ):
        p.print(f"   $ {cmd}")
    p.print()
    p.note(f"Open-WebUI's plugin docs: {DOCS}")
    p.note("This repository's: docs/authoring.md, docs/plugin-format.md, docs/libraries.md")
    p.print()


def ask_spec(p: Prompter, directory: Path, preset_id: str = "") -> PluginSpec:
    """Every stage but the last: the answers, as a PluginSpec."""
    answers: dict = stage_identity(p, directory, preset_id)
    answers |= stage_header(p, answers["title"])
    answers["type"] = stage_type(p)
    answers |= stage_type_options(p, answers["type"], answers["title"])
    answers["valves"] = stage_valves(p, answers)
    answers["user_valves"] = stage_user_valves(p, answers["type"])
    answers["tool"] = stage_tool(p, answers["id"], answers["title"])
    answers["skills"] = stage_skills(p)
    answers |= stage_libraries(p, answers["type"])
    spec = PluginSpec(**answers)
    validate(spec)
    return spec


def run_wizard(
    directory: Path,
    preset_id: str = "",
    prompter: Prompter | None = None,
    check: Callable[[Path, str], int] | None = None,
) -> int:
    """`owpp create`. `check(directory, id)` runs `owpp check --strict` on the new plugin."""
    p = prompter or Prompter()
    try:
        p.banner(
            "Create an Open-WebUI plugin",
            [
                "Answer a few questions and get a plugin folder that uses owpp: a function,",
                "and optionally a tool, skills, a page and libraries, with tests and a README.",
                "Enter takes the default. Nothing is written until the last stage; Ctrl-C stops.",
            ],
        )
        spec = ask_spec(p, directory, preset_id)
        folder = stage_write(p, directory, spec)
    except Cancelled:
        p.print()
        p.warn("cancelled: nothing was written")
        return 130
    if folder is None:
        p.warn("nothing was written")
        return 1
    checked = check(directory, spec.id) if check else None
    _summary(p, folder, spec, checked)
    return 0
