"""Background workers for Refresh ▾ extras (health recheck, Steam icons/names).

These used to run on the GUI thread with WaitCursor and froze the shell —
especially Portable when the Clips sheet was open.
"""
from __future__ import annotations

import copy
import logging
import os
from typing import Dict, List, Tuple

from PySide6.QtCore import QThread, Signal

from steempeg.core import games
from steempeg.core.dash import health
from steempeg.library.scan import _resolve_clip_health


class ClipHealthRecheckWorker(QThread):
    """Full ffprobe health pass for listed DASH clip folders."""

    progress = Signal(int, int)  # done, total
    finished_recheck = Signal(object)  # payload dict
    failed = Signal(str)

    def __init__(
        self,
        clip_paths: List[str],
        health_cache: Dict[str, dict],
        parent=None,
    ):
        super().__init__(parent)
        self._clip_paths = list(clip_paths)
        self._health_cache = copy.deepcopy(health_cache)

    @property
    def health_cache(self) -> Dict[str, dict]:
        return self._health_cache

    def run(self) -> None:
        try:
            results: Dict[str, Tuple[str, List[str]]] = {}
            counts = {
                health.ClipHealth.HEALTHY.value: 0,
                health.ClipHealth.DEGRADED.value: 0,
                health.ClipHealth.DEAD.value: 0,
                health.ClipHealth.CURED.value: 0,
            }
            total = len(self._clip_paths)
            for i, path in enumerate(self._clip_paths):
                if self.isInterruptionRequested():
                    break
                report = _resolve_clip_health(
                    path, self._health_cache, fast=False, force=True
                )
                level = report.level.value
                results[os.path.normpath(path)] = (level, list(report.issues))
                counts[level] = counts.get(level, 0) + 1
                self.progress.emit(i + 1, total)

            self.finished_recheck.emit(
                {
                    "results": results,
                    "counts": counts,
                    "checked": len(results),
                    "health_cache": self._health_cache,
                }
            )
        except Exception as exc:
            logging.exception("Clip health recheck worker failed")
            self.failed.emit(str(exc))


class SteamIconsRefreshWorker(QThread):
    """Re-download game icons from Steam CDN for the given app ids."""

    progress = Signal(int, int)
    finished_icons = Signal(object)  # {"updated": int, "total": int, "app_ids": [...]}
    failed = Signal(str)

    def __init__(self, app_ids: List[str], cache_dir: str, parent=None):
        super().__init__(parent)
        self._app_ids = list(app_ids)
        self._cache_dir = cache_dir

    def run(self) -> None:
        try:
            updated = 0
            total = len(self._app_ids)
            for i, app_id in enumerate(self._app_ids):
                if self.isInterruptionRequested():
                    break
                icon_path = os.path.join(self._cache_dir, f"{app_id}.jpg")
                try:
                    if os.path.isfile(icon_path):
                        os.remove(icon_path)
                except OSError:
                    pass
                if games.download_icon(app_id, icon_path):
                    updated += 1
                self.progress.emit(i + 1, total)
            self.finished_icons.emit(
                {
                    "updated": updated,
                    "total": total,
                    "app_ids": list(self._app_ids),
                }
            )
        except Exception as exc:
            logging.exception("Steam icons refresh worker failed")
            self.failed.emit(str(exc))


class SteamNamesRefreshWorker(QThread):
    """Re-fetch game display names from the Steam store API."""

    progress = Signal(int, int)
    finished_names = Signal(object)  # {"updated": int, "total": int, "names": {id: name}}
    failed = Signal(str)

    def __init__(self, app_ids: List[str], parent=None):
        super().__init__(parent)
        self._app_ids = list(app_ids)

    def run(self) -> None:
        try:
            names: Dict[str, str] = {}
            updated = 0
            total = len(self._app_ids)
            for i, app_id in enumerate(self._app_ids):
                if self.isInterruptionRequested():
                    break
                name = games.fetch_game_name(app_id)
                if name:
                    names[app_id] = name
                    updated += 1
                self.progress.emit(i + 1, total)
            self.finished_names.emit(
                {
                    "updated": updated,
                    "total": total,
                    "names": names,
                }
            )
        except Exception as exc:
            logging.exception("Steam names refresh worker failed")
            self.failed.emit(str(exc))
