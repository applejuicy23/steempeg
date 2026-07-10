"""Refresh clips library: main rescan + dropdown for heavier maintenance actions."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget


_REFRESH_BUTTON_STYLE = """
    QPushButton#RefreshMain {
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 13px;
        font-weight: bold;
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-right: none;
        border-top-left-radius: 14px;
        border-bottom-left-radius: 14px;
        border-top-right-radius: 0px;
        border-bottom-right-radius: 0px;
        padding: 4px 12px;
        min-height: 24px;
    }
    QPushButton#RefreshMain:hover {
        background-color: #404040;
        border: 2px solid #6b5a8e;
        border-right: none;
    }
    QPushButton#RefreshMain:pressed {
        background-color: #3a324a;
        border: 2px solid #b29ae7;
        border-right: none;
    }
    QPushButton#RefreshMenu {
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-left: 1px solid #555555;
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        border-top-right-radius: 14px;
        border-bottom-right-radius: 14px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 12px;
        font-weight: bold;
        min-width: 28px;
        max-width: 32px;
        padding: 4px 0;
        min-height: 24px;
    }
    QPushButton#RefreshMenu:hover {
        background-color: #404040;
        color: #d4c4ff;
        border: 2px solid #6b5a8e;
        border-left: 1px solid #6b5a8e;
    }
    QPushButton#RefreshMenu:pressed {
        background-color: #3a324a;
        border: 2px solid #b29ae7;
        border-left: 1px solid #b29ae7;
    }
"""


class RefreshButton(QWidget):
    """Rescan library (left) with a menu trigger (right) for Steam icons, health, etc."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(_REFRESH_BUTTON_STYLE)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_btn = QPushButton("🔄 Refresh")
        self.main_btn.setObjectName("RefreshMain")
        self.main_btn.setToolTip(
            "Rescan clip folders and rebuild the list (cached icons and health only)"
        )
        self.main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.menu_btn = QPushButton("▾")
        self.menu_btn.setObjectName("RefreshMenu")
        self.menu_btn.setToolTip("More refresh options")
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout.addWidget(self.main_btn, 1)
        layout.addWidget(self.menu_btn)
