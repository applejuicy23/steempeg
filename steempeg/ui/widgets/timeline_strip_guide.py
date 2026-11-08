"""A small timeline ruler showing the actual Strip size metrics."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from steempeg.ui import design_tokens as tok
from steempeg.ui.timeline_strip_size import metrics_for, normalize_timeline_strip_size
from steempeg.ui.widgets.clip_card_style_guide import ClipCardStyleCombo


STRIP_SIZE_HELP = (
    "Time labels and tick marks under the scrubber. "
    "The progress track stays the same height."
)


def timeline_strip_copy(style: str) -> tuple[str, str, str]:
    """Names the chosen size without explaining individual sizes."""
    return normalize_timeline_strip_size(style).title(), "", ""


class TimelineStripDiagram(QWidget):
    """Fixed pins and progress track, with a ruler sized like the real player."""

    _SCALE = 0.8
    _WIDTH = 340

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.set_style("large")

    def set_style(self, style: str) -> None:
        """Uses the same ticks, type, and padding as the player preference."""
        self._metrics = metrics_for(style)
        self._font = QFont(tok.FONT_FAMILIES[0])
        self._font.setPixelSize(round(self._metrics.ruler_font_pt * 4 / 3 * self._SCALE))
        self._ruler_h = max(
            QFontMetrics(self._font).height(),
            round(self._metrics.major_tick_h * self._SCALE),
        )
        self._track_top = 24.0
        height = int(self._track_top) + 2 + round(self._metrics.track_h * self._SCALE)
        height += self._metrics.ruler_gap + self._ruler_h
        height += self._metrics.bottom_pad + 9
        self.setFixedSize(self._WIDTH, height)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#262626"), 1.0))
        painter.setBrush(QColor("#0b0b0b"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        left, right, top = 12.0, self.width() - 12.0, self._track_top
        width = right - left
        track_h = round(self._metrics.track_h * self._SCALE)
        painter.fillRect(QRectF(left, top, width, track_h), QColor("#49434f"))
        painter.fillRect(QRectF(left, top, width * 0.62, track_h), QColor("#b29ae7"))
        # Pins stay the same size for every ruler setting.
        for fraction in (0.21, 0.69):
            x = left + width * fraction
            pin = QPainterPath()
            pin.moveTo(x, 20)
            pin.cubicTo(x - 1, 16, x - 5, 14, x - 5, 10)
            pin.cubicTo(x - 5, 3, x + 5, 3, x + 5, 10)
            pin.cubicTo(x + 5, 14, x + 1, 16, x, 20)
            painter.fillPath(pin, QColor("#e8e8e8"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#6a6a6a"))
            painter.drawEllipse(QRectF(x - 1.6, 8, 3.2, 3.2))
        painter.setFont(self._font)
        ruler_y = top + track_h + self._metrics.ruler_gap
        for tick in range(25):
            x = left + width * tick / 24
            major = tick % 6 == 0
            tick_h = self._metrics.major_tick_h if major else self._metrics.minor_tick_h
            painter.setPen(QPen(QColor("#77727d"), 1.0))
            painter.drawLine(int(x), int(ruler_y), int(x), int(ruler_y + tick_h * self._SCALE))
            if major:
                label = f"{tick // 6}:00"
                label_w = QFontMetrics(self._font).horizontalAdvance(label)
                label_x = min(x + 3, right - label_w)
                painter.setPen(QColor("#e5deed"))
                painter.drawText(QRectF(label_x, ruler_y - 2, label_w + 2, self._ruler_h + 4),
                                 int(Qt.AlignmentFlag.AlignVCenter), label)
        # A sample playhead and overview scroller make this read as a timeline.
        needle_x = left + width * 0.62
        painter.fillRect(QRectF(needle_x - 1, top - 2, 2, track_h + 4), QColor("#eeeeee"))
        painter.fillRect(QRectF(needle_x - 3, top - 3, 6, 2), QColor("#eeeeee"))
        scroll_y = self.height() - 9
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#302b37"))
        painter.drawRoundedRect(QRectF(left, scroll_y, width, 3), 1.5, 1.5)
        painter.setBrush(QColor("#8773ac"))
        painter.drawRoundedRect(QRectF(left + width * 0.28, scroll_y, width * 0.4, 3), 1.5, 1.5)


class TimelineStripCombo(ClipCardStyleCombo):
    """Size choices with a matching timeline preview beside the list."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, diagram_factory=TimelineStripDiagram, copy_of=timeline_strip_copy)
