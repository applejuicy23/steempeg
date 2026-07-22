"""Compact render-queue sidebar for the portable Render sheet."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.render.queue import STATUS_COLORS, JobStatus, RenderJob
from steempeg.render.queue_display import format_job_preset
from steempeg.ui.queue_card_shared import _FONT, set_game_icon_label, status_dot_style
from steempeg.ui.widgets.elided_label import ElidedLabel

_SIDEBAR_W = 220
_ICON = 22

_FRAME = """
QFrame#portableQueueSidebar {
    background-color: #252525;
    border: 1px solid #353535;
    border-radius: 10px;
}
"""

_ROW_IDLE = """
QFrame#portableQueueRow {
    background-color: #2a2a2a;
    border: 1px solid #383838;
    border-radius: 8px;
}
QFrame#portableQueueRow:hover {
    border-color: #6b5a8e;
}
"""

_ROW_SELECTED = """
QFrame#portableQueueRow {
    background-color: #322a45;
    border: 2px solid #8e7cc3;
    border-radius: 8px;
}
"""

_BTN_ADD = """
QPushButton {
    background-color: #383838; color: #e0e0e0; border: 2px solid #4a4a4a;
    border-radius: 8px; padding: 4px 8px; font-size: 11px; font-weight: bold;
    font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
}
QPushButton:hover { background-color: #404040; border-color: #6b5a8e; color: #fff; }
QPushButton:disabled { background-color: #262626; color: #555; border-color: #333; }
"""


class _PortableQueueRow(QFrame):
    clicked = Signal(str)

    def __init__(self, job: RenderJob, index: int, selected: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("portableQueueRow")
        self._job_id = job.id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_ROW_SELECTED if selected else _ROW_IDLE)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)

        num = QLabel(str(index))
        num.setFixedWidth(16)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setStyleSheet(f"color: #b29ae7; font-size: 11px; font-weight: bold; {_FONT}")
        lay.addWidget(num, 0)

        icon = QLabel()
        set_game_icon_label(icon, job, size=_ICON)
        lay.addWidget(icon, 0)

        text = QVBoxLayout()
        text.setSpacing(1)
        text.setContentsMargins(0, 0, 0, 0)
        title = ElidedLabel(job.game_name.strip() or os.path.basename(job.clip_path))
        title.setStyleSheet(f"color: #f0f0f0; font-size: 11px; font-weight: bold; {_FONT}")
        meta = ElidedLabel(format_job_preset(job.settings))
        meta.setStyleSheet(f"color: #888888; font-size: 10px; {_FONT}")
        text.addWidget(title)
        text.addWidget(meta)
        lay.addLayout(text, 1)

        dot = QLabel()
        dot.setFixedSize(8, 8)
        color = STATUS_COLORS.get(job.status, "#888888")
        if not isinstance(color, str):
            color = "#888888"
        dot.setStyleSheet(status_dot_style(color, size=8))
        lay.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._job_id)
            event.accept()
            return
        super().mousePressEvent(event)


class PortableQueueSidebar(QFrame):
    """Left queue rail: pick a job → load its settings into the sheet."""

    job_selected = Signal(str)

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(parent)
        self._app = app
        self.setObjectName("portableQueueSidebar")
        self.setStyleSheet(_FRAME)
        self.setFixedWidth(_SIDEBAR_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._title = QLabel("Queue")
        self._title.setStyleSheet(
            f"color: #c4b5e8; font-size: 12px; font-weight: bold; {_FONT}"
        )
        head.addWidget(self._title, 1)

        self._btn_add = QPushButton("+ Add")
        self._btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_add.setFixedHeight(26)
        self._btn_add.setStyleSheet(_BTN_ADD)
        self._btn_add.setToolTip("Add the current clip to the queue")
        self._btn_add.clicked.connect(self._on_add_current)
        head.addWidget(self._btn_add, 0)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._host = QWidget()
        self._list = QVBoxLayout(self._host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(6)
        self._list.addStretch(1)

        self._empty = QLabel("Empty — Add current\nclip, or queue from\nClips Manager.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet(f"color: #777777; font-size: 11px; {_FONT}")
        self._list.insertWidget(0, self._empty)

        scroll.setWidget(self._host)
        root.addWidget(scroll, 1)
        self.refresh()

    def refresh(self) -> None:
        # Clear rows (keep stretch at end).
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        jobs = list(getattr(getattr(self._app, "render_queue", None), "jobs", []) or [])
        selected = getattr(self._app, "_selected_queue_job_id", None)
        self._title.setText(f"Queue ({len(jobs)})")

        if not jobs:
            self._empty = QLabel("Empty — Add current\nclip, or queue from\nClips Manager.")
            self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._empty.setWordWrap(True)
            self._empty.setStyleSheet(f"color: #777777; font-size: 11px; {_FONT}")
            self._list.insertWidget(0, self._empty)
            self._sync_add_enabled()
            return

        pending_i = 0
        for job in jobs:
            if getattr(job, "status", None) == JobStatus.COMPLETED:
                continue
            pending_i += 1
            row = _PortableQueueRow(job, pending_i, selected == job.id, self._host)
            row.clicked.connect(self.job_selected.emit)
            self._list.insertWidget(self._list.count() - 1, row)

        # If we skipped all (all done), show empty-ish count still.
        if self._list.count() == 1:
            self._empty = QLabel("No pending jobs.")
            self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._empty.setStyleSheet(f"color: #777777; font-size: 11px; {_FONT}")
            self._list.insertWidget(0, self._empty)

        self._sync_add_enabled()

    def _sync_add_enabled(self) -> None:
        resolve = getattr(self._app, "_resolve_export_clip_path", None)
        ok = False
        if callable(resolve):
            try:
                ok = bool(resolve())
            except Exception:
                ok = False
        self._btn_add.setEnabled(ok and not getattr(self._app, "_is_rendering", False))

    def _on_add_current(self) -> None:
        resolve = getattr(self._app, "_resolve_export_clip_path", None)
        path = resolve() if callable(resolve) else None
        if not path:
            return
        if hasattr(self._app, "add_clip_to_render_queue"):
            self._app.add_clip_to_render_queue(path)
        self.refresh()
