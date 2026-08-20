"""Ping-pong overflow marquee for labels that don't fit (ClipCard titles, etc.).

All overflowing labels share one wall-clock cycle: pause → ease-in/out cruise →
pause → ease-in/out return. Reverse/pause moments stay synchronized; different
title lengths map the same progress to their own pixel offset (longer = faster).

Only viewport-visible overflowing labels register on the shared ticker.
"""
from __future__ import annotations

import re
import weakref
from typing import Optional

from PySide6.QtCore import QElapsedTimer, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QSizePolicy,
    QStyleOptionFrame,
    QWidget,
)

_COLOR_RE = re.compile(r"color:\s*([^;}\s]+)", re.IGNORECASE)

# Shared cycle (wall-clock). All labels reverse/pause on these beats.
_PAUSE_MS = 900
_TRAVEL_MS = 2000  # fixed cruise duration → sync reverse; speed = max_offset / travel
_CYCLE_MS = 2 * _PAUSE_MS + 2 * _TRAVEL_MS
_TICK_MS = 16  # ~60 fps refresh; position comes from QElapsedTimer, not tick count
_MIN_OVERFLOW_PX = 4


def _ease_in_out_cubic(t: float) -> float:
    """Smooth acceleration out of rest, deceleration into the end (t in [0, 1])."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    if t < 0.5:
        return 4.0 * t * t * t
    u = -2.0 * t + 2.0
    return 1.0 - (u * u * u) / 2.0


def _scroll_factor(elapsed_ms: int) -> float:
    """Map global elapsed time → offset factor in [0, 1] for the current cycle."""
    t = int(elapsed_ms) % _CYCLE_MS
    if t < _PAUSE_MS:
        return 0.0
    t -= _PAUSE_MS
    if t < _TRAVEL_MS:
        return _ease_in_out_cubic(float(t) / float(_TRAVEL_MS))
    t -= _TRAVEL_MS
    if t < _PAUSE_MS:
        return 1.0
    t -= _PAUSE_MS
    return 1.0 - _ease_in_out_cubic(float(t) / float(_TRAVEL_MS))


class _MarqueeTicker:
    """One shared timer + wall clock for all active OverflowMarqueeLabel instances."""

    def __init__(self) -> None:
        self._refs: list[weakref.ref] = []
        self._timer: Optional[QTimer] = None
        self._clock = QElapsedTimer()
        self._clock_started = False

    def elapsed_ms(self) -> int:
        if not self._clock_started:
            return 0
        return int(self._clock.elapsed())

    def scroll_factor(self) -> float:
        return _scroll_factor(self.elapsed_ms())

    def _ensure_timer(self) -> QTimer:
        if self._timer is None:
            timer = QTimer()
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.setInterval(_TICK_MS)
            timer.timeout.connect(self._on_tick)
            self._timer = timer
        return self._timer

    def register(self, label: "OverflowMarqueeLabel") -> None:
        self._prune()
        if not self._clock_started:
            self._clock.start()
            self._clock_started = True
        for ref in self._refs:
            if ref() is label:
                self._ensure_timer().start()
                return
        self._refs.append(weakref.ref(label))
        self._ensure_timer().start()

    def unregister(self, label: "OverflowMarqueeLabel") -> None:
        self._refs = [
            ref for ref in self._refs if ref() is not None and ref() is not label
        ]
        if not self._refs and self._timer is not None and self._timer.isActive():
            self._timer.stop()

    def _prune(self) -> None:
        self._refs = [ref for ref in self._refs if ref() is not None]

    def _on_tick(self) -> None:
        self._prune()
        if not self._refs:
            if self._timer is not None:
                self._timer.stop()
            return
        alive: list[weakref.ref] = []
        for ref in self._refs:
            label = ref()
            if label is None:
                continue
            if label._on_shared_tick():
                alive.append(ref)
        self._refs = alive
        if not self._refs and self._timer is not None:
            self._timer.stop()


_TICKER = _MarqueeTicker()


class OverflowMarqueeLabel(QLabel):
    """Left-aligned label that marquees when text is wider than the widget."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._full_text = ""
        self._offset = 0.0
        self._max_offset = 0.0
        self._active = False
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        if text:
            self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 — Qt API
        self._full_text = text or ""
        super().setText(self._full_text)
        self.setToolTip(self._full_text)
        self._recompute_overflow()
        self._sync_active()
        self.update()

    def setStyleSheet(self, stylesheet: str) -> None:  # noqa: N802
        super().setStyleSheet(stylesheet)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def sizeHint(self):
        sh = super().sizeHint()
        # Prefer growing into layout slack; don't force full text width.
        return QSize(0, sh.height())

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        return QSize(0, sh.height())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_active()

    def hideEvent(self, event) -> None:
        self._deactivate()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._recompute_overflow()
        self._sync_active()

    def paintEvent(self, event) -> None:  # noqa: N802
        rect = self.contentsRect()
        if rect.width() <= 1:
            return

        self._recompute_overflow()
        # Painting implies on-screen — join the shared clock if we overflow.
        if self._max_offset > 0 and not self._active:
            self._activate()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self.font())
        painter.setPen(self._text_color())
        painter.setClipRect(rect)

        metrics = self.fontMetrics()
        text = self._full_text
        if self._max_offset <= 0:
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            return

        # Snap to the global phase on every paint (scroll-back / click stay in sync).
        self._offset = _TICKER.scroll_factor() * self._max_offset
        y = rect.y() + (rect.height() + metrics.ascent() - metrics.descent()) // 2
        painter.translate(float(rect.x()) - self._offset, 0.0)
        painter.drawText(0, y, text)

    def _text_color(self) -> QColor:
        match = _COLOR_RE.search(self.styleSheet() or "")
        if match is not None:
            color = QColor(match.group(1).strip())
            if color.isValid():
                return color
        opt = QStyleOptionFrame()
        self.initStyleOption(opt)
        color = opt.palette.color(QPalette.ColorRole.Text)
        if color.isValid():
            return color
        return self.palette().color(QPalette.ColorRole.WindowText)

    def _recompute_overflow(self) -> None:
        width = self.contentsRect().width()
        if width <= 1 or not self._full_text:
            self._max_offset = 0.0
            return
        text_w = float(QFontMetrics(self.font()).horizontalAdvance(self._full_text))
        overflow = text_w - float(width)
        self._max_offset = overflow if overflow >= _MIN_OVERFLOW_PX else 0.0
        if self._max_offset <= 0:
            self._offset = 0.0

    def _viewport_visible(self) -> bool:
        if not self.isVisible():
            return False
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractItemView):
                vp = parent.viewport()
                top_left = self.mapTo(vp, QPoint(0, 0))
                return vp.rect().intersects(QRect(top_left, self.size()))
            parent = parent.parentWidget()
        return bool(self.visibleRegion())

    def _sync_active(self) -> None:
        self._recompute_overflow()
        if self._max_offset > 0 and self._viewport_visible():
            self._activate()
        else:
            self._deactivate()

    def _activate(self) -> None:
        if self._active:
            return
        self._active = True
        # Join current global phase immediately (no private start delay).
        self._offset = _TICKER.scroll_factor() * self._max_offset
        _TICKER.register(self)

    def _deactivate(self) -> None:
        if not self._active:
            return
        self._active = False
        _TICKER.unregister(self)

    def _on_shared_tick(self) -> bool:
        """Refresh from the shared clock. Return False to unregister."""
        try:
            if self._max_offset <= 0 or not self._viewport_visible():
                self._deactivate()
                return False
        except RuntimeError:
            return False

        self._offset = _TICKER.scroll_factor() * self._max_offset
        self.update()
        return True
