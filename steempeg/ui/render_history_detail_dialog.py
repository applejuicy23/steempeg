"""Steempeg dialog — full metadata for a render-history job."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from steempeg.render.queue import JobStatus
from steempeg.render.queue_display import format_job_output, format_job_preset, format_job_trim
from steempeg.render.queue_history import parse_history_job
from steempeg.ui import design_tokens as tok
from steempeg.ui.message_dialog import _BTN_PRIMARY, _BTN_SECONDARY, dialog_theme
from steempeg.ui.widgets import ElidedLabel
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

_LABEL = (
    f"color: {tok.TEXT_MUTED}; font-size: 11px; font-weight: 600; "
    f"background: transparent; font-family: {tok.FONT_APP};"
)
_VALUE = (
    f"color: {tok.TEXT_PRIMARY}; font-size: 12px; background: transparent; "
    f"font-family: {tok.FONT_APP};"
)
_MISSING = (
    f"color: #aa6666; font-size: 12px; background: transparent; "
    f"font-family: {tok.FONT_APP};"
)


class RenderHistoryDetailDialog(SteempegDialog):
    open_source_clip_requested = Signal(str)
    open_in_rendered_requested = Signal(str)
    open_folder_requested = Signal(str)

    def __init__(self, job_data: dict, parent=None, **theme_kwargs):
        if not theme_kwargs.get("bar_color"):
            theme_kwargs = {**dialog_theme(parent), **theme_kwargs}
        super().__init__("Render details", parent, **theme_kwargs)
        self.setMinimumWidth(460)
        self.resize(500, 380)

        job, status_key = parse_history_job(job_data)
        if job is None:
            err = QLabel("Could not read this history entry.")
            err.setStyleSheet(_VALUE)
            self.content_layout.addWidget(err)
            self._add_close_only()
            return

        if status_key == "cancelled":
            status_text = "Skipped"
        else:
            try:
                status_text = JobStatus(status_key).value.capitalize()
            except ValueError:
                status_text = status_key.capitalize()

        out_path = job.output_file or format_job_output(job)
        file_exists = bool(out_path and os.path.isfile(out_path))
        clip_path = (job.clip_path or "").strip()
        clip_exists = bool(clip_path and os.path.isdir(clip_path))

        self._add_row("Status", status_text)
        game = job.game_name.strip() or os.path.basename(clip_path) or "Unknown"
        self._add_row("Game", game)
        self._add_row("Clip date", f"{job.clip_date} {job.clip_time}".strip())
        self._add_row("Preset", format_job_preset(job.settings))
        trim = format_job_trim(job.settings)
        if trim != "Full clip":
            self._add_row("Trim", trim.replace("✂️ ", ""))

        self._add_path_row("Source clip", clip_path, clip_exists)
        self._add_path_row("Output file", out_path, file_exists)

        if job.error_message and status_key == JobStatus.ERROR.value:
            err_lbl = QLabel(job.error_message)
            err_lbl.setWordWrap(True)
            err_lbl.setStyleSheet(
                f"color: #ff8888; font-size: 11px; background: transparent; font-family: {tok.FONT_APP};"
            )
            cap = QLabel("Error")
            cap.setStyleSheet(_LABEL)
            self.content_layout.addWidget(cap)
            self.content_layout.addWidget(err_lbl)

        if not file_exists and status_key == JobStatus.COMPLETED.value:
            hint = QLabel(
                "The exported file is gone, but Steempeg still remembers this render in history."
            )
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"color: {tok.TEXT_MUTED}; font-size: 11px; background: transparent; font-family: {tok.FONT_APP};"
            )
            self.content_layout.addWidget(hint)

        self.content_layout.addStretch(1)
        self._add_actions(
            clip_path=clip_path if clip_exists else "",
            out_path=out_path if file_exists else "",
        )

    def _add_row(self, label: str, value: str) -> None:
        if not value:
            return
        cap = QLabel(label)
        cap.setStyleSheet(_LABEL)
        val = QLabel(value)
        val.setWordWrap(True)
        val.setStyleSheet(_VALUE)
        self.content_layout.addWidget(cap)
        self.content_layout.addWidget(val)

    def _add_path_row(self, label: str, path: str, exists: bool) -> None:
        if not path:
            return
        cap = QLabel(label)
        cap.setStyleSheet(_LABEL)
        suffix = "" if exists else "  (not found)"
        val = ElidedLabel(f"{path}{suffix}")
        val.setToolTip(path)
        val.setStyleSheet(_MISSING if not exists else _VALUE)
        self.content_layout.addWidget(cap)
        self.content_layout.addWidget(val)

    def _add_actions(self, *, clip_path: str, out_path: str) -> None:
        actions = QHBoxLayout()
        actions.setSpacing(8)

        if clip_path:
            btn_clip = QPushButton("Open source clip")
            btn_clip.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_clip.setStyleSheet(_BTN_SECONDARY)
            btn_clip.clicked.connect(lambda: self._action(self.open_source_clip_requested, clip_path))
            actions.addWidget(btn_clip)

        if out_path:
            btn_folder = QPushButton("Open folder")
            btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_folder.setStyleSheet(_BTN_SECONDARY)
            btn_folder.clicked.connect(lambda: self._action(self.open_folder_requested, out_path))
            actions.addWidget(btn_folder)

            btn_library = QPushButton("Rendered videos")
            btn_library.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_library.setStyleSheet(_BTN_SECONDARY)
            btn_library.clicked.connect(
                lambda: self._action(self.open_in_rendered_requested, out_path)
            )
            actions.addWidget(btn_library)

        actions.addStretch(1)

        btn_close = QPushButton("Close")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet(_BTN_PRIMARY)
        btn_close.clicked.connect(self.accept)
        actions.addWidget(btn_close)

        self.content_layout.addLayout(actions)

    def _add_close_only(self) -> None:
        self.content_layout.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton("Close")
        btn.setStyleSheet(_BTN_PRIMARY)
        btn.clicked.connect(self.accept)
        row.addWidget(btn)
        self.content_layout.addLayout(row)

    def _action(self, signal, value: str) -> None:
        signal.emit(value)
        self.accept()
