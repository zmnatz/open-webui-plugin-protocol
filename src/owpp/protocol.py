"""The version of the plugin format a manifest was written for.

A manifest's `protocol:` is a quoted major.minor string: it tracks the owpp package's
major.minor, so 0.1 plugins (written before the key existed, when there was no key at all)
can be told from a 0.2 one. A plugin that claims a newer version cannot be read by an older
owpp: refuse it rather than guess at keys whose meaning may have changed.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import OwppError

VERSION = "0.2"
OLDEST = "0.1"  # a manifest with no `protocol:` was written before the key existed
CURRENT = tuple(map(int, VERSION.split(".")))
FORMAT = re.compile(r"^(\d+)\.(\d+)$")


def parse(value: Any, path: str = "plugin.yaml") -> str:
    """The declared protocol as a canonical major.minor string. No key means the first version."""
    if value is None:
        return OLDEST
    if not isinstance(value, str) or not (m := FORMAT.fullmatch(value)):
        raise OwppError(
            f'{path}: `protocol:` must be a quoted major.minor string, e.g. `protocol: "{VERSION}"`'
        )
    major, minor = (int(group) for group in m.groups())
    version = f"{major}.{minor}"
    if (major, minor) > CURRENT:
        raise OwppError(
            f"{path}: protocol {version} is newer than owpp supports ({VERSION}); upgrade owpp"
        )
    return version


def report(path: str, value: Any) -> tuple[str | None, str | None]:
    """A (warning, note) pair for `owpp check`: a missing key is a 0.1 plugin that should be
    migrated; an older declared version is accepted, but the migration is pointed out."""
    if value is None:
        return (
            f"{path}: no `protocol:` key (it predates {VERSION}); run `owpp migrate` to add it",
            None,
        )
    version = parse(value, path)
    if version == VERSION:
        return None, None
    return (
        None,
        f"{path}: protocol {version}, older than {VERSION}; run `owpp migrate` to upgrade it",
    )
