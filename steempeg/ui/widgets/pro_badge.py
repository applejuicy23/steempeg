"""Steempeg PRO brand chip — rounded rect, bold PRO.

Draft seed for v50: title bar + splash only. Not a second app logo.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QSize
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

# Warm red chip — sibling to free violet, not the whole UI theme yet.
PRO_RED = QColor("#d64545")
PRO_RED_SOFT = QColor("#e85a5a")
PRO_TEXT = QColor("#ffffff")


class ProBadge(QWidget):
    """Compact ``PRO`` plaque. ``size``: ``title`` (bar) | ``splash`` (larger)."""

    def __init__(
        self,
        *,
        size: str = "title",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._size = "splash" if str(size).strip().lower() == "splash" else "title"
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip("Steempeg PRO")
        self._apply_metrics()

    def _apply_metrics(self) -> None:
        if self._size == "splash":
            self._pad_h = 7
            self._pad_v = 3
            self._radius = 5.0
            self._font_px = 11
            self._weight = QFont.Weight.Bold
        else:
            self._pad_h = 5
            self._pad_v = 2
            self._radius = 4.0
            self._font_px = 9
            self._weight = QFont.Weight.Bold
        font = QFont()
        font.setFamilies(["Cascadia UI", "Segoe UI Variable", "Segoe UI"])
        font.setPixelSize(self._font_px)
        font.setWeight(self._weight)
        self._font = font
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance("PRO")
        text_h = fm.height()
        self.setFixedSize(
            text_w + self._pad_h * 2,
            max(14, text_h + self._pad_v * 2),
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.size()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        p.fillPath(path, PRO_RED)
        p.setPen(PRO_TEXT)
        p.setFont(self._font)
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "PRO")
