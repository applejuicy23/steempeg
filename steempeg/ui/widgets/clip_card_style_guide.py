"""ClipCard style pictures: the ? card, and the panel beside the open list.

The open list shows the row under the pointer. The ? circle keeps explaining
the style that is already chosen.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut

_BLURB_W = 196


def _mode_key(value: object) -> str:
    """The list id, without any extra context packed after a pipe."""
    return str(value or "").split("|", 1)[0]


def clip_card_style_copy(style: str) -> tuple[str, str, str]:
    """Returns the mode name, the short line, and the ? explanation."""
    style = str(style or "")
    if style == "square":
        return (
            "Square",
            "Every corner is square.",
            "Every corner is square.\n"
            "A card above or below does not change the shape.",
        )
    if style == "round":
        return (
            "Round",
            "Every corner is round.",
            "Every corner is round.\n"
            "A card above or below does not change the shape.",
        )
    return (
        "SteempegUI",
        "Corners follow the card above and the card below.",
        "No card above: square top.\n"
        "A card above: round top.\n"
        "A card below: round bottom.\n"
        "No card below: square bottom.",
    )


def clip_card_style_help(style: str) -> str:
    """Explanation the ? circle shows for the style that is already chosen."""
    return clip_card_style_copy(style)[2]


def _corner_path(rect: QRectF, radii: tuple[float, float, float, float]) -> QPainterPath:
    """Rounded rectangle. Radii are top-left, top-right, bottom-right, bottom-left."""
    tl, tr, br, bl = radii
    path = QPainterPath()
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path.moveTo(x + tl, y)
    path.lineTo(x + w - tr, y)
    if tr:
        path.arcTo(QRectF(x + w - 2 * tr, y, 2 * tr, 2 * tr), 90, -90)
    path.lineTo(x + w, y + h - br)
    if br:
        path.arcTo(QRectF(x + w - 2 * br, y + h - 2 * br, 2 * br, 2 * br), 0, -90)
    path.lineTo(x + bl, y + h)
    if bl:
        path.arcTo(QRectF(x, y + h - 2 * bl, 2 * bl, 2 * bl), 270, -90)
    path.lineTo(x, y + tl)
    if tl:
        path.arcTo(QRectF(x, y, 2 * tl, 2 * tl), 180, -90)
    path.closeSubpath()
    return path


class ClipCardStyleDiagram(QWidget):
    """Six mini cards, two columns. Corners follow one ClipCard style."""

    _COLS = 2
    _ROWS = 3
    _CARD_W = 40
    _CARD_H = 28
    _GAP = 5
    _RADIUS = 7.0

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        width = self._COLS * self._CARD_W + (self._COLS - 1) * self._GAP
        height = self._ROWS * self._CARD_H + (self._ROWS - 1) * self._GAP
        self.setFixedSize(width, height)
        self._style = "steempeg_ui"
        self.setStyleSheet("background: transparent;")

    def set_style(self, style: str) -> None:
        """Redraws the six cards for ``steempeg_ui``, ``square``, or ``round``."""
        self._style = style or "steempeg_ui"
        self.update()

    def _radii(self, row: int) -> tuple[float, float, float, float]:
        """Returns this row's corner radii for the style being shown."""
        radius = self._RADIUS
        if self._style == "round":
            return (radius, radius, radius, radius)
        if self._style == "square":
            return (0.0, 0.0, 0.0, 0.0)
        if row <= 0:
            return (0.0, 0.0, radius, radius)
        if row >= self._ROWS - 1:
            return (radius, radius, 0.0, 0.0)
        return (radius, radius, radius, radius)

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        thumb = QColor("#8b74c4")
        footer = QColor("#4a4560")
        edge = QColor("#c4b6e4")
        for row in range(self._ROWS):
            radii = self._radii(row)
            for col in range(self._COLS):
                x = col * (self._CARD_W + self._GAP)
                y = row * (self._CARD_H + self._GAP)
                rect = QRectF(x + 0.5, y + 0.5, self._CARD_W - 1, self._CARD_H - 1)
                path = _corner_path(rect, radii)
                painter.save()
                painter.setClipPath(path)
                painter.fillPath(path, footer)
                painter.fillRect(
                    QRectF(rect.x(), rect.y(), rect.width(), rect.height() * 0.62),
                    thumb,
                )
                painter.restore()
                painter.setPen(QPen(edge, 1.0))
                painter.drawPath(path)
        painter.end()


