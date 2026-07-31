"""Bring an already-running Steempeg window to the foreground (Windows).

Used by the ``steempeg:`` toast protocol / ``--raise-existing`` so a notification
click restores the app instead of opening a second instance.
"""
from __future__ import annotations

import logging
import os
import sys

_log = logging.getLogger(__name__)

_GW_OWNER = 4
_SW_RESTORE = 9
_SW_SHOW = 5


def _pid_from_instance_lock() -> int | None:
    try:
        from steempeg.infra.single_instance import instance_lock_path

        path = instance_lock_path()
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as fh:
            raw = fh.read(256)
        # QLockFile: first line is the owning PID (UTF-8 decimal).
        line = raw.split(b"\n", 1)[0].strip()
        if line.isdigit():
            return int(line)
    except Exception as exc:
        _log.debug("lock pid read failed: %s", exc)
    return None


def _enum_top_level_hwnds_for_pid(pid: int) -> list[int]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: list[int] = []

    @WNDENUMPROC
    def _cb(hwnd, _lparam):  # type: ignore[misc]
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, _GW_OWNER):
            return True
        proc = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
        if int(proc.value) == int(pid):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(_cb, 0)
    return found


def _hwnd_title(hwnd: int) -> str:
    import ctypes

    user32 = ctypes.windll.user32
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value or ""


def _pick_main_hwnd(hwnds: list[int]) -> int | None:
    if not hwnds:
        return None
    scored: list[tuple[int, int]] = []
    for hwnd in hwnds:
        title = _hwnd_title(hwnd)
        score = 0
        if title.startswith("Steempeg"):
            score += 100
        if title:
            score += min(len(title), 40)
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
                score += min(area // 10000, 50)
        except Exception:
            pass
        scored.append((score, hwnd))
    scored.sort(reverse=True)
    return scored[0][1]


def _force_foreground(hwnd: int) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, _SW_SHOW)

    foreground = user32.GetForegroundWindow()
    if foreground == hwnd:
        user32.BringWindowToTop(hwnd)
        return

    pid_fore = wintypes.DWORD()
    tid_fore = user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid_fore))
    tid_target = user32.GetWindowThreadProcessId(hwnd, None)
    tid_cur = kernel32.GetCurrentThreadId()

    attached_fore = False
    attached_target = False
    try:
        if tid_fore and tid_fore != tid_cur:
            attached_fore = bool(user32.AttachThreadInput(tid_cur, tid_fore, True))
        if tid_target and tid_target != tid_cur:
            attached_target = bool(user32.AttachThreadInput(tid_cur, tid_target, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        try:
            user32.SetFocus(hwnd)
        except Exception:
            pass
    finally:
        if attached_target:
            user32.AttachThreadInput(tid_cur, tid_target, False)
        if attached_fore:
            user32.AttachThreadInput(tid_cur, tid_fore, False)


def raise_steempeg_window() -> bool:
    """Restore + focus the running Steempeg main window. No Qt required."""
    if sys.platform != "win32":
        return False
    try:
        pid = _pid_from_instance_lock()
        hwnds: list[int] = []
        if pid:
            hwnds = _enum_top_level_hwnds_for_pid(pid)
        if not hwnds:
            # Fallback: any visible top-level titled Steempeg…
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            WNDENUMPROC = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )
            titled: list[int] = []

            @WNDENUMPROC
            def _cb(hwnd, _lparam):  # type: ignore[misc]
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.GetWindow(hwnd, _GW_OWNER):
                    return True
                if _hwnd_title(int(hwnd)).startswith("Steempeg"):
                    titled.append(int(hwnd))
                return True

            user32.EnumWindows(_cb, 0)
            hwnds = titled

        hwnd = _pick_main_hwnd(hwnds)
        if not hwnd:
            _log.info("raise_steempeg_window: no window found")
            return False
        _force_foreground(hwnd)
        _log.info("raise_steempeg_window: focused hwnd=%s", hwnd)
        return True
    except Exception as exc:
        _log.warning("raise_steempeg_window failed: %s", exc)
        return False


def ensure_toast_protocol_registered() -> None:
    """HKCU URL protocol ``steempeg:`` → ``--raise-existing`` (toast click)."""
    if sys.platform != "win32":
        return
    try:
        import winreg

        if getattr(sys, "frozen", False):
            cmd = f'"{os.path.abspath(sys.executable)}" --raise-existing "%1"'
        else:
            cmd = f'"{os.path.abspath(sys.executable)}" -m steempeg --raise-existing "%1"'

        base = r"Software\Classes\steempeg"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, base) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:Steempeg Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, base + r"\shell\open\command"
        ) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, cmd)
        _log.info("Registered steempeg: protocol → %s", cmd)
    except Exception as exc:
        _log.debug("toast protocol registration failed: %s", exc)


TOAST_PROTOCOL_LAUNCH = "steempeg:focus"
