"""Background size estimate for Steempeg PRO constant quality (CRF / CQ).

The Detailed Summary asks ``size_text`` on every refresh. A cache miss schedules
a debounced probe (``render.cq_size_probe``) on a worker thread; when it lands
the summary is refreshed and reads the cached bitrate.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from steempeg.core.dash import mpd as dash_mpd
from steempeg.core.rendered_media import resolve_ffmpeg_exe
from steempeg.render.cq_size_probe import measure_video_mbps
from steempeg.render.queue import RenderJob
from steempeg.ui.render_pro_controls import read_pro_state

_log = logging.getLogger(__name__)

_DEBOUNCE_MS = 700
ESTIMATING = "Estimating…"
UNKNOWN = "Varies (constant quality)"


def _estimate_key(app) -> tuple | None:
    clip = getattr(app, "_preview_clip_path", None)
    if not clip:
        return None
    ui = app.ui
    tl = getattr(app, "custom_timeline", None)
    trim = (
        (int(tl.trim_start_ms), int(tl.trim_end_ms))
        if tl is not None and tl.is_trim_mode
        else None
    )
    state = read_pro_state(app)
    return (
        os.path.normpath(clip),
        trim,
        ui.combo_quality.currentText(),
        ui.combo_fps.currentText(),
        state.encoder,
        state.quality,
        state.preset,
        state.tune,
        state.ten_bit,
        state.keyint_sec,
        str(ui.combo_encode_speed.currentData() or "") if hasattr(ui, "combo_encode_speed") else "",
    )


class CqSizeEstimator(QObject):
    _done = Signal(object, object)

    def __init__(self, app):
        super().__init__(app if isinstance(app, QObject) else None)
        self._app = app
        self._cache: dict[tuple, float | None] = {}
        self._pending: tuple | None = None
        self._running: tuple | None = None
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._start)
        self._done.connect(self._on_done)

    def size_text(self, duration_sec: float, audio_mbps: float, format_mb) -> str:
        """``~42.0 MB (estimated)`` from the cache, else schedule a probe."""
        if getattr(self._app, "_is_rendering", False):
            return UNKNOWN
        key = _estimate_key(self._app)
        if key is None or duration_sec <= 0:
            return UNKNOWN
        if key in self._cache:
            mbps = self._cache[key]
            if mbps is None:
                return UNKNOWN
            return f"{format_mb((mbps + audio_mbps) * duration_sec / 8)} (estimated)"
        if key != self._running:
            self._pending = key
            self._timer.start()
        return ESTIMATING

    def _start(self) -> None:
        key = self._pending
        self._pending = None
        if key is None or key in self._cache:
            return
        if self._running is not None:
            self._cancel.set()
            proc = self._proc
            if proc is not None:
                try:
                    proc.kill()
                except OSError:
                    pass
        job_args = self._probe_inputs(key)
        if job_args is None:
            self._running = None
            self._cache[key] = None
            self._refresh()
            return
        self._cancel = threading.Event()
        self._running = key
        cancel = self._cancel
        threading.Thread(
            target=self._work, args=(key, cancel, *job_args), daemon=True
        ).start()

    def _probe_inputs(self, key: tuple):
        from steempeg.ui.render_job_builder import resolve_render_params, snapshot_settings_from_ui

        app = self._app
        try:
            settings = snapshot_settings_from_ui(app)
            job = RenderJob(
                clip_path=key[0],
                game_name="",
                clip_date="",
                clip_time="",
                game_icon_path="",
                settings=settings,
                output_file=os.path.join(settings.save_dir or ".", "cq_probe.mkv"),
            )
            params = resolve_render_params(job, resolve_ffmpeg_exe())
        except Exception:
            _log.exception("CQ size estimate: could not resolve render params")
            return None
        if params is None or not params.all_mpds:
            return None
        mpd_path = params.all_mpds[0]
        if params.trim_duration_sec > 0:
            start, length = max(0.0, params.trim_start_sec), params.trim_duration_sec
        else:
            start, length = 0.0, dash_mpd.estimate_render_duration_sec(mpd_path)
        if length <= 0:
            return None
        return params, mpd_path, start, length

    def _set_proc(self, proc) -> None:
        self._proc = proc

    def _work(self, key, cancel, params, mpd_path, start, length) -> None:
        try:
            mbps = measure_video_mbps(
                params,
                mpd_path,
                start,
                length,
                on_process=self._set_proc,
                cancelled=cancel.is_set,
            )
        except Exception:
            _log.exception("CQ size estimate failed")
            mbps = None
        if cancel.is_set():
            return
        self._done.emit(key, mbps)

    def _on_done(self, key, mbps) -> None:
        if key != self._running:
            return
        self._running = None
        self._cache[key] = mbps
        _log.info("CQ size estimate: %s Mbps for %s", f"{mbps:.2f}" if mbps else "-", key[0])
        self._refresh()

    def _refresh(self) -> None:
        if hasattr(self._app, "update_final_setup"):
            self._app.update_final_setup()


def cq_size_text(app, duration_sec: float, audio_mbps: float) -> str:
    est = getattr(app, "_cq_size_estimator", None)
    if est is None:
        est = app._cq_size_estimator = CqSizeEstimator(app)
    return est.size_text(duration_sec, audio_mbps, app._format_size_mb)