class _ClipCardStylePopupGuide(QWidget):
    """Name, short line, and preview beside an open style list."""

    _RADIUS = 10.0

    def __init__(self, parent: QWidget | None, diagram: QWidget, copy_of):
        self._copy_of = copy_of
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self._bg = "#1a1a1a"
        self._border = "#333333"
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self._mark = QLabel(self)
        self._mark.setFixedSize(16, 16)
        self._mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mark.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._title = QLabel(self)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        title_row.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self._title, 1, Qt.AlignmentFlag.AlignVCenter)
        self._blurb = QLabel(self)
        self._blurb.setWordWrap(True)
        self._blurb.setTextFormat(Qt.TextFormat.PlainText)
        self._blurb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._diagram = diagram
        diagram.setParent(self)
        self._shown = ("", False)
        lay.addLayout(title_row)
        lay.addWidget(self._blurb)
        lay.addWidget(self._diagram, 0, Qt.AlignmentFlag.AlignLeft)
        self._apply_font()

    def show_style(self, style: str, combo: QComboBox) -> None:
        """Shows this mode to the right of the open list.

        A white check sits in front of the name only when this mode is the
        one already chosen in the list.
        """
        chosen = _mode_key(combo.currentData()) == _mode_key(style)
        if self.isVisible() and self._shown == (style, chosen):
            return
        self._shown = (style, chosen)
        self._apply_font()
        title, blurb, _help = self._copy_of(style)
        self._title.setText(title)
        self._blurb.setText(blurb)
        self._mark.setVisible(chosen)
        self._diagram.set_style(style)
        self._fit(title, blurb)
        self._apply_mask()
        self._place(combo)
        self._show_passive()
        QTimer.singleShot(0, lambda combo=combo: self._place_if_shown(combo))

    def _place_if_shown(self, combo: QComboBox) -> None:
        """The list's window gets its real place after the popup opens."""
        view = combo.view()
        if view is not None and view.isVisible() and self.isVisible():
            self._place(combo)

    def _fit(self, title: str, blurb: str) -> None:
        """Sizes the panel to this mode's own words."""
        self._title.setMinimumWidth(0)
        self._title.setMaximumWidth(16777215)
        self._blurb.setMinimumWidth(0)
        self._blurb.setMaximumWidth(16777215)
        title_w = self._title.fontMetrics().horizontalAdvance(title) + 4
        if self._mark.isVisible():
            title_w += self._mark.width() + 6
        has_blurb = bool(blurb.strip())
        self._blurb.setVisible(has_blurb)
        blurb_w = (
            min(self._blurb.fontMetrics().horizontalAdvance(blurb) + 4, _BLURB_W)
            if has_blurb
            else 0
        )
        text_w = max(title_w, blurb_w, self._diagram.width(), 1)
        lead = (self._mark.width() + 6) if self._mark.isVisible() else 0
        self._title.setFixedWidth(max(1, text_w - lead))
        blurb_h = 0
        if has_blurb:
            self._blurb.setFixedWidth(text_w)
            blurb_h = self._blurb.fontMetrics().boundingRect(
                QRect(0, 0, text_w, 400),
                int(Qt.TextFlag.TextWordWrap),
                blurb,
            ).height()
        title_h = self._title.fontMetrics().height()
        if self._mark.isVisible():
            title_h = max(title_h, self._mark.height())
        margins = self.layout().contentsMargins()
        blurb_block = (self.layout().spacing() + blurb_h) if blurb_h else 0
        self.setFixedSize(
            margins.left() + margins.right() + text_w,
            margins.top()
            + margins.bottom()
            + title_h
            + blurb_block
            + self.layout().spacing()
            + self._diagram.height(),
        )

    def _place(self, combo: QComboBox) -> None:
        """Sits just to the right of the open list, or to the left if it would not fit."""
        view = combo.view()
        container = view.parentWidget() if view is not None else None
        if container is None:
            return
        origin = container.mapToGlobal(QPoint(0, 0))
        gap = 8
        x = origin.x() + container.width() + gap
        y = origin.y()
        screen = QGuiApplication.screenAt(origin) or self.screen()
        area = screen.availableGeometry() if screen is not None else QRect()
        if area.isValid() and x + self.width() > area.right() - 4:
            x = origin.x() - self.width() - gap
        if area.isValid():
            x = max(area.left() + 4, min(x, area.right() - self.width() - 4))
            y = max(area.top() + 4, min(y, area.bottom() - self.height() - 4))
        self.move(x, y)

    def _apply_font(self) -> None:
        """Same faces as the ? card. A stylesheet font would measure wrong."""
        bg, border, _, fg = ut.timeline_hover_preview_colors()
        self._bg = bg
        self._border = border
        from steempeg.ui.icon_assets import tinted_pixmap

        title_font = QFont(tok.FONT_FAMILIES[0])
        title_font.setPixelSize(13)
        title_font.setWeight(QFont.Weight.Bold)
        self._title.setFont(title_font)
        # success.png is the Healthy plaque check. Tint it white for this panel.
        self._mark.setPixmap(tinted_pixmap("success.png", "#ffffff", 16))
        blurb_font = QFont(tok.FONT_FAMILIES[0])
        blurb_font.setPixelSize(11)
        blurb_font.setWeight(QFont.Weight.Normal)
        self._blurb.setFont(blurb_font)
        self._title.setStyleSheet(f"background: transparent; color: {fg};")
        self._blurb.setStyleSheet("background: transparent; color: #a8a8a8;")

    def _shape(self) -> QPainterPath:
        path = QPainterPath()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path.addRoundedRect(rect, self._RADIUS, self._RADIUS)
        return path

    def _apply_mask(self) -> None:
        poly = self._shape().toFillPolygon().toPolygon()
        if poly.isEmpty():
            self.clearMask()
        else:
            self.setMask(QRegion(poly))
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            if not hwnd:
                return
            pref = ctypes.c_int(1)  # DWMWCP_DONOTROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref)
            )
        except Exception:
            return

    def _show_passive(self) -> None:
        """Shows the panel without taking focus, so the list stays open."""
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if sys.platform == "win32":
            try:
                import ctypes

                self.createWinId()
                hwnd = int(self.winId())
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 4)
                    if not self.isVisible():
                        self.setVisible(True)
                    return
            except Exception:
                pass
        self.show()

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = self._shape()
        painter.fillPath(path, QColor(self._bg))
        painter.setPen(QPen(QColor(self._border), 1.0))
        painter.drawPath(path)

    def showEvent(self, event) -> None:  # noqa: N802 — Qt override
        self._apply_mask()
        super().showEvent(event)


