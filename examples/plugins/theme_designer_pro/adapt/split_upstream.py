"""Split upstream Theme Designer Pro's string literals into this plugin's templates/.

usage, from the repository root, with a checkout of silentoplayz/theme-designer-pro-presets at
the commit to adapt:

    python -I examples/plugins/theme_designer_pro/adapt/split_upstream.py <upstream checkout> examples/plugins/theme_designer_pro

It rewrites templates/ from the upstream files; function.py and tool.py are ported by hand
(see the README's "Moving to a newer upstream release"). Run on the pinned commit, it writes
templates/ exactly as committed: `git status` shows nothing.
"""

import ast
import re
import sys
from pathlib import Path

upstream, out = Path(sys.argv[1]), Path(sys.argv[2])
event_py = upstream / "event-function/theme_designer_pro_event.py"
launcher_py = upstream / "launcher/theme_designer_pro_launcher.py"
T = out / "templates"
if T.exists():
    import shutil

    shutil.rmtree(T)


def strings(path):
    tree = ast.parse(path.read_text())
    found = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[ast.unparse(node.targets[0])] = node.value.value
    return found


def write(rel, text):
    p = T / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


ev = strings(event_py)
la = strings(launcher_py)

# The bootloader as Event._bootloader_body() makes it: the HTML wrapper the old
# index.html injection needed, removed.
body = re.sub(
    r"^\s*<!--.*?-->\s*<script[^>]*>\s*|\s*</script>\s*$",
    "",
    ev["BOOTLOADER_SCRIPT"].strip(),
    flags=re.DOTALL,
)
write("bootloader.js", body + "\n")
write("settings_tab.js", ev["ADMIN_TAB_SCRIPT"].strip() + "\n")
write("admin_page.js", ev["ADMIN_PAGE_SCRIPT"].strip() + "\n")
write("designer/personal.html", ev["PERSONAL_DESIGNER_BLOCK"])  # used as it is, leading newline too
write("launcher/card.html", la["CARD_HTML"] + "\n")

# The designer page: one 943 KB string, cut at its own section boundaries.
lines = ev["html_content"].split("\n")
assert lines[-1].endswith("</html>"), lines[-1]


def take(a, b):  # 1-based, inclusive
    return "\n".join(lines[a - 1 : b]) + "\n"


def start(pattern, after=1):
    for i in range(after - 1, len(lines)):
        if re.search(pattern, lines[i]):
            return i + 1
    raise SystemExit(f"not found: {pattern}")


css0 = start(r"^    <style>$")
css1 = start(r"^    </style>$", css0)
skin0 = start(r'^    <style id="owui-skin">$')
skin1 = start(r"^    </style>$", skin0)
tabs = ["lch", "custom", "canvas", "bg", "surfaces", "backgrounds", "themes"]
tab_at = {t: start(rf'^        <div id="tab-{t}" class="tab-content"') for t in tabs}
docs0 = start(r'^        <div id="tab-docs" ')
content_end = start(r"^    </div>$", docs0)  # closes .content-area
docs1 = content_end - 1
script0 = start(r"^<script>$", start(r'id="bootloader-src"'))
script1 = len(lines) - 3  # last JS line; then "</script>", "</body>", "</html>"
assert lines[script1] == "</script>", lines[script1]

order = sorted(tab_at.items(), key=lambda kv: kv[1])
assert order[-1][1] < docs0

# The app script's sections, by their own "// --- Name ---" headers.
SECTIONS = [
    ("01-core.js", None),
    ("02-storage-and-saves.js", "// --- Storage ---"),
    ("03-modes.js", "// --- Mode data ---"),
    ("04-ai-consultant.js", "// --- AI Consultant ---"),
    ("05-animation-settings.js", "// ---- Animation settings ----"),
    ("06-gradient-css.js", "// === Gradient CSS Helpers ==="),
    ("07-line-numbers.js", "// --- Line Number Gutter Engine ---"),
    ("08-gradient-builder.js", "// === GRADIENT BUILDER LOGIC ==="),
    ("09-surfaces.js", "// === SURFACES TAB ==="),
    ("10-selective-sync.js", "// --- Selective Sync ---"),
    ("11-import-export.js", "// --- Mass Import/Export Portability ---"),
    ("12-backgrounds.js", "// --- Open WebUI's own backgrounds ---"),
    ("13-theme-updates.js", "// --- Theme Update System ---"),
    ("14-community-themes.js", "// --- Community Themes Browser ---"),
    ("15-update-diffs.js", "// --- Ignored Updates ---"),
    ("16-snapshots-and-presets.js", "// --- Snapshot System ---"),
]
cuts = []
for name, header in SECTIONS:
    if header is None:
        cuts.append((name, script0 + 1))
    else:
        cuts.append((name, start("^    " + re.escape(header) + "$", script0)))
