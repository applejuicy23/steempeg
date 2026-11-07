"""A ? circle beside a setting, and the short splash it opens.

The long helper line used to sit under the control. The circle keeps that
text off the card until the pointer hovers it or the circle is pressed.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui.widgets.clip_card_style_guide import (
    ClipCardStyleDiagram as _ClipCardStyleDiagram,
    clip_card_style_copy,
)
from steempeg.ui.widgets.header_layout_guide import (
    HeaderLayoutDiagram as _HeaderLayoutDiagram,
    header_layout_copy,
    header_size_copy,
)
from steempeg.ui.widgets.player_layout_guide import (
    PlayerStackDiagram as _PlayerStackDiagram,
    player_layout_copy,
    player_outline_copy,
)
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

_CIRCLE = 16
_HIDE_MS = 220

_open_help: "SettingHelpButton | None" = None


class _SettingHelpSplash(QWidget):
    """Marker-style card: a ? disc, the setting name, then the explanation.

    A stylesheet radius on this Tool window stays square, the same way the
    marker tip's did. The card is painted and masked instead. No caret.
    """

    _RADIUS = 10.0
    _DISC = 28
    _TEXT_MAX_W = 280

    def __init__(self, button: "SettingHelpButton", host: QWidget):
        super().__init__(
            host,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self._button = button
        self._bg = "#1a1a1a"
        self._border = "#333333"
        self._show_diagram = False
        self._show_header = False
        self._show_player = False
        self._show_chosen = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 14, 8)
        row.setSpacing(10)
        self._mark = QLabel("?", self)
        self._mark.setFixedSize(self._DISC, self._DISC)
        self._mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mark.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._mark.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self._title = QLabel(self)
        self._title.setWordWrap(True)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chosen_row = QWidget(self)
        self._chosen_row.setStyleSheet("background: transparent;")
        chosen_lay = QHBoxLayout(self._chosen_row)
        chosen_lay.setContentsMargins(0, 4, 0, 2)
        chosen_lay.setSpacing(6)
        self._chosen_mark = QLabel(self._chosen_row)
        self._chosen_mark.setFixedSize(16, 16)
        self._chosen_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chosen_mark.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chosen = QLabel(self._chosen_row)
        self._chosen.setTextFormat(Qt.TextFormat.PlainText)
        self._chosen.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        chosen_lay.addWidget(self._chosen_mark, 0, Qt.AlignmentFlag.AlignVCenter)
        chosen_lay.addWidget(self._chosen, 1, Qt.AlignmentFlag.AlignVCenter)
        self._chosen_row.hide()
        self._desc = QLabel(self)
        self._desc.setWordWrap(True)
        self._desc.setTextFormat(Qt.TextFormat.PlainText)
        self._desc.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        text_col.addWidget(self._title)
        text_col.addWidget(self._chosen_row)
        text_col.addWidget(self._desc)
        self._header_gap = QWidget(self)
        self._header_gap.setFixedHeight(14)
        self._header_gap.hide()
        text_col.addWidget(self._header_gap)
        self._header = _HeaderLayoutDiagram(self)
        self._header.hide()
        self._player = _PlayerStackDiagram(self)
        self._player.hide()
        text_col.addWidget(self._header)
        text_col.addWidget(self._player)
        self._diagram = _ClipCardStyleDiagram(self)
        self._diagram.hide()
        row.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addLayout(text_col)
        row.addWidget(self._diagram, 0, Qt.AlignmentFlag.AlignVCenter)
        self._apply_font()

    def set_content(self, title: str, text: str) -> None:
        """Puts the setting name on the bold line and the explanation under it."""
        self._apply_font()
        self._sync_diagram()
        self._fit(title, text)
        self._apply_mask()

    def _sync_diagram(self) -> None:
        """Shows the ClipCard picture only for the setting that asked for one."""
        kind = getattr(self._button, "_diagram_kind", "")
        style_of = getattr(self._button, "_diagram_style", None)
        card = kind == "clip_card_style" and callable(style_of)
        header = kind in ("header_layout", "header_size") and callable(style_of)
        player = kind in ("player_layout", "player_outline") and callable(style_of)
        # isVisible() is false until the card itself is on screen, so the
        # width has to follow these flags, not the widget's visible bit.
        self._show_diagram = card
        self._show_header = header
        self._show_player = player
        self._diagram.setVisible(card)
        self._header.setVisible(header)
        self._player.setVisible(player)
        self._header_gap.setVisible(header or player)
        self._show_chosen = card or header or player
        if card or header or player:
            style = str(style_of() or "")
            if card:
                self._diagram.set_style(style)
                name = clip_card_style_copy(style)[0]
            elif header:
                self._header.set_style(style)
                if kind == "header_size":
                    name = header_size_copy(style)[0]
                else:
                    name = header_layout_copy(style)[0]
            else:
                self._player.set_style(style)
                if kind == "player_outline":
                    name = player_outline_copy(style)[0]
                else:
                    name = player_layout_copy(style)[0]
            self._chosen.setText(name)
            self._chosen_row.setVisible(True)
        else:
            self._chosen.clear()
            self._chosen_row.setVisible(False)

    def place_at_cursor(self) -> None:
        """Puts the card just off the pointer and keeps it on the same screen.

        The card is a real window, so ``move`` takes screen coordinates.
        """
        from PySide6.QtGui import QCursor

        cursor = QCursor.pos()
        gap_x, gap_y = 14, 18
        x = cursor.x() + gap_x
        y = cursor.y() + gap_y
        screen = QGuiApplication.screenAt(cursor) or self.screen()
        area = screen.availableGeometry() if screen is not None else QRect()
        if area.isValid():
            if x + self.width() > area.right() - 4:
                x = cursor.x() - self.width() - gap_x
            if y + self.height() > area.bottom() - 4:
                y = cursor.y() - self.height() - gap_y
            x = max(area.left() + 4, min(x, area.right() - self.width() - 4))
            y = max(area.top() + 4, min(y, area.bottom() - self.height() - 4))
        self.move(x, y)

    def _apply_font(self) -> None:
        """Marker tip faces. A stylesheet font would measure as a different width."""
        bg, border, _, fg = ut.timeline_hover_preview_colors()
        self._bg = bg
        self._border = border
        self._mark.setStyleSheet(
            "background-color: rgba(255, 255, 255, 22); color: "
            f"{fg}; border-radius: {self._DISC // 2}px;"
        )
        mark_font = QFont(tok.FONT_FAMILIES[0])
        mark_font.setPixelSize(14)
        mark_font.setWeight(QFont.Weight.Bold)
        self._mark.setFont(mark_font)
        title_font = QFont(tok.FONT_FAMILIES[0])
        title_font.setPixelSize(13)
        title_font.setWeight(QFont.Weight.Bold)
        self._title.setFont(title_font)
        # The closed list draws its value at 12px bold. Same face here, so the
        # rules underneath are clearly about that mode.
        chosen_font = QFont(tok.FONT_FAMILIES[0])
        chosen_font.setPixelSize(12)
        chosen_font.setWeight(QFont.Weight.Bold)
        self._chosen.setFont(chosen_font)
        from steempeg.ui.icon_assets import tinted_pixmap

        # success.png is the Healthy plaque check, tinted white.
        self._chosen_mark.setPixmap(tinted_pixmap("success.png", "#ffffff", 16))
        desc_font = QFont(tok.FONT_FAMILIES[0])
        desc_font.setPixelSize(11)
        desc_font.setWeight(QFont.Weight.Normal)
        self._desc.setFont(desc_font)
        self._title.setStyleSheet(f"background: transparent; color: {fg};")
        self._chosen.setStyleSheet("background: transparent; color: #ffffff;")
        self._desc.setStyleSheet("background: transparent; color: #a8a8a8;")

    def _fit(self, title: str, text: str) -> None:
        """Sizes the card to this name and explanation, not the previous one."""
        title = title.strip()
        text = text.strip()
        self._title.setText(title)
        self._desc.setText(text)
        self._title.setVisible(bool(title))
        self._desc.setVisible(bool(text))
        for label in (self._title, self._desc):
            label.setMinimumWidth(0)
            label.setMaximumWidth(16777215)
        title_w = 0
        if title:
            title_w = min(
                self._title.fontMetrics().horizontalAdvance(title) + 8,
                self._TEXT_MAX_W,
            )
        desc_w = 0
        if text:
            desc_w = min(
                self._desc.fontMetrics().horizontalAdvance(text) + 8,
                self._TEXT_MAX_W,
            )
        chosen = self._chosen.text().strip() if self._show_chosen else ""
        chosen_w = 0
        if chosen:
            chosen_w = min(
                self._chosen.fontMetrics().horizontalAdvance(chosen)
                + self._chosen_mark.width()
                + 6
                + 8,
                self._TEXT_MAX_W,
            )
        if self._show_header:
            text_w_floor = self._header.width()
        elif self._show_player:
            text_w_floor = self._player.width()
        else:
            text_w_floor = 0
        text_w = max(title_w, chosen_w, desc_w, text_w_floor, 1)
        text_h = 0
        if title:
            self._title.setFixedWidth(text_w)
            text_h += self._title.fontMetrics().boundingRect(
                QRect(0, 0, text_w, 1000),
                int(Qt.TextFlag.TextWordWrap),
                title,
            ).height()
        if chosen:
            lead = self._chosen_mark.width() + 6
            self._chosen.setFixedWidth(max(1, text_w - lead))
            if text_h:
                text_h += 1
            pad = self._chosen_row.layout().contentsMargins()
            text_h += pad.top() + pad.bottom()
            text_h += max(
                self._chosen_mark.height(),
                self._chosen.fontMetrics().boundingRect(
                    QRect(0, 0, max(1, text_w - lead), 1000),
                    int(Qt.TextFlag.TextWordWrap),
                    chosen,
                ).height(),
            )
        if text:
            self._desc.setFixedWidth(text_w)
            if text_h:
                text_h += 1
            text_h += self._desc.fontMetrics().boundingRect(
                QRect(0, 0, text_w, 1000),
                int(Qt.TextFlag.TextWordWrap),
                text,
            ).height()
        if self._show_header or self._show_player:
            text_h += self._header_gap.height()
            text_h += self._header.height() if self._show_header else self._player.height()
        margins = self.layout().contentsMargins()
        card_w = margins.left() + margins.right() + text_w + self._DISC + self.layout().spacing()
        row_h = max(text_h, self._DISC)
        if self._show_diagram:
            card_w += self.layout().spacing() + self._diagram.width()
            row_h = max(row_h, self._diagram.height())
        self.setFixedSize(card_w, margins.top() + margins.bottom() + row_h)

    def _shape(self) -> QPainterPath:
        """Rounded card. No caret: that spike belongs to the marker pin."""
        path = QPainterPath()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path.addRoundedRect(rect, self._RADIUS, self._RADIUS)
        return path

    def _apply_mask(self) -> None:
        """Clips the Tool window to the painted round rect, including on Windows."""
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
        app = QGuiApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt override
        app = QGuiApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802 — Qt override
        self._button.hold_open()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — Qt override
        self._button.schedule_hide()
        super().leaveEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 — Qt override
        """Closes a pinned card on a click elsewhere, and any card when the page scrolls."""
        del watched
        kind = event.type()
        if kind == QEvent.Type.Wheel:
            self._button.dismiss()
            return False
        if kind != QEvent.Type.MouseButtonPress or not self._button.is_pinned():
            return False
        pos = event.globalPosition().toPoint()
        on_card = self.frameGeometry().contains(pos)
        on_circle = self._button.rect().contains(self._button.mapFromGlobal(pos))
        if not on_card and not on_circle:
            self._button.dismiss()
        return False


class SettingHelpButton(QWidget):
    """Circle with ? that opens the setting's explanation."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        self._help_title = ""
        self._diagram_kind = ""
        self._diagram_style = None
        self._text_of = None
        self._pinned = False
        self._hot = False
        self._splash: _SettingHelpSplash | None = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_if_idle)
        self.setFixedSize(_CIRCLE, _CIRCLE)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setProperty("settings_helper", True)

    def set_help_diagram(self, kind: str, style_of, text_of=None) -> None:
        """Pins a picture to this card.

        ``style_of`` returns the mode. ``text_of`` returns the explanation for
        that mode, read again whenever the list changes.
        """
        self._diagram_kind = kind
        self._diagram_style = style_of
        self._text_of = text_of

    def refresh_diagram(self) -> None:
        """Redraws an open card from the list's current choice."""
        self._pull_live_text()
        splash = self._splash
        # isVisible() is false while a combo popup is up, even though the card
        # is still on screen. isHidden() is the flag hide() actually sets.
        if splash is not None and not splash.isHidden():
            splash.set_content(self._help_title, self._text)

    def _pull_live_text(self) -> None:
        """Reads the explanation for whatever the list shows right now."""
        if callable(self._text_of):
            self._text = str(self._text_of() or "")

    def set_help_title(self, title: str) -> None:
        """Names the setting this circle explains. The card shows it in bold."""
        self._help_title = title.strip()
        splash = self._splash
        if splash is not None and splash.isVisible():
            splash.set_content(self._help_title, self._text)

    def set_help_text(self, text: str) -> None:
        """Replaces the explanation this circle opens."""
        self._text = text
        self.refresh_diagram()

    def help_text(self) -> str:
        """Returns the explanation this circle opens."""
        return self._text

    def is_pinned(self) -> bool:
        """True after a press, until another click or another circle opens."""
        return self._pinned

    def hold_open(self) -> None:
        """Keeps the card up while the pointer is on it."""
        self._hide_timer.stop()

    def schedule_hide(self) -> None:
        """Hides an unpinned card once the pointer has left the circle and the card."""
        if self._pinned:
            return
        self._hide_timer.start(_HIDE_MS)

    def dismiss(self) -> None:
        """Closes the card and clears a pin."""
        self._hide(force=True)

    def enterEvent(self, event) -> None:  # noqa: N802 — Qt override
        self._hot = True
        self.update()
        self.hold_open()
        self._show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 — Qt override
        self._hot = False
        self.update()
        self.schedule_hide()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Keeps the card on the pointer while it stays inside the circle."""
        splash = self._splash
        if splash is not None and splash.isVisible():
            splash.place_at_cursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            if self._pinned:
                self.dismiss()
            else:
                self._pinned = True
                self.update()
                self._show()
            event.accept()
            return
        super().mousePressEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt override
        global _open_help
        self._pinned = False
        self._hide_timer.stop()
        if self._splash is not None and self._splash.isVisible():
            self._splash.hide()
        if _open_help is self:
            _open_help = None
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt override
        del event
        hot = self._hot or self._pinned
        color = QColor(tok.ACCENT_PRIMARY if hot else tok.TEXT_MUTED)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color)
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(1.0, 1.0, _CIRCLE - 2.0, _CIRCLE - 2.0)
        painter.drawEllipse(rect)
        font = QFont(tok.FONT_APP)
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "?")
        painter.end()

    def _show(self) -> None:
        """Opens this circle's card and closes any other one."""
        global _open_help
        if not self.isVisible():
            return
        self._pull_live_text()
        if not self._text and not self._diagram_kind:
            return
        if _open_help is not None and _open_help is not self:
            _open_help.dismiss()
        _open_help = self
        splash = self._ensure_splash()
        splash.set_content(self._help_title, self._text)
        splash.place_at_cursor()
        splash.show()
        splash.place_at_cursor()

    def _ensure_splash(self) -> _SettingHelpSplash:
        """Creates the card on the settings window the first time it opens."""
        if self._splash is None:
            host = self.window()
            if not isinstance(host, QWidget):
                host = self
            self._splash = _SettingHelpSplash(self, host)
        return self._splash

    def _hide_if_idle(self) -> None:
        """Hides the card when the pointer is on neither the circle nor the card."""
        if self._pinned or self.underMouse():
            return
        splash = self._splash
        if splash is not None and splash.isVisible() and splash.underMouse():
            return
        self._hide(force=False)

    def _hide(self, *, force: bool) -> None:
        """Hides the card. ``force`` also drops a pin."""
        global _open_help
        if force:
            self._pinned = False
            self._hot = self.underMouse()
            self.update()
        self._hide_timer.stop()
        if self._splash is not None:
            self._splash.hide()
        if _open_help is self:
            _open_help = None


