"""`${NAME}` and `${NAME:-default}` templates in a plugin's data (plugin.yaml `jobs:`, config.yaml).

They are never expanded here. The bundle embeds them as written and the plugin resolves them from
the Open-WebUI container's environment when it loads (the `plugin_env` function of the core
library), so a bundle depends only on the plugin folder, and the machine that deploys it can
neither change it nor leak its own environment into the code Open-WebUI stores."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

# Keep in step with _ENV_TEMPLATE in runtime/lib/plugin_core.py (a test compares them).
TEMPLATE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_ESCAPED = "$${"  # a literal ${


def strings(value: Any) -> Iterator[str]:
    """Every string value in `value` (keys are not templates)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def problems(value: Any) -> list[str]:
    """Malformed templates: a `${` that is not `${NAME}` or `${NAME:-default}`."""
    found = []
    for text in strings(value):
        text = text.replace(_ESCAPED, "")
        valid = {m.start() for m in TEMPLATE.finditer(text)}
        for at in (m.start() for m in re.finditer(re.escape("${"), text)):
            if at not in valid:
                found.append(
                    f"{text[at : at + 24]!r} is not a template: write ${{NAME}} or ${{NAME:-default}}"
                )
    return found


def references(value: Any) -> list[tuple[str, str | None]]:
    """The environment variables `value` refers to, with their defaults, in order of first use."""
    seen: dict[str, str | None] = {}
    for text in strings(value):
        for m in TEMPLATE.finditer(text.replace(_ESCAPED, "")):
            seen.setdefault(m.group(1), m.group(2))
    return list(seen.items())


def is_whole(text: str) -> bool:
    """The whole string is one template (so its value is typed: 60 is a number, not "60")."""
    m = TEMPLATE.fullmatch(text)
    return m is not None
