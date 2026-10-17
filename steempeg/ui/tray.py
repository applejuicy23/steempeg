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
        """Single left click on the icon opens the main window."""
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
