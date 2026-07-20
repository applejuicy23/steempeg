"""A small square icon button that opens the filter panel."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton

from steempeg.infra.paths import get_resource_path
from steempeg.ui.ui_density import COMFORT, UiDensity


class FilterPillButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterPill")
        self.setText("")
        self.setToolTip("Filters")
        self.setIcon(QIcon(get_resource_path("filter.png")))
        self.setCursor(Qt.PointingHandCursor)
        self.apply_density(COMFORT)

    def apply_density(self, dense: UiDensity) -> None:
        sz = dense.filter_size
        # Keep the glyph inside the circle — comfort ~16px icon on 36px, compact ~11 on 22.
        icon = max(10, sz // 2 - (1 if dense.compact else 2))
        radius = sz // 2
        border = 1 if dense.compact else 2
        pad = 1 if dense.compact else 2
        self.setFixedSize(sz, sz)
        self.setIconSize(QSize(icon, icon))
        self.setStyleSheet(f"""
        QPushButton#FilterPill {{
            background-color: #383838;
            border: {border}px solid #444444;
            border-radius: {radius}px;
            padding: {pad}px;
        }}
        QPushButton#FilterPill:hover {{
            background-color: #404040;
            border: {border}px solid #6b5a8e;
        }}
        QPushButton#FilterPill:pressed {{
            background-color: #3a324a;
            border: {border}px solid #b29ae7;
        }}
    """)
