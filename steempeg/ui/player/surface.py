"""The video surface that libmpv renders into, plus a 16:9 aspect helper.

MPVWrapper owns the child window the mpv player attaches to, draws an optional
highlight border and keeps the video centered at 16:9. VideoAspectKeeper caps a
widget's height to a 16:9 ratio so black bars do not appear above and below.

Geometry follows the Windows formula: synchronous update_geometry on resize /
move / show and on splitterMoved, with an early-out when the video rect is
unchanged.

Trim border:
  * Windows — four native child widgets + QSS ``#ffcc00`` (same HWND stack as
    the embed; compositor handles it).
  * Linux — paint the ring in ``paintEvent`` on this (non-native) wrapper.
    Sibling QWidgets next to a wid= X11 surface force recompositing and bring
    back the splitter tear; QSS on native X11 children also does not fill.

On Linux, native embed is opt-in via ``prepare_native_embed()`` (called right
before ``winId()``) so startup does not create X11 children under NVIDIA.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class MPVWrapper(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.aspect_frame = self

        self._is_border_active = False
        self._border_ring = None  # (x, y, total_w, total_h, b, video_h) for Linux paint
        # Windows: native child from the start. Linux: plain Qt until embed.
        self._native_embed = sys.platform == "win32"

        self.mpv_screen = QWidget(self)
        if self._native_embed:
            self._apply_native_attrs(self.mpv_screen, for_video=True)
        else:
            # Placeholder until prepare_native_embed() / external mpv window.
            self.mpv_screen.setStyleSheet("background-color: #0a0a0a;")

        self.lines = []
        if sys.platform == "win32":
            for _ in range(4):
                line = QWidget(self)
                self._apply_native_attrs(line, for_video=False)
                line.setStyleSheet("background-color: #ffcc00;")
                line.hide()
                self.lines.append(line)
            self.top_line, self.bottom_line, self.left_line, self.right_line = self.lines
        else:
            self.top_line = self.bottom_line = self.left_line = self.right_line = None

        self.setStyleSheet("background-color: transparent;")

    @staticmethod
    def _apply_native_attrs(widget: QWidget, *, for_video: bool) -> None:
        widget.setAttribute(Qt.WA_NativeWindow)
        # Critical on Linux: without this, winId() native-izes ancestors
        # (left_panel etc.) → flicker + "must be a top level window" spam.
        widget.setAttribute(Qt.WA_DontCreateNativeAncestors)
        if for_video:
            widget.setAttribute(Qt.WA_OpaquePaintEvent)
            widget.setAttribute(Qt.WA_NoSystemBackground)

    def prepare_native_embed(self) -> None:
        """Enable a wid=-safe native video child on Linux right before creating libmpv."""
        if self._native_embed:
            return
        self._native_embed = True
        self.mpv_screen.setStyleSheet("")
        self._apply_native_attrs(self.mpv_screen, for_video=True)

    def setStyleSheet(self, style):
        if "#ffcc00" in style:
            self.set_border_active(True)
        elif "transparent" in style or "none" in style:
            self.set_border_active(False)
        super().setStyleSheet("background-color: transparent;")

    def paintEvent(self, event):
        super().paintEvent(event)
        # Linux-only: yellow trim without sibling widgets (see module docstring).
        if sys.platform == "win32":
            return
        if not getattr(self, "_is_border_active", False):
            return
        ring = getattr(self, "_border_ring", None)
        if not ring:
            return
        x, y, total_w, total_h, b, video_h = ring
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffcc00"))
        painter.drawRect(x, y, total_w, b)
        painter.drawRect(x, y + total_h - b, total_w, b)
        painter.drawRect(x, y + b, b, video_h)
        painter.drawRect(x + total_w - b, y + b, b, video_h)

    def _park_mpv_screen(self):
        """Hide the native embed so it cannot punch through stacked siblings.

        QStackedLayout only toggles Qt visibility; a WA_NativeWindow child that
        is shown() during a resize (e.g. entering immersive mode on the idle
        placeholder) can still paint an empty gray GPU surface on top.
        """
        self.mpv_screen.setGeometry(0, 0, 0, 0)
        self.mpv_screen.hide()
        for line in self.lines:
            line.hide()
        self._border_ring = None
        if getattr(self, "hud_reference", None) and self.hud_reference.parent() == self:
            self.hud_reference.hide()
        self._last_video_rect = (0, 0, 0, 0)
        if sys.platform != "win32":
            self.update()

    def update_geometry(self):
        w = self.width()
        h = self.height()

        # Hidden in the video stack (placeholder / blank): never show the native
        # surface — fullscreen resize used to call show() here and cover the UI.
        if w < 5 or h < 5 or not self.isVisible():
            self._park_mpv_screen()
            return

        if self.mpv_screen.isHidden():
            self.mpv_screen.show()
            if getattr(self, "_is_border_active", False):
                for line in self.lines:
                    line.show()
            if getattr(self, "hud_reference", None) and self.hud_reference.parent() == self:
                self.hud_reference.show()

        b = 3 if getattr(self, "_is_border_active", False) else 0

        avail_w = w - (b * 2)
        avail_h = h - (b * 2)

        if avail_w * 9 > avail_h * 16:
            video_h = avail_h
            video_w = int(avail_h * 16 / 9)
        else:
            video_w = avail_w
            video_h = int(avail_w * 9 / 16)

        total_w = video_w + (b * 2)
        total_h = video_h + (b * 2)

        x = (w - total_w) // 2
        y = (h - total_h) // 2

        video_rect = (x + b, y + b, video_w, video_h)
        border_ring = (
            (x, y, total_w, total_h, b, video_h)
            if getattr(self, "_is_border_active", False) and b > 0
            else None
        )
        # Skip redundant ConfigureWindow when nothing changed (multi-caller paths).
        if (
            getattr(self, "_last_video_rect", None) == video_rect
            and getattr(self, "_border_ring", None) == border_ring
        ):
            return
        self._last_video_rect = video_rect
        self._border_ring = border_ring

        self.mpv_screen.setGeometry(*video_rect)

        if self.lines and border_ring is not None:
            self.top_line.setGeometry(x, y, total_w, b)
            self.bottom_line.setGeometry(x, y + total_h - b, total_w, b)
            self.left_line.setGeometry(x, y + b, b, video_h)
            self.right_line.setGeometry(x + total_w - b, y + b, b, video_h)
            for line in self.lines:
                line.raise_()

        if sys.platform != "win32":
            self.update()

        if getattr(self, "hud_reference", None) and self.hud_reference.parent() == self:
            hud = self.hud_reference
            hud_h = max(55, hud.sizeHint().height())
            hud_w = min(800, w - 40)
            hud.setGeometry((w - hud_w) // 2, h - hud_h - 30, hud_w, hud_h)
            hud.raise_()

    def resizeEvent(self, event):
        self.update_geometry()
        super().resizeEvent(event)

    def moveEvent(self, event):
        # Native embed does not always track parent moves during splitter drags.
        self.update_geometry()
        super().moveEvent(event)

    def showEvent(self, event):
        self.update_geometry()
        super().showEvent(event)

    def set_border_active(self, active):
        if active == getattr(self, "_is_border_active", None):
            return

        self._is_border_active = active
        self._last_video_rect = None
        for line in self.lines:
            if active:
                line.show()
                line.raise_()
            else:
                line.hide()

        self.update_geometry()
        if sys.platform != "win32":
            self.update()


class VideoAspectKeeper(QObject):
    """Keeps the widget strictly within the 16:9 aspect ratio."""

    def __init__(self, video_widget):
        super().__init__(video_widget)
        self.video_widget = video_widget
        self.video_widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            w = event.size().width()
            ideal_height = int(w * 9 / 16)
            if self.video_widget.maximumHeight() != ideal_height:
                self.video_widget.setMaximumHeight(ideal_height)

        return super().eventFilter(obj, event)
