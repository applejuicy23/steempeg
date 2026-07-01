"""Grid-style cards for the render queue (mirrors library ClipCard layout)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal, QMimeData, QPoint, QRectF
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from steempeg.core.clip_thumbnails import find_clip_thumbnail
from steempeg.infra import paths
from steempeg.infra.paths import get_resource_path
from steempeg.render.queue import STATUS_COLORS, JobStatus, RenderJob
from steempeg.render.queue_display import (
    format_job_datetime_line,
    format_job_output,
    format_job_preset,
    format_job_trim,
)
from steempeg.ui.widgets.elided_label import ElidedLabel

from steempeg.ui.queue_card_shared import (
    _FONT,
    _MIME_JOB_ID,
    _QUEUE_MENU_STYLE,
    job_accepts_drop as _job_accepts_drop,
    job_can_remove as _job_can_remove,
)

# Match library grid card width; queue footer is taller (more metadata lines).
_CARD_W = 280
_THUMB_H = 148
_TEXT_H = 96
_CARD_H = _THUMB_H + _TEXT_H
_STATUS_DOT = 26
_DRAG_PIXMAP_MAX_W = 280
_DRAG_PIXMAP_MAX_H = 140

_REMOVE_BTN_STYLE = """
    QPushButton#queueRemoveBtn {
        background-color: rgba(120, 45, 45, 0.92);
        border: 1px solid #aa4444;
        color: #ffcccc;
        font-size: 13px;
        font-weight: bold;
        border-radius: 13px;
        padding: 0;
    }
    QPushButton#queueRemoveBtn:hover {
        background-color: #cc3333;
        color: #ffffff;
        border: 1px solid #ff6666;
    }
