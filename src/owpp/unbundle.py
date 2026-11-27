"""The reverse of bundling, for `owpp import`: a function's code with what owpp (or the Shared
Assets Protocol) put into it taken back out.

- **owpp's libraries**, which `link` puts right after the docstring header, one after the other,
  each ending in its `# end ... library` line: each becomes a name in `include:`, and the data
  it carries becomes the file or key it was made from (templates/, static/, assets/,
  config.yaml, `jobs:`). A block is taken only where `link` puts it, and only when it starts as
  owpp's copy does, so a block from an older owpp is recognised too.
- **The plugin runtime**, which the bundler appends to a function with a tool or skills: it goes,
  and the tool and skills in its data come back (`tools`, `skills`).
- **The Shared Assets Protocol's blocks** (live_reload, shared_assets) anywhere in the code, but
  only when they are byte-identical to owpp's copy, as the protocol requires: they become
  `include:` too. A different copy is the plugin's own code, and stays.

What is left is the plugin's own code. Nothing else is changed.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .libraries import BY_NAME, LIBRARIES, VENDORED, Library, _text, closure

# The runtime's first line, as the bundler appends it (src/owpp/runtime/plugin_runtime.py).
_RUNTIME_START = (
    "\n\n# =============================================================== plugin runtime\n"
)
_RUNTIME_DATA = re.compile(r'^_PLUGIN = _json\.loads\(("(?:[^"\\\n]|\\.)*")\)$', re.M)
_HEADER = re.compile(r'\s*"""[\s\S]*?"""\n')
_FUTURE = re.compile(r"(?:from __future__ import [^\n]+\n)+")
# A JSON string literal, as json_literal writes it.
_LITERAL = r'("(?:[^"\\\n]|\\.)*")'
# What the protocol says to copy: its blocks from their first banner line to their end line.
_BANNER = re.compile(r"^# =+\n", re.M)
# Where a library carries data, the folder or key it came from.
_DATA_FROM = {
    "static": "static/",
    "templates": "templates/",
    "assets": "assets/",
    "config": "config.yaml",
}


@dataclass
class Unbundled:
    """A function's own code, and what was taken out of it."""

    code: str
    include: list[str] = field(default_factory=list)
    # Each library's data: {library name: data} (static, templates, assets, config, jobs).
    data: dict[str, Any] = field(default_factory=dict)
    tools: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    found: list[str] = field(default_factory=list)  # every library taken out, in order


def _lines(lib: Library, n: int = 3) -> str:
    return "".join(_text(lib).splitlines(keepends=True)[:n])


def _data(lib: Library, block: str) -> Any:
    """The data `fill` put into a library's block, or None when it has none."""
    if not lib.placeholder:
        return None
    use = next(
        (
            line
            for line in _text(lib).splitlines()
            if lib.placeholder in line and not line.startswith(f"{lib.placeholder} =")
        ),
        None,
    )
    if use is None:
        return None
    before, _, after = use.partition(lib.placeholder)
    m = re.search(f"^{re.escape(before)}{_LITERAL}{re.escape(after)}$", block, re.M)
    return json.loads(json.loads(m.group(1))) if m else None


def _end_of(code: str, marker: str, start: int) -> int:
    """The index after the line holding `marker` at or past `start`, or -1."""
    at = code.find(marker, start)
    if at < 0:
        return -1
    newline = code.find("\n", at)
    return len(code) if newline < 0 else newline + 1


def _linked(code: str, start: int) -> tuple[list[tuple[Library, str]], int]:
    """The library blocks `link` put at `start` (after the header and any hoisted
    `from __future__` lines), each as "\\n" + its text, in the catalogue's order."""
    blocks: list[tuple[Library, str]] = []
    pos = start
    remaining = list(LIBRARIES)
    while remaining:
        for i, lib in enumerate(remaining):
            if not code.startswith("\n" + _lines(lib), pos):
                continue
            end = _end_of(code, lib.end, pos)
            block = code[pos:end] if end > 0 else ""
            others = [o.end for o in LIBRARIES if o is not lib]
            if block and not any(o in block for o in others):
                blocks.append((lib, block))
                pos = end
                remaining = remaining[i + 1 :]
                break
        else:
            break
    return blocks, pos


def _protocol_body(lib: Library) -> str:
    """A vendored block as the protocol says to copy it: from its first banner to its end."""
    text = _text(lib)
    m = _BANNER.search(text)
    return text[m.start() :] if m else text


def unbundle(content: str) -> Unbundled:
    """`content` without owpp's libraries and runtime, and the protocol's byte-identical blocks
    (see the module's docstring)."""
    code, tools, skills = content, [], []
    at = code.find(_RUNTIME_START)
    if at >= 0:
        m = _RUNTIME_DATA.search(code, at)
        if m:
            data = json.loads(json.loads(m.group(1)))
            tools, skills = data.get("tools", []), data.get("skills", [])
        code = code[:at]
    header = _HEADER.match(code)
    found: list[str] = []
    data: dict[str, Any] = {}
    if header:
        future = _FUTURE.match(code, header.end())
        start = future.end() if future else header.end()
        blocks, end = _linked(code, start)
        for lib, block in blocks:
            found.append(lib.name)
            if (value := _data(lib, block)) is not None:
                data[lib.name] = value
        code = code[:start] + code[end:]
    for name in VENDORED:
        lib = BY_NAME[name]
        body = _protocol_body(lib)
        if name not in found and code.count(body) == 1:
            code = code.replace(body, "")
            found.append(name)
    found = [lib.name for lib in LIBRARIES if lib.name in found]
    return Unbundled(code, _include(found, data), data, tools, skills, found)


def _include(found: list[str], data: dict[str, Any]) -> list[str]:
    """The `include:` that gives a bundle the libraries `found` again: without the ones the
    plugin's files turn on, or that another one pulls in."""
    held = {_DATA_FROM[name] for name in data if name in _DATA_FROM}
    if "jobs" in data and data["jobs"] != BY_NAME["jobs"].default:
        held.add("jobs:")
    on = {lib.name for lib in LIBRARIES if lib.on_when in held}
    pulled = set(closure([p for name in [*found, *on] for p in BY_NAME[name].pulls_in]))
    return [name for name in found if name not in on and name not in pulled]


def files_of(entries: dict[str, dict] | list[dict]) -> dict[str, str | bytes]:
    """{path: text or bytes} from the runtime's file entries ({path: {content, encoding?}} or
    [{path, content, encoding?}])."""
    items = entries.items() if isinstance(entries, dict) else ((e["path"], e) for e in entries)
    return {
        path: base64.b64decode(e["content"]) if e.get("encoding") == "base64" else e["content"]
        for path, e in items
    }
