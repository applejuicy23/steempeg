"""Purple square checkbox with animated checkmark (Render Queue dialog style)."""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QCheckBox


class SteempegCheckBox(QCheckBox):
    """Steempeg accent checkbox — same look as the render-queue «Don't show again» control."""

    _IND = 14
    _GAP = 8
    _PAD = 2

    def __init__(
        self,
        text: str = "",
        parent=None,
        *,
        accent_label: bool = True,
        font_size: int = 11,
    ):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accent_label = accent_label
        self._font_size = font_size
        self._progress = 1.0 if self.isChecked() else 0.0

        self._anim = QPropertyAnimation(self, b"checkProgress", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_to_state)

        self.setStyleSheet(
            "QCheckBox { spacing: 0px; background: transparent; border: none; }"
            " QCheckBox::indicator { width: 0px; height: 0px; border: none; }"
        )

    def _label_color(self) -> QColor:
        if self.isEnabled():
            return QColor("#b29ae7" if self._accent_label else "#cccccc")
        return QColor("#666666")

    def _indicator_rect(self) -> QRectF:
        y = (self.height() - self._IND) / 2.0
        return QRectF(float(self._PAD), y, float(self._IND), float(self._IND))

    def _text_left(self) -> int:
        return self._PAD + self._IND + self._GAP

    def sizeHint(self):
        base = super().sizeHint()
        return QSize(base.width() + self._text_left(), base.height())

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.contentsRect().contains(pos)

    def _animate_to_state(self, checked: bool) -> None:
        self._anim.stop()
        end = 1.0 if checked else 0.0
        if abs(self._progress - end) < 0.01:
            self._progress = end
            self.update()
            return
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(end)
        self._anim.start()

    def get_check_progress(self) -> float:
        return self._progress

    def set_check_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    checkProgress = Property(float, get_check_progress, set_check_progress)

    def paintEvent(self, _event) -> None:
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._progress = 1.0 if self.isChecked() else 0.0

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        t = max(0.0, min(1.0, self._progress))
        ind = self._indicator_rect()
        radius = 3.0

        unchecked_bg = QColor("#1a1a1a")
        checked_bg = QColor("#5138e6")
        unchecked_border = QColor("#666666")
        checked_border = QColor("#b29ae7")

        def _lerp(a: QColor, b: QColor, u: float) -> QColor:
            return QColor(
                int(a.red() + (b.red() - a.red()) * u),
                int(a.green() + (b.green() - a.green()) * u),
                int(a.blue() + (b.blue() - a.blue()) * u),
            )

        bg = _lerp(unchecked_bg, checked_bg, t)
        border = _lerp(unchecked_border, checked_border, t)

        p.setPen(QPen(border, 2))
        p.setBrush(bg)
        p.drawRoundedRect(ind, radius, radius)

        if t > 0.02:
            pen = QPen(QColor("#ffffff"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            x, y, w, h = ind.x(), ind.y(), ind.width(), ind.height()
            p1 = (x + 3.0, y + h * 0.55)
            p2 = (x + w * 0.42, y + h - 3.5)
            p3 = (x + w - 2.5, y + 3.0)
            if t < 1.0:
                mid = (p1[0] + (p2[0] - p1[0]) * min(1.0, t * 2.0),
                       p1[1] + (p2[1] - p1[1]) * min(1.0, t * 2.0))
                if t <= 0.5:
                    p.drawLine(int(p1[0]), int(p1[1]), int(mid[0]), int(mid[1]))
                else:
                    p.drawLine(int(p1[0]), int(p1[1]), int(p2[0]), int(p2[1]))
                    tail_t = (t - 0.5) * 2.0
                    mid2 = (p2[0] + (p3[0] - p2[0]) * tail_t, p2[1] + (p3[1] - p2[1]) * tail_t)
                    p.drawLine(int(p2[0]), int(p2[1]), int(mid2[0]), int(mid2[1]))
            else:
                p.drawLine(int(p1[0]), int(p1[1]), int(p2[0]), int(p2[1]))
                p.drawLine(int(p2[0]), int(p2[1]), int(p3[0]), int(p3[1]))

        font = QFont("Segoe UI")
        font.setPixelSize(self._font_size)
        if self._accent_label:
            font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(self._label_color())

        text_rect = self.rect().adjusted(self._text_left(), 0, -self._PAD, 0)
        p.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )
        p.end()
