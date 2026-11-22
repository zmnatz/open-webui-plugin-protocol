# Theme Designer Pro Launcher: builds a theme someone describes in a chat and shows it as a card
# with a live preview, Apply and Undo, or opens the designer inside the chat.
#
# Adapted from Theme Designer Pro Launcher 2.1.2 by G30 (https://openwebui.com/u/g30), from
# silentoplayz/theme-designer-pro-presets, Copyright (c) 2026 silentoplayz, MIT licence (the
# notice is in NOTICE.md at the repository root):
# https://github.com/silentoplayz/theme-designer-pro-presets/blob/9a7e68c9afe51539effae22767e843f26205d895/launcher/theme_designer_pro_launcher.py
#
# It does what the original does. What changed: the header is plugin.yaml's `tool:`; the theme
# card and the designer frame are templates/launcher/ (the tool embeds only that folder,
# `tool: templates: [launcher/]`); and the signed link is shared.py's, the same code the
# function reads it with.

import asyncio
import colorsys
import hashlib
import json
import re
import time
from urllib.parse import quote

from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from owpp.lib import plugin_template_text

from shared import THEME_TOKEN_PREFIX, _fill, _sign_token, _token_key

# A card's Apply button works for this long after the chat built the theme.
THEME_TOKEN_SECONDS = 30 * 24 * 3600
MODES = ("all", "dark", "oled", "light", "her")

# A script the chat model wrote starts with this line, and Theme Designer Pro
# 1.18.0 and later run such a script isolated: no cookies, no requests, no page
ISOLATED_MARK = "/* tdp:isolated */"
ANIMATION_MAX_BYTES = 40 * 1024
CSS_MAX_BYTES = 16 * 1024

# The Canvas FX catalog, fetched once an hour at most
_catalog = {"at": 0.0, "url": "", "presets": []}
_catalog_lock = asyncio.Lock()
# Animations that aren't backgrounds
CATALOG_SKIP = {"diagnostic hud"}
STOPWORDS = {
    "the",
    "and",
    "with",
    "for",
    "that",
    "this",
    "your",
    "theme",
    "themes",
    "background",
    "animated",
    "animation",
    "like",
    "some",
    "make",
    "want",
    "into",
    "over",
    "from",
    "chat",
}

# Frosted glass in Open WebUI's own shapes, tinted by the palette and the
# theme's accent. !important only where Canvas FX transparency clears a background.
GLASS_RULES = """
#message-input-container {
	background-color: var(--tdp-glass) !important;
	border-color: var(--tdp-glass-line) !important;
	backdrop-filter: blur(18px) saturate(1.35);
	box-shadow: 0 14px 40px -18px var(--tdp-glass-shade);
	transition: border-color 0.3s ease, box-shadow 0.3s ease;
}
#message-input-container:focus-within {
	border-color: var(--tdp-glass-glow) !important;
	box-shadow: 0 0 0 3px var(--tdp-glass-ring), 0 14px 40px -18px var(--tdp-glass-shade);
}
.chat-user .rounded-3xl {
	background-color: var(--tdp-glass-bubble) !important;
	backdrop-filter: blur(12px);
	box-shadow: inset 0 0 0 1px var(--tdp-glass-line);
}
#sidebar {
	background-color: var(--tdp-glass-side) !important;
	backdrop-filter: blur(22px) saturate(1.25);
	border-inline-end: 1px solid var(--tdp-glass-line);
}
#sidebar-chat-item.selected { background-color: var(--tdp-glass-selected); }
.markdown-prose a { color: var(--tdp-accent); text-decoration-color: var(--tdp-glass-glow); }
.markdown-prose blockquote { border-inline-start-color: var(--tdp-glass-glow); }
::selection { background-color: var(--tdp-glass-ring); }
"""
GLASS_DARK = """:root {
	--tdp-glass: color-mix(in oklab, var(--color-gray-900) 55%, transparent);
	--tdp-glass-side: color-mix(in oklab, var(--color-gray-950) 68%, transparent);
	--tdp-glass-bubble: color-mix(in oklab, var(--tdp-accent) 14%, var(--color-gray-800) 46%);
	--tdp-glass-selected: color-mix(in oklab, var(--color-gray-500) 20%, transparent);
	--tdp-glass-line: color-mix(in oklab, var(--color-gray-400) 20%, transparent);
	--tdp-glass-glow: color-mix(in oklab, var(--tdp-accent) 45%, transparent);
	--tdp-glass-ring: color-mix(in oklab, var(--tdp-accent) 16%, transparent);
	--tdp-glass-shade: color-mix(in oklab, var(--color-gray-950) 70%, transparent);
}
"""
GLASS_LIGHT = """:root {
	--tdp-glass: color-mix(in oklab, var(--color-gray-50) 64%, transparent);
	--tdp-glass-side: color-mix(in oklab, var(--color-gray-50) 70%, transparent);
	--tdp-glass-bubble: color-mix(in oklab, var(--tdp-accent) 10%, var(--color-gray-100) 56%);
	--tdp-glass-selected: color-mix(in oklab, var(--color-gray-400) 18%, transparent);
	--tdp-glass-line: color-mix(in oklab, var(--color-gray-500) 26%, transparent);
	--tdp-glass-glow: color-mix(in oklab, var(--tdp-accent) 50%, transparent);
	--tdp-glass-ring: color-mix(in oklab, var(--tdp-accent) 18%, transparent);
	--tdp-glass-shade: color-mix(in oklab, var(--color-gray-600) 26%, transparent);
}
"""


