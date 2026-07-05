"""A QLabel that elides its text in the middle and keeps the full text in a tooltip."""
import re

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QLabel, QStyleOptionFrame

_COLOR_RE = re.compile(r"color:\s*([^;}\s]+)", re.IGNORECASE)


class ElidedLabel(QLabel):
    """Shows '...' in the middle of text that is too wide, with the full text on hover."""

    _MAX_LAYOUT_RETRIES = 8

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._layout_retry_pending = False
        self._layout_retries = 0
        if text:
            self.setText(text)

    def setStyleSheet(self, stylesheet):
        super().setStyleSheet(stylesheet)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def setText(self, text):
        self._full_text = text
        super().setText(text)  # let Qt compute the preferred size
        self.setToolTip(text)  # hover over the cut text to see the full path
        self._layout_retries = 0
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() > 1:
            self._layout_retries = 0
        self.update()

    def sizeHint(self):
        sh = super().sizeHint()
        return QSize(0, sh.height())

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        return QSize(0, sh.height())

    def _schedule_layout_repaint(self) -> None:
        if self._layout_retry_pending:
            return
        if self._layout_retries >= self._MAX_LAYOUT_RETRIES:
            return
        self._layout_retry_pending = True
        QTimer.singleShot(0, self._repaint_after_layout)

    def _repaint_after_layout(self) -> None:
        self._layout_retry_pending = False
        self._layout_retries += 1
        self.update()

    def _text_color(self) -> QColor:
        match = _COLOR_RE.search(self.styleSheet() or "")
        if match is not None:
            color = QColor(match.group(1).strip())
            if color.isValid():
                return color

        opt = QStyleOptionFrame()
        self.initStyleOption(opt)
        color = opt.palette.color(QPalette.ColorRole.Text)
        if color.isValid():
            return color
        return self.palette().color(QPalette.ColorRole.WindowText)

    def paintEvent(self, event):
        rect = self.contentsRect()
        if rect.width() <= 1:
            if self._full_text:
                self._schedule_layout_repaint()
            return

        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self._text_color())
        metrics = self.fontMetrics()
        elided = metrics.elidedText(
            self._full_text, Qt.TextElideMode.ElideMiddle, rect.width(),
        )
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, elided)
