"""Rendering controls and the export pipeline, mixed into the main application.

These methods drive the render tab: probing clip media, building quality and
bitrate options, validating custom input, running the export thread and reporting
results. They run on the application instance and reach its widgets and state
through self.
"""
import logging
import os
import subprocess

from PySide6.QtWidgets import QFileDialog

from steempeg.core import capabilities
from steempeg.core.dash import discovery, mpd, repair
from steempeg.infra.paths import get_save_directory


class RenderMixin:
    def get_all_mpd_paths(self, clip_path):
        return discovery.find_mpd_paths(clip_path)

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
            self.ui.destination_button.setText(f"Destination: {folder}")
        else:
            # If we change our minds and click Cancel, we return to our cool folder
            default_export_dir = os.path.join(get_save_directory(), "rendered_videos").replace('\\', '/')
            if not os.path.exists(default_export_dir):
                os.makedirs(default_export_dir, exist_ok=True)
            self.custom_destination = default_export_dir
            self.ui.destination_button.setText(f"Destination: {default_export_dir}")

        self.update_final_setup()

    def on_audio_only_toggled(self, checked):
        """ Disables video settings if audio-only mode is active """
        if checked and hasattr(self.ui, 'check_mute_audio'):
            self.ui.check_mute_audio.blockSignals(True)
            self.ui.check_mute_audio.setChecked(False)
            self.ui.check_mute_audio.blockSignals(False)

        if hasattr(self.ui, 'tab_video'):
            self.ui.tab_video.setEnabled(not checked)  # Freeze entire Video Tab
        self.update_final_setup()

    def on_mute_audio_toggled(self, checked):
        """ Disables audio settings if video-only mode is active """
        if checked and hasattr(self.ui, 'check_audio_only'):
            self.ui.check_audio_only.blockSignals(True)
            self.ui.check_audio_only.setChecked(False)
            self.ui.check_audio_only.blockSignals(False)

        if hasattr(self.ui, 'tab_audio'):
            self.ui.tab_audio.setEnabled(not checked)  # Freeze entire Audio Tab
        self.update_final_setup()

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