class ClipCardStyleCombo(QComboBox):
    """ClipCard style list with a preview panel beside the open popup."""

    def __init__(self, parent: QWidget | None = None, *, diagram_factory=None, copy_of=None):
        super().__init__(parent)
        self._diagram_factory = diagram_factory or ClipCardStyleDiagram
        self._copy_of = copy_of or clip_card_style_copy
        self._guide: _ClipCardStylePopupGuide | None = None
        self._watched_popup: list[QWidget] = []
        self.highlighted.connect(self._on_highlighted)

    def _ensure_guide(self) -> _ClipCardStylePopupGuide:
        """Creates the panel on the settings window the first time the list opens."""
        if self._guide is None:
            self._guide = _ClipCardStylePopupGuide(
                self.window(),
                self._diagram_factory(),
                self._copy_of,
            )
        return self._guide

    def showPopup(self) -> None:  # noqa: N802 — Qt override
        super().showPopup()
        self._watch_popup()
        self._show_under_cursor()

    def hidePopup(self) -> None:  # noqa: N802 — Qt override
        if self._guide is not None:
            self._guide.hide()
        super().hidePopup()

    def _watch_popup(self) -> None:
        """The list paints a hover without telling us. Watch the pointer instead."""
        view = self.view()
        if view is None:
            return
        targets: list[QWidget] = [view]
        view.setMouseTracking(True)
        viewport = view.viewport()
        if viewport is not None:
            viewport.setMouseTracking(True)
            targets.append(viewport)
        container = view.parentWidget()
        if isinstance(container, QWidget) and container is not view:
            container.setMouseTracking(True)
            targets.append(container)
        if targets == self._watched_popup:
            return
        for widget in self._watched_popup:
            widget.removeEventFilter(self)
        for widget in targets:
            widget.installEventFilter(self)
        self._watched_popup = targets

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt override
        """A row under the pointer shows that mode. Leaving the list shows the chosen one."""
        if obj in self._watched_popup:
            kind = event.type()
            if kind in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
                self._show_under_cursor()
            elif kind == QEvent.Type.Leave and self._cursor_left_popup():
                self._show_chosen()
        return False

    def _cursor_left_popup(self) -> bool:
        """True when the pointer is no longer inside the open list window."""
        view = self.view()
        container = view.parentWidget() if view is not None else None
        if container is None:
            return True
        return not container.rect().contains(container.mapFromGlobal(QCursor.pos()))

    def _popup_is_open(self) -> bool:
        """The list window can be up while the inner view still says it is hidden."""
        view = self.view()
        if view is None:
            return False
        if view.isVisible():
            return True
        container = view.parentWidget()
        return container is not None and container.isVisible()

    def _show_chosen(self) -> None:
        """The pointer left the list. Keep the panel on the style that is chosen."""
        if not self._popup_is_open():
            return
        self._ensure_guide().show_style(self._guide_style(str(self.currentData() or "")), self)

    def _show_under_cursor(self) -> None:
        """Shows the row under the pointer, or the chosen style when it is not on a row."""
        view = self.view()
        if view is None or not self._popup_is_open():
            return
        chosen = str(self.currentData() or "")
        style = chosen
        viewport = view.viewport()
        if viewport is not None:
            pos = viewport.mapFromGlobal(QCursor.pos())
            if viewport.rect().contains(pos):
                index = view.indexAt(pos)
                if index.isValid():
                    style = str(self.itemData(index.row()) or chosen)
        self._ensure_guide().show_style(self._guide_style(style), self)

    def _guide_style(self, raw: str) -> str:
        """The list value the panel should draw. Subclasses may add context."""
        return raw

    def _on_highlighted(self, index: int) -> None:
        """Keyboard movement through the list. The pointer path is separate."""
        if not self._popup_is_open() or index < 0:
            return
        self._ensure_guide().show_style(
            self._guide_style(str(self.itemData(index) or "")),
            self,
        )
