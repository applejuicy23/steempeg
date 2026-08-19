"""Build and resolve render jobs from the live settings UI."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt

from steempeg.core.dash import discovery, mpd
from steempeg.core import capabilities
from steempeg.render.bitrate import format_video_mbps
from steempeg.render.encode_speed import normalize_encode_speed
from steempeg.ui.settings_prefs import resolve_app_export_folder
from steempeg.render.output_formats import resolve_video_encoder
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


def apply_job_settings_to_ui(
    app: SteempegApp,
    settings: RenderJobSettings,
    *,
    refresh_summary: bool = True,
) -> None:
    """Restore a job's saved settings into the live settings panel.

    When ``refresh_summary`` is True (default), runs one ``update_final_setup`` at
    the end. Bulk apply blocks combo signals so Apply-preset does not fire the
    summary rebuild once per field.
    """
    ui = app.ui
    app.custom_target_bitrate = settings.custom_target_bitrate
    app.custom_target_height = settings.custom_target_height
    app.current_orig_fps = settings.orig_fps
    app.current_orig_bitrate = settings.orig_video_mbps
    app.current_orig_audio_bitrate = settings.orig_audio_kbps

    if settings.save_dir:
        app.custom_destination = settings.save_dir
        # Keep the button's static label; the destination path is shown in the Output line.

    prev_bulk = bool(getattr(app, "_bulk_settings_apply", False))
    app._bulk_settings_apply = True

    blockers = []
    try:
        for name in (
            "combo_quality",
            "combo_fps",
            "combo_bitrate",
            "combo_codec",
            "combo_encoder",
            "combo_encode_speed",
            "combo_audio_format",
            "combo_audio_bitrate",
            "combo_container",
            "combo_output_preset",
            "check_audio_only",
            "check_mute_audio",
            "input_filename",
            "size_slider",
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
            saved = str(settings.encoder_codec)
            # Don't re-apply a stale CPU choice when NVENC/AMF/QSV is available —
            # old sessions defaulted to libx264 and kept restoring it on every launch.
            hw_available = any(
                not capabilities.is_software_encoder(
                    str(ui.combo_encoder.itemData(i, Qt.UserRole) or "")
                )
                for i in range(ui.combo_encoder.count())
            )
            if capabilities.is_software_encoder(saved) and hw_available:
                pass  # keep the HW default from detect_gpu_and_set_encoder
            else:
                matched = False
                for i in range(ui.combo_encoder.count()):
                    data = ui.combo_encoder.itemData(i, Qt.UserRole)
                    if data and str(data) == saved:
                        ui.combo_encoder.setCurrentIndex(i)
                        matched = True
                        break
                if not matched and settings.encoder_display:
                    _set_combo_text(ui.combo_encoder, settings.encoder_display)

        if hasattr(app, "refresh_encode_speed_options"):
            app.refresh_encode_speed_options(settings.encode_speed)
        elif hasattr(ui, "combo_encode_speed") and settings.encode_speed:
            idx = ui.combo_encode_speed.findData(
                normalize_encode_speed(settings.encode_speed), Qt.UserRole
            )
            if idx >= 0:
                ui.combo_encode_speed.setCurrentIndex(idx)

        if hasattr(ui, "check_audio_only"):
            ui.check_audio_only.setChecked(settings.audio_only)
        if hasattr(ui, "check_mute_audio"):
            ui.check_mute_audio.setChecked(settings.mute_audio)
        if hasattr(ui, "combo_audio_format") and settings.audio_format:
            _set_combo_text(ui.combo_audio_format, settings.audio_format)
        if hasattr(ui, "combo_audio_bitrate") and settings.audio_bitrate_text:
            _set_combo_text(ui.combo_audio_bitrate, settings.audio_bitrate_text)
        if hasattr(ui, "combo_container") and settings.container_format:
            _set_combo_text(ui.combo_container, settings.container_format)
        if hasattr(ui, "combo_output_preset") and settings.output_preset:
            # User presets are not Share/Edit/Web entries — keep Custom in the mux combo.
            preset_label = settings.output_preset
            if preset_label.startswith("User:"):
                preset_label = "Custom"
            _set_combo_text(ui.combo_output_preset, preset_label)
        if hasattr(ui, "input_filename") and settings.output_basename:
            ui.input_filename.setText(settings.output_basename)

        if hasattr(ui, "size_slider"):
            ui.size_slider.setValue(settings.size_slider_index)

        fps_custom = "Custom" in (settings.fps_text or "")
        if hasattr(app, "input_custom_fps"):
            if fps_custom and settings.custom_fps is not None:
                app.input_custom_fps.setText(str(settings.custom_fps))
            else:
                app.input_custom_fps.clear()

        br_custom = "Custom" in (settings.bitrate_text or "")
        if hasattr(app, "input_custom_vbitrate"):
            if br_custom and settings.custom_vbitrate is not None:
                app.input_custom_vbitrate.setText(str(settings.custom_vbitrate))
            else:
                app.input_custom_vbitrate.clear()

        ab_custom = "Custom" in (settings.audio_bitrate_text or "")
        if hasattr(app, "input_custom_abitrate"):
            if ab_custom and settings.custom_abitrate is not None:
                app.input_custom_abitrate.setText(str(settings.custom_abitrate))
            else:
                app.input_custom_abitrate.clear()

        # Refresh Custom overlays without emitting currentTextChanged (that used to
        # rebuild the Export summary once per combo — felt like a multi-second hitch).
        sync_custom_combo_overlays(app, emit=False)

        if hasattr(app, "_sync_original_audio_controls"):
            app._sync_original_audio_controls()
    finally:
        for w in blockers:
            w.blockSignals(False)
        app._bulk_settings_apply = prev_bulk

    if refresh_summary and hasattr(app, "update_final_setup"):
        app.update_final_setup()


def sync_custom_combo_overlays(app, *, emit: bool = True) -> None:
    """Refresh custom FPS/bitrate overlay visibility after programmatic combo changes."""
    from PySide6.QtWidgets import QFrame

    ui = app.ui
    pairs = (
        ("combo_fps", "input_custom_fps", "validate_custom_fps", "warn_fps"),
        ("combo_bitrate", "input_custom_vbitrate", "validate_custom_vbitrate", "warn_vbitrate"),
        (
            "combo_audio_bitrate",
            "input_custom_abitrate",
            "validate_custom_abitrate",
            "warn_abitrate",
        ),
    )
    for combo_name, input_attr, validate_attr, warn_attr in pairs:
        combo = getattr(ui, combo_name, None)
        if combo is None:
            continue
        text = combo.currentText()
        if emit:
            combo.currentTextChanged.emit(text)
            if "Custom" in text:
                edit = getattr(ui, input_attr, None)
                validate = getattr(app, validate_attr, None)
                if edit is not None and validate is not None:
                    validate(edit.text())
            continue

        is_custom = "Custom" in (text or "")
        for overlay in combo.findChildren(QFrame, "customOverlay"):
            if is_custom:
                pos = getattr(overlay, "_positioner", None)
                if pos is not None:
                    pos.reposition()
                overlay.show()
                overlay.raise_()
            else:
                overlay.hide()
        warn = getattr(ui, warn_attr, None)
        if warn is not None and not is_custom:
            warn.hide()
        if is_custom:
            edit = getattr(ui, input_attr, None)
            validate = getattr(app, validate_attr, None)
            if edit is not None and validate is not None:
                validate(edit.text())


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
            # Col 2 = ``date\\ntime``; col 3 = duration (not clock time).
            date_item = table.item(row, 2)
            dur_item = table.item(row, 3)
            from steempeg.ui.player_header_layout import split_clip_date_cell

            date_part, time_part = split_clip_date_cell(
                date_item.text() if date_item else ""
            )
            return {
                "game_name": item.text(),
                "clip_date": date_part,
                "clip_time": time_part,
                "duration_label": (dur_item.text() if dur_item else "").strip(),
            }
    return None


def _salvage_mpd_paths(clip_path: str) -> list[str]:
    """Find ``session_salvage.mpd`` trees without touching Qt."""
    mpds: list[str] = []
    if not os.path.isdir(clip_path):
        return mpds
    for root, _dirs, files in os.walk(clip_path):
        if "session_salvage.mpd" in files:
            mpds.append(os.path.join(root, "session_salvage.mpd"))
    return sorted(mpds)


def _mpd_paths_for_clip(app: SteempegApp, clip_path: str) -> list[str]:
    """Resolve manifests for a clip, including cured/salvage manifests."""
    clip_path = os.path.normpath(clip_path)
    if hasattr(app, "_register_salvaged_clip") and hasattr(app, "_is_clip_cured"):
        try:
            if app._is_clip_cured(clip_path):
                app._register_salvaged_clip(clip_path)
        except Exception:
            pass
    mpds = discovery.find_mpd_paths(clip_path)
    if mpds:
        return mpds
    salvage = list(getattr(app, "_salvaged_clips", {}).get(clip_path, []))
    if salvage:
        return salvage
    return _salvage_mpd_paths(clip_path)


def _ui_encoder_snapshot(app: SteempegApp) -> tuple[str, str, str]:
    """Live encoder combo → (codec, display, encode_speed). Used for non-preview queue jobs."""
    ui = app.ui
    codec_raw = ui.combo_codec.currentText() if hasattr(ui, "combo_codec") else ""
    encoder_display = ui.combo_encoder.currentText() if hasattr(ui, "combo_encoder") else ""
    encoder_codec = (
        ui.combo_encoder.currentData(Qt.UserRole) if hasattr(ui, "combo_encoder") else "libx264"
    )
    encoder_codec = resolve_video_encoder(
        codec_raw,
        str(encoder_codec or "libx264"),
        capabilities.av1_encoder_available(),
    )
    encode_speed = "balanced"
    if hasattr(ui, "combo_encode_speed"):
        data = ui.combo_encode_speed.currentData(Qt.UserRole)
        if data:
            encode_speed = normalize_encode_speed(str(data))
    return str(encoder_codec), str(encoder_display or ""), encode_speed


def probe_clip_render_defaults(
    clip_path: str,
    app: SteempegApp | None = None,
    *,
    mpds: list[str] | None = None,
    allow_ffprobe: bool = True,
) -> dict:
    """Per-clip Original preset strings from MPD (for queue add without preview).

    Queue-add passes ``allow_ffprobe=False`` so we never spawn ffprobe on the UI
    thread — FPS/bitrate come from MPD text only.
    """
    clip_path = os.path.normpath(clip_path)
    if mpds is None:
        if app is not None:
            mpds = _mpd_paths_for_clip(app, clip_path)
        else:
            mpds = discovery.find_mpd_paths(clip_path)
    if not mpds:
        return {
            "orig_fps": 60,
            "orig_video_mbps": 0.0,
            "orig_audio_kbps": 192,
            "quality_text": "Original (Lossless)",
            "fps_text": "60 FPS (Original)",
            "bitrate_text": "Unknown Mbps (Original)",
            "duration_label": "",
        }

    orig_fps = 60
    orig_video_mbps = 0.0
    max_height = 0
    orig_audio_kbps = 192
    duration_label = ""

    for mpd_path in mpds:
        try:
            with open(mpd_path, encoding="utf-8") as handle:
                content = handle.read()
            if not duration_label:
                seconds = discovery.parse_duration_seconds(content)
                if seconds is not None and seconds > 0:
                    total = int(seconds)
                    minutes, secs = divmod(total, 60)
                    hours, minutes = divmod(minutes, 60)
                    if hours:
                        duration_label = f"{hours}h {minutes}m"
                    elif minutes:
                        duration_label = f"{minutes}m {secs}s"
                    else:
                        duration_label = f"{secs}s"
            fps_match = re.search(r'\bframeRate="(\d+)(?:/\d+)?"', content)
            if fps_match:
                orig_fps = int(fps_match.group(1))
            elif allow_ffprobe:
                probed = mpd.get_fps(mpd_path)
                if probed:
                    orig_fps = int(probed)
            if allow_ffprobe:
                peak = mpd.get_video_bitrate_mbps(mpd_path)
            else:
                # Bandwidth attrs only — no disk walk / ffprobe on the UI path.
                bws = [
                    int(b)
                    for b in re.findall(
                        r'mimeType="video/[^"]*"[^>]*\bbandwidth="(\d+)"', content
                    )
                ]
                if not bws:
                    bws = [int(b) for b in re.findall(r'\bbandwidth="(\d+)"', content)]
                peak = (max(bws) / 1_000_000.0) if bws else 0.0
            if peak > orig_video_mbps:
                orig_video_mbps = peak
            height_match = re.search(r'\bheight="(\d+)"', content)
            if height_match:
                max_height = max(max_height, int(height_match.group(1)))
        except OSError:
            pass

    if allow_ffprobe:
        ab = mpd.get_audio_bitrate_kbps(mpds[0])
        if ab:
            orig_audio_kbps = int(ab)
    else:
        try:
            with open(mpds[0], encoding="utf-8") as handle:
                content = handle.read()
            ab_match = re.search(
                r'mimeType="audio/[^"]*"[^>]*\bbandwidth="(\d+)"', content
            )
            if ab_match:
                orig_audio_kbps = max(64, int(int(ab_match.group(1)) / 1000))
        except OSError:
            pass

    quality_text = (
        f"Original (Lossless, {max_height}p)" if max_height > 0 else "Original (Lossless)"
    )
    fps_text = f"{orig_fps} FPS (Original)"
    if orig_video_mbps > 0:
        bitrate_text = f"{format_video_mbps(orig_video_mbps)} (Original)"
    else:
        bitrate_text = "Unknown Mbps (Original)"

    return {
        "orig_fps": orig_fps,
        "orig_video_mbps": orig_video_mbps,
        "orig_audio_kbps": orig_audio_kbps,
        "quality_text": quality_text,
        "fps_text": fps_text,
        "bitrate_text": bitrate_text,
        "duration_label": duration_label,
    }


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
    encoder_codec = resolve_video_encoder(
        codec_raw,
        str(encoder_codec),
        capabilities.av1_encoder_available(),
    )

    container_format = (
        ui.combo_container.currentText() if hasattr(ui, "combo_container") else "MP4"
    )
    output_preset = (
        ui.combo_output_preset.currentText() if hasattr(ui, "combo_output_preset") else "Custom"
    )

    audio_only = ui.check_audio_only.isChecked() if hasattr(ui, "check_audio_only") else False
    mute_audio = ui.check_mute_audio.isChecked() if hasattr(ui, "check_mute_audio") else False
    audio_format = ui.combo_audio_format.currentText() if hasattr(ui, "combo_audio_format") else "AAC"
    audio_bitrate = (
        ui.combo_audio_bitrate.currentText() if hasattr(ui, "combo_audio_bitrate") else "192 kbps"
    )

    save_dir = resolve_app_export_folder(app, notify=False)
    output_basename = ui.input_filename.text().strip() if hasattr(ui, "input_filename") else "rendered"

    trim_start_ms = 0
    trim_end_ms = 0
    is_trim_mode = False
    preview = getattr(app, "_preview_clip_path", None)
    if (
        preview
        and hasattr(app, "custom_timeline")
        and app.custom_timeline.is_trim_mode
    ):
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

    encode_speed = "balanced"
    if hasattr(ui, "combo_encode_speed"):
        data = ui.combo_encode_speed.currentData(Qt.UserRole)
        if data:
            encode_speed = normalize_encode_speed(str(data))

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
        container_format=container_format or "MP4",
        output_preset=output_preset or "Custom",
        encode_speed=encode_speed,
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


def apply_per_clip_export_to_settings(
    app: SteempegApp, clip_path: str, settings: RenderJobSettings
) -> None:
    """When queueing a clip that is not being previewed, use its own export memory."""
    clip_norm = os.path.normpath(clip_path)
    preview = getattr(app, "_preview_clip_path", None)
    if preview and os.path.normpath(preview) == clip_norm:
        return

    memory = getattr(app, "_clip_session_memory", {}).get(clip_norm, {})
    if memory:
        settings.container_format = memory.get("container", "MP4")
        settings.codec_text = memory.get("codec_text", "H.264 (AVC)")
        settings.audio_format = memory.get("audio_format", "AAC")
        settings.output_preset = memory.get("output_preset", "Custom")
        settings.audio_only = bool(memory.get("audio_only", False))
        settings.mute_audio = bool(memory.get("mute_audio", False))
        return

    job = app.render_queue.find_by_clip_path(clip_path) if hasattr(app, "render_queue") else None
    if job:
        s = job.settings
        settings.container_format = s.container_format or "MP4"
        settings.codec_text = s.codec_text
        settings.audio_format = s.audio_format
        settings.output_preset = s.output_preset or "Custom"
        settings.audio_only = bool(s.audio_only)
        settings.mute_audio = bool(s.mute_audio)
        return

    settings.container_format = "MP4"
    settings.codec_text = "H.264 (AVC)"
    settings.audio_format = "AAC"
    settings.output_preset = "Custom"
    settings.audio_only = False
    settings.mute_audio = False


@dataclass
class QueueAddPayload:
    """UI-thread snapshot so MPD walk / probe can run off the GUI thread."""

    clip_path: str
    same_preview: bool
    settings: Optional[RenderJobSettings]
    encoder_codec: str
    encoder_display: str
    encode_speed: str
    meta: dict[str, Any]
    cache_dir: str
    current_game_icon: str
    is_cured: bool
    salvage_mpds: list[str]
    trim: dict[str, Any]
    clip_memory: dict[str, Any]
    existing_export: Optional[dict[str, Any]]
    output_basename: str
    save_dir: str


def collect_queue_add_payload(
    app: SteempegApp, clip_path: str
) -> Optional[QueueAddPayload]:
    """Read widgets / tables only. Safe to call from the UI thread."""
    clip_path = os.path.normpath(clip_path)
    if not os.path.isdir(clip_path):
        logging.warning("build_render_job_from_ui: not a clip folder: %s", clip_path)
        return None

    is_cured = False
    if hasattr(app, "_is_clip_cured"):
        try:
            is_cured = bool(app._is_clip_cured(clip_path))
        except Exception:
            is_cured = False

    salvage_mpds = list(getattr(app, "_salvaged_clips", {}).get(clip_path, []) or [])
    meta = find_clip_metadata(app, clip_path) or {}
    preview = getattr(app, "_preview_clip_path", None)
    same_preview = bool(preview and os.path.normpath(preview) == clip_path)
    enc_codec, enc_display, enc_speed = _ui_encoder_snapshot(app)

    settings = snapshot_settings_from_ui(app) if same_preview else None
    save_dir = ""
    if settings is not None:
        save_dir = str(settings.save_dir or "")
    if not save_dir:
        save_dir = resolve_app_export_folder(app, notify=False)

    trim = {"is_trim_mode": False, "trim_start_ms": 0, "trim_end_ms": 0}
    if not same_preview and hasattr(app, "_trim_state_for_clip"):
        try:
            trim = dict(app._trim_state_for_clip(clip_path) or {})
        except Exception:
            pass

    clip_memory = dict(
        getattr(app, "_clip_session_memory", {}).get(clip_path, {}) or {}
    )
    existing_export = None
    if not same_preview and not clip_memory and hasattr(app, "render_queue"):
        existing = app.render_queue.find_by_clip_path(clip_path)
        if existing is not None:
            s = existing.settings
            existing_export = {
                "container_format": s.container_format or "MP4",
                "codec_text": s.codec_text,
                "audio_format": s.audio_format,
                "output_preset": s.output_preset or "Custom",
                "audio_only": bool(s.audio_only),
                "mute_audio": bool(s.mute_audio),
            }

    basename_src = settings or RenderJobSettings(
        output_basename=(
            app.ui.input_filename.text().strip()
            if hasattr(app.ui, "input_filename")
            else "rendered"
        )
    )
    output_basename = _output_basename_for_clip(app, clip_path, basename_src)

    return QueueAddPayload(
        clip_path=clip_path,
        same_preview=same_preview,
        settings=settings,
        encoder_codec=enc_codec,
        encoder_display=enc_display,
        encode_speed=enc_speed,
        meta=dict(meta),
        cache_dir=str(getattr(app, "cache_dir", "") or ""),
        current_game_icon=str(getattr(app, "current_game_icon", "") or ""),
        is_cured=is_cured,
        salvage_mpds=salvage_mpds,
        trim=trim,
        clip_memory=clip_memory,
        existing_export=existing_export,
        output_basename=output_basename,
        save_dir=save_dir,
    )


def _apply_export_memory_to_settings(
    settings: RenderJobSettings,
    *,
    clip_memory: dict[str, Any],
    existing_export: Optional[dict[str, Any]],
) -> None:
    if clip_memory:
        settings.container_format = clip_memory.get("container", "MP4")
        settings.codec_text = clip_memory.get("codec_text", "H.264 (AVC)")
        settings.audio_format = clip_memory.get("audio_format", "AAC")
        settings.output_preset = clip_memory.get("output_preset", "Custom")
        settings.audio_only = bool(clip_memory.get("audio_only", False))
        settings.mute_audio = bool(clip_memory.get("mute_audio", False))
        return
    if not existing_export:
        return
    settings.container_format = existing_export.get("container_format") or "MP4"
    settings.codec_text = existing_export.get("codec_text") or settings.codec_text
    settings.audio_format = existing_export.get("audio_format") or settings.audio_format
    settings.output_preset = existing_export.get("output_preset") or "Custom"
    settings.audio_only = bool(existing_export.get("audio_only", False))
    settings.mute_audio = bool(existing_export.get("mute_audio", False))


def _duration_label_from_mpd(mpd_path: str) -> str:
    try:
        with open(mpd_path, encoding="utf-8") as handle:
            content = handle.read()
        seconds = discovery.parse_duration_seconds(content)
        if seconds is None or seconds <= 0:
            return ""
        total = int(seconds)
        minutes, secs = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {secs}s"
        return f"{secs}s"
    except OSError:
        return ""


def build_render_job_from_payload(payload: QueueAddPayload) -> Optional[RenderJob]:
    """MPD walk / probe / job assemble — no Qt widgets (worker-safe)."""
    clip_path = payload.clip_path
    real_mpds = discovery.find_mpd_paths(clip_path)
    salvage_mpds = list(payload.salvage_mpds)
    if not real_mpds:
        if payload.is_cured:
            found = _salvage_mpd_paths(clip_path)
            if found:
                salvage_mpds = found
        mpds = salvage_mpds
    else:
        mpds = real_mpds
        salvage_mpds = []
    if not mpds:
        logging.warning("build_render_job_from_ui: no MPD for %s", clip_path)
        return None

    meta = payload.meta or {}
    duration_label = str(meta.get("duration_label") or "")
    if payload.same_preview and payload.settings is not None:
        settings = payload.settings
    else:
        defaults = probe_clip_render_defaults(
            clip_path, app=None, mpds=mpds, allow_ffprobe=False
        )
        settings = RenderJobSettings(
            quality_text=defaults["quality_text"],
            fps_text=defaults["fps_text"],
            bitrate_text=defaults["bitrate_text"],
            orig_fps=int(defaults["orig_fps"]),
            orig_video_mbps=float(defaults["orig_video_mbps"]),
            orig_audio_kbps=int(defaults["orig_audio_kbps"]),
            save_dir=payload.save_dir,
            encoder_codec=payload.encoder_codec,
            encoder_display=payload.encoder_display,
            encode_speed=payload.encode_speed,
        )
        _apply_export_memory_to_settings(
            settings,
            clip_memory=payload.clip_memory,
            existing_export=payload.existing_export,
        )
        settings.encoder_codec = payload.encoder_codec
        settings.encoder_display = payload.encoder_display
        settings.encode_speed = payload.encode_speed
        duration_label = str(defaults.get("duration_label") or "") or duration_label
        settings.is_trim_mode = bool(payload.trim.get("is_trim_mode", False))
        settings.trim_start_ms = int(payload.trim.get("trim_start_ms", 0))
        settings.trim_end_ms = int(payload.trim.get("trim_end_ms", 0))

    settings.output_basename = payload.output_basename or settings.output_basename

    if payload.same_preview and payload.settings is not None:
        if not payload.settings.is_trim_mode:
            settings.is_trim_mode = False
            settings.trim_start_ms = 0
            settings.trim_end_ms = 0

    icon_path = game_icon_path_for_clip(payload.cache_dir, clip_path)
    if not icon_path or not os.path.exists(icon_path):
        icon_path = payload.current_game_icon or icon_path

    if not duration_label and mpds:
        duration_label = _duration_label_from_mpd(mpds[0])

    job = RenderJob(
        clip_path=clip_path,
        game_name=meta.get("game_name") or os.path.basename(clip_path),
        clip_date=meta.get("clip_date", ""),
        clip_time=meta.get("clip_time", ""),
        game_icon_path=icon_path,
        settings=settings,
        salvage_mpds=salvage_mpds,
        duration_label=duration_label,
    )
    job.refresh_output_path()
    return job


def build_render_job_from_ui(app: SteempegApp, clip_path: str) -> Optional[RenderJob]:
    """Snapshot the current settings panel into a queue job for ``clip_path``."""
    payload = collect_queue_add_payload(app, clip_path)
    if payload is None:
        return None
    return build_render_job_from_payload(payload)


def resolve_render_params(job: RenderJob, ffmpeg_exe: str) -> Optional[ResolvedRenderParams]:
    """Turn a job's stored settings into RenderThread arguments."""
    s = job.settings
    all_mpds = discovery.find_mpd_paths(job.clip_path)
    if not all_mpds:
        all_mpds = list(getattr(job, "salvage_mpds", []) or [])
    if not all_mpds:
        return None

    output_file = job.output_file or job.refresh_output_path()

    quality_text = s.quality_text
    fps_text = s.fps_text
    bitrate_text = s.bitrate_text
    selected_encoder = resolve_video_encoder(
        s.codec_text,
        s.encoder_codec,
        capabilities.av1_encoder_available(),
    )

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
        container_format=s.container_format or "MP4",
        encode_speed=normalize_encode_speed(s.encode_speed),
    )
