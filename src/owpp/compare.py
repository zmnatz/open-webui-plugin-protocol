"""The comparison of two copies of a function's code, as Open-WebUI stores them.

The deploy compares a live function with a new bundle, and `owpp check --since` compares two
bundles from git. Both sides get Open-WebUI's import rewrite first, so a bundle compares the same
as the copy Open-WebUI stored of it. The function, its tool and each skill are versioned apart,
so each is a part of the comparison, with its old and new version. What to say about a change,
and whose version it is to bump, is the caller's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .bundle import parse_skill
from .embedding import runtime_data, without_runtime_data
from .openwebui import replace_imports
from .versioning import is_older, version_of


@dataclass(frozen=True)
class Part:
    """The function (`id` is ""), its tool or one skill, and how it changed: `status` is new,
    removed, changed or unchanged. A version is "" when the part has none, or is absent."""

    kind: str
    id: str
    status: str
    old_version: str = ""
    new_version: str = ""


@dataclass(frozen=True)
class Comparison:
    """What changed from `old` to `new`. `unchanged` holds when the stored code is the same.
    `parts` has the function first, then each tool and each skill, by id. `downgrades` are the
    parts whose version goes back."""

    unchanged: bool
    parts: tuple[Part, ...]

    @property
    def downgrades(self) -> tuple[Part, ...]:
        return tuple(p for p in self.parts if is_older(p.new_version, p.old_version))


def compare(old: str | None, new: str) -> Comparison:
    """`old` is None when there is no copy yet: every part of `new` is then new."""
    a = None if old is None else _norm(replace_imports(old))
    b = _norm(replace_imports(new))
    function_status = (
        "new" if a is None else "unchanged" if _own_code(a) == _own_code(b) else "changed"
    )
    parts = [Part("function", "", function_status, version_of(a), version_of(b))]
    parts += _items("tool", _tools_of(a), _tools_of(b), _tool_version)
    parts += _items("skill", _skills_of(a), _skills_of(b), _skill_version)
    return Comparison(unchanged=a == b, parts=tuple(parts))


def _items(kind: str, old: dict, new: dict, version) -> list[Part]:
    parts = []
    for item_id in sorted(set(old) | set(new)):
        a, b = old.get(item_id), new.get(item_id)
        if a is None:
            status = "new"
        elif b is None:
            status = "removed"
        else:
            status = "unchanged" if _same(a, b) else "changed"
        parts.append(Part(kind, item_id, status, version(a) if a else "", version(b) if b else ""))
    return parts


def _norm(s: str) -> str:
    return s.replace("\r\n", "\n").rstrip()


def _own_code(content: str) -> str:
    """A function's code without the tool and skills it embeds, which are versioned apart."""
    return without_runtime_data(content)


def _tools_of(content: str | None) -> dict[str, dict]:
    return {t["id"]: t for t in runtime_data(content)["tools"] if not t.get("self")}


def _skills_of(content: str | None) -> dict[str, dict]:
    return {s["id"]: s for s in runtime_data(content)["skills"]}


def _tool_version(tool: dict) -> str:
    return version_of(tool.get("content"))


def _skill_version(skill: dict) -> str:
    root = next((f for f in skill.get("files", []) if f.get("path") == "SKILL.md"), None)
    if not root or "content" not in root:
        return ""
    fm, _ = parse_skill(skill["id"], root["content"])
    return str(fm.get("version") or "")


def _same(a: object, b: object) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
