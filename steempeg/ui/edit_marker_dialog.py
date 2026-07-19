"""Steempeg-styled editor for custom Steam timeline markers."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout

from steempeg.ui import design_tokens as tok
from steempeg.ui.message_dialog import _BTN_PRIMARY, _BTN_SECONDARY, dialog_theme
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

_FIELD_STYLE = """
    QLineEdit, QTextEdit {
        background-color: #2d2d2d; color: #f0f0f0; border: 1px solid #555;
        border-radius: 6px; padding: 6px 8px; font-size: 12px;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }
    QLineEdit:focus, QTextEdit:focus { border-color: #6b5a8e; }
"""

_LABEL_STYLE = (
    f"color: {tok.TEXT_MUTED}; font-size: 11px; font-weight: 600; "
    f"background: transparent; font-family: {tok.FONT_APP};"
)


class EditSteamMarkerDialog(SteempegDialog):
    def __init__(
        self,
        title_text: str,
        description: str,
        parent=None,
        **theme_kwargs,
    ):
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent), **theme_kwargs}
        super().__init__("Edit Steam Marker", parent, **theme_kwargs)
        self.setMinimumWidth(360)
        self.resize(400, 280)

        title_lbl = QLabel("Title")
        title_lbl.setStyleSheet(_LABEL_STYLE)
        self.content_layout.addWidget(title_lbl)

        self._title_edit = QLineEdit(title_text)
        self._title_edit.setStyleSheet(_FIELD_STYLE)
        self.content_layout.addWidget(self._title_edit)

        desc_lbl = QLabel("Description")
        desc_lbl.setStyleSheet(_LABEL_STYLE)
        self.content_layout.addWidget(desc_lbl)

        self._desc_edit = QTextEdit(description)
        self._desc_edit.setStyleSheet(_FIELD_STYLE)
        self.content_layout.addWidget(self._desc_edit, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(_BTN_SECONDARY)
        btn_cancel.clicked.connect(self.reject)
        actions.addWidget(btn_cancel)

        btn_save = QPushButton("Save")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(_BTN_PRIMARY)
        btn_save.clicked.connect(self.accept)
        actions.addWidget(btn_save)

        self.content_layout.addLayout(actions)

    @property
    def title_text(self) -> str:
        return self._title_edit.text().strip()

    @property
    def description_text(self) -> str:
        return self._desc_edit.toPlainText().strip()
