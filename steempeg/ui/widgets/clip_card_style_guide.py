"""ClipCard style pictures: the ? card, and the panel beside the open list.

The open list shows the row under the pointer. The ? circle keeps explaining
the style that is already chosen.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut

_BLURB_W = 196


def _mode_key(value: object) -> str:
    """The list id, without any extra context packed after a pipe."""
    return str(value or "").split("|", 1)[0]


def clip_card_style_copy(style: str) -> tuple[str, str, str]:
    """Returns the mode name, the short line, and the ? explanation."""
    style = str(style or "")
    if style == "square":
        return (
            "Square",
            "Every corner is square.",
            "Every corner is square.\n"
            "A card above or below does not change the shape.",
        )
    if style == "round":
        return (
            "Round",
            "Every corner is round.",
            "Every corner is round.\n"
            "A card above or below does not change the shape.",
        )
    return (
        "SteempegUI",
        "Corners follow the card above and the card below.",
        "No card above: square top.\n"
        "A card above: round top.\n"
        "A card below: round bottom.\n"
        "No card below: square bottom.",
    )


def clip_card_style_help(style: str) -> str:
    """Explanation the ? circle shows for the style that is already chosen."""
    return clip_card_style_copy(style)[2]


def _corner_path(rect: QRectF, radii: tuple[float, float, float, float]) -> QPainterPath:
    """Rounded rectangle. Radii are top-left, top-right, bottom-right, bottom-left."""
    tl, tr, br, bl = radii
    path = QPainterPath()
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path.moveTo(x + tl, y)
    path.lineTo(x + w - tr, y)
    if tr:
        path.arcTo(QRectF(x + w - 2 * tr, y, 2 * tr, 2 * tr), 90, -90)
    path.lineTo(x + w, y + h - br)
    if br:
        path.arcTo(QRectF(x + w - 2 * br, y + h - 2 * br, 2 * br, 2 * br), 0, -90)
    path.lineTo(x + bl, y + h)
    if bl:
        path.arcTo(QRectF(x, y + h - 2 * bl, 2 * bl, 2 * bl), 270, -90)
    path.lineTo(x, y + tl)
    if tl:
        path.arcTo(QRectF(x, y, 2 * tl, 2 * tl), 180, -90)
    path.closeSubpath()
    return path


class ClipCardStyleDiagram(QWidget):
    """Six mini cards, two columns. Corners follow one ClipCard style."""

    _COLS = 2
    _ROWS = 3
    _CARD_W = 40
    _CARD_H = 28
    _GAP = 5
    _RADIUS = 7.0

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        width = self._COLS * self._CARD_W + (self._COLS - 1) * self._GAP
        height = self._ROWS * self._CARD_H + (self._ROWS - 1) * self._GAP
        self.setFixedSize(width, height)
        self._style = "steempeg_ui"
        self.setStyleSheet("background: transparent;")

    def set_style(self, style: str) -> None:
        """Redraws the six cards for ``steempeg_ui``, ``square``, or ``round``."""
        self._style = style or "steempeg_ui"
        self.update()

    def _radii(self, row: int) -> tuple[float, float, float, float]:
        """Returns this row's corner radii for the style being shown."""
        radius = self._RADIUS
        if self._style == "round":
            return (radius, radius, radius, radius)
        if self._style == "square":
            return (0.0, 0.0, 0.0, 0.0)
        if row <= 0:
            return (0.0, 0.0, radius, radius)
        if row >= self._ROWS - 1:
            return (radius, radius, 0.0, 0.0)
        return (radius, radius, radius, radius)

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        thumb = QColor("#8b74c4")
        footer = QColor("#4a4560")
        edge = QColor("#c4b6e4")
        for row in range(self._ROWS):
            radii = self._radii(row)
            for col in range(self._COLS):
                x = col * (self._CARD_W + self._GAP)
                y = row * (self._CARD_H + self._GAP)
                rect = QRectF(x + 0.5, y + 0.5, self._CARD_W - 1, self._CARD_H - 1)
                path = _corner_path(rect, radii)
                painter.save()
                painter.setClipPath(path)
                painter.fillPath(path, footer)
                painter.fillRect(
                    QRectF(rect.x(), rect.y(), rect.width(), rect.height() * 0.62),
                    thumb,
                )
                painter.restore()
                painter.setPen(QPen(edge, 1.0))
                painter.drawPath(path)
        painter.end()

