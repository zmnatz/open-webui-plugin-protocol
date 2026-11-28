"""The pinned Open-WebUI's own code, for the test harness (ADR 0004).

The pure-Python wheel is downloaded once, checked against the pinned sha256 and unpacked into
owpp's cache. The harness puts the folder on `sys.path`: the wheel is never installed, so its full
dependency list (torch, CUDA, chromadb) is never resolved. The `test` extra installs the packages
of upstream's slim image instead.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from . import pin


def cache_dir() -> Path:
    """`OWPP_CACHE_DIR`, else `$XDG_CACHE_HOME/owpp`, else `~/.cache/owpp`."""
    own = os.environ.get("OWPP_CACHE_DIR")
    if own:
        return Path(own).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg).expanduser() if xdg else Path.home() / ".cache") / "owpp"


def open_webui_dir() -> Path:
    """The folder that holds the pinned `open_webui` package, unpacked from its wheel. The first
    call downloads it."""
    folder = cache_dir() / f"open-webui-{pin.VERSION}"
    if _ready(folder):
        return folder
    folder.parent.mkdir(parents=True, exist_ok=True)
    # One download for every process that starts at once (pytest -n auto): the others wait.
    with _locked(folder.parent / f".open-webui-{pin.VERSION}.lock"):
        if not _ready(folder):
            _download(folder)
    return folder


def _ready(folder: Path) -> bool:
    return (folder / "open_webui").is_dir() and (folder / ".sha256").is_file()


@contextlib.contextmanager
def _locked(path: Path):
    """An exclusive lock on `path`, held until the block ends (fcntl, or msvcrt on Windows)."""
    with path.open("a+") as handle:
        try:
            import fcntl
        except ImportError:  # Windows
            import msvcrt

            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:  # LK_LOCK gives up after ten tries: try again
                    continue
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _download(folder: Path) -> None:
    with tempfile.TemporaryDirectory(dir=folder.parent, prefix=".open-webui-") as tmp:
        wheel = Path(tmp) / "open_webui.whl"
        print(f"owpp: downloading Open-WebUI v{pin.VERSION} for the tests (once)", file=sys.stderr)
        digest = hashlib.sha256()
        with urllib.request.urlopen(pin.WHEEL_URL, timeout=300) as response, wheel.open("wb") as f:
            while chunk := response.read(1 << 20):
                digest.update(chunk)
                f.write(chunk)
        if digest.hexdigest() != pin.WHEEL_SHA256:
            raise RuntimeError(
                f"the Open-WebUI v{pin.VERSION} wheel from {pin.WHEEL_URL} has sha256 "
                f"{digest.hexdigest()}, not the pinned {pin.WHEEL_SHA256}"
            )
        unpacked = Path(tmp) / "unpacked"
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(unpacked)
        (unpacked / ".sha256").write_text(pin.WHEEL_SHA256 + "\n")
        shutil.rmtree(folder, ignore_errors=True)
        unpacked.rename(folder)
