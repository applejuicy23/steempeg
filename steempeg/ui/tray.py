"""Tray icon and background mode.

While the tray is active the red close button hides the main window instead
of quitting, so the new-clip watcher keeps catching Steam clips. Real quit
lives in the tray menu. ``--background`` launches build the main window
hidden and reveal it on the first «Open Steempeg».
"""
from __future__ import annotations

import logging
import sys
from typing import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

_log = logging.getLogger(__name__)


def tray_is_supported() -> bool:
    """Tells whether this desktop has a system tray to put the icon in."""
    return QSystemTrayIcon.isSystemTrayAvailable()


_CMD_OPEN = 1
_CMD_LAST_CLIP = 2
_CMD_PAUSE = 3
_CMD_QUEUE = 4
_CMD_QUIT = 5


def _windows_menu_owner():
    """Hidden popup that owns the native tray menu, not the main window.

    ``TrackPopupMenu`` needs an owner. The main window would come forward and
    Explorer would drop the auto-hide taskbar. A zero-size tool window does not.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    hwnd = user32.CreateWindowExW(
        0x00000080 | 0x08000000,  # WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        "STATIC",
        "SteempegTrayMenu",
        0x80000000,  # WS_POPUP
        0,
        0,
        0,
        0,
        None,
        None,
        kernel32.GetModuleHandleW(None),
        None,
    )
    return int(hwnd or 0)


def _show_windows_tray_menu(app, *, pause_checked: bool, last_clip_enabled: bool, queue_label: str) -> int:
    """Open a Win32 menu at the cursor. Returns the chosen command id, or 0.

    A Qt popup is an ordinary window, so Explorer treats it as leaving the tray
    and slides the taskbar away. A real menu stays inside that click, the same
    way other tray icons do.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_size_t,
        wintypes.LPCWSTR,
    ]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
    user32.SetMenuDefaultItem.restype = wintypes.BOOL
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.c_void_p]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    user32.TrackPopupMenu.restype = wintypes.UINT
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    user32.PostMessageW.restype = wintypes.BOOL

    owner = int(getattr(app, "_tray_menu_owner", 0) or 0)
    if not owner:
        owner = _windows_menu_owner()
        app._tray_menu_owner = owner
    if not owner:
        return 0

    mf_string = 0x0000
    mf_grayed = 0x0001
    mf_checked = 0x0008
    mf_separator = 0x0800
    menu = user32.CreatePopupMenu()
    if not menu:
        return 0
    try:
        user32.AppendMenuW(menu, mf_string, _CMD_OPEN, "Open Steempeg")
        user32.SetMenuDefaultItem(menu, 0, 1)
        last_flags = mf_string if last_clip_enabled else mf_string | mf_grayed
        user32.AppendMenuW(menu, last_flags, _CMD_LAST_CLIP, "Open last clip in Express player")
        user32.AppendMenuW(menu, mf_separator, 0, None)
        pause_flags = mf_string | (mf_checked if pause_checked else 0)
        user32.AppendMenuW(menu, pause_flags, _CMD_PAUSE, "Pause new-clip detection")
        user32.AppendMenuW(menu, mf_string, _CMD_QUEUE, queue_label)
        user32.AppendMenuW(menu, mf_separator, 0, None)
        user32.AppendMenuW(menu, mf_string, _CMD_QUIT, "Quit Steempeg")

        class _Point(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        point = _Point()
        user32.GetCursorPos(ctypes.byref(point))
        # Required so the menu closes on a click outside it. The owner is not
        # the main window, so this does not raise Steempeg over the taskbar.
        user32.SetForegroundWindow(owner)
        flags = 0x0008 | 0x0020 | 0x0002 | 0x0100  # RIGHTALIGN BOTTOMALIGN RIGHTBUTTON RETURNCMD
        chosen = int(
            user32.TrackPopupMenu(menu, flags, int(point.x), int(point.y), 0, owner, None) or 0
        )
        user32.PostMessageW(owner, 0, 0, 0)  # WM_NULL, per the Shell_NotifyIcon sample
        return chosen
    finally:
        user32.DestroyMenu(menu)


def describe_render_queue(app) -> str:
    """Builds the tray menu label for the render queue: idle / rendering / waiting jobs."""
    queue = getattr(app, "render_queue", None)
    waiting = int(queue.pending_count()) if queue is not None else 0
    rendering = bool(getattr(app, "_is_rendering", False))
    express = len(getattr(app, "_express_renders", None) or [])
    parts = []
    if rendering or express:
        parts.append("rendering")
    if waiting:
        parts.append(f"{waiting} waiting")
    return "Render Queue · " + (" · ".join(parts) if parts else "idle")


class SteempegTray(QObject):
    """Owns the tray icon, its menu, and hiding / revealing the main window."""

    def __init__(self, app, *, background_launch: bool = False):
        """Builds the icon and menu for ``app`` (shown later by ``apply_keep_running``)."""
        super().__init__(app.ui)
        from steempeg.ui.icon_utils import app_window_icon

        self._app = app
        self._background_launch = bool(background_launch)
        self._keep_running = False
        self._quitting = False
        self._was_maximized = True
        self._hint_shown = False
        self._first_reveal: Callable[[], None] | None = None

        self._icon = QSystemTrayIcon(app_window_icon(), self)
        self._icon.setToolTip("Steempeg")
        self._icon.activated.connect(self._on_icon_activated)
        # Windows uses a native menu. A Qt popup takes the foreground and
        # Explorer then hides the auto-hide taskbar and the tray flyout.
        self._menu = None if sys.platform == "win32" else self._build_menu()
        if self._menu is not None:
            self._icon.setContextMenu(self._menu)

    # -- state ----------------------------------------------------------------

    def is_active(self) -> bool:
        """True while the tray icon is up (setting on, or launched with ``--background``)."""
        return self._keep_running or self._background_launch

    def keeps_running_on_close(self) -> bool:
        """True when the red close button should hide to the tray instead of quitting."""
        return self.is_active() and not self._quitting and tray_is_supported()

    def is_quitting(self) -> bool:
        """True once a real quit started (tray Quit, Restart app, updater)."""
        return self._quitting

    def mark_quitting(self) -> None:
        """Lets the next close really close: Qt 6 ``quit()`` is cancelled if a window refuses to close."""
        self._quitting = True

    def apply_keep_running(self, enabled: bool) -> None:
        """Applies the Settings toggle: shows / hides the icon and stops Qt quitting on hidden windows."""
        self._keep_running = bool(enabled)
        active = self.is_active() and tray_is_supported()
        QApplication.instance().setQuitOnLastWindowClosed(not active)
        self._icon.setVisible(active)
        _log.info("Tray: %s", "active" if active else "off")

    def set_first_reveal(self, reveal: Callable[[], None]) -> None:
        """Remembers the full startup show sequence for a window built hidden by ``--background``."""
        self._first_reveal = reveal

    # -- menu -----------------------------------------------------------------

    def _build_menu(self) -> QMenu:
        """Creates the right-click menu (labels refresh every time it opens)."""
        from steempeg.ui import ui_theme as ut

        menu = QMenu()
        menu.setStyleSheet(ut.menu_stylesheet())
        self._act_open = QAction("Open Steempeg", menu)
        font = self._act_open.font()
        font.setBold(True)
        self._act_open.setFont(font)
        self._act_open.triggered.connect(self.show_main_window)
        menu.addAction(self._act_open)

        self._act_last_clip = QAction("Open last clip in Express player", menu)
        self._act_last_clip.triggered.connect(self.open_last_clip)
        menu.addAction(self._act_last_clip)
        menu.addSeparator()

        self._act_pause_watch = QAction("Pause new-clip detection", menu)
        self._act_pause_watch.setCheckable(True)
        self._act_pause_watch.toggled.connect(self._on_pause_watch_toggled)
        menu.addAction(self._act_pause_watch)

        self._act_queue = QAction("Render Queue", menu)
        self._act_queue.triggered.connect(self.open_render_queue)
        menu.addAction(self._act_queue)
        menu.addSeparator()

        act_quit = QAction("Quit Steempeg", menu)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_quit)
        menu.aboutToShow.connect(self._refresh_menu)
        return menu

    def _refresh_menu(self) -> None:
        """Updates the theme, the last-clip availability, the pause tick and the queue status."""
        from steempeg.ui import ui_theme as ut

        self._menu.setStyleSheet(ut.menu_stylesheet())
        self._act_last_clip.setEnabled(bool(self._app.find_last_clip_for_express()))
        self._act_pause_watch.blockSignals(True)
        self._act_pause_watch.setChecked(self._app.is_new_clip_watch_paused())
        self._act_pause_watch.blockSignals(False)
        self._act_queue.setText(describe_render_queue(self._app))

    def _on_pause_watch_toggled(self, checked: bool) -> None:
        """Pauses or resumes the new-clip watcher from the menu."""
        self._app.set_new_clip_watch_paused(checked)
        self._icon.setToolTip("Steempeg · new-clip detection paused" if checked else "Steempeg")

    def _on_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Left click opens the window. Right click opens the native Windows menu."""
        if reason == QSystemTrayIcon.ActivationReason.Context and sys.platform == "win32":
            self._popup_windows_menu()
            return
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_main_window()

    def _popup_windows_menu(self) -> None:
        """Shows the tray menu without pulling the taskbar down."""
        try:
            chosen = _show_windows_tray_menu(
                self._app,
                pause_checked=bool(self._app.is_new_clip_watch_paused()),
                last_clip_enabled=bool(self._app.find_last_clip_for_express()),
                queue_label=describe_render_queue(self._app),
            )
        except Exception:
            _log.debug("Tray: native menu failed", exc_info=True)
            return
        if chosen == _CMD_OPEN:
            self.show_main_window()
        elif chosen == _CMD_LAST_CLIP:
            self.open_last_clip()
        elif chosen == _CMD_PAUSE:
            paused = not bool(self._app.is_new_clip_watch_paused())
            self._app.set_new_clip_watch_paused(paused)
            self._icon.setToolTip(
                "Steempeg · new-clip detection paused" if paused else "Steempeg"
            )
        elif chosen == _CMD_QUEUE:
            self.open_render_queue()
        elif chosen == _CMD_QUIT:
            self.quit_app()

    # -- actions --------------------------------------------------------------

    def hide_main_window(self) -> None:
        """Pauses playback and hides the main window; the first time, tells the user where it went."""
        ui = self._app.ui
        self._was_maximized = ui.isMaximized()
        player = getattr(self._app, "player", None)
        try:
            if player is not None and not player.pause and hasattr(self._app, "toggle_play"):
                self._app.toggle_play()
        except Exception:
            _log.debug("Tray: pause before hide failed", exc_info=True)
        ui.hide()
        if not self._hint_shown:
            self._hint_shown = True
            self._icon.showMessage(
                "Steempeg is still running",
                "New Steam clips will still pop up. Quit from the tray icon menu.",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )

    def show_main_window(self) -> None:
        """Shows the main window (running the hidden-launch reveal the first time) and focuses it."""
        if self._first_reveal is not None:
            reveal = self._first_reveal
            self._first_reveal = None
            reveal()
            return
        ui = self._app.ui
        if ui.isHidden():
            if sys.platform == "win32" and self._was_maximized:
                ui.showMaximized()
            else:
                ui.show()
        elif ui.isMinimized():
            ui.setWindowState(
                (ui.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
            )
        ui.raise_()
        ui.activateWindow()
        try:
            from steempeg.infra.window_focus import force_widget_foreground

            force_widget_foreground(ui)
        except Exception:
            _log.debug("Tray: bring to front failed", exc_info=True)

    def open_last_clip(self) -> None:
        """Opens the newest clip in the Express mini player without showing the main window."""
        clip = self._app.find_last_clip_for_express()
        if clip:
            self._app.open_express_player(clip)

    def open_render_queue(self) -> None:
        """Shows the main window with the render queue pane open (Desktop shell)."""
        self.show_main_window()
        from steempeg.ui.shell_chooser import UI_SHELL_PORTABLE

        if getattr(self._app, "_ui_shell", "") == UI_SHELL_PORTABLE:
            return
        if hasattr(self._app, "_open_queue_in_right_splitter"):
            try:
                self._app._open_queue_in_right_splitter()
            except Exception:
                _log.debug("Tray: open render queue failed", exc_info=True)

    def quit_app(self) -> None:
        """Really quits: closes Express players and the main window (full cleanup), then stops Qt."""
        self.mark_quitting()
        for player in list((getattr(self._app, "_express_players", None) or {}).values()):
            try:
                player.close()
            except RuntimeError:
                pass
        self._icon.hide()
        self._app.ui.close()
        QApplication.instance().quit()