def _hsl_hex(hue: float, sat: float, lit: float) -> str:
    r, g, b = colorsys.hls_to_rgb((hue % 360) / 360, lit / 100, sat / 100)
    return "#{:02x}{:02x}{:02x}".format(*tuple(round(v * 255) for v in (r, g, b)))


def _hex(value: str) -> str:
    value = str(value or "").strip().lower()
    return value if re.fullmatch(r"#[0-9a-f]{6}", value) else ""


def _light_accent(accent: str) -> str:
    """The same accent, dark enough to read on Light and Her."""
    if not accent:
        return ""
    r, g, b = (int(accent[i : i + 2], 16) / 255 for i in (1, 3, 5))
    h, light, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, min(light, 0.42), s)
    return "#{:02x}{:02x}{:02x}".format(*tuple(round(v * 255) for v in (r, g, b)))


def _words(text: str) -> set:
    """Words that say what an animation shows, plurals folded: "leaves" meets "leave"."""
    words = {
        w
        for w in re.findall(r"[a-z]+", str(text or "").lower())
        if len(w) > 2 and w not in STOPWORDS
    }
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words}


def _strip_js_comments(code: str) -> str:
    return re.sub(r"(^|\s)//.*$", r"\1", re.sub(r"/\*[\s\S]*?\*/", "", code), flags=re.M)


# A setting the designer turns into a slider, switch or color picker: a top-level
# UPPER_CASE constant with a literal value, above the first function
SETTING_LINE = re.compile(
    r"""^(?:const|let|var)\s+[A-Z][A-Z0-9_]*\s*=\s*(?:-?\d*\.?\d+(?:e-?\d+)?|true|false|['"]#[0-9a-fA-F]{3,8}['"])\s*;"""
)
FROM_TEMPLATE = " Start from the theme-designer-pro skill's templates/animation.js (read it with read_skill_file) and change what it draws."


def _check_animation(code: str) -> str:
    problem = _animation_problem(code)
    return problem + "." + FROM_TEMPLATE if problem else ""


