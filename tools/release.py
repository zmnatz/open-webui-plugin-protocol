"""Prepare a release or hotfix branch: the version, the changelog and the docs' version pins.

    python tools/release.py prepare minor            # or patch, major, or 0.5.0
    python tools/release.py prepare patch --hotfix   # on a hotfix branch cut from main

Sets `__version__` in `src/owpp/__init__.py`, turns `## Unreleased` in CHANGELOG.md into
`## <version> (<date>)`, and moves every pin of the old version in the docs (`owpp@`, `owpp==`,
the action's `@v`, the README's status line) to the new one. Prints the new version.

A release needs an `## Unreleased` section with entries. A hotfix starts from main, which has
none, so `--hotfix` adds an empty dated section for the fix's entries instead; until they are
written, `tools/release_notes.py` (and with it CI on the pull request into main) fails.

`.github/workflows/release.yml` runs this, so a release is started from the Actions tab; see
docs/contributing.md#releasing.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = Path("src/owpp/__init__.py")
CHANGELOG = Path("CHANGELOG.md")
# Where the docs pin a version for readers to copy. docs/adr/ is history, so it keeps its versions.
PINNED = ["README.md", "docs/**/*.md", "skills/**/*.md"]
UNPINNED = ["docs/adr/"]


def package_version(root: Path) -> str:
    return re.search(r'^__version__ = "([^"]+)"', (root / INIT).read_text(), re.M).group(1)


def next_version(current: str, how: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", how):
        new = how
    elif how in ("patch", "minor", "major"):
        major, minor, patch = (int(n) for n in current.split("."))
        new = {
            "patch": f"{major}.{minor}.{patch + 1}",
            "minor": f"{major}.{minor + 1}.0",
            "major": f"{major + 1}.0.0",
        }[how]
    else:
        raise SystemExit(f"{how!r}: give patch, minor, major or a version such as 1.2.3")
    if tuple(map(int, new.split("."))) <= tuple(map(int, current.split("."))):
        raise SystemExit(f"{new} is not after the current version, {current}")
    return new


def date_changelog(text: str, version: str, date: str, hotfix: bool) -> str:
    if re.search(rf"^## {re.escape(version)} ", text, re.M):
        raise SystemExit(f"CHANGELOG.md already has a section for {version}")
    heading = f"## {version} ({date})"
    m = re.search(r"^## Unreleased[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if m:
        if not m.group(1).strip() and not hotfix:
            raise SystemExit("CHANGELOG.md's `## Unreleased` section is empty: nothing to release")
        return text[: m.start()] + heading + text[m.start() + len("## Unreleased") :]
    if not hotfix:
        raise SystemExit("CHANGELOG.md has no `## Unreleased` section: nothing to release")
    first = re.search(r"^## ", text, re.M)
    at = first.start() if first else len(text)
    return text[:at] + heading + "\n\n" + text[at:]


def move_pins(text: str, old: str, new: str) -> str:
    v = re.escape(old)
    end = r"(?![0-9])"
    text = re.sub(rf"(owpp(?:\[[a-z,]+\])?(?:@|==)){v}{end}", rf"\g<1>{new}", text)
    text = re.sub(rf"(open-webui-plugin-protocol@v){v}{end}", rf"\g<1>{new}", text)
    return re.sub(rf"^{v}(, written against)", rf"{new}\g<1>", text, flags=re.M)


def pinned_files(root: Path) -> list[Path]:
    files = {p for pattern in PINNED for p in root.glob(pattern)}
    return sorted(
        p for p in files if not any(p.relative_to(root).as_posix().startswith(u) for u in UNPINNED)
    )


def prepare(root: Path, how: str, date: str, hotfix: bool = False) -> str:
    old = package_version(root)
    new = next_version(old, how)
    changelog = root / CHANGELOG
    changelog.write_text(date_changelog(changelog.read_text(), new, date, hotfix))
    init = root / INIT
    init.write_text(init.read_text().replace(f'__version__ = "{old}"', f'__version__ = "{new}"'))
    for path in pinned_files(root):
        text = path.read_text()
        moved = move_pins(text, old, new)
        if moved != text:
            path.write_text(moved)
    return new


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="release.py")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare", help="bump the version, date the changelog, move the pins")
    p.add_argument("version", help="patch, minor, major, or the new version")
    p.add_argument("--hotfix", action="store_true", help="add a dated changelog section if none")
    p.add_argument("--date", default=datetime.date.today().isoformat(), help="default: today")
    args = parser.parse_args(argv)
    print(prepare(ROOT, args.version, args.date, args.hotfix))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
