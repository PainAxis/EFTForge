"""Cross-process generation marker for item-graph-derived result caches.

Gunicorn workers keep independent in-memory caches.  A successful data sync
therefore publishes a small atomic generation token that every worker can
observe before using its local cache.
"""

import os
import secrets
import tempfile
import time
from collections.abc import Callable

from config import RUNTIME_DIR

CACHE_EPOCH_FILE = os.path.join(RUNTIME_DIR, "solver_cache_epoch")


def read_solver_cache_epoch() -> str:
    try:
        with open(CACHE_EPOCH_FILE, "r", encoding="ascii") as f:
            return f.read(128).strip()
    except OSError:
        return ""


def bump_solver_cache_epoch() -> str:
    """Atomically publish a new generation and return its token."""
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    token = f"{time.time_ns()}:{os.getpid()}:{secrets.token_hex(8)}"
    fd, tmp_path = tempfile.mkstemp(prefix=".solver-cache-epoch-", dir=RUNTIME_DIR)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(token)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CACHE_EPOCH_FILE)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
    return token


class SolverCacheEpochTracker:
    """Per-process view of the shared cache generation."""

    def __init__(self, reader: Callable[[], str] = read_solver_cache_epoch):
        self._reader = reader
        self.value = reader()

    def refresh(self) -> tuple[str, bool]:
        current = self._reader()
        changed = current != self.value
        self.value = current
        return current, changed
