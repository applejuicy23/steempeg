"""Buffering indicator for the player.

This is intentionally a SEPARATE top-level window (Qt.Tool), not a child widget
mounted over the native mpv video surface. A floating tool window is composited
independently by the OS, so dragging the splitters never touches it.

Windows: never own / transient-parent this Tool to the Steempeg shell, never
``SetWindowPos`` relative to the shell, and only show after the shell has been
the real OS foreground for a short dwell. Otherwise opening Explorer / Zen while
video plays races a Buffering flicker and Steempeg jumps over that window.
"""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

_SW_SHOWNOACTIVATE = 4
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
# Must hold OS foreground this long before the pill may appear (Explorer open race).
_FOREGROUND_DWELL_SEC = 0.45


def _shell_hwnd(anchor_widget) -> int:
    if anchor_widget is None:
        return 0
    try:
        shell = anchor_widget.window()
        if shell is None:
            return 0
        return int(shell.winId()) or 0
    except Exception:
        return 0


def _foreground_hwnd() -> int:
    if sys.platform != "win32":
        return 0
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _shell_is_true_foreground(anchor_widget) -> bool:
    """True only when the Steempeg shell HWND (or a child) is OS foreground."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        hwnd = _shell_hwnd(anchor_widget)
        if not hwnd:
            return False
        fg = _foreground_hwnd()
        if not fg:
            return False
        if fg == hwnd:
            return True
        return bool(ctypes.windll.user32.IsChild(hwnd, fg))
    except Exception:
        return False


class BufferingOverlay(QWidget):
    """A small rounded 'Buffering…' pill with an animated spinner."""

    def __init__(self, parent=None):
        # Always unowned on Windows — parent would make show() re-stack Steempeg.
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

        self._angle = 0
        self._message = "Buffering…"
        self.resize(168, 60)
        self._shell = None
        self._fg_since: float | None = None

        self._spin = QTimer(self)
        self._spin.setInterval(33)
        self._spin.timeout.connect(self._advance)
        self.hide()

    def _advance(self):
        self._angle = (self._angle + 24) % 360
        self.update()

    def _track_foreground_dwell(self, anchor_widget) -> bool:
        """Update dwell clock; True when shell has been FG long enough to show."""
        if not _shell_is_true_foreground(anchor_widget):
            self._fg_since = None
            return False
        now = time.monotonic()
        if self._fg_since is None:
            self._fg_since = now
            return False
        return (now - self._fg_since) >= _FOREGROUND_DWELL_SEC

    def _ensure_detached_noactivate(self) -> None:
        """No owner, no transient parent, WS_EX_NOACTIVATE."""
        if sys.platform != "win32":
            return
        try:
            from steempeg.infra.window_focus import detach_tool_ownership

            detach_tool_ownership(self)
        except Exception:
            pass
        try:
            import ctypes

            self.createWinId()
            hwnd = int(self.winId())
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            ex = int(user32.GetWindowLongW(hwnd, _GWL_EXSTYLE))
            if not (ex & _WS_EX_NOACTIVATE):
                user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_NOACTIVATE)
        except Exception:
            pass

    def _show_without_activating(self) -> None:
        """Show the pill without moving Steempeg in the global Z-order."""
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if sys.platform == "win32":
            try:
                import ctypes

                self._ensure_detached_noactivate()
                hwnd = int(self.winId())
                if hwnd:
                    # Only ShowWindow — do NOT SetWindowPos relative to the shell
                    # (that can promote Steempeg over Explorer mid-open).
                    ctypes.windll.user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
                    if not self.isVisible():
                        super().setVisible(True)
                    return
            except Exception:
                pass
        self.show()

    def show_loading(self, anchor_widget, message="Buffering…"):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None or app.applicationState() != Qt.ApplicationState.ApplicationActive:
            self._fg_since = None
            self.hide_loading()
            return
        # Race guard: Explorer/browser often take FG a beat after click; refuse
        # to show until Steempeg has been true OS foreground for a dwell.
        if not self._track_foreground_dwell(anchor_widget):
            self.hide_loading()
            return
        try:
            win = anchor_widget.window() if anchor_widget is not None else None
            self._shell = win
            if win is not None and (win.isMinimized() or not win.isVisible()):
                self.hide_loading()
                return
        except RuntimeError:
            self.hide_loading()
            return
        try:
            from PySide6.QtWidgets import QApplication as _QA

            modal = _QA.activeModalWidget()
            if modal is not None and modal is not self:
                self.hide_loading()
                return
        except Exception:
            pass
        self._message = message
        self._reposition(anchor_widget)
        if not self._spin.isActive():
            self._spin.start()
        if not self.isVisible():
            self._show_without_activating()

    def hide_loading(self):
        self._spin.stop()
        self.hide()

    def note_foreground_lost(self) -> None:
        """Reset dwell when the app / shell loses OS focus."""
        self._fg_since = None
        self.hide_loading()

    def _reposition(self, anchor_widget):
        """Center the pill over the anchor (the video surface), in global coords."""
        if anchor_widget is None or not anchor_widget.isVisible():
            return
        center = anchor_widget.mapToGlobal(anchor_widget.rect().center())
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 225))
        painter.drawRoundedRect(rect, 14, 14)

        cx, cy, r = 30.0, self.height() / 2.0, 11.0
        pen = QPen(QColor("#b29ae7"))
        pen.setWidth(4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(
            int(cx - r), int(cy - r), int(2 * r), int(2 * r),
            self._angle * 16, 110 * 16,
        )

        painter.setPen(QColor("#eeeeee"))
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        text_rect = QRectF(52, 0, self.width() - 60, self.height())
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._message,
        )
