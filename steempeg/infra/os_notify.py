"""Native OS notification center toasts (Windows Action Center / Linux notify).

Windows: WinRT ``ToastNotification`` via a short PowerShell helper. Qt's
``QSystemTrayIcon.showMessage`` is a balloon and usually never reaches Action
Center on Win10/11.

Important: an unpackaged AUMID only shows banners if Windows has a Start Menu
shortcut for that ID pointing at a real ``.exe``. Dev runs (python / .bat) do
not qualify — so we deliver through the registered PowerShell host AUMID (same
path Probe A used) and stamp ``placement="attribution"`` as Steempeg. Frozen
builds additionally register ``Steempeg.SteempegApp`` against the real exe.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from enum import Enum
from pathlib import Path
from xml.sax.saxutils import escape

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.infra.system_sound import SystemSound, play_system_sound
from steempeg.infra.window_focus import (
    TOAST_PROTOCOL_LAUNCH,
    ensure_toast_protocol_registered,
)

_log = logging.getLogger(__name__)

# Must match SetCurrentProcessExplicitAppUserModelID in steempeg.app.
_WINDOWS_AUMID = "Steempeg.SteempegApp"
# Always-registered host — Win11 shows these; used when Steempeg AUMID has no exe shortcut.
_PS_HOST_AUMID = (
    r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
)

_notifier: "OsNotifier | None" = None
_shortcut_ready = False


class NotifyKind(Enum):
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"


def _icon_for(kind: NotifyKind) -> QSystemTrayIcon.MessageIcon:
    if kind == NotifyKind.ERROR:
        return QSystemTrayIcon.MessageIcon.Critical
    if kind == NotifyKind.WARNING:
        return QSystemTrayIcon.MessageIcon.Warning
    return QSystemTrayIcon.MessageIcon.Information


def _sound_for(kind: NotifyKind) -> SystemSound:
    if kind == NotifyKind.ERROR:
        return SystemSound.ERROR
    if kind == NotifyKind.WARNING:
        return SystemSound.WARNING
    return SystemSound.SUCCESS


def app_is_in_background(widget: QWidget | None = None) -> bool:
    """True when Steempeg is minimized or not the foreground app."""
    app = QApplication.instance()
    if app is not None:
        try:
            if app.applicationState() != Qt.ApplicationState.ApplicationActive:
                return True
        except Exception:
            pass

    win = widget.window() if widget is not None else None
    if win is None and app is not None:
        win = app.activeWindow()
    if win is None:
        return False
    try:
        if win.isMinimized():
            return True
        if not win.isActiveWindow():
            return True
    except Exception:
        return False
    return False


def _toast_exe_candidate() -> str | None:
    """Best .exe to bind the Start Menu AUMID shortcut to (frozen install)."""
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        if exe.lower().endswith(".exe") and os.path.isfile(exe):
            return exe
    try:
        from steempeg.infra.paths import get_install_root

        root = Path(get_install_root())
    except Exception:
        root = Path(__file__).resolve().parents[2]
    for name in (
        "Steempeg-windows.exe",
        "Steempeg.exe",
        "Steempeg-linux",  # not useful on win
    ):
        cand = root / name
        if cand.is_file() and cand.suffix.lower() == ".exe":
            return str(cand)
    # Nested onedir layouts
    for pattern in ("Steempeg*.exe", "**/Steempeg-windows.exe"):
        try:
            found = next(root.glob(pattern))
            if found.is_file():
                return str(found)
        except StopIteration:
            pass
    return None


def _ensure_steempeg_toast_shortcut() -> bool:
    """Register Start Menu .lnk with System.AppUserModel.ID → real exe.

    Returns True when a usable Steempeg AUMID shortcut exists.
    """
    global _shortcut_ready
    if _shortcut_ready:
        return True
    exe = _toast_exe_candidate()
    if not exe:
        return False
    try:
        programs = (
            Path(os.environ.get("APPDATA", ""))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
        )
        programs.mkdir(parents=True, exist_ok=True)
        lnk_path = programs / "Steempeg.lnk"
        icon = get_resource_path("logo.ico")
        if not icon or not os.path.isfile(icon):
            icon = exe
        exe_lit = exe.replace("'", "''")
        lnk_lit = str(lnk_path).replace("'", "''")
        work_lit = str(Path(exe).parent).replace("'", "''")
        icon_lit = str(icon).replace("'", "''")
        aumid = _WINDOWS_AUMID
        ps = f"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut('{lnk_lit}')
$sc.TargetPath = '{exe_lit}'
$sc.WorkingDirectory = '{work_lit}'
$sc.Description = 'Steempeg'
$sc.IconLocation = '{icon_lit}'
$sc.Save()
$code = @'
using System;
using System.Runtime.InteropServices;
public static class LnkAumid {{
  [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IPropertyStore {{
    int GetCount(out uint cProps);
    int GetAt(uint iProp, out PROPERTYKEY pkey);
    int GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
    int SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
    int Commit();
  }}
  [StructLayout(LayoutKind.Sequential, Pack=4)]
  struct PROPERTYKEY {{ public Guid fmtid; public uint pid; }}
  [StructLayout(LayoutKind.Sequential)]
  struct PROPVARIANT {{
    public ushort vt;
    public ushort wReserved1, wReserved2, wReserved3;
    public IntPtr pointerValue;
  }}
  [DllImport("shell32.dll", CharSet=CharSet.Unicode, PreserveSig=false)]
  static extern void SHGetPropertyStoreFromParsingName(
    string pszPath, IntPtr pbc, uint flags, ref Guid riid, out IPropertyStore ppv);
  [DllImport("ole32.dll")] static extern void PropVariantClear(ref PROPVARIANT pvar);
  public static void SetAppId(string lnk, string appId) {{
    var iid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
    IPropertyStore store;
    SHGetPropertyStoreFromParsingName(lnk, IntPtr.Zero, 2, ref iid, out store);
    var key = new PROPERTYKEY {{
      fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),
      pid = 5
    }};
    var pv = new PROPVARIANT();
    pv.vt = 31;
    pv.pointerValue = Marshal.StringToCoTaskMemUni(appId);
    store.SetValue(ref key, ref pv);
    store.Commit();
    PropVariantClear(ref pv);
  }}
}}
'@
Add-Type -TypeDefinition $code -Language CSharp
[LnkAumid]::SetAppId('{lnk_lit}', '{aumid}')
"""
        script = Path(tempfile.gettempdir()) / f"steempeg_aumid_{os.getpid()}.ps1"
        script.write_text(ps, encoding="utf-8")
        kwargs: dict = {
            "args": [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script),
            ],
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.run(**kwargs, timeout=20)
        _shortcut_ready = lnk_path.is_file()
        return _shortcut_ready
    except Exception as exc:
        _log.debug("toast shortcut registration failed: %s", exc)
        return False


