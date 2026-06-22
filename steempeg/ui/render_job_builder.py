"""Build and resolve render jobs from the live settings UI."""
from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt

from steempeg.core.dash import discovery
from steempeg.infra.paths import get_save_directory
from steempeg.render.queue import (
    RenderJob,
    RenderJobSettings,
    ResolvedRenderParams,
    compute_unique_output_path,
    game_icon_path_for_clip,
)


def _set_combo_text(combo, text: str) -> None:
    if not combo or not text:
        return
    idx = combo.findText(text)
    if idx >= 0:
        combo.setCurrentIndex(idx)


def apply_job_settings_to_ui(app: SteempegApp, settings: RenderJobSettings) -> None:
    """Restore a job's saved settings into the live settings panel."""
    ui = app.ui
    app.custom_target_bitrate = settings.custom_target_bitrate
    app.custom_target_height = settings.custom_target_height
    app.current_orig_fps = settings.orig_fps
    app.current_orig_bitrate = settings.orig_video_mbps
    app.current_orig_audio_bitrate = settings.orig_audio_kbps

    if settings.save_dir:
        app.custom_destination = settings.save_dir
        if hasattr(ui, "destination_button"):
            ui.destination_button.setText(f"Destination: {settings.save_dir}")

    blockers = []
    for name in (
        "combo_quality",
        "combo_fps",
        "combo_bitrate",
        "combo_codec",
        "combo_encoder",
        "combo_audio_format",
        "combo_audio_bitrate",
        "check_audio_only",
        "check_mute_audio",
        "input_filename",
    ):
        w = getattr(ui, name, None)
        if w is not None and hasattr(w, "blockSignals"):
            w.blockSignals(True)
            blockers.append(w)

    if hasattr(ui, "combo_quality") and settings.quality_text:
        _set_combo_text(ui.combo_quality, settings.quality_text)
        if hasattr(app, "on_quality_mode_changed"):
            app.on_quality_mode_changed(settings.quality_text)
        if hasattr(app, "update_bitrate_options"):
            app.update_bitrate_options()

    if hasattr(ui, "combo_fps") and settings.fps_text:
        _set_combo_text(ui.combo_fps, settings.fps_text)
    if hasattr(ui, "combo_bitrate") and settings.bitrate_text:
        _set_combo_text(ui.combo_bitrate, settings.bitrate_text)
    if hasattr(ui, "combo_codec") and settings.codec_text:
        _set_combo_text(ui.combo_codec, settings.codec_text)

    if hasattr(ui, "combo_encoder") and settings.encoder_codec:
        matched = False
        for i in range(ui.combo_encoder.count()):
            data = ui.combo_encoder.itemData(i, Qt.UserRole)
            if data and str(data) == settings.encoder_codec:
                ui.combo_encoder.setCurrentIndex(i)
                matched = True
                break
        if not matched and settings.encoder_display:
            _set_combo_text(ui.combo_encoder, settings.encoder_display)

    if hasattr(ui, "check_audio_only"):
        ui.check_audio_only.setChecked(settings.audio_only)
    if hasattr(ui, "check_mute_audio"):
        ui.check_mute_audio.setChecked(settings.mute_audio)
    if hasattr(ui, "combo_audio_format") and settings.audio_format:
        _set_combo_text(ui.combo_audio_format, settings.audio_format)
    if hasattr(ui, "combo_audio_bitrate") and settings.audio_bitrate_text:
        _set_combo_text(ui.combo_audio_bitrate, settings.audio_bitrate_text)
    if hasattr(ui, "input_filename") and settings.output_basename:
        ui.input_filename.setText(settings.output_basename)

    if hasattr(ui, "size_slider"):
        ui.size_slider.setValue(settings.size_slider_index)

    if settings.custom_fps is not None and hasattr(app, "input_custom_fps"):
        app.input_custom_fps.setText(str(settings.custom_fps))
    if settings.custom_vbitrate is not None and hasattr(app, "input_custom_vbitrate"):
        app.input_custom_vbitrate.setText(str(settings.custom_vbitrate))
    if settings.custom_abitrate is not None and hasattr(app, "input_custom_abitrate"):
        app.input_custom_abitrate.setText(str(settings.custom_abitrate))

    for w in blockers:
        w.blockSignals(False)

if TYPE_CHECKING:
    from steempeg.app import SteempegApp


def find_clip_metadata(app: SteempegApp, clip_path: str) -> Optional[dict]:
    if not hasattr(app.ui, "table_clips"):
        return None
    norm = os.path.normpath(clip_path)
    table = app.ui.table_clips
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is None:
            continue
        row_path = item.data(Qt.UserRole)
        if row_path and os.path.normpath(row_path) == norm:
            date_item = table.item(row, 2)
            time_item = table.item(row, 3)
            return {
                "game_name": item.text(),
                "clip_date": date_item.text() if date_item else "",
                "clip_time": time_item.text() if time_item else "",
            }
    return None