def _animation_problem(code: str) -> str:
    """What keeps a script the chat model wrote from running well, or "".

    The house standard's hard rules (scripts/validate.js) and the template's
    shape, which gives every animation its settings, plus the isolated
    runtime's: no requests of any kind."""
    if len(code.encode("utf-8")) > ANIMATION_MAX_BYTES:
        return f"it is over {ANIMATION_MAX_BYTES // 1024} KB; keep it between 4 and 20 KB"
    if not re.match(r"\s*/\*\*[\s\S]*?Title:\s*\S[\s\S]*?Description:\s*\S[\s\S]*?\*/", code):
        return "it doesn't open with the header block: /** with a Title: line and a Description: line */"
    body = _strip_js_comments(code)
    if "onmessage" not in body:
        return "it has no self.onmessage handler"
    handlers = len(re.findall(r"onmessage\s*=(?!=)", body)) + len(
        re.findall(r"addEventListener\(\s*['\"]message['\"]", body)
    )
    if handlers > 1:
        return "it sets its message handler more than once; handle every message in one self.onmessage switch"
    for case in ("init", "resize"):
        if not re.search(rf"['\"]{case}['\"]", body):
            return f"it has no '{case}' case in its self.onmessage switch"
    for pattern, what in (
        (r"(^|[^.\w$])document\b", "`document`"),
        (r"(^|[^.\w$])window\s*[.\[]", "`window`"),
        (r"(^|[^.\w$])(localStorage|sessionStorage|indexedDB)\b", "browser storage"),
        (r"(^|[^.\w$])alert\s*\(", "`alert`"),
        (
            r"\b(fetch|importScripts|XMLHttpRequest|WebSocket|EventSource|navigator\.sendBeacon)\b|\bimport\s*\(",
            "network requests",
        ),
    ):
        if re.search(pattern, body):
            return f"it uses {what}, which an animation can't: it runs in an isolated worker that can only draw"
    if "getContext(" not in body:
        return "it never gets a drawing context from the canvas the 'init' message carries"
    if re.search(r"getContext\(\s*['\"]webgl2?['\"]", body) and "webglcontextlost" not in body:
        return "it uses WebGL without handling webglcontextlost"
    settings = 0
    for line in code.split("\n"):
        if re.match(r"\s*(?:function|class|async\s+function|self\.onmessage|onmessage)\b", line):
            break
        settings += bool(SETTING_LINE.match(line))
    if settings < 4:
        return (
            f"it has {settings} settings; it needs at least 4 top-level constants such as "
            "`const SPEED = 1; // speed (0-3)` above its first function, which the designer turns into sliders"
        )
    return ""


# An escape is its own token, first: \/* opens no comment and \" no string.
CSS_TOKEN = re.compile(
    r"""\\[\s\S]|/\*[\s\S]*?(?:\*/|\Z)|"(?:[^"\\\n]|\\[\s\S])*(?:"|(?=\n)|\Z)|'(?:[^'\\\n]|\\[\s\S])*(?:'|(?=\n)|\Z)"""
)
CLOSED_STRING = re.compile(r"""\A(?:"(?:[^"\\\n]|\\[\s\S])*"|'(?:[^'\\\n]|\\[\s\S])*')\Z""")
CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\n]?|(\n)|([\s\S]))")
# Where an image may sit in image-set(): only a data: string or a gradient
# (url() is checked on its own). A var() could hold a string the browser fetches.
IMAGE_CANDIDATE = re.compile(r"""[ \t\n]*(?:["']data:|url\(|[a-z-]*gradient\()""")


def _css_as_browser_reads_it(css: str):
    """The stylesheet with comments gone and escapes decoded, ASCII-lowercased,
    and whether it leaves a comment or string unclosed.

    Comments go and strings stay, as in the browser's tokenizer. An escaped
    character is never syntax, so one that isn't a letter, digit, - or _
    becomes _: it can't open a string or a function the browser wouldn't.
    Whitespace is CSS's own, [ \\t\\n] once newlines are normalized."""
    css = re.sub(r"\r\n?|\f", "\n", css)
    unclosed = False

    def token(m):
        nonlocal unclosed
        t = m.group()
        if t.startswith("/*"):
            unclosed = unclosed or len(t) < 4 or not t.endswith("*/")
            return ""
        if t[0] in "\"'" and not CLOSED_STRING.match(t):
            unclosed = True
        return t

    css = CSS_TOKEN.sub(token, css)

    def decode(m):
        if m.group(2):
            return ""
        if m.group(1):
            n = int(m.group(1), 16)
            ch = chr(n) if 0 < n < 0x110000 and not 0xD800 <= n < 0xE000 else "_"
        else:
            ch = m.group(3)
        return ch if re.fullmatch(r"[A-Za-z0-9_-]", ch) else "_"

    css = re.sub(r"[A-Z]+", lambda m: m.group().lower(), CSS_ESCAPE.sub(decode, css))
    return css, unclosed