def _windows_toast(title: str, body: str) -> bool:
    """Post an Action Center toast via WinRT (fire-and-forget)."""
    try:
        ensure_toast_protocol_registered()
        # Prefer Steempeg identity when a real .exe shortcut can back it;
        # otherwise fall back to the PowerShell host AUMID that Win11 always shows.
        use_steempeg_id = _ensure_steempeg_toast_shortcut()
        app_id = _WINDOWS_AUMID if use_steempeg_id else _PS_HOST_AUMID

        xml = (
            "<toast activationType=\"protocol\" "
            f"launch=\"{TOAST_PROTOCOL_LAUNCH}\">"
            "<visual><binding template=\"ToastGeneric\">"
            f"<text>{escape(title)}</text>"
            f"<text>{escape(body)}</text>"
            "<text placement=\"attribution\">Steempeg</text>"
            "</binding></visual>"
            "</toast>"
        )
        tmp = Path(tempfile.gettempdir())
        xml_path = tmp / f"steempeg_toast_{os.getpid()}_{os.urandom(4).hex()}.xml"
        xml_path.write_text(xml, encoding="utf-8")
        xml_lit = str(xml_path).replace("'", "''")
        app_lit = app_id.replace("'", "''")
        ps = (
            "$ErrorActionPreference = 'Stop'\n"
            "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
            "ContentType = WindowsRuntime] | Out-Null\n"
            f"$p = '{xml_lit}'\n"
            "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
            "$xml.LoadXml((Get-Content -LiteralPath $p -Raw -Encoding UTF8))\n"
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)\n"
            f"[Windows.UI.Notifications.ToastNotificationManager]::"
            f"CreateToastNotifier('{app_lit}').Show($toast)\n"
            "Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue\n"
        )
        script = tmp / f"steempeg_toast_{os.getpid()}_{os.urandom(4).hex()}.ps1"
        script.write_text(ps, encoding="utf-8")
        kwargs: dict = {
            "args": [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script),
            ],
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            kwargs["startupinfo"] = subprocess.STARTUPINFO()
            kwargs["startupinfo"].dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.Popen(**kwargs)
        _log.info(
            "WinRT toast queued via %s: %s — %s",
            "Steempeg" if use_steempeg_id else "PowerShell-host",
            title,
            body,
        )
        return True
    except Exception as exc:
        _log.debug("WinRT toast failed: %s", exc)
        return False


