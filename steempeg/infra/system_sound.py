"""Play the host OS alert / notification sound (no bundled SFX).

Windows uses the shell sound aliases (version-appropriate). Linux / SteamOS
try freedesktop event sounds via canberra or paplay, then Qt's bell.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from enum import Enum

_log = logging.getLogger(__name__)


class SystemSound(Enum):
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"


def play_system_sound(kind: SystemSound | str = SystemSound.SUCCESS) -> None:
    """Fire-and-forget system sound. Never raises to callers."""
    try:
        sound = kind if isinstance(kind, SystemSound) else SystemSound(str(kind))
    except ValueError:
        sound = SystemSound.SUCCESS
    try:
        if sys.platform == "win32":
            _play_windows(sound)
        else:
            _play_linux(sound)
    except Exception as exc:
        _log.debug("system sound failed (%s): %s", sound.value, exc)


def _play_windows(sound: SystemSound) -> None:
    import winsound

    # SND_ALIAS picks the sound the user (or Windows theme) assigned —
    # SystemExclamation / Asterisk / etc. change with Windows version & skin.
    alias = {
        SystemSound.ERROR: "SystemExclamation",
        SystemSound.WARNING: "SystemExclamation",
        SystemSound.SUCCESS: "SystemNotification",
    }.get(sound, "SystemAsterisk")
    flags = winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT
    if not winsound.PlaySound(alias, flags):
        # Fallback MessageBeep if the alias is missing on a stripped install.
        beep = {
            SystemSound.ERROR: winsound.MB_ICONEXCLAMATION,
            SystemSound.WARNING: winsound.MB_ICONEXCLAMATION,
            SystemSound.SUCCESS: winsound.MB_ICONASTERISK,
        }.get(sound, winsound.MB_OK)
        winsound.MessageBeep(beep)


def _play_linux(sound: SystemSound) -> None:
    # Freedesktop event ids — GNOME/KDE/SteamOS themes map these to local files.
    event = {
        SystemSound.ERROR: "dialog-error",
        SystemSound.WARNING: "dialog-warning",
        SystemSound.SUCCESS: "complete",
    }.get(sound, "dialog-information")

    canberra = shutil.which("canberra-gtk-play")
    if canberra:
        subprocess.Popen(
            [canberra, "-i", event],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return

    # Static freedesktop stereo pack (Debian/Ubuntu/SteamOS often ship this).
    name = {
        SystemSound.ERROR: "dialog-error.oga",
        SystemSound.WARNING: "dialog-warning.oga",
        SystemSound.SUCCESS: "complete.oga",
    }.get(sound, "dialog-information.oga")
    path = f"/usr/share/sounds/freedesktop/stereo/{name}"
    player = shutil.which("paplay") or shutil.which("pw-play") or shutil.which("aplay")
    if player and os.path.isfile(path):
        subprocess.Popen(
            [player, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return

    # Last resort: terminal bell / Qt beep.
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.beep()
            return
    except Exception:
        pass
    sys.stdout.write("\a")
    sys.stdout.flush()
