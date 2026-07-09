"""Steempeg-styled updater window for download / extract / install / launch."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel

from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.animated_render_bar import AnimatedRenderBar
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

_PHASE_LABELS = {
    "download": "Downloading update…",
    "extract": "Extracting update…",
    "install": "Installing files…",
    "launch": "Starting Steempeg…",
    "error": "Update failed",
}


class UpdateProgressDialog(SteempegDialog):
    cancel_requested = Signal()

    def __init__(
        self,
        target_label: str,
        parent=None,
        *,
        bar_color: str | None = None,
        bg_color: str | None = None,
    ):
        super().__init__(
            "Steempeg Updater",
            parent,
            bar_color=bar_color,
            bg_color=bg_color,
            show_minimize=True,
        )
        self.setMinimumWidth(420)
        self.resize(440, 200)
        self._phase_key = "download"

        root = self.content_layout

        self._title = QLabel(f"⚙️ Updating to {target_label}")
        self._title.setStyleSheet(tok.STYLE_PANEL_HEADING)
        root.addWidget(self._title)

        self._phase = QLabel(_PHASE_LABELS["download"])
        self._phase.setStyleSheet(
            f"color: {tok.TEXT_PRIMARY}; font-family: {tok.FONT_APP}; "
            "font-size: 12px; background: transparent;"
        )
        root.addWidget(self._phase)

        self._detail = QLabel("")
        self._detail.setStyleSheet(
            f"color: {tok.TEXT_MUTED}; font-family: {tok.FONT_APP}; "
            "font-size: 11px; background: transparent;"
        )
        self._detail.setWordWrap(True)
        root.addWidget(self._detail)

        self._bar = AnimatedRenderBar()
        self._bar.set_progress(0.0)
        self._bar.set_state("rendering")
        root.addWidget(self._bar)

        hint = QLabel("Close during download to cancel. After that, let the updater finish.")
        hint.setStyleSheet(
            f"color: {tok.TEXT_MUTED}; font-family: {tok.FONT_APP}; "
            "font-size: 10px; background: transparent;"
        )
        root.addWidget(hint)

        self._title_bar.close_requested.disconnect()
        self._title_bar.close_requested.connect(self._on_close_requested)
        self._sync_close_enabled()

    def _on_close_requested(self) -> None:
        if self._phase_key == "download":
            self.cancel_requested.emit()
            self.reject()
        elif self._phase_key == "error":
            self.reject()

    def _sync_close_enabled(self) -> None:
        self._title_bar.btn_close.setEnabled(self._phase_key in ("download", "error"))

    def set_phase(self, phase_key: str, *, percent: float | None = None) -> None:
        self._phase_key = phase_key
        self._phase.setText(_PHASE_LABELS.get(phase_key, phase_key))
        if percent is not None:
            self._bar.set_progress(percent)
        if phase_key == "launch":
            self._bar.set_state("rendering")
            self._bar.set_progress(95.0)
        if phase_key == "error":
            self._bar.set_state("error")
        self._sync_close_enabled()

    def set_detail(self, text: str) -> None:
        self._detail.setText(text)

    def set_download_progress(self, percent: int, text: str) -> None:
        self._phase_key = "download"
        self._phase.setText(_PHASE_LABELS["download"])
        self._bar.set_progress(float(percent) * 0.7)
        self._detail.setText(text.replace("Downloading update...\n", ""))
        self._sync_close_enabled()
