"""Animated render progress bar for the export dashboard.

Replaces the flat QProgressBar strip with smooth value easing, a purple
gradient fill, and a moving shimmer while FFmpeg is working.
"""
import math

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
    "busy": "gradient",
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
        self._indeterminate: str | None = None  # "bounce" while searching clips

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
        if state == self._state and state not in ("ready", "error"):
            return
        self._state = state
        if state in ("ready", "error"):
            self._indeterminate = None
            self._target = 0.0
        elif state == "success":
            self._indeterminate = None
            self._target = 100.0
        self._ensure_timer()
        self.update()

    def set_scan_bounce(self) -> None:
        """Indeterminate ping-pong segment (library search / clip discovery)."""
        self._indeterminate = "bounce"
        self._state = "busy"
        self._target = 0.0
        self._display = 0.0
        self._ensure_timer()
        self.update()

    def set_loading_progress(self, percent: float) -> None:
        """Determinate left-to-right fill while library rows load (eased)."""
        self._indeterminate = None
        self._state = "busy"
        clamped = max(0.0, min(100.0, float(percent)))
        self._target = clamped
        if clamped < self._display:
            self._display = clamped
        self._ensure_timer()
        self.update()

    def set_progress(self, percent, *, animate=True):
        self._indeterminate = None
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
            self._indeterminate is not None
            or self._state in ("rendering", "busy")
            or abs(self._display - self._target) > 0.05
        )
        if needs_motion:
            if not self._tick.isActive():
                self._tick.start()
        elif self._tick.isActive():
            self._tick.stop()

    def _on_tick(self):
        moved = False

        if self._indeterminate is None and abs(self._display - self._target) > 0.05:
            self._display += (self._target - self._display) * _LERP
            moved = True
        elif self._indeterminate is None and self._display != self._target:
            self._display = self._target
            moved = True

        if self._indeterminate is not None or self._state in ("rendering", "busy"):
            self._shimmer = (self._shimmer + 0.014) % 1.0
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

        if self._indeterminate == "bounce":
            self._paint_bounce(painter, track, radius)
            painter.end()
            return

        if self._state == "rendering" and self._display < _INDETERMINATE_CUTOFF:
            self._paint_marquee(painter, track, radius)
            painter.end()
            return

        fill_pct = self._display
        fill_w = max(0.0, w * fill_pct / 100.0)
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

    def _segment_gradient(self, x: float, seg: float) -> QLinearGradient:
        grad = QLinearGradient(x, 0.0, x + seg, 0.0)
        grad.setColorAt(0.0, _GRADIENT_START)
        grad.setColorAt(0.5, _GRADIENT_END)
        grad.setColorAt(1.0, _GRADIENT_START)
        return grad

    def _paint_bounce(self, painter, track, radius):
        """Purple segment ping-pongs inside the track (library search)."""
        w = track.width()
        h = track.height()
        seg = max(28.0, w * 0.22)
        travel = max(1.0, w - seg)
        phase = (1.0 - math.cos(self._shimmer * math.pi * 2.0)) * 0.5
        x = phase * travel

        painter.setBrush(self._segment_gradient(x, seg))
        painter.drawRoundedRect(QRectF(x, 0.0, seg, h), radius, radius)

    def _paint_marquee(self, painter, track, radius):
        """Single segment marquees left → right (early render / generic busy)."""
        w = track.width()
        h = track.height()
        seg = max(28.0, w * 0.22)
        period = w + seg
        x = self._shimmer * period - seg

        painter.setBrush(self._segment_gradient(x, seg))
        painter.drawRoundedRect(QRectF(x, 0.0, seg, h), radius, radius)

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
