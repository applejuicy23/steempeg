"""Custom-painted vertical scrollbars — capsule thumb/track like the player timeline."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import QColor, QPainter, QMouseEvent
from PySide6.QtWidgets import QScrollBar, QWidget


@dataclass(frozen=True)
class VerticalScrollbarChrome:
    """Paint tokens for a Steempeg vertical scrollbar."""

    track_color: QColor | None
    thumb_color: QColor
    thumb_hover_color: QColor
    width: int = 12
    margin_left: int = 2
    margin_right: int = 2
    margin_top: int = 4
    margin_bottom: int = 4
    # Keep grab-able even when the document is huge (Screenshots × thousands).
    min_thumb_extent: int = 40


def _library_chrome() -> VerticalScrollbarChrome:
    from steempeg.ui.library.library_styles import (
        SCROLLBAR_THUMB,
        SCROLLBAR_THUMB_HOVER,
        SCROLLBAR_TRACK,
        SCROLLBAR_WIDTH,
    )

    return VerticalScrollbarChrome(
        track_color=QColor(SCROLLBAR_TRACK),
        thumb_color=QColor(SCROLLBAR_THUMB),
        thumb_hover_color=QColor(SCROLLBAR_THUMB_HOVER),
        width=SCROLLBAR_WIDTH,
        margin_left=2,
        margin_right=2,
        margin_top=4,
        margin_bottom=4,
        min_thumb_extent=40,
    )


def settings_scrollbar_chrome() -> VerticalScrollbarChrome:
    """Render settings panel — invisible track, rounded thumb only."""
    return VerticalScrollbarChrome(
        track_color=None,
        thumb_color=QColor("#5a4b7a"),
        thumb_hover_color=QColor("#8e7cc3"),
        width=12,
        margin_left=0,
        margin_right=5,
        margin_top=15,
        margin_bottom=15,
        min_thumb_extent=36,
    )


def filters_games_scrollbar_chrome() -> VerticalScrollbarChrome:
    """Compact games filter strip — invisible track."""
    from steempeg.ui import ui_theme as ut

    p = ut.active_palette()
    if p.name == ut.UI_THEME_DEFAULT:
        thumb, hover = "#4e4e4e", "#b29ae7"
    else:
        thumb = p.border_default
        hover = "#b29ae7"
    return VerticalScrollbarChrome(
        track_color=None,
        thumb_color=QColor(thumb),
        thumb_hover_color=QColor(hover),
        width=8,
        margin_left=2,
        margin_right=2,
        margin_top=2,
        margin_bottom=2,
        min_thumb_extent=28,
    )


def error_dialog_scrollbar_chrome() -> VerticalScrollbarChrome:
    """Render error dialog — theme track + gray thumb (Default legacy / TrueDark tokens)."""
    from steempeg.ui import ui_theme as ut

    track, thumb, hover = ut.render_error_scrollbar_colors()
    return VerticalScrollbarChrome(
        track_color=QColor(track),
        thumb_color=QColor(thumb),
        thumb_hover_color=QColor(hover),
        width=12,
        margin_left=2,
        margin_right=2,
        margin_top=2,
        margin_bottom=2,
        min_thumb_extent=28,
    )


class SteempegVerticalScrollBar(QScrollBar):
    """Rounded capsule vertical scrollbar (TimelineOverviewScrollBar vertical twin).

    Own hit-testing: Qt's native slider shrinks to 1–2px with huge lists (8k
    Screenshots), so paint + drag/click use a floor ``min_thumb_extent``. Track
    click jumps to that position (scroll-to-here); LMB or RMB can drag.
    """

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
        *,
        chrome: VerticalScrollbarChrome | None = None,
    ):
        super().__init__(orientation, parent)
        self._chrome = chrome or _library_chrome()
        self._press_grab_offset = 0
        self._dragging = False
        self.setMouseTracking(True)
        self.setFixedWidth(self._chrome.width)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        # Hide native chrome — we paint + handle mouse ourselves.
        self.setStyleSheet(
            "QScrollBar:vertical { background: transparent; border: none; }"
            " QScrollBar::handle:vertical { background: transparent; border: none; }"
            " QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
            " { height: 0px; border: none; background: none; }"
            " QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical"
            " { background: none; }"
        )

    def set_chrome(self, chrome: VerticalScrollbarChrome) -> None:
        self._chrome = chrome
        self.setFixedWidth(chrome.width)
        self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def _groove_rect(self) -> QRect:
        c = self._chrome
        return self.rect().adjusted(
            c.margin_left,
            c.margin_top,
            -c.margin_right,
            -c.margin_bottom,
        )

    def _thumb_metrics(self, groove: QRect) -> tuple[int, int]:
        """Return (thumb_h, usable_travel) for the painted / hit thumb."""
        gmin, gmax = int(self.minimum()), int(self.maximum())
        page = max(1, int(self.pageStep()))
        span = gmax - gmin
        gh = max(1, groove.height())
        if span <= 0:
            return gh, 0
        thumb_h = max(
            int(self._chrome.min_thumb_extent),
            int(round(gh * page / float(span + page))),
        )
        thumb_h = min(thumb_h, gh)
        usable = max(0, gh - thumb_h)
        return thumb_h, usable

    def _thumb_rect(self, groove: QRect | None = None) -> QRect:
        groove = groove if groove is not None else self._groove_rect()
        gmin, gmax = int(self.minimum()), int(self.maximum())
        span = gmax - gmin
        thumb_h, usable = self._thumb_metrics(groove)
        if span <= 0 or usable <= 0:
            return QRect(groove.left(), groove.top(), groove.width(), thumb_h)
        y = groove.top() + int(
            round(usable * (int(self.value()) - gmin) / float(span))
        )
        return QRect(groove.left(), y, groove.width(), thumb_h)

    def _value_for_thumb_top(self, thumb_top: int, groove: QRect | None = None) -> int:
        groove = groove if groove is not None else self._groove_rect()
        gmin, gmax = int(self.minimum()), int(self.maximum())
        span = gmax - gmin
        _thumb_h, usable = self._thumb_metrics(groove)
        if span <= 0 or usable <= 0:
            return gmin
        rel = max(0, min(usable, int(thumb_top) - groove.top()))
        return gmin + int(round(span * rel / float(usable)))

    def _value_for_click_y(self, y: int, groove: QRect | None = None) -> int:
        """Map a track click so the thumb centers on ``y`` (scroll-to-here)."""
        groove = groove if groove is not None else self._groove_rect()
        thumb_h, _usable = self._thumb_metrics(groove)
        return self._value_for_thumb_top(int(y) - thumb_h // 2, groove)

    def _is_scroll_button(self, button: Qt.MouseButton) -> bool:
        return button in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.MiddleButton,
        )

    def mousePressEvent(self, event: QMouseEvent):
        if self.orientation() != Qt.Orientation.Vertical or not self._is_scroll_button(
            event.button()
        ):
            super().mousePressEvent(event)
            return

        pos = event.position().toPoint()
        groove = self._groove_rect()
        # Widen hit box to the full bar width — margins are paint-only.
        hit_groove = QRect(0, groove.top(), self.width(), groove.height())
        if not hit_groove.contains(pos) and not groove.contains(pos):
            event.accept()
            return

        thumb = self._thumb_rect(groove)
        # Slightly taller grab slop so a near-miss still starts a drag.
        grab = thumb.adjusted(0, -4, 0, 4)
        grab.setLeft(0)
        grab.setWidth(self.width())

        if grab.contains(pos):
            self._dragging = True
            self._press_grab_offset = pos.y() - thumb.top()
            self.setSliderDown(True)
        else:
            # Track click → jump thumb to this spot, then allow drag.
            self.setValue(self._value_for_click_y(pos.y(), groove))
            thumb = self._thumb_rect(groove)
            self._dragging = True
            self._press_grab_offset = pos.y() - thumb.top()
            self.setSliderDown(True)
        self.update()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.orientation() != Qt.Orientation.Vertical:
            super().mouseMoveEvent(event)
            return
        if self._dragging and self.isSliderDown():
            groove = self._groove_rect()
            thumb_top = int(event.position().y()) - self._press_grab_offset
            self.setValue(self._value_for_thumb_top(thumb_top, groove))
            event.accept()
            return
        super().mouseMoveEvent(event)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.orientation() != Qt.Orientation.Vertical or not self._is_scroll_button(
            event.button()
        ):
            super().mouseReleaseEvent(event)
            return
        if self._dragging:
            self._dragging = False
            self.setSliderDown(False)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        groove = self._groove_rect()
        if groove.width() <= 1 or groove.height() <= 1:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        radius = float(groove.width()) * 0.5

        track = self._chrome.track_color
        if track is not None:
            painter.setBrush(track)
            painter.drawRoundedRect(QRectF(groove), radius, radius)

        thumb = self._thumb_rect(groove)
        if thumb.width() > 0 and thumb.height() > 0:
            active = self.underMouse() or self.isSliderDown()
            painter.setBrush(
                self._chrome.thumb_hover_color
                if active
                else self._chrome.thumb_color
            )
            painter.drawRoundedRect(QRectF(thumb), radius, radius)

        painter.end()


def ensure_steempg_vertical_scrollbar(
    host: QWidget,
    *,
    chrome: VerticalScrollbarChrome | None = None,
) -> SteempegVerticalScrollBar:
    """Replace the host's vertical scrollbar with a painted capsule bar (idempotent)."""
    bar = host.verticalScrollBar()
    resolved = chrome or _library_chrome()
    if isinstance(bar, SteempegVerticalScrollBar):
        bar.set_chrome(resolved)
        return bar
    custom = SteempegVerticalScrollBar(
        Qt.Orientation.Vertical, host, chrome=resolved
    )
    host.setVerticalScrollBar(custom)
    return custom
