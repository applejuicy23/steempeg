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
        background-color: #262626;
        color: #cccccc;
        border: 2px solid #444444;
        border-left: 2px solid #4a4a4a;
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        border-top-right-radius: 14px;
        border-bottom-right-radius: 14px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 16px;
        font-weight: bold;
        min-width: 30px;
        max-width: 30px;
        min-height: 24px;
    }
    QPushButton#FolderPickerAdd:hover {
        background-color: #3a324a;
        color: #d4c4ff;
        border: 2px solid #6b5a8e;
        border-left: 2px solid #6b5a8e;
    }
    QPushButton#FolderPickerAdd:pressed {
        background-color: #2d2640;
        border: 2px solid #b29ae7;
        border-left: 2px solid #b29ae7;
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
        self.main_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("FolderPickerAdd")
        self.add_btn.setToolTip("Manage clips folders")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.main_btn, 1)
        layout.addWidget(self.add_btn)

    def set_folder_label(self, text, tooltip=""):
        self.main_btn.setText(text)
        tip = tooltip or text
        self.main_btn.setToolTip(tip)
        self.setToolTip(tip)
