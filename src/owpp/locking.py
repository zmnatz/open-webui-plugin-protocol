"""A lock between processes, held on a file."""

from __future__ import annotations

import contextlib
from pathlib import Path


@contextlib.contextmanager
def locked(path: Path):
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
