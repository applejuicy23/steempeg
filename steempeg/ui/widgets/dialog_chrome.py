"""Shared frameless dialog chrome — a custom title bar (logo + title + close dot)
that matches the main window's SteempegTitleBar, plus a draggable rounded card.

Dialogs subclass ``SteempegDialog`` and add their widgets to ``self.content_layout``
instead of building their own outer layout, so every window shares one top bar.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok
from steempeg.ui.window_chrome import _TrafficLight


class _DialogTitleBar(QWidget):
    """Logo + title on the left, a single red close dot on the right. Draggable."""

    close_requested = Signal()

    def __init__(self, dialog: QDialog, *, title: str, bar_color: str, parent=None):
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

        self.btn_close = _TrafficLight(tok.TRAFFIC_CLOSE, tok.TRAFFIC_CLOSE_HOVER, "\u2715")
        self.btn_close.clicked.connect(self.close_requested.emit)
        root.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignVCenter)

        self.setStyleSheet(
            f"""
            QWidget#SteempegDialogBar {{
                background-color: {bar_color};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
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
    ):
        super().__init__(parent)
        theme = tok.chrome_theme_colors(tok.DEFAULT_CHROME_THEME)
        bar_color = bar_color or theme["title_bar"]
        bg_color = bg_color or theme["app_bg"]

        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._card = QWidget(self)
        self._card.setObjectName("SteempegDialogCard")
        outer.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        self._title_bar = _DialogTitleBar(self, title=title, bar_color=bar_color)
        self._title_bar.close_requested.connect(self.reject)
        card_layout.addWidget(self._title_bar)

        content = QWidget(self._card)
        content.setObjectName("SteempegDialogContent")
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(*content_margins)
        self.content_layout.setSpacing(12)
        card_layout.addWidget(content, 1)

        self.setStyleSheet(
            f"""
            QWidget#SteempegDialogCard {{
                background-color: {bg_color};
                border: 1px solid {tok.BORDER_DEFAULT};
                border-radius: 10px;
            }}
            QWidget#SteempegDialogContent {{ background-color: {bg_color}; }}
            """
        )
