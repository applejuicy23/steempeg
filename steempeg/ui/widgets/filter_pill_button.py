"""A small square icon button that opens the filter panel."""
from PySide6.QtCore import Qt, QSize
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
        # Match the sort combo's rendered height (min-height 24 + padding 8 + border 4
        # = 36) so the two controls line up; a slightly smaller icon leaves more of the
        # light #383838 face showing, so the button no longer reads as darker.
        self.setFixedSize(36, 36)
        self.setIconSize(QSize(16, 16))

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