def place_setting_help(layout: QLayout) -> None:
    """Moves each ? circle onto the setting row it explains."""
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is not None and item.layout() is not None:
            place_setting_help(item.layout())
    index = 0
    while index < layout.count():
        item = layout.itemAt(index)
        widget = item.widget() if item is not None else None
        if isinstance(widget, SettingHelpButton) and not widget.property("help_placed"):
            if _place_help_button(layout, index, widget):
                continue
        index += 1


def _place_help_button(layout: QLayout, index: int, button: SettingHelpButton) -> bool:
    """Sits the circle beside the previous setting, or beside a following button."""
    if index == 0:
        return _place_help_beside_button(layout, button)
    previous = layout.itemAt(index - 1)
    if previous is None:
        return False
    target = _help_target_layout(previous)
    if target is not None:
        layout.takeAt(index)
        _remember_row_title(button, target)
        target.insertWidget(1, button, 0, Qt.AlignmentFlag.AlignVCenter)
        button.setProperty("help_placed", True)
        return True
    checkbox = previous.widget()
    if isinstance(checkbox, QCheckBox):
        _wrap_checkbox(layout, index - 1, checkbox, button)
        return True
    return False


def _remember_widget_title(button: SettingHelpButton, widget: QWidget) -> None:
    """Uses a neighbour's own words as the card's bold line."""
    text = ""
    if isinstance(widget, (QLabel, QCheckBox, QPushButton)):
        text = widget.text().strip()
    if text:
        button.set_help_title(text)


