"""The docs site's pages of built functions (tools/build_docs.py): the file at the address
Open-WebUI imports from, the code to copy, and what is left to do after saving it."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_docs", ROOT / "tools" / "build_docs.py")
build_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_docs)


def built(tmp_path: Path, cls: str, header: str = "", extra: str = "", body: str = "pass"):
    """The page, its code block and the function, of a plugin whose function defines
    `class <cls>`."""
    plugin = tmp_path / "plugins" / "My_Plugin"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        'protocol: "0.5"\n'
        "function:\n"
        "  title: My Plugin\n"
        "  version: 1.0.0\n"
        "  description: Does a thing.\n" + header + extra
    )
    (plugin / "function.py").write_text(f"class {cls}:\n    {body}\n")
    function = build_docs._functions(plugin.parent)["my_plugin"]
    text, block = build_docs._built_page(function, tmp_path / "out")
    return text, block, function


def test_the_address_serves_the_built_function_under_its_id(tmp_path):
    text, block, function = built(tmp_path, "Filter")
    # Open-WebUI takes the id from the file's name, so it is the id a deploy would use.
    path = f"{build_docs.DOWNLOADS}/my_plugin.py"
    assert (tmp_path / "out" / path).read_text() == function.content
    assert f"\n{build_docs.SITE_URL}{path}\n" in text
    assert block == f'\n```python title="my_plugin.py"\n{function.content.rstrip()}\n```\n'


def test_a_fence_in_the_code_does_not_end_the_block(tmp_path):
    body = '''HELP = """
```
[not a link](nowhere.md)
```
"""'''
    _, block, function = built(tmp_path, "Filter", body=body)
    assert block.startswith('\n````python title="my_plugin.py"\n')
    assert block.endswith("\n````\n")
    assert function.content.rstrip() in block


@pytest.mark.parametrize(
    ("cls", "header", "global_step"),
    [
        ("Filter", "", True),
        ("Filter", "  global: false\n", False),
        ("Action", "", False),
        ("Action", "  global: true\n", True),
        ("Event", "", False),
    ],
)
def test_it_says_to_make_global_what_a_deploy_would(tmp_path, cls, header, global_step):
    text, _, _ = built(tmp_path, cls, header)
    assert "switch it on" in text
    assert ("switch on **Global**" in text) is global_step


def test_it_names_the_settings_and_version_the_plugin_needs(tmp_path):
    text, _, _ = built(
        tmp_path,
        "Event",
        "  required_open_webui_version: 0.11.3\n",
        "requires:\n  iframe_sandbox_allow_same_origin: true\n",
    )
    assert "**iframe Sandbox Allow Same Origin**" in text
    assert "needs Open WebUI 0.11.3 or newer" in text


def test_it_asks_for_no_setting_a_plugin_does_not_need(tmp_path):
    text, _, _ = built(tmp_path, "Event")
    assert "Sandbox" not in text and "or newer" not in text
