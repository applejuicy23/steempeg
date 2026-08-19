"""Shared constants and helpers for render-queue list/grid cards."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from steempeg.core.clip_thumbnails import resolve_clip_thumbnail
from steempeg.infra.paths import get_resource_path
from steempeg.render.queue import STATUS_COLORS, JobStatus, RenderJob
from steempeg.ui.ui_density import COMFORT, UiDensity

_FONT = "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"
_MIME_JOB_ID = "application/x-steempeg-queue-job"

_LIST_THUMB_W = 128
_LIST_THUMB_H = 76
_STATUS_DOT = 26
_QUEUE_CHROME_INSET = 12  # match Clips Manager top_bar horizontal margins

# Pipeline outline (portable + desktop list) — gray waiting · yellow ready · etc.
STATUS_BORDER_IDLE = "#555555"
STATUS_BORDER_READY = "#ffcc00"
STATUS_BORDER_NEXT = "#d4b84a"
STATUS_BORDER_RENDER = "#ff9800"
STATUS_BORDER_DONE = "#4CAF50"
STATUS_BORDER_ERROR = "#ff4444"

# Flat card fill (portable). Desktop Ready keeps a soft yellow wash on top of this rule.
STATUS_CARD_BG = "#2a2a2a"
STATUS_CARD_BG_SELECTED = "#322a45"
STATUS_CARD_BG_READY = "rgba(255, 204, 0, 0.10)"


def status_border_for_job(job: RenderJob, jobs: list[RenderJob]) -> tuple[str, int]:
    """Return (border_color, border_px) for the render pipeline outline.

    Gray = further back · yellow = next ready · soft yellow = up next while
    another job renders · orange = rendering · green = done · red = error.
    """
    st = getattr(job, "status", None)
    if st == JobStatus.COMPLETED:
        return STATUS_BORDER_DONE, 2
    if st == JobStatus.ERROR:
        return STATUS_BORDER_ERROR, 2
    if st == JobStatus.RENDERING:
        return STATUS_BORDER_RENDER, 2

    rendering = any(getattr(j, "status", None) == JobStatus.RENDERING for j in jobs)
    queued = [j for j in jobs if getattr(j, "status", None) == JobStatus.QUEUED]
    if queued and job.id == queued[0].id:
        if rendering:
            return STATUS_BORDER_NEXT, 2
        return STATUS_BORDER_READY, 2
    return STATUS_BORDER_IDLE, 1


def status_card_background(
    job: RenderJob,
    jobs: list[RenderJob],
    *,
    selected: bool = False,
) -> str:
    """Card fill: flat like portable, plus desktop Ready yellow tint."""
    from steempeg.ui import ui_theme as ut

    if selected:
        return STATUS_CARD_BG_SELECTED
    border, _ = status_border_for_job(job, jobs)
    ready = border == STATUS_BORDER_READY
    return ut.queue_job_card_face(selected=False, ready_tint=ready)


def queue_card_idle_border() -> str:
    """Non-pipeline idle ring — ClipCard ``border_card`` in TrueDark."""
    from steempeg.ui import ui_theme as ut

    if ut.get_ui_theme() == ut.UI_THEME_DEFAULT:
        return STATUS_BORDER_IDLE
    _, _, idle = ut.clip_card_chrome()
    return idle

def queue_menu_stylesheet() -> str:
    from steempeg.ui import ui_theme as ut

    return ut.queue_menu_stylesheet()


def status_dot_style(
    color: str,
    *,
    size: int = _STATUS_DOT,
    dense: UiDensity | None = None,
) -> str:
    """Yellow/status queue index circle — same face as Refresh (Segoe bold + footer_font)."""
    font_px = int((dense or COMFORT).footer_font)
    radius = size // 2
    return (
        f"color: #1a1a1a; {_FONT} "
        f"font-weight: bold; font-size: {font_px}px;"
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
    from steempeg.ui.icon_utils import apply_square_icon

    icon_path = job.game_icon_path
    unknown = get_resource_path("unknown_icon.png")
    pix_path = icon_path if icon_path and os.path.exists(icon_path) else unknown
    shaped = None
    if pix_path and os.path.exists(pix_path):
        from steempeg.ui.icon_shape import shaped_game_icon_pixmap

        src = QPixmap(pix_path)
        if not src.isNull():
            shaped = shaped_game_icon_pixmap(src, size)
    apply_square_icon(label, shaped, size)


def build_queue_thumb_strip(
    job: RenderJob,
    *,
    width: int = _LIST_THUMB_W,
    height: int = _LIST_THUMB_H,
    show_game_icon: bool = True,
    cache_dir: str | None = None,
    dense: UiDensity | None = None,
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
    badge.setStyleSheet(status_dot_style(color, dense=dense))
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
