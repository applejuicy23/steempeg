"""Shared frameless dialog chrome — a custom title bar (logo + title + close dot)
that matches the main window's SteempegTitleBar, plus a draggable rounded card.

Dialogs subclass ``SteempegDialog`` and add their widgets to ``self.content_layout``
instead of building their own outer layout, so every window shares one top bar.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QFont, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok
from steempeg.ui.window_chrome import _TrafficLight

_SIDE_RAIL_PX = 2
_CARD_RADIUS_PX = 10


class _DialogTitleBar(QWidget):
    """Logo + title on the left, optional minimize + close dots on the right. Draggable."""

    close_requested = Signal()

    def __init__(
        self,
        dialog: QDialog,
        *,
        title: str,
        bar_color: str,
        show_minimize: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._dialog = dialog
        self._drag_offset: QPoint | None = None
        self.setObjectName("SteempegDialogBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(tok.TITLE_BAR_HEIGHT)

        bar_h = tok.TITLE_BAR_HEIGHT
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 0, 10, 0)
        root.setSpacing(0)

        icon_path = get_resource_path("logo.png")
        if os.path.isfile(icon_path):
            icon_lbl = QLabel()
            icon_lbl.setPixmap(
                QPixmap(icon_path).scaled(
                    16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
            )
            icon_lbl.setFixedSize(16, bar_h)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
            root.addWidget(icon_lbl)
            root.addSpacing(7)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("SteempegDialogTitle")
        font = QFont()
        font.setFamilies(["Cascadia UI", "Segoe UI Variable", "Segoe UI"])
        font.setPointSize(tok.FONT_TITLE_SIZE)
        font.setWeight(QFont.Weight.DemiBold)
        title_lbl.setFont(font)
        title_lbl.setFixedHeight(bar_h)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        title_lbl.setContentsMargins(0, 0, 0, 2)
        root.addWidget(title_lbl)

        root.addStretch(1)

        if show_minimize:
            self.btn_minimize = _TrafficLight(
                tok.TRAFFIC_MINIMIZE, tok.TRAFFIC_MINIMIZE_HOVER, "minimize"
            )
            self.btn_minimize.clicked.connect(dialog.showMinimized)
            root.addWidget(self.btn_minimize, 0, Qt.AlignmentFlag.AlignVCenter)
            root.addSpacing(6)
        else:
            self.btn_minimize = None

        self.btn_close = _TrafficLight(tok.TRAFFIC_CLOSE, tok.TRAFFIC_CLOSE_HOVER, "close")
        self.btn_close.clicked.connect(self.close_requested.emit)
        root.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignVCenter)

        self.setStyleSheet(
            f"""
            QWidget#SteempegDialogBar {{
                background-color: {bar_color};
                border-top-left-radius: {_CARD_RADIUS_PX}px;
                border-top-right-radius: {_CARD_RADIUS_PX}px;
                border-bottom: 1px solid {tok.BORDER_SUBTLE};
            }}
            QLabel#SteempegDialogTitle {{
                color: {tok.TEXT_TITLE};
                font-family: {tok.FONT_UI};
                background: transparent;
            }}
            """
        )

    # --- Drag the frameless dialog by its title bar -----------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Wayland/X11: compositor-owned move (manual QWidget.move is often ignored).
            handle = self._dialog.windowHandle()
            if handle is not None:
                try:
                    if handle.startSystemMove():
                        event.accept()
                        return
                except Exception:
                    pass
            self._drag_offset = (
                event.globalPosition().toPoint() - self._dialog.frameGeometry().topLeft()
            )
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._dialog.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class SteempegDialog(QDialog):
    """Frameless dialog with the shared Steempeg title bar.

    Subclasses add their content to ``self.content_layout``. Colors default to the
    active chrome theme so dialogs match the main window's title bar / background.
    """

    def __init__(
        self,
        title: str,
        parent=None,
        *,
        bar_color: str | None = None,
        bg_color: str | None = None,
        content_margins: tuple[int, int, int, int] = (16, 16, 16, 16),
        show_minimize: bool = False,
    ):
        super().__init__(parent)
        theme = tok.chrome_theme_colors(tok.DEFAULT_CHROME_THEME)
        bar_color = bar_color or theme["title_bar"]
        bg_color = bg_color or theme["app_bg"]
        self._bar_color = bar_color
        self._bg_color = bg_color

        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._card = QWidget(self)
        self._card.setObjectName("SteempegDialogCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        self._title_bar = _DialogTitleBar(
            self, title=title, bar_color=bar_color, show_minimize=show_minimize
        )
        self._title_bar.close_requested.connect(self.reject)
        card_layout.addWidget(self._title_bar)

        body_host = QWidget(self._card)
        body_host.setObjectName("SteempegDialogBodyHost")
        body_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        body_layout = QVBoxLayout(body_host)
        body_layout.setContentsMargins(_SIDE_RAIL_PX, 0, _SIDE_RAIL_PX, _SIDE_RAIL_PX)
        body_layout.setSpacing(0)

        content = QWidget(body_host)
        content.setObjectName("SteempegDialogContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(*content_margins)
        self.content_layout.setSpacing(12)
        body_layout.addWidget(content, 1)
        card_layout.addWidget(body_host, 1)

        self._apply_card_chrome(bar_color, bg_color)
        self._comfort_size: tuple[int, int] | None = None

    def set_comfort_size(self, width: int, height: int) -> None:
        """Design size at desktop density; auto-shrinks on Deck-class screens."""
        self._comfort_size = (int(width), int(height))
        self._apply_scaled_size()

    def _apply_scaled_size(self) -> None:
        if not self._comfort_size:
            return
        from steempeg.ui.ui_density import scaled_dialog_size

        w, h = scaled_dialog_size(*self._comfort_size, parent=self.parent())
        self.setFixedSize(w, h)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_scaled_size()
        self._center_on_parent()
        self._apply_round_mask()

    def _center_on_parent(self) -> None:
        """Place the dialog on the parent (or available screen) so HD/Deck windows stay in view."""
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication, QWidget

        ref: QWidget | None = None
        parent = self.parentWidget()
        if isinstance(parent, QWidget) and parent.isVisible():
            ref = parent.window() if parent.window() is not None else parent
        if ref is None:
            aw = QApplication.activeWindow()
            if isinstance(aw, QWidget):
                ref = aw

        if ref is not None and ref.isVisible():
            geo = ref.frameGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
        else:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            x = avail.x() + (avail.width() - self.width()) // 2
            y = avail.y() + (avail.height() - self.height()) // 2

        # Keep fully inside the screen that contains the reference point.
        screen = QGuiApplication.screenAt(ref.frameGeometry().center()) if ref else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = max(avail.x(), min(x, avail.x() + avail.width() - self.width()))
            y = max(avail.y(), min(y, avail.y() + avail.height() - self.height()))
        self.move(x, y)

    def _apply_round_mask(self) -> None:
        path = QPainterPath()
        path.addRoundedRect(
            0.0, 0.0, float(self.width()), float(self.height()),
            float(_CARD_RADIUS_PX), float(_CARD_RADIUS_PX),
        )
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_round_mask()

    def _apply_card_chrome(self, bar_color: str, bg_color: str) -> None:
        """Title-bar-colored side rails so the shell does not melt into the desktop."""
        inner_radius = max(_CARD_RADIUS_PX - _SIDE_RAIL_PX, 0)
        self.setStyleSheet(
            f"""
            QWidget#SteempegDialogCard {{
                background-color: {bar_color};
                border: 2px solid {bar_color};
                border-radius: {_CARD_RADIUS_PX}px;
            }}
            QWidget#SteempegDialogBodyHost {{
                background-color: transparent;
            }}
            QWidget#SteempegDialogContent {{
                background-color: {bg_color};
                border-bottom-left-radius: {inner_radius}px;
                border-bottom-right-radius: {inner_radius}px;
            }}
            """
        )
