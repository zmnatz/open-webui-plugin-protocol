"""Test plugins against a mock Open-WebUI (docs/testing.md).

    from owpp.testing import MockOpenWebUI

    with MockOpenWebUI() as owui:
        plugin = owui.load("plugins/my_plugin")
        owui.startup()

Under pytest the `owui` and `plugin` fixtures do this for you (owpp.testing.pytest_plugin),
and `owpp test` runs each plugin's tests/ folder.
"""

from .mock import LoadedPlugin, LoadedTool, MockOpenWebUI, Record

__all__ = ["LoadedPlugin", "LoadedTool", "MockOpenWebUI", "Record", "plugin_folder"]


def plugin_folder(path):
    """The plugin folder (the nearest one with a plugin.yaml) that `path` is in."""
    from pathlib import Path

    path = Path(path).resolve()
    for folder in (path, *path.parents):
        if (folder / "plugin.yaml").is_file():
            return folder
    raise LookupError(f"{path} is not inside a plugin folder (no plugin.yaml above it)")