"""


def _status_dot_style(color: str) -> str:
    r = _STATUS_DOT // 2
    return (
        f"color: #1a1a1a; font-weight: bold; font-size: 12px;"
        f"background-color: {color}; border-radius: {r}px;"
        f"min-width: {_STATUS_DOT}px; max-width: {_STATUS_DOT}px;"
        f"min-height: {_STATUS_DOT}px; max-height: {_STATUS_DOT}px;"
        f"padding: 0; margin: 0;"
    )


class QueueGridJobCard(QWidget):
    clicked = Signal(str)
    remove_requested = Signal(str)
    dropped_on = Signal(str, str)

    def __init__(self, job: RenderJob, selected: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("QueueGridJobCard")
        self._job = job
        self._job_id = job.id
        self._drag_start = QPoint()
        self._selected = selected
        self._hovered = False
        self._drop_highlight = False
        self._press_on_remove = False
        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(_job_accepts_drop(job))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(_CARD_W, _THUMB_H)
        self._thumb_label.setStyleSheet("background-color: #1a1a1a; border: none;")

        thumb_path = find_clip_thumbnail(job.clip_path)
        if thumb_path:
            pixmap = QPixmap(thumb_path)
            if not pixmap.isNull():
                self._thumb_label.setPixmap(
                    pixmap.scaled(
                        _CARD_W,
                        _THUMB_H,
                        Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation,
                    )
                )

        thumb_wrap = QWidget()
        thumb_wrap.setFixedSize(_CARD_W, _THUMB_H)
        thumb_lay = QVBoxLayout(thumb_wrap)
        thumb_lay.setContentsMargins(0, 0, 0, 0)
        thumb_lay.addWidget(self._thumb_label)

        color = STATUS_COLORS.get(job.status, "#ffcc00")
        self._index_badge = QLabel(str(job.queue_index), thumb_wrap)
        self._index_badge.setFixedSize(_STATUS_DOT, _STATUS_DOT)
        self._index_badge.setAlignment(Qt.AlignCenter)
        self._index_badge.setStyleSheet(_status_dot_style(color))
        self._index_badge.move(8, 8)

        icon_path = job.game_icon_path
        unknown = get_resource_path("unknown_icon.png")
        pix_path = icon_path if icon_path and os.path.exists(icon_path) else unknown
        self._icon_label = QLabel(thumb_wrap)
        self._icon_label.setFixedSize(24, 24)
        self._icon_label.move(8, _THUMB_H - 32)
        if pix_path and os.path.exists(pix_path):
            self._icon_label.setPixmap(
                QPixmap(pix_path).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

        self._btn_remove = None
        if _job_can_remove(job):
            self._btn_remove = QPushButton("✕", self)
            self._btn_remove.setObjectName("queueRemoveBtn")
            self._btn_remove.setFixedSize(_STATUS_DOT, _STATUS_DOT)
            self._btn_remove.setCursor(Qt.PointingHandCursor)
            self._btn_remove.setToolTip("Remove from queue")
            self._btn_remove.setStyleSheet(_REMOVE_BTN_STYLE)
            self._btn_remove.clicked.connect(self._on_remove_clicked)
            self._btn_remove.move(_CARD_W - 34, 8)

        text_widget = QWidget()
        text_widget.setFixedHeight(_TEXT_H)
        text_widget.setStyleSheet("""
            QWidget {
                background-color: #383838;
                border: none;
                border-bottom-left-radius: 9px;
                border-bottom-right-radius: 9px;
            }
        """)
        text_layout = QVBoxLayout(text_widget)
        # Padding matched to the comfortable 3-line reference block (12px sides, ~8/10 vertical).
        text_layout.setContentsMargins(12, 8, 12, 10)
        text_layout.setSpacing(3)

        self._title_label = ElidedLabel()
        self._title_label.setText(job.game_name.strip() or os.path.basename(job.clip_path))
        self._title_label.setStyleSheet(
            "QLabel { color: #e0e0e0; font-weight: bold; font-size: 13px; "
            "background: transparent; border: none; }"
        )

        self._meta_label = QLabel(format_job_datetime_line(job))
        self._meta_label.setStyleSheet(
            f"QLabel {{ color: #888888; font-size: 11px; background: transparent; border: none; {_FONT} }}"
        )

        self._preset_label = QLabel(format_job_preset(job.settings))
        self._preset_label.setStyleSheet(
            f"color: #c4b5e8; font-size: 11px; background: transparent; {_FONT}"
        )

        trim_text = format_job_trim(job.settings)
        self._trim_label = QLabel(trim_text)
        self._trim_label.setStyleSheet(
            f"color: #b29ae7; font-size: 11px; background: transparent; {_FONT}"
        )
        self._trim_label.setVisible(
            job.settings.is_trim_mode and job.settings.trim_end_ms > job.settings.trim_start_ms
        )

        self._output_label = ElidedLabel()
        self._output_label.setStyleSheet(
            f"color: #999999; font-size: 11px; background: transparent; {_FONT}"
        )
        self._output_label.setText(format_job_output(job))

        text_layout.addWidget(self._title_label)
        text_layout.addWidget(self._meta_label)
        text_layout.addWidget(self._preset_label)
        text_layout.addWidget(self._trim_label)
        text_layout.addWidget(self._output_label)

        layout.addWidget(thumb_wrap)
        layout.addWidget(text_widget)

        self._border_overlay = QFrame(self)
        self._border_overlay.setGeometry(0, 0, _CARD_W, _CARD_H)
        self._border_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        for child in self.findChildren(QWidget):
            if child in (self, self._border_overlay, self._btn_remove):
                continue
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._border_overlay.raise_()
        self._index_badge.raise_()
        if self._btn_remove is not None:
            self._btn_remove.raise_()
        self._apply_border_style()

    def _on_remove_clicked(self) -> None:
        self.remove_requested.emit(self._job_id)

    def apply_job(self, job: RenderJob, *, selected: bool) -> None:
        self._job = job
        self._selected = selected
        self._drop_highlight = False
        self._index_badge.setText(str(job.queue_index))
        color = STATUS_COLORS.get(job.status, "#ffcc00")
        self._index_badge.setStyleSheet(_status_dot_style(color))
        self._title_label.setText(job.game_name.strip() or os.path.basename(job.clip_path))
        self._meta_label.setText(format_job_datetime_line(job))
        self._preset_label.setText(format_job_preset(job.settings))
        trim_text = format_job_trim(job.settings)
        has_trim = job.settings.is_trim_mode and job.settings.trim_end_ms > job.settings.trim_start_ms
        self._trim_label.setText(trim_text)
        self._trim_label.setVisible(has_trim)
        self._output_label.setText(format_job_output(job))
        self.setAcceptDrops(_job_accepts_drop(job))
        self._apply_border_style()

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_border_style()

    def _apply_border_style(self) -> None:
        if self._drop_highlight:
            border = "2px dashed #b29ae7"
        elif self._selected:
            border = "3px solid #b29ae7"
        elif self._hovered:
            border = "2px solid #7a6aa8"
        else:
            border = "2px solid #444444"
        # Square top (thumb flush), rounded bottom — same as ClipCard.
        self._border_overlay.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: {border};
                border-top-left-radius: 0px;
                border-top-right-radius: 0px;
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }}
        """)

    def enterEvent(self, event):
        self._hovered = True
        self._apply_border_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_border_style()
        super().leaveEvent(event)

    def _drag_preview_pixmap(self) -> QPixmap:
        w = max(1, min(self.width(), _DRAG_PIXMAP_MAX_W))
        h = max(1, min(self.height(), _DRAG_PIXMAP_MAX_H))
        dpr = self.devicePixelRatioF()
        pix = QPixmap(int(w * dpr), int(h * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 12, 12)
        painter.fillPath(path, QColor("#262229"))
        painter.save()
        painter.setClipPath(path)
        painter.setOpacity(0.97)
        self.render(painter, QPoint(0, 0))
        painter.restore()
        painter.setPen(QPen(QColor("#b29ae7"), 2))
        painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 11, 11)
        painter.end()
        return pix

    def _hit_remove_button(self, event) -> bool:
        if self._btn_remove is None or not self._btn_remove.isVisible():
            return False
        gp = event.globalPosition().toPoint()
        return self._btn_remove.rect().contains(self._btn_remove.mapFromGlobal(gp))

    def mousePressEvent(self, event):
        if self._hit_remove_button(event):
            self._press_on_remove = True
            return
        self._press_on_remove = False
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._press_on_remove:
            self._press_on_remove = False
            if self._hit_remove_button(event):
                self.remove_requested.emit(self._job_id)
            return
        if event.button() == Qt.LeftButton:
            if (event.position().toPoint() - self._drag_start).manhattanLength() < 8:
                self.clicked.emit(self._job_id)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_on_remove:
            return
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
        drag.setPixmap(self._drag_preview_pixmap())
        drag.setHotSpot(QPoint(min(event.position().toPoint().x(), _DRAG_PIXMAP_MAX_W // 2), 24))
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if not _job_accepts_drop(self._job):
            return
        if event.mimeData().hasFormat(_MIME_JOB_ID):
            raw = event.mimeData().data(_MIME_JOB_ID)
            source_id = bytes(raw).decode("utf-8") if raw else ""
            if source_id and source_id != self._job_id:
                self._drop_highlight = True
                self._apply_border_style()
                event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drop_highlight = False
        self._apply_border_style()
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_MIME_JOB_ID):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self._drop_highlight = False
        self._apply_border_style()
        raw = event.mimeData().data(_MIME_JOB_ID)
        if not raw:
            return
        source_id = bytes(raw).decode("utf-8")
        if source_id and source_id != self._job_id:
            self.dropped_on.emit(source_id, self._job_id)
        event.acceptProposedAction()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(_QUEUE_MENU_STYLE)
        job = self._job
        is_done = job.status == JobStatus.COMPLETED
        output_dir = os.path.dirname(job.output_file) if job.output_file else ""

        act_select = menu.addAction("▶  Select in editor")
        act_select.triggered.connect(lambda: self.clicked.emit(self._job_id))

        act_open_clip = menu.addAction("📂  Open clip folder")
        act_open_clip.setEnabled(bool(job.clip_path) and os.path.isdir(job.clip_path))
        act_open_clip.triggered.connect(lambda: paths.open_in_file_manager(job.clip_path))

        if is_done:
            act_open_out = menu.addAction("🎬  Open output folder")
            act_open_out.setEnabled(bool(output_dir) and os.path.isdir(output_dir))
            act_open_out.triggered.connect(lambda: paths.open_in_file_manager(output_dir))

        if _job_can_remove(job):
            menu.addSeparator()
            act_remove = menu.addAction("🗑️  Remove from queue")
            act_remove.triggered.connect(lambda: self.remove_requested.emit(self._job_id))

        menu.exec(event.globalPos())
