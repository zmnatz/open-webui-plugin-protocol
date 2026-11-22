"""Shared by Theme Designer Pro's tests: the plugin started, the people who use it, a theme to
save, and the open pages that hear about it (its live-update streams)."""

import asyncio
import json
import re

import pytest

ID = "theme_designer_pro"
TOOL = "theme_designer_pro_launcher"
BASE = "/api/v1/theme-designer"
# The designer as the Settings tab or a chat's frame loads it: a page, in a frame, so a missing
# session is a 401 and not a redirect to the sign-in page.
FRAME = {"accept": "text/html", "sec-fetch-dest": "iframe"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32

CSS = (
    ":root { --color-gray-950: oklch(0.2 0.02 250); }\n"
    "/*[OWUI_STRUCTURAL_START]*/#sidebar { /*[FX]*/ background-color: var(--color-gray-950) !important; }"
    "/*[OWUI_STRUCTURAL_END]*/\n"
    "/*[OWUI_CUSTOM_START]*/.chat { color: red; }/*[OWUI_CUSTOM_END]*/\n"
)
SECTIONS = {
    "vars": ":root { --color-gray-950: oklch(0.2 0.02 250); }\n",
    "structural": "/*[OWUI_STRUCTURAL_START]*/#sidebar { /*[FX]*/ background-color: var(--color-gray-950) !important; }/*[OWUI_STRUCTURAL_END]*/\n",
    "gradient": "",
    "custom": "/*[OWUI_CUSTOM_START]*/.chat { color: red; }/*[OWUI_CUSTOM_END]*/\n",
}
STATE = {"dark": {"canvasEnabled": True, "canvasScript": "draw()", "themeShowAuth": True}}


class Designer:
    """The plugin as its pages use it: a client for each person, and the calls the designer's
    own page makes."""

    BASE, FRAME, CSS, SECTIONS, STATE, PNG = BASE, FRAME, CSS, SECTIONS, STATE, PNG

    def __init__(self, owui, plugin, ada):
        self.owui, self.plugin, self.ada = owui, plugin, ada
        self.admin = owui.client(owui.admin)
        self.user = owui.client(ada)
        self.anon = owui.client()

    @property
    def event(self):
        """The Event class of the function as loaded now."""
        return self.plugin.module.Event

    def valves(self, **valves):
        self.owui.set_valves(ID, **valves)

    def page(self, client, query=""):
        return client.get(BASE + query, headers=FRAME)

    def config(self, client, query="") -> dict:
        """window.__THEME_PRO_CONFIG__ of the designer page: what the valves tell the page."""
        page = self.page(client, query)
        assert page.status_code == 200, page.text[:200]
        return self.script_value(page.text, "__THEME_PRO_CONFIG__")

    @staticmethod
    def script_value(html, name):
        found = re.search(rf"window\.{name}=(.*?);window\.|window\.{name}=(.*?);</script>", html)
        return json.loads((found.group(1) or found.group(2)).replace("\\u003c", "<"))

    def save(self, client=None, path="", **body):
        body = {"css": CSS, "state": json.dumps(STATE), "sections": SECTIONS, **body}
        return (client or self.admin).post(BASE + path, json=body)

    def stream(self, user=None):
        """An open page's live-update stream, as the SSE route registers it: what is sent to
        it piles up here, and `heard()` reads it."""
        queue = asyncio.Queue(maxsize=64)
        if user is not None:
            queue._tdp_user = user.id
        self.event._sse_clients.add(queue)
        return queue

    @staticmethod
    def heard(queue) -> list:
        """The event names sent to a stream since it was last read, with their data."""
        out = []
        while not queue.empty():
            frame = queue.get_nowait()
            if frame is None:
                out.append(("end", None))
                continue
            name = re.search(r"^event: (.+)$", frame, re.M)
            data = re.search(r"^data: (.+)$", frame, re.M)
            out.append((name.group(1) if name else "comment", json.loads(data.group(1)) if data else None))
        return out


@pytest.fixture
def tdp(owui, plugin):
    """The plugin, started: its routes are mounted and its fragments published, and the
    background work its load starts (reading its valves back, as on a worker no event
    reached) is done, so it does not land in the middle of a test."""
    owui.startup()
    for _ in range(5):
        owui.run(asyncio.sleep(0.01))
    return plugin


@pytest.fixture
def ada(owui):
    return owui.add_user("Ada")


@pytest.fixture
def td(owui, tdp, ada):
    return Designer(owui, tdp, ada)