def snapshot_settings_from_ui(app: SteempegApp) -> RenderJobSettings:
    ui = app.ui
    quality = ui.combo_quality.currentText() if hasattr(ui, "combo_quality") else ""
    fps = ui.combo_fps.currentText() if hasattr(ui, "combo_fps") else ""
    bitrate = ui.combo_bitrate.currentText() if hasattr(ui, "combo_bitrate") else ""
    codec_raw = ui.combo_codec.currentText() if hasattr(ui, "combo_codec") else ""
    encoder_display = ui.combo_encoder.currentText() if hasattr(ui, "combo_encoder") else ""
    encoder_codec = (
        ui.combo_encoder.currentData(Qt.UserRole) if hasattr(ui, "combo_encoder") else "libx264"
    )
    if hasattr(ui, "combo_codec") and "H.265" in ui.combo_codec.currentText():
        encoder_codec = (
            str(encoder_codec).replace("h264", "hevc").replace("libx264", "libx265")
        )

    audio_only = ui.check_audio_only.isChecked() if hasattr(ui, "check_audio_only") else False
    mute_audio = ui.check_mute_audio.isChecked() if hasattr(ui, "check_mute_audio") else False
    audio_format = ui.combo_audio_format.currentText() if hasattr(ui, "combo_audio_format") else "AAC"
    audio_bitrate = (
        ui.combo_audio_bitrate.currentText() if hasattr(ui, "combo_audio_bitrate") else "192 kbps"
    )

    save_dir = app.custom_destination if app.custom_destination else get_save_directory()
    output_basename = ui.input_filename.text().strip() if hasattr(ui, "input_filename") else "rendered"

    trim_start_ms = 0
    trim_end_ms = 0
    is_trim_mode = False
    if hasattr(app, "custom_timeline") and app.custom_timeline.is_trim_mode:
        is_trim_mode = True
        trim_start_ms = int(app.custom_timeline.trim_start_ms)
        trim_end_ms = int(app.custom_timeline.trim_end_ms)

    size_slider_index = 0
    if hasattr(ui, "size_slider") and ui.size_slider.isVisible():
        size_slider_index = ui.size_slider.value()

    custom_fps = None
    if "Custom" in fps and hasattr(app, "input_custom_fps"):
        try:
            custom_fps = int(app.input_custom_fps.text().strip())
        except ValueError:
            pass

    custom_vbitrate = None
    if "Custom" in bitrate and hasattr(app, "input_custom_vbitrate"):
        try:
            custom_vbitrate = float(app.input_custom_vbitrate.text().replace(",", ".").strip())
        except ValueError:
            pass

    custom_abitrate = None
    if "Custom" in audio_bitrate and hasattr(app, "input_custom_abitrate"):
        try:
            custom_abitrate = int(app.input_custom_abitrate.text().strip())
        except ValueError:
            pass

    return RenderJobSettings(
        quality_text=quality,
        fps_text=fps,
        bitrate_text=bitrate,
        codec_text=codec_raw,
        encoder_codec=str(encoder_codec),
        encoder_display=encoder_display,
        audio_only=audio_only,
        mute_audio=mute_audio,
        audio_format=audio_format,
        audio_bitrate_text=audio_bitrate,
        output_basename=output_basename,
        save_dir=save_dir,
        trim_start_ms=trim_start_ms,
        trim_end_ms=trim_end_ms,
        is_trim_mode=is_trim_mode,
        custom_target_bitrate=int(getattr(app, "custom_target_bitrate", 1500)),
        custom_target_height=int(getattr(app, "custom_target_height", -1)),
        size_slider_index=size_slider_index,
        custom_fps=custom_fps,
        custom_vbitrate=custom_vbitrate,
        custom_abitrate=custom_abitrate,
        orig_fps=int(getattr(app, "current_orig_fps", 60)),
        orig_video_mbps=float(getattr(app, "current_orig_bitrate", 0.0)),
        orig_audio_kbps=int(getattr(app, "current_orig_audio_bitrate", 192)),
    )


def _output_basename_for_clip(app: SteempegApp, clip_path: str, settings: RenderJobSettings) -> str:
    clip_folder = os.path.basename(clip_path)
    default_name = f"{clip_folder}_rendered"

    if not hasattr(app.ui, "table_clips") or app.ui.table_clips.currentRow() < 0:
        return default_name

    row = app.ui.table_clips.currentRow()
    current_path = app.ui.table_clips.item(row, 0).data(Qt.UserRole)
    if current_path and os.path.normpath(current_path) == os.path.normpath(clip_path):
        return settings.output_basename or default_name
    return default_name


