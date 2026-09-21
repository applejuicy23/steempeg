"""Background parse of rendered_library_cache.json — no Qt widgets."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QThread, Signal

from steempeg.library.rendered_library_cache import files_from_rendered_library_cache


class RenderedCachePrefetchWorker(QThread):
    """Load session Rendered rows off the UI thread (plain list only)."""

    finished_ok = Signal(object)  # list[dict]
    failed = Signal(str)

    def __init__(self, cache_dir: str, parent=None):
        super().__init__(parent)
        self._cache_dir = cache_dir or ""

    def run(self) -> None:
        try:
            files: list[dict[str, Any]] = files_from_rendered_library_cache(
                self._cache_dir,
                require_exists=False,
            )
            logging.info(
                "Rendered cache prefetched off-UI: %d files",
                len(files),
            )
            self.finished_ok.emit(list(files or []))
        except Exception as exc:  # noqa: BLE001
            logging.debug("Rendered cache prefetch failed", exc_info=True)
            self.failed.emit(str(exc))
