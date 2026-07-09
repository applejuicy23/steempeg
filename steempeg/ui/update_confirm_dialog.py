"""Steempeg-styled confirmation before starting an update."""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

_BTN_PRIMARY = """
    QPushButton {
        background-color: #4a3d66; color: #f0ecff; border: 2px solid #6b5a8e;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
    }
    QPushButton:hover { background-color: #5a4d76; border-color: #b29ae7; }
    QPushButton:pressed { background-color: #3a324a; }
"""

_BTN_SECONDARY = """
    QPushButton {
        background-color: #333; color: #ccc; border: 1px solid #555;
        border-radius: 8px; padding: 8px 16px; font-size: 12px;
    }
    QPushButton:hover { background-color: #444; color: #fff; }
"""

_BTN_DANGER = """
    QPushButton {
        background-color: #3a2222; color: #ff8a8a; border: 1px solid #8b3a3a;
        border-radius: 8px; padding: 8px 16px; font-size: 12px;
    }
    QPushButton:hover { background-color: #522828; color: #ffb3b3; border-color: #c44; }
    QPushButton:pressed { background-color: #2a1818; }
"""


class UpdateConfirmChoice(Enum):
    CANCEL = "cancel"
    UPDATE = "update"
    UPDATE_KEEP_BACKUP = "update_keep_backup"


class UpdateConfirmDialog(SteempegDialog):
    def __init__(
        self,
        target_version: str,
        parent=None,
        *,
        bar_color: str | None = None,
        bg_color: str | None = None,
    ):
        super().__init__("Before updating", parent, bar_color=bar_color, bg_color=bg_color)
        self.setMinimumWidth(420)
        self.resize(460, 210)
        self._choice = UpdateConfirmChoice.CANCEL

        root = self.content_layout

        heading = QLabel(f"Install v{target_version}?")
        heading.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-size: 14px; font-weight: 600; background: transparent;"
        )
        root.addWidget(heading)

        body = QLabel(
            "Steempeg will close and a small updater window will finish the download and install."
        )
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {tok.TEXT_PRIMARY}; font-size: 12px; background: transparent;")
        root.addWidget(body)

        hint = QLabel("Keeping a backup is recommended — you can restore it from Update Center.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent;")
        root.addWidget(hint)

        root.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(_BTN_DANGER)
        btn_cancel.clicked.connect(self._on_cancel)
        actions.addWidget(btn_cancel)

        actions.addStretch(1)

        btn_update = QPushButton("Update")
        btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_update.setStyleSheet(_BTN_SECONDARY)
        btn_update.clicked.connect(self._on_update)
        actions.addWidget(btn_update)

        btn_backup = QPushButton("Update && keep backup")
        btn_backup.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_backup.setStyleSheet(_BTN_PRIMARY)
        btn_backup.clicked.connect(self._on_update_backup)
        actions.addWidget(btn_backup)

        root.addLayout(actions)

    @property
    def choice(self) -> UpdateConfirmChoice:
        return self._choice

    def _on_cancel(self) -> None:
        self._choice = UpdateConfirmChoice.CANCEL
        self.reject()

    def _on_update(self) -> None:
        self._choice = UpdateConfirmChoice.UPDATE
        self.accept()

    def _on_update_backup(self) -> None:
        self._choice = UpdateConfirmChoice.UPDATE_KEEP_BACKUP
        self.accept()
