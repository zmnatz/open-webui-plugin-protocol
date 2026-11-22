# Plugin assets library (docs/libraries.md), inserted automatically when a plugin has an
# assets/ folder. It publishes assets/loader.js and assets/custom.css as this plugin's
# fragments of the Shared Assets Protocol (the shared asset block above, which stays
# byte-identical), so the script and the stylesheet are files and not Python strings.
# Use it as `class Event(PluginAssets)`. Needs the core, events and shared_assets libraries,
# which the bundler adds.

import json as _json
import re as _asset_re
from typing import TYPE_CHECKING as _TYPE_CHECKING

from .plugin_events import PluginEvents, on
from .shared_assets import CUSTOM_CSS_PATH, LOADER_PATH, asset_register, asset_withdraw_deleted

if _TYPE_CHECKING:  # optional: used only when the live_reload library is in the bundle too
    from .live_reload import reload_active, reload_bootstrap, reload_on_event

# {"id": "<plugin id>", "order": 0, "wrap": true, "files": {"loader.js": text, "custom.css": text}}
__ASSETS_DATA__ = '{"id": "", "order": 0, "wrap": true, "files": {}}'  # for imports; the bundler drops it
_ASSETS = _json.loads(__ASSETS_DATA__)
_ASSET_PATHS = {"loader.js": LOADER_PATH, "custom.css": CUSTOM_CSS_PATH}
# instance: the Event (its asset_vars() fills __NAME__ placeholders); app: where we registered;
# active: without live_reload, whether the function is enabled; cache: {file: (variables, fragment)}
_asset_state = {"instance": None, "app": None, "active": True, "cache": {}}


def _asset_markers(name: str) -> tuple:
    if name == "custom.css":
        return f"/* owui:{_ASSETS['id']}:start */", f"/* owui:{_ASSETS['id']}:end */"
    return f"// owui:{_ASSETS['id']}:start", f"// owui:{_ASSETS['id']}:end"


def _asset_render(name: str) -> str:
    """The fragment, rebuilt only when the plugin's variables change (it runs on every page load)."""
    instance = _asset_state["instance"]
    variables = instance.asset_vars() if hasattr(instance, "asset_vars") else {}
    key = tuple(sorted((str(k), str(v)) for k, v in (variables or {}).items()))
    cached = _asset_state["cache"].get(name)
    if cached and cached[0] == key:
        return cached[1]
    text = _ASSETS["files"][name]
    if key:
        # One pass over the file: a value is never read again, so one that holds another
        # placeholder's text (a valve someone typed) is served as written. Longest names first,
        # so no name matches inside a longer one.
        values = dict(key)
        names = sorted(values, key=len, reverse=True)
        pattern = _asset_re.compile("|".join(_asset_re.escape(f"__{n}__") for n in names))
        text = pattern.sub(lambda m: values[m.group()[2:-2]], text)
    if name == "loader.js" and _ASSETS["wrap"]:
        # The protocol's rule: one plugin's names and errors must not stop the others in the shared
        # file, so the script runs in its own function scope, in strict mode, inside a try/catch.
        label = _json.dumps(f"[{_ASSETS['id']}]")
        text = (
            "(function () {\n  \"use strict\";\n  try {\n"
            + text.strip()
            + "\n  } catch (e) {\n    console.error("
            + label
            + ", e);\n  }\n})();"
        )
    start, end = _asset_markers(name)
    fragment = f"{start}\n{text.strip()}\n{end}"
    _asset_state["cache"][name] = (key, fragment)
    return fragment


def _asset_enabled(app) -> bool:
    if "reload_active" in globals():  # the live_reload library is included
        return reload_active(app)
    return _asset_state["active"]


def _asset_producer(app, name: str):
    return lambda: _asset_render(name) if _asset_enabled(app) else ""


def plugin_assets_register(app) -> None:
    """Publish this plugin's fragments. Idempotent. A producer returns "" while the plugin is
    switched off, which is how the protocol withdraws a fragment."""
    if app is None:
        return
    for name, path in _ASSET_PATHS.items():
        if name in _ASSETS["files"]:
            start, end = _asset_markers(name)
            asset_register(app, path, start, end, _asset_producer(app, name), _ASSETS["order"])
    _asset_state["app"] = app


def register(app) -> None:
    """What the live_reload library calls when the plugin loads on any container."""
    plugin_assets_register(app)


class PluginAssets(PluginEvents):
    """Mixin for the Event function of a plugin with an assets/ folder: `class Event(PluginAssets)`.
    Define `asset_vars(self) -> dict` to fill `__NAME__` placeholders in the files from the
    valves (values must be strings). It is a PluginEvents class, so `@on` handlers of your own
    work beside it; if you override `__init__` or `event`, call `super()`."""

    def __init__(self):
        super().__init__()  # creates self.valves
        _asset_state["instance"] = self
        if "reload_bootstrap" in globals():
            reload_bootstrap()

    async def event(
        self,
        event: dict = None,
        __event_name__: str = None,
        __id__: str = None,
        __app__=None,
        __request__=None,
        **kwargs,
    ):
        _asset_state["instance"] = self
        if __app__ is not None:
            if "reload_on_event" in globals():
                await reload_on_event(__app__, event, __event_name__)
            else:
                asset_withdraw_deleted(__app__, event, __event_name__)
            if _asset_state["app"] is not __app__:
                plugin_assets_register(__app__)
        await super().event(
            event,
            __event_name__=__event_name__,
            __id__=__id__,
            __app__=__app__,
            __request__=__request__,
            **kwargs,
        )

    # Without live_reload (which tracks this itself), the fragments follow this function's
    # own enable and disable events.
    @on("function.disable_started", own=True)
    def _assets_switch_off(self):
        if "reload_active" not in globals():
            _asset_state["active"] = False

    @on("function.enable_started", own=True)
    def _assets_switch_on(self):
        if "reload_active" not in globals():
            _asset_state["active"] = True


# end plugin assets library
