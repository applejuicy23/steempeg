"""Steempeg dialog when a render queue batch finishes."""
from __future__ import annotations

import os
from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import reveal_in_file_manager
from steempeg.render.queue import JobStatus, RenderJob, job_to_dict
from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui.widgets.dialog_chrome import SteempegDialog
from steempeg.ui.render_result_widgets import ExportResultCard, ResultHeader

def _result_action_style() -> str:
    """Use the same action buttons as Settings General Browse / Reset."""
    return ut.settings_dialog_secondary_button_stylesheet()


class BatchCompleteChoice(Enum):
    OK = "ok"
    OPEN_HISTORY = "history"


def _batch_heading_summary(jobs: list[RenderJob]) -> tuple[str, str]:
    done = sum(1 for j in jobs if j.status == JobStatus.COMPLETED)
    failed = sum(1 for j in jobs if j.status == JobStatus.ERROR)
    if failed == 0:
        clip_word = "clip" if done == 1 else "clips"
        return "Batch render complete", f"{done} {clip_word} exported successfully"
    if done == 0:
        render_word = "render" if failed == 1 else "renders"
        return "Batch render finished", f"All {failed} {render_word} failed"
    parts = []
    if done:
        parts.append(f"{done} exported")
    if failed:
        parts.append(f"{failed} failed")
    return "Batch render complete", " | ".join(parts)


