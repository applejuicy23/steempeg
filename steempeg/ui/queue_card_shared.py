"""Shared constants and helpers for render-queue list/grid cards."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from steempeg.core.clip_thumbnails import resolve_clip_thumbnail
from steempeg.infra.paths import get_resource_path
from steempeg.render.queue import STATUS_COLORS, JobStatus, RenderJob

_FONT = "font-family: 'Segoe UI', Arial, sans-serif;"
_MIME_JOB_ID = "application/x-steempeg-queue-job"

_LIST_THUMB_W = 128
_LIST_THUMB_H = 76
_STATUS_DOT = 26
_QUEUE_CHROME_INSET = 12  # match Clips Manager top_bar horizontal margins

_QUEUE_MENU_STYLE = """
    QMenu {
        background-color: #2d2d2d;
        color: #ffffff;
        border: 2px solid #444444;
        border-radius: 8px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 13px;
        font-weight: bold;
        padding: 4px 0;
    }
    QMenu::item {
        padding: 8px 28px 8px 20px;
        border-radius: 4px;
        margin: 2px 6px;
    }
    QMenu::item:selected {
        background-color: #3a324a;
        color: #b29ae7;
    }
    QMenu::item:disabled {
        color: #777777;
    }
    QMenu::separator {
        height: 1px;
        background: #444444;
        margin: 4px 10px;
    }
"""


def status_dot_style(color: str, *, size: int = _STATUS_DOT) -> str:
    radius = size // 2
    return (
        f"color: #1a1a1a; font-weight: bold; font-size: 12px;"
        f"background-color: {color}; border-radius: {radius}px;"
        f"min-width: {size}px; max-width: {size}px;"
        f"min-height: {size}px; max-height: {size}px;"
        f"padding: 0; margin: 0;"
    )


def set_thumb_pixmap(
    label: QLabel,
    clip_path: str,
    width: int,
    height: int,
    cache_dir: str | None = None,
) -> None:
    label.setPixmap(QPixmap())
    thumb_path = resolve_clip_thumbnail(clip_path, cache_dir, allow_generate=False)
    if not thumb_path:
        return
    pixmap = QPixmap(thumb_path)
    if pixmap.isNull():
        return
    label.setPixmap(
        pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                      Qt.TransformationMode.SmoothTransformation)
    )


def set_game_icon_label(label: QLabel, job: RenderJob, *, size: int = 28) -> None:
    label.setPixmap(QPixmap())
    label.setFixedSize(size, size)
    icon_path = job.game_icon_path
    unknown = get_resource_path("unknown_icon.png")
    pix_path = icon_path if icon_path and os.path.exists(icon_path) else unknown
    if pix_path and os.path.exists(pix_path):
        label.setPixmap(
            QPixmap(pix_path).scaled(
                size, size, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


def build_queue_thumb_strip(
    job: RenderJob,
    *,
    width: int = _LIST_THUMB_W,
    height: int = _LIST_THUMB_H,
    show_game_icon: bool = True,
    cache_dir: str | None = None,
) -> tuple[QWidget, QLabel, QLabel]:
    """Thumbnail area with queue index badge; optional game icon bottom-left."""
    wrap = QWidget()
    wrap.setFixedSize(width, height)

    thumb = QLabel(wrap)
    thumb.setGeometry(0, 0, width, height)
    thumb.setStyleSheet("background-color: #1a1a1a; border: none; border-radius: 8px;")
    set_thumb_pixmap(thumb, job.clip_path, width, height, cache_dir=cache_dir)

    color = STATUS_COLORS.get(job.status, "#ffcc00")
    badge = QLabel(str(job.queue_index), wrap)
    badge.setFixedSize(_STATUS_DOT, _STATUS_DOT)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setStyleSheet(status_dot_style(color))
    badge.move(6, 6)

    icon_label = QLabel(wrap)
    icon_label.setFixedSize(22, 22)
    icon_label.move(6, height - 28)
    if show_game_icon:
        icon_path = job.game_icon_path
        unknown = get_resource_path("unknown_icon.png")
        pix_path = icon_path if icon_path and os.path.exists(icon_path) else unknown
        if pix_path and os.path.exists(pix_path):
            icon_label.setPixmap(
                QPixmap(pix_path).scaled(
                    22, 22, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
    else:
        icon_label.hide()

    badge.raise_()
    icon_label.raise_()
    return wrap, badge, icon_label


def job_accepts_drop(job: RenderJob) -> bool:
    return job.status == JobStatus.QUEUED


def job_can_remove(job: RenderJob) -> bool:
    return job.status != JobStatus.RENDERING
