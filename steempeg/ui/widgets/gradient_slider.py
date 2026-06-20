"""A horizontal slider with a rainbow groove for the Target File Size control.

The groove runs red -> orange -> yellow -> green across the quality stops (worst -> best),
then ends in the app's purple for the final "Custom MB" stop (the user's own choice). The
handle is filled with the colour sampled at its current position, so it shifts hue as it
moves. Subclasses QSlider so the rest of the app keeps using value()/setValue()/valueChanged
unchanged; only the look (and click-to-position mapping) is custom.

Stop layout (from render_controller.setup_dynamic_slider):
    index 0          -> smallest size  (worst quality)  -> red
    index max-1      -> Lossless        (best quality)   -> green
    index max        -> Custom (-1)     (pick MB)        -> purple
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

    # -- geometry / interaction --------------------------------------------
    def _track(self):
        margin = _HANDLE_R + 2.0
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

        grad = QLinearGradient(x0, 0, x1, 0)
        for pos, col in self._keypoints():
            grad.setColorAt(max(0.0, min(1.0, pos)), col)
        painter.setBrush(grad)
        painter.drawRoundedRect(QRectF(x0, cy - _GROOVE_H / 2, track_w, _GROOVE_H),
                                _GROOVE_H / 2, _GROOVE_H / 2)

        frac = self._frac()
        hx = x0 + frac * track_w
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QPointF(hx, cy), _HANDLE_R, _HANDLE_R)
        painter.setBrush(self._color_at(frac))
        painter.drawEllipse(QPointF(hx, cy), _HANDLE_R - 2.5, _HANDLE_R - 2.5)
        painter.end()