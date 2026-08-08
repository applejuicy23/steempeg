"""Background thumbnail generation for Screenshots library cards."""
from __future__ import annotations

import os

from PySide6.QtCore import QRect, Qt, QThread, Signal
from PySide6.QtGui import QImage

from steempeg.library.screenshots_library_cache import (
    THUMB_JPEG_QUALITY,
    THUMB_MAX_H,
    THUMB_MAX_W,
    screenshot_thumb_path,
)


def _make_screenshot_thumb(source: QImage) -> QImage:
    """Cover-scale + center-crop to the cache size (sharp on HiDPI cards)."""
    if source.isNull():
        return QImage()
    # Prefer a high-quality format before the expensive scale.
    img = source
    if img.format() not in (
        QImage.Format.Format_RGB32,
        QImage.Format.Format_ARGB32,
        QImage.Format.Format_ARGB32_Premultiplied,
    ):
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    scaled = img.scaled(
        THUMB_MAX_W,
        THUMB_MAX_H,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    if scaled.isNull():
        return QImage()
    if scaled.width() == THUMB_MAX_W and scaled.height() == THUMB_MAX_H:
        return scaled
    x = max(0, (scaled.width() - THUMB_MAX_W) // 2)
    y = max(0, (scaled.height() - THUMB_MAX_H) // 2)
    return scaled.copy(QRect(x, y, THUMB_MAX_W, THUMB_MAX_H))


class ScreenshotThumbBackfillWorker(QThread):
    """Generate missing screenshot thumbs one at a time."""

    thumb_ready = Signal(str, str)  # file_path, thumb_path
    finished_batch = Signal()

    def __init__(
        self,
        entries: list[tuple[str, float]],
        cache_dir: str,
        parent=None,
    ):
        super().__init__(parent)
        self._entries = list(entries)
        self._cache_dir = cache_dir

    def run(self) -> None:
        for file_path, mtime in self._entries:
            if self.isInterruptionRequested():
                break
            try:
                out = screenshot_thumb_path(self._cache_dir, file_path, mtime)
                if os.path.isfile(out) and os.path.getsize(out) > 0:
                    self.thumb_ready.emit(file_path, out)
                    continue
                img = QImage(file_path)
                if img.isNull():
                    continue
                scaled = _make_screenshot_thumb(img)
                if scaled.isNull() or not scaled.save(out, "JPG", THUMB_JPEG_QUALITY):
                    continue
                self.thumb_ready.emit(file_path, out)
            except Exception:
                continue
        self.finished_batch.emit()