def _remember_row_title(button: SettingHelpButton, row: QHBoxLayout) -> None:
    """Uses the row's label as the card's bold line."""
    for index in range(row.count()):
        item = row.itemAt(index)
        widget = item.widget() if item is not None else None
        if isinstance(widget, QLabel) and widget.text().strip():
            button.set_help_title(widget.text().strip())
            return


def _help_target_layout(item) -> QHBoxLayout | None:
    """Returns the horizontal row a circle should join, when the item is one."""
    candidate = item.layout()
    if candidate is None and item.widget() is not None:
        candidate = item.widget().layout()
    if isinstance(candidate, QHBoxLayout):
        return candidate
    return None


def _wrap_checkbox(
    layout: QLayout, checkbox_index: int, checkbox: QCheckBox, button: SettingHelpButton
) -> None:
    """Puts the circle on the checkbox's text line."""
    page = checkbox.parentWidget()
    layout.takeAt(checkbox_index + 1)
    layout.takeAt(checkbox_index)
    row = QWidget(page)
    row.setStyleSheet("background: transparent;")
    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(6)
    checkbox.setParent(row)
    button.setParent(row)
    # The style's checkbox is wider than the painted label. Pin the width to
    # the glyphs so the circle sits on the text, not in the spare strip.
    _remember_widget_title(button, checkbox)
    if isinstance(checkbox, SteempegCheckBox):
        checkbox.setFixedWidth(checkbox.content_width())
    box.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignVCenter)
    box.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
    box.addStretch(1)
    layout.insertWidget(checkbox_index, row)
    button.setProperty("help_placed", True)


def _place_help_beside_button(layout: QLayout, button: SettingHelpButton) -> bool:
    """Moves a leading circle to the right of the button it labels."""
    if layout.count() < 2:
        return False
    following = layout.itemAt(1)
    widget = following.widget() if following is not None else None
    if not isinstance(widget, QPushButton):
        return False
    layout.takeAt(0)
    _remember_widget_title(button, widget)
    layout.insertWidget(1, button, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addStretch(1)
    button.setProperty("help_placed", True)
    return True
