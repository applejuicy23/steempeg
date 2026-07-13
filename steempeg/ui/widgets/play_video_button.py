"""Split Play video button — main play action + arrow menu (like Refresh ▾)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from steempeg.ui.icon_assets import arrow_icon, load_icon

_PLAY_SPLIT_STYLE = """
    QPushButton#PlayMain {
        background-color: #4a3d66; color: #f0ecff; border: 2px solid #6b5a8e;
        border-right: none; border-top-left-radius: 8px; border-bottom-left-radius: 8px;
        border-top-right-radius: 0px; border-bottom-right-radius: 0px;
        padding: 8px 14px 8px 12px; min-height: 28px;
        font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
    QPushButton#PlayMain:hover { background-color: #5a4d76; border: 2px solid #b29ae7; border-right: none; }
    QPushButton#PlayMain:pressed { background-color: #3a324a; border: 2px solid #6b5a8e; border-right: none; }
    QPushButton#PlayMenu {
        background-color: #4a3d66; color: #f0ecff; border: 2px solid #6b5a8e;
        border-left: 1px solid #6b5a8e;
        border-top-left-radius: 0px; border-bottom-left-radius: 0px;
        border-top-right-radius: 8px; border-bottom-right-radius: 8px;
        min-width: 26px; max-width: 30px; padding: 0; min-height: 28px;
    }
    QPushButton#PlayMenu:hover {
        background-color: #5a4d76; border: 2px solid #b29ae7; border-left: 1px solid #b29ae7;
    }
    QPushButton#PlayMenu:pressed {
        background-color: #3a324a; border: 2px solid #6b5a8e; border-left: 1px solid #6b5a8e;
    }
    QPushButton#PlayMenu:disabled {
        background-color: #3a324a; color: #888888; border: 2px solid #4a4a4a;
        border-left: 1px solid #4a4a4a;
    }
"""


class PlayVideoSplitButton(QWidget):
    """Play video (left) with a ▾ menu trigger (right)."""

    play_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setStyleSheet(_PLAY_SPLIT_STYLE)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_btn = QPushButton("Play video")
        self.main_btn.setObjectName("PlayMain")
        self.main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_btn.setIcon(load_icon("playmini.png", 10))
        self.main_btn.setIconSize(QSize(12, 12))
        self.main_btn.clicked.connect(self.play_clicked.emit)

        self.menu_btn = QPushButton()
        self.menu_btn.setObjectName("PlayMenu")
        self.menu_btn.setIcon(arrow_icon(10, direction="down"))
        self.menu_btn.setIconSize(QSize(10, 10))
        self.menu_btn.setToolTip("More play options")
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout.addWidget(self.main_btn)
        layout.addWidget(self.menu_btn)

    def set_menu_enabled(self, enabled: bool) -> None:
        self.menu_btn.setEnabled(enabled)
