"""Semi-transparent loading overlay for the MPV video surface."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaybackLoadingOverlay(QWidget):
    """Spinner + label centered over the 16:9 video area."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 64);")
        self._angle = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setAlignment(Qt.AlignCenter)

        self._label = QLabel("Buffering…")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "color: #eeeeee; font-size: 13px; font-weight: bold; background: transparent;"
        )
        root.addWidget(self._label)

        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(33)
        self._spin_timer.timeout.connect(self._advance_spinner)
        self.hide()

    def _advance_spinner(self):
        self._angle = (self._angle + 24) % 360
        self.update()

    def show_loading(self, message="Buffering…"):
        self._label.setText(message)
        if not self._spin_timer.isActive():
            self._spin_timer.start()
        if not self.isVisible():
            self.show()
        self.raise_()

    def hide_loading(self):
        self._spin_timer.stop()
        self.hide()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.width() // 2
        cy = max(36, self.height() // 2 - 20)
        pen = QPen(QColor("#b29ae7"))
        pen.setWidth(4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(cx - 18, cy - 18, 36, 36, self._angle * 16, 110 * 16)
