"""The main application window, replacing the runtime-loaded smpegui13.ui.

Wraps the pyside6-uic-generated Ui_Dialog so the rest of the app keeps using
self.ui.<widget_name> exactly as it did under QUiLoader. setupUi() builds the
widgets and parents them to this window; we then mirror them as attributes so
existing references (self.ui.table_clips, self.ui.combo_quality, ...) resolve.

On Linux we use QWidget (not QDialog): Wayland/KDE often never maps a QDialog
toplevel to the screen even when Qt reports visible=True.
"""
import sys

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QDialog, QWidget

from steempeg.ui.main_window_ui import Ui_Dialog
from steempeg.ui.window_chrome import (
    handle_native_event,
    install_title_bar,
    poke_frame,
    refresh_dwm_chrome,
    soft_full_redraw,
)

_WindowBase = QDialog if sys.platform == "win32" else QWidget


class MainWindow(_WindowBase):
    def __init__(self, parent=None, app_host=None):
        super().__init__(parent)
        self._app_host = app_host
        self._ui = Ui_Dialog()
        self._ui.setupUi(self)

        # Mirror every widget built by setupUi onto the window itself, matching
        # the old QUiLoader behaviour (self.ui.<objectName> attribute access).
        for name, obj in vars(self._ui).items():
            if name.startswith("_"):
                continue
            setattr(self, name, obj)

        install_title_bar(self)

        # Frameless + DWM: aggressive shrink-to-min can leave a translucent
        # "ghost" copy of the chrome over the player. Clear after resize settles.
        # Use soft redraw only — force_full_redraw's 1px SetWindowPos re-enters
        # resizeEvent and can spawn more ghosts (especially with Render Queue open).
        self._dwm_ghost_timer = QTimer(self)
        self._dwm_ghost_timer.setSingleShot(True)
        self._dwm_ghost_timer.setInterval(120)
        self._dwm_ghost_timer.timeout.connect(self._clear_dwm_resize_ghost)
        self._dwm_redrawing = False

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            tb = getattr(self, "title_bar", None)
            if tb is not None:
                tb.sync_window_state()
            # Windows re-adds the native caption on maximize/restore — re-trigger
            # WM_NCCALCSIZE so our frameless client area stays caption-free.
            poke_frame(self)
            refresh_dwm_chrome(self)
            if sys.platform == "win32":
                self._dwm_ghost_timer.start()
        super().changeEvent(event)

    def showEvent(self, event):
        refresh_dwm_chrome(self)
        host = self._app_host
        if host is not None and hasattr(host, "on_main_window_resized"):
            host.on_main_window_resized()
        super().showEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_dwm_redrawing", False):
            return
        host = self._app_host
        if host is not None and hasattr(host, "on_main_window_resized"):
            host.on_main_window_resized()
        if sys.platform == "win32":
            self._dwm_ghost_timer.start()

    def _clear_dwm_resize_ghost(self) -> None:
        if sys.platform != "win32":
            return
        if not self.isVisible() or self.isMinimized():
            return
        if self._dwm_redrawing:
            return
        self._dwm_redrawing = True
        try:
            refresh_dwm_chrome(self)
            soft_full_redraw(self)
        finally:
            # Clear on next tick so any late resize from RedrawWindow is ignored.
            QTimer.singleShot(0, self._end_dwm_redraw)

    def _end_dwm_redraw(self) -> None:
        self._dwm_redrawing = False

    def nativeEvent(self, eventType, message):
        result = handle_native_event(self, eventType, message)
        if result is not None:
            return result
        return super().nativeEvent(eventType, message)

    def closeEvent(self, event):
        host = self._app_host
        if host is not None and hasattr(host, "closeEvent"):
            host.closeEvent(event)
        else:
            super().closeEvent(event)
