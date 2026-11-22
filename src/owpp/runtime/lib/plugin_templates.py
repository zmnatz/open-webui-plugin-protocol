# Plugin templates library (docs/libraries.md), inserted automatically when a plugin has a
# templates/ folder. The files are embedded in the bundle and never served: the function reads them
# (plugin_template_text) and renders them itself, for example a page it fills in for the signed-in
# user. Files that are simply served belong in static/.

import base64 as _base64
import json as _json

# {path: {"content", "encoding"?}}
__TEMPLATES_DATA__ = '{}'  # for imports; the bundler drops it
_TEMPLATES = _json.loads(__TEMPLATES_DATA__)


def plugin_template_files() -> list:
    return sorted(_TEMPLATES)


def plugin_template_bytes(path: str) -> bytes:
    entry = _TEMPLATES.get(path)
    if entry is None:
        raise FileNotFoundError(path)
    if entry.get("encoding") == "base64":
        return _base64.b64decode(entry["content"])
    return entry["content"].encode("utf-8")


def plugin_template_text(path: str) -> str:
    """A template as text, to be filled in."""
    return plugin_template_bytes(path).decode("utf-8")


# end plugin templates library
