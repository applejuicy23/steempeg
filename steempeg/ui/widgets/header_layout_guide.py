"""Mini player-header strip for the Layout setting.

Steam-like keeps the loupe and 100% on the left and the title in the center.
SteempegUI keeps the title, date, and duration on the left, and the loupe
with the tools on the right. The queue chip is left out of the sample.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.clip_card_style_guide import ClipCardStyleCombo

_STEAM = "steam_like"


def header_layout_copy(style: str) -> tuple[str, str, str]:
    """Returns the mode name, the short line, and the ? explanation."""
    if str(style or "") == "steempeg_ui":
        return (
            "SteempegUI",
            "Title, date, and duration on the left. Zoom sits with the tools.",
            "Logo and Game sit on the left, with the date and duration beside them. "
            "Healthy stays next. Loupe, 100%, settings, and close sit on the right.",
        )
    return (
        "Steam-like",
        "Zoom on the left. The game name sits in the center.",
        "Loupe and 100% sit on the left. Logo and Game sit in the center. "
        "The date and duration stay in the info tip. "
        "Healthy, settings, and close sit on the right.",
    )


def header_layout_help(style: str) -> str:
    """Explanation the ? circle shows for the layout that is already chosen."""
    return header_layout_copy(style)[2]


class HeaderLayoutDiagram(QWidget):
    """One header bar. The order of the chips follows the chosen layout.

    A value ``small|steam_like`` also scales the bar. A bare layout name
    stays at the Large size, which is the Layout setting's own sample.
    """

    _W = 460
    _H = 40
    _SCALES = {"large": 1.0, "medium": 0.86, "small": 0.72}

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._style = _STEAM
        self._size = "large"
        self._scale = 1.0
        self.setFixedSize(self._W, self._H)
        self._ready = False

    def set_style(self, style: str) -> None:
        """Redraws the bar. ``size|layout`` picks both the order and the height."""
        text = str(style or "")
        if "|" in text:
            size, layout = text.split("|", 1)
            self._size = size if size in self._SCALES else "large"
            self._style = layout or _STEAM
        else:
            self._size = "large"
            self._style = text or _STEAM
        self._scale = self._SCALES[self._size]
        self.setFixedSize(
            max(1, int(round(self._W * self._scale))),
            max(1, int(round(self._H * self._scale))),
        )
        self.update()

    def _assets(self) -> None:
        """Loads the real header glyphs once. They are tiny copies of the chips."""
        if self._ready:
            return
        from steempeg.ui.icon_assets import (
            load_pixmap,
            loupe_icon,
            playinfo_pixmap,
            preview_settings_icon,
            tinted_pixmap,
        )
        from steempeg.ui.icon_utils import app_logo_pixmap

        self._loupe = loupe_icon(11, color="#ffffff").pixmap(11, 11)
        self._gear = preview_settings_icon(11).pixmap(11, 11)
        self._close = tinted_pixmap("cancel.png", "#e05555", 11)
        self._health = load_pixmap("success.png", 10)
        self._info = playinfo_pixmap("#c8c8c8", 11)
        logo = app_logo_pixmap(14, dpr=1.0)
        self._logo = logo if logo is not None else self._loupe
        self._name_font = QFont(tok.FONT_FAMILIES[0])
        self._name_font.setPixelSize(10)
        self._name_font.setWeight(QFont.Weight.Bold)
        self._meta_font = QFont(tok.FONT_FAMILIES[0])
        self._meta_font.setPixelSize(9)
        self._chip_font = QFont(tok.FONT_FAMILIES[0])
        self._chip_font.setPixelSize(9)
        self._chip_font.setWeight(QFont.Weight.Bold)
        self._ready = True

    def _advance(self, font: QFont, text: str) -> int:
        return QFontMetrics(font).horizontalAdvance(text)

    def _pieces(self) -> list[tuple[str, int]]:
        """Chip order for the style. ``gap`` takes the leftover width."""
        self._assets()
        pct = self._advance(self._chip_font, "100%") + 12
        name = self._advance(self._name_font, "Game") + 2
        healthy = self._advance(self._chip_font, "Healthy") + 22
        if self._style == "steempeg_ui":
            date = "11 May 02:28"
            dur = "2:23"
            return [
                ("logo", 14),
                ("name", name),
                ("dot", self._advance(self._meta_font, "·") + 4),
                ("date", self._advance(self._meta_font, date) + 2),
                ("dot", self._advance(self._meta_font, "·") + 4),
                ("dur", self._advance(self._meta_font, dur) + 2),
                ("info", 12),
                ("gap", 0),
                ("healthy", healthy),
                ("divider", 1),
                ("loupe", 18),
                ("pct", pct),
                ("gear", 18),
                ("close", 18),
            ]
        return [
            ("loupe", 18),
            ("pct", pct),
            ("gap", 0),
            ("logo", 14),
            ("name", name),
            ("info", 12),
            ("gap", 0),
            ("healthy", healthy),
            ("divider", 1),
            ("gear", 18),
            ("close", 18),
        ]

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.scale(self._scale, self._scale)
        bar = QRectF(0.5, 0.5, self._W - 1.0, self._H - 1.0)
        path = QPainterPath()
        path.addRoundedRect(bar, 8.0, 8.0)
        painter.fillPath(path, QColor("#16161c"))
        painter.setPen(QPen(QColor("#3a3a44"), 1.0))
        painter.drawPath(path)

        pieces = self._pieces()
        gap_n = sum(1 for kind, _w in pieces if kind == "gap")
        fixed = sum(w for kind, w in pieces if kind != "gap")
        boxes = sum(1 for kind, _w in pieces if kind != "gap")
        pad = 6
        between = 4
        inner = self._W - pad * 2
        free = inner - fixed - between * max(0, boxes + gap_n - 1)
        gap_w = max(6.0, free / gap_n) if gap_n else 0.0
        x = float(pad)
        cy = self._H / 2.0
        seen = 0
        total = boxes + gap_n
        for kind, width in pieces:
            span = gap_w if kind == "gap" else float(width)
            if kind != "gap":
                self._paint_piece(painter, kind, x, cy, float(width))
            x += span
            seen += 1
            if seen < total:
                x += between
        painter.end()

    def _chip(
        self, painter: QPainter, x: float, cy: float, w: float, border: str, fill: QColor
    ) -> QRectF:
        """Draws a small rounded plaque and returns its rectangle."""
        h = 20.0
        rect = QRectF(x, cy - h / 2.0, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, 4.0, 4.0)
        painter.setPen(QPen(QColor(border), 1.0))
        painter.setBrush(fill)
        painter.drawPath(path)
        return rect

    def _icon(self, painter: QPainter, pix, rect: QRectF) -> None:
        """Centers a glyph inside ``rect``."""
        if pix is None or pix.isNull():
            return
        painter.drawPixmap(
            int(rect.center().x() - pix.width() / 2),
            int(rect.center().y() - pix.height() / 2),
            pix,
        )

    def _paint_piece(self, painter: QPainter, kind: str, x: float, cy: float, w: float) -> None:
        """Draws one sample chip."""
        if kind == "loupe":
            rect = self._chip(painter, x, cy, w, "#b29ae7", QColor(178, 154, 231, 46))
            self._icon(painter, self._loupe, rect)
            return
        if kind == "pct":
            rect = self._chip(painter, x, cy, w, "#b29ae7", QColor(178, 154, 231, 46))
            painter.setFont(self._chip_font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "100%")
            return
        if kind == "logo":
            pix = self._logo
            painter.drawPixmap(int(x), int(cy - pix.height() / 2), pix)
            return
        if kind == "name":
            painter.setFont(self._name_font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                QRectF(x, cy - 8, w, 16),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                "Game",
            )
            return
        if kind == "info":
            pix = self._info
            painter.drawPixmap(int(x), int(cy - pix.height() / 2), pix)
            return
        if kind in ("dot", "date", "dur"):
            text = {"dot": "·", "date": "11 May 02:28", "dur": "2:23"}[kind]
            painter.setFont(self._meta_font)
            painter.setPen(QColor("#a8a8a8"))
            painter.drawText(
                QRectF(x, cy - 8, w, 16),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                text,
            )
            return
        if kind == "healthy":
            rect = self._chip(painter, x, cy, w, "#4caf50", QColor(76, 175, 80, 56))
            pix = self._health
            painter.drawPixmap(int(rect.left() + 4), int(cy - pix.height() / 2), pix)
            painter.setFont(self._chip_font)
            painter.setPen(QColor("#4caf50"))
            painter.drawText(
                rect.adjusted(16, 0, -2, 0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                "Healthy",
            )
            return
        if kind == "divider":
            painter.setPen(QPen(QColor("#4a4a4a"), 1.0))
            painter.drawLine(int(x), int(cy - 7), int(x), int(cy + 7))
            return
        if kind == "gear":
            rect = self._chip(painter, x, cy, w, "#4a9fd8", QColor(74, 159, 216, 46))
            self._icon(painter, self._gear, rect)
            return
        if kind == "close":
            rect = self._chip(painter, x, cy, w, "#e05555", QColor(224, 85, 85, 46))
            self._icon(painter, self._close, rect)

