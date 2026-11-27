"""Plant one bug at a time in Better Banners and see which tests catch it
(docs/testing/existing-plugins.md).

    owpp live --up                          # in this folder; then export what it prints
    uv run python mutants.py [names...]     # all of them, or some

For each bug: the unit tests with the changed code loaded (BB_MUTANT, read by
tests/conftest.py), then the changed code put on the running Open-WebUI through its API, the
container restarted, and the live tests run. The results go to mutants.json here. The original
is put back at the end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OWPP = str(HERE.parents[2])  # this repository: `owpp` and pytest from its environment
URL = os.environ.get("OWPP_LIVE_URL", "http://127.0.0.1:3000")
# The upstream file, at the commit plugins/better_banners/plugin.yaml pins.
UPSTREAM = (
    "https://raw.githubusercontent.com/Classic298/open-webui-plugins/"
    "917c88f3029c0c6500139ba7b7b061f358d8aaea/better-banners/event.py"
)

# name: (what a developer might plausibly get wrong, old text, new text)
MUTANTS = {
    "dismiss-key": (
        "dismissals stored under its own key, not Open-WebUI's",
        "var DISMISSED_KEY = 'dismissedBannerIds';",
        "var DISMISSED_KEY = 'owui-better-banners:dismissed';",
    ),
    "bottom-ignored": (
        "position: bottom ignored, always at the top",
        "    if (CFG.position === 'top') {\n      // In the page flow",
        "    if (true) {\n      // In the page flow",
    ),
    "event-typo": (
        "a typo in the banners-updated event name: no live push",
        'BANNERS_UPDATED_EVENT = "config.banners.updated"',
        'BANNERS_UPDATED_EVENT = "config.banner.updated"',
    ),
    "frame-prefix": (
        "the socket frame matched wrongly in the page: no live update",
        "var FRAME = '42[\"' + CFG.event + '\"';",
        "var FRAME = '42[' + CFG.event;",
    ),
    "javascript-links": (
        "javascript: URLs accepted as safe links",
        r"return /^(https?:\/\/|mailto:|\/(?!\/))/i.test(url);",
        r"return /^(https?:\/\/|mailto:|javascript:|\/(?!\/))/i.test(url);",
    ),
    "event-attributes": (
        "the HTML sanitizer keeps onclick/onmouseover",
        "['title', 'class', 'colspan',",
        "['title', 'class', 'onclick', 'onmouseover', 'colspan',",
    ),
    "title-as-html": (
        "the banner title set as HTML, not text",
        "heading.textContent = title;",
        "heading.innerHTML = title;",
    ),
    "collapse-forgotten": (
        "collapsing not saved, so it is lost on reload",
        "    writeJson(COLLAPSED_KEY, map);\n    lastRenderKey = renderKey(visible, true);",
        "    writeJson(COLLAPSED_KEY, {});\n    lastRenderKey = renderKey(visible, true);",
    ),
    "all-dismissible": (
        "every banner gets a close button",
        "    if (banner.dismissible) {",
        "    if (true) {",
    ),
    "on-new-chat-screen": (
        "shown on the new-chat screen too, beside Open-WebUI's own",
        "    if (!inChat) return null;\n",
        "",
    ),
    "no-base-language": (
        "de-DE no longer falls back to a de translation",
        "var candidates = base && base !== lang ? [lang, base] : lang ? [lang] : [];",
        "var candidates = lang ? [lang] : [];",
    ),
    "pill-level-order": (
        "the pill takes the lowest level's colour, not the highest",
        "var LEVEL_ORDER = ['success', 'info', 'warning', 'error'];",
        "var LEVEL_ORDER = ['error', 'warning', 'info', 'success'];",
    ),
    "served-when-disabled": (
        "the script still served once the function is disabled",
        'lambda: Event.instance._loader_fragment() if reload_active(app) else "",',
        "lambda: Event.instance._loader_fragment(),",
    ),
    "cache-ignores-position": (
        "the script cache ignores the position valve",
        "        cache_key = (\n            valves.position,\n            valves.max_height_px,",
        "        cache_key = (\n            valves.max_height_px,",
    ),
    "weak-etag": (
        "a proxy's weak W/ ETag never answered 304",
        '.removeprefix("W/") == etag',
        " == etag",
    ),
    "legacy-kept": (
        "1.0.2's fragment not dropped on upgrade",
        '    asset_fragments(app, LOADER_PATH).pop("better-banners", None)\n',
        "",
    ),
}


def mutate(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"{old!r} is in the code {text.count(old)} times"
    return text.replace(old, new)


def failed_tests(junit: Path) -> list[str]:
    """The tests that failed or errored, from pytest's JUnit XML."""
    import xml.etree.ElementTree as ET

    names = set()
    for case in ET.parse(junit).iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            names.add(case.get("name").split("[")[0])
    return sorted(names)


def api(method: str, path: str, token: str, body=None):
    request = urllib.request.Request(
        URL + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read() or b"null")


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


def deploy(token: str, content: str) -> None:
    function = api("GET", "/api/v1/functions/id/better_banners", token)
    form = {k: function[k] for k in ("id", "name", "meta")} | {"content": content}
    api("POST", "/api/v1/functions/id/better_banners/update", token, form)
    subprocess.run(["docker", "restart", "owpp-live-open-webui-1"], check=True, capture_output=True)  # noqa: E501
    wait_healthy()
    assert api("GET", "/api/v1/functions/id/better_banners", token)["content"] == content
    time.sleep(3)


def main(exp: Path, names: list[str]) -> None:
    env = dict(os.environ)
    token = json.loads(env["OWPP_LIVE_ADMIN"])["token"]
    with urllib.request.urlopen(UPSTREAM, timeout=30) as response:
        upstream = response.read().decode()
    deployed = api("GET", "/api/v1/functions/id/better_banners", token)["content"]
    results_file = HERE / "mutants.json"
    results = json.loads(results_file.read_text()) if results_file.exists() else {}
    try:
        for name in names or list(MUTANTS):
            what, old, new = MUTANTS[name]
            mutant = HERE / "mutants" / f"{name}.py"  # git-ignored
            mutant.parent.mkdir(exist_ok=True)
            mutant.write_text(mutate(upstream, old, new))
            mock = subprocess.run(
                [
                    "uv",
                    "run",
                    "--project",
                    OWPP,
                    "owpp",
                    "test",
                    "better_banners",
                    "--",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    f"--junitxml={HERE / 'mutants' / 'mock.xml'}",
                ],
                cwd=exp,
                env=env | {"BB_MUTANT": str(mutant)},
                capture_output=True,
                text=True,
            )
            deploy(token, mutate(deployed, old, new))
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
                    f"--junitxml={HERE / 'mutants' / 'live.xml'}",
                ],
                cwd=exp,
                env=env,
                capture_output=True,
                text=True,
            )
            results[name] = {
                "what": what,
                "mock": failed_tests(HERE / "mutants" / "mock.xml"),
                "live": failed_tests(HERE / "mutants" / "live.xml"),
                "mock_summary": mock.stdout.strip().splitlines()[-1],
                "live_summary": live.stdout.strip().splitlines()[-1],
            }
            print(
                name, "| mock:", results[name]["mock"], "| live:", results[name]["live"], flush=True
            )
            results_file.write_text(json.dumps(results, indent=2))
    finally:
        deploy(token, deployed)
        print("original put back", flush=True)


if __name__ == "__main__":
    main(HERE, sys.argv[1:])
