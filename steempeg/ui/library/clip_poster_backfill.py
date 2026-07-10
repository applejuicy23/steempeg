"""Background ffmpeg poster generation for clips missing folder thumbnails."""
from __future__ import annotations

import os

from PySide6.QtCore import QThread, Signal

from steempeg.core.clip_thumbnails import (
    clip_poster_cache_path,
    extract_clip_poster_frame,
    find_clip_thumbnail,
)


class ClipPosterBackfillWorker(QThread):
    """Generate missing clip posters one at a time (ffmpeg is heavy)."""

    poster_ready = Signal(str, str)  # clip_path, thumb_path
    finished_batch = Signal()

    def __init__(self, clip_paths: list[str], cache_dir: str, parent=None):
        super().__init__(parent)
        self._clip_paths = list(clip_paths)
        self._cache_dir = cache_dir

    def run(self) -> None:
        for clip_path in self._clip_paths:
            if self.isInterruptionRequested():
                break
            if find_clip_thumbnail(clip_path):
                continue
            cached = clip_poster_cache_path(self._cache_dir, clip_path)
            if os.path.isfile(cached):
                self.poster_ready.emit(clip_path, cached)
                continue
            thumb = extract_clip_poster_frame(clip_path, self._cache_dir)
            if thumb:
                self.poster_ready.emit(clip_path, thumb)
        self.finished_batch.emit()
