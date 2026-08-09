"""Gradient QSliders: Target Size rainbow + compact volume/speed level track.

Target File Size (``GradientSlider``):
    red -> orange -> yellow -> green across quality, then purple for Custom MB.

Player volume / speed (``LevelGradientSlider``):
    green (low / quiet / slow) -> yellow (mid) -> red (high / loud / fast).
    Compact chrome to replace the old purple ``linevolume.png`` strip.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QSlider

_RED = QColor("#ff4d4d")
_ORANGE = QColor("#ff9f43")
_YELLOW = QColor("#ffd93d")
_GREEN = QColor("#4cd964")
_PURPLE = QColor("#b29ae7")  # app accent (player bar) -> the "your choice" Custom stop

_HANDLE_R = 9.0
_GROOVE_H = 6.0

# Compact player chrome (matches old volume/speed groove height ~4px, handle ~12px).
# Groove length stays ~80px like ``linevolume.png``; widget adds handle room so
# the knob at 0%/100% is not clipped.
_LEVEL_HANDLE_R = 6.0
_LEVEL_GROOVE_H = 4.0
_LEVEL_GROOVE_W = 80
LEVEL_SLIDER_WIDTH = int(_LEVEL_GROOVE_W + 2 * _LEVEL_HANDLE_R)  # 92


class GradientSlider(QSlider):
    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setMinimumHeight(28)
        self.valueChanged.connect(self.update)

    # -- colour model ---
    def _keypoints(self):
        """(pos, colour) stops along the groove. Lossless (best) sits at the second-to-last
        slider stop; the very last stop is Custom -> purple."""
        mx = self.maximum()
        lf = (mx - 1) / mx if mx > 1 else 0.85
        return [
            (0.0, _RED),
            (lf * 0.34, _ORANGE),
            (lf * 0.67, _YELLOW),
            (lf, _GREEN),
            (1.0, _PURPLE),
        ]

    def _color_at(self, frac):
        frac = max(0.0, min(1.0, frac))
        stops = self._keypoints()
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]
            p1, c1 = stops[i + 1]
            if p0 <= frac <= p1:
                t = 0.0 if p1 <= p0 else (frac - p0) / (p1 - p0)
                return QColor(
                    round(c0.red() + (c1.red() - c0.red()) * t),
                    round(c0.green() + (c1.green() - c0.green()) * t),
                    round(c0.blue() + (c1.blue() - c0.blue()) * t),
                )
        return stops[-1][1]

    def _frac(self):
        lo, hi = self.minimum(), self.maximum()
        return (self.value() - lo) / (hi - lo) if hi > lo else 0.0

    def _handle_r(self) -> float:
        return _HANDLE_R

    def _groove_h(self) -> float:
        return _GROOVE_H

    # -- geometry / interaction --------------------------------------------
    def _track(self):
        margin = self._handle_r() + 2.0
        return margin, self.width() - margin

    def _value_from_x(self, x):
        x0, x1 = self._track()
        frac = (x - x0) / max(1.0, x1 - x0)
        frac = max(0.0, min(1.0, frac))
        lo, hi = self.minimum(), self.maximum()
        return round(lo + frac * (hi - lo))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setValue(self._value_from_x(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.setValue(self._value_from_x(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    # -- painting ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        x0, x1 = self._track()
        track_w = max(1.0, x1 - x0)
        cy = self.height() / 2.0
        groove_h = self._groove_h()
        handle_r = self._handle_r()

        grad = QLinearGradient(x0, 0, x1, 0)
        for pos, col in self._keypoints():
            grad.setColorAt(max(0.0, min(1.0, pos)), col)
        painter.setBrush(grad)
        painter.drawRoundedRect(
            QRectF(x0, cy - groove_h / 2, track_w, groove_h),
            groove_h / 2,
            groove_h / 2,
        )

        frac = self._frac()
        hx = x0 + frac * track_w
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QPointF(hx, cy), handle_r, handle_r)
        painter.setBrush(self._color_at(frac))
        painter.drawEllipse(QPointF(hx, cy), handle_r - 2.0, handle_r - 2.0)
        painter.end()


class LevelGradientSlider(GradientSlider):
    """Compact green→yellow→red groove for volume and playback speed."""

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setMinimumHeight(24)
        # Transparent so QSS from the old linevolume path never fights us.
        self.setStyleSheet("background: transparent; border: none;")

    def _keypoints(self):
        return [
            (0.0, _GREEN),
            (0.5, _YELLOW),
            (1.0, _RED),
        ]

    def _handle_r(self) -> float:
        return _LEVEL_HANDLE_R

    def _groove_h(self) -> float:
        return _LEVEL_GROOVE_H

    def _track(self):
        # Inset by handle radius: ~80px groove inside LEVEL_SLIDER_WIDTH, full knob.
        margin = self._handle_r()
        return margin, max(margin + 1.0, float(self.width()) - margin)
