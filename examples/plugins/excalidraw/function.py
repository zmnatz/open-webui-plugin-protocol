# Serves the editor, adds it to replies as an artifact and keeps the Excalidraw tool installed.
# The scene store and the constants come from shared.py, and plugin_* from the libraries: the
# bundler puts both above this file.

import json
import re
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# Editor assets: the browser loads React and Excalidraw from esm.sh (no integrity check), or
# from EXCALIDRAW_ASSETS_URL when self-hosted (self-host/build.sh). To upgrade Excalidraw, change
# EXCALIDRAW_VERSION in shared.py and self-host/package.json together.
VIEWER = plugin_template_text("viewer.html")  # templates/viewer.html, rendered per request below

# A plain http(s) URL or path, safe inside an HTML attribute and a JS string.
_ASSETS_URL = re.compile(r"(?:https?://|/)[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]*")


def _assets_url() -> str:
    """Where this deployment hosts the editor's files (config.yaml: assets_url), or "" for esm.sh."""
    url = str(plugin_config().get("assets_url") or "").strip().rstrip("/")
    if url and not _ASSETS_URL.fullmatch(url):
        log.warning("Excalidraw: assets_url %r is not a plain http(s) URL or path; using esm.sh", url)
        return ""
    return url


def _editor_page(token: str) -> str:
    """The editor page for one signed-in view: the self-hosted head or the esm.sh one, the token."""
    url = _assets_url()
    keep, drop = ("hosted", "esm.sh") if url else ("esm.sh", "hosted")
    html = re.sub(rf"<!--{re.escape(drop)}-->.*?<!--/{re.escape(drop)}-->\n?", "", VIEWER, flags=re.S)
    html = re.sub(rf"<!--/?{re.escape(keep)}-->\n?", "", html)
    return (
        html.replace("__ASSETS_URL__", url)
        .replace("__VERSION__", EXCALIDRAW_VERSION)
        .replace("__TOKEN__", token)
    )


def _reply(body: dict) -> Optional[dict]:
    """The assistant message this outlet run is for."""
    messages = body.get("messages") or []
    target = body.get("id")
    for m in reversed(messages):
        if target and m.get("id") == target:
            return m
    for m in reversed(messages):
        if m.get("role") == "assistant":
            return m
    return None


def _shown(message: dict) -> str:
    """The text of a reply, from content and its structured output."""
    return _text(message.get("content")) + "".join(
        _text(item.get("content"))
        for item in message.get("output") or []
        if item.get("type") == "message"
    )


def _artifacts(output: List[dict]) -> List[str]:
    found = []
    for item in output:
        if item.get("type") != "function_call_output":
            continue
        result = _first_json_object(_text(item.get("output")))
        if isinstance(result, dict) and isinstance(result.get(MARKER), str):
            found.append(result[MARKER])
    return found


def _first_json_object(text: str) -> Any:
    """The tool result, even if Open-WebUI appended context after it."""
    start = text.find("{")
    if start == -1:
        return None
    try:
        return json.JSONDecoder().raw_decode(text, start)[0]
    except ValueError:
        return None


def _text(value: Any) -> str:
    """Output fields are either a string or a list of {"text": ...} parts."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in value
        )
    return ""


class Filter:
    class Valves(BaseModel):
        SESSION_TOKEN_HOURS: int = Field(
            default=12,
            description="How long the editor's API token lasts once the page is opened.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.mounted = False
        # Global filters load at startup, so the routes are up before any chat; inlet/outlet retry.
        self._mount(plugin_app())

    async def inlet(self, body: dict, __request__=None) -> dict:
        self._ensure(__request__)
        await _plugin_ensure()
        return body

    # ----------------------------------------------------------- artifact
    def outlet(self, body: dict, __request__=None) -> dict:
        self._ensure(__request__)
        message = _reply(body)
        if message is None:
            return body
        output = message.get("output") or []
        # The panel keeps blocks from every reply, so add the editor only once per chat.
        shown = "".join(
            _shown(m)
            for m in body.get("messages") or []
            if m.get("role") == "assistant"
        )
        blocks = []
        for html in _artifacts(output):
            if html not in shown and html not in blocks:
                blocks.append(html)
        if not blocks:
            return body

        text = "".join(f"\n\n```html\n{html}\n```" for html in blocks)
        message["content"] = (message.get("content") or "") + text
        if output:
            output.append(
                {
                    "type": "message",
                    "id": f"msg_{MARKER}_{len(output)}",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text.lstrip()}],
                }
            )
        log.info(
            "Excalidraw: added %d artifact(s) to message %s",
            len(blocks),
            message.get("id"),
        )
        return body

    async def _stored_valves(self) -> "Filter.Valves":
        """Valves are only applied to this instance when a chat runs the
        filter, so read them fresh outside one. The editor polls its API every
        couple of seconds, so a read is reused for a few seconds."""
        return await plugin_stored_valves(self.Valves, ttl=10)

    # ------------------------------------------------------- editor routes
    def _ensure(self, request) -> None:
        if not self.mounted and request is not None:
            self._mount(request.app)

    def _mount(self, app) -> None:
        if app is None:
            return

        async def authorised(chat_id: str, t: str = "") -> str:
            # The sandboxed panel sends no cookies, so the API takes the chat-bound token the page was
            # rendered with instead of a session.
            if not _ID.fullmatch(chat_id) or not plugin_check_token(t, chat_id):
                raise HTTPException(404, "Not found")
            return chat_id

        page = APIRouter(prefix=PREFIX)
        api = APIRouter(prefix=PREFIX)

        # WritableChat: signed in and allowed to write to this chat.
        @page.get("/view/{chat_id}", response_class=HTMLResponse)
        async def view(chat_id: WritableChat):
            if not _ID.fullmatch(chat_id):
                raise HTTPException(404, "Not found")
            valves = await self._stored_valves()
            token = plugin_token(chat_id, valves.SESSION_TOKEN_HOURS)
            return HTMLResponse(_editor_page(token), headers=NO_STORE)

        @api.get("/api/scenes/{chat_id}")
        async def get_scene(chat_id: str, since: int = -1):
            try:
                scene = await _load(chat_id) or _empty()
            except _NoChat:
                raise HTTPException(404, "Not found") from None
            if scene["version"] == since:
                return JSONResponse({"changed": False, "version": since}, headers=CORS)
            return JSONResponse({"changed": True, **scene}, headers=CORS)

        # A text/plain POST is a CORS simple request: no preflight.
        @api.post("/api/scenes/{chat_id}")
        async def put_scene(request: Request, chat_id: str):
            try:
                body = json.loads(await request.body())
                elements, client = body["elements"], str(body["client"])
                if not isinstance(elements, list):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise HTTPException(400, "expected {client, elements}") from None
            try:
                scene = await _mutate(chat_id, lambda _: elements, client)
            except _NoChat:
                raise HTTPException(404, "Not found") from None
            return JSONResponse({"version": scene["version"]}, headers=CORS)

        # The page mount replaces any earlier routes; the API mount uses the token guard.
        plugin_mount(app, page, PREFIX)
        plugin_mount(app, api, PREFIX, name="api", guard=authorised)
        self.mounted = True
        log.info("Excalidraw: mounted %s/*", PREFIX)