def build_render_job_from_ui(app: SteempegApp, clip_path: str) -> Optional[RenderJob]:
    """Snapshot the current settings panel into a queue job for ``clip_path``."""
    clip_path = os.path.normpath(clip_path)
    if not os.path.isdir(clip_path):
        logging.warning("build_render_job_from_ui: not a clip folder: %s", clip_path)
        return None

    mpds = discovery.find_mpd_paths(clip_path)
    if not mpds:
        logging.warning("build_render_job_from_ui: no MPD for %s", clip_path)
        return None

    meta = find_clip_metadata(app, clip_path) or {}
    settings = snapshot_settings_from_ui(app)
    settings.output_basename = _output_basename_for_clip(app, clip_path, settings)

    icon_path = game_icon_path_for_clip(app.cache_dir, clip_path)
    if not icon_path or not os.path.exists(icon_path):
        icon_path = getattr(app, "current_game_icon", "") or icon_path

    job = RenderJob(
        clip_path=clip_path,
        game_name=meta.get("game_name") or os.path.basename(clip_path),
        clip_date=meta.get("clip_date", ""),
        clip_time=meta.get("clip_time", ""),
        game_icon_path=icon_path,
        settings=settings,
    )
    job.refresh_output_path()
    return job


def resolve_render_params(job: RenderJob, ffmpeg_exe: str) -> Optional[ResolvedRenderParams]:
    """Turn a job's stored settings into RenderThread arguments."""
    s = job.settings
    all_mpds = discovery.find_mpd_paths(job.clip_path)
    if not all_mpds:
        return None

    output_file = job.output_file or job.refresh_output_path()

    quality_text = s.quality_text
    fps_text = s.fps_text
    bitrate_text = s.bitrate_text
    selected_encoder = s.encoder_codec

    trim_start_sec = -1.0
    trim_duration_sec = -1.0
    if s.is_trim_mode and s.trim_end_ms > s.trim_start_ms:
        trim_start_sec = s.trim_start_ms / 1000.0
        trim_duration_sec = (s.trim_end_ms - s.trim_start_ms) / 1000.0

    orig_fps = s.orig_fps or 60
    max_allowed_fps = min(60, orig_fps)
    fps_multiplier = 1.0

    if "Custom" in fps_text:
        try:
            val = s.custom_fps if s.custom_fps is not None else max_allowed_fps
            val = max(1, min(val, max_allowed_fps))
            fps_text = f"{val} FPS"
            fps_multiplier = val / orig_fps if orig_fps > 0 else 1.0
        except (TypeError, ValueError):
            fps_text = f"{max_allowed_fps} FPS"
    else:
        try:
            selected_fps = int(re.search(r"(\d+)", fps_text).group(1))
            fps_multiplier = selected_fps / orig_fps if orig_fps > 0 else 1.0
        except (AttributeError, ValueError):
            pass

    video_bitrate = "12M"
    orig_v_bitrate = s.orig_video_mbps or 10.0
    target_scale_h = -1

    if "Target File Size" in quality_text:
        video_bitrate = f"{s.custom_target_bitrate}k"
        target_scale_h = s.custom_target_height
    elif "Custom" in bitrate_text:
        try:
            val = s.custom_vbitrate if s.custom_vbitrate is not None else orig_v_bitrate
            val = max(0.1, min(float(val), orig_v_bitrate))
            final_bitrate = int(val * fps_multiplier * 1000)
            final_bitrate = max(final_bitrate, 100)
            video_bitrate = f"{final_bitrate}k"
        except (TypeError, ValueError):
            final_bitrate = max(int(orig_v_bitrate * fps_multiplier * 1000), 100)
            video_bitrate = f"{final_bitrate}k"
    elif "Original" not in bitrate_text:
        match = re.search(r"-\s*([\d.]+)\s*Mbps", bitrate_text)
        if match:
            final_bitrate = max(int(float(match.group(1)) * 1000), 100)
            video_bitrate = f"{final_bitrate}k"

    orig_a_bitrate = s.orig_audio_kbps or 192
    audio_bitrate_kbps = "192k"
    if "Custom" in s.audio_bitrate_text:
        try:
            val = s.custom_abitrate if s.custom_abitrate is not None else orig_a_bitrate
            val = max(1, min(int(val), orig_a_bitrate))
            audio_bitrate_kbps = f"{val}k"
        except (TypeError, ValueError):
            audio_bitrate_kbps = f"{orig_a_bitrate}k"
    elif s.audio_bitrate_text:
        audio_bitrate_kbps = s.audio_bitrate_text.split(" ")[0] + "k"

    return ResolvedRenderParams(
        all_mpds=all_mpds,
        quality_text=quality_text,
        output_file=output_file,
        ffmpeg_exe=ffmpeg_exe,
        save_dir=s.save_dir,
        selected_encoder=selected_encoder,
        video_bitrate=video_bitrate,
        fps_text=fps_text,
        audio_only=s.audio_only,
        mute_audio=s.mute_audio,
        audio_format=s.audio_format,
        audio_bitrate_kbps=audio_bitrate_kbps,
        target_scale_h=target_scale_h,
        trim_start_sec=trim_start_sec,
        trim_duration_sec=trim_duration_sec,
    )
