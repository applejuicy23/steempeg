"""Dialog showing past render-queue batch runs."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.render.queue import JobStatus, STATUS_COLORS
from steempeg.render.queue_display import format_job_output, format_job_preset, format_job_trim
from steempeg.render.queue_history import RenderBatchRecord, parse_history_job
from steempeg.ui.queue_card_shared import _FONT
from steempeg.ui.widgets import ElidedLabel

_DIALOG_STYLE = """
    QDialog { background-color: #1e1e1e; }
    QLabel { background: transparent; border: none; }
"""

_BATCH_FRAME = """
    QFrame#batchFrame {
        background-color: #2a2a2a;
        border: 1px solid #3d3d3d;
        border-radius: 10px;
    }
"""

_JOB_FRAME = """
    QFrame#jobFrame {
        background-color: #242424;
        border: 1px solid #353535;
        border-radius: 8px;
    }
"""


def _format_batch_when(iso: str) -> str:
    if not iso:
        return "Unknown time"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        return iso[:16].replace("T", " ")


def _batch_summary(batch: RenderBatchRecord) -> str:
    parts = []
    if batch.completed_count:
        parts.append(f"{batch.completed_count} done")
    if batch.error_count:
        parts.append(f"{batch.error_count} failed")
    if batch.cancelled_count:
        parts.append(f"{batch.cancelled_count} skipped")
    if batch.cancelled and not parts:
        return "Cancelled"
    return ", ".join(parts) if parts else "No renders"


class RenderQueueHistoryDialog(QDialog):
    open_output_requested = Signal(str)

    def __init__(self, batches: list[RenderBatchRecord], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Render History")
        self.setMinimumSize(520, 480)
        self.resize(560, 560)
        self._batches = batches
        self.setStyleSheet(_DIALOG_STYLE + _BATCH_FRAME + _JOB_FRAME)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Render History")
        title.setStyleSheet(
            f"color: #ffffff; font-size: 16px; font-weight: bold; {_FONT}"
        )
        header.addWidget(title)
        header.addStretch()
        btn_clear = QPushButton("Clear all")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a; color: #cccccc; border: 1px solid #555;
                border-radius: 8px; padding: 4px 12px; font-size: 11px;
            }
            QPushButton:hover { background-color: #5a3535; color: #ffaaaa; }
        """)
        btn_clear.clicked.connect(self._confirm_clear)
        header.addWidget(btn_clear)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(12)

        if not batches:
            empty = QLabel("No batch renders yet.\nRun Render Queue to see history here.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: #666666; font-size: 13px; padding: 40px; {_FONT}")
            host_layout.addWidget(empty)
        else:
            for batch in batches:
                host_layout.addWidget(self._build_batch_card(batch))

        host_layout.addStretch()
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setFixedWidth(100)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #3a324a; color: #e0d4ff; border: 1px solid #6b5a8e;
                border-radius: 8px; padding: 8px 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #4a3f5c; }
        """)
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        root.addLayout(close_row)

    def _confirm_clear(self) -> None:
        if not self._batches:
            return
        if QMessageBox.question(
            self,
            "Clear history",
            "Remove all saved render batches?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._batches.clear()
        self.done(2)

    def _build_batch_card(self, batch: RenderBatchRecord) -> QFrame:
        frame = QFrame()
        frame.setObjectName("batchFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        when = _format_batch_when(batch.finished_at or batch.started_at)
        summary = _batch_summary(batch)
        head = QLabel(f"{when}  •  {summary}")
        head.setStyleSheet(
            f"color: #c4b5e8; font-size: 12px; font-weight: bold; {_FONT}"
        )
        layout.addWidget(head)

        for job_data in batch.jobs:
            layout.addWidget(self._build_job_row(job_data))

        return frame

    def _build_job_row(self, job_data: dict) -> QFrame:
        job, status_key = parse_history_job(job_data)
        frame = QFrame()
        frame.setObjectName("jobFrame")
        row = QVBoxLayout(frame)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(3)

        if job is None:
            row.addWidget(QLabel("Unknown job"))
            return frame

        if status_key == "cancelled":
            color = "#888888"
            status_lbl = "Skipped"
        else:
            try:
                st = JobStatus(status_key)
            except ValueError:
                st = JobStatus.QUEUED
            color = STATUS_COLORS.get(st, "#888888")
            status_lbl = st.value.capitalize()

        title_line = QHBoxLayout()
        name = QLabel(job.game_name.strip() or os.path.basename(job.clip_path))
        name.setStyleSheet(f"color: #f0f0f0; font-weight: bold; font-size: 12px; {_FONT}")
        badge = QLabel(status_lbl)
        badge.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: bold; {_FONT}"
        )
        title_line.addWidget(name, 1)
        title_line.addWidget(badge)
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
        out_lbl = ElidedLabel(f"📁 {out_path}")
        out_lbl.setStyleSheet(f"color: #999999; font-size: 11px; {_FONT}")
        row.addWidget(out_lbl)

        if job.error_message and status_key == JobStatus.ERROR.value:
            err = ElidedLabel(job.error_message[:120])
            err.setStyleSheet(f"color: #ff8888; font-size: 10px; {_FONT}")
            row.addWidget(err)

        if out_path and status_key == JobStatus.COMPLETED.value and os.path.isfile(out_path):
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_open = QPushButton("Open file")
            btn_open.setCursor(Qt.PointingHandCursor)
            btn_open.setStyleSheet("""
                QPushButton {
                    background-color: #333; color: #ccc; border: 1px solid #555;
                    border-radius: 6px; padding: 2px 10px; font-size: 10px;
                }
                QPushButton:hover { background-color: #444; color: #fff; }
            """)
            btn_open.clicked.connect(lambda _=False, p=out_path: self.open_output_requested.emit(p))
            btn_row.addWidget(btn_open)
            row.addLayout(btn_row)

        return frame
