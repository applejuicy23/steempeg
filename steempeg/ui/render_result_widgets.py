"""Shared header and library-style export cards for render completion windows."""
from __future__ import annotations

import os
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from steempeg.ui.pro_appearance import accent_qcolor

from steempeg.core.clip_thumbnails import resolve_clip_thumbnail_ui_safe
from steempeg.infra.paths import get_resource_path
from steempeg.render.queue import JobStatus
from steempeg.render.queue_display import format_job_output, format_job_preset, format_job_trim
from steempeg.ui import design_tokens as tok, ui_theme as ut
from steempeg.ui.icon_assets import tinted_pixmap
from steempeg.ui.queue_card_shared import set_game_icon_label
from steempeg.ui.widgets import ElidedLabel


def _label(text, size=12, *, bold=False, elided=False):
    label = ElidedLabel(text) if elided else QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setFont(tok.ui_qfont(pixel_size=size, weight=QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
    label.setStyleSheet("background: transparent; border: none;")
    return label


def format_render_elapsed(seconds):
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return ""
    if seconds < 1:
        return f"{seconds:.1f} s"
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02}m {secs:02}s"
    return f"{minutes}m {secs:02}s" if minutes else f"{secs} s"


class ResultHeader(QWidget):
    def __init__(self, title, summary, *, success=True, elapsed_seconds=None):
        super().__init__()
        self.setObjectName("renderResultHeader")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)
        self.mascot = QLabel()
        self.mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mascot.setFixedSize(100, 104)
        pixmap = QPixmap(get_resource_path("chupisuccess.png" if success else "saderror.png"))
        if not pixmap.isNull():
            self.mascot.setPixmap(pixmap.scaled(100, 104, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        self.mascot.setStyleSheet("background: transparent; border: none;")
        text = QVBoxLayout()
        text.setSpacing(6)
        text.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.heading = _label(title, 18, bold=True)
        self.heading.setWordWrap(True)
        self.summary = _label(summary, 13)
        self.summary.setWordWrap(True)
        text.addWidget(self.heading)
        elapsed = format_render_elapsed(elapsed_seconds)
        self.elapsed = _label(f"Render time: {elapsed}" if elapsed else "", 13, bold=True)
        self.elapsed.setVisible(bool(elapsed))
        text.addWidget(self.elapsed)
        text.addWidget(self.summary)
        row.addWidget(self.mascot)
        row.addLayout(text, 1)
        self.apply_theme()

    def apply_theme(self):
        self.heading.setStyleSheet(f"background: transparent; color: {tok.TEXT_TITLE}; border: none;")
        self.elapsed.setStyleSheet("background: transparent; color: #bda4f0; border: none;")
        self.summary.setStyleSheet(f"background: transparent; color: {tok.TEXT_MUTED}; border: none;")


class _ExportPreview(QWidget):
    def __init__(self, job, cache_dir, extension):
        super().__init__()
        self.setFixedSize(152, 86)
        path = resolve_clip_thumbnail_ui_safe(job.clip_path, cache_dir)
        self.pixmap = QPixmap(path) if path else QPixmap()
        self.fallback = QPixmap(job.game_icon_path) if job.game_icon_path else QPixmap()
        self.extension = extension.upper() or "VIDEO"

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()), 9, 9)
        painter.setClipPath(shape)
        painter.fillRect(self.rect(), QColor(ut.active_palette().bg_settings_panel))
        if not self.pixmap.isNull():
            size = self.pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            painter.drawPixmap((self.width()-size.width())//2, (self.height()-size.height())//2,
                               self.pixmap.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
        elif not self.fallback.isNull():
            image = self.fallback.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            painter.setOpacity(.55)
            painter.drawPixmap((self.width()-image.width())//2, (self.height()-image.height())//2, image)
            painter.setOpacity(1)
        painter.setFont(tok.ui_qfont(pixel_size=10, weight=QFont.Weight.Bold))
        width = painter.fontMetrics().horizontalAdvance(self.extension) + 12
        chip = QRectF(self.width()-width-6, self.height()-23, width, 17)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent_qcolor(QColor("#b29ae7")))
        painter.drawRoundedRect(chip, 4, 4)
        painter.setPen(QColor("#16121d"))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, self.extension)


