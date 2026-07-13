"""Background ffmpeg poster generation for rendered video files."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from steempeg.core.rendered_media import extract_poster_frame


class RenderedPosterBackfillWorker(QThread):
    """Generate missing rendered video posters one at a time."""

    poster_ready = Signal(str, str)  # file_path, thumb_path
    finished_batch = Signal()

    def __init__(self, file_paths: list[str], cache_dir: str, parent=None):
        super().__init__(parent)
        self._file_paths = list(file_paths)
        self._cache_dir = cache_dir

    def run(self) -> None:
        for file_path in self._file_paths:
            if self.isInterruptionRequested():
                break
            thumb = extract_poster_frame(file_path, self._cache_dir)
            if thumb:
                self.poster_ready.emit(file_path, thumb)
        self.finished_batch.emit()
