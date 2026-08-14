"""Background Steam userdata screenshot walk for the unified Screenshots shelf."""
from __future__ import annotations

from typing import Dict

from PySide6.QtCore import QThread, Signal

from steempeg.core import games


class SteamScreenshotsScanWorker(QThread):
    """Walk Steam userdata off the UI thread; emit row batches for incremental paint.

    Resolves game names from the shared ``games.json`` cache + local appmanifests
    once per unique app id (no network here — backfill runs after the scan).
    """

    batch_ready = Signal(list)  # list[dict] with path/mtime/steam_id/app_id/game_name
    scan_failed = Signal(str)
    finished_ok = Signal(int)  # total rows emitted

    def __init__(
        self,
        *,
        game_names_cache: Dict[str, str] | None = None,
        batch_size: int = 250,
        parent=None,
    ):
        super().__init__(parent)
        self._batch_size = max(50, int(batch_size) or 250)
        self._game_names_cache: Dict[str, str] = dict(game_names_cache or {})
        self._resolved_names: Dict[str, str] = {}

    @property
    def game_names_cache(self) -> Dict[str, str]:
        """Cache snapshot including any local names discovered during the walk."""
        merged = dict(self._game_names_cache)
        merged.update(self._resolved_names)
        return merged

    def _name_for_app_id(self, app_id: str) -> str:
        aid = str(app_id or "").strip()
        if not aid:
            return "Unknown"
        if aid in self._resolved_names:
            return self._resolved_names[aid]
        if aid in self._game_names_cache:
            name = str(self._game_names_cache[aid] or "").strip()
            if name and not games.is_unresolved_game_name(name, aid):
                self._resolved_names[aid] = name
                return name
        local = games.find_local_steam_game_name(aid)
        if local:
            self._resolved_names[aid] = local
            return local
        return f"App {aid}"

    def run(self) -> None:
        try:
            from steempeg.core.steam_screenshots import iter_steam_library_screenshots

            entries = iter_steam_library_screenshots()
        except Exception as exc:
            self.scan_failed.emit(str(exc))
            self.finished_ok.emit(0)
            return

        if self.isInterruptionRequested():
            self.finished_ok.emit(0)
            return

        # Resolve unique app ids once before painting batches.
        seen_ids: set[str] = set()
        for entry in entries:
            if self.isInterruptionRequested():
                break
            aid = str(entry.get("app_id") or "").strip()
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                self._name_for_app_id(aid)

        if self.isInterruptionRequested():
            self.finished_ok.emit(0)
            return

        total = 0
        batch: list[dict] = []
        for entry in entries:
            if self.isInterruptionRequested():
                break
            path = str(entry.get("path") or "")
            if not path:
                continue
            row = dict(entry)
            aid = str(row.get("app_id") or "").strip()
            row["game_name"] = self._name_for_app_id(aid) if aid else "Unknown"
            batch.append(row)
            if len(batch) >= self._batch_size:
                total += len(batch)
                self.batch_ready.emit(batch)
                batch = []
        if batch and not self.isInterruptionRequested():
            total += len(batch)
            self.batch_ready.emit(batch)
        self.finished_ok.emit(total)
