"""CPU priority for render children, never for the Steempeg GUI process."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time

import psutil

_log = logging.getLogger(__name__)
_WINDOWS_CLASSES = {"normal": 0x20, "above_normal": 0x8000, "high": 0x80}
_NICE_LEVELS = {"normal": 0, "above_normal": -2, "high": -5}


def load_render_priority(app) -> str:
    try:
        value = (app.load_user_settings() or {}).get("render_process_priority", "normal")
    except Exception:
        value = "normal"
    value = str(value or "normal")
    return value if value in _WINDOWS_CLASSES else "normal"


def _rtkit_nice(pid: int, tid: int, value: int) -> None:
    """Ask the desktop's permission broker for ordinary nice, not realtime scheduling."""
    busctl = shutil.which("busctl") if sys.platform == "linux" else None
    if not busctl:
        raise PermissionError("RealtimeKit transport is unavailable")
    result = subprocess.run(
        [busctl, "--system", "--timeout=2", "--allow-interactive-authorization=no",
         "call", "org.freedesktop.RealtimeKit1", "/org/freedesktop/RealtimeKit1",
         "org.freedesktop.RealtimeKit1", "MakeThreadHighPriorityWithPID",
         "tti", str(pid), str(tid), str(value)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True, timeout=3,
    )
    if result.returncode:
        raise PermissionError((result.stderr or "RealtimeKit denied the request").strip()[:300])


def _set_thread_nice(pid: int, tid: int, value: int) -> None:
    try:
        os.setpriority(os.PRIO_PROCESS, tid, value)
    except PermissionError:
        if value >= 0:
            raise
        # CAP_SYS_NICE / RLIMIT_NICE may be absent on desktop distributions.
        # RealtimeKit can authorize the child's thread without elevating the app.
        _rtkit_nice(pid, tid, value)


def _apply_posix_priority(process, priority: str) -> None:
    value = _NICE_LEVELS[priority]
    pid = process.pid
    try:
        tracked = psutil.Process(pid)
        _set_thread_nice(pid, pid, value)
    except (ProcessLookupError, psutil.NoSuchProcess):
        return
    except (OSError, psutil.Error, subprocess.SubprocessError) as exc:
        if process.poll() is not None:
            return
        _log.warning("FFmpeg priority %s unavailable for PID %s: %s; keeping OS priority",
                     priority, pid, exc)
        return
    _log.info("FFmpeg priority: PID=%s requested=%s nice=%s", pid, priority, value)
    if value == 0:
        return

    def follow_threads():
        # Linux nice is per-thread. Decoder/encoder workers may already exist
        # when Popen returns, and RealtimeKit resets nice on newly spawned tasks.
        seen = {pid}
        try:
            while process.poll() is None and tracked.is_running():
                for thread in tracked.threads():
                    if thread.id in seen:
                        continue
                    try:
                        _set_thread_nice(pid, thread.id, value)
                    except ProcessLookupError:
                        continue
                    seen.add(thread.id)
                time.sleep(0.2)
        except psutil.NoSuchProcess:
            pass
        except (OSError, psutil.Error, subprocess.SubprocessError) as exc:
            _log.warning("FFmpeg worker-thread priority limited for PID %s: %s; "
                         "remaining workers keep OS priority", pid, exc)

    threading.Thread(target=follow_threads, name="ffmpeg-priority", daemon=True).start()


def popen_render_command(cmd: str, *, cwd, creation_flags: int, priority: str = "normal", **kwargs):
    priority = str(priority or "normal")
    priority = priority if priority in _WINDOWS_CLASSES else "normal"
    if sys.platform == "win32":
        # Priority class bits are mutually exclusive; preserve unrelated flags.
        priority_mask = 0x20 | 0x40 | 0x80 | 0x100 | 0x4000 | 0x8000
        flags = (creation_flags & ~priority_mask) | _WINDOWS_CLASSES[priority]
        try:
            process = subprocess.Popen(cmd, shell=False, cwd=cwd, creationflags=flags, **kwargs)
        except PermissionError:
            if priority == "normal":
                raise
            _log.warning("FFmpeg priority %s denied at launch; retrying at Normal", priority)
            priority = "normal"
            flags = (creation_flags & ~priority_mask) | _WINDOWS_CLASSES[priority]
            process = subprocess.Popen(cmd, shell=False, cwd=cwd, creationflags=flags, **kwargs)
        _log.info("FFmpeg priority: PID=%s requested=%s class=0x%x",
                  process.pid, priority, _WINDOWS_CLASSES[priority])
        return process
    # exec keeps FFmpeg at the tracked PID rather than prioritizing a shell
    # while its actual renderer remains a separate normal-priority child.
    process = subprocess.Popen(["/bin/sh", "-c", "exec " + cmd], shell=False, cwd=cwd, **kwargs)
    if priority == "normal":
        _apply_posix_priority(process, priority)
    else:
        # A broker request may take seconds. Return the Popen immediately so
        # render cancellation can already terminate the tracked child.
        threading.Thread(target=_apply_posix_priority, args=(process, priority),
                         name="ffmpeg-priority-request", daemon=True).start()
    return process
