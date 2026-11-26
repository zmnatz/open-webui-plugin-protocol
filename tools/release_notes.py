"""The GitHub release notes for a version tag, from CHANGELOG.md.

    python tools/release_notes.py v0.3.0 > notes.md

Prints the entries of the `## <version> (<date>)` section, with links made absolute so they work
on the release page (relative to the repository at that tag). Fails, so the release is not made,
when the tag is not `v<version>` for the package's `__version__` (owpp's, and owpp-live's,
released with it at the same version), or the changelog has no dated
section for it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/zmnatz/open-webui-plugin-protocol"


def package_version(root: Path = ROOT) -> str:
    text = (root / "src" / "owpp" / "__init__.py").read_text()
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


def live_version(root: Path = ROOT) -> str | None:
    """owpp-live's version, released together with owpp (packages/owpp-live)."""
    init = root / "packages" / "owpp-live" / "src" / "owpp_live" / "__init__.py"
    if not init.is_file():
        return None
    return re.search(r'^__version__ = "([^"]+)"', init.read_text(), re.M).group(1)


def notes(tag: str, changelog: str, version: str) -> str:
    if tag != f"v{version}":
        raise SystemExit(f"tag {tag} is not v{version}, the package's version")
    m = re.search(
        rf"^## {re.escape(version)} \(\d{{4}}-\d{{2}}-\d{{2}}\)\n(.*?)(?=^## |\Z)",
        changelog,
        re.M | re.S,
    )
    if not m or not m.group(1).strip():
        raise SystemExit(f"CHANGELOG.md has no dated `## {version} (YYYY-MM-DD)` section")

    def absolute(link: re.Match) -> str:
        target = link.group(2)
        if re.match(r"[a-z]+:|#", target):
            return link.group(0)
        return f"{link.group(1)}{REPO}/blob/{tag}/{target}{link.group(3)}"

    return re.sub(r"(\]\()([^)\s]+)(\))", absolute, m.group(1).strip()) + "\n"


def main(argv: list[str], root: Path = ROOT) -> int:
    if len(argv) != 1:
        raise SystemExit("usage: release_notes.py <tag>")
    version, live = package_version(root), live_version(root)
    if live is not None and live != version:
        raise SystemExit(f"owpp-live is at {live}, owpp at {version}: they release together")
    sys.stdout.write(notes(argv[0], (root / "CHANGELOG.md").read_text(), version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
