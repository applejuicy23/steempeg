"""Trim ring and play/pause pulse drawn by mpv itself (``osd-overlay``).

Anything Qt draws next to the embedded ``wid=`` HWND is composited separately
from mpv's swapchain: during a splitter drag it lags behind the picture, and a
floating Tool window sits above every other dialog. ASS drawings in mpv's OSD
are part of the video frame, so they follow the surface exactly.

Coordinates use the embed's physical pixel size as the ASS play resolution, so
one ASS unit is one screen pixel.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QEvent, QObject, QTimer

_RING_OVERLAY_ID = 61
_PULSE_OVERLAY_ID = 62

_RING_PX = 3
_RING_ASS_COLOR = "&H00CCFF&"  # #ffcc00 in ASS BGR order

_FADE_IN_S = 0.18
_HOLD_S = 0.42
_FADE_OUT_S = 0.40
_TOTAL_S = _FADE_IN_S + _HOLD_S + _FADE_OUT_S
_CIRCLE_PX = 100
_GLYPH_PX = 44
_DISK_ALPHA = 150
_BEZIER_K = 0.5523


def _surface_size(surface) -> tuple[int, int, float]:
    """Physical pixel size of the mpv embed plus its device pixel ratio."""
    try:
        dpr = float(surface.devicePixelRatioF() or 1.0)
        return int(round(surface.width() * dpr)), int(round(surface.height() * dpr)), dpr
    except RuntimeError:
        return 0, 0, 1.0


def _send_overlay(player, overlay_id: int, data: str, res_x: int, res_y: int, z: int) -> None:
    """Push one ASS-events overlay to mpv; silently skip a dead player."""
    if player is None:
        return
    try:
        player.command(
            "osd-overlay",
            id=overlay_id,
            format="ass-events",
            data=data,
            res_x=res_x,
            res_y=res_y,
            z=z,
            hidden=False,
        )
    except Exception:
        logging.debug("mpv osd-overlay %s failed", overlay_id, exc_info=True)


def _remove_overlay(player, overlay_id: int) -> None:
    """Drop an overlay from mpv's OSD."""
    if player is None:
        return
    try:
        player.command("osd-overlay", id=overlay_id, format="none", data="")
    except Exception:
        logging.debug("mpv osd-overlay remove %s failed", overlay_id, exc_info=True)


def _rect_path(x: float, y: float, w: float, h: float) -> str:
    """ASS drawing commands for one filled rectangle."""
    return f"m {x:.1f} {y:.1f} l {x + w:.1f} {y:.1f} {x + w:.1f} {y + h:.1f} {x:.1f} {y + h:.1f}"


def _circle_path(cx: float, cy: float, r: float) -> str:
    """ASS drawing commands for a filled circle built from four bezier arcs."""
    k = r * _BEZIER_K
    return (
        f"m {cx - r:.1f} {cy:.1f} "
        f"b {cx - r:.1f} {cy - k:.1f} {cx - k:.1f} {cy - r:.1f} {cx:.1f} {cy - r:.1f} "
        f"b {cx + k:.1f} {cy - r:.1f} {cx + r:.1f} {cy - k:.1f} {cx + r:.1f} {cy:.1f} "
        f"b {cx + r:.1f} {cy + k:.1f} {cx + k:.1f} {cy + r:.1f} {cx:.1f} {cy + r:.1f} "
        f"b {cx - k:.1f} {cy + r:.1f} {cx - r:.1f} {cy + k:.1f} {cx - r:.1f} {cy:.1f}"
    )


def _ass_shape(path: str, color: str, alpha: int) -> str:
    """One ASS event that fills ``path`` with a flat color and alpha (0 = opaque)."""
    alpha = max(0, min(255, int(alpha)))
    return (
        f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c{color}\\1a&H{alpha:02X}&\\p1}}{path}{{\\p0}}"
    )


