# Theme Designer Pro: themes the whole of Open-WebUI for every user (a palette, gradients, animated
# Canvas FX backgrounds, frosted glass and custom CSS) from a designer page of its own, and lets
# each user design a personal theme when the admin allows it.
#
# Adapted from Theme Designer Pro 1.22.0 by G30 (https://openwebui.com/u/g30), from
# silentoplayz/theme-designer-pro-presets, Copyright (c) 2026 silentoplayz, MIT licence (the
# notice is in NOTICE.md at the repository root):
# https://github.com/silentoplayz/theme-designer-pro-presets/blob/9a7e68c9afe51539effae22767e843f26205d895/event-function/theme_designer_pro_event.py
#
# It does what the original does. What changed (the README has the whole list):
# - The header is plugin.yaml's `function:`.
# - The 1.3 MB file is split up. The designer page is templates/designer/ (page.html includes its
#   two stylesheets, seven tabs, its documentation, four pieces of markup that were built in
#   Python, and its script as sixteen files); the bootloader and the Settings and Admin Panel
#   scripts are templates/*.js; the consultant's prompt and the notice page are templates too.
#   What is left here is Python.
# - The Shared Assets Protocol and live-reload blocks are owpp's libraries (include: in
#   plugin.yaml), byte-identical to the protocol's; live reload is its newer copy.
# - Routes are mounted with plugin_mount, behind owpp's sign-in guard, and marked PluginAdmin or
#   PluginUser where they need more, replacing the hand-written token checks and the hand-made
#   insertion into app.routes. What signed-out pages need (the theme, its live updates, the
#   sign-in picture) is a public mount.
# - Lifecycle events are @on handlers (the events library) instead of one event() of if-checks.
# - The Launcher's signed-link format is shared.py, used here and by tool.py.
# - The AI Consultant's rate limit is plugin_claim (the jobs library), so it holds across workers.
# - The per-worker limits on live-update streams can be set in config.yaml.

import asyncio
import hashlib
import json as _json
import logging
import os
import re as _re
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from owpp.lib import (
    CUSTOM_CSS_PATH,
    LOADER_PATH,
    RELOAD_EXEC_ID,
    RELOAD_FUNCTION_ID,
    PluginAdmin,
    PluginEvents,
    PluginUser,
    asset_fragments,
    asset_register,
    on,
    plugin_claim,
    plugin_config,
    plugin_guard,
    plugin_mount,
    plugin_template_text,
    plugin_user,
    reload_active,
    reload_bootstrap,
    reload_on_event,
    reload_publish,
    reload_tasks,
)

from shared import APPLY_TOKEN_PREFIX, THEME_TOKEN_PREFIX, _fill, _open_token, _token_key

VERSION = "1.22.0"
ROUTE_PATH = "/api/v1/theme-designer"
CSS_FILE_NAME = "open_theme_designer.css"

log = logging.getLogger(__name__)

# config.yaml: what one worker holds for the live updates. The defaults are upstream's.
LIMITS = plugin_config(
    {"sse_max_clients": 8192, "sse_heartbeat_seconds": 15, "consult_interval_seconds": 3}
)

_INCLUDE = _re.compile(r"<!--#include ([\w./-]+)-->")


def _designer_page() -> str:
    """templates/designer/page.html with every `<!--#include path-->` replaced by that file of
    templates/designer/, less its last newline: the designer as one page, before the valves are
    filled in. A marker on a line of its own gives the file as it is."""
    return _INCLUDE.sub(
        lambda m: plugin_template_text("designer/" + m[1]).removesuffix("\n"),
        plugin_template_text("designer/page.html"),
    )


DESIGNER_PAGE = _designer_page()  # the same for every request, so built once

# The designer is for admins; with ?scope=me it edits the signed-in user's own theme, so any
# signed-in user may open it. Built from owpp's own guards, so the level is still on the route.
_ADMIN, _SIGNED_IN = plugin_guard("admin"), plugin_guard("user")


async def _designer_access(request: Request, response: Response):
    guard = _SIGNED_IN if request.query_params.get("scope") == "me" else _ADMIN
    return await guard(request, response)


DesignerUser = Annotated[Any, Depends(_designer_access)]


