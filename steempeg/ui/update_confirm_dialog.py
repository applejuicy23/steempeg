"""Steempeg-styled confirmation before starting an update."""
from __future__ import annotations

from enum import Enum

from PySide6.QtWidgets import QHBoxLayout

from steempeg.ui import ui_theme as ut
from steempeg.ui.release_communication import add_release_card, release_button
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.version import APP_VERSION_STR


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
        self.set_comfort_size(540, 318)
        self._choice = UpdateConfirmChoice.CANCEL
        self.content_layout.setSpacing(10)
        version = target_version.lstrip("vV")
        add_release_card(
            self,
            f"Install Steempeg v{version}?",
            f"Installed version: v{APP_VERSION_STR}\n"
            "Steempeg will close while the updater downloads and installs the selected version.",
        )
        add_release_card(
            self,
            "Keep a backup",
            "Save the current build so you can restore it from Update Center. "
            "Restore is available for v37 and later.",
        )
        self.content_layout.addStretch()
        actions = QHBoxLayout()
        actions.setSpacing(8)
        cancel = release_button(actions, "Cancel", self._on_cancel)
        ut.set_stylesheet_if_changed(cancel, ut.about_danger_button_stylesheet())
        actions.addStretch()
        release_button(actions, "Update", self._on_update)
        primary = release_button(actions, "Update && keep backup", self._on_update_backup, primary=True)
        primary.setDefault(True)
        self.content_layout.addLayout(actions)

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
