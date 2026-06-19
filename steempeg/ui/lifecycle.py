"""Application lifecycle and chrome, mixed into the main application.

These methods cover the status bar, the global event filter, window close and
exit cleanup, the About dialog, opening the logs, path elision and resetting
per-clip state. They run on the application instance and reach its widgets and
state through self.
"""
import os
import re

import psutil

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QMessageBox

from steempeg.infra import paths
from steempeg.infra.paths import get_resource_path
from steempeg.version import APP_VERSION_STR


class LifecycleMixin:
    def eventFilter(self, source, event):
        if getattr(self, '_is_closing', False):
            return False

        if source == self.ui and event.type() == QEvent.Type.WindowStateChange:
            if not self.ui.isMaximized() and not getattr(self, 'is_fullscreen', False):
                if getattr(self, 'needs_geometry_restore', False) and hasattr(self, 'true_normal_geom'):
                    
                    def restore_geom():
                        if not getattr(self, 'is_fullscreen', False) and not self.ui.isMaximized():
                            self.ui.setGeometry(self.true_normal_geom)
                            
                    QTimer.singleShot(50, restore_geom)
                    self.needs_geometry_restore = False

        # --- FLOATING PANEL RESIZE LOGIC ---
        if hasattr(self, 'video_wrapper') and source == self.video_wrapper and event.type() == QEvent.Type.Resize:
            if getattr(self, 'is_fullscreen', False) and hasattr(self, 'player_footer_frame'):
                self.align_fullscreen_hud()
            return False

        # 1. Disable right-click selection in the Table (List)
        if hasattr(self.ui, 'table_clips') and source == self.ui.table_clips.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    click_pos = event.position().toPoint()
                    self.show_clip_context_menu(click_pos)
                    return True
                    
        # 2. Disable right-click selection in the Grid
        if hasattr(self, 'grid_clips') and source == self.grid_clips.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    click_pos = event.position().toPoint()
                    self.show_grid_context_menu(click_pos)
                    return True

        return super().eventFilter(source, event)
    
    def set_status(self, text):
        """ Updates the status text and the progress bar """
        if hasattr(self.ui, 'label_status'):
            self.ui.label_status.setText(text.split('..')[0] + '..')
            
        if hasattr(self.ui, 'progress_render'):
            # 0
            if text in ["Ready", "Success", "Cancelled", "Error!"]:
                self.ui.progress_render.setValue(0)
                if hasattr(self, 'label_pct'): self.label_pct.setText("0%")
                if text != "Error!": self.ui.label_status.setText(text)
                
            # Separating Logic: The bar consumes 0.1%, yet the text displays WHOLE numbers!
            match = re.search(r'\(([\d.]+)%\)', text)
            if match:
                val_float = float(match.group(1))
                self.ui.progress_render.setValue(int(val_float * 10))
                if hasattr(self, 'label_pct'):
                    self.label_pct.setText(f"{int(val_float)}%") 

    def elide_path(self, path, max_len=75):
        """ Smart truncation of long paths (keeps start and end) """
        if len(path) <= max_len: return path
        half = (max_len - 7) // 2
        return path[:half] + " [...] " + path[-half:]
    
    def closeEvent(self, event):
        """ Triggered automatically when the window's red 'X' button is clicked """
        self._force_pause = True
        self._is_closing = True

        # 1. Kill the player if it is active.
        if hasattr(self, 'player') and self.player:
            self.player.pause = True 
            try:
                self.player.command('stop') 
            except:
                pass
                
        # 2. Killing the frozen FFmpeg
        try:
            current_process = psutil.Process()
            # We are looking for all child processes launched by our program.
            children = current_process.children(recursive=True)
            for child in children:
                # If the process is named ffmpeg or ffprobe, terminate it.
                if "ffmpeg" in child.name().lower() or "ffprobe" in child.name().lower():
                    child.kill()
                    print(f"Zombie proccess killed: {child.name()}")
        except Exception as e:
            print(f"⚠️ Error with killing zombie pcorsalfgn: {e}")

        event.accept()

    
    
    def on_app_exit(self):
        """ Global Intercept: Triggers when the entire program closes. """
        self._is_closing = True
        print("CLEANING BEFORE CLOSING...")
        if hasattr(self, 'player') and self.player:
            try:
                self.player.command('stop')
                self.player.terminate()
            except: pass
            
        # Killing all zombie FFmpeg child processes
        try:
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            for child in children:
                if "ffmpeg" in child.name().lower() or "ffprobe" in child.name().lower():
                    child.kill()
                    print(f"Killed FFmpeg after exit: {child.name()}")
        except: pass
    
    def show_about_dialog(self):
        """ Shows the About dialog"""
        if getattr(self, '_about_is_open', False): 
            return # Block if already open
        self._about_is_open = True
        
        msg_box = QMessageBox(self.ui)
        msg_box.setWindowTitle("About Steempeg")
        
        # Logo of the window itself
        icon_path = get_resource_path("logo.png")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            msg_box.setIconPixmap(pixmap)
        else:
            msg_box.setIcon(QMessageBox.Information)

        # Prepare 100% working absolute paths for icons within HTML
        # Use QUrl so Qt knows exactly where the images are located, even within an .exe file
        github_icon = QUrl.fromLocalFile(get_resource_path("github.jpg")).toString()
        steam_icon = QUrl.fromLocalFile(get_resource_path("steam.png")).toString()

        about_text = f"""
        <h3>Steempeg v{APP_VERSION_STR}</h3>
        <p><b>Build:</b> v{APP_VERSION_STR}</p>
        <p><b>Developer:</b> Emily 🎀 <span style="color: #888888; font-size: 10pt;">@applejuicy23</span></p>

        <p><img src="{github_icon}" width="16" height="16" align="middle"> <b>GitHub:</b> <a href="https://github.com/applejuicy23/steempeg">applejuicy23/steempeg</a></p>
        <p><img src="{steam_icon}" width="16" height="16" align="middle"> <b>Steam:</b> <a href="https://steamcommunity.com/id/applejuicy23/">applejuicy23</a></p>

        <p>A smart, elegant, and fast hardware-accelerated video renderer for Steam Clips.</p>
        <p>Powered by <b>FFmpeg,</b> <b>PyAV</b> & <b>MPV</b></p>

        <p style="font-size: 8pt; color: #777777; margin-top: 15px;">
        <i>Steempeg is an unofficial, community-created tool.<br>
        Not affiliated with, associated with, authorized, or endorsed by Valve Corporation or Steam.</i>
        </p>
        """
        
        msg_box.setText(about_text)
        msg_box.setTextInteractionFlags(Qt.TextBrowserInteraction)

        msg_box.setStandardButtons(QMessageBox.Close)
        msg_box.exec()
        
        self._about_is_open = False # Release the lock when closed


    def open_logs_folder(self):
        if hasattr(self, 'logs_dir'):
            paths.open_in_file_manager(self.logs_dir)

    def open_current_log(self):
        if hasattr(self, 'current_log_file'):
            paths.open_in_file_manager(self.current_log_file)


    def clear_clip_state(self):
        """ Clears the interface when the clip is closed by clicking the X """
        
        self.ui.lbl_top_info.setText("Clip not chosen") 
        
        self.ui.lbl_source_resolution.setText("-")
        self.ui.lbl_source_fps.setText("-")
        self.ui.lbl_source_duration.setText("-")

      
        if hasattr(self, 'player'):
            self.player.command("stop")
        if hasattr(self, 'video_wrapper'):
            self.video_wrapper.layout().setCurrentIndex(1) 
        self.ui.btn_start.setEnabled(False)
        self.ui.btn_start.setText("Choose clip for render")

        if hasattr(self.ui, 'label_time'):
            self.ui.label_time.setText("00:00 / 00:00")
            
        if hasattr(self.ui, 'btn_play'):
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))
            
        # 1. Clear the Source Info tab to dashes.
        if hasattr(self.ui, 'source_label'): self.ui.source_label.setText("Source: -")
        if hasattr(self.ui, 'orig_res_label'): self.ui.orig_res_label.setText("Original resolution: -")
        if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate: -")
        if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate: -")
        if hasattr(self.ui, 'label_size'): self.ui.label_size.setText("Size: -")
        if hasattr(self.ui, 'label_duration'): self.ui.label_duration.setText("Time: -")
        if hasattr(self.ui, 'label_fps'): self.ui.label_fps.setText("FPS: -")

       # 2. Hiding the small path-copying icons
        if hasattr(self, 'btn_copy_src'): self.btn_copy_src.hide()
        if hasattr(self, 'btn_copy_loc'): self.btn_copy_loc.hide()

        # 3. Safely clearing dropdown lists (blocking signals to avoid crashing Python)
        def clear_combo(combo_name):
            if hasattr(self.ui, combo_name):
                widget = getattr(self.ui, combo_name)
                widget.blockSignals(True)
                widget.clear()
                widget.blockSignals(False)

        clear_combo('combo_quality')
        clear_combo('combo_fps')
        clear_combo('combo_bitrate')
        clear_combo('combo_audio_bitrate')

        # Hide the custom size slider (if it was open)
        if hasattr(self.ui, 'size_slider'): self.ui.size_slider.hide()
        if hasattr(self, 'size_container'): self.size_container.hide()

        #4. Clear the Export Settings and delete the filename.
        if hasattr(self.ui, 'input_filename'):
            self.ui.input_filename.blockSignals(True)
            self.ui.input_filename.clear()
            self.ui.input_filename.blockSignals(False)
            
        if hasattr(self.ui, 'label_short_summary'):
            if hasattr(self, 'reset_bottom_summary'): self.reset_bottom_summary()
        if hasattr(self.ui, 'label_detailed_summary'):
            self.ui.label_detailed_summary.setText("Waiting for clip selection...")
        if hasattr(self.ui, 'label_location'):
            self.ui.label_location.setText("Output: -")
            
        # 5. Hard-Block the Render Button
        if hasattr(self.ui, 'btn_start'):
            self.ui.btn_start.setEnabled(False)