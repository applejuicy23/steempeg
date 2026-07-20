"""Event filter that collapses the bottom pane when the settings tabs are hidden.

Installed on the settings tab widget: when it hides, the vertical splitter
collapses its bottom pane; when it shows again, the pane is restored.
"""
from PySide6.QtCore import QEvent, QObject

from steempeg.ui.layout_defaults import restore_v_splitter_sizes


class HideWatcher(QObject):
    def __init__(self, splitter):
        super().__init__()
        self.splitter = splitter
        self._saved_sizes = None
        self._suppressed = False

    def set_suppressed(self, suppressed: bool):
        self._suppressed = suppressed

    def eventFilter(self, obj, event):
        if self._suppressed:
            return False
        if event.type() == QEvent.Type.Hide:
            sizes = self.splitter.sizes()
            if len(sizes) >= 2 and sizes[1] > 0:
                self._saved_sizes = sizes
            total = sum(sizes) if sum(sizes) > 0 else max(self.splitter.height(), 1)
            self.splitter.setSizes([int(total), 0])
        elif event.type() == QEvent.Type.Show:
            if self._saved_sizes and len(self._saved_sizes) >= 2 and self._saved_sizes[1] > 0:
                self.splitter.setSizes(self._saved_sizes)
            else:
                self.splitter.setSizes(restore_v_splitter_sizes(self.splitter.height()))
        return False
