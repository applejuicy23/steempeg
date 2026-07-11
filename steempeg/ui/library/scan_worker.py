"""Background library scan worker — keeps folder parsing off the GUI thread."""
from __future__ import annotations

import copy
import logging
from typing import Dict, List

from PySide6.QtCore import QThread, Signal

from steempeg.library.scan import ScannedClip, ScanFinishedStats, run_library_scan


class LibraryScanWorker(QThread):
    """Discover clip folders and emit each row as it is parsed."""

    discovering = Signal(int)  # total candidates (0 while still searching)
    clip_ready = Signal(object, int, int)  # ScannedClip, index, total
    finished_scan = Signal(object)  # ScanFinishedStats
    scan_error = Signal(str)

    def __init__(
        self,
        library_roots: List[str],
        cache_dir: str,
        health_cache: Dict[str, dict],
        game_names_cache: Dict[str, str],
        *,
        fast: bool,
        parent=None,
    ):
        super().__init__(parent)
        self._library_roots = list(library_roots)
        self._cache_dir = cache_dir
        self._health_cache = copy.deepcopy(health_cache)
        self._game_names_cache = dict(game_names_cache)
        self._fast = fast
        self._stats: ScanFinishedStats | None = None

    @property
    def health_cache(self) -> Dict[str, dict]:
        return self._health_cache

    @property
    def game_names_cache(self) -> Dict[str, str]:
        return self._game_names_cache

    def run(self) -> None:
        try:
            def on_discovered(total: int) -> None:
                self.discovering.emit(total)

            def on_clip(row: ScannedClip, index: int, total: int) -> None:
                self.clip_ready.emit(row, index, total)

            self._stats = run_library_scan(
                self._library_roots,
                cache_dir=self._cache_dir,
                health_cache=self._health_cache,
                game_names_cache=self._game_names_cache,
                fast=self._fast,
                on_discovered=on_discovered,
                on_clip=on_clip,
                should_cancel=self.isInterruptionRequested,
            )
            self.finished_scan.emit(self._stats)
        except Exception as exc:
            logging.exception("Library scan worker failed")
            self.scan_error.emit(str(exc))
