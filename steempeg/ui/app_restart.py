"""Restart the running Steempeg process (Settings → Restart app)."""
from __future__ import annotations

import logging
import sys

_log = logging.getLogger(__name__)


def restart_application(app_obj=None) -> None:
    """Spawn a fresh process, release the single-instance lock, then quit.

    Must unlock before ``startDetached`` or the new instance hits Already Running.
    """
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication

    lock = getattr(app_obj, "_instance_lock", None) if app_obj is not None else None
    if lock is not None:
        try:
            lock.unlock()
        except Exception as exc:
            _log.debug("Could not unlock instance lock before restart: %s", exc)
        try:
            delattr(app_obj, "_instance_lock")
        except Exception:
            pass

    exe = sys.executable
    argv = list(sys.argv)
    if getattr(sys, "frozen", False):
        # Frozen: argv[0] is the exe; only pass trailing args.
        ok = QProcess.startDetached(exe, argv[1:])
    else:
        ok = QProcess.startDetached(exe, argv)
    if not ok:
        _log.error("QProcess.startDetached failed for restart (%s %s)", exe, argv)
        return

    qapp = QApplication.instance()
    if qapp is not None:
        qapp.quit()
    else:
        raise SystemExit(0)
