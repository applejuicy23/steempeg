"""The main application window, replacing the runtime-loaded smpegui13.ui.
 
Wraps the pyside6-uic-generated Ui_Dialog so the rest of the app keeps using
self.ui.<widget_name> exactly as it did under QUiLoader. setupUi() builds the
widgets and parents them to this dialog; we then mirror them as attributes on
the window so existing references (self.ui.table_clips, self.ui.combo_quality, ...)
resolve unchanged.
"""
from PySide6.QtWidgets import QDialog
 
from steempeg.ui.main_window_ui import Ui_Dialog
 
 
class MainWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ui = Ui_Dialog()
        self._ui.setupUi(self)
 
        # Mirror every widget built by setupUi onto the window itself, matching
        # the old QUiLoader behaviour (self.ui.<objectName> attribute access).
        for name, obj in vars(self._ui).items():
            if name.startswith("_"):
                continue
            setattr(self, name, obj)