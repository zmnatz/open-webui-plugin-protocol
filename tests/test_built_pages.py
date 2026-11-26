"""The built function the docs site offers on each example's page (tools/build_docs.py): the file
at the address Open-WebUI imports from, and the button that leads to it."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_docs", ROOT / "tools" / "build_docs.py")
build_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_docs)

# One example's README opens with its credit, above the title.
README = "**Adapted.**\n\n# My Plugin\n\nDoes a thing.\n\n## Test\n"


def built(tmp_path: Path):
    """The example page's text and the function, for a plugin in a folder named `My_Plugin`."""
    plugin = tmp_path / "plugins" / "My_Plugin"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        'protocol: "0.5"\nfunction:\n  title: My Plugin\n  version: 1.0.0\n'
    )
    (plugin / "function.py").write_text("class Filter:\n    pass\n")
    function = build_docs._functions(plugin.parent)["my_plugin"]
    return build_docs._with_built(README, function, tmp_path / "out"), function


def test_the_file_is_the_built_function_named_for_its_id(tmp_path):
    _, function = built(tmp_path)
    # Open-WebUI takes the id from the file's name, so it is the id a deploy would use.
    file = tmp_path / "out" / build_docs.DOWNLOADS / "my_plugin.py"
    assert file.read_text() == function.content


def test_the_button_sits_under_the_title_and_links_to_the_file(tmp_path):
    page, _ = built(tmp_path)
    before, _, after = page.partition("# My Plugin\n\n")
    button, _, rest = after.partition("\n\n")
    assert before == "**Adapted.**\n\n" and rest == "Does a thing.\n\n## Test\n"
    assert button.startswith(build_docs.BUTTON) and 'href="downloads/my_plugin.py"' in button


def test_the_button_stays_out_of_the_pages_summary(tmp_path):
    page, _ = built(tmp_path)
    assert build_docs._summary(page.partition("\n\n")[2]) == "Does a thing."
