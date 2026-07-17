"""Locate the Steam install and Game Recording clip library folders.

Pure filesystem helpers — no Qt.
"""
from __future__ import annotations

import os
import re
import sys

_STEAM_ID_RE = re.compile(r"^\d{5,}$")


def _candidate_steam_roots() -> list[str]:
    """Ordered Steam install candidates for the current OS."""
    home = os.path.expanduser("~")
    env = (os.environ.get("STEAM_DIR") or os.environ.get("STEAM_PATH") or "").strip()
    roots: list[str] = []

    def add(path: str | None) -> None:
        if not path:
            return
        norm = os.path.normpath(os.path.expanduser(path))
        if norm not in roots:
            roots.append(norm)

    add(env)

    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                add(winreg.QueryValueEx(key, "SteamPath")[0])
        except Exception:
            pass
        add(r"C:\Program Files (x86)\Steam")
        add(r"C:\Program Files\Steam")
        return roots

    if sys.platform == "darwin":
        add(os.path.join(home, "Library", "Application Support", "Steam"))
        return roots

    # Linux / SteamOS / Deck (native, Flatpak, common symlinks)
    add(os.path.join(home, ".local", "share", "Steam"))
    add(os.path.join(home, ".steam", "steam"))
    add(os.path.join(home, ".steam", "root"))
    add(os.path.join(home, ".steam", "debian-installation"))
    add(
        os.path.join(
            home,
            ".var",
            "app",
            "com.valvesoftware.Steam",
            "data",
            "Steam",
        )
    )
    # Extra Deck-ish absolute paths if $HOME is weird in a chroot/VM
    add("/home/deck/.local/share/Steam")
    add("/home/deck/.steam/steam")
    return roots


def _looks_like_steam_root(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    # Prefer roots that already have userdata (clips live there).
    if os.path.isdir(os.path.join(path, "userdata")):
        return True
    # Fresh installs may lack userdata yet; steamapps / steam.sh are enough.
    if os.path.isdir(os.path.join(path, "steamapps")):
        return True
    if os.path.isfile(os.path.join(path, "steam.sh")):
        return True
    if sys.platform == "win32" and os.path.isfile(os.path.join(path, "steam.exe")):
        return True
    return False


def get_steam_path() -> str:
    """Steam install dir (registry on Windows, filesystem heuristics elsewhere)."""
    for root in _candidate_steam_roots():
        if _looks_like_steam_root(root):
            # Resolve symlinks so userdata paths stay stable on Linux (~/.steam/steam).
            try:
                return os.path.normpath(os.path.realpath(root))
            except OSError:
                return os.path.normpath(root)

    # Last resort: first existing candidate, else a sensible default for dialogs.
    for root in _candidate_steam_roots():
        if os.path.isdir(root):
            try:
                return os.path.normpath(os.path.realpath(root))
            except OSError:
                return os.path.normpath(root)

    if sys.platform == "win32":
        return r"C:\Program Files (x86)\Steam"
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Steam")
    return os.path.expanduser("~/.local/share/Steam")


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
    return os.path.expanduser("~")