def _image_set_fetches(css: str, start: int) -> bool:
    """Whether the image-set() whose arguments begin at start names anything
    but data: strings and gradients."""
    depth, i, candidate = 0, start, True
    while i < len(css):
        if candidate and depth == 0:
            if not IMAGE_CANDIDATE.match(css, i):
                return True
            candidate = False
        ch = css[i]
        if ch in "\"'":
            string = CSS_TOKEN.match(css, i)
            i = string.end() if string else i + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return False
            depth -= 1
        elif ch == "," and depth == 0:
            candidate = True
        i += 1
    return False


def _css_fetch_problem(css: str) -> str:
    read, unclosed = _css_as_browser_reads_it(css)
    if unclosed:
        return "it leaves a comment or string unclosed"
    if "@import" in read:
        return "it uses @import; everything has to be in the stylesheet itself"
    # Only a quoted data: URL: an unquoted one followed by anything but ) is a
    # broken url token, which the browser skips to the next ), comments and
    # quotes included, so what looks like a comment after it is live CSS
    if re.search(r"""(?:url|src)[ \t\n]*\((?![ \t\n]*['"]data:)""", read) or any(
        _image_set_fetches(read, m.end()) for m in re.finditer(r"image(?:-set)?[ \t\n]*\(", read)
    ):
        return 'it loads a url(), image-set() or src(); only quoted data: URLs such as url("data:...") are allowed, so a theme never fetches anything'
    if re.search(r"expression[ \t\n]*\(|javascript:|-moz-binding|behavior[ \t\n]*:", read):
        return "it uses script in CSS"
    return ""


def _check_css(css: str) -> str:
    """What a stylesheet the chat model wrote may not do, or ""."""
    if len(css.encode("utf-8")) > CSS_MAX_BYTES:
        return f"it is over {CSS_MAX_BYTES // 1024} KB"
    # The HTML parser ends a <style> before CSS comments or escapes mean anything
    if "</style" in css.lower() or "<script" in css.lower():
        return "it contains HTML tags"
    return _css_fetch_problem(css)


def _gradient_from(colors: str):
    """Stops spread evenly from a comma-separated list of #rrggbb colors, or None."""
    hexes = [c for c in (_hex(x) for x in str(colors or "").split(",")) if c][:8]
    if len(hexes) < 2:
        return None
    return {
        "stops": [
            {"color": c, "position": round(i * 100 / (len(hexes) - 1))} for i, c in enumerate(hexes)
        ]
    }


def _title(script: str) -> str:
    found = re.search(r"Title:\s*(.+)", script)
    return re.sub(r"\s*\(.*?\)", "", found.group(1).strip())[:48] if found else "Custom animation"


def _mode_data(
    h, c, lum, accent="", gradient=None, canvas="", css="", accent2="", accent3=""
) -> dict:
    """One mode with every field the theme format lists, defaults included."""
    g = gradient or {}
    return {
        "h": h,
        "c": c,
        "l": lum,
        "paletteEnabled": True,
        "accent": accent,
        "accent2": accent2,
        "accent3": accent3,
        "overrides": {},
        "locks": {},
        "manualOverrides": "",
        "manualOverridesEnabled": False,
        "customCSS": css,
        "customCssEnabled": bool(css),
        "autoScope": True,
        "canvasScript": canvas,
        "canvasEnabled": bool(canvas),
        "gradientEnabled": bool(g),
        "gradientType": "linear",
        "gradientStops": g.get("stops", []),
        "gradientAngle": 135,
        "gradientRadialPosX": 50,
        "gradientRadialPosY": 50,
        "gradientRadialShape": "ellipse",
        "gradientRadialSize": "farthest-corner",
        "gradientMeshPoints": [],
        "gradientMeshBgColor": "#0a0a12",
        "gradientIntensity": 100 if g else 85,
        "gradientAnimation": False,
        "gradientAnimationSpeed": 8,
        "themeShowAuth": True,
        "customCssShowAuth": True,
        "canvasShowAuth": True,
        "gradientShowAuth": True,
        "themeAuthOnly": False,
        "customCssAuthOnly": False,
        "canvasAuthOnly": False,
        "gradientAuthOnly": False,
    }


class Tools:
    class Valves(BaseModel):
        designer_url: str = Field(
            default="/api/v1/theme-designer",
            description="Route where the Theme Designer Pro event function serves its page. Must match the event function's designer_url valve.",
        )
        background_animations: bool = Field(
            default=True,
            description="Let a theme from a chat have an animated Canvas FX background from the catalog below. Off, themes are palette, gradient and glass only.",
        )
        model_written_animations: bool = Field(
            default=True,
            description="Let the chat model write a new animation when nothing in the catalog fits. It runs isolated, with no access to the account, the page or the network, and needs Theme Designer Pro 1.18.0. Off, animations come from the catalog only.",
        )
        model_written_css: bool = Field(
            default=True,
            description='Let the chat model add its own CSS to a theme. It can\'t load anything: no @import, and url(), image-set() and src() only with quoted data: URLs such as url("data:...").',
        )
        canvas_catalog_url: str = Field(
            default="https://raw.githubusercontent.com/silentoplayz/theme-designer-pro-presets/main/bundles/canvas-fx-all.json",
            description="Canvas FX bundle the animated backgrounds come from, fetched by the server. Only scripts from here ever run; the chat model only names one.",
        )
        iframe_height: int = Field(
            default=800,
            description="Height of the designer in pixels when a chat opens it.",
        )
        iframe_scale: float = Field(
            default=1.0,
            description="Scale factor for the designer page inside the chat. Lower values fit more content but make it smaller. 1.0 = native size.",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _designer_url(self, personal: bool, apply_token: str = "") -> str:
        url = self.valves.designer_url.rstrip("/")
        params = []
        if personal:
            params.append("scope=me")
        if apply_token:
            params.append("apply=" + quote(apply_token, safe=""))
        return url + ("?" + "&".join(params) if params else "")

    @staticmethod
    def _sign(user_id: str, personal: bool, sha: str, mode: str) -> str:
        """A token the event function accepts for this user only: the hash of
        the theme the chat built, signed with WEBUI_SECRET_KEY."""
        key = _token_key()
        if not key or not user_id:
            return ""
        payload = {
            "u": user_id,
            "x": int(time.time()) + THEME_TOKEN_SECONDS,
            "s": "me" if personal else "everyone",
            "h": sha,
            "m": mode,
        }
        return _sign_token(key, THEME_TOKEN_PREFIX, payload)

    async def _presets(self) -> list:
        """The catalog's animations as (name, description, script)."""
        url = self.valves.canvas_catalog_url.strip()
        async with _catalog_lock:
            if (
                _catalog["url"] == url
                and _catalog["presets"]
                and time.time() - _catalog["at"] < 3600
            ):
                return _catalog["presets"]
            try:
                import aiohttp

                async with (
                    aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session,
                    session.get(url) as response,
                ):
                    response.raise_for_status()
                    data = json.loads(await response.text())
            except Exception:
                return _catalog["presets"] if _catalog["url"] == url else []
            presets = []
            for p in data.get("canvas_presets", []) if isinstance(data, dict) else []:
                name, script = str(p.get("name") or ""), str(p.get("script") or "")
                if not name or not script or name.lower() in CATALOG_SKIP:
                    continue
                found = re.search(r"Description:\s*(.+)", script)
                presets.append((name, found.group(1).strip() if found else "", script))
            _catalog.update(at=time.time(), url=url, presets=presets)
            return presets

    async def _animation(self, wanted: str):
        """The catalog animation that best fits the words asked for, or None."""
        words = _words(wanted)
        if not words:
            return None, []
        presets = await self._presets()
        best, best_score = None, 0
        for name, description, script in presets:
            label = re.sub(r"\s*\(.*?\)", "", name).lower()
            # How much of the request it covers first; a word in its name breaks ties
            covered = words & (_words(label) | _words(description))
            score = (
                (10 if label in str(wanted).lower() else 0)
                + 4 * len(covered)
                + len(words & _words(label))
            )
            if score > best_score:
                best, best_score = (name, description, script), score
        return best, [p[0] for p in presets]

    async def open_theme_designer(
        self, my_theme: bool = False, __user__: dict | None = None
    ) -> tuple:
        """
        Open the Theme Designer Pro designer inside the chat, for working on a theme by hand.

        When to use: ONLY when the user asks for the designer itself.
        Trigger phrases: "open theme designer", "launch theme designer", "open the theme editor",
        "show me the designer", "theme settings".

        Do NOT use this when the user asks for a theme, describes colors, a mood, a place or an
        aesthetic; use create_theme for that.

        :param my_theme: For admins only. True opens the admin's own personal theme; False (default) opens the instance theme every user sees. Users always get their own personal theme.
        """
        __user__ = __user__ or {}
        personal = __user__.get("role") != "admin" or bool(my_theme)
        url = self._designer_url(personal)
        return await self._embed(
            url,
            url,
            "The designer is open in the chat, on "
            + (
                "the user's own personal theme."
                if personal
                else "the instance theme every user sees."
            ),
        )

    async def create_theme(
        self,
        name: str,
        hue: int,
        chroma: int,
        lightness: int = 16,
        description: str = "",
        accent: str = "",
        background: str = "",
        animation_code: str = "",
        glass: bool = True,
        custom_css: str = "",
        gradient: bool = True,
        gradient_colors: str = "",
        accent2: str = "",
        accent3: str = "",
        mode: str = "all",
        everyone: bool = False,
        __user__: dict | None = None,
    ) -> tuple:
        """
        Build a whole Open WebUI theme the user describes and show it in the chat as a card with a live
        preview and an Apply button. Nothing changes until the user presses Apply on the card. When the
        theme-designer-pro skill is available, read it first: it covers palettes, glass, custom CSS and
        writing a new animation.

        When to use: The user asks for a theme or describes one: colors, a mood, a place, an aesthetic.
        Trigger phrases: "give me a blue theme", "make my chat a koi pond", "a cozy autumn theme",
        "something cyberpunk with rain", "change my theme to red", "ocean vibe".

        :param name: A short, evocative theme name shown on the card (e.g. "Honu Lagoon", "Warm Copper").
        :param hue: Palette hue angle (0-360). 0=red, 25=orange, 50=yellow, 90=chartreuse, 120=green, 165=teal, 200=cyan, 220=blue, 260=indigo, 290=purple, 330=pink/magenta.
        :param chroma: Palette colorfulness (0-60). 3-8=muted/neutral, 10-25=balanced, 30-60=vivid.
        :param lightness: Dark mode base lightness (5-30). 5-10=very dark, 12-18=standard, 20-30=lighter. Light mode is made to match.
        :param description: One sentence for the card about how the theme looks.
        :param accent: Optional "#rrggbb" for links, focus rings and highlights; empty picks one from the hue.
        :param background: An animated background from Theme Designer Pro's catalog, described in a few words, such as "koi pond", "deep ocean with jellyfish", "falling leaves", "rain and lightning", "aurora", "starry constellations", "matrix rain", "snow", "fireflies", "embers", "synthwave sun", "lava lamp". The closest one is used. Empty for a still background.
        :param animation_code: A complete new Canvas FX script you wrote, for a background the catalog doesn't have. Used instead of `background`. Follow the theme-designer-pro skill's Canvas FX reference: a header with Title and Description, a self.onmessage switch with 'init', 'resize' and 'theme' cases, colors from the theme, transparent canvas, calm behind the chat column. No document, window, storage or network: it runs isolated and can only draw.
        :param glass: Frosted, see-through panels so the background shows through (default True).
        :param custom_css: Extra CSS for the theme, after the glass. Use Open WebUI's own element ids and the theme's variables (--color-gray-50 to --color-gray-950, --tdp-accent). No @import; url(), image-set() and src() only with quoted data: URLs, such as url("data:image/png;base64,..."); close every comment and string.
        :param gradient: A gradient background when there is no animated background (default True).
        :param gradient_colors: Optional comma-separated "#rrggbb" colors (2-8) for the gradient, dark to light or as they should run; empty makes one from the hue.
        :param accent2: Optional "#rrggbb" second accent (animations use all three).
        :param accent3: Optional "#rrggbb" third accent (animations use all three).
        :param mode: Which mode(s) to build for. "all" (default), "dark", "oled", "light" or "her".
        :param everyone: For admins only. True builds it for the instance theme every user sees, and only when the admin clearly asks for that (e.g. "for everyone"). Default False: the user's own theme.
        """
        __user__ = __user__ or {}
        personal = __user__.get("role") != "admin" or not everyone
        mode = mode if mode in MODES else "all"
        name = " ".join(str(name or "").split())[:60] or "Chat theme"
        description = " ".join(str(description or "").split())[:240]
        h = max(0, min(360, int(hue)))
        c = max(0, min(60, int(chroma)))
        lum = max(5, min(30, int(lightness)))
        accent, accent2, accent3 = _hex(accent), _hex(accent2), _hex(accent3)

        # The chat model's own animation and CSS: checked here, so a problem goes
        # back to it to fix before anything reaches the user
        written = str(animation_code or "").strip()
        extra_css = str(custom_css or "").strip()
        if written and not self.valves.model_written_animations:
            return "Not built: an admin turned off animations the chat model writes. Use `background` to pick one from the catalog instead."
        if written:
            problem = _check_animation(written)
            if problem:
                return f"Not built: the animation_code can't be used because {problem} Then call create_theme again."
        if extra_css and not self.valves.model_written_css:
            return (
                "Not built: an admin turned off CSS the chat model writes. Leave custom_css empty."
            )
        if extra_css:
            problem = _check_css(extra_css)
            if problem:
                return f"Not built: the custom_css can't be used because {problem}. Fix it and call create_theme again."

        animation, catalog = (None, [])
        if written:
            animation = (_title(written), "", ISOLATED_MARK + "\n" + written)
        elif background.strip() and self.valves.background_animations:
            animation, catalog = await self._animation(background)
        script = animation[2] if animation else ""
        dark_gradient = None
        light_gradient = None
        if gradient and not script and _gradient_from(gradient_colors):
            dark_gradient = _gradient_from(gradient_colors)
        if gradient and not script and not dark_gradient:
            dark_gradient = {
                "stops": [
                    {"color": _hsl_hex(h, 15, 4), "position": 0},
                    {"color": _hsl_hex(h, 25, 12), "position": 33},
                    {"color": _hsl_hex(h, 20, 7), "position": 66},
                    {"color": _hsl_hex(h, 15, 4), "position": 100},
                ]
            }
        if gradient and not script:
            light_gradient = {
                "stops": [
                    {"color": _hsl_hex(h, 35, 97), "position": 0},
                    {"color": _hsl_hex(h + 15, 45, 91), "position": 40},
                    {"color": _hsl_hex(h, 40, 95), "position": 75},
                    {"color": _hsl_hex(h, 35, 97), "position": 100},
                ]
            }
        dark_css = ((GLASS_DARK + GLASS_RULES) if glass else "") + (
            extra_css + "\n" if extra_css else ""
        )
        light_css = ((GLASS_LIGHT + GLASS_RULES) if glass else "") + (
            extra_css + "\n" if extra_css else ""
        )
        la, la2, la3 = _light_accent(accent), _light_accent(accent2), _light_accent(accent3)
        light_c = round(c * 0.6)
        theme = {
            "name": name,
            "description": description or "Made in a chat with the Theme Designer Pro Launcher.",
            "author": "",
            "version": "1.0.0",
            "targetVersion": "1.18.0" if written else "1.17.0",
            "repositoryUrl": "",
            "updateUrl": "",
            "dark": _mode_data(
                h, c, lum, accent, dark_gradient, script, dark_css, accent2, accent3
            ),
            "oled": _mode_data(h, c, 0, accent, dark_gradient, script, dark_css, accent2, accent3),
            "light": _mode_data(h, light_c, 20, la, light_gradient, script, light_css, la2, la3),
            "her": _mode_data(h, light_c, 20, la, light_gradient, script, light_css, la2, la3),
        }
        text = json.dumps(theme, separators=(",", ":"), ensure_ascii=False)
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        token = self._sign(str(__user__.get("id") or ""), personal, sha, mode)

        parts = []
        if animation:
            parts.append(re.sub(r"\s*\(.*?\)", "", animation[0]) + (" (new)" if written else ""))
        elif gradient:
            parts.append("gradient")
        if glass:
            parts.append("glass")
        details = {
            "name": name,
            "description": theme["description"],
            "subtitle": " · ".join(["Your theme" if personal else "Instance theme"] + parts),
            "mode": mode,
            "written": bool(written),
            "sha": sha,
            "applyUrl": self._designer_url(personal, token) if token else "",
            "designerUrl": self._designer_url(personal),
            "theme": text,
        }

        built = f'Built "{name}"'
        if written:
            built += f', with your new animation "{animation[0]}"'
        elif animation:
            built += f', with the "{animation[0]}" animated background'
        elif background.strip() and not self.valves.background_animations:
            built += ", without an animated background (an admin turned them off)"
        elif background.strip():
            built += ", without an animated background: none in the catalog matched" + (
                " (it has: " + ", ".join(catalog) + ")"
                if catalog
                else " (the catalog could not be reached)"
            )
        built += (" and frosted glass panels" if glass else "") + ", for "
        built += "the user's own theme" if personal else "the instance theme every user sees"
        built += "" if mode == "all" else f" in {mode} mode only"
        return await self._card(details), (
            built
            + ". A card in the chat shows it with a live preview, Apply and Preview. Nothing has changed yet: "
            "the theme is applied only when the user presses Apply. Tell them in a sentence or two how it looks and "
            "that Apply puts it on; don't list settings or code."
        )

    async def _card(self, details: dict) -> HTMLResponse:
        """The theme card shown in the chat."""
        data = json.dumps(details, ensure_ascii=False).replace("<", "\\u003c")
        return HTMLResponse(
            headers={"Content-Disposition": "inline"}, content=CARD_HTML.replace("__DATA__", data)
        )

    async def _embed(self, frame_url: str, popout_url: str, result: str) -> tuple:
        """The designer in a frame, shown in the chat."""
        h = self.valves.iframe_height
        scale = self.valves.iframe_scale
        inner_h = int(h / scale)
        inner_w_pct = 100 / scale

        headers = {"Content-Disposition": "inline"}

        content = _fill(
            EMBED_HTML,
            {
                "HEIGHT": h,
                "INNER_WIDTH": inner_w_pct,
                "INNER_HEIGHT": inner_h,
                "SCALE": scale,
                "POPOUT_URL": popout_url,
                "FRAME_URL": frame_url,
            },
        )

        # Open WebUI shows an inline HTMLResponse as an embed in both function
        # calling modes; the text beside it is what the model reads.
        return HTMLResponse(headers=headers, content=content), result


# The card: the theme's name, a live preview (its palette, gradient, glass and
# Canvas FX running in a worker, as the presets website previews them),
# Apply and Preview. Apply opens the designer out of sight with the signed
# link and hands it the theme; the designer saves it and answers.
CARD_HTML = plugin_template_text("launcher/card.html").removesuffix("\n")

# The designer in a frame, shown in the chat: __HEIGHT__, __SCALE__ and the rest are filled in
# from the valves by _embed.
EMBED_HTML = plugin_template_text("launcher/embed.html").removesuffix("\n")
