"""The Launcher, upstream vs the adaptation, on owpp's test harness. Tokens are masked (they hold a time),
then each run's token is opened by its own designer page.

usage, from the repository root:

    uv run python examples/plugins/theme_designer_pro/adapt/compare_launcher.py <upstream checkout> examples/plugins/theme_designer_pro
"""

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from owpp.testing import Harness

repo, plugin_dir = Path(sys.argv[1]), Path(sys.argv[2])
TOOL = "theme_designer_pro_launcher"
TOKEN = re.compile(r"tdp-apply\.v2\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def run(kind):
    out = {}
    tmp = Path(tempfile.mkdtemp())
    try:
        with Harness() as owui:
            if kind == "upstream":
                d = tmp / "theme_designer_pro"
                d.mkdir()
                (d / "plugin.yaml").write_text(
                    'protocol: "0.7"\nsource:\n  git: https://github.com/silentoplayz/theme-designer-pro-presets.git\n'
                    '  ref: 34345eaffb8678ddfd38b45d7bc173f5b0d27132\n  path: ""\n'
                    "function:\n  file: event-function/theme_designer_pro_event.py\n"
                    f"tool:\n  id: {TOOL}\n  file: launcher/theme_designer_pro_launcher.py\n  access: public\n"
                )
                owui.load(
                    d,
                    sources={
                        "event-function/theme_designer_pro_event.py": (
                            repo / "event-function/theme_designer_pro_event.py"
                        ).read_text(),
                        "launcher/theme_designer_pro_launcher.py": (
                            repo / "launcher/theme_designer_pro_launcher.py"
                        ).read_text(),
                    },
                )
            else:
                shutil.copytree(
                    plugin_dir,
                    tmp / "theme_designer_pro",
                    ignore=shutil.ignore_patterns("tests", "__pycache__"),
                )
                owui.load(tmp / "theme_designer_pro")
            owui.startup()
            owui.set_valves("theme_designer_pro", allow_personal_themes=True)
            admin, ada = owui.admin, owui.add_user("Ada")
            tool = owui.tool(TOOL)
            specs = {s["name"]: s for s in tool.specs}
            out["specs: names"] = sorted(specs)
            out["specs: parameters"] = {
                n: sorted(s["parameters"]["properties"]) for n, s in specs.items()
            }
            tokens = {}

            def call(label, method, user, **kw):
                result = tool.call(method, user=user, **kw)
                parts = result if isinstance(result, tuple) else (result,)
                texts = []
                for part in parts:
                    body = getattr(part, "body", None)
                    text = body.decode() if isinstance(body, (bytes, bytearray)) else str(part)
                    for t in TOKEN.findall(text):
                        tokens.setdefault(label, t)
                    texts.append(TOKEN.sub("<token>", text))
                out[label] = texts

            call("open, admin", "open_theme_designer", admin)
            call("open, admin, my theme", "open_theme_designer", admin, my_theme=True)
            call("open, user", "open_theme_designer", ada)
            call(
                "create, user",
                "create_theme",
                ada,
                name="Honu Lagoon",
                hue=180,
                chroma=20,
                accent="#22aacc",
                gradient_colors="#001122,#114455",
            )
            call(
                "create, admin, everyone",
                "create_theme",
                admin,
                name="Warm Copper",
                hue=25,
                chroma=30,
                everyone=True,
                mode="dark",
            )
            call(
                "create, css refused",
                "create_theme",
                ada,
                name="X",
                hue=1,
                chroma=1,
                custom_css="@import url(x)",
            )
            call(
                "create, animation refused",
                "create_theme",
                ada,
                name="X",
                hue=1,
                chroma=1,
                animation_code="fetch('/api')",
            )
            owui.set_tool_valves(TOOL, iframe_height=600, iframe_scale=0.8) if hasattr(
                owui, "set_tool_valves"
            ) else None
            # Each token opens its own designer, for the user it was made for only.
            for name, user, scope in (
                ("create, user", ada, "&scope=me"),
                ("create, admin, everyone", admin, ""),
            ):
                page = (
                    owui.client(user)
                    .get(
                        f"/api/v1/theme-designer?apply={tokens[name]}{scope}",
                        headers={"accept": "text/html", "sec-fetch-dest": "iframe"},
                    )
                    .text
                )
                cfg = json.loads(
                    re.search(r"window.__THEME_PRO_CONFIG__=(\{.*?\});window", page)
                    .group(1)
                    .replace("\\u003c", "<")
                )
                out[f"applyOnLoad from {name}"] = cfg["applyOnLoad"]
                other = ada if user is admin else admin
                r = owui.client(other).get(
                    f"/api/v1/theme-designer?apply={tokens[name]}{scope}",
                    headers={"accept": "text/html", "sec-fetch-dest": "iframe"},
                )
                m = re.search(r"window.__THEME_PRO_CONFIG__=(\{.*?\});window", r.text)
                out[f"applyOnLoad from {name}, someone else"] = (
                    json.loads(m.group(1).replace("\\u003c", "<"))["applyOnLoad"]
                    if m
                    else r.status_code
                )
            # On purpose: the adaptation also installs the theme-designer-pro skill (README).
            out["x: skills"] = (
                sorted(
                    (k, getattr(v, "access_grants", None) is not None)
                    for k, v in owui.skills.items()
                )
                if isinstance(owui.skills, dict)
                else str(owui.skills)
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


up, ours = run("upstream"), run("ours")
for name in sorted(set(up) | set(ours)):
    a, b = up.get(name), ours.get(name)
    if a == b:
        print("same ", name)
    else:
        print("DIFF ", name)
        print("   upstream:", str(a)[:300])
        print("   ours:    ", str(b)[:300])
