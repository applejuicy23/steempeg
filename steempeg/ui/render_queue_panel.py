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
_SCROLL_STYLE = """
    QScrollArea { background: transparent; border: none; }
    QWidget#queueListHost { background: transparent; }
    QScrollBar:vertical { border: none; background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: #4e4e4e; min-height: 30px; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background: #b29ae7; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _job_accepts_drop(job: RenderJob) -> bool:
    return job.status == JobStatus.QUEUED


def _job_can_remove(job: RenderJob) -> bool:
    return job.status != JobStatus.RENDERING


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
        self._selected = selected
        self._drop_highlight = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(_job_accepts_drop(job))
        self._apply_card_style()

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        num = QLabel(str(job.queue_index))
        num.setFixedSize(26, 26)
        num.setAlignment(Qt.AlignCenter)
        self._num_label = num
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

        if _job_can_remove(job):
            btn_remove = QPushButton("✕")
            btn_remove.setObjectName("queueRemoveBtn")
            btn_remove.setFixedSize(24, 24)
            btn_remove.setToolTip("Remove from queue")
            btn_remove.setCursor(Qt.PointingHandCursor)
            btn_remove.clicked.connect(lambda: self.remove_requested.emit(self._job_id))
            root.addWidget(btn_remove, 0, Qt.AlignTop)

        for label in self.findChildren(QLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._refresh_num_style()

    def _refresh_num_style(self) -> None:
        color = STATUS_COLORS.get(self._job.status, "#ffcc00")
        self._num_label.setStyleSheet(
            f"color: #1a1a1a; font-weight: bold; font-size: 12px;"
            f"background-color: {color}; border-radius: 13px;"
        )

    def _apply_card_style(self) -> None:
        color = STATUS_COLORS.get(self._job.status, "#ffcc00")
        r, g, b = _hex_to_rgb(color)
        if self._drop_highlight:
            border = "2px dashed #b29ae7"
        elif self._selected:
            border = "3px solid #b29ae7"
        else:
            border = "2px solid #444444"
        self.setStyleSheet(f"""
            QueueJobCard {{
                background-color: rgba({r}, {g}, {b}, 0.10);
                border: {border};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; border: none; {_FONT} }}
            QPushButton#queueRemoveBtn {{
                background-color: rgba(120, 45, 45, 0.55);
                border: 1px solid #aa4444;
                color: #ffcccc;
                font-size: 13px;
                font-weight: bold;
                border-radius: 12px;
                padding: 0;
            }}
            QPushButton#queueRemoveBtn:hover {{
                background-color: #cc3333;
                color: #ffffff;
                border: 1px solid #ff6666;
            }}
        """)

    def set_drop_highlight(self, active: bool) -> None:
        if self._drop_highlight == active:
            return
        self._drop_highlight = active
        self._apply_card_style()

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

        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        self.render(pixmap)
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.position().toPoint())

        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if not _job_accepts_drop(self._job):
            return
        if event.mimeData().hasFormat(_MIME_JOB_ID):
            raw = event.mimeData().data(_MIME_JOB_ID)
            source_id = bytes(raw).decode("utf-8") if raw else ""
            if source_id and source_id != self._job_id:
                self.set_drop_highlight(True)
                event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_MIME_JOB_ID):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.set_drop_highlight(False)
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
        if _job_can_remove(self._job):
            act_remove = menu.addAction("Remove from queue")
            act_remove.triggered.connect(lambda: self.remove_requested.emit(self._job_id))
        menu.exec(event.globalPos())


class QueueListHost(QWidget):
    """Drop target for inserting at the end of the queue list."""

    dropped_at_end = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("queueListHost")
        self.setAcceptDrops(True)

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
        if source_id:
            self.dropped_at_end.emit(source_id)
        event.acceptProposedAction()


class RenderQueuePanel(QWidget):
    """Scrollable queue list inside a Clips-Manager-style rounded container."""

    job_selected = Signal(str)
    job_remove_requested = Signal(str)
    job_reorder_requested = Signal(str, str)
    job_reorder_after_requested = Signal(str, str)
    clear_queue_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("render_queue_panel")
        self._selected_id: str | None = None
        self._card_widgets: list[QueueJobCard] = []
        self._jobs: list[RenderJob] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 0, 8, 8)
        outer.setSpacing(0)

        self._container = QFrame()
        self._container.setObjectName("queuePanelContainer")
        self._container.setStyleSheet("""
            QFrame#queuePanelContainer {
                background-color: #2d2d2d;
                border: 1px solid #353535;
                border-radius: 12px;
            }
        """)
        container_layout = QVBoxLayout(self._container)
        container_layout.setContentsMargins(10, 10, 10, 10)
        container_layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

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

        header_row.addWidget(self._title_label)
        header_row.addStretch()
        header_row.addWidget(self._count_label)
        header_row.addWidget(self._btn_clear)
        container_layout.addLayout(header_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(_SCROLL_STYLE)

        self._list_host = QueueListHost()
        self._list_host.dropped_at_end.connect(self._on_drop_at_end)
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)

        self._empty_label = QLabel("Right-click a clip → Add to queue\n✕ removes a clip from the queue")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(f"color: #666666; font-size: 12px; {_FONT}")

        self._scroll.setWidget(self._list_host)
        container_layout.addWidget(self._scroll, 1)

        outer.addWidget(self._container, 1)

        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def _clear_drop_highlights(self) -> None:
        for card in self._card_widgets:
            card.set_drop_highlight(False)

    def _on_drop_at_end(self, source_id: str) -> None:
        last_queued = None
        for job in self._jobs:
            if job.status == JobStatus.QUEUED:
                last_queued = job
        if last_queued is None or last_queued.id == source_id:
            return
        self.job_reorder_after_requested.emit(source_id, last_queued.id)

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
            card.dropped_on.connect(self._on_card_drop)
            self._list_layout.addWidget(card)
            self._card_widgets.append(card)
        self._list_layout.addStretch()

    def _on_card_drop(self, source_id: str, target_id: str) -> None:
        self._clear_drop_highlights()
        self.job_reorder_requested.emit(source_id, target_id)

    def _on_card_clicked(self, job_id: str) -> None:
        self._selected_id = job_id
        self.refresh(self._jobs, selected_id=job_id)
        self.job_selected.emit(job_id)
