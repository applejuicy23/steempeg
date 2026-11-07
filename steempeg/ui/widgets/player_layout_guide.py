"""A small drawing of the player stack for Layout and Outline.

Reunited is one piece. Fractured leaves a gap between the header, the
video, and the bar. Outline draws a line around that piece, around each
part, or only around the header and the bar.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.clip_card_style_guide import ClipCardStyleCombo

_REUNITED = "reunited"
_FRACTURED = "fractured"
_WITH = "with_lines"
_WITHOUT = "without_lines"
_CHROME = "chrome_only"


def _split_player_style(style: str) -> tuple[str, str]:
    """Returns ``(layout, outline)`` from a packed preview value."""
    text = str(style or "")
    if "|" not in text:
        if text in (_FRACTURED, _REUNITED):
            return text, _WITH
        return _REUNITED, text or _WITH
    left, right = text.split("|", 1)
    if left in (_FRACTURED, _REUNITED):
        return left, right or _WITH
    return right or _REUNITED, left or _WITH


def player_layout_copy(style: str) -> tuple[str, str, str]:
    """Name, short line, and ? text for Reunited or Fractured."""
    layout, _outline = _split_player_style(style)
    if layout == _FRACTURED:
        return (
            "Fractured",
            "Header, video, and the bar sit apart.",
            "The header, the video, and the player bar each sit on their own.",
        )
    return (
        "Reunited",
        "Header, video, and the bar sit as one piece.",
        "The header, the video, and the player bar sit together as one piece.",
    )


def player_layout_help(style: str) -> str:
    """Explanation the ? circle shows for the layout that is already chosen."""
    return player_layout_copy(style)[2]


def player_outline_copy(style: str) -> tuple[str, str, str]:
    """Name, short line, and ? text for one outline mode."""
    _layout, outline = _split_player_style(style)
    if outline == _WITHOUT:
        return (
            "Without lines",
            "No outline.",
            "No line around the header, the video, or the player bar.",
        )
    if outline == _CHROME:
        return (
            "With lines, not wrapping the video",
            "A line on the header and the bar. The video stays open.",
            "The header and the player bar have a line. The video does not.",
        )
    return (
        "With lines",
        "A line around the player.",
        "A line around the whole player. Fractured draws that line on each part.",
    )


def player_outline_help(style: str) -> str:
    """Explanation the ? circle shows for the outline that is already chosen."""
    return player_outline_copy(style)[2]


class PlayerStackDiagram(QWidget):
    """Header, a play button, and a three-button bar."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layout = _REUNITED
        self._outline = _WITH
        self.setFixedSize(168, 128)

    def set_style(self, style: str) -> None:
        """Redraws for ``layout|outline`` or ``outline|layout``."""
        self._layout, self._outline = _split_player_style(style)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fractured = self._layout == _FRACTURED
        pad = 4.0
        gap = 6.0 if fractured else 0.0
        width = self.width() - pad * 2
        height = self.height() - pad * 2
        header_h = 22.0
        footer_h = 28.0
        video_h = height - header_h - footer_h - gap * 2
        x = pad
        y = pad
        header = QRectF(x, y, width, header_h)
        video = QRectF(x, y + header_h + gap, width, max(20.0, video_h))
        footer = QRectF(x, video.bottom() + gap, width, footer_h)
        radius = 6.0
        chrome = QColor("#4a4560")
        picture = QColor("#8b74c4")
        if fractured:
            self._plate(painter, header, radius, chrome, self._stroke("header"))
            self._plate(painter, video, radius, picture, self._stroke("video"))
            self._plate(painter, footer, radius, chrome, self._stroke("footer"))
        else:
            whole = QRectF(x, y, width, footer.bottom() - y)
            outer = QPainterPath()
            outer.addRoundedRect(whole, radius, radius)
            painter.save()
            painter.setClipPath(outer)
            painter.fillRect(header, chrome)
            painter.fillRect(video, picture)
            painter.fillRect(footer, chrome)
            painter.restore()
            if self._outline == _WITH:
                self._stroke_path(painter, outer)
            elif self._outline == _CHROME:
                self._stroke_path(painter, self._top_cap(header, radius))
                self._stroke_path(painter, self._bottom_cap(footer, radius))
        self._play(painter, video)
        self._controls(painter, footer)
        painter.end()

    def _stroke(self, part: str) -> bool:
        """Whether this part gets a line."""
        if self._outline == _WITHOUT:
            return False
        if self._outline == _CHROME:
            return part in ("header", "footer")
        return True

    def _plate(
        self, painter: QPainter, rect: QRectF, radius: float, fill: QColor, stroke: bool
    ) -> None:
        """Fills one separated block. ``stroke`` draws its outline."""
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, fill)
        if stroke:
            self._stroke_path(painter, path)

    def _stroke_path(self, painter: QPainter, path: QPainterPath) -> None:
        """Draws the outline line."""
        painter.setPen(QPen(QColor("#c4b6e4"), 1.25))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _top_cap(self, rect: QRectF, radius: float) -> QPainterPath:
        """Header outline: round on top, square where it meets the video."""
        path = QPainterPath()
        path.moveTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + radius)
        path.arcTo(QRectF(rect.left(), rect.top(), radius * 2, radius * 2), 180, -90)
        path.lineTo(rect.right() - radius, rect.top())
        path.arcTo(
            QRectF(rect.right() - radius * 2, rect.top(), radius * 2, radius * 2),
            90,
            -90,
        )
        path.lineTo(rect.right(), rect.bottom())
        path.closeSubpath()
        return path

    def _bottom_cap(self, rect: QRectF, radius: float) -> QPainterPath:
        """Bar outline: square where it meets the video, round on the bottom."""
        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right(), rect.top())
        path.lineTo(rect.right(), rect.bottom() - radius)
        path.arcTo(
            QRectF(rect.right() - radius * 2, rect.bottom() - radius * 2, radius * 2, radius * 2),
            0,
            -90,
        )
        path.lineTo(rect.left() + radius, rect.bottom())
        path.arcTo(
            QRectF(rect.left(), rect.bottom() - radius * 2, radius * 2, radius * 2),
            270,
            -90,
        )
        path.closeSubpath()
        return path

    def _play(self, painter: QPainter, video: QRectF) -> None:
        """A circle with a triangle pointing right."""
        d = 22.0
        circle = QRectF(
            video.center().x() - d / 2.0,
            video.center().y() - d / 2.0,
            d,
            d,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3d2a68"))
        painter.drawEllipse(circle)
        painter.setBrush(QColor("#f4efff"))
        tri = QPainterPath()
        cx, cy = circle.center().x() + 1.0, circle.center().y()
        tri.moveTo(cx - 4.0, cy - 5.0)
        tri.lineTo(cx + 6.0, cy)
        tri.lineTo(cx - 4.0, cy + 5.0)
        tri.closeSubpath()
        painter.drawPath(tri)

    def _controls(self, painter: QPainter, footer: QRectF) -> None:
        """Three doodle buttons: +15, play, −15."""
        font = QFont(tok.FONT_FAMILIES[0])
        font.setPixelSize(7)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        labels = ("+15", "", "−15")
        d = 16.0
        gap = 6.0
        total = d * 3 + gap * 2
        x = footer.center().x() - total / 2.0
        y = footer.center().y() - d / 2.0
        for index, label in enumerate(labels):
            rect = QRectF(x + index * (d + gap), y, d, d)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#6a5a94"))
            painter.drawEllipse(rect)
            painter.setPen(QColor("#f4efff"))
            if label:
                painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label)
            else:
                tri = QPainterPath()
                cx, cy = rect.center().x() + 0.6, rect.center().y()
                tri.moveTo(cx - 2.5, cy - 3.2)
                tri.lineTo(cx + 3.4, cy)
                tri.lineTo(cx - 2.5, cy + 3.2)
                tri.closeSubpath()
                painter.setBrush(QColor("#f4efff"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPath(tri)


class PlayerLayoutCombo(ClipCardStyleCombo):
    """Player layout list. The drawing uses the outline chosen below it."""

    def __init__(self, parent: QWidget | None = None, *, outline_of=None):
        super().__init__(
            parent,
            diagram_factory=PlayerStackDiagram,
            copy_of=player_layout_copy,
        )
        self._outline_of = outline_of

    def _guide_style(self, raw: str) -> str:
        """Packs the current outline so the lines match that setting."""
        outline = _WITH
        if callable(self._outline_of):
            outline = str(self._outline_of() or outline)
        return f"{raw}|{outline}"


class PlayerOutlineCombo(ClipCardStyleCombo):
    """Outline list. The drawing uses whichever Layout is chosen above it."""

    def __init__(self, parent: QWidget | None = None, *, layout_of=None):
        super().__init__(
            parent,
            diagram_factory=PlayerStackDiagram,
            copy_of=player_outline_copy,
        )
        self._layout_of = layout_of

    def _guide_style(self, raw: str) -> str:
        """Packs the current layout in front, so the check still sees the outline."""
        layout = _REUNITED
        if callable(self._layout_of):
            layout = str(self._layout_of() or layout)
        return f"{raw}|{layout}"
