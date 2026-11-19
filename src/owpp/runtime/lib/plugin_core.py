# Plugin core library (docs/libraries.md). Added automatically by the `routes`, `jobs` and
# `public` libraries (and listable as `include: [core]`): the few lookups every one
# of them, and most plugins, need.

import logging as _logging
import os as _os
import re as _re
import sys as _sys
import time as _time

_core_valves_cache = {}


def plugin_function_id():
    """This function's id, from the module name Open-WebUI gives it
    (function_<id>_<32 hex>), or None outside Open-WebUI."""
    match = _re.fullmatch(r"function_(.+?)(?:_[0-9a-f]{32})?", __name__)
    return match.group(1) if match else None


def plugin_app():
    """Open-WebUI's FastAPI app, or None before it has been imported."""
    return getattr(_sys.modules.get("open_webui.main"), "app", None)


async def plugin_is_active(function_id: str = None) -> bool:
    """Whether this function is still installed and enabled. True when that cannot
    be told (no id, or the lookup failed): callers use it to stop work, and
    stopping on a hiccup would be worse than carrying on."""
    function_id = function_id or plugin_function_id()
    if not function_id:
        return True
    try:
        from open_webui.models.functions import Functions

        function = await Functions.get_function_by_id(function_id)
    except Exception:
        return True
    return bool(function and function.is_active)


async def plugin_stored_valves(valves_cls, function_id: str = None, ttl: float = 0):
    """The function's valves as stored. A running instance only has them applied
    when it handles an event or a chat, so routes and background jobs read them
    here. `ttl` reuses a read for that many seconds (a page that polls)."""
    function_id = function_id or plugin_function_id()
    key = (function_id, valves_cls)
    cached = _core_valves_cache.get(key)
    if ttl and cached and _time.monotonic() - cached[0] < ttl:
        return cached[1]
    stored = {}
    if function_id:
        try:
            from open_webui.models.functions import Functions

            stored = await Functions.get_function_valves_by_id(function_id) or {}
        except Exception:
            import logging

            logging.getLogger(__name__).warning("core: could not read the stored valves", exc_info=True)
    valves = valves_cls(**stored)
    _core_valves_cache[key] = (_time.monotonic(), valves)
    return valves


# Keep in step with TEMPLATE in owpp/envtemplate.py (a test compares them).
_ENV_TEMPLATE = _re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_ENV_ESCAPE = "\x00"


def _env_typed(text: str):
    """A value read from the environment, typed like a YAML 1.2 scalar: 60 is a number, true a
    boolean, null empty; anything else stays text."""
    s = text.strip()
    if _re.fullmatch(r"true|True|TRUE", s):
        return True
    if _re.fullmatch(r"false|False|FALSE", s):
        return False
    if _re.fullmatch(r"null|Null|NULL|~", s):
        return None
    if _re.fullmatch(r"[-+]?[0-9]+", s):
        return int(s)
    if _re.fullmatch(r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][-+]?[0-9]+)?", s):
        return float(s)
    return text


def _env_lookup(name: str, default):
    """The variable if it is set and not empty, else the default (like `${NAME:-default}`), else None."""
    value = _os.environ.get(name)
    return value if value not in (None, "") else default


def plugin_env(value):
    """Resolve `${NAME}` and `${NAME:-default}` templates from the container's environment, in a
    string or in the strings of a dict or list (keys are left alone). A string that is one template
    is typed (`${N:-60}` is the number 60); a template inside a longer string is text. An unset or
    empty variable uses its default; with no default a whole-string template is None (with a
    warning) and an embedded one is empty. `$${` writes a literal `${`."""
    if isinstance(value, dict):
        return {k: plugin_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plugin_env(v) for v in value]
    if not isinstance(value, str):
        return value
    text = value.replace("$${", _ENV_ESCAPE + "{")
    whole = _ENV_TEMPLATE.fullmatch(text)
    if whole:
        found = _env_lookup(whole.group(1), whole.group(2))
        if found is None:
            _logging.getLogger(__name__).warning("core: %s is not set and has no default", whole.group(1))
            return None
        return _env_typed(found)

    def fill(match):
        found = _env_lookup(match.group(1), match.group(2))
        if found is None:
            _logging.getLogger(__name__).warning("core: %s is not set and has no default", match.group(1))
        return found or ""

    return _ENV_TEMPLATE.sub(fill, text).replace(_ENV_ESCAPE, "$")


# end plugin core library
