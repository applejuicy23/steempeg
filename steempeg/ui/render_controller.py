"""Rendering controls and the export pipeline, mixed into the main application.

These methods drive the render tab: probing clip media, building quality and
bitrate options, validating custom input, running the export thread and reporting
results. They run on the application instance and reach its widgets and state
through self.
"""
import json
import logging
import os
import re
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from steempeg.core import capabilities
from steempeg.core.dash import discovery, health, mpd, repair
from steempeg.infra.paths import get_resource_path, get_save_directory
from steempeg.render import bitrate
from steempeg.render.output_formats import (
    AUDIO_FORMATS,
    CONTAINERS,
    KNOWN_OUTPUT_EXTENSIONS,
    OUTPUT_PRESETS,
    VIDEO_CODEC_ITEMS,
    audio_needs_bitrate,
    is_valid_output_combo,
    output_extension,
)
from steempeg.render.queue import (
    JobStatus,
    PREVIEW_BADGE_COLOR,
    PREVIEW_BADGE_TEXT,
    STATUS_COLORS,
    STATUS_HEADER_LABELS,
    load_queue_from_file,
    save_queue_to_file,
)
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
    resolve_render_params,
    snapshot_settings_from_ui,
)
from steempeg.ui.render_thread import RenderThread


def _fmt_orig_mbps(value: float) -> str:
    """Round source bitrate for Original UI (e.g. 21.9 → 22)."""
    return str(int(round(value)))


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


