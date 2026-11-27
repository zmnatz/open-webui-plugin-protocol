"""The runtime embedded in a bundle, and the only place that knows its format.

The bundler appends runtime/plugin_runtime.py to a function (and to each tool it embeds), with
the bundle's data as a JSON string literal in the line that loads it. The banner the runtime
starts with and that data line are both taken from the runtime's source, so they cannot differ
from what is written.
"""

from __future__ import annotations

import json
import re
from functools import cache

from .libraries import LITERAL, RUNTIME_FILE, fill, json_literal
from .manifest import read_text

_PLACEHOLDER = "__PLUGIN_DATA__"


@cache
def _banner() -> str:
    """The runtime's source up to the end of its first line that is not blank."""
    return re.match(r"\n*.*\n", read_text(RUNTIME_FILE)).group()


@cache
def _data_line() -> re.Pattern:
    """The runtime's line that loads its data, matching the literal (group 1) in a bundle."""
    use = next(
        line
        for line in read_text(RUNTIME_FILE).splitlines()
        if _PLACEHOLDER in line and not line.startswith(f"{_PLACEHOLDER} =")
    )
    before, after = use.split(_PLACEHOLDER)
    return re.compile(f"^{re.escape(before)}{LITERAL}{re.escape(after)}$", re.M)


def _find_data(content: str) -> re.Match | None:
    """The data line of the runtime appended to `content`: the last one, since a line like it in
    the plugin's own code comes before. The banner is not needed, so a bundle another owpp made
    is read even if its banner differs."""
    found = list(_data_line().finditer(content))
    return found[-1] if found else None


def embed_runtime(code: str, data: dict) -> str:
    """`code` with the runtime appended, carrying `data`: {"tools": [...], "skills": [...]}."""
    return code + fill(read_text(RUNTIME_FILE), _PLACEHOLDER, json_literal(data))


def runtime_data(content: str | None) -> dict:
    """The tool and skills a bundle's runtime holds: {"tools": [...], "skills": [...]}, empty
    for code with no runtime."""
    m = _find_data(content or "")
    data = json.loads(json.loads(m.group(1))) if m else {}
    return {"tools": data.get("tools", []), "skills": data.get("skills", [])}


def without_runtime_data(content: str) -> str:
    """`content` with its runtime's data line left empty, to compare the code around it."""
    m = _find_data(content)
    return content[: m.start()] + content[m.end() :] if m else content


def runtime_start(content: str) -> int:
    """The index where the runtime appended to `content` starts, or -1 when it has none."""
    return content.find(_banner())
