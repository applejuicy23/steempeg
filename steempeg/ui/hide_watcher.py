"""Event filter that collapses the bottom pane when the settings tabs are hidden.

Installed on the settings tab widget: when it hides, the vertical splitter
collapses its bottom pane; when it shows again, the pane is restored.
"""
from PySide6.QtCore import QEvent, QObject


class HideWatcher(QObject):
    def __init__(self, splitter):
        super().__init__()
        self.splitter = splitter

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Hide:
            self.splitter.setSizes([10000, 0])  # Collapse the bottom pane
        elif event.type() == QEvent.Type.Show:
            self.splitter.setSizes([750, 250])  # Expand the bottom pane back
        return False  # Do not block the actual hide/show event
