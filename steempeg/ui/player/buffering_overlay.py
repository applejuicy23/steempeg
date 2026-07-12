"""Buffering indicator for the player.

This is intentionally a SEPARATE top-level window (Qt.Tool), not a child widget
mounted over the native mpv video surface. The previous overlay was a non-native
QWidget drawn on top of the native mpv window, which forced an expensive
re-composition on every repaint and made the splitters stutter. A floating tool
window is composited independently by the OS, so dragging the splitters never
touches it — the same proven pattern as the fullscreen HUD and the screenshot
toast.
"""
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class BufferingOverlay(QWidget):
    """A small rounded 'Buffering…' pill with an animated spinner."""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._angle = 0
        self._message = "Buffering…"
        self.resize(168, 60)

        self._spin = QTimer(self)
        self._spin.setInterval(33)
        self._spin.timeout.connect(self._advance)
        self.hide()

    def _advance(self):
        self._angle = (self._angle + 24) % 360
        self.update()

    def show_loading(self, anchor_widget, message="Buffering…"):
        from PySide6.QtWidgets import QApplication

        if QApplication.instance().applicationState() != Qt.ApplicationState.ApplicationActive:
            self.hide_loading()
            return
        self._message = message
        self._reposition(anchor_widget)
        if not self._spin.isActive():
            self._spin.start()
        if not self.isVisible():
            self.show()
            self.raise_()

    def hide_loading(self):
        self._spin.stop()
        self.hide()

    def _reposition(self, anchor_widget):
        """Center the pill over the anchor (the video surface), in global coords."""
        if anchor_widget is None or not anchor_widget.isVisible():
            return
        center = anchor_widget.mapToGlobal(anchor_widget.rect().center())
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Rounded dark pill background.
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 225))
        painter.drawRoundedRect(rect, 14, 14)

        # Spinner arc on the left.
        cx, cy, r = 30.0, self.height() / 2.0, 11.0
        pen = QPen(QColor("#b29ae7"))
        pen.setWidth(4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(
            int(cx - r), int(cy - r), int(2 * r), int(2 * r),
            self._angle * 16, 110 * 16,
        )

        # Message text to the right of the spinner.
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
