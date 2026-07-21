"""Steempeg dialog when a render queue batch finishes."""
from __future__ import annotations

import os
from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path, reveal_in_file_manager
from steempeg.render.queue import JobStatus, RenderJob, STATUS_COLORS, job_to_dict
from steempeg.render.queue_display import format_job_output, format_job_preset, format_job_trim
from steempeg.ui import design_tokens as tok
from steempeg.ui.icon_assets import close_clip_icon, load_icon
from steempeg.ui.queue_card_shared import _FONT, set_game_icon_label
from steempeg.ui.widgets import ElidedLabel, SteempegCheckBox
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

_BTN_PRIMARY = """
    QPushButton {
        background-color: #4a3d66; color: #f0ecff; border: 2px solid #6b5a8e;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }
    QPushButton:hover { background-color: #5a4d76; border-color: #b29ae7; }
    QPushButton:pressed { background-color: #3a324a; }
"""

_BTN_SECONDARY = """
    QPushButton {
        background-color: #383838; color: #e0e0e0; border: 2px solid #4a4a4a;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }
    QPushButton:hover { background-color: #404040; color: #ffffff; border: 2px solid #6b5a8e; }
    QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
"""

_PILL_BTN_STYLE = """
    QPushButton {
        background-color: #383838; color: #e0e0e0; border: 2px solid #4a4a4a;
        border-radius: 8px; padding: 6px 14px; font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }
    QPushButton:hover { background-color: #404040; color: #ffffff; border: 2px solid #6b5a8e; }
    QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
"""

_ACTION_BTN_STYLE = """
    QPushButton {
        background-color: #383838; color: #e0e0e0; border: 2px solid #4a4a4a;
        border-radius: 8px; padding: 6px 14px; font-size: 12px; font-weight: normal;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }
    QPushButton:hover { background-color: #404040; color: #ffffff; border: 2px solid #6b5a8e; }
    QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
"""

_JOB_FRAME = """
    QFrame#jobFrame {
        background-color: #242424;
        border: 1px solid #353535;
        border-radius: 8px;
    }
"""

_MASCOT_H = 120
_JOB_TITLE_ICON = 22
_STATUS_ICON = 14
_FONT_SEMIBOLD = f"font-family: {tok.FONT_APP}; font-weight: 600;"


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
    return "Batch render complete", " · ".join(parts)


def _mascot_label(*, success: bool) -> QLabel:
    lbl = QLabel()
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
    lbl.setStyleSheet("background: transparent; border: none;")
    asset = "chupisuccess.png" if success else "saderror.png"
    pix = QPixmap(get_resource_path(asset))
    if not pix.isNull():
        lbl.setPixmap(pix.scaledToHeight(_MASCOT_H, Qt.TransformationMode.SmoothTransformation))
        lbl.setFixedWidth(lbl.pixmap().width())
        lbl.setFixedHeight(_MASCOT_H)
    return lbl