class ExportResultCard(QFrame):
    def __init__(self, job, *, output_file=None, cache_dir=None, status=None):
        super().__init__()
        self.setObjectName("exportResultCard")
        self.status = status or job.status
        self.output_path = output_file or job.output_file or format_job_output(job)
        self.file_exists = bool(self.output_path and os.path.isfile(self.output_path))
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 12, 12, 12)
        self.body.setSpacing(10)
        main = QHBoxLayout()
        main.setSpacing(14)
        self.preview = _ExportPreview(job, cache_dir, os.path.splitext(self.output_path)[1].lstrip("."))
        main.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        icon = QLabel()
        set_game_icon_label(icon, job, size=22)
        self.name = _label(job.game_name.strip() or os.path.basename(job.clip_path or "Clip"), 14, bold=True, elided=True)
        title_row.addWidget(icon)
        title_row.addWidget(self.name, 1)
        self.badge = QFrame()
        self.badge.setObjectName("exportStatus")
        badge_row = QHBoxLayout(self.badge)
        badge_row.setContentsMargins(7, 4, 7, 4)
        badge_row.setSpacing(4)
        self.success = self.status == JobStatus.COMPLETED
        self.failed = self.status == JobStatus.ERROR
        self._status_color = "#94dc83" if self.success else "#ff9999" if self.failed else "#b0aab8"
        mark = QLabel()
        mark.setFixedSize(12, 12)
        mark.setPixmap(tinted_pixmap("success.png" if self.success else "cancel.png" if self.failed else "info.png",
                                     self._status_color, 12))
        self.status_label = _label(self.status.value.capitalize(), 11, bold=True)
        badge_row.addWidget(mark)
        badge_row.addWidget(self.status_label)
        title_row.addWidget(self.badge)
        text.addLayout(title_row)
        self.preset = _label(format_job_preset(job.settings).replace(" · ", " | "), 12, elided=True)
        text.addWidget(self.preset)
        trim = format_job_trim(job.settings)
        self.range = _label(trim.removeprefix("✂️ "), 12, elided=True)
        range_row = QHBoxLayout()
        range_row.setSpacing(5)
        self.range_icon = QLabel()
        self.range_icon.setFixedSize(14, 14)
        self.range_icon.setPixmap(QPixmap(get_resource_path("trim_icon.png")).scaled(
            14, 14, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.range_icon.setStyleSheet("background: transparent; border: none;")
        self.range_icon.setVisible(trim != "Full clip")
        range_row.addWidget(self.range_icon)
        range_row.addWidget(self.range, 1)
        text.addLayout(range_row)
        self.date = _label(" at ".join(p for p in (job.clip_date, job.clip_time) if p), 11, elided=True)
        self.date.setVisible(bool(self.date.text()))
        text.addWidget(self.date)
        text.addStretch(1)
        main.addLayout(text, 1)
        self.body.addLayout(main)
        suffix = "" if self.file_exists or not self.output_path else "  |  File unavailable"
        self.path = _label(self.output_path + suffix, 11, elided=True)
        self.path.setToolTip(self.output_path)
        self.body.addWidget(self.path)
        self.error = None
        if job.error_message and self.status == JobStatus.ERROR:
            self.error = _label(job.error_message.splitlines()[0], 12, elided=True)
            self.error.setToolTip(job.error_message)
            self.body.addWidget(self.error)
        self.apply_theme()

    def apply_theme(self):
        palette = ut.active_palette()
        self.setStyleSheet(f"QFrame#exportResultCard {{background: {palette.bg_elevated}; "
                          f"border: 1px solid {palette.border_card}; border-radius: 12px;}}")
        for label in (self.name,):
            label.setStyleSheet(f"background: transparent; border: none; color: {tok.TEXT_TITLE};")
        for label in (self.preset, self.date, self.path):
            label.setStyleSheet(f"background: transparent; border: none; color: {tok.TEXT_MUTED};")
        self.range.setStyleSheet("background: transparent; border: none; color: #bda4f0;")
        color = self._status_color
        bg = "rgba(91, 164, 75, 28)" if self.success else "rgba(195, 68, 68, 28)" if self.failed else "rgba(130, 120, 150, 28)"
        self.badge.setStyleSheet(f"QFrame#exportStatus {{background: {bg}; border: none; border-radius: 8px;}}")
        self.status_label.setStyleSheet(f"background: transparent; border: none; color: {color};")
        if self.error is not None:
            self.error.setStyleSheet("background: transparent; border: none; color: #ff9999;")
        self.preview.update()
