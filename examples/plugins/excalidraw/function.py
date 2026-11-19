# The Excalidraw function: serves the editor, adds it to replies as an artifact and
# keeps the Excalidraw tool installed (the plugin runtime is appended to this file).
# (Imports and the scene store come from shared.py.)

# Editor assets
# -------------
# This function only sends the page below. The user's browser then fetches the
# editor's code from esm.sh, a public CDN that bundles npm packages on request:
#   * the stylesheet:     https://esm.sh/@excalidraw/excalidraw@<version>/dist/prod/index.css
#   * React, React DOM:   https://esm.sh/react@18.3.1, react-dom@18.3.1 (the import map)
#   * Excalidraw itself:  https://esm.sh/@excalidraw/excalidraw@<version>?external=react,react-dom
#   * fonts and other files Excalidraw loads at runtime: EXCALIDRAW_ASSET_PATH,
#     https://esm.sh/@excalidraw/excalidraw@<version>/dist/prod/
# So the browser needs internet access to esm.sh, and esm.sh is trusted to
# serve that code (there is no integrity check). It sees the user's IP and the
# Open-WebUI origin, not the editor token (browsers send only the origin as
# the Referer to other sites).
#
# Self-hosting: to stop browsers depending on esm.sh, build the editor once with self-host/build.sh,
# serve the folder from your own host with a permissive CORS header (the Artifacts panel's iframe
# has an opaque origin), and set EXCALIDRAW_ASSETS_URL in the Open-WebUI container (config.yaml).
# The page then loads nothing from the internet. To upgrade Excalidraw, change EXCALIDRAW_VERSION in
# shared.py and the versions in self-host/package.json together.
VIEWER = plugin_template_text("viewer.html")  # templates/viewer.html, rendered per request below

# Where the self-hosted editor is: a plain http(s) URL or a path, with nothing that could break out
# of an HTML attribute or a JS string.
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
        # Open-WebUI loads global filters at startup (to build the model list),
        # so the routes are ready before anyone opens a chat; inlet/outlet retry
        # in case that failed here. The Tool this plugin installs is kept in sync
        # by the plugin runtime appended to this file (plugin.yaml: tool).
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
        # The Artifacts panel collects blocks from every reply in the chat and
        # keeps showing them, so one block per editor is enough: skip any that
        # an earlier reply (or this one) already carries.
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
            # The editor's API calls come from the sandboxed panel, which sends no
            # cookies, so they cannot carry an Open-WebUI session: they carry the
            # short-lived token the page was rendered with after a real login (see
            # view), bound to this chat. This is mounted as the API's own guard
            # (plugin_mount(guard=...)); the page itself uses the library's sign-in check.
            if not _ID.fullmatch(chat_id) or not plugin_check_token(t, chat_id):
                raise HTTPException(404, "Not found")
            return chat_id

        page = APIRouter(prefix=PREFIX)
        api = APIRouter(prefix=PREFIX)

        # Signed-in users who can write to this chat: the WritableChat marker checks both (the
        # library's guard covers the sign-in; the marker the chat), so there is no check here.
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

        # POST with a text/plain body is a CORS "simple" request, so the browser
        # sends no preflight that Open-WebUI's CORS settings could refuse.
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

        # Replaces routes from an earlier load of this function and goes ahead of
        # Open-WebUI's catch-all SPA mount (the `routes` library, plugin.yaml: include).
        # The unnamed mount is the page (and drops every route an older version mounted
        # here); the API is its own mount, with the token guard instead of a session.
        plugin_mount(app, page, PREFIX)
        plugin_mount(app, api, PREFIX, name="api", guard=authorised)
        self.mounted = True
        log.info("Excalidraw: mounted %s/*", PREFIX)
