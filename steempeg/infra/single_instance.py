"""Single-instance lock for Steempeg (Windows-friendly QLockFile)."""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import QLockFile

from steempeg.infra.paths import get_save_directory

_log = logging.getLogger(__name__)

_LOCK_NAME = "steempeg_instance.lock"
# If a previous process crashed, treat the lock as stale after this many ms.
_STALE_LOCK_MS = 30_000


def instance_lock_path() -> str:
    return os.path.join(get_save_directory(), _LOCK_NAME)


def try_acquire_instance_lock() -> tuple[QLockFile, bool]:
    """Try to become the primary Steempeg instance.

    Returns ``(lock, acquired)``. Keep ``lock`` alive for the whole process
    lifetime when ``acquired`` is True; otherwise discard it (or never lock).
    """
    path = instance_lock_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    except OSError as exc:
        _log.debug("Could not create lock dir: %s", exc)

    lock = QLockFile(path)
    lock.setStaleLockTime(_STALE_LOCK_MS)
    if lock.tryLock(100):
        _log.info("Single-instance lock acquired: %s", path)
        return lock, True

    # Stale lock from a crashed run — remove and retry once.
    if lock.error() == QLockFile.LockError.LockFailedError:
        if lock.removeStaleLockFile():
            if lock.tryLock(100):
                _log.info("Single-instance lock acquired after stale cleanup: %s", path)
                return lock, True

    _log.info("Single-instance lock busy: %s", path)
    return lock, False