_RENDER_ERROR_DIALOG_STYLE = """
    QDialog {
        background-color: #202020;
        border: 1px solid #444444;
        border-radius: 8px;
    }
    QLabel#ErrorTitle {
        color: #ff4444;
        font-size: 18px;
        font-weight: bold;
    }
    QLabel#ErrorDesc {
        color: #cccccc;
        font-size: 13px;
    }
    QTextEdit {
        background-color: #141414;
        color: #ff8888;
        border: 1px solid #333333;
        border-radius: 6px;
        padding: 8px;
        font-family: Consolas, monospace;
        font-size: 11px;
    }
    QScrollBar:vertical { border: none; background: #141414; width: 12px; margin: 2px; border-radius: 4px; }
    QScrollBar::handle:vertical { background: #444444; min-height: 20px; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background: #666666; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
    QPushButton {
        background-color: #333333;
        color: white;
        border: 1px solid #555555;
        border-radius: 16px;
        padding: 6px 20px;
        font-weight: bold;
        font-size: 12px;
        min-height: 32px;
        outline: none;
    }
    QPushButton:hover {
        background-color: #444444;
        border: 1px solid #777777;
    }
    QPushButton:pressed {
        background-color: #222222;
    }
    QPushButton#LogBtn {
        background-color: #4a2525;
        border: 1px solid #7a3535;
    }
    QPushButton#LogBtn:hover {
        background-color: #6a2e2e;
        border: 1px solid #9a4545;
    }
    QPushButton#StopBtn {
        background-color: #4a2525;
        border: 1px solid #7a3535;
    }
    QPushButton#StopBtn:hover {
        background-color: #6a2e2e;
        border: 1px solid #9a4545;
    }
"""

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
            folder = os.path.dirname(mpd_path)
            init_a = os.path.join(folder, "init-stream1.m4s")
            if os.path.isfile(init_a) and os.path.getsize(init_a) > 100:
                try:
                    for entry in os.listdir(folder):
                        if entry.startswith("chunk-stream1-") and entry.endswith(".m4s"):
                            return True
                except OSError:
                    pass
            try:
                with open(mpd_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if 'contentType="audio"' in content or 'mimeType="audio' in content:
                        return True
            except OSError:
                pass
        return False

    def get_all_mpd_paths(self, clip_path):
        paths = discovery.find_mpd_paths(clip_path)
        if paths:
            return paths
        # Force-play salvage: a clip with no scanner-visible manifest but a built
        # session_salvage.mpd is playable/renderable through that salvage manifest.
        salvaged = getattr(self, "_salvaged_clips", {}).get(os.path.normpath(clip_path))
        return list(salvaged) if salvaged else []

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
        folder = QFileDialog.getExistingDirectory(self.ui, "Select Destination Folder")
        if folder:
            self.custom_destination = folder
        else:
            # If we change our minds and click Cancel, we return to our cool folder
            default_export_dir = os.path.join(get_save_directory(), "rendered_videos").replace('\\', '/')
            if not os.path.exists(default_export_dir):
                os.makedirs(default_export_dir, exist_ok=True)
            self.custom_destination = default_export_dir

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
        self.update_final_setup()

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
        self.update_final_setup()

    def _sync_original_audio_controls(self):
        """Freeze audio encode controls when Original is doing stream copy."""
        if not getattr(self, "_current_clip_has_audio", True):
            # No audio track on the source — keep all audio controls disabled and let
            # refresh_output_format_availability own the final clamped state.
            for name in (
                "label_audio_format", "combo_audio_format", "label_audio_bitrate",
                "combo_audio_bitrate", "input_custom_abitrate", "check_audio_only",
                "check_mute_audio",
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

        # default to the first hardware encoder if there is one, otherwise CPU
        self.ui.combo_encoder.setCurrentIndex(1 if self.ui.combo_encoder.count() > 1 else 0)

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

        if hasattr(ui, "combo_container"):
            for i in range(ui.combo_container.count()):
                c = ui.combo_container.itemText(i)
                ok = is_valid_output_combo(
                    c, codec, audio_fmt, audio_only=audio_only, mute_audio=mute
                )
                set_combo_item_enabled(ui.combo_container, i, ok)

        if hasattr(ui, "combo_codec"):
            for i in range(ui.combo_codec.count()):
                ctext = ui.combo_codec.itemText(i)
                ok = is_valid_output_combo(
                    container, ctext, audio_fmt, audio_only=audio_only, mute_audio=mute
                )
                set_combo_item_enabled(ui.combo_codec, i, ok)

        if hasattr(ui, "combo_audio_format"):
            for i in range(ui.combo_audio_format.count()):
                afmt = ui.combo_audio_format.itemText(i)
                ok = is_valid_output_combo(
                    container, codec, afmt, audio_only=audio_only, mute_audio=mute
                )
                if afmt == "Copy" and not is_original_copy:
                    ok = False
                set_combo_item_enabled(ui.combo_audio_format, i, ok)

        needs_bitrate = audio_needs_bitrate(audio_fmt) and not is_original_copy
        bitrate_enabled = needs_bitrate and (audio_only or not mute)
        for name in ("label_audio_bitrate", "combo_audio_bitrate"):
            widget = getattr(ui, name, None)
            if widget is not None:
                widget.setEnabled(bitrate_enabled)
        if hasattr(ui, "input_custom_abitrate"):
            ui.input_custom_abitrate.setEnabled(bitrate_enabled)

        # Source has no audio track: clamp every audio choice off so the user can't
        # pick a format/bitrate for something that doesn't exist.
        if no_audio:
            for name in (
                "combo_audio_format", "combo_audio_bitrate", "label_audio_format",
                "label_audio_bitrate", "input_custom_abitrate", "check_audio_only",
                "check_mute_audio",
            ):
                widget = getattr(ui, name, None)
                if widget is not None:
                    widget.setEnabled(False)
            if hasattr(ui, "label_abitrate"):
                ui.label_abitrate.setText("Audio Bitrate: None (no audio track)")

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
            self.refresh_output_format_availability()
            self.update_final_setup()
            return

        ui = self.ui
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
                idx = ui.combo_container.findText(preset["container"])
                if idx >= 0:
                    ui.combo_container.setCurrentIndex(idx)
            if hasattr(ui, "combo_codec"):
                idx = ui.combo_codec.findText(preset["codec"])
                if idx >= 0:
                    ui.combo_codec.setCurrentIndex(idx)
            if hasattr(ui, "combo_audio_format"):
                idx = ui.combo_audio_format.findText(preset["audio"])
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
            msg = f"({self._batch_current}/{self._batch_total}) {msg}"
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

    def update_status_indicator(self, text, state="ready"):
        """Update the macOS-style status dot, label, progress bar and percent label."""
        if not hasattr(self.ui, 'label_status'):
            return

        colors = {
            "ready": "#4CAF50",
            "rendering": "#a871ff",
            "paused": "#ffcc00",
            "error": "#ff4444",
            "success": "#4CAF50",
            "cancelling": "#ff4444",
            "cancelled": "#ff4444",
        }
        color = colors.get(state, "#a871ff")
        preserve_progress = state in ("cancelling", "cancelled", "paused")

        display_text = str(text)
        percent = None

        pct_match = re.search(r'\((\d+(?:\.\d+)?)%\)', display_text)
        if pct_match:
            percent = max(0.0, min(100.0, float(pct_match.group(1))))
            display_text = re.sub(r'\s*\(\d+(?:\.\d+)?%\)', '', display_text).strip()

        if state == "rendering" and not display_text:
            display_text = "Rendering"

        if hasattr(self, 'status_dot'):
            dot_px = self.status_dot.width() or 12
            radius = max(3, dot_px // 2)
            self.status_dot.setStyleSheet(
                f"background-color: {color}; border-radius: {radius}px;"
            )

        self.ui.label_status.setText(
            f"<span style='font-weight: bold; font-size: 14px; color: {color}; "
            f"font-family: Segoe UI, Arial, sans-serif;'>{display_text}</span>"
        )

        if state == "success":
            percent = 100.0
        elif state == "ready" or state == "error":
            percent = 0.0

        if hasattr(self.ui, 'progress_render'):
            bar = self.ui.progress_render
            if hasattr(bar, 'set_progress'):
                if percent is not None:
                    bar.set_progress(percent)
                elif state == "success":
                    bar.set_progress(100.0)
                elif not preserve_progress and state in ("ready", "error"):
                    bar.set_progress(0.0)
                bar.set_state(state)
            else:
                if percent is not None:
                    bar.setValue(int(percent * 10))
                elif state == "success":
                    bar.setValue(1000)
                elif not preserve_progress and state in ("ready", "error"):
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
            if percent is not None:
                self.label_pct.setText(self._format_pct_label(percent))
            elif state == "success":
                self.label_pct.setText("100%")
            elif not preserve_progress and state in ("ready", "error"):
                self.label_pct.setText("0%")

    def open_rendered_folder(self, file_path):
        """ Opens Windows Explorer and automatically highlights the rendered file! """
        try:
            if os.path.exists(file_path):
                # Magic Windows command to open folder AND select the specific file
                subprocess.run(['explorer', '/select,', os.path.normpath(file_path)])
            else:
                # Fallback: Just open the directory if the file is somehow missing
                folder_dir = os.path.dirname(file_path)
                if folder_dir and os.path.exists(folder_dir):
                    os.startfile(folder_dir)
        except Exception as e:
            print(f"Failed to open folder: {e}")

    def _queue_is_active(self) -> bool:
        """True when the render queue has jobs (queue drives batch render)."""
        return bool(getattr(self, "render_queue", None)) and len(self.render_queue) > 0

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

    def _apply_header_from_table_row(self, selected_row: int) -> None:
        if selected_row < 0 or not hasattr(self.ui, "table_clips"):
            return
        game_item = self.ui.table_clips.item(selected_row, 0)
        if not game_item:
            return
        game_name = game_item.text()
        game_icon = game_item.icon()
        clip_date = self.ui.table_clips.item(selected_row, 2)
        clip_time = self.ui.table_clips.item(selected_row, 3)
        date_text = clip_date.text() if clip_date else ""
        time_text = clip_time.text() if clip_time else ""
        if hasattr(self, "custom_text_label"):
            header_html = (
                f"<b>{game_name}</b> <span style='color: #888;'>&nbsp;&nbsp;•&nbsp;&nbsp; "
                f"{date_text} &nbsp;&nbsp;•&nbsp;&nbsp; {time_text}</span>"
            )
            self.custom_text_label.setText(header_html)
        if hasattr(self, "custom_icon_label"):
            self.custom_icon_label.setPixmap(game_icon.pixmap(24, 24))

    def _handle_clips_manager_selection_with_queue(self, clip_path: str, selected_row: int) -> None:
        """Preview from Clips Manager while queue is active; sync queue highlight if clip is queued."""
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
        self._apply_header_from_table_row(selected_row)

        queue_job = self.render_queue.find_by_clip_path(clip_path)
        if queue_job:
            # Clip is already queued -> behave exactly like clicking its queue card.
            self.activate_queue_job(queue_job.id)
            return

        trim_restore = self._trim_state_for_clip(clip_path)
        self._selected_queue_job_id = None
        self._populate_quality_options_for_clip(clip_path)

        if hasattr(self, "btn_close_clip"):
            self.btn_close_clip.show()
        self.generate_and_play_preview(clip_path, trim_restore=trim_restore)
        self.update_final_setup()
        self.refresh_render_queue_panel()
        self.update_playback_badge()
        self._update_start_button_label()
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()
        if hasattr(self, "_persist_library_ui_state"):
            self._persist_library_ui_state()

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
        except OSError as exc:
            logging.warning("Could not save render history: %s", exc)

    def show_render_queue_history(self) -> None:
        from steempeg.ui.render_queue_history import RenderQueueHistoryDialog

        batches = load_history(self._queue_history_path())
        dlg = RenderQueueHistoryDialog(batches, parent=self.ui)
        dlg.open_output_requested.connect(self.open_rendered_folder)
        if dlg.exec() == 2:
            clear_history(self._queue_history_path())

    def _persist_render_queue(self) -> None:
        try:
            save_queue_to_file(self._queue_persist_path(), self.render_queue)
        except OSError as exc:
            logging.warning("Could not save render queue: %s", exc)

    def _load_persisted_render_queue(self) -> None:
        if not hasattr(self, "render_queue"):
            return
        loaded = load_queue_from_file(self._queue_persist_path())
        if loaded:
            self.render_queue = loaded
            if self.render_queue.jobs:
                self._selected_queue_job_id = self.render_queue.jobs[0].id

    def _update_start_button_label(self) -> None:
        if not hasattr(self.ui, "btn_start"):
            return
        pending = self.render_queue.pending_count() if hasattr(self, "render_queue") else 0
        if pending > 0:
            self.ui.btn_start.setText(f"🚩 Render Queue ({pending})")
        else:
            self.ui.btn_start.setText("🚩 START RENDER")

    def _capture_trim_state(self) -> dict:
        if not hasattr(self, "custom_timeline"):
            return {"is_trim_mode": False, "trim_start_ms": 0, "trim_end_ms": 0}
        return {
            "is_trim_mode": bool(self.custom_timeline.is_trim_mode),
            "trim_start_ms": int(self.custom_timeline.trim_start_ms),
            "trim_end_ms": int(self.custom_timeline.trim_end_ms),
        }

    def _trim_memory_path(self) -> str:
        return os.path.join(self.cache_dir, "clip_trim_state.json")

    def _ensure_trim_memory_loaded(self) -> None:
        """Lazily load the per-clip trim memory from disk (once)."""
        if getattr(self, "_clip_trim_memory", None) is not None:
            return
        self._clip_trim_memory = {}
        path = self._trim_memory_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, TypeError):
            return
        if not isinstance(data, dict):
            return
        for key, trim in data.items():
            if not isinstance(trim, dict):
                continue
            self._clip_trim_memory[os.path.normpath(key)] = {
                "is_trim_mode": bool(trim.get("is_trim_mode", False)),
                "trim_start_ms": int(trim.get("trim_start_ms", 0)),
                "trim_end_ms": int(trim.get("trim_end_ms", 0)),
            }

    def _save_trim_memory(self) -> None:
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._trim_memory_path(), "w", encoding="utf-8") as f:
                json.dump(self._clip_trim_memory, f, indent=2)
        except OSError as exc:
            logging.warning("Could not save clip trim memory: %s", exc)

    def _write_trim_state(self, clip_path: str, trim: dict) -> None:
        clip_path = os.path.normpath(clip_path)
        job = self.render_queue.find_by_clip_path(clip_path)
        if job and job.status in (JobStatus.QUEUED, JobStatus.ERROR):
            job.settings.is_trim_mode = bool(trim.get("is_trim_mode", False))
            job.settings.trim_start_ms = int(trim.get("trim_start_ms", 0))
            job.settings.trim_end_ms = int(trim.get("trim_end_ms", 0))
            job.refresh_output_path()
            if hasattr(self, "render_queue_panel"):
                self.refresh_render_queue_panel(sync_splitter=False)
        self._ensure_trim_memory_loaded()
        has_trim = bool(trim.get("is_trim_mode", False)) and (
            int(trim.get("trim_end_ms", 0)) > int(trim.get("trim_start_ms", 0))
        )
        if has_trim:
            self._clip_trim_memory[clip_path] = trim
        else:
            # No meaningful trim -> drop the entry so we don't litter the file.
            self._clip_trim_memory.pop(clip_path, None)
        self._save_trim_memory()

    def _trim_state_for_clip(self, clip_path: str) -> dict:
        clip_path = os.path.normpath(clip_path)
        job = self.render_queue.find_by_clip_path(clip_path)
        if job:
            s = job.settings
            return {
                "is_trim_mode": bool(s.is_trim_mode),
                "trim_start_ms": int(s.trim_start_ms),
                "trim_end_ms": int(s.trim_end_ms),
            }
        self._ensure_trim_memory_loaded()
        return self._clip_trim_memory.get(
            clip_path,
            {"is_trim_mode": False, "trim_start_ms": 0, "trim_end_ms": 0},
        )

    def _flush_current_trim_state(self) -> None:
        clip_path = getattr(self, "_preview_clip_path", None)
        if not clip_path:
            return
        self._write_trim_state(clip_path, self._capture_trim_state())

    def _persist_trim_for_current_clip(self) -> None:
        clip_path = getattr(self, "_preview_clip_path", None)
        if not clip_path:
            if hasattr(self.ui, "table_clips") and self.ui.table_clips.currentRow() >= 0:
                item = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0)
                if item:
                    clip_path = item.data(Qt.UserRole)
        if not clip_path:
            return
        self._write_trim_state(clip_path, self._capture_trim_state())
        if self._queue_is_active():
            self._persist_render_queue()

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
        job = self.render_queue.find_by_clip_path(preview)
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

        source_dirs = [os.path.dirname(m) for m in all_mpds]
        unique_source_dirs = list(dict.fromkeys(source_dirs))
        self.current_source_raw_paths = "\n".join(unique_source_dirs)

        if hasattr(self.ui.source_label, "set_sources"):
            self.ui.source_label.set_sources(unique_source_dirs)
        else:
            self.ui.source_label.setText("Source:\n" + "\n".join(unique_source_dirs))

        orig_audio_bitrate = self.get_audio_bitrate_from_mpd(all_mpds[0]) if all_mpds else 192
        self.current_orig_audio_bitrate = orig_audio_bitrate

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

        unique_resolutions = set()
        max_height = 0
        self.current_orig_bitrate = 0

        for mpd_path in all_mpds:
            try:
                with open(mpd_path, "r", encoding="utf-8") as file:
                    content = file.read()
                    clip_full_path = os.path.dirname(mpd_path)
                    size_str, duration_str = self.get_clip_size_and_duration(clip_full_path, content)
                    if hasattr(self.ui, "label_size"):
                        self.ui.label_size.setText(f"Size: {size_str}")
                    if hasattr(self.ui, "label_duration"):
                        self.ui.label_duration.setText(f"Time: {duration_str}")

                    fps_match = re.search(r'\bframeRate="(\d+)(?:/\d+)?"', content)
                    if fps_match:
                        self.current_orig_fps = int(fps_match.group(1))
                    else:
                        self.current_orig_fps = self.get_fps_from_mpd(mpd_path)

                    if hasattr(self.ui, "label_fps"):
                        self.ui.label_fps.setText(f"FPS: {self.current_orig_fps}")

                    height_match = re.search(r'\bheight="(\d+)"', content)
                    width_match = re.search(r'\bwidth="(\d+)"', content)
                    peak_mbps = mpd.get_video_bitrate_mbps(mpd_path)
                    if peak_mbps > self.current_orig_bitrate:
                        self.current_orig_bitrate = peak_mbps

                    if height_match and width_match:
                        h = int(height_match.group(1))
                        w = int(width_match.group(1))
                        unique_resolutions.add(f"{w}x{h}")
                        if h > max_height:
                            max_height = h
            except Exception:
                pass

        if unique_resolutions:
            res_text = ", ".join(sorted(list(unique_resolutions)))
            audio_kbps = getattr(self, "current_orig_audio_bitrate", 192)
            self.ui.orig_res_label.setText(f"Original resolution: {res_text}")
            if hasattr(self.ui, "label_vbitrate"):
                if hasattr(self, "current_orig_bitrate") and self.current_orig_bitrate > 0:
                    rounded_bitrate = int(round(self.current_orig_bitrate))
                    self.ui.label_vbitrate.setText(f"Video Bitrate: {rounded_bitrate} Mbps")
                else:
                    self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            if hasattr(self.ui, "label_abitrate"):
                self.ui.label_abitrate.setText(f"Audio Bitrate: {audio_kbps} kbps")
        else:
            self.ui.orig_res_label.setText("Original resolution: Unknown")
            if hasattr(self.ui, "label_vbitrate"):
                if getattr(self, "current_orig_bitrate", 0) > 0:
                    self.ui.label_vbitrate.setText(
                        f"Video Bitrate: {int(round(self.current_orig_bitrate))} Mbps"
                    )
                else:
                    self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            if hasattr(self.ui, "label_abitrate"):
                self.ui.label_abitrate.setText("Audio Bitrate: Unknown")
            max_height = 1080

        self.current_orig_height = max_height

        if hasattr(self.ui, "combo_quality"):
            self.ui.combo_quality.clear()
            if max_height > 0:
                self.ui.combo_quality.addItem(f"Original (Lossless, {max_height}p)")
            else:
                self.ui.combo_quality.addItem("Original (Lossless)")
            for preset_name, preset_height in self.all_qualities:
                self.ui.combo_quality.addItem(preset_name)
                idx = self.ui.combo_quality.count() - 1
                if max_height > 0 and preset_height > max_height:
                    set_combo_item_enabled(
                        self.ui.combo_quality,
                        idx,
                        False,
                        tooltip=(
                            f"Clip is {max_height}p — cannot upscale to {preset_height}p. "
                            "Pick a lower preset or Original."
                        ),
                    )
            self.ui.combo_quality.setCurrentIndex(0)
            self.ui.combo_quality.insertSeparator(self.ui.combo_quality.count())
            self.ui.combo_quality.addItem("🎯 Target File Size...")
            self.update_bitrate_options()

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

        if preserve_ui_selection and current_quality and hasattr(self.ui, "combo_quality"):
            index = find_enabled_combo_text(self.ui.combo_quality, current_quality)
            if index >= 0:
                self.ui.combo_quality.setCurrentIndex(index)
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

    def update_quality_options(self):
        """ Reads the clip's XML data and prepares the UI for the render settings """
        if getattr(self, "_library_panel_mode", "clips") == "rendered":
            if hasattr(self, "update_rendered_selection"):
                self.update_rendered_selection()
            return
        if getattr(self, '_grid_select_in_progress', False):
            return
        if not hasattr(self.ui, 'table_clips'): return
        selected_row = self.ui.table_clips.currentRow()
        if selected_row < 0:
            self.ui.source_label.setText("Source:")
            self.ui.orig_res_label.setText("Original Resolution:")
            # Set default empty states for our new widgets
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate:")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate:")
            self.update_playback_badge()
            return
        if hasattr(self, 'grid_clips'):
            selected_rows = {
                idx.row() for idx in self.ui.table_clips.selectionModel().selectedRows()
            }
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
        if hasattr(self, "_clear_rendered_selection_visual"):
            self._clear_rendered_selection_visual()
        self._saved_rendered_selection_path = ""
        self._preview_clip_path = clip_path
        self._rendered_media_path = None
        trim_restore = self._trim_state_for_clip(clip_path)
        self._populate_quality_options_for_clip(clip_path)

        game_item = self.ui.table_clips.item(selected_row, 0)
        game_name = game_item.text()
        game_icon = game_item.icon()
        clip_date = self.ui.table_clips.item(selected_row, 2).text()
        clip_time = self.ui.table_clips.item(selected_row, 3).text()

        if hasattr(self, "custom_text_label"):
            header_html = (
                f"<b>{game_name}</b> <span style='color: #888;'>&nbsp;&nbsp;•&nbsp;&nbsp; "
                f"{clip_date} &nbsp;&nbsp;•&nbsp;&nbsp; {clip_time}</span>"
            )
            self.custom_text_label.setText(header_html)
        if hasattr(self, "custom_icon_label"):
            self.custom_icon_label.setPixmap(game_icon.pixmap(24, 24))

        self._selected_queue_job_id = None
        self.update_playback_badge()
        self.generate_and_play_preview(clip_path, trim_restore=trim_restore)
        self._update_start_button_label()
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()
        if hasattr(self, "_persist_library_ui_state"):
            self._persist_library_ui_state()

    def fit_settings_tab_to_page(self, idx=None):
        """ Keep the scroll content as tall as the CURRENT settings page only.

        settings_tabs is a QTabWidget (QStackedLayout under the hood), which reports
        the height of its TALLEST page. Inside the scroll area that means short pages
        (Source Info, Export) show a phantom scrollbar over empty space. Collapsing the
        non-current pages to an Ignored size policy makes each page contribute 0 height,
        so the scroll range matches what's actually visible.
        """
        tabs = getattr(self.ui, 'settings_tabs', None)
        if tabs is None:
            return
        if idx is None:
            idx = tabs.currentIndex()
        for i in range(tabs.count()):
            page = tabs.widget(i)
            if page is None:
                continue
            if i == idx:
                page.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            else:
                page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            page.updateGeometry()
        tabs.updateGeometry()

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
                rounded = int(round(peak))
                self.ui.label_vbitrate.setText(f"Video Bitrate: {rounded} Mbps")
        return peak

    def update_bitrate_options(self):
        """ Refreshes lists, applies FPS math visually, and freezes settings if Original is selected. """
        if not hasattr(self.ui, 'combo_bitrate') or not hasattr(self.ui, 'combo_quality'):
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
                val = _fmt_orig_mbps(source_cap_mbps)
                self.ui.combo_bitrate.addItem(f"{val} Mbps (Original)")
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
            self.ui.combo_bitrate.blockSignals(False)
            self.update_final_setup()
            return

        self.ui.combo_bitrate.setEnabled(True) 
        if hasattr(self.ui, 'combo_fps'): self.ui.combo_fps.setEnabled(True)
        if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(True)
        if hasattr(self.ui, 'combo_encoder'):
            self.ui.combo_encoder.setEnabled(True)
            self.ui.combo_encoder.setToolTip("")
        
        match = re.search(r'^(\d+)p', quality_text)
        if not match: 
            self.ui.combo_bitrate.blockSignals(False)
            return
            
        res_key = f"{match.group(1)}p"
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
            f"~{int(round(source_cap_mbps))} Mbps"
            if source_cap_mbps > 0
            else "unknown"
        )
        for quality_level in ["Ultra", "High", "Medium", "Low"]:
            if res_key in self.steam_bitrate_presets.get(quality_level, {}):
                preset_bitrate = self.steam_bitrate_presets[quality_level][res_key]

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

    def update_final_setup(self):
        """Dynamically updates the Detailed Summary, Size, and Save Path."""
        clip_path = self._active_preview_clip_path()
        if not clip_path:
            if hasattr(self.ui, 'label_short_summary'):
                if hasattr(self, 'reset_bottom_summary'): self.reset_bottom_summary()
            if hasattr(self.ui, 'label_detailed_summary'):
                self.ui.label_detailed_summary.setText("Waiting for clip selection...")
            if hasattr(self, 'update_status_indicator'):
                self.update_status_indicator("Ready", "ready")
            if hasattr(self, 'btn_copy_loc'): self.btn_copy_loc.hide()
            return

        #1: Read everything from the UI
        quality = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else ""
        fps = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else ""
        bitrate_text = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else ""
        codec_raw = self.ui.combo_codec.currentText() if hasattr(self.ui, 'combo_codec') else ""
        codec = codec_raw.split()[0] if codec_raw else "Unknown"
        encoder = self.ui.combo_encoder.currentText() if hasattr(self.ui, 'combo_encoder') else ""

        audio_only = self.ui.check_audio_only.isChecked() if hasattr(self.ui, 'check_audio_only') else False
        mute_audio = self.ui.check_mute_audio.isChecked() if hasattr(self.ui, 'check_mute_audio') else False
        audio_format = self.ui.combo_audio_format.currentText() if hasattr(self.ui, 'combo_audio_format') else "AAC"
        audio_bitrate = self.ui.combo_audio_bitrate.currentText() if hasattr(self.ui, 'combo_audio_bitrate') else "192 kbps"
        container = self.ui.combo_container.currentText() if hasattr(self.ui, 'combo_container') else "MP4"

        # 2. Calculate the file extension
        ext = output_extension(container, audio_only, audio_format)

        # 3. OVERWRITE PROTECTION 
        save_dir = self.custom_destination if self.custom_destination else get_save_directory()
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

        if hasattr(self, 'btn_copy_loc') and full_path:
            self.btn_copy_loc.show()

        # 4. Collecting texts & Smart Math
        duration = self.get_effective_duration() # Use trimmed duration for math!
        
        # Format the beautiful "Clip time: ✂️ 00:10 - 01:50" string
        if hasattr(self, 'custom_timeline') and self.custom_timeline.is_trim_mode:
            start_s = self.custom_timeline.trim_start_ms / 1000.0
            end_s = self.custom_timeline.trim_end_ms / 1000.0
            
            s_h = int(start_s // 3600)
            s_m = int((start_s % 3600) // 60)
            s_s = int(start_s % 60)
            
            e_h = int(end_s // 3600)
            e_m = int((end_s % 3600) // 60)
            e_s = int(end_s % 60)
            
            if s_h > 0 or e_h > 0:
                duration_str = f"✂️ {s_h:02d}:{s_m:02d}:{s_s:02d} - {e_h:02d}:{e_m:02d}:{e_s:02d}"
            else:
                duration_str = f"✂️ {s_m:02d}:{s_s:02d} - {e_m:02d}:{e_s:02d}"
        else:
            duration_str = getattr(self, 'current_clip_duration_str', "Unknown")
        
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
            video_bitrate_display = f"⚙️ {val * fps_multiplier:.1f} Mbps"
        elif "Original" in bitrate_text:
            # Original = stream copy: show the source Mbps only — "Original" is already
            # in the quality label; the bottom summary must not repeat "Original copy".
            orig_mbps = orig_v_bitrate
            if orig_mbps <= 0:
                m = re.search(r'([\d.]+)\s*Mbps', bitrate_text)
                if m:
                    orig_mbps = float(m.group(1))
            video_bitrate_display = (
                f"{_fmt_orig_mbps(orig_mbps)} Mbps" if orig_mbps > 0 else "—"
            )
        else:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match: 
                video_bitrate_display = f"{float(match.group(1)):.1f} Mbps"

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
                f"Sound: {audio_format}, {audio_bitrate_clean}\n"
                f"Other settings: Normal Render\n"
                f"Est. File Size: {size_str}"
            )
            
        if hasattr(self.ui, 'label_detailed_summary'):
            self.ui.label_detailed_summary.setText(detailed_text)

        combo_valid = is_valid_output_combo(
            container, codec_raw, audio_format, audio_only=audio_only, mute_audio=mute_audio
        )
        if hasattr(self.ui, 'btn_start') and not getattr(self, '_is_rendering', False):
            self.ui.btn_start.setEnabled(combo_valid)

        # 6. Short Summary ABOVE Ready 
        q_word = quality.split()[0] if quality.split() else "Unknown"
        
        game_name = "Steam Clip"
        target_icon = getattr(self, 'current_game_icon', '')
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

        if audio_only:
            text_part = f"<span style='font-size: 14px;'><b>{game_name} &nbsp;•&nbsp; AUDIO ONLY: {audio_format} {audio_bitrate_clean}</b></span>"
        elif mute_audio:
            text_part = f"<span style='font-size: 14px;'><b>{game_name} &nbsp;•&nbsp; {q_word}, {fps_display} &nbsp;•&nbsp; {video_bitrate_display} &nbsp;•&nbsp; {codec} (Muted)</b></span>"
        else:
            text_part = f"<span style='font-size: 14px;'><b>{game_name} &nbsp;•&nbsp; {q_word}, {fps_display} &nbsp;•&nbsp; {video_bitrate_display} &nbsp;•&nbsp; {codec}</b></span>"
            
        # GIVE ORDER TO OUR NEW CSS WIDGETS
        if hasattr(self, 'bottom_text_label'):
            self.bottom_text_label.setText(text_part)
            icon_css = target_icon.replace('\\', '/')
            self.bottom_icon_label.setStyleSheet(f"image: url('{icon_css}'); background: transparent; border: none;")
            
            # We are updating the TOP panel of the player!
            if hasattr(self, 'custom_text_label') and hasattr(self, 'custom_icon_label'):
                self.custom_icon_label.setStyleSheet(f"image: url('{icon_css}'); background: transparent; border: none;")
                

            # CONNECTING THE MAIN BOSS: Updating the CENTRAL plug!
            if hasattr(self, 'place_logo') and hasattr(self, 'place_text'):
                # Pixmap only (no stylesheet image) so the game icon scales with the
                # aspect ratio kept and never overlaps the Steempeg logo underneath.
                self.place_logo.setStyleSheet("")
                game_pix = QPixmap(place_icon)
                if not game_pix.isNull():
                    self.place_logo.setPixmap(
                        game_pix.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )
                self.place_logo.setAlignment(Qt.AlignCenter)
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
        is_target_mode = "Target File Size" in text
        
        if hasattr(self.ui, 'size_slider'):
            self.ui.size_slider.setVisible(is_target_mode)
            
        if hasattr(self, 'size_container'):
            self.size_container.setVisible(is_target_mode)
            
        if is_target_mode:
            self.setup_dynamic_slider()
        self._sync_original_audio_controls()
        self.refresh_output_format_availability()
        if is_target_mode:
            self.update_final_setup()

    def on_custom_size_changed(self, text):
        """ Live updates when typing a custom MB value with idiot-proof protection """
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
                
            self.calculate_strict_target(target_mb, is_custom=True)
        except: 
            self.warn_size.hide()

    def refresh_slider_if_needed(self):
        """ Updates the monkeymeter if the user has switched FPS """
        if hasattr(self.ui, 'size_slider') and self.ui.size_slider.isVisible():
            self.on_slider_moved(self.ui.size_slider.value())

        
    
    
    def setup_dynamic_slider(self):
        """ Generates strict slider steps and adds Lossless & Custom modes """
        duration = self.get_effective_duration() 
        if duration <= 0: return
            
        # Dynamically calculate the maximum MB for the current trimmed duration
        orig_mb = (getattr(self, 'current_orig_bitrate', 10) * duration) / 8 
        if orig_mb < 1: orig_mb = 1
        
        anchors = [10, 25, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, 4000, 5000]
        self.dynamic_stops = [size for size in anchors if size < orig_mb]
        
        self.dynamic_stops.append(int(orig_mb)) # Lossless
        self.dynamic_stops.append(-1) # Custom
        
        self.ui.size_slider.blockSignals(True)
        self.ui.size_slider.setMinimum(0)
        self.ui.size_slider.setMaximum(len(self.dynamic_stops) - 1)
        # Always snap to the new Lossless value when the trim changes
        self.ui.size_slider.setValue(len(self.dynamic_stops) - 2) 
        self.ui.size_slider.blockSignals(False)
        
        self.on_slider_moved(self.ui.size_slider.value())

    def calculate_strict_target(self, target_mb, is_lossless=False, is_custom=False):
        """Read the controls, run the bitrate math, show the result."""
        duration = self.get_effective_duration()

        # --- read inputs from the UI ---
        orig_video_mbps = getattr(self, 'current_orig_bitrate', 10)

        audio_text = self.ui.combo_audio_bitrate.currentText() if hasattr(self.ui, 'combo_audio_bitrate') else "192 kbps"
        if hasattr(self.ui, 'check_mute_audio') and self.ui.check_mute_audio.isChecked():
            audio_kbps = 0
        elif "Custom" in audio_text:
            audio_kbps = self._audio_kbps_from_ui()
        else:
            match = re.search(r'(\d+)', audio_text)
            audio_kbps = int(match.group(1)) if match else 192

        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        fps = self._resolved_fps_from_ui() if "Custom" in fps_text else None
        if fps is None:
            try:
                fps = int(re.search(r'(\d+)', fps_text).group(1))
            except (AttributeError, ValueError):
                fps = getattr(self, 'current_orig_fps', 60)

        # --- run the pure math ---
        native_height = getattr(self, 'current_orig_height', 0)
        plan = bitrate.plan_bitrate(duration, orig_video_mbps, target_mb, audio_kbps, fps,
                                    is_lossless=is_lossless, is_custom=is_custom,
                                    native_height=native_height)
        if plan is None:
            return

        # --- show the result ---
        self.custom_target_height = plan.height
        self.custom_target_bitrate = plan.video_kbps
        custom_tag = "⚙️ Custom " if is_custom else ""
        self.ui.label_target_size.setText(
            f"Target: <b>{custom_tag}{plan.target_mb} MB</b> | Safe Bitrate: {plan.video_kbps} kbps<br>"
            f"Quality: <span style='color:{plan.color}'><b>{plan.label}</b></span>"
        )
        self.update_final_setup()

    def on_slider_moved(self, index):
        """ Handles slider logic and reveals custom input if needed """
        target_mb = self.dynamic_stops[index]
        
        if target_mb == -1:
            self.input_custom_size.show()
            if self.input_custom_size.text():
                self.on_custom_size_changed(self.input_custom_size.text())
            else:
                self.ui.label_target_size.setText("Target: <b>--- MB</b> (Type specific size)<br>Quality: <span style='color:#aaaaaa'><b>Waiting for input...</b></span>")
        else:
            self.input_custom_size.hide()
            if hasattr(self, 'warn_size'): self.warn_size.hide() 
            self.calculate_strict_target(target_mb, is_lossless=(index == len(self.dynamic_stops) - 2))

    def validate_custom_fps(self, text):
        """ Validates FPS input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_fps.hide()
            self.update_final_setup()
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
        except:
            self.warn_fps.hide()
            
        self.update_final_setup() # Live UI update

    def validate_custom_vbitrate(self, text):
        """ Validates video bitrate input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_vbitrate.hide()
            self.update_final_setup()
            return
            
        try:
            val = float(text.replace(',', '.'))
            orig_v_bitrate = getattr(self, 'current_orig_bitrate', 10.0)
            
            if val > orig_v_bitrate:
                self.warn_vbitrate.setToolTip(f"The maximum bitrate of the original video is {orig_v_bitrate:.1f} Mbps. Higher values will be capped!")
                self.warn_vbitrate.show()
            elif val < 0.1:
                self.warn_vbitrate.setToolTip("Video bitrate cannot be less than 0.1 Mbps.")
                self.warn_vbitrate.show()
            else:
                self.warn_vbitrate.hide()
        except:
            self.warn_vbitrate.hide()
            
        self.update_final_setup() # Live UI update

    def validate_custom_abitrate(self, text):
        """ Validates audio bitrate input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_abitrate.hide()
            self.update_final_setup()
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
        except:
            self.warn_abitrate.hide()
            
        self.update_final_setup() # Live UI update

    def add_clip_to_render_queue(self, clip_path: str):
        """Snapshot current settings into a new queued job (stage 2+ UI will call this)."""
        if hasattr(self, "get_clip_health_report"):
            report = self.get_clip_health_report(clip_path)
            if report.level == health.ClipHealth.DEAD:
                logging.warning("Skipped dead clip for queue: %s", clip_path)
                return None
        job = build_render_job_from_ui(self, clip_path)
        if job is None:
            return None
        self.render_queue.add(job)
        logging.info(
            "Queued render job #%s: %s -> %s",
            job.queue_index,
            job.game_name,
            job.output_file,
        )
        return job

    def add_clips_to_render_queue(self, clip_paths):
        """Add one or more clips using the current render settings snapshot."""
        added = 0
        skipped = 0
        failed = []

        self._flush_current_trim_state()
        for clip_path in clip_paths:
            if self.render_queue.contains_clip(clip_path):
                skipped += 1
                continue
            job = self.add_clip_to_render_queue(clip_path)
            if job is None:
                failed.append(os.path.basename(clip_path))
            else:
                added += 1

        if not added and not skipped and not failed:
            return

        if added:
            lines = [f"Added {added} clip(s) to the render queue."]
            if skipped:
                lines.append(f"{skipped} already in queue.")
            if failed:
                lines.append(f"Could not queue: {', '.join(failed)}")
            QMessageBox.information(self.ui, "Render Queue", "\n".join(lines))
        elif skipped and not failed:
            QMessageBox.information(
                self.ui,
                "Render Queue",
                "All selected clips are already in the queue.",
            )
        elif failed:
            QMessageBox.warning(
                self.ui,
                "Render Queue",
                "Could not add the selected clip(s).\n"
                + "\n".join(failed),
            )

        logging.info(
            "Queue update: added=%s skipped=%s failed=%s total=%s",
            added,
            skipped,
            len(failed),
            len(self.render_queue),
        )
        self.refresh_render_queue_panel()
        self._update_start_button_label()
        self._persist_render_queue()

    def activate_queue_job(self, job_id: str) -> None:
        """Load preview, trim, and settings from a queue job snapshot."""
        job = self.render_queue.get(job_id)
        if not job:
            return
        self._flush_current_trim_state()
        if self._sync_active_queue_job_from_ui():
            self._persist_render_queue()
        self._selected_queue_job_id = job_id
        self._preview_clip_path = job.clip_path
        trim_restore = self._trim_state_for_clip(job.clip_path)
        self._loading_queue_job = True
        try:
            self._apply_header_from_job(job)
            self._populate_quality_options_for_clip(
                job.clip_path, preserve_ui_selection=False,
            )
            apply_job_settings_to_ui(self, job.settings)
            if hasattr(self, "btn_close_clip"):
                self.btn_close_clip.show()
            self.generate_and_play_preview(job.clip_path, trim_restore=trim_restore)
            self.update_final_setup()
        finally:
            self._loading_queue_job = False
        self._highlight_clip_in_library(job.clip_path)
        self.refresh_render_queue_panel()
        self.update_playback_badge()
        self._update_start_button_label()
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()

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
            if anchor_item is not None:
                self._grid_anchor_item = anchor_item
                self._grid_anchor_index = self._list_widget_item_index(self.grid_clips, anchor_item)
                self.grid_clips.scrollToItem(anchor_item)
            if hasattr(self, "_sync_grid_card_visuals"):
                self._sync_grid_card_visuals()

    def remove_queue_job(self, job_id: str) -> None:
        job = self.render_queue.get(job_id)
        if not job:
            return
        if job.status == JobStatus.RENDERING:
            return
        was_selected = getattr(self, "_selected_queue_job_id", None) == job_id
        self.render_queue.remove(job_id)
        self._persist_render_queue()
        if not self.render_queue:
            self._on_queue_became_empty()
            return
        if was_selected:
            nxt = self.render_queue.jobs[0]
            self.activate_queue_job(nxt.id)
        else:
            self.refresh_render_queue_panel()
            self._update_start_button_label()

    def clear_render_queue(self) -> None:
        if getattr(self, "_queue_batch_active", False):
            QMessageBox.warning(self.ui, "Render Queue", "Stop the batch render before clearing the queue.")
            return
        if not len(self.render_queue):
            return
        reply = QMessageBox.question(
            self.ui,
            "Clear Queue",
            f"Remove all {len(self.render_queue)} clip(s) from the render queue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.render_queue.clear()
        self._on_queue_became_empty()

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
        self.refresh_render_queue_panel()
        self._update_start_button_label()
        self._persist_render_queue()
        self.update_playback_badge()

    def _current_header_clip_path(self):
        return self._current_preview_clip_path()

    def _queue_job_for_clip(self, clip_path):
        if not clip_path:
            return None
        return self.render_queue.find_by_clip_path(clip_path)

    def _playback_badge_for_context(self):
        clip_path = self._current_header_clip_path()
        if not clip_path:
            return None, None

        if hasattr(self, "get_clip_health_report"):
            if self.get_clip_health_report(clip_path).level == health.ClipHealth.DEAD:
                return None, None

        if getattr(self, "_is_rendering", False):
            active = getattr(self, "_active_render_job", None)
            if active and os.path.normpath(active.clip_path) == os.path.normpath(clip_path):
                return STATUS_HEADER_LABELS[JobStatus.RENDERING], STATUS_COLORS[JobStatus.RENDERING]

        job = self._queue_job_for_clip(clip_path)

        if job:
            if job.status == JobStatus.COMPLETED:
                return STATUS_HEADER_LABELS[JobStatus.COMPLETED], STATUS_COLORS[JobStatus.COMPLETED]
            if job.status == JobStatus.ERROR:
                return STATUS_HEADER_LABELS[JobStatus.ERROR], STATUS_COLORS[JobStatus.ERROR]
            if job.status == JobStatus.RENDERING:
                return STATUS_HEADER_LABELS[JobStatus.RENDERING], STATUS_COLORS[JobStatus.RENDERING]
            return f"In queue ({job.queue_index})", STATUS_COLORS[JobStatus.QUEUED]

        return PREVIEW_BADGE_TEXT, PREVIEW_BADGE_COLOR

    def update_playback_badge(self):
        if not hasattr(self, "label_playback_badge"):
            return

        text, color = self._playback_badge_for_context()
        if not text:
            self.label_playback_badge.hide()
            if hasattr(self, "update_clip_health_button"):
                self.update_clip_health_button()
            return

        self.label_playback_badge.setText(text)
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        self.label_playback_badge.setStyleSheet(
            f"color: {color};"
            f"background-color: rgba({r}, {g}, {b}, 0.18);"
            f"border: 2px solid {color};"
            "border-radius: 8px; padding: 4px 10px;"
            "font-weight: bold; font-size: 13px;"
            "font-family: 'Segoe UI';"
        )
        self.label_playback_badge.show()
        if hasattr(self, "update_clip_health_button"):
            self.update_clip_health_button()

    def _apply_header_from_job(self, job):
        if not job or not hasattr(self, "custom_text_label"):
            return
        date_line = (job.clip_date or "").replace("\n", " • ")
        meta = date_line
        if job.clip_time and job.clip_time not in date_line:
            meta = f"{date_line} • {job.clip_time}" if date_line else job.clip_time
        header_html = (
            f"<b>{job.game_name.strip()}</b>"
            f" <span style='color: #888;'>&nbsp;&nbsp;•&nbsp;&nbsp; {meta}</span>"
        )
        self.custom_text_label.setText(header_html)
        if hasattr(self, "custom_icon_label"):
            icon_path = job.game_icon_path
            unknown = get_resource_path("unknown_icon.png")
            path = icon_path if icon_path and os.path.exists(icon_path) else unknown
            if path and os.path.exists(path):
                self.custom_icon_label.setPixmap(QPixmap(path).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _sync_queue_job_render_status(self, clip_path, success, error_msg):
        job = self.render_queue.find_by_clip_path(clip_path)
        if not job:
            return
        if success:
            job.status = JobStatus.COMPLETED
        elif "cancelled by user" in (error_msg or "").lower():
            job.status = JobStatus.QUEUED
            job.error_message = ""
        else:
            job.status = JobStatus.ERROR
            job.error_message = (error_msg or "")[:240]

    def refresh_render_queue_panel(self, sync_splitter: bool = True):
        """Rebuild the right-side queue list from ``render_queue``."""
        if not hasattr(self, "render_queue_panel"):
            return
        selected_id = getattr(self, "_selected_queue_job_id", None)
        preview_path = self._current_preview_clip_path()
        if selected_id and preview_path:
            job = self.render_queue.get(selected_id)
            if job and os.path.normpath(job.clip_path) != os.path.normpath(preview_path):
                selected_id = None
        self.render_queue_panel.refresh(
            self.render_queue.jobs,
            selected_id,
        )
        if sync_splitter:
            self._sync_queue_splitter_visibility()
        self.update_playback_badge()

    def _sync_queue_splitter_visibility(self):
        if not hasattr(self, "right_h_splitter"):
            return
        # Theatre and fullscreen own the layout and keep the queue collapsed. Many
        # unrelated events (render progress, queue add/remove, refresh) funnel through
        # here, so without this guard the panel pops back open mid-immersive.
        if getattr(self, "is_theater", False) or getattr(self, "is_fullscreen", False):
            if hasattr(self, "render_queue_panel"):
                self.render_queue_panel.hide()
            total = sum(self.right_h_splitter.sizes()) or self.right_h_splitter.width()
            self.right_h_splitter.setSizes([max(int(total), 1), 0])
            return
        sizes = self.right_h_splitter.sizes()
        total = sum(sizes) if sum(sizes) > 0 else self.right_h_splitter.width()
        if len(self.render_queue) > 0:
            self.render_queue_panel.show()
            if sizes[1] <= 0:
                from steempeg.ui.layout_defaults import (
                    DEFAULT_QUEUE_PANEL_WIDTH,
                    MIN_QUEUE_PANEL_WIDTH,
                )

                queue_w = self.get_layout_setting("queue_panel_width", DEFAULT_QUEUE_PANEL_WIDTH)
                queue_w = max(MIN_QUEUE_PANEL_WIDTH, min(int(queue_w), total))
                self.right_h_splitter.setSizes([total - queue_w, queue_w])
        else:
            self.render_queue_panel.show()
            if sizes[1] > 0:
                self._selected_queue_job_id = None
                self.right_h_splitter.setSizes([total, 0])

    def on_queue_job_selected(self, job_id: str):
        """Load preview and settings for the selected queue card."""
        logging.info("Queue selection: %s", job_id)
        self.activate_queue_job(job_id)

    def start_render_thread(self):
        """Prepares parameters and starts rendering (single clip or full queue)."""
        if getattr(self, '_is_rendering', False):
            return

        if self._queue_is_active() and self.render_queue.pending_count() > 0:
            self.start_queue_batch_render()
            return

        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            QMessageBox.warning(self.ui, "Error", "Please select a clip from the list first!")
            return

        clip_name = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).data(Qt.UserRole)
        job = build_render_job_from_ui(self, clip_name)
        if job is None:
            QMessageBox.warning(self.ui, "Error", "session.mpd files not found inside this clip!")
            return
        self._start_render_job(job)

    def start_queue_batch_render(self) -> None:
        pending = self.render_queue.pending_count()
        if pending <= 0:
            QMessageBox.information(self.ui, "Render Queue", "No queued clips to render.")
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
        self.refresh_render_queue_panel()
        self.update_playback_badge()
        job.refresh_output_path()
        self._start_render_job(job, batch_mode=True)

    def _start_render_job(self, job, batch_mode: bool = False) -> None:
        job.refresh_output_path()
        ffmpeg_exe = os.path.join(_bin_dir, "ffmpeg.exe")
        if not os.path.exists(ffmpeg_exe):
            QMessageBox.critical(self.ui, "Error", "ffmpeg.exe not found!")
            if batch_mode:
                self._stop_queue_batch()
            return

        params = resolve_render_params(job, ffmpeg_exe)
        if params is None:
            QMessageBox.warning(self.ui, "Error", "session.mpd files not found inside this clip!")
            if batch_mode:
                self._stop_queue_batch()
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
        self.update_status_indicator(label, "rendering")
        logging.info("--- RENDER STARTED ---")

        self._is_rendering = True
        self._active_render_job = job
        queue_job = self.render_queue.find_by_clip_path(job.clip_path)
        if queue_job:
            queue_job.status = JobStatus.RENDERING
            self.refresh_render_queue_panel()
        self.update_playback_badge()

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
                QMessageBox.critical(self.ui, "Thread Error", f"Could not start render:\n{e}")

    def _finish_queue_batch(self) -> None:
        completed = sum(1 for j in self.render_queue if j.status == JobStatus.COMPLETED)
        errors = sum(1 for j in self.render_queue if j.status == JobStatus.ERROR)
        self._queue_batch_active = False
        set_settings_panel_locked(self, False)
        if hasattr(self.ui, 'btn_start'):
            self.ui.btn_start.setEnabled(True)
        if hasattr(self.ui, 'btn_cancel'):
            self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.setText("Pause")
        self._update_start_button_label()
        self.refresh_render_queue_panel()
        self.update_playback_badge()
        self._persist_render_queue()
        self._archive_batch_to_history(cancelled=False)
        self.update_status_indicator("Ready", "ready")
        QMessageBox.information(
            self.ui,
            "Render Queue",
            f"Batch finished.\nCompleted: {completed}\nErrors: {errors}",
        )

    def _stop_queue_batch(self, cancelled: bool = False) -> None:
        self._archive_batch_to_history(cancelled=cancelled)
        self._queue_batch_active = False
        set_settings_panel_locked(self, False)
        if hasattr(self.ui, 'btn_start'):
            self.ui.btn_start.setEnabled(True)
        if hasattr(self.ui, 'btn_cancel'):
            self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.setText("Pause")
        self._update_start_button_label()
        self.refresh_render_queue_panel()
        self.update_playback_badge()
        if cancelled:
            self.update_status_indicator("Cancelled", "cancelled")
            QMessageBox.information(self.ui, "Cancelled", "Queue render was cancelled.")
        self.update_status_indicator("Ready", "ready")

    def _show_steempeg_render_error_dialog(
        self,
        error_msg: str,
        *,
        batch_continue: bool = False,
        auto_continue_seconds: int = 10,
    ) -> bool:
        """Frameless FFmpeg error dialog. Returns True to continue queue, False to stop."""
        dialog = QDialog(self.ui)
        dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        dialog.setFixedSize(780, 420)
        dialog.setStyleSheet(_RENDER_ERROR_DIALOG_STYLE)

        main_layout = QHBoxLayout(dialog)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        pic_label = QLabel()
        pixmap = QPixmap(get_resource_path("saderror.png"))
        if not pixmap.isNull():
            pic_label.setPixmap(pixmap.scaledToWidth(240, Qt.TransformationMode.SmoothTransformation))
        else:
            pic_label.setText("Sad pic\nnot found =(")
            pic_label.setStyleSheet("color: gray; font-size: 12px;")
        pic_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        main_layout.addWidget(pic_label)

        content_layout = QVBoxLayout()
        content_layout.setSpacing(15)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)

        if batch_continue:
            title_text = "Render Failed"
            desc_text = (
                "FFmpeg crashed while processing this clip. "
                f"Auto-continuing in {auto_continue_seconds} s..."
            )
        else:
            title_text = "Render Failed"
            desc_text = "FFmpeg encountered a critical error during processing."

        title_lbl = QLabel(title_text)
        title_lbl.setObjectName("ErrorTitle")
        desc_lbl = QLabel(desc_text)
        desc_lbl.setObjectName("ErrorDesc")
        title_layout.addWidget(title_lbl)
        title_layout.addWidget(desc_lbl)
        content_layout.addLayout(title_layout)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        short_error = (error_msg or "Unknown error")[-2000:]
        text_edit.setText(short_error)
        content_layout.addWidget(text_edit)

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
                subprocess.Popen(["notepad.exe", os.path.abspath(self.current_log_file)])

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
        main_layout.addLayout(content_layout)

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
            
            # Change the button text depending on the status
            if is_paused:
                if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setText("Resume")
                self.update_status_indicator("Paused...", "paused")
            else:
                if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setText("Pause")
                self.update_status_indicator("Processing...", "rendering")

    def on_render_finished(self, success, error_msg, output_file):
        """ Fires when the background rendering thread exits. """
        active_job = getattr(self, "_active_render_job", None)
        if active_job:
            self._sync_queue_job_render_status(active_job.clip_path, success, error_msg)

        self._is_rendering = False
        self._active_render_job = None
        self.refresh_render_queue_panel()
        self.update_playback_badge()
        self._persist_render_queue()

        if getattr(self, "_queue_batch_active", False):
            if success:
                logging.info("=== BATCH RENDER SUCCESS === %s", output_file)
                self.process_next_in_queue()
                return
            if "cancelled by user" in (error_msg or "").lower():
                self._stop_queue_batch(cancelled=True)
                return
            if self._prompt_batch_continue_after_error(error_msg or ""):
                self.process_next_in_queue()
            else:
                self._stop_queue_batch()
            return

        set_settings_panel_locked(self, False)

        if hasattr(self.ui, 'btn_start'): self.ui.btn_start.setEnabled(True)
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.setText("Pause")

        if success:
            logging.info("=== RENDER SUCCESS ===")
            if output_file and active_job:
                try:
                    from steempeg.core.rendered_media import (
                        parse_app_id_from_clip_folder,
                        parse_app_id_from_name,
                        save_rendered_companion_meta,
                    )

                    clip_name = os.path.basename(active_job.clip_path or "")
                    app_id = (
                        parse_app_id_from_name(clip_name)
                        or parse_app_id_from_clip_folder(clip_name)
                    )
                    save_rendered_companion_meta(
                        output_file,
                        app_id=app_id,
                        game_name=active_job.game_name,
                        clip_path=active_job.clip_path,
                        game_icon_path=active_job.game_icon_path,
                    )
                    self._rendered_output_meta_index = None
                except Exception as exc:
                    logging.debug("Rendered companion meta not saved: %s", exc)

            self.update_status_indicator("Success!", "success")
            
            # A CUSTOM SUCCESS WINDOW
            msg_box = QMessageBox(self.ui)
            msg_box.setWindowTitle("Success!")
            msg_box.setText(f"Clip successfully saved to:\n{output_file}")
            msg_box.setIcon(QMessageBox.Information)
            
            btn_folder = msg_box.addButton("Open Folder", QMessageBox.ActionRole)
            btn_play = msg_box.addButton("Play Video", QMessageBox.ActionRole)
            btn_ok = msg_box.addButton(QMessageBox.Ok)
            
            # The code pauses here. The user sees 100% in the background and a window.
            msg_box.exec()
            
            # Handling User Selection
            if msg_box.clickedButton() == btn_folder:
                self.open_rendered_folder(output_file)
                
            elif msg_box.clickedButton() == btn_play:
                file_path = os.path.abspath(output_file)
                os.startfile(file_path)

            self.update_status_indicator("Ready", "ready")

        elif "cancelled by user" in error_msg.lower():
            logging.warning("=== RENDER CANCELED ===")
            self.update_status_indicator("Cancelled", "cancelled")
            QMessageBox.information(self.ui, "Cancelled", "Render was cancelled.")
            self.update_status_indicator("Ready", "ready")

        else:
            logging.error(f"=== RENDER ERROR === \n{error_msg}")
            self.update_status_indicator("Error!", "error")
            self._show_steempeg_render_error_dialog(error_msg or "")
            self.update_status_indicator("Ready", "ready")

        self.update_final_setup()

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

        # Load the attention icon smoothly
        pix_path = get_resource_path("attention.png")
        if os.path.exists(pix_path):
            pixmap = QPixmap(pix_path)
            warn_icon.setPixmap(pixmap.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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