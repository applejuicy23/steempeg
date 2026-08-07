"""Background thumbnail generation for Screenshots library cards."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage

from steempeg.library.screenshots_library_cache import screenshot_thumb_path


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
                scaled = img.scaled(
                    160,
                    90,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if scaled.isNull() or not scaled.save(out, "JPG", 82):
                    continue
                self.thumb_ready.emit(file_path, out)
            except Exception:
                continue
        self.finished_batch.emit()
