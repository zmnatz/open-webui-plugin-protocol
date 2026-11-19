# Plugin config library (docs/libraries.md), inserted automatically when a plugin has a
# config.yaml. The file is parsed when the plugin is bundled and embedded as data, so a
# deployed plugin needs no YAML parser and a mistake in it is caught by `owpp check`.
# It is read-only at runtime: change it by redeploying. A value may be an environment template,
# `${NAME}` or `${NAME:-default}`, resolved from the container when it is read (plugin_env).

import copy as _copy
import json as _json

_CONFIG = _json.loads(__CONFIG_DATA__)


def _plugin_config_merge(base: dict, over: dict) -> dict:
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _plugin_config_merge(base[key], value)
        else:
            base[key] = _copy.deepcopy(value)
    return base


def plugin_config(defaults: dict = None) -> dict:
    """The plugin's config.yaml laid over `defaults`: mappings merge key by key, anything else
    (a list, a number, a string) is replaced. `${NAME:-default}` templates in the file's values are
    filled from the container's environment (see plugin_env). A fresh copy, so callers may change it."""
    return _plugin_config_merge(_copy.deepcopy(defaults or {}), plugin_env(_CONFIG))


# end plugin config library
