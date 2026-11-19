"""Open-WebUI's lifecycle event names, for checking `@on(...)` in a plugin's code.

The list is not closed: Open-WebUI adds events, and a plugin may handle one this file does not
know. So a name is only refused when it is malformed or looks like a typo of a known one."""

from __future__ import annotations

import difflib
import re

KNOWN_EVENTS = (
    "system.startup.completed",
    "function.enable_started",
    "function.disable_started",
    "function.enabled",
    "function.disabled",
    "function.updated",
    "function.valves_updated",
    "function.deleted",
    "tool.deleted",
    "chat.created",
    "config.banners.updated",
)

_SHAPE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")


def problem_with(name: str) -> str | None:
    """Why `name` cannot be an event name, or None when it is fine or plausibly a newer one."""
    if not _SHAPE.fullmatch(name):
        return (
            f"{name!r} is not an event name (lowercase words joined by dots, like function.updated)"
        )
    if name in KNOWN_EVENTS:
        return None
    close = difflib.get_close_matches(name, KNOWN_EVENTS, n=1, cutoff=0.85)
    if close:
        return f"{name!r} never fires: did you mean {close[0]!r}?"
    return None
