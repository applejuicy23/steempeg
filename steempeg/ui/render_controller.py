"""Rendering controls and the export pipeline, mixed into the main application.

These methods drive the render tab: probing clip media, building quality and
bitrate options, validating custom input, running the export thread and reporting
results. They run on the application instance and reach its widgets and state
through self.
"""
import logging
import os
import re
import subprocess
import sys

from PySide6.QtCore import Qt
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
from steempeg.core.dash import discovery, mpd, repair
from steempeg.infra.paths import get_resource_path, get_save_directory
from steempeg.render import bitrate
from steempeg.render.queue import RenderQueue
from steempeg.ui.render_panel import set_settings_panel_locked
from steempeg.ui.render_job_builder import build_render_job_from_ui, resolve_render_params
from steempeg.ui.render_thread import RenderThread

# Folder holding the bundled ffmpeg/ffprobe binaries (repo/bin), mirroring the
# PATH setup the application performs at startup.
if getattr(sys, "frozen", False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_bin_dir = os.path.join(_base_dir, "bin")


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

    def _on_render_progress(self, msg):
        """Helper to safely receive thread signals on the main GUI thread."""
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

        display_text = str(text)
        percent = None

        pct_match = re.search(r'\((\d+(?:\.\d+)?)%\)', display_text)
        if pct_match:
            percent = max(0.0, min(100.0, float(pct_match.group(1))))
            display_text = re.sub(r'\s*\(\d+(?:\.\d+)?%\)', '', display_text).strip()

        if state == "rendering" and not display_text:
            display_text = "Rendering"

        if hasattr(self, 'status_dot'):
            self.status_dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")

        self.ui.label_status.setText(
            f"<span style='font-weight: bold; color: {color}; font-family: Segoe UI, Arial, sans-serif;'>"
            f"{display_text}</span>"
        )

        if state == "success":
            percent = 100.0
        elif state == "ready" or state == "error":
            percent = 0.0

        if hasattr(self.ui, 'progress_render'):
            if percent is not None:
                self.ui.progress_render.setValue(int(percent * 10))
            elif state == "success":
                self.ui.progress_render.setValue(1000)
            elif state in ("ready", "error"):
                self.ui.progress_render.setValue(0)
            self.ui.progress_render.setTextVisible(False)

            chunk = (
                "qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #6b5a8e, stop:1 #b29ae7)"
                if state == "rendering"
                else color
            )
            self.ui.progress_render.setStyleSheet(f"""
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
            elif state in ("ready", "error"):
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

    def update_quality_options(self):
        """ Reads the clip's XML data and prepares the UI for the render settings """
        if not hasattr(self.ui, 'table_clips'): return
        selected_row = self.ui.table_clips.currentRow()
        if selected_row < 0:
            self.ui.source_label.setText("Source:")
            self.ui.orig_res_label.setText("Original Resolution:")
            # Set default empty states for our new widgets
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate:")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate:")
            return
        if hasattr(self, 'grid_clips'):
            self.grid_clips.blockSignals(True) # To Avoid Conflicts
            for i in range(self.grid_clips.count()):
                item = self.grid_clips.item(i)
                # Verify the card's hidden index against the selected row in the table.
                if item.data(Qt.UserRole) == selected_row:
                    item.setSelected(True)
                    self.grid_clips.scrollToItem(item)# Automatically scroll to the desired tile!
                else:
                    item.setSelected(False)
            self.grid_clips.blockSignals(False)
        
        # --- 1. SAVE CURRENT USER SELECTION ---
        current_quality = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else ""
        current_fps = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else ""
        current_bitrate = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else ""
            
        # Extract the FULL path (for FFmpeg)
        clip_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
        

        
        # Extract ONLY the folder NAME (for example, bg_3513350_20260508) for the text field
        clip_folder_name = os.path.basename(clip_path)

        parts = clip_folder_name.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            self.current_game_icon = os.path.join(self.cache_dir, f"{parts[1]}.jpg")
        else:
            self.current_game_icon = ""

        ## Automatically insert a neat file name
        if hasattr(self.ui, 'input_filename'):
            self.ui.input_filename.setText(f"{clip_folder_name}_rendered")
            
        # Search for mpd files by full path
        all_mpds = self.get_all_mpd_paths(clip_path)

        if not all_mpds:
            self.ui.source_label.setText("Source: No MPD files found")
            self.ui.orig_res_label.setText("Original resolution: Unknown")
            # Update our new widgets
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate: Unknown")
            self.ui.combo_quality.clear()
            if hasattr(self, 'btn_copy_src'): self.btn_copy_src.hide()
            return

        # Update the label with the path to the sources
        source_dirs = [os.path.dirname(m) for m in all_mpds]
        unique_source_dirs = list(dict.fromkeys(source_dirs))
        
        # Save FULL raw paths to memory so our COPY button can copy them completely!
        self.current_source_raw_paths = "\n".join(unique_source_dirs)
        
        # Local helper to cleanly cut long HTML paths
        def elide_html_path(path, max_len=75):
            if len(path) <= max_len: return path
            half = (max_len - 5) // 2
            return path[:half] + "[...]" + path[-half:]
        
        # Apply the cut [...] only for the visual UI
        formatted_sources = "<br>".join([f"{i+1}. {elide_html_path(p)}" for i, p in enumerate(unique_source_dirs)])
        self.ui.source_label.setText(f"Source:<br><span style='font-size:8pt; color:#aaaaaa;'>{formatted_sources}</span>")
        
        # Show the copy button now that we have a valid path!
        if hasattr(self, 'btn_copy_src'): 
            self.btn_copy_src.show()

        # Reading bitrait
        orig_audio_bitrate = self.get_audio_bitrate_from_mpd(all_mpds[0]) if all_mpds else 192
        self.current_orig_audio_bitrate = orig_audio_bitrate

        if hasattr(self.ui, 'combo_audio_bitrate'):
            self.ui.combo_audio_bitrate.blockSignals(True)
            self.ui.combo_audio_bitrate.clear()
            
            bitrates = [
                (320, "320 kbps (Best Quality)"),
                (256, "256 kbps (High Quality)"),
                (192, "192 kbps (Good Quality)"),
                (128, "128 kbps (Standard)"),
                (64, "64 kbps (Bad)"),
                (32, "32 kbps (Very bad)")
            ]
            
            self.ui.combo_audio_bitrate.addItem(f"{orig_audio_bitrate} kbps (Original)")
            
            # We add to the list only those that do not exceed the original (with a small margin)
            for val, text in bitrates:
                if val <= orig_audio_bitrate + 15: 
                    self.ui.combo_audio_bitrate.addItem(text)
            
            self.ui.combo_audio_bitrate.insertSeparator(self.ui.combo_audio_bitrate.count())
            self.ui.combo_audio_bitrate.addItem("⚙️ Custom Audio...")

            self.ui.combo_audio_bitrate.blockSignals(False)
        
        unique_resolutions = set()
        max_height = 0
        self.current_orig_bitrate = 0

        # Parsing session.mpd to find the original resolution and bitrate
        for mpd_path in all_mpds:
            try:
                with open(mpd_path, 'r', encoding='utf-8') as file:
                    content = file.read()

                    # Call our function to calculate the size and time
                    clip_full_path = os.path.dirname(mpd_path)
                    size_str, duration_str = self.get_clip_size_and_duration(clip_full_path, content)
                    
                    if hasattr(self.ui, 'label_size'):
                        self.ui.label_size.setText(f"Size: {size_str}")
                    if hasattr(self.ui, 'label_duration'):
                        self.ui.label_duration.setText(f"Time: {duration_str}")

                    #1. Trying to find FPS in an XML file (the fastest way)
                    fps_match = re.search(r'\bframeRate="(\d+)(?:/\d+)?"', content)
                    if fps_match:
                        self.current_orig_fps = int(fps_match.group(1))
                    else:
                        # 2. Call ffprobe and let it READ THE MPD FILE!
                        self.current_orig_fps = self.get_fps_from_mpd(mpd_path)
                        
                    #UPDATE YOUR LABEL
                    if hasattr(self.ui, 'label_fps'):
                        self.ui.label_fps.setText(f"FPS: {self.current_orig_fps}")
                    
                    height_match = re.search(r'\bheight="(\d+)"', content)
                    width_match = re.search(r'\bwidth="(\d+)"', content)
                    bandwidth_match = re.search(r'\bbandwidth="(\d+)"', content)
                    
                    if bandwidth_match:
                        # Converting bitrate from bytes to mb
                        self.current_orig_bitrate = int(bandwidth_match.group(1)) / 1000000
                    
                    if height_match and width_match:
                        h = int(height_match.group(1))
                        w = int(width_match.group(1))
                        unique_resolutions.add(f"{w}x{h}")
                        if h > max_height: max_height = h
            except: pass

        if unique_resolutions:
            res_text = ", ".join(sorted(list(unique_resolutions)))
            audio_kbps = getattr(self, 'current_orig_audio_bitrate', 192)
            
            # Keep only the resolution here
            self.ui.orig_res_label.setText(f"Original resolution: {res_text}")
            
            # Populate Video Bitrate independently (Removed the '~' symbol!)
            if hasattr(self.ui, 'label_vbitrate'):
                if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                    rounded_bitrate = int(round(self.current_orig_bitrate))
                    self.ui.label_vbitrate.setText(f"Video Bitrate: {rounded_bitrate} Mbps")
                else:
                    self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            
            # Populate Audio Bitrate independently
            if hasattr(self.ui, 'label_abitrate'):
                self.ui.label_abitrate.setText(f"Audio Bitrate: {audio_kbps} kbps")
                
        else:
            self.ui.orig_res_label.setText("Original resolution: Unknown")
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate: Unknown")
            max_height = 1080

        # Fill in the drop-down list of resolutions (cutting off those that are larger than the original)
        if hasattr(self.ui, 'combo_quality'):
            self.ui.combo_quality.clear()
            
            # Dynamic Original Title (eg: Original (Lossless, 1440p))
            if max_height > 0:
                self.ui.combo_quality.addItem(f"Original (Lossless, {max_height}p)")
            else:
                self.ui.combo_quality.addItem("Original (Lossless)")

            for preset_name, preset_height in self.all_qualities:
                if preset_height <= max_height:
                    self.ui.combo_quality.addItem(preset_name)
            
            self.ui.combo_quality.setCurrentIndex(0)
            self.ui.combo_quality.insertSeparator(self.ui.combo_quality.count())
            self.ui.combo_quality.addItem("🎯 Target File Size...")
            self.update_bitrate_options() # Calling a function to update bitrates
        
        if hasattr(self.ui, 'combo_fps'):
            self.ui.combo_fps.clear()
            
            # Take FPS from the clip
            fps_val = getattr(self, 'current_orig_fps', 60)
            
            if fps_val >= 60:
                self.ui.combo_fps.addItem(f"{fps_val} FPS (Original)")
                self.ui.combo_fps.addItem("30 FPS")
                self.ui.combo_fps.addItem("15 FPS")
            elif fps_val >= 30:
                self.ui.combo_fps.addItem(f"{fps_val} FPS (Original)")
                self.ui.combo_fps.addItem("15 FPS")
            else:
                self.ui.combo_fps.addItem(f"{fps_val} FPS (Original)")

            self.ui.combo_fps.insertSeparator(self.ui.combo_fps.count())
            self.ui.combo_fps.addItem("⚙️ Custom FPS...")

            self.ui.combo_fps.setCurrentIndex(0)
        else:
            print("ERROR: Widget combo_fps not found! Check objectName in Qt Designer.")
        
        # 2. RESTORE USER SELECTION (IF IT STILL EXISTS)
        if current_quality and hasattr(self.ui, 'combo_quality'):
            index = self.ui.combo_quality.findText(current_quality)
            if index >= 0: self.ui.combo_quality.setCurrentIndex(index)
            
        if current_fps and hasattr(self.ui, 'combo_fps'):
            index = self.ui.combo_fps.findText(current_fps)
            if index >= 0: self.ui.combo_fps.setCurrentIndex(index)
            
        if current_bitrate and hasattr(self.ui, 'combo_bitrate'):
            index = self.ui.combo_bitrate.findText(current_bitrate)
            if index >= 0: self.ui.combo_bitrate.setCurrentIndex(index)

        # Unlock start button safely
        if not getattr(self, '_is_rendering', False):
            self.ui.btn_start.setEnabled(True)

        self.ui.btn_start.setEnabled(True)
        self.update_final_setup()

        # --- PLAYER HEADER DATA ---
        game_item = self.ui.table_clips.item(selected_row, 0)
        game_name = game_item.text()
        game_icon = game_item.icon()
        
        clip_date = self.ui.table_clips.item(selected_row, 2).text()
        clip_time = self.ui.table_clips.item(selected_row, 3).text()
        
        # Updating our correct software panel
        if hasattr(self, 'custom_text_label'):
            header_html = f"<b>{game_name}</b> <span style='color: #888;'>&nbsp;&nbsp;•&nbsp;&nbsp; {clip_date} &nbsp;&nbsp;•&nbsp;&nbsp; {clip_time}</span>"
            self.custom_text_label.setText(header_html)
            
        if hasattr(self, 'custom_icon_label'):
            self.custom_icon_label.setPixmap(game_icon.pixmap(24, 24))

        # Automatically load and play the new clip. This overwrites the stuck frame of the previous clip!
        self.generate_and_play_preview()
        
    
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

        if "Original" in quality_text:
            if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                self.ui.combo_bitrate.addItem(f"~{int(self.current_orig_bitrate)} Mbps (Original Copy)")
            else:
                self.ui.combo_bitrate.addItem("Original Bitrate (Copy)")
                
            self.ui.combo_bitrate.setEnabled(False) 
            if hasattr(self.ui, 'combo_fps'):
                self.ui.combo_fps.setCurrentIndex(0) 
                self.ui.combo_fps.setEnabled(False)
            if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(False)
            if hasattr(self.ui, 'combo_encoder'): self.ui.combo_encoder.setEnabled(False)
            self.ui.combo_bitrate.blockSignals(False)
            self.update_final_setup()
            return

        self.ui.combo_bitrate.setEnabled(True) 
        if hasattr(self.ui, 'combo_fps'): self.ui.combo_fps.setEnabled(True)
        if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(True)
        if hasattr(self.ui, 'combo_encoder'): self.ui.combo_encoder.setEnabled(True)
        
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

        for quality_level in ["Ultra", "High", "Medium", "Low"]:
            if res_key in self.steam_bitrate_presets.get(quality_level, {}):
                preset_bitrate = self.steam_bitrate_presets[quality_level][res_key]
                
                if getattr(self, 'current_orig_bitrate', 0) == 0 or preset_bitrate <= (self.current_orig_bitrate + 5):
                    # We're multiplying right here just for the sake of appearance in the ComboBox!
                    scaled_bitrate = preset_bitrate * fps_multiplier
                    
                    display_val = f"{scaled_bitrate:.1f}".rstrip('0').rstrip('.') if scaled_bitrate % 1 != 0 else str(int(scaled_bitrate))
                    
                    self.ui.combo_bitrate.addItem(f"{quality_level} - {display_val} Mbps")
                    added_any = True
        
        if not added_any and res_key in self.steam_bitrate_presets["Low"]:
            lowest_bitrate = self.steam_bitrate_presets["Low"][res_key] * fps_multiplier
            display_val = f"{lowest_bitrate:.1f}".rstrip('0').rstrip('.') if lowest_bitrate % 1 != 0 else str(int(lowest_bitrate))
            self.ui.combo_bitrate.addItem(f"Low - {display_val} Mbps")
        
        self.ui.combo_bitrate.insertSeparator(self.ui.combo_bitrate.count())
        self.ui.combo_bitrate.addItem("⚙️ Custom Bitrate...")
        
        # --- RESTORING SELECTION ---
        if selected_level:
            for i in range(self.ui.combo_bitrate.count()):
                if self.ui.combo_bitrate.itemText(i).startswith(selected_level):
                    self.ui.combo_bitrate.setCurrentIndex(i)
                    break

        self.ui.combo_bitrate.blockSignals(False)
        self.update_final_setup()
    
    def update_final_setup(self):
        """Dynamically updates the Detailed Summary, Size, and Save Path."""
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
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

        # 2. Calculate the file extension
        ext = ".mp3" if (audio_only and audio_format == "MP3") else (".aac" if audio_only else ".mp4")

        # 3. OVERWRITE PROTECTION 
        save_dir = self.custom_destination if self.custom_destination else get_save_directory()
        base_filename = self.ui.input_filename.text().strip() if hasattr(self.ui, 'input_filename') else "rendered"
        
        for e in [".mp4", ".mp3", ".aac"]:
            if base_filename.lower().endswith(e): base_filename = base_filename[:-4]

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
            self.ui.label_location.setText(f"Output: {display_path}")
            
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
        if fps:
            if "Custom" in fps and hasattr(self, 'input_custom_fps'):
                try: selected_fps = int(self.input_custom_fps.text())
                except: selected_fps = getattr(self, 'current_orig_fps', 60)
            else:
                try: selected_fps = int(re.search(r'(\d+)', fps).group(1))
                except: selected_fps = getattr(self, 'current_orig_fps', 60)
                
            orig_fps = getattr(self, 'current_orig_fps', 60)
            if selected_fps < orig_fps and orig_fps > 0:
                fps_multiplier = selected_fps / orig_fps

        if duration > 0:
            if "Target File Size" in quality:
                if hasattr(self, 'dynamic_stops') and hasattr(self.ui, 'size_slider'):
                    target_mb = self.dynamic_stops[self.ui.size_slider.value()]
                    size_str = f"~{target_mb / 1024:.2f} GB (Target)" if target_mb >= 1000 else f"~{target_mb} MB (Target)"
            elif "Original" in bitrate_text:
                if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                    orig_total_bitrate = (self.current_orig_bitrate * fps_multiplier) + 0.19 
                    size_mb = (orig_total_bitrate * duration) / 8 
                    size_str = f"Same as original (~{size_mb / 1024:.2f} GB)" if size_mb >= 1000 else f"Same as original (~{size_mb:.1f} MB)"
                else:
                    size_str = "Same as original"
            else:
                match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
                if match:
                    video_bitrate = float(match.group(1)) 
                    audio_bitrate_val = float(audio_bitrate.split(' ')[0]) / 1000 if ' ' in audio_bitrate else 0.19
                    if mute_audio: audio_bitrate_val = 0
                    total_bitrate = video_bitrate + audio_bitrate_val
                    size_mb = (total_bitrate * duration) / 8 
                    size_str = f"~{size_mb / 1024:.2f} GB" if size_mb >= 1000 else f"~{size_mb:.1f} MB"

        if audio_only:
            sound_info = f"{audio_format} {audio_bitrate.split(' ')[0]} kbps"
            other_info = ">> EXTRACT AUDIO ONLY (NO VIDEO)"
        elif mute_audio:
            sound_info = "None"
            other_info = ">> NO SOUND (MUTED)"
        else:
            sound_info = audio_bitrate
            other_info = "Normal Render"

        # 5. Smart Detailed Summary in Export Settings
        
        # --- CLEAN PARSING FOR UI DISPLAY ---
        
        # Parse Video Bitrate for UI
        video_bitrate_display = "Unknown"
        orig_v_bitrate = getattr(self, 'current_orig_bitrate', 10.0)

        if "Target File Size" in quality:
            val_mbps = getattr(self, 'custom_target_bitrate', 1500) / 1000
            scale_h = getattr(self, 'custom_target_height', -1)
            res_str = f"Auto: {scale_h}p" if scale_h > 0 else "Original"
            clean_mbps = int(round(val_mbps))
            video_bitrate_display = f"{clean_mbps} Mbps ({res_str})"
        elif "Custom" in bitrate_text:
            try:
                val = float(self.input_custom_vbitrate.text().replace(',', '.'))
                val = max(0.1, min(val, orig_v_bitrate))
                # Multiply by the FPS drop
                video_bitrate_display = f"⚙️ {val * fps_multiplier:.1f} Mbps"
            except:
                video_bitrate_display = f"{orig_v_bitrate * fps_multiplier:.1f} Mbps"
        elif "Original" in bitrate_text:
            video_bitrate_display = f"{orig_v_bitrate * fps_multiplier:.1f} Mbps"
        else:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match: 
                video_bitrate_display = f"{float(match.group(1)):.1f} Mbps"

        # Parse Audio Bitrate for UI
        orig_a_bitrate = getattr(self, 'current_orig_audio_bitrate', 192)
        if "Custom" in audio_bitrate:
            try:
                val = int(self.input_custom_abitrate.text())
                val = max(1, min(val, orig_a_bitrate))
                audio_bitrate_clean = f"⚙️ {val} kbps"
            except:
                audio_bitrate_clean = f"{orig_a_bitrate} kbps"
        else:
            # Clean up "(Original Copy)" just "192 kbps"
            audio_bitrate_clean = audio_bitrate.split('(')[0].strip() if audio_bitrate else "192 kbps"

        # Parse FPS for UI (includes the word "FPS" inside)
        orig_fps = getattr(self, 'current_orig_fps', 60)
        if "Custom" in fps:
            max_allowed = min(60, orig_fps)
            try:
                val = int(self.input_custom_fps.text())
                val = max(1, min(val, max_allowed))
                fps_display = f"⚙️ {val} FPS"
            except:
                fps_display = f"{max_allowed} FPS"
        else:
            val_str = fps.split(' ')[0] if fps else "Unknown"
            fps_display = f"{val_str} FPS" if val_str != "Unknown" else "Unknown"

        # Clean strings
        q_clean = quality.split('(')[0].strip() if quality else "Unknown"
        enc_clean = encoder if encoder else "Unknown"

        # Construct the final detailed text block 
        if audio_only:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Format: {audio_format}\n"
                f"Sound: {audio_format}, {audio_bitrate_clean}\n"
                f"Other settings: >> EXTRACT AUDIO ONLY (NO VIDEO)\n"
                f"Est. File Size: {size_str}"
            )
        elif mute_audio:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Quality: {q_clean}\n"
                f"FPS: {fps_display}\n"
                f"Bitrate: {video_bitrate_display}\n"
                f"Codec: {codec}\n"
                f"Encoder: {enc_clean}\n"
                f"Other settings: >> NO SOUND (MUTED)\n"
                f"Est. File Size: {size_str}"
            )
        else:
            detailed_text = (
                f"Clip time: {duration_str}\n"
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

        # 6. Short Summary ABOVE Ready 
        q_word = quality.split()[0] if quality.split() else "Unknown"
        
        game_name = "Steam Clip"
        if hasattr(self.ui, 'table_clips') and self.ui.table_clips.currentRow() >= 0:
            game_name = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).text().strip()
            
        game_icon = getattr(self, 'current_game_icon', '')
        unknown_icon_path = get_resource_path("unknown_icon.png")
        target_icon = game_icon if (game_icon and os.path.exists(game_icon)) else unknown_icon_path

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
                self.place_logo.setStyleSheet(f"image: url('{icon_css}'); background: transparent; border: none;")
                self.place_text.setText(f"Ready to play: {game_name}") 
                self.place_text.setStyleSheet("color: #a0a0a0; font-size: 15px; font-weight: bold; margin-top: 15px;")
            
        if not getattr(self, '_is_rendering', False):
            self.update_status_indicator("Ready", "ready")

    def on_quality_mode_changed(self, text):
        """ Hides or shows the slider and target inputs depending on the mode """
        is_target_mode = "Target File Size" in text
        
        if hasattr(self.ui, 'size_slider'):
            self.ui.size_slider.setVisible(is_target_mode)
            
        if hasattr(self, 'size_container'):
            self.size_container.setVisible(is_target_mode)
            
        if is_target_mode:
            self.setup_dynamic_slider()

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
        elif "Custom" in audio_text and hasattr(self, 'input_custom_abitrate'):
            try:
                audio_kbps = int(self.input_custom_abitrate.text())
            except ValueError:
                audio_kbps = getattr(self, 'current_orig_audio_bitrate', 192)
        else:
            match = re.search(r'(\d+)', audio_text)
            audio_kbps = int(match.group(1)) if match else 192

        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        if "Custom" in fps_text and hasattr(self, 'input_custom_fps'):
            try:
                fps = int(self.input_custom_fps.text())
            except ValueError:
                fps = getattr(self, 'current_orig_fps', 60)
        else:
            try:
                fps = int(re.search(r'(\d+)', fps_text).group(1))
            except (AttributeError, ValueError):
                fps = getattr(self, 'current_orig_fps', 60)

        # --- run the pure math ---
        plan = bitrate.plan_bitrate(duration, orig_video_mbps, target_mb, audio_kbps, fps,
                                    is_lossless=is_lossless, is_custom=is_custom)
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

    def start_render_thread(self):
        """ Prepares parameters and starts the background rendering thread """
        if getattr(self, '_is_rendering', False):
            return
        
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            QMessageBox.warning(self.ui, "Error", "Please select a clip from the list first!")
            return
            
        clip_name = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).data(Qt.UserRole)

        job = build_render_job_from_ui(self, clip_name)
        if job is None:
            QMessageBox.warning(self.ui, "Error", "session.mpd files not found inside this clip!")
            return

        ffmpeg_exe = os.path.join(_bin_dir, "ffmpeg.exe")
        if not os.path.exists(ffmpeg_exe):
            QMessageBox.critical(self.ui, "Error", "ffmpeg.exe not found!")
            return

        params = resolve_render_params(job, ffmpeg_exe)
        if params is None:
            QMessageBox.warning(self.ui, "Error", "session.mpd files not found inside this clip!")
            return

        set_settings_panel_locked(self, True)
        self.ui.btn_start.setEnabled(False)
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(True)
        if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(True)

        self.update_status_indicator("Initializing...", "rendering")
        logging.info(f"--- RENDER STARTED ---")

        self._is_rendering = True
        self._active_render_job = job

        logging.info(f"Source: {clip_name}")
        logging.info(f"Saving in: {params.output_file}")
        logging.info(
            f"Settings: Quality={params.quality_text}, FPS={params.fps_text}, "
            f"Bitrate={params.video_bitrate}, Codec={params.selected_encoder}, "
            f"AudioOnly={params.audio_only}, Muted={params.mute_audio}"
        )

        try:
            self.thread = RenderThread(
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
            self.thread.progress_signal.connect(self._on_render_progress)
            self.thread.finished_signal.connect(self.on_render_finished)
            self.thread.start()
        except Exception as e:
            logging.error(f"Thread Start Error: {e}")
            self._is_rendering = False
            self._active_render_job = None
            set_settings_panel_locked(self, False)
            self.update_status_indicator("Error!", "error")
            self.ui.btn_start.setEnabled(True)
            if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
            if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(False)
            QMessageBox.critical(self.ui, "Thread Error", f"Could not start render:\n{e}")
    def cancel_render(self):
        """ Cancel Button Handler """
        logging.warning("User cancelled rendering (Cancel)")
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.update_status_indicator("Cancelling... Please wait", "cancelling")
            if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
            if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(False)
            self.thread.cancel() # Send a cancel signal to the thread

    def toggle_pause(self):
        """ Pause button handler """
        logging.info("User Paused/Resumed rendering")
        if hasattr(self, 'thread') and self.thread.isRunning():
            is_paused = self.thread.toggle_pause() # Send a pause signal to the thread
            
            # Change the button text depending on the status
            if is_paused:
                if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setText("Resume")
                self.update_status_indicator("Paused...", "paused")
            else:
                if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setText("Pause")
                self.update_status_indicator("Processing...", "rendering")

    def on_render_finished(self, success, error_msg, output_file):
        """ Fires when the background rendering thread exits. """
        self._is_rendering = False
        self._active_render_job = None
        set_settings_panel_locked(self, False)

        # Unlocking the UI
        if hasattr(self.ui, 'btn_start'): self.ui.btn_start.setEnabled(True)
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'): 
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.setText("Pause")
        
        # Show the result to the user
        if success:
            logging.info("=== RENDER SUCCESS ===")
            
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
            
            # --- STEEMPEG CUSTOM ERROR WINDOW ---


            dialog = QDialog(self.ui)
            dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
            # Make the window wider so that the image and logs fit comfortably.
            dialog.setFixedSize(780, 420)
            
            dialog.setStyleSheet("""
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
            """)
            
            # --- MAIN LAYER (Horizontal) ---
            main_layout = QHBoxLayout(dialog)
            main_layout.setContentsMargins(20, 20, 20, 20)
            main_layout.setSpacing(20)

            # --- LEFT SIDE: Sad Image ---
            pic_label = QLabel()
            pixmap = QPixmap(get_resource_path("saderror.png"))
            
            if not pixmap.isNull():
                # Shrinking a huge image to 240 pixels in width with beautiful anti-aliasing
                scaled_pixmap = pixmap.scaledToWidth(240, Qt.TransformationMode.SmoothTransformation)
                pic_label.setPixmap(scaled_pixmap)
            else:
                pic_label.setText("Sad pic\nnot found =(")
                pic_label.setStyleSheet("color: gray; font-size: 12px;")
                
            pic_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            main_layout.addWidget(pic_label)

            # --- RIGHT SIDE: Text, Logs, and Buttons ---
            content_layout = QVBoxLayout()
            content_layout.setSpacing(15)

            # 1. HEADER (without the crooked icon—text only)
            title_layout = QVBoxLayout()
            title_layout.setSpacing(2)

            title_lbl = QLabel("Render Failed")
            title_lbl.setObjectName("ErrorTitle")
            desc_lbl = QLabel("FFmpeg encountered a critical error during processing.")
            desc_lbl.setObjectName("ErrorDesc")
            
            title_layout.addWidget(title_lbl)
            title_layout.addWidget(desc_lbl)
            content_layout.addLayout(title_layout)

            # 2. LOGS FIELD
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            short_error = error_msg[-2000:] if len(error_msg) > 2000 else error_msg
            text_edit.setText(short_error)
            content_layout.addWidget(text_edit)

            # 3. Control Buttons
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            btn_log = QPushButton("📄 Open Log File")
            btn_log.setObjectName("LogBtn")
            btn_log.setCursor(Qt.CursorShape.PointingHandCursor)
            
            btn_ok = QPushButton("Close")
            btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
            
            btn_layout.addWidget(btn_log)
            btn_layout.addWidget(btn_ok)
            
            content_layout.addLayout(btn_layout)
            
           # Bringing Everything Together in the Main Window
            main_layout.addLayout(content_layout)
            
            def open_log_and_close():
                if hasattr(self, 'current_log_file') and os.path.exists(self.current_log_file):
                    log_path = os.path.abspath(self.current_log_file)
                    subprocess.Popen(["notepad.exe", log_path])
                dialog.accept()
                
            btn_log.clicked.connect(open_log_and_close)
            btn_ok.clicked.connect(dialog.accept)

            dialog.exec()
            
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