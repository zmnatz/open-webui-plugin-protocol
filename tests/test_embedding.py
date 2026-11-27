"""The runtime embedded in a bundle (owpp.embedding): written with its data, read back, found
again, and left out when code is compared."""

from __future__ import annotations

import ast
import json
import random

import pytest

from owpp.embedding import embed_runtime, runtime_data, runtime_start, without_runtime_data
from owpp.unbundle import unbundle

CODE = '"""\ntitle: T\n"""\n\n\nclass Filter:\n    pass\n'
EMPTY = {"tools": [], "skills": []}

# What could end the data early, or be taken for the format around it.
AWKWARD = (
    '")\n',
    '\\")\n',
    '")',
    '"',
    "\\",
    "\n",
    "\r\n",
    "\t",
    "\x00",
    "\x85",
    "\u2028",
    "\u2029",
    "é 🎨",
    '_PLUGIN = _json.loads("{}")\n',
    "__PLUGIN_DATA__",
    "\n\n# =============================================================== plugin runtime\n",
    "a",
    " ",
)


def _text(rng: random.Random) -> str:
    return "".join(
        rng.choice(AWKWARD) if rng.random() < 0.8 else chr(rng.randrange(1, 0xD800))
        for _ in range(rng.randrange(8))
    )


def _value(rng: random.Random, depth: int = 0):
    kind = rng.randrange(6 if depth < 3 else 4)
    if kind == 0:
        return rng.choice([None, True, False, rng.randrange(-(10**9), 10**9)])
    if kind < 4:
        return _text(rng)
    if kind == 4:
        return [_value(rng, depth + 1) for _ in range(rng.randrange(4))]
    return {_text(rng): _value(rng, depth + 1) for _ in range(rng.randrange(4))}


def _plugin_data(rng: random.Random) -> dict:
    def items() -> list:
        return [
            {"id": _text(rng), "content": _text(rng), "extra": _value(rng)}
            for _ in range(rng.randrange(4))
        ]

    return {"tools": items(), "skills": items()}


def _loaded_by_python(bundle: str):
    """The string the runtime's `_PLUGIN` line hands to json.loads, as Python parses it."""
    (value,) = [
        node.value
        for node in ast.parse(bundle).body
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_PLUGIN"
    ]
    return ast.literal_eval(value.args[0])


@pytest.mark.parametrize("seed", range(300))
def test_any_plugin_data_round_trips(seed):
    rng = random.Random(seed)
    data, other = _plugin_data(rng), _plugin_data(rng)
    bundle = embed_runtime(CODE, data)

    assert runtime_data(bundle) == data
    assert bundle[: runtime_start(bundle)] == CODE
    assert without_runtime_data(bundle) == without_runtime_data(embed_runtime(CODE, other))
    own = unbundle(bundle)
    assert (own.code, own.tools, own.skills) == (CODE, data["tools"], data["skills"])


@pytest.mark.parametrize("text", AWKWARD)
def test_awkward_text_round_trips_and_is_what_the_runtime_loads(text):
    data = {
        "tools": [{"id": "t", "content": f"x = {text}{text}"}],
        "skills": [{"id": text, "files": [{"path": "SKILL.md", "content": text}]}],
    }
    bundle = embed_runtime(CODE, data)
    assert runtime_data(bundle) == data
    assert runtime_data(embed_runtime(CODE, EMPTY)) == EMPTY
    assert runtime_data(f'x = ")"\n{bundle}y = ")"\n') == data
    assert json.loads(_loaded_by_python(bundle)) == data


def test_a_tools_content_may_embed_a_runtime_of_its_own():
    """A tool carries the runtime too, so the function's data holds a whole embedded runtime."""
    ids = {"tools": [{"id": "t"}], "skills": []}
    data = {"tools": [{"id": "t", "content": embed_runtime(CODE, ids)}], "skills": []}
    bundle = embed_runtime(CODE, data)
    assert runtime_data(bundle) == data
    assert runtime_data(runtime_data(bundle)["tools"][0]["content"]) == ids
    assert bundle[: runtime_start(bundle)] == CODE


@pytest.mark.parametrize("content", [None, "", CODE])
def test_code_without_a_runtime_has_no_data_and_nothing_to_strip(content):
    assert runtime_data(content) == EMPTY
    assert runtime_start(content or "") == -1
    assert without_runtime_data(content or "") == (content or "")


def test_stripping_leaves_the_rest_of_the_bundle_to_compare():
    changed = CODE.replace("pass", "x = 1")
    assert without_runtime_data(embed_runtime(CODE, EMPTY)) != without_runtime_data(
        embed_runtime(changed, EMPTY)
    )


def test_data_is_read_from_a_bundle_whose_banner_differs():
    """A function another owpp deployed is still read when only its banner is not this one's."""
    data = {"tools": [{"id": "t"}], "skills": []}
    bundle = embed_runtime(CODE, data)
    start = runtime_start(bundle)
    older = bundle[:start] + bundle[start:].replace("plugin runtime", "an older runtime", 1)
    assert runtime_start(older) == -1
    assert runtime_data(older) == data


def test_the_appended_runtimes_data_is_read_not_a_line_like_it_in_the_plugins_code():
    own = CODE + '_PLUGIN = _json.loads("not json")\n'
    data = {"tools": [{"id": "t"}], "skills": []}
    bundle = embed_runtime(own, data)
    assert runtime_data(bundle) == data
    assert own in without_runtime_data(bundle)