class MpvTrimRing(QObject):
    """Yellow trim border drawn on the edges of the mpv picture."""

    def __init__(self, get_player, surface):
        super().__init__(surface)
        self._get_player = get_player
        self._surface = surface
        self._active = False
        self._last_key = None
        surface.installEventFilter(self)

    def set_active(self, active: bool) -> None:
        """Show or hide the ring; resends only when something changed."""
        self._active = bool(active)
        self.refresh()

    def refresh(self) -> None:
        """Redraw the ring for the current embed size (or remove it)."""
        player = self._get_player()
        w, h, dpr = _surface_size(self._surface)
        if not self._active or w < 8 or h < 8:
            if self._last_key is not None:
                _remove_overlay(player, _RING_OVERLAY_ID)
                self._last_key = None
            return
        t = max(1, int(round(_RING_PX * dpr)))
        key = (w, h, t, id(player))
        if key == self._last_key:
            return
        self._last_key = key
        path = " ".join(
            (
                _rect_path(0, 0, w, t),
                _rect_path(0, h - t, w, t),
                _rect_path(0, t, t, h - 2 * t),
                _rect_path(w - t, t, t, h - 2 * t),
            )
        )
        _send_overlay(player, _RING_OVERLAY_ID, _ass_shape(path, _RING_ASS_COLOR, 0), w, h, 0)

    def invalidate(self) -> None:
        """Forget the last sent ring (new player / file) and redraw."""
        self._last_key = None
        self.refresh()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._surface and event.type() == QEvent.Type.Resize and self._active:
            self.refresh()
        return super().eventFilter(obj, event)


class MpvPlayPausePulse(QObject):
    """Centered dark circle + play/pause glyph that fades in and out inside mpv."""

    def __init__(self, get_player, surface):
        super().__init__(surface)
        self._get_player = get_player
        self._surface = surface
        self._paused = False
        self._opacity = 0.0
        self._scale = 0.82
        self._t0 = 0.0
        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._on_tick)

    def pulse(self, anchor_widget=None, *, paused: bool) -> bool:
        """Start (or restart) the pulse; never maps a window, so always False."""
        del anchor_widget
        interrupted = self._tick.isActive()
        self._paused = bool(paused)
        if interrupted and self._opacity > 0.15:
            self._opacity = min(1.0, max(0.35, self._opacity))
            self._scale = 0.88
            self._t0 = time.monotonic() - (_FADE_IN_S * 0.55)
        else:
            self._opacity = 0.0
            self._scale = 0.82
            self._t0 = time.monotonic()
        if not self._tick.isActive():
            self._tick.start()
        self._draw()
        return False

    def cancel(self) -> None:
        """Stop the animation and wipe the pulse from the OSD."""
        self._tick.stop()
        self._opacity = 0.0
        _remove_overlay(self._get_player(), _PULSE_OVERLAY_ID)

    def isVisible(self) -> bool:  # noqa: N802
        """True while the pulse animation is running."""
        return self._tick.isActive()

    def _on_tick(self) -> None:
        """Advance the appear → hold → fade curve by one frame."""
        elapsed = time.monotonic() - self._t0
        if elapsed >= _TOTAL_S:
            self.cancel()
            return
        if elapsed < _FADE_IN_S:
            t = elapsed / _FADE_IN_S
            eased = 1.0 - (1.0 - t) ** 3
            self._opacity = eased
            self._scale = 0.82 + 0.18 * eased
        elif elapsed < _FADE_IN_S + _HOLD_S:
            self._opacity = 1.0
            self._scale = 1.0
        else:
            t = (elapsed - _FADE_IN_S - _HOLD_S) / _FADE_OUT_S
            self._opacity = 1.0 - t * t
            self._scale = 1.0
        self._draw()

    def _draw(self) -> None:
        """Send the circle and glyph for the current opacity and scale."""
        player = self._get_player()
        w, h, dpr = _surface_size(self._surface)
        if w < 8 or h < 8 or self._opacity <= 0.01:
            _remove_overlay(player, _PULSE_OVERLAY_ID)
            return
        cx = w / 2.0
        cy = h / 2.0
        r = _CIRCLE_PX * dpr * self._scale / 2.0
        g = _GLYPH_PX * dpr * self._scale
        disk = _ass_shape(_circle_path(cx, cy, r), "&H000000&", 255 - _DISK_ALPHA * self._opacity)
        glyph_alpha = 255 - 255 * self._opacity
        if self._paused:
            bar_w = g * 0.26
            bar_h = g * 0.82
            gap = g * 0.2
            path = " ".join(
                (
                    _rect_path(cx - gap / 2 - bar_w, cy - bar_h / 2, bar_w, bar_h),
                    _rect_path(cx + gap / 2, cy - bar_h / 2, bar_w, bar_h),
                )
            )
        else:
            left = cx - g * 0.30
            right = cx + g * 0.42
            half = g * 0.42
            path = (
                f"m {left:.1f} {cy - half:.1f} l {right:.1f} {cy:.1f} {left:.1f} {cy + half:.1f}"
            )
        glyph = _ass_shape(path, "&HFFFFFF&", glyph_alpha)
        _send_overlay(player, _PULSE_OVERLAY_ID, f"{disk}\n{glyph}", w, h, 1)
