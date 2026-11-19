"""`owpp create`: a wizard that scaffolds a plugin, one stage at a time.

It asks what the plugin is and writes a folder ready to fill in: the files, stubs for the code,
tests and a README. Each stage clears the screen (on a terminal) and shows how far along it is.
Every question has a default (Enter takes it), and nothing is written until the last stage shows
the files and you say yes.

The first branch is where the code lives:

- **written here**: a function (filter, action, event or pipe) with optional tool, skills, page
  and libraries, or an **installer**, a plugin with no function code that only deploys a tool
  and/or skills (the function that installs them is generated);
- **a git repository**: pinned to a commit, from which it takes the function itself, or just a
  tool and skills (then it is an installer).

The answers become a `PluginSpec` and `owpp.create` writes the folder, so what the wizard makes is
what the tests of `owpp.create` check.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TextIO

from .bundle import VALID_ID, VALID_SKILL_ID
from .create import (
    ACCESS,
    FILTER_HOOKS,
    VALID_SKILL,
    VALID_SUB_ID,
    PluginSpec,
    SkillSpec,
    SourceSpec,
    ToolSpec,
    render,
    title_of,
    validate,
    write_plugin,
)
from .errors import OwppError
from .events import KNOWN_EVENTS, problem_with
from .sources import GIT_URL, SHA40

DOCS = "https://docs.openwebui.com/features/extensibility/"
# (stages, minutes) for each branch; the first two stages are the same in both.
HERE = (9, 8)
FROM_GIT = (6, 5)
TOTAL_STAGES, TOTAL_MINUTES = HERE


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


def resolve_ref(git: str, ref: str) -> str | None:
    """The full commit SHA a branch or tag of `git` points at (with `git ls-remote`), or None
    when it cannot be found. A full SHA is returned as it is."""
    if SHA40.fullmatch(ref):
        return ref
    if not GIT_URL.fullmatch(git) or not shutil.which("git") or ref.startswith("-"):
        return None
    try:
        done = subprocess.run(
            ["git", "ls-remote", git, ref, f"{ref}^{{}}"],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},  # never wait for a password
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    found = dict(
        (name, sha)
        for sha, _, name in (line.partition("\t") for line in done.stdout.splitlines())
        if SHA40.fullmatch(sha)
    )
    # An annotated tag's commit is the peeled ^{} entry; a branch or light tag has just one.
    for name in (f"refs/tags/{ref}^{{}}", f"refs/heads/{ref}", f"refs/tags/{ref}", ref):
        if name in found:
            return found[name]
    return next(iter(found.values()), None)


def _need(text: str, label: str) -> str | None:
    return None if text else f"{label} is required"


def _repo_path(text: str) -> str | None:
    parts = [p for p in text.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        return "a path inside the repository, without . or .."
    return None


def _decide_type(p: Prompter) -> str:
    """The questions in docs/authoring.md, "Pick the function type first"."""
    if p.confirm("Is it only there to deploy a tool or skills (no code of its own)?"):
        return "installer"
    if p.confirm("Is it a model people pick in the chat (its own backend)?"):
        return "pipe"
    if p.confirm("Is it a button the user presses under a message?"):
        return "action"
    if p.confirm("Does it change chat requests or replies as they pass (or add to them)?"):
        return "filter"
    p.note("Then it reacts to Open-WebUI itself (startup, settings), runs on a schedule or")
    p.note("serves its own pages: an event function.")
    return "event"


def _ask_pairs(p: Prompter, label: str) -> list[tuple[str, str]]:
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


def _names(text: str) -> list[str]:
    names = [n.strip() for n in text.split(",") if n.strip()]
    bad = [n for n in names if not VALID_SUB_ID.fullmatch(n)]
    if bad:
        raise OwppError(f"not a valid name: {', '.join(bad)} (a-z, 0-9, _)")
    if len(set(names)) != len(names):
        raise OwppError("a name is listed twice")
    return names


def stage_identity(p: Prompter, directory: Path, preset_id: str = "") -> dict:
    p.stage("Name the plugin")
    p.say(f"It will be a folder in {directory}.")
    p.say("Its name is the function id in Open-WebUI, so it cannot change once deployed.")
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


def stage_origin(p: Prompter) -> bool:
    """True: the code comes from a git repository."""
    p.stage("Where the code lives")
    origin = p.choose(
        "Where does its code come from?",
        [
            ("here", "written in this repository (a function, or an installer of a tool/skills)"),
            ("git", "another git repository, pinned to a commit (a function, a tool, skills)"),
        ],
        "here",
    )
    return origin == "git"


def stage_header(p: Prompter, title: str, kind: str) -> dict:
    p.stage("Describe it")
    p.say("These go into plugin.yaml's function: section, which becomes the header")
    p.say("Open-WebUI reads. Each answer must fit on one line.")
    default = (
        f"Installs {title}; disabling this function removes it."
        if kind == "installer"
        else f"What {title} does, on one line."
    )
    answers = {
        "description": p.ask("One-line description", default),
        "author": p.ask("Author", _git_author() or "you"),
        "version": p.ask("Version", "0.1.0"),
        "license": p.ask("License", "MIT"),
    }
    if kind == "installer":
        return answers
    return answers | {
        "required_open_webui_version": p.ask(
            "Oldest Open-WebUI it supports (Event functions need 0.10.0)", "0.10.0"
        ),
        "requirements": p.ask(
            "Extra pip packages, comma-separated (optional; installed when the function is saved)",
            "",
        ),
    }


def stage_type(p: Prompter) -> str:
    p.stage("Pick the plugin type")
    p.say("The function is the plugin's parent: its tool and skills come and go with it.")
    kind = p.choose(
        "What kind of plugin?",
        [
            ("filter", "changes chat requests and replies (inlet, stream, outlet)"),
            ("action", "a button under a message"),
            ("event", "reacts to Open-WebUI events, runs on a schedule, serves pages"),
            ("pipe", "appears as a model"),
            ("installer", "no code of its own: deploys a tool and/or skills"),
            ("help", "not sure: ask me a few questions"),
        ],
        "event",
    )
    return _decide_type(p) if kind == "help" else kind


def stage_type_options(p: Prompter, kind: str) -> dict:
    p.stage(f"{kind.capitalize()} options")
    if kind == "installer":
        p.say("An installer's function is generated: a global filter that installs the tool")
        p.say("and skills when it is enabled and removes them when it is disabled.")
        p.pause()
        return {}
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
        buttons = _ask_pairs(p, "Button") if p.confirm("More than one button?") else []
        return {
            "buttons": buttons,
            "global_": True if p.confirm("Global (on every model's messages)?", True) else None,
            "rich_ui": p.confirm("Show a page (HTML) above the message when pressed?"),
            "priority": p.confirm("A priority valve (its place among other actions)?"),
        }
    if kind == "pipe":
        models = _ask_pairs(p, "Model") if p.confirm("Several models (a manifold)?") else []
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
    events = p.choose_many(
        "Which Open-WebUI events should it handle (with @on)?",
        [(e, "") for e in KNOWN_EVENTS],
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
    p.note(f"Every event: {DOCS}plugin/functions/event")
    return {"sync": sync, "sync_minutes": minutes, "events": events}


def stage_tool(p: Prompter, plugin_id: str, title: str, kind: str) -> ToolSpec | None:
    p.stage("Tool")
    p.say("A tool is code the model can call. The function installs it when enabled and")
    p.say("removes it when disabled.")
    if not p.confirm("Add a tool?", kind == "installer"):
        return None
    tool_id = p.ask(
        "Tool id",
        plugin_id,
        check=lambda t: None if VALID_ID.fullmatch(t) else "lowercase letters, digits and _",
    )
    methods = _names(
        p.ask(
            "Method names the model can call, comma-separated",
            "lookup",
            check=lambda t: (_names(t) and None) if t.strip() else "at least one",
        )
    )
    return ToolSpec(
        tool_id,
        p.ask("Tool title", title),
        "",
        methods,
        public=p.confirm("Let every signed-in user use it (access: public)?", True),
        rich_ui=p.confirm("A method that shows a page (HTML) in the chat?"),
        chat_data=p.confirm("Does the tool keep data with the chat (chat_data)?"),
    )


def stage_skills(p: Prompter, need_one: bool) -> list[SkillSpec]:
    p.stage("Skills")
    p.say("A skill is a SKILL.md of instructions the model reads when it needs them.")
    skills: list[SkillSpec] = []
    while True:
        if need_one and not skills:
            p.note("An installer with no tool needs at least one skill.")
        elif not p.confirm("Add a skill?" if not skills else "Add another skill?"):
            return skills
        name = p.ask(
            "Skill name (lowercase, hyphens)",
            check=lambda n: (
                None
                if VALID_SKILL.fullmatch(n) and n not in {s.id for s in skills}
                else "lowercase letters, digits and hyphens, at most 64, not taken"
            ),
        )
        description = p.ask(
            "When it applies, in a sentence",
            f"Use {name} when ...",
            check=lambda t: "at most 1024 characters" if len(t) > 1024 else None,
        )
        public = p.confirm("Let every signed-in user use it (access: public)?", True)
        skills.append(SkillSpec(name, description, public))


def stage_libraries(p: Prompter, kind: str) -> dict:
    p.stage("Pages and libraries")
    if kind == "installer":
        p.say("An installer has no code of its own, so no page or libraries.")
        p.pause()
        return {}
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
    }
    if kind == "event" and p.confirm("Add JavaScript or CSS to every page (assets/)?"):
        out["assets"] = True
        out["live_reload"] = p.confirm(
            "Reach every container within a second of a change (live_reload; Redis)?"
        )
    return out


def stage_repository(p: Prompter, resolve: Callable[[str, str], str | None]) -> SourceSpec:
    p.stage("The repository")
    p.say("The plugin takes its files from this repository at one commit, so what is")
    p.say("deployed never changes until you move the commit yourself.")
    git = p.ask(
        "Git URL (https://, ssh:// or user@host:path)",
        check=lambda t: (
            None if GIT_URL.fullmatch(t) else "an https://, ssh:// or user@host:path URL"
        ),
    )
    ref = p.ask("Branch, tag or commit SHA", "main", check=lambda t: _need(t, "a ref"))
    sha = resolve(git, ref)
    if sha:
        p.done(f"{ref} is commit {sha}")
    else:
        p.warn(f"could not look up {ref} in {git} (offline, private, or no such ref)")
        sha = p.ask(
            "Full 40-character commit SHA",
            check=lambda t: None if SHA40.fullmatch(t) else "40 lowercase hex characters",
        )
    path = p.ask(
        "Folder in the repository the files are in (Enter for the root)",
        check=lambda t: _repo_path(t) if t else None,
    )
    return SourceSpec(git, sha, path.strip("/"))


def stage_take(p: Prompter, plugin_id: str, title: str, src: SourceSpec) -> dict:
    p.stage("What it takes")
    where = f"`{src.path}/`" if src.path else "the repository root"
    p.say(f"Paths are relative to {where}.")
    out: dict = {"type": "installer", "tool": None, "skills": []}
    if p.confirm("Take the function itself from the repository (its header included)?"):
        src.function_file = p.ask("Its file", "function.py", check=_repo_path)
        out["type"] = "upstream"
    if p.confirm("Take a tool from it?", True):
        file = p.ask("The tool's file", "tool.py", check=_repo_path)
        tool_id = p.ask(
            "Tool id",
            plugin_id,
            check=lambda t: None if VALID_ID.fullmatch(t) else "lowercase letters, digits and _",
        )
        public = p.confirm("Let every signed-in user use it (access: public)?", True)
        out["tool"] = ToolSpec(tool_id, title, file=file, public=public)
    skills: list[SkillSpec] = []
    while p.confirm("Take a skill from it?" if not skills else "Take another skill?"):
        skill_id = p.ask(
            "Skill id",
            check=lambda n: (
                None
                if VALID_SKILL_ID.fullmatch(n) and n not in {s.id for s in skills}
                else "a-z, 0-9, _ and -, not taken"
            ),
        )
        path = p.ask(
            "Its folder (SKILL.md plus files), or its SKILL.md",
            f"skills/{skill_id}",
            check=_repo_path,
        )
        public = p.confirm("Let every signed-in user use it (access: public)?", True)
        skills.append(
            SkillSpec(skill_id, path=path, is_dir=not path.endswith(".md"), public=public)
        )
    out["skills"] = skills
    if out["type"] == "installer" and not (out["tool"] or skills):
        raise OwppError("it takes nothing from the repository: a function, a tool or a skill")
    return out


def stage_git_header(p: Prompter, title: str, kind: str) -> dict:
    if kind == "installer":
        return stage_header(p, title, kind)
    p.stage("Global?")
    p.say("The function's header comes from its file. One thing is set here:")
    if p.confirm("Make it active and global on every deploy (filters and actions only)?"):
        return {"global_": True}
    return {}


def stage_write(p: Prompter, directory: Path, spec: PluginSpec) -> Path | None:
    p.stage("Review and write")
    files = render(spec)
    kind = {"installer": "installer", "upstream": "function from git"}.get(
        spec.type, f"{spec.type} function"
    )
    p.say(f"{spec.title} ({kind}) in {directory / spec.id}:")
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
    todo = []
    if spec.has_code:
        todo.append(
            "function.py: the work itself, and its valves (every hook and handler is a stub)"
        )
    if spec.tool and not spec.tool.file:
        todo.append("tool.py: each method's parameters, body and description for the model")
    if spec.skills and not spec.source:
        todo.append("skills/*/SKILL.md: the instructions")
    if spec.page:
        todo.append(
            f"{'static/index.html' if spec.page == 'static' else 'templates/page.html'}: the page"
        )
    todo.append("README.md: what it does, and the live checks under ## Test")
    p.say("Next:")
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


def ask_spec(
    p: Prompter,
    directory: Path,
    preset_id: str = "",
    resolve: Callable[[str, str], str | None] = resolve_ref,
) -> PluginSpec:
    """Every stage but the last: the answers, as a PluginSpec."""
    answers: dict = stage_identity(p, directory, preset_id)
    if stage_origin(p):
        p.total_stages, p.total_minutes = FROM_GIT
        src = stage_repository(p, resolve)
        answers |= stage_take(p, answers["id"], answers["title"], src)
        answers |= stage_git_header(p, answers["title"], answers["type"])
        answers["source"] = src
    else:
        p.total_stages, p.total_minutes = HERE
        kind = answers["type"] = stage_type(p)
        answers |= stage_header(p, answers["title"], kind)
        answers |= stage_type_options(p, kind)
        answers["tool"] = stage_tool(p, answers["id"], answers["title"], kind)
        answers["skills"] = stage_skills(p, kind == "installer" and not answers["tool"])
        answers |= stage_libraries(p, kind)
    spec = PluginSpec(**answers)
    validate(spec)
    return spec


def run_wizard(
    directory: Path,
    preset_id: str = "",
    prompter: Prompter | None = None,
    check: Callable[[Path, str], int] | None = None,
    resolve: Callable[[str, str], str | None] = resolve_ref,
) -> int:
    """`owpp create`. `check(directory, id)` runs `owpp check --strict` on the new plugin;
    `resolve(git, ref)` turns a branch or tag into a commit SHA."""
    p = prompter or Prompter()
    try:
        p.banner(
            "Create an Open-WebUI plugin",
            [
                "Answer a few questions and get a plugin folder that uses owpp, ready to fill",
                "in: a function, or an installer for a tool and skills, written here or taken",
                "from a git repository, with tests and a README. Enter takes the default.",
                "Nothing is written until the last stage; Ctrl-C stops.",
            ],
        )
        spec = ask_spec(p, directory, preset_id, resolve)
        folder = stage_write(p, directory, spec)
    except Cancelled:
        p.print()
        p.warn("cancelled: nothing was written")
        return 130
    except OwppError as e:
        p.print()
        p.warn(f"{e}: nothing was written")
        return 1
    if folder is None:
        p.warn("nothing was written")
        return 1
    checked = check(directory, spec.id) if check else None
    _summary(p, folder, spec, checked)
    return 0
