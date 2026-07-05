"""Animated render progress bar for the export dashboard.

Replaces the flat QProgressBar strip with smooth value easing, a purple
gradient fill, and a moving shimmer while FFmpeg is working.
"""
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

_TRACK = QColor("#414141")
_GRADIENT_START = QColor("#6b5a8e")
_GRADIENT_END = QColor("#b29ae7")
_SHIMMER = QColor(255, 255, 255, 72)

_STATE_FILL = {
    "ready": None,
    "rendering": "gradient",
    "paused": QColor("#ffcc00"),
    "error": QColor("#ff4444"),
    "success": QColor("#4CAF50"),
    "cancelling": QColor("#ff4444"),
    "cancelled": QColor("#ff4444"),
}

_BAR_H = 6.0
_LERP = 0.22
_INDETERMINATE_CUTOFF = 0.35


class AnimatedRenderBar(QWidget):
    """Thin horizontal bar with eased progress and optional shimmer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(int(_BAR_H))
        self.setMaximumHeight(int(_BAR_H))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._display = 0.0
        self._target = 0.0
        self._state = "ready"
        self._shimmer = 0.0

        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._on_tick)

    # -- QProgressBar compatibility (0..1000) --------------------------------
    def setRange(self, _lo, _hi):
        pass

    def setTextVisible(self, _visible):
        pass

    def setValue(self, value):
        self.set_progress(float(value) / 10.0)

    def value(self):
        return int(round(self._display * 10))

    # -- API -----------------------------------------------------------------
    def set_state(self, state):
        state = state or "ready"
        if state == self._state:
            return
        self._state = state
        if state == "ready" or state == "error":
            self._target = 0.0
        elif state == "success":
            self._target = 100.0
        self._ensure_timer()
        self.update()

    def set_progress(self, percent, *, animate=True):
        self._target = max(0.0, min(100.0, float(percent)))
        if not animate:
            self._display = self._target
        self._ensure_timer()
        self.update()

    def setStyleSheet(self, _stylesheet):
        """Ignored — styling is painted in code."""

    # -- animation -----------------------------------------------------------
    def _ensure_timer(self):
        needs_motion = (
            self._state == "rendering"
            or abs(self._display - self._target) > 0.05
        )
        if needs_motion:
            if not self._tick.isActive():
                self._tick.start()
        elif self._tick.isActive():
            self._tick.stop()

    def _on_tick(self):
        moved = False

        if abs(self._display - self._target) > 0.05:
            self._display += (self._target - self._display) * _LERP
            moved = True
        elif self._display != self._target:
            self._display = self._target
            moved = True

        if self._state == "rendering":
            self._shimmer = (self._shimmer + 0.018) % 1.0
            moved = True

        if moved:
            self.update()
        else:
            self._ensure_timer()

    # -- painting ------------------------------------------------------------
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        w = float(self.width())
        h = float(self.height())
        radius = min(h / 2.0, 3.0)
        track = QRectF(0.0, 0.0, w, h)

        painter.setBrush(_TRACK)
        painter.drawRoundedRect(track, radius, radius)

        if self._state == "rendering" and self._display < _INDETERMINATE_CUTOFF:
            self._paint_indeterminate(painter, track, radius)
            painter.end()
            return

        fill_w = max(0.0, w * self._display / 100.0)
        if fill_w < 0.5:
            painter.end()
            return

        fill_rect = QRectF(0.0, 0.0, fill_w, h)
        mode = _STATE_FILL.get(self._state)

        if mode == "gradient" or self._state == "rendering":
            grad = QLinearGradient(0.0, 0.0, fill_w, 0.0)
            grad.setColorAt(0.0, _GRADIENT_START)
            grad.setColorAt(1.0, _GRADIENT_END)
            painter.setBrush(grad)
        elif isinstance(mode, QColor):
            painter.setBrush(mode)
        else:
            painter.end()
            return

        painter.drawRoundedRect(fill_rect, radius, radius)

        if self._state == "rendering":
            self._paint_shimmer(painter, fill_w, h, radius)

        painter.end()

    def _paint_indeterminate(self, painter, track, radius):
        w = track.width()
        seg = max(28.0, w * 0.18)
        travel = max(1.0, w - seg)
        x = (self._shimmer * travel) if self._shimmer else 0.0

        grad = QLinearGradient(x, 0.0, x + seg, 0.0)
        grad.setColorAt(0.0, _GRADIENT_START)
        grad.setColorAt(0.5, _GRADIENT_END)
        grad.setColorAt(1.0, _GRADIENT_START)
        painter.setBrush(grad)
        painter.drawRoundedRect(QRectF(x, 0.0, seg, track.height()), radius, radius)

    def _paint_shimmer(self, painter, fill_w, h, radius):
        band = max(18.0, fill_w * 0.28)
        x = -band + (fill_w + band) * self._shimmer

        painter.save()
        painter.setClipRect(QRectF(0.0, 0.0, fill_w, h))

        shimmer = QLinearGradient(x, 0.0, x + band, 0.0)
        shimmer.setColorAt(0.0, QColor(255, 255, 255, 0))
        shimmer.setColorAt(0.45, _SHIMMER)
        shimmer.setColorAt(0.55, _SHIMMER)
        shimmer.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(shimmer)
        painter.drawRoundedRect(QRectF(0.0, 0.0, fill_w, h), radius, radius)
        painter.restore()