def _notify_send(title: str, body: str, kind: NotifyKind) -> bool:
    exe = shutil.which("notify-send")
    if not exe:
        return False
    urgency = "critical" if kind == NotifyKind.ERROR else "normal"
    try:
        subprocess.Popen(
            [
                exe,
                "--app-name=Steempeg",
                f"--urgency={urgency}",
                "--expire-time=8000",
                title,
                body,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError as exc:
        _log.debug("notify-send failed: %s", exc)
        return False


class OsNotifier(QObject):
    """Cross-platform toast transport (+ optional Linux tray fallback)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._tray: QSystemTrayIcon | None = None
        if sys.platform != "win32" and QSystemTrayIcon.isSystemTrayAvailable():
            icon_path = get_resource_path("logo.png")
            icon = QIcon(icon_path) if icon_path else QIcon()
            self._tray = QSystemTrayIcon(icon, parent)
            self._tray.setToolTip("Steempeg")
            self._tray.setVisible(True)

    def show(
        self,
        title: str,
        body: str,
        *,
        kind: NotifyKind = NotifyKind.SUCCESS,
        play_sound: bool = True,
        msec: int = 8000,
    ) -> None:
        if play_sound:
            play_system_sound(_sound_for(kind))
        delivered = False
        if sys.platform == "win32":
            delivered = _windows_toast(title, body)
        else:
            delivered = _notify_send(title, body, kind)
            if not delivered and self._tray is not None and self._tray.isVisible():
                try:
                    self._tray.showMessage(title, body, _icon_for(kind), msec)
                    delivered = True
                except Exception as exc:
                    _log.debug("tray showMessage failed: %s", exc)
        if not delivered:
            _log.info("OS notify (no backend): %s — %s", title, body)


def get_os_notifier(parent: QWidget | None = None) -> OsNotifier:
    global _notifier
    if _notifier is None:
        _notifier = OsNotifier(parent)
    return _notifier


def notify_render_event(
    title: str,
    body: str,
    *,
    kind: NotifyKind = NotifyKind.SUCCESS,
    parent: QWidget | None = None,
    force: bool = False,
    play_sound: bool = True,
) -> bool:
    """Post an OS toast when the app is in the background (or ``force``).

    Returns True if a toast was requested.
    """
    if not force and not app_is_in_background(parent):
        return False
    get_os_notifier(parent).show(title, body, kind=kind, play_sound=play_sound)
    return True
