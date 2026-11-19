# Shared by the function and the tool (both bundles start with this file): imports,
# constants, the scene store (a drawing is kept in its chat's metadata), the
# editor's tokens and the element helpers. The scene store is the chat_data library.

import json
import logging
import re
import secrets
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

PREFIX = "/excalidraw"
# Key the tool sets in show_excalidraw's result; its value is the artifact HTML.
MARKER = "excalidraw_artifact"
# Key under chat.meta that holds the drawing.
META_KEY = "excalidraw"
EXCALIDRAW_VERSION = "0.18.0"
NO_STORE = {"Cache-Control": "no-store"}
# The editor runs in Open-WebUI's sandboxed Artifacts iframe, whose origin is
# opaque ("null"), so its API calls are cross-origin and carry no cookies.
CORS = {**NO_STORE, "Access-Control-Allow-Origin": "*"}
_ID = re.compile(
    r"[A-Za-z0-9_:-]{1,128}"
)  # chat UUIDs, plus "local:..." temporary chats


# A scene is {"version", "writer", "elements", "updated_at"}, kept under
# chat.meta["excalidraw"] so it lives and dies with its chat. Temporary chats
# have no row, so theirs are kept in memory until Open-WebUI restarts.


# The scene store is the `chat_data` library (plugin.yaml: include) under META_KEY.
_NoChat = ChatNotSaved


def _empty() -> dict:
    return {"version": 0, "writer": "tool", "elements": []}


async def _load(chat_id: str) -> Optional[dict]:
    """The chat's scene, or None if it has none. Raises _NoChat."""
    scene = await plugin_chat_read(chat_id, META_KEY)
    return (
        scene
        if isinstance(scene, dict) and isinstance(scene.get("elements"), list)
        else None
    )


async def _save(chat_id: str, scene: dict) -> None:
    await plugin_chat_write(chat_id, scene, META_KEY)


async def _mutate(
    chat_id: str, change: Callable, writer: str, pass_new: bool = False
) -> dict:
    """Apply change(elements) under the chat's lock and save a new version.
    change may return None to keep the scene as it is."""

    def apply(current: Optional[dict], is_new: bool) -> Optional[dict]:
        valid = isinstance(current, dict) and isinstance(current.get("elements"), list)
        scene = current if valid else _empty()
        elements = (
            change(scene["elements"], is_new or not valid)
            if pass_new
            else change(scene["elements"])
        )
        if elements is None:
            return None
        return {
            "version": scene["version"] + 1,
            "writer": writer,
            "elements": elements,
            "updated_at": int(time.time()),
        }

    return await plugin_chat_update(chat_id, apply, META_KEY, default=_empty()) or _empty()


# Fields worth showing the model; Excalidraw elements carry ~30 more.
_KEEP = (
    "id",
    "type",
    "x",
    "y",
    "width",
    "height",
    "text",
    "strokeColor",
    "backgroundColor",
    "points",
    "angle",
)


def _simplify(elements: List[dict]) -> List[dict]:
    """Compact view for the model: drop deleted, fold bound text into `label`."""
    labels = {
        e["containerId"]: e.get("text", "")
        for e in elements
        if e.get("type") == "text" and e.get("containerId") and not e.get("isDeleted")
    }
    out = []
    for e in elements:
        if e.get("isDeleted") or (e.get("type") == "text" and e.get("containerId")):
            continue
        s = {k: e[k] for k in _KEEP if k in e}
        label = labels.get(e.get("id")) or (
            e["label"].get("text") if isinstance(e.get("label"), dict) else None
        )
        if label:
            s["label"] = label
        for side in ("start", "end"):
            binding = e.get(f"{side}Binding")
            if isinstance(binding, dict) and binding.get("elementId"):
                s[side] = {"id": binding["elementId"]}
            elif isinstance(e.get(side), dict):
                s[side] = e[side]
        out.append(s)
    return out


def _with_ids(elements: List[dict]) -> List[dict]:
    """Models often omit ids; give each element one so it can be read, updated
    and deleted later. (Nested label/start/end skeleton fields are untouched.)"""
    return [
        e if e.get("id") else {**e, "id": secrets.token_urlsafe(6)} for e in elements
    ]


def _merge(existing: List[dict], incoming: List[dict]) -> List[dict]:
    incoming = _with_ids(incoming)
    by_id = {e["id"]: e for e in incoming}
    merged = [by_id.pop(e.get("id"), e) for e in existing]
    return merged + [e for e in incoming if e["id"] in by_id]


def _as_list(elements: Any) -> List[dict]:
    """Models pass elements as a list, one object, or JSON text; accept all."""
    if isinstance(elements, str):
        elements = json.loads(elements)
    if isinstance(elements, dict):
        elements = [elements]
    return [json.loads(e) if isinstance(e, str) else e for e in elements or []]


