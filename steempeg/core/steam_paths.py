"""Locate the Steam install and Game Recording clip library folders.

Pure filesystem helpers — no Qt.
"""
import os
import re

_STEAM_ID_RE = re.compile(r"^\d{5,}$")


def get_steam_path():
    """Steam install dir from the Windows registry, falling back to the default."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            return os.path.normpath(winreg.QueryValueEx(key, "SteamPath")[0])
    except Exception:
        return r"C:\Program Files (x86)\Steam"


def steam_id_from_clips_folder(path):
    """Return the Steam user id from ``.../userdata/<id>/gamerecordings/clips``, or None."""
    if not path:
        return None
    parts = os.path.normpath(path).split(os.sep)
    try:
        idx = parts.index("userdata")
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    steam_id = parts[idx + 1]
    return steam_id if _STEAM_ID_RE.match(steam_id) else None


def discover_steam_clips_folders(steam_path=None):
    """Find every ``userdata/<steamid>/gamerecordings/clips`` folder that exists.

    Mirrors the old SteamClips behaviour: scan all numeric Steam IDs under
    ``userdata``, not just the active account. Returns normalized paths sorted
    by Steam ID (numeric).
    """
    steam_root = os.path.normpath(steam_path or get_steam_path())
    userdata = os.path.join(steam_root, "userdata")
    if not os.path.isdir(userdata):
        return []

    found = []
    try:
        entries = os.listdir(userdata)
    except OSError:
        return []

    for name in entries:
        if not _STEAM_ID_RE.match(name):
            continue
        clips = os.path.join(userdata, name, "gamerecordings", "clips")
        if os.path.isdir(clips):
            found.append(os.path.normpath(clips))

    found.sort(key=lambda p: int(steam_id_from_clips_folder(p) or 0))
    return found


def default_clips_dialog_path(clips_folders=None, steam_path=None):
    """Best starting path for a folder-picker dialog."""
    for folder in clips_folders or []:
        if folder and os.path.isdir(folder):
            return folder

    discovered = discover_steam_clips_folders(steam_path)
    if discovered:
        return discovered[0]

    steam_root = os.path.normpath(steam_path or get_steam_path())
    userdata = os.path.join(steam_root, "userdata")
    if os.path.isdir(userdata):
        return userdata
    if os.path.isdir(steam_root):
        return steam_root
    return "C:\\"
