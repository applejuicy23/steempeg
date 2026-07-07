"""The main application window, replacing the runtime-loaded smpegui13.ui.
 
Wraps the pyside6-uic-generated Ui_Dialog so the rest of the app keeps using
self.ui.<widget_name> exactly as it did under QUiLoader. setupUi() builds the
widgets and parents them to this dialog; we then mirror them as attributes on
the window so existing references (self.ui.table_clips, self.ui.combo_quality, ...)
resolve unchanged.
"""
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QDialog
 
from steempeg.ui.main_window_ui import Ui_Dialog
from steempeg.ui.window_chrome import (
    handle_native_event,
    install_title_bar,
    poke_frame,
    refresh_dwm_chrome,
)


class MainWindow(QDialog):
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

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            tb = getattr(self, "title_bar", None)
            if tb is not None:
                tb.sync_window_state()
            # Windows re-adds the native caption on maximize/restore — re-trigger
            # WM_NCCALCSIZE so our frameless client area stays caption-free.
            poke_frame(self)
            refresh_dwm_chrome(self)
        super().changeEvent(event)

    def showEvent(self, event):
        refresh_dwm_chrome(self)
        super().showEvent(event)

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