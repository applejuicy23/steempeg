"""Background loader for render-queue history JSON."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from steempeg.render.queue_history import RenderBatchRecord, load_history


class HistoryLoadWorker(QThread):
    """Load render history off the UI thread."""

    finished_ok = Signal(object)  # list[RenderBatchRecord]
    failed = Signal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self) -> None:
        try:
            batches: list[RenderBatchRecord] = load_history(self.path)
            self.finished_ok.emit(batches)
        except Exception as exc:  # noqa: BLE001 — surface to UI status
            self.failed.emit(str(exc))
