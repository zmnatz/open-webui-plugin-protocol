"""Drive upstream Theme Designer Pro and the owpp adaptation through the same requests in owpp's
mock Open-WebUI, and diff every response.

usage, from the repository root:

    uv run python examples/plugins/theme_designer_pro/adapt/compare_pages.py <upstream checkout> examples/plugins/theme_designer_pro

It prints each response that differs, then "N identical, M different". The responses named
"x: ..." are the ones owpp's sign-in guard answers itself, and differ on purpose (README:
"What behaves differently").
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from owpp.testing import MockOpenWebUI

upstream_file = Path(sys.argv[1]) / "event-function/theme_designer_pro_event.py"
plugin_dir = Path(sys.argv[2])
BASE = "/api/v1/theme-designer"
SAME_ORIGIN = {"sec-fetch-site": "same-origin"}
HTML = {"accept": "text/html", "sec-fetch-dest": "iframe"}

CSS = (
    ":root { --color-gray-950: oklch(0.2 0.02 250); }\n"
    "/*[OWUI_STRUCTURAL_START]*/#sidebar { /*[FX]*/ background-color: var(--color-gray-950) !important; }"
    "/*[OWUI_STRUCTURAL_END]*/\n/*[OWUI_CUSTOM_START]*/.x{color:red}/*[OWUI_CUSTOM_END]*/\n"
)
SECTIONS = {
    "vars": ":root { --color-gray-950: oklch(0.2 0.02 250); }\n",
    "structural": "/*[OWUI_STRUCTURAL_START]*/#sidebar { /*[FX]*/ background-color: var(--color-gray-950) !important; }/*[OWUI_STRUCTURAL_END]*/\n",
    "gradient": "",
    "custom": "/*[OWUI_CUSTOM_START]*/.x{color:red}/*[OWUI_CUSTOM_END]*/\n",
}
STATE = json.dumps({"dark": {"canvasEnabled": True, "canvasScript": "/* __THEME_ROUTE__ */ draw()", "themeShowAuth": True}})


def upstream_folder(tmp: Path) -> Path:
    d = tmp / "theme_designer_pro"
    d.mkdir()
    (d / "plugin.yaml").write_text(
        'protocol: "0.5"\nsource:\n  git: https://github.com/silentoplayz/theme-designer-pro-presets.git\n'
        "  ref: 9a7e68c9afe51539effae22767e843f26205d895\n  path: \"\"\n"
        "function:\n  file: event-function/theme_designer_pro_event.py\n"
    )
    return d


def run(kind: str) -> dict:
    out = {}
    tmp = Path(tempfile.mkdtemp())
    try:
        with MockOpenWebUI() as owui:
            if kind == "upstream":
                plugin = owui.load(
                    upstream_folder(tmp),
                    sources={"event-function/theme_designer_pro_event.py": upstream_file.read_text()},
                )
            else:
                shutil.copytree(plugin_dir, tmp / "theme_designer_pro", ignore=shutil.ignore_patterns("tests", "__pycache__"))
                plugin = owui.load(tmp / "theme_designer_pro")
            owui.startup()
            admin, ada = owui.admin, owui.add_user("Ada")
            admin.token, ada.token = "session-admin-0123456789", "session-ada-0123456789"  # upstream refuses sk- keys
            a, u, anon = owui.client(admin), owui.client(ada), owui.client()

            def rec(name, r):
                out[name] = (r.status_code, r.headers.get("content-type", "").split(";")[0], r.text)

            rec("designer, empty", a.get(BASE, headers=HTML))
            rec("theme.css, empty", anon.get(BASE + "/theme.css"))
            rec("state.json, empty", anon.get(BASE + "/state.json"))
            rec("save", a.post(BASE, json={"css": CSS, "state": STATE, "sections": SECTIONS, "origin": "tab1"}, headers=SAME_ORIGIN))
            rec("save again (no-op)", a.post(BASE, json={"css": CSS, "state": STATE, "sections": SECTIONS}, headers=SAME_ORIGIN))
            rec("save from another site", a.post(BASE, json={"css": CSS}, headers={"sec-fetch-site": "cross-site"}))
            rec("save as text/plain", a.post(BASE, content=b"{}", headers={**SAME_ORIGIN, "content-type": "text/plain"}))
            rec("theme.css", anon.get(BASE + "/theme.css"))
            rec("state.json", anon.get(BASE + "/state.json"))
            rec("library.json", a.get(BASE + "/library.json"))
            rec("designer", a.get(BASE, headers=HTML))
            rec("loader.js", anon.get("/static/loader.js"))
            rec("custom.css", anon.get("/static/custom.css"))
            rec("me/theme.css, off", u.get(BASE + "/me/theme.css"))
            rec("me/state.json signed out", anon.get(BASE + "/me/state.json"))
            rec("me/library.json signed out", anon.get(BASE + "/me/library.json"))

            for valves in (
                {"overlay_transparency": "translucent"},
                {"sidebar_transparency": "transparent"},
                {"enable_canvas_fx": False},
                {"enable_auth_page_theming": False},
                {"show_in_admin_panel": True, "show_in_admin_settings": False},
                {"enable_canvas_api_access": True, "calm_chat_column": True, "allowed_import_domains": "a.com, b.org"},
                {"draft_mode_default": True, "auto_sync": True, "enable_custom_css": False},
            ):
                owui.set_valves("theme_designer_pro", **valves)
                tag = ",".join(f"{k}={v}" for k, v in valves.items())
                rec(f"designer [{tag}]", a.get(BASE, headers=HTML))
                rec(f"theme.css [{tag}]", anon.get(BASE + "/theme.css"))
                rec(f"state.json [{tag}]", anon.get(BASE + "/state.json"))
                rec(f"loader.js [{tag}]", anon.get("/static/loader.js"))
                rec(f"custom.css [{tag}]", anon.get("/static/custom.css"))
                owui.set_valves("theme_designer_pro", **{k: plugin.instance.Valves.model_fields[k].default for k in valves})

            owui.set_valves("theme_designer_pro", allow_personal_themes=True)
            rec("personal designer", u.get(BASE + "?scope=me", headers=HTML))
            rec("personal save", u.post(BASE + "/me", json={"css": CSS.replace("red", "blue"), "state": STATE}, headers=SAME_ORIGIN))
            rec("me/theme.css", u.get(BASE + "/me/theme.css"))
            rec("me/state.json", u.get(BASE + "/me/state.json"))
            rec("me/library.json", u.get(BASE + "/me/library.json"))
            rec("personal designer, saved", u.get(BASE + "?scope=me", headers=HTML))
            rec("loader.js, personal on", anon.get("/static/loader.js"))
            rec("personal reset", u.post(BASE + "/me", json={"reset": True}, headers=SAME_ORIGIN))
            rec("me/theme.css after reset", u.get(BASE + "/me/theme.css"))
            rec("instance reset", a.post(BASE, json={"reset": True}, headers=SAME_ORIGIN))
            rec("theme.css after reset", anon.get(BASE + "/theme.css"))
            rec("custom.css after reset", anon.get("/static/custom.css"))
            rec("x: designer, signed out, browser", owui.client(follow_redirects=False).get(BASE, headers={"accept": "text/html"}))
            rec("x: designer, signed out, fetch", anon.get(BASE))
            rec("x: designer, a user", u.get(BASE, headers=HTML))
            rec("x: library.json, a user", u.get(BASE + "/library.json"))
            rec("x: save, signed out", anon.post(BASE, json={"css": "a"}, headers=SAME_ORIGIN))
            key = owui.client(); key.headers["Authorization"] = "Bearer sk-api-key"
            rec("x: page-background, signed out", anon.get(BASE + "/page-background"))
            owui.disable("theme_designer_pro")
            rec("x: theme.css, disabled", anon.get(BASE + "/theme.css"))
            rec("x: designer, disabled", a.get(BASE, headers=HTML))
            rec("loader.js, disabled", anon.get("/static/loader.js"))
            rec("custom.css, disabled", anon.get("/static/custom.css"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


up, ours = run("upstream"), run("ours")
same = differ = 0
for name in up:
    if up[name] == ours.get(name):
        same += 1
        continue
    differ += 1
    (us, ut, ub), (os_, ot, ob) = up[name], ours.get(name, (None, None, ""))
    print(f"DIFF {name}: upstream {us} {ut} {len(ub)}B, ours {os_} {ot} {len(ob)}B")
    if us == os_ and ub != ob:
        import difflib

        for line in list(difflib.unified_diff(ub.splitlines(), ob.splitlines(), lineterm="", n=0))[:12]:
            print("   ", line[:200])
    elif ub != ob:
        print("    upstream:", ub[:200].replace("\n", "\\n"))
        print("    ours:    ", ob[:200].replace("\n", "\\n"))
print(f"{same} identical, {differ} different")