def _status_badge(status: JobStatus) -> QWidget:
    host = QWidget()
    host.setStyleSheet("background: transparent; border: none;")
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    icon = QLabel()
    icon.setFixedSize(_STATUS_ICON, _STATUS_ICON)
    icon.setStyleSheet("background: transparent; border: none;")
    if status == JobStatus.COMPLETED:
        icon.setPixmap(load_icon("success.png", _STATUS_ICON).pixmap(_STATUS_ICON, _STATUS_ICON))
    elif status == JobStatus.ERROR:
        icon.setPixmap(close_clip_icon(_STATUS_ICON).pixmap(_STATUS_ICON, _STATUS_ICON))
    else:
        icon.hide()
    color = STATUS_COLORS.get(status, "#888888")
    text = QLabel(status.value.capitalize())
    text.setStyleSheet(
        f"color: {color}; font-size: 10px; font-weight: bold; {_FONT} background: transparent;"
    )
    row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(text, 0, Qt.AlignmentFlag.AlignVCenter)
    return host


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
    ):
        super().__init__("Batch render complete", parent, bar_color=bar_color, bg_color=bg_color)
        from steempeg.ui.ui_density import scaled_dialog_size

        mw, mh = scaled_dialog_size(520, 420, parent=parent)
        rw, rh = scaled_dialog_size(580, 560, parent=parent)
        self.setMinimumSize(mw, mh)
        self.resize(rw, rh)
        self._choice = BatchCompleteChoice.OK
        self.setStyleSheet(self.styleSheet() + _JOB_FRAME)

        done = sum(1 for j in jobs if j.status == JobStatus.COMPLETED)
        heading_text, summary_text = _batch_heading_summary(jobs)

        header_row = QHBoxLayout()
        header_row.setSpacing(16)
        header_row.addWidget(_mascot_label(success=done > 0), 0, Qt.AlignmentFlag.AlignTop)

        header_text = QVBoxLayout()
        header_text.setSpacing(6)
        heading = QLabel(heading_text)
        heading.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-size: 15px; font-weight: 600; background: transparent;"
        )
        summary = QLabel(summary_text)
        summary.setStyleSheet(f"color: #b29ae7; font-size: 13px; font-weight: 600; background: transparent; {_FONT}")
        header_text.addWidget(heading)
        header_text.addWidget(summary)
        header_row.addLayout(header_text, 1)
        self.content_layout.addLayout(header_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 4, 0, 0)
        host_layout.setSpacing(8)
        for job in jobs:
            host_layout.addWidget(self._build_job_row(job))
        host_layout.addStretch()
        scroll.setWidget(host)
        self.content_layout.addWidget(scroll, 1)

        self._chk_clear_queue = SteempegCheckBox("Always clear render queue after render")
        self._chk_clear_queue.setChecked(bool(always_clear_queue))
        self.content_layout.addWidget(self._chk_clear_queue)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        btn_history = QPushButton("📜  Open Render History")
        btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_history.setStyleSheet(_BTN_SECONDARY)
        btn_history.clicked.connect(lambda: self._pick(BatchCompleteChoice.OPEN_HISTORY))
        actions.addWidget(btn_history)

        actions.addStretch(1)

        btn_ok = QPushButton("OK")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet(_BTN_PRIMARY)
        btn_ok.clicked.connect(lambda: self._pick(BatchCompleteChoice.OK))
        actions.addWidget(btn_ok)

        self.content_layout.addLayout(actions)

    def _pick(self, choice: BatchCompleteChoice) -> None:
        self._choice = choice
        self.accept()

    def choice(self) -> BatchCompleteChoice:
        return self._choice

    def always_clear_queue(self) -> bool:
        return self._chk_clear_queue.isChecked()

    def _build_job_row(self, job: RenderJob) -> QFrame:
        frame = QFrame()
        frame.setObjectName("jobFrame")
        row = QVBoxLayout(frame)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(3)

        title_line = QHBoxLayout()
        title_line.setSpacing(8)
        game_icon = QLabel()
        set_game_icon_label(game_icon, job, size=_JOB_TITLE_ICON)
        name = QLabel(job.game_name.strip() or os.path.basename(job.clip_path))
        name.setStyleSheet(
            f"color: #f0f0f0; font-size: 13px; {_FONT_SEMIBOLD} background: transparent;"
        )
        badge = _status_badge(job.status)
        title_line.addWidget(game_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        title_line.addWidget(name, 1, Qt.AlignmentFlag.AlignVCenter)
        title_line.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addLayout(title_line)

        meta = QLabel(
            f"{job.clip_date} {job.clip_time}  •  {format_job_preset(job.settings)}"
        )
        meta.setStyleSheet(f"color: #888888; font-size: 11px; {_FONT}")
        row.addWidget(meta)

        trim = format_job_trim(job.settings)
        if trim != "Full clip":
            trim_lbl = QLabel(trim)
            trim_lbl.setStyleSheet(f"color: #b29ae7; font-size: 11px; {_FONT}")
            row.addWidget(trim_lbl)

        out_path = job.output_file or format_job_output(job)
        file_exists = bool(out_path and os.path.isfile(out_path))
        path_color = "#999999" if file_exists else "#666666"
        path_suffix = "" if file_exists or not out_path else "  (file deleted)"
        out_lbl = ElidedLabel(f"📁 {out_path}{path_suffix}")
        out_lbl.setToolTip(out_path)
        out_lbl.setStyleSheet(f"color: {path_color}; font-size: 11px; {_FONT}")
        row.addWidget(out_lbl)

        if job.error_message and job.status == JobStatus.ERROR:
            err = ElidedLabel(job.error_message[:120])
            err.setToolTip(job.error_message)
            err.setStyleSheet(f"color: #ff8888; font-size: 10px; {_FONT}")
            row.addWidget(err)

        if file_exists and job.status == JobStatus.COMPLETED:
            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(0, 8, 0, 0)
            btn_row.setSpacing(8)
            btn_row.addStretch()
            btn_folder = QPushButton("Open folder")
            btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_folder.setStyleSheet(_ACTION_BTN_STYLE)
            btn_folder.clicked.connect(lambda _=False, p=out_path: reveal_in_file_manager(p))
            btn_open = QPushButton("Open file")
            btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_open.setStyleSheet(_ACTION_BTN_STYLE)
            btn_open.clicked.connect(lambda _=False, p=out_path: self.open_output_requested.emit(p))
            btn_library = QPushButton("Rendered videos")
            btn_library.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_library.setStyleSheet(_ACTION_BTN_STYLE)
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
            btn_details.setStyleSheet(_PILL_BTN_STYLE)
            job_data = job_to_dict(job)
            btn_details.clicked.connect(lambda _=False, data=job_data: self._show_job_details(data))
            btn_row.addWidget(btn_details)
            clip_path = (job.clip_path or "").strip()
            if clip_path and os.path.isdir(clip_path):
                btn_source = QPushButton("Source clip")
                btn_source.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_source.setStyleSheet(_PILL_BTN_STYLE)
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
