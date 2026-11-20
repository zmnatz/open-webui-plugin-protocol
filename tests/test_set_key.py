"""Changing one value in plugin.yaml text: comments, layout, quoting and line endings kept."""

from __future__ import annotations

import pytest

from owpp.errors import OwppError
from owpp.manifest import set_key

SHA = "a" * 40
NEW = "b" * 40


@pytest.mark.parametrize(
    ("before", "key", "value", "after", "expected"),
    [
        # Block style: replaced in place, comment and quotes kept.
        (
            f'# pinned\nsource:\n  git: G\n  ref: "{SHA}" # reviewed\n',
            "source.ref",
            NEW,
            "git",
            f'# pinned\nsource:\n  git: G\n  ref: "{NEW}" # reviewed\n',
        ),
        # Block style: added after `after`.
        (
            "source:\n  git: G\n  path: p\n",
            "source.ref",
            NEW,
            "git",
            f"source:\n  git: G\n  ref: {NEW}\n  path: p\n",
        ),
        # After a key whose value is nested: after its lines.
        (
            "function:\n  valves:\n    A: 1\n  license: MIT\n",
            "function.version",
            "1.0.0",
            "valves",
            "function:\n  valves:\n    A: 1\n  version: 1.0.0\n  license: MIT\n",
        ),
        # No `after` key: first in the mapping.
        (
            "function:\n  license: MIT\n",
            "function.version",
            "1.0.0",
            "title",
            "function:\n  version: 1.0.0\n  license: MIT\n",
        ),
        # A one-line mapping: replaced, or added after `after`, or first.
        (
            f"source: {{git: G, ref: {SHA}}}  # pin\n",
            "source.ref",
            NEW,
            "git",
            f"source: {{git: G, ref: {NEW}}}  # pin\n",
        ),
        (
            "source: {git: G, path: p}\n",
            "source.ref",
            NEW,
            "git",
            f"source: {{git: G, ref: {NEW}, path: p}}\n",
        ),
        (
            "function: {license: MIT}\n",
            "function.version",
            "1.0.0",
            "title",
            "function: {version: 1.0.0, license: MIT}\n",
        ),
        ("function: {}\n", "function.version", "1.0.0", None, "function: {version: 1.0.0}\n"),
        # CRLF stays CRLF, on the changed line and on an added one.
        (
            "source:\r\n    git: G  # where\r\n",
            "source.ref",
            NEW,
            "git",
            f"source:\r\n    git: G  # where\r\n    ref: {NEW}\r\n",
        ),
        (
            f"source:\r\n  ref: {SHA}\r\n",
            "source.ref",
            NEW,
            None,
            f"source:\r\n  ref: {NEW}\r\n",
        ),
        # A top-level key: replaced, or added before the first key (after leading comments).
        (
            'protocol: "0.1" # when we started\nfunction: {}\n',
            "protocol",
            '"0.2"',
            None,
            'protocol: "0.2" # when we started\nfunction: {}\n',
        ),
        (
            "# notes\n\nfunction: {}\n",
            "protocol",
            '"0.2"',
            None,
            '# notes\n\nprotocol: "0.2"\nfunction: {}\n',
        ),
    ],
)
def test_sets_one_value_and_changes_no_other_line(before, key, value, after, expected):
    assert set_key(before, key, value, after=after) == expected


@pytest.mark.parametrize(
    ("text", "key", "message"),
    [
        ("source: {git: G,\n  path: p}\n", "source.ref", "several lines; edit plugin.yaml by hand"),
        ("function:\n  title: T\n", "source.ref", "has no `source:` section"),
        ("source: just text\n", "source.ref", "not a mapping; edit plugin.yaml by hand"),
        ("source:\n  ref:\n    nested: 1\n", "source.ref", "not a one-line value"),
        ("a: 1\n", "a.b.c", "only `key` or `mapping.key`"),
    ],
)
def test_refuses_what_it_cannot_change_in_place(text, key, message):
    with pytest.raises(OwppError, match=message):
        set_key(text, key, NEW)
