"""A QLabel that elides its text in the middle and keeps the full text in a tooltip."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel


class ElidedLabel(QLabel):
    """Shows '...' in the middle of text that is too wide, with the full text on hover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""

    def setText(self, text):
        self._full_text = text
        super().setText(text)  # let Qt compute the preferred size
        self.setToolTip(text)  # hover over the cut text to see the full path
        self.update()

    def minimumSizeHint(self):
        # Let the layout shrink this widget below its full text width.
        return QSize(50, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = self.fontMetrics()
        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, self.width())
        painter.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, elided)
