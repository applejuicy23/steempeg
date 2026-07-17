"""Cross-platform process helpers (no Qt)."""
from __future__ import annotations

import logging
import os
import subprocess
import sys

_log = logging.getLogger(__name__)


def kill_process_tree(proc_or_pid, *, label: str = "process") -> None:
    """Force-kill a process and its children.

    Accepts a ``subprocess.Popen``, a ``psutil.Process``, or an int PID.
    """
    if proc_or_pid is None:
        return

    pid = getattr(proc_or_pid, "pid", proc_or_pid)
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return

    try:
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=flags,
                capture_output=True,
                timeout=5,
                check=False,
            )
            return

        # Prefer psutil when available (covers children on Linux).
        try:
            import psutil

            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except Exception:
                    pass
            try:
                parent.kill()
            except Exception:
                pass
            return
        except Exception:
            pass

        # Fallback: signal the leaf process only.
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        except Exception as exc:
            _log.debug("Could not kill %s pid=%s: %s", label, pid, exc)
    except Exception as exc:
        _log.debug("kill_process_tree(%s) failed: %s", label, exc)
        try:
            if hasattr(proc_or_pid, "kill"):
                proc_or_pid.kill()
        except Exception:
            pass
