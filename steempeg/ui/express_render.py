"""Express render — one-click export of a Steam clip without the full editor.

Recipe rules:
- a saved default or a one-off recipe can override the automatic choice;
- otherwise healthy clips use Original (stream copy unless exact Trim is active);
- clips with Issues / Dead / Cured re-encode at source resolution and bitrate,
  because stream-copying broken chunks keeps the breakage.

Each render runs its own ``RenderThread`` with a private temp folder so it can
run next to a main-window render without the two clobbering temp parts.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from shutil import which

from PySide6.QtCore import QObject, Signal

from steempeg.core.dash import health
from steempeg.render.queue import RenderJob

EXPRESS_PRESET_KEY = "express_last_preset"
AUTO_RECIPE_LABEL = "Original"
MAX_REENCODE_LABEL = "Max quality re-encode"

_PERCENT_RE = re.compile(r"\(([\d.]+)%\)")


@dataclass
class ExpressJob:
    """A ready-to-run Express job plus the recipe name shown to the user."""

    job: RenderJob
    recipe_label: str
    health_report: health.ClipHealthReport
    explicit_destination: bool = False

    @property
    def method_label(self) -> str:
        settings = self.job.settings
        if settings.audio_only:
            return "Audio export"
        if "Original" in settings.quality_text:
            return "Re-encode for exact trim" if settings.is_trim_mode else "Stream copy"
        return "Re-encode"


@dataclass(frozen=True)
class ExpressExportOptions:
    height: int | None
    fps: int | None
    codec: str
    destination: str
    target_mb: int | None = None


def load_express_preset_name(app) -> str:
    """Returns the preset name remembered for Express, or "" for the automatic recipe."""
    try:
        settings = app.load_user_settings() or {}
    except Exception:
        return ""
    return str(settings.get(EXPRESS_PRESET_KEY) or "").strip()


def save_express_preset_name(app, name: str) -> None:
    """Remembers which preset Express should use next time ("" = automatic)."""
    try:
        app.save_user_settings(EXPRESS_PRESET_KEY, (name or "").strip())
    except Exception:
        logging.exception("Express: could not save last preset")


def express_clip_health(app, clip_path: str) -> health.ClipHealthReport:
    try:
        display_report = getattr(app, "get_clip_display_health_report", None)
        return (display_report or app.get_clip_health_report)(clip_path)
    except Exception:
        return health.assess_clip_health(clip_path, probe=False)


def apply_max_reencode(job: RenderJob, *, source_height: int, height: int | None = None) -> None:
    """Switches a job from stream copy to a re-encode at source height and source bitrate."""
    from steempeg.render.quality_presets import format_quality_item

    settings = job.settings
    settings.quality_text = format_quality_item(min(source_height, height or source_height))
    settings.bitrate_text = "Custom"
    settings.custom_vbitrate = float(settings.orig_video_mbps or 0) or 50.0
    settings.output_preset = f"Express: {MAX_REENCODE_LABEL}"


def build_express_job(
    app,
    clip_path: str,
    *,
    preset_name: str | None = None,
    trim_ms: tuple[int, int] | None = None,
    options: ExpressExportOptions | None = None,
) -> ExpressJob | None:
    """Builds the Express render job for a clip folder.

    ``preset_name`` None means "use the remembered Express preset"; "" forces
    the automatic recipe. ``trim_ms`` limits the export to that range.
    """
    from steempeg.render.export_presets import apply_preset_to_job, get_preset_settings
    from steempeg.ui.render_job_builder import (
        build_render_job_from_payload,
        collect_queue_add_payload,
    )

    payload = collect_queue_add_payload(app, clip_path)
    if payload is None:
        return None
    # Clean per-clip defaults: never inherit the main editor's live panel.
    payload.same_preview = False
    payload.settings = None
    payload.clip_memory = {}
    payload.existing_export = None
    if trim_ms is not None and trim_ms[1] > trim_ms[0]:
        payload.trim = {
            "is_trim_mode": True,
            "trim_start_ms": int(trim_ms[0]),
            "trim_end_ms": int(trim_ms[1]),
        }
    else:
        payload.trim = {"is_trim_mode": False, "trim_start_ms": 0, "trim_end_ms": 0}

    job = build_render_job_from_payload(payload)
    if job is None:
        return None

    report = express_clip_health(app, clip_path)
    source = re.search(r"(\d+)p", job.settings.quality_text or "")
    source_height = int(source.group(1)) if source else 1080
    if options is not None:
        apply_max_reencode(job, source_height=source_height, height=options.height)
        settings = job.settings
        settings.output_preset = "Express: Custom settings"
        settings.save_dir = options.destination or settings.save_dir
        settings.codec_text = options.codec
        if options.fps is not None:
            settings.fps_text = "Custom FPS"
            settings.custom_fps = options.fps
        recipe = "Custom settings"
        if options.target_mb is not None:
            from steempeg.render.quality_presets import TARGET_FILE_SIZE_LABEL
            from steempeg.render.target_size import retarget_job_file_size

            settings.quality_text = TARGET_FILE_SIZE_LABEL
            settings.custom_target_mb = options.target_mb
            recipe = "Target File Size"
            settings.output_preset = f"Express: {recipe}"
            if retarget_job_file_size(job) is None:
                return None
        return ExpressJob(job, recipe, report, bool(options.destination))

    name = load_express_preset_name(app) if preset_name is None else preset_name.strip()
    if name:
        preset = get_preset_settings(name, app.load_user_settings)
        if preset is not None:
            from steempeg.ui.preset_compat import preset_settings_for_plan

            preset = preset_settings_for_plan(app, preset, name)
            apply_preset_to_job(job, preset, preset_name=name)
            if report.level != health.ClipHealth.HEALTHY and "Original" in job.settings.quality_text and not job.settings.audio_only:
                apply_max_reencode(job, source_height=source_height)
            return ExpressJob(job, name, report)
        logging.warning("Express: preset %r is gone, using the automatic recipe", name)

    if report.level != health.ClipHealth.HEALTHY:
        apply_max_reencode(job, source_height=source_height)
        return ExpressJob(job, MAX_REENCODE_LABEL, report)
    return ExpressJob(job, AUTO_RECIPE_LABEL, report)


def confirm_express_export(parent, express_job: ExpressJob) -> bool:
    report = express_job.health_report
    if report.level == health.ClipHealth.HEALTHY:
        return True

    from steempeg.infra.paths import get_resource_path
    from steempeg.ui.message_dialog import DialogButton, SteempegMessageDialog

    audio_only = express_job.job.settings.audio_only
    action = "Continue export" if audio_only else "Re-encode and export"
    detail = "Missing audio may still be unrecoverable." if audio_only else (
        "Express will re-encode the video. Missing frames or audio may still be unrecoverable."
    )
    dialog = SteempegMessageDialog(
        f"Clip health · {report.label}",
        "This recording has issues. Joining the original Steam chunks without re-encoding "
        f"can carry those issues into the export. {detail}",
        parent,
        detail="\n".join(report.issues[:3]) or None,
        bar_icon=get_resource_path(health.WARNING_ICON_FILE),
        buttons=(DialogButton("Cancel"), DialogButton(action, "primary", accept=True)),
    )
    return bool(dialog.exec())


class ExpressRender(QObject):
    """Runs one Express job in the background and reports progress."""

    progress_changed = Signal(float)
    finished = Signal(bool, str, str)

    def __init__(self, app, express_job: ExpressJob, parent=None):
        """Keeps the job; call ``start()`` to begin encoding."""
        super().__init__(parent)
        self._app = app
        self._express_job = express_job
        self._thread = None
        self._temp_dir = ""
        self._running = False

    @property
    def clip_path(self) -> str:
        """Returns the source clip folder of this render."""
        return self._express_job.job.clip_path

    @property
    def recipe_label(self) -> str:
        """Returns the recipe name (preset / Original / max re-encode)."""
        return self._express_job.recipe_label

    @property
    def is_running(self) -> bool:
        """Tells whether ffmpeg is still working on this job."""
        return self._running

    def start(self) -> bool:
        """Resolves ffmpeg + output folder and starts the render thread."""
        from steempeg.core.rendered_media import resolve_ffmpeg_exe
        from steempeg.ui.render_job_builder import resolve_render_params
        from steempeg.ui.render_thread import RenderThread
        from steempeg.infra.render_priority import load_render_priority
        from steempeg.ui.settings_prefs import ensure_usable_export_folder

        job = self._express_job.job
        folder, fell_back = ensure_usable_export_folder(job.settings.save_dir or None)
        if fell_back and self._express_job.explicit_destination:
            self.finished.emit(False, "The selected export folder is not writable.", "")
            return False
        job.settings.save_dir = folder
        job.refresh_output_path()

        ffmpeg_exe = resolve_ffmpeg_exe()
        if not os.path.isfile(ffmpeg_exe):
            ffmpeg_exe = which(ffmpeg_exe) or which("ffmpeg") or ""
        if not ffmpeg_exe:
            self.finished.emit(False, "ffmpeg not found", "")
            return False

        from dataclasses import replace
        from steempeg.ui.preset_compat import preset_settings_for_plan

        effective_settings = preset_settings_for_plan(self._app, job.settings, self.recipe_label)
        params = resolve_render_params(replace(job, settings=effective_settings), ffmpeg_exe)
        if params is None:
            self.finished.emit(False, "No playable session.mpd found for this clip.", "")
            return False

        from steempeg.render.gpu_decode import job_uses_nvdec

        gpu_decode = job_uses_nvdec(
            self._app,
            job,
            params.selected_encoder,
            audio_only=params.audio_only,
        )
        self._temp_dir = tempfile.mkdtemp(prefix="steempeg_express_")
        self._thread = RenderThread(
            params.all_mpds,
            params.quality_text,
            params.output_file,
            params.ffmpeg_exe,
            self._temp_dir,
            params.selected_encoder,
            params.video_bitrate,
            params.fps_text,
            params.audio_only,
            params.mute_audio,
            params.audio_format,
            params.audio_bitrate_kbps,
            params.target_scale_h,
            params.trim_start_sec,
            params.trim_duration_sec,
            params.encode_speed,
            rate_control=params.rate_control,
            quality_value=params.quality_value,
            two_pass=params.two_pass,
            ten_bit=params.ten_bit,
            preset=params.preset,
            tune=params.tune,
            keyint_frames=params.keyint_frames,
            gpu_decode=gpu_decode,
            process_priority=load_render_priority(self._app),
        )
        self._thread.progress_signal.connect(self._on_progress)
        self._thread.finished_signal.connect(self._on_finished)
        self._running = True
        logging.info(
            "Express render started: %s -> %s (%s)",
            job.clip_path,
            params.output_file,
            self.recipe_label,
        )
        self._thread.start()
        return True

    def cancel(self) -> None:
        """Stops ffmpeg; ``finished`` fires with a cancelled error."""
        if self._thread is not None and self._running:
            self._thread.cancel()

    def _on_progress(self, message: str) -> None:
        """Turns RenderThread status text into a 0..100 number."""
        match = _PERCENT_RE.search(message or "")
        if match:
            self.progress_changed.emit(float(match.group(1)))
        elif message and message.startswith(("Finalizing", "Merging")):
            self.progress_changed.emit(99.9)

    def _on_finished(self, success: bool, error_msg: str, output_file: str) -> None:
        """Cleans the temp folder, registers the export and re-emits the result."""
        self._running = False
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = ""
        if success and output_file:
            logging.info("Express render done: %s", output_file)
            try:
                self._app._save_render_companion_meta(self._express_job.job, output_file)
            except Exception:
                logging.exception("Express: companion meta save failed")
            try:
                self._app.register_new_rendered_output(output_file)
            except Exception:
                logging.exception("Express: rendered library register failed")
        else:
            logging.warning("Express render failed: %s", error_msg)
        self.finished.emit(bool(success), error_msg or "", output_file or "")
