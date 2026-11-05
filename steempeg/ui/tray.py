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

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QAction, QHideEvent, QIcon, QShowEvent
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

_log = logging.getLogger(__name__)


def tray_is_supported() -> bool:
    """Tells whether this desktop has a system tray to put the icon in."""
    return QSystemTrayIcon.isSystemTrayAvailable()


# The menu does not activate, so Qt never sees a click on the desktop.
# A low-level mouse hook would sit on every move and stall the pointer,
# so a timer only samples the buttons.
_VK_LBUTTON = 0x01
_VK_RBUTTON = 0x02
_VK_MBUTTON = 0x04
_OUTSIDE_POLL_MS = 32

_outside_timer: QTimer | None = None
_outside_menu: QMenu | None = None
_outside_prev_buttons = 0
_outside_ignore_buttons = 0


class _TrayMenu(QMenu):
    """App-styled tray menu that does not take the foreground on Windows.

    A normal popup becomes the foreground window, and Explorer then slides an
    auto-hide taskbar away. The menu stays up if the pointer leaves. A click
    anywhere else closes it, the same way a Telegram tray card does. That
    click is sampled on a timer: a low-level mouse hook stalls the pointer.
    """

    def __init__(self) -> None:
        super().__init__()
        self._show_generation = 0
        if sys.platform == "win32":
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def showEvent(self, event: QShowEvent) -> None:
        self._show_generation += 1
        if sys.platform == "win32":
            _keep_windows_taskbar(self)
            _arm_outside_click(self)
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        if sys.platform == "win32":
            _disarm_outside_click(self)
        super().hideEvent(event)


def _keep_windows_taskbar(menu: QMenu) -> None:
    """Stop this popup from becoming the foreground window."""
    try:
        menu.createWinId()
        hwnd = int(menu.winId())
        if not hwnd:
            return
        import ctypes

        user32 = ctypes.windll.user32
        ex = int(user32.GetWindowLongW(hwnd, -20))
        noactivate = 0x08000000
        if not (ex & noactivate):
            user32.SetWindowLongW(hwnd, -20, ex | noactivate)
    except Exception:
        _log.debug("Tray menu: keep taskbar visible failed", exc_info=True)


def _click_is_on_menu(menu: QMenu, x: int, y: int) -> bool:
    """True when the screen point lands on the tray menu window."""
    try:
        hwnd = int(menu.winId())
    except RuntimeError:
        return False
    if not hwnd:
        return False
    import ctypes
    from ctypes import wintypes

    class _Rect(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    rect = _Rect()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    return rect.left <= x < rect.right and rect.top <= y < rect.bottom


def _mouse_buttons_down() -> int:
    """Bitmask of mouse buttons held now. This does not sit on the cursor path."""
    import ctypes

    user32 = ctypes.windll.user32
    mask = 0
    if user32.GetAsyncKeyState(_VK_LBUTTON) & 0x8000:
        mask |= 1
    if user32.GetAsyncKeyState(_VK_RBUTTON) & 0x8000:
        mask |= 2
    if user32.GetAsyncKeyState(_VK_MBUTTON) & 0x8000:
        mask |= 4
    return mask


def _cursor_pos() -> tuple[int, int]:
    """Screen position of the pointer, in pixels."""
    import ctypes
    from ctypes import wintypes

    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)


def _poll_outside_click() -> None:
    """Hide the tray menu when a new click starts outside it."""
    global _outside_prev_buttons, _outside_ignore_buttons
    menu = _outside_menu
    if menu is None:
        return
    try:
        if not menu.isVisible():
            return
        down = _mouse_buttons_down()
    except Exception:
        _log.debug("Tray menu: outside click poll failed", exc_info=True)
        return
    # The click that opened the menu is still held. Wait until it is released.
    if _outside_ignore_buttons:
        _outside_ignore_buttons &= down
        _outside_prev_buttons = down
        return
    pressed = down & ~_outside_prev_buttons
    _outside_prev_buttons = down
    if not pressed:
        return
    try:
        x, y = _cursor_pos()
        on_menu = _click_is_on_menu(menu, x, y)
    except RuntimeError:
        return
    if on_menu:
        return
    generation = menu._show_generation

    def _close(shown: int = generation, target: QMenu = menu) -> None:
        try:
            if target._show_generation == shown and target.isVisible():
                target.hide()
        except RuntimeError:
            return

    QTimer.singleShot(0, _close)


def _arm_outside_click(menu: QMenu) -> None:
    """Watch mouse clicks until this menu closes."""
    global _outside_timer, _outside_menu, _outside_prev_buttons, _outside_ignore_buttons
    _disarm_outside_click(None)
    held = _mouse_buttons_down()
    _outside_menu = menu
    _outside_prev_buttons = held
    _outside_ignore_buttons = held
    timer = _outside_timer
    if timer is None:
        timer = QTimer(menu)
        timer.setInterval(_OUTSIDE_POLL_MS)
        timer.timeout.connect(_poll_outside_click)
        _outside_timer = timer
    timer.start()


def _disarm_outside_click(menu: QMenu | None) -> None:
    """Drop the click watch. ``menu`` limits the drop to that popup."""
    global _outside_timer, _outside_menu, _outside_prev_buttons, _outside_ignore_buttons
    if menu is not None and _outside_menu is not menu:
        return
    _outside_menu = None
    _outside_prev_buttons = 0
    _outside_ignore_buttons = 0
    timer = _outside_timer
    if timer is not None:
        timer.stop()


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
    return "Render Queue | " + (" | ".join(parts) if parts else "idle")


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
        self._menu = self._build_menu()
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

    def _menu_icon(self, name: str) -> QIcon:
        """Loads a small tray-menu glyph from the bundled assets."""
        from steempeg.infra.paths import get_resource_path

        return QIcon(get_resource_path(name))

    def _build_menu(self) -> QMenu:
        """Creates the right-click menu (labels refresh every time it opens)."""
        from steempeg.ui import ui_theme as ut
        from steempeg.ui.icon_utils import app_window_icon

        menu = _TrayMenu()
        menu.setStyleSheet(ut.menu_stylesheet())
        self._act_open = QAction("Open Steempeg", menu)
        self._act_open.setIcon(app_window_icon())
        font = self._act_open.font()
        font.setBold(True)
        self._act_open.setFont(font)
        self._act_open.triggered.connect(self.show_main_window)
        menu.addAction(self._act_open)

        self._act_last_clip = QAction("Open last clip in Express player", menu)
        self._act_last_clip.setIcon(self._menu_icon("play2.png"))
        self._act_last_clip.triggered.connect(self.open_last_clip)
        menu.addAction(self._act_last_clip)
        menu.addSeparator()

        self._act_pause_watch = QAction("Pause new-clip detection", menu)
        self._act_pause_watch.setIcon(self._menu_icon("pause_player.png"))
        self._act_pause_watch.setCheckable(True)
        self._act_pause_watch.toggled.connect(self._on_pause_watch_toggled)
        menu.addAction(self._act_pause_watch)

        self._act_queue = QAction("Render Queue", menu)
        self._act_queue.setIcon(self._menu_icon("queue.png"))
        self._act_queue.triggered.connect(self.open_render_queue)
        menu.addAction(self._act_queue)
        menu.addSeparator()

        act_quit = QAction("Quit Steempeg", menu)
        act_quit.setIcon(self._menu_icon("exit.png"))
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
        """Left click opens the window. Right click is the context menu."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_main_window()

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
