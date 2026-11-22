# Shared by the function and the tool: the signed link the Launcher puts a theme in.
#
# The Launcher (tool.py) signs a theme for one user with WEBUI_SECRET_KEY, and the designer page
# (function.py) applies it only when the signature holds. Upstream wrote the format twice, once
# in each file; here it is written once and bundled into both.

import base64
import hashlib
import hmac
import json
import re

_PLACEHOLDER = re.compile(r"__([A-Z][A-Z0-9_]*?)__")


def _fill(template: str, values: dict) -> str:
    """A template with each `__NAME__` replaced by `values["NAME"]`, in one pass, so a value that
    happens to hold a placeholder's text is left as it is. Names not in `values` stay."""
    return _PLACEHOLDER.sub(lambda m: str(values[m[1]]) if m[1] in values else m[0], template)


# Values the Launcher picked (hue, chroma, lightness), signed for one user.
APPLY_TOKEN_PREFIX = "tdp-apply.v1."
# A whole theme the Launcher built: the token carries the theme file's SHA-256, and the chat's
# theme card sends the file itself to the designer, which applies it only when it hashes to that.
THEME_TOKEN_PREFIX = "tdp-apply.v2."


def _token_key() -> bytes | None:
    """WEBUI_SECRET_KEY as bytes, or None when the instance has none (then no link is signed or
    accepted)."""
    from open_webui.env import WEBUI_SECRET_KEY

    return WEBUI_SECRET_KEY.encode("utf-8") if WEBUI_SECRET_KEY else None


def _token_signature(key: bytes, prefix: str, body: str) -> str:
    digest = hmac.new(key, (prefix + body).encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _sign_token(key: bytes, prefix: str, payload: dict) -> str:
    """`prefix` + the payload as base64url JSON + "." + its HMAC-SHA256 under `key`."""
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return prefix + body + "." + _token_signature(key, prefix, body)


def _open_token(key: bytes | None, token) -> tuple[str, dict] | None:
    """(prefix, payload) of a token signed with `key`, or None: no key, not one of ours, not
    ASCII (a link can carry anything, and a real token never does), forged, or not a JSON object.
    Who it is for and when it expires are the caller's to check."""
    token = str(token or "")
    prefix = next(
        (p for p in (APPLY_TOKEN_PREFIX, THEME_TOKEN_PREFIX) if token.startswith(p)), None
    )
    if not key or not prefix or not token.isascii():
        return None
    body, _, sig = token[len(prefix) :].partition(".")
    if not sig or not hmac.compare_digest(sig, _token_signature(key, prefix, body)):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return None
    return (prefix, data) if isinstance(data, dict) else None
