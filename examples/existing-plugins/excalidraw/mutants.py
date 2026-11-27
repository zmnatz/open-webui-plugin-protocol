"""Plant one bug at a time in Excalidraw and see which tests catch it
(docs/testing/existing-plugins.md).

    owpp live --up                          # in this folder; then export what it prints
    uv run python mutants.py [names...]     # all of them, or some

plugins/excalidraw takes the example whole from git, so the bugs go into a local copy of
examples/plugins/excalidraw, in mutants/ here, with this folder's tests beside it. For each bug:
change one file, run the unit tests, `owpp deploy` it to the running Open-WebUI, restart
Open-WebUI, run the live tests. The results go to mutants.json here. The original is deployed
again at the end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
OWPP = str(HERE.parents[2])  # this repository: `owpp` and pytest from its environment
URL = os.environ.get("OWPP_LIVE_URL", "http://127.0.0.1:3000")

# name: (what a developer might plausibly get wrong, file, old text, new text)
MUTANTS = {
    "show-replaces": (
        "show with elements replaces the drawing instead of adding to it",
        "tool.py",
        "_merge(current, incoming) if incoming else",
        "incoming if incoming else",
    ),
    "merge-without-ids": (
        "elements the model sends without an id are kept without one",
        "shared.py",
        '    incoming = _with_ids(incoming)\n    by_id = {e["id"]: e for e in incoming}',
        '    by_id = {e.get("id"): e for e in incoming}',
    ),
    "delete-keeps-labels": (
        "deleting a shape leaves its bound text behind",
        "tool.py",
        'e.get("id") not in drop and e.get("containerId") not in drop',
        'e.get("id") not in drop',
    ),
    "read-without-labels": (
        "read does not fold bound text into the shape's label",
        "shared.py",
        '        label = labels.get(e.get("id")) or (',
        "        label = (",
    ),
    "as-list-no-json": (
        "elements sent as JSON text are not parsed",
        "shared.py",
        "    if isinstance(elements, str):\n        elements = json.loads(elements)\n",
        "",
    ),
    "chat-id-unchecked": (
        "the tool accepts any chat id, ../etc included",
        "tool.py",
        "    if not chat_id or not _ID.fullmatch(chat_id):",
        "    if not chat_id:",
    ),
    "no-element-doc": (
        "the element format is no longer in the tool's description",
        "tool.py",
        '    _fn.__doc__ = _head.rstrip() + "\\n\\n" + ELEMENT_DOC + "\\n\\n        " + _sep + _params',
        "    pass",
    ),
    "editor-every-reply": (
        "the editor is added to every reply, not once per chat",
        "function.py",
        "            if html not in shown and html not in blocks:",
        "            if html not in blocks:",
    ),
    "content-only": (
        "the editor is added to the reply's text but not its output",
        "function.py",
        "        if output:\n            output.append(",
        "        if False:\n            output.append(",
    ),
    "strict-tool-result": (
        "a tool result with context after it is not recognised",
        "function.py",
        "        return json.JSONDecoder().raw_decode(text, start)[0]",
        "        return json.loads(text[start:])",
    ),
    "view-any-user": (
        "any signed-in user can open another's editor",
        "function.py",
        "        async def view(chat_id: WritableChat):",
        "        async def view(chat_id: str):",
    ),
    "token-unbound": (
        "the scene API takes any token, for any chat",
        "function.py",
        "not plugin_check_token(t, chat_id)",
        "not t",
    ),
    "assets-url-unchecked": (
        "any assets_url is used, javascript: included",
        "function.py",
        "    if url and not _ASSETS_URL.fullmatch(url):",
        "    if False:",
    ),
    "token-hours-ignored": (
        "the SESSION_TOKEN_HOURS valve is ignored (always 1 hour)",
        "function.py",
        "plugin_token(chat_id, valves.SESSION_TOKEN_HOURS)",
        "plugin_token(chat_id, 1)",
    ),
    "save-without-client": (
        "the editor saves without saying which editor it is",
        "templates/viewer.html",
        "body: JSON.stringify({ client: me, elements }),",
        "body: JSON.stringify({ elements }),",
    ),
    "poll-once": (
        "the editor polls once and stops",
        "templates/viewer.html",
        "  recover();\n  setTimeout(poll, 1500);\n",
        "  recover();\n",
    ),
    "own-writes-reapplied": (
        "the editor reapplies its own saves",
        "templates/viewer.html",
        "        if (d.writer !== me) {",
        "        if (true) {",
    ),
    "poll-while-drawing": (
        "the editor applies remote changes while the user is mid-stroke",
        "templates/viewer.html",
        "    if (api && !pointerDown && timer === null) {",
        "    if (api) {",
    ),
}


def mutate(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"{old!r} is in the code {text.count(old)} times"
    return text.replace(old, new)


def failed(junit: Path) -> list[str]:
    names = set()
    for case in ET.parse(junit).iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            names.add(case.get("name").split("[")[0])
    return sorted(names)


def wait_healthy(seconds: int = 300) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(URL + "/health", timeout=5) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit("Open-WebUI did not come back")


def deploy(repo: Path, env: dict) -> None:
    out = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            OWPP,
            "owpp",
            "deploy",
            "--dir",
            "plugins",
            "--only",
            "excalidraw",
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    subprocess.run(["docker", "restart", "owpp-live-open-webui-1"], check=True, capture_output=True)
    wait_healthy()
    time.sleep(3)


def local_copy() -> Path:
    """mutants/plugins/excalidraw: the example's code, with this folder's tests."""
    import shutil

    repo = HERE / "mutants"
    plugin = repo / "plugins" / "excalidraw"
    shutil.rmtree(plugin, ignore_errors=True)
    shutil.copytree(
        Path(OWPP) / "examples" / "plugins" / "excalidraw",
        plugin,
        ignore=shutil.ignore_patterns("tests", "__pycache__"),
    )
    shutil.copytree(HERE / "plugins" / "excalidraw" / "tests", plugin / "tests")
    return repo


def main(names: list[str]) -> None:
    admin = json.loads(os.environ["OWPP_LIVE_ADMIN"])
    env = dict(os.environ) | {"OPEN_WEBUI_URL": URL, "OPEN_WEBUI_API_KEY": admin["token"]}
    repo = local_copy()
    plugin = repo / "plugins" / "excalidraw"
    results_file = HERE / "mutants.json"
    results = json.loads(results_file.read_text()) if results_file.exists() else {}
    originals = {f: (plugin / f).read_text() for f in {m[1] for m in MUTANTS.values()}}
    try:
        for name in names or list(MUTANTS):
            what, file, old, new = MUTANTS[name]
            (plugin / file).write_text(mutate(originals[file], old, new))
            unit = subprocess.run(
                [
                    "uv",
                    "run",
                    "--project",
                    OWPP,
                    "owpp",
                    "test",
                    "excalidraw",
                    "--",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    f"--junitxml={repo / 'unit.xml'}",
                ],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
            deploy(repo, env)
            live = subprocess.run(
                [
                    "uv",
                    "run",
                    "--project",
                    OWPP,
                    "pytest",
                    "live",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    f"--junitxml={repo / 'live.xml'}",
                ],
                cwd=HERE,
                env=env,
                capture_output=True,
                text=True,
            )
            results[name] = {
                "what": what,
                "unit": failed(repo / "unit.xml"),
                "live": failed(repo / "live.xml"),
                "unit_summary": unit.stdout.strip().splitlines()[-1],
                "live_summary": live.stdout.strip().splitlines()[-1],
            }
            (plugin / file).write_text(originals[file])
            print(
                name, "| unit:", results[name]["unit"], "| live:", results[name]["live"], flush=True
            )
            results_file.write_text(json.dumps(results, indent=2))
    finally:
        for file, text in originals.items():
            (plugin / file).write_text(text)
        deploy(repo, env)
        print("original put back", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
