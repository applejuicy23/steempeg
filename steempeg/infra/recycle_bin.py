"""Send files / folders to the OS trash instead of deleting them for good."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

_FO_DELETE = 0x0003
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400
_FOF_NOCONFIRMMKDIR = 0x0200


def recycle_bin_available() -> bool:
    if sys.platform == "win32":
        return True
    return shutil.which("gio") is not None


def _send_windows(path: str) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = _FO_DELETE
    # pFrom is a double-NUL-terminated list.
    op.pFrom = path + "\0"
    op.pTo = None
    op.fFlags = (
        _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI | _FOF_NOCONFIRMMKDIR
    )
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0:
        raise OSError(result, f"Recycle Bin move failed (code {result:#x})", path)
    if op.fAnyOperationsAborted:
        raise OSError(f"Recycle Bin move was aborted: {path}")


def send_to_recycle_bin(path: str) -> None:
    """Move one file or folder to the trash. Raises ``OSError`` on failure."""
    norm = os.path.abspath(os.path.normpath(path))
    if not os.path.exists(norm):
        raise FileNotFoundError(norm)
    if sys.platform == "win32":
        _send_windows(norm)
        return
    if shutil.which("gio") is None:
        raise OSError(f"No trash helper available for {norm}")
    proc = subprocess.run(["gio", "trash", norm], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise OSError(proc.stderr.strip() or f"gio trash failed for {norm}")
