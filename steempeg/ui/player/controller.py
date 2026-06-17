"""Video playback and the player surface, mixed into the main application.

These methods drive the mpv-backed player: opening and closing clips, play/pause,
volume and speed, the timeline and trim controls, fullscreen/theatre mode,
screenshots and markers. They run on the application instance and reach its widgets
and player through self.
"""
from PySide6.QtGui import QIcon, QPixmap

from steempeg.infra.paths import get_resource_path


class PlayerMixin:
    def close_current_clip(self):
        """ Completely destroys the current clip and clears the interface. """
        if getattr(self, '_is_switching', False):
            return

        self._force_pause = True
        
        # 1. STOP THE PLAYER
        if hasattr(self, 'player') and self.player:
            self.player.pause = True
            try:
                self.player.stop()
                self.player.play("")
            except:
                pass
                
        
        # 2. Clearing the Player Interface and Cache
        if hasattr(self.ui, 'video_container'):
            self.ui.video_container.setStyleSheet("background-color: transparent; border: none;")
            
        if hasattr(self, 'custom_timeline'):
            if hasattr(self.custom_timeline, 'preview_widget'):
                self.custom_timeline.preview_widget.hide()
            if hasattr(self.custom_timeline, 'img_label'):
                self.custom_timeline.img_label.setPixmap(QPixmap()) 
            self.custom_timeline.thumb_dir = None
            self.custom_timeline.current_video_path = None
            if hasattr(self.custom_timeline, 'sniper'):
                self.custom_timeline.sniper.video_path = None
                if hasattr(self.custom_timeline.sniper, 'cache'):
                    self.custom_timeline.sniper.cache.clear()

            self.custom_timeline.set_vlc_time(0, False)
            self.custom_timeline.setEnabled(False)
            self.custom_timeline.set_duration(0)
            self.custom_timeline.force_jump(0)
            self.custom_timeline.canvas.markers.clear()
            self.custom_timeline.canvas.update()

        # 3. Resetting the Table and Grid
        if hasattr(self.ui, 'table_clips'):
            self.ui.table_clips.blockSignals(True)
            self.ui.table_clips.clearSelection()
            self.ui.table_clips.blockSignals(False)
        if hasattr(self, 'grid_clips'):
            self.grid_clips.blockSignals(True)
            self.grid_clips.clearSelection()
            self.grid_clips.blockSignals(False)
            
        # 4. Restoring the Player Placeholder and Header Text
        if hasattr(self, 'video_stack') and hasattr(self, 'placeholder_frame'):
            self.video_stack.setCurrentWidget(self.placeholder_frame)
            
        if hasattr(self, 'btn_close_clip'):
            self.btn_close_clip.hide()
        if hasattr(self, 'custom_text_label'):
            self.custom_text_label.setText("Select a clip to preview...")
        if hasattr(self, 'custom_icon_label'):
            self.custom_icon_label.setPixmap(QIcon(get_resource_path("unknown_icon.png")).pixmap(24, 24))
            
        # 5. Resetting the Time and the PLAY Button
        if hasattr(self.ui, 'label_time'):
            self.ui.label_time.setText("00:00 / 00:00")
            
        if hasattr(self.ui, 'btn_play'):
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))

        # 6. GLOBAL WIPE OF ALL SETTINGS TABS (UI WIPE)
        # clean the Source Info tab
        if hasattr(self.ui, 'source_label'): self.ui.source_label.setText("Source: -")
        if hasattr(self.ui, 'orig_res_label'): self.ui.orig_res_label.setText("Original resolution: -")
        if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate: -")
        if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate: -")
        if hasattr(self.ui, 'label_size'): self.ui.label_size.setText("Size: -")
        if hasattr(self.ui, 'label_duration'): self.ui.label_duration.setText("Time: -")
        if hasattr(self.ui, 'label_fps'): self.ui.label_fps.setText("FPS: -")

        # Hiding Copy Buttons
        if hasattr(self, 'btn_copy_src'): self.btn_copy_src.hide()
        if hasattr(self, 'btn_copy_loc'): self.btn_copy_loc.hide()

        # Cleaning Up Lists
        def clear_combo(name):
            if hasattr(self.ui, name):
                w = getattr(self.ui, name)
                w.blockSignals(True)
                w.clear()
                w.blockSignals(False)
                
        clear_combo('combo_quality')
        clear_combo('combo_fps')
        clear_combo('combo_bitrate')
        clear_combo('combo_audio_bitrate')

        # Hide the size slider
        if hasattr(self.ui, 'size_slider'): self.ui.size_slider.hide()
        if hasattr(self, 'size_container'): self.size_container.hide()

        # Clean Export Settings
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
            
        # We're locking down the render button
        if hasattr(self.ui, 'btn_start'):
            self.ui.btn_start.setEnabled(False)
            
    


    # VIDEO PLAYER CONTROLS
    def toggle_play(self):
        """ Toggles Play/Pause state in MPV and updates the button icon. """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): return
        if getattr(self.player, 'path', None) is None: return

        self.player.pause = not self.player.pause
        if hasattr(self.ui, 'btn_play'):
            icon_path = get_resource_path("icon_play.png") if self.player.pause else get_resource_path("icon_pause.png")
            self.ui.btn_play.setIcon(QIcon(icon_path))
                
    def set_vlc_volume(self, value):
        """ Passes the volume value to MPV with a perceptual logarithmic curve for human hearing """
        if hasattr(self, 'player') and self.player:
            if value > 0:
                perceived_volume = (value / 100.0) ** 0.5 * 100.0
            else:
                perceived_volume = 0.0
                
            self.player.volume = perceived_volume
    def set_vlc_speed(self, value):
        """ Passes the speed value to MPV (MPV handles pitch correction automatically) """
        if hasattr(self, 'player') and self.player:
            # Convert 5..30 back to 0.5..3.0
            speed_float = value / 10.0
            self.player.speed = speed_float