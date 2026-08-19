"""Reusable loading veil + determinate percent ring for clip/queue thumbnails."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QWidget

_ACCENT = QColor("#b29ae7")
_TRACK = QColor(178, 154, 231, 55)  # same hue, faint track
_FULL_CIRCLE_16 = 360 * 16


def _asymmetric_round_rect(
    w: float, h: float, tl: float, tr: float, br: float, bl: float
) -> QPainterPath:
    """Clockwise path with independent corner radii (CSS-style tl/tr/br/bl)."""
    path = QPainterPath()
    if w <= 0 or h <= 0:
        return path
    tl = max(0.0, min(float(tl), w / 2.0, h / 2.0))
    tr = max(0.0, min(float(tr), w / 2.0, h / 2.0))
    br = max(0.0, min(float(br), w / 2.0, h / 2.0))
    bl = max(0.0, min(float(bl), w / 2.0, h / 2.0))
    path.moveTo(tl, 0.0)
    path.lineTo(w - tr, 0.0)
    if tr > 0:
        path.arcTo(w - 2.0 * tr, 0.0, 2.0 * tr, 2.0 * tr, 90.0, -90.0)
    else:
        path.lineTo(w, 0.0)
    path.lineTo(w, h - br)
    if br > 0:
        path.arcTo(w - 2.0 * br, h - 2.0 * br, 2.0 * br, 2.0 * br, 0.0, -90.0)
    else:
        path.lineTo(w, h)
    path.lineTo(bl, h)
    if bl > 0:
        path.arcTo(0.0, h - 2.0 * bl, 2.0 * bl, 2.0 * bl, 270.0, -90.0)
    else:
        path.lineTo(0.0, h)
    path.lineTo(0.0, tl)
    if tl > 0:
        path.arcTo(0.0, 0.0, 2.0 * tl, 2.0 * tl, 180.0, -90.0)
    else:
        path.lineTo(0.0, 0.0)
    path.closeSubpath()
    return path


class ThumbLoadingOverlay(QWidget):
    """Dim veil + centered percent with a purple arc that fills 0–100.

    ``percent`` is the same value already wired from probe/mpv (not faked).
    Unknown / start is drawn as ``0%`` and an empty track. Corner radii clip
    the dark fill to the host card (ClipCard thumb plan).
    """

    def __init__(self, parent=None, *, radius: float = 14.0, pen_w: int = 4):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._radius = float(radius)
        self._pen_w = int(pen_w)
        self._percent: int = 0
        self._clip_radii: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self.hide()

    def set_clip_radii(self, tl: float, tr: float, br: float, bl: float) -> None:
        """Clip the veil to the same corner radii as the thumbnail well."""
        radii = (max(0.0, float(tl)), max(0.0, float(tr)), max(0.0, float(br)), max(0.0, float(bl)))
        if radii == self._clip_radii:
            return
        self._clip_radii = radii
        self._apply_clip_mask()
        self.update()

    def _apply_clip_mask(self) -> None:
        w, h = self.width(), self.height()
        tl, tr, br, bl = self._clip_radii
        if w <= 0 or h <= 0 or (tl <= 0 and tr <= 0 and br <= 0 and bl <= 0):
            self.clearMask()
            return
        path = _asymmetric_round_rect(float(w), float(h), tl, tr, br, bl)
        # Windows: widget mask clips fill + any child paint to the card curve.
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_clip_mask()

    def set_progress(self, percent: int | None) -> None:
        """0–100 from the host; ``None`` / unknown draws as an empty 0% ring."""
        if percent is None:
            self._percent = 0
        else:
            self._percent = max(0, min(100, int(percent)))
        self.update()

    def start(self, *, percent: int | None = None) -> None:
        self.set_progress(percent)
        self.show()
        self.raise_()

    def stop(self) -> None:
        self._percent = 0
        self.hide()

    def _ring_metrics(self) -> tuple[float, float, float, int]:
        """Centered ring large enough to wrap ``100%``; constructor radius is a floor."""
        side = float(min(self.width(), self.height()))
        pen_w = float(self._pen_w)
        max_r = max(8.0, side / 2.0 - pen_w - 3.0)
        radius = min(max_r, max(self._radius, side * 0.32))
        inner = max(10.0, 2.0 * radius - pen_w * 2.0 - 6.0)
        font_px = max(9, min(int(inner * 0.38), int(side * 0.28)))
        return self.width() / 2.0, self.height() / 2.0, radius, font_px

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        tl, tr, br, bl = self._clip_radii
        if tl > 0 or tr > 0 or br > 0 or bl > 0:
            path = _asymmetric_round_rect(rect.width(), rect.height(), tl, tr, br, bl)
            painter.setClipPath(path)
            painter.fillPath(path, QColor(0, 0, 0, 130))
        else:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 130))

        cx, cy, radius, font_px = self._ring_metrics()
        arc_rect = QRectF(cx - radius, cy - radius, 2.0 * radius, 2.0 * radius)
        pct = self._percent

        painter.setBrush(Qt.BrushStyle.NoBrush)
        track = QPen(_TRACK)
        track.setWidth(self._pen_w)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawEllipse(arc_rect)

        # Qt: 0° is 3 o'clock, positive span is CCW. Start at 12 o'clock, fill clockwise.
        if pct >= 100:
            fill = QPen(_ACCENT)
            fill.setWidth(self._pen_w)
            fill.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(fill)
            painter.drawEllipse(arc_rect)
        elif pct > 0:
            fill = QPen(_ACCENT)
            fill.setWidth(self._pen_w)
            fill.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(fill)
            span = -int(round(pct * _FULL_CIRCLE_16 / 100.0))
            painter.drawArc(arc_rect, 90 * 16, span)

        painter.setPen(QColor("#f0f0f0"))
        font = QFont()
        font.setFamilies(["Segoe UI", "Noto Sans", "Arial"])
        font.setBold(True)
        font.setPixelSize(font_px)
        painter.setFont(font)
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), f"{pct}%")
