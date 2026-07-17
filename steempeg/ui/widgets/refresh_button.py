"""Refresh clips library: main rescan + dropdown for heavier maintenance actions."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from steempeg.ui.icon_assets import arrow_icon
from steempeg.ui.ui_density import COMFORT, UiDensity


def _refresh_style(dense: UiDensity) -> str:
    r = dense.footer_radius
    menu_w = 24 if dense.compact else 28
    menu_max = 28 if dense.compact else 32
    return f"""
    QPushButton#RefreshMain {{
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: {dense.footer_font}px;
        font-weight: bold;
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-right: none;
        border-top-left-radius: {r}px;
        border-bottom-left-radius: {r}px;
        border-top-right-radius: 0px;
        border-bottom-right-radius: 0px;
        padding: {dense.footer_pad};
        min-height: {dense.footer_min_h}px;
    }}
    QPushButton#RefreshMain:hover {{
        background-color: #404040;
        border: 2px solid #6b5a8e;
        border-right: none;
    }}
    QPushButton#RefreshMain:pressed {{
        background-color: #3a324a;
        border: 2px solid #b29ae7;
        border-right: none;
    }}
    QPushButton#RefreshMenu {{
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-left: 1px solid #555555;
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        border-top-right-radius: {r}px;
        border-bottom-right-radius: {r}px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 12px;
        font-weight: bold;
        min-width: {menu_w}px;
        max-width: {menu_max}px;
        padding: 2px 0;
        min-height: {dense.footer_min_h}px;
    }}
    QPushButton#RefreshMenu:hover {{
        background-color: #404040;
        color: #d4c4ff;
        border: 2px solid #6b5a8e;
        border-left: 1px solid #6b5a8e;
    }}
    QPushButton#RefreshMenu:pressed {{
        background-color: #3a324a;
        border: 2px solid #b29ae7;
        border-left: 1px solid #b29ae7;
    }}
"""


class RefreshButton(QWidget):
    """Rescan library (left) with a menu trigger (right) for Steam icons, health, etc."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

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

        self.menu_btn = QPushButton()
        self.menu_btn.setObjectName("RefreshMenu")
        self.menu_btn.setIcon(arrow_icon(10, direction="down"))
        self.menu_btn.setIconSize(QSize(10, 10))
        self.menu_btn.setToolTip("More refresh options")
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout.addWidget(self.main_btn, 1)
        layout.addWidget(self.menu_btn)
        self.apply_density(COMFORT)

    def apply_density(self, dense: UiDensity) -> None:
        self.setStyleSheet(_refresh_style(dense))
