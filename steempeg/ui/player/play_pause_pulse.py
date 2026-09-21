"""Brief play/pause pulse over the video surface.

Child widgets cannot paint over an embedded mpv ``wid=`` HWND, so this is a
frameless ``Qt.Tool`` (same family as buffering / queue hover). Opacity eases
in, holds, then eases out — about one second total.

Rapid clicks **interrupt** the current gesture: the glyph swaps immediately and
the appear→hold→fade cycle restarts for the new play/pause action.

On Windows the Tool HWND must be ``WS_EX_TRANSPARENT`` so clicks pass through to
the embed while the circle is visible — otherwise the center of the picture
eats LMB and YouTube-style interrupt is impossible.
"""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

_SW_SHOWNOACTIVATE = 4
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000

# ~1s gesture: soft appear, brief hold, soft disappear.
_FADE_IN_S = 0.18
_HOLD_S = 0.42
_FADE_OUT_S = 0.40
_TOTAL_S = _FADE_IN_S + _HOLD_S + _FADE_OUT_S

_CIRCLE_PX = 100
_GLYPH_PX = 44
_DISK_ALPHA = 150  # dark disk at full opacity


class PlayPausePulseOverlay(QWidget):
    """Centered dark circle + play/pause glyph that fades in and out."""

    def __init__(self, parent=None):
        super().__init__(None if sys.platform == "win32" else parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFixedSize(_CIRCLE_PX, _CIRCLE_PX)

        self._opacity = 0.0
        self._scale = 0.82
        self._glyph = QPixmap()
        self._paused = None
        self._t0 = 0.0
        self._anchor = None
        self._glyph_cache: dict[bool, QPixmap] = {}

        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._on_tick)
        self.hide()

    def _glyph_for(self, *, paused: bool) -> QPixmap:
        cached = self._glyph_cache.get(paused)
        if cached is not None and not cached.isNull():
            return cached
        from steempeg.ui.icon_assets import _glyph_pixmap_from_bw

        name = "pause_player.png" if paused else "play2.png"
        pix = _glyph_pixmap_from_bw(name, _GLYPH_PX, color="#ffffff")
        self._glyph_cache[paused] = pix
        return pix

    def pulse(self, anchor_widget, *, paused: bool) -> bool:
        """Show pause glyph when now paused, play glyph when now playing.

        Safe to call mid-animation — swaps the glyph and restarts the cycle.

        Returns True when the Tool window was newly mapped (caller should briefly
        ignore phantom Win32 clicks from ``ShowWindow``).
        """
        was_hidden = not self.isVisible()
        interrupted = self._tick.isActive() and not was_hidden
        self._glyph = self._glyph_for(paused=paused)
        self._paused = bool(paused)
        self._anchor = anchor_widget
        # Interrupt: pop from a soft mid-opacity so the swap reads instantly,
        # then re-run appear→hold→fade for the new action.
        if interrupted and self._opacity > 0.15:
            self._opacity = min(1.0, max(0.35, self._opacity))
            self._scale = 0.88
            # Shift t0 so we sit near the end of fade-in (snappy restart).
            self._t0 = time.monotonic() - (_FADE_IN_S * 0.55)
        else:
            self._opacity = 0.0
            self._scale = 0.82
            self._t0 = time.monotonic()
        self._reposition()
        newly_mapped = False
        if was_hidden:
            # Fresh map — ShowWindow can synthesize a second LMB on Windows.
            self._show_without_activating()
            newly_mapped = True
        else:
            # Already up (interrupt): never re-ShowWindow; just keep click-through.
            self._apply_click_through()
        if not self._tick.isActive():
            self._tick.start()
        self.update()
        return newly_mapped

    def cancel(self) -> None:
        self._tick.stop()
        self._opacity = 0.0
        self._paused = None
        self.hide()

    def _apply_click_through(self) -> None:
        """Win32: hit-test transparent so LMB reaches the mpv embed underneath."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            self.createWinId()
            hwnd = int(self.winId())
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            ex = int(user32.GetWindowLongW(hwnd, _GWL_EXSTYLE))
            want = _WS_EX_TRANSPARENT | _WS_EX_LAYERED | _WS_EX_NOACTIVATE
            if (ex & want) != want:
                user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | want)
        except Exception:
            pass

    def _show_without_activating(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if sys.platform == "win32":
            try:
                from steempeg.infra.window_focus import detach_tool_ownership

                detach_tool_ownership(self)
            except Exception:
                pass
            try:
                import ctypes

                self.createWinId()
                self._apply_click_through()
                hwnd = int(self.winId())
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
                    if not self.isVisible():
                        super().setVisible(True)
                    return
            except Exception:
                pass
        self.show()

    def _reposition(self) -> None:
        anchor = self._anchor
        if anchor is None:
            return
        try:
            if not anchor.isVisible():
                return
            center = anchor.mapToGlobal(anchor.rect().center())
        except RuntimeError:
            return
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
        # Re-assert click-through after move/show — Qt can drop exstyles.
        self._apply_click_through()

    def _on_tick(self) -> None:
        elapsed = time.monotonic() - self._t0
        if elapsed >= _TOTAL_S:
            self._tick.stop()
            self._opacity = 0.0
            self.hide()
            return

        if elapsed < _FADE_IN_S:
            t = elapsed / _FADE_IN_S
            # Ease-out cubic for a soft settle.
            eased = 1.0 - (1.0 - t) ** 3
            self._opacity = eased
            self._scale = 0.82 + 0.18 * eased
        elif elapsed < _FADE_IN_S + _HOLD_S:
            self._opacity = 1.0
            self._scale = 1.0
        else:
            t = (elapsed - _FADE_IN_S - _HOLD_S) / _FADE_OUT_S
            eased = t * t  # ease-in for a soft dissolve
            self._opacity = 1.0 - eased
            self._scale = 1.0

        self._reposition()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        if self._opacity <= 0.01:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(self._opacity)

        side = _CIRCLE_PX * self._scale
        pad = (_CIRCLE_PX - side) / 2.0
        disk = QRectF(pad, pad, side, side)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, _DISK_ALPHA))
        painter.drawEllipse(disk)

        if not self._glyph.isNull():
            gw = self._glyph.width()
            gh = self._glyph.height()
            gx = (self.width() - gw) / 2.0
            gy = (self.height() - gh) / 2.0
            painter.drawPixmap(int(gx), int(gy), self._glyph)
        painter.end()
