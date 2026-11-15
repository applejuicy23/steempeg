"""Apply action with an indeterminate, elapsed-time-driven loading ring."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QPushButton


class ApplyButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("Apply", parent)
        self._busy = False
        self._started = 0.0
        self.setIconSize(QSize(16, 16))
        self.setMinimumWidth(104)
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(33)
        self._spinner_timer.timeout.connect(self._paint_spinner)

    def set_busy(self, busy: bool):
        if self._busy == bool(busy):
            return
        self._busy = bool(busy)
        if self._busy:
            self._started = time.perf_counter()
            self._paint_spinner()
            self._spinner_timer.start()
        else:
            self._spinner_timer.stop()
            self.setIcon(QIcon())
        self.setAccessibleDescription("Applying settings" if self._busy else "")
        # Paint the busy state before entering synchronous Qt style work.
        if self.isVisible():
            self.repaint()

    def _paint_spinner(self):
        elapsed = time.perf_counter() - self._started
        pixmap = QPixmap(32, 32)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#c9b0ff"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        span = 180 + 90 * math.sin(elapsed * math.tau)
        painter.drawArc(QRectF(2, 2, 12, 12), round(-elapsed * 360 * 16), round(-span * 16))
        painter.end()
        icon = QIcon()
        icon.addPixmap(pixmap, QIcon.Mode.Normal)
        icon.addPixmap(pixmap, QIcon.Mode.Disabled)
        self.setIcon(icon)
