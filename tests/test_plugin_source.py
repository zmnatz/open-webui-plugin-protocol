"""owpp.testing.plugin_source: a plugin's files imported as modules, each plugin with its own
shared.py and libraries."""

from __future__ import annotations

import sys

import pytest
from conftest import EXAMPLES, write_tree

from owpp.testing import MockOpenWebUI, plugin_source


def two_plugins(tmp_path):
    """Two plugins whose shared.py both define NAME, differently."""
    for name in ("one", "two"):
        write_tree(
            tmp_path / name,
            {
                "plugin.yaml": "function:\n  title: T\n",
                "shared.py": f"NAME = {name!r}\n",
                "function.py": "from shared import NAME\n\nclass Filter:\n    name = NAME\n",
            },
        )
    return tmp_path / "one", tmp_path / "two"


def test_each_plugin_gets_its_own_shared_py(tmp_path):
    """Imported as `shared` by both, but one module would give the second plugin the first's."""
    one, two = two_plugins(tmp_path)
    a, b = plugin_source(one), plugin_source(two)
    assert (a.function.Filter.name, b.function.Filter.name) == ("one", "two")
    assert a.function.NAME is a.shared.NAME


def test_sys_modules_is_left_as_it_was(tmp_path):
    one, _ = two_plugins(tmp_path)
    before = {name: sys.modules.get(name) for name in ("shared", "owpp.lib")}
    plugin_source(one)
    assert {name: sys.modules.get(name) for name in ("shared", "owpp.lib")} == before


def test_the_libraries_carry_the_plugins_own_data(tmp_path):
    """A plugin may read its templates or config.yaml as it imports (as excalidraw does), so the
    libraries it imports are built as its bundle has them."""
    write_tree(
        tmp_path / "p",
        {
            "plugin.yaml": "function:\n  title: T\n",
            "config.yaml": "greeting: hi\n",
            "templates/page.html": "<p>page</p>\n",
            "function.py": (
                "from owpp.lib import plugin_config, plugin_template_text\n\n"
                'PAGE = plugin_template_text("page.html")\nGREETING = plugin_config()["greeting"]\n\n'
                "class Filter:\n    pass\n"
            ),
        },
    )
    src = plugin_source(tmp_path / "p")
    assert (src.function.PAGE, src.function.GREETING) == ("<p>page</p>\n", "hi")
    assert src.shared is None and src.tool is None


def test_shared_py_is_imported_once_per_bundle_like_open_webui_does():
    """The function and the tool are separate modules there, each with a copy of shared.py."""
    with MockOpenWebUI():
        src = plugin_source(EXAMPLES / "excalidraw" / "tests")  # any path inside the plugin
    assert src.function and src.tool and src.shared and src.tool_shared
    assert src.shared is not src.tool_shared
    assert src.function._load is src.shared._load and src.tool._load is src.tool_shared._load
    assert "Excalidraw" in src.function.VIEWER


@pytest.mark.parametrize(
    "name", sorted(p.name for p in EXAMPLES.iterdir() if (p / "plugin.yaml").exists())
)
def test_every_example_imports(name):
    with MockOpenWebUI():
        plugin_source(EXAMPLES / name)
