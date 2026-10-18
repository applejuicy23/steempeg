"""«Start Steempeg with Windows» — the per-user Run entry.

The installer (installer/steempeg.iss) writes the same value, so the Settings
toggle and the installer checkbox always agree. Only installed / frozen builds
can autostart: a source checkout has no stable exe to point Windows at.
"""
from __future__ import annotations

import logging
import os
import sys

_log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "Steempeg"


def autostart_is_supported() -> bool:
    """True on Windows builds packed into Steempeg.exe (not when running from source)."""
    from steempeg.infra.paths import is_frozen_build

    return sys.platform == "win32" and is_frozen_build()


def build_autostart_command() -> str:
    """Builds the command Windows runs at sign-in: this exe, hidden in the tray."""
    return f'"{os.path.abspath(sys.executable)}" --background'


def read_autostart_enabled() -> bool:
    """Tells whether a Steempeg entry exists in the per-user Run key."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, RUN_VALUE_NAME)
        return bool(str(value or "").strip())
    except OSError:
        return False


def set_autostart_enabled(enabled: bool) -> bool:
    """Adds or removes the Run entry; returns False when Windows refused or it is unsupported."""
    if not autostart_is_supported():
        return False
    try:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, build_autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        _log.info("Autostart %s", "enabled" if enabled else "disabled")
        return True
    except OSError as exc:
        _log.warning("Autostart change failed: %s", exc)
        return False