class Event(PluginEvents):
    class Valves(BaseModel):
        # ── Feature Toggles ──
        enable_canvas_fx: bool = Field(
            default=True,
            description="Allow Canvas FX (JavaScript background animations). When disabled, the Canvas FX tab is hidden and running animations are suppressed.",
        )
        calm_chat_column: bool = Field(
            default=False,
            description="Let animations fade behind the chat, each by its own Center Calm setting. When disabled, every script's Center Calm counts as 0, so animations show at full strength across the whole page. Takes effect on the next page load.",
        )
        enable_custom_css: bool = Field(
            default=True,
            description="Allow the Style Overrides (custom CSS) editor. When disabled, the Style Overrides tab is hidden.",
        )
        enable_gradient_builder: bool = Field(
            default=True,
            description="Allow the Gradient Background builder. When disabled, the Gradient tab is hidden.",
        )
        enable_ai_consultant: bool = Field(
            default=True,
            description="Show the AI Consultant in the designer: describe a theme in words, and a model on this instance picks its colors and gradient. Admins can always use it; users can when personal themes are on. Each request is one call to the model set in AI Consultant Model, or the task model.",
        )
        enable_theme_update_checks: bool = Field(
            default=True,
            description="Let the designer check installed themes for newer versions: the Updates button, each theme's own update check, and the Update badges in Community Themes. When disabled, the designer makes none of these requests to GitHub or to a theme's update URL.",
        )
        enable_community_themes: bool = Field(
            default=True,
            description="Show the Community Themes browser in the Themes tab. When disabled, the community themes grid is hidden and its catalog isn't fetched.\n\n---\n\n#### 🖌️ UX Policy",
        )
        # ── UX Policy ──
        enable_auth_page_theming: bool = Field(
            default=True,
            description="Allow theming the login/signup pages. When disabled, all auth visibility toggles are hidden and forced off.",
        )
        draft_mode_default: bool = Field(
            default=False,
            description="Open the designer in Draft mode by default. When enabled, the designer starts in Draft mode on every fresh page load, preventing accidental live changes.",
        )
        show_in_admin_settings: bool = Field(
            default=True,
            description="Add a Themes tab to the Admin section of Open WebUI's Settings, after Interface, that opens this designer inside Settings. The designer stays available at its own URL either way.",
        )
        show_in_admin_panel: bool = Field(
            default=False,
            description="Add a Themes page to the Admin Panel's top bar, between Functions and Settings, that opens the instance designer there. The designer stays available at its own URL, and in Settings, either way.",
        )
        allow_personal_themes: bool = Field(
            default=False,
            description="Let every user design a personal theme from a Themes tab in their own Settings. A personal theme replaces the instance theme for that user only and follows them to every browser, within the limits the other valves set. Off: everyone sees the instance theme.",
        )
        auto_sync: bool = Field(
            default=False,
            description="Skip the Selective Sync modal when loading presets or syncing. When enabled, a 'Sync All' toggle appears in the designer footer — turn it on to propagate changes to all modes, or leave it off to apply only to the active mode.\n\n---\n\n#### 🎨 Visual Style",
        )
        # ── Visual Style ──
        sidebar_transparency: Literal["opaque", "translucent", "transparent"] = Field(
            default="opaque",
            description=(
                "Controls sidebar background style. "
                "'opaque' (default) — solid background for best readability. "
                "'translucent' — frosted glass effect (backdrop-blur) that lets backgrounds show through. "
                "'transparent' — fully see-through sidebar with no blur "
                "(automatically uses translucent on mobile for readability). "
                "Open WebUI's fades at the top and bottom of the sidebar show only while it's 'opaque'."
            ),
        )
        overlay_transparency: Literal["opaque", "translucent"] = Field(
            default="opaque",
            description=(
                "Controls overlay UI (settings modal, dropdowns, integration menus) background style. "
                "'opaque' (default) — solid background for best readability. "
                "'translucent' — frosted glass effect (backdrop-blur) that lets backgrounds show through. "
                "The fade at the top of chats shows only while it's 'opaque'."
                "\n\n---\n\n#### 🔒 Security"
            ),
        )
        # ── Security ──
        enable_canvas_api_access: bool = Field(
            default=False,
            description=(
                "⚠️ **Gives every Canvas FX script each viewer's own Open WebUI auth token.** "
                "Not just yours: Canvas FX scripts are JavaScript that runs on **every user's page**, "
                "so with this ON a script receives whichever user is viewing and can call the API "
                "as them — read their chats, change their settings, act with their permissions.\n\n"
                "Worth knowing before enabling:\n"
                "- Scripts that reference `document` run on the **main thread**, where a Web Worker's "
                "isolation does not apply.\n"
                "- Themes you import or install from the community can carry scripts, and an installed "
                "theme can **replace its script later** through its update URL. Enabling this means "
                "trusting every one of those authors on an ongoing basis, not just today.\n\n"
                "Only turn this on if you wrote or fully audited every Canvas FX script in every "
                "installed theme. Leave OFF (the default) unless a script genuinely needs authenticated "
                "API calls — with it off, `env.authToken` is an empty string and everything else about "
                "Canvas FX works normally."
            ),
        )
        enable_url_import: bool = Field(
            default=True,
            description="Show the 'Load from URL' import controls in the designer. This is a UI convenience guard (the fetch runs in the browser of whoever uses the designer), not a server-enforced security boundary.",
        )
        allowed_import_domains: str = Field(
            default="",
            description="Comma-separated domains the designer may fetch from for URL imports, theme update checks and Community Themes (e.g. 'raw.githubusercontent.com, openwebui.com'). Empty = allow any. Enforced in the browser as a guardrail against typos and mistakes, not a security control.\n\n---\n\n#### 🛠️ Advanced",
        )
        # ── Advanced ──
        designer_url: str = Field(
            default=ROUTE_PATH,
            description=(
                "🎨 **Theme Designer Pro**: "
                "the URL path where the designer UI is served (by default `/api/v1/theme-designer`). "
                "Change this to serve the designer at a custom path. "
                "A path ending in /me is refused and the default is used, because personal themes use that name. "
                "Takes effect when you save the valves."
            ),
        )
        ai_consultant_model: str = Field(
            default="",
            description="The model the AI Consultant asks, by its ID. Empty: the task model set under Admin Settings > Interface, local first, then external.",
        )

    # templates/bootloader.js: what /static/loader.js runs on every page, and the designer too.
    BOOTLOADER_SCRIPT = plugin_template_text("bootloader.js").strip()

    def __init__(self):
        super().__init__()  # PluginEvents: self.valves
        Event.instance = self
        reload_bootstrap()

    def _valves_snapshot(self):
        """A hashable, order-stable snapshot of every valve value.

        Used to detect that ANY valve changed — the existing per-valve flags
        only cover the three that alter a live SSE broadcast, but nearly every
        valve changes the composed loader.js (it embeds the whole config), so
        a peer worker has to re-read on any of them.
        """
        return tuple(sorted(self.valves.model_dump().items()))

    # -- URL validation -------------------------------------------------------

    def _get_route_base(self) -> str:
        """Return the validated designer URL, auto-correcting if needed."""
        route = self.valves.designer_url.rstrip("/")
        # Sanitize: only allow alphanumeric, hyphens, underscores, slashes, and dots
        route = _re.sub(r"[^a-zA-Z0-9/_.-]", "", route)
        if not route.startswith("/api/v1/"):
            corrected = "/api/v1" + (route if route.startswith("/") else "/" + route)
            log.warning(
                "[Theme Pro] designer_url '%s' is outside /api/v1/ — "
                "auto-correcting to '%s' (SPA catch-all intercepts non-API routes)",
                route,
                corrected,
            )
            route = corrected
        # An uploaded picture's address can't tell /<base>/me/page-background,
        # the instance theme's under a base ending in /me, from a personal one
        if route.rsplit("/", 1)[-1] == "me":
            if Event._route_base_refused != route:
                Event._route_base_refused = route
                log.warning(
                    "[Theme Pro] designer_url '%s' ends in /me, which personal themes use; serving at '%s' instead",
                    route,
                    ROUTE_PATH,
                )
            return ROUTE_PATH
        return route

    _route_base_refused = None  # The designer_url refused for ending in /me, so it is logged once

    # -- bootloader management -----------------------------------------------

    # The bootloader block has no end marker of its own: it ends at the first
    # </script> after its start comment.
    LEGACY_INDEX_MARKERS = (
        ("<!-- OWUI Theme Pro Bootloader -->", "</script>"),
        ('<style id="owui-server-theme">', "</style><!-- /owui-server-theme -->"),
        (
            '<script type="application/json" id="owui-theme-state">',
            "</script><!-- /owui-theme-state -->",
        ),
    )

    @staticmethod
    def _strip_legacy_index_blocks(content: str, markers=LEGACY_INDEX_MARKERS) -> str:
        """Remove every block between each (start, end) marker pair, with the
        newline after it. A while loop, so duplicates left by older builds all
        go; a block whose end marker is missing stays."""
        for start_marker, end_marker in markers:
            while start_marker in content:
                start = content.find(start_marker)
                end = content.find(end_marker, start)
                if end == -1:
                    break
                end += len(end_marker)
                if end < len(content) and content[end] == "\n":
                    end += 1
                content = content[:start] + content[end:]
        return content

    @staticmethod
    def _find_index_file():
        """The frontend index.html served by SPAStaticFiles, or None."""
        from open_webui.env import FRONTEND_BUILD_DIR

        idx = Path(FRONTEND_BUILD_DIR) / "index.html"
        return str(idx) if idx.exists() else None

    @staticmethod
    @contextmanager
    def _file_lock(path: Path):
        """Lock one file across processes on Windows and Unix."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a+b") as fd:
            if os.name == "nt":
                import msvcrt

                # msvcrt locks a byte range, so ensure byte zero exists.
                fd.seek(0, os.SEEK_END)
                if fd.tell() == 0:
                    fd.write(b"\0")
                    fd.flush()
                fd.seek(0)
                msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    fd.seek(0)
                    msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)

    @staticmethod
    def _atomic_write(path, content):
        """Atomically write content to path, creating its folder if needed."""
        Event._write_together([(Path(path), content)])

    # -- shared static-asset fragments ---------------------------------------

    # Marker pairs wrapping this plugin's block inside each composed asset, so
    # asset_compose can strip a previous build's block before re-appending.
    LOADER_BLOCK_START = "// owui-theme-designer-pro:start"
    LOADER_BLOCK_END = "// owui-theme-designer-pro:end"
    CSS_BLOCK_START = "/* owui-theme-designer-pro:start */"
    CSS_BLOCK_END = "/* owui-theme-designer-pro:end */"

    # asset_compose sorts fragments by (order, key); higher composes last. On
    # custom.css that is the CSS cascade between plugins, and this plugin's
    # custom-CSS section is documented as last = highest priority (Section 13),
    # so it claims a high order explicitly rather than relying on where
    # its key happens to fall alphabetically. On loader.js the
    # same value makes this bootloader the outermost wrapper.
    ASSET_ORDER = 100

    @staticmethod
    def _strip_canvas_scripts(state_str: str) -> str:
        """Drop only the canvasScript bodies from a delivered state JSON string.

        Measured on the largest Canvas FX script in the presets repo across four
        modes, the scripts are 93% of the inlined state (129 KB of 139 KB) and
        would make the loader fragment ~205 KB. asset_compose rebuilds and
        md5-hashes the entire composed body on EVERY request — the ETag is
        compared only after the producer has already run, so a 304 revalidation
        costs almost exactly as much server CPU as a 200 (measured: 3.87 ms vs
        4.08 ms per request). Inlining the scripts would therefore charge every
        page load of every user for a background animation that nobody can
        perceive starting one round trip later.

        Nothing flash-sensitive is lost. enforceTheme() reads CSS, not state,
        and that CSS arrives via the render-blocking /static/custom.css.
        _cssSections stays inlined (9 KB) because the auth page assembles its
        CSS from it before the fetch lands. initCanvas() simply finds no script
        on its first pass and starts the canvas when /state.json arrives.
        """
        try:
            data = _json.loads(state_str)
            if not isinstance(data, dict):
                return state_str
            stripped = False
            for config in data.values():
                # _cssSections is a sibling of the mode dicts and has no
                # canvasScript, so it falls through untouched.
                if isinstance(config, dict) and config.get("canvasScript"):
                    config.pop("canvasScript", None)
                    stripped = True
            if not stripped:
                return state_str
            return _json.dumps(data, separators=(",", ":"))
        except Exception:
            return state_str  # Unparseable state is served as-is by design

    @classmethod
    def _bootloader_body(cls) -> str:
        """The bootloader, before its placeholders are filled in."""
        return cls.BOOTLOADER_SCRIPT

    # Adds the designer to the Admin section of Open WebUI's Settings dialog.
    # The dialog's tabs are fixed in its own code, so this adds a tab of its
    # own after Interface and shows the designer page in a frame in place of
    # the dialog's panel while that tab is open.
    ADMIN_TAB_SCRIPT = plugin_template_text("settings_tab.js").strip()

    # Adds a Themes page to the Admin Panel's top bar.
    ADMIN_PAGE_SCRIPT = plugin_template_text("admin_page.js").strip()

    def _loader_fragment(self, active: bool) -> str:
        """Producer for the /static/loader.js fragment.

        Runs inside the request handler on every page load, so the whole result
        is memoised and the steady state is a tuple compare. The two stat()s
        behind _get_state_delivery are the only syscalls; its ETag stands in for
        the state and sections mtimes plus the valves that affect delivery.

        Stays published while the function is disabled, with __THEME_ACTIVE__
        false: the bootloader strips the theme from a fresh load but keeps the
        SSE connection, which is how a later re-enable reaches open tabs. The
        CSS fragment is what goes empty on disable.
        """
        delivery = self._get_state_delivery() if active else None
        cache_key = (
            active,
            self._get_route_base(),
            self.valves.enable_canvas_api_access,
            delivery[1] if delivery else None,  # state delivery ETag
            self.valves.show_in_admin_settings,
            self.valves.allow_personal_themes,
            self.valves.show_in_admin_panel,
            self.valves.enable_canvas_fx,
            self.valves.calm_chat_column,
        )
        cached = Event._loader_fragment_cache
        if cached and cached[0] == cache_key:
            return cached[1]

        js = (
            self._bootloader_body()
            .replace("__THEME_ROUTE__", cache_key[1])
            .replace(
                "__CANVAS_API_ACCESS__",
                "true" if self.valves.enable_canvas_api_access else "false",
            )
            .replace(
                "__THEME_ACTIVE__",
                "true" if active else "false",
            )
            .replace(
                "__PERSONAL_THEMES__",
                "true" if self.valves.allow_personal_themes else "false",
            )
            .replace(
                "__CANVAS_FX__",
                "true" if self.valves.enable_canvas_fx else "false",
            )
            .replace(
                "__CALM_CHAT_COLUMN__",
                "true" if self.valves.calm_chat_column else "false",
            )
        )

        # State inlined as a JS string literal, minus the canvas scripts.
        # ensure_ascii (json.dumps default) escapes U+2028/U+2029, which are raw
        # line terminators in JS.
        embedded = "null"
        if delivery:
            embedded = _json.dumps(self._strip_canvas_scripts(delivery[0]))
        js = js.replace("__EMBEDDED_STATE__", embedded)

        if active and (self.valves.show_in_admin_settings or self.valves.allow_personal_themes):
            js += "\n" + (
                self.ADMIN_TAB_SCRIPT.strip()
                .replace("__THEME_ROUTE__", cache_key[1])
                .replace("__TAB_ADMIN__", "true" if self.valves.show_in_admin_settings else "false")
                .replace(
                    "__TAB_PERSONAL__", "true" if self.valves.allow_personal_themes else "false"
                )
            )

        if active and self.valves.show_in_admin_panel:
            js += "\n" + self.ADMIN_PAGE_SCRIPT.strip().replace("__THEME_ROUTE__", cache_key[1])

        fragment = f"{self.LOADER_BLOCK_START}\n{js}\n{self.LOADER_BLOCK_END}"
        Event._loader_fragment_cache = (cache_key, fragment)
        return fragment

    def _safe_subset_css(self) -> str:
        """The CSS safe to apply at first paint: vars + custom.

        Structural transparency and gradient rules are deferred to the
        bootloader — applied before the canvas is painting, they flash the page
        through to the background colour. Prefers the structured sections file
        and falls back to marker regexes for legacy flat-CSS saves.

        Cached like the /theme.css and /state.json deliveries, and for the same
        reason twice over: this runs inside the request handler on every page
        load, and the shared-registry contract requires producers to be cheap
        and do no I/O. Uncached, every visitor would pay a sections read plus a
        JSON parse, or two DOTALL passes over the whole blob on the legacy path.
        """
        try:
            css_mtime = Event._file_sig(self._get_css_path())
        except OSError:
            return ""
        try:
            sections_mtime = Event._file_sig(self._get_sections_path())
        except OSError:
            sections_mtime = None
        # sidebar_transparency cannot reach this subset today (it rewrites
        # /*[FX]*/ rules inside structural + gradient, both dropped here) but is
        # keyed on anyway — a stale safe subset is a far worse failure than an
        # occasional extra recompute on a valve nobody changes at runtime.
        cache_key = (css_mtime, sections_mtime, *self._css_valve_key())
        cached = Event._safe_css_cache
        if cached and cached[0] == cache_key:
            return cached[1]

        try:
            raw = self._load_css()
        except OSError:
            raw = None  # Vanished between stat() and read (reset race)
        if not raw:
            return ""

        sections = self._load_sections()
        if sections:
            # Raw sections, not _postprocess_sections(): the sidebar valve only
            # rewrites structural + gradient, and the synthetic 'extra' section
            # bundles the mobile sidebar upgrade in with the overlay glass. That
            # sidebar rule is itself a transparency rule and belongs with the
            # deferred structural block, so only the overlay part is applied
            # below — matching what the pre-1.7.0 embedded subset shipped.
            safe_css = (
                sections["vars"]
                + "/* structural rules deferred to bootloader */\n"
                + "/* gradient rules deferred to bootloader */\n"
                + sections["custom"]
            )
        else:
            safe_css = _re.sub(
                r"/\*\[OWUI_STRUCTURAL_START\]\*/.*?/\*\[OWUI_STRUCTURAL_END\]\*/",
                "/* structural rules deferred to bootloader */",
                raw,
                flags=_re.DOTALL,
            )
            safe_css = _re.sub(
                r"/\*\[OWUI_GRADIENT_START\]\*/.*?/\*\[OWUI_GRADIENT_END\]\*/",
                "/* gradient rules deferred to bootloader */",
                safe_css,
                flags=_re.DOTALL,
            )

        # The block below wraps this in @supports { }, inside a stylesheet
        # shared with other plugins. Unbalanced braces in the admin's custom
        # CSS either closed it early (the rest escaped the switch-off) or
        # never closed it (it swallowed every later plugin's rules). Leave the
        # custom part to the bootloader, which applies it from /theme.css.
        if not self._css_balanced(safe_css):
            if sections:
                safe_css = (
                    sections["vars"]
                    + "/* structural rules deferred to bootloader */\n"
                    + "/* gradient rules deferred to bootloader */\n"
                    + "/* custom CSS deferred to bootloader */\n"
                )
            else:
                safe_css = _re.sub(
                    r"/\*\[OWUI_CUSTOM_START\]\*/.*?/\*\[OWUI_CUSTOM_END\]\*/",
                    "/* custom CSS deferred to bootloader */",
                    safe_css,
                    flags=_re.DOTALL,
                )
            if not self._css_balanced(safe_css):
                safe_css = ""

        # custom.css reaches every page and every user, but the instance theme
        # doesn't belong on all of them: a user with a personal theme sees
        # theirs instead, and a sign-in page can hide the colors or the custom
        # CSS. The condition is always true; it marks the block so the
        # bootloader can switch it off in that page's copy of the stylesheet.
        safe_css = f"@supports ({self.INSTANCE_CSS_MARK}) {{\n{safe_css}\n}}\n"

        # The overlay valve APPENDS glass rules for portaled overlays, so unlike
        # the sidebar valve it has to be baked in here or overlays pop from
        # opaque to glass the moment the bootloader's /theme.css fetch lands.
        # They're the admin's for every page, so they stay outside the block.
        if self.valves.overlay_transparency != "opaque":
            safe_css += self._overlay_css()

        Event._safe_css_cache = (cache_key, safe_css)
        return safe_css

    @staticmethod
    def _css_balanced(css: str) -> bool:
        """Whether every { has its }, no } comes first, and no comment or
        string is left open, ignoring braces inside comments and strings."""
        depth = 0
        i, n = 0, len(css)
        while i < n:
            ch = css[i]
            if ch == "/" and css.startswith("/*", i):
                end = css.find("*/", i + 2)
                if end == -1:
                    return False
                i = end + 2
                continue
            if ch in "\"'":
                j = i + 1
                while j < n and css[j] != ch:
                    if css[j] == "\\":
                        j += 1
                    elif css[j] == "\n":
                        return False
                    j += 1
                if j >= n:
                    return False
                i = j + 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < 0:
                    return False
            i += 1
        return depth == 0

    # The @supports condition around the instance theme in custom.css. The
    # bootloader looks for it by the property name.
    INSTANCE_CSS_MARK = "--tdp-instance: 1"

    @staticmethod
    def _file_sig(path):
        """A saved file's identity for the delivery cache keys. The mtime
        alone repeats within a tick on filesystems with coarse timestamps
        (1 s on some NFS and SMB mounts), so two quick saves served the first
        one's body and ETag. Saves replace the file, which gives it a new
        inode, and the size usually changes too."""
        st = path.stat()
        return (st.st_mtime_ns, st.st_ino, st.st_size)

    def _custom_css_fragment(self) -> str:
        """Producer for the /static/custom.css fragment.

        The producer in _publish_fragments returns "" in its place while the
        function is off: that empty return is how the Shared Assets Protocol
        withdraws a fragment.
        """
        safe_css = self._safe_subset_css()
        if not safe_css.strip():
            return ""
        return f"{self.CSS_BLOCK_START}\n{safe_css}\n{self.CSS_BLOCK_END}"

    def _publish_fragments(self, app) -> bool:
        """(Re)point both shared fragments at this instance and ensure the
        routes exist. Idempotent — safe to call on every event.

        The producers read Event.instance, the object Open WebUI holds and
        refreshes valves on, and live_reload's on/off state at compose time.
        """
        try:
            asset_register(
                app,
                LOADER_PATH,
                self.LOADER_BLOCK_START,
                self.LOADER_BLOCK_END,
                lambda: Event.instance._loader_fragment(reload_active(app)),
                order=self.ASSET_ORDER,
            )
            asset_register(
                app,
                CUSTOM_CSS_PATH,
                self.CSS_BLOCK_START,
                self.CSS_BLOCK_END,
                lambda: Event.instance._custom_css_fragment() if reload_active(app) else "",
                order=self.ASSET_ORDER,
            )
            return True
        except Exception:
            log.exception("[Theme Pro] Could not publish static-asset fragments")
            return False

    # -- CSS file persistence ------------------------------------------------

    def _get_css_path(self, user_id: str | None = None) -> Path:
        """Return the path to the persisted theme CSS file.

        With user_id, the user's personal theme, kept in its own folder under
        theme/users/. That folder is only created when the user first saves.
        """
        from open_webui.env import DATA_DIR

        css_dir = Path(DATA_DIR) / "theme"
        if user_id:
            return css_dir / "users" / Event._user_dir_name(user_id) / CSS_FILE_NAME
        css_dir.mkdir(parents=True, exist_ok=True)
        return css_dir / CSS_FILE_NAME

    @staticmethod
    def _user_dir_name(user_id: str) -> str:
        """A folder name for a user id: the id itself when it is a plain token
        (Open WebUI's are UUIDs), otherwise its hash, so no id can reach
        outside theme/users/."""
        safe = str(user_id)
        if safe and len(safe) <= 64 and all(c.isalnum() or c in "-_" for c in safe):
            return safe
        return hashlib.sha256(safe.encode("utf-8")).hexdigest()

    @staticmethod
    def _write_together(files) -> None:
        """Write (path, content) pairs together: every temp file is written
        before any replaces its target, so a full disk partway through leaves
        the old set in place instead of new CSS beside old state. The renames
        that follow are not rolled back if one of them fails."""
        import tempfile as _tmpf

        staged = []
        try:
            for path, content in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                _fd, _tmp = _tmpf.mkstemp(dir=path.parent, suffix=".tmp")
                staged.append((_tmp, path))
                with os.fdopen(_fd, "w", encoding="utf-8") as f:
                    f.write(content)
            for _tmp, path in staged:
                os.replace(_tmp, path)
        except BaseException:
            for _tmp, _ in staged:
                with suppress(OSError):
                    os.unlink(_tmp)
            raise

    AUTH_BG_FILE_NAME = "auth_background"
    AUTH_BG_MAX_BYTES = 5 * 1024 * 1024

    def _get_auth_bg_path(self) -> Path:
        """The instance theme's sign-in page picture, next to its CSS."""
        return self._get_css_path().parent / Event.AUTH_BG_FILE_NAME

    PAGE_BG_FILE_NAME = "page_background"

    def _get_page_bg_path(self, user_id: str | None = None) -> Path:
        """The picture behind pages without a chat: the instance theme's next
        to its CSS, a personal theme's in that user's own folder."""
        return self._get_css_path(user_id).parent / Event.PAGE_BG_FILE_NAME

    @staticmethod
    def _image_mime(data: bytes) -> str | None:
        """The image type from the file's first bytes, whatever it was sent as.
        No SVG: it can carry script."""
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        return None

    @staticmethod
    def _write_bytes(path: Path, data: bytes) -> None:
        """Atomically write bytes to path via tempfile + os.replace."""
        import tempfile as _tmpf

        path.parent.mkdir(parents=True, exist_ok=True)
        _fd, _tmp = _tmpf.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(_fd, "wb") as f:
                f.write(data)
            os.replace(_tmp, path)
        except BaseException:
            with suppress(OSError):
                os.unlink(_tmp)
            raise

    _UNDECODABLE_WARNED: set = set()

    @staticmethod
    def _read_theme_file(path: Path) -> str | None:
        """Read a theme file, or None if not found.

        Bytes that aren't UTF-8 (a latin-1 editor, a restore tool) decode as
        U+FFFD: the rest of the theme still serves, and JSON this breaks goes
        through the same checks as any other damaged file instead of raising
        into callers that only expect OSError.
        """
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            if path not in Event._UNDECODABLE_WARNED:
                if len(Event._UNDECODABLE_WARNED) > 256:
                    Event._UNDECODABLE_WARNED.clear()
                Event._UNDECODABLE_WARNED.add(path)
                log.warning(
                    "[Theme Pro] %s is not valid UTF-8; reading it with the bad bytes replaced",
                    path,
                )
            return path.read_text(encoding="utf-8", errors="replace")

    def _load_css(self, user_id: str | None = None) -> str | None:
        """Read theme CSS from disk, or None if not found."""
        return Event._read_theme_file(self._get_css_path(user_id))

    def _get_state_path(self, user_id: str | None = None) -> Path:
        """Return the path to the persisted theme state JSON file."""
        return self._get_css_path(user_id).with_name("open_theme_designer.json")

    def _load_state(self, user_id: str | None = None) -> str | None:
        """Read theme state JSON from disk, or None if not found."""
        return Event._read_theme_file(self._get_state_path(user_id))

    # Structured CSS sections — the same theme CSS broken into the four marker
    # regions. Persisted alongside the flat CSS so consumers (bootloader auth
    # stripping, custom.css safe subset) assemble what they need instead of
    # regex-slicing the concatenated blob. Concatenating the four sections in
    # this order reproduces the flat CSS exactly.
    SECTION_KEYS = ("vars", "structural", "gradient", "custom")

    def _get_sections_path(self, user_id: str | None = None) -> Path:
        """Return the path to the persisted CSS sections JSON file."""
        return self._get_css_path(user_id).with_name("open_theme_designer_sections.json")

    def _load_sections(self, user_id: str | None = None) -> dict | None:
        """Read structured CSS sections from disk, or None if missing/invalid.

        None means "no sections available" — callers fall back to regex-slicing
        the flat CSS (themes saved by pre-sections designer builds).
        """
        path = self._get_sections_path(user_id)
        if not path.exists():
            return None
        try:
            data = _json.loads(Event._read_theme_file(path))
        except Exception:
            return None
        if not isinstance(data, dict) or not all(
            isinstance(data.get(k), str) for k in self.SECTION_KEYS
        ):
            return None
        return {k: data[k] for k in self.SECTION_KEYS}

    def _delete_sections(self, user_id: str | None = None) -> None:
        """Remove the sections file (stale-prevention when only flat CSS is saved)."""
        path = self._get_sections_path(user_id)
        if path.exists():
            path.unlink()
            log.info("[Theme Pro] Deleted CSS sections file")

    def _get_library_path(self, user_id: str | None = None) -> Path:
        """Return the path to the persisted preset/snapshot library file."""
        return self._get_css_path(user_id).with_name("open_theme_designer_library.json")

    def _save_library(self, library: str, user_id: str | None = None) -> None:
        """Write preset/snapshot library JSON to disk atomically."""
        path = self._get_library_path(user_id)
        Event._atomic_write(path, library)
        log.info("[Theme Pro] Saved library to %s (%d bytes)", path, len(library))

    def _load_library(self, user_id: str | None = None) -> str | None:
        """Read preset/snapshot library JSON from disk, or None if not found."""
        return Event._read_theme_file(self._get_library_path(user_id))

    @staticmethod
    def _is_json_object(text) -> bool:
        """Whether text is a string holding a JSON object."""
        try:
            return isinstance(text, str) and isinstance(_json.loads(text), dict)
        except (ValueError, RecursionError):
            return False

    def _load_library_or_set_aside(
        self, user_id: str | None = None
    ) -> tuple[str | None, str | None]:
        """(library, None), or (None, the name it was kept under) when the
        file has text but isn't a JSON object. The designer would open on an
        empty gallery and its next library save would overwrite a file that
        may still be repairable, so it's renamed aside, stamped so a second
        bad file doesn't replace the first. Checked again under the save
        lock: a save that lands meanwhile is kept, not renamed. The name is
        also noted beside the library for _take_library_notice, since the
        Launcher's hidden apply frame loads the designer too."""
        import time as _time

        library = self._load_library(user_id)
        if not (library and library.strip()):
            return None, None
        if Event._is_json_object(library):
            return library, None
        path = self._get_library_path(user_id)
        with Event._save_transaction():
            library = Event._read_theme_file(path)
            if not (library and library.strip()):
                return None, None
            if Event._is_json_object(library):
                return library, None
            stamp = _time.strftime("%Y%m%d-%H%M%S")
            aside = path.with_name(f"{path.name}.corrupt-{stamp}")
            n = 1
            while aside.exists():
                n += 1
                aside = path.with_name(f"{path.name}.corrupt-{stamp}-{n}")
            path.rename(aside)
            notice = self._library_notice_path(user_id)
            try:
                Event._atomic_write(
                    notice, (Event._read_theme_file(notice) or "") + aside.name + "\n"
                )
            except OSError as e:
                log.warning(
                    "[Theme Pro] Couldn't record the kept library name for the designer: %s", e
                )
        log.warning(
            "[Theme Pro] %s isn't a JSON object; kept it as %s and started an empty gallery",
            path,
            aside.name,
        )
        return None, aside.name

    def _library_notice_path(self, user_id: str | None = None) -> Path:
        path = self._get_library_path(user_id)
        return path.with_name(path.name + ".kept")

    def _take_library_notice(self, user_id: str | None = None) -> str | None:
        """The names libraries were kept under since a designer last said so,
        or None; read once, for a designer someone sees."""
        notice = self._library_notice_path(user_id)
        if not notice.exists():
            return None
        with Event._save_transaction():
            names = (Event._read_theme_file(notice) or "").split()
            notice.unlink(missing_ok=True)
        return ", ".join(names) or None

    # -- delivery assembly -----------------------------------------------------
    # Blocking (stat + read + regex post-processing): route handlers call these
    # via asyncio.to_thread so a cache miss never stalls the event loop.

    def _get_css_delivery(self):
        """Return (css, etag) for /theme.css delivery, or None when unavailable.

        Post-processing runs regexes over the full CSS — cache the result per
        (file mtime, valve settings) so the steady-state cost is a stat().
        Every page load of every user hits this path. Read errors (including
        the file vanishing between stat() and read during a reset) resolve to
        None — callers serve the graceful empty response, never a 500.
        """
        try:
            css_mtime = Event._file_sig(self._get_css_path())
        except OSError:
            return None
        cache_key = (css_mtime, *self._css_valve_key())
        cached = Event._css_delivery_cache
        if cached and cached[0] == cache_key:
            return cached[1], cached[2]
        try:
            raw = self._load_css()
        except OSError:
            raw = None  # File vanished/unreadable between stat() and read (reset race)
        if not raw:
            return None
        css = self._postprocess_css(raw)
        # usedforsecurity=False: this is a cache validator, not a security
        # digest — the flag keeps md5 usable on FIPS hosts (where a bare
        # md5() raises ValueError).
        etag = '"' + hashlib.md5(css.encode("utf-8"), usedforsecurity=False).hexdigest() + '"'
        Event._css_delivery_cache = (cache_key, css, etag)
        return css, etag

    def _get_state_delivery(self):
        """Return (state, etag) for /state.json delivery, or None when unavailable.

        Mirrors _get_css_delivery: cached per (state mtime, sections mtime,
        valve settings), OSError-safe against reset races.
        """
        try:
            state_mtime = Event._file_sig(self._get_state_path())
        except OSError:
            return None
        try:
            sections_mtime = Event._file_sig(self._get_sections_path())
        except OSError:
            sections_mtime = None
        cache_key = (state_mtime, sections_mtime, *self._state_valve_key())
        cached = Event._state_delivery_cache
        if cached and cached[0] == cache_key:
            return cached[1], cached[2]
        try:
            raw = self._load_state()
        except OSError:
            raw = None  # File vanished/unreadable between stat() and read (reset race)
        if not raw:
            return None
        state = self._postprocess_state(raw)
        # Merge valve-postprocessed CSS sections (_cssSections) so the
        # bootloader assembles auth-page CSS without regex-slicing
        state = self._state_with_sections(state)
        # usedforsecurity=False — see _get_css_delivery (FIPS-safe).
        etag = '"' + hashlib.md5(state.encode("utf-8"), usedforsecurity=False).hexdigest() + '"'
        Event._state_delivery_cache = (cache_key, state, etag)
        return state, etag

    _personal_delivery_cache = {}  # (user_id, kind) -> (cache_key, body, etag)
    _PERSONAL_CACHE_MAX = 512

    @staticmethod
    def _cache_put(cache: dict, key, value) -> None:
        """Store key in a per-user cache, evicting the oldest entry when full.

        Callers run in to_thread workers, so two misses can evict at once:
        the same oldest key (KeyError) or mid-insert (RuntimeError from the
        iterator). Losing a cache entry is harmless; a 500 is not.
        """
        if len(cache) >= Event._PERSONAL_CACHE_MAX:
            with suppress(RuntimeError):
                cache.pop(next(iter(cache), None), None)
        cache[key] = value

    # Saves run their file work in a thread, one at a time, so two of them
    # can't interleave one's CSS with the other's state
    import threading as _threading

    _save_lock = _threading.Lock()

    @classmethod
    @contextmanager
    def _save_transaction(cls):
        """Serialize a save or reset across threads and processes.

        With several workers or containers on one DATA_DIR, only the file
        lock under theme/ keeps two saves from leaving one's CSS beside the
        other's state. The thread lock keeps one process's threads from
        sharing a single file lock.
        """
        with cls._save_lock:
            from open_webui.env import DATA_DIR

            with cls._file_lock(Path(DATA_DIR) / "theme" / ".save.lock"):
                yield

    def _get_personal_delivery(self, user_id: str, kind: str):
        """(body, etag) of a user's personal theme.css or state.json, or None.

        The same valve post-processing as the instance theme: personal themes
        stay within the limits the admin sets (canvas, sidebar, overlays).
        Cached per user on file mtimes and valves, like the instance delivery.
        """
        css_path = self._get_css_path(user_id)
        path = css_path if kind == "css" else self._get_state_path(user_id)
        try:
            mtime = Event._file_sig(path)
        except OSError:
            return None
        try:
            sections_mtime = Event._file_sig(self._get_sections_path(user_id))
        except OSError:
            sections_mtime = None
        # The state's valves for the CSS too: a superset, so never stale
        cache_key = (mtime, sections_mtime, *self._state_valve_key())
        cached = Event._personal_delivery_cache.get((user_id, kind))
        if cached and cached[0] == cache_key:
            return cached[1], cached[2]
        try:
            raw = Event._read_theme_file(path)
        except OSError:
            return None
        if not raw:
            return None
        if kind == "css":
            body = self._postprocess_css(raw)
        else:
            body = self._state_with_sections(self._postprocess_state(raw, personal=True), user_id)
        etag = '"' + hashlib.md5(body.encode("utf-8"), usedforsecurity=False).hexdigest() + '"'
        Event._cache_put(Event._personal_delivery_cache, (user_id, kind), (cache_key, body, etag))
        return body, etag

    def _delete_personal_theme(self, user_id: str) -> None:
        """Remove a user's personal theme, keeping their library: the user is
        back on the instance theme, with their saved themes still there."""
        for path in (
            self._get_css_path(user_id),
            self._get_state_path(user_id),
            self._get_sections_path(user_id),
        ):
            with suppress(FileNotFoundError):
                path.unlink()
        for kind in ("css", "state"):
            Event._personal_delivery_cache.pop((user_id, kind), None)
        log.info("[Theme Pro] Removed a personal theme; that user is back on the instance theme")

    def _is_unchanged_save(self, css, state, sections, library, user_id: str | None) -> bool:
        """Whether a save would write exactly what's already stored."""
        if css != self._load_css(user_id):
            return False
        if not (isinstance(state, str) and state) or state != self._load_state(user_id):
            return False
        valid = isinstance(sections, dict) and all(
            isinstance(sections.get(k), str) for k in self.SECTION_KEYS
        )
        if valid and {k: sections[k] for k in self.SECTION_KEYS} != self._load_sections(user_id):
            return False
        return not (library and isinstance(library, str) and library != self._load_library(user_id))

    def _delete_personal_library(self, user_id: str) -> None:
        """Remove a user's saved themes and presets, for a Factory Reset in
        their personal designer."""
        with suppress(FileNotFoundError):
            self._get_library_path(user_id).unlink()

    def _delete_user_themes(self, user_id: str) -> bool:
        """Remove everything a deleted account kept here: its personal theme
        and its library. True when there was something to remove."""
        import shutil

        folder = self._get_css_path(user_id).parent
        for kind in ("css", "state"):
            Event._personal_delivery_cache.pop((user_id, kind), None)
        Event._library_tag_cache.pop(user_id, None)
        if not folder.is_dir():
            return False
        shutil.rmtree(folder, ignore_errors=True)
        log.info("[Theme Pro] Removed the personal theme and library of a deleted account")
        return True

    def _prime_delivery_caches(self, app) -> dict:
        """Recompute both delivery caches; return their ETags for broadcasting.

        Called via asyncio.to_thread right before a theme-update broadcast so
        (a) the etags ride in the SSE payload — clients already holding that
        exact version skip the refetch — and (b) the first post-save fetches
        hit a warm cache instead of all racing the post-processing pipeline.
        """
        css = self._get_css_delivery()
        state = self._get_state_delivery()
        # Warm the composed-asset producers too: they run inside the request
        # handler, so the first page load after a save would otherwise rebuild
        # both fragments on the event loop.
        self._safe_subset_css()
        self._loader_fragment(reload_active(app))
        return {
            "cssTag": css[1] if css else None,
            "stateTag": state[1] if state else None,
        }

    _legacy_index_cleaned = False

    def _clean_legacy_index_injection(self) -> None:
        """One-shot removal of blocks written into index.html by pre-registry builds.

        Up to v1.6.2 this function injected the bootloader, a <style
        id="owui-server-theme"> subset and a <script id="owui-theme-state">
        block straight into index.html. Those blocks survive an upgrade (the
        file lives on the container filesystem, not in the image), so without
        this pass an upgraded install would run two bootloaders and keep
        applying a frozen CSS subset that no save can ever refresh.

        This is the only remaining writer to index.html, it runs once per
        process, and it only ever removes. The lock file serializes it with
        the other workers starting at the same time.
        """
        if Event._legacy_index_cleaned:
            return
        Event._legacy_index_cleaned = True

        path = self._find_index_file()
        if not path:
            return
        try:
            from open_webui.env import DATA_DIR

            with Event._file_lock(Path(DATA_DIR) / "theme" / ".index.lock"):
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                cleaned = self._strip_legacy_index_blocks(content)
                if cleaned != content:
                    Event._atomic_write(path, cleaned)
                    log.info(
                        "[Theme Pro] Removed legacy index.html injection from %s — "
                        "the bootloader and theme CSS now ship via the shared "
                        "static-asset registry",
                        path,
                    )
        except Exception as e:
            log.warning(
                "[Theme Pro] Could not clean legacy index.html injection from %s: %s",
                path,
                e,
            )

    # -- route registration --------------------------------------------------

    class _BodyTooLarge(Exception):
        pass

    @staticmethod
    async def _read_json_capped(request, cap: int):
        """The request's JSON, reading at most cap bytes of body.

        The routes' Content-Length checks don't see a chunked upload, which
        has no length: request.json() buffered all of it, so one signed-in
        user could stream a worker out of memory. Raises _BodyTooLarge past
        the cap and ValueError for a body that isn't JSON.
        """
        buf = bytearray()
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > cap:
                raise Event._BodyTooLarge()
        return _json.loads(bytes(buf))

    @staticmethod
    async def _from_other_origin(request) -> bool:
        """Whether a web page on another origin sent this request.

        Auth accepts the token cookie, which the browser sends from any
        same-site origin (any site at all under SameSite=None), and Open
        WebUI's default CORS_ALLOW_ORIGIN='*' with credentials passes every
        origin's preflight. Sec-Fetch-Site is set by the browser alone, so it
        decides when present. Browsers send it only to https and localhost,
        so on plain http the Origin's hostname is compared instead: with the
        Host header's, port and case aside since cookies ignore both, or with
        WEBUI_URL's for a proxy that rewrites Host. X-Forwarded-Host is not
        trusted, since a page that passed the preflight can set any header.
        A request with neither header did not come from a web page."""
        from urllib.parse import urlsplit

        site = request.headers.get("sec-fetch-site")
        if site is not None:
            return site != "same-origin"
        origin = request.headers.get("origin")
        if origin is None:
            return False
        try:
            hostname = urlsplit(origin).hostname
            if not hostname:
                return True  # Origin: null, a sandboxed frame
            if hostname == urlsplit("//" + request.headers.get("host", "")).hostname:
                return False
            from open_webui.models.config import Config

            webui_url = await Config.get("webui.url")
            return not webui_url or hostname != urlsplit(webui_url).hostname
        except Exception:
            return True

    @staticmethod
    def _cookie_user_id(request) -> str | None:
        """The account the token cookie names, by its signature and expiry
        alone, without the database reads of plugin_user."""
        from open_webui.utils.auth import decode_token

        token = request.cookies.get("token")
        if not token or token.startswith("sk-"):
            return None
        claims = decode_token(token)
        uid = claims.get("id") if isinstance(claims, dict) else None
        return str(uid) if uid else None

    @classmethod
    def _share_sse_clients(cls, app) -> None:
        """Point this exec's client set at app.state's, which outlives a
        re-exec of this source, so broadcasts and the exit hook reach the
        streams an older exec opened. A set gives O(1) disconnect cleanup:
        with a list, mass disconnects (deploys) degrade to O(n^2) scans.
        _sse_cids maps each stream's id to its queue for the same reason: every
        page binds its stream as it reconnects."""
        existing = getattr(app.state, "_theme_sse_clients", None)
        if existing is None:
            app.state._theme_sse_clients = set()
        elif not isinstance(existing, set):
            # Pre-set builds stored a list: convert, keeping live client queues
            app.state._theme_sse_clients = set(existing)
        cls._sse_clients = app.state._theme_sse_clients
        cids = getattr(app.state, "_theme_sse_cids", None)
        if not isinstance(cids, dict):
            cids = app.state._theme_sse_cids = {}
        if cls._sse_cids is not cids or len(cids) != len(cls._sse_clients):
            # A build without the map opened or closed streams in the set
            # alone: rebuilt on each exec's first share and whenever the two
            # disagree. In place: an older exec's streams still hold this dict.
            cids.clear()
            cids.update((q._tdp_cid, q) for q in cls._sse_clients if hasattr(q, "_tdp_cid"))
        cls._sse_cids = cids

    def _register_route(self, app) -> None:
        """Mount the designer's routes at the current designer URL.

        plugin_mount puts owpp's sign-in guard on every route, keeps them ahead of the SPA
        catch-all, and replaces this function's earlier mount of the same name wherever it was,
        so a reload or a designer_url change leaves no stale route behind. Two mounts:

        - "designer": a signed-in user. The routes that need an admin are marked PluginAdmin.
        - "public": what a signed-out page needs, since the sign-in page is themed too: the
          theme, its live updates and the sign-in picture. The personal theme is here as well,
          because the bootloader reads an empty answer as "use the instance theme", and that is
          what someone signed out gets.

        Pages loaded before a designer_url change keep the old URL compiled into their
        bootloader, so the read-only routes stay at every URL this app has served (until a
        restart), each its own public mount named after its URL.
        """
        route_base = self._get_route_base()

        # NOTE: _published is NOT reset here. Route registration can happen
        # without needing a full bootloader + CSS re-injection cycle.

        Event._share_sse_clients(app)

        alias_bases = getattr(app.state, "_theme_alias_bases", None)
        if not isinstance(alias_bases, set):
            alias_bases = set()
            app.state._theme_alias_bases = alias_bases
        prev = Event._routes_registered_url  # normalized, unlike the raw valve
        if prev and prev.startswith("/api/") and prev != route_base and len(alias_bases) < 16:
            alias_bases.add(prev)
        alias_bases.discard(route_base)

        event_instance = self

        from starlette.responses import (
            HTMLResponse,
            JSONResponse,
            PlainTextResponse,
            StreamingResponse,
        )

        def _disabled():
            return JSONResponse(
                {"error": "Theme Designer Pro is currently disabled"},
                status_code=503,
            )

        def _personal_off():
            return JSONResponse(
                {"error": "Personal themes are turned off on this instance"},
                status_code=403,
            )

        async def _cross_origin_refusal(request: Request):
            """A 403 for a change sent by a page on another origin, else None."""
            if not await Event._from_other_origin(request):
                return None
            return JSONResponse(
                {"error": "Changes must come from Open WebUI's own pages"},
                status_code=403,
            )

        async def _save_request_refusal(request: Request):
            """The checks every save shares, or None when the request may go on."""
            if not reload_active(request.app):
                return _disabled()
            refusal = await _cross_origin_refusal(request)
            if refusal is not None:
                return refusal
            ctype = request.headers.get("content-type", "")
            if not ctype.lower().startswith("application/json"):
                return JSONResponse(
                    {"error": "Content-Type must be application/json"},
                    status_code=415,
                )
            # Reject oversized payloads up front — the per-field caps in
            # _handle_css_save only run after the body is read. 64MB
            # comfortably covers the field caps (5+5+20MB) plus JSON escaping
            # overhead. A chunked upload has no length; _read_json_capped
            # bounds that one.
            try:
                if int(request.headers.get("content-length") or 0) > 64 * 1024 * 1024:
                    return JSONResponse(
                        {"error": "Request body exceeds 64MB limit"},
                        status_code=413,
                    )
            except ValueError:
                pass  # Malformed header — let the framework handle it
            return None

        async def held_tags(user_id):
            try:
                return await asyncio.to_thread(event_instance._held_tags, user_id)
            except Exception:
                return {}  # The designer then never reloads for a resync

        def _tagged_response(request, delivery, media_type, cache_control):
            body, etag = delivery
            headers = {"Cache-Control": cache_control, "ETag": etag}
            # Gzipping proxies send the tag back weakened to W/"...".
            if request.headers.get("if-none-match", "").removeprefix("W/") == etag:
                return PlainTextResponse("", status_code=304, headers=headers)
            return PlainTextResponse(content=body, media_type=media_type, headers=headers)

        def _delivery_response(request, delivery, media_type, empty, cache_control):
            """The delivery with its ETag, or an empty 200 when there is none.

            Not 204: a 204 must not carry a body, and some proxies rewrite or
            warn on it. The bootloader reads the empty body (or `{}`) as nothing saved.
            """
            if delivery is None:
                return PlainTextResponse(
                    empty, media_type=media_type, headers={"Cache-Control": "no-store"}
                )
            return _tagged_response(request, delivery, media_type, cache_control)

        # Personal, so never stored by a shared cache.
        PERSONAL_CACHE = "private, no-cache, must-revalidate"

        async def _personal_user(request: Request):
            """The signed-in user whose personal theme to serve, or None: signed out, or
            personal themes off, which the personal routes answer with an empty body."""
            if not reload_active(request.app) or not event_instance.valves.allow_personal_themes:
                return None
            return await plugin_user(request)

        # A picture's GET, DELETE and POST (upload), once the route has
        # checked who may do which.
        async def _picture(request, path, url, cache_control="private, no-cache"):
            if request.method == "GET":
                try:
                    data = await asyncio.to_thread(path.read_bytes)
                except OSError:
                    return PlainTextResponse("", status_code=404)
                mime = Event._image_mime(data)
                if not mime:
                    return PlainTextResponse("", status_code=404)
                etag = '"' + hashlib.sha256(data).hexdigest()[:16] + '"'
                headers = {
                    "ETag": etag,
                    "Cache-Control": cache_control,
                    "X-Content-Type-Options": "nosniff",
                }
                if request.headers.get("if-none-match", "").removeprefix("W/") == etag:
                    return Response(status_code=304, headers=headers)
                return Response(data, media_type=mime, headers=headers)
            if request.method == "DELETE":
                try:
                    await asyncio.to_thread(path.unlink)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    return JSONResponse(
                        {"error": f"Could not remove the picture: {e}"}, status_code=500
                    )
                return JSONResponse({"ok": True})
            buf = bytearray()
            async for chunk in request.stream():
                buf += chunk
                if len(buf) > Event.AUTH_BG_MAX_BYTES:
                    return JSONResponse({"error": "The picture is over 5 MB"}, status_code=413)
            data = bytes(buf)
            if not Event._image_mime(data):
                return JSONResponse(
                    {"error": "Use a PNG, JPEG, GIF or WebP picture"}, status_code=415
                )
            try:
                await asyncio.to_thread(Event._write_bytes, path, data)
            except OSError as e:
                return JSONResponse({"error": f"Could not save the picture: {e}"}, status_code=500)
            return JSONResponse({"url": f"{url}?v={hashlib.sha256(data).hexdigest()[:12]}"})

        # ---- the "designer" mount: a signed-in user ------------------------------------

        designer = APIRouter(prefix=route_base)

        # GET {base}: the designer, for an admin; ?scope=me, on the user's own theme.
        @designer.get("")
        async def theme_designer_page(request: Request, user: DesignerUser):
            if not reload_active(request.app):
                return _disabled()
            apply_token = request.query_params.get("apply")
            if request.query_params.get("scope") == "me":
                if not event_instance.valves.allow_personal_themes:
                    # Opened in a frame (the Settings tab, the Launcher tool in
                    # a chat), a sentence reads better than raw JSON.
                    if "text/html" in request.headers.get("accept", ""):
                        return HTMLResponse(
                            content=Event._notice_page(
                                "Personal themes are turned off on this instance.",
                                "An admin can turn on Allow Personal Themes in Theme Designer Pro's valves.",
                            ),
                            status_code=403,
                            headers={"Cache-Control": "no-store"},
                        )
                    return _personal_off()
                return HTMLResponse(
                    content=await asyncio.to_thread(
                        event_instance._build_html,
                        user_id=user.id,
                        apply=event_instance._read_apply_token(apply_token, user.id, personal=True),
                    ),
                    headers={"Cache-Control": "no-store"},
                )
            return HTMLResponse(
                content=await asyncio.to_thread(
                    event_instance._build_html,
                    apply=event_instance._read_apply_token(apply_token, user.id, personal=False),
                ),
                headers={"Cache-Control": "no-store"},
            )

        # POST {base}: save the instance theme.
        @designer.post("")
        async def save_theme_css(request: Request, user: PluginAdmin):
            refusal = await _save_request_refusal(request)
            if refusal is not None:
                return refusal
            return await event_instance._handle_css_save(request)

        # POST {base}/me: save the signed-in user's own theme.
        @designer.post("/me")
        async def save_personal_theme(request: Request, user: PluginUser):
            refusal = await _save_request_refusal(request)
            if refusal is not None:
                return refusal
            if not event_instance.valves.allow_personal_themes:
                return _personal_off()
            return await event_instance._handle_css_save(request, user_id=user.id)

        # POST {base}/consult: the AI Consultant.
        @designer.post("/consult")
        async def ai_consult(request: Request, user: PluginUser):
            refusal = await _save_request_refusal(request)
            if refusal is not None:
                return refusal
            if not event_instance.valves.enable_ai_consultant:
                return JSONResponse({"error": "The AI Consultant is turned off"}, status_code=403)
            # Users design only their own theme, so they consult only when they
            # can have one.
            if user.role != "admin" and not event_instance.valves.allow_personal_themes:
                return JSONResponse({"error": "Access denied"}, status_code=403)
            return await event_instance._handle_consult(request, user)

        # GET {base}/library.json: the instance's saved themes and presets.
        @designer.get("/library.json")
        async def serve_theme_library(request: Request, user: PluginAdmin):
            if not reload_active(request.app):
                return _disabled()
            try:
                library = await asyncio.to_thread(event_instance._load_library)
            except OSError:
                library = None  # Reset race / unreadable data dir — serve empty
            return PlainTextResponse(library or "{}", media_type="application/json")

        async def bind_sse(request: Request, user: PluginUser):
            """Tie one open stream to the signed-in user, so their personal
            theme saves and Chat Background Image changes reach it. The page
            sends the id its stream announced, with the same token it signs
            every other request with."""
            refusal = await _cross_origin_refusal(request)
            if refusal is not None:
                return refusal
            try:
                body = await Event._read_json_capped(request, 4096)
            except Exception:
                body = None
            cid = body.get("cid") if isinstance(body, dict) else None
            if not isinstance(cid, str) or not _re.fullmatch(r"[A-Za-z0-9_-]{16,64}", cid):
                return JSONResponse({"error": "Invalid stream id"}, status_code=400)
            # The stream may be held by another worker; Redis tells it
            if not Event._bind_stream(cid, user.id):
                Event._redis_publish(f"{Event._CTRL_PREFIX}bind {cid} {user.id}\n\n")
            # The personal theme saved now, by the tags its fetches carry, so
            # the page fetches again only when it shows something else: a save
            # that landed before this claim reached no stream
            tags = await asyncio.to_thread(event_instance._personal_tags, user.id)
            return JSONResponse({"status": "ok", **tags})

        designer.add_api_route("/events/bind", bind_sse, methods=["POST"])

        # {base}/page-background: the picture behind pages without a chat. The
        # instance theme's shows to anyone signed in; only an admin changes it.
        @designer.get("/page-background")
        async def page_background(request: Request):
            if not reload_active(request.app):
                return _disabled()
            return await _picture(
                request, event_instance._get_page_bg_path(), route_base + "/page-background"
            )

        @designer.api_route("/page-background", methods=["POST", "DELETE"])
        async def change_page_background(request: Request, user: PluginAdmin):
            if not reload_active(request.app):
                return _disabled()
            refusal = await _cross_origin_refusal(request)
            if refusal is not None:
                return refusal
            return await _picture(
                request, event_instance._get_page_bg_path(), route_base + "/page-background"
            )

        # {base}/me/page-background: a personal theme's, for its owner alone.
        @designer.api_route("/me/page-background", methods=["GET", "POST", "DELETE"])
        async def personal_page_background(request: Request, user: PluginUser):
            if not reload_active(request.app):
                return _disabled()
            if not event_instance.valves.allow_personal_themes:
                return _personal_off()
            if request.method != "GET":
                refusal = await _cross_origin_refusal(request)
                if refusal is not None:
                    return refusal
            return await _picture(
                request,
                event_instance._get_page_bg_path(user.id),
                route_base + "/me/page-background",
            )

        # ---- the "public" mount: what signed-out pages need too ------------------------

        async def serve_theme_css(request: Request):
            """The saved theme CSS. No auth: themes are visual.

            The bootloader fetches with cache 'no-cache', so the ETag makes an
            unchanged theme a 304 on every page load.
            """
            delivery = None
            if reload_active(request.app):
                delivery = await asyncio.to_thread(event_instance._get_css_delivery)
            return _delivery_response(
                request, delivery, "text/css", "", "no-cache, must-revalidate"
            )

        async def serve_theme_state(request: Request):
            """The saved theme state, for the bootloader's seeding. No auth.
            Unchanged state is a 304 instead of the full canvas script again."""
            delivery = None
            if reload_active(request.app):
                delivery = await asyncio.to_thread(event_instance._get_state_delivery)
            return _delivery_response(
                request, delivery, "application/json", "{}", "no-cache, must-revalidate"
            )

        async def serve_personal_css(request: Request):
            user = await _personal_user(request)
            delivery = None
            if user is not None:
                delivery = await asyncio.to_thread(
                    event_instance._get_personal_delivery, user.id, "css"
                )
            return _delivery_response(request, delivery, "text/css", "", PERSONAL_CACHE)

        async def serve_personal_state(request: Request):
            user = await _personal_user(request)
            delivery = None
            if user is not None:
                delivery = await asyncio.to_thread(
                    event_instance._get_personal_delivery, user.id, "state"
                )
            return _delivery_response(request, delivery, "application/json", "{}", PERSONAL_CACHE)

        async def serve_personal_library(request: Request):
            user = await _personal_user(request)
            library = None
            if user is not None:
                try:
                    library = await asyncio.to_thread(event_instance._load_library, user.id)
                except OSError:
                    library = None
            return PlainTextResponse(
                library or "{}",
                media_type="application/json",
                headers={"Cache-Control": "no-store"},
            )

        async def theme_sse(request: Request):
            """Server-Sent Events endpoint for live theme updates."""
            sse_headers = {
                "Cache-Control": "no-cache, no-store, no-transform",
                "Content-Encoding": "identity",  # Prevent compression buffering
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx/Cloudflare buffering
            }

            # Connection cap: this endpoint is unauthenticated (auth pages need
            # live updates too), so bound per-worker resource usage. Over-cap
            # clients get a valid SSE body that only sets a long retry interval
            # and then ends — EventSource retries later, and the bootloader's
            # visibilitychange refetch keeps them themed in the meantime.
            # Once uvicorn is stopping, a new stream would hold its graceful
            # wait, so it gets the same body with the normal retry.
            ending = getattr(request.app.state, "_theme_streams_ending", False)
            if ending or len(Event._sse_clients) >= Event._SSE_MAX_CLIENTS:
                # An over-cap page still says hello, so it checks for missed
                # saves on each retry; a stopping worker's doesn't, so the
                # restarted worker's hello is the one that refetches
                body = (
                    "retry: 3000\n\n"
                    if ending
                    else (
                        "retry: 60000\n\n"
                        f'event: hello\ndata: {{"spread":{Event._RESYNC_SPREAD}}}\n\n'
                    )
                )
                return StreamingResponse(
                    iter([body]),
                    media_type="text/event-stream",
                    headers=sse_headers,
                )

            # One shared heartbeat task fans keep-alives into every client
            # queue, replacing a per-connection wait_for timeout — per-client
            # timers get expensive with tens of thousands of connections.
            # Stored on app.state so it survives function hot-reloads;
            # restarted here if it ever died (self-healing: without it, idle
            # connections get proxy-killed and EventSource reconnects here).
            _hb = getattr(request.app.state, "_theme_sse_heartbeat", None)
            if (_hb is None or _hb.done()) and not getattr(
                request.app.state, "_theme_shutting_down", False
            ):

                async def _sse_heartbeat():
                    while True:
                        await asyncio.sleep(Event._SSE_HEARTBEAT_SECONDS)  # 15s for Cloudflare
                        Event._deliver(": heartbeat\n\n")

                request.app.state._theme_sse_heartbeat = asyncio.get_running_loop().create_task(
                    _sse_heartbeat()
                )

            queue = asyncio.Queue(maxsize=8)
            # Signed-in pages also hear what is theirs alone: their personal
            # theme, and their Chat Background Image changing. The stream
            # stays open to everyone, so a failed check only means none of
            # that on it. Without personal themes it carries no theme of the
            # user's, only a nudge to look their settings up again, so the
            # token cookie's signature is check enough: every page connects,
            # and a full check on each would read the database each time.
            user = None
            if event_instance.valves.allow_personal_themes:
                user = await plugin_user(request)
                if user is not None:
                    queue._tdp_user = user.id
            else:
                uid = Event._cookie_user_id(request)
                if uid:
                    queue._tdp_user = uid
            # EventSource sends only cookies, and Open WebUI's token cookie
            # can be missing while the page is signed in by its localStorage
            # token: a session cookie after a browser restart, a Secure
            # cookie on plain http, or a sign-in after the page loaded. The
            # stream's first message names it, and the page claims it with
            # its own token at POST /events/bind.
            import secrets

            queue._tdp_cid = secrets.token_urlsafe(18)

            # A designer's stream (?_badge) opens with a resync naming what
            # is saved now: nothing resends a save broadcast while it was
            # down. For the signed-in owner's personal designer, or "" for an
            # admin's instance one.
            resync_for = None
            if "_badge" in request.query_params and reload_active(request.app):
                if request.query_params.get("scope") == "me":
                    if user is not None:
                        resync_for = getattr(queue, "_tdp_user", None)
                elif user is not None:
                    resync_for = "" if getattr(user, "role", None) == "admin" else None
                else:
                    signed_in = await plugin_user(request)
                    if signed_in is not None and signed_in.role == "admin":
                        resync_for = ""

            async def event_stream():
                # Registered here, not before the response starts: a client
                # that disconnects first never starts this generator, so its
                # finally never ran and the queue stayed in the set for good,
                # filling it toward the cap
                Event._sse_clients.add(queue)
                Event._sse_cids[queue._tdp_cid] = queue
                try:
                    # The exit hook already woke the streams it could see:
                    # this one started after (its request was still awaiting
                    # auth, or its body had not started)
                    if getattr(request.app.state, "_theme_streams_ending", False):
                        return
                    # Flush padding: Cloudflare's free-tier proxy may buffer small SSE
                    # chunks until an internal threshold (~4KB) is reached. Sending a
                    # burst of SSE comments forces the proxy into streaming mode.
                    yield "retry: 3000\n\n"  # Auto-reconnect after 3s
                    yield ": " + "x" * 4096 + "\n\n"  # Flush padding
                    yield ": stream-ready\n\n"
                    hello = {"spread": Event._RESYNC_SPREAD, "cid": queue._tdp_cid}
                    # A page signed in as this account needs no claim
                    if getattr(queue, "_tdp_user", None):
                        hello["uid"] = queue._tdp_user
                    yield f"event: hello\ndata: {_json.dumps(hello, separators=(',', ':'))}\n\n"
                    if resync_for is not None:
                        # Read once the queue is in _sse_clients: a save
                        # broadcast after that reaches it, any before is read here
                        uid = resync_for or None
                        held = await held_tags(uid)
                        frames = []
                        if "theme" in held:
                            frames.append(
                                (
                                    "theme-update",
                                    {"cssTag": held["theme"][0], "stateTag": held["theme"][1]},
                                )
                            )
                        if "library" in held:
                            frames.append(
                                (
                                    "library-update",
                                    {
                                        "scope": "me" if uid else "instance",
                                        "tag": held["library"][0],
                                    },
                                )
                            )
                        if "personal" in held:
                            frames.append(
                                (
                                    "personal-theme-update",
                                    {
                                        "cssTag": held["personal"][0],
                                        "stateTag": held["personal"][1],
                                    },
                                )
                            )
                        for name, data in frames:
                            yield f"event: {name}\ndata: {_json.dumps({**data, 'resync': True}, separators=(',', ':'))}\n\n"
                    while True:
                        # Pre-formatted SSE strings; heartbeats arrive via the
                        # shared task above, so no per-client timeout needed.
                        msg = await queue.get()
                        if msg is None:
                            # Shutdown sentinel from _shutdown_cleanup(): end
                            # the stream so uvicorn's graceful wait for
                            # in-flight responses can complete. Without this,
                            # an open EventSource stalls shutdown until the
                            # container runtime SIGKILLs the process.
                            break
                        yield msg
                except (asyncio.CancelledError, GeneratorExit):
                    pass
                finally:
                    Event._sse_clients.discard(queue)
                    if Event._sse_cids.get(queue._tdp_cid) is queue:
                        del Event._sse_cids[queue._tdp_cid]

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers=sse_headers,
            )

        # {base}/auth-background: the sign-in page's picture. Anyone can read
        # it, since nobody is signed in there; only an admin changes it.
        async def auth_background(request: Request):
            if not reload_active(request.app):
                return _disabled()
            return await _picture(
                request,
                event_instance._get_auth_bg_path(),
                route_base + "/auth-background",
                "no-cache",
            )

        def read_only_routes(router: APIRouter) -> APIRouter:
            """What a page loaded at some time from this URL reads: at the designer URL, and at
            every URL it had before."""
            router.add_api_route("/theme.css", serve_theme_css, methods=["GET"])
            router.add_api_route("/state.json", serve_theme_state, methods=["GET"])
            router.add_api_route("/events", theme_sse, methods=["GET"])
            router.add_api_route("/me/theme.css", serve_personal_css, methods=["GET"])
            router.add_api_route("/me/state.json", serve_personal_state, methods=["GET"])
            router.add_api_route("/auth-background", auth_background, methods=["GET"])
            return router

        public = read_only_routes(APIRouter(prefix=route_base))
        public.add_api_route("/me/library.json", serve_personal_library, methods=["GET"])

        @public.api_route("/auth-background", methods=["POST", "DELETE"])
        async def change_auth_background(request: Request, user: PluginAdmin):
            if not reload_active(request.app):
                return _disabled()
            refusal = await _cross_origin_refusal(request)
            if refusal is not None:
                return refusal
            return await _picture(
                request,
                event_instance._get_auth_bg_path(),
                route_base + "/auth-background",
                "no-cache",
            )

        plugin_mount(app, designer, route_base, name="designer")
        plugin_mount(app, public, route_base, name="public", access="public")
        for base in sorted(alias_bases):
            alias = read_only_routes(APIRouter(prefix=base))
            alias.add_api_route("/events/bind", bind_sse, methods=["POST"])
            plugin_mount(app, alias, base, name=f"alias {base}", access="public")
        # The designer URL is no alias of itself, should it have been one
        plugin_mount(app, APIRouter(), route_base, name=f"alias {route_base}", access="public")
        log.info("[Theme Pro] Registered routes at %s", route_base)

    async def _handle_css_save(self, request, user_id: str | None = None) -> JSONResponse:
        """Handle POST to save or reset theme CSS + state.

        With user_id, the save is that user's personal theme: it goes to their
        own folder, and only their own open pages hear about it.
        """
        from starlette.responses import JSONResponse

        try:
            body = await Event._read_json_capped(request, 64 * 1024 * 1024)
        except Event._BodyTooLarge:
            return JSONResponse({"error": "Request body exceeds 64MB limit"}, status_code=413)
        except Exception:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"error": "Expected a JSON object"}, status_code=400)
        try:
            css = body.get("css", "")
            state = body.get("state", "")
            sections = body.get("sections")
            library = body.get("library", "")
            is_reset = body.get("reset", False)
            # The designer tab that saved, so its own broadcast doesn't make it
            # reload while every other open designer does.
            origin = body.get("origin")
            if not (isinstance(origin, str) and _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", origin)):
                origin = None
            # A save a designer makes on its own as it opens: other designers
            # don't reload for it. Open WebUI pages still refetch as usual.
            settle = body.get("settle") is True

            # Size caps — admin-only endpoint, but a runaway payload would be
            # written to disk and trigger a refetch on every connected client.
            for name, value, cap_mb in (
                ("css", css, 5),
                ("state", state, 5),
                ("library", library, 20),
            ):
                if isinstance(value, str) and len(value) > cap_mb * 1024 * 1024:
                    return JSONResponse(
                        {"error": f"{name} exceeds {cap_mb}MB limit"},
                        status_code=413,
                    )
            if isinstance(sections, dict):
                total = sum(len(v) for v in sections.values() if isinstance(v, str))
                if total > 5 * 1024 * 1024:
                    return JSONResponse({"error": "sections exceeds 5MB limit"}, status_code=413)

            if is_reset and user_id:
                # A personal reset puts the user back on the instance theme.
                # Under the save lock, like a save: a reset landing between a
                # save's CSS and state writes left the state without its CSS.
                wipe_library = body.get("wipe_library") is True

                def reset_personal():
                    with Event._save_transaction():
                        self._delete_personal_theme(user_id)
                        # Factory Reset also wipes their library; Use instance theme keeps it.
                        if wipe_library:
                            self._delete_personal_library(user_id)

                await asyncio.to_thread(reset_personal)
                tags = await asyncio.to_thread(self._personal_tags, user_id)
                Event._broadcast_personal(user_id, origin=origin, tags=tags)
                return JSONResponse({"status": "reset"})

            if is_reset:

                def reset_instance():
                    with Event._save_transaction():
                        for path, what in (
                            (self._get_css_path(), "CSS"),
                            (self._get_state_path(), "state"),
                            (self._get_library_path(), "gallery"),
                        ):
                            if path.exists():
                                path.unlink(missing_ok=True)
                                log.info("[Theme Pro] Deleted theme %s file", what)
                        self._delete_sections()

                await asyncio.to_thread(reset_instance)
                # No index.html work: the CSS fragment producer reads through
                # _get_css_delivery(), which now finds no file and returns "",
                # so the next request composes a custom.css without our block.
                # The loader fragment stays published so SSE survives the reset
                # and a theme saved afterwards still reaches loaded pages.
                # "reset", not "disabled": the function is still running, and
                # the designer must not latch its save-hold on this broadcast.
                Event._broadcast_disable("reset")
                return JSONResponse({"status": "reset"})

            # A library that isn't one would load as an empty gallery.
            if library and not await asyncio.to_thread(Event._is_json_object, library):
                return JSONResponse({"error": "library must be a JSON object"}, status_code=400)

            # Library-only sync (no CSS/state to save — e.g., draft mode preset import)
            if not css:
                if library and isinstance(library, str):

                    def write_library():
                        with Event._save_transaction():
                            if library == self._load_library(user_id):
                                return False
                            self._save_library(library, user_id)
                            return True

                    if not await asyncio.to_thread(write_library):
                        return JSONResponse({"status": "ok", "noop": True})
                    # Open designers hold the library in memory; tell them.
                    tag = await asyncio.to_thread(Event._library_tag, library)
                    Event._broadcast_library(user_id, origin, settle, tag=tag)
                    return JSONResponse({"status": "ok", "library_only": True, "tag": tag})
                return JSONResponse({"status": "ok", "noop": True})

            if not isinstance(css, str):
                return JSONResponse({"error": "css must be a string"}, status_code=400)
            # A designer that can't read the stored state opens on its defaults
            # and would publish them over the theme on its first save.
            if state and not await asyncio.to_thread(Event._is_json_object, state):
                return JSONResponse({"error": "state must be a JSON object"}, status_code=400)

            # The comparison, the writes and the post-processing are file I/O
            # and regex work over up to tens of MB: on the event loop, every
            # request on the worker would wait on each save.
            def write() -> bool:
                nonlocal state
                with Event._save_transaction():
                    # The same theme again, as a designer sends when it opens:
                    # nothing to write, and no broadcast to make the other open
                    # designers reload.
                    if self._is_unchanged_save(css, state, sections, library, user_id):
                        return False
                    files = [(self._get_css_path(user_id), css)]

                    # Persist the structured sections alongside the flat CSS. When the
                    # payload has no valid sections (older designer build still cached
                    # in a browser tab), drop any stale sections file so consumers fall
                    # back to regex-slicing the flat CSS instead of assembling
                    # sections from a previous save. Dropped before the writes: if they
                    # fail, the old CSS without sections still serves the old theme.
                    if isinstance(sections, dict) and all(
                        isinstance(sections.get(k), str) for k in self.SECTION_KEYS
                    ):
                        files.append(
                            (
                                self._get_sections_path(user_id),
                                _json.dumps({k: sections[k] for k in self.SECTION_KEYS}),
                            )
                        )
                    else:
                        self._delete_sections(user_id)

                    if state and isinstance(state, str):
                        # '_cssSections' is a delivery-time key (merged into state.json
                        # when served) — strip it if a client echoed it back, so it
                        # never round-trips into the persisted state.
                        if '"_cssSections"' in state:
                            try:
                                parsed = _json.loads(state)
                                if (
                                    isinstance(parsed, dict)
                                    and parsed.pop("_cssSections", None) is not None
                                ):
                                    state = _json.dumps(parsed, separators=(",", ":"))
                            except Exception:
                                pass
                        files.append((self._get_state_path(user_id), state))

                    if library and isinstance(library, str):
                        files.append((self._get_library_path(user_id), library))
                    Event._write_together(files)
                    log.info(
                        "[Theme Pro] Saved theme to %s (%d files, %d bytes of CSS)",
                        files[0][0].parent,
                        len(files),
                        len(css),
                    )
                    return True

            if not await asyncio.to_thread(write):
                return JSONResponse({"status": "ok", "noop": True, "bytes": len(css)})

            # NOTE: the composed static assets need no work here — their producers
            # read through the mtime-keyed delivery caches, so the save above is
            # already visible to the next request for /static/custom.css. The
            # broadcast is a version token; clients refetch /theme.css +
            # /state.json (post-processed at delivery).
            # The saved theme's ETags go back to the designer too, which a
            # resync compares with (see _resync_local_clients).
            if user_id:
                # Only the owner's open pages show a personal theme.
                tags = await asyncio.to_thread(self._personal_tags, user_id)
                Event._broadcast_personal(user_id, origin=origin, settle=settle, tags=tags)
            else:
                # Prime delivery caches off-loop so the broadcast carries the
                # new ETags and post-save fetches hit a warm cache.
                tags = await asyncio.to_thread(self._prime_delivery_caches, request.app)
                Event._broadcast_update(tags, origin=origin, settle=settle)

            resp = {"status": "ok", "bytes": len(css), **tags}
            # Return the valve-postprocessed CSS when it differs from what was
            # submitted, so the designer can write the same CSS every other
            # client receives into its localStorage fallback (raw CSS remains
            # the source of truth on disk). State is deliberately NOT returned:
            # the designer's localStorage state key doubles as its editing
            # store, and writing back a canvas-stripped copy would lose data.
            processed_css = await asyncio.to_thread(self._postprocess_css, css)
            if processed_css != css:
                resp["css"] = processed_css
            return JSONResponse(resp)
        except Exception:
            log.exception("[Theme Pro] Error saving CSS")
            return JSONResponse({"error": "Failed to save theme data"}, status_code=500)

    # -- AI Consultant ---------------------------------------------------------

    CONSULT_PROMPT = plugin_template_text("consult_prompt.txt").strip()
    # Seconds between one user's requests, on every worker (config.yaml)
    CONSULT_INTERVAL = LIMITS["consult_interval_seconds"]

    # A theme the chat asked for. The Theme Designer Pro Launcher tool signs it
    # with WEBUI_SECRET_KEY for one user (shared.py), and the designer applies it
    # on load. Unsigned values in the URL are ignored, so a link alone can never
    # restyle anyone's theme.

    @classmethod
    def _read_apply_token(cls, token, user_id: str, personal: bool) -> dict | None:
        """The theme a Launcher token carries for this user and this designer,
        or None: missing, forged, expired, someone else's, or the other scope."""
        import time as _time

        opened = _open_token(_token_key(), token)
        if opened is None:
            return None
        prefix, data = opened
        if data.get("u") != user_id:
            return None
        if not isinstance(data.get("x"), (int, float)) or data["x"] < _time.time():
            return None
        if (data.get("s") == "me") != personal:
            return None
        mode = data.get("m") if data.get("m") in ("dark", "oled", "light", "her") else "all"
        if prefix == THEME_TOKEN_PREFIX:
            sha = data.get("h")
            if not isinstance(sha, str) or not _re.fullmatch(r"[0-9a-f]{64}", sha):
                return None
            return {"kind": "theme", "sha": sha, "mode": mode}
        assert prefix == APPLY_TOKEN_PREFIX
        theme = cls._parse_consult(
            _json.dumps(
                {
                    "hue": data.get("h"),
                    "chroma": data.get("c"),
                    "lightness": data.get("l"),
                    "gradient": bool(data.get("g")),
                    "name": data.get("n") or "",
                }
            )
        )
        if not theme:
            return None
        theme["mode"] = mode
        return theme

    async def _consult_model(self, request):
        """(model id, task params) for the AI Consultant, or (None, None).

        The AI Consultant Model valve when it names a model this instance has;
        otherwise Open WebUI's task model, as its own background tasks use it.
        """
        models = getattr(request.app.state, "MODELS", None) or {}
        wanted = (self.valves.ai_consultant_model or "").strip()
        if wanted:
            return (wanted, None) if wanted in models else (None, None)
        try:
            from open_webui.models.config import Config

            # The local task model, or the external one when only that is set.
            base = next(
                (
                    m
                    for m in (
                        await Config.get("task.model.default"),
                        await Config.get("task.model.external"),
                    )
                    if m and m in models
                ),
                None,
            )
        except Exception:
            return None, None
        if not base:
            return None, None
        from open_webui.routers.tasks import get_task_model_generation_config

        return await get_task_model_generation_config(base, models)

    @staticmethod
    def _completion_text(result) -> str:
        """The text of a chat completion, whatever shape Open WebUI returned it
        in; "" for a shape it isn't, which the consultant answers with its 502."""
        data = result
        body = getattr(result, "body", None)
        if isinstance(body, (bytes, bytearray)):
            try:
                data = _json.loads(body)
            except ValueError:
                return ""
        if not isinstance(data, dict):
            return ""
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
        else:
            message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            # Content parts, as some pipelines answer
            content = "".join(
                p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)
            )
        return content if isinstance(content, str) else ""

    @staticmethod
    def _parse_consult(text: str) -> dict | None:
        """The theme in a model's answer, range-checked, or None."""
        text = _re.sub(r"<think>.*?</think>", "", text or "", flags=_re.S)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = _json.loads(text[start : end + 1])
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None

        def number(key, low, high):
            try:
                return max(low, min(high, int(round(float(data.get(key))))))
            except (TypeError, ValueError, OverflowError):
                return None

        hue, chroma, lightness = (
            number("hue", 0, 360),
            number("chroma", 0, 40),
            number("lightness", 0, 50),
        )
        if hue is None or chroma is None or lightness is None:
            return None
        gradient = data.get("gradient")
        name = " ".join(str(data.get("name") or "").split())[:60]
        return {
            "hue": hue,
            "chroma": chroma,
            "lightness": lightness,
            "gradient": gradient if isinstance(gradient, bool) else str(gradient).lower() == "true",
            "name": name,
        }

    async def _handle_consult(self, request, user) -> JSONResponse:
        """Ask a model on this instance to turn a description into a theme."""
        from starlette.responses import JSONResponse

        try:
            body = await Event._read_json_capped(request, 64 * 1024)
        except Event._BodyTooLarge:
            return JSONResponse({"error": "Request too large"}, status_code=413)
        except Exception:
            body = None
        if not isinstance(body, dict):
            body = {}
        description = " ".join(str(body.get("description") or "").split())[:500]
        if not description:
            return JSONResponse({"error": "Describe the theme you want"}, status_code=400)

        if not await plugin_claim(f"consult:{user.id}", Event.CONSULT_INTERVAL):
            return JSONResponse({"error": "Wait a few seconds between requests"}, status_code=429)

        model_id, params = await self._consult_model(request)
        if not model_id:
            return JSONResponse(
                {
                    "error": "No model to ask: set AI Consultant Model in this function's valves, or a task model under Admin Settings > Interface"
                },
                status_code=409,
            )
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": self.CONSULT_PROMPT},
                {"role": "user", "content": description},
            ],
            "stream": False,
            "metadata": {"task": "theme_designer_pro_consultant"},
        }
        models = getattr(request.app.state, "MODELS", None) or {}
        from open_webui.routers.pipelines import process_pipeline_inlet_filter

        try:
            payload = await process_pipeline_inlet_filter(request, payload, user, models)
        except Exception as exc:
            log.warning("[Theme Pro] A pipeline filter refused the AI Consultant request: %s", exc)
            return JSONResponse({"error": "A pipeline filter refused the request"}, status_code=400)
        if params:
            from open_webui.routers.tasks import apply_task_model_params

            payload = apply_task_model_params(payload, models, model_id, params)
        try:
            from open_webui.utils.chat import generate_chat_completion

            result = await generate_chat_completion(request, form_data=payload, user=user)
        except Exception:
            log.exception("[Theme Pro] The AI Consultant's model failed")
            return JSONResponse({"error": "The model could not answer"}, status_code=502)
        theme = self._parse_consult(self._completion_text(result))
        if not theme:
            return JSONResponse(
                {
                    "error": "The model's answer had no theme in it — try again or describe it differently"
                },
                status_code=502,
            )
        theme["model"] = model_id
        return JSONResponse(theme, headers={"Cache-Control": "no-store"})

    # -- HTML assembly -------------------------------------------------------

    # The designer, editing one user's personal theme: its own storage keys and
    # save routes, and controls that make sense for a theme only its owner sees.
    PERSONAL_DESIGNER_KEYS = (
        ("'owui_dev_theme_v1", "'owui_tdp_me_theme_v1"),
        ("'owui_theme_snapshots'", "'owui_tdp_me_snapshots'"),
        ("'owui_canvas_presets'", "'owui_tdp_me_canvas_presets'"),
        ("'owui_css_presets'", "'owui_tdp_me_css_presets'"),
        ("'owui_gradient_presets'", "'owui_tdp_me_gradient_presets'"),
        ("'owui_theme_last_metadata'", "'owui_tdp_me_last_metadata'"),
        ("'owui_canvas_last_mode'", "'owui_tdp_me_canvas_last_mode'"),
        ("'owui_canvas_last_script'", "'owui_tdp_me_canvas_last_script'"),
        ("'owui_theme_draft_mode'", "'owui_tdp_me_draft_mode'"),
        ("'owui_tdp_unsaved_theme'", "'owui_tdp_me_unsaved_theme'"),
        ("'owui_tdp_library_dropped'", "'owui_tdp_me_library_dropped'"),
        ("fetch('{ROUTE_BASE}', ", "fetch('{ROUTE_BASE}/me', "),
    )

    # The personal designer's own styles and script (templates/designer/personal.html)
    PERSONAL_DESIGNER_BLOCK = plugin_template_text("designer/personal.html")
    NOTICE_PAGE = plugin_template_text("notice.html").strip()

    @staticmethod
    def _notice_page(title: str, detail: str) -> str:
        """A small page, light or dark with the browser, for a designer that
        can't open: fits inside a Settings tab or a chat's frame."""
        import html as _html

        return _fill(
            Event.NOTICE_PAGE, {"TITLE": _html.escape(title), "DETAIL": _html.escape(detail)}
        )

    def _build_html(self, user_id: str | None = None, apply: dict | None = None) -> str:
        """Assemble the full Theme Designer HTML with current valve config.

        With user_id, the designer edits that user's personal theme. Blocking
        (file reads, delivery assembly): the route runs it in a thread.
        """
        html_content = DESIGNER_PAGE

        # Same substitutions as _loader_fragment, minus the embedded state:
        # the designer manages its own state (the bootloader's fetch/state
        # path is gated on !window.__THEME_DESIGNER__), so it gets null.
        route_base = self._get_route_base()
        bootloader_js = (
            self._bootloader_body()
            .replace("__THEME_ROUTE__", route_base)
            .replace(
                "__CANVAS_API_ACCESS__",
                "true" if self.valves.enable_canvas_api_access else "false",
            )
            .replace(
                "__THEME_ACTIVE__",
                "true",
            )
            .replace(
                # The designer applies the theme it is editing itself.
                "__PERSONAL_THEMES__",
                "false",
            )
            .replace(
                "__EMBEDDED_STATE__",
                "null",
            )
            .replace(
                "__CANVAS_FX__",
                "true" if self.valves.enable_canvas_fx else "false",
            )
            .replace(
                "__CALM_CHAT_COLUMN__",
                "true" if self.valves.calm_chat_column else "false",
            )
        )

        valve_config = {
            "enableCanvasFx": self.valves.enable_canvas_fx,
            "enableCanvasApiAccess": self.valves.enable_canvas_api_access,
            "enableUrlImport": self.valves.enable_url_import,
            "allowedImportDomains": [
                d.strip() for d in self.valves.allowed_import_domains.split(",") if d.strip()
            ],
            "enableCustomCss": self.valves.enable_custom_css,
            "enableAuthPageTheming": self.valves.enable_auth_page_theming,
            "enableGradientBuilder": self.valves.enable_gradient_builder,
            "enableCommunityThemes": self.valves.enable_community_themes,
            "enableThemeUpdateChecks": self.valves.enable_theme_update_checks,
            "draftModeDefault": self.valves.draft_mode_default,
            "autoSync": self.valves.auto_sync,
            "sidebarTransparency": self.valves.sidebar_transparency,
            "overlayTransparency": self.valves.overlay_transparency,
            # "me": the signed-in user's personal theme; "instance": everyone's.
            "scope": "me" if user_id else "instance",
            # Who an instance save reaches: with personal themes on, only
            # people without a theme of their own
            "allowPersonalThemes": self.valves.allow_personal_themes,
            "enableAiConsultant": self.valves.enable_ai_consultant,
            # A theme the chat asked for, checked by _read_apply_token.
            "applyOnLoad": apply,
            "personalHasTheme": bool(user_id) and self._get_css_path(user_id).exists(),
        }
        if user_id:
            # Personal designs follow the admin's Draft choice no further:
            # saves only ever change the user's own theme.
            valve_config["draftModeDefault"] = False

        def script_json(value):
            # Every '<' escaped, not only '</': a saved theme holding '<!--'
            # and '<script' (in a Canvas FX script, say) put the HTML parser in
            # its escaped state, and the tag never closed, so the designer
            # didn't load
            return _json.dumps(value).replace("<", "\\u003c")

        # The designer starts from the theme the server is serving, as the
        # main app's bootloader does. Its own localStorage copy can predate a
        # save made from another browser, and Live mode saves whatever it
        # starts from straight back to every user. null means no saved theme.
        # A personal designer starts from the user's own theme, or from the
        # instance theme until they have one.
        try:
            own_state = self._load_state(user_id) if user_id else None
            saved_state = own_state or self._load_state()
        except OSError:
            own_state = saved_state = None  # Reset race / unreadable data dir
        if user_id and not own_state and saved_state:
            # The instance theme marks which gallery entries it came from by
            # their position in the admin's galleries. A user's gallery is
            # their own, so that position picked an unrelated theme of theirs,
            # after Use instance theme or before their first save.
            try:
                parsed = _json.loads(saved_state)
            except ValueError:
                parsed = None
            gallery_refs = (
                "_activeThemeRef",
                "_activeCanvasRef",
                "_activeCssRef",
                "_activeGradientRef",
            )
            if isinstance(parsed, dict) and any(k in parsed for k in gallery_refs):
                for key in gallery_refs:
                    parsed.pop(key, None)
                saved_state = _json.dumps(parsed)
        if not saved_state or saved_state.strip() in ("", "{}"):
            saved_state = None
        # The galleries too: the designer keeps them in memory, not in the
        # browser's storage, so they have to be there from its first line
        # (see _libraryStore). null means none saved yet.
        try:
            library = self._load_library_or_set_aside(user_id)[0]
        except OSError:
            library = None
        # Not in the Launcher's hidden apply frame: nobody would see it there
        if not (apply and apply.get("kind") == "theme"):
            try:
                library_kept_as = self._take_library_notice(user_id)
            except OSError:
                library_kept_as = None
            if library_kept_as:
                valve_config["libraryKeptAs"] = library_kept_as
        try:
            held = self._held_tags(user_id)
        except Exception:
            held = {}  # The designer then never reloads for a resync
        config_tag = (
            '<script id="owui-valve-config">'
            f"window.__THEME_PRO_CONFIG__={script_json(valve_config)};"
            f"window.__THEME_PRO_SAVED_STATE__={script_json(saved_state)};"
            f"window.__THEME_PRO_LIBRARY__={script_json(library)};"
            f"window.__THEME_PRO_HELD__={_json.dumps(held)};"
            "</script>"
        )

        if user_id:
            for old, new in self.PERSONAL_DESIGNER_KEYS:
                html_content = html_content.replace(old, new)
            # The styles go in the head, with the page marked as personal from
            # the start, so the instance-only controls never show while it loads.
            style, _, script = self.PERSONAL_DESIGNER_BLOCK.partition("</style>")
            html_content = html_content.replace(
                '<html lang="en" id="tool-html">',
                '<html lang="en" id="tool-html" data-tdp-scope="me">',
                1,
            )
            html_content = html_content.replace("</head>", style + "</style></head>", 1)
            html_content = html_content.replace("</body>", script + "</body>", 1)

        final_html = (
            html_content.replace("{VERSION}", VERSION)
            .replace("{BOOTLOADER_SRC}", bootloader_js)
            .replace("{ROUTE_BASE}", route_base)
            .replace("{OVERLAY_TRANSPARENCY}", self.valves.overlay_transparency)
            .replace("</head>", config_tag + "</head>")
            .strip()
        )

        return final_html

    # -- entry point ---------------------------------------------------------

    _published = False  # Set once the shared-asset fragments are published in this process
    # Delivery caches for /theme.css and /state.json: (cache_key, body, etag).
    # Keyed on source-file mtimes + valve settings, so saves and valve changes
    # invalidate naturally; per-process (each worker warms its own copy).
    _css_delivery_cache = None
    _state_delivery_cache = None
    _safe_css_cache = None  # (cache_key, css) for the first-paint-safe subset
    _loader_fragment_cache = None  # (cache_key, fragment) for the composed loader.js block
    _reenabling = False  # Set by function.enable_started; triggers SSE broadcast on next inject
    _routes_registered_url = None  # Route base the routes were registered under
    _last_designer_url = None  # Track URL changes to re-register routes
    _last_enable_canvas_fx = None  # Track Canvas FX valve to broadcast changes
    _last_sidebar_transparency = None  # Track sidebar transparency valve to broadcast changes
    _last_overlay_transparency = None  # Track overlay transparency valve to broadcast changes
    # Cross-worker valve convergence (multi-container / Redis only).
    instance = None  # Live instance the producers and peer valve sync read
    _last_valves_snapshot = None  # All valve values at the last event(), to detect ANY change
    _sse_clients: set = (
        set()
    )  # Active SSE connections, aliased to app.state by _share_sse_clients()
    _sse_cids: dict = {}  # Stream id -> queue of _sse_clients, aliased the same way
    # Per-worker ceiling on concurrent SSE connections. The endpoint is
    # unauthenticated, so this bounds worst-case memory/FD usage; over-cap
    # clients degrade gracefully to reconnect-later + refetch-on-focus.
    _SSE_MAX_CLIENTS = LIMITS["sse_max_clients"]
    # Seconds between keep-alives on every stream; 15 keeps Cloudflare's proxy from closing them
    _SSE_HEARTBEAT_SECONDS = LIMITS["sse_heartbeat_seconds"]
    # Tags this process's own Redis messages so its subscriber skips them. Not
    # hostname:pid, which repeats across containers (the server is PID 1, and
    # host networking or a fixed hostname repeats the name).
    # _ensure_redis_subscriber keeps the first exec's value on app.state.
    _WORKER_ID = uuid.uuid4().hex

    @staticmethod
    def _strip_canvas_from_state(state_str: str) -> str:
        """Switch Canvas FX off in every mode of a state JSON, for the Enable
        Canvas FX valve, leaving the saved file as it is."""
        try:
            data = _json.loads(state_str)
            for mode in ("dark", "oled", "light", "her"):
                if isinstance(data.get(mode), dict):
                    data[mode]["canvasEnabled"] = False
                    data[mode].pop("canvasScript", None)
                    data[mode].pop("canvasShowAuth", None)
                    data[mode].pop("canvasAuthOnly", None)
            return _json.dumps(data, separators=(",", ":"))
        except Exception:
            # Fail closed: this enforces a valve. JSON Python can't parse
            # (nesting past its recursion limit) still parses in the browser,
            # which would then run the script the admin switched off.
            return "{}"

    @staticmethod
    def _rewrite_sidebar_fx(css: str, mode: str) -> str:
        """Rewrite the opaque /*[FX]*/ sidebar rules (Canvas FX and gradient
        blocks) for the Sidebar Transparency valve: tinted glass for
        'translucent', see-through with no blur for 'transparent'.

        Unmarked sidebar rules are left alone. Works rule by rule, so it runs
        on the flat CSS or on the structural and gradient sections alike.
        """
        rule_open = r"#sidebar(?::not\(\.h-full\))?\s*\{\s*/\*\[FX\]\*/"
        # The designer tints a gradient's hex base colour as rgba() and any
        # other colour as color-mix(in srgb, <colour> NN%, transparent), with
        # a lone blur(). Only that lone blur matches, never the -webkit-
        # property, so CSS this already rewrote (a copy kept aside and saved
        # back as a personal theme) passes unchanged.
        lone_blur = r"blur\([^)]*\)(?=\s*!important)"

        def rewrite(rule: str) -> str:
            if mode == "translucent":
                blur = "blur(20px) saturate(1.3)"
                rule = _re.sub(
                    r"("
                    + rule_open
                    + r"\s*background-color:\s*)(var\(--[^)]+\))(\s*!important\s*;)\s*\}",
                    rf"\1color-mix(in srgb, \2 20%, transparent)\3 backdrop-filter: {blur} !important; -webkit-backdrop-filter: {blur} !important; }}",
                    rule,
                )
                rule = _re.sub(
                    r"("
                    + rule_open
                    + r"[^}]*background-color:\s*)rgba\(([^,]+,[^,]+,[^,]+),\s*[\d.]+\)(\s*!important\s*;[^}]*(?<![\w-])backdrop-filter:\s*)"
                    + lone_blur,
                    rf"\1rgba(\2, 0.25)\3{blur}",
                    rule,
                )
                rule = _re.sub(
                    r"("
                    + rule_open
                    + r"[^}]*background-color:\s*color-mix\(in srgb,\s*[^;{}]+\s)\d+%(,\s*transparent\)\s*!important\s*;[^}]*(?<![\w-])backdrop-filter:\s*)"
                    + lone_blur,
                    rf"\g<1>25%\2{blur}",
                    rule,
                )
            else:
                blur = "none"
                rule = _re.sub(
                    r"("
                    + rule_open
                    + r"\s*background-color:\s*)var\(--[^)]+\)(\s*!important\s*;)\s*\}",
                    rf"\1transparent\2 backdrop-filter: {blur} !important; -webkit-backdrop-filter: {blur} !important; }}",
                    rule,
                )
                rule = _re.sub(
                    r"("
                    + rule_open
                    + r"[^}]*background-color:\s*)(?:rgba\([^)]+\)|color-mix\([^;{}]+\))(\s*!important\s*;[^}]*(?<![\w-])backdrop-filter:\s*)"
                    + lone_blur,
                    rf"\1transparent\2{blur}",
                    rule,
                )
            return _re.sub(
                r"[^\n]*#sidebar[^{]*\{\s*/\*\[FX\]\*/\s*background-color:\s*revert-layer\s*;?\s*\}",
                "",
                rule,
            )

        # Each marked rule on its own. Run over the whole CSS, these patterns
        # backtracked in quadratic to cubic time on a long line (custom CSS
        # with an inline font is one), freezing the worker for seconds to
        # minutes. A rule starts on the marker's line and ends at its '}'.
        marker, window = "/*[FX]*/", 2000
        out, pos = [], 0
        while True:
            at = css.find(marker, pos)
            if at < 0:
                break
            line_break = css.rfind("\n", max(pos, at - window), at)
            start = line_break + 1 if line_break >= 0 else (pos if at - pos <= window else at)
            end = css.find("}", at, at + window)
            if end < 0:
                out.append(css[pos : at + len(marker)])
                pos = at + len(marker)
                continue
            out.append(css[pos:start])
            rewritten = rewrite(css[start : end + 1])
            out.append(rewritten)
            pos = end + 1
            if not rewritten.strip():
                # A removed rule takes its line with it
                line_break = css.find("\n", pos)
                if line_break >= 0 and not css[pos:line_break].strip():
                    pos = line_break + 1
        out.append(css[pos:])
        return "".join(out)

    @staticmethod
    def _sidebar_fade_css() -> str:
        """Hide Open WebUI's fades at the top and bottom of the sidebar.

        They are solid gradients in the sidebar's own color, so over a
        translucent or transparent sidebar they read as opaque bands.
        """
        return (
            "\n/* Sidebar Transparency: no solid fades over a see-through sidebar */\n"
            "#sidebar .sidebar-bg-gradient-to-t,\n"
            "#sidebar .sidebar-bg-gradient-to-b { display: none !important; }\n"
        )

    @staticmethod
    def _sidebar_mobile_css() -> str:
        """Turn a transparent sidebar translucent on phones.

        #sidebar#sidebar outranks the transparent rules.
        """
        return (
            "\n/* Mobile: auto-upgrade transparent sidebar to translucent */\n"
            "@media (max-width: 768px) {\n"
            "  .dark #sidebar#sidebar,\n"
            '  [data-theme="dark"] #sidebar#sidebar,\n'
            '  [data-theme="oled-dark"] #sidebar#sidebar {\n'
            "    background-color: color-mix(in srgb, var(--color-gray-950) 20%, transparent) !important;\n"
            "    backdrop-filter: blur(20px) saturate(1.3) !important;\n"
            "    -webkit-backdrop-filter: blur(20px) saturate(1.3) !important;\n"
            "  }\n"
            '  :root:not(.dark):not([data-theme="dark"]):not([data-theme="oled-dark"]) #sidebar#sidebar {\n'
            "    background-color: color-mix(in srgb, var(--color-gray-50) 20%, transparent) !important;\n"
            "    backdrop-filter: blur(20px) saturate(1.3) !important;\n"
            "    -webkit-backdrop-filter: blur(20px) saturate(1.3) !important;\n"
            "  }\n"
            "}\n"
        )

    @staticmethod
    def _overlay_css() -> str:
        """Translucent glass for the overlays Open WebUI portals onto <body>,
        outside .app: the settings modal and the dropdown, user and
        integration menus. Descendant selectors, because the portals nest
        their surfaces at varying depths.
        """
        blur = "blur(20px) saturate(1.3)"
        # A portal: a direct child of body that isn't the app or the theme
        # system's own. SvelteKit's page wrapper is a body > div too; pages
        # outside .app, such as a shared chat, sit in it.
        portal = ':not(.app):not(#theme-designer-container):not([id^="owui-"]):not([style*="display: contents"]):not(script):not(style)'
        # A surface inside it: not an interactive widget or the app's own
        surface = ":not(button):not(a):not(input):not(select):not(label):not(span):not(svg):not(img):not(.app *):not(#theme-designer-container *)"

        def surfaces_with(*utilities):
            """Divs carrying one of these background utilities, plain or dark:."""
            selectors = [
                s
                for utility in utilities
                for s in (
                    f'div[class^="{utility}"]',
                    f'div[class*=" {utility}"]',
                    f'div[class^="dark:{utility}"]',
                    f'div[class*=" dark:{utility}"]',
                )
            ]
            return ":where(" + ", ".join(s + surface for s in selectors) + ")"

        # Open WebUI's UI greys are bg-base-* after 0.13.4 (bg-gray-* through 0.13.4)
        grey = surfaces_with("bg-gray-", "bg-base-")
        white = surfaces_with("bg-white")

        def glass(color_var):
            return (
                f"  background-color: color-mix(in srgb, var({color_var}) 25%, transparent) !important;\n"
                f"  backdrop-filter: {blur} !important;\n"
                f"  -webkit-backdrop-filter: {blur} !important;\n"
            )

        light = ':root:not(.dark):not([data-theme="dark"]):not([data-theme="oled-dark"]):not([data-theme="her"])'
        # (theme selectors, surfaces, tint)
        rules = [
            (
                (".dark", '[data-theme="dark"]', '[data-theme="oled-dark"]'),
                (grey,),
                "--color-gray-950",
            ),
            ((light,), (white, grey), "--color-gray-50"),
            ((".her", '[data-theme="her"]'), (white, grey), "--color-gray-50"),
        ]
        css = "\n/* --- Overlay Translucency (valve-injected) --- */\n"
        for themes, surfaces, color_var in rules:
            selectors = [f"{theme} body > div{portal} {s}" for s in surfaces for theme in themes]
            css += ",\n".join(selectors) + " {\n" + glass(color_var) + "}\n"
        for scheme, surfaces, color_var in (
            ("dark", (grey,), "--color-gray-950"),
            ("light", (white, grey), "--color-gray-50"),
        ):
            selectors = [f'  [data-theme="system"] body > div{portal} {s}' for s in surfaces]
            css += f"@media (prefers-color-scheme: {scheme}) {{\n"
            css += ",\n".join(selectors) + " {\n" + glass(color_var) + "  }\n}\n"
        # The fade at the top of a chat goes with the solid overlays
        css += "\n/* Overlay Transparency: no fade at the top of chats */\n#navbar-bg-gradient-to-b { display: none !important; }\n"
        return css

    def _valve_appended_css(self) -> str:
        """The rules the transparency valves add once, at the end of the
        delivered CSS: the 'extra' section when it is assembled from
        sections."""
        css = ""
        sidebar_mode = self.valves.sidebar_transparency
        if sidebar_mode != "opaque":
            css += self._sidebar_fade_css()
            if sidebar_mode == "transparent":
                css += self._sidebar_mobile_css()
        if self.valves.overlay_transparency != "opaque":
            css += self._overlay_css()
        return css

    _CANVAS_CLEARING = _re.compile(
        r"/\*\[OWUI_CLEAR_CANVAS_START\]\*/.*?/\*\[OWUI_CLEAR_CANVAS_END\]\*/", _re.DOTALL
    )
    _STRUCTURAL = _re.compile(
        r"/\*\[OWUI_STRUCTURAL_START\]\*/.*?/\*\[OWUI_STRUCTURAL_END\]\*/", _re.DOTALL
    )

    @classmethod
    def _drop_canvas_clearing(cls, css: str) -> str:
        """Remove the clearing of canvas-only modes, inside the structural
        block only, so a marker anywhere else can't widen the match."""
        return cls._STRUCTURAL.sub(lambda m: cls._CANVAS_CLEARING.sub("", m.group()), css)

    def _postprocess_css(self, css):
        """The flat CSS as the valves deliver it: Enable Canvas FX off drops
        the clearing of modes whose only background is the canvas, and the
        transparency valves rewrite and add their rules."""
        if not self.valves.enable_canvas_fx:
            css = self._drop_canvas_clearing(css)
        if self.valves.sidebar_transparency != "opaque":
            css = self._rewrite_sidebar_fx(css, self.valves.sidebar_transparency)
        return css + self._valve_appended_css()

    def _postprocess_sections(self, sections: dict) -> dict:
        """Per-section mirror of _postprocess_css.

        The /*[FX]*/ rules the sidebar valve rewrites live only in the
        structural and gradient sections. The appended rules go into a
        synthetic 'extra' section, so consumers assembling from sections
        deliver the same CSS as /theme.css. The bootloader never auth-gates
        'extra'.
        """
        out = dict(sections)
        if not self.valves.enable_canvas_fx:
            out["structural"] = self._drop_canvas_clearing(out["structural"])
        sidebar_mode = self.valves.sidebar_transparency
        if sidebar_mode != "opaque":
            out["structural"] = self._rewrite_sidebar_fx(out["structural"], sidebar_mode)
            out["gradient"] = self._rewrite_sidebar_fx(out["gradient"], sidebar_mode)
        out["extra"] = self._valve_appended_css()
        return out

    def _state_with_sections(self, state: str, user_id: str | None = None) -> str:
        """Merge valve-postprocessed CSS sections into a state JSON string.

        Added at delivery under the reserved '_cssSections' key so the
        bootloader can assemble auth-page CSS from sections instead of
        regex-slicing the flat blob. No-op without a sections file (the
        bootloader falls back to marker regexes) or when the state isn't
        parseable JSON (served as-is by design).
        """
        sections = self._load_sections(user_id)
        if not sections:
            return state
        try:
            data = _json.loads(state)
            if not isinstance(data, dict):
                return state
        except Exception:
            return state
        data["_cssSections"] = self._postprocess_sections(sections)
        return _json.dumps(data, separators=(",", ":"))

    def _css_valve_key(self) -> tuple:
        """The valves _postprocess_css reads, for the delivery cache keys."""
        return (
            self.valves.enable_canvas_fx,
            self.valves.sidebar_transparency,
            self.valves.overlay_transparency,
        )

    def _state_valve_key(self) -> tuple:
        """The valves _postprocess_state and _state_with_sections read, for
        the delivery cache keys."""
        return (
            self.valves.enable_auth_page_theming,
            *self._css_valve_key(),
            self.valves.designer_url,
        )

    def _postprocess_state(self, state, personal: bool = False):
        """The state as the valves deliver it: Canvas FX off with Enable
        Canvas FX, sign-in page theming off with Enable Auth Page Theming,
        and uploads at the current Designer Url."""
        if not state:
            return state
        if not self.valves.enable_canvas_fx:
            state = self._strip_canvas_from_state(state)
        if not self.valves.enable_auth_page_theming:
            state = self._strip_auth_from_state(state)
        return self._rebase_uploads(state, self._get_route_base(), personal)

    # An uploaded picture's address up to its route name, which is the base it
    # was uploaded under. The instance theme's uploads are /page-background and
    # /auth-background. A personal theme's own is /me/page-background, and one
    # started from the instance theme can still hold the instance picture, so
    # the personal name is tried first. The designer's rebaseUpload does the same.
    _UPLOAD_BASE = {
        False: _re.compile(r"^/api/v1/[\w./-]*?(?=/(?:page|auth)-background\?)"),
        True: _re.compile(r"^/api/v1/[\w./-]*?(?=/me/page-background\?)"),
    }

    @staticmethod
    def _rebase_uploads(state_str: str, route_base: str, personal: bool = False) -> str:
        """Point uploaded pictures at the current route base: only it serves
        them after a Designer Url change, and saved themes keep the old one."""
        if "-background?" not in state_str:
            return state_str
        try:
            data = _json.loads(state_str)
            hidden = data.get("_hiddenBackgrounds")
        except Exception:
            return state_str
        changed = False
        for key in ("pages",) if personal else ("auth", "pages"):
            picture = hidden.get(key) if isinstance(hidden, dict) else None
            url = picture.get("url") if isinstance(picture, dict) else None
            old = None
            if isinstance(url, str):
                old = (personal and Event._UPLOAD_BASE[True].match(url)) or Event._UPLOAD_BASE[
                    False
                ].match(url)
            if old and old.group() != route_base:
                picture["url"] = route_base + url[old.end() :]
                changed = True
        return _json.dumps(data, separators=(",", ":")) if changed else state_str

    @staticmethod
    def _strip_auth_from_state(state_str: str) -> str:
        """Turn every Show on Auth Pages and Only on Auth Pages flag off, and
        drop the sign-in page picture, for the Enable Auth Page Theming valve."""
        try:
            data = _json.loads(state_str)
            for mode in ("dark", "oled", "light", "her"):
                if isinstance(data.get(mode), dict):
                    for key in (
                        "themeShowAuth",
                        "customCssShowAuth",
                        "canvasShowAuth",
                        "gradientShowAuth",
                        "themeAuthOnly",
                        "customCssAuthOnly",
                        "canvasAuthOnly",
                        "gradientAuthOnly",
                    ):
                        data[mode][key] = False
            hidden = data.get("_hiddenBackgrounds")
            if isinstance(hidden, dict):
                hidden.pop("auth", None)
            return _json.dumps(data, separators=(",", ":"))
        except Exception:
            return state_str

    _redis_url_warned = None  # The unusable REDIS_URL already reported, so it is logged once

    @classmethod
    def _redis_url(cls) -> str:
        """REDIS_URL when redis-py can use it, else "".

        A value it cannot parse is a setup mistake, not a dropped connection,
        so it is reported once instead of retried every few seconds. The usual
        cause is quotes in a Docker Compose `environment:` list, where
        `- REDIS_URL="redis://..."` keeps the quotes as part of the value.
        Open WebUI quietly runs without Redis on such a value; the warning says
        why live updates stay within one worker.
        """
        url = os.environ.get("REDIS_URL", "").strip()
        if not url or url.lower().startswith(("redis://", "rediss://", "unix://")):
            return url
        if cls._redis_url_warned != url:
            cls._redis_url_warned = url
            # The part before :// (or the first character) shows the problem
            # without logging a password.
            head = url.split("://", 1)[0][:16] if "://" in url else url[:1]
            log.warning(
                "[Theme Pro] REDIS_URL must start with redis://, rediss:// or unix://, "
                "but it starts with %r. If the value is wrapped in quotes, remove them: "
                "in a Docker Compose `environment:` list, quotes become part of the value. "
                "Until then, live theme updates only reach browsers on the same worker.",
                head,
            )
        return ""

    @staticmethod
    def _sse_channel() -> str:
        """The Redis channel that relays SSE messages between workers.

        Named under the instance's REDIS_KEY_PREFIX, like Open WebUI's own
        keys: Redis pub/sub ignores the database number, so two instances
        sharing one Redis server on different databases would otherwise hear
        each other's theme updates and disables.
        """
        from open_webui.env import REDIS_KEY_PREFIX

        return f"{REDIS_KEY_PREFIX}:theme_pro_sse" if REDIS_KEY_PREFIX else "theme_pro_sse"

    @classmethod
    def _pin_worker_id(cls, app) -> str:
        """The first exec's ID, for every exec in this process: the running
        subscriber skips only frames tagged with the ID it knows."""
        if not getattr(app.state, "_theme_worker_id", None):
            app.state._theme_worker_id = cls._WORKER_ID
        cls._WORKER_ID = app.state._theme_worker_id
        return cls._WORKER_ID

    @classmethod
    def _redis_publish(cls, msg: str):
        """Publish a message to the Redis SSE relay channel (best-effort).

        Goes through Open WebUI's own async client (app.state.redis), so it
        connects wherever Open WebUI does, Sentinel and Cluster included. The
        client is shared: never close it. Every caller runs on the event loop.
        """
        try:
            from open_webui.main import app

            redis = getattr(app.state, "redis", None)
            loop = asyncio.get_running_loop()
        except Exception:
            return
        if redis is None:
            return
        wid = cls._pin_worker_id(app)

        async def publish():
            try:
                await redis.publish(cls._sse_channel(), f"wid:{wid}\n{msg}")
            except Exception as e:
                log.warning("[Theme Pro] Redis publish failed: %s", type(e).__name__)

        task = loop.create_task(publish())
        reload_tasks.add(task)
        task.add_done_callback(reload_tasks.discard)

    # Redis relay prefixes: a frame for one user's pages, followed by the
    # user id, and a frame only signed-in pages hear
    _PERSONAL_PREFIX = "personal:"
    _SIGNED_IN_PREFIX = "users:\n"
    # Frames the subscriber relays per batch, so a flood still yields the loop
    _RELAY_BATCH_MAX = 100

    @classmethod
    def _deliver(cls, msg: str, user_id: str | None = None, signed_in_only: bool = False):
        """Queue msg on this worker's streams: only user_id's pages when
        given, only signed-in pages with signed_in_only. A stream too backed
        up to take it misses it."""
        for q in list(cls._sse_clients):
            user = getattr(q, "_tdp_user", None)
            if user_id is not None and user != user_id:
                continue
            if signed_in_only and not user:
                continue
            with suppress(asyncio.QueueFull):
                q.put_nowait(msg)

    @classmethod
    def _send(
        cls,
        msg: str,
        user_id: str | None = None,
        signed_in_only: bool = False,
        local_only: bool = False,
    ):
        """Deliver msg here and, unless local_only, to the same pages on the
        other workers through Redis."""
        if not local_only:
            if user_id is not None:
                cls._redis_publish(f"{cls._PERSONAL_PREFIX}{user_id}\n{msg}")
            elif signed_in_only:
                cls._redis_publish(f"{cls._SIGNED_IN_PREFIX}{msg}")
            else:
                cls._redis_publish(msg)
        cls._deliver(msg, user_id, signed_in_only)

    @classmethod
    def _broadcast_update(
        cls,
        etags: dict | None = None,
        local_only: bool = False,
        origin: str | None = None,
        settle: bool = False,
        resync: bool = False,
    ):
        """Tell every page the instance theme changed.

        The frame carries only a version token: pages refetch /theme.css and
        /state.json, which apply valve post-processing at delivery, so a
        debounced save doesn't ship the whole CSS and canvas script to every
        client. etags (from _prime_delivery_caches) let a page that already
        holds that version skip the refetch.

        local_only skips the Redis relay, for a broadcast that answers a
        peer's message and must not echo back onto the channel.
        """
        import time

        data = {"v": int(time.time() * 1000)}
        if etags:
            if etags.get("cssTag"):
                data["cssTag"] = etags["cssTag"]
            if etags.get("stateTag"):
                data["stateTag"] = etags["stateTag"]
        if origin:
            data["origin"] = origin
        if settle:
            data["settle"] = True
        if resync:
            data["resync"] = True
        data["spread"] = cls._refetch_spread()
        payload = _json.dumps(data, separators=(",", ":"))
        cls._send(f"event: theme-update\ndata: {payload}\n\n", local_only=local_only)

    # A page resyncs over this many ms when its stream opens again. Every
    # page that was open reconnects within moments of a restart, so the
    # count _refetch_spread scales by is still climbing then, and the first
    # pages back would refetch together.
    _RESYNC_SPREAD = 2000

    @classmethod
    def _refetch_spread(cls) -> int:
        """How many ms the pages told of a theme-update spread their refetch
        over, so one save doesn't send every open page to the server at once.
        Scaled to the pages connected here: a few refetch at once, a few
        hundred over the full two seconds. Through Redis other workers' pages
        hear it too and aren't counted, so they get the full spread."""
        if cls._redis_url():
            return 2000
        return min(2000, 8 * len(cls._sse_clients))

    @classmethod
    def _broadcast_personal(
        cls,
        user_id: str,
        local_only: bool = False,
        origin: str | None = None,
        settle: bool = False,
        tags: dict | None = None,
        resync: bool = False,
    ):
        """Tell one user's open pages that their personal theme changed.

        Nobody else's page is told, on this worker or, through Redis, on any
        other. The pages refetch their own theme, as they do on theme-update.
        tags (from _personal_tags) let the user's designers tell a resync
        from a change.
        """
        payload = {"origin": origin} if origin else {}
        if settle:
            payload["settle"] = True
        if tags:
            payload.update(tags)
        if resync:
            payload["resync"] = True
        data = _json.dumps(payload, separators=(",", ":"))
        cls._send(f"event: personal-theme-update\ndata: {data}\n\n", user_id, local_only=local_only)

    @classmethod
    def _broadcast_library(
        cls,
        user_id: str | None,
        origin: str | None,
        settle: bool = False,
        tag: str | None = None,
        local_only: bool = False,
        resync: bool = False,
    ):
        """Tell open designers the saved themes and presets changed, so one
        holding an older copy reloads instead of saving it over the new one.
        Only designers listen for this event; a personal library's goes to its
        owner's pages alone. tag is _library_tag of the library saved now."""
        payload = {"scope": "me" if user_id else "instance", "tag": tag}
        if origin:
            payload["origin"] = origin
        if settle:
            payload["settle"] = True
        if resync:
            payload["resync"] = True
        data = _json.dumps(payload, separators=(",", ":"))
        cls._send(
            f"event: library-update\ndata: {data}\n\n", user_id or None, local_only=local_only
        )

    # More model ids than this go out as "every model"
    _MODEL_IDS_MAX = 50

    @classmethod
    def _broadcast_backgrounds(
        cls, user_id: str | None = None, model_ids: list | None = None, signed_in_only: bool = False
    ):
        """Tell pages that a background image they may fade changed, so they
        look its address up again: user_id's pages for their Chat Background
        Image, the others for a model's. Without model_ids, every model's.
        Only ids the instance theme publishes may go in, since every page
        hears this, signed out or not."""
        if user_id:
            cls._send('event: backgrounds-update\ndata: {"scope":"chat"}\n\n', user_id)
            return
        payload = {"scope": "models", "spread": cls._refetch_spread()}
        if model_ids:
            payload["ids"] = [str(i) for i in model_ids]
        data = _json.dumps(payload, separators=(",", ":"))
        cls._send(f"event: backgrounds-update\ndata: {data}\n\n", signed_in_only=signed_in_only)

    def _instance_faded_models(self) -> set:
        """The model ids the instance theme fades, which its public
        state.json already names."""
        delivered = self._get_state_delivery()
        try:
            hidden = _json.loads(delivered[0]).get("_hiddenBackgrounds") if delivered else None
        except Exception:
            hidden = None
        models = hidden.get("models") if isinstance(hidden, dict) else None
        if isinstance(models, dict):
            return {str(k) for k in models}
        if isinstance(models, list):
            return {m for m in models if isinstance(m, str)}
        return set()

    @classmethod
    def _bind_stream(cls, cid: str, user_id: str) -> bool:
        """Tag this worker's stream cid with user_id. False when another
        worker holds it."""
        q = cls._sse_cids.get(cid)
        if q is None:
            return False
        if q not in cls._sse_clients:
            # Ended under a build that kept no map
            del cls._sse_cids[cid]
            return False
        q._tdp_user = user_id
        return True

    @classmethod
    def _broadcast_disable(cls, reason="disabled"):
        """Push a theme-disable event to all SSE clients (strip theme + reload).

        reason distinguishes a function toggle ("disabled") from a Global Reset
        ("reset"). Clients strip the theme identically in both cases, but the
        designer's save-hold must only latch on a real disable: after a reset
        the function is still running and saves must keep working; latching
        would hold every save while no theme-update can ever arrive to release
        them, deadlocking the designer until a page reload.
        """
        data = {"reason": reason}
        if reason == "reset":
            data["spread"] = cls._refetch_spread()
        cls._send(f"event: theme-disable\ndata: {_json.dumps(data, separators=(',', ':'))}\n\n")

    # --- Cross-worker valve convergence -------------------------------------
    # An admin changes a valve on ONE worker; Open WebUI reloads the function
    # there, but every other worker keeps its cached instance with the old
    # values until its own next dispatched event. All valves alter rendered
    # output (the loader.js fragment embeds the whole config), so peers can
    # serve a stale theme for that window. The worker that saw the change tells
    # the others to re-read from the DB. Redis-only: a single-worker install
    # already holds the fresh valves, so _redis_publish is a no-op there.
    #
    # Framed as an SSE comment (":") so a peer still on an older build, whose
    # subscriber forwards raw channel traffic straight to browsers, delivers an
    # ignored keep-alive rather than a malformed event. Our own subscriber
    # intercepts it before any client sees it.
    _CTRL_PREFIX = ":owui-theme-ctrl "

    @classmethod
    def _broadcast_valve_sync(cls):
        """Signal peer workers that a valve changed and they should re-read it."""
        cls._redis_publish(f"{cls._CTRL_PREFIX}valvesync\n\n")

    @staticmethod
    async def _read_valves_from_db(inst, function_id):
        """Read + validate this function's stored valves; None on any failure.

        A missing Open WebUI API, an unreadable row, or data that no longer
        validates all resolve to None, and the caller then leaves the current
        valves untouched: the worker converges on its own next event. No
        stored valves means the defaults, as in Open WebUI's own dispatch.
        """
        try:
            from open_webui.models.functions import Functions

            stored = await Functions.get_function_valves_by_id(function_id) or {}
        except Exception:
            return None
        if not isinstance(stored, dict):
            return None
        try:
            return inst.Valves(**stored)
        except Exception:
            return None

    @classmethod
    async def _handle_peer_valve_sync(cls, app, resync: bool = False) -> bool:
        """Apply a peer's valve change to this worker's live instance. True
        when the valves changed and local clients were told.

        Also runs after live_reload executes this code on a worker that no
        event reaches, which is how that worker gets its valves and routes.

        Cache priming runs off-loop; the app-state mutations (route
        re-registration, fragment republish) run on-loop, the same order
        event() uses, so they interleave cooperatively with event() instead of
        racing it in a thread.
        """
        inst = cls.instance
        if inst is None or (app is not None and not reload_active(app)):
            return False
        new_valves = await cls._read_valves_from_db(inst, RELOAD_FUNCTION_ID)
        if new_valves is None:
            return False
        inst.valves = new_valves
        snap = inst._valves_snapshot()
        if snap == cls._last_valves_snapshot:
            return False
        cls._last_valves_snapshot = snap
        if app is not None:
            route = inst._get_route_base()
            if route != cls._routes_registered_url:
                inst._register_route(app)
                cls._routes_registered_url = route
            inst._publish_fragments(app)
        etags = await asyncio.to_thread(inst._prime_delivery_caches, app)
        # local_only: this refetch nudge is the downstream of a peer's message;
        # echoing it back to Redis would ripple across the cluster.
        cls._broadcast_update(etags, local_only=True, resync=resync)
        log.info(
            "[Theme Pro] Applied peer valve change — refreshed valves, re-primed, notified local clients"
        )
        return True

    @staticmethod
    def _library_tag(library: str | None) -> str | None:
        """Names one saved library's content; None when there is none."""
        if not library:
            return None
        return hashlib.md5(library.encode("utf-8"), usedforsecurity=False).hexdigest()

    _library_tag_cache = {}  # user_id -> (file signature, tag)

    def _saved_library_tag(self, user_id: str | None = None) -> str | None:
        """_library_tag of the library saved now. Cached on the file's
        signature: every designer stream asks as it connects, all at once
        after a restart, and the file can be tens of MB."""
        try:
            sig = Event._file_sig(self._get_library_path(user_id))
        except FileNotFoundError:
            return None
        cached = Event._library_tag_cache.get(user_id)
        if cached and cached[0] == sig:
            return cached[1]
        tag = Event._library_tag(self._load_library(user_id))
        Event._cache_put(Event._library_tag_cache, user_id, (sig, tag))
        return tag

    def _held_tags(self, user_id: str | None) -> dict:
        """What a designer opened now starts from, by the tags a resync
        compares with (see the designer's missedSave)."""
        css, state = self._get_css_delivery(), self._get_state_delivery()
        held = {
            "theme": [css[1] if css else None, state[1] if state else None],
            "library": [self._saved_library_tag(user_id), None],
        }
        if user_id:
            personal = self._personal_tags(user_id)
            held["personal"] = [personal["cssTag"], personal["stateTag"]]
        return held

    def _personal_tags(self, user_id: str) -> dict:
        """The ETags of a user's personal theme.css and state.json now, as
        /me serves them: none while personal themes are off."""
        if not self.valves.allow_personal_themes:
            return {"cssTag": None, "stateTag": None}
        css = self._get_personal_delivery(user_id, "css")
        state = self._get_personal_delivery(user_id, "state")
        return {"cssTag": css[1] if css else None, "stateTag": state[1] if state else None}

    @classmethod
    async def _resync_local_clients(cls, app):
        """Tell this worker's clients what is saved now, after its subscriber
        missed whatever was published while it was away.

        Every frame carries resync and the tags saved now: pages and
        designers act only on a tag that differs from what they hold, so a
        client that missed nothing does nothing.
        """
        inst = cls.instance
        if inst is None or not reload_active(app):
            return
        # A valve change missed in the gap is told with these same tags
        if not await cls._handle_peer_valve_sync(app, resync=True):
            etags = await asyncio.to_thread(inst._prime_delivery_caches, app)
            cls._broadcast_update(etags, local_only=True, resync=True)
        users = set()
        if inst.valves.allow_personal_themes:
            users = {getattr(q, "_tdp_user", None) for q in list(cls._sse_clients)} - {None}

        def read_tags():
            return inst._saved_library_tag(), {
                uid: (inst._personal_tags(uid), inst._saved_library_tag(uid)) for uid in users
            }

        library, personal = await asyncio.to_thread(read_tags)
        cls._broadcast_library(None, None, tag=library, local_only=True, resync=True)
        for uid, (tags, personal_library) in personal.items():
            cls._broadcast_personal(uid, local_only=True, tags=tags, resync=True)
            cls._broadcast_library(uid, None, tag=personal_library, local_only=True, resync=True)

    @classmethod
    async def _shutdown_cleanup(cls, app):
        """Cancel background tasks and end SSE streams before the loop closes.

        Called from event() on system.shutdown.*, which Open WebUI publishes
        from its lifespan exit while the event loop is still fully alive.

        Idempotent via app.state._theme_shutting_down. That flag also gates
        the subscriber/heartbeat creation paths: shutdown events are
        dispatched as fire-and-forget tasks, so a straggler event() can run
        mid-teardown — if it respawned the Redis subscriber, the new task
        would miss the runner's cancellation sweep and be destroyed pending
        at loop close ("Task was destroyed but it is pending!",
        "RuntimeError: no running event loop", un-awaited redis disconnect
        coroutines in the GC phase of interpreter shutdown).
        """
        app.state._theme_shutting_down = True
        for attr in ("_theme_redis_task", "_theme_sse_heartbeat"):
            task = getattr(app.state, attr, None)
            if task is not None:
                task.cancel()
                with suppress(BaseException):  # CancelledError (expected) or teardown noise
                    await task
                setattr(app.state, attr, None)
        cls._end_sse_streams()

    @classmethod
    def _end_sse_streams(cls):
        """Wake every SSE stream with a None sentinel so the generators
        return, letting uvicorn's graceful wait for in-flight responses
        finish instead of stalling on open EventSource connections until the
        container runtime SIGKILLs the process (~10s restart penalty)."""
        for q in list(cls._sse_clients):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()  # Drop one queued frame to make room
                    q.put_nowait(None)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    @classmethod
    def _install_exit_hook(cls, app):
        """End SSE streams the moment uvicorn is asked to stop.

        The system.shutdown.* events come from Open WebUI's lifespan exit,
        and uvicorn runs that only AFTER every open response has finished
        (Server.shutdown waits on its tasks first, with no timeout by
        default). An EventSource never finishes on its own, so any open tab
        held the shutdown until Docker's SIGKILL, and Open WebUI's own
        lifespan cleanup never ran.

        uvicorn bound its handler with signal.signal() at startup, so this
        wraps whatever handler is installed now: mark streams as ending, wake
        the open ones, then hand over. Re-running (a hot reload) only swaps
        the hook it calls.
        """
        import signal
        import threading

        loop = asyncio.get_running_loop()

        def hook():
            app.state._theme_streams_ending = True
            with suppress(RuntimeError):  # loop already closed
                loop.call_soon_threadsafe(Event._end_sse_streams)

        app.state._theme_exit_hook = hook
        if threading.current_thread() is not threading.main_thread():
            return  # signal handlers can only be set from the main thread
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                prev = signal.getsignal(sig)
                if not callable(prev) or getattr(prev, "_tdp_exit_wrapper", False):
                    continue

                def wrapper(signum, frame, prev=prev):
                    try:
                        current = getattr(app.state, "_theme_exit_hook", None)
                        if current is not None:
                            current()
                    except Exception:
                        pass
                    return prev(signum, frame)

                wrapper._tdp_exit_wrapper = True
                signal.signal(sig, wrapper)
            except (ValueError, OSError, RuntimeError):
                pass

    def _ensure_redis_subscriber(self, app):
        """Start the Redis subscriber that relays SSE messages between workers.

        Called from event() and register() (async context) rather than
        _register_route (sync) to avoid 'Task was destroyed' errors from
        transient startup event loops. Starts once, and again when the
        running task died or was started by an older exec of this code.
        """
        Event._share_sse_clients(app)
        Event._pin_worker_id(app)
        redis_url = Event._redis_url()
        task = getattr(app.state, "_theme_redis_task", None)
        alive = task is not None and not task.done()
        # A subscriber started by an older exec of this code would hand peer
        # valve syncs to that exec's dead class, so a new exec replaces it.
        if alive and getattr(app.state, "_theme_redis_exec", None) != RELOAD_EXEC_ID:
            task.cancel()
            alive = False
        # Never (re)spawn once shutdown cleanup ran: shutdown events are
        # dispatched fire-and-forget, so this code can execute mid-teardown
        # after the old subscriber was cancelled (alive False again), and a
        # respawned task would be orphaned at loop close.
        if not redis_url or alive or getattr(app.state, "_theme_shutting_down", False):
            return
        try:
            app.state._theme_redis_task = asyncio.get_running_loop().create_task(
                Event._run_redis_subscriber(app)
            )
            app.state._theme_redis_exec = RELOAD_EXEC_ID
        except Exception as exc:
            log.warning("[Theme Pro] Could not start Redis subscriber: %s", exc)

    @classmethod
    async def _run_redis_subscriber(cls, app):
        """Forward the Redis relay channel to this worker's SSE streams,
        reconnecting after a timeout or a lost connection.

        Subscribes through Open WebUI's shared client (app.state.redis), the
        way its own task listener does, so it connects wherever Open WebUI
        does. Only the pubsub is closed, never the shared client.
        """
        waited = 0
        reconnecting = False
        while True:
            pubsub = None
            # Set when the loop/interpreter is dying: skip every remaining
            # await (logging included) so finalization stays silent instead
            # of raising into the GC.
            teardown = False
            try:
                redis = getattr(app.state, "redis", None)
                if redis is None:
                    # Open WebUI creates it in its lifespan, after
                    # system.startup.started started this task.
                    waited += 1
                    if waited == 60:
                        log.warning(
                            "[Theme Pro] Open WebUI has had no Redis client for 60s; live push stays within this worker until it has one"
                        )
                    await asyncio.sleep(1)
                    continue
                # RedisCluster routes a subscribe only after initialize()
                # fills its slot cache.
                await redis.initialize()
                pubsub = redis.pubsub()
                channel = cls._sse_channel()
                await pubsub.subscribe(channel)
                log.info("[Theme Pro] Redis subscriber connected on channel '%s'", channel)
                # Pub/sub keeps nothing for a subscriber that is away, and a
                # dead connection can go unnoticed for the 90s below.
                if reconnecting:
                    reconnecting = False
                    try:
                        await cls._resync_local_clients(app)
                    except Exception:
                        log.warning(
                            "[Theme Pro] Resync after reconnecting to Redis failed", exc_info=True
                        )
                # listen() blocked forever on a connection dropped without a
                # reset (an idle timeout in a NAT, load balancer or Swarm's
                # IPVS), and this worker stopped hearing the others with
                # nothing in the log. Ping when idle and reconnect when Redis
                # goes quiet.
                loop = asyncio.get_running_loop()
                last_rx = last_ping = loop.time()
                while True:
                    message = await pubsub.get_message(timeout=15.0)
                    now = loop.time()
                    if message is None:
                        if now - last_rx > 90:
                            raise ConnectionError("no reply from Redis for 90s")
                        if now - last_ping >= 30:
                            last_ping = now
                            await pubsub.ping()
                        continue
                    last_rx = now
                    # Relay what has arrived meanwhile as one batch, primed
                    # once: a prime per frame of a near-cap theme costs about
                    # 0.4s, and a burst of saves fell further behind with each
                    batch = [message]
                    while len(batch) < cls._RELAY_BATCH_MAX:
                        more = await pubsub.get_message(timeout=0)
                        if more is None:
                            break
                        batch.append(more)
                    primed = False
                    for m in batch:
                        if m["type"] == "message":
                            primed = await cls._relay_redis_message(app, m["data"], primed)
                    # A batch of buffered frames can relay without suspending,
                    # so yield between batches
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                break
            except GeneratorExit:
                # GC is finalizing this coroutine after the loop already
                # closed (shutdown cleanup never ran, e.g. a hard kill). Any
                # await here raises straight into the finalizer.
                teardown = True
                raise
            except Exception as exc:
                # During finalization redis-py can convert the thrown
                # GeneratorExit into an ordinary ConnectionError, landing here
                # with no loop to sleep on. Only log + retry on a live loop.
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    teardown = True
                    return
                log.warning(
                    "[Theme Pro] Redis subscriber lost connection: %s — reconnecting in 5s", exc
                )
                reconnecting = True
                await asyncio.sleep(5)
            finally:
                # Return the pubsub's connection on every reconnect.
                # BaseException: a re-delivered CancelledError during shutdown
                # must not skip it.
                if not teardown and pubsub:
                    with suppress(BaseException):
                        await pubsub.aclose()

    @classmethod
    async def _relay_redis_message(cls, app, raw: str, primed: bool = False) -> bool:
        """Hand one frame from the relay channel to the pages it is for.
        True once the delivery caches are primed: primed says they already
        are, for this batch of frames.

        raw is a str: Open WebUI's client sets decode_responses.
        """
        if raw.startswith("wid:"):
            newline = raw.index("\n")
            if raw[4:newline] == cls._WORKER_ID:
                return primed
            raw = raw[newline + 1 :]
        if raw.startswith(cls._PERSONAL_PREFIX):
            user_id, _, msg = raw[len(cls._PERSONAL_PREFIX) :].partition("\n")
            cls._deliver(msg, user_id)
        elif raw.startswith(cls._SIGNED_IN_PREFIX):
            cls._deliver(raw[len(cls._SIGNED_IN_PREFIX) :], signed_in_only=True)
        elif raw.startswith(cls._CTRL_PREFIX):
            # Control messages never reach browsers
            ctrl = raw[len(cls._CTRL_PREFIX) :].strip()
            if ctrl.startswith("bind "):
                # A page on another worker claimed one of our streams
                parts = ctrl.split()
                if len(parts) == 3:
                    cls._bind_stream(parts[1], parts[2])
            elif ctrl == "valvesync":
                try:
                    await cls._handle_peer_valve_sync(app)
                except Exception:
                    log.warning("[Theme Pro] Peer valve sync failed", exc_info=True)
        else:
            # A peer saved the theme: rebuild what its pages refetch here, off
            # the loop, before telling them. Frames after it wait, in order.
            inst = cls.instance
            if (
                not primed
                and raw.startswith("event: theme-update\n")
                and inst is not None
                and reload_active(app)
            ):
                primed = True
                try:
                    await asyncio.to_thread(inst._prime_delivery_caches, app)
                except Exception:
                    log.warning("[Theme Pro] Priming after a peer's save failed", exc_info=True)
            cls._deliver(raw)
        return primed

    # Every event that can change a model's background image
    _MODEL_EVENTS = (
        "model.created",
        "model.updated",
        "model.deleted",
        "model.imported",
        "model.synced",
    )

    async def _broadcast_background_event(self, event_name: str, event: dict, subject: dict):
        """Tell pages about a changed background image: Open WebUI shows the
        new image at once, and the theme's fade finds an image by its
        address."""
        if event_name == "user.settings_updated":
            if subject.get("id") and subject.get("type") == "user":
                Event._broadcast_backgrounds(str(subject["id"]))
            return
        if event_name not in self._MODEL_EVENTS:
            return
        ids = ((event or {}).get("data") or {}).get("model_ids")
        if subject.get("id"):
            ids = [subject["id"]]
        if not isinstance(ids, list) or not ids or len(ids) > self._MODEL_IDS_MAX:
            Event._broadcast_backgrounds()
            return
        # A personal theme may fade a model the instance theme doesn't name,
        # and its id must not reach signed-out pages
        ids = {str(i) for i in ids}
        public = ids & await asyncio.to_thread(self._instance_faded_models)
        if public:
            Event._broadcast_backgrounds(model_ids=sorted(public))
        if ids - public and self.valves.allow_personal_themes:
            Event._broadcast_backgrounds(signed_in_only=True)

    async def event(
        self,
        event: dict = None,
        __event_name__: str = None,
        __id__: str = None,
        __app__=None,
        __request__=None,
        **kwargs,
    ) -> None:
        """Every event first shares the stream set (this dispatch may be the one that exec'd
        the source, and the disable and shutdown handlers reach streams through it) and goes to
        live_reload, which switches the function on and off on every worker; then to the @on
        handlers below."""
        if __app__ is None:
            return
        Event._share_sse_clients(__app__)
        if __event_name__ not in ("system.shutdown.started", "system.shutdown.completed"):
            await reload_on_event(__app__, event, __event_name__)
        await super().event(
            event,
            __event_name__=__event_name__,
            __id__=__id__,
            __app__=__app__,
            __request__=__request__,
            **kwargs,
        )

    @on("system.shutdown.started", "system.shutdown.completed")
    async def _shutting_down(self, app):
        """Open WebUI publishes system.shutdown.* from its lifespan exit while
        the event loop still runs: the only reliable shutdown hook, since
        router.on_shutdown never fires on lifespan-based apps. A subscriber
        still running when the loop closes surfaces at interpreter exit as
        "Task was destroyed but it is pending!" / "RuntimeError: no running
        event loop"."""
        if not getattr(app.state, "_theme_shutting_down", False):
            log.info(
                "[Theme Pro] Server shutdown — cancelling background tasks and closing SSE streams"
            )
            await Event._shutdown_cleanup(app)

    @on("function.disable_started", own=True)
    def _disabling(self):
        """Open WebUI dispatches function.disable_started BEFORE it commits
        is_active=False, and live_reload has already switched the function
        off on every worker: the next request composes a custom.css without
        our block and a loader.js with __THEME_ACTIVE__=false. theme-disable
        strips the theme from open tabs now."""
        log.info("[Theme Pro] Function is being disabled — CSS fragment withdrawn")
        Event._broadcast_disable()
        Event._published = False
        log.info(
            "[Theme Pro] Cleanup complete — CSS withdrawn, bootloader set inactive, clients notified"
        )

    @on("function.enable_started", own=True)
    def _enabling(self):
        """function.enable_started also comes before the commit (the
        not-yet-active function rides in extra_function_ids). _sync, which
        runs next, then republishes the fragments and rebroadcasts to open tabs."""
        log.info("[Theme Pro] Function is being re-enabled — triggering re-injection")
        Event._published = False
        Event._reenabling = True

    @on("user.deleted")
    async def _account_deleted(self, app, event):
        """A deleted account's personal theme and library go with it, whether
        personal themes are on or not."""
        if not reload_active(app):
            return
        subject = (event or {}).get("subject") or {}
        if subject.get("id") and subject.get("type", "user") == "user":
            await asyncio.to_thread(self._delete_user_themes, str(subject["id"]))

    @on(
        "user.settings_updated",
        "model.created",
        "model.updated",
        "model.deleted",
        "model.imported",
        "model.synced",
    )
    async def _background_changed(self, app, event, name):
        """A Chat Background Image or a model's image changed: pages fading it look it up again."""
        if reload_active(app):
            subject = (event or {}).get("subject") or {}
            await self._broadcast_background_event(name, event, subject)

    @on(
        "system.startup.started",
        "system.startup.completed",
        "function.enable_started",
        "function.updated",
        "function.valves_updated",
        own=True,
    )
    async def _sync(self, app):
        """Mount the routes, start the Redis subscriber and the exit hook, publish the two
        fragments, and tell open pages when what they show changed."""
        if not reload_active(app):
            return
        url_changed = (
            Event._last_designer_url is not None
            and Event._last_designer_url != self.valves.designer_url
        )
        route = self._get_route_base()
        if Event._routes_registered_url is None or route != Event._routes_registered_url:
            self._register_route(app)
            Event._routes_registered_url = route
            # Rebroadcast, so tabs already loaded refetch the theme. They stay
            # on the old route, served by its aliases, until they reload or
            # the server restarts.
            if url_changed:
                Event._published = False

        self._ensure_redis_subscriber(app)
        if getattr(app.state, "_theme_exit_hook_exec", None) != RELOAD_EXEC_ID:
            app.state._theme_exit_hook_exec = RELOAD_EXEC_ID
            with suppress(Exception):
                Event._install_exit_hook(app)

        # The valves whose change pushes a theme-update to open pages
        valve_changes = [
            f"{label} → {now}"
            for label, before, now in (
                ("Canvas FX", Event._last_enable_canvas_fx, self.valves.enable_canvas_fx),
                ("sidebar", Event._last_sidebar_transparency, self.valves.sidebar_transparency),
                ("overlay", Event._last_overlay_transparency, self.valves.overlay_transparency),
            )
            if before is not None and before != now
        ]

        # Any valve change tells peer workers to re-read from the DB: Open
        # WebUI reloads the function only on the worker where the change was
        # made. The first event of the process (no snapshot yet) is not a
        # change: peers load their own valves on their own startup.
        valves_now = self._valves_snapshot()
        if Event._last_valves_snapshot is not None and valves_now != Event._last_valves_snapshot:
            Event._broadcast_valve_sync()

        # Threaded: the flock can wait on another process and must not stall
        # the loop
        if not Event._legacy_index_cleaned:
            await asyncio.to_thread(self._clean_legacy_index_injection)

        was_not_published = not Event._published

        # Unconditional: re-pointing the two fragments on every event is what
        # makes a hot reload converge on the new instance's producers, and the
        # producers read self.valves at compose time.
        if self._publish_fragments(app):
            reenabling = Event._reenabling
            Event._reenabling = False
            reasons = (
                (["first publish cycle"] if was_not_published else [])
                + (["function re-enabled"] if reenabling else [])
                + valve_changes
            )
            if reasons:
                # Clients refetch unless the tags show they hold this
                # version already. Priming runs off-loop.
                etags = await asyncio.to_thread(self._prime_delivery_caches, app)
                Event._broadcast_update(etags)
                log.info(
                    "[Theme Pro] Valve change (%s) — pushed to SSE clients", ", ".join(reasons)
                )
            if was_not_published:
                log.info(
                    "[Theme Pro] Published loader.js + custom.css fragments to the shared static-asset registry"
                )
            Event._published = True
        else:
            # Only latch on success, so the next event retries
            log.warning("[Theme Pro] Fragment publish failed — will retry on next event")

        Event._last_designer_url = self.valves.designer_url
        Event._last_enable_canvas_fx = self.valves.enable_canvas_fx
        Event._last_sidebar_transparency = self.valves.sidebar_transparency
        Event._last_overlay_transparency = self.valves.overlay_transparency
        Event._last_valves_snapshot = valves_now


def register(app: Any) -> None:
    # Up to the last release the key was "theme-designer-pro": drop those fragments, wake its listeners.
    asset_fragments(app, LOADER_PATH).pop("theme-designer-pro", None)
    asset_fragments(app, CUSTOM_CSS_PATH).pop("theme-designer-pro", None)
    task = asyncio.create_task(reload_publish(app, True, "theme-designer-pro"))
    reload_tasks.add(task)
    task.add_done_callback(reload_tasks.discard)
    inst = Event.instance
    inst._publish_fragments(app)
    Event._share_sse_clients(app)

    # live_reload can execute this code on a worker that no event reaches, so
    # load its valves, routes and Redis subscriber the way a peer valve sync
    # does. Runs as a task: the valves are read from the database.
    async def load():
        inst._ensure_redis_subscriber(app)
        with suppress(Exception):
            Event._install_exit_hook(app)
        await Event._handle_peer_valve_sync(app)

    task = asyncio.get_running_loop().create_task(load())
    reload_tasks.add(task)
    task.add_done_callback(reload_tasks.discard)
