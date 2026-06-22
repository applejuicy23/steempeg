"""Right-side render queue panel — job cards with status colours."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal, QMimeData, QPoint
from PySide6.QtGui import QDrag, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.render.queue import STATUS_COLORS, JobStatus, RenderJob

_FONT = "font-family: 'Segoe UI', Arial, sans-serif;"
_MIME_JOB_ID = "application/x-steempeg-queue-job"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class QueueJobCard(QFrame):
    clicked = Signal(str)
    remove_requested = Signal(str)
    dropped_on = Signal(str, str)

    def __init__(self, job: RenderJob, selected: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("QueueJobCard")
        self._job = job
        self._job_id = job.id
        self._drag_start = QPoint()
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(job.status == JobStatus.QUEUED)

        color = STATUS_COLORS.get(job.status, "#ffcc00")
        r, g, b = _hex_to_rgb(color)
        border = "2px solid #8e7cc3" if selected else f"2px solid {color}"
        self.setStyleSheet(f"""
            QueueJobCard {{
                background-color: rgba({r}, {g}, {b}, 0.12);
                border: {border};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; border: none; {_FONT} }}
            QPushButton#queueRemoveBtn {{
                background: transparent; border: none; color: #888888;
                font-size: 11px; font-weight: bold; padding: 0;
            }}
            QPushButton#queueRemoveBtn:hover {{ color: #ff6666; }}
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        num = QLabel(str(job.queue_index))
        num.setFixedSize(26, 26)
        num.setAlignment(Qt.AlignCenter)
        num.setStyleSheet(
            f"color: #1a1a1a; font-weight: bold; font-size: 12px;"
            f"background-color: {color}; border-radius: 13px;"
        )
        root.addWidget(num, 0, Qt.AlignTop)

        icon = QLabel()
        icon.setFixedSize(28, 28)
        icon_path = job.game_icon_path
        unknown = get_resource_path("unknown_icon.png")
        pix_path = icon_path if icon_path and os.path.exists(icon_path) else unknown
        if pix_path and os.path.exists(pix_path):
            icon.setPixmap(
                QPixmap(pix_path).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        root.addWidget(icon, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title = QLabel(job.game_name.strip())
        title.setStyleSheet("color: #f0f0f0; font-weight: bold; font-size: 13px;")
        title.setWordWrap(True)

        date_line = (job.clip_date or "").replace("\n", " • ")
        meta_text = date_line
        if job.clip_time and job.clip_time not in date_line:
            meta_text = f"{date_line} • {job.clip_time}" if date_line else job.clip_time
        meta = QLabel(meta_text)
        meta.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        meta.setWordWrap(True)

        text_col.addWidget(title)
        text_col.addWidget(meta)
        root.addLayout(text_col, 1)

        if job.status in (JobStatus.QUEUED, JobStatus.ERROR):
            btn_remove = QPushButton("✕")
            btn_remove.setObjectName("queueRemoveBtn")
            btn_remove.setFixedSize(20, 20)
            btn_remove.setToolTip("Remove from queue")
            btn_remove.setCursor(Qt.PointingHandCursor)
            btn_remove.clicked.connect(lambda: self.remove_requested.emit(self._job_id))
            root.addWidget(btn_remove, 0, Qt.AlignTop)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if (event.position().toPoint() - self._drag_start).manhattanLength() < 8:
                self.clicked.emit(self._job_id)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if self._job.status != JobStatus.QUEUED:
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME_JOB_ID, self._job_id.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_MIME_JOB_ID):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_MIME_JOB_ID):
            event.acceptProposedAction()

    def dropEvent(self, event):
        raw = event.mimeData().data(_MIME_JOB_ID)
        if not raw:
            return
        source_id = bytes(raw).decode("utf-8")
        if source_id and source_id != self._job_id:
            self.dropped_on.emit(source_id, self._job_id)
        event.acceptProposedAction()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #2d2d2d; color: white; border: 1px solid #444; }
            QMenu::item:selected { background-color: #5a4b7a; }
        """)
        if self._job.status in (JobStatus.QUEUED, JobStatus.ERROR):
            act_remove = menu.addAction("Remove from queue")
            act_remove.triggered.connect(lambda: self.remove_requested.emit(self._job_id))
        menu.exec(event.globalPos())


class RenderQueuePanel(QWidget):
    """Scrollable queue list with a Clips-Manager-style header pill."""

    job_selected = Signal(str)
    job_remove_requested = Signal(str)
    job_reorder_requested = Signal(str, str)
    clear_queue_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("render_queue_panel")
        self._selected_id: str | None = None
        self._card_widgets: list[QueueJobCard] = []
        self._jobs: list[RenderJob] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)

        pill = QFrame()
        pill.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border: 1px solid #353535;
                border-radius: 16px;
            }
        """)
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(16, 8, 12, 8)

        self._title_label = QLabel("🎬 Render Queue")
        self._title_label.setStyleSheet(
            f"color: #ffffff; font-weight: bold; font-size: 14px; {_FONT}"
        )
        self._count_label = QLabel("0")
        self._count_label.setStyleSheet(
            f"color: #888888; font-weight: bold; font-size: 13px; {_FONT}"
        )

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setCursor(Qt.PointingHandCursor)
        self._btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a; color: #cccccc; border: 1px solid #555;
                border-radius: 10px; padding: 2px 10px; font-size: 11px;
            }
            QPushButton:hover { background-color: #5a3535; color: #ffaaaa; }
        """)
        self._btn_clear.clicked.connect(self.clear_queue_requested.emit)

        pill_layout.addWidget(self._title_label)
        pill_layout.addStretch()
        pill_layout.addWidget(self._count_label)
        pill_layout.addWidget(self._btn_clear)

        header_row.addStretch()
        header_row.addWidget(pill)
        header_row.addStretch()
        outer.addLayout(header_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QWidget#queueListHost { background: transparent; }
            QScrollBar:vertical {
                background: transparent; width: 10px; margin: 4px 2px 4px 0;
            }
            QScrollBar::handle:vertical {
                background: #5a4b7a; min-height: 24px; border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self._list_host = QWidget()
        self._list_host.setObjectName("queueListHost")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(4, 0, 4, 8)
        self._list_layout.setSpacing(8)

        self._empty_label = QLabel("Add clips via\nright-click → Add to queue")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(f"color: #666666; font-size: 12px; {_FONT}")

        self._scroll.setWidget(self._list_host)
        outer.addWidget(self._scroll, 1)

        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def refresh(self, jobs: list[RenderJob], selected_id: str | None = None) -> None:
        self._jobs = list(jobs)
        self._selected_id = selected_id
        self._count_label.setText(str(len(jobs)))
        self._btn_clear.setEnabled(len(jobs) > 0)

        if self._empty_label.parent() is not None:
            self._list_layout.removeWidget(self._empty_label)

        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._empty_label:
                w.deleteLater()
        self._card_widgets.clear()

        if not jobs:
            self._list_layout.addWidget(self._empty_label)
            self._list_layout.addStretch()
            self._empty_label.show()
            return

        self._empty_label.hide()
        for job in jobs:
            card = QueueJobCard(job, selected=(job.id == selected_id))
            card.clicked.connect(self._on_card_clicked)
            card.remove_requested.connect(self.job_remove_requested.emit)
            card.dropped_on.connect(self.job_reorder_requested.emit)
            self._list_layout.addWidget(card)
            self._card_widgets.append(card)
        self._list_layout.addStretch()

    def _on_card_clicked(self, job_id: str) -> None:
        self._selected_id = job_id
        self.refresh(self._jobs, selected_id=job_id)
        self.job_selected.emit(job_id)
