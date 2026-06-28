"""Composite Choose Folder button with a combobox-style side that opens a panel."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget


_FOLDER_PICKER_STYLE = """
    QPushButton#FolderPickerMain {
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
    QPushButton#FolderPickerMain:hover {
        background-color: #404040;
        border: 2px solid #6b5a8e;
        border-right: none;
    }
    QPushButton#FolderPickerMain:pressed {
        background-color: #3a324a;
        border: 2px solid #b29ae7;
        border-right: none;
    }
    QPushButton#FolderPickerAdd {
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-left: 1px solid #555555;
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        border-top-right-radius: 14px;
        border-bottom-right-radius: 14px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 17px;
        font-weight: bold;
        min-width: 40px;
        max-width: 44px;
        padding: 4px 0;
        min-height: 24px;
    }
    QPushButton#FolderPickerAdd:hover {
        background-color: #404040;
        color: #d4c4ff;
        border: 2px solid #6b5a8e;
        border-left: 1px solid #6b5a8e;
    }
    QPushButton#FolderPickerAdd:pressed {
        background-color: #3a324a;
        border: 2px solid #b29ae7;
        border-left: 1px solid #b29ae7;
    }
"""


class FolderPickerButton(QWidget):
    """Choose Folder… with a combobox-style + cell that opens the folders panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(_FOLDER_PICKER_STYLE)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_btn = QPushButton("Choose Folder…")
        self.main_btn.setObjectName("FolderPickerMain")
        self.main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("FolderPickerAdd")
        self.add_btn.setToolTip("Manage clips folders")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout.addWidget(self.main_btn, 1)
        layout.addWidget(self.add_btn)

        self._add_visible = True
        self._update_main_radius()

    def _update_main_radius(self):
        """When the + is hidden, the main button should be fully rounded on both sides.

        Tracks an explicit flag instead of QWidget.isVisible(): during construction (and
        before the window is shown) isVisible() is always False, which previously made the
        main button render with the "no +" rounding even though the + was about to show.
        """
        if self._add_visible:
            self.main_btn.setStyleSheet("")  # inherit composite stylesheet
        else:
            self.main_btn.setStyleSheet(
                "QPushButton#FolderPickerMain {"
                " border: 2px solid #444444;"
                " border-top-right-radius: 14px;"
                " border-bottom-right-radius: 14px; }"
                "QPushButton#FolderPickerMain:hover { border: 2px solid #6b5a8e; }"
                "QPushButton#FolderPickerMain:pressed { border: 2px solid #b29ae7; }"
            )

    def set_add_visible(self, visible):
        self._add_visible = bool(visible)
        self.add_btn.setVisible(self._add_visible)
        self._update_main_radius()

    def set_folder_label(self, text, tooltip=""):
        self.main_btn.setText(text)
        tip = tooltip or text
        self.main_btn.setToolTip(tip)
        self.setToolTip(tip)
