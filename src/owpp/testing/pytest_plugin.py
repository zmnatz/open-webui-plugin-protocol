"""pytest fixtures for plugin tests, registered for every pytest run where owpp is installed.

- `owui`: a fresh MockOpenWebUI, installed for the test and closed after it.
- `plugin_dir`: the plugin folder the test file is in (the nearest plugin.yaml above it).
- `plugin`: that plugin, loaded into `owui` (enabled, with the manifest's valves).

Imports are deferred so that loading this plugin costs nothing in a run that never uses them.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def owui(tmp_path):
    """A mock Open-WebUI (owpp.testing.MockOpenWebUI) for this test."""
    from owpp.testing import MockOpenWebUI

    with MockOpenWebUI(static_dir=tmp_path / "owui-static") as mock:
        yield mock


@pytest.fixture
def plugin_dir(request):
    """The folder of the plugin this test belongs to."""
    from owpp.testing import plugin_folder

    try:
        return plugin_folder(request.path)
    except LookupError as error:
        pytest.fail(f"{error}: the plugin_dir and plugin fixtures are for tests inside a plugin")


@pytest.fixture
def plugin(owui, plugin_dir):
    """This test's plugin, bundled and loaded into `owui` (startup has not run yet)."""
    return owui.load(plugin_dir)
