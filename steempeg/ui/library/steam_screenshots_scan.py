"""Background Steam userdata screenshot walk for the unified Screenshots shelf."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class SteamScreenshotsScanWorker(QThread):
    """Walk Steam userdata off the UI thread; emit row batches for incremental paint."""

    batch_ready = Signal(list)  # list[dict] with path/mtime/steam_id/app_id
    scan_failed = Signal(str)
    finished_ok = Signal(int)  # total rows emitted

    def __init__(self, *, batch_size: int = 250, parent=None):
        super().__init__(parent)
        self._batch_size = max(50, int(batch_size) or 250)

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

        total = 0
        batch: list[dict] = []
        for entry in entries:
            if self.isInterruptionRequested():
                break
            path = str(entry.get("path") or "")
            if not path:
                continue
            batch.append(dict(entry))
            if len(batch) >= self._batch_size:
                total += len(batch)
                self.batch_ready.emit(batch)
                batch = []
        if batch and not self.isInterruptionRequested():
            total += len(batch)
            self.batch_ready.emit(batch)
        self.finished_ok.emit(total)
