"""Background parse of screenshots_library_cache.json — no Qt widgets."""
from __future__ import annotations

import logging
import os
from typing import Any

from PySide6.QtCore import QThread, Signal

from steempeg.library.screenshots_library_cache import (
    files_from_screenshots_library_cache,
)


class ScreenshotsCachePrefetchWorker(QThread):
    """Load + split + sort session screenshot rows off the UI thread.

    Result is plain Python dicts only — never touches grids/tables. The UI
    paints later when the Screenshots tab opens.
    """

    finished_ok = Signal(object)  # dict
    failed = Signal(str)

    def __init__(self, cache_dir: str, folder: str | None = None, parent=None):
        super().__init__(parent)
        self._cache_dir = cache_dir or ""
        self._folder = folder

    def run(self) -> None:
        try:
            rows = files_from_screenshots_library_cache(
                self._cache_dir,
                folder=self._folder,
            )
            steempeg_rows: list[dict[str, Any]] = []
            steam_rows: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                source = str(row.get("source") or "steempeg").strip().lower()
                if source == "steam":
                    steam_rows.append(row)
                else:
                    steempeg_rows.append(row)
            steempeg_rows.sort(
                key=lambda t: float(t.get("mtime") or 0.0), reverse=True
            )
            steam_rows.sort(key=lambda t: float(t.get("mtime") or 0.0), reverse=True)
            payload = {
                "folder": self._folder,
                "steempeg_rows": steempeg_rows,
                "steam_rows": steam_rows,
                "games_catalog": self._build_games_catalog(steempeg_rows, steam_rows),
                "known_count": len(steempeg_rows) + len(steam_rows),
            }
            logging.info(
                "Screenshots cache prefetched off-UI: steempeg=%d steam=%d",
                len(steempeg_rows),
                len(steam_rows),
            )
            self.finished_ok.emit(payload)
        except Exception as exc:  # noqa: BLE001
            logging.debug("Screenshots cache prefetch failed", exc_info=True)
            self.failed.emit(str(exc))

    @staticmethod
    def _build_games_catalog(
        steempeg_rows: list[dict[str, Any]],
        steam_rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Filter-menu catalog without creating Qt widgets."""
        catalog: dict[str, dict[str, Any]] = {}
        for row in steempeg_rows + steam_rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("game_name") or "").strip() or "Unknown"
            app_id = str(row.get("app_id") or "").strip()
            try:
                mtime = float(row.get("mtime") or 0.0)
            except (TypeError, ValueError):
                mtime = 0.0
            rec = catalog.setdefault(
                name, {"app_id": app_id, "count": 0, "max_mtime": 0.0}
            )
            rec["count"] = int(rec.get("count") or 0) + 1
            rec["max_mtime"] = max(float(rec.get("max_mtime") or 0.0), mtime)
            if app_id and not rec.get("app_id"):
                rec["app_id"] = app_id
        return catalog