class BatchCompleteDialog(SteempegDialog):
    open_output_requested = Signal(str)
    open_in_rendered_requested = Signal(str)
    open_source_clip_requested = Signal(str)

    def __init__(
        self,
        jobs: list[RenderJob],
        parent=None,
        *,
        bar_color: str | None = None,
        bg_color: str | None = None,
        always_clear_queue: bool = True,
        cache_dir: str | None = None,
        elapsed_seconds: float | None = None,
    ):
        # Retain the legacy keyword for older callers, without an opt-out UI.
        super().__init__("Batch render complete", parent, bar_color=bar_color, bg_color=bg_color)
        from steempeg.ui.ui_density import scaled_dialog_size

        mw, mh = scaled_dialog_size(520, 420, parent=parent)
        rw, rh = scaled_dialog_size(640, 640, parent=parent)
        self.setMinimumSize(mw, mh)
        self.resize(rw, rh)
        self._choice = BatchCompleteChoice.OK
        self._cache_dir = cache_dir

        done = sum(1 for j in jobs if j.status == JobStatus.COMPLETED)
        heading_text, summary_text = _batch_heading_summary(jobs)

        self._result_header = ResultHeader(heading_text, summary_text, success=done > 0,
                                           elapsed_seconds=elapsed_seconds)
        self.content_layout.addWidget(self._result_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        tok.apply_dialog_scroll_bg(scroll, self._bg_color)
        from steempeg.ui.library.library_styles import (
            LIBRARY_SCROLLBAR_VERTICAL,
            install_library_vertical_scrollbar,
        )

        scroll.setStyleSheet(
            tok.dialog_scroll_stylesheet(self._bg_color) + LIBRARY_SCROLLBAR_VERTICAL
        )
        install_library_vertical_scrollbar(scroll)

        host = QWidget()
        host.setObjectName("batchResultsHost")
        host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        host.setStyleSheet(f"QWidget#batchResultsHost {{ background-color: {self._bg_color}; }}")
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(8)
        for job in jobs:
            host_layout.addWidget(self._build_job_row(job))
        host_layout.addStretch()
        scroll.setWidget(host)
        self.content_layout.addWidget(scroll, 1)
        self._results_scroll = scroll
        self._results_host = host

        actions = QHBoxLayout()
        actions.setSpacing(8)

        btn_history = QPushButton("📜  Open Render History")
        btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_history.setStyleSheet(ut.about_secondary_button_stylesheet())
        btn_history.clicked.connect(lambda: self._pick(BatchCompleteChoice.OPEN_HISTORY))
        actions.addWidget(btn_history)

        actions.addStretch(1)

        btn_ok = QPushButton("OK")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet(ut.about_accent_button_stylesheet())
        btn_ok.clicked.connect(lambda: self._pick(BatchCompleteChoice.OK))
        actions.addWidget(btn_ok)

        self.content_layout.addLayout(actions)
        self._footer_buttons = (btn_history, btn_ok)

    def apply_ui_theme_chrome(self) -> None:
        super().apply_ui_theme_chrome()
        self._result_header.apply_theme()
        for card in self.findChildren(ExportResultCard):
            card.apply_theme()
            for button in card.findChildren(QPushButton):
                button.setStyleSheet(_result_action_style())
        self._footer_buttons[0].setStyleSheet(ut.about_secondary_button_stylesheet())
        self._footer_buttons[1].setStyleSheet(ut.about_accent_button_stylesheet())
        tok.apply_dialog_scroll_bg(self._results_scroll, self._bg_color)
        from steempeg.ui.library.library_styles import LIBRARY_SCROLLBAR_VERTICAL
        self._results_scroll.setStyleSheet(tok.dialog_scroll_stylesheet(self._bg_color) + LIBRARY_SCROLLBAR_VERTICAL)
        self._results_host.setStyleSheet(f"QWidget#batchResultsHost {{background-color: {self._bg_color};}}")

    def _pick(self, choice: BatchCompleteChoice) -> None:
        self._choice = choice
        self.accept()

    def choice(self) -> BatchCompleteChoice:
        return self._choice

    def always_clear_queue(self) -> bool:
        """Compatibility for older callers; completed batches always clear."""
        return True

    def _build_job_row(self, job: RenderJob) -> QFrame:
        frame = ExportResultCard(job, cache_dir=self._cache_dir)
        row = frame.body
        out_path = frame.output_path
        file_exists = frame.file_exists

        if file_exists and job.status == JobStatus.COMPLETED:
            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(0, 8, 0, 0)
            btn_row.setSpacing(8)
            btn_row.addStretch()
            btn_folder = QPushButton("📂  Open folder")
            btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_folder.setStyleSheet(_result_action_style())
            btn_folder.clicked.connect(lambda _=False, p=out_path: reveal_in_file_manager(p))
            btn_open = QPushButton("▶️  Open file")
            btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_open.setStyleSheet(_result_action_style())
            btn_open.clicked.connect(lambda _=False, p=out_path: self.open_output_requested.emit(p))
            btn_library = QPushButton("🎬  Rendered videos")
            btn_library.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_library.setStyleSheet(_result_action_style())
            btn_library.clicked.connect(
                lambda _=False, p=out_path: self.open_in_rendered_requested.emit(p)
            )
            btn_row.addWidget(btn_folder)
            btn_row.addWidget(btn_open)
            btn_row.addWidget(btn_library)
            row.addLayout(btn_row)
        elif job.status in (JobStatus.COMPLETED, JobStatus.ERROR):
            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(0, 8, 0, 0)
            btn_row.setSpacing(8)
            btn_row.addStretch()
            btn_details = QPushButton("Details")
            btn_details.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_details.setStyleSheet(_result_action_style())
            job_data = job_to_dict(job)
            btn_details.clicked.connect(lambda _=False, data=job_data: self._show_job_details(data))
            btn_row.addWidget(btn_details)
            clip_path = (job.clip_path or "").strip()
            if clip_path and os.path.isdir(clip_path):
                btn_source = QPushButton("Source clip")
                btn_source.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_source.setStyleSheet(_result_action_style())
                btn_source.clicked.connect(
                    lambda _=False, p=clip_path: self.open_source_clip_requested.emit(p)
                )
                btn_row.addWidget(btn_source)
            row.addLayout(btn_row)

        return frame

    def _show_job_details(self, job_data: dict) -> None:
        from steempeg.ui.render_history_detail_dialog import RenderHistoryDetailDialog

        dlg = RenderHistoryDetailDialog(job_data, parent=self)
        dlg.open_source_clip_requested.connect(self.open_source_clip_requested.emit)
        dlg.open_in_rendered_requested.connect(self.open_in_rendered_requested.emit)
        dlg.open_folder_requested.connect(lambda p: reveal_in_file_manager(p))
        dlg.exec()