assert [c[1] for c in cuts] == sorted(c[1] for c in cuts)

page = []
page.append(take(1, css0))
write("designer/styles/designer.css", take(css0 + 1, css1 - 1))
page.append("<!--#include styles/designer.css-->\n")
page.append(take(css1, skin0))
write("designer/styles/skin.css", take(skin0 + 1, skin1 - 1))
page.append("<!--#include styles/skin.css-->\n")
page.append(take(skin1, order[0][1] - 1))
for i, (tab, at) in enumerate(order):
    end = order[i + 1][1] - 1 if i + 1 < len(order) else docs0 - 1
    write(f"designer/tabs/{tab}.html", take(at, end))
    page.append(f"<!--#include tabs/{tab}.html-->\n")
write("designer/docs.html", take(docs0, docs1))
page.append("<!--#include docs.html-->\n")
page.append(take(content_end, script0))
for i, (name, at) in enumerate(cuts):
    end = cuts[i + 1][1] - 1 if i + 1 < len(cuts) else script1
    write(f"designer/scripts/{name}", take(at, end))
    page.append(f"<!--#include scripts/{name}-->\n")
page.append(take(script1 + 1, len(lines)))
page = "".join(page)

# The markup _build_html built in Python never depends on the valves: run that code once and
# keep what it made as files, included where its placeholder was.
build = next(
    n
    for n in ast.walk(ast.parse(event_py.read_text()))
    if isinstance(n, ast.FunctionDef) and n.name == "_build_html"
)
NAMES = {
    "metadata_grid",
    "shared_meta_fields",
    "save_meta",
    "rename_meta",
    "sync_options",
    "sync_html",
    "json_modal",
    "css_modal",
    "json_modals",
}
code = [
    s
    for s in build.body
    if (isinstance(s, ast.FunctionDef) and s.name in NAMES)
    or (isinstance(s, ast.Assign) and ast.unparse(s.targets[0]) in NAMES)
]
made = {}
exec(compile(ast.Module(body=code, type_ignores=[]), "_build_html", "exec"), made)
for placeholder, name, var in [
    ("{SAVE_METADATA_GRID}", "save-metadata.html", "save_meta"),
    ("{RENAME_METADATA_GRID}", "rename-metadata.html", "rename_meta"),
    ("{SYNC_OPTIONS}", "sync-options.html", "sync_html"),
    ("{JSON_EDITOR_MODALS}", "json-editor-modals.html", "json_modals"),
]:
    assert page.count(placeholder) == 1, placeholder
    write(f"designer/parts/{name}", made[var] + "\n")
    page = page.replace(placeholder, f"<!--#include parts/{name}-->")
write("designer/page.html", page)

# The consultant's prompt, as the text it is.
write("consult_prompt.txt", ev["CONSULT_PROMPT"] + "\n")

# The notice page (_notice_page), one line as the original builds it, with placeholders.
notice = next(
    n
    for n in ast.walk(ast.parse(event_py.read_text()))
    if isinstance(n, ast.FunctionDef) and n.name == "_notice_page"
)
joined = next(n for n in ast.walk(notice) if isinstance(n, ast.JoinedStr))
text = "".join(
    v.value
    if isinstance(v, ast.Constant)
    else "__TITLE__"
    if "title" in ast.unparse(v)
    else "__DETAIL__"
    for v in joined.values
)
write("notice.html", text + "\n")

# The Launcher's designer frame: its f-string, with __NAME__ placeholders for its fields.
launcher = launcher_py.read_text()
a = launcher.index('        content = f"""') + len('        content = f"""')
frame = launcher[a : launcher.index('"""', a)]
fields = {
    "h": "HEIGHT",
    "inner_w_pct": "INNER_WIDTH",
    "inner_h": "INNER_HEIGHT",
    "scale": "SCALE",
    "popout_url": "POPOUT_URL",
    "frame_url": "FRAME_URL",
}
frame = re.sub(r"(?<!\{)\{([a-z_]+)\}(?!\})", lambda m: "__" + fields[m[1]] + "__", frame)
write("launcher/embed.html", frame.replace("{{", "{").replace("}}", "}") + "\n")

for name, at in [("css", css0), ("skin", skin0), ("docs", docs0), ("script", script0)]:
    print(f"{name:8} line {at}")
for tab, at in order:
    print(f"tab {tab:12} line {at}")
for name, at in cuts:
    print(f"{name:32} line {at}")
