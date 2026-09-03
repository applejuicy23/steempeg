"""Rendering controls and the export pipeline, mixed into the main application.

These methods drive the render tab: probing clip media, building quality and
bitrate options, validating custom input, running the export thread and reporting
results. They run on the application instance and reach its widgets and state
through self.
"""
from steempeg.ui import design_tokens as tok
import json
import logging
import os
import re
import subprocess
import sys

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.core import capabilities
from steempeg.ui.design_tokens import ACCENT_PRIMARY

_TRANSIENT_STATUS_MS = 3500

_DEFAULT_CLIP_SESSION = {
    "is_trim_mode": False,
    "trim_start_ms": 0,
    "trim_end_ms": 0,
    "zoom_level": 1.0,
    "scroll_x": 0,
    "container": "MP4",
    "codec_text": "H.264 (AVC)",
    "audio_format": "AAC",
    "output_preset": "Custom",
    "audio_only": False,
    "mute_audio": False,
}


def _format_mbit(kbps: float | int) -> str:
    """Show bitrate as Mbit/s with one decimal (e.g. 22.3, 55, 0.3 Mbit)."""
    mbps = float(kbps) / 1000.0
    rounded = round(mbps, 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{int(round(rounded))} Mbit"
    return f"{rounded:.1f} Mbit"
from steempeg.core.dash import discovery, health, mpd, repair
from steempeg.core.rendered_media import resolve_ffmpeg_exe
from steempeg.infra.paths import (
    get_resource_path,
    open_path_with_default_app,
    open_text_file,
)
from steempeg.ui.icon_assets import (
    LOADING_WAVE_PHASE_STEP,
    LOADING_WAVE_TICK_MS,
    UPDATE_ARROWS_DEG_PER_TICK,
    UPDATE_ARROWS_TICK_MS,
    canceled_badge_icon,
    completed_badge_icon,
    error_badge_icon,
    loading_wave_frame,
    paused_badge_icon,
    rendering_badge_icon,
    update_arrows_spin_frame,
    warning_pixmap,
)
from steempeg.render import bitrate
from steempeg.render.output_formats import (
    AUDIO_FORMATS,
    CONTAINERS,
    KNOWN_OUTPUT_EXTENSIONS,
    OUTPUT_PRESETS,
    VIDEO_CODEC_ITEMS,
    audio_needs_bitrate,
    is_valid_output_combo,
    normalize_container,
    output_extension,
    resolve_video_encoder,
)
from steempeg.render.encode_speed import (
    ENCODE_SPEED_OPTIONS,
    encode_speed_hint,
    encoder_family,
    normalize_encode_speed,
)
from steempeg.render.queue import (
    JobStatus,
    PREVIEW_BADGE_COLOR,
    PREVIEW_BADGE_TEXT,
    STATUS_COLORS,
    STATUS_HEADER_LABELS,
    load_queue_from_file,
    resolve_job_game_icon_path,
    save_queue_to_file,
)
from steempeg.render.queue_display import format_dash_job_summary
from steempeg.render.queue_history import (
    _utc_now_iso,
    append_batch,
    clear_history,
    load_history,
    snapshot_queue_batch,
)
from steempeg.ui.widgets.combo_chrome import (
    find_enabled_combo_text,
    set_combo_index_if_enabled,
    set_combo_item_enabled,
)
from steempeg.ui.render_panel import set_settings_panel_locked
from steempeg.ui.render_job_builder import (
    apply_job_settings_to_ui,
    build_render_job_from_ui,
    collect_queue_add_payload,
    resolve_render_params,
    snapshot_settings_from_ui,
)
from steempeg.ui.render_thread import RenderThread
from steempeg.ui.message_dialog import (
    steempeg_critical,
    steempeg_information,
    steempeg_information_dont_ask,
    steempeg_question,
    steempeg_warning,
)

# Player-header status plaques (siblings to In queue / Rendering / Completed).
PAUSED_BADGE_TEXT = "Paused"
PAUSED_BADGE_COLOR = "#ffcc00"
CANCELED_BADGE_TEXT = "Canceled"
CANCELED_BADGE_COLOR = "#ff6b6b"  # distinct from Error #ff4444
ERROR_BADGE_COLOR = STATUS_COLORS[JobStatus.ERROR]


def _source_vbitrate_label(mbps: float) -> str:
    """Source Info video-bitrate line; Unknown when the probe has no value."""
    if mbps > 0:
        return f"Video Bitrate: {bitrate.format_video_mbps(mbps)}"
    return "Video Bitrate: Unknown"


def _fmt_mbps(value: float) -> str:
    """Format a Mbps value for the bitrate dropdown.

    Whole/large numbers stay short ("12", "7.5"), but sub-1-Mbps values keep enough
    precision to stay distinct instead of all rounding to "0.1" / "0.0" — which is
    exactly what happened at 144p with a low FPS multiplier (e.g. 0.13 / 0.08 / 0.05
    / 0.03 was collapsing to 0.1 / 0.1 / 0.1 / 0.0).
    """
    if value >= 1:
        return f"{value:.1f}".rstrip("0").rstrip(".") if value % 1 else str(int(value))
    # Below 1 Mbps: two decimals, but never show a meaningless 0.00.
    return f"{max(value, 0.01):.2f}".rstrip("0").rstrip(".")


# Folder holding the bundled ffmpeg/ffprobe binaries (repo/bin), mirroring the
# PATH setup the application performs at startup.
if getattr(sys, "frozen", False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_bin_dir = os.path.join(_base_dir, "bin")


class RenderMixin:
    def _detect_clip_has_audio(self, all_mpds) -> bool:
        """True if any source manifest/folder carries a real audio stream."""
        for mpd_path in all_mpds:
            try:
                with open(mpd_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if 'contentType="audio"' in content or 'mimeType="audio' in content:
                        return True
            except OSError:
                pass
            folder = os.path.dirname(mpd_path)
            init_a = os.path.join(folder, "init-stream1.m4s")
            if os.path.isfile(init_a) and os.path.getsize(init_a) > 100:
                # Stop at the first audio chunk — full listdir on long clips is laggy.
                try:
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            name = entry.name
                            if name.startswith("chunk-stream1-") and name.endswith(".m4s"):
                                return True
                except OSError:
                    pass
            try:
                kbps = self.get_audio_bitrate_from_mpd(mpd_path)
                if kbps and int(kbps) > 0:
                    return True
            except (TypeError, ValueError):
                pass
        return False

    def get_all_mpd_paths(self, clip_path):
        # One select/open calls this from quality populate + preview — cache the
        # walk/repair result for the same folder so the UI thread does not pay twice.
        norm = os.path.normpath(clip_path) if clip_path else ""
        cached = getattr(self, "_mpd_paths_memo", None)
        if (
            isinstance(cached, tuple)
            and len(cached) == 2
            and cached[0] == norm
            and isinstance(cached[1], list)
        ):
            return list(cached[1])

        paths = discovery.find_mpd_paths(clip_path)
        if not paths:
            # Force-play salvage: a clip with no scanner-visible manifest but a built
            # session_salvage.mpd is playable/renderable through that salvage manifest.
            salvaged = getattr(self, "_salvaged_clips", {}).get(norm)
            paths = list(salvaged) if salvaged else []
        self._mpd_paths_memo = (norm, list(paths))
        return list(paths)

    def fix_steam_manifest(self, mpd_path):
        return repair.fix_steam_manifest(mpd_path)

    def recover_orphaned_clip(self, folder_path):
        return repair.recover_orphaned_clip(folder_path)

    def get_fps_from_mpd(self, mpd_path):
        return mpd.get_fps(mpd_path)

    def get_audio_bitrate_from_mpd(self, mpd_path):
        return mpd.get_audio_bitrate_kbps(mpd_path)

    def choose_destination(self):
        """ Select a custom folder to save the finished video """
        from steempeg.ui.settings_prefs import (
            apply_export_folder,
            default_export_dir,
            is_outside_default_rendered,
            normalize_export_folder,
            resolve_permanent_export_folder,
        )

        start = normalize_export_folder(
            getattr(self, "custom_destination", "") or ""
        ) or default_export_dir()
        folder = QFileDialog.getExistingDirectory(
            self.ui, "Select Destination Folder", start
        )
        if folder:
            folder = normalize_export_folder(folder)
            apply_export_folder(self, folder, persist=True)
            if is_outside_default_rendered(folder):
                try:
                    from steempeg.ui.message_dialog import steempeg_information

                    steempeg_information(
                        self.ui,
                        "Custom export folder",
                        "This folder is outside the default rendered_videos library.\n\n"
                        "Exports still work. The Rendered tab keeps scanning this path "
                        "while it is set, but «Open in Steempeg» after render is limited "
                        "to files inside rendered_videos.",
                    )
                except Exception:
                    pass
        else:
            # Cancel: keep permanent folder if set, else default rendered_videos.
            settings = {}
            if hasattr(self, "load_user_settings"):
                try:
                    settings = self.load_user_settings() or {}
                except Exception:
                    settings = {}
            apply_export_folder(
                self, resolve_permanent_export_folder(settings), persist=False
            )

        self.update_final_setup()

    def on_audio_only_toggled(self, checked):
        """ Disables video settings if audio-only mode is active """
        if checked and hasattr(self.ui, 'check_mute_audio'):
            self.ui.check_mute_audio.blockSignals(True)
            self.ui.check_mute_audio.setChecked(False)
            self.ui.check_mute_audio.blockSignals(False)

        if hasattr(self.ui, 'tab_video'):
            self.ui.tab_video.setEnabled(not checked)  # Freeze entire Video Tab
        self._sync_original_audio_controls()
        self.refresh_output_format_availability()
        self._mark_output_preset_custom()
        self._schedule_update_final_setup()

    def on_mute_audio_toggled(self, checked):
        """ Disables audio settings if video-only mode is active """
        if checked and hasattr(self.ui, 'check_audio_only'):
            self.ui.check_audio_only.blockSignals(True)
            self.ui.check_audio_only.setChecked(False)
            self.ui.check_audio_only.blockSignals(False)

        if hasattr(self.ui, 'tab_audio'):
            self.ui.tab_audio.setEnabled(not checked)  # Freeze entire Audio Tab
        self._sync_original_audio_controls()
        self.refresh_output_format_availability()
        self._mark_output_preset_custom()
        self.refresh_slider_if_needed()
        self._schedule_update_final_setup()

    def _sync_original_audio_controls(self):
        """Freeze audio encode controls when Original is doing stream copy."""
        if not getattr(self, "_current_clip_has_audio", True):
            # No source audio — audio-only is impossible; video-only (mute) still works.
            for name in (
                "label_audio_format", "combo_audio_format", "label_audio_bitrate",
                "combo_audio_bitrate", "input_custom_abitrate", "check_audio_only",
            ):
                widget = getattr(self.ui, name, None)
                if widget is not None:
                    widget.setEnabled(False)
            return
        quality_text = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else ""
        audio_only = self.ui.check_audio_only.isChecked() if hasattr(self.ui, 'check_audio_only') else False
        is_original_copy = "Original" in quality_text and "Target File" not in quality_text and not audio_only

        if is_original_copy and hasattr(self.ui, 'combo_audio_bitrate') and self.ui.combo_audio_bitrate.count() > 0:
            self.ui.combo_audio_bitrate.setCurrentIndex(0)

        tooltip = (
            "Original preset uses stream copy: audio is copied as-is, without re-encoding."
            if is_original_copy else ""
        )
        for name in ("label_audio_format", "combo_audio_format", "label_audio_bitrate", "combo_audio_bitrate"):
            widget = getattr(self.ui, name, None)
            if widget is not None:
                widget.setEnabled(not is_original_copy)
                widget.setToolTip(tooltip)

        audio_fmt = self.ui.combo_audio_format.currentText() if hasattr(self.ui, "combo_audio_format") else "AAC"
        if not is_original_copy and audio_fmt == "Copy" and hasattr(self.ui, "combo_audio_format"):
            idx = self.ui.combo_audio_format.findText("AAC")
            if idx >= 0:
                self.ui.combo_audio_format.setCurrentIndex(idx)
            audio_fmt = "AAC"

        if not is_original_copy and audio_needs_bitrate(audio_fmt):
            for name in ("label_audio_bitrate", "combo_audio_bitrate"):
                widget = getattr(self.ui, name, None)
                if widget is not None:
                    widget.setEnabled(True)

    def detect_gpu_and_set_encoder(self):
        """Probe the hardware encoders and fill the encoder dropdown."""
        if not hasattr(self.ui, 'combo_encoder'):
            return
        self.ui.combo_encoder.clear()

        logging.info("Starting silent hardware encoder probe...")
        encoders = capabilities.detect_supported_encoders()
        logging.info(f"Probe done. Available: {[name for name, _ in encoders]}")
        for display_name, codec in encoders:
            self.ui.combo_encoder.addItem(display_name, codec)

        # Prefer NVENC / AMF / QSV — never default to CPU when HW is present.
        idx = capabilities.preferred_encoder_index(encoders)
        self.ui.combo_encoder.setCurrentIndex(idx)
        logging.info(
            "Default encoder → %s",
            encoders[idx][0] if encoders else "?",
        )
        self.refresh_encode_speed_options()

    def refresh_encode_speed_options(self, preferred_id: str | None = None) -> None:
        """Fill encode-speed presets for the active codec + encoder pair."""
        ui = self.ui
        if not hasattr(ui, "combo_encode_speed"):
            return

        current_id = preferred_id
        if current_id is None:
            data = ui.combo_encode_speed.currentData(Qt.UserRole)
            if data:
                current_id = str(data)

        codec_raw = ui.combo_codec.currentText() if hasattr(ui, "combo_codec") else ""
        enc_data = ui.combo_encoder.currentData(Qt.UserRole) if hasattr(ui, "combo_encoder") else "libx264"
        resolved = resolve_video_encoder(
            codec_raw,
            str(enc_data) if enc_data else "libx264",
            capabilities.av1_encoder_available(),
        )
        hint = encode_speed_hint(encoder_family(resolved))

        ui.combo_encode_speed.blockSignals(True)
        ui.combo_encode_speed.clear()
        for opt in ENCODE_SPEED_OPTIONS:
            ui.combo_encode_speed.addItem(opt.label, opt.id)

        target = normalize_encode_speed(current_id)
        idx = ui.combo_encode_speed.findData(target, Qt.UserRole)
        if idx >= 0:
            ui.combo_encode_speed.setCurrentIndex(idx)

        ui.combo_encode_speed.setToolTip(hint)
        if hasattr(ui, "label_encode_speed"):
            ui.label_encode_speed.setToolTip(hint)
        ui.combo_encode_speed.blockSignals(False)

    def populate_output_format_combos(self) -> None:
        """Fill container / codec / audio / preset dropdowns (post-restyle)."""
        ui = self.ui
        optional = set(capabilities.detect_optional_video_codecs())

        if hasattr(ui, "combo_codec"):
            ui.combo_codec.clear()
            for item in VIDEO_CODEC_ITEMS:
                if item == "AV1" and "AV1" not in optional:
                    continue
                if item == "VP9" and "VP9" not in optional:
                    continue
                ui.combo_codec.addItem(item)
            if ui.combo_codec.count():
                ui.combo_codec.setCurrentIndex(min(1, ui.combo_codec.count() - 1))

        if hasattr(ui, "combo_audio_format"):
            ui.combo_audio_format.clear()
            for fmt in AUDIO_FORMATS:
                ui.combo_audio_format.addItem(fmt)

        if hasattr(ui, "combo_container"):
            ui.combo_container.clear()
            for container in CONTAINERS:
                ui.combo_container.addItem(container)

        if hasattr(ui, "combo_output_preset"):
            ui.combo_output_preset.clear()
            ui.combo_output_preset.addItem("Custom")
            for name in OUTPUT_PRESETS:
                ui.combo_output_preset.addItem(name)

        self.refresh_output_format_availability()

    def refresh_output_format_availability(self) -> None:
        """Grey invalid container/codec/audio pairs; toggle lossless audio bitrate."""
        ui = self.ui
        no_audio = not getattr(self, "_current_clip_has_audio", True)
        if no_audio and hasattr(ui, "check_audio_only") and ui.check_audio_only.isChecked():
            ui.check_audio_only.blockSignals(True)
            ui.check_audio_only.setChecked(False)
            ui.check_audio_only.blockSignals(False)
        container = ui.combo_container.currentText() if hasattr(ui, "combo_container") else "MP4"
        codec = ui.combo_codec.currentText() if hasattr(ui, "combo_codec") else ""
        audio_fmt = ui.combo_audio_format.currentText() if hasattr(ui, "combo_audio_format") else "AAC"
        audio_only = ui.check_audio_only.isChecked() if hasattr(ui, "check_audio_only") else False
        mute = ui.check_mute_audio.isChecked() if hasattr(ui, "check_mute_audio") else False
        quality_text = ui.combo_quality.currentText() if hasattr(ui, "combo_quality") else ""
        is_original_copy = (
            "Original" in quality_text and "Target File" not in quality_text and not audio_only
        )

        _tip_webm_copy = (
            "Original copies the source stream as-is (H.264/AAC). WebM cannot hold that — use MP4 or MKV."
        )
        _tip_wav_mp4 = "WAV (PCM) does not fit in MP4 — use MKV/MOV or pick AAC/FLAC."
        _tip_wav_webm = "WebM only supports Opus/Vorbis audio — not WAV."

        if hasattr(ui, "combo_container"):
            for i in range(ui.combo_container.count()):
                c = ui.combo_container.itemText(i)
                ok = is_valid_output_combo(
                    c, codec, audio_fmt, audio_only=audio_only, mute_audio=mute,
                    stream_copy=is_original_copy,
                )
                tip = ""
                if not ok and is_original_copy and c == "WebM":
                    tip = _tip_webm_copy
                set_combo_item_enabled(ui.combo_container, i, ok, tooltip=tip)

        if hasattr(ui, "combo_codec"):
            for i in range(ui.combo_codec.count()):
                ctext = ui.combo_codec.itemText(i)
                ok = is_valid_output_combo(
                    container, ctext, audio_fmt, audio_only=audio_only, mute_audio=mute,
                    stream_copy=is_original_copy,
                )
                set_combo_item_enabled(ui.combo_codec, i, ok)

        if hasattr(ui, "combo_audio_format"):
            for i in range(ui.combo_audio_format.count()):
                afmt = ui.combo_audio_format.itemText(i)
                ok = is_valid_output_combo(
                    container, codec, afmt, audio_only=audio_only, mute_audio=mute,
                    stream_copy=is_original_copy,
                )
                if afmt == "Copy" and not is_original_copy:
                    ok = False
                tip = ""
                if not ok and afmt == "WAV":
                    if normalize_container(container) == "MP4":
                        tip = _tip_wav_mp4
                    elif normalize_container(container) == "WebM":
                        tip = _tip_wav_webm
                set_combo_item_enabled(ui.combo_audio_format, i, ok, tooltip=tip)

        needs_bitrate = audio_needs_bitrate(audio_fmt) and not is_original_copy
        bitrate_enabled = needs_bitrate and (audio_only or not mute)
        for name in ("label_audio_bitrate", "combo_audio_bitrate"):
            widget = getattr(ui, name, None)
            if widget is not None:
                widget.setEnabled(bitrate_enabled)
        if hasattr(ui, "input_custom_abitrate"):
            ui.input_custom_abitrate.setEnabled(bitrate_enabled)

        # Source has no audio track: audio-only is off-limits; video-only export still works.
        if no_audio:
            for name in (
                "combo_audio_format", "combo_audio_bitrate", "label_audio_format",
                "label_audio_bitrate", "input_custom_abitrate", "check_audio_only",
            ):
                widget = getattr(ui, name, None)
                if widget is not None:
                    widget.setEnabled(False)
            if hasattr(ui, "check_mute_audio"):
                ui.check_mute_audio.setEnabled(True)
            if hasattr(ui, "label_abitrate"):
                ui.label_abitrate.setText("Audio Bitrate: None (no audio track)")
            if mute and hasattr(ui, "tab_audio"):
                ui.tab_audio.setEnabled(False)
            elif hasattr(ui, "tab_audio"):
                ui.tab_audio.setEnabled(True)
            if hasattr(ui, "tab_video"):
                ui.tab_video.setEnabled(True)
        else:
            for name in ("check_audio_only", "check_mute_audio"):
                widget = getattr(ui, name, None)
                if widget is not None:
                    widget.setEnabled(True)
            if audio_only and hasattr(ui, "tab_video"):
                ui.tab_video.setEnabled(False)
            elif mute and hasattr(ui, "tab_audio"):
                ui.tab_audio.setEnabled(False)
            elif hasattr(ui, "tab_video"):
                ui.tab_video.setEnabled(True)
            if hasattr(ui, "tab_audio") and not mute:
                ui.tab_audio.setEnabled(True)

        if self._fix_invalid_output_combo():
            self._mark_output_preset_custom()
            if hasattr(self, "refresh_encode_speed_options"):
                self.refresh_encode_speed_options()

    def _output_mode_flags(self) -> tuple[str, str, str, bool, bool, bool]:
        """Current container/codec/audio and mode flags for validation."""
        ui = self.ui
        container = ui.combo_container.currentText() if hasattr(ui, "combo_container") else "MP4"
        codec = ui.combo_codec.currentText() if hasattr(ui, "combo_codec") else ""
        audio_fmt = ui.combo_audio_format.currentText() if hasattr(ui, "combo_audio_format") else "AAC"
        audio_only = ui.check_audio_only.isChecked() if hasattr(ui, "check_audio_only") else False
        mute = ui.check_mute_audio.isChecked() if hasattr(ui, "check_mute_audio") else False
        quality_text = ui.combo_quality.currentText() if hasattr(ui, "combo_quality") else ""
        is_original_copy = (
            "Original" in quality_text and "Target File" not in quality_text and not audio_only
        )
        return container, codec, audio_fmt, audio_only, mute, is_original_copy

    def _fix_invalid_output_combo(self) -> bool:
        """Snap container/codec/audio to the first valid enabled triple."""
        ui = self.ui
        container, codec, audio_fmt, audio_only, mute, is_original_copy = self._output_mode_flags()
        if is_valid_output_combo(
            container, codec, audio_fmt,
            audio_only=audio_only, mute_audio=mute, stream_copy=is_original_copy,
        ):
            return False

        changed = False
        for combo_name, field in (
            ("combo_audio_format", "audio"),
            ("combo_codec", "codec"),
            ("combo_container", "container"),
        ):
            combo = getattr(ui, combo_name, None)
            if combo is None:
                continue
            model = combo.model()
            for i in range(combo.count()):
                if model is not None:
                    item = model.item(i)
                    if item is not None and not item.isEnabled():
                        continue
                text = combo.itemText(i)
                test_c, test_codec, test_a = container, codec, audio_fmt
                if field == "audio":
                    test_a = text
                elif field == "codec":
                    test_codec = text
                else:
                    test_c = text
                if is_valid_output_combo(
                    test_c, test_codec, test_a,
                    audio_only=audio_only, mute_audio=mute, stream_copy=is_original_copy,
                ):
                    if combo.currentIndex() != i:
                        combo.blockSignals(True)
                        combo.setCurrentIndex(i)
                        combo.blockSignals(False)
                        changed = True
                    container, codec, audio_fmt = test_c, test_codec, test_a
                    break
            if is_valid_output_combo(
                container, codec, audio_fmt,
                audio_only=audio_only, mute_audio=mute, stream_copy=is_original_copy,
            ):
                break
        return changed

    def _mark_output_preset_custom(self) -> None:
        if getattr(self, "_applying_output_preset", False):
            return
        combo = getattr(self.ui, "combo_output_preset", None)
        if combo is None:
            return
        idx = combo.findText("Custom")
        if idx >= 0 and combo.currentIndex() != idx:
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    def on_output_preset_changed(self, text: str) -> None:
        preset = OUTPUT_PRESETS.get((text or "").strip())
        if not preset:
            if (text or "").strip() == "Custom":
                self._reset_export_to_custom_defaults()
            self.refresh_output_format_availability()
            self._sync_original_audio_controls()
            self.update_final_setup()
            return

        ui = self.ui
        quality_text = ui.combo_quality.currentText() if hasattr(ui, "combo_quality") else ""
        audio_only = ui.check_audio_only.isChecked() if hasattr(ui, "check_audio_only") else False
        is_original_copy = (
            "Original" in quality_text and "Target File" not in quality_text and not audio_only
        )

        self._applying_output_preset = True
        blockers = []
        for name in (
            "combo_container",
            "combo_codec",
            "combo_audio_format",
            "check_audio_only",
            "check_mute_audio",
        ):
            w = getattr(ui, name, None)
            if w is not None and hasattr(w, "blockSignals"):
                w.blockSignals(True)
                blockers.append(w)

        try:
            if hasattr(ui, "combo_container"):
                idx = find_enabled_combo_text(ui.combo_container, preset["container"])
                if idx >= 0:
                    ui.combo_container.setCurrentIndex(idx)
            if not is_original_copy:
                if hasattr(ui, "combo_codec"):
                    idx = find_enabled_combo_text(ui.combo_codec, preset["codec"])
                    if idx >= 0:
                        ui.combo_codec.setCurrentIndex(idx)
                if hasattr(ui, "combo_audio_format"):
                    idx = find_enabled_combo_text(ui.combo_audio_format, preset["audio"])
                    if idx >= 0:
                        ui.combo_audio_format.setCurrentIndex(idx)
            if hasattr(ui, "check_audio_only") and ui.check_audio_only.isChecked():
                ui.check_audio_only.setChecked(False)
            if hasattr(ui, "check_mute_audio") and ui.check_mute_audio.isChecked():
                ui.check_mute_audio.setChecked(False)
            if hasattr(ui, "tab_video"):
                ui.tab_video.setEnabled(True)
            if hasattr(ui, "tab_audio"):
                ui.tab_audio.setEnabled(True)
        finally:
            for w in blockers:
                w.blockSignals(False)
            self._applying_output_preset = False

        self.refresh_output_format_availability()
        self._sync_original_audio_controls()
        self.update_final_setup()

    def _on_render_progress(self, msg):
        """Helper to safely receive thread signals on the main GUI thread."""
        if getattr(self, "_queue_batch_active", False):
            total = max(1, int(getattr(self, "_batch_total", 0) or 0))
            current = max(1, min(int(getattr(self, "_batch_current", 0) or 0), total))
            msg = f"({current}/{total}) {msg}"
        self.update_status_indicator(msg, "rendering")

    @staticmethod
    def _format_pct_label(percent):
        percent = max(0.0, min(100.0, float(percent)))
        if percent >= 100:
            return "100%"
        if percent <= 0:
            return "0%"
        rounded = round(percent, 1)
        if rounded == int(rounded):
            return f"{int(rounded)}%"
        return f"{rounded:.1f}%"

    def _cancel_transient_status_timer(self) -> None:
        timer = getattr(self, "_transient_status_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

    def _schedule_transient_status_clear(self, ms: int = _TRANSIENT_STATUS_MS) -> None:
        timer = getattr(self, "_transient_status_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._clear_transient_status)
            self._transient_status_timer = timer
        else:
            timer.stop()
        timer.start(max(500, int(ms)))

    def _clear_transient_status(self) -> None:
        if getattr(self, "_is_rendering", False):
            return
        self.update_status_indicator("Ready", "ready")

    @staticmethod
    def _elide_status_label_text(label, full_text: str) -> str:
        """Keep «Loading N/M —» visible; elide only the game/file name tail."""
        metrics = QFontMetrics(label.font())
        max_w = label.maximumWidth() if label.maximumWidth() > 0 else 280
        if full_text.startswith("Loading "):
            match = re.match(r"^(Loading \d+/\d+ — )(.+)$", full_text)
            if match:
                prefix, tail = match.group(1), match.group(2)
                tail_budget = max(24, max_w - metrics.horizontalAdvance(prefix))
                if metrics.horizontalAdvance(tail) > tail_budget:
                    tail = metrics.elidedText(tail, Qt.TextElideMode.ElideRight, tail_budget)
                return prefix + tail
        return metrics.elidedText(full_text, Qt.TextElideMode.ElideRight, max_w)

    def update_status_indicator(
        self,
        text,
        state="ready",
        *,
        scan_phase: str | None = None,
        status_tooltip: str | None = None,
    ):
        """Update the macOS-style status dot, label, progress bar and percent label."""
        if not hasattr(self.ui, 'label_status'):
            return
        if state != "accent":
            self._cancel_transient_status_timer()
        # While the library scan is running, ignore unrelated "Ready" updates that
        # would reset the progress bar mid-load (settings callbacks, layout refresh, etc).
        if getattr(self, "_clips_scan_active", False) and scan_phase is None and state == "ready":
            return
        if getattr(self, "_rendered_scan_active", False) and scan_phase is None and state == "ready":
            return
        if getattr(self, "_update_check_busy", False) and scan_phase is None and state == "ready":
            return
        # Live encode: never let a stray Ready (e.g. old Render Settings open path)
        # wipe Part N% / the progress strip.
        if (
            scan_phase is None
            and state == "ready"
            and getattr(self, "_is_rendering", False)
        ):
            return

        # Queue owns the idle Ready cluster: numbered coloured badge, not plain green.
        # Digit = next-to-render only (never the selected clip).
        if (
            scan_phase is None
            and state in ("ready", "success")
            and not getattr(self, "_is_rendering", False)
            and self._sync_dash_queue_status_chrome()
        ):
            return

        colors = {
            "ready": "#4CAF50",
            "rendering": "#a871ff",
            "busy": "#a871ff",
            "paused": "#ffcc00",
            "error": "#ff4444",
            "success": "#4CAF50",
            "cancelling": "#ff4444",
            "cancelled": "#ff4444",
            "accent": ACCENT_PRIMARY,
        }
        color = colors.get(state, "#a871ff")
        queue_index = None
        job = None
        if self._queue_is_active():
            # Badge tracks next-to-render / live encode — not library selection.
            job = self._dash_ready_queue_job()
            if job is not None:
                queue_index = int(getattr(job, "queue_index", 0) or 0) or None
                if state in ("rendering", "busy") and job.status == JobStatus.RENDERING:
                    color = STATUS_COLORS[JobStatus.RENDERING]
                elif state == "error":
                    color = STATUS_COLORS[JobStatus.ERROR]
                elif state == "paused":
                    color = colors["paused"]
        preserve_progress = state in ("cancelling", "cancelled", "paused")

        display_text = str(text)
        percent = None

        pct_match = re.search(r'\((\d+(?:\.\d+)?)%\)', display_text)
        if pct_match:
            percent = max(0.0, min(100.0, float(pct_match.group(1))))
            display_text = re.sub(r'\s*\(\d+(?:\.\d+)?%\)', '', display_text).strip()

        if state == "rendering" and not display_text:
            display_text = "Rendering"

        # Library Loading/search: three-dot purple wave — never the queue index
        # digit, even when Render Queue owns the strip.
        # Update-check busy: spinning purple update arrows (badge-sized).
        # (Render progress itself uses state=rendering and keeps the badge.)
        library_scan_busy = (
            scan_phase is not None
            or getattr(self, "_clips_scan_active", False)
            or getattr(self, "_rendered_scan_active", False)
        )
        suppress_queue_badge = (
            library_scan_busy or getattr(self, "_update_check_busy", False)
        )
        if getattr(self, "_update_check_busy", False):
            self._paint_status_dot_update_spin(color)
        elif library_scan_busy:
            self._paint_status_dot_loading_wave(color)
        elif queue_index and self._queue_is_active() and not suppress_queue_badge:
            # Numbered queue badge only — Rendering/Completed glyphs live on the
            # player-header plaque (label_playback_badge), never Part/progress chrome.
            self._paint_status_dot_queue_badge(queue_index, color)
        else:
            self._paint_status_dot_plain(color)

        status_label = self.ui.label_status
        dense = getattr(self, "_ui_density", None)
        status_font = int(getattr(dense, "dash_font", 14) or 14)
        self._status_indicator_color = color
        status_label.setStyleSheet(
            f"background: transparent; border: none; font-size: {status_font}px; font-weight: bold; "
            f"color: {color}; font-family: Segoe UI, Arial, sans-serif;"
        )
        full_text = display_text
        display_text = self._elide_status_label_text(status_label, full_text)
        status_label.setText(display_text)
        if status_tooltip:
            tip = status_tooltip
        elif full_text != display_text:
            tip = full_text
        else:
            tip = ""
        status_label.setToolTip(tip)

        if state == "success":
            percent = 100.0
        elif state in ("ready", "error", "accent"):
            percent = 0.0
        # busy/rendering: keep percent parsed from "(N%)" in the status text

        if hasattr(self.ui, 'progress_render'):
            bar = self.ui.progress_render
            if hasattr(bar, 'set_progress'):
                if scan_phase == "search" and hasattr(bar, "set_scan_bounce"):
                    bar.set_scan_bounce()
                elif scan_phase == "loading" and percent is not None and hasattr(bar, "set_loading_progress"):
                    bar.set_loading_progress(percent)
                elif percent is not None:
                    bar.set_progress(percent)
                elif state == "success":
                    bar.set_progress(100.0)
                elif not preserve_progress and state in ("ready", "error", "accent"):
                    bar.set_progress(0.0)
                elif state == "busy" and hasattr(bar, "set_scan_bounce"):
                    bar.set_scan_bounce()
                bar.set_state("ready" if state == "accent" else state)
            else:
                if percent is not None:
                    bar.setValue(int(percent * 10))
                elif state == "success":
                    bar.setValue(1000)
                elif not preserve_progress and state in ("ready", "error", "accent"):
                    bar.setValue(0)
                bar.setTextVisible(False)
                chunk = (
                    "qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #6b5a8e, stop:1 #b29ae7)"
                    if state == "rendering"
                    else color
                )
                bar.setStyleSheet(f"""
                    QProgressBar {{
                        background-color: #414141;
                        border: none;
                        border-radius: 3px;
                        min-height: 6px;
                        max-height: 6px;
                    }}
                    QProgressBar::chunk {{
                        background-color: {chunk};
                        border-radius: 3px;
                    }}
                """)

        if hasattr(self, 'label_pct'):
            if scan_phase == "search":
                self.label_pct.setText("")
            elif percent is not None:
                self.label_pct.setText(self._format_pct_label(percent))
            elif state == "success":
                self.label_pct.setText("100%")
            elif not preserve_progress and state in ("ready", "error", "accent"):
                self.label_pct.setText("0%")

        strip_state = "ready" if state == "accent" else state
        self._sync_portable_render_strip(full_text, strip_state, percent)

    def _status_dot_widget(self):
        """Visible status chrome dot — portable strip when shell is active."""
        if getattr(self, "_portable_shell", False):
            strip = getattr(self, "_portable_render_strip", None)
            strip_dot = getattr(strip, "status_dot", None) if strip is not None else None
            if strip_dot is not None:
                return strip_dot
        return getattr(self, "status_dot", None)

    def _stop_status_dot_update_spin(self) -> None:
        """Stop update-check arrows and clear pixmap from the status dot."""
        timer = getattr(self, "_status_update_spin_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._status_update_spin_angle = 0.0
        self._status_update_spin_active = False
        dots = [getattr(self, "status_dot", None)]
        strip = getattr(self, "_portable_render_strip", None)
        if strip is not None:
            dots.append(getattr(strip, "status_dot", None))
        for dot in dots:
            if dot is None:
                continue
            try:
                dot.setPixmap(QPixmap())
            except RuntimeError:
                pass

    def _stop_status_dot_loading_wave(self) -> None:
        """Stop library-loading wave dots and clear pixmap from the status chrome."""
        timer = getattr(self, "_status_loading_wave_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._status_loading_wave_phase = 0.0
        self._status_loading_wave_active = False
        dots = [getattr(self, "status_dot", None)]
        strip = getattr(self, "_portable_render_strip", None)
        if strip is not None:
            dots.append(getattr(strip, "status_dot", None))
        for dot in dots:
            if dot is None:
                continue
            try:
                dot.setPixmap(QPixmap())
            except RuntimeError:
                pass

    def _paint_status_dot_update_spin(self, color: str) -> None:
        """Spinning purple update.png — same asset/cadence as portable Updates."""
        if getattr(self, "_status_loading_wave_active", False):
            self._stop_status_dot_loading_wave()
        dot = self._status_dot_widget()
        if dot is None:
            return
        dense = getattr(self, "_ui_density", None)
        # Match Ready queue number badge circle (comfort 24 / compact 22).
        sz = 22 if dense is not None and getattr(dense, "compact", False) else 24
        glyph = max(14, sz - 4)
        self._status_indicator_color = color
        self._status_update_spin_color = color
        self._status_update_spin_size = sz
        self._status_update_spin_glyph = glyph
        self._status_update_spin_active = True
        if not hasattr(self, "_status_update_spin_angle"):
            self._status_update_spin_angle = 0.0

        dot.setFixedSize(sz, sz)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setText("")
        dot.setStyleSheet("background: transparent; border: none;")

        timer = getattr(self, "_status_update_spin_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(UPDATE_ARROWS_TICK_MS)
            timer.timeout.connect(self._on_status_update_spin_tick)
            self._status_update_spin_timer = timer
        self._refresh_status_update_spin_frame()
        if not timer.isActive():
            timer.start()

    def _on_status_update_spin_tick(self) -> None:
        if not getattr(self, "_status_update_spin_active", False):
            self._stop_status_dot_update_spin()
            return
        if not getattr(self, "_update_check_busy", False):
            self._stop_status_dot_update_spin()
            return
        self._status_update_spin_angle = (
            float(getattr(self, "_status_update_spin_angle", 0.0))
            + UPDATE_ARROWS_DEG_PER_TICK
        ) % 360.0
        self._refresh_status_update_spin_frame()

    def _refresh_status_update_spin_frame(self) -> None:
        dot = self._status_dot_widget()
        if dot is None:
            return
        color = getattr(self, "_status_update_spin_color", "#a871ff")
        sz = int(getattr(self, "_status_update_spin_size", 24) or 24)
        glyph = int(getattr(self, "_status_update_spin_glyph", max(14, sz - 4)) or sz)
        angle = float(getattr(self, "_status_update_spin_angle", 0.0))
        frame = update_arrows_spin_frame(color, sz, angle, glyph_size=glyph)
        try:
            dot.setPixmap(frame)
        except RuntimeError:
            self._stop_status_dot_update_spin()

    def _paint_status_dot_loading_wave(self, color: str) -> None:
        """Three purple dots bouncing in a wave — library Loading / search busy."""
        if getattr(self, "_status_update_spin_active", False):
            self._stop_status_dot_update_spin()
        dot = self._status_dot_widget()
        if dot is None:
            return
        dense = getattr(self, "_ui_density", None)
        # Same height as queue badge / update-spin; slightly wider for three dots.
        h = 22 if dense is not None and getattr(dense, "compact", False) else 24
        w = 28 if h <= 22 else 32
        self._status_indicator_color = color
        self._status_loading_wave_color = color
        self._status_loading_wave_size = (w, h)
        self._status_loading_wave_active = True
        if not hasattr(self, "_status_loading_wave_phase"):
            self._status_loading_wave_phase = 0.0

        dot.setFixedSize(w, h)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setText("")
        dot.setStyleSheet("background: transparent; border: none;")

        timer = getattr(self, "_status_loading_wave_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(LOADING_WAVE_TICK_MS)
            timer.timeout.connect(self._on_status_loading_wave_tick)
            self._status_loading_wave_timer = timer
        self._refresh_status_loading_wave_frame()
        if not timer.isActive():
            timer.start()

    def _on_status_loading_wave_tick(self) -> None:
        # Stop only via paint restore paths (plain / queue badge / update-spin).
        # Do not key off scan flags here — brief gaps (clips done → rendered
        # search) would kill the wave while status text is still Loading/search.
        if not getattr(self, "_status_loading_wave_active", False):
            self._stop_status_dot_loading_wave()
            return
        self._status_loading_wave_phase = (
            float(getattr(self, "_status_loading_wave_phase", 0.0))
            + LOADING_WAVE_PHASE_STEP
        )
        self._refresh_status_loading_wave_frame()

    def _refresh_status_loading_wave_frame(self) -> None:
        dot = self._status_dot_widget()
        if dot is None:
            return
        color = getattr(self, "_status_loading_wave_color", "#a871ff")
        size = getattr(self, "_status_loading_wave_size", (32, 24))
        try:
            w, h = int(size[0]), int(size[1])
        except (TypeError, ValueError, IndexError):
            w, h = 32, 24
        phase = float(getattr(self, "_status_loading_wave_phase", 0.0))
        frame = loading_wave_frame(color, w, h, phase)
        try:
            dot.setPixmap(frame)
        except RuntimeError:
            self._stop_status_dot_loading_wave()

    def _paint_status_dot_plain(self, color: str) -> None:
        self._stop_status_dot_update_spin()
        self._stop_status_dot_loading_wave()
        # Clear any leftover Part-strip Rendering orbit from older builds.
        timer = getattr(self, "_status_rendering_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._status_rendering_active = False
        dot = self._status_dot_widget()
        if dot is None:
            return
        try:
            dot.setPixmap(QPixmap())
        except (RuntimeError, Exception):
            pass
        dense = getattr(self, "_ui_density", None)
        sz = 8 if dense is not None and getattr(dense, "compact", False) else 12
        # Portable strip uses a fixed 12px plain dot for visual parity with dash.
        if getattr(self, "_portable_shell", False) and getattr(
            self, "_portable_render_strip", None
        ) is not None:
            sz = 12
        dot.setFixedSize(sz, sz)
        dot.setText("")
        radius = max(3, sz // 2)
        dot.setStyleSheet(f"background-color: {color}; border-radius: {radius}px;")
        self._status_indicator_color = color

    def _paint_status_dot_queue_badge(self, index: int, color: str) -> None:
        """Numbered circle — yellow queue / orange render / red error / green done."""
        self._stop_status_dot_update_spin()
        self._stop_status_dot_loading_wave()
        # Clear any leftover Part-strip Rendering orbit from older builds.
        timer = getattr(self, "_status_rendering_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._status_rendering_active = False
        dot = self._status_dot_widget()
        if dot is None:
            return
        try:
            dot.setPixmap(QPixmap())
        except (RuntimeError, Exception):
            pass
        dense = getattr(self, "_ui_density", None)
        # Slightly larger than the plain status dot so the queue index digit stays readable.
        sz = 22 if dense is not None and getattr(dense, "compact", False) else 24
        font = 12 if sz <= 22 else 13
        dot.setFixedSize(sz, sz)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setText(str(max(1, int(index))))
        radius = sz // 2
        # Dark digit on bright badge colours (yellow/orange/green); light on red.
        ink = "#ffffff" if color.lower() in ("#ff4444", "#ff0000") else "#1a1a1a"
        dot.setStyleSheet(
            f"background-color: {color}; color: {ink}; border-radius: {radius}px; "
            f"font-size: {font}px; font-weight: 800; "
            f"font-family: {tok.FONT_APP};"
        )
        self._status_indicator_color = color

    def _sync_dash_queue_status_chrome(self) -> bool:
        """Drive Ready cluster + left summary from the **next-to-render** job.

        True = queue owns the chrome. Digit and game line follow queue head /
        live encode — never the ClipCard or queue-row selection (that only
        updates the player-header ``In queue (N)`` plaque).
        """
        # Do not stamp a numbered queue badge over Loading N/M / search / update-check.
        if (
            getattr(self, "_clips_scan_active", False)
            or getattr(self, "_rendered_scan_active", False)
            or getattr(self, "_update_check_busy", False)
        ):
            return False
        if not self._queue_is_active():
            return False
        job = self._status_strip_context_job()
        if job is None:
            return False

        self._apply_status_strip_summary(job)

        color = STATUS_COLORS.get(job.status, STATUS_COLORS[JobStatus.QUEUED])
        index = int(getattr(job, "queue_index", 0) or 0) or 1
        if job.status == JobStatus.QUEUED:
            label = "Ready"
        else:
            label = STATUS_HEADER_LABELS.get(job.status, "Ready")

        # Progress strip keeps the numbered circle; Rendering/Completed icons
        # belong on label_playback_badge next to Healthy.
        self._paint_status_dot_queue_badge(index, color)

        tip = f"#{index} · {label}"
        status_label = getattr(self.ui, "label_status", None)
        if status_label is not None:
            dense = getattr(self, "_ui_density", None)
            status_font = int(getattr(dense, "dash_font", 14) or 14)
            status_label.setStyleSheet(
                f"background: transparent; border: none; font-size: {status_font}px; "
                f"font-weight: bold; color: {color}; font-family: Segoe UI, Arial, sans-serif;"
            )
            full = label
            shown = self._elide_status_label_text(status_label, full)
            status_label.setText(shown)
            status_label.setToolTip(full if shown != full else tip)

        # Portable sheet strip mirrors the same queue-first Ready cluster.
        strip = getattr(self, "_portable_render_strip", None)
        if strip is not None:
            try:
                if hasattr(strip, "status_label") and strip.status_label is not None:
                    strip.status_label.setText(label)
                    strip.status_label.setStyleSheet(
                        f"color: {color}; font-size: 14px; font-weight: bold; "
                        f"font-family: {tok.FONT_APP};"
                    )
                    strip.status_label.setToolTip(tip)
                if hasattr(strip, "sync_game_header"):
                    strip.sync_game_header()
                if hasattr(strip, "sync_from_app"):
                    strip.sync_from_app()
                if hasattr(strip, "progress") and not getattr(self, "_is_rendering", False):
                    strip.progress.set_progress(0.0)
                    strip.progress.set_state("ready")
                if hasattr(strip, "pct_label") and not getattr(self, "_is_rendering", False):
                    strip.pct_label.setText("0%")
            except RuntimeError:
                self._portable_render_strip = None

        if hasattr(self.ui, "progress_render") and not getattr(self, "_is_rendering", False):
            bar = self.ui.progress_render
            if hasattr(bar, "set_progress"):
                bar.set_progress(0.0)
                if hasattr(bar, "set_state"):
                    bar.set_state("ready")
        if hasattr(self, "label_pct") and not getattr(self, "_is_rendering", False):
            self.label_pct.setText("0%")
        return True

    def _sync_portable_render_strip(
        self,
        text: str | None = None,
        state: str | None = None,
        percent: float | None = None,
    ) -> None:
        strip = getattr(self, "_portable_render_strip", None)
        if strip is None:
            return
        try:
            if text is not None and state is not None and hasattr(strip, "apply_status"):
                strip.apply_status(text, state, percent)
            elif hasattr(strip, "sync_from_app"):
                strip.sync_from_app()
            if hasattr(strip, "sync_game_header"):
                strip.sync_game_header()
        except RuntimeError:
            self._portable_render_strip = None

    def open_rendered_folder(self, file_path):
        """Open the file manager with the rendered output selected."""
        from steempeg.infra.paths import reveal_in_file_manager

        try:
            reveal_in_file_manager(file_path)
        except Exception as e:
            print(f"Failed to open folder: {e}")

    def open_rendered_file(self, file_path: str) -> None:
        """Open a rendered output with the system default app."""
        try:
            if os.path.isfile(file_path):
                open_path_with_default_app(file_path)
        except OSError as exc:
            logging.warning("Could not open rendered file %s: %s", file_path, exc)

    def _queue_is_active(self) -> bool:
        """True when the queue owns Start CTA (jobs exist, scheme not left)."""
        if not (getattr(self, "render_queue", None) and len(self.render_queue) > 0):
            return False
        return not bool(getattr(self, "_queue_scheme_deferred", False))

    def _queue_owns_identity_chrome(self) -> bool:
        """True when queue mode is active (jobs kept, scheme not Left).

        Footer / Ready cluster always follow ``_status_strip_context_job``.
        Player header always follows the open clip — never queue head.
        False while Left (deferred).
        """
        return self._queue_is_active()

    def _player_has_open_clip(self) -> bool:
        """True when the player is showing real media (not the idle poster).

        Steam DASH previews only set ``_preview_clip_path`` (not
        ``_active_play_media_path``, which is for flat rendered files). After
        first frame, awaiting clears — so the idle-poster check is the
        authority: queue encode may stamp a path without leaving the poster.
        """
        if hasattr(self, "_is_player_idle_placeholder"):
            try:
                if self._is_player_idle_placeholder():
                    return False
            except RuntimeError:
                return False
        if getattr(self, "_active_play_media_path", None):
            return True
        if getattr(self, "_preview_clip_path", None):
            return True
        # Mid-open: blank stack while first frame arrives (poster already left).
        if getattr(self, "_awaiting_first_frame", False):
            return True
        return False

    def _apply_player_idle_chrome(self) -> None:
        """Idle player header + center placeholder (Steempeg logo, no queue bleed)."""
        if hasattr(self, "_reset_player_placeholder_default"):
            self._reset_player_placeholder_default()
        elif hasattr(self, "place_logo") and hasattr(self, "place_text"):
            from steempeg.ui.icon_utils import apply_square_icon, app_logo_pixmap

            self.place_logo.setStyleSheet("background: transparent; border: none;")
            apply_square_icon(self.place_logo, app_logo_pixmap(80, dpr=1.0), 80)
            self.place_logo.show()
            self.place_text.setText("Please select a clip from the library")
            self.place_text.setStyleSheet(
                "color: #888888; font-size: 14px; font-weight: bold; margin-top: 15px;"
            )

        if hasattr(self, "custom_icon_label") and hasattr(self, "custom_text_label"):
            from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap
            from steempeg.ui.icon_utils import apply_square_icon
            from steempeg.ui.player_header_layout import (
                player_header_icon_px,
                set_player_header_game_text,
            )

            unknown = get_resource_path("unknown_icon.png")
            self.custom_icon_label.setStyleSheet("background: transparent; border: none;")
            hdr_px = player_header_icon_px(self)
            hdr_pix = shaped_game_icon_pixmap(QPixmap(unknown), hdr_px, ICON_SHAPE_CIRCLE)
            apply_square_icon(self.custom_icon_label, hdr_pix, hdr_px)
            set_player_header_game_text(
                self,
                "Choose a clip to preview...",
                placeholder=True,
            )
        if hasattr(self, "set_player_header_clip_controls_visible"):
            try:
                self.set_player_header_clip_controls_visible(False)
            except Exception:
                pass

    def _refresh_clip_queue_badges_safe(self) -> None:
        """Refresh ClipCard queue # circles; no-op if the mixin is absent."""
        if hasattr(self, "refresh_clip_queue_badges"):
            try:
                self.refresh_clip_queue_badges()
            except Exception:
                logging.debug("refresh_clip_queue_badges failed", exc_info=True)

    def _idle_dash_after_queue_work(self) -> bool:
        """True when dash should drop queue-job leftovers (Unknown / game line).

        While encode is live or jobs are still pending, the strip may follow the
        queue head. After the batch finishes with nothing open in the player,
        show Select-a-clip instead of a stale completed-job summary.
        """
        if self._player_has_open_clip():
            return False
        if getattr(self, "_is_rendering", False):
            return False
        if self._queue_pending_count() > 0:
            return False
        return True

    def _sync_queue_player_and_dash_chrome(self) -> None:
        """Split chrome: header = open clip; dash = Render Queue while active.

        Library diversion must not wipe the playing clip's logo / name / close /
        quality, and must not replace the Ready+#N strip with Select-a-clip.
        """
        open_clip = self._player_has_open_clip()
        # Dead / blocked export sits on the idle poster but still owns header chrome.
        bound_dead_export = bool(
            not open_clip and getattr(self, "_rendered_media_path", None)
        )

        if open_clip or bound_dead_export:
            # Header always follows the media on screen — never queue head.
            if open_clip:
                self._restore_header_from_library_selection()
            if hasattr(self, "set_player_header_clip_controls_visible"):
                try:
                    self.set_player_header_clip_controls_visible(True)
                except Exception:
                    pass
        else:
            self._apply_player_idle_chrome()

        # Dash / Ready cluster: queue-first whenever RQ owns Start (incl. diversion).
        if self._queue_is_active():
            if not self._sync_dash_queue_status_chrome():
                if not open_clip and self._idle_dash_after_queue_work():
                    if hasattr(self, "reset_bottom_summary"):
                        self.reset_bottom_summary()
        elif not open_clip:
            if hasattr(self, "reset_bottom_summary"):
                self.reset_bottom_summary()

        self._refresh_clip_queue_badges_safe()
        if hasattr(self, "update_playback_badge"):
            self.update_playback_badge()

    def _queue_drives_start_cta(self) -> bool:
        """True when Start should batch-render pending queue jobs."""
        return self._queue_is_active() and self._queue_pending_count() > 0

    def _queue_context_job(self):
        """Job that owns player-header identity while a clip is on screen.

        Follow the clip actually playing — never queue head when idle.
        Clicking a queue card plays it, so selection matches preview.
        Active render still wins during a batch.
        """
        if not self._queue_owns_identity_chrome():
            return None
        preview = getattr(self, "_preview_clip_path", None)
        preview_norm = os.path.normpath(preview) if preview else ""
        if not preview_norm:
            return None

        def _clip_matches(job) -> bool:
            if job is None:
                return False
            path = getattr(job, "clip_path", None) or ""
            return os.path.normpath(path) == preview_norm

        active = getattr(self, "_active_render_job", None)
        if active is not None:
            live = self.render_queue.get(getattr(active, "id", ""))
            if live is not None:
                return live
        selected_id = getattr(self, "_selected_queue_job_id", None)
        if selected_id:
            job = self.render_queue.get(selected_id)
            if job is not None and _clip_matches(job):
                return job
        job = self._queue_job_for_clip(preview_norm)
        if job is not None:
            return job
        # Playing a clip that is not queued — don't advertise Ready #1.
        return None

    def _dash_ready_queue_job(self):
        """Job for the Ready cluster digit + left summary — next to render only.

        The circle must stay on whatever will encode next (or the live encode),
        never the library / queue-card selection. Selection only drives the
        player-header ``In queue (N)`` plaque via ``_focused_queue_job_for_badge``.
        """
        if not self._queue_is_active():
            return None
        active = getattr(self, "_active_render_job", None)
        if active is not None:
            live = self.render_queue.get(getattr(active, "id", ""))
            if live is not None:
                return live
        pending = self.render_queue.next_queued()
        if pending is not None:
            return pending
        jobs = list(getattr(self.render_queue, "jobs", None) or [])
        return jobs[0] if jobs else None

    def _status_strip_context_job(self):
        """Job that owns the footer Ready strip (name/stats + numbered badge).

        Always the next-to-render / live encode job — selecting another ClipCard
        or queue row must not change the Ready # digit (that belongs on
        ``In queue (N)`` only).
        """
        return self._dash_ready_queue_job()

    def _apply_status_strip_summary(self, job) -> None:
        """Left dash line (icon + game • preset) for the status-strip job."""
        if job is None or not hasattr(self, "bottom_text_label"):
            return
        game_name = (getattr(job, "game_name", "") or "").strip() or "Steam Clip"
        self.bottom_text_label.setText(
            format_dash_job_summary(game_name, getattr(job, "settings", None))
        )

        cache_dir = getattr(self, "cache_dir", "") or ""
        target_icon = resolve_job_game_icon_path(cache_dir, job)
        unknown_icon_path = get_resource_path("unknown_icon.png")
        if not target_icon or not os.path.isfile(target_icon):
            target_icon = unknown_icon_path
        from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap

        is_unknown_icon = os.path.basename(target_icon).lower() == "unknown_icon.png"
        header_shape = ICON_SHAPE_CIRCLE if is_unknown_icon else None
        if hasattr(self, "_set_bottom_summary_icon"):
            self._set_bottom_summary_icon(target_icon)
            return
        if not hasattr(self, "bottom_icon_label"):
            return
        from steempeg.ui.icon_utils import apply_square_icon

        self.bottom_icon_label.setStyleSheet("background: transparent; border: none;")
        bottom_pix = QPixmap(target_icon)
        shaped = (
            shaped_game_icon_pixmap(bottom_pix, 24, header_shape)
            if not bottom_pix.isNull()
            else None
        )
        apply_square_icon(self.bottom_icon_label, shaped, 24)

    def _sync_player_header_to_queue_context(self) -> bool:
        """Drive header from the queue context job. False = no queue context."""
        job = self._queue_context_job()
        if job is None:
            # Queue is active but the playing clip is not the Ready/#1 job —
            # keep (or restore) identity from the clip on screen.
            if self._queue_owns_identity_chrome() and getattr(
                self, "_preview_clip_path", None
            ):
                self._restore_header_from_library_selection()
            return False
        self._apply_header_from_job(job)
        self._sync_dash_queue_status_chrome()
        return True

    def _restore_header_from_library_selection(self) -> None:
        """After the queue clears or Leave — fall back to Clips / Rendered selection.

        Header chrome only — never call ``update_rendered_selection`` here (that
        reloads MPV and resets playback position on tab / queue chrome sync).
        """
        preview = getattr(self, "_preview_clip_path", None)
        preview_norm = os.path.normpath(preview) if preview else ""

        # Prefer the media actually playing — table currentRow can still point at
        # a queue-highlighted card after a library preview diversion.
        if preview_norm and hasattr(self, "_resolved_rendered_meta") and os.path.isfile(
            preview_norm
        ):
            if hasattr(self, "custom_text_label"):
                from steempeg.ui.player_header_layout import set_player_header_game_text

                display_title, icon_path, _t, is_unknown, _k = self._resolved_rendered_meta(
                    preview_norm, os.path.basename(preview_norm)
                )
                extra = ["Unknown"] if is_unknown else []
                set_player_header_game_text(self, display_title, extra=extra)
                if icon_path and hasattr(self, "_set_player_header_game_icon"):
                    self._set_player_header_game_icon(icon_path=icon_path)
            return

        if preview_norm and hasattr(self.ui, "table_clips"):
            for r in range(self.ui.table_clips.rowCount()):
                item = self.ui.table_clips.item(r, 0)
                if item and os.path.normpath(item.data(Qt.UserRole) or "") == preview_norm:
                    self._apply_header_from_table_row(r)
                    return

        if hasattr(self.ui, "table_clips"):
            row = self.ui.table_clips.currentRow()
            if row >= 0:
                self._apply_header_from_table_row(row)
                return

    def _queue_controls_preview(self) -> bool:
        """Alias kept for library/grid hooks."""
        return self._queue_is_active()

    def _current_preview_clip_path(self):
        """Path of the clip currently shown in the player."""
        if getattr(self, "_preview_clip_path", None):
            return self._preview_clip_path
        if hasattr(self.ui, "table_clips") and self.ui.table_clips.currentRow() >= 0:
            item = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0)
            if item:
                return item.data(Qt.UserRole)
        job_id = getattr(self, "_selected_queue_job_id", None)
        if job_id:
            job = self.render_queue.get(job_id)
            if job:
                return job.clip_path
        return None

    def _active_preview_clip_path(self):
        return self._current_preview_clip_path()

    def _is_export_clip_path(self, path: str | None) -> bool:
        if not path or not os.path.isdir(path):
            return False
        if hasattr(self, "_is_valid_clip_path"):
            return self._is_valid_clip_path(path)
        return True

    def _is_rendered_export_path(self, path: str | None) -> bool:
        """True for a flat finished export file (Rendered videos), not a Steam clip folder."""
        if not path:
            return False
        try:
            if not os.path.isfile(path):
                return False
        except OSError:
            return False
        ext = os.path.splitext(path)[1].lower()
        try:
            from steempeg.ui.library.rendered_library import RENDERED_ALL_EXTS

            return ext in RENDERED_ALL_EXTS
        except Exception:
            return ext in {
                ".mp4",
                ".mkv",
                ".webm",
                ".mov",
                ".avi",
                ".m4v",
                ".mp3",
                ".wav",
                ".aac",
                ".flac",
                ".m4a",
                ".ogg",
                ".opus",
            }

    def _resolve_export_clip_path(self) -> str | None:
        """Steam clip folder for single export — survives library tab switches.

        While a finished export is on screen, never fall through to sticky Steam
        clip memory — that made START RENDER re-encode the previous clip from
        the Rendered videos tab. Queue-driven Start still uses pending jobs.
        """
        if hasattr(self, "_is_previewing_rendered_media") and self._is_previewing_rendered_media():
            return None

        preview = getattr(self, "_preview_clip_path", None)
        if self._is_export_clip_path(preview):
            path = os.path.normpath(preview)
            self._last_export_clip_path = path
            return path

        saved = getattr(self, "_saved_clips_selection_path", "")
        if self._is_export_clip_path(saved):
            path = os.path.normpath(saved)
            self._last_export_clip_path = path
            return path

        if hasattr(self.ui, "table_clips") and self.ui.table_clips.currentRow() >= 0:
            item = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0)
            if item:
                path = item.data(Qt.UserRole)
                if self._is_export_clip_path(path):
                    path = os.path.normpath(path)
                    self._last_export_clip_path = path
                    return path

        job_id = getattr(self, "_selected_queue_job_id", None)
        if job_id:
            job = self.render_queue.get(job_id)
            if job and self._is_export_clip_path(job.clip_path):
                path = os.path.normpath(job.clip_path)
                self._last_export_clip_path = path
                return path

        # Sticky: keep last Steam clip after preview switches (e.g. Screenshots).
        sticky = getattr(self, "_last_export_clip_path", None)
        if self._is_export_clip_path(sticky):
            return os.path.normpath(sticky)

        return None

    def _apply_header_from_table_row(self, selected_row: int) -> None:
        if selected_row < 0 or not hasattr(self.ui, "table_clips"):
            return
        game_item = self.ui.table_clips.item(selected_row, 0)
        if not game_item:
            return
        game_name = game_item.text()
        # Col 2 = ``date\\ntime``; col 3 = duration (not clock time).
        clip_date = self.ui.table_clips.item(selected_row, 2)
        clip_dur = self.ui.table_clips.item(selected_row, 3)
        date_text = clip_date.text() if clip_date else ""
        duration_text = clip_dur.text() if clip_dur else ""
        if hasattr(self, "custom_text_label"):
            from steempeg.ui.player_header_layout import (
                set_player_header_game_text,
                split_clip_date_cell,
            )

            date_part, time_part = split_clip_date_cell(date_text)
            set_player_header_game_text(
                self,
                game_name,
                date=date_part,
                time=time_part,
                duration=duration_text,
            )
        clip_path = game_item.data(Qt.UserRole)
        self._set_player_header_game_icon(clip_path=clip_path)

    def _set_player_header_game_icon(
        self,
        *,
        clip_path: str | None = None,
        icon_path: str | None = None,
    ) -> None:
        """Set custom_icon_label from disk path with Settings → Visual shape."""
        if not hasattr(self, "custom_icon_label"):
            return
        from steempeg.infra.paths import get_resource_path
        from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap

        path = icon_path or ""
        if not path and clip_path:
            parts = os.path.basename(str(clip_path)).split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                path = os.path.join(self.cache_dir, f"{parts[1]}.jpg")
        if not path:
            path = getattr(self, "current_game_icon", "") or ""
        unknown = get_resource_path("unknown_icon.png")
        if path and os.path.isfile(path):
            self.current_game_icon = path
        if not path or not os.path.isfile(path):
            path = unknown
        is_unknown = os.path.basename(path).lower() == "unknown_icon.png"
        self.custom_icon_label.setStyleSheet("background: transparent; border: none;")
        src = QPixmap(path)
        from steempeg.ui.icon_utils import apply_square_icon
        from steempeg.ui.player_header_layout import player_header_icon_px

        icon_px = player_header_icon_px(self)
        shaped = None
        if not src.isNull():
            shape = ICON_SHAPE_CIRCLE if is_unknown else None
            shaped = shaped_game_icon_pixmap(src, icon_px, shape)
        apply_square_icon(self.custom_icon_label, shaped, icon_px)

    def _handle_clips_manager_selection_with_queue(self, clip_path: str, selected_row: int) -> None:
        """Preview from Clips Manager while queue mode is on (not Left).

        Queued card click → activate that job (queue-first chrome).
        Any other library card → play it and bind header/dash to that clip
        (Preview diversion) until Leave, Resume, or a queue card is chosen.
        """
        self._flush_current_trim_state()
        clip_path = os.path.normpath(clip_path)
        if hasattr(self, "_is_valid_clip_path") and not self._is_valid_clip_path(clip_path):
            logging.warning("Ignored invalid clip selection: %s", clip_path)
            return
        if hasattr(self, "_clear_rendered_selection_visual"):
            self._clear_rendered_selection_visual()
        self._saved_rendered_selection_path = ""
        self._preview_clip_path = clip_path
        self._rendered_media_path = None
        if self._is_export_clip_path(clip_path):
            self._last_export_clip_path = os.path.normpath(clip_path)

        # Clip is queued — activate the right card rather than always the first.
        # If one of this clip's duplicate cards is already selected, stay on it
        # (the user is switching library rows to a clip already loaded in the player).
        # Otherwise activate the first (or only) matching card.
        queue_job = self.render_queue.find_by_clip_path(clip_path)
        if queue_job:
            clip_norm = os.path.normpath(clip_path)
            selected_id = getattr(self, "_selected_queue_job_id", None)
            if selected_id:
                selected = self.render_queue.get(selected_id)
                if (
                    selected is not None
                    and os.path.normpath(selected.clip_path or "") == clip_norm
                ):
                    # Already on a card for this clip — refresh header only.
                    self._apply_header_from_table_row(selected_row)
                    if hasattr(self, "set_player_header_clip_controls_visible"):
                        self.set_player_header_clip_controls_visible(True)
                    self.refresh_render_queue_panel(sync_splitter=False)
                    self.update_playback_badge()
                    return
            self.activate_queue_job(queue_job.id)
            return

        trim_restore = self._session_state_for_clip(clip_path)
        self._selected_queue_job_id = None
        self._queue_library_preview_diversion = True
        self._apply_header_from_table_row(selected_row)

        if hasattr(self, "set_player_header_clip_controls_visible"):
            self.set_player_header_clip_controls_visible(True)
        # Play first — Source Info XML / folder size must not block first frame.
        self.generate_and_play_preview(clip_path, trim_restore=trim_restore)
        self._schedule_quality_populate_after_open(clip_path, trim_restore)
        # Selection only — never inflate Render Queue from a library click.
        self.refresh_render_queue_panel(sync_splitter=False)
        self.update_playback_badge()
        self._update_start_button_label()
        if hasattr(self, "_sync_library_mode_chrome"):
            if not getattr(self, "_render_dock_visible", False):
                self._sync_library_mode_chrome()
        if hasattr(self, "_schedule_persist_library_ui_state"):
            self._schedule_persist_library_ui_state()
        elif hasattr(self, "_persist_library_ui_state"):
            self._persist_library_ui_state()
        if not getattr(self, "_is_rendering", False):
            self.update_status_indicator("Ready", "ready")

    def _queue_persist_path(self) -> str:
        return os.path.join(self.cache_dir, "render_queue.json")

    def _queue_history_path(self) -> str:
        return os.path.join(self.cache_dir, "render_queue_history.json")

    def _archive_batch_to_history(self, *, cancelled: bool = False) -> None:
        started = getattr(self, "_batch_started_at", None)
        if not started:
            return
        batch = snapshot_queue_batch(
            self.render_queue, started_at=started, cancelled=cancelled,
        )
        self._batch_started_at = None
        if not batch.jobs:
            return
        try:
            append_batch(self._queue_history_path(), batch)
            self._invalidate_render_history_cache()
        except OSError as exc:
            logging.warning("Could not save render history: %s", exc)

    def _archive_single_render_to_history(self, job, output_file: str) -> None:
        from steempeg.render.queue_history import append_batch, snapshot_completed_job

        try:
            append_batch(self._queue_history_path(), snapshot_completed_job(job, output_file))
            self._invalidate_render_history_cache()
        except OSError as exc:
            logging.warning("Could not save render history: %s", exc)

    def _save_render_companion_meta(self, job, output_file: str) -> None:
        if not output_file or not job:
            return
        try:
            from steempeg.core.rendered_health import (
                apply_assessment_to_companion,
                assess_rendered_health,
            )
            from steempeg.core.rendered_media import (
                duration_from_source_clip,
                is_sane_media_duration,
                parse_app_id_from_clip_folder,
                parse_app_id_from_name,
                save_rendered_companion_meta,
            )

            clip_name = os.path.basename(job.clip_path or "")
            app_id = parse_app_id_from_name(clip_name) or parse_app_id_from_clip_folder(clip_name)
            expected_sec = None
            s = job.settings
            if s.is_trim_mode and s.trim_end_ms > s.trim_start_ms:
                expected_sec = (s.trim_end_ms - s.trim_start_ms) / 1000.0
            elif not s.is_trim_mode:
                # Full-clip job: source length is a fair abort/mismatch check.
                # Trim jobs must NOT use full source — that caused false "849s vs 12s".
                expected_sec = duration_from_source_clip(job.clip_path)
            if not is_sane_media_duration(expected_sec):
                expected_sec = None

            quality = getattr(s, "quality_text", "") or ""
            stream_copy = "Original" in quality and "Target File" not in quality

            save_rendered_companion_meta(
                output_file,
                app_id=app_id,
                game_name=job.game_name,
                clip_path=job.clip_path,
                game_icon_path=job.game_icon_path,
                duration_sec=None,
                expected_duration_sec=expected_sec,
                stream_copy=stream_copy,
                cache_dir=getattr(self, "cache_dir", None),
            )
            assessment = assess_rendered_health(
                output_file,
                expected_duration_sec=expected_sec,
                cache_dir=getattr(self, "cache_dir", None),
            )
            apply_assessment_to_companion(
                output_file,
                assessment,
                cured=False,
                stream_copy=stream_copy,
                expected_duration_sec=expected_sec,
                extra={
                    "app_id": app_id or "",
                    "game_name": job.game_name or "",
                    "clip_path": job.clip_path or "",
                    "game_icon_path": job.game_icon_path or "",
                },
                cache_dir=getattr(self, "cache_dir", None),
            )
            if hasattr(self, "_store_rendered_health_cache"):
                self._store_rendered_health_cache(output_file, assessment)
            self._rendered_output_meta_index = None
        except Exception as exc:
            logging.debug("Rendered companion meta not saved: %s", exc)

    def _show_batch_complete_dialog(self, jobs=None) -> None:
        from steempeg.ui.batch_complete_dialog import BatchCompleteChoice, BatchCompleteDialog
        from steempeg.ui import design_tokens as tok

        jobs = list(jobs if jobs is not None else self.render_queue.jobs)
        if not jobs:
            return
        theme = tok.chrome_theme_colors(getattr(self, "_chrome_theme", tok.DEFAULT_CHROME_THEME))
        always_clear = bool(
            self.load_user_settings().get("always_clear_render_queue_after_batch", True)
        )
        parent = self.ui.window() if hasattr(self.ui, "window") else self.ui
        dlg = BatchCompleteDialog(
            jobs,
            parent=parent,
            bar_color=theme["title_bar"],
            bg_color=theme["app_bg"],
            always_clear_queue=always_clear,
        )
        dlg.open_output_requested.connect(self.open_rendered_file)
        dlg.open_in_rendered_requested.connect(self.open_in_rendered_videos)
        dlg.open_source_clip_requested.connect(self.open_source_clip)
        if always_clear:
            self._clear_render_queue_silent()
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        self.save_user_settings("always_clear_render_queue_after_batch", dlg.always_clear_queue())
        if not accepted:
            return
        if dlg.choice() == BatchCompleteChoice.OPEN_HISTORY:
            self.show_render_queue_history()
        elif dlg.always_clear_queue():
            self._clear_render_queue_silent()

    def _show_render_complete_dialog(self, job, output_file: str) -> None:
        from steempeg.ui import design_tokens as tok
        from steempeg.ui.render_complete_dialog import RenderCompleteChoice, RenderCompleteDialog

        theme = tok.chrome_theme_colors(getattr(self, "_chrome_theme", tok.DEFAULT_CHROME_THEME))
        clip_path = getattr(job, "clip_path", None)
        queue_rows = (
            self.render_queue.find_all_by_clip_path(clip_path)
            if clip_path and hasattr(self, "render_queue")
            else []
        )
        show_clear = bool(queue_rows)
        always_clear = bool(
            self.load_user_settings().get("always_clear_render_queue_after_batch", True)
        )
        if show_clear and always_clear:
            self._remove_clip_from_render_queue(clip_path)
            show_clear = False
        parent = self.ui.window() if hasattr(self.ui, "window") else self.ui
        dlg = RenderCompleteDialog(
            job,
            output_file,
            parent=parent,
            bar_color=theme["title_bar"],
            bg_color=theme["app_bg"],
            show_clear_queue=show_clear,
            always_clear_queue=always_clear,
        )
        dlg.open_in_rendered_requested.connect(self.open_in_rendered_videos)
        dlg.raise_()
        dlg.activateWindow()
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        if show_clear:
            self.save_user_settings(
                "always_clear_render_queue_after_batch", dlg.clear_queue()
            )
            if accepted and dlg.clear_queue():
                self._remove_clip_from_render_queue(clip_path)
        if not accepted:
            return
        choice = dlg.choice()
        if choice == RenderCompleteChoice.OPEN_FOLDER:
            self.open_rendered_folder(output_file)
        elif choice == RenderCompleteChoice.PLAY:
            self.open_rendered_file(output_file)
        elif choice == RenderCompleteChoice.OPEN_HISTORY:
            self.show_render_queue_history()

    def show_render_queue_history(self) -> None:
        from steempeg.ui.render_queue_history import RenderQueueHistoryDialog

        from steempeg.ui import design_tokens as tok
        from steempeg.ui import ui_theme as ut

        batches = getattr(self, "_render_history_cache", None)
        if batches is None:
            batches = load_history(self._queue_history_path())
            self._render_history_cache = batches
        if ut.get_ui_theme() == ut.UI_THEME_DEFAULT:
            theme = tok.chrome_theme_colors(
                getattr(self, "_chrome_theme", tok.DEFAULT_CHROME_THEME)
            )
        else:
            theme = ut.chrome_colors_for_active()
        dlg = RenderQueueHistoryDialog(
            batches, parent=self.ui, bar_color=theme["title_bar"], bg_color=theme["app_bg"]
        )
        dlg.open_output_requested.connect(self.open_rendered_file)
        dlg.open_in_rendered_requested.connect(self.open_in_rendered_videos)
        dlg.open_source_clip_requested.connect(self.open_source_clip)
        if dlg.exec() == 2:
            clear_history(self._queue_history_path())
            self._render_history_cache = []
            self._rendered_output_meta_index = None

    def preload_render_history(self, *, announce: bool = False) -> None:
        """Load render history JSON off the UI thread (startup / refresh)."""
        if getattr(self, "_history_preload_running", False):
            return
        if getattr(self, "_render_history_cache", None) is not None and not announce:
            return

        from steempeg.ui.library.history_load_worker import HistoryLoadWorker

        path = self._queue_history_path()
        self._history_preload_running = True
        if announce and hasattr(self, "update_status_indicator"):
            self.update_status_indicator("Loading render history…", "busy", scan_phase="search")

        worker = HistoryLoadWorker(path, parent=self.ui if hasattr(self, "ui") else None)
        self._history_load_worker = worker

        def _ok(batches):
            self._history_preload_running = False
            self._render_history_cache = batches or []
            self._rendered_output_meta_index = None
            if announce and hasattr(self, "update_status_indicator"):
                self.update_status_indicator("Ready", "ready")
            logging.info("Render history preloaded: %d batches", len(self._render_history_cache))

        def _fail(msg: str):
            self._history_preload_running = False
            self._render_history_cache = []
            if announce and hasattr(self, "update_status_indicator"):
                self.update_status_indicator("Ready", "ready")
            logging.warning("Render history preload failed: %s", msg)

        worker.finished_ok.connect(_ok)
        worker.failed.connect(_fail)
        worker.start()

    def _invalidate_render_history_cache(self) -> None:
        self._render_history_cache = None
        self._rendered_output_meta_index = None

    def _persist_render_queue(self) -> None:
        try:
            save_queue_to_file(self._queue_persist_path(), self.render_queue)
        except OSError as exc:
            logging.warning("Could not save render queue: %s", exc)

    def _persist_render_queue_async(self) -> None:
        """Snapshot queue JSON on the UI thread; write the file off-thread.

        Used after Add so disk I/O does not contend with card rebuild on the
        same click. Other call sites keep the synchronous persist (quit-safe).
        """
        import json
        import threading

        if bool(getattr(self, "_queue_persist_busy", False)):
            # Prior async write still running — sync so the newer snapshot wins.
            self._persist_render_queue()
            return

        try:
            path = self._queue_persist_path()
            payload = self.render_queue.to_json_list()
        except Exception:
            logging.exception("Could not snapshot render queue for async save")
            self._persist_render_queue()
            return

        self._queue_persist_busy = True

        def _write() -> None:
            try:
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2)
            except OSError as exc:
                logging.warning("Could not save render queue: %s", exc)
            finally:
                self._queue_persist_busy = False

        threading.Thread(
            target=_write, name="steempeg-queue-persist", daemon=True
        ).start()

    def _load_persisted_render_queue(self) -> None:
        if not hasattr(self, "render_queue"):
            return
        loaded = load_queue_from_file(self._queue_persist_path())
        if loaded:
            self.render_queue = loaded
            self._selected_queue_job_id = None

    def _update_start_button_label(self) -> None:
        if not hasattr(self.ui, "btn_start"):
            return
        pending = self._queue_pending_count() if self._queue_drives_start_cta() else 0
        btn = self.ui.btn_start
        # Desktop: white startrender glyph before the label.
        if not getattr(self, "_portable_shell", False):
            from PySide6.QtCore import QSize

            from steempeg.ui.icon_assets import start_render_icon

            icon_sz = 16
            btn.setIcon(start_render_icon(icon_sz))
            btn.setIconSize(QSize(icon_sz, icon_sz))
            if pending > 0:
                btn.setText(f" Render Queue ({pending})")
            else:
                btn.setText(" START RENDER")
        else:
            if pending > 0:
                btn.setText(f"🚩 Render Queue ({pending})")
            else:
                btn.setText("🚩 START RENDER")
        # Any label refresh must not leave a pending queue with a dead Start button.
        if self._queue_drives_start_cta() and not getattr(self, "_is_rendering", False):
            btn.setEnabled(True)
        if getattr(self, "_portable_shell", False):
            from steempeg.ui.portable import sync_portable_render_button

            sync_portable_render_button(self)
        else:
            self._sync_dash_render_settings_button()

    def _ensure_dash_render_settings_button(self) -> None:
        """Purple «Render Settings» next to Start — Like a Portable mode only."""
        if getattr(self, "btn_render_settings", None) is not None:
            try:
                self.btn_render_settings.objectName()
                return
            except RuntimeError:
                pass
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QPushButton, QSizePolicy

        from steempeg.ui.icon_assets import preview_settings_icon

        style = getattr(self, "_dash_btn_style_render_settings", None)
        if not style:
            style = (
                "QPushButton {{ font-family: <<FONT>>; "
                "font-size: {font}px; font-weight: bold; background-color: #5a4b7a; color: #ffffff; "
                "border: 2px solid #8e7cc3; border-radius: {radius}px; padding: {pad}; }}"
                "QPushButton:hover {{ background-color: #6b5a8e; border: 2px solid #b29ae7; }}"
                "QPushButton:pressed {{ background-color: #3a324a; border: 2px solid #8e7cc3; }}"
                "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
            )
            self._dash_btn_style_render_settings = style

        from steempeg.ui.ui_density import COMFORT

        dense = getattr(self, "_ui_density", None) or COMFORT
        btn = QPushButton()
        btn.setObjectName("btn_render_settings")
        btn.setText(" Render Settings")
        btn.setIcon(preview_settings_icon(16))
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Open render settings in a floating window (click again to close)")
        btn.setAutoDefault(False)
        btn.setDefault(False)
        btn.setFixedHeight(int(getattr(dense, "dash_btn_h", 36)))
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(self._dash_render_settings_qss())
        btn.clicked.connect(self.toggle_desktop_render_settings)
        self.btn_render_settings = btn
        self._sync_dash_render_settings_button()

    def _dash_render_settings_qss(self, *, border: str | None = None) -> str:
        """Stock Render Settings QSS (current density). Optional live border color."""
        from steempeg.ui.ui_density import COMFORT

        dense = getattr(self, "_ui_density", None) or COMFORT
        pad = "1px 8px" if getattr(dense, "compact", False) else "6px 14px"
        radius = max(8, int(getattr(dense, "dash_btn_h", 36)) // 2)
        font = int(getattr(dense, "dash_font", 12))
        template = getattr(self, "_dash_btn_style_render_settings", None) or (
            "QPushButton {{ font-family: <<FONT>>; "
            "font-size: {font}px; font-weight: bold; background-color: #5a4b7a; color: #ffffff; "
            "border: 2px solid #8e7cc3; border-radius: {radius}px; padding: {pad}; }}"
            "QPushButton:hover {{ background-color: #6b5a8e; border: 2px solid #b29ae7; }}"
            "QPushButton:pressed {{ background-color: #3a324a; border: 2px solid #8e7cc3; }}"
            "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
        )
        fmt = getattr(self, "_fmt_dash_btn", None)
        if callable(fmt):
            qss = fmt(template, font=font, radius=radius, pad=pad)
        else:
            qss = template.replace("<<FONT>>", tok.FONT_APP).format(
                font=font, radius=radius, pad=pad
            )
        if border:
            # Only the outline breathes — swap stock + hover border tokens.
            qss = qss.replace("#8e7cc3", border).replace("#b29ae7", border)
        return qss

    def _ensure_dash_render_settings_breath(self):
        from steempeg.ui.widgets.soft_accent_breath import SoftAccentBorderBreath

        breath = getattr(self, "_dash_render_settings_breath", None)
        btn = getattr(self, "btn_render_settings", None)
        if btn is None:
            return None
        if breath is not None:
            try:
                if breath._button is btn:
                    return breath
            except RuntimeError:
                pass
        breath = SoftAccentBorderBreath(
            btn,
            style_builder=lambda c: self._dash_render_settings_qss(border=c),
            from_color="#f2eef8",
            to_color="#b29ae7",
            parent=btn,
        )
        self._dash_render_settings_breath = breath
        return breath

    def _sync_dash_render_settings_button(self) -> None:
        btn = getattr(self, "btn_render_settings", None)
        if btn is None:
            return
        show = self._desktop_render_layout_is_portable_like()
        btn.setVisible(show)
        open_dlg = getattr(self, "_desktop_render_settings_dlg", None)
        is_open = False
        is_minimized = False
        try:
            if open_dlg is not None:
                open_dlg.objectName()
                if hasattr(open_dlg, "is_parked_minimized"):
                    is_minimized = bool(open_dlg.is_parked_minimized())
                else:
                    is_minimized = bool(open_dlg.isMinimized())
                is_open = bool(open_dlg.isVisible()) and not is_minimized
        except RuntimeError:
            is_open = False
            is_minimized = False
        if is_open:
            btn.setText(" Close Settings")
        else:
            btn.setText(" Render Settings")

        # Breath only while yellow-minimized — soft light↔purple outline cue.
        breath = self._ensure_dash_render_settings_breath()
        if breath is None:
            return
        stock = self._dash_render_settings_qss()
        if show and is_minimized:
            if not breath.active:
                btn.setStyleSheet(stock)
            breath.start()
        else:
            breath.stop(restore_style=stock)

    def _desktop_render_layout_is_portable_like(self) -> bool:
        if getattr(self, "_portable_shell", False):
            return False
        from steempeg.ui.settings_prefs import (
            DESKTOP_RENDER_LIKE_A_PORTABLE,
            load_desktop_render_layout,
        )

        settings = {}
        if hasattr(self, "load_user_settings"):
            try:
                settings = self.load_user_settings() or {}
            except Exception:
                settings = {}
        return load_desktop_render_layout(settings) == DESKTOP_RENDER_LIKE_A_PORTABLE

    def _portable_like_middle_splitter_enabled(self) -> bool:
        if not self._desktop_render_layout_is_portable_like():
            return False
        from steempeg.ui.settings_prefs import load_portable_like_middle_splitter

        settings = {}
        if hasattr(self, "load_user_settings"):
            try:
                settings = self.load_user_settings() or {}
            except Exception:
                settings = {}
        return load_portable_like_middle_splitter(settings)

    def apply_desktop_render_layout(self) -> None:
        """Apply Settings → It's a Desktop / Like a Portable (live, no restart)."""
        # Legacy Trim-adjacent Render CTA — always off (replaced by dash button).
        legacy = getattr(self, "btn_player_render", None)
        if legacy is not None:
            try:
                legacy.hide()
            except RuntimeError:
                pass
        portable_like = self._desktop_render_layout_is_portable_like()
        bottom = getattr(self, "bottom_v_wrap", None)
        neo = getattr(self, "neo_wrapper", None)
        garage = getattr(self, "_neo_chrome_garage", None)
        bottom_still_glued = False
        if bottom is not None:
            try:
                bottom_still_glued = int(bottom.maximumHeight()) < 100000
            except RuntimeError:
                bottom_still_glued = False
        neo_parked = bool(
            getattr(self, "_neo_dock_home", None)
            or (neo is not None and garage is not None and neo.parentWidget() is garage)
        )
        leaving_portable = not portable_like and (
            bool(getattr(self, "_desktop_layout_was_portable_like", False))
            or bottom_still_glued
            or neo_parked
        )
        if not portable_like:
            from steempeg.ui.desktop_render_settings import close_desktop_render_settings

            close_desktop_render_settings(self)
        # Before chrome mutates the splitter: remember a tall Desktop dock so
        # Like a Portable glue cannot overwrite settings.json.
        if portable_like and not getattr(self, "_desktop_layout_was_portable_like", False):
            self._snapshot_desktop_v_splitter_before_portable_like()
        self._desktop_layout_was_portable_like = bool(portable_like)
        self._sync_dash_render_settings_button()
        self._sync_portable_like_dock_chrome(
            restore_v_sizes=leaving_portable or portable_like
        )
        try:
            from steempeg.ui.portable_splitter_reveal import (
                sync_portable_splitter_reveal,
            )

            sync_portable_splitter_reveal(self)
        except Exception:
            pass
        if portable_like:
            # Second pass after layout settles — keep user close, else glue open.
            QTimer.singleShot(0, self._settle_portable_like_dash)
        elif leaving_portable:
            # Second pass: neo stretch + splitter sizes after reparent/show.
            QTimer.singleShot(0, self._settle_desktop_dock_layout)
        elif hasattr(self, "_desktop_v_splitter_looks_minimal") and hasattr(
            self, "_apply_desktop_main_v_splitter_sizes"
        ):
            # Cold Desktop start / density pass: don't leave a dash-height stub.
            if self._desktop_v_splitter_looks_minimal():
                self._apply_desktop_main_v_splitter_sizes()

    def _settle_portable_like_dash(self) -> None:
        if not self._desktop_render_layout_is_portable_like():
            return
        self._reapply_portable_like_middle_gap()

    def _settle_desktop_dock_layout(self) -> None:
        """Re-apply Desktop dock geometry after Portable→Desktop reparent settles."""
        if self._desktop_render_layout_is_portable_like():
            return
        self._sync_portable_like_dock_chrome(restore_v_sizes=True)

    def _snapshot_desktop_v_splitter_before_portable_like(self) -> None:
        """Keep Desktop dock sizes in memory before glue shrinks the pane.

        Disk is only written by the Desktop drag/close path — never from this
        snapshot — so a cold start into Like a Portable cannot clobber a saved
        Desktop preference with construction defaults.
        """
        v_split = getattr(self, "main_v_splitter", None)
        if v_split is None:
            return
        live = list(v_split.sizes())
        if len(live) < 2:
            return
        dash_h = max(int(self._dash_only_bottom_height()), 1)
        if int(live[1]) <= dash_h + 48:
            return
        if not getattr(self, "_pre_portable_like_v_sizes", None):
            self._pre_portable_like_v_sizes = live

    def _floating_render_settings_holds_neo(self) -> bool:
        """True when Desktop floating settings or Portable Render sheet owns neo.

        Must NOT require dialog visibility. ``DesktopRenderSettingsDialog.__init__``
        registers itself then calls dock chrome sync *before* ``show()`` — an
        ``isVisible()`` gate re-parks neo into the chrome garage and leaves the
        settings host empty black (Desktop Like a Portable + Portable sheet).

        Stale closed-dialog refs must NOT count: that blocked classic Desktop
        neo reclaim and left a tall black void above the dash on clip select.
        """
        neo = getattr(self, "neo_wrapper", None)
        from steempeg.ui.desktop_render_settings import DesktopRenderSettingsDialog
        from steempeg.ui.portable.sheets import PortableRenderSettingsDialog

        # Authoritative: neo already lives under a settings host.
        if neo is not None:
            try:
                w = neo.parentWidget()
            except RuntimeError:
                w = None
            while w is not None:
                if isinstance(
                    w, (DesktopRenderSettingsDialog, PortableRenderSettingsDialog)
                ):
                    return True
                w = w.parentWidget()

        # Mid-init / open: dialog registered and not yet returned neo.
        dlg = getattr(self, "_desktop_render_settings_dlg", None)
        if dlg is not None:
            try:
                dlg.objectName()
                if not getattr(dlg, "_returned", False):
                    return True
            except RuntimeError:
                if getattr(self, "_desktop_render_settings_dlg", None) is dlg:
                    self._desktop_render_settings_dlg = None

        sheet = getattr(self, "_portable_render_sheet_dlg", None)
        if sheet is not None:
            try:
                sheet.objectName()
                # Warm / open sheet claims neo for its right column (stub or live).
                if getattr(sheet, "_neo", None) is not None or getattr(
                    self, "_portable_render_settings_open", False
                ):
                    return True
            except RuntimeError:
                if getattr(self, "_portable_render_sheet_dlg", None) is sheet:
                    self._portable_render_sheet_dlg = None

        return False

    def _neo_is_parked_in_chrome_garage(self) -> bool:
        neo = getattr(self, "neo_wrapper", None)
        garage = getattr(self, "_neo_chrome_garage", None)
        if neo is None or garage is None:
            return False
        try:
            return neo.parentWidget() is garage
        except RuntimeError:
            return False

    def _ensure_docked_neo_visible_for_context(self) -> None:
        """Classic Desktop: don't leave a tall empty dock when neo is parked.

        Like a Portable keeps neo in the floating window / garage by design.
        Classic Desktop must re-dock neo whenever the bottom chrome is meant to
        show settings (clip, queue, or empty stub — never a black void).
        """
        if getattr(self, "_portable_shell", False):
            return
        if self._desktop_render_layout_is_portable_like():
            return
        if self._floating_render_settings_holds_neo():
            return
        if not (
            self._neo_is_parked_in_chrome_garage()
            or getattr(self, "_neo_dock_home", None)
        ):
            return
        self._restore_neo_to_dock_layout()

    def _dash_content_height(self) -> int:
        """Uncompressed render-dashboard height (density metrics, not live geometry).

        Like a Portable glue used to accept any live ``dash.height()`` in
        ``[80, hint+24]``. Mid-layout that locked a too-short pane and vertically
        squashed Start / Render Settings / Pause / Cancel / Logs.
        """
        dense = getattr(self, "_ui_density", None)
        btn_h = int(getattr(dense, "dash_btn_h", 36) or 36) if dense else 36
        mv = int(getattr(dense, "dash_margin_v", 16) or 16) if dense else 16
        sp = int(getattr(dense, "dash_spacing", 12) or 12) if dense else 12
        # status row 24 + %/bar row (label taller than the 6px bar) + 2px card border
        font = int(getattr(dense, "dash_font", 13) or 13) if dense else 13
        pct_row = max(6, font + 6)
        metric = (mv * 2) + (sp * 2) + 24 + pct_row + btn_h + 2
        metric = max(metric, 120)
        dash = getattr(self, "render_dashboard", None)
        if dash is None:
            return metric
        hint = int(dash.sizeHint().height() or 0)
        if hint < 80:
            hint = int(dash.minimumSizeHint().height() or 0)
        # Honour sizeHint when it is close to metrics; ignore stretch-inflated values.
        if 80 <= hint <= metric + 48:
            return max(hint, metric)
        return metric

    def _dash_only_bottom_height(self) -> int:
        """Exact height for the glued render-control strip (no black padding)."""
        from steempeg.ui.layout_defaults import (
            MAIN_V_SPLIT_BOTTOM_PAD,
            PORTABLE_LIKE_MIDDLE_GAP,
        )

        if self._desktop_render_layout_is_portable_like():
            if self._portable_like_middle_splitter_enabled():
                pad = 0
            else:
                pad = int(PORTABLE_LIKE_MIDDLE_GAP)
        else:
            pad = int(MAIN_V_SPLIT_BOTTOM_PAD)
        return pad + self._dash_content_height()

    def _set_main_v_splitter_handle_visible(self, visible: bool) -> None:
        """Show/hide the player↔dash handle (Like a Portable default keeps it gone)."""
        v_split = getattr(self, "main_v_splitter", None)
        if v_split is None:
            return
        try:
            if visible:
                width = int(getattr(self, "_pre_portable_like_v_handle_width", 0) or 0)
                if width <= 0:
                    width = 6
                v_split.setHandleWidth(width)
                if v_split.count() >= 2:
                    handle = v_split.handle(1)
                    if handle is not None:
                        handle.setEnabled(True)
                        handle.show()
            else:
                live = int(v_split.handleWidth() or 0)
                if live > 0:
                    self._pre_portable_like_v_handle_width = live
                v_split.setHandleWidth(0)
                if v_split.count() >= 2:
                    handle = v_split.handle(1)
                    if handle is not None:
                        handle.setEnabled(False)
                        handle.hide()
        except RuntimeError:
            return

    def _pin_dash_queue_header_buttons(self) -> None:
        """Keep Start / Render Settings / Pause / Cancel / Logs from stretching tall.

        Horizontal Expanding is intentional (equal-width row). Vertical must stay
        Fixed + fixed height so a tall bottom pane cannot blow the buttons up.
        """
        from PySide6.QtWidgets import QSizePolicy

        dense = getattr(self, "_ui_density", None)
        btn_h = int(getattr(dense, "dash_btn_h", 36) or 36)
        names = ("btn_start", "btn_pause", "btn_cancel", "btn_logs")
        ui = getattr(self, "ui", None)
        pinned = []
        for name in names:
            btn = getattr(ui, name, None) if ui is not None else None
            if btn is not None:
                pinned.append(btn)
        settings_btn = getattr(self, "btn_render_settings", None)
        if settings_btn is not None:
            pinned.append(settings_btn)
        leave_btn = getattr(self, "_btn_queue_leave_resume", None)
        if leave_btn is not None:
            pinned.append(leave_btn)
        for btn in pinned:
            try:
                btn.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
                btn.setFixedHeight(btn_h)
                btn.setAutoDefault(False)
                btn.setDefault(False)
            except RuntimeError:
                if btn is leave_btn:
                    self._btn_queue_leave_resume = None

    def _ensure_neo_chrome_garage(self):
        """Off-layout host so neo cannot leave a void in bottom_v_wrap."""
        g = getattr(self, "_neo_chrome_garage", None)
        if g is not None:
            try:
                g.objectName()
                return g
            except RuntimeError:
                pass
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        host = getattr(self, "ui", None)
        g = QWidget(host)
        g.setObjectName("neoChromeGarage")
        g.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        g.hide()
        g.setFixedSize(0, 0)
        lay = QVBoxLayout(g)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._neo_chrome_garage = g
        return g

    def _ensure_dash_in_bottom_wrap(self) -> None:
        """Keep the render dash in bottom_v_wrap (early neo-park can strand it in top)."""
        dash = getattr(self, "render_dashboard", None)
        bottom = getattr(self, "bottom_v_wrap", None)
        if dash is None or bottom is None:
            return
        if dash.parentWidget() is bottom:
            return
        prev = dash.parentWidget()
        prev_lay = prev.layout() if prev is not None else None
        if prev_lay is not None:
            prev_lay.removeWidget(dash)
        lay = bottom.layout()
        if lay is not None:
            lay.addWidget(dash)
            lay.setStretchFactor(dash, 0)

    def _park_neo_away_from_dock(self) -> None:
        """Pull neo out of the vertical splitter so the dash can glue to the bottom."""
        neo = getattr(self, "neo_wrapper", None)
        if neo is None or self._floating_render_settings_holds_neo():
            return
        # Shell still assembling — leave neo in the right-panel tree so the
        # v-splitter routes neo + dash into bottom_v_wrap together.
        if getattr(self, "main_v_splitter", None) is None:
            neo.hide()
            return
        garage = self._ensure_neo_chrome_garage()
        if neo.parentWidget() is garage:
            neo.hide()
            return
        from steempeg.ui.portable.sheets import _borrow_widget

        if not getattr(self, "_neo_dock_home", None):
            self._neo_dock_home = _borrow_widget(neo)
        else:
            parent = neo.parentWidget()
            lay = parent.layout() if parent is not None else None
            if lay is not None:
                lay.removeWidget(neo)
            else:
                from steempeg.ui.portable.sheets import _reparent_borrowed

                _reparent_borrowed(neo)
        garage.layout().addWidget(neo)
        neo.hide()

    def _restore_neo_to_dock_layout(self) -> None:
        """Put neo back into bottom_v_wrap above the dash (It's a Desktop)."""
        from PySide6.QtWidgets import QSizePolicy

        neo = getattr(self, "neo_wrapper", None)
        if neo is None or self._floating_render_settings_holds_neo():
            return
        bottom = getattr(self, "bottom_v_wrap", None)
        if bottom is None or bottom.layout() is None:
            return
        lay = bottom.layout()
        dash = getattr(self, "render_dashboard", None)

        # Detach from garage / stale parent — always re-dock into bottom_v_wrap.
        # No setParent(None): that maps a brief top-level HWND at (0,0).
        parent = neo.parentWidget()
        if parent is not None:
            prev_lay = parent.layout()
            if prev_lay is not None:
                prev_lay.removeWidget(neo)

        insert_at = 0
        if dash is not None:
            for i in range(lay.count()):
                item = lay.itemAt(i)
                if item is not None and item.widget() is dash:
                    insert_at = i
                    break
        lay.insertWidget(insert_at, neo)
        self._neo_dock_home = None

        neo.setMaximumHeight(16777215)
        neo.setMinimumHeight(0)
        neo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        neo.show()
        lay.setStretchFactor(neo, 1)
        if dash is not None:
            lay.setStretchFactor(dash, 0)
            # Ensure dash stays the footer strip under neo.
            if dash.parentWidget() is not bottom:
                self._ensure_dash_in_bottom_wrap()
            else:
                # Keep dash after neo even if insert shifted indices.
                dash_idx = -1
                neo_idx = -1
                for i in range(lay.count()):
                    item = lay.itemAt(i)
                    w = item.widget() if item is not None else None
                    if w is neo:
                        neo_idx = i
                    elif w is dash:
                        dash_idx = i
                if neo_idx >= 0 and dash_idx >= 0 and dash_idx < neo_idx:
                    lay.removeWidget(dash)
                    lay.addWidget(dash)
                    lay.setStretchFactor(dash, 0)

    def _unlock_portable_like_dash_for_drag(self) -> None:
        """Lift glued min/max so the v-splitter handle can actually move."""
        bottom = getattr(self, "bottom_v_wrap", None)
        if bottom is None:
            return
        dash_h = max(int(self._dash_only_bottom_height()), 1)
        bottom.setMinimumHeight(0)
        # Cap at dash height — reopenable, but no air gap above the strip.
        bottom.setMaximumHeight(dash_h)

    def _apply_portable_like_dash_closed(self, closed: bool) -> None:
        """Binary dock: open = exact dash height; closed = 0 but still drag-openable."""
        v_split = getattr(self, "main_v_splitter", None)
        bottom = getattr(self, "bottom_v_wrap", None)
        if v_split is None:
            return
        sizes = v_split.sizes()
        total = sum(sizes) if sizes and sum(sizes) > 0 else max(int(v_split.height() or 0), 1)
        dash_h = max(int(self._dash_only_bottom_height()), 1)
        self._portable_like_dash_closed = bool(closed)
        self._portable_like_snap_lock = True
        try:
            if closed:
                if bottom is not None:
                    # Never maxHeight=0 — that glued the pane shut permanently.
                    bottom.setMinimumHeight(0)
                    bottom.setMaximumHeight(dash_h)
                v_split.setSizes([total, 0])
            else:
                if bottom is not None:
                    bottom.setMinimumHeight(dash_h)
                    bottom.setMaximumHeight(dash_h)
                v_split.setSizes([max(total - dash_h, 1), dash_h])
        finally:
            self._portable_like_snap_lock = False

    def _portable_like_snap_after_drag(self) -> None:
        """End a handle drag (release or debounce) and binary-snap the dash."""
        self._portable_like_dash_dragging = False
        timer = getattr(self, "_portable_like_snap_timer", None)
        if timer is not None:
            timer.stop()
        if getattr(self, "_portable_like_snap_lock", False):
            return
        if not self._desktop_render_layout_is_portable_like():
            return
        self._snap_portable_like_v_splitter()

    def _ensure_portable_like_splitter_guard(self) -> None:
        if getattr(self, "_portable_like_splitter_guard_connected", False):
            return
        v_split = getattr(self, "main_v_splitter", None)
        if v_split is None:
            return
        v_split.splitterMoved.connect(self._on_portable_like_v_splitter_moved)

        host = self

        class _HandleGuard(QObject):
            def eventFilter(self, obj, event):  # noqa: ANN001
                if not host._desktop_render_layout_is_portable_like():
                    return False
                et = event.type()
                if et == QEvent.Type.MouseButtonPress:
                    if event.button() == Qt.MouseButton.LeftButton:
                        host._portable_like_dash_dragging = True
                        host._unlock_portable_like_dash_for_drag()
                elif et == QEvent.Type.MouseButtonRelease:
                    if event.button() == Qt.MouseButton.LeftButton:
                        host._portable_like_snap_after_drag()
                return False

        guard = _HandleGuard(v_split)
        self._portable_like_handle_guard = guard
        if v_split.count() >= 2:
            handle = v_split.handle(1)
            if handle is not None:
                handle.installEventFilter(guard)
        self._portable_like_splitter_guard_connected = True

    def _on_portable_like_v_splitter_moved(self, _pos: int = 0, _index: int = 0) -> None:
        if not self._desktop_render_layout_is_portable_like():
            return
        if getattr(self, "_portable_like_snap_lock", False):
            return
        # While dragging: leave sizes alone; snap on mouse release (debounced fallback).
        if getattr(self, "_portable_like_dash_dragging", False):
            timer = getattr(self, "_portable_like_snap_timer", None)
            if timer is None:
                parent = getattr(self, "main_v_splitter", None)
                timer = QTimer(parent)
                timer.setSingleShot(True)
                timer.timeout.connect(self._portable_like_snap_after_drag)
                self._portable_like_snap_timer = timer
            timer.start(120)
            return
        # Non-drag size change (programmatic / edge cases) — snap immediately.
        self._unlock_portable_like_dash_for_drag()
        self._snap_portable_like_v_splitter()

    def _glue_portable_like_dash_open(self) -> None:
        """Force bottom pane to exact dash height (no threshold / no air gap)."""
        self._apply_portable_like_dash_closed(False)

    def _reapply_portable_like_middle_gap(self, *, glue: bool = True) -> None:
        """Re-assert player↔dash air gap after library chrome or layout settle.

        ``_sync_library_mode_chrome`` used to stamp a Desktop-only 10px pad on
        ``top_v_wrap`` and only re-glue the splitter — margins stayed wrong on
        cold start until clip select ran the same glue path.
        """
        if not self._desktop_render_layout_is_portable_like():
            return
        from steempeg.ui.layout_defaults import PORTABLE_LIKE_MIDDLE_GAP

        middle_splitter = self._portable_like_middle_splitter_enabled()
        top = getattr(self, "top_v_wrap", None)
        if top is not None:
            top_lay = top.layout()
            if top_lay is not None:
                top_lay.setContentsMargins(0, 0, 0, 0)

        bottom = getattr(self, "bottom_v_wrap", None)
        if bottom is not None:
            lay = bottom.layout()
            if lay is not None:
                if middle_splitter:
                    lay.setContentsMargins(0, 0, 0, 0)
                else:
                    lay.setContentsMargins(0, int(PORTABLE_LIKE_MIDDLE_GAP), 0, 0)

        if middle_splitter:
            self._set_main_v_splitter_handle_visible(True)
            self._ensure_portable_like_splitter_guard()
        else:
            self._set_main_v_splitter_handle_visible(False)
            try:
                from steempeg.ui.portable_splitter_reveal import (
                    sync_portable_splitter_reveal,
                )

                sync_portable_splitter_reveal(self)
            except Exception:
                pass

        if not glue:
            return
        if getattr(self, "_portable_like_dash_closed", False):
            self._apply_portable_like_dash_closed(True)
        else:
            self._glue_portable_like_dash_open()

    def _snap_portable_like_v_splitter(self) -> None:
        """Open = exact dash height glued down; drag small → close (0). Nothing else."""
        v_split = getattr(self, "main_v_splitter", None)
        if v_split is None:
            return
        sizes = v_split.sizes()
        if len(sizes) < 2:
            return
        dash_h = max(int(self._dash_only_bottom_height()), 1)
        threshold = max(28, dash_h // 2)
        was_closed = bool(getattr(self, "_portable_like_dash_closed", False))
        # From shut: any real upward drag opens (don't require half height mid-gesture).
        if was_closed:
            closed = sizes[1] <= 8
        else:
            closed = sizes[1] < threshold
        self._apply_portable_like_dash_closed(closed)

    def _sync_portable_like_dock_chrome(self, *, restore_v_sizes: bool = True) -> None:
        """Like a Portable: dash glued to bottom; middle splitter optional."""
        from PySide6.QtWidgets import QSizePolicy

        neo = getattr(self, "neo_wrapper", None)
        bottom = getattr(self, "bottom_v_wrap", None)
        v_split = getattr(self, "main_v_splitter", None)
        portable_like = self._desktop_render_layout_is_portable_like()
        floating = self._floating_render_settings_holds_neo()

        hw = getattr(self, "hide_watcher", None)
        if hw is not None and hasattr(hw, "set_suppressed"):
            # Suppress while we reparent / setSizes — neo.show() must not race
            # HideWatcher. Portable-like and portable shell keep it suppressed.
            hw.set_suppressed(True)

        # Button visibility can sync before the v-splitter exists; dock geometry waits.
        if v_split is None:
            if portable_like and not floating:
                if neo is not None:
                    neo.hide()
            if hw is not None and hasattr(hw, "set_suppressed"):
                hw.set_suppressed(
                    bool(portable_like)
                    or bool(getattr(self, "_portable_shell", False))
                )
            return

        if not portable_like:
            from steempeg.ui.layout_defaults import (
                DESKTOP_BOTTOM_PANE_SPACING,
                MAIN_V_SPLIT_BOTTOM_PAD,
                MAIN_V_SPLIT_TOP_PAD,
            )

            # Unlock glue BEFORE re-docking neo so stretch can fill the pane.
            top = getattr(self, "top_v_wrap", None)
            if top is not None:
                top_lay = top.layout()
                if top_lay is not None:
                    top_lay.setContentsMargins(0, 0, 0, MAIN_V_SPLIT_TOP_PAD)
            if bottom is not None:
                bottom.setMaximumHeight(16777215)
                bottom.setMinimumHeight(0)
                bottom.setSizePolicy(
                    QSizePolicy.Policy.Preferred,
                    QSizePolicy.Policy.Preferred,
                )
                lay = bottom.layout()
                if lay is not None:
                    lay.setContentsMargins(0, MAIN_V_SPLIT_BOTTOM_PAD, 0, 0)
                    lay.setSpacing(DESKTOP_BOTTOM_PANE_SPACING)
            self._ensure_dash_in_bottom_wrap()
            self._restore_neo_to_dock_layout()
            dash = getattr(self, "render_dashboard", None)
            if dash is not None:
                dash.setSizePolicy(
                    QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
                )
                self._pin_dash_queue_header_buttons()
            self._set_main_v_splitter_handle_visible(True)
            v_split.setStretchFactor(0, 1)
            v_split.setStretchFactor(1, 1)
            if restore_v_sizes:
                saved = getattr(self, "_pre_portable_like_v_sizes", None)
                if saved and len(saved) >= 2 and saved[1] > 80:
                    total = (
                        sum(v_split.sizes())
                        if sum(v_split.sizes()) > 0
                        else max(int(v_split.height() or 0), 1)
                    )
                    from steempeg.ui.layout_defaults import (
                        scale_main_v_splitter_sizes,
                    )

                    ui = getattr(self, "ui", None)
                    avail_h = int((ui.height() if ui is not None else 0) or 0)
                    v_split.setSizes(
                        scale_main_v_splitter_sizes(
                            saved, total, window_height=avail_h or total
                        )
                    )
                    self._pre_portable_like_v_sizes = None
                elif not floating and hasattr(
                    self, "_apply_desktop_main_v_splitter_sizes"
                ):
                    self._apply_desktop_main_v_splitter_sizes()
                elif not floating:
                    from steempeg.ui.layout_defaults import (
                        restore_v_splitter_sizes,
                    )

                    v_split.setSizes(
                        restore_v_splitter_sizes(v_split.height())
                    )
            self._portable_like_dash_closed = False
            if hw is not None and hasattr(hw, "set_suppressed"):
                hw.set_suppressed(bool(getattr(self, "_portable_shell", False)))
            # Safety: classic Desktop must never keep neo parked after a layout pass.
            if hasattr(self, "_ensure_docked_neo_visible_for_context"):
                try:
                    self._ensure_docked_neo_visible_for_context()
                except Exception:
                    pass
            return

        # --- Like a Portable ---
        # Floating Render Settings already owns neo — do NOT re-glue / setSizes the
        # main v-splitter here. That was the 1–2s open lag (neo borrow + full dock
        # sync × N). Dash geometry stays as-is until settings close.
        if floating:
            if hw is not None and hasattr(hw, "set_suppressed"):
                hw.set_suppressed(True)
            return

        self._park_neo_away_from_dock()
        self._ensure_dash_in_bottom_wrap()

        dash = getattr(self, "render_dashboard", None)
        if dash is not None:
            dash.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            content_h = max(int(self._dash_content_height()), 1)
            dash.setMinimumHeight(content_h)
            dash.setMaximumHeight(content_h)
            self._pin_dash_queue_header_buttons()

        if bottom is not None:
            # No stretch void above the dash inside the bottom pane.
            lay = bottom.layout()
            if lay is not None:
                if getattr(self, "_pre_portable_like_bottom_spacing", None) is None:
                    self._pre_portable_like_bottom_spacing = int(lay.spacing())
                lay.setSpacing(0)
                # Drop leftover spacers that used to sit under neo.
                for i in range(lay.count() - 1, -1, -1):
                    item = lay.itemAt(i)
                    if item is None:
                        continue
                    if item.spacerItem() is not None:
                        lay.removeItem(item)
                    w = item.widget()
                    if w is not None and w is not dash and w is not neo:
                        # Keep unknown siblings, but don't let them stretch.
                        lay.setStretchFactor(w, 0)
                if dash is not None:
                    lay.setStretchFactor(dash, 0)
            bottom.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        sizes = v_split.sizes()
        if not getattr(self, "_pre_portable_like_v_sizes", None):
            if sizes and len(sizes) >= 2 and sizes[1] > self._dash_only_bottom_height() + 40:
                self._pre_portable_like_v_sizes = list(sizes)
        v_split.setStretchFactor(0, 1)
        v_split.setStretchFactor(1, 0)
        # Glued open on entry; middle handle (when enabled) allows drag shut.
        self._portable_like_dash_closed = False
        self._reapply_portable_like_middle_gap()

    def toggle_desktop_render_settings(self) -> None:
        from steempeg.ui.desktop_render_settings import toggle_desktop_render_settings

        toggle_desktop_render_settings(self)

    def focus_export_settings_panel(self) -> None:
        """Open Export Settings — Portable sheet, floating window, or neo Export tab."""
        if getattr(self, "_portable_shell", False):
            try:
                from steempeg.ui.portable.chrome import open_portable_render_settings

                open_portable_render_settings(self)
            except Exception:
                logging.exception("Open portable render settings failed")
            return
        if self._desktop_render_layout_is_portable_like():
            self.toggle_desktop_render_settings()
            return
        from steempeg.ui.settings_prefs import RENDER_TAB_EXPORT, apply_default_render_tab

        apply_default_render_tab(self, RENDER_TAB_EXPORT)
        neo = getattr(self, "neo_wrapper", None)
        if neo is not None:
            neo.show()
            neo.raise_()
        scroll = getattr(self, "right_scroll", None)
        if scroll is not None:
            scroll.ensureVisible(0, 0)

    def _apply_desktop_dash_render_icons(self) -> None:
        """White glyphs on desktop Start / Pause / Cancel (portable keeps emoji labels)."""
        if getattr(self, "_portable_shell", False):
            return
        from PySide6.QtCore import QSize

        from steempeg.ui.icon_assets import (
            cancel_render_icon,
            logs_info_icon,
            pause_render_icon,
            start_render_icon,
        )

        icon_sz = 16
        size = QSize(icon_sz, icon_sz)
        if hasattr(self.ui, "btn_start"):
            self.ui.btn_start.setIcon(start_render_icon(icon_sz))
            self.ui.btn_start.setIconSize(size)
        if hasattr(self.ui, "btn_pause"):
            self.ui.btn_pause.setIcon(pause_render_icon(icon_sz))
            self.ui.btn_pause.setIconSize(size)
            # Keep leading space so icon doesn't glue to the label.
            text = (self.ui.btn_pause.text() or "Pause").strip()
            self.ui.btn_pause.setText(f" {text}")
        if hasattr(self.ui, "btn_cancel"):
            self.ui.btn_cancel.setIcon(cancel_render_icon(icon_sz))
            self.ui.btn_cancel.setIconSize(size)
            text = (self.ui.btn_cancel.text() or "Cancel").strip()
            self.ui.btn_cancel.setText(f" {text}")
        if hasattr(self.ui, "btn_logs"):
            self.ui.btn_logs.setIcon(logs_info_icon(icon_sz))
            self.ui.btn_logs.setIconSize(size)
            text = (self.ui.btn_logs.text() or "Logs").strip()
            self.ui.btn_logs.setText(f" {text}")

    def _set_desktop_pause_label(self, text: str) -> None:
        if not hasattr(self.ui, "btn_pause"):
            return
        label = (text or "Pause").strip()
        if getattr(self, "_portable_shell", False):
            self.ui.btn_pause.setText(label)
        else:
            self.ui.btn_pause.setText(f" {label}")

    def _queue_pending_count(self) -> int:
        if not hasattr(self, "render_queue"):
            return 0
        return int(self.render_queue.pending_count())

    def _sync_start_render_enabled(self, *, combo_valid: bool | None = None) -> None:
        """Enable Start for a selected clip, or for pending jobs while queue mode is on."""
        if not hasattr(self.ui, "btn_start"):
            return
        if getattr(self, "_is_rendering", False):
            self.ui.btn_start.setEnabled(False)
        else:
            if self._queue_drives_start_cta():
                enabled = True
            elif combo_valid is not None:
                enabled = bool(combo_valid)
            else:
                enabled = bool(self._resolve_export_clip_path())
            self.ui.btn_start.setEnabled(enabled)
        self._update_start_button_label()
        if getattr(self, "_portable_shell", False):
            from steempeg.ui.portable import sync_portable_render_button

            sync_portable_render_button(self)
        elif hasattr(self, "_sync_portable_render_strip"):
            self._sync_portable_render_strip()

    def _capture_trim_state(self) -> dict:
        if not hasattr(self, "custom_timeline"):
            return {"is_trim_mode": False, "trim_start_ms": 0, "trim_end_ms": 0}
        return {
            "is_trim_mode": bool(self.custom_timeline.is_trim_mode),
            "trim_start_ms": int(self.custom_timeline.trim_start_ms),
            "trim_end_ms": int(self.custom_timeline.trim_end_ms),
        }

    def _capture_clip_session_state(self) -> dict:
        state = dict(_DEFAULT_CLIP_SESSION)
        state.update(self._capture_trim_state())
        if hasattr(self, "custom_timeline"):
            tl = self.custom_timeline
            state["zoom_level"] = float(getattr(tl, "zoom_level", 1.0))
            bar = tl.horizontalScrollBar()
            state["scroll_x"] = int(bar.value()) if bar is not None else 0
        ui = self.ui
        if hasattr(ui, "combo_container"):
            state["container"] = ui.combo_container.currentText()
        if hasattr(ui, "combo_codec"):
            state["codec_text"] = ui.combo_codec.currentText()
        if hasattr(ui, "combo_audio_format"):
            state["audio_format"] = ui.combo_audio_format.currentText()
        if hasattr(ui, "combo_output_preset"):
            state["output_preset"] = ui.combo_output_preset.currentText()
        if hasattr(ui, "check_audio_only"):
            state["audio_only"] = bool(ui.check_audio_only.isChecked())
        if hasattr(ui, "check_mute_audio"):
            state["mute_audio"] = bool(ui.check_mute_audio.isChecked())
        return state

    def _session_state_for_clip(self, clip_path: str) -> dict:
        clip_path = os.path.normpath(clip_path)
        memory = getattr(self, "_clip_session_memory", None) or {}
        if clip_path in memory:
            return dict(memory[clip_path])
        job = self.render_queue.find_by_clip_path(clip_path)
        if job:
            return self._session_state_from_job_settings(job)
        return dict(_DEFAULT_CLIP_SESSION)

    def _session_state_from_job_settings(self, job) -> dict:
        """Build UI session from a *specific* queue job (duplicates share clip_path)."""
        s = job.settings
        state = dict(_DEFAULT_CLIP_SESSION)
        state.update(
            {
                "is_trim_mode": bool(s.is_trim_mode),
                "trim_start_ms": int(s.trim_start_ms or 0),
                "trim_end_ms": int(s.trim_end_ms or 0),
                "container": s.container_format or state["container"],
                "codec_text": s.codec_text or state["codec_text"],
                "audio_format": s.audio_format or state["audio_format"],
                "output_preset": s.output_preset or state["output_preset"],
                "audio_only": bool(s.audio_only),
                "mute_audio": bool(s.mute_audio),
            }
        )
        # Zoom/scroll may be remembered per job without poisoning the path slot.
        saved = (getattr(self, "_queue_job_session_memory", None) or {}).get(job.id)
        if saved:
            state["zoom_level"] = float(
                saved.get("zoom_level", state.get("zoom_level", 1.0))
            )
            state["scroll_x"] = int(saved.get("scroll_x", state.get("scroll_x", 0)))
        return state

    def _enable_all_output_combo_items(self) -> None:
        ui = self.ui
        for name in ("combo_container", "combo_codec", "combo_audio_format"):
            combo = getattr(ui, name, None)
            if combo is None:
                continue
            model = combo.model()
            if model is None:
                continue
            for i in range(combo.count()):
                item = model.item(i)
                if item is not None:
                    item.setEnabled(True)

    def _apply_export_session_state(self, state: dict, *, silent: bool = True) -> None:
        """Restore per-clip export container/codec/audio toggles."""
        ui = self.ui
        defaults = _DEFAULT_CLIP_SESSION
        self._enable_all_output_combo_items()
        blockers = []
        for name in (
            "combo_container",
            "combo_codec",
            "combo_audio_format",
            "combo_output_preset",
            "check_audio_only",
            "check_mute_audio",
        ):
            w = getattr(ui, name, None)
            if w is not None and hasattr(w, "blockSignals"):
                w.blockSignals(True)
                blockers.append(w)

        container = state.get("container", defaults["container"])
        codec = state.get("codec_text", defaults["codec_text"])
        audio_fmt = state.get("audio_format", defaults["audio_format"])
        preset = state.get("output_preset", defaults["output_preset"])

        if hasattr(ui, "combo_container"):
            idx = find_enabled_combo_text(ui.combo_container, container)
            if idx < 0:
                idx = find_enabled_combo_text(ui.combo_container, defaults["container"])
            if idx >= 0:
                ui.combo_container.setCurrentIndex(idx)
        if hasattr(ui, "combo_codec"):
            idx = find_enabled_combo_text(ui.combo_codec, codec)
            if idx < 0:
                idx = find_enabled_combo_text(ui.combo_codec, defaults["codec_text"])
            if idx >= 0:
                ui.combo_codec.setCurrentIndex(idx)
        if hasattr(ui, "combo_audio_format"):
            idx = find_enabled_combo_text(ui.combo_audio_format, audio_fmt)
            if idx < 0:
                idx = find_enabled_combo_text(ui.combo_audio_format, defaults["audio_format"])
            if idx >= 0:
                ui.combo_audio_format.setCurrentIndex(idx)
        if hasattr(ui, "combo_output_preset"):
            idx = ui.combo_output_preset.findText(preset)
            if idx < 0:
                idx = ui.combo_output_preset.findText(defaults["output_preset"])
            if idx >= 0:
                ui.combo_output_preset.setCurrentIndex(idx)
        if hasattr(ui, "check_audio_only"):
            ui.check_audio_only.setChecked(bool(state.get("audio_only", False)))
        if hasattr(ui, "check_mute_audio"):
            ui.check_mute_audio.setChecked(bool(state.get("mute_audio", False)))

        for w in blockers:
            w.blockSignals(False)

        if hasattr(ui, "tab_video"):
            ui.tab_video.setEnabled(not (hasattr(ui, "check_audio_only") and ui.check_audio_only.isChecked()))
        if hasattr(ui, "tab_audio"):
            ui.tab_audio.setEnabled(not (hasattr(ui, "check_mute_audio") and ui.check_mute_audio.isChecked()))

        self.refresh_output_format_availability()
        self._sync_original_audio_controls()
        if not silent and hasattr(self, "update_final_setup"):
            self.update_final_setup()

    def _reset_export_to_custom_defaults(self) -> None:
        """When the user picks Custom preset, start from standard MP4/H.264/AAC."""
        self._apply_export_session_state(dict(_DEFAULT_CLIP_SESSION), silent=True)

    def _apply_clip_session_state(self, state: dict | None, *, silent: bool = True) -> None:
        state = state or dict(_DEFAULT_CLIP_SESSION)
        if hasattr(self, "apply_trim_state"):
            self.apply_trim_state(
                bool(state.get("is_trim_mode", False)),
                int(state.get("trim_start_ms", 0)),
                int(state.get("trim_end_ms", 0)),
                silent=silent,
            )
        if hasattr(self, "custom_timeline"):
            self.custom_timeline.set_zoom_state(
                float(state.get("zoom_level", 1.0)),
                int(state.get("scroll_x", 0)),
            )
        self._apply_export_session_state(state, silent=silent)

    def _flush_clip_session_state(self) -> None:
        clip_path = getattr(self, "_preview_clip_path", None)
        if not clip_path:
            return
        state = self._capture_clip_session_state()
        norm = os.path.normpath(clip_path)
        job = self._queue_job_for_preview_sync(clip_path)
        if job and job.status in (JobStatus.QUEUED, JobStatus.ERROR):
            job.settings.is_trim_mode = bool(state["is_trim_mode"])
            job.settings.trim_start_ms = int(state["trim_start_ms"])
            job.settings.trim_end_ms = int(state["trim_end_ms"])
            if not hasattr(self, "_queue_job_session_memory"):
                self._queue_job_session_memory = {}
            self._queue_job_session_memory[job.id] = state
            # Do NOT write shared path memory while a queue job owns the preview —
            # duplicate cards of the same clip would inherit each other's Trim.
            return
        if not hasattr(self, "_clip_session_memory"):
            self._clip_session_memory = {}
        self._clip_session_memory[norm] = state

    def _flush_current_trim_state(self) -> None:
        self._flush_clip_session_state()

    def _sync_queue_trim_from_timeline(self) -> bool:
        """Update only trim fields on the queued job for the clip being previewed."""
        if getattr(self, "_loading_queue_job", False):
            return False
        if not hasattr(self, "custom_timeline"):
            return False
        preview = self._current_preview_clip_path()
        if not preview:
            return False
        job = self._queue_job_for_preview_sync(preview)
        if not job or job.status not in (JobStatus.QUEUED, JobStatus.ERROR):
            return False
        job.settings.is_trim_mode = bool(self.custom_timeline.is_trim_mode)
        job.settings.trim_start_ms = int(self.custom_timeline.trim_start_ms)
        job.settings.trim_end_ms = int(self.custom_timeline.trim_end_ms)
        return True

    def _trim_state_for_clip(self, clip_path: str) -> dict:
        state = self._session_state_for_clip(clip_path)
        return {
            "is_trim_mode": bool(state["is_trim_mode"]),
            "trim_start_ms": int(state["trim_start_ms"]),
            "trim_end_ms": int(state["trim_end_ms"]),
        }

    def _persist_trim_for_current_clip(self) -> None:
        if getattr(self, "_loading_queue_job", False):
            return
        clip_path = self._current_preview_clip_path()
        if not clip_path:
            return
        state = self._capture_clip_session_state()
        norm = os.path.normpath(clip_path)
        job = self._queue_job_for_preview_sync(clip_path)
        if job and job.status in (JobStatus.QUEUED, JobStatus.ERROR):
            job.settings.is_trim_mode = bool(state["is_trim_mode"])
            job.settings.trim_start_ms = int(state["trim_start_ms"])
            job.settings.trim_end_ms = int(state["trim_end_ms"])
            if not hasattr(self, "_queue_job_session_memory"):
                self._queue_job_session_memory = {}
            self._queue_job_session_memory[job.id] = state
            if hasattr(self, "render_queue_panel"):
                self.render_queue_panel.patch_job_trim(job)
            return
        if not hasattr(self, "_clip_session_memory"):
            self._clip_session_memory = {}
        self._clip_session_memory[norm] = state
        if not self._queue_is_active():
            return
        job = self.render_queue.find_by_clip_path(clip_path)
        if not job or job.status not in (JobStatus.QUEUED, JobStatus.ERROR):
            return
        job.settings.is_trim_mode = bool(state["is_trim_mode"])
        job.settings.trim_start_ms = int(state["trim_start_ms"])
        job.settings.trim_end_ms = int(state["trim_end_ms"])
        if hasattr(self, "render_queue_panel"):
            self.render_queue_panel.patch_job_trim(job)

    def _apply_trim_from_job_settings(self, settings) -> None:
        if hasattr(self, "apply_trim_state"):
            self.apply_trim_state(
                settings.is_trim_mode,
                settings.trim_start_ms,
                settings.trim_end_ms,
            )

    def _sync_active_queue_job_from_ui(self) -> bool:
        """Push live export/trim UI into the queued job for the clip being previewed."""
        if getattr(self, "_loading_queue_job", False):
            return False
        preview = self._current_preview_clip_path()
        if not preview:
            return False
        job = self._queue_job_for_preview_sync(preview)
        if not job or job.status not in (JobStatus.QUEUED, JobStatus.ERROR):
            return False
        job.settings = snapshot_settings_from_ui(self)
        job.refresh_output_path()
        return True

    def _sync_ui_to_selected_job(self) -> None:
        self._sync_active_queue_job_from_ui()

    def _populate_quality_options_for_clip(
        self, clip_path: str, *, preserve_ui_selection: bool = True,
    ) -> None:
        """Fill render settings combos from clip metadata (no preview/header)."""
        clip_path = os.path.normpath(clip_path)
        current_quality = ""
        current_fps = ""
        current_bitrate = ""
        if preserve_ui_selection:
            current_quality = self.ui.combo_quality.currentText() if hasattr(self.ui, "combo_quality") else ""
            current_fps = self.ui.combo_fps.currentText() if hasattr(self.ui, "combo_fps") else ""
            current_bitrate = self.ui.combo_bitrate.currentText() if hasattr(self.ui, "combo_bitrate") else ""

        clip_folder_name = os.path.basename(clip_path)
        parts = clip_folder_name.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            self.current_game_icon = os.path.join(self.cache_dir, f"{parts[1]}.jpg")
        else:
            self.current_game_icon = ""

        if hasattr(self.ui, "input_filename"):
            self.ui.input_filename.setText(f"{clip_folder_name}_rendered")

        all_mpds = self.get_all_mpd_paths(clip_path)
        if hasattr(self, "update_clip_open_loading_progress"):
            self.update_clip_open_loading_progress(18)
        if not all_mpds:
            self.ui.source_label.setText("Source: No MPD files found")
            self.ui.orig_res_label.setText("Original resolution: Unknown")
            if hasattr(self.ui, "label_vbitrate"):
                self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            if hasattr(self.ui, "label_abitrate"):
                self.ui.label_abitrate.setText("Audio Bitrate: Unknown")
            self.ui.combo_quality.clear()
            return

        # Detect whether the source actually carries an audio track. Salvaged clips
        # (and some Steam recordings) have video only; without this the audio format/
        # bitrate combos would offer choices for a track that doesn't exist.
        self._current_clip_has_audio = self._detect_clip_has_audio(all_mpds)
        if hasattr(self, "update_clip_open_loading_progress"):
            self.update_clip_open_loading_progress(28)

        source_dirs = [os.path.dirname(m) for m in all_mpds]
        unique_source_dirs = list(dict.fromkeys(source_dirs))
        self.current_source_raw_paths = "\n".join(unique_source_dirs)

        if hasattr(self.ui.source_label, "set_sources"):
            self.ui.source_label.set_sources(unique_source_dirs)
        else:
            self.ui.source_label.setText("Source:\n" + "\n".join(unique_source_dirs))

        unique_resolutions = set()
        max_height = 0
        self.current_orig_bitrate = 0
        self.current_orig_audio_bitrate = 192
        for mpd_path in all_mpds:
            try:
                with open(mpd_path, "r", encoding="utf-8") as file:
                    content = file.read()
                    clip_full_path = os.path.dirname(mpd_path)
                    # Duration from XML only — folder_size walk deferred (thousands of chunks).
                    size_str, duration_str = self.get_clip_size_and_duration(
                        clip_full_path, content, measure_size=False
                    )
                    if hasattr(self.ui, "label_size"):
                        self.ui.label_size.setText(f"Size: {size_str}")
                    if hasattr(self.ui, "label_duration"):
                        self.ui.label_duration.setText(f"Time: {duration_str}")
                    # Keep SteempegUI header meta in sync once duration is known.
                    meta = getattr(self, "_player_header_meta", None)
                    if meta is not None and not meta.get("placeholder"):
                        from steempeg.ui.player_header_layout import (
                            refresh_player_header_text,
                            store_player_header_meta,
                        )

                        store_player_header_meta(
                            self,
                            title=str(meta.get("title") or ""),
                            date=str(meta.get("date") or ""),
                            time=str(meta.get("time") or ""),
                            duration=duration_str or "",
                            extra=list(meta.get("extra") or ()),
                        )
                        refresh_player_header_text(self)

                    fps_match = re.search(r'\bframeRate="(\d+)(?:/\d+)?"', content)
                    if fps_match:
                        self.current_orig_fps = int(fps_match.group(1))
                    else:
                        # Prefer XML; do not spawn ffprobe on the select path.
                        self.current_orig_fps = getattr(self, "current_orig_fps", 60) or 60

                    if hasattr(self.ui, "label_fps"):
                        self.ui.label_fps.setText(f"FPS: {self.current_orig_fps}")

                    height_match = re.search(r'\bheight="(\d+)"', content)
                    width_match = re.search(r'\bwidth="(\d+)"', content)
                    # Manifest bandwidth only — no chunk glob / ffprobe on UI thread.
                    peak_mbps = mpd.peak_video_mbps_from_content(content)
                    if peak_mbps > self.current_orig_bitrate:
                        self.current_orig_bitrate = peak_mbps

                    if height_match and width_match:
                        h = int(height_match.group(1))
                        w = int(width_match.group(1))
                        unique_resolutions.add(f"{w}x{h}")
                        if h > max_height:
                            max_height = h

                    # Audio bitrate from first readable AdaptationSet (no ffprobe).
                    if all_mpds and mpd_path == all_mpds[0]:
                        orig_audio_bitrate = mpd.audio_bitrate_kbps_from_content(content)
                        self.current_orig_audio_bitrate = orig_audio_bitrate
            except Exception:
                pass

        if clip_path and hasattr(self, "_schedule_clip_folder_size_label"):
            self._schedule_clip_folder_size_label(clip_path)

        # Rebuild audio combo once we know Original kbps from XML.
        orig_audio_bitrate = int(getattr(self, "current_orig_audio_bitrate", 192) or 192)
        if hasattr(self.ui, "combo_audio_bitrate"):
            self.ui.combo_audio_bitrate.blockSignals(True)
            self.ui.combo_audio_bitrate.clear()
            bitrates = [
                (320, "320 kbps (Best Quality)"),
                (256, "256 kbps (High Quality)"),
                (192, "192 kbps (Good Quality)"),
                (128, "128 kbps (Standard)"),
                (64, "64 kbps (Bad)"),
                (32, "32 kbps (Very bad)"),
            ]
            self.ui.combo_audio_bitrate.addItem(f"{orig_audio_bitrate} kbps (Original)")
            for val, text in bitrates:
                self.ui.combo_audio_bitrate.addItem(text)
                idx = self.ui.combo_audio_bitrate.count() - 1
                if val > orig_audio_bitrate + 15:
                    set_combo_item_enabled(
                        self.ui.combo_audio_bitrate,
                        idx,
                        False,
                        tooltip=f"Source audio is {orig_audio_bitrate} kbps — cannot increase.",
                    )
            self.ui.combo_audio_bitrate.insertSeparator(self.ui.combo_audio_bitrate.count())
            self.ui.combo_audio_bitrate.addItem("⚙️ Custom Audio...")
            self.ui.combo_audio_bitrate.blockSignals(False)

        if hasattr(self, "update_clip_open_loading_progress"):
            self.update_clip_open_loading_progress(40)

        if unique_resolutions:
            res_text = ", ".join(sorted(list(unique_resolutions)))
            audio_kbps = getattr(self, "current_orig_audio_bitrate", 192)
            self.ui.orig_res_label.setText(f"Original resolution: {res_text}")
            if hasattr(self.ui, "label_vbitrate"):
                self.ui.label_vbitrate.setText(
                    _source_vbitrate_label(getattr(self, "current_orig_bitrate", 0))
                )
            if hasattr(self.ui, "label_abitrate"):
                self.ui.label_abitrate.setText(f"Audio Bitrate: {audio_kbps} kbps")
        else:
            self.ui.orig_res_label.setText("Original resolution: Unknown")
            if hasattr(self.ui, "label_vbitrate"):
                self.ui.label_vbitrate.setText(
                    _source_vbitrate_label(getattr(self, "current_orig_bitrate", 0))
                )
            if hasattr(self.ui, "label_abitrate"):
                self.ui.label_abitrate.setText("Audio Bitrate: Unknown")
            max_height = 1080

        self.current_orig_height = max_height

        if hasattr(self.ui, "combo_quality"):
            self._rebuild_quality_preset_combo(
                max_height=max_height,
                preserve_text=current_quality if preserve_ui_selection else "",
            )

        if hasattr(self.ui, "combo_fps"):
            self.ui.combo_fps.clear()
            fps_val = getattr(self, "current_orig_fps", 60)
            self.ui.combo_fps.addItem(f"{fps_val} FPS (Original)")

            optional_fps = []
            if fps_val >= 60:
                optional_fps = [30, 15]
            elif fps_val >= 30:
                optional_fps = [15]
            for target in optional_fps:
                self.ui.combo_fps.addItem(f"{target} FPS")
            # Show common higher FPS greyed when source is lower (cannot invent frames).
            for target in (60, 30, 15):
                label = f"{target} FPS"
                if self.ui.combo_fps.findText(label) < 0 and target > fps_val:
                    self.ui.combo_fps.addItem(label)
                    idx = self.ui.combo_fps.count() - 1
                    set_combo_item_enabled(
                        self.ui.combo_fps,
                        idx,
                        False,
                        tooltip=f"Source is {fps_val} FPS — cannot upscale to {target} FPS.",
                    )

            self.ui.combo_fps.insertSeparator(self.ui.combo_fps.count())
            self.ui.combo_fps.addItem("⚙️ Custom FPS...")
            self.ui.combo_fps.setCurrentIndex(0)

        if preserve_ui_selection and current_fps and hasattr(self.ui, "combo_fps"):
            index = find_enabled_combo_text(self.ui.combo_fps, current_fps)
            if index >= 0:
                self.ui.combo_fps.setCurrentIndex(index)
        if preserve_ui_selection and current_bitrate and hasattr(self.ui, "combo_bitrate"):
            index = find_enabled_combo_text(self.ui.combo_bitrate, current_bitrate)
            if index >= 0:
                self.ui.combo_bitrate.setCurrentIndex(index)

        if not getattr(self, "_is_rendering", False):
            self.ui.btn_start.setEnabled(True)
        self.ui.btn_start.setEnabled(True)
        self.update_final_setup()
        # Enforce audio-track availability (disables audio choices for video-only clips).
        self._sync_original_audio_controls()
        self.refresh_output_format_availability()
        if hasattr(self, "refresh_player_header_info"):
            self.refresh_player_header_info(has_clip=True)

    def _quality_combo_item_meta(self, index: int = -1) -> dict:
        """UserRole payload for a Quality Preset combo row."""
        combo = getattr(self.ui, "combo_quality", None)
        if combo is None:
            return {}
        idx = int(index) if index is not None and int(index) >= 0 else combo.currentIndex()
        if idx < 0 or idx >= combo.count():
            return {}
        raw = combo.itemData(idx, Qt.ItemDataRole.UserRole)
        return dict(raw) if isinstance(raw, dict) else {}

    def _add_quality_combo_item(
        self,
        text: str,
        *,
        kind: str,
        name: str = "",
        height: int | None = None,
        enabled: bool = True,
    ) -> int:
        from steempeg.render.quality_presets import quality_item_meta
        from steempeg.ui.widgets.combo_chrome import set_combo_item_enabled

        combo = self.ui.combo_quality
        combo.addItem(text)
        idx = combo.count() - 1
        combo.setItemData(
            idx,
            quality_item_meta(kind=kind, name=name, height=height),
            Qt.ItemDataRole.UserRole,
        )
        if not enabled:
            set_combo_item_enabled(combo, idx, False)
        if kind == "header":
            from PySide6.QtCore import QSize

            # Beat popup QSS min-height so captions stay tight.
            combo.setItemData(idx, QSize(0, 20), Qt.ItemDataRole.SizeHintRole)
        return idx

    def _rebuild_quality_preset_combo(
        self, *, max_height: int = 0, preserve_text: str = ""
    ) -> None:
        """Fill Video Settings Quality Preset: Standard ladder + Custom recipes.

        Standard resolution rows are capped to the source height — never offer
        2160p/4320p (or any taller step) when the clip is e.g. 1440p. Missing
        height must not expand to the full Goddess ladder (that was the bug).
        """
        from steempeg.render.export_presets import list_preset_names, load_favourite_names
        from steempeg.render.quality_presets import (
            KIND_CUSTOM,
            KIND_HEADER,
            KIND_STANDARD,
            KIND_TARGET,
            TARGET_FILE_SIZE_LABEL,
            build_quality_presets,
            original_quality_label,
        )
        from steempeg.ui.widgets.combo_chrome import install_quality_section_header_delegate
        from steempeg.ui.widgets.quality_preset_dual_popup import (
            install_quality_preset_dual_popup,
        )

        combo = getattr(self.ui, "combo_quality", None)
        if combo is None:
            return

        install_quality_section_header_delegate(combo)
        install_quality_preset_dual_popup(combo)

        want = (preserve_text or "").strip()
        want_custom = ""
        # If the live selection is a Custom row, keep that recipe selected.
        cur_meta = self._quality_combo_item_meta()
        if cur_meta.get("kind") == KIND_CUSTOM and cur_meta.get("name"):
            want_custom = str(cur_meta.get("name") or "")

        # Prefer explicit arg, else last known clip height.
        src_h = int(max_height or 0) or int(
            getattr(self, "current_orig_height", 0) or 0
        )
        # Unknown source → conservative 1080 ladder (same as populate fallback),
        # never ``None`` (that used to dump 4320p/2160p for every clip).
        ladder_h = src_h if src_h > 0 else 1080

        combo.blockSignals(True)
        combo.clear()
        self.all_qualities = build_quality_presets(ladder_h)

        self._add_quality_combo_item(
            "Standard",
            kind=KIND_HEADER,
            enabled=False,
        )
        orig = original_quality_label(src_h if src_h > 0 else None)
        self._add_quality_combo_item(orig, kind=KIND_STANDARD, name="original")
        for preset_name, preset_height in self.all_qualities:
            self._add_quality_combo_item(
                preset_name,
                kind=KIND_STANDARD,
                name=preset_name,
                height=preset_height,
            )

        # Custom column: Target (built-in hybrid) + saved recipes.
        self._add_quality_combo_item(
            "Custom",
            kind=KIND_HEADER,
            enabled=False,
        )
        self._add_quality_combo_item(
            TARGET_FILE_SIZE_LABEL,
            kind=KIND_TARGET,
            name="target",
        )

        custom_names: list[str] = []
        try:
            custom_names = list_preset_names(self.load_user_settings)
            fav_set = set(load_favourite_names(self.load_user_settings))
        except Exception:
            custom_names = []
            fav_set = set()

        for name in custom_names:
            label = f"★ {name}" if name in fav_set else name
            self._add_quality_combo_item(
                label,
                kind=KIND_CUSTOM,
                name=name,
            )

        # Restore selection: prefer Custom recipe, else matching Standard text.
        # Drop preserved labels taller than the source (stale 4320p after a 1440 clip).
        restored = False
        if want_custom:
            for i in range(combo.count()):
                meta = combo.itemData(i, Qt.ItemDataRole.UserRole)
                if (
                    isinstance(meta, dict)
                    and meta.get("kind") == KIND_CUSTOM
                    and meta.get("name") == want_custom
                ):
                    combo.setCurrentIndex(i)
                    restored = True
                    break
        if not restored and want:
            index = find_enabled_combo_text(combo, want)
            if index >= 0:
                meta = combo.itemData(index, Qt.ItemDataRole.UserRole)
                row_h = (
                    int(meta.get("height") or 0)
                    if isinstance(meta, dict)
                    else 0
                )
                if row_h <= 0 or src_h <= 0 or row_h <= src_h:
                    combo.setCurrentIndex(index)
                    restored = True
        if not restored:
            # First enabled Standard row (skip header).
            for i in range(combo.count()):
                meta = combo.itemData(i, Qt.ItemDataRole.UserRole)
                if isinstance(meta, dict) and meta.get("kind") == KIND_STANDARD:
                    combo.setCurrentIndex(i)
                    break

        combo.setMaxVisibleItems(max(8, min(24, combo.count())))
        combo.blockSignals(False)
        self.update_bitrate_options()
        self.on_quality_mode_changed(combo.currentText())

    def on_quality_preset_combo_changed(self, text: str = "") -> None:
        """Video Settings Quality Preset: Standard ladder vs apply Custom recipe."""
        if getattr(self, "_bulk_settings_apply", False):
            return
        if getattr(self, "_quality_combo_applying_custom", False):
            return
        meta = self._quality_combo_item_meta()
        kind = str(meta.get("kind") or "")
        if kind == "header":
            return
        if kind == "custom":
            name = str(meta.get("name") or "").strip()
            if not name:
                return
            self._quality_combo_applying_custom = True
            try:
                self.apply_export_preset_to_panel(name)
            finally:
                self._quality_combo_applying_custom = False
            return
        # Standard / Target — leave custom-canon mode (checkmark drops).
        self._clear_active_custom_preset()
        self.update_bitrate_options()
        self.on_quality_mode_changed(text or self.ui.combo_quality.currentText())

    def apply_standard_quality_to_panel(self, label: str) -> None:
        """Presets manager → Apply a Standard ladder row onto Video Settings."""
        from steempeg.render.quality_presets import KIND_STANDARD, KIND_TARGET

        label = (label or "").strip()
        if not label:
            return
        self._clear_active_custom_preset()
        combo = getattr(self.ui, "combo_quality", None)
        if combo is None:
            return
        # Ensure combo has current ladder (may be empty before first clip).
        if combo.count() <= 0:
            self._rebuild_quality_preset_combo(
                max_height=int(getattr(self, "current_orig_height", 0) or 0),
            )
        for i in range(combo.count()):
            meta = combo.itemData(i, Qt.ItemDataRole.UserRole)
            if not isinstance(meta, dict):
                continue
            if meta.get("kind") not in (KIND_STANDARD, KIND_TARGET):
                continue
            if combo.itemText(i) == label:
                combo.setCurrentIndex(i)
                self.on_quality_preset_combo_changed(label)
                self._set_preset_status(f"Applied standard “{label}” to Video Settings.")
                return
        # Fallback: set by text match (Original height suffix may differ).
        idx = find_enabled_combo_text(combo, label)
        if idx < 0 and label.startswith("Original"):
            for i in range(combo.count()):
                meta = combo.itemData(i, Qt.ItemDataRole.UserRole)
                if isinstance(meta, dict) and meta.get("name") == "original":
                    idx = i
                    break
        if idx >= 0:
            combo.setCurrentIndex(idx)
            self.on_quality_preset_combo_changed(combo.itemText(idx))
            self._set_preset_status(
                f"Applied standard “{combo.itemText(idx)}” to Video Settings."
            )

    def update_quality_options(self):
        """ Reads the clip's XML data and prepares the UI for the render settings """
        if getattr(self, "_library_panel_mode", "clips") == "rendered":
            previewing_rendered = (
                hasattr(self, "_is_previewing_rendered_media")
                and self._is_previewing_rendered_media()
            )
            if previewing_rendered:
                # Header/chrome only — never re-open the export (resets position).
                self._restore_header_from_library_selection()
                self._sync_start_render_enabled()
                return
            clip_path = self._resolve_export_clip_path()
            if clip_path:
                self._populate_quality_options_for_clip(clip_path)
                self.update_final_setup()
                self._update_start_button_label()
                return
            self._restore_header_from_library_selection()
            self._sync_start_render_enabled()
            return
        if getattr(self, '_grid_select_in_progress', False):
            return
        if not hasattr(self.ui, 'table_clips'): return
        selected_row = self.ui.table_clips.currentRow()
        if selected_row < 0:
            clip_path = self._resolve_export_clip_path()
            if clip_path:
                self._populate_quality_options_for_clip(clip_path)
                self.update_final_setup()
                self._update_start_button_label()
                return
            self.ui.source_label.setText("Source:")
            self.ui.orig_res_label.setText("Original Resolution:")
            # Set default empty states for our new widgets
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate:")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate:")
            self.update_playback_badge()
            self._sync_start_render_enabled()
            return
        if hasattr(self, 'grid_clips'):
            selected_rows = {
                idx.row() for idx in self.ui.table_clips.selectionModel().selectedRows()
            }
            grid_rows = {
                item.data(Qt.UserRole)
                for item in self.grid_clips.selectedItems()
                if item.data(Qt.UserRole) is not None
            }
            # Grid-originated selects already mirrored the table — skip a full
            # setSelected walk (O(n) on large libraries) on every open.
            if grid_rows != selected_rows:
                self.grid_clips.blockSignals(True)
                for i in range(self.grid_clips.count()):
                    item = self.grid_clips.item(i)
                    row = item.data(Qt.UserRole)
                    item.setSelected(row in selected_rows)
                    if row == selected_row:
                        self.grid_clips.scrollToItem(item)
                self.grid_clips.blockSignals(False)
                if hasattr(self, '_sync_grid_card_visuals'):
                    self._sync_grid_card_visuals()
            elif selected_row >= 0:
                for item in self.grid_clips.selectedItems():
                    if item.data(Qt.UserRole) == selected_row:
                        self.grid_clips.scrollToItem(item)
                        break

        # Multi-select (Ctrl/Shift) builds a SET — don't thrash the preview on every click.
        from PySide6.QtWidgets import QApplication
        if QApplication.keyboardModifiers() & (
            Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier
        ):
            self.update_playback_badge()
            self._update_start_button_label()
            return

        if self._queue_is_active():
            clip_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
            self._handle_clips_manager_selection_with_queue(clip_path, selected_row)
            return

        self._flush_current_trim_state()
        clip_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
        if hasattr(self, "_is_valid_clip_path") and not self._is_valid_clip_path(clip_path):
            logging.warning("Ignored invalid clip selection: %s", clip_path)
            return
        # Warm remux cache while Source Info fills (Linux).
        if hasattr(self, "_prefetch_clip_playback_media"):
            self._prefetch_clip_playback_media(clip_path)
        if hasattr(self, "_clear_rendered_selection_visual"):
            self._clear_rendered_selection_visual()
        self._saved_rendered_selection_path = ""
        self._preview_clip_path = clip_path
        self._rendered_media_path = None
        # While Left with jobs kept, keep diversion so Resume does not snap the
        # header back to Ready #1 while this clip is still playing.
        has_jobs = bool(getattr(self, "render_queue", None)) and len(self.render_queue) > 0
        self._queue_library_preview_diversion = bool(
            has_jobs and getattr(self, "_queue_scheme_deferred", False)
        )
        if self._is_export_clip_path(clip_path):
            self._last_export_clip_path = os.path.normpath(clip_path)
        session = self._session_state_for_clip(clip_path)

        game_item = self.ui.table_clips.item(selected_row, 0)
        game_name = game_item.text()
        # Col 2 = ``date\\ntime``; col 3 = duration (not clock time).
        clip_date = self.ui.table_clips.item(selected_row, 2)
        clip_dur = self.ui.table_clips.item(selected_row, 3)
        date_text = clip_date.text() if clip_date else ""
        duration_text = clip_dur.text() if clip_dur else ""

        if hasattr(self, "custom_text_label"):
            from steempeg.ui.player_header_layout import (
                set_player_header_game_text,
                split_clip_date_cell,
            )

            date_part, time_part = split_clip_date_cell(date_text)
            set_player_header_game_text(
                self,
                game_name,
                date=date_part,
                time=time_part,
                duration=duration_text,
            )
        self._set_player_header_game_icon(clip_path=clip_path)

        self._selected_queue_job_id = None
        # Play first — Source Info / quality populate deferred off the open stack.
        self.generate_and_play_preview(clip_path, trim_restore=session)
        self._schedule_quality_populate_after_open(clip_path, session)
        self._update_start_button_label()
        if hasattr(self, "_schedule_persist_library_ui_state"):
            self._schedule_persist_library_ui_state()
        elif hasattr(self, "_persist_library_ui_state"):
            self._persist_library_ui_state()

    def _schedule_quality_populate_after_open(
        self, clip_path: str, session=None
    ) -> None:
        """Fill Source Info / quality combos after first frame (keeps open responsive)."""
        self._clips_quality_gen = getattr(self, "_clips_quality_gen", 0) + 1
        gen = self._clips_quality_gen
        self._pending_quality_populate = (gen, clip_path, session)
        # Already revealed / idle — flush on next tick; otherwise finish does it.
        if not getattr(self, "_awaiting_first_frame", False) and not getattr(
            self, "_is_switching", False
        ):
            QTimer.singleShot(
                0,
                lambda g=getattr(self, "_media_switch_gen", 0): self._flush_deferred_clip_open_work(
                    g
                )
                if hasattr(self, "_flush_deferred_clip_open_work")
                else None,
            )

    def _run_quality_populate_after_open(self, gen: int, clip_path: str, session) -> None:
        if gen != getattr(self, "_clips_quality_gen", 0):
            return
        want = (
            self._norm_clip_path_key(clip_path)
            if hasattr(self, "_norm_clip_path_key")
            else os.path.normpath(clip_path or "")
        )
        active = getattr(self, "_preview_clip_path", None)
        active_key = (
            self._norm_clip_path_key(active)
            if active and hasattr(self, "_norm_clip_path_key")
            else (os.path.normpath(active) if active else "")
        )
        if want and active_key and want != active_key:
            return
        self._populate_quality_options_for_clip(clip_path)
        if session is not None:
            # Export/settings only — trim/markers restore after duration is known.
            self._apply_export_session_state(session, silent=True)
        self.update_final_setup()
        if hasattr(self, "update_playback_badge"):
            self.update_playback_badge()
        # Duration is known now — start timeline thumbs if play deferred them.
        if hasattr(self, "_maybe_start_thumbs_after_quality"):
            self._maybe_start_thumbs_after_quality(clip_path)

    def fit_settings_tab_to_page(self, idx=None):
        """ Keep the scroll content as tall as the CURRENT settings page only.

        settings_tabs is a QTabWidget (QStackedLayout under the hood), which reports
        the height of its TALLEST page. Inside the scroll area that means short pages
        (Source Info, Export) show a phantom scrollbar over empty space. Collapsing the
        non-current pages to an Ignored size policy makes each page contribute 0 height,
        so the scroll range matches what's actually visible.

        Floating Render Settings must keep Expanding on the active page / scroll /
        neo — Preferred sizeHints collapse the plate into a postage stamp (or let
        it crawl past the dialog chrome on the next map).
        """
        from PySide6.QtWidgets import QSizePolicy

        tabs = getattr(self.ui, 'settings_tabs', None)
        if tabs is None:
            return
        if idx is None:
            idx = tabs.currentIndex()
        floating = False
        try:
            floating = bool(self._floating_render_settings_holds_neo())
        except Exception:
            floating = False
        active = (
            QSizePolicy.Policy.Expanding
            if floating
            else QSizePolicy.Policy.Preferred
        )
        for i in range(tabs.count()):
            page = tabs.widget(i)
            if page is None:
                continue
            if i == idx:
                page.setSizePolicy(active, active)
            else:
                page.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
                )
            page.updateGeometry()
        tabs.updateGeometry()
        if floating:
            try:
                tabs.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
                )
                scroll = getattr(self, "right_scroll", None)
                if scroll is not None:
                    scroll.setSizePolicy(
                        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
                    )
                    scroll.setMinimumSize(0, 0)
                    scroll.setMaximumSize(16777215, 16777215)
                neo = getattr(self, "neo_wrapper", None)
                if neo is not None:
                    neo.setSizePolicy(
                        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
                    )
                    neo.setMinimumSize(0, 0)
                    neo.setMaximumSize(16777215, 16777215)
            except RuntimeError:
                pass

    def _refresh_source_video_bitrate(self) -> float:
        """Return source video Mbps, re-probing from disk when the cached value is missing."""
        mbps = float(getattr(self, "current_orig_bitrate", 0) or 0)
        if mbps > 0:
            return mbps
        clip_path = self._active_preview_clip_path()
        if not clip_path:
            return 0.0
        peak = 0.0
        for mpd_path in self.get_all_mpd_paths(clip_path):
            v = mpd.get_video_bitrate_mbps(mpd_path)
            if v > peak:
                peak = v
        if peak > 0:
            self.current_orig_bitrate = peak
            if hasattr(self.ui, "label_vbitrate"):
                self.ui.label_vbitrate.setText(_source_vbitrate_label(peak))
        return peak

    def update_bitrate_options(self):
        """ Refreshes lists, applies FPS math visually, and freezes settings if Original is selected. """
        if not hasattr(self.ui, 'combo_bitrate') or not hasattr(self.ui, 'combo_quality'):
            return
        # Custom recipe rows apply via on_quality_preset_combo_changed — don't
        # treat the display name as a ladder quality string.
        meta = self._quality_combo_item_meta()
        if meta.get("kind") == "custom":
            return
            
        # --- SAVE CURRENT SELECTION (so it doesn't get lost when changing FPS) ---
        current_selection = self.ui.combo_bitrate.currentText()
        selected_level = current_selection.split(" - ")[0] if " - " in current_selection else ""

        self.ui.combo_bitrate.blockSignals(True)
        self.ui.combo_bitrate.clear()
        quality_text = self.ui.combo_quality.currentText()
        self._sync_original_audio_controls()

        if "Original" in quality_text:
            source_cap_mbps = self._refresh_source_video_bitrate()
            if source_cap_mbps > 0:
                self.ui.combo_bitrate.addItem(
                    f"{bitrate.format_video_mbps(source_cap_mbps)} (Original)"
                )
            else:
                self.ui.combo_bitrate.addItem("Unknown Mbps (Original)")

            self.ui.combo_bitrate.setEnabled(False)
            self.ui.combo_bitrate.setCurrentIndex(0)
            if hasattr(self.ui, 'combo_fps'):
                self.ui.combo_fps.setCurrentIndex(0) 
                self.ui.combo_fps.setEnabled(False)
            if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(False)
            if hasattr(self.ui, 'combo_encoder'):
                self.ui.combo_encoder.setEnabled(False)
                self.ui.combo_encoder.setToolTip(
                    "Original copies the source stream as-is (no re-encode), so no encoder "
                    "is used. Pick a quality preset (e.g. 1440p) to re-encode and choose "
                    "NVENC / CPU."
                )
            if hasattr(self.ui, 'combo_encode_speed'):
                self.ui.combo_encode_speed.setEnabled(False)
            self.ui.combo_bitrate.blockSignals(False)
            self.update_final_setup()
            return

        if "Target File Size" in quality_text:
            self.ui.combo_bitrate.addItem("Auto (target size slider)")
            self.ui.combo_bitrate.setEnabled(False)
            self.ui.combo_bitrate.setCurrentIndex(0)
            if hasattr(self.ui, 'combo_fps'):
                self.ui.combo_fps.setEnabled(True)
            if hasattr(self.ui, 'combo_codec'):
                self.ui.combo_codec.setEnabled(True)
            if hasattr(self.ui, 'combo_encoder'):
                self.ui.combo_encoder.setEnabled(True)
                self.ui.combo_encoder.setToolTip("")
            if hasattr(self.ui, 'combo_encode_speed'):
                self.ui.combo_encode_speed.setEnabled(True)
            self.ui.combo_bitrate.blockSignals(False)
            self.update_final_setup()
            return

        self.ui.combo_bitrate.setEnabled(True) 
        if hasattr(self.ui, 'combo_fps'): self.ui.combo_fps.setEnabled(True)
        if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(True)
        if hasattr(self.ui, 'combo_encoder'):
            self.ui.combo_encoder.setEnabled(True)
            self.ui.combo_encoder.setToolTip("")
        if hasattr(self.ui, 'combo_encode_speed'):
            self.ui.combo_encode_speed.setEnabled(True)
        
        match = re.search(r'^(\d+)p', quality_text)
        if not match: 
            self.ui.combo_bitrate.blockSignals(False)
            return
            
        added_any = False
        
        # Calculating the FPS Multiplier for Visuals
        fps_multiplier = 1.0
        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        orig_fps = getattr(self, 'current_orig_fps', 60)
        
        if "Custom" in fps_text and hasattr(self, 'input_custom_fps'):
            try: selected_fps = int(self.input_custom_fps.text())
            except: selected_fps = orig_fps
        else:
            try: selected_fps = int(re.search(r'(\d+)', fps_text).group(1))
            except: selected_fps = orig_fps
            
        if selected_fps < orig_fps and orig_fps > 0:
            fps_multiplier = selected_fps / orig_fps

        source_cap_mbps = self._refresh_source_video_bitrate()
        cap_label = (
            bitrate.format_video_mbps(source_cap_mbps)
            if source_cap_mbps > 0
            else "unknown"
        )
        from steempeg.render.quality_presets import bitrate_mbps_for

        try:
            height_px = int(match.group(1))
        except (TypeError, ValueError):
            height_px = 0

        for quality_level in ["Ultra", "High", "Medium", "Low"]:
            preset_bitrate = bitrate_mbps_for(
                self.steam_bitrate_presets, quality_level, height_px
            )
            if preset_bitrate is None:
                continue

            scaled_bitrate = preset_bitrate * fps_multiplier
            display_val = _fmt_mbps(scaled_bitrate)

            self.ui.combo_bitrate.addItem(f"{quality_level} - {display_val} Mbps")
            idx = self.ui.combo_bitrate.count() - 1
            if source_cap_mbps > 0 and preset_bitrate > source_cap_mbps + 0.25:
                set_combo_item_enabled(
                    self.ui.combo_bitrate,
                    idx,
                    False,
                    tooltip=(
                        f"Source video is {cap_label} — cannot exceed the original bitrate."
                    ),
                )
            else:
                added_any = True
        
        if not added_any and source_cap_mbps > 0:
            display_val = _fmt_mbps(source_cap_mbps * fps_multiplier)
            self.ui.combo_bitrate.addItem(f"Source Max - {display_val} Mbps")
            added_any = True

        self.ui.combo_bitrate.insertSeparator(self.ui.combo_bitrate.count())
        self.ui.combo_bitrate.addItem("⚙️ Custom Bitrate...")
        
        # --- RESTORING SELECTION ---
        restored = False
        if selected_level and selected_level not in ("⚙️", "Original"):
            for i in range(self.ui.combo_bitrate.count()):
                if self.ui.combo_bitrate.itemText(i).startswith(f"{selected_level} -"):
                    if set_combo_index_if_enabled(self.ui.combo_bitrate, i):
                        restored = True
                    break
        if not restored:
            for i in range(self.ui.combo_bitrate.count()):
                text = self.ui.combo_bitrate.itemText(i)
                if text.startswith("⚙️") or not text.strip():
                    break
                if set_combo_index_if_enabled(self.ui.combo_bitrate, i):
                    break

        self.ui.combo_bitrate.blockSignals(False)
        self.update_final_setup()
    
    def _audio_kbps_from_ui(self):
        """Resolve the selected audio bitrate (kbps) from the combo / custom field.

        Handles the "⚙️ Custom Audio..." sentinel and mute so callers never try to
        float() the emoji label (the old crash in update_final_setup).
        """
        if hasattr(self.ui, 'check_mute_audio') and self.ui.check_mute_audio.isChecked():
            return 0
        text = self.ui.combo_audio_bitrate.currentText() if hasattr(self.ui, 'combo_audio_bitrate') else "192 kbps"
        if "Custom" in text and hasattr(self, 'input_custom_abitrate'):
            try:
                val = int(self.input_custom_abitrate.text().strip())
                orig = getattr(self, 'current_orig_audio_bitrate', 192)
                return max(1, min(val, orig))
            except (ValueError, TypeError):
                return getattr(self, 'current_orig_audio_bitrate', 192)
        match = re.search(r'(\d+)', text)
        return int(match.group(1)) if match else 192

    def _audio_kbps_for_size_plan(self) -> int:
        """Conservative audio budget (kbps) for Target File Size math."""
        if hasattr(self.ui, 'check_mute_audio') and self.ui.check_mute_audio.isChecked():
            return 0
        audio_fmt = (
            self.ui.combo_audio_format.currentText()
            if hasattr(self.ui, "combo_audio_format") else "AAC"
        )
        orig = getattr(self, "current_orig_audio_bitrate", 192)
        if audio_fmt == "WAV":
            return min(1411, max(orig * 4, 384))
        if audio_fmt == "FLAC":
            return min(960, max(orig * 3, 256))
        if not audio_needs_bitrate(audio_fmt):
            return orig
        return self._audio_kbps_from_ui()

    def _resolved_fps_from_ui(self) -> int:
        fps = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else ""
        orig_fps = getattr(self, 'current_orig_fps', 60)
        max_allowed = min(60, orig_fps)
        if "Custom" in fps and hasattr(self, 'input_custom_fps'):
            try:
                val = int(self.input_custom_fps.text().strip())
                return max(1, min(val, max_allowed))
            except (ValueError, TypeError):
                return orig_fps
        try:
            return int(re.search(r'(\d+)', fps).group(1))
        except (AttributeError, ValueError, TypeError):
            return orig_fps

    def _resolved_custom_video_mbps(self) -> float:
        """Clamped custom video Mbps (before any FPS scaling)."""
        orig_v = getattr(self, 'current_orig_bitrate', 10.0)
        if not hasattr(self, 'input_custom_vbitrate'):
            return orig_v
        try:
            val = float(self.input_custom_vbitrate.text().replace(',', '.').strip())
            return max(0.1, min(val, orig_v))
        except (ValueError, TypeError):
            return orig_v

    def _video_mbps_for_size_estimate(self, bitrate_text: str, fps_multiplier: float) -> float | None:
        if "Original" in bitrate_text:
            return None
        if "Custom" in bitrate_text:
            return self._resolved_custom_video_mbps() * fps_multiplier
        match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
        return float(match.group(1)) if match else None

    def _format_size_mb(self, size_mb: float) -> str:
        if size_mb >= 1000:
            return f"~{size_mb / 1024:.2f} GB"
        return f"~{size_mb:.1f} MB"

    def _format_trim_duration_str(self) -> str:
        if hasattr(self, "custom_timeline") and self.custom_timeline.is_trim_mode:
            start_s = self.custom_timeline.trim_start_ms / 1000.0
            end_s = self.custom_timeline.trim_end_ms / 1000.0
            s_h = int(start_s // 3600)
            s_m = int((start_s % 3600) // 60)
            s_s = int(start_s % 60)
            e_h = int(end_s // 3600)
            e_m = int((end_s % 3600) // 60)
            e_s = int(end_s % 60)
            if s_h > 0 or e_h > 0:
                return (
                    f"✂️ {s_h:02d}:{s_m:02d}:{s_s:02d} - "
                    f"{e_h:02d}:{e_m:02d}:{e_s:02d}"
                )
            return f"✂️ {s_m:02d}:{s_s:02d} - {e_m:02d}:{e_s:02d}"
        return getattr(self, "current_clip_duration_str", "Unknown")

    def _schedule_update_final_setup(self, delay_ms: int = 180) -> None:
        """Debounce heavy export summary/path work while typing the output filename."""
        timer = getattr(self, "_filename_setup_timer", None)
        if timer is None:
            timer = QTimer(self.ui if hasattr(self, "ui") else None)
            timer.setSingleShot(True)
            timer.timeout.connect(self.update_final_setup)
            self._filename_setup_timer = timer
        timer.start(max(0, int(delay_ms)))

    def _on_output_filename_changed(self, _text: str = "") -> None:
        self._schedule_update_final_setup()

    def _schedule_custom_size_recalc(self, delay_ms: int = 180) -> None:
        timer = getattr(self, "_custom_size_timer", None)
        if timer is None:
            timer = QTimer(self.ui if hasattr(self, "ui") else None)
            timer.setSingleShot(True)
            timer.timeout.connect(self._run_custom_size_recalc)
            self._custom_size_timer = timer
        timer.start(max(0, int(delay_ms)))

    def _run_custom_size_recalc(self) -> None:
        text = getattr(self, "_pending_custom_size_text", "")
        if not text.strip():
            return
        try:
            target_mb = int(text)
            self.calculate_strict_target(target_mb, is_custom=True)
        except ValueError:
            pass

    def _update_trim_only_summary(self) -> bool:
        """Fast path: patch only the Clip time row while dragging trim handles."""
        summary = getattr(self.ui, "label_detailed_summary", None)
        if summary is None or not hasattr(summary, "patch_field"):
            return False
        return summary.patch_field("Clip time", self._format_trim_duration_str())

    def update_final_setup(self, *, trim_only: bool = False):
        """Dynamically updates the Detailed Summary, Size, and Save Path."""
        if getattr(self, "_bulk_settings_apply", False) and not trim_only:
            return
        if not trim_only:
            self._revalidate_active_custom_preset()
        clip_path = self._active_preview_clip_path()
        # Queue encode stamps preview path without opening media — treat as idle.
        if not clip_path or not self._player_has_open_clip():
            self._sync_queue_player_and_dash_chrome()
            if hasattr(self.ui, 'label_detailed_summary'):
                self.ui.label_detailed_summary.setText("Waiting for clip selection...")
            if hasattr(self.ui, 'label_location'):
                self.ui.label_location.setText("")
            path_row = getattr(self.ui, "output_path_row", None)
            if path_row is not None:
                path_row.hide()
            if hasattr(self, 'update_status_indicator'):
                self.update_status_indicator("Ready", "ready")
            if hasattr(self, 'btn_copy_loc'):
                self.btn_copy_loc.hide()
            # Queue can still render with no preview selection.
            self._sync_start_render_enabled()
            return

        if trim_only and self._update_trim_only_summary():
            return

        #1: Read everything from the UI
        quality = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else ""
        fps = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else ""
        bitrate_text = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else ""
        codec_raw = self.ui.combo_codec.currentText() if hasattr(self.ui, 'combo_codec') else ""
        codec = codec_raw.split()[0] if codec_raw else "Unknown"
        encoder = self.ui.combo_encoder.currentText() if hasattr(self.ui, 'combo_encoder') else ""
        encode_speed = ""
        if hasattr(self.ui, "combo_encode_speed"):
            encode_speed = self.ui.combo_encode_speed.currentText()

        audio_only = self.ui.check_audio_only.isChecked() if hasattr(self.ui, 'check_audio_only') else False
        mute_audio = self.ui.check_mute_audio.isChecked() if hasattr(self.ui, 'check_mute_audio') else False
        audio_format = self.ui.combo_audio_format.currentText() if hasattr(self.ui, 'combo_audio_format') else "AAC"
        audio_bitrate = self.ui.combo_audio_bitrate.currentText() if hasattr(self.ui, 'combo_audio_bitrate') else "192 kbps"
        container = self.ui.combo_container.currentText() if hasattr(self.ui, 'combo_container') else "MP4"

        if trim_only:
            full_path = getattr(self, "current_output_file", "") or ""
            final_filename = os.path.basename(full_path) if full_path else "rendered"
        else:
            # 2. Calculate the file extension
            ext = output_extension(container, audio_only, audio_format)

            # 3. OVERWRITE PROTECTION
            from steempeg.ui.settings_prefs import resolve_app_export_folder

            save_dir = resolve_app_export_folder(self, notify=False)
            base_filename = self.ui.input_filename.text().strip() if hasattr(self.ui, 'input_filename') else "rendered"

            lower_base = base_filename.lower()
            for e in KNOWN_OUTPUT_EXTENSIONS:
                if lower_base.endswith(e):
                    base_filename = base_filename[: -len(e)]
                    break

            test_path = os.path.join(save_dir, f"{base_filename}{ext}")
            counter = 1
            while os.path.exists(test_path):
                test_path = os.path.join(save_dir, f"{base_filename}_{counter}{ext}")
                counter += 1

            full_path = test_path
            final_filename = os.path.basename(full_path)
            self.current_output_file = full_path

            if hasattr(self.ui, 'label_location'):
                display_path = full_path.replace('\\', '/')
                self.ui.label_location.setText(display_path)
            path_row = getattr(self.ui, "output_path_row", None)
            if path_row is not None:
                path_row.show()

            if hasattr(self, 'btn_copy_loc') and full_path:
                self.btn_copy_loc.show()

        # 4. Collecting texts & Smart Math
        duration = self.get_effective_duration() # Use trimmed duration for math!
        
        # Format the beautiful "Clip time: ✂️ 00:10 - 01:50" string
        duration_str = self._format_trim_duration_str()
        
        # Calculating the size using the EFFECTIVE duration
        size_str = "Unknown"
        fps_multiplier = 1.0
        selected_fps = self._resolved_fps_from_ui()
        orig_fps = getattr(self, 'current_orig_fps', 60)
        if selected_fps < orig_fps and orig_fps > 0:
            fps_multiplier = selected_fps / orig_fps

        if duration > 0:
            if audio_only:
                audio_mbps = self._audio_kbps_from_ui() / 1000.0
                size_mb = (audio_mbps * duration) / 8
                size_str = self._format_size_mb(size_mb)
            elif "Target File Size" in quality:
                if hasattr(self, 'dynamic_stops') and hasattr(self.ui, 'size_slider'):
                    target_mb = self.dynamic_stops[self.ui.size_slider.value()]
                    size_str = f"~{target_mb / 1024:.2f} GB (Target)" if target_mb >= 1000 else f"~{target_mb} MB (Target)"
            elif "Original" in bitrate_text:
                if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                    # Stream copy keeps the source bitrate untouched — don't scale by
                    # fps_multiplier (a copy can't drop FPS), or the size estimate
                    # collapses the same way the bitrate label used to show "0.0".
                    orig_total_bitrate = self.current_orig_bitrate + 0.19
                    size_mb = (orig_total_bitrate * duration) / 8 
                    size_str = f"Same as original (~{size_mb / 1024:.2f} GB)" if size_mb >= 1000 else f"Same as original (~{size_mb:.1f} MB)"
                else:
                    size_str = "Same as original"
            else:
                video_bitrate = self._video_mbps_for_size_estimate(bitrate_text, fps_multiplier)
                if video_bitrate is not None:
                    audio_bitrate_val = 0 if mute_audio else self._audio_kbps_from_ui() / 1000.0
                    total_bitrate = video_bitrate + audio_bitrate_val
                    size_mb = (total_bitrate * duration) / 8
                    size_str = self._format_size_mb(size_mb)

        # Pretty audio label that never shows the raw "⚙️ Custom Audio..." sentinel.
        if "Custom" in audio_bitrate:
            audio_display = f"{self._audio_kbps_from_ui()} kbps (Custom)"
        else:
            audio_display = audio_bitrate

        if audio_only:
            if audio_format in ("FLAC", "WAV", "Copy"):
                sound_info = audio_format
            else:
                sound_info = f"{audio_format} {self._audio_kbps_from_ui()} kbps"
            other_info = ">> EXTRACT AUDIO ONLY (NO VIDEO)"
        elif mute_audio:
            sound_info = "None"
            other_info = ">> NO SOUND (MUTED)"
        elif "Original" in quality and "Target File Size" not in quality:
            sound_info = "Original audio (copy)"
            other_info = "Original stream copy"
        elif audio_format == "Copy":
            sound_info = "Copy (from source)"
            other_info = "Normal Render"
        elif audio_format in ("FLAC", "WAV"):
            sound_info = audio_format
            other_info = "Normal Render"
        else:
            sound_info = audio_display
            other_info = "Normal Render"

        # 5. Smart Detailed Summary in Export Settings
        
        # --- CLEAN PARSING FOR UI DISPLAY ---
        
        # Parse Video Bitrate for UI
        video_bitrate_display = "Unknown"
        orig_v_bitrate = getattr(self, 'current_orig_bitrate', 10.0)

        if "Target File Size" in quality:
            val_mbps = getattr(self, 'custom_target_bitrate', 1500) / 1000
            scale_h = getattr(self, 'custom_target_height', -1)
            native_h = getattr(self, 'current_orig_height', 0)
            if scale_h > 0:
                res_str = f"Auto: {scale_h}p"
            elif native_h > 0:
                res_str = f"{native_h}p"
            else:
                res_str = "Original res"
            clean_mbps = int(round(val_mbps))
            video_bitrate_display = f"{clean_mbps} Mbps ({res_str})"
        elif "Custom" in bitrate_text:
            val = self._resolved_custom_video_mbps()
            # Effective Mbps after FPS scale — use _fmt_mbps so sub-1 values
            # (e.g. 0.1 @ 1 FPS → ~0.002) do not collapse to "0.0".
            video_bitrate_display = f"⚙️ {_fmt_mbps(val * fps_multiplier)} Mbps"
        elif "Original" in bitrate_text:
            # Original = stream copy: show the source Mbps only — "Original" is already
            # in the quality label; the bottom summary must not repeat "Original copy".
            orig_mbps = orig_v_bitrate
            if orig_mbps <= 0:
                m = re.search(r'([\d.]+)\s*Mbps', bitrate_text)
                if m:
                    orig_mbps = float(m.group(1))
            video_bitrate_display = (
                bitrate.format_video_mbps(orig_mbps) if orig_mbps > 0 else "—"
            )
        else:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match:
                video_bitrate_display = f"{_fmt_mbps(float(match.group(1)))} Mbps"

        # Parse Audio Bitrate for UI
        if audio_format in ("FLAC", "WAV", "Copy"):
            audio_bitrate_clean = "lossless / copy" if audio_format != "Copy" else "copy"
        elif "Custom" in audio_bitrate:
            val = self._audio_kbps_from_ui()
            audio_bitrate_clean = f"⚙️ {val} kbps"
        elif "Original" in quality and "Target File Size" not in quality and not audio_only:
            audio_bitrate_clean = "Original audio (copy)"
        else:
            # Clean up "(Original Copy)" just "192 kbps"
            audio_bitrate_clean = audio_bitrate.split('(')[0].strip() if audio_bitrate else "192 kbps"

        # Parse FPS for UI (includes the word "FPS" inside)
        if "Custom" in fps:
            val = self._resolved_fps_from_ui()
            fps_display = f"⚙️ {val} FPS"
        else:
            val_str = fps.split(' ')[0] if fps else "Unknown"
            fps_display = f"{val_str} FPS" if val_str != "Unknown" else "Unknown"

        # Clean strings
        q_clean = quality.split('(')[0].strip() if quality else "Unknown"
        enc_clean = encoder if encoder else "Unknown"

        # Construct the final detailed text block 
        container_line = f"Container: {container}\n"
        if audio_only:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"{container_line}"
                f"Format: {audio_format}\n"
                f"Sound: {audio_format}, {audio_bitrate_clean}\n"
                f"Other settings: >> EXTRACT AUDIO ONLY (NO VIDEO)\n"
                f"Est. File Size: {size_str}"
            )
        elif mute_audio:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"{container_line}"
                f"Quality: {q_clean}\n"
                f"FPS: {fps_display}\n"
                f"Bitrate: {video_bitrate_display}\n"
                f"Codec: {codec}\n"
                f"Encoder: {enc_clean}\n"
                f"Encode speed: {encode_speed or 'Balanced'}\n"
                f"Other settings: >> NO SOUND (MUTED)\n"
                f"Est. File Size: {size_str}"
            )
        elif "Original" in quality and "Target File Size" not in quality:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"{container_line}"
                f"Quality: {q_clean}\n"
                f"FPS: {fps_display}\n"
                f"Bitrate: {video_bitrate_display}\n"
                f"Codec: Original copy\n"
                f"Encoder: —\n"
                f"Sound: Original audio\n"
                f"Other settings: Original stream copy\n"
                f"Est. File Size: {size_str}"
            )
        else:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"{container_line}"
                f"Quality: {q_clean}\n"
                f"FPS: {fps_display}\n"
                f"Bitrate: {video_bitrate_display}\n"
                f"Codec: {codec}\n"
                f"Encoder: {enc_clean}\n"
                f"Encode speed: {encode_speed or 'Balanced'}\n"
                f"Sound: {audio_format}, {audio_bitrate_clean}\n"
                f"Other settings: Normal Render\n"
                f"Est. File Size: {size_str}"
            )
            
        if hasattr(self.ui, 'label_detailed_summary'):
            self.ui.label_detailed_summary.setText(detailed_text)

        combo_valid = is_valid_output_combo(
            container,
            codec_raw,
            audio_format,
            audio_only=audio_only,
            mute_audio=mute_audio,
            stream_copy=(
                "Original" in quality and "Target File Size" not in quality and not audio_only
            ),
        )
        if hasattr(self.ui, 'btn_start') and not getattr(self, '_is_rendering', False):
            self._sync_start_render_enabled(combo_valid=combo_valid)

        # 6. Short Summary ABOVE Ready
        # Footer follows the next queue job while queue mode is active; player
        # header follows the open clip (handled elsewhere when strip_job is set).
        strip_job = self._status_strip_context_job()
        q_word = quality.split()[0] if quality.split() else "Unknown"

        game_name = "Steam Clip"
        target_icon = getattr(self, 'current_game_icon', '')
        if strip_job is not None:
            game_name = (strip_job.game_name or "").strip() or game_name
            resolved = resolve_job_game_icon_path(
                getattr(self, "cache_dir", "") or "", strip_job
            )
            if resolved:
                target_icon = resolved
        else:
            preview_path = self._active_preview_clip_path()
            if preview_path and hasattr(self.ui, "table_clips"):
                for row in range(self.ui.table_clips.rowCount()):
                    item = self.ui.table_clips.item(row, 0)
                    if not item:
                        continue
                    row_path = item.data(Qt.UserRole)
                    if row_path and os.path.normpath(row_path) == os.path.normpath(preview_path):
                        game_name = item.text().strip()
                        break
            elif hasattr(self.ui, 'table_clips') and self.ui.table_clips.currentRow() >= 0:
                game_name = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).text().strip()
                target_icon = getattr(self, 'current_game_icon', '')

        unknown_icon_path = get_resource_path("unknown_icon.png")
        logo_path = get_resource_path("logo.png")
        if not target_icon or not os.path.exists(target_icon):
            target_icon = unknown_icon_path
        place_icon = target_icon
        if place_icon == unknown_icon_path or not os.path.exists(place_icon):
            place_icon = logo_path if os.path.exists(logo_path) else unknown_icon_path

        if strip_job is not None:
            text_part = format_dash_job_summary(
                game_name, getattr(strip_job, "settings", None)
            )
        elif audio_only:
            text_part = f"{game_name}  •  AUDIO ONLY: {audio_format} {audio_bitrate_clean}"
        elif mute_audio:
            text_part = (
                f"{game_name}  •  {q_word}, {fps_display}  •  "
                f"{video_bitrate_display}  •  {codec} (Muted)"
            )
        else:
            text_part = (
                f"{game_name}  •  {q_word}, {fps_display}  •  "
                f"{video_bitrate_display}  •  {codec}"
            )

        # GIVE ORDER TO OUR NEW CSS WIDGETS
        if hasattr(self, 'bottom_text_label'):
            if strip_job is not None:
                self._apply_status_strip_summary(strip_job)
            else:
                self.bottom_text_label.setText(text_part)
                from steempeg.ui.icon_shape import (
                    ICON_SHAPE_CIRCLE,
                    shaped_game_icon_pixmap,
                )

                is_unknown_icon = (
                    os.path.basename(target_icon).lower() == "unknown_icon.png"
                )
                header_shape = ICON_SHAPE_CIRCLE if is_unknown_icon else None
                if hasattr(self, "_set_bottom_summary_icon"):
                    self._set_bottom_summary_icon(target_icon)
                elif hasattr(self, "bottom_icon_label"):
                    from steempeg.ui.icon_utils import apply_square_icon

                    self.bottom_icon_label.setStyleSheet(
                        "background: transparent; border: none;"
                    )
                    bottom_pix = QPixmap(target_icon)
                    shaped = (
                        shaped_game_icon_pixmap(bottom_pix, 24, header_shape)
                        if not bottom_pix.isNull()
                        else None
                    )
                    apply_square_icon(self.bottom_icon_label, shaped, 24)

            # Player header icon from preview only — never the queue strip job.
            if (
                hasattr(self, 'custom_text_label')
                and hasattr(self, 'custom_icon_label')
                and strip_job is None
            ):
                self._set_player_header_game_icon(icon_path=target_icon)

            # CONNECTING THE MAIN BOSS: Updating the CENTRAL plug!
            if hasattr(self, 'place_logo') and hasattr(self, 'place_text'):
                from steempeg.ui.icon_shape import shaped_game_icon_pixmap
                from steempeg.ui.icon_utils import apply_square_icon

                # Pixmap only (no stylesheet image) so the game icon scales with the
                # aspect ratio kept and never overlaps the Steempeg logo underneath.
                self.place_logo.setStyleSheet("background: transparent; border: none;")
                game_pix = QPixmap(place_icon)
                shaped = (
                    shaped_game_icon_pixmap(game_pix, 80)
                    if not game_pix.isNull()
                    else None
                )
                apply_square_icon(self.place_logo, shaped, 80)
                self.place_logo.show()
                self.place_text.setText(f"Ready to play: {game_name}")
                self.place_text.setStyleSheet(
                    "color: #a0a0a0; font-size: 15px; font-weight: bold; margin-top: 15px;"
                )

        if not getattr(self, '_is_rendering', False):
            self.update_status_indicator("Ready", "ready")

        if self._queue_is_active() and self._sync_active_queue_job_from_ui():
            self.refresh_render_queue_panel(sync_splitter=False)

    def on_quality_mode_changed(self, text):
        """ Hides or shows the slider and target inputs depending on the mode """
        self._last_quality_text = text
        is_target_mode = "Target File Size" in (text or "")

        if hasattr(self.ui, 'size_slider'):
            self.ui.size_slider.setVisible(is_target_mode)
            
        if hasattr(self, 'size_container'):
            self.size_container.setVisible(is_target_mode)
            
        if is_target_mode:
            self._ensure_fps_combo_for_target()
            self.setup_dynamic_slider()
        self._sync_original_audio_controls()
        self.refresh_output_format_availability()
        # Skip summary rebuild during bulk preset/job apply — caller runs it once.
        if is_target_mode and not getattr(self, "_bulk_settings_apply", False):
            self.update_final_setup()

    def _ensure_fps_combo_for_target(self) -> None:
        """Target mode needs a usable FPS row (blank combo broke the size plan)."""
        combo = getattr(self.ui, "combo_fps", None)
        if combo is None:
            return
        if combo.count() > 0 and (combo.currentText() or "").strip():
            return
        fps_val = int(getattr(self, "current_orig_fps", 60) or 60)
        combo.blockSignals(True)
        if combo.count() <= 0:
            combo.addItem(f"{fps_val} FPS (Original)")
        combo.setCurrentIndex(0)
        combo.setEnabled(True)
        combo.blockSignals(False)

    def init_original_help_state(self) -> None:
        """Apply the saved 'don't show again' preference to the Original warning icon."""
        btn = getattr(self.ui, "btn_quality_original_help", None)
        if btn is None:
            return
        dismissed = bool(self.load_user_settings().get("original_preset_warning_dismissed"))
        btn.setProperty("warning_dismissed", dismissed)
        sync = getattr(btn, "_sync_help", None)
        if callable(sync) and hasattr(self.ui, "combo_quality"):
            sync(self.ui.combo_quality.currentText())

    def show_original_help_popup(self) -> None:
        """Popup anchored to the Original warning icon with a 'don't show again' checkbox."""
        from PySide6.QtWidgets import QMenu, QWidgetAction, QVBoxLayout, QLabel, QWidget

        from steempeg.ui.widgets.steempeg_check import SteempegCheckBox

        btn = getattr(self.ui, "btn_quality_original_help", None)
        if btn is None:
            return

        from steempeg.ui import ui_theme as ut

        menu = QMenu(self.ui)
        menu.setStyleSheet(
            ut.menu_stylesheet(menu_padding="4px", extra="QLabel { background: transparent; }")
        )

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel("Original preset warning")
        title.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 12px; font-family: " + tok.FONT_APP + ";")
        body = QLabel(
            "Original uses fast stream copy / block merge without re-encoding.\n\n"
            "If Steam DASH chunks are slightly broken, the output duration can be wrong "
            "(for example, a 3-second clip may become much longer).\n\n"
            "If that happens, use a normal re-encode preset such as 1440p / 1080p."
        )
        body.setWordWrap(True)
        body.setFixedWidth(320)
        body.setStyleSheet("color: #c8c8c8; font-size: 11px; font-family: " + tok.FONT_APP + ";")

        chk = SteempegCheckBox("Don't show this again")
        chk.setChecked(bool(btn.property("warning_dismissed")))

        def _on_toggled(checked):
            self.save_user_settings("original_preset_warning_dismissed", bool(checked))
            btn.setProperty("warning_dismissed", bool(checked))
            if checked:
                menu.close()
                btn.hide()

        chk.toggled.connect(_on_toggled)

        lay.addWidget(title)
        lay.addWidget(body)
        lay.addWidget(chk)

        act = QWidgetAction(menu)
        act.setDefaultWidget(host)
        menu.addAction(act)
        menu.exec(btn.mapToGlobal(QPoint(0, btn.height() + 4)))

    def on_custom_size_changed(self, text):
        """ Live updates when typing a custom MB value with idiot-proof protection """
        self._pending_custom_size_text = text
        if not text.strip():
            self.warn_size.hide()
            return

        try:
            target_mb = int(text)

            # --- Use EFFECTIVE duration for correct calculation! ---
            duration = self.get_effective_duration()
            orig_bitrate = getattr(self, 'current_orig_bitrate', 10)
            orig_mb = int((orig_bitrate * duration) / 8)
            if orig_mb < 1: orig_mb = 1

            # Idiot-proof protection lol
            if target_mb < 1:
                self.warn_size.setToolTip("Oops! Minimum size is 1 MB, otherwise the video will turn to dust")
                self.warn_size.show()
            elif target_mb > orig_mb:
                self.warn_size.setToolTip(f"No need to inflate the file! Maximum for this clip: {orig_mb} MB.\n The program will automatically cap the value to this limit.")
                self.warn_size.show()
            else:
                self.warn_size.hide()

            self._schedule_custom_size_recalc()
        except Exception:
            self.warn_size.hide()

    def refresh_slider_if_needed(self):
        """ Updates the monkeymeter if the user has switched FPS """
        if hasattr(self.ui, 'size_slider') and self.ui.size_slider.isVisible():
            self.on_slider_moved(self.ui.size_slider.value())

        
    
    
    def setup_dynamic_slider(self):
        """ Generates strict slider steps and adds Lossless & Custom modes """
        duration = float(self.get_effective_duration() or 0)
        if duration <= 0:
            duration = float(getattr(self, "current_clip_duration_sec", 0) or 0)
        if duration <= 0:
            # Still no duration — don't leave the Designer "Target Size" stub,
            # and don't leave dynamic_stops unset (slider moves would crash).
            self.dynamic_stops = [10, 25, 50, 100, -1]
            if hasattr(self.ui, "size_slider"):
                self.ui.size_slider.blockSignals(True)
                self.ui.size_slider.setMinimum(0)
                self.ui.size_slider.setMaximum(len(self.dynamic_stops) - 1)
                self.ui.size_slider.setValue(0)
                self.ui.size_slider.blockSignals(False)
            if hasattr(self.ui, "label_target_size"):
                self.ui.label_target_size.setText(
                    "Target: <b>— MB</b><br>"
                    "Quality: <span style='color:#aaaaaa'><b>"
                    "Need clip duration — open a clip / wait for load"
                    "</b></span>"
                )
            return

        # Dynamically calculate the maximum MB for the current trimmed duration
        orig_mb = (getattr(self, 'current_orig_bitrate', 10) * duration) / 8
        if orig_mb < 1:
            orig_mb = 1

        anchors = [10, 25, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, 4000, 5000]
        self.dynamic_stops = [size for size in anchors if size < orig_mb]

        self.dynamic_stops.append(int(orig_mb))  # Lossless
        self.dynamic_stops.append(-1)  # Custom

        self.ui.size_slider.blockSignals(True)
        self.ui.size_slider.setMinimum(0)
        self.ui.size_slider.setMaximum(len(self.dynamic_stops) - 1)
        # Always snap to the new Lossless value when the trim changes
        self.ui.size_slider.setValue(len(self.dynamic_stops) - 2)
        self.ui.size_slider.blockSignals(False)

        self.on_slider_moved(self.ui.size_slider.value())

    def calculate_strict_target(self, target_mb, is_lossless=False, is_custom=False):
        """Read the controls, run the bitrate math, show the result."""
        duration = float(self.get_effective_duration() or 0)
        if duration <= 0:
            duration = float(getattr(self, "current_clip_duration_sec", 0) or 0)
        if duration <= 0:
            if hasattr(self.ui, "label_target_size"):
                self.ui.label_target_size.setText(
                    f"Target: <b>{int(target_mb)} MB</b><br>"
                    "Quality: <span style='color:#aaaaaa'><b>"
                    "Need clip duration — open a clip / wait for load"
                    "</b></span>"
                )
            return

        # --- read inputs from the UI ---
        orig_video_mbps = getattr(self, 'current_orig_bitrate', 10)

        audio_kbps = self._audio_kbps_for_size_plan()

        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        fps = self._resolved_fps_from_ui() if "Custom" in fps_text else None
        if fps is None:
            try:
                fps = int(re.search(r'(\d+)', fps_text).group(1))
            except (AttributeError, ValueError, TypeError):
                fps = getattr(self, 'current_orig_fps', 60)

        # --- run the pure math ---
        native_height = getattr(self, 'current_orig_height', 0)
        plan = bitrate.plan_bitrate(duration, orig_video_mbps, target_mb, audio_kbps, fps,
                                    is_lossless=is_lossless, is_custom=is_custom,
                                    native_height=native_height)
        if plan is None:
            if hasattr(self.ui, "label_target_size"):
                self.ui.label_target_size.setText(
                    f"Target: <b>{int(target_mb)} MB</b><br>"
                    "Quality: <span style='color:#aaaaaa'><b>"
                    "Could not plan bitrate — check duration / FPS"
                    "</b></span>"
                )
            return

        # --- show the result ---
        self.custom_target_height = plan.height
        self.custom_target_bitrate = plan.video_kbps
        custom_tag = "⚙️ Custom " if is_custom else ""
        mbit = _format_mbit(plan.video_kbps)
        self.ui.label_target_size.setText(
            f"Target: <b>{custom_tag}{plan.target_mb} MB</b> | Safe Bitrate: <b>{mbit}</b><br>"
            f"Quality: <span style='color:{plan.color}'><b>{plan.label}</b></span>"
        )
        self.update_final_setup()

    def on_slider_moved(self, index):
        """ Handles slider logic and reveals custom input if needed """
        stops = getattr(self, "dynamic_stops", None)
        if not stops:
            return
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        if index < 0 or index >= len(stops):
            return
        target_mb = stops[index]

        if target_mb == -1:
            self.input_custom_size.show()
            if self.input_custom_size.text():
                self.on_custom_size_changed(self.input_custom_size.text())
            else:
                self.ui.label_target_size.setText("Target: <b>--- MB</b> (Type specific size)<br>Quality: <span style='color:#aaaaaa'><b>Waiting for input...</b></span>")
        else:
            self.input_custom_size.hide()
            if hasattr(self, 'warn_size'): self.warn_size.hide()
            self.calculate_strict_target(target_mb, is_lossless=(index == len(stops) - 2))

    def validate_custom_fps(self, text):
        """ Validates FPS input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_fps.hide()
            self._schedule_update_final_setup()
            return
            
        try:
            val = int(text)
            orig_fps = getattr(self, 'current_orig_fps', 60)
            max_allowed = min(60, orig_fps)
            
            if val > max_allowed:
                self.warn_fps.setToolTip(f"The maximum FPS of the original video is {max_allowed} FPS. Higher values will be capped!")
                self.warn_fps.show()
            elif val < 1:
                self.warn_fps.setToolTip("FPS cannot be less than 1.")
                self.warn_fps.show()
            else:
                self.warn_fps.hide()
        except Exception:
            self.warn_fps.hide()

        self._schedule_update_final_setup()

    def validate_custom_vbitrate(self, text):
        """ Validates video bitrate input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_vbitrate.hide()
            self._schedule_update_final_setup()
            return
            
        try:
            val = float(text.replace(',', '.'))
            orig_v_bitrate = getattr(self, 'current_orig_bitrate', 10.0)
            
            if val > orig_v_bitrate:
                self.warn_vbitrate.setToolTip(
                    f"The maximum bitrate of the original video is "
                    f"{bitrate.format_video_mbps(orig_v_bitrate)}. Higher values will be capped!"
                )
                self.warn_vbitrate.show()
            elif val < 0.1:
                self.warn_vbitrate.setToolTip("Video bitrate cannot be less than 0.1 Mbps.")
                self.warn_vbitrate.show()
            else:
                self.warn_vbitrate.hide()
        except Exception:
            self.warn_vbitrate.hide()

        self._schedule_update_final_setup()

    def validate_custom_abitrate(self, text):
        """ Validates audio bitrate input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_abitrate.hide()
            self._schedule_update_final_setup()
            return
            
        try:
            val = int(text)
            orig_a_bitrate = getattr(self, 'current_orig_audio_bitrate', 192)
            
            if val > orig_a_bitrate:
                self.warn_abitrate.setToolTip(f"The maximum audio bitrate of the original file is {orig_a_bitrate} kbps. Higher values will be capped!")
                self.warn_abitrate.show()
            elif val < 1:
                self.warn_abitrate.setToolTip("Audio bitrate cannot be less than 1 kbps.")
                self.warn_abitrate.show()
            else:
                self.warn_abitrate.hide()
        except Exception:
            self.warn_abitrate.hide()

        self._schedule_update_final_setup()

    def add_clip_to_render_queue(self, clip_path: str, *, sync_ui: bool = True):
        """Snapshot current settings into a new queued job.

        The same clip may be queued more than once (e.g. Discord vs Drive presets).
        When ``sync_ui`` is True (portable Add, single-clip callers), refresh the
        queue panel and optionally notify about an existing duplicate.

        Heavy work: widget snapshot on the click, MPD walk / probe on a worker
        thread, then card rebuild + queue JSON on the next tick so Portable Add
        does not freeze the sheet.
        """
        if self._is_rendered_export_path(clip_path):
            logging.warning("Refused to queue rendered export: %s", clip_path)
            if sync_ui:
                steempeg_warning(
                    self.ui,
                    "Cannot queue export",
                    "Rendered exports cannot be added to the Render Queue. "
                    "Select a Steam clip in Clips Manager instead.",
                )
            return None
        if clip_path and not self._is_export_clip_path(clip_path):
            logging.warning("Refused to queue non-clip path: %s", clip_path)
            if sync_ui:
                steempeg_warning(
                    self.ui,
                    "Cannot queue clip",
                    "Only Steam clip folders can be queued for render.",
                )
            return None
        was_duplicate = bool(
            clip_path and self.render_queue.contains_clip(clip_path)
        )
        if hasattr(self, "get_clip_health_report"):
            report = self.get_clip_health_report(clip_path)
            if report.level == health.ClipHealth.DEAD:
                verified = hasattr(self, "_is_clip_cured") and self._is_clip_cured(clip_path)
                if not verified:
                    logging.warning("Skipped unverified dead clip for queue: %s", clip_path)
                    return None
        if sync_ui:
            # Widget snapshot now; MPD walk / probe on a worker so Add doesn't freeze.
            if bool(getattr(self, "_queue_add_busy", False)):
                return None
            payload = collect_queue_add_payload(self, clip_path)
            if payload is None:
                return None
            if was_duplicate:
                # Notice promises a fresh Original-style row — do not copy the
                # live Trim from the sibling card of the same clip.
                payload.trim = {
                    "is_trim_mode": False,
                    "trim_start_ms": 0,
                    "trim_end_ms": 0,
                }
                if payload.settings is not None:
                    payload.settings.is_trim_mode = False
                    payload.settings.trim_start_ms = 0
                    payload.settings.trim_end_ms = 0
            self._start_async_queue_add(payload, clip_path, was_duplicate)
            return None

        job = build_render_job_from_ui(self, clip_path)
        if job is None:
            return None
        if was_duplicate and job.settings is not None:
            job.settings.is_trim_mode = False
            job.settings.trim_start_ms = 0
            job.settings.trim_end_ms = 0
        return self._commit_queue_job(job, clip_path, was_duplicate, sync_ui=False)

    def _remember_job_salvage(self, job) -> None:
        mpds = list(getattr(job, "salvage_mpds", None) or [])
        if not mpds:
            return
        if not hasattr(self, "_salvaged_clips"):
            self._salvaged_clips = {}
        self._salvaged_clips[os.path.normpath(job.clip_path)] = mpds

    def _sync_queue_add_busy_chrome(self) -> None:
        sidebar = getattr(self, "_portable_queue_sidebar", None)
        if sidebar is not None and hasattr(sidebar, "_sync_add_enabled"):
            try:
                sidebar._sync_add_enabled()
            except RuntimeError:
                pass
        if getattr(self, "_portable_shell", False):
            try:
                from steempeg.ui.portable.chrome import sync_portable_queue_header

                sync_portable_queue_header(self)
            except Exception:
                pass

    def _start_async_queue_add(self, payload, clip_path: str, was_duplicate: bool) -> None:
        from steempeg.ui.queue_add_worker import QueueAddWorker

        self._queue_add_busy = True
        self._sync_queue_add_busy_chrome()
        worker = QueueAddWorker(
            payload, parent=self.ui if hasattr(self, "ui") else None
        )
        self._queue_add_worker = worker

        def _ok(job) -> None:
            self._queue_add_busy = False
            self._commit_queue_job(job, clip_path, was_duplicate, sync_ui=True)

        def _fail(msg: str) -> None:
            self._queue_add_busy = False
            self._sync_queue_add_busy_chrome()
            logging.warning("Could not add clip to render queue: %s", msg)

        worker.finished_ok.connect(_ok)
        worker.failed.connect(_fail)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _commit_queue_job(
        self, job, clip_path: str, was_duplicate: bool, *, sync_ui: bool
    ):
        self._remember_job_salvage(job)
        self.render_queue.add(job)
        logging.info(
            "Queued render job #%s: %s -> %s",
            job.queue_index,
            job.game_name,
            job.output_file,
        )
        self._sync_queue_add_busy_chrome()
        if sync_ui:
            self._queue_library_preview_diversion = False
            QTimer.singleShot(
                0,
                lambda p=clip_path, d=was_duplicate: self._sync_ui_after_queue_add(p, d),
            )
        return job

    def _sync_ui_after_queue_add(self, clip_path: str, was_duplicate: bool) -> None:
        """Persist + refresh queue chrome after a single-clip Add.

        When the portable Render sheet owns the visible queue rail, refresh that
        rail first and defer the (hidden) desktop card rebuild so Add stays snappy.
        """
        self._persist_render_queue_async()

        sidebar = getattr(self, "_portable_queue_sidebar", None)
        portable_visible = False
        if sidebar is not None:
            try:
                portable_visible = bool(sidebar.isVisible())
            except RuntimeError:
                self._portable_queue_sidebar = None
                sidebar = None

        if portable_visible and sidebar is not None and hasattr(sidebar, "refresh"):
            sidebar.refresh()
            self._update_start_button_label()
            self._sync_start_render_enabled()
            self._sync_queue_scheme_chrome()
            self._sync_queue_player_and_dash_chrome()
            self.update_playback_badge()
            # Desktop dock is behind the sheet — catch up on the following tick.
            QTimer.singleShot(
                0,
                lambda: self.refresh_render_queue_panel(
                    sync_splitter=False, include_portable=False
                ),
            )
        else:
            self.refresh_render_queue_panel()
            self._sync_start_render_enabled()
            self._sync_queue_player_and_dash_chrome()
            self.update_playback_badge()

        if was_duplicate:
            self._maybe_notify_queue_duplicate([clip_path])

    def _maybe_notify_queue_duplicate(self, clip_paths) -> None:
        """Inform that a clip was already queued; skip if user opted out."""
        if not clip_paths:
            return
        if bool(self.load_user_settings().get("render_queue_duplicate_notice_dismissed")):
            return
        paths = [p for p in clip_paths if p]
        if not paths:
            return
        if len(paths) == 1:
            name = os.path.basename(paths[0])
            message = (
                f"“{name}” is already in the render queue.\n\n"
                "A duplicate will be added to the Queue with the starting "
                "Original preset."
            )
        else:
            message = (
                f"{len(paths)} selected clip(s) were already in the render queue.\n\n"
                "Duplicates will be added to the Queue with the starting "
                "Original preset."
            )
        dont_ask = steempeg_information_dont_ask(
            self.ui,
            "Render Queue",
            message,
            checkbox_label="Don't ask again",
        )
        if dont_ask:
            self.save_user_settings("render_queue_duplicate_notice_dismissed", True)

    def add_clips_to_render_queue(self, clip_paths):
        """Add one or more clips using the current render settings snapshot.

        Duplicates are allowed (same clip, different presets). No success popup —
        only failures and an optional one-time duplicate notice.
        """
        added = 0
        failed = []
        duplicates = []

        self._flush_current_trim_state()
        for clip_path in clip_paths:
            was_duplicate = self.render_queue.contains_clip(clip_path)
            job = self.add_clip_to_render_queue(clip_path, sync_ui=False)
            if job is None:
                failed.append(os.path.basename(clip_path))
            else:
                added += 1
                if was_duplicate:
                    duplicates.append(clip_path)

        if not added and not failed:
            return

        if failed:
            steempeg_warning(
                self.ui,
                "Render Queue",
                "Could not add the selected clip(s).\n"
                + "\n".join(failed),
            )

        if duplicates:
            self._maybe_notify_queue_duplicate(duplicates)

        logging.info(
            "Queue update: added=%s duplicates=%s failed=%s total=%s",
            added,
            len(duplicates),
            len(failed),
            len(self.render_queue),
        )
        self.refresh_render_queue_panel()
        self._sync_start_render_enabled()
        self._persist_render_queue()
        self._queue_library_preview_diversion = False
        self._sync_queue_player_and_dash_chrome()
        self.update_playback_badge()

    # --- Custom export presets (v41 → v45 manager UX) ------------------------

    def _export_preset_expanded_names(self) -> set[str]:
        names = getattr(self, "_export_preset_expanded", None)
        if names is None:
            names = set()
            self._export_preset_expanded = names
        return names

    def _export_preset_search_text(self) -> str:
        edit = getattr(self.ui, "preset_search_edit", None)
        if edit is None:
            return ""
        return (edit.text() or "").strip()

    def _list_selected_export_preset_name(self) -> str:
        """Name from the selected list row only (Delete / Update target)."""
        lst = getattr(self.ui, "preset_list", None)
        if lst is None or lst.currentItem() is None:
            return ""
        item = lst.currentItem()
        raw = item.data(Qt.ItemDataRole.UserRole)
        if raw:
            text = str(raw).strip()
            # Section / Standard rows are not Custom recipes.
            if text.startswith("__"):
                return ""
            return text
        # Fallback for plain text rows (strip favourite star prefix).
        text = (item.text() or "").strip()
        if text.startswith("★ "):
            text = text[2:].strip()
        return text

    def refresh_export_presets_list(self) -> None:
        import json

        from PySide6.QtWidgets import QListWidgetItem

        from steempeg.render.export_presets import (
            format_preset_summary,
            get_preset_settings,
            list_preset_names,
            load_favourite_names,
            load_presets_map,
        )
        from steempeg.render.quality_presets import (
            TARGET_FILE_SIZE_LABEL,
            build_quality_presets,
            original_quality_label,
        )
        from steempeg.ui.render_panel import (
            PresetListRow,
            PresetSectionHeader,
            StandardPresetRow,
        )

        lst = getattr(self.ui, "preset_list", None)
        if lst is None:
            return
        selected = self._list_selected_export_preset_name()
        search_raw = self._export_preset_search_text()
        search = search_raw.lower()
        # Fingerprint before widget rebuild — open paths call this every show.
        presets_map = load_presets_map(self.load_user_settings)
        fav_set = set(load_favourite_names(self.load_user_settings))
        expanded = self._export_preset_expanded_names()
        known = set(presets_map.keys())
        expanded.intersection_update(known)
        names = list_preset_names(self.load_user_settings, search=search_raw)
        max_h = int(getattr(self, "current_orig_height", 0) or 0)
        standard_labels = [original_quality_label(max_h if max_h > 0 else None)]
        ladder_h = max_h if max_h > 0 else 1080
        standard_labels.extend(
            label for label, _h in build_quality_presets(ladder_h)
        )
        # Target lives under Custom (built-in hybrid) — not in the Standard ladder.
        show_target = True
        if search:
            standard_labels = [s for s in standard_labels if search in s.lower()]
            show_target = search in TARGET_FILE_SIZE_LABEL.lower()
        try:
            presets_blob = json.dumps(presets_map, sort_keys=True, default=str)
        except (TypeError, ValueError):
            presets_blob = repr(presets_map)
        fp = (
            search,
            selected,
            tuple(standard_labels),
            show_target,
            tuple(names),
            frozenset(fav_set),
            frozenset(expanded),
            presets_blob,
            max_h,
        )
        expected_rows = (
            2 + len(standard_labels) + (1 if show_target else 0) + len(names)
        )
        if (
            getattr(self, "_export_presets_list_fp", None) == fp
            and lst.count() == expected_rows
        ):
            return
        self._export_presets_list_fp = fp

        lst.blockSignals(True)
        lst.clear()

        def _add_section(title: str) -> None:
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setData(Qt.ItemDataRole.UserRole, f"__section__:{title}")
            header = PresetSectionHeader(title)
            lst.addItem(item)
            lst.setItemWidget(item, header)
            item.setSizeHint(header.preferred_size_hint())

        def _add_standard(label: str) -> None:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, f"__standard__:{label}")
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            row = StandardPresetRow(
                label,
                on_apply=self.apply_standard_quality_to_panel,
            )
            lst.addItem(item)
            lst.setItemWidget(item, row)
            item.setSizeHint(row.preferred_size_hint())

        _add_section("Standard")
        for label in standard_labels:
            _add_standard(label)

        _add_section("Custom")
        if show_target:
            _add_standard(TARGET_FILE_SIZE_LABEL)
        for name in names:
            summary = format_preset_summary(
                get_preset_settings(name, self.load_user_settings)
            )
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(summary)
            row = PresetListRow(
                name,
                summary=summary,
                is_favourite=name in fav_set,
                expanded=name in expanded,
                on_select=self._select_export_preset_by_name,
                on_toggle_fav=self.toggle_export_preset_favourite_from_ui,
                on_toggle_expand=self._toggle_export_preset_row_expanded,
                on_apply=self.apply_export_preset_to_panel,
                on_edit=self.edit_export_preset_in_editor,
                on_update=self.update_export_preset_from_ui,
                on_rename=self.rename_export_preset_from_ui,
                on_duplicate=self.duplicate_export_preset_from_ui,
                on_delete=self.delete_export_preset_from_ui,
            )
            lst.addItem(item)
            lst.setItemWidget(item, row)
            item.setSizeHint(row.preferred_size_hint())
        lst.blockSignals(False)

        if selected and not str(selected).startswith("__"):
            for i in range(lst.count()):
                it = lst.item(i)
                if it is not None and it.data(Qt.ItemDataRole.UserRole) == selected:
                    lst.setCurrentItem(it)
                    break

        self._sync_export_preset_selection_chrome()
        # Keep Video Settings Custom section in sync (not on expand-only rebuilds).
        quality_fp = (tuple(names), frozenset(fav_set), max_h)
        if getattr(self, "_quality_combo_custom_fp", None) != quality_fp:
            self._quality_combo_custom_fp = quality_fp
            preserve = ""
            if hasattr(self.ui, "combo_quality"):
                preserve = self.ui.combo_quality.currentText()
            self._rebuild_quality_preset_combo(
                max_height=max_h,
                preserve_text=preserve,
            )

    def _toggle_export_preset_row_expanded(self, name: str) -> None:
        key = (name or "").strip()
        if not key:
            return
        self._select_export_preset_by_name(key)
        expanded = self._export_preset_expanded_names()
        if key in expanded:
            expanded.discard(key)
        else:
            expanded.add(key)
        lst = getattr(self.ui, "preset_list", None)
        if lst is None:
            return
        for i in range(lst.count()):
            it = lst.item(i)
            if it is None or it.data(Qt.ItemDataRole.UserRole) != key:
                continue
            row = lst.itemWidget(it)
            if row is not None and hasattr(row, "set_expanded"):
                row.set_expanded(key in expanded)
                it.setSizeHint(row.preferred_size_hint())
            break

    def _select_export_preset_by_name(self, name: str) -> None:
        lst = getattr(self.ui, "preset_list", None)
        if lst is None:
            return
        for i in range(lst.count()):
            it = lst.item(i)
            if it is not None and it.data(Qt.ItemDataRole.UserRole) == name:
                lst.setCurrentItem(it)
                return
        # Not in filtered list — clear search and retry.
        search = getattr(self.ui, "preset_search_edit", None)
        if search is not None and (search.text() or "").strip():
            search.blockSignals(True)
            search.clear()
            search.blockSignals(False)
            self.refresh_export_presets_list()
            for i in range(lst.count()):
                it = lst.item(i)
                if it is not None and it.data(Qt.ItemDataRole.UserRole) == name:
                    lst.setCurrentItem(it)
                    break

    def _sync_export_preset_selection_chrome(self) -> None:
        # Row widgets carry their own actions; selection only drives the name field.
        return

    def _on_export_preset_selection_changed(self) -> None:
        edit = getattr(self.ui, "preset_name_edit", None)
        name = self._list_selected_export_preset_name()
        if edit is not None and name:
            edit.setText(name)

    def _selected_export_preset_name(self) -> str:
        """Name field first (Save as new), else selected list row."""
        edit = getattr(self.ui, "preset_name_edit", None)
        if edit is not None:
            typed = (edit.text() or "").strip()
            if typed:
                return typed
        return self._list_selected_export_preset_name()

    def _set_preset_status(self, text: str) -> None:
        label = getattr(self.ui, "preset_status_label", None)
        if label is not None:
            label.setText(text or "")

    def _persist_render_settings_quiet(self) -> None:
        try:
            from steempeg.ui.portable.sheets import persist_render_settings

            persist_render_settings(self)
        except Exception:
            pass

    def _prompt_export_preset_rename(self, current: str) -> str | None:
        """Steempeg-chrome rename prompt. Returns new name or None if cancelled."""
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton

        from steempeg.ui.message_dialog import _BTN_PRIMARY, _BTN_SECONDARY, dialog_theme
        from steempeg.ui.widgets.dialog_chrome import SteempegDialog

        theme = dialog_theme(self.ui)
        dlg = SteempegDialog("Rename preset", self.ui, **theme)
        from steempeg.ui.ui_density import scaled_dialog_size

        mw, mh = scaled_dialog_size(380, 160, parent=self.ui)
        dlg.setMinimumSize(mw, mh)
        dlg.resize(*scaled_dialog_size(400, 170, parent=self.ui))

        root = dlg.content_layout
        tip = QLabel(f"Rename “{current}”")
        tip.setStyleSheet(
            "color: #cfcfcf; background: transparent; font-size: 12px;"
            f" font-family: {tok.FONT_APP};"
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        edit = QLineEdit(current)
        edit.setStyleSheet(
            "QLineEdit { background-color: #2a2a2a; color: #e8e8e8; border: 1px solid #444;"
            " border-radius: 8px; padding: 8px 10px; font-weight: bold; }"
            " QLineEdit:focus { border: 1px solid #8e7cc3; }"
        )
        edit.selectAll()
        root.addWidget(edit)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(_BTN_SECONDARY)
        btn_cancel.clicked.connect(dlg.reject)
        actions.addWidget(btn_cancel)
        actions.addStretch(1)
        btn_ok = QPushButton("Rename")
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet(_BTN_PRIMARY)
        btn_ok.clicked.connect(dlg.accept)
        actions.addWidget(btn_ok)
        root.addLayout(actions)

        edit.returnPressed.connect(dlg.accept)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return None
        return (edit.text() or "").strip() or None

    def create_export_preset_in_editor(self) -> None:
        """Open the mini-editor to author a new Custom preset."""
        from steempeg.ui.preset_mini_editor import open_preset_mini_editor

        key = open_preset_mini_editor(self)
        if not key:
            return
        self.refresh_export_presets_list()
        self._select_export_preset_by_name(key)
        edit = getattr(self.ui, "preset_name_edit", None)
        if edit is not None:
            edit.setText(key)
        self._set_preset_status(f"Created “{key}” in the mini-editor.")

    def edit_export_preset_in_editor(self, name: str | None = None) -> None:
        """Open the mini-editor for an existing Custom preset."""
        from steempeg.ui.message_dialog import steempeg_warning
        from steempeg.ui.preset_mini_editor import open_preset_mini_editor

        selected = (name or "").strip() or self._list_selected_export_preset_name()
        if not selected:
            steempeg_warning(
                self.ui,
                "Edit preset",
                "Select a saved Custom preset in the list first.",
            )
            return
        key = open_preset_mini_editor(self, edit_name=selected)
        if not key:
            return
        expanded = self._export_preset_expanded_names()
        if selected in expanded and key != selected:
            expanded.discard(selected)
            expanded.add(key)
        self.refresh_export_presets_list()
        self._select_export_preset_by_name(key)
        edit = getattr(self.ui, "preset_name_edit", None)
        if edit is not None:
            edit.setText(key)
        self._set_preset_status(f"Updated “{key}” in the mini-editor.")

    def save_export_preset_from_ui(self) -> None:
        from steempeg.render.export_presets import load_presets_map, save_preset
        from steempeg.ui.message_dialog import steempeg_information, steempeg_question, steempeg_warning
        from steempeg.ui.render_job_builder import snapshot_settings_from_ui

        name = self._selected_export_preset_name()
        if not name:
            steempeg_warning(
                self.ui,
                "Save preset",
                "Enter a name for the preset first.",
            )
            return
        existing = load_presets_map(self.load_user_settings)
        if name in existing:
            if not steempeg_question(
                self.ui,
                "Overwrite preset?",
                f"“{name}” already exists. Overwrite it with the current panel settings?",
            ):
                return
        try:
            key = save_preset(
                name,
                snapshot_settings_from_ui(self),
                load_settings=self.load_user_settings,
                save_settings=self.save_user_settings,
            )
        except ValueError as exc:
            steempeg_warning(self.ui, "Save preset", str(exc))
            return
        self.refresh_export_presets_list()
        self._select_export_preset_by_name(key)
        self._set_preset_status(f"Saved preset “{key}”.")
        steempeg_information(self.ui, "Preset saved", f"Saved “{key}”.")
        self._persist_render_settings_quiet()

    def update_export_preset_from_ui(self, name: str | None = None) -> None:
        """Overwrite a saved preset from the live panel."""
        from steempeg.render.export_presets import save_preset
        from steempeg.ui.message_dialog import steempeg_warning
        from steempeg.ui.render_job_builder import snapshot_settings_from_ui

        selected = (name or "").strip() or self._list_selected_export_preset_name()
        if not selected:
            steempeg_warning(
                self.ui,
                "Update preset",
                "Select a saved preset in the list first.",
            )
            return
        self._select_export_preset_by_name(selected)
        try:
            key = save_preset(
                selected,
                snapshot_settings_from_ui(self),
                load_settings=self.load_user_settings,
                save_settings=self.save_user_settings,
            )
        except (KeyError, ValueError) as exc:
            steempeg_warning(self.ui, "Update preset", str(exc))
            return
        self.refresh_export_presets_list()
        self._select_export_preset_by_name(key)
        self._set_preset_status(f"Updated “{key}” from the current panel.")
        self._persist_render_settings_quiet()

    def rename_export_preset_from_ui(self, name: str | None = None) -> None:
        from steempeg.render.export_presets import rename_preset
        from steempeg.ui.message_dialog import steempeg_warning

        selected = (name or "").strip() or self._list_selected_export_preset_name()
        if not selected:
            steempeg_warning(
                self.ui,
                "Rename preset",
                "Select a saved preset in the list first.",
            )
            return
        self._select_export_preset_by_name(selected)
        new_name = self._prompt_export_preset_rename(selected)
        if new_name is None:
            return
        if new_name == selected:
            self._set_preset_status(f"“{selected}” already has that name.")
            return
        try:
            key = rename_preset(
                selected,
                new_name,
                load_settings=self.load_user_settings,
                save_settings=self.save_user_settings,
            )
        except FileExistsError:
            steempeg_warning(
                self.ui,
                "Rename preset",
                f"A preset named “{new_name}” already exists.",
            )
            return
        except (KeyError, ValueError) as exc:
            steempeg_warning(self.ui, "Rename preset", str(exc))
            return
        expanded = self._export_preset_expanded_names()
        if selected in expanded:
            expanded.discard(selected)
            expanded.add(key)
        self.refresh_export_presets_list()
        self._select_export_preset_by_name(key)
        edit = getattr(self.ui, "preset_name_edit", None)
        if edit is not None:
            edit.setText(key)
        self._set_preset_status(f"Renamed to “{key}”.")

    def duplicate_export_preset_from_ui(self, name: str | None = None) -> None:
        from steempeg.render.export_presets import duplicate_preset
        from steempeg.ui.message_dialog import steempeg_warning

        selected = (name or "").strip() or self._list_selected_export_preset_name()
        if not selected:
            steempeg_warning(
                self.ui,
                "Duplicate preset",
                "Select a saved preset in the list first.",
            )
            return
        try:
            key = duplicate_preset(
                selected,
                load_settings=self.load_user_settings,
                save_settings=self.save_user_settings,
            )
        except (KeyError, ValueError, FileExistsError) as exc:
            steempeg_warning(self.ui, "Duplicate preset", str(exc))
            return
        self.refresh_export_presets_list()
        self._select_export_preset_by_name(key)
        edit = getattr(self.ui, "preset_name_edit", None)
        if edit is not None:
            edit.setText(key)
        self._set_preset_status(f"Duplicated as “{key}”.")

    def toggle_export_preset_favourite_from_ui(self, name: str | None = None) -> None:
        from steempeg.render.export_presets import toggle_favourite
        from steempeg.ui.message_dialog import steempeg_warning

        selected = (name or "").strip() or self._list_selected_export_preset_name()
        if not selected:
            steempeg_warning(
                self.ui,
                "Favourite preset",
                "Select a saved preset in the list first.",
            )
            return
        try:
            pinned = toggle_favourite(
                selected,
                load_settings=self.load_user_settings,
                save_settings=self.save_user_settings,
            )
        except (KeyError, ValueError) as exc:
            steempeg_warning(self.ui, "Favourite preset", str(exc))
            return
        self.refresh_export_presets_list()
        self._select_export_preset_by_name(selected)
        if pinned:
            self._set_preset_status(f"Pinned “{selected}” to favourites.")
        else:
            self._set_preset_status(f"Removed “{selected}” from favourites.")

    def apply_export_preset_to_panel(self, name: str | None = None) -> None:
        from dataclasses import replace

        from steempeg.render.export_presets import get_preset_settings
        from steempeg.render.quality_presets import (
            resolve_fps_for_source,
            resolve_quality_for_source,
        )
        from steempeg.ui.message_dialog import steempeg_warning
        from steempeg.ui.render_job_builder import apply_job_settings_to_ui

        preset_name = (
            (name or "").strip()
            or self._list_selected_export_preset_name()
            or self._selected_export_preset_name()
        )
        if not preset_name:
            steempeg_warning(self.ui, "Apply preset", "Select a preset in the list.")
            return
        settings = get_preset_settings(preset_name, self.load_user_settings)
        if settings is None:
            steempeg_warning(
                self.ui,
                "Apply preset",
                f"No saved preset named “{preset_name}”.",
            )
            return
        self._select_export_preset_by_name(preset_name)

        src_h = int(getattr(self, "current_orig_height", 0) or 0)
        src_fps = int(getattr(self, "current_orig_fps", 0) or 0)
        orig_q = settings.quality_text or ""
        resolved_q = resolve_quality_for_source(
            settings.quality_text,
            src_h,
            fallback=getattr(settings, "quality_fallback", None) or "Original",
        )
        resolved_fps = resolve_fps_for_source(settings.fps_text, src_fps)
        if resolved_q != settings.quality_text or resolved_fps != settings.fps_text:
            settings = replace(
                settings,
                quality_text=resolved_q,
                fps_text=resolved_fps,
            )

        # One summary rebuild at the end — not once per combo signal.
        self._applying_export_preset = True
        try:
            apply_job_settings_to_ui(self, settings, refresh_summary=True)
            # Explicit apply only — never auto-check from matching UI by accident.
            self._set_active_custom_preset(preset_name)
        finally:
            self._applying_export_preset = False
        if resolved_q != orig_q:
            self._set_preset_status(
                f"Applied “{preset_name}” (quality → {resolved_q} for this clip)."
            )
        else:
            self._set_preset_status(f"Applied “{preset_name}” to the export panel.")
        self._persist_render_settings_quiet()

    # --- Active Custom preset checkmark (Quality Preset combo) ---------------

    def _custom_preset_canon_fp(self, settings) -> tuple:
        """Fingerprint of recipe fields — ignore clip path / basename drift."""
        from steempeg.render.export_presets import settings_to_preset_dict

        data = settings_to_preset_dict(settings)
        for key in ("save_dir", "output_basename"):
            data.pop(key, None)
        return tuple(sorted((str(k), repr(v)) for k, v in data.items()))

    def _set_active_custom_preset(self, name: str | None) -> None:
        """Mark a Custom recipe as the live canon (shows ✓ in the dual popup)."""
        key = " ".join((name or "").strip().split())
        self._active_custom_preset_name = key or None
        self._active_custom_preset_fp = None
        combo = getattr(self.ui, "combo_quality", None)
        if combo is not None:
            combo._steempeg_active_custom_preset = key or None
        if not key:
            return
        try:
            from steempeg.ui.render_job_builder import snapshot_settings_from_ui

            self._active_custom_preset_fp = self._custom_preset_canon_fp(
                snapshot_settings_from_ui(self)
            )
        except Exception:
            self._active_custom_preset_fp = None

    def _clear_active_custom_preset(self) -> None:
        if not getattr(self, "_active_custom_preset_name", None):
            return
        self._set_active_custom_preset(None)

    def _revalidate_active_custom_preset(self) -> None:
        """Drop ✓ when the panel drifts from the explicitly applied Custom recipe."""
        if getattr(self, "_applying_export_preset", False):
            return
        if getattr(self, "_bulk_settings_apply", False):
            return
        if getattr(self, "_quality_combo_applying_custom", False):
            return
        name = getattr(self, "_active_custom_preset_name", None)
        if not name:
            return
        want = getattr(self, "_active_custom_preset_fp", None)
        if want is None:
            self._clear_active_custom_preset()
            return
        try:
            from steempeg.ui.render_job_builder import snapshot_settings_from_ui

            live = self._custom_preset_canon_fp(snapshot_settings_from_ui(self))
        except Exception:
            return
        if live != want:
            self._clear_active_custom_preset()

    def delete_export_preset_from_ui(self, name: str | None = None) -> None:
        from steempeg.render.export_presets import delete_preset
        from steempeg.ui.message_dialog import steempeg_question, steempeg_warning

        preset_name = (name or "").strip() or self._list_selected_export_preset_name()
        if not preset_name:
            steempeg_warning(
                self.ui,
                "Delete preset",
                "Select a preset in the list to delete.",
            )
            return
        if not steempeg_question(
            self.ui,
            "Delete preset?",
            f"Delete saved preset “{preset_name}”?\n\nThis cannot be undone.",
        ):
            return
        if not delete_preset(
            preset_name,
            load_settings=self.load_user_settings,
            save_settings=self.save_user_settings,
        ):
            steempeg_warning(
                self.ui,
                "Delete preset",
                f"No saved preset named “{preset_name}”.",
            )
            return
        self._export_preset_expanded_names().discard(preset_name)
        edit = getattr(self.ui, "preset_name_edit", None)
        if edit is not None:
            edit.clear()
        self.refresh_export_presets_list()
        self._set_preset_status(f"Deleted “{preset_name}”.")

    def apply_export_preset_to_queue_job(self, job_id: str, preset_name: str) -> None:
        from steempeg.render.export_presets import apply_preset_to_job, get_preset_settings
        from steempeg.ui.message_dialog import steempeg_warning

        job = self.render_queue.get(job_id) if hasattr(self, "render_queue") else None
        if job is None:
            return
        settings = get_preset_settings(preset_name, self.load_user_settings)
        if settings is None:
            steempeg_warning(
                self.ui,
                "Apply preset",
                f"No saved preset named “{preset_name}”.",
            )
            return
        apply_preset_to_job(job, settings, preset_name=preset_name)
        if job_id == getattr(self, "_selected_queue_job_id", None):
            from steempeg.ui.render_job_builder import apply_job_settings_to_ui

            apply_job_settings_to_ui(self, job.settings)
            if hasattr(self, "update_final_setup"):
                self.update_final_setup()
        self._persist_render_queue()
        self.refresh_render_queue_panel()
        if hasattr(self, "set_status"):
            self.set_status(f"Applied preset “{preset_name}” to queue job.")

    def apply_panel_settings_to_queue_job(self, job_id: str) -> None:
        """Per-job edit: push the live export panel onto one queued job."""
        from steempeg.render.export_presets import apply_preset_to_job
        from steempeg.ui.render_job_builder import snapshot_settings_from_ui

        job = self.render_queue.get(job_id) if hasattr(self, "render_queue") else None
        if job is None:
            return
        apply_preset_to_job(job, snapshot_settings_from_ui(self), preset_name="")
        # Don't force "User: …" label when pushing live panel.
        if (job.settings.output_preset or "").startswith("User:"):
            job.settings.output_preset = "Custom"
            job.refresh_output_path()
        self._persist_render_queue()
        self.refresh_render_queue_panel()
        if hasattr(self, "set_status"):
            self.set_status("Applied panel settings to queue job.")

    def activate_queue_job(self, job_id: str) -> None:
        """Load preview, trim, and settings from a queue job snapshot."""
        if getattr(self, "_clips_scan_active", False):
            if hasattr(self, "set_status"):
                self.set_status("Library is still loading — Queue is locked.")
            return
        job = self.render_queue.get(job_id)
        if not job:
            return
        if getattr(self, "_queue_scheme_deferred", False):
            # Clicking a queued card re-enters the scheme with this job.
            self._queue_scheme_deferred = False
            self._queue_resume_job_id = None
        self._queue_library_preview_diversion = False
        # Persist the *previous* selection before the loading gate blocks sync.
        self._flush_clip_session_state()
        if self._sync_active_queue_job_from_ui():
            self._persist_render_queue()
        prev_preview = os.path.normpath(getattr(self, "_preview_clip_path", None) or "")
        prev_opening = os.path.normpath(getattr(self, "_opening_clip_path", None) or "")
        job_norm = os.path.normpath(job.clip_path or "")
        self._loading_queue_job = True
        try:
            self._selected_queue_job_id = job_id
            self._preview_clip_path = job.clip_path
            # Per-job snapshot — never path memory (duplicates share clip_path).
            session = self._session_state_from_job_settings(job)
            self._apply_header_from_job(job)
            if hasattr(self, "set_player_header_clip_controls_visible"):
                self.set_player_header_clip_controls_visible(True)
            same_preview = bool(job_norm) and job_norm in (prev_preview, prev_opening)
            preview_idle = not (
                getattr(self, "_is_switching", False)
                or getattr(self, "_awaiting_first_frame", False)
            )
            if same_preview and preview_idle and hasattr(self, "apply_trim_state"):
                # Same media already up — remounting is wasteful and the in-flight
                # spam guard can leave the previous job's Trim on screen.
                self._pending_trim_restore = None
                self._apply_clip_session_state(session, silent=True)
                self._populate_quality_options_for_clip(
                    job.clip_path, preserve_ui_selection=False,
                )
                apply_job_settings_to_ui(self, job.settings)
                self.update_final_setup()
                self._loading_queue_job = False
            else:
                # Start playback before Source Info XML / size work.
                self.generate_and_play_preview(job.clip_path, trim_restore=session)
                self._populate_quality_options_for_clip(
                    job.clip_path, preserve_ui_selection=False,
                )
                self._apply_export_session_state(session, silent=True)
                apply_job_settings_to_ui(self, job.settings)
                self.update_final_setup()
                if hasattr(self, "_maybe_start_thumbs_after_quality"):
                    self._maybe_start_thumbs_after_quality(job.clip_path)
        except Exception:
            self._loading_queue_job = False
            raise
        self._highlight_clip_in_library(job.clip_path)
        # Card/list selection only — do not force the Render Queue pane open.
        self.refresh_render_queue_panel(sync_splitter=False)
        self.update_playback_badge()
        self._update_start_button_label()
        if hasattr(self, "_sync_library_mode_chrome"):
            if not getattr(self, "_render_dock_visible", False):
                self._sync_library_mode_chrome()
        # Queue selection must refresh Ready badge + neo binding chrome.
        if hasattr(self, "update_status_indicator"):
            self.update_status_indicator("Ready", "ready")
        if hasattr(self, "_ensure_docked_neo_visible_for_context"):
            try:
                self._ensure_docked_neo_visible_for_context()
            except Exception:
                pass

    def on_queue_job_selected(self, job_id: str):
        """Load preview and settings for the selected queue card."""
        if getattr(self, "_clips_scan_active", False):
            if hasattr(self, "set_status"):
                self.set_status("Library is still loading — Queue is locked.")
            return
        logging.info("Queue selection: %s", job_id)
        self.activate_queue_job(job_id)
    def _highlight_clip_in_library(self, clip_path: str) -> None:
        """Mirror a queue selection back onto the Grid/List card (no preview reload)."""
        if not clip_path or not hasattr(self.ui, "table_clips"):
            return
        norm = os.path.normpath(clip_path)
        table = self.ui.table_clips
        target_row = -1
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and os.path.normpath(item.data(Qt.UserRole) or "") == norm:
                target_row = row
                break
        if target_row < 0:
            return

        # Filtered-out clips stay in the table as hidden rows. Selecting them and
        # scrollToItem left a blank strip at the top of Choose-a-Clip — reveal
        # just this card so the queue pick is visible without wiping the filter.
        if table.isRowHidden(target_row):
            table.setRowHidden(target_row, False)
            if hasattr(self, "grid_clips"):
                for i in range(self.grid_clips.count()):
                    gi = self.grid_clips.item(i)
                    if gi is not None and gi.data(Qt.UserRole) == target_row:
                        gi.setHidden(False)
                        break

        table.blockSignals(True)
        table.clearSelection()
        table.selectRow(target_row)
        table.setCurrentCell(target_row, 0)
        table.blockSignals(False)

        if hasattr(self, "grid_clips"):
            self.grid_clips.blockSignals(True)
            anchor_item = None
            for i in range(self.grid_clips.count()):
                gi = self.grid_clips.item(i)
                is_match = gi.data(Qt.UserRole) == target_row
                gi.setSelected(is_match)
                if is_match:
                    anchor_item = gi
            self.grid_clips.blockSignals(False)
            if anchor_item is not None and not anchor_item.isHidden():
                self._grid_anchor_item = anchor_item
                self._grid_anchor_index = self._list_widget_item_index(self.grid_clips, anchor_item)
                self.grid_clips.scrollToItem(anchor_item)
            if hasattr(self, "_sync_grid_card_visuals"):
                self._sync_grid_card_visuals()
            if hasattr(self, "_update_library_count_label"):
                self._update_library_count_label()

    def remove_queue_job(self, job_id: str) -> None:
        self.remove_queue_jobs([job_id])

    def remove_queue_jobs(self, job_ids) -> None:
        """Remove one or more queued jobs (skips the job currently rendering)."""
        ids = [jid for jid in (job_ids or []) if jid]
        if not ids:
            return
        selected_id = getattr(self, "_selected_queue_job_id", None)
        was_selected = selected_id in ids
        removed_any = False
        removed_jobs: list = []
        for job_id in ids:
            job = self.render_queue.get(job_id)
            if not job:
                continue
            if job.status == JobStatus.RENDERING:
                continue
            if self.render_queue.remove(job_id):
                removed_any = True
                removed_jobs.append(job)
        if not removed_any:
            return
        for job in removed_jobs:
            self._maybe_clear_export_plaque_for_job(job)
        if not self.render_queue:
            self._on_queue_became_empty()
            return
        if was_selected:
            nxt = self.render_queue.jobs[0]
            self.activate_queue_job(nxt.id)
        sidebar = getattr(self, "_portable_queue_sidebar", None)
        portable_visible = False
        if sidebar is not None:
            try:
                portable_visible = bool(sidebar.isVisible())
            except RuntimeError:
                self._portable_queue_sidebar = None
                sidebar = None
        if portable_visible and sidebar is not None and hasattr(sidebar, "refresh"):
            sidebar.refresh()
            self._update_start_button_label()
            self._sync_start_render_enabled()
            self._sync_queue_scheme_chrome()
            self.update_playback_badge()
            QTimer.singleShot(
                0,
                lambda: self.refresh_render_queue_panel(
                    sync_splitter=False, include_portable=False
                ),
            )
        else:
            self.refresh_render_queue_panel()
            self._sync_start_render_enabled()
            self.update_playback_badge()
        self._persist_render_queue_async()

    def toggle_render_queue_scheme(self) -> None:
        """Leave queue-first chrome without Clear, or Resume the same list."""
        if getattr(self, "_queue_scheme_deferred", False):
            self.resume_render_queue_scheme()
        else:
            self.leave_render_queue_scheme()

    def leave_render_queue_scheme(self) -> None:
        """Drop queue-first chrome (header / Start) while keeping jobs and the queue UI."""
        if getattr(self, "_queue_batch_active", False):
            steempeg_warning(
                self.ui,
                "Render Queue",
                "Stop the batch render before leaving queue mode.",
            )
            return
        if getattr(self, "_is_rendering", False):
            steempeg_warning(
                self.ui,
                "Render Queue",
                "Wait for the current render to finish before leaving queue mode.",
            )
            return
        if not getattr(self, "render_queue", None) or not len(self.render_queue):
            return
        self._queue_resume_job_id = None
        self._queue_scheme_deferred = True
        # While Left, identity follows the playing clip; keep that across Resume
        # until the user activates a queue card (or clears the queue).
        self._queue_library_preview_diversion = bool(
            getattr(self, "_preview_clip_path", None)
        )
        logging.info(
            "Left render queue mode — %s job(s) kept",
            len(self.render_queue),
        )
        self._clear_queue_selection()
        # Drop queue-driven header / Ready cluster / In-queue plaque immediately.
        self._sync_queue_player_and_dash_chrome()
        if hasattr(self, "update_final_setup"):
            try:
                self.update_final_setup()
            except Exception:
                logging.debug("update_final_setup after leave queue failed", exc_info=True)
        self._sync_start_render_enabled()
        if not getattr(self, "_is_rendering", False):
            self.update_status_indicator("Ready", "ready")
        self.update_playback_badge()
        self.refresh_render_queue_panel()

    def resume_render_queue_scheme(self) -> None:
        """Re-enter queue mode with the same jobs — keep current preview/selection."""
        if not getattr(self, "_queue_scheme_deferred", False):
            return
        if getattr(self, "_clips_scan_active", False):
            if hasattr(self, "set_status"):
                self.set_status("Library is still loading — Queue is locked.")
            return
        if not getattr(self, "render_queue", None) or not len(self.render_queue):
            self._queue_scheme_deferred = False
            self._queue_resume_job_id = None
            self._queue_library_preview_diversion = False
            self._sync_queue_scheme_chrome()
            return
        self._queue_scheme_deferred = False
        self._queue_resume_job_id = None
        # Resume restores queue-first identity unless the user is mid library preview.
        # Keep an existing diversion (previewing a non-queue card) so the header
        # does not jump back to Ready #1 while that clip is still playing.
        logging.info(
            "Resumed render queue mode — %s job(s)",
            len(self.render_queue),
        )
        # Do not seek/select job #1 or any queue card.
        self._sync_queue_player_and_dash_chrome()
        self._sync_start_render_enabled()
        self.update_playback_badge()
        self.refresh_render_queue_panel()
        if not getattr(self, "_is_rendering", False):
            self.update_status_indicator("Ready", "ready")

    def _sync_queue_scheme_chrome(self) -> None:
        has_jobs = bool(getattr(self, "render_queue", None)) and len(self.render_queue) > 0
        if not has_jobs:
            self._queue_scheme_deferred = False
            self._queue_resume_job_id = None
            self._queue_library_preview_diversion = False
        deferred = bool(getattr(self, "_queue_scheme_deferred", False)) and has_jobs
        busy = bool(
            getattr(self, "_is_rendering", False)
            or getattr(self, "_queue_batch_active", False)
        )
        self._sync_host_queue_leave_resume(deferred=deferred, has_jobs=has_jobs, busy=busy)

    def _sync_host_queue_leave_resume(
        self, *, deferred: bool, has_jobs: bool, busy: bool
    ) -> None:
        """Leave/Resume beside Render Queue (N) / Start — purple while deferred."""
        self._ensure_desktop_queue_leave_resume_button()
        desk = getattr(self, "_btn_queue_leave_resume", None)
        if desk is not None:
            try:
                show = bool(has_jobs)
                desk.setVisible(show)
                desk.setEnabled(show and not bool(busy))
                if show:
                    self._paint_desktop_queue_leave_resume(desk, deferred=bool(deferred))
            except RuntimeError:
                self._btn_queue_leave_resume = None
        strip = getattr(self, "_portable_render_strip", None)
        if strip is not None and hasattr(strip, "sync_queue_leave_resume"):
            try:
                strip.sync_queue_leave_resume(
                    deferred=bool(deferred),
                    has_jobs=bool(has_jobs),
                    busy=bool(busy),
                )
            except RuntimeError:
                self._portable_render_strip = None
        elif strip is not None and hasattr(strip, "set_queue_resume_visible"):
            try:
                strip.set_queue_resume_visible(bool(has_jobs))
            except RuntimeError:
                self._portable_render_strip = None

    def _paint_desktop_queue_leave_resume(self, btn, *, deferred: bool) -> None:
        from PySide6.QtCore import QSize

        from steempeg.ui.icon_assets import load_icon

        dense = getattr(self, "_ui_density", None)
        font = int(getattr(dense, "dash_font", 13) or 13)
        btn_h = int(getattr(dense, "dash_btn_h", 36) or 36)
        pad = "1px 8px" if getattr(dense, "compact", False) else "6px 14px"
        radius = max(8, btn_h // 2)
        icon_sz = 16
        btn.setFixedHeight(btn_h)
        btn.setIconSize(QSize(icon_sz, icon_sz))
        if deferred:
            btn.setText(" Resume")
            btn.setToolTip("Return to queue mode with the same jobs and order")
            btn.setIcon(load_icon("resume.png", icon_sz))
            btn.setStyleSheet(
                "QPushButton {"
                f" background-color: #5a4b7a; color: #ffffff; border: 2px solid #8e7cc3;"
                f" border-radius: {radius}px; padding: {pad}; font-size: {font}px;"
                " font-weight: bold;"
                " font-family: " + tok.FONT_APP + ";"
                "}"
                "QPushButton:hover { background-color: #6b5a8e; border: 2px solid #b29ae7; }"
                "QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }"
                "QPushButton:disabled {"
                " background-color: #262626; color: #5a5a5a; border: 2px solid #333333;"
                "}"
            )
        else:
            btn.setText(" Leave")
            btn.setToolTip(
                "Leave queue mode — keep all jobs. Preview or render something else, then Resume."
            )
            btn.setIcon(load_icon("exit.png", icon_sz))
            from steempeg.ui import ui_theme as ut

            if ut.get_ui_theme() != ut.UI_THEME_DEFAULT:
                btn.setStyleSheet(
                    ut.dash_secondary_button_stylesheet(
                        font=font, radius=radius, pad=pad
                    )
                )
            else:
                btn.setStyleSheet(
                    "QPushButton {"
                    f" background-color: #383838; color: #e0e0e0; border: 2px solid #4a4a4a;"
                    f" border-radius: {radius}px; padding: {pad}; font-size: {font}px;"
                    " font-weight: bold;"
                    " font-family: " + tok.FONT_APP + ";"
                    "}"
                    "QPushButton:hover { background-color: #404040; color: #ffffff; border: 2px solid #6b5a8e; }"
                    "QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }"
                    "QPushButton:disabled {"
                    " background-color: #262626; color: #5a5a5a; border: 2px solid #333333;"
                    "}"
                )

    def _ensure_desktop_queue_leave_resume_button(self) -> None:
        """Leave/Resume CTA on the desktop render dash beside Render Queue (N)."""
        if getattr(self, "_portable_shell", False):
            return
        btn = getattr(self, "_btn_queue_leave_resume", None)
        if btn is not None:
            try:
                btn.objectName()
                return
            except RuntimeError:
                self._btn_queue_leave_resume = None
        # Migrate older Resume-only host if still present.
        legacy = getattr(self, "_btn_queue_resume_host", None)
        if legacy is not None:
            try:
                legacy.hide()
                legacy.deleteLater()
            except RuntimeError:
                pass
            self._btn_queue_resume_host = None
        row = getattr(self, "_dash_btn_row", None)
        if row is None:
            return
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QSizePolicy

        from steempeg.ui.icon_assets import load_icon

        btn = QPushButton(" Leave")
        btn.setObjectName("desktopQueueLeaveResume")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(
            "Leave queue mode — keep all jobs. Preview or render something else, then Resume."
        )
        btn.setIcon(load_icon("exit.png", 16))
        btn.setIconSize(QSize(16, 16))
        btn.setMinimumHeight(36)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setAutoDefault(False)
        btn.setDefault(False)
        self._paint_desktop_queue_leave_resume(btn, deferred=False)
        btn.clicked.connect(self.toggle_render_queue_scheme)
        btn.hide()
        # Sit beside Start / Render Queue (N).
        insert_at = 1
        start = getattr(getattr(self, "ui", None), "btn_start", None)
        if start is not None:
            for i in range(row.count()):
                item = row.itemAt(i)
                if item is not None and item.widget() is start:
                    insert_at = i + 1
                    break
        row.insertWidget(insert_at, btn)
        self._btn_queue_leave_resume = btn

    def _sync_host_queue_resume_buttons(self, *, deferred: bool, busy: bool) -> None:
        """Compat shim for older call sites."""
        has_jobs = bool(getattr(self, "render_queue", None)) and len(self.render_queue) > 0
        self._sync_host_queue_leave_resume(
            deferred=bool(deferred) and has_jobs,
            has_jobs=has_jobs,
            busy=busy,
        )

    def _ensure_desktop_queue_resume_button(self) -> None:
        """Compat shim — creates the Leave/Resume dash control."""
        self._ensure_desktop_queue_leave_resume_button()

    def clear_render_queue(self) -> None:
        if getattr(self, "_queue_batch_active", False):
            steempeg_warning(self.ui, "Render Queue", "Stop the batch render before clearing the queue.")
            return
        if not len(self.render_queue):
            return
        if not steempeg_question(
            self.ui,
            "Clear Queue",
            f"Remove all {len(self.render_queue)} clip(s) from the render queue?",
        ):
            return
        self._clear_render_queue_silent()

    def _clear_render_queue_silent(self) -> None:
        """Clear the live queue without a confirmation prompt (history is separate)."""
        if not len(self.render_queue):
            return
        self.render_queue.clear()
        self._completed_plaque_clip_path = None
        self._error_plaque_clip_path = None
        self._on_queue_became_empty()

    def _maybe_clear_export_plaque_for_job(self, job) -> None:
        """Drop Completed/Error header plaques when their queue row goes away."""
        if job is None:
            return
        if job.status not in (JobStatus.COMPLETED, JobStatus.ERROR):
            return
        clip_path = getattr(job, "clip_path", None)
        if not clip_path:
            return

        def _same(a, b) -> bool:
            if not a or not b:
                return False
            return os.path.normcase(os.path.normpath(a)) == os.path.normcase(
                os.path.normpath(b)
            )

        if _same(getattr(self, "_completed_plaque_clip_path", None), clip_path):
            self._completed_plaque_clip_path = None
        if _same(getattr(self, "_error_plaque_clip_path", None), clip_path):
            self._error_plaque_clip_path = None

    def reorder_queue_job(self, source_id: str, target_id: str) -> None:
        if getattr(self, "_queue_batch_active", False):
            return
        if self.render_queue.reorder(source_id, target_id):
            self.refresh_render_queue_panel()
            self._persist_render_queue()

    def reorder_queue_job_after(self, source_id: str, after_id: str) -> None:
        if getattr(self, "_queue_batch_active", False):
            return
        if self.render_queue.reorder_after(source_id, after_id):
            self.refresh_render_queue_panel()
            self._persist_render_queue()

    def _on_queue_became_empty(self) -> None:
        self._selected_queue_job_id = None
        self._queue_scheme_deferred = False
        self._queue_resume_job_id = None
        self._queue_library_preview_diversion = False
        self.refresh_render_queue_panel()
        self._sync_start_render_enabled()
        self._persist_render_queue()
        self._restore_header_from_library_selection()
        self.update_playback_badge()
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()
        if not getattr(self, "_is_rendering", False):
            self._reset_export_ui_after_queue_cleared()
            self.update_status_indicator("Ready", "ready")

    def _reset_export_ui_after_queue_cleared(self) -> None:
        """Drop stale export toggles/preset once the queue drains."""
        if getattr(self, "_loading_queue_job", False):
            return
        preview = getattr(self, "_preview_clip_path", None)
        self._apply_export_session_state(dict(_DEFAULT_CLIP_SESSION), silent=True)
        if preview and hasattr(self, "_clip_session_memory"):
            norm = os.path.normpath(preview)
            mem = self._clip_session_memory.get(norm)
            if mem is not None:
                for key in (
                    "container", "codec_text", "audio_format", "output_preset",
                    "audio_only", "mute_audio",
                ):
                    mem[key] = _DEFAULT_CLIP_SESSION[key]
        self.refresh_output_format_availability()
        self._sync_original_audio_controls()
        self._schedule_update_final_setup()

    def _current_header_clip_path(self):
        return self._current_preview_clip_path()

    def _queue_job_for_clip(self, clip_path):
        if not clip_path:
            return None
        return self.render_queue.find_by_clip_path(clip_path)

    def _queue_job_for_preview_sync(self, clip_path: str | None = None):
        """Resolve the queue job that should receive live trim/settings edits.

        Prefer the *selected* queue job when its clip path matches — identical
        clips share a path, so ``find_by_clip_path`` alone always hits the first
        duplicate and confuses TRIM / export memory across rows.
        """
        preview = clip_path or self._current_preview_clip_path()
        if not preview or not hasattr(self, "render_queue"):
            return None
        preview_norm = os.path.normpath(preview)
        selected_id = getattr(self, "_selected_queue_job_id", None)
        if selected_id:
            selected = self.render_queue.get(selected_id)
            if (
                selected is not None
                and os.path.normpath(selected.clip_path or "") == preview_norm
            ):
                return selected
        return self.render_queue.find_by_clip_path(preview)

    def _in_queue_membership_indices(self, clip_path) -> list:
        """1-based ``queue_index`` values for every job of this clip (ClipCard order)."""
        if not clip_path or not hasattr(self, "render_queue"):
            return []
        jobs = self.render_queue.find_all_by_clip_path(clip_path)
        indices = []
        for job in jobs:
            try:
                idx = int(getattr(job, "queue_index", 0) or 0)
            except (TypeError, ValueError):
                continue
            if idx > 0:
                indices.append(idx)
        return indices

    def _in_queue_label_for_clip(self, clip_path) -> str | None:
        """``In queue (N)`` for this clip; cycles when the clip is queued more than once."""
        indices = self._in_queue_membership_indices(clip_path)
        if not indices:
            return None
        stored = getattr(self, "_in_queue_cycle_indices", None) or []
        if list(stored) != list(indices):
            self._in_queue_cycle_i = 0
        if len(indices) == 1:
            return f"In queue ({indices[0]})"
        i = int(getattr(self, "_in_queue_cycle_i", 0) or 0) % len(indices)
        return f"In queue ({indices[i]})"

    def _ensure_in_queue_cycle(self, indices) -> None:
        clean = []
        for raw in indices or []:
            try:
                idx = int(raw)
            except (TypeError, ValueError):
                continue
            if idx > 0:
                clean.append(idx)
        indices = clean
        prev = getattr(self, "_in_queue_cycle_indices", None) or []
        if list(prev) != list(indices):
            self._in_queue_cycle_i = 0
        self._in_queue_cycle_indices = list(indices)
        if len(indices) <= 1:
            self._stop_in_queue_cycle()
            return
        timer = getattr(self, "_in_queue_cycle_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(1000)  # same cadence as ClipCard queue-badge cycling
            timer.timeout.connect(self._on_in_queue_cycle_tick)
            self._in_queue_cycle_timer = timer
        if not timer.isActive():
            timer.start()

    def _stop_in_queue_cycle(self) -> None:
        timer = getattr(self, "_in_queue_cycle_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._in_queue_cycle_i = 0

    def _sync_in_queue_cycle_for_clip(self, clip_path, *, showing_in_queue: bool) -> None:
        if not showing_in_queue or not clip_path:
            self._stop_in_queue_cycle()
            self._in_queue_cycle_indices = []
            return
        self._ensure_in_queue_cycle(self._in_queue_membership_indices(clip_path))

    def _on_in_queue_cycle_tick(self) -> None:
        indices = getattr(self, "_in_queue_cycle_indices", None) or []
        if len(indices) <= 1:
            self._stop_in_queue_cycle()
            return
        self._in_queue_cycle_i = (
            int(getattr(self, "_in_queue_cycle_i", 0) or 0) + 1
        ) % len(indices)
        try:
            self._apply_in_queue_cycle_frame()
        except RuntimeError:
            self._stop_in_queue_cycle()

    def _apply_in_queue_cycle_frame(self) -> None:
        """Swap In queue (N) text only — no chrome restyle on the 1s tick."""
        indices = getattr(self, "_in_queue_cycle_indices", None) or []
        if not indices:
            return
        i = int(getattr(self, "_in_queue_cycle_i", 0) or 0) % len(indices)
        label = f"In queue ({indices[i]})"
        badge = getattr(self, "label_playback_badge", None)
        if badge is not None:
            try:
                if badge.isVisible() and badge.text().strip().lower().startswith("in queue"):
                    badge.setText(f" {label}")
            except RuntimeError:
                pass
        in_btn = getattr(self, "btn_portable_in_queue", None)
        if in_btn is not None:
            try:
                if in_btn.isVisible() and in_btn.text().strip().lower().startswith("in queue"):
                    in_btn.setText(f" {label}")
            except RuntimeError:
                pass

    def _encode_is_paused(self) -> bool:
        """True while dash Pause has suspended the live encode thread."""
        if bool(getattr(self, "_encode_paused", False)):
            return True
        thread = getattr(self, "render_thread", None)
        if thread is not None and thread.isRunning():
            return bool(getattr(thread, "is_paused", False))
        return False

    def _focused_queue_job_for_badge(self, clip_path=None):
        """Queue job for the In-queue header chip (selected card, else clip match).

        N in ``In queue (N)`` is a 1-based ``queue_index``. When the open clip is
        queued more than once, the chip cycles those indices (~1s, same as ClipCard).
        Footer Ready+#N is next-to-render via ``_dash_ready_queue_job`` (not this).
        """
        def _same(a, b) -> bool:
            if not a or not b:
                return False
            return os.path.normcase(os.path.normpath(a)) == os.path.normcase(
                os.path.normpath(b)
            )

        selected_id = getattr(self, "_selected_queue_job_id", None)
        if selected_id:
            job = self.render_queue.get(selected_id)
            if job is not None:
                if not clip_path:
                    return job
                if _same(job.clip_path, clip_path):
                    return job
        if clip_path:
            # Prefer a live RENDERING job for this clip over an earlier QUEUED twin.
            matches = self.render_queue.find_all_by_clip_path(clip_path) or []
            for job in matches:
                if job.status == JobStatus.RENDERING:
                    return job
            return matches[0] if matches else None
        return None

    def _playback_badge_for_context(self):
        clip_path = self._current_header_clip_path()
        idle = not self._player_has_open_clip()

        def _same_clip(a, b) -> bool:
            if not a or not b:
                return False
            return os.path.normcase(os.path.normpath(a)) == os.path.normcase(
                os.path.normpath(b)
            )

        # Canceled dialog open → plaque stays until OK.
        if bool(getattr(self, "_canceled_plaque_active", False)):
            return CANCELED_BADGE_TEXT, CANCELED_BADGE_COLOR

        is_rendering = bool(getattr(self, "_is_rendering", False))
        deferred = not self._queue_is_active()

        def _live_encode_plaque():
            """Rendering or yellow Paused when dash Pause suspended the encode."""
            if self._encode_is_paused():
                return PAUSED_BADGE_TEXT, PAUSED_BADGE_COLOR
            return (
                STATUS_HEADER_LABELS[JobStatus.RENDERING],
                STATUS_COLORS[JobStatus.RENDERING],
            )

        # Live encode → orange Rendering (or yellow Paused) next to Healthy, even
        # after Leave and even when the header is idle «Choose a clip…».
        if is_rendering:
            active = getattr(self, "_active_render_job", None)
            if active is not None:
                if idle or _same_clip(getattr(active, "clip_path", None), clip_path):
                    return _live_encode_plaque()
                selected_id = getattr(self, "_selected_queue_job_id", None)
                if selected_id and selected_id == getattr(active, "id", None):
                    return _live_encode_plaque()

        # Idle after export / fail: keep Completed or Error without inventing a title.
        if idle:
            err_path = getattr(self, "_error_plaque_clip_path", None)
            if err_path:
                return STATUS_HEADER_LABELS[JobStatus.ERROR], ERROR_BADGE_COLOR
            remembered = getattr(self, "_completed_plaque_clip_path", None)
            if remembered:
                return (
                    STATUS_HEADER_LABELS[JobStatus.COMPLETED],
                    STATUS_COLORS[JobStatus.COMPLETED],
                )
            if not clip_path:
                return None, None

        if not clip_path:
            # No open clip → no Queue plank (desktop sidebar / portable chip cover totals).
            return None, None

        job = self._focused_queue_job_for_badge(clip_path)

        # Error — queue job or single-render latch (same idea as Completed).
        err_path = getattr(self, "_error_plaque_clip_path", None)
        if err_path and _same_clip(err_path, clip_path):
            return STATUS_HEADER_LABELS[JobStatus.ERROR], ERROR_BADGE_COLOR
        if job is not None and job.status == JobStatus.ERROR:
            return STATUS_HEADER_LABELS[JobStatus.ERROR], ERROR_BADGE_COLOR

        # Completed — always, including normal Start Render and Leave/deferred.
        # Single-clip exports never land a COMPLETED row in render_queue, so we
        # also honour ``_completed_plaque_clip_path`` set on successful finish.
        if job is not None and job.status == JobStatus.COMPLETED:
            return (
                STATUS_HEADER_LABELS[JobStatus.COMPLETED],
                STATUS_COLORS[JobStatus.COMPLETED],
            )
        remembered = getattr(self, "_completed_plaque_clip_path", None)
        if remembered and _same_clip(remembered, clip_path):
            return (
                STATUS_HEADER_LABELS[JobStatus.COMPLETED],
                STATUS_COLORS[JobStatus.COMPLETED],
            )

        # Leave (deferred): hide In-queue / Preview / Error plaques only.
        # Healthy stays; live Rendering + Completed handled above.
        if deferred:
            return None, None

        if hasattr(self, "get_clip_health_report"):
            if self.get_clip_health_report(clip_path).level == health.ClipHealth.DEAD:
                if hasattr(self, "_is_clip_cured") and self._is_clip_cured(clip_path):
                    if job:
                        if job.status == JobStatus.QUEUED:
                            return (
                                self._in_queue_label_for_clip(clip_path)
                                or f"In queue ({job.queue_index})",
                                STATUS_COLORS[JobStatus.QUEUED],
                            )
                        return STATUS_HEADER_LABELS[job.status], STATUS_COLORS[job.status]
                return None, None

        if job:
            if job.status == JobStatus.ERROR:
                return STATUS_HEADER_LABELS[JobStatus.ERROR], ERROR_BADGE_COLOR
            if job.status == JobStatus.RENDERING:
                if self._encode_is_paused():
                    return PAUSED_BADGE_TEXT, PAUSED_BADGE_COLOR
                return STATUS_HEADER_LABELS[JobStatus.RENDERING], STATUS_COLORS[JobStatus.RENDERING]
            return (
                self._in_queue_label_for_clip(clip_path)
                or f"In queue ({job.queue_index})",
                STATUS_COLORS[JobStatus.QUEUED],
            )

        # Preview only shows while the Render Queue actually has clips in it.
        # Portable replaces Preview with the Add to Queue / Queue chip.
        if getattr(self, "_portable_shell", False):
            return None, None
        return PREVIEW_BADGE_TEXT, PREVIEW_BADGE_COLOR

    def update_playback_badge(self):
        if not hasattr(self, "label_playback_badge"):
            return

        text, color = self._playback_badge_for_context()
        badge = self.label_playback_badge
        showing_in_queue = bool(text) and text.strip().lower().startswith("in queue")
        if not getattr(self, "_portable_shell", False):
            self._sync_in_queue_cycle_for_clip(
                self._current_header_clip_path(),
                showing_in_queue=showing_in_queue,
            )
        if not text:
            badge.hide()
            try:
                from PySide6.QtGui import QIcon

                badge.setIcon(QIcon())
            except Exception:
                pass
            if hasattr(self, "update_clip_health_button"):
                self.update_clip_health_button()
            self._sync_portable_queue_header_controls()
            return

        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon

        from steempeg.ui import design_tokens as tok
        from steempeg.ui.icon_assets import preview_badge_icon, queue_chip_icon

        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        label = text.strip()
        low = label.lower()
        icon_px = int(getattr(self, "_player_header_status_icon", 18) or 18)
        pad = getattr(self, "_player_header_status_pad", None) or "4px 12px 4px 10px"
        font_px = int(getattr(self, "_player_header_status_font", 13) or 13)
        min_h = int(getattr(self, "_player_header_status_min_h", 30) or 30)
        if low == "rendering":
            # Static tinted cube left of “Rendering” (mirrors Healthy icon+text).
            badge.setText(f" {label}")
            badge.setIcon(rendering_badge_icon(color, icon_px))
            badge.setIconSize(QSize(icon_px, icon_px))
        elif low == "paused":
            # Same pauserender bars as the dash Pause button, yellow plaque tint.
            badge.setText(f" {label}")
            badge.setIcon(paused_badge_icon(color, icon_px))
            badge.setIconSize(QSize(icon_px, icon_px))
        elif low == "canceled":
            badge.setText(f" {label}")
            badge.setIcon(canceled_badge_icon(color, icon_px))
            badge.setIconSize(QSize(icon_px, icon_px))
        elif low == "error":
            # Untinted issue.png — already a yellow warning triangle.
            badge.setText(f" {label}")
            badge.setIcon(error_badge_icon(icon_px))
            badge.setIconSize(QSize(icon_px, icon_px))
        elif low == "completed":
            badge.setIcon(completed_badge_icon(color, icon_px))
            badge.setIconSize(QSize(icon_px, icon_px))
            badge.setText(f" {label}")
        elif low.startswith("in queue"):
            # Match desktop health chip height (was squashed at 16px + 2px pad).
            badge.setIcon(queue_chip_icon(icon_px, color=color))
            badge.setIconSize(QSize(icon_px, icon_px))
            badge.setText(f" {label}")
        elif low == "preview":
            badge.setIcon(preview_badge_icon(icon_px, color=color))
            badge.setIconSize(QSize(icon_px, icon_px))
            badge.setText(f" {label}")
        else:
            badge.setIcon(QIcon())
            badge.setText(label)
        badge.setMinimumHeight(min_h)
        badge.setMinimumWidth(0)
        badge.setMaximumWidth(16777215)
        try:
            from steempeg.ui.player_header_layout import player_header_chip_qfont

            badge.setFont(player_header_chip_qfont(font_px))
        except Exception:
            pass
        badge.setStyleSheet(
            f"QPushButton {{"
            f"color: {color};"
            f"background-color: rgba({r}, {g}, {b}, 0.18);"
            f"border: 2px solid {color};"
            f"border-radius: 8px;"
            f"padding: {pad};"
            f"font-weight: bold;"
            f"font-size: {font_px}px;"
            f"font-family: {tok.FONT_APP};"
            f"}}"
        )
        badge.show()
        if hasattr(self, "update_clip_health_button"):
            self.update_clip_health_button()
        self._sync_portable_queue_header_controls()

    def _sync_portable_queue_header_controls(self) -> None:
        # Queue # circles on ClipCards — desktop + portable (not portable-like).
        # Debounce: full grid walk on every Preview/Healthy paint freezes footer clicks.
        if hasattr(self, "refresh_clip_queue_badges") or hasattr(
            self, "refresh_portable_clip_queue_badges"
        ):
            self._schedule_refresh_clip_queue_badges()
        if not getattr(self, "_portable_shell", False):
            return
        try:
            from steempeg.ui.portable.chrome import sync_portable_queue_header

            sync_portable_queue_header(self)
        except Exception:
            pass
        # Keep portable theatre CTA label in sync (count stays on Queue chip).
        try:
            from steempeg.ui.portable.chrome import sync_portable_render_button

            sync_portable_render_button(self)
        except Exception:
            pass

    def _schedule_refresh_clip_queue_badges(self, delay_ms: int = 80) -> None:
        timer = getattr(self, "_queue_badge_refresh_timer", None)
        if timer is None:
            timer = QTimer(getattr(self, "ui", None))
            timer.setSingleShot(True)
            timer.timeout.connect(self._run_scheduled_clip_queue_badge_refresh)
            self._queue_badge_refresh_timer = timer
        timer.start(max(0, int(delay_ms)))

    def _run_scheduled_clip_queue_badge_refresh(self) -> None:
        if hasattr(self, "refresh_clip_queue_badges"):
            try:
                self.refresh_clip_queue_badges()
                return
            except Exception:
                pass
        if hasattr(self, "refresh_portable_clip_queue_badges"):
            try:
                self.refresh_portable_clip_queue_badges()
            except Exception:
                pass

    def _apply_header_from_job(self, job):
        if not job or not hasattr(self, "custom_text_label"):
            return
        from steempeg.ui.player_header_layout import set_player_header_game_text

        # ``format_player_header_html`` splits ``date\\ntime`` and ignores
        # duration values mis-stored in ``clip_time`` on older jobs.
        set_player_header_game_text(
            self,
            (job.game_name or "").strip() or "—",
            date=job.clip_date or "",
            time=job.clip_time or "",
            duration=getattr(job, "duration_label", "") or "",
        )
        if hasattr(self, "custom_icon_label"):
            icon_path = resolve_job_game_icon_path(
                getattr(self, "cache_dir", "") or "", job
            )
            unknown = get_resource_path("unknown_icon.png")
            path = icon_path if icon_path and os.path.isfile(icon_path) else unknown
            if path and os.path.isfile(path):
                from steempeg.ui.icon_shape import shaped_game_icon_pixmap
                from steempeg.ui.icon_utils import apply_square_icon
                from steempeg.ui.player_header_layout import player_header_icon_px

                if icon_path and os.path.isfile(icon_path):
                    self.current_game_icon = icon_path
                icon_px = player_header_icon_px(self)
                src = QPixmap(path)
                shaped = shaped_game_icon_pixmap(src, icon_px) if not src.isNull() else None
                apply_square_icon(self.custom_icon_label, shaped, icon_px)

    def _sync_queue_job_render_status(self, job, success, error_msg, output_file: str = ""):
        """Update the queue row for this encode (by id, else same clip_path)."""
        if job is None:
            return
        target = self.render_queue.get(getattr(job, "id", ""))
        if target is None:
            clip_path = getattr(job, "clip_path", None)
            if clip_path:
                matches = self.render_queue.find_all_by_clip_path(clip_path) or []
                for candidate in matches:
                    if candidate.status == JobStatus.RENDERING:
                        target = candidate
                        break
                if target is None and len(matches) == 1:
                    target = matches[0]
                elif target is None and matches:
                    target = matches[0]
        if target is None:
            target = job
        if success:
            target.status = JobStatus.COMPLETED
            if output_file:
                target.output_file = output_file
        elif "cancelled by user" in (error_msg or "").lower():
            target.status = JobStatus.QUEUED
            target.error_message = ""
        else:
            target.status = JobStatus.ERROR
            target.error_message = (error_msg or "")[:240]

    def _remove_clip_from_render_queue(self, clip_path: str | None) -> None:
        """Drop every queue row for ``clip_path`` (after a successful export)."""
        if not clip_path or not hasattr(self, "render_queue"):
            return
        matches = self.render_queue.find_all_by_clip_path(clip_path) or []
        ids = [getattr(j, "id", "") for j in matches if getattr(j, "id", "")]
        if ids:
            self.remove_queue_jobs(ids)

    def _queue_source_unavailable_reason(self, clip_path: str) -> str | None:
        """Why this clip cannot encode now — missing folder or uncured Dead."""
        if not clip_path or not os.path.isdir(clip_path):
            return "Source clip folder is missing."
        if hasattr(self, "get_clip_health_report"):
            try:
                report = self.get_clip_health_report(clip_path)
            except Exception:
                report = None
            if report is not None and report.level == health.ClipHealth.DEAD:
                cured = hasattr(self, "_is_clip_cured") and self._is_clip_cured(clip_path)
                if not cured:
                    return "Source clip is Dead and cannot be rendered."
        return None

    def _fail_queue_job(
        self, job, message: str, *, batch_mode: bool, notify: bool = True
    ) -> None:
        """Mark a queue job ERROR (visible failed) without removing it."""
        if job is None:
            return
        live = self.render_queue.get(getattr(job, "id", "")) or job
        live.status = JobStatus.ERROR
        live.error_message = (message or "Source clip unavailable.")[:240]
        self._completed_plaque_clip_path = None
        self._error_plaque_clip_path = getattr(live, "clip_path", None)
        logging.warning(
            "Queue job ERROR (source unavailable): %s — %s",
            getattr(live, "clip_path", ""),
            live.error_message,
        )
        self.refresh_render_queue_panel()
        self.update_playback_badge()
        if hasattr(self, "_persist_render_queue"):
            self._persist_render_queue()
        if batch_mode:
            if getattr(self, "_queue_batch_active", False):
                self.process_next_in_queue()
            return
        if notify:
            steempeg_warning(
                self.ui,
                "Cannot render",
                live.error_message,
            )

    def _abort_active_render_as_error(self, message: str) -> bool:
        """Kill the running encode so finish lands as ERROR, not user-cancel."""
        msg = (message or "Source clip folder is missing.").strip()
        thread = getattr(self, "render_thread", None)
        if thread is None or not thread.isRunning():
            return False
        self._pending_render_error_override = msg
        # Do not latch batch cancel — that would stop the queue as a user Cancel.
        logging.warning("Aborting active render as ERROR: %s", msg)
        try:
            thread.cancel()
        except Exception:
            logging.exception("Failed to cancel render thread for source abort")
        return True

    def _on_queue_source_removed(self, clip_path: str) -> None:
        """Clip deleted / gone: fail matching QUEUED jobs; abort active encode."""
        if not clip_path or not hasattr(self, "render_queue"):
            return
        norm = os.path.normpath(clip_path)
        reason = "Source clip folder is missing."
        active = getattr(self, "_active_render_job", None)
        if (
            active is not None
            and os.path.normpath(getattr(active, "clip_path", "") or "") == norm
            and bool(getattr(self, "_is_rendering", False))
        ):
            self._abort_active_render_as_error(reason)

        touched = False
        for job in list(self.render_queue.jobs):
            if os.path.normpath(getattr(job, "clip_path", "") or "") != norm:
                continue
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.ERROR
                job.error_message = reason[:240]
                touched = True
        if touched:
            logging.warning(
                "Marked queued job(s) ERROR — source removed: %s", clip_path
            )
            self.refresh_render_queue_panel()
            self.update_playback_badge()
            if hasattr(self, "_persist_render_queue"):
                self._persist_render_queue()

    def _clear_queue_selection(self) -> None:
        """Clear the active queue card highlight when preview leaves the queue."""
        self._selected_queue_job_id = None
        if hasattr(self, "render_queue_panel"):
            self.render_queue_panel.clear_selection()

    def refresh_render_queue_panel(
        self, sync_splitter: bool = True, *, include_portable: bool = True
    ):
        """Rebuild the right-side queue list from ``render_queue``."""
        if not hasattr(self, "render_queue_panel"):
            return
        selected_id = getattr(self, "_selected_queue_job_id", None)
        preview_path = self._current_preview_clip_path()
        if selected_id and preview_path:
            job = self.render_queue.get(selected_id)
            if job and os.path.normpath(job.clip_path) != os.path.normpath(preview_path):
                selected_id = None
                self._selected_queue_job_id = None
        skip_rebuild = bool(getattr(self, "_skip_portable_queue_rebuild", False))
        if skip_rebuild:
            # Portable queue click: selection-only. Rebuilding desktop cards with
            # setParent(None) flashes orphan windows on Linux and can hang Qt.
            panel = self.render_queue_panel
            panel._selected_id = selected_id
            for card in getattr(panel, "_card_widgets", []) or []:
                try:
                    card.set_selected(getattr(card, "_job_id", None) == selected_id)
                except RuntimeError:
                    pass
        else:
            self.render_queue_panel.refresh(
                self.render_queue.jobs,
                selected_id,
            )
        self._update_start_button_label()
        self._sync_queue_scheme_chrome()
        if not getattr(self, "_is_rendering", False):
            self._sync_queue_player_and_dash_chrome()
        if include_portable:
            sidebar = getattr(self, "_portable_queue_sidebar", None)
            if sidebar is not None:
                try:
                    if skip_rebuild:
                        if hasattr(sidebar, "sync_selection"):
                            sidebar.sync_selection(selected_id)
                    elif hasattr(sidebar, "refresh"):
                        sidebar.refresh()
                except RuntimeError:
                    self._portable_queue_sidebar = None
        if sync_splitter:
            self._sync_queue_splitter_visibility()
        self.update_playback_badge()
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()

    def _sync_queue_splitter_visibility(self):
        if not hasattr(self, "right_h_splitter"):
            return
        # Theatre and fullscreen own the layout and keep the queue collapsed. Many
        # unrelated events (render progress, queue add/remove, refresh) funnel through
        # here, so without this guard the panel pops back open mid-immersive.
        if getattr(self, "is_theater", False) or getattr(self, "is_fullscreen", False):
            if hasattr(self, "_clamp_queue_panel_for_immersive"):
                self._clamp_queue_panel_for_immersive(True)
            total = sum(self.right_h_splitter.sizes()) or self.right_h_splitter.width()
            self.right_h_splitter.setSizes([max(int(total), 1), 0])
            return

        if hasattr(self, "_clamp_queue_panel_for_immersive"):
            self._clamp_queue_panel_for_immersive(False)

        # Always allow collapse — locking the pane open while jobs exist made the
        # nested minimumWidth shove Clips Manager on the outer splitter.
        self.right_h_splitter.setCollapsible(1, True)

        sizes = self.right_h_splitter.sizes()
        total = sum(sizes) if sum(sizes) > 0 else self.right_h_splitter.width()
        has_jobs = len(self.render_queue) > 0
        had_jobs = bool(getattr(self, "_queue_sync_had_jobs", False))
        self._queue_sync_had_jobs = has_jobs

        if has_jobs:
            if not bool(getattr(self, "_queue_user_collapsed", False)):
                self.render_queue_panel.show()
            if not had_jobs:
                # Fresh jobs — clear any prior user-collapse and open once.
                self._queue_user_collapsed = False
                if hasattr(self, "_persist_queue_panel_open"):
                    self._persist_queue_panel_open(True)
            # Auto-open only when jobs first appear, or when the pane is shut
            # without a user-collapse latch (theatre exit safety). Never reopen
            # on routine refreshes (clip select, progress ticks, Leave/Resume).
            # Scrap ≤48 counts as shut — closed panes often sit at PANE_FREED (1).
            should_open = (
                sizes[1] <= 48
                and not bool(getattr(self, "_queue_user_collapsed", False))
                and not bool(getattr(self, "_splitter_dragging", False))
                and (
                    not had_jobs
                    or bool(getattr(self, "_queue_splitter_restore_open", False))
                )
            )
            if should_open and hasattr(self, "_open_queue_in_right_splitter"):
                self._open_queue_in_right_splitter()
                if hasattr(self, "_persist_queue_panel_open"):
                    self._persist_queue_panel_open(True)
            self._queue_splitter_restore_open = False
        else:
            self.render_queue_panel.show()
            if bool(getattr(self, "_queue_user_collapsed", False)) or (
                had_jobs and sizes[1] > 0
            ):
                self._selected_queue_job_id = None
                if hasattr(self, "_close_queue_pane"):
                    self._close_queue_pane()
                else:
                    self.right_h_splitter.setSizes([max(int(total), 1), 0])
            elif sizes[1] <= 0 and hasattr(self, "_set_queue_pane_closed"):
                # Empty + already shut: keep maxWidth clamped, handle visible.
                self._set_queue_pane_closed(True)

        if hasattr(self, "sync_queue_minimum"):
            self.sync_queue_minimum()

    def start_render_thread(self):
        """Prepares parameters and starts rendering (single clip or full queue)."""
        if getattr(self, '_is_rendering', False):
            return

        if self._queue_drives_start_cta():
            self.start_queue_batch_render()
            return

        if hasattr(self, "_is_previewing_rendered_media") and self._is_previewing_rendered_media():
            steempeg_warning(
                self.ui,
                "Cannot render export",
                "Finished exports cannot be re-encoded. "
                "Select a Steam clip in Clips Manager, or Resume Render Queue "
                "and start pending jobs.",
            )
            return

        clip_path = self._resolve_export_clip_path()
        if not clip_path:
            steempeg_warning(self.ui, "Error", "Please select a clip from the list first!")
            return
        if self._is_rendered_export_path(clip_path) or not self._is_export_clip_path(clip_path):
            steempeg_warning(
                self.ui,
                "Cannot render export",
                "Only Steam clip folders can be rendered.",
            )
            return

        job = build_render_job_from_ui(self, clip_path)
        if job is None:
            steempeg_warning(self.ui, "Error", "session.mpd files not found inside this clip!")
            return
        self._start_render_job(job)

    def start_queue_batch_render(self) -> None:
        pending = self.render_queue.pending_count()
        if pending <= 0:
            steempeg_information(self.ui, "Render Queue", "No queued clips to render.")
            return

        self._queue_batch_active = True
        self._batch_total = pending
        self._batch_current = 0
        self._batch_started_at = _utc_now_iso()
        self._flush_current_trim_state()
        self._sync_ui_to_selected_job()
        set_settings_panel_locked(self, True)
        self.ui.btn_start.setEnabled(False)
        if hasattr(self.ui, 'btn_cancel'):
            self.ui.btn_cancel.setEnabled(True)
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(True)
        self.process_next_in_queue()

    def process_next_in_queue(self) -> None:
        if not getattr(self, '_queue_batch_active', False):
            return
        job = self.render_queue.next_queued()
        if job is None:
            self._finish_queue_batch()
            return
        self._batch_current += 1
        self._selected_queue_job_id = job.id
        # Only bind preview path when a clip is actually open. Stamping the path
        # on an idle player made Clips Manager treat the card as «already
        # previewing» and refuse to open anything until a queue card was clicked.
        # Rendering / Completed plaques use ``_active_render_job`` /
        # ``_completed_plaque_clip_path`` instead.
        if self._player_has_open_clip():
            self._preview_clip_path = job.clip_path
            self._apply_header_from_job(job)
        else:
            self._apply_player_idle_chrome()
            self._sync_dash_queue_status_chrome()
        self.refresh_render_queue_panel()
        self.update_playback_badge()
        job.refresh_output_path()
        self._start_render_job(job, batch_mode=True)

    def _apply_render_performance_prefs(self) -> None:
        """Bump process priority / pause preview for the active render (Settings)."""
        from steempeg.ui.settings_dialog import (
            KEY_PAUSE_PREVIEW_DURING_RENDER,
            KEY_RENDER_PROCESS_PRIORITY,
            PRIORITY_ABOVE,
            PRIORITY_HIGH,
            PRIORITY_NORMAL,
        )

        settings = {}
        if hasattr(self, "load_user_settings"):
            try:
                settings = self.load_user_settings() or {}
            except Exception:
                settings = {}

        if bool(settings.get(KEY_PAUSE_PREVIEW_DURING_RENDER, False)):
            player = getattr(self, "player", None)
            if player is not None:
                try:
                    was_paused = bool(player.pause)
                except Exception:
                    was_paused = True
                self._preview_paused_for_render = not was_paused
                if not was_paused:
                    try:
                        player.pause = True
                    except Exception:
                        self._preview_paused_for_render = False
            else:
                self._preview_paused_for_render = False
        else:
            self._preview_paused_for_render = False

        prio = str(settings.get(KEY_RENDER_PROCESS_PRIORITY, PRIORITY_NORMAL))
        self._render_priority_applied = prio
        if sys.platform == "win32" and prio in (PRIORITY_ABOVE, PRIORITY_HIGH):
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                handle = kernel32.GetCurrentProcess()
                # ABOVE_NORMAL_PRIORITY_CLASS=0x8000, HIGH_PRIORITY_CLASS=0x80
                cls = 0x80 if prio == PRIORITY_HIGH else 0x8000
                kernel32.SetPriorityClass(handle, cls)
            except Exception:
                logging.debug("Could not raise process priority", exc_info=True)
        elif sys.platform != "win32" and prio in (PRIORITY_ABOVE, PRIORITY_HIGH):
            try:
                os.nice(-5 if prio == PRIORITY_HIGH else -2)
            except Exception:
                logging.debug("Could not raise process nice", exc_info=True)

    def _restore_render_performance_prefs(self) -> None:
        if getattr(self, "_preview_paused_for_render", False):
            player = getattr(self, "player", None)
            if player is not None:
                try:
                    player.pause = False
                except Exception:
                    pass
            self._preview_paused_for_render = False

        if sys.platform == "win32" and getattr(self, "_render_priority_applied", "normal") != "normal":
            try:
                import ctypes

                # NORMAL_PRIORITY_CLASS
                ctypes.windll.kernel32.SetPriorityClass(
                    ctypes.windll.kernel32.GetCurrentProcess(), 0x20
                )
            except Exception:
                pass
            self._render_priority_applied = "normal"

    def _start_render_job(self, job, batch_mode: bool = False) -> None:
        from steempeg.ui.settings_prefs import resolve_app_export_folder

        clip_path = getattr(job, "clip_path", None) or ""
        if self._is_rendered_export_path(clip_path) or not self._is_export_clip_path(clip_path):
            steempeg_warning(
                self.ui,
                "Cannot render export",
                "Only Steam clip folders can be rendered — finished exports are not encode sources.",
            )
            if batch_mode:
                # Drop the bad job and continue the batch if anything remains.
                job_id = getattr(job, "id", None)
                if job_id and hasattr(self, "render_queue"):
                    self.render_queue.remove(job_id)
                    self._persist_render_queue_async()
                self.process_next_in_queue()
            return

        unavailable = self._queue_source_unavailable_reason(clip_path)
        if unavailable:
            self._fail_queue_job(job, unavailable, batch_mode=batch_mode)
            return

        # Catch deleted / unwritable destinations before ffmpeg opens the output.
        safe_dir = resolve_app_export_folder(
            self,
            getattr(job.settings, "save_dir", None) or getattr(self, "custom_destination", ""),
            notify=True,
        )
        if getattr(job.settings, "save_dir", None) != safe_dir:
            job.settings.save_dir = safe_dir
        job.refresh_output_path()
        from shutil import which

        self._apply_render_performance_prefs()

        ffmpeg_exe = resolve_ffmpeg_exe()
        if not os.path.isfile(ffmpeg_exe):
            ffmpeg_exe = which(ffmpeg_exe) or which("ffmpeg") or ""
        if not ffmpeg_exe:
            steempeg_critical(self.ui, "Error", "ffmpeg not found!")
            if batch_mode:
                self._stop_queue_batch()
            return

        params = resolve_render_params(job, ffmpeg_exe)
        if params is None:
            self._fail_queue_job(
                job,
                "No playable session.mpd found for this clip.",
                batch_mode=batch_mode,
            )
            return

        if not batch_mode:
            set_settings_panel_locked(self, True)
            self.ui.btn_start.setEnabled(False)
            if hasattr(self.ui, 'btn_cancel'):
                self.ui.btn_cancel.setEnabled(True)
            if hasattr(self.ui, 'btn_pause'):
                self.ui.btn_pause.setEnabled(True)

        if batch_mode:
            label = f"Rendering ({self._batch_current}/{self._batch_total})"
        else:
            label = "Initializing..."
        # Bind strip context before the Ready cluster paints so name + badge agree.
        self._is_rendering = True
        self._encode_paused = False
        self._active_render_job = job
        self._pending_render_error_override = None
        # New encode supersedes any prior Completed / Error plaque for this session.
        self._completed_plaque_clip_path = None
        self._error_plaque_clip_path = None
        # Mark this job only — find_by_clip_path would hit an earlier duplicate of the same clip.
        live = self.render_queue.get(getattr(job, "id", "")) or job
        live.status = JobStatus.RENDERING
        self._apply_status_strip_summary(live)
        self.update_status_indicator(label, "rendering")
        logging.info("--- RENDER STARTED ---")

        self.refresh_render_queue_panel()
        self.update_playback_badge()
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()

        logging.info(f"Source: {job.clip_path}")
        logging.info(f"Saving in: {params.output_file}")

        try:
            self.render_thread = RenderThread(
                params.all_mpds,
                params.quality_text,
                params.output_file,
                params.ffmpeg_exe,
                params.save_dir,
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
            )
            self.render_thread.progress_signal.connect(self._on_render_progress)
            self.render_thread.finished_signal.connect(self.on_render_finished)
            self.render_thread.start()
        except Exception as e:
            logging.error(f"Thread Start Error: {e}")
            self._is_rendering = False
            self._active_render_job = None
            if not getattr(self, '_queue_batch_active', False):
                set_settings_panel_locked(self, False)
            self.update_status_indicator("Error!", "error")
            self.ui.btn_start.setEnabled(True)
            if hasattr(self.ui, 'btn_cancel'):
                self.ui.btn_cancel.setEnabled(False)
            if hasattr(self.ui, 'btn_pause'):
                self.ui.btn_pause.setEnabled(False)
            if batch_mode:
                self._stop_queue_batch()
            else:
                steempeg_critical(self.ui, "Thread Error", f"Could not start render:\n{e}")

    def _notify_render_outcome(
        self,
        *,
        success: bool,
        title: str,
        body: str,
    ) -> None:
        """OS toast + system sound when Steempeg is in the background.

        Honours Settings → «Notify when render finishes». Errors also beep
        when the window is focused (dialog is already on screen).
        """
        from steempeg.infra.os_notify import (
            NotifyKind,
            app_is_in_background,
            notify_render_event,
        )
        from steempeg.infra.system_sound import SystemSound, play_system_sound
        from steempeg.ui.settings_dialog import KEY_NOTIFY_ON_RENDER_COMPLETE

        enabled = True
        if hasattr(self, "load_user_settings"):
            try:
                enabled = bool(
                    self.load_user_settings().get(KEY_NOTIFY_ON_RENDER_COMPLETE, True)
                )
            except Exception:
                enabled = True
        if not enabled:
            return

        parent = getattr(self, "ui", None)
        kind = NotifyKind.SUCCESS if success else NotifyKind.ERROR
        if app_is_in_background(parent):
            notify_render_event(
                title, body, kind=kind, parent=parent, force=True, play_sound=True
            )
        elif not success:
            play_system_sound(SystemSound.ERROR)

    def _release_idle_queue_preview_stamp(self) -> None:
        """Drop queue-only preview binding when the player never opened a clip.

        Batch encode may leave ``_selected_queue_job_id`` / a stale
        ``_preview_clip_path`` without media on screen — that blocked library
        opens via the same-clip click guard.
        """
        if self._player_has_open_clip():
            return
        self._preview_clip_path = None
        if hasattr(self, "_opening_clip_path"):
            self._opening_clip_path = None
        self._clear_queue_selection()

    def _finish_queue_batch(self) -> None:
        self._queue_batch_active = False
        self._restore_render_performance_prefs()
        set_settings_panel_locked(self, False)
        if hasattr(self.ui, 'btn_start'):
            self.ui.btn_start.setEnabled(True)
        if hasattr(self.ui, 'btn_cancel'):
            self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self._set_desktop_pause_label("Pause")
        self._update_start_button_label()
        self._release_idle_queue_preview_stamp()
        self.refresh_render_queue_panel()
        self._queue_library_preview_diversion = False
        self._sync_queue_player_and_dash_chrome()
        self.update_playback_badge()
        self._persist_render_queue()
        self._archive_batch_to_history(cancelled=False)
        self.update_status_indicator("Ready", "ready")
        if hasattr(self, "update_final_setup"):
            try:
                self.update_final_setup()
            except Exception:
                pass
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()

        jobs = list(self.render_queue.jobs)
        try:
            from steempeg.render.queue import JobStatus

            done = sum(1 for j in jobs if j.status == JobStatus.COMPLETED)
            failed = sum(1 for j in jobs if j.status == JobStatus.ERROR)
        except Exception:
            done, failed = 0, 0
        if failed == 0 and done > 0:
            self._notify_render_outcome(
                success=True,
                title="Videos are ready",
                body=f"{done} exported",
            )
        elif failed:
            self._notify_render_outcome(
                success=False,
                title="Render failed",
                body=f"{done} ok · {failed} failed",
            )

        self._show_batch_complete_dialog(jobs=jobs)

    def _stop_queue_batch(self, cancelled: bool = False) -> None:
        self._archive_batch_to_history(cancelled=cancelled)
        self._queue_batch_active = False
        self._restore_render_performance_prefs()
        set_settings_panel_locked(self, False)
        if hasattr(self.ui, 'btn_start'):
            self.ui.btn_start.setEnabled(True)
        if hasattr(self.ui, 'btn_cancel'):
            self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self._set_desktop_pause_label("Pause")
        self._update_start_button_label()
        self._release_idle_queue_preview_stamp()
        self.refresh_render_queue_panel()
        self._queue_library_preview_diversion = False
        self._sync_queue_player_and_dash_chrome()
        self.update_playback_badge()
        if cancelled:
            self.update_status_indicator("Cancelled", "cancelled")
            self._show_canceled_information(
                "Cancelled", "Queue render was cancelled."
            )
        self.update_status_indicator("Ready", "ready")
        if hasattr(self, "update_final_setup"):
            try:
                self.update_final_setup()
            except Exception:
                pass
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()

    def _show_canceled_information(self, title: str, message: str) -> None:
        """Show cancel dialog with Canceled plaque until OK."""
        self._canceled_plaque_active = True
        try:
            self.update_playback_badge()
            steempeg_information(self.ui, title, message)
        finally:
            self._canceled_plaque_active = False
            self.update_playback_badge()

    def _show_steempeg_render_error_dialog(
        self,
        error_msg: str,
        *,
        batch_continue: bool = False,
        auto_continue_seconds: int = 10,
    ) -> bool:
        """Frameless FFmpeg error dialog. Returns True to continue queue, False to stop."""
        from steempeg.render.ffmpeg_error_hints import classify_ffmpeg_error
        from steempeg.ui import ui_theme as ut

        dialog = QDialog(self.ui)
        dialog.setObjectName("SteempegRenderErrorDialog")
        dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setFixedSize(780, 460)

        shell = QWidget(dialog)
        shell.setObjectName("RenderErrorShell")
        shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell.setStyleSheet(ut.render_error_dialog_stylesheet())

        root = QVBoxLayout(dialog)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(shell)

        main_layout = QHBoxLayout(shell)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        pic_label = QLabel()
        pixmap = QPixmap(get_resource_path("saderror.png"))
        if not pixmap.isNull():
            pic_label.setPixmap(pixmap.scaledToWidth(240, Qt.TransformationMode.SmoothTransformation))
        else:
            pic_label.setText("Sad pic\nnot found =(")
            pic_label.setStyleSheet("color: gray; font-size: 12px;")
        pic_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        main_layout.addWidget(pic_label, 0, Qt.AlignmentFlag.AlignTop)

        content_layout = QVBoxLayout()
        content_layout.setSpacing(12)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)

        hint = classify_ffmpeg_error(error_msg)
        title_lbl = QLabel("Render Failed")
        title_lbl.setObjectName("ErrorTitle")
        hint_lbl = QLabel(hint.message)
        hint_lbl.setObjectName("ErrorHint")
        hint_lbl.setWordWrap(True)
        title_layout.addWidget(title_lbl)
        title_layout.addWidget(hint_lbl)

        desc_lbl = None
        if batch_continue:
            desc_lbl = QLabel(
                "FFmpeg crashed while processing this clip. "
                f"Auto-continuing in {auto_continue_seconds} s..."
            )
            desc_lbl.setObjectName("ErrorDesc")
            desc_lbl.setWordWrap(True)
            title_layout.addWidget(desc_lbl)
        content_layout.addLayout(title_layout)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        short_error = (error_msg or "Unknown error")[-2000:]
        text_edit.setText(short_error)
        from steempeg.ui.widgets.vertical_scrollbar import (
            ensure_steempg_vertical_scrollbar,
            error_dialog_scrollbar_chrome,
        )

        ensure_steempg_vertical_scrollbar(
            text_edit, chrome=error_dialog_scrollbar_chrome()
        )

        log_toggle = QPushButton("Hide FFmpeg log")
        log_toggle.setObjectName("ErrorLogToggle")
        log_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        log_toggle.setFlat(True)
        log_visible = [True]

        # Stretch host keeps the button row pinned to the same baseline whether
        # the log is shown or hidden (only the log pane empties).
        log_host = QWidget()
        log_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_host_layout = QVBoxLayout(log_host)
        log_host_layout.setContentsMargins(0, 0, 0, 0)
        log_host_layout.setSpacing(0)
        log_host_layout.addWidget(text_edit)

        def toggle_log() -> None:
            log_visible[0] = not log_visible[0]
            text_edit.setVisible(log_visible[0])
            log_toggle.setText(
                "Hide FFmpeg log" if log_visible[0] else "Show FFmpeg log"
            )

        log_toggle.clicked.connect(toggle_log)
        content_layout.addWidget(log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        content_layout.addWidget(log_host, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_log = QPushButton("📄 Open Log File")
        btn_log.setObjectName("LogBtn")
        btn_log.setCursor(Qt.CursorShape.PointingHandCursor)

        result = {"continue": True}
        timer = QTimer(dialog)
        remaining = [auto_continue_seconds]

        def open_log_file():
            if hasattr(self, "current_log_file") and os.path.exists(self.current_log_file):
                open_text_file(self.current_log_file)

        if batch_continue:
            btn_log.clicked.connect(open_log_file)
        else:
            btn_log.clicked.connect(lambda: (open_log_file(), dialog.accept()))
        btn_layout.addWidget(btn_log)

        if batch_continue:
            btn_stop = QPushButton("Stop Queue")
            btn_stop.setObjectName("StopBtn")
            btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)

            btn_continue = QPushButton("Continue")
            btn_continue.setCursor(Qt.CursorShape.PointingHandCursor)

            def tick():
                if desc_lbl is None:
                    return
                remaining[0] -= 1
                if remaining[0] > 0:
                    desc_lbl.setText(
                        "FFmpeg crashed while processing this clip. "
                        f"Auto-continuing in {remaining[0]} s..."
                    )
                else:
                    desc_lbl.setText("Continuing queue...")
                    timer.stop()
                    dialog.accept()

            timer.timeout.connect(tick)
            timer.start(1000)

            def stop_queue():
                result["continue"] = False
                timer.stop()
                dialog.reject()

            btn_continue.clicked.connect(dialog.accept)
            btn_stop.clicked.connect(stop_queue)
            btn_layout.addWidget(btn_stop)
            btn_layout.addWidget(btn_continue)
        else:
            btn_ok = QPushButton("Close")
            btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_ok.clicked.connect(dialog.accept)
            btn_layout.addWidget(btn_ok)

        content_layout.addLayout(btn_layout)
        main_layout.addLayout(content_layout, 1)

        # Soft rounding via stylesheet only — QRegion masks look jagged.
        dialog.setStyleSheet(
            (dialog.styleSheet() or "")
            + "QDialog { border-radius: 10px; }"
        )

        def apply_ui_theme_chrome() -> None:
            """Live-retint if Settings switches theme while this dialog is open."""
            shell.setStyleSheet(ut.render_error_dialog_stylesheet())
            ensure_steempg_vertical_scrollbar(
                text_edit, chrome=error_dialog_scrollbar_chrome()
            )

        dialog.apply_ui_theme_chrome = apply_ui_theme_chrome  # type: ignore[attr-defined]

        if batch_continue:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            timer.stop()
            return accepted and result["continue"]

        dialog.exec()
        return True

    def _prompt_batch_continue_after_error(self, error_msg: str) -> bool:
        return self._show_steempeg_render_error_dialog(
            error_msg,
            batch_continue=True,
            auto_continue_seconds=10,
        )

    def cancel_render(self):
        """ Cancel Button Handler """
        logging.warning("User cancelled rendering (Cancel)")
        if getattr(self, "render_thread", None) and self.render_thread.isRunning():
            self.update_status_indicator("Cancelling... Please wait", "cancelling")
            if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
            if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(False)
            self.render_thread.cancel()
            if getattr(self, '_queue_batch_active', False):
                self._batch_cancel_requested = True

    def toggle_pause(self):
        """ Pause button handler """
        logging.info("User Paused/Resumed rendering")
        if getattr(self, "render_thread", None) and self.render_thread.isRunning():
            is_paused = self.render_thread.toggle_pause()
            self._encode_paused = bool(is_paused)

            # Change the button text depending on the status
            if is_paused:
                if hasattr(self.ui, 'btn_pause'): self._set_desktop_pause_label("Resume")
                self.update_status_indicator("Paused...", "paused")
            else:
                if hasattr(self.ui, 'btn_pause'): self._set_desktop_pause_label("Pause")
                self.update_status_indicator("Processing...", "rendering")
            self.update_playback_badge()

    def on_render_finished(self, success, error_msg, output_file):
        """ Fires when the background rendering thread exits. """
        # Source-gone abort kills FFmpeg via cancel(); remap to ERROR so the job
        # is not quietly put back to QUEUED like a user Cancel.
        override = getattr(self, "_pending_render_error_override", None)
        if override:
            self._pending_render_error_override = None
            if not success:
                success = False
                error_msg = override

        active_job = getattr(self, "_active_render_job", None)
        if active_job:
            self._sync_queue_job_render_status(
                active_job, success, error_msg, output_file or ""
            )

        if success and active_job is not None:
            # Remember for normal-mode / deferred Completed plaque (job may not
            # live in render_queue after a single Start Render).
            self._completed_plaque_clip_path = getattr(active_job, "clip_path", None)
            self._error_plaque_clip_path = None
        elif not success:
            # Cancel / error: drop a stale Completed from a prior export.
            self._completed_plaque_clip_path = None
            if "cancelled by user" not in (error_msg or "").lower():
                self._error_plaque_clip_path = getattr(active_job, "clip_path", None)

        self._is_rendering = False
        self._encode_paused = False
        self._active_render_job = None
        self.refresh_render_queue_panel()
        self.update_playback_badge()
        self._persist_render_queue()

        if getattr(self, "_queue_batch_active", False):
            if success:
                logging.info("=== BATCH RENDER SUCCESS === %s", output_file)
                if active_job and output_file:
                    self._save_render_companion_meta(active_job, output_file)
                    if hasattr(self, "register_new_rendered_output"):
                        self.register_new_rendered_output(output_file)
                self.process_next_in_queue()
                return
            if "cancelled by user" in (error_msg or "").lower():
                self._error_plaque_clip_path = None
                self._stop_queue_batch(cancelled=True)
                return
            short = (error_msg or "FFmpeg error").strip().splitlines()[0][:80]
            game = getattr(active_job, "game_name", None) or "Clip"
            self._notify_render_outcome(
                success=False,
                title="Render failed",
                body=f"{game}: {short}",
            )
            if self._prompt_batch_continue_after_error(error_msg or ""):
                # Continue → drop Error plaque; failed job stays ERROR in the list.
                self._error_plaque_clip_path = None
                self.update_playback_badge()
                self.process_next_in_queue()
            else:
                # Stop queue → keep Error plaque on the failed clip.
                self._stop_queue_batch()
            return

        self._restore_render_performance_prefs()

        set_settings_panel_locked(self, False)

        if hasattr(self.ui, 'btn_start'): self.ui.btn_start.setEnabled(True)
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self._set_desktop_pause_label("Pause")

        if success:
            logging.info("=== RENDER SUCCESS ===")
            if output_file and active_job:
                self._save_render_companion_meta(active_job, output_file)
                if hasattr(self, "register_new_rendered_output"):
                    self.register_new_rendered_output(output_file)

            self.update_status_indicator("Success!", "success")

            if active_job and output_file:
                game = getattr(active_job, "game_name", None) or "Clip"
                self._notify_render_outcome(
                    success=True,
                    title="Video is ready",
                    body=game,
                )
                if not getattr(self, "_queue_batch_active", False):
                    self._archive_single_render_to_history(active_job, output_file)
                self._show_render_complete_dialog(active_job, output_file)

            self.update_status_indicator("Ready", "ready")

        elif "cancelled by user" in error_msg.lower():
            logging.warning("=== RENDER CANCELED ===")
            self._error_plaque_clip_path = None
            self.update_status_indicator("Cancelled", "cancelled")
            self._show_canceled_information("Cancelled", "Render was cancelled.")
            self.update_status_indicator("Ready", "ready")

        else:
            logging.error(f"=== RENDER ERROR === \n{error_msg}")
            self.update_status_indicator("Error!", "error")
            short = (error_msg or "FFmpeg error").strip().splitlines()[0][:80]
            game = getattr(active_job, "game_name", None) or "Clip"
            self._notify_render_outcome(
                success=False,
                title="Render failed",
                body=f"{game}: {short}",
            )
            self.update_playback_badge()
            self._show_steempeg_render_error_dialog(error_msg or "")
            self.update_status_indicator("Ready", "ready")

        self.update_final_setup()
        self._sync_start_render_enabled()
        if hasattr(self, "_sync_portable_render_strip"):
            self._sync_portable_render_strip()
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()

    def inject_custom_input(self, combo_widget, placeholder):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)  # Small gap between input and icon

        combo_widget.parentWidget().layout().replaceWidget(combo_widget, container)

        # Tell the ComboBox to aggressively expand and fill all available horizontal space!
        combo_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        line_edit = QLineEdit()
        line_edit.setPlaceholderText(placeholder)
        # Make the input box exactly 70px wide (no more, no less) so it doesn't stretch
        line_edit.setFixedWidth(70)
        line_edit.hide()  # Hidden by default

        warn_icon = QLabel()
        warn_icon.setFixedSize(16, 16)
        _warn_pix = warning_pixmap(16)
        if not _warn_pix.isNull():
            warn_icon.setPixmap(_warn_pix)
        warn_icon.hide()  # Hidden by default

        # ---> APPLY THE INSTANT TOOLTIP MAGIC HERE <---
        if hasattr(self, 'instant_tooltip'):
            warn_icon.installEventFilter(self.instant_tooltip)

        # Add widgets to layout.
        layout.addWidget(combo_widget)
        layout.addWidget(line_edit)
        layout.addWidget(warn_icon)

        # Show/hide logic
        combo_widget.currentTextChanged.connect(lambda t: (
            line_edit.setVisible("Custom" in t),
            warn_icon.setVisible(False) if "Custom" not in t else None
        ))
        return line_edit, warn_icon