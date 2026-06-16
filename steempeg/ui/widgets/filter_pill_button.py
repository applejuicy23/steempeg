"""A small square icon button that opens the filter panel."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton

from steempeg.infra.paths import get_resource_path


class FilterPillButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterPill")
        self.setText("")
        self.setToolTip("Filters")
        self.setIcon(QIcon(get_resource_path("filter.png")))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(34, 34)

        # Static styling that matches the sort combo box look.
        self.setStyleSheet("""
        QPushButton#FilterPill {
            background-color: #383838;
            border: 2px solid #444444;
            border-radius: 8px;
            padding: 4px;
        }
        QPushButton#FilterPill:hover {
            background-color: #404040;
            border: 2px solid #6b5a8e;
        }
        QPushButton#FilterPill:pressed {
            background-color: #3a324a;
            border: 2px solid #b29ae7;
        }
    """)
