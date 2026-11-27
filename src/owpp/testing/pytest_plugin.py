"""pytest fixtures for plugin tests, registered for every pytest run where owpp is installed.

- `owui`: a fresh MockOpenWebUI, installed for the test and closed after it.
- `plugin_dir`: the plugin folder the test file is in (the nearest plugin.yaml above it).
- `plugin`: that plugin, loaded into `owui` (enabled, with the manifest's valves).

Every `owui` reads git through one Sources, so what `owui.load()` fetched is kept for the session
and deleted when it ends.

Imports are deferred so that loading this plugin costs nothing in a run that never uses them.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def _owpp_session_sources():
    """The session's Sources, which every `owui` reads git through: each pinned file is
    fetched once. Closed once the session is done."""
    from owpp.sources import Sources

    with Sources() as sources:
        yield sources


@pytest.fixture
def owui(tmp_path, _owpp_session_sources):
    """A mock Open-WebUI (owpp.testing.MockOpenWebUI) for this test."""
    from owpp.testing import MockOpenWebUI

    static = tmp_path / "owui-static"
    with MockOpenWebUI(static_dir=static, sources=_owpp_session_sources) as mock:
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
