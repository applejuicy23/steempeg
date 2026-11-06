"""A ? circle beside a setting, and the short splash it opens.

The long helper line used to sit under the control. The circle keeps that
text off the card until the pointer hovers it or the circle is pressed.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
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

_CIRCLE = 16
_SPLASH_TEXT_W = 260
_HIDE_MS = 220

_open_help: "SettingHelpButton | None" = None


class _SettingHelpSplash(QWidget):
    """Short explanation card. It does not take focus from Settings."""

    def __init__(self, button: "SettingHelpButton", host: QWidget):
        super().__init__(
            host,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self._button = button
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._panel = QFrame(self)
        self._panel.setObjectName("settingHelpSplash")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._panel)
        inner = QVBoxLayout(self._panel)
        inner.setContentsMargins(10, 8, 10, 8)
        self._label = QLabel(self._panel)
        self._label.setWordWrap(True)
        self._label.setFixedWidth(_SPLASH_TEXT_W)
        self._label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        inner.addWidget(self._label)
        self._apply_chrome()

    def set_text(self, text: str) -> None:
        """Replaces the explanation and resizes the card around it."""
        self._label.setText(text)
        self._apply_chrome()
        self.adjustSize()

    def place_at_cursor(self) -> None:
        """Puts the card just off the pointer and keeps it on the same screen.

        The card is a real window, so ``move`` takes screen coordinates.
        """
        from PySide6.QtGui import QCursor

        self.adjustSize()
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

    def _apply_chrome(self) -> None:
        """Paints the card in the active theme."""
        palette = ut.active_palette()
        self._panel.setStyleSheet(
            f"QFrame#settingHelpSplash {{ background-color: {palette.tooltip_bg}; "
            f"border: 1px solid {palette.tooltip_border}; border-radius: 8px; }}"
        )
        self._label.setStyleSheet(
            f"color: {palette.tooltip_fg}; background: transparent; border: none; "
            f"font-size: 12px; font-family: {tok.FONT_APP};"
        )

    def showEvent(self, event) -> None:  # noqa: N802 — Qt override
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

    def set_help_text(self, text: str) -> None:
        """Replaces the explanation this circle opens."""
        self._text = text
        if self._splash is not None:
            self._splash.set_text(text)

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
        if not self._text or not self.isVisible():
            return
        if _open_help is not None and _open_help is not self:
            _open_help.dismiss()
        _open_help = self
        splash = self._ensure_splash()
        splash.set_text(self._text)
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
        target.insertWidget(1, button, 0, Qt.AlignmentFlag.AlignVCenter)
        button.setProperty("help_placed", True)
        return True
    checkbox = previous.widget()
    if isinstance(checkbox, QCheckBox):
        _wrap_checkbox(layout, index - 1, checkbox, button)
        return True
    return False


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
    layout.insertWidget(1, button, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addStretch(1)
    button.setProperty("help_placed", True)
    return True
