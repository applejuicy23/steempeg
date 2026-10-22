"""Keep the Windows Apps version in step with the running install.

Inno Setup writes DisplayVersion once, when the installer runs. An in-app
update replaces the files and never that registry value, so Settings → Apps
keeps showing the version the installer had. A portable copy has no uninstall
key, and this module must not create one.
"""
from __future__ import annotations

import logging
import os
import sys

_log = logging.getLogger(__name__)

# AppId in installer/steempeg.iss. Inno appends _is1 to the per-user uninstall key.
UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{8FDC961D-EEA5-4016-BB3C-7235F7E56619}_is1"
)


def paths_match(left: str, right: str) -> bool:
    """True when two paths name the same folder, ignoring case and a trailing slash."""
    if not left or not right:
        return False
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def write_display_version_if_ours(
    install_root: str,
    version: str,
    *,
    key_path: str = UNINSTALL_KEY,
) -> bool:
    """Sets DisplayVersion when `key_path` already exists and names `install_root`.

    Returns True only when the value changed. A missing key, a key that points
    at another folder, or a version that is already current is left untouched.
    """
    if sys.platform != "win32":
        return False
    version = str(version or "").strip()
    if not version or not install_root:
        return False
    try:
        import winreg
    except ImportError:
        return False

    access = winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE | getattr(winreg, "KEY_WOW64_64KEY", 0)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, access) as key:
            try:
                location, _kind = winreg.QueryValueEx(key, "InstallLocation")
            except FileNotFoundError:
                return False
            if not paths_match(str(location), install_root):
                _log.debug(
                    "Installed version left unchanged: uninstall entry points at %s, this copy is %s",
                    location,
                    install_root,
                )
                return False
            try:
                current, _kind = winreg.QueryValueEx(key, "DisplayVersion")
            except FileNotFoundError:
                current = ""
            if str(current) == version:
                return False
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
    except FileNotFoundError:
        return False
    except OSError as exc:
        _log.warning("Installed version was not updated: %s", exc)
        return False
    _log.info("Installed version in Windows Apps is now %s", version)
    return True


def sync_installed_display_version() -> bool:
    """Points the Windows Apps entry at this build's version, when this is that install."""
    from steempeg.infra.paths import get_install_root, is_frozen_build
    from steempeg.version import APP_VERSION_STR

    if not is_frozen_build():
        return False
    return write_display_version_if_ours(get_install_root(), APP_VERSION_STR)
