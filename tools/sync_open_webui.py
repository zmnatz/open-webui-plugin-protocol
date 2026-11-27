"""Pin the Open-WebUI that `owpp test` and `owpp live` run (ADR 0004).

    python tools/sync_open_webui.py 0.13.6    # move the pin to v0.13.6
    python tools/sync_open_webui.py           # write the current pin's files again
    python tools/sync_open_webui.py --check   # fail if a file differs from upstream (CI)

From upstream at the tag it takes: the pure-Python wheel's URL and sha256 (PyPI), and from
GitHub `backend/requirements-slim.lock`, the list Open-WebUI builds its slim image from, and the
Python of that image (the Dockerfile's `FROM python:X.Y`), which the lock is compiled for. It
writes:

- src/owpp/testing/pin.py: the version, the wheel and its hash, the image's Python;
- pyproject.toml: `requires-python`, the image's Python (owpp runs on the Python Open-WebUI runs
  on), and the `test` extra, every pin of the slim lock, with the lock's markers and the image's
  Python as markers;
- src/owpp/live/compose.yaml: the `-slim` image tag.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "src" / "owpp" / "testing" / "pin.py"
PYPROJECT = ROOT / "pyproject.toml"
COMPOSE = ROOT / "src" / "owpp" / "live" / "compose.yaml"

GITHUB = "https://raw.githubusercontent.com/open-webui/open-webui/v{version}/"
LOCK_URL = GITHUB + "backend/requirements-slim.lock"
DOCKERFILE_URL = GITHUB + "Dockerfile"
PYPI_URL = "https://pypi.org/pypi/open-webui/{version}/json"

# What owpp test needs on top of Open-WebUI's own packages.
OWN = ['"pytest>=8"', '"pytest-xdist>=3.6"']  # -n auto: each worker starts its own Open-WebUI
BEGIN = "test = [  # tools/sync_open_webui.py writes this list: do not edit it by hand"
END = "]  # end of the test extra"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def current_version() -> str:
    match = re.search(r'^VERSION = "([^"]+)"', PIN.read_text(), re.M)
    if not match:
        sys.exit(f"{PIN}: no VERSION; give the version to pin")
    return match.group(1)


def image_python(dockerfile: str) -> str:
    """The X.Y of the slim image's `FROM python:X.Y-...` line."""
    found = set(re.findall(r"^FROM\s+(?:--\S+\s+)*python:(\d+\.\d+)", dockerfile, re.M))
    if len(found) != 1:
        sys.exit(f"the Dockerfile has no single python base image: {sorted(found)}")
    return found.pop()


def lock_pins(lock: str) -> list[tuple[str, str]]:
    """(requirement, marker) for each package of a pip-compile lock, hashes left out."""
    pins = []
    for line in lock.splitlines():
        if not line or line[0] in " #-":
            continue
        requirement, _, marker = line.rstrip(" \\").partition(";")
        pins.append((requirement.strip(), marker.strip()))
    return pins


def extra(pins: list[tuple[str, str]], python: str) -> str:
    lines = [BEGIN, *(f"  {own}," for own in OWN)]
    for requirement, marker in pins:
        both = f"({marker}) and {python}" if marker else python
        lines.append(f'  "{requirement} ; {both}",')
    lines.append(END)
    return "\n".join(lines)


def full_requirements(requires_dist: list[str]) -> dict[str, str]:
    """{package: version} of the full package's own pins, extras left out."""
    out = {}
    for requirement in requires_dist:
        if "extra ==" in requirement:
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==([^;\s]+)", requirement)
        if match:
            out[match.group(1).lower().replace("_", "-")] = match.group(2)
    return dict(sorted(out.items()))


def pin_module(version: str, wheel: dict, python: str, full: dict[str, str]) -> str:
    pins = "".join(f'    "{name}": "{v}",\n' for name, v in full.items())
    return f'''"""The Open-WebUI that `owpp test` runs. tools/sync_open_webui.py writes this file."""

VERSION = "{version}"
WHEEL_URL = "{wheel["url"]}"
WHEEL_SHA256 = "{wheel["digests"]["sha256"]}"
PYTHON = "{python}"  # the Python of the slim image, which the lock is compiled for

# The full package's own pins, which the harness names when a plugin needs one slim leaves out.
FULL_REQUIREMENTS = {{
{pins}}}
'''


def rendered(version: str) -> dict[Path, str]:
    release = json.loads(fetch(PYPI_URL.format(version=version)))
    wheels = [u for u in release["urls"] if u["filename"].endswith("-py3-none-any.whl")]
    if len(wheels) != 1:
        sys.exit(f"open-webui {version}: expected one py3-none-any wheel on PyPI")
    python = image_python(fetch(DOCKERFILE_URL.format(version=version)).decode())
    lock = fetch(LOCK_URL.format(version=version)).decode()

    pyproject = PYPROJECT.read_text()
    start, end = pyproject.find(BEGIN), pyproject.find(END)
    if start < 0 or end < start:
        sys.exit(f"{PYPROJECT}: no test extra between the markers")
    block = extra(lock_pins(lock), f"python_version == '{python}'")
    pyproject = pyproject[:start] + block + pyproject[end + len(END) :]
    major, minor = python.split(".")
    pyproject = re.sub(
        r'^requires-python = ".*"$',
        f'requires-python = ">={python},<{major}.{int(minor) + 1}"',
        pyproject,
        count=1,
        flags=re.M,
    )

    compose = re.sub(
        r"(ghcr\.io/open-webui/open-webui:v)[^\s-]+(-slim)",
        rf"\g<1>{version}\g<2>",
        COMPOSE.read_text(),
    )
    return {
        PIN: pin_module(
            version, wheels[0], python, full_requirements(release["info"]["requires_dist"])
        ),
        PYPROJECT: pyproject,
        COMPOSE: compose,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", nargs="?", help="the Open-WebUI version (default: the pin)")
    parser.add_argument("--check", action="store_true", help="fail if a file is out of date")
    args = parser.parse_args()
    version = args.version or current_version()
    stale = []
    for path, text in rendered(version).items():
        if (path.read_text() if path.exists() else None) != text:
            stale.append(path.relative_to(ROOT))
            if not args.check:
                path.write_text(text)
    if args.check and stale:
        names = ", ".join(map(str, stale))
        print(
            f"out of date with Open-WebUI v{version}: {names}. Run: python tools/sync_open_webui.py"
        )
        return 1
    print(f"Open-WebUI v{version}: " + ("up to date" if not stale else f"wrote {len(stale)} files"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
