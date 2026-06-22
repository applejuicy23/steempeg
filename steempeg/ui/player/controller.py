"""Video playback and the player surface, mixed into the main application.

These methods drive the mpv-backed player: opening and closing clips, play/pause,
volume and speed, the timeline and trim controls, fullscreen/theatre mode,
screenshots and markers. They run on the application instance and reach its widgets
and player through self.
"""
import json
import os
import re
import time
from datetime import datetime

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QIcon, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QSizePolicy,
    QToolTip,
)

from steempeg.infra.paths import get_resource_path, get_save_directory
from steempeg.ui.player.thumbnails import ThumbnailBatchThread


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
        if hasattr(self, 'update_playback_badge'):
            self.update_playback_badge()
            
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

    def toggle_theater_mode(self):
        """ Safely collapses side and bottom panels, aware of Fullscreen state, and swaps icon. """
        
        if getattr(self, 'is_fullscreen', False):
            self.toggle_fullscreen() 
            
        self.is_theater = not getattr(self, 'is_theater', False)
        
        if hasattr(self.ui, 'left_panel'):
            self.ui.left_panel.setVisible(not self.is_theater)
        else:
            if hasattr(self.ui, 'table_clips'):
                left_wrapper = self.ui.table_clips.parentWidget()
                if left_wrapper and "Splitter" not in type(left_wrapper).__name__ and left_wrapper.objectName() != "centralwidget":
                    left_wrapper.setVisible(not self.is_theater)
                else:
                    self.ui.table_clips.setVisible(not self.is_theater)

        if hasattr(self, 'mega_top_pill'):
            self.mega_top_pill.setVisible(not self.is_theater)
        elif hasattr(self.ui, 'mega_top_pill'):
            self.ui.mega_top_pill.setVisible(not self.is_theater)

        if hasattr(self, 'library_views_container'):
            self.library_views_container.setVisible(not self.is_theater)
        elif hasattr(self.ui, 'library_views_container'):
            self.ui.library_views_container.setVisible(not self.is_theater)

        if hasattr(self.ui, 'main_splitter'):
            self.ui.main_splitter.handle(1).setVisible(not self.is_theater)

        if hasattr(self, 'bottom_v_wrap'):
            self.bottom_v_wrap.setVisible(not self.is_theater)

        # Hiding new settings panels
        if hasattr(self.ui, 'settings_tabs'):
            self.ui.settings_tabs.setVisible(not self.is_theater)
        if hasattr(self, 'neo_wrapper'):
            self.neo_wrapper.setVisible(not self.is_theater)
            
        # Hiding the new render block
        if hasattr(self.ui, 'btn_start'):
            bottom_wrapper = self.ui.btn_start.parentWidget()
            if bottom_wrapper and "Splitter" not in type(bottom_wrapper).__name__ and bottom_wrapper.objectName() != "centralwidget":
                bottom_wrapper.setVisible(not self.is_theater)
        if hasattr(self, 'render_dashboard'):
            self.render_dashboard.setVisible(not self.is_theater)
        if hasattr(self, 'render_queue_panel'):
            self.render_queue_panel.setVisible(not self.is_theater)
        if hasattr(self, 'right_h_splitter') and self.is_theater:
            sizes = self.right_h_splitter.sizes()
            total = sum(sizes) if sum(sizes) > 0 else 1
            self.right_h_splitter.setSizes([total, 0])

        if hasattr(self, 'btn_refresh'):
            browse_wrapper = self.btn_refresh.parentWidget()
            if browse_wrapper: browse_wrapper.setVisible(not self.is_theater)
            
        if hasattr(self.ui, 'btn_about'): self.ui.btn_about.setVisible(not self.is_theater)
        if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.setVisible(not self.is_theater)

        # Set the background to black and remove the 10px splitter offset.
        if hasattr(self, 'video_wrapper'):
            bg_color = "black" if self.is_theater else "transparent"
            self.video_wrapper.setStyleSheet(f"background-color: {bg_color}; border: none;")
            
        if hasattr(self, 'top_v_wrap') and self.top_v_wrap.layout():
            margin_bottom = 0 if self.is_theater else 10
            self.top_v_wrap.layout().setContentsMargins(0, 0, 0, margin_bottom)
                
        # --- THE MAGIC SWAP ---
        if hasattr(self, 'btn_theater'):
            if self.is_theater:
                icon_path = get_resource_path("theatremodeclosed.png")
                if not os.path.exists(icon_path): icon_path = get_resource_path("theatremodeclosed.jpg")
                
                if os.path.exists(icon_path):
                    self.btn_theater.setIcon(QIcon(icon_path))
                else:
                    self.btn_theater.setText("❌")
            else:
                icon_path = get_resource_path("theatremode.png")
                if os.path.exists(icon_path):
                    self.btn_theater.setIcon(QIcon(icon_path))
                else:
                    self.btn_theater.setText("🎦") 
            
            self.btn_theater.clearFocus()
            QApplication.postEvent(self.btn_theater, QEvent(QEvent.Type.Leave))

        if not self.is_theater and hasattr(self, '_sync_queue_splitter_visibility'):
            self._sync_queue_splitter_visibility()
    def toggle_fullscreen(self):
        """ Completely isolates the video container with Anti-Spam Lock & Black Background """
        
        if getattr(self, 'fullscreen_lock', False): return
        self.fullscreen_lock = True
        

        QTimer.singleShot(700, lambda: setattr(self, 'fullscreen_lock', False))

        self.is_fullscreen = not getattr(self, 'is_fullscreen', False)
        
        if self.is_fullscreen:
            # --- ENTERING TRUE FULLSCREEN ---
            self.window_maximized_before = self.ui.isMaximized()

            if not getattr(self, 'needs_geometry_restore', False):
                self.true_normal_geom = self.ui.normalGeometry()
            
            if getattr(self, 'is_theater', False):
                self.is_theater = False
                if hasattr(self, 'btn_theater'):
                    icon_path = get_resource_path("theatremode.png")
                    if os.path.exists(icon_path):
                        self.btn_theater.setIcon(QIcon(icon_path))
                    else:
                        self.btn_theater.setText("🎦")
            
            # Hide ALL old and NEW panels
            if hasattr(self.ui, 'left_panel'): self.ui.left_panel.hide()
            if hasattr(self, 'mega_top_pill'): self.mega_top_pill.hide()
            if hasattr(self, 'library_views_container'): self.library_views_container.hide()
            if hasattr(self.ui, 'settings_tabs'): self.ui.settings_tabs.hide()
            if hasattr(self, 'neo_wrapper'): self.neo_wrapper.hide()
            if hasattr(self.ui, 'frame_status'): self.ui.frame_status.hide()
            if hasattr(self, 'player_header_frame'): self.player_header_frame.hide()
            if hasattr(self, 'render_dashboard'): self.render_dashboard.hide() 
            
            if hasattr(self.ui, 'btn_start'):
                bw = self.ui.btn_start.parentWidget()
                if bw and "Splitter" not in type(bw).__name__ and bw.objectName() != "centralwidget": bw.hide()
            if hasattr(self, 'btn_refresh'):
                rw = self.btn_refresh.parentWidget()
                if rw: rw.hide()
            if hasattr(self.ui, 'btn_about'): self.ui.btn_about.hide()
            if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.hide()

            if hasattr(self.ui, 'main_splitter'):
                self.ui.main_splitter.handle(1).hide()
            if hasattr(self, 'main_v_splitter'):
                self.main_v_splitter.handle(1).hide()
            
            if hasattr(self, 'bottom_v_wrap'): 
                self.bottom_v_wrap.hide()
            
            # Collapse the 10px margin that the splitter had
            if hasattr(self, 'top_v_wrap') and self.top_v_wrap.layout():
                self.top_v_wrap.layout().setContentsMargins(0, 0, 0, 0)
                
            # Set the background to black (removes gray bars at the edges of the video)
            if hasattr(self, 'video_wrapper'):
                self.video_wrapper.setStyleSheet("background-color: black; border: none;")
            
            main_layout = self.ui.layout()
            if main_layout:
                self.original_main_margins = main_layout.contentsMargins()
                main_layout.setContentsMargins(0, 0, 0, 0)
                
            right_layout = self.ui.right_panel.layout()
            if right_layout:
                self.original_right_margins = right_layout.contentsMargins()
                self.original_right_spacing = right_layout.spacing()
                right_layout.setContentsMargins(0, 0, 0, 0)
                right_layout.setSpacing(0)

            self.ui.showFullScreen()

            self.player_footer_frame.setParent(self.ui)
            self.player_footer_frame.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            
            self.player_footer_frame.setObjectName("HudFrame")
            self.player_footer_frame.setStyleSheet("""
                QFrame#HudFrame { 
                    background-color: rgba(25, 25, 25, 200); 
                    border-radius: 16px; 
                    border: none;
                }
                QFrame#HudFrame QPushButton, QFrame#HudFrame QToolButton {
                    background-color: transparent;
                    border: none;
                }
            """)
            self.player_footer_frame.show()
            self.player_footer_frame.raise_()

            if hasattr(self, 'wake_up_fullscreen_controls'):
                self.wake_up_fullscreen_controls()

            QTimer.singleShot(50, self.align_fullscreen_hud)
            
        else:
            # --- EXITING FULLSCREEN ---
            if hasattr(self, 'fs_timer'): 
                self.fs_timer.stop()
            self.ui.setCursor(Qt.ArrowCursor) 
            
            is_t = getattr(self, 'is_theater', False)
            
            # Restoring panel visibility
            if hasattr(self.ui, 'left_panel'): self.ui.left_panel.setVisible(not is_t)
            if hasattr(self, 'mega_top_pill'): self.mega_top_pill.setVisible(not is_t)
            if hasattr(self, 'library_views_container'): self.library_views_container.setVisible(not is_t)
            if hasattr(self.ui, 'settings_tabs'): self.ui.settings_tabs.setVisible(not is_t)
            if hasattr(self, 'neo_wrapper'): self.neo_wrapper.setVisible(not is_t) 
            if hasattr(self.ui, 'frame_status'): self.ui.frame_status.setVisible(not is_t)
            if hasattr(self, 'bottom_v_wrap'): 
                self.bottom_v_wrap.setVisible(not is_t)
            if hasattr(self, 'render_dashboard'): self.render_dashboard.setVisible(not is_t)
            
            if hasattr(self.ui, 'btn_start'):
                bw = self.ui.btn_start.parentWidget()
                if bw and "Splitter" not in type(bw).__name__ and bw.objectName() != "centralwidget": bw.setVisible(not is_t)
            if hasattr(self, 'btn_refresh'):
                rw = self.btn_refresh.parentWidget()
                if rw: rw.setVisible(not is_t)
            if hasattr(self.ui, 'btn_about'): self.ui.btn_about.setVisible(not is_t)
            if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.setVisible(not is_t)

            if hasattr(self, 'player_header_frame'): self.player_header_frame.show()
            if hasattr(self.ui, 'main_splitter'): self.ui.main_splitter.handle(1).setVisible(not is_t)
            if hasattr(self, 'main_v_splitter'): 
                self.main_v_splitter.handle(1).setVisible(not is_t)
            
            # Restoring margins and transparent background
            if hasattr(self, 'top_v_wrap') and self.top_v_wrap.layout():
                margin_bottom = 0 if is_t else 10
                self.top_v_wrap.layout().setContentsMargins(0, 0, 0, margin_bottom)
            if hasattr(self, 'video_wrapper'):
                self.video_wrapper.setStyleSheet("background-color: transparent; border: none;")
            
            main_layout = self.ui.layout()
            if main_layout and hasattr(self, 'original_main_margins'):
                main_layout.setContentsMargins(self.original_main_margins)

            right_layout = self.ui.right_panel.layout()
            if right_layout and hasattr(self, 'original_right_margins'):
                right_layout.setContentsMargins(self.original_right_margins)
                right_layout.setSpacing(getattr(self, 'original_right_spacing', 8))

            self.player_footer_frame.setWindowFlags(Qt.Widget)
            self.player_footer_frame.setAttribute(Qt.WA_TranslucentBackground, False)
            self.player_footer_frame.setParent(self.ui.right_panel)
            self.player_footer_frame.clearMask()
            
            self.player_footer_frame.setMinimumWidth(0)
            self.player_footer_frame.setMaximumWidth(16777215)
            
            self.player_footer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

            idx = getattr(self, 'controls_layout_index', -1)
            v_container = getattr(self.ui, 'video_container', None)
            
            def snap_to_cage():
                if v_container:
                    v_container.setMinimumSize(1, 1)
                    v_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                    v_container.updateGeometry()
                    parent = v_container.parentWidget()
                    if parent and parent.layout():
                        parent.layout().activate()
                        
            QTimer.singleShot(50, snap_to_cage)

            target_layout = getattr(self, 'top_v_wrap', self.ui.right_panel).layout()
            if target_layout and idx >= 0:
                target_layout.insertWidget(idx, self.player_footer_frame)
            else:
                if target_layout: target_layout.addWidget(self.player_footer_frame)

            self.player_footer_frame.setObjectName("HudFrame")
            self.player_footer_frame.setStyleSheet("QFrame#HudFrame { background-color: #2d2d2d; border-radius: 6px; border: none; }")
            self.player_footer_frame.show()
            
            if right_layout: right_layout.activate()

            if hasattr(self, 'btn_fullscreen'):
                self.btn_fullscreen.clearFocus()
                QApplication.postEvent(self.btn_fullscreen, QEvent(QEvent.Type.Leave))
            if hasattr(self, 'btn_theater'):
                self.btn_theater.clearFocus()
                QApplication.postEvent(self.btn_theater, QEvent(QEvent.Type.Leave))

            if getattr(self, 'window_maximized_before', False):
                screen_geom = self.ui.screen().availableGeometry()
                self.ui.setMinimumSize(screen_geom.size())
                self.ui.showNormal()
                self.ui.move(screen_geom.topLeft())
                self.ui.showMaximized()
                self.ui.setMinimumSize(1000, 650)
                self.needs_geometry_restore = True
            else:
                self.ui.showNormal()
                self.ui.setMinimumSize(1000, 600)
                if hasattr(self, 'true_normal_geom'):
                    self.ui.setGeometry(self.true_normal_geom)

    
    def align_fullscreen_hud(self):
        """ Calculates global coordinates and aligns the floating panel. """
        if not getattr(self, 'is_fullscreen', False) or not hasattr(self, 'player_footer_frame'):
            return
            
        
        w = self.ui.width()
        h = self.ui.height()
        footer_h = self.player_footer_frame.sizeHint().height()
        
        # Get the global coordinates of the window itself.
        global_pos = self.ui.mapToGlobal(self.ui.rect().topLeft())
        
        hud_w = w - 80
        hud_x = global_pos.x() + 40
        hud_y = global_pos.y() + h - footer_h - 15
        
        # Place the glass shard exactly in the center.
        self.player_footer_frame.setGeometry(hud_x, hud_y, hud_w, footer_h)
        
        #Applying the Rounding Mask
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(hud_w), float(footer_h), 16.0, 16.0)
        region = QRegion(path.toFillPolygon().toPolygon())
        self.player_footer_frame.setMask(region)
    def hide_hud_on_minimize(self, state):
        
       # This matters to us ONLY if we are in fullscreen mode.
        if not getattr(self, 'is_fullscreen', False):
            return
            
        # If the program was minimized (Win+D) or you switched to another window (Alt-Tab)
        if state != Qt.ApplicationState.ApplicationActive:
            if hasattr(self, 'player_footer_frame'):
                self.player_footer_frame.hide()
        
        # If you switched away from the app and returned to it
        else:
            if hasattr(self, 'player_footer_frame'):
                self.player_footer_frame.show()
                # Force-wake the panel so it doesn't end up in a coma!
                if hasattr(self, 'wake_up_fullscreen_controls'):
                    self.wake_up_fullscreen_controls()

    def wake_up_fullscreen_controls(self):
        """ Restores mouse arrow visibility and maps HUD controls layer on motion. """
        
        if not getattr(self, 'is_fullscreen', False): 
            return
            
        # If the program is minimized (Win+D) or we are currently Alt-Tabbing, completely ignore any mouse attempts to wake up the interface!
        if QApplication.instance().applicationState() != Qt.ApplicationState.ApplicationActive:
            return
        
        self.ui.setCursor(Qt.ArrowCursor) 
        if hasattr(self, 'player_footer_frame'):
            self.player_footer_frame.show()   
        self.fs_timer.start()           

    def sleep_fullscreen_controls(self):
        """ Completely terminates cursor rendering and hides controls layer after 3 seconds of stagnation. """
        if not getattr(self, 'is_fullscreen', False): return
        
        if hasattr(self, 'player_footer_frame') and self.player_footer_frame.underMouse():
            self.fs_timer.start() 
            return
            
        self.ui.setCursor(Qt.BlankCursor) 
        if hasattr(self, 'player_footer_frame'):
            self.player_footer_frame.hide()   
        
        QToolTip.hideText()

    def keyPressEvent(self, event):
        """ Captures keyboard events. Exits fullscreen seamlessly if Escape key is pressed. """
        if event.key() == Qt.Key_Escape and getattr(self, 'is_fullscreen', False):
            self.toggle_fullscreen()
            event.accept()
        else:
            super().keyPressEvent(event)

    def toggle_trim_state(self):
        """ Toggles between Trim mode and Normal mode seamlessly without interrupting playback """
        if not hasattr(self, 'custom_timeline'): return

        if self.custom_timeline.is_trim_mode:
            # TURN OFF TRIM MODE
            self.custom_timeline.disable_trim_mode()
            
            # Hide border on aspect_frame
            if hasattr(self, 'aspect_frame'):
                self.aspect_frame.setStyleSheet("border: 3px solid transparent; background-color: transparent;")
            
            # Hide the interactive border instantly
            if hasattr(self, 'video_overlay'):
                self.video_overlay.show_border = False
                self.video_overlay.update()

            if hasattr(self, 'border_overlay'):
                self.border_overlay.setStyleSheet("border: 3px solid #ffcc00; background-color: transparent;")
            
            # Restore to default Trim button with custom scissors icon...
            trim_icon_path = get_resource_path("trim_icon.png")
            if os.path.exists(trim_icon_path):
                self.btn_trim.setIcon(QIcon(trim_icon_path))
                self.btn_trim.setText(" Trim")
            else:
                self.btn_trim.setIcon(QIcon())
                self.btn_trim.setText("✂️ Trim")
                
            # Restore the slightly golden premium style
            self.btn_trim.setStyleSheet("background-color: #cfa94a; color: black; border-radius: 15px; padding: 0 12px; font-weight: bold;")
            

            if hasattr(self, 'aspect_frame'):
                self.aspect_frame.setStyleSheet("background-color: transparent;")
            if hasattr(self, 'trim_tools_pill'):
                self.trim_tools_pill.hide()
        else:
            # TURN ON TRIM MODE
            self.custom_timeline.enable_trim_mode()
            
            # Transform into Cancel button with custom cancel icon
            cancel_icon_path = get_resource_path("cancel.png")
            if os.path.exists(cancel_icon_path):
                self.btn_trim.setIcon(QIcon(cancel_icon_path))
                self.btn_trim.setText(" Cancel")
            else:
                self.btn_trim.setIcon(QIcon()) 
                self.btn_trim.setText("❌ Cancel")
                
            # Apply the red danger style
            self.btn_trim.setStyleSheet("background-color: #ff4444; color: white; border-radius: 15px; padding: 0 12px; font-weight: bold;")

            if hasattr(self, 'trim_tools_pill'):
                self.trim_tools_pill.show()
        # --- FORCE UI REFRESH ON TOGGLE ---
        self.update_final_setup()
        if hasattr(self.ui, 'combo_quality') and "Target File Size" in self.ui.combo_quality.currentText():
            self.setup_dynamic_slider()
    def set_trim_start_to_playhead(self):
        """ Sets the left end of the yellow strip with a UNO REVERSAL. """
        if not hasattr(self, 'custom_timeline'): return
        canvas = self.custom_timeline.canvas
        pos = canvas.visual_ms
        old_start = canvas.trim_start_ms
        old_end = canvas.trim_end_ms
        duration = old_end - old_start
        
        if pos >= old_end:
            # UNO CARD! The scroller is positioned *after* the end. 
            # We shift the entire segment as a whole: the scroller becomes the new start, and the end point flies further out! 
            canvas.trim_start_ms = pos
            canvas.trim_end_ms = min(pos + duration, canvas.duration_ms)
        else:

            canvas.trim_start_ms = pos
            
        self.custom_timeline.trim_changed.emit(int(canvas.trim_start_ms), int(canvas.trim_end_ms))
        canvas.update()

    def set_trim_end_to_playhead(self):
        """ Sets the right end of the yellow strip with a U-turn. """
        if not hasattr(self, 'custom_timeline'): return
        canvas = self.custom_timeline.canvas
        pos = canvas.visual_ms
        old_start = canvas.trim_start_ms
        old_end = canvas.trim_end_ms
        duration = old_end - old_start
        
        if pos <= old_start:
            # UNO CARD! The scroller is positioned before the start. 
            # We shift the entire chunk: the scroller becomes the new end, while the original start flies backward!
            canvas.trim_end_ms = pos
            canvas.trim_start_ms = max(pos - duration, 0.0)
        else:
            # Standard Click
            canvas.trim_end_ms = pos
            
        self.custom_timeline.trim_changed.emit(int(canvas.trim_start_ms), int(canvas.trim_end_ms))
        canvas.update()

    def jump_to_trim_start(self):
        """ Simply teleports the scroller back to the start of the clipping. """
        if not hasattr(self, 'custom_timeline'): return
        self.custom_timeline.force_jump(self.custom_timeline.trim_start_ms)

    def on_timeline_press(self):
        """ Triggered when the user clicks on the timeline track. """
        if hasattr(self, 'player') and self.player:
            # Check if video is playing (if pause is False, it means it is playing)
            self.was_playing_before_drag = not self.player.pause
            
            # Pause the video while the user is dragging the playhead
            self.player.pause = True

    def on_timeline_seek(self, position_ms):
        """ Commands MPV to jump. """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): 
            return
            
        if hasattr(self, 'player') and self.player:
            if getattr(self.player, 'duration', None):
                self.player.seek(position_ms / 1000.0, reference='absolute', precision='exact')


    def on_timeline_release(self):
        """ Triggered when the user releases the mouse button after dragging. """
        if hasattr(self, 'player') and self.player:
            
            # Restore playback state if it was playing before we clicked
            if getattr(self, 'was_playing_before_drag', False):
                self.player.pause = False
                
            # If you have a variable 'is_muted' in your scope, apply it to MPV like this:
            # (Replace the old audio_set_mute line with this one)
            if hasattr(self, 'is_muted'):
                self.player.mute = self.is_muted

    def skip_backward(self):
        """ Rewind 15 seconds using the Independent Timeline Engine """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): return
        new_time = self.custom_timeline.visual_ms - 15000
        self.custom_timeline.force_jump(new_time)

    def skip_forward(self):
        """ Skips 15 seconds forward using the Independent Timeline Engine """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): return
        new_time = self.custom_timeline.visual_ms + 15000
        self.custom_timeline.force_jump(new_time)

    def skip_back(self):
        """ Skips 15 seconds backward using the Independent Timeline Engine """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): return
        new_time = self.custom_timeline.visual_ms - 15000
        self.custom_timeline.force_jump(new_time)
        

    def get_effective_duration(self):
        """ Calculates the real duration of the video. If Trim is active, returns only the trimmed part! """
        if hasattr(self, 'custom_timeline') and self.custom_timeline.is_trim_mode:
            # Return duration of the yellow bar
            return max(0.1, (self.custom_timeline.trim_end_ms - self.custom_timeline.trim_start_ms) / 1000.0)
        return getattr(self, 'current_clip_duration_sec', 0)

    def on_trim_changed(self, start_ms, end_ms):
        """ Fires instantly when the user drags the yellow trim handles """
        # 1. Update text info in Export Settings
        self.update_final_setup()
        
        # 2. Recalculate slider sizes because shorter video = less Megabytes!
        if hasattr(self.ui, 'combo_quality') and "Target File Size" in self.ui.combo_quality.currentText():
            self.setup_dynamic_slider()

    def generate_and_play_preview(self):
        """ Instantly loads and plays the Steam .mpd playlist using MPV. No proxy needed! """ 
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            return

        # 1. STOP CURRENT PLAYBACK
        self._is_switching = True
        self._force_pause = False

        
        # 2. GET THE CLIP FOLDER PATH
        clip_path = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).data(Qt.UserRole)
        
        # STEP 1: FIND THE VIDEO FOLDER
        all_mpds = self.get_all_mpd_paths(clip_path)
        if not all_mpds: 
            return

        mpd_path = all_mpds[0] 

        # STEP 2: AUTO-SEARCH JSON TIMELINE
        # STEP 2: AUTO-SEARCH JSON TIMELINE
        offset_ms = 0
        
        def find_json_in_dir(directory):
            if not directory or not os.path.isdir(directory): 
                return None
            # Searching for the Right Timeline
            for root_dir, dirs, files in os.walk(directory):
                for file in files:
                    if file.startswith("timeline_") and file.endswith(".json"):
                        return os.path.join(root_dir, file)
            # Backup Option
            for root_dir, dirs, files in os.walk(directory):
                for file in files:
                    if file.endswith(".json") and "settings" not in file and "games" not in file:
                        return os.path.join(root_dir, file)
            return None

        # 1. Search strictly within the clip's own folder!
        json_path = find_json_in_dir(clip_path)

        # 2. If the clip is in the standard Steam folder (video/fg_123), look in the adjacent folder: timelines/fg_123.
        if not json_path:
            parent_dir = os.path.dirname(clip_path)
            if os.path.basename(parent_dir).lower() == "video":
                timelines_dir = os.path.join(os.path.dirname(parent_dir), "timelines")
                clip_folder_name = os.path.basename(clip_path)
                json_path = find_json_in_dir(os.path.join(timelines_dir, clip_folder_name))

        # 3. Passing to the Engine
        if hasattr(self, 'custom_timeline'):
            if json_path:
                print(f"Json was found successfully: {json_path}")
                
                json_name = os.path.basename(json_path) 
                video_folder_name = os.path.basename(os.path.dirname(mpd_path))
                
                json_match = re.search(r'(\d{8})_(\d{6})', json_name)
                video_match = re.search(r'(\d{8})_(\d{6})', video_folder_name)
                
                if json_match and video_match:
                    try:
                        j_str = json_match.group(1) + json_match.group(2)
                        v_str = video_match.group(1) + video_match.group(2)
                        
                        json_dt = datetime.strptime(j_str, "%Y%m%d%H%M%S")
                        video_dt = datetime.strptime(v_str, "%Y%m%d%H%M%S")
                        
                        offset_ms = int((video_dt - json_dt).total_seconds() * 1000)
                    except Exception as e:
                        print(f"Time Count Error: {e}")
                        offset_ms = 0
                        
                print(f"Delay: {offset_ms} ms")
                self.custom_timeline.canvas.load_timeline_json(json_path, offset_ms)
                
            else:
                print(f"No JSON found for this clip: {clip_path}")
                self.custom_timeline.canvas.markers.clear()
                self.custom_timeline.canvas.update()


        # 3. PREPARE THE CANVAS
        self.ui.video_container.setStyleSheet("background-color: transparent;")
        if hasattr(self, 'video_stack'): 
            self.video_stack.setCurrentWidget(self.ui.video_container)
        if hasattr(self, 'btn_close_clip'): 
            self.btn_close_clip.show()
        if hasattr(self, 'update_playback_badge'):
            self.update_playback_badge()
        if hasattr(self, 'custom_timeline'): 
            self.custom_timeline.setEnabled(True)

        # 4. FEED THE RAW STEAM DASH FILE DIRECTLY TO MPV
        print(f"---> Feeding MPD directly to MPV: {mpd_path}")
        
        # A Reliable Path for Windows:
        abs_path = os.path.abspath(mpd_path).replace('\\', '/')
        
        # Start the video and unpause it.
        self.player.play(abs_path) 
        self.player.pause = False

        # --- BACKGROUND THUMBNAIL BATCH GENERATION (THE MATRIX 2.0) ---
        if hasattr(self, 'thumb_thread') and self.thumb_thread.isRunning():
            self.thumb_thread.stop()
            
        # Launch the Batch Generator
        self.thumb_thread = ThumbnailBatchThread(abs_path, self.current_clip_duration_sec, interval=3)
        
        if hasattr(self, 'custom_timeline'):
            self.custom_timeline.thumb_dir = self.thumb_thread.thumb_dir
            self.custom_timeline.current_video_path = abs_path
            
            # A function that removes the shield and activates the timeline
            def finish_switch():
                self.custom_timeline.setEnabled(True)
                self._is_switching = False 
                
            QTimer.singleShot(500, finish_switch)
                
        self.thumb_thread.start()

        # --- IMMEDIATELY UPDATE PLAY BUTTON ICON TO PAUSE ---
        if hasattr(self.ui, 'btn_play'):
            icon_path = get_resource_path("icon_pause.png")
            self.ui.btn_play.setIcon(QIcon(icon_path))
        

    def update_ui_from_vlc(self):
        """ Updates UI and Timeline from MPV engine """
        if not hasattr(self, 'player') or not self.player:
            return
            
        # If the strip is off, prevent the timer from toggling it!
        if hasattr(self, 'custom_timeline') and not self.custom_timeline.isEnabled():
            return

        # Safe check to prevent jumpiness after seeking
        if time.time() < getattr(self, '_ignore_vlc_until', 0):
            return

        try:
            duration_sec = getattr(self, 'current_clip_duration_sec', self.player.duration)
            if duration_sec is None or duration_sec <= 0:
                duration_sec = self.player.duration
                if duration_sec is None: return
                
            time_sec = self.player.time_pos
            

            current_dw = getattr(self.player, 'dwidth', None)
            if current_dw != getattr(self, '_last_video_width', None):
                self._last_video_width = current_dw
                if hasattr(self, 'recalculate_video_geometry'):
                    self.recalculate_video_geometry()
            
            # If duration is missing, the video is not fully loaded yet
            if duration_sec is None:
                return
                
            duration_ms = int(duration_sec * 1000)
            
            # MPV sometimes returns None for time_pos at the exact moment the video ends
            if time_sec is None:
                if getattr(self.player, 'eof_reached', False):
                    time_sec = duration_sec 
                else:
                    return
                    
            current_ms = int(time_sec * 1000)

            # --- AUTO-REWIND AT THE END OF VIDEO (EOF) ---
            # If MPV flags end-of-file, or we are within 100ms of the end
            if getattr(self.player, 'eof_reached', False) or current_ms >= duration_ms - 5:
                self.player.pause = True 
                self.player.seek(0, reference='absolute', precision='exact') 
                current_ms = 0 
                
                if hasattr(self, 'custom_timeline'):
                    self.custom_timeline.force_jump(0)
                    
                # Change the pause button back to play
                if hasattr(self.ui, 'btn_play'):
                    icon_path = get_resource_path("icon_play.png")
                    self.ui.btn_play.setIcon(QIcon(icon_path))

            is_playing = not self.player.pause

            # Send the data to our smooth custom timeline
            if hasattr(self, 'custom_timeline'):
                self.custom_timeline.set_duration(duration_ms)
                self.custom_timeline.set_vlc_time(current_ms, is_playing)

            # --- UPDATE TEXT TIMERS (00:00 / 00:00) ---
            def format_time(ms):
                """ Converts milliseconds into HH:MM:SS or MM:SS format """
                s = ms // 1000
                h = s // 3600
                m = (s % 3600) // 60 
                s = s % 60
                
                if h > 0:
                    return f"{h:02d}:{m:02d}:{s:02d}"
                return f"{m:02d}:{s:02d}"
            
            # --- YELLOW BORDER INDICATOR ---
            if getattr(self, 'is_fullscreen', False):
                if hasattr(self, 'aspect_frame'):
                    self.aspect_frame.setStyleSheet("border: 3px solid transparent; background-color: transparent;")
            else:
                if hasattr(self, 'custom_timeline') and self.custom_timeline.is_trim_mode:
                    if self.custom_timeline.trim_start_ms <= current_ms <= self.custom_timeline.trim_end_ms:
                        if hasattr(self, 'aspect_frame'):
                            # Draw perfect yellow border
                            self.aspect_frame.setStyleSheet("border: 3px solid #ffcc00; background-color: transparent;")
                    else:
                        if hasattr(self, 'aspect_frame'):
                            # Remove border
                            self.aspect_frame.setStyleSheet("border: 3px solid transparent; background-color: transparent;")
                else:
                    if hasattr(self, 'aspect_frame'):
                        # Remove border
                        self.aspect_frame.setStyleSheet("border: 3px solid transparent; background-color: transparent;")

            # --- UPDATE TEXT TIMERS (00:00 / 00:00) ---

            # Update the main timer label
            # Check if your specific UI label exists and update it ONLY if the text changed!
            if hasattr(self.ui, 'label_time'):
                current_str = format_time(current_ms)
                total_str = format_time(duration_ms)
                new_time_text = f"{current_str} / {total_str}"
                
                # Prevent UI lag by updating text only once per second
                if self.ui.label_time.text() != new_time_text:
                    self.ui.label_time.setText(new_time_text)
        except Exception as e:
            pass # Ignore random missing property errors during video switching

    def add_user_marker(self, target_ms=None):
        """ Sets a tag according to Gaben's GOST standard and saves it to JSON. """
        
        if not hasattr(self, 'custom_timeline'): return
        canvas = self.custom_timeline.canvas
        
        markers_list = getattr(canvas, 'markers', None)
        if markers_list is None: return

        # FIX: The "clicked" signal of QPushButton passes a boolean (False). 
        # We must ignore it so the marker doesn't fly to 0:00!
        if isinstance(target_ms, bool) or target_ms is None:
            current_time = int(canvas.visual_ms)
        else:
            current_time = int(target_ms)
            
        for m in markers_list:
            if m.get('time_ms', -1) == current_time:
                return 

        # Generate a powerful, unique ID
        new_id = str(int(time.time() * 1000))
        
        # 1. INTERNAL MARKER
        internal_marker = {
            'id': new_id,
            'time_ms': current_time,
            'icon_key': 'usermarker',
            'is_round': False,
            'title': '',
            'desc': ''
        }
        markers_list.append(internal_marker)
        markers_list.sort(key=lambda x: x.get('time_ms', 0))
        canvas.update()
        
        # 2. Steam Format
        json_path = getattr(canvas, 'current_json_path', None)
        if not json_path or not os.path.exists(json_path):
            return
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if 'entries' not in data:
                data['entries'] = []
                
            raw_time = current_time + getattr(canvas, 'current_offset_ms', 0)
            
            steam_marker = {
                "id": new_id,
                "time": str(raw_time),
                "type": "usermarker",
                "title": "",
                "description": "",
                "icon": "steam_marker",
                "priority": 0
            }
            
            data['entries'].append(steam_marker)
            data['entries'].sort(key=lambda x: int(x.get('time', 0)))
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Marker save error: {e}")
    def take_screenshot(self, target_ms=None):
        """ Takes a clean screenshot directly from MPV and saves it to the global folder. """
        if not hasattr(self, 'player') or not self.player: return
        
        # Ensure the global folder exists (just in case)
        if not hasattr(self, 'screenshots_dir') or not os.path.exists(self.screenshots_dir):
            self.screenshots_dir = os.path.join(get_save_directory(), "Screenshots")
            os.makedirs(self.screenshots_dir, exist_ok=True)
            
        # Get the clip name (if selected) to add to the file name
        game_name = "Clip"
        row = self.ui.table_clips.currentRow()
        if hasattr(self.ui, 'table_clips') and row >= 0:
            item = self.ui.table_clips.item(row, 0)
            if item: 
                # Trim extra spaces from the ends of the name
                game_name = item.text().strip()
                # Replace characters forbidden in filenames with underscores.
                game_name = re.sub(r'[\\/*?:"<>|]', "_", game_name)

        # Determine the time (if a marker was clicked, use its time; otherwise, use the player's time)
        pos_ms = float(target_ms) if target_ms is not None else (getattr(self.player, 'time_pos', 0) * 1000)
        
        # Creating an attractive name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{game_name}_{int(pos_ms)}ms_{timestamp}.png"
        filepath = os.path.join(self.screenshots_dir, filename).replace('\\', '/')
        
        need_seek = False
        original_pos = getattr(self.player, 'time_pos', 0) * 1000
        
        # If we right-click far away from the slider, we need to jump there for a split second
        if target_ms is not None and abs(target_ms - original_pos) > 200:
            need_seek = True
            self.player.seek(pos_ms / 1000.0, reference='absolute', precision='exact')
            time.sleep(0.15) 
            
        try:
            self.player.command('screenshot-to-file', filepath, 'video')
            print(f"📸 Screenshot saved to: {filepath}")
        except Exception as e:
            print(f"Screenshot error: {e}")
            
        # We jump back in as if nothing had happened.
        if need_seek:
            self.player.seek(original_pos / 1000.0, reference='absolute', precision='exact')