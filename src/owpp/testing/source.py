"""A plugin's files imported as modules, as an editor reads them, for tests of their logic.

    from owpp.testing import plugin_source

    src = plugin_source("plugins/excalidraw")
    assert src.shared._simplify([...]) == [...]

A file imports the plugin's shared code (`from shared import NAME`) and the libraries
(`from owpp.lib import NAME`). Neither can be the one module every plugin in a test run shares:
two plugins' shared.py would be cached under one name, and the libraries hold each plugin's own
data (its templates, config.yaml, static files). So each plugin gets its own: its libraries are
built from what its bundle would have, as one module, and while each file runs `shared` and
`owpp.lib` in sys.modules are that plugin's, then put back. The modules are named
`_owpp_src_<id>_<file>`.

This is for logic. The function's class, its routes, its events and its tool run through
`owui.load()` (the test harness), which tests the bundle that is deployed. A file that imports
`open_webui` at its top needs a harness open first (the `owui` fixture), so that the real
Open-WebUI is importable.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

from . import plugin_folder

PREFIX = "_owpp_src_"


@dataclass
class PluginSource:
    """The plugin's files as modules: None for a file the plugin does not have. shared.py is in
    both bundles, each with its own libraries, so it is imported for each, as Open-WebUI does:
    `shared` is the function's copy (the tool's when there is no function), `tool_shared` the
    tool's."""

    folder: Path
    shared: types.ModuleType | None
    function: types.ModuleType | None
    tool: types.ModuleType | None
    tool_shared: types.ModuleType | None = None


def _module(name: str, path: Path, text: str | None = None) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    code = path.read_text(encoding="utf-8") if text is None else text
    exec(compile(code, str(path), "exec"), module.__dict__)
    return module


def _swapped(modules: dict[str, types.ModuleType], run):
    """Run `run()` with `modules` in sys.modules under their names, then put back what was there."""
    before = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        return run()
    finally:
        for name, module in before.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def plugin_source(path: Path | str) -> PluginSource:
    """Import the plugin `path` is in (its folder, or any file inside it): shared.py, then
    function.py and tool.py, each with the plugin's own shared and libraries."""
    from ..bundle import library_code

    folder = plugin_folder(path)
    base = f"{PREFIX}{folder.name}_"
    has_shared = (folder / "shared.py").exists()

    def load(name: str) -> tuple[types.ModuleType | None, types.ModuleType | None]:
        """function.py or tool.py, and the copy of shared.py its bundle has."""
        path = folder / f"{name}.py"
        if not path.exists():
            return None, None
        where = Path(f"<owpp.lib as bundled with {folder.name}/{name}.py>")
        lib = _module(f"{base}{name}_lib", where, library_code(folder, name))
        shared = None
        if has_shared:
            shared = _swapped(
                {"owpp.lib": lib}, lambda: _module(f"{base}{name}_shared", folder / "shared.py")
            )
        swap = {"owpp.lib": lib} | ({"shared": shared} if shared is not None else {})
        return _swapped(swap, lambda: _module(f"{base}{name}", path)), shared

    function, function_shared = load("function")
    tool, tool_shared = load("tool")
    return PluginSource(folder, function_shared or tool_shared, function, tool, tool_shared)
