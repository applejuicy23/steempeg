"""Right-side render queue panel — job cards with status colours."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.render.queue import STATUS_COLORS, RenderJob

_FONT = "font-family: 'Segoe UI', Arial, sans-serif;"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class QueueJobCard(QFrame):
    clicked = Signal(str)

    def __init__(self, job: RenderJob, selected: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("QueueJobCard")
        self._job_id = job.id
        self.setCursor(Qt.PointingHandCursor)

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

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._job_id)
        super().mousePressEvent(event)


class RenderQueuePanel(QWidget):
    """Scrollable queue list with a Clips-Manager-style header pill."""

    job_selected = Signal(str)

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
        pill_layout.setContentsMargins(20, 8, 20, 8)

        self._title_label = QLabel("🎬 Render Queue")
        self._title_label.setStyleSheet(
            f"color: #ffffff; font-weight: bold; font-size: 14px; {_FONT}"
        )
        self._count_label = QLabel("0")
        self._count_label.setStyleSheet(
            f"color: #888888; font-weight: bold; font-size: 13px; {_FONT}"
        )
        pill_layout.addWidget(self._title_label)
        pill_layout.addStretch()
        pill_layout.addWidget(self._count_label)

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

        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
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
            self._list_layout.addWidget(card)
            self._card_widgets.append(card)
        self._list_layout.addStretch()

    def _on_card_clicked(self, job_id: str) -> None:
        self._selected_id = job_id
        self.refresh(self._jobs, selected_id=job_id)
        self.job_selected.emit(job_id)
