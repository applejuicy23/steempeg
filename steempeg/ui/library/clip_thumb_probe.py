"""Background Steam/cache thumb probe for Progressive — no ffmpeg, no UI I/O."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QThread, Signal

from steempeg.core.clip_thumbnails import (
    find_clip_thumbnail_fast,
    probe_clip_poster_cache,
)


class ClipThumbProbeWorker(QThread):
    """Resolve folder ``thumbnail.jpg`` / poster cache off the UI thread."""

    thumb_ready = Signal(str, str)  # clip_path, thumb_path
    finished_batch = Signal()

    def __init__(self, clip_paths: list[str], cache_dir: str, parent=None):
        super().__init__(parent)
        self._clip_paths = list(clip_paths)
        self._cache_dir = cache_dir or ""

    def run(self) -> None:
        for clip_path in self._clip_paths:
            if self.isInterruptionRequested():
                break
            thumb = find_clip_thumbnail_fast(clip_path)
            if not thumb and self._cache_dir:
                thumb = probe_clip_poster_cache(self._cache_dir, clip_path)
            if thumb and os.path.isfile(thumb):
                self.thumb_ready.emit(clip_path, thumb)
            # Yield so marquees keep ticking while we touch a cold library drive.
            if self.isInterruptionRequested():
                break
            time.sleep(0.02)
        self.finished_batch.emit()
