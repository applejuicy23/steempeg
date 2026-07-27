"""Reusable loading veil + arc spinner for clip/queue thumbnails."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class ThumbLoadingOverlay(QWidget):
    """Dim veil + purple arc spinner — same language as timeline hover preview.

    Optional ``percent`` draws a centered label (e.g. Linux DASH remux progress).
    """

    def __init__(self, parent=None, *, radius: float = 14.0, pen_w: int = 4):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._angle = 0
        self._radius = float(radius)
        self._pen_w = int(pen_w)
        self._percent: int | None = None
        self._spin = QTimer(self)
        self._spin.setInterval(33)
        self._spin.timeout.connect(self._advance)
        self.hide()

    def _advance(self) -> None:
        self._angle = (self._angle + 24) % 360
        self.update()

    def set_progress(self, percent: int | None) -> None:
        """0–100 while known; ``None`` = indeterminate spinner only."""
        if percent is None:
            self._percent = None
        else:
            self._percent = max(0, min(100, int(percent)))
        self.update()

    def start(self, *, percent: int | None = None) -> None:
        self.set_progress(percent)
        if not self._spin.isActive():
            self._spin.start()
        self.show()
        self.raise_()

    def stop(self) -> None:
        self._spin.stop()
        self._percent = None
        self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 130))

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        # Leave room for a percent label under the arc when present.
        radius = min(self._radius, min(self.width(), self.height()) * 0.18)
        if self._percent is not None:
            cy = self.height() * 0.38
        pen = QPen(QColor("#b29ae7"))
        pen.setWidth(self._pen_w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(
            int(cx - radius),
            int(cy - radius),
            int(2 * radius),
            int(2 * radius),
            self._angle * 16,
            110 * 16,
        )
        if self._percent is not None:
            painter.setPen(QColor("#f0f0f0"))
            font = QFont()
            font.setFamilies(["Segoe UI", "Noto Sans", "Arial"])
            font.setBold(True)
            font.setPixelSize(max(11, min(16, int(self.height() * 0.18))))
            painter.setFont(font)
            painter.drawText(
                self.rect().adjusted(0, int(self.height() * 0.12), 0, 0),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                f"{self._percent}%",
            )
