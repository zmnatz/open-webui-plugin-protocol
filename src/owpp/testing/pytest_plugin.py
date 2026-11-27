"""pytest fixtures for plugin tests, registered for every pytest run where owpp is installed.

- `owui`: the test harness (owpp.testing.Harness): the real Open-WebUI, as it was just after its
  startup, for this test.
- `plugin_dir`: the plugin folder the test file is in (the nearest plugin.yaml above it).
- `plugin`: that plugin, loaded into `owui` (enabled, with the manifest's valves).

Every `owui` reads git through one Sources, so what `owui.load()` fetched is kept for the session
and deleted when it ends.

Imports are deferred so that loading this plugin costs nothing in a run that never uses them.
"""

from __future__ import annotations

import pytest


def pytest_configure(config):
    # Open-WebUI's own code warns about its dependencies (pydantic, pyasn1, SQLAlchemy
    # reflection): not the plugin's business.
    for module in ("open_webui", "ldap3", "sqlalchemy", "pydantic", "jwt", "typer", "alembic"):
        config.addinivalue_line("filterwarnings", f"ignore::DeprecationWarning:{module}")
    config.addinivalue_line("filterwarnings", "ignore::UserWarning:open_webui")
    config.addinivalue_line("filterwarnings", "ignore:.*unsupported reflection")
    config.addinivalue_line("filterwarnings", "ignore:Table '_alembic_tmp")
    config.addinivalue_line(
        "markers",
        "fresh_open_webui: give this test a new Open-WebUI, imported and started again",
    )


@pytest.fixture(scope="session")
def _owpp_session_sources():
    """The session's Sources, which every `owui` reads git through: each pinned file is
    fetched once. Closed once the session is done."""
    from owpp.sources import Sources

    with Sources() as sources:
        yield sources


@pytest.fixture
def owui(request, _owpp_session_sources):
    """The test harness (owpp.testing.Harness) for this test. A test marked
    `@pytest.mark.fresh_open_webui`, or every test when OWPP_FRESH_OPEN_WEBUI is set, gets a new
    Open-WebUI, imported and started again (slower)."""
    import os

    from owpp.testing import Harness

    fresh = bool(os.environ.get("OWPP_FRESH_OPEN_WEBUI")) or (
        request.node.get_closest_marker("fresh_open_webui") is not None
    )
    with Harness(sources=_owpp_session_sources, fresh=fresh) as harness:
        yield harness


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
