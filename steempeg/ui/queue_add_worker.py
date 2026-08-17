"""Build a render-queue job off the UI thread (MPD walk / probe)."""
from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal


class QueueAddWorker(QThread):
    """Turn a UI-thread payload into a ``RenderJob`` without blocking the sheet."""

    finished_ok = Signal(object)  # RenderJob
    failed = Signal(str)

    def __init__(self, payload, parent=None):
        super().__init__(parent)
        self._payload = payload

    def run(self) -> None:
        try:
            from steempeg.ui.render_job_builder import build_render_job_from_payload

            job = build_render_job_from_payload(self._payload)
            if job is None:
                self.failed.emit("Could not add clip to the queue.")
                return
            self.finished_ok.emit(job)
        except Exception as exc:  # noqa: BLE001 — surface to UI log
            logging.exception("Queue add worker failed")
            self.failed.emit(str(exc))
