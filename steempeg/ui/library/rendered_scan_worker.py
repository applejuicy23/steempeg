"""Background rendered-library scan worker."""
from __future__ import annotations

import copy
import logging
from typing import Dict, List

from PySide6.QtCore import QThread, Signal

from steempeg.library.rendered_scan import RenderedScanStats, ScannedRenderedFile, run_rendered_scan


class RenderedScanWorker(QThread):
    """Discover rendered files and emit each row as it is parsed."""

    discovering = Signal(int)  # total candidates (0 while still searching)
    file_ready = Signal(object, int, int)  # ScannedRenderedFile, index, total
    finished_scan = Signal(object)  # RenderedScanStats
    scan_error = Signal(str)

    def __init__(
        self,
        scan_roots: List[str],
        meta_index: Dict[str, dict],
        cache_dir: str,
        game_names_cache: Dict[str, str],
        parent=None,
    ):
        super().__init__(parent)
        self._scan_roots = list(scan_roots)
        self._meta_index = copy.deepcopy(meta_index)
        self._cache_dir = cache_dir
        self._game_names_cache = dict(game_names_cache)
        self._stats: RenderedScanStats | None = None

    @property
    def game_names_cache(self) -> Dict[str, str]:
        return self._game_names_cache

    def run(self) -> None:
        try:
            def on_discovered(total: int) -> None:
                self.discovering.emit(total)

            def on_file(row: ScannedRenderedFile, index: int, total: int) -> None:
                self.file_ready.emit(row, index, total)

            self._stats = run_rendered_scan(
                self._scan_roots,
                self._meta_index,
                self._cache_dir,
                self._game_names_cache,
                on_discovered=on_discovered,
                on_file=on_file,
                should_cancel=self.isInterruptionRequested,
            )
            self.finished_scan.emit(self._stats)
        except Exception as exc:
            logging.exception("Rendered scan worker failed")
            self.scan_error.emit(str(exc))
