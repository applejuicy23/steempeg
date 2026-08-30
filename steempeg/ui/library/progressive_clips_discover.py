"""Shallow clip discovery for Progressive library launch — no ffprobe / DASH walk."""
from __future__ import annotations

import copy
import logging
import os
from typing import Dict, List

from PySide6.QtCore import QThread, Signal

from steempeg.library.clips_library_cache import (
    _lightweight_row_from_path,
    clips_from_library_cache,
)
from steempeg.library.scan import ScannedClip, discover_clip_paths

_BATCH = 64


class ProgressiveClipsDiscoverWorker(QThread):
    """Emit lightweight ScannedClip batches from session cache and/or shallow roots."""

    batch_ready = Signal(object)  # list[ScannedClip]
    finished_ok = Signal(int)  # total rows emitted
    discover_failed = Signal(str)

    def __init__(
        self,
        library_roots: List[str],
        cache_dir: str,
        health_cache: Dict[str, dict],
        game_names_cache: Dict[str, str],
        *,
        prefer_session: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._library_roots = list(library_roots)
        self._cache_dir = cache_dir
        self._health_cache = copy.deepcopy(health_cache or {})
        self._game_names_cache = dict(game_names_cache or {})
        self._prefer_session = bool(prefer_session)

    def run(self) -> None:
        try:
            rows = self._collect_rows()
            total = 0
            batch: list[ScannedClip] = []
            for row in rows:
                if self.isInterruptionRequested():
                    break
                batch.append(row)
                if len(batch) >= _BATCH:
                    self.batch_ready.emit(list(batch))
                    total += len(batch)
                    batch.clear()
            if batch and not self.isInterruptionRequested():
                self.batch_ready.emit(list(batch))
                total += len(batch)
            self.finished_ok.emit(total)
        except Exception as exc:
            logging.exception("Progressive clips discover failed")
            self.discover_failed.emit(str(exc))

    def _collect_rows(self) -> list[ScannedClip]:
        roots = [r for r in self._library_roots if r]
        root_keys = {os.path.normcase(os.path.normpath(r)) for r in roots}
        seen: set[str] = set()
        out: list[ScannedClip] = []

        def _is_library_root(path: str) -> bool:
            return os.path.normcase(os.path.normpath(path)) in root_keys

        if self._prefer_session:
            for row in clips_from_library_cache(
                self._cache_dir,
                library_roots=roots,
                require_exists=False,
            ):
                if _is_library_root(row.full_path):
                    continue
                key = os.path.normcase(row.full_path)
                if key in seen:
                    continue
                seen.add(key)
                out.append(row)

        # Same path filter as Refresh / Full — collect_clip_roots alone would
        # paint the library folder itself as an Unknown/FG card (SteamLibrary).
        try:
            paths, _dupes = discover_clip_paths(roots)
        except OSError:
            paths = []
        for path in paths:
            if self.isInterruptionRequested():
                break
            if _is_library_root(path):
                continue
            key = os.path.normcase(os.path.normpath(path))
            if key in seen:
                continue
            seen.add(key)
            row = _lightweight_row_from_path(
                path,
                cache_dir=self._cache_dir,
                health_cache=self._health_cache,
                game_names_cache=self._game_names_cache,
            )
            if row is not None:
                out.append(row)
        return out
