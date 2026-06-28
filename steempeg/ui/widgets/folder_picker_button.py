"""Composite Choose Folder button with an inline + for extra library roots."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget


_FOLDER_PICKER_STYLE = """
    QPushButton#FolderPickerMain {
        font-family: 'Segoe UI';
        font-size: 12px;
        font-weight: bold;
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-top-left-radius: 8px;
        border-bottom-left-radius: 8px;
        border-top-right-radius: 0px;
        border-bottom-right-radius: 0px;
        border-right: 1px solid #555555;
        padding: 6px 10px;
    }
    QPushButton#FolderPickerMain:hover {
        background-color: #404040;
        border: 2px solid #6b5a8e;
        border-right: 1px solid #6b5a8e;
    }
    QPushButton#FolderPickerMain:pressed {
        background-color: #3a324a;
    }
    QPushButton#FolderPickerAdd {
        font-family: 'Segoe UI';
        font-size: 14px;
        font-weight: bold;
        background-color: #383838;
        color: #b29ae7;
        border: 2px solid #444444;
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        border-top-right-radius: 8px;
        border-bottom-right-radius: 8px;
        border-left: none;
        padding: 6px 0px;
        min-width: 30px;
        max-width: 34px;
    }
    QPushButton#FolderPickerAdd:hover {
        background-color: #3a324a;
        border: 2px solid #6b5a8e;
        border-left: none;
        color: #d4c4ff;
    }
    QPushButton#FolderPickerAdd:pressed {
        background-color: #2d2640;
    }
"""


class FolderPickerButton(QWidget):
    """Choose Folder… with a + slot to add more scan roots."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(_FOLDER_PICKER_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_btn = QPushButton("Choose Folder…")
        self.main_btn.setObjectName("FolderPickerMain")
        self.main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("FolderPickerAdd")
        self.add_btn.setToolTip("Add another clips folder")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.main_btn, 1)
        layout.addWidget(self.add_btn)

    def set_folder_label(self, text, tooltip=""):
        self.main_btn.setText(text)
        tip = tooltip or text
        self.main_btn.setToolTip(tip)
        self.setToolTip(tip)
