"""Ping-pong overflow marquee for labels that don't fit (ClipCard titles, etc.).

All overflowing labels share one wall-clock cycle: pause → ease-in/out cruise →
pause → ease-in/out return. Reverse/pause moments stay synchronized; different
title lengths map the same progress to their own pixel offset (longer = faster).

Only viewport-visible overflowing labels register on the shared ticker.

Overflow edges dissolve the glyphs themselves (smooth alpha), not a fog overlay.
"""
from __future__ import annotations

import re
import weakref
from typing import Optional

from PySide6.QtCore import QElapsedTimer, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPalette,
)
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
# Soft glyph dissolve at clipped edges (logical px; scaled by DPR in paint).
_EDGE_FADE_PX = 10.0
_EDGE_FADE_MIN_W = 48
# How long a side eases in/out when entering/leaving a rest (seamless A/B).
_EDGE_FADE_EASE_MS = 320


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


def _smoothstep(t: float) -> float:
    """Hermite smoothstep — no visible 'start of fade' kink."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


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


def _edge_fade_width(rect_w: float) -> float:
    if rect_w < _EDGE_FADE_MIN_W:
        return 0.0
    return min(_EDGE_FADE_PX, max(6.0, rect_w * 0.10))


def _edge_fade_strengths(elapsed_ms: int) -> tuple[float, float]:
    """Left [A] / right [B] dissolve from the ping-pong phase.

    Rest @ start (title head visible): only [B] — overflow cut on the right.
    Rest @ end   (title tail visible): only [A] — overflow cut on the left.
    Cruising: both [A] and [B]. Ease the side that appears/disappears at rests
    so pause ↔ travel stays seamless (no both-sides blur while parked).
    """
    t = int(elapsed_ms) % _CYCLE_MS
    ease = max(80, min(_EDGE_FADE_EASE_MS, _TRAVEL_MS // 3))

    # --- pause @ start: "Hatsune Miku: …" — blur only on the right ---
    if t < _PAUSE_MS:
        return 0.0, 1.0
    t -= _PAUSE_MS

    # --- cruise → end ---
    if t < _TRAVEL_MS:
        left = 1.0
        right = 1.0
        # Leaving start: bring [A] up (was off at rest).
        if t < ease:
            left = _smoothstep(float(t) / float(ease))
        # Approaching end rest: drop [B] (end pause is left-only).
        rem = _TRAVEL_MS - t
        if rem < ease:
            right = _smoothstep(float(rem) / float(ease))
        return left, right
    t -= _TRAVEL_MS

    # --- pause @ end: "…DIVA MIX" — blur only on the left ---
    if t < _PAUSE_MS:
        return 1.0, 0.0
    t -= _PAUSE_MS

    # --- cruise → start ---
    left = 1.0
    right = 1.0
    # Leaving end: bring [B] up (was off at rest).
    if t < ease:
        right = _smoothstep(float(t) / float(ease))
    # Approaching start rest: drop [A] (start pause is right-only).
    rem = _TRAVEL_MS - t
    if rem < ease:
        left = _smoothstep(float(rem) / float(ease))
    return left, right


def _dissolve_layer_edges(
    img: QImage,
    *,
    left_strength: float,
    right_strength: float,
    fade_px: float,
) -> None:
    """Smoothstep-dissolve glyph alpha on the text layer (not a widget fog)."""
    left_strength = max(0.0, min(1.0, float(left_strength)))
    right_strength = max(0.0, min(1.0, float(right_strength)))
    fade_left = left_strength > 0.02
    fade_right = right_strength > 0.02
    if fade_px <= 0.0 or (not fade_left and not fade_right):
        return
    # Paint in logical coords — QImage DPR maps them to physical pixels.
    dpr = max(float(img.devicePixelRatio()), 1.0)
    lw = float(img.width()) / dpr
    lh = float(img.height()) / dpr
    if lw <= 1.0:
        return
    fade_l = min(fade_px * left_strength, lw * 0.4)
    fade_r = min(fade_px * right_strength, lw * 0.4)
    fl = fade_l / lw if fade_left else 0.0
    fr = fade_r / lw if fade_right else 0.0

    # Build stops in order. Alpha 0 = drop glyph, 255 = keep.
    stops: list[tuple[float, int]] = []
    steps = 8
    if fade_left and fl > 0.0:
        for i in range(steps + 1):
            t = float(i) / float(steps)
            stops.append((fl * t, int(255 * _smoothstep(t))))
    else:
        stops.append((0.0, 255))

    mid_lo = fl if fade_left else 0.0
    mid_hi = (1.0 - fr) if fade_right else 1.0
    if mid_lo < mid_hi:
        stops.append((mid_lo + 1e-4, 255))
        stops.append((mid_hi - 1e-4, 255))

    if fade_right and fr > 0.0:
        for i in range(steps + 1):
            t = float(i) / float(steps)
            stops.append((1.0 - fr * t, int(255 * _smoothstep(t))))
    else:
        stops.append((1.0, 255))

    stops.sort(key=lambda s: s[0])
    grad = QLinearGradient(0.0, 0.0, lw, 0.0)
    last_p = -1.0
    for pos, alpha in stops:
        pos = max(0.0, min(1.0, pos))
        if pos - last_p < 1e-5:
            pos = min(1.0, last_p + 1e-5)
        grad.setColorAt(pos, QColor(0, 0, 0, alpha))
        last_p = pos

    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.fillRect(0, 0, int(round(lw + 0.5)), int(round(lh + 0.5)), grad)
    p.end()
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

        metrics = self.fontMetrics()
        text = self._full_text
        if self._max_offset <= 0:
            painter.setClipRect(rect)
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            return

        # Snap to the global phase on every paint (scroll-back / click stay in sync).
        elapsed = _TICKER.elapsed_ms()
        self._offset = _scroll_factor(elapsed) * self._max_offset
        left_s, right_s = _edge_fade_strengths(elapsed)
        fade_px = _edge_fade_width(float(rect.width()))

        # Paint glyphs on a transparent layer, dissolve edge columns, then blit.
        # (DestinationIn on the widget painted a visible fog band over the footer.)
        dpr = max(1.0, float(self.devicePixelRatioF()))
        phys_w = max(1, int(round(rect.width() * dpr)))
        phys_h = max(1, int(round(rect.height() * dpr)))
        layer = QImage(phys_w, phys_h, QImage.Format.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(dpr)
        layer.fill(Qt.GlobalColor.transparent)

        lp = QPainter(layer)
        lp.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        lp.setFont(self.font())
        lp.setPen(self._text_color())
        y = (rect.height() + metrics.ascent() - metrics.descent()) // 2
        lp.translate(-self._offset, 0.0)
        lp.drawText(0, y, text)
        lp.end()

        _dissolve_layer_edges(
            layer,
            left_strength=left_s,
            right_strength=right_s,
            fade_px=fade_px,
        )
        painter.drawImage(rect.topLeft(), layer)

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
