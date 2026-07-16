"""Already-running dialog: warn + optional second instance."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from steempeg.ui import design_tokens as tok
from steempeg.ui.message_dialog import _BTN_DANGER, _BTN_SECONDARY, dialog_theme
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.widgets.steempeg_check import SteempegCheckBox


class AlreadyRunningDialog(SteempegDialog):
    """Shown when another Steempeg process holds the instance lock."""

    def __init__(self, parent=None, **theme_kwargs):
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent), **theme_kwargs}
        super().__init__("Already running", parent, **theme_kwargs)
        self.setMinimumWidth(420)
        self._run_anyway = False

        body = QLabel("Steempeg is already running.")
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-size: 13px; background: transparent; "
            f"font-family: {tok.FONT_APP};"
        )
        self.content_layout.addWidget(body)

        detail = QLabel(
            "A second copy can fight over the same library cache, render queue, "
            "and update lock — clips and exports may get corrupted or stuck."
        )
        detail.setWordWrap(True)
        detail.setStyleSheet(
            f"color: {tok.TEXT_MUTED}; font-size: 12px; background: transparent; "
            f"font-family: {tok.FONT_APP};"
        )
        self.content_layout.addWidget(detail)

        self._chk = SteempegCheckBox(
            "I understand that launching anyway may cause problems"
        )
        self._chk.stateChanged.connect(self._sync_anyway_enabled)
        self.content_layout.addWidget(self._chk)

        self.content_layout.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(_BTN_SECONDARY)
        btn_cancel.clicked.connect(self.reject)

        self._btn_anyway = QPushButton("RUN ANYWAY")
        self._btn_anyway.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_anyway.setStyleSheet(_BTN_DANGER)
        self._btn_anyway.setEnabled(False)
        self._btn_anyway.clicked.connect(self._accept_anyway)

        actions.addWidget(btn_cancel)
        actions.addWidget(self._btn_anyway)
        self.content_layout.addLayout(actions)

    def _sync_anyway_enabled(self, *_args) -> None:
        self._btn_anyway.setEnabled(self._chk.isChecked())

    def _accept_anyway(self) -> None:
        self._run_anyway = True
        self.accept()

    @property
    def run_anyway(self) -> bool:
        return bool(self._run_anyway)
