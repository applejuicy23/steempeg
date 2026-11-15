"""One startup measurement: entry point to the shown, settled initial library."""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel
from steempeg.infra import cache

_FILE = "startup_statistics.json"
_BUSY = ("_startup_settle_active", "_startup_library_scan_active", "_clips_scan_active", "_clips_eager_cards_pending",
         "_rendered_scan_active", "_defer_rendered_scan_until_clips_done",
         "_scan_flush_scheduled", "_scan_pending_rows", "_scan_finalize_pending",
         "_pending_rendered_restore_files", "_rendered_restore_chunk_scheduled",
         "_progressive_clips_worker", "_screenshots_prefetch_worker",
         "_history_preload_running")


def read_startup_statistics(cache_dir) -> dict:
    if not cache_dir:
        return {}
    data = cache.read_json(os.path.join(cache_dir, _FILE))
    return data if isinstance(data, dict) else {}


def valid_sample(sample) -> bool:
    return (isinstance(sample, dict) and isinstance(sample.get("seconds"), (int, float))
            and isinstance(sample.get("mode"), str)
            and sample["mode"] in ("progressive", "quick", "full", "cache")
            and sample.get("status", "ready") == "ready"
            and math.isfinite(sample["seconds"]) and 0 <= sample["seconds"] < 86400)


class StartupMeasurement(QObject):
    def __init__(self, app, started: float, *, clock=time.perf_counter):
        super().__init__(app.ui)
        self.app, self.started, self.clock = app, started, clock
        self.shown = None
        self.ready_since = None
        self.result = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)

    def window_shown(self):
        if self.shown is None:
            self.shown = self.clock() - self.started
        self.timer.start()

    def poll(self):
        if self.result is not None:
            self.timer.stop()
            return
        if self.shown is None:
            return
        now = self.clock()
        if getattr(self.app, "_startup_metrics_failed", False):
            self.result = dict(status="failed", seconds=round(now - self.started, 3))
            self.app._startup_metrics_current = self.result
            self.timer.stop()
            return
        if any(getattr(self.app, flag, False) for flag in _BUSY):
            self.ready_since = None
            return
        if self.ready_since is None:
            self.ready_since = now
            return
        # Observe a quiet event-loop interval, including the first viewport pass.
        if now - self.ready_since < .2:
            return
        mode = getattr(self.app, "_startup_scan_mode", "progressive")
        self.result = dict(mode=mode, status="ready", seconds=round(now - self.started, 3),
                           window_seconds=round(self.shown, 3),
                           recorded_at=datetime.now(timezone.utc).isoformat())
        self.app._startup_metrics_current = self.result
        self.timer.stop()
        logging.info("Startup measured: mode=%s ready=%.3fs window=%.3fs",
                     mode, self.result["seconds"], self.shown)
        folder = getattr(self.app, "cache_dir", None)
        if folder:
            result = dict(self.result)
            def persist():
                data = read_startup_statistics(folder)
                modes = data.get("modes")
                modes = dict(modes) if isinstance(modes, dict) else {}
                modes[mode] = result
                cache.write_json(os.path.join(folder, _FILE),
                                 dict(schema=1, last=result, modes=modes))
            threading.Thread(target=persist, name="startup-statistics", daemon=True).start()


class StartupTimeLabel(QLabel):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._saved = read_startup_statistics(getattr(app, "cache_dir", None))
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self):
        from steempeg.ui.widgets.startup_mode_guide import MODES
        current = getattr(self._app, "_startup_metrics_current", None)
        measurement = getattr(self._app, "_startup_measurement", None)
        sample = current or self._saved.get("last")
        if measurement is not None and current is None:
            self.setText("Startup time: measuring…")
        elif valid_sample(sample):
            name = MODES.get(sample.get("mode"), (str(sample.get("mode", "")),))[0]
            self.setText(f"{'This' if current else 'Last'} launch: {name} · {sample['seconds']:.2f} s")
        elif isinstance(current, dict) and current.get("status") == "failed":
            self.setText("Startup time: startup did not complete")
        else:
            self.setText("Startup time: available after the next launch")
        lines = ["From app entry to a shown, settled window and the initial library being ready.",
                 "Deferred Progressive cards, thumbnails and network refreshes are excluded."]
        modes = self._saved.get("modes") or {}
        if not isinstance(modes, dict):
            modes = {}
        modes = dict(modes)
        if valid_sample(current):
            modes[current["mode"]] = current
        for key, (name, _speed, _description) in MODES.items():
            if valid_sample(modes.get(key)):
                lines.append(f"{name}: {modes[key]['seconds']:.2f} s (last measured)")
        self.setToolTip("\n".join(lines))

    def showEvent(self, event):  # noqa: N802
        self.refresh(); self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)
