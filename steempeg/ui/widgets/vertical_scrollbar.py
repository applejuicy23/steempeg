"""Custom-painted vertical scrollbars — capsule thumb/track like the player timeline."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QScrollBar, QStyle, QStyleOptionSlider, QWidget


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
    min_thumb_extent: int = 30


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
        min_thumb_extent=24,
    )


def error_dialog_scrollbar_chrome() -> VerticalScrollbarChrome:
    """Render error dialog — dark track + gray thumb."""
    return VerticalScrollbarChrome(
        track_color=QColor("#141414"),
        thumb_color=QColor("#444444"),
        thumb_hover_color=QColor("#666666"),
        width=12,
        margin_left=2,
        margin_right=2,
        margin_top=2,
        margin_bottom=2,
        min_thumb_extent=20,
    )


class SteempegVerticalScrollBar(QScrollBar):
    """Rounded capsule vertical scrollbar (TimelineOverviewScrollBar vertical twin)."""

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
        *,
        chrome: VerticalScrollbarChrome | None = None,
    ):
        super().__init__(orientation, parent)
        self._chrome = chrome or _library_chrome()
        self.setMouseTracking(True)
        self.setFixedWidth(self._chrome.width)
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

    def _thumb_rect(self, groove: QRect) -> QRect:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        thumb = self.style().subControlRect(
            QStyle.ComplexControl.CC_ScrollBar,
            opt,
            QStyle.SubControl.SC_ScrollBarSlider,
            self,
        )
        if thumb.width() > 1 and thumb.height() > 1:
            return QRect(groove.left(), thumb.y(), groove.width(), thumb.height())

        gmin, gmax = int(self.minimum()), int(self.maximum())
        page = max(1, int(self.pageStep()))
        span = gmax - gmin
        gh = max(1, groove.height())
        if span <= 0:
            return QRect(groove.left(), groove.top(), groove.width(), gh)
        thumb_h = max(
            self._chrome.min_thumb_extent,
            int(round(gh * page / float(span + page))),
        )
        thumb_h = min(thumb_h, gh)
        usable = max(0, gh - thumb_h)
        y = groove.top() + int(
            round(usable * (int(self.value()) - gmin) / float(span))
        )
        return QRect(groove.left(), y, groove.width(), thumb_h)

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
