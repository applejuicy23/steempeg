"""Video playback and the player surface, mixed into the main application.

These methods drive the mpv-backed player: opening and closing clips, play/pause,
volume and speed, the timeline and trim controls, fullscreen/theatre mode,
screenshots and markers. They run on the application instance and reach its widgets
and player through self.
"""
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime

from PySide6.QtCore import QEvent, QEventLoop, Qt, QPropertyAnimation, QTimer
from PySide6.QtGui import QCursor, QIcon, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from steempeg.core.dash import health
from steempeg.core.rendered_media import (
    duration_from_source_clip,
    is_sane_media_duration,
    load_rendered_companion_meta,
    probe_media_duration_sec,
)
from steempeg.infra.paths import get_resource_path, get_save_directory
from steempeg.ui.player.immersive_chrome import enter_immersive_chrome, exit_immersive_chrome
from steempeg.ui.window_chrome import collapse_content_insets, force_full_redraw, restore_content_insets, set_window_transitions
from steempeg.ui.player.thumbnails import PreviewSniperWorker, ThumbnailBatchThread
from steempeg.ui.message_dialog import steempeg_information


class PlayerMixin:
    def _clear_player_surface(self):
        """Stop mpv and return the player area to the empty placeholder.

        Does not touch library selection or the header — callers that need a full
        reset (close_current_clip) clear those separately.
        """
        self._force_pause = True
        self._eof_rewind_pending = 0
        self._current_mpd_abs_path = None
        self._is_switching = False
        self._awaiting_first_frame = False

        if hasattr(self, 'player') and self.player:
            self.player.pause = True
            try:
                self.player.stop()
                self.player.play("")
            except Exception:
                pass

        self._set_playback_loading(False)

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
            if hasattr(self.custom_timeline.canvas, 'mode_segments'):
                self.custom_timeline.canvas.mode_segments = []
            self.custom_timeline.canvas.update()

        if hasattr(self, 'video_stack') and hasattr(self, 'placeholder_frame'):
            self.video_stack.setCurrentWidget(self.placeholder_frame)

        if hasattr(self.ui, 'label_time'):
            self.ui.label_time.setText("00:00 / 00:00")

        if hasattr(self.ui, 'btn_play'):
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))

    def _reset_player_placeholder_default(self):
        """Restore the idle Steempeg poster (centered logo, no game icon overlay)."""
        if not hasattr(self, 'place_logo') or not hasattr(self, 'place_text'):
            return
        # Use a pixmap only and clear any stylesheet image — mixing the two stacked a
        # stretched game icon behind the logo and left a square halo around it.
        self.place_logo.setStyleSheet("")
        logo_path = get_resource_path("logo.png")
        if os.path.exists(logo_path):
            self.place_logo.setPixmap(
                QPixmap(logo_path).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.place_logo.setAlignment(Qt.AlignCenter)
        self.place_logo.show()
        self.place_text.setText("Please select a clip from the library")
        self.place_text.setStyleSheet(
            "color: #888888; font-size: 14px; font-weight: bold; margin-top: 15px;"
        )

    def close_current_clip(self):
        """ Completely destroys the current clip and clears the interface. """
        if getattr(self, '_is_switching', False):
            return

        self._clear_player_surface()
        # NOTE: clearSelection() leaves the *current* index intact, so the badge's
        # fallback (_current_preview_clip_path -> table.currentRow()) still resolved the
        # old clip and the badge never hid. Reset the current index too.
        if hasattr(self.ui, 'table_clips'):
            self.ui.table_clips.blockSignals(True)
            self.ui.table_clips.clearSelection()
            self.ui.table_clips.setCurrentCell(-1, -1)
            self.ui.table_clips.blockSignals(False)
        if hasattr(self, 'grid_clips'):
            self.grid_clips.blockSignals(True)
            self.grid_clips.clearSelection()
            self.grid_clips.setCurrentItem(None)
            self.grid_clips.blockSignals(False)
            # The QListWidget selection sits hidden under the custom ClipCard overlay,
            # so clearSelection() alone leaves the card's "selected" border drawn.
            # Repaint the cards to actually drop the highlight.
            if hasattr(self, '_sync_grid_card_visuals'):
                self._sync_grid_card_visuals()
        if hasattr(self, 'table_rendered'):
            self.table_rendered.blockSignals(True)
            self.table_rendered.clearSelection()
            self.table_rendered.setCurrentCell(-1, -1)
            self.table_rendered.blockSignals(False)
        if hasattr(self, 'grid_rendered'):
            self.grid_rendered.blockSignals(True)
            self.grid_rendered.clearSelection()
            self.grid_rendered.setCurrentItem(None)
            self.grid_rendered.blockSignals(False)
            if hasattr(self, '_sync_rendered_grid_card_visuals'):
                self._sync_rendered_grid_card_visuals()
        if hasattr(self, '_rendered_play_timer'):
            self._rendered_play_timer.stop()
        self._pending_rendered_play_path = None
        self._active_play_media_path = None
        self._rendered_media_path = None

        if hasattr(self, "set_player_header_clip_controls_visible"):
            self.set_player_header_clip_controls_visible(False)
        if hasattr(self, 'custom_text_label'):
            self.custom_text_label.setText("Select a clip to preview...")
        if hasattr(self, 'custom_icon_label'):
            self.custom_icon_label.setPixmap(QIcon(get_resource_path("unknown_icon.png")).pixmap(24, 24))
        # Forget the previewed clip / queue selection so the top-right badge
        # ("Preview" / "In queue (N)") clears instead of lingering after close.
        self._preview_clip_path = None
        if hasattr(self, "_clear_queue_selection"):
            self._clear_queue_selection()
        else:
            self._selected_queue_job_id = None
        if hasattr(self, 'update_playback_badge'):
            self.update_playback_badge()
        if hasattr(self, 'update_clip_health_button'):
            self.update_clip_health_button()

        # GLOBAL WIPE OF ALL SETTINGS TABS (UI WIPE)
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
            self.ui.label_location.setText("—")
            
        # We're locking down the render button
        if hasattr(self.ui, 'btn_start'):
            self.ui.btn_start.setEnabled(False)

        self._reset_player_placeholder_default()


    def _ignore_playback_stall(self, seconds=0.5):
        """Suppress stall detection briefly after seeks or clip switches."""
        self._playback_ignore_stall_until = time.time() + seconds
        self._playback_last_time_pos = None
        self._playback_stall_since = None
        self._playback_recover_at = None

    def _get_buffering_overlay(self):
        overlay = getattr(self, '_buffering_overlay', None)
        if overlay is None:
            from steempeg.ui.player.buffering_overlay import BufferingOverlay
            overlay = BufferingOverlay()
            self._buffering_overlay = overlay
        return overlay

    def _set_playback_loading(self, active, message="Buffering…"):
        # Render the indicator in a SEPARATE top-level tool window, never as a Qt
        # child over the native mpv surface — that overlap was the root cause of the
        # splitter stutter. A floating window composites independently and is safe.
        app = QApplication.instance()
        if active and app is not None and app.applicationState() != Qt.ApplicationState.ApplicationActive:
            overlay = getattr(self, '_buffering_overlay', None)
            if overlay is not None:
                overlay.hide_loading()
            self._playback_loading_active = False
            self._playback_recover_at = None
            return
        if active:
            self._playback_loading_active = True
            self._playback_recover_at = None
            overlay = self._get_buffering_overlay()
            anchor = getattr(self, 'mpv_wrapper', None) or getattr(self.ui, 'video_container', None)
            overlay.show_loading(anchor, message)
        else:
            overlay = getattr(self, '_buffering_overlay', None)
            if overlay is not None and getattr(self, '_playback_loading_active', False):
                overlay.hide_loading()
            self._playback_loading_active = False
            self._playback_recover_at = None
            self._playback_stall_since = None

    def _mpv_is_buffering(self):
        if not hasattr(self, 'player') or not self.player:
            return False
        try:
            cache_state = self.player['cache-buffering-state']
            if cache_state is not None and int(cache_state) > 0:
                return True
        except Exception:
            pass
        try:
            if self.player['paused-for-cache']:
                return True
        except Exception:
            pass
        return False

    def _update_playback_loading_state(self):
        """Show a loading overlay when MPV is buffering or playback time stalls."""
        if not hasattr(self, 'player') or not self.player:
            return

        app = QApplication.instance()
        if app is not None and app.applicationState() != Qt.ApplicationState.ApplicationActive:
            if getattr(self, '_playback_loading_active', False):
                self._set_playback_loading(False)
            return

        if getattr(self, '_is_switching', False):
            return

        now = time.time()
        if now < getattr(self, '_playback_ignore_stall_until', 0):
            return

        timeline = getattr(self, 'custom_timeline', None)
        if timeline is None or not timeline.isEnabled():
            self._set_playback_loading(False)
            return

        if getattr(self.player, 'pause', True) or getattr(self, '_force_pause', False):
            self._set_playback_loading(False)
            self._playback_last_time_pos = None
            return

        try:
            if self._mpv_is_buffering():
                self._set_playback_loading(True, "Buffering…")
                self._playback_last_time_pos = self.player.time_pos
                return

            time_sec = self.player.time_pos
            if time_sec is None:
                self._set_playback_loading(True, "Buffering…")
                return

            duration_sec = self._playback_duration_sec()
            if not duration_sec:
                duration_sec = getattr(self, 'current_clip_duration_sec', None) or self.player.duration
            if duration_sec and time_sec >= duration_sec - 0.05:
                self._set_playback_loading(False)
                return

            last_pos = getattr(self, '_playback_last_time_pos', None)
            if last_pos is None or abs(time_sec - last_pos) > 0.02:
                self._playback_last_time_pos = time_sec
                self._playback_stall_since = None
                if getattr(self, '_playback_loading_active', False):
                    if self._playback_recover_at is None:
                        self._playback_recover_at = now
                    elif now - self._playback_recover_at >= 0.2:
                        self._set_playback_loading(False)
                return

            if self._playback_stall_since is None:
                self._playback_stall_since = now
            elif now - self._playback_stall_since >= 0.35:
                self._set_playback_loading(True, "Buffering…")
        except Exception:
            pass

    def _reveal_video_when_ready(self):
        """Swap the placeholder for the live mpv surface once the first frame exists.

        Polls mpv's time_pos (a real position means a frame is decoded) and waits out
        any cache buffering, with a hard deadline so a hidden/idle surface can never
        leave us stuck on the placeholder forever.
        """
        if not getattr(self, '_awaiting_first_frame', False):
            return

        # "width" (the decoded frame's pixel width) is only set once mpv has actually
        # decoded the first frame — the precise moment it's safe to show the surface.
        # We deliberately do NOT gate on buffering: cache-buffering-state often reads
        # non-zero even on healthy playback, which would stall the reveal for the full
        # deadline and cause a visible poster blink on every load.
        ready = False
        try:
            if self.player.width:
                ready = True
        except Exception:
            ready = True  # never get wedged on a transient property error

        if not ready and time.time() < getattr(self, '_first_frame_deadline', 0):
            QTimer.singleShot(16, self._reveal_video_when_ready)
            return

        self._awaiting_first_frame = False
        if hasattr(self, 'video_stack') and hasattr(self.ui, 'video_container'):
            self.video_stack.setCurrentWidget(self.ui.video_container)
        if hasattr(self, '_maybe_offer_salvage_verification'):
            self._maybe_offer_salvage_verification()

    def _reopen_current_clip_paused(self):
        """Reload the current clip and pause on the first frame.

        Recovery path for a wedged DASH demuxer: some Steam clips (a non-zero
        Period start plus keep_open) can't be seeked back to 0 after EOF — ffmpeg
        fails to reload the first fragment and then spins on "Invalid data found"
        forever, killing playback for this clip and sometimes the whole player.
        Reopening the file tears down that broken demuxer and lands cleanly on
        frame 0. The surface already shows video_container, so there's no flash.
        """
        path = getattr(self, '_current_mpd_abs_path', None)
        if not path or not hasattr(self, 'player') or not self.player:
            return
        try:
            self._ignore_playback_stall(0.8)
            self.player.play(path)
            self.player.pause = True
            if hasattr(self.ui, 'btn_play'):
                self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))
            if hasattr(self, 'custom_timeline'):
                self.custom_timeline.force_jump(0)
        except Exception:
            pass

    # VIDEO PLAYER CONTROLS
    def toggle_play(self):
        """ Toggles Play/Pause state in MPV and updates the button icon. """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled(): return
        if getattr(self.player, 'path', None) is None: return

        if self.player.pause:
            dur = self._playback_duration_sec()
            try:
                pos = self.player.time_pos
            except Exception:
                pos = None
            if dur and pos is not None and float(pos) >= float(dur) - 0.05:
                self._ignore_playback_stall(0.5)
                try:
                    self.player.seek(0, reference='absolute', precision='exact')
                except Exception:
                    pass
                if hasattr(self, 'custom_timeline'):
                    self.custom_timeline.force_jump(0)

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
            # Keep the timeline's playhead interpolation in sync with the real rate,
            # otherwise the playhead jitters at non-1x speeds (e.g. 0.1x when zoomed in).
            if hasattr(self, 'custom_timeline') and hasattr(self.custom_timeline, 'canvas'):
                self.custom_timeline.canvas.playback_speed = speed_float

    def _keep_deprecated_library_pill_hidden(self):
        """mega_top_pill was replaced by tab buttons; never show it (orphan window on Windows)."""
        if hasattr(self, 'mega_top_pill'):
            self.mega_top_pill.hide()

    def _set_left_library_panel_visible(self, visible: bool):
        """Toggle the whole library column — do not show/hide tab children individually."""
        if hasattr(self.ui, 'left_panel'):
            self.ui.left_panel.setVisible(visible)
        elif hasattr(self.ui, 'table_clips'):
            left_wrapper = self.ui.table_clips.parentWidget()
            if left_wrapper and "Splitter" not in type(left_wrapper).__name__ and left_wrapper.objectName() != "centralwidget":
                left_wrapper.setVisible(visible)
            else:
                self.ui.table_clips.setVisible(visible)
        self._keep_deprecated_library_pill_hidden()

    def toggle_theater_mode(self):
        """ Safely collapses side and bottom panels, aware of Fullscreen state, and swaps icon. """
        
        if getattr(self, 'is_fullscreen', False):
            self.toggle_fullscreen() 
            
        self.is_theater = not getattr(self, 'is_theater', False)

        # Capture the real (expanded) splitter sizes the moment we enter theatre,
        # while the side/bottom panels are still visible. Hiding them next makes the
        # splitter report 0 for those panes, so we need this snapshot to restore a
        # clean layout if the user jumps theatre -> fullscreen -> exit.
        if self.is_theater:
            self._save_splitter_sizes(getattr(self.ui, 'main_splitter', None), '_pre_theater_main_sizes')
            self._save_splitter_sizes(getattr(self, 'main_v_splitter', None), '_pre_theater_v_sizes')
            self._save_splitter_sizes(getattr(self, 'right_h_splitter', None), '_pre_theater_h_sizes')

        self._set_left_library_panel_visible(not self.is_theater)

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
            # Remember original handle geometry so we can restore the exact
            # same thickness as the left splitter (it is not always equal to
            # QUEUE_SPLITTER_GUTTER).
            self._pre_theater_right_handle_width = self.right_h_splitter.handleWidth()
            try:
                self._pre_theater_right_handle_visible = self.right_h_splitter.handle(1).isVisible()
            except Exception:
                self._pre_theater_right_handle_visible = True
            # Collapse the queue splitter handle itself — otherwise a thick dark
            # strip remains on the right and breaks symmetry with the left edge.
            self._hide_right_h_splitter_handle()

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

        # Player top inset + right margin: in theatre keep a symmetric right inset
        # matching the custom content padding (same visual spacing as left side).
        if hasattr(self, 'right_content_wrap') and self.right_content_wrap.layout():
            from steempeg.ui.layout_defaults import (
                QUEUE_SPLITTER_GUTTER,
                RIGHT_PANEL_PLAYER_TOP_INSET,
            )
            margin_top = 0 if self.is_theater else RIGHT_PANEL_PLAYER_TOP_INSET
            right_inset = 9
            custom_margins = getattr(self.ui, '_custom_content_margins', None)
            if custom_margins and len(custom_margins) >= 3:
                right_inset = int(custom_margins[2])
            margin_right = right_inset if self.is_theater else QUEUE_SPLITTER_GUTTER
            self.right_content_wrap.layout().setContentsMargins(0, margin_top, margin_right, 0)

        # Restore the queue splitter handle after leaving theatre (we zeroed it on enter).
        if hasattr(self, 'right_h_splitter') and not self.is_theater:
            # Restore the original handle width/visibility instead of hardcoding
            # constants; otherwise theatre toggling can make the right handle
            # thicker than the left.
            restored_width = getattr(self, '_pre_theater_right_handle_width', None)
            if restored_width is not None:
                self.right_h_splitter.setHandleWidth(int(restored_width))
            else:
                # Fallback: main splitter uses 6px; keep right visually aligned.
                self.right_h_splitter.setHandleWidth(6)
            restored_visible = getattr(self, '_pre_theater_right_handle_visible', None)
            if restored_visible is None:
                restored_visible = True
            self.right_h_splitter.handle(1).setVisible(bool(restored_visible))

        # Theatre keeps the normal content padding (only true fullscreen goes flush).
        restore_content_insets(self.ui)

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
        if hasattr(self, '_sync_library_mode_chrome'):
            self._sync_library_mode_chrome()

    def _save_splitter_sizes(self, splitter, attr_name):
        if splitter is None:
            return
        setattr(self, attr_name, splitter.sizes())

    def _save_right_h_splitter_handle(self, width_attr: str, visible_attr: str) -> None:
        splitter = getattr(self, "right_h_splitter", None)
        if splitter is None:
            return
        setattr(self, width_attr, splitter.handleWidth())
        try:
            setattr(self, visible_attr, splitter.handle(1).isVisible())
        except Exception:
            setattr(self, visible_attr, True)

    def _restore_right_h_splitter_handle(self) -> None:
        splitter = getattr(self, "right_h_splitter", None)
        if splitter is None:
            return
        width = getattr(self, "_immersive_right_h_handle_width", None)
        visible = getattr(self, "_immersive_right_h_handle_visible", None)
        if width is None:
            width = getattr(self, "_pre_theater_right_handle_width", None)
        if visible is None:
            visible = getattr(self, "_pre_theater_right_handle_visible", None)
        if width is None:
            width = 6
        if visible is None:
            visible = True
        splitter.setHandleWidth(int(width))
        try:
            splitter.handle(1).setVisible(bool(visible))
        except Exception:
            pass

    def _hide_right_h_splitter_handle(self) -> None:
        splitter = getattr(self, "right_h_splitter", None)
        if splitter is None:
            return
        try:
            splitter.handle(1).setVisible(False)
        except Exception:
            pass
        splitter.setHandleWidth(0)

    def _collapse_splitter(self, splitter, keep_index):
        if splitter is None:
            return
        sizes = splitter.sizes()
        total = sum(sizes) if sum(sizes) > 0 else (
            splitter.width() if splitter.orientation() == Qt.Horizontal else splitter.height()
        )
        total = max(int(total), 1)
        if keep_index == 0:
            splitter.setSizes([total, 0])
        else:
            splitter.setSizes([0, total])

    def _set_hide_watcher_suppressed(self, suppressed: bool):
        watcher = getattr(self, 'hide_watcher', None)
        if watcher is not None:
            watcher.set_suppressed(suppressed)

    def _save_immersive_splitter_sizes(self):
        self._save_splitter_sizes(getattr(self.ui, 'main_splitter', None), '_immersive_main_splitter_sizes')
        self._save_splitter_sizes(getattr(self, 'main_v_splitter', None), '_immersive_v_splitter_sizes')
        self._save_splitter_sizes(getattr(self, 'right_h_splitter', None), '_immersive_h_splitter_sizes')

    def _enter_immersive_layout(self):
        """Collapse splitters only — sizes must be saved before panels are hidden."""
        self._collapse_splitter(getattr(self.ui, 'main_splitter', None), keep_index=1)
        self._collapse_splitter(getattr(self, 'main_v_splitter', None), keep_index=0)
        self._collapse_splitter(getattr(self, 'right_h_splitter', None), keep_index=0)

        if hasattr(self, 'render_queue_panel'):
            self.render_queue_panel.hide()

    def _exit_immersive_layout(self, is_theater=False):
        if hasattr(self.ui, 'main_splitter') and hasattr(self, '_immersive_main_splitter_sizes'):
            self.ui.main_splitter.setSizes(self._immersive_main_splitter_sizes)
        if hasattr(self, 'main_v_splitter') and hasattr(self, '_immersive_v_splitter_sizes'):
            self.main_v_splitter.setSizes(self._immersive_v_splitter_sizes)
        if hasattr(self, 'right_h_splitter') and hasattr(self, '_immersive_h_splitter_sizes'):
            self.right_h_splitter.setSizes(self._immersive_h_splitter_sizes)
        if not is_theater and hasattr(self, '_sync_queue_splitter_visibility'):
            self._sync_queue_splitter_visibility()

    def _immersive_screen_geometry(self):
        screen = self.ui.screen() or QApplication.primaryScreen()
        return screen.geometry() if screen else self.ui.geometry()

    def _enter_immersive_chrome(self):
        if hasattr(self.ui, "title_bar"):
            self.ui.title_bar.hide()
        enter_immersive_chrome(self.ui, self._immersive_screen_geometry())
        self.ui.raise_()
        self.ui.activateWindow()

    def _show_immersive_transition_cover(self):
        if getattr(self, '_immersive_transition_cover', None) is None:
            cover = QWidget()
            cover.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            cover.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            cover.setStyleSheet("background-color: #1e1e1e;")
            self._immersive_transition_cover = cover
        cover = self._immersive_transition_cover
        cover.setGeometry(self._immersive_screen_geometry())
        cover.show()
        cover.raise_()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _hide_immersive_transition_cover(self):
        cover = getattr(self, '_immersive_transition_cover', None)
        if cover is not None:
            cover.hide()

    def _finish_fullscreen_enter(self):
        """Drop the transition cover once the restore animation is done + repainted."""
        if not getattr(self, 'is_fullscreen', False):
            self._hide_immersive_transition_cover()
            set_window_transitions(self.ui, True)
            return
        # Re-assert full-monitor geometry: clearing the maximized state queues a
        # restore to the old (small) normalGeometry which, with transitions disabled,
        # overrides the setGeometry done in enter_immersive_chrome. Applying it here
        # (after Qt processed the state change) makes the fullscreen size stick.
        self.ui.setGeometry(self._immersive_screen_geometry())
        self.ui.raise_()
        self.ui.activateWindow()
        self.ui.update()
        force_full_redraw(self.ui)
        # Flush the paint before lifting the cover so the first visible frame is the
        # finished fullscreen layout (no transparent edges / animation tail).
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        if hasattr(self, 'player_footer_frame'):
            self.player_footer_frame.show()
            self.player_footer_frame.raise_()
        self._hide_immersive_transition_cover()
        # Restore native min/max/restore animations that were disabled for the switch.
        set_window_transitions(self.ui, True)
        self._show_immersive_esc_hint()

    def _activate_window_layouts(self):
        for layout in (
            self.ui.layout() if hasattr(self.ui, 'layout') else None,
            self.ui.right_panel.layout() if hasattr(self.ui, 'right_panel') else None,
            getattr(self, 'top_v_wrap', None) and self.top_v_wrap.layout(),
            getattr(self, 'bottom_v_wrap', None) and self.bottom_v_wrap.layout(),
        ):
            if layout is not None:
                layout.activate()
        self.ui.updateGeometry()

    def _get_immersive_esc_hint(self):
        if getattr(self, '_immersive_esc_hint', None) is None:
            hint = QLabel("Press ESC to exit full screen")
            hint.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            hint.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            hint.setStyleSheet(
                "QLabel {"
                " background-color: rgba(15, 15, 15, 210);"
                " color: #eeeeee;"
                " padding: 12px 24px;"
                " border-radius: 6px;"
                " font-size: 15px;"
                " font-family: 'Segoe UI', Arial, sans-serif;"
                "}"
            )
            self._immersive_esc_hint = hint
        return self._immersive_esc_hint

    def _position_immersive_esc_hint(self):
        hint = getattr(self, '_immersive_esc_hint', None)
        if hint is None:
            return
        screen_geo = self._immersive_screen_geometry()
        hint.adjustSize()
        hint.move(
            screen_geo.x() + max(0, (screen_geo.width() - hint.width()) // 2),
            screen_geo.y() + 36,
        )

    def _show_immersive_esc_hint(self):
        hint = self._get_immersive_esc_hint()
        self._position_immersive_esc_hint()

        effect = hint.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(hint)
            hint.setGraphicsEffect(effect)
        effect.setOpacity(1.0)

        anim = getattr(self, '_immersive_hint_fade_anim', None)
        if anim is not None:
            anim.stop()

        hint.show()
        hint.raise_()

        fade = QPropertyAnimation(effect, b"opacity", hint)
        fade.setDuration(600)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.finished.connect(hint.hide)
        self._immersive_hint_fade_anim = fade
        QTimer.singleShot(2200, fade.start)

    def _hide_immersive_esc_hint(self):
        anim = getattr(self, '_immersive_hint_fade_anim', None)
        if anim is not None:
            anim.stop()
        hint = getattr(self, '_immersive_esc_hint', None)
        if hint is not None:
            hint.hide()

    def _exit_immersive_mode(self):
        """Restore UI under a solid cover, then title bar — avoids MPV-only flash."""
        is_t = getattr(self, 'is_theater', False)

        self._show_immersive_transition_cover()
        # Same as enter: kill the SW_RESTORE/maximize cross-fade so exit is instant
        # under the cover (no torn animation / desktop bleed). Restored in finish_exit.
        set_window_transitions(self.ui, False)
        self._hide_immersive_esc_hint()
        if hasattr(self, 'fs_timer'):
            self.fs_timer.stop()
        self.ui.setCursor(Qt.CursorShape.ArrowCursor)
        self._set_hide_watcher_suppressed(True)

        if hasattr(self, 'player_footer_frame'):
            self.player_footer_frame.hide()

        self._set_left_library_panel_visible(not is_t)

        if hasattr(self.ui, 'btn_start'):
            bw = self.ui.btn_start.parentWidget()
            if bw and "Splitter" not in type(bw).__name__ and bw.objectName() != "centralwidget":
                bw.setVisible(not is_t)
        if hasattr(self, 'btn_refresh'):
            rw = self.btn_refresh.parentWidget()
            if rw:
                rw.setVisible(not is_t)
        if hasattr(self.ui, 'btn_about'):
            self.ui.btn_about.setVisible(not is_t)
        if hasattr(self.ui, 'btn_update_check'):
            self.ui.btn_update_check.setVisible(not is_t)

        if hasattr(self, 'player_header_frame'):
            self.player_header_frame.show()
        if hasattr(self.ui, 'main_splitter'):
            self.ui.main_splitter.handle(1).setVisible(not is_t)
        if hasattr(self, 'main_v_splitter'):
            self.main_v_splitter.handle(1).setVisible(not is_t)

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

        # Restore player inset + right margin when returning from immersive mode.
        if hasattr(self, 'right_content_wrap') and self.right_content_wrap.layout():
            from steempeg.ui.layout_defaults import (
                QUEUE_SPLITTER_GUTTER,
                RIGHT_PANEL_PLAYER_TOP_INSET,
            )
            margin_top = 0 if is_t else RIGHT_PANEL_PLAYER_TOP_INSET
            right_inset = 9
            custom_margins = getattr(self.ui, '_custom_content_margins', None)
            if custom_margins and len(custom_margins) >= 3:
                right_inset = int(custom_margins[2])
            margin_right = right_inset if is_t else QUEUE_SPLITTER_GUTTER
            self.right_content_wrap.layout().setContentsMargins(0, margin_top, margin_right, 0)

        # Both theatre and windowed keep the normal content padding; only the
        # dedicated fullscreen mode collapses it (handled in toggle_fullscreen).
        restore_content_insets(self.ui)

        footer = self.player_footer_frame
        footer.setWindowFlags(Qt.WindowType.Widget)
        footer.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        footer.setParent(self.ui.right_panel)
        footer.clearMask()
        footer.setMinimumWidth(0)
        footer.setMaximumWidth(16777215)
        footer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        idx = getattr(self, 'controls_layout_index', -1)
        target_layout = getattr(self, 'top_v_wrap', self.ui.right_panel).layout()
        if target_layout and idx >= 0:
            target_layout.insertWidget(idx, footer)
        elif target_layout:
            target_layout.addWidget(footer)

        footer.setObjectName("HudFrame")
        footer.setStyleSheet(
            "QFrame#HudFrame { background-color: #2d2d2d; border-radius: 6px; border: none; }"
        )

        v_container = getattr(self.ui, 'video_container', None)
        if v_container:
            v_container.setMinimumSize(1, 1)
            v_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._exit_immersive_layout(is_t)

        self._restore_right_h_splitter_handle()

        if not is_t:
            if hasattr(self, 'bottom_v_wrap'):
                self.bottom_v_wrap.show()
            if hasattr(self.ui, 'settings_tabs'):
                self.ui.settings_tabs.show()
            if hasattr(self, 'neo_wrapper'):
                self.neo_wrapper.show()
            if hasattr(self.ui, 'frame_status'):
                self.ui.frame_status.show()
            if hasattr(self, 'render_dashboard'):
                self.render_dashboard.show()
            # The block above unconditionally re-shows the render dock + restores the
            # queue splitter. For a rendered-video preview that must stay hidden
            # (finished exports can't be re-rendered), so re-apply the library-mode
            # chrome to collapse the dock again after leaving immersive mode.
            if hasattr(self, '_sync_library_mode_chrome'):
                self._sync_library_mode_chrome()

        self._activate_window_layouts()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

        def finish_exit():
            # Show the title bar *before* restoring the window state so WM_NCCALCSIZE
            # sees it visible and re-applies the maximized inset (otherwise a restored
            # maximized window overhangs the monitor / covers the taskbar).
            if hasattr(self.ui, "title_bar"):
                self.ui.title_bar.show()
            exit_immersive_chrome(self.ui)
            if hasattr(self.ui, "title_bar"):
                self.ui.title_bar.sync_window_state()
            self._activate_window_layouts()
            footer.show()
            if right_layout:
                right_layout.activate()
            if hasattr(self, 'btn_fullscreen'):
                self.btn_fullscreen.clearFocus()
                QApplication.postEvent(self.btn_fullscreen, QEvent(QEvent.Type.Leave))
            if hasattr(self, 'btn_theater'):
                self.btn_theater.clearFocus()
                QApplication.postEvent(self.btn_theater, QEvent(QEvent.Type.Leave))
            self._set_hide_watcher_suppressed(False)
            self._hide_immersive_transition_cover()
            set_window_transitions(self.ui, True)
            # The fullscreen HUD footer was a floating Tool window; after reparenting
            # it back, force a full relayout + repaint so no ghost copy lingers at the
            # bottom edge of the restored window.
            if right_layout:
                right_layout.activate()
            self.ui.right_panel.updateGeometry()
            self.ui.update()
            self.ui.repaint()

        QTimer.singleShot(0, finish_exit)

    def toggle_fullscreen(self):
        """Immersive player mode: hide chrome inside the current window (no showFullScreen)."""
        
        if getattr(self, 'fullscreen_lock', False): return
        self.fullscreen_lock = True
        QTimer.singleShot(200, lambda: setattr(self, 'fullscreen_lock', False))

        self.is_fullscreen = not getattr(self, 'is_fullscreen', False)
        
        if self.is_fullscreen:
            # --- ENTERING IMMERSIVE MODE (stay maximized / current window state) ---
            # Mask the whole transition with a solid cover: while growing the window
            # from the work area to the full monitor, Windows briefly paints the native
            # frame and leaves a stale "ghost" strip at the old bottom. The cover hides
            # all of that until the surface is rebuilt and repainted.
            self._show_immersive_transition_cover()

            came_from_theater = getattr(self, 'is_theater', False)
            if came_from_theater:
                self.is_theater = False
                if hasattr(self, 'btn_theater'):
                    icon_path = get_resource_path("theatremode.png")
                    if os.path.exists(icon_path):
                        self.btn_theater.setIcon(QIcon(icon_path))
                    else:
                        self.btn_theater.setText("🎦")

            self._set_hide_watcher_suppressed(True)
            self._save_immersive_splitter_sizes()

            # In theatre the side/bottom panes are collapsed to 0, so the snapshot
            # above is degenerate. Swap in the expanded sizes captured on theatre
            # entry, otherwise exiting fullscreen lands in a broken "panels visible
            # but zero-width" layout.
            if came_from_theater:
                if hasattr(self, '_pre_theater_main_sizes'):
                    self._immersive_main_splitter_sizes = list(self._pre_theater_main_sizes)
                if hasattr(self, '_pre_theater_v_sizes'):
                    self._immersive_v_splitter_sizes = list(self._pre_theater_v_sizes)
                if hasattr(self, '_pre_theater_h_sizes'):
                    self._immersive_h_splitter_sizes = list(self._pre_theater_h_sizes)
            elif hasattr(self, 'right_h_splitter'):
                self._save_right_h_splitter_handle(
                    '_immersive_right_h_handle_width',
                    '_immersive_right_h_handle_visible',
                )

            # Hide ALL old and NEW panels
            self._set_left_library_panel_visible(False)
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

            # Drop the 10px gutter that sits before the (now collapsed) queue splitter,
            # otherwise it leaves an empty strip on the right edge of the fullscreen video.
            if hasattr(self, 'right_content_wrap') and self.right_content_wrap.layout():
                self.right_content_wrap.layout().setContentsMargins(0, 0, 0, 0)

            # Collapse the custom title-bar content wrapper padding so the video
            # reaches every edge (otherwise a 9-11px border frames the fullscreen).
            collapse_content_insets(self.ui)

            # Make the un-maximize into fullscreen instant (no SW_RESTORE cross-fade
            # that leaks the desktop through the window). Re-enabled in _finish.
            set_window_transitions(self.ui, False)

            self._enter_immersive_layout()
            if hasattr(self, 'right_h_splitter'):
                self._hide_right_h_splitter_handle()
            self._enter_immersive_chrome()

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
            # Transitions are disabled, so the switch is instant — a short cover is
            # enough to hide the single-frame swap, then restore animations.
            QTimer.singleShot(80, self._finish_fullscreen_enter)
            
        else:
            self._exit_immersive_mode()

    
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

        # The buffering pill is an always-on-top tool window; hide it whenever the
        # app loses focus so it never floats over other applications. It re-shows on
        # the next buffering tick if playback is still stalling.
        if state != Qt.ApplicationState.ApplicationActive:
            overlay = getattr(self, '_buffering_overlay', None)
            if overlay is not None:
                overlay.hide_loading()
            self._playback_loading_active = False
            self._playback_recover_at = None

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

    def _set_trim_button_active(self, active: bool) -> None:
        """Sync the Trim / Cancel button and tools pill with trim mode."""
        if not hasattr(self, "btn_trim"):
            return
        if active:
            cancel_icon_path = get_resource_path("cancel.png")
            if os.path.exists(cancel_icon_path):
                self.btn_trim.setIcon(QIcon(cancel_icon_path))
                self.btn_trim.setText(" Cancel")
            else:
                self.btn_trim.setIcon(QIcon())
                self.btn_trim.setText("❌ Cancel")
            self.btn_trim.setStyleSheet(
                "background-color: #ff4444; color: white; border-radius: 15px; "
                "padding: 0 12px; font-weight: bold;"
            )
            if hasattr(self, "trim_tools_pill"):
                self.trim_tools_pill.show()
        else:
            trim_icon_path = get_resource_path("trim_icon.png")
            if os.path.exists(trim_icon_path):
                self.btn_trim.setIcon(QIcon(trim_icon_path))
                self.btn_trim.setText(" Trim")
            else:
                self.btn_trim.setIcon(QIcon())
                self.btn_trim.setText("✂️ Trim")
            self.btn_trim.setStyleSheet(
                "background-color: #cfa94a; color: black; border-radius: 15px; "
                "padding: 0 12px; font-weight: bold;"
            )
            if hasattr(self, "trim_tools_pill"):
                self.trim_tools_pill.hide()
            self._apply_video_border(False)

    def apply_trim_state(
        self,
        is_trim_mode: bool,
        trim_start_ms: int = 0,
        trim_end_ms: int = 0,
        *,
        silent: bool = False,
    ) -> None:
        """Restore per-clip trim handles and button state (does not toggle via enable_trim_mode)."""
        if not hasattr(self, "custom_timeline"):
            return
        canvas = self.custom_timeline.canvas
        duration = float(getattr(canvas, "duration_ms", 0) or 0)
        if duration <= 0:
            duration = float(getattr(self, "current_clip_duration_sec", 0) or 0) * 1000.0

        if is_trim_mode and trim_end_ms > trim_start_ms and duration > 0:
            start = max(0.0, min(float(trim_start_ms), duration - 1000.0))
            end = max(start + 1000.0, min(float(trim_end_ms), duration))
            canvas.is_trim_mode = True
            canvas.trim_start_ms = start
            canvas.trim_end_ms = end
            self._set_trim_button_active(True)
            if not silent:
                self.custom_timeline.trim_changed.emit(int(start), int(end))
        else:
            canvas.disable_trim_mode()
            self._set_trim_button_active(False)
        canvas.update()

    def _deferred_apply_trim_restore(self) -> None:
        pending = getattr(self, "_pending_trim_restore", None)
        if not pending:
            if hasattr(self, "_loading_queue_job"):
                self._loading_queue_job = False
            return
        if pending.get("is_trim_mode") and hasattr(self, "custom_timeline"):
            duration = float(getattr(self.custom_timeline.canvas, "duration_ms", 0) or 0)
            if duration <= 0:
                QTimer.singleShot(300, self._deferred_apply_trim_restore)
                return
        self._pending_trim_restore = None
        if hasattr(self, "_apply_clip_session_state"):
            self._apply_clip_session_state(pending, silent=True)
        else:
            self.apply_trim_state(
                pending.get("is_trim_mode", False),
                pending.get("trim_start_ms", 0),
                pending.get("trim_end_ms", 0),
                silent=True,
            )
        if hasattr(self, "_loading_queue_job"):
            self._loading_queue_job = False
        if hasattr(self, "update_final_setup"):
            self.update_final_setup(trim_only=True)

    def _deactivate_trim_ui(self):
        """Turn off trim mode on the timeline and reset its button/border chrome."""
        if not hasattr(self, 'custom_timeline'):
            return
        self.custom_timeline.disable_trim_mode()
        if hasattr(self, 'video_overlay'):
            self.video_overlay.show_border = False
            self.video_overlay.update()
        if hasattr(self, 'border_overlay'):
            self.border_overlay.setStyleSheet("border: 3px solid #ffcc00; background-color: transparent;")
        self._set_trim_button_active(False)

    def cancel_trim_mode(self):
        """Exit trim mode if active (used when leaving the clip via a tab switch)."""
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.is_trim_mode:
            return
        self._deactivate_trim_ui()
        self.update_final_setup()
        if hasattr(self, '_persist_trim_for_current_clip'):
            self._persist_trim_for_current_clip()

    def toggle_trim_state(self):
        """ Toggles between Trim mode and Normal mode seamlessly without interrupting playback """
        if not hasattr(self, 'custom_timeline'): return

        if self.custom_timeline.is_trim_mode:
            self._deactivate_trim_ui()
            self._run_trim_side_effects()
        else:
            self.custom_timeline.enable_trim_mode()
            self._set_trim_button_active(True)

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
                self._ignore_playback_stall(0.6)


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
        """ Fires when trim handles move or trim mode toggles — defer heavy UI work. """
        if getattr(self, '_loading_queue_job', False):
            return
        timer = getattr(self, '_trim_side_effects_timer', None)
        if timer is None:
            timer = QTimer(self.ui)
            timer.setSingleShot(True)
            timer.timeout.connect(self._run_trim_side_effects)
            self._trim_side_effects_timer = timer
        timer.start(0)

    def _run_trim_side_effects(self) -> None:
        if getattr(self, '_loading_queue_job', False):
            return
        self.update_final_setup(trim_only=True)
        if hasattr(self, '_persist_trim_for_current_clip'):
            self._persist_trim_for_current_clip()
        if hasattr(self.ui, 'combo_quality') and "Target File Size" in self.ui.combo_quality.currentText():
            self.setup_dynamic_slider()

    def _clear_timeline_clip_overlays(self):
        """Drop clip-specific trim, markers, and hover preview when switching media."""
        if not hasattr(self, 'custom_timeline'):
            return
        tl = self.custom_timeline
        tl.disable_trim_mode()
        if hasattr(tl, 'preview_widget'):
            tl.preview_widget.hide()
            tl.preview_widget.clear_for_new_media()
        canvas = tl.canvas
        canvas.markers.clear()
        canvas.mode_segments = []
        canvas.clip_ranges = []
        canvas.current_app_id = None
        canvas.current_json_path = None
        canvas.rendered_media_path = None
        canvas._hover_preview_bucket = -1
        canvas._batch_thumbs_busy = False
        canvas.update()

    def _begin_preview_switch(self) -> int:
        """Pause MPV and stop background workers before loading another file."""
        self._media_switch_gen = getattr(self, "_media_switch_gen", 0) + 1
        self._clear_timeline_clip_overlays()

        if hasattr(self, "thumb_thread") and self.thumb_thread and self.thumb_thread.isRunning():
            self._stop_timeline_thumb_batch()
        else:
            self._set_timeline_batch_thumbs_busy(False)

        if hasattr(self, "custom_timeline") and hasattr(self.custom_timeline, "canvas"):
            sniper = getattr(self.custom_timeline.canvas, "sniper", None)
            if sniper:
                sniper.kill_worker()

        if hasattr(self, "player") and self.player:
            try:
                self.player.pause = True
            except Exception:
                pass

        return self._media_switch_gen

    def _set_timeline_batch_thumbs_busy(self, busy: bool) -> None:
        if hasattr(self, "custom_timeline") and hasattr(self.custom_timeline, "canvas"):
            self.custom_timeline.canvas._batch_thumbs_busy = busy

    def _playback_duration_sec(self):
        """Clip length from MPD for DASH; MPV/ffprobe for exported rendered files."""
        if getattr(self, "_rendered_media_path", None):
            return self._resolved_rendered_duration_sec()

        clip_dur = getattr(self, "current_clip_duration_sec", None)
        if clip_dur and is_sane_media_duration(clip_dur):
            return float(clip_dur)
        try:
            dur = self.player.duration
            if is_sane_media_duration(dur):
                return float(dur)
        except Exception:
            pass
        return None

    def _resolved_rendered_duration_sec(self) -> float | None:
        """Duration for a flat exported file — never trust absurd MPV/Matroska headers."""
        path = getattr(self, "_rendered_media_path", None)
        if not path:
            return None

        cache = getattr(self, "_rendered_duration_cache", None)
        if cache and cache[0] == os.path.normpath(path):
            return cache[1]

        try:
            dur = self.player.duration
            if is_sane_media_duration(dur):
                val = float(dur)
                self._rendered_duration_cache = (os.path.normpath(path), val)
                return val
        except Exception:
            pass

        meta = load_rendered_companion_meta(path) or {}
        meta_dur = meta.get("duration_sec")
        if is_sane_media_duration(meta_dur):
            val = float(meta_dur)
            self._rendered_duration_cache = (os.path.normpath(path), val)
            return val

        clip_path = (meta.get("clip_path") or "").strip()
        if clip_path:
            src_dur = duration_from_source_clip(clip_path)
            if src_dur is not None:
                self._rendered_duration_cache = (os.path.normpath(path), src_dur)
                return src_dur

        probed = probe_media_duration_sec(path)
        if probed is not None:
            self._rendered_duration_cache = (os.path.normpath(path), probed)
            return probed

        clip_dur = getattr(self, "current_clip_duration_sec", None)
        if is_sane_media_duration(clip_dur):
            return float(clip_dur)
        return None

    def _apply_playback_duration(self, duration_sec: float) -> None:
        if not is_sane_media_duration(duration_sec):
            return
        self.current_clip_duration_sec = float(duration_sec)
        if hasattr(self, "custom_timeline"):
            self.custom_timeline.set_duration(int(duration_sec * 1000))

    def _poll_rendered_media_duration(self, file_path: str, switch_gen: int, attempt: int = 0) -> None:
        """MPV often reports duration a few hundred ms after play — poll before hover preview."""
        if switch_gen != getattr(self, "_media_switch_gen", 0):
            return
        if getattr(self, "_active_play_media_path", None) != file_path:
            return

        from steempeg.ui.library.rendered_library import RENDERED_AUDIO_EXTS

        duration_sec = 0.0
        resolved = self._resolved_rendered_duration_sec()
        if resolved is not None:
            duration_sec = resolved
        else:
            try:
                dur = self.player.duration
                if is_sane_media_duration(dur):
                    duration_sec = float(dur)
            except Exception:
                pass

        if duration_sec >= 1.0:
            self._apply_playback_duration(duration_sec)
            ext = os.path.splitext(file_path)[1].lower()
            if ext in RENDERED_AUDIO_EXTS:
                if hasattr(self, "custom_timeline"):
                    self.custom_timeline.thumb_dir = None
                self._set_timeline_batch_thumbs_busy(False)
            else:
                abs_path = os.path.abspath(file_path).replace("\\", "/")
                self._start_timeline_thumb_batch(abs_path, duration_sec)
            if hasattr(self, "custom_timeline"):
                self.custom_timeline.setEnabled(True)
            self._is_switching = False
            if hasattr(self.ui, "btn_play"):
                self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_pause.png")))
            return

        if attempt < 10:
            QTimer.singleShot(120, lambda: self._poll_rendered_media_duration(file_path, switch_gen, attempt + 1))
        else:
            resolved = self._resolved_rendered_duration_sec()
            if resolved is not None and resolved >= 1.0:
                self._apply_playback_duration(resolved)
                ext = os.path.splitext(file_path)[1].lower()
                if ext not in RENDERED_AUDIO_EXTS:
                    abs_path = os.path.abspath(file_path).replace("\\", "/")
                    self._start_timeline_thumb_batch(abs_path, resolved)
            self._is_switching = False

    def _stop_timeline_thumb_batch(self) -> None:
        thread = getattr(self, "thumb_thread", None)
        if not thread:
            return
        try:
            thread.finished_generation.disconnect(self._on_timeline_thumb_batch_done)
        except (TypeError, RuntimeError):
            pass
        thread.stop()
        self.thumb_thread = None
        self._set_timeline_batch_thumbs_busy(False)

    def _on_timeline_thumb_batch_done(self, thumb_dir: str) -> None:
        sender = self.sender()
        if sender is not getattr(self, "thumb_thread", None):
            logging.debug("Ignored stale thumb batch completion for %s", thumb_dir)
            return
        if getattr(sender, "_cancelled", False):
            return
        expected = getattr(sender, "mpd_path", "")
        current = ""
        if hasattr(self, "custom_timeline"):
            current = getattr(self.custom_timeline, "current_video_path", "") or ""
        if PreviewSniperWorker._norm_media_path(expected) != PreviewSniperWorker._norm_media_path(current):
            logging.debug(
                "Ignored thumb batch for wrong clip (got %s, playing %s)",
                expected, current,
            )
            return
        if hasattr(self, "custom_timeline"):
            self.custom_timeline.thumb_dir = thumb_dir
        self._set_timeline_batch_thumbs_busy(False)

    def _start_timeline_thumb_batch(self, abs_path: str, duration_sec: float) -> None:
        if duration_sec < 1.0:
            self._stop_timeline_thumb_batch()
            if hasattr(self, "custom_timeline"):
                self.custom_timeline.thumb_dir = None
            return

        self._stop_timeline_thumb_batch()
        self._set_timeline_batch_thumbs_busy(True)

        self.thumb_thread = ThumbnailBatchThread(abs_path, duration_sec, interval=3)
        if hasattr(self, "custom_timeline"):
            self.custom_timeline.thumb_dir = self.thumb_thread.thumb_dir
        self.thumb_thread.finished_generation.connect(self._on_timeline_thumb_batch_done)
        self.thumb_thread.start()

    def schedule_play_media_file(self, file_path: str, delay_ms: int = 220):
        """Debounce rendered-file preview so rapid grid clicks don't wedge MPV."""
        if not file_path:
            return
        if not hasattr(self, "_rendered_play_timer"):
            self._rendered_play_timer = QTimer(self.ui)
            self._rendered_play_timer.setSingleShot(True)
            self._rendered_play_timer.timeout.connect(self._flush_scheduled_media_play)
        self._pending_rendered_play_path = file_path
        self._rendered_play_timer.start(delay_ms)

    def _flush_scheduled_media_play(self):
        path = getattr(self, "_pending_rendered_play_path", None)
        if path and os.path.isfile(path):
            self.play_media_file(path)

    def play_media_file(self, file_path: str):
        """Play a plain exported media file (mp4, mp3, etc.) in the preview player."""
        if not file_path or not os.path.isfile(file_path):
            return

        from steempeg.ui.library.rendered_library import RENDERED_AUDIO_EXTS, RENDERED_VIDEO_EXTS
        from steempeg.core.rendered_media import load_markers_sidecar, markers_to_canvas

        switch_gen = self._begin_preview_switch()
        self._is_switching = True
        self._force_pause = False
        self.current_clip_duration_sec = 0
        self._active_play_media_path = file_path
        self._preview_clip_path = file_path
        self._rendered_media_path = file_path
        self._rendered_duration_cache = None
        self._pending_trim_restore = None
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()
        self._current_mpd_abs_path = None
        self._eof_rewind_pending = 0

        if hasattr(self, "custom_timeline"):
            canvas = self.custom_timeline.canvas
            canvas.rendered_media_path = file_path
            if hasattr(self, "cache_dir"):
                sidecar_entries = load_markers_sidecar(self.cache_dir, file_path)
                canvas.markers.extend(markers_to_canvas(sidecar_entries))
            canvas.update()

        self.ui.video_container.setStyleSheet("background-color: transparent;")
        self._awaiting_first_frame = True
        if hasattr(self, "video_stack") and hasattr(self, "video_blank_frame"):
            self.video_stack.setCurrentWidget(self.video_blank_frame)
        if hasattr(self, "set_player_header_clip_controls_visible"):
            self.set_player_header_clip_controls_visible(True)
        if hasattr(self, "custom_timeline"):
            self.custom_timeline.setEnabled(True)

        abs_path = os.path.abspath(file_path).replace("\\", "/")

        if hasattr(self, "custom_timeline"):
            self.custom_timeline.current_video_path = abs_path
            self.custom_timeline.thumb_dir = None
            self.custom_timeline.set_duration(0)

        logging.info("MPV play file: %s", abs_path)
        self._playback_last_time_pos = None
        self._playback_stall_since = None
        self._ignore_playback_stall(0.35)

        # Pre-seed duration from sidecar / source clip before MPV reports garbage headers.
        meta = load_rendered_companion_meta(file_path) or {}
        seed_dur = meta.get("duration_sec")
        if not is_sane_media_duration(seed_dur):
            seed_dur = duration_from_source_clip((meta.get("clip_path") or "").strip())
        if is_sane_media_duration(seed_dur):
            self._apply_playback_duration(float(seed_dur))
            self._rendered_duration_cache = (os.path.normpath(file_path), float(seed_dur))

        try:
            self.player.play(abs_path)
            self.player.pause = False
        except Exception as exc:
            logging.error("MPV play file failed for %s: %s", abs_path, exc)
            self._is_switching = False
            return

        QTimer.singleShot(80, self._apply_saved_preview_quality_to_player)

        if hasattr(self, "custom_timeline") and hasattr(self.custom_timeline, "canvas"):
            self.custom_timeline.canvas.playback_speed = float(getattr(self.player, "speed", 1.0) or 1.0)

        self._first_frame_deadline = time.time() + 0.6
        QTimer.singleShot(30, self._reveal_video_when_ready)

        if hasattr(self, "thumb_thread") and self.thumb_thread and self.thumb_thread.isRunning():
            self.thumb_thread.stop()

        QTimer.singleShot(80, lambda: self._poll_rendered_media_duration(file_path, switch_gen))

        if hasattr(self.ui, "btn_play"):
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_pause.png")))

    def generate_and_play_preview(self, clip_path=None, trim_restore=None, force=False, mpd_override=None):
        """ Instantly loads and plays the Steam .mpd playlist using MPV. No proxy needed!

        force=True bypasses the dead-clip guard for a best-effort "salvage" preview
        (may show corrupted video, audio only, or nothing — entirely on the user).
        mpd_override plays a specific manifest directly (used for salvage manifests
        that the health/discovery scanners intentionally ignore)."""
        self._rendered_media_path = None
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()
        if clip_path is None:
            if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
                return
            clip_path = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).data(Qt.UserRole)

        if not clip_path or not os.path.isdir(clip_path):
            return

        if hasattr(self, "_is_valid_clip_path") and not self._is_valid_clip_path(clip_path):
            logging.warning("Ignored invalid clip preview path: %s", clip_path)
            return

        if hasattr(self, "get_clip_health_report"):
            report = self.get_clip_health_report(clip_path)
            logging.info(
                "Preview request: %s — health=%s issues=%s",
                clip_path,
                report.level.name,
                report.issues,
            )
            already_salvaged = (
                hasattr(self, "_is_salvaged_clip") and self._is_salvaged_clip(clip_path)
            )
            if report.level == health.ClipHealth.DEAD and not force and not already_salvaged:
                if (
                    hasattr(self, "_is_clip_cured")
                    and self._is_clip_cured(clip_path)
                    and hasattr(self, "_is_salvage_auto_play")
                    and self._is_salvage_auto_play(clip_path)
                    and hasattr(self, "force_play_dead_clip")
                ):
                    self.force_play_dead_clip(clip_path, skip_confirm=True, skip_verify=True)
                    return
                logging.warning("Blocked dead clip preview: %s", clip_path)
                self._preview_clip_path = clip_path
                self._selected_queue_job_id = None
                self._clear_player_surface()
                if hasattr(self, '_reset_player_placeholder_default'):
                    self._reset_player_placeholder_default()
                if hasattr(self, "set_player_header_clip_controls_visible"):
                    self.set_player_header_clip_controls_visible(False)
                if hasattr(self.ui, 'btn_start'):
                    self.ui.btn_start.setEnabled(False)
                if hasattr(self, 'update_playback_badge'):
                    self.update_playback_badge()
                if hasattr(self, 'update_clip_health_button'):
                    self.update_clip_health_button()

                # Dead, but not necessarily hopeless: offer a salvage attempt instead
                # of a dead-end warning. Yes -> force_play_dead_clip (shows its own
                # disclaimer + rebuilds a manifest). No -> stay blocked.
                issues = report.issues[:6]
                from steempeg.ui.dead_clip_dialogs import DeadClipOfferDialog, dialog_theme

                offer = DeadClipOfferDialog(issues, parent=self.ui, **dialog_theme(self))
                if offer.exec() and offer.accepted_yes and hasattr(self, "force_play_dead_clip"):
                    self.force_play_dead_clip(clip_path)
                return

        self._pending_trim_restore = trim_restore

        # 1. STOP CURRENT PLAYBACK
        self._is_switching = True
        self._force_pause = False

        # 2. GET THE CLIP FOLDER PATH
        
        # STEP 1: FIND THE VIDEO FOLDER
        all_mpds = [mpd_override] if mpd_override else self.get_all_mpd_paths(clip_path)
        if not all_mpds:
            logging.warning("No MPD found for clip: %s", clip_path)
            self._is_switching = False
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
            self.custom_timeline.canvas.rendered_media_path = None
            if json_path:
                logging.debug("Timeline JSON: %s", json_path)
                
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
                        logging.debug("Timeline offset calc failed: %s", e)
                        offset_ms = 0

                logging.debug("Timeline offset: %d ms", offset_ms)
                canvas = self.custom_timeline.canvas
                canvas.load_timeline_json(json_path, offset_ms, clip_path=clip_path)
                app_id = canvas.current_app_id
                if app_id:
                    canvas.marker_store.prefetch(
                        app_id,
                        on_ready=canvas.update,
                    )
                
            else:
                logging.debug("No timeline JSON for clip: %s", clip_path)
                self.custom_timeline.canvas.markers.clear()
                self.custom_timeline.canvas.update()


        # 3. PREPARE THE CANVAS
        # Show a plain BLACK page (not the bare mpv surface, not the "Ready to play"
        # poster) until the new clip's first frame is actually decoded. Switching to the
        # mpv surface immediately exposed mpv's stale/last frame for a split second on
        # every load — the flash the user saw (most reliably right after Refresh).
        # _reveal_video_when_ready flips to the live video once the first frame exists.
        self.ui.video_container.setStyleSheet("background-color: transparent;")
        self._awaiting_first_frame = True
        if hasattr(self, 'video_stack') and hasattr(self, 'video_blank_frame'):
            self.video_stack.setCurrentWidget(self.video_blank_frame)
        if hasattr(self, "set_player_header_clip_controls_visible"):
            self.set_player_header_clip_controls_visible(True)
        if hasattr(self, 'update_playback_badge'):
            self.update_playback_badge()
        if hasattr(self, 'update_clip_health_button'):
            self.update_clip_health_button()
        if hasattr(self, 'custom_timeline'): 
            self.custom_timeline.setEnabled(True)

        # 4. FEED THE RAW STEAM DASH FILE DIRECTLY TO MPV
        logging.info("MPV play: %s (clip=%s)", mpd_path, clip_path)
        
        # A Reliable Path for Windows:
        abs_path = os.path.abspath(mpd_path).replace('\\', '/')

        if hasattr(self, 'custom_timeline'):
            self.custom_timeline.current_video_path = abs_path
            self.custom_timeline.thumb_dir = None

        # Remember the source so the EOF watchdog can reopen it if a rewind wedges
        # ffmpeg's DASH demuxer (see update_ui_from_vlc / _reopen_current_clip_paused).
        self._current_mpd_abs_path = abs_path
        self._eof_rewind_pending = 0

        self._playback_last_time_pos = None
        self._playback_stall_since = None
        self._ignore_playback_stall(0.35)

        try:
            self.player.play(abs_path)
            self.player.pause = False
        except Exception as exc:
            logging.error("MPV play failed for %s: %s", abs_path, exc)
            self._is_switching = False
            return

        QTimer.singleShot(80, self._apply_saved_preview_quality_to_player)

        # Keep the timeline interpolation in sync with mpv's current rate from the start
        # (the speed setting persists across clips), so the playhead doesn't jitter.
        if hasattr(self, 'custom_timeline') and hasattr(self.custom_timeline, 'canvas'):
            self.custom_timeline.canvas.playback_speed = float(getattr(self.player, 'speed', 1.0) or 1.0)

        # Reveal the live video only once the first frame is ready (see step 3).
        self._first_frame_deadline = time.time() + 0.6
        QTimer.singleShot(30, self._reveal_video_when_ready)

        # --- BACKGROUND THUMBNAIL BATCH GENERATION (THE MATRIX 2.0) ---
        if hasattr(self, 'thumb_thread') and self.thumb_thread.isRunning():
            self.thumb_thread.stop()

        clip_dur = float(getattr(self, 'current_clip_duration_sec', 0) or 0)
        if clip_dur >= 1.0:
            self._start_timeline_thumb_batch(abs_path, clip_dur)
        elif hasattr(self, 'custom_timeline'):
            self.custom_timeline.thumb_dir = None
            self._set_timeline_batch_thumbs_busy(False)
        
        if hasattr(self, 'custom_timeline'):
            def finish_switch():
                self.custom_timeline.setEnabled(True)
                self._is_switching = False
                if getattr(self, "_pending_trim_restore", None):
                    QTimer.singleShot(150, self._deferred_apply_trim_restore)
                elif hasattr(self, "_loading_queue_job"):
                    self._loading_queue_job = False

            QTimer.singleShot(500, finish_switch)

        if hasattr(self, '_maybe_offer_salvage_verification'):
            QTimer.singleShot(600, self._maybe_offer_salvage_verification)

        # --- IMMEDIATELY UPDATE PLAY BUTTON ICON TO PAUSE ---
        if hasattr(self.ui, 'btn_play'):
            icon_path = get_resource_path("icon_pause.png")
            self.ui.btn_play.setIcon(QIcon(icon_path))
        

    def _apply_video_border(self, active):
        """Toggle the yellow trim border only when it actually changes.

        aspect_frame is the MPVWrapper: setStyleSheet there repositions the native
        mpv surface, so we cache the last state and no-op when nothing changed to
        avoid moving native windows 60x/sec during playback.
        """
        if getattr(self, '_video_border_active', None) == active:
            return
        self._video_border_active = active
        if not hasattr(self, 'aspect_frame'):
            return
        color = "#ffcc00" if active else "transparent"
        self.aspect_frame.setStyleSheet(f"border: 3px solid {color}; background-color: transparent;")

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
            duration_sec = self._playback_duration_sec()
            if duration_sec is None or duration_sec <= 0:
                return
                
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
            max_ms = 48 * 3600 * 1000
            duration_ms = max(0, min(duration_ms, max_ms))
            
            # MPV sometimes returns None for time_pos at the exact moment the video ends
            if time_sec is None:
                if getattr(self.player, 'eof_reached', False):
                    time_sec = duration_sec 
                else:
                    return
                    
            current_ms = int(time_sec * 1000)
            current_ms = max(0, min(current_ms, duration_ms if duration_ms > 0 else max_ms))

            if hasattr(self, "_record_salvage_playback_evidence"):
                self._record_salvage_playback_evidence()

            canvas = getattr(getattr(self, 'custom_timeline', None), 'canvas', None)
            user_scrubbing = canvas is not None and canvas.drag_state == 'playhead'
            at_end = (
                getattr(self.player, 'eof_reached', False)
                or (duration_ms > 0 and current_ms >= duration_ms - 50)
            )

            if at_end:
                current_ms = min(current_ms, duration_ms)
                if user_scrubbing:
                    pass
                elif not self.player.pause:
                    self.player.pause = True
                    if hasattr(self.ui, 'btn_play'):
                        self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))
            else:
                self._eof_rewind_pending = 0

            is_playing = not self.player.pause

            # Send the data to our smooth custom timeline
            if hasattr(self, 'custom_timeline'):
                self.custom_timeline.set_duration(duration_ms)
                self.custom_timeline.set_vlc_time(current_ms, is_playing)

            # --- UPDATE TEXT TIMERS (00:00 / 00:00) ---
            def format_time(ms):
                """ Converts milliseconds into HH:MM:SS or MM:SS format """
                ms = max(0, min(int(ms), max_ms))
                s = ms // 1000
                h = s // 3600
                m = (s % 3600) // 60
                s = s % 60

                if h > 0:
                    return f"{h:02d}:{m:02d}:{s:02d}"
                return f"{m:02d}:{s:02d}"
            
            # --- YELLOW BORDER INDICATOR ---
            # aspect_frame is the MPVWrapper; its setStyleSheet repositions the native
            # mpv window. Calling it every 16ms tick while playing is what makes a
            # splitter drag stutter during playback, so only restyle on state change.
            want_yellow = False
            if not getattr(self, 'is_fullscreen', False):
                tl = getattr(self, 'custom_timeline', None)
                if tl is not None and tl.is_trim_mode:
                    want_yellow = tl.trim_start_ms <= current_ms <= tl.trim_end_ms
            self._apply_video_border(want_yellow)

            # --- BUFFERING INDICATOR (native mpv OSD, no Qt overlay) ---
            self._update_playback_loading_state()

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
        
        rendered_path = getattr(canvas, "rendered_media_path", None)
        if rendered_path and os.path.isfile(rendered_path) and hasattr(self, "cache_dir"):
            from steempeg.core.rendered_media import canvas_markers_to_sidecar, save_markers_sidecar
            save_markers_sidecar(
                self.cache_dir,
                rendered_path,
                canvas_markers_to_sidecar(markers_list),
            )
            return

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
            
        saved_ok = False
        try:
            self.player.command('screenshot-to-file', filepath, 'video')
            print(f"📸 Screenshot saved to: {filepath}")
            saved_ok = True
        except Exception as e:
            print(f"Screenshot error: {e}")
            
        # We jump back in as if nothing had happened.
        if need_seek:
            self.player.seek(original_pos / 1000.0, reference='absolute', precision='exact')

        if saved_ok:
            self._show_screenshot_toast(self.screenshots_dir, screenshot_path=filepath)

    def _steam_screenshot_marker_context(self, marker):
        """Resolve Steam user, app id, and screenshot folder for a timeline marker."""
        from steempeg.core.steam_screenshots import (
            resolve_steam_id_for_clip,
            steam_screenshots_dir,
            timeline_json_start_utc,
        )

        if not hasattr(self, "custom_timeline"):
            return None
        canvas = self.custom_timeline.canvas
        clip_path = getattr(canvas, "current_clip_path", None) or getattr(
            self, "_preview_clip_path", None
        )
        app_id = getattr(canvas, "current_app_id", None)
        if not clip_path or not app_id:
            steempeg_information(
                self.ui,
                "Screenshot",
                "Open a Steam Game Recording clip first — screenshot lookup needs the clip folder.",
            )
            return None

        steam_id = resolve_steam_id_for_clip(
            clip_path, getattr(self, "clips_folders", None) or []
        )
        if not steam_id:
            steempeg_information(
                self.ui,
                "Screenshot",
                "Could not determine your Steam user id from the library folder path.",
            )
            return None

        marker_ms = float(marker.get("time_ms", 0))
        raw_time_ms = marker.get("raw_time_ms")
        if raw_time_ms is None:
            raw_time_ms = marker_ms + float(getattr(canvas, "current_offset_ms", 0) or 0)
        else:
            raw_time_ms = float(raw_time_ms)

        json_start_utc = getattr(canvas, "current_json_start_utc", None)
        if json_start_utc is None:
            json_start_utc = timeline_json_start_utc(getattr(canvas, "current_json_path", None))

        return {
            "clip_path": clip_path,
            "steam_id": steam_id,
            "app_id": str(app_id),
            "marker_ms": marker_ms,
            "raw_time_ms": raw_time_ms,
            "json_start_utc": json_start_utc,
            "folder": steam_screenshots_dir(steam_id, str(app_id)),
        }

    def open_steam_screenshot_for_marker(self, marker):
        """Open the Steam client screenshot that matches a timeline screenshot marker."""
        from steempeg.core.steam_screenshots import find_steam_screenshot_files

        ctx = self._steam_screenshot_marker_context(marker)
        if not ctx:
            return

        files = find_steam_screenshot_files(
            steam_id=ctx["steam_id"],
            app_id=ctx["app_id"],
            json_start_utc=ctx["json_start_utc"],
            raw_time_ms=ctx["raw_time_ms"],
            clip_path=ctx["clip_path"],
            marker_time_ms=ctx["marker_ms"],
        )
        if not files:
            steempeg_information(
                self.ui,
                "Screenshot",
                "No matching Steam screenshot was found on disk.\n\n"
                f"Looked in:\n{ctx['folder']}\n\n"
                "Steam names files like 20260711152410_1.jpg (local date/time when captured).",
            )
            return

        if len(files) == 1:
            self._open_file_with_default_app(files[0])
            return

        pick = QMenu(self.ui)
        pick.setStyleSheet("""
            QMenu { background-color: #2d2d2d; color: #ffffff; border: 2px solid #444444;
                    border-radius: 8px; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
            QMenu::item { padding: 6px 24px; border-radius: 4px; margin: 2px 4px; }
            QMenu::item:selected { background-color: #6b5a8e; }
        """)
        for path in files:
            action = pick.addAction(os.path.basename(path))
            action.triggered.connect(
                lambda _checked=False, p=path: self._open_file_with_default_app(p)
            )
        pick.exec(QCursor.pos())

    def open_steam_screenshot_folder_for_marker(self, marker):
        """Open the Steam screenshots folder with the matching screenshot selected."""
        from steempeg.core.steam_screenshots import find_steam_screenshot_files
        from steempeg.infra.paths import open_in_file_manager, reveal_in_file_manager

        ctx = self._steam_screenshot_marker_context(marker)
        if not ctx:
            return

        files = find_steam_screenshot_files(
            steam_id=ctx["steam_id"],
            app_id=ctx["app_id"],
            json_start_utc=ctx["json_start_utc"],
            raw_time_ms=ctx["raw_time_ms"],
            clip_path=ctx["clip_path"],
            marker_time_ms=ctx["marker_ms"],
        )
        if not files:
            folder = ctx["folder"]
            if os.path.isdir(folder):
                open_in_file_manager(folder)
            else:
                steempeg_information(
                    self.ui,
                    "Screenshot folder",
                    "Steam screenshot folder was not found on disk.\n\n"
                    f"Expected:\n{folder}",
                )
            return

        if len(files) == 1:
            reveal_in_file_manager(files[0])
            return

        pick = QMenu(self.ui)
        pick.setStyleSheet("""
            QMenu { background-color: #2d2d2d; color: #ffffff; border: 2px solid #444444;
                    border-radius: 8px; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
            QMenu::item { padding: 6px 24px; border-radius: 4px; margin: 2px 4px; }
            QMenu::item:selected { background-color: #6b5a8e; }
        """)
        for path in files:
            action = pick.addAction(os.path.basename(path))
            action.triggered.connect(
                lambda _checked=False, p=path: reveal_in_file_manager(p)
            )
        pick.exec(QCursor.pos())

    @staticmethod
    def _open_file_with_default_app(path: str) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(os.path.normpath(path))  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except OSError as exc:
            logging.error("Failed to open file %s: %s", path, exc)

    def _show_screenshot_toast(self, directory, *, screenshot_path=None):
        """Flash a small 'Screenshot saved in <dir>' toast with copy/open actions."""
        directory = os.path.normpath(directory)

        toast = getattr(self, '_screenshot_toast', None)
        if toast is None:
            toast = QWidget(self.ui)
            toast.setObjectName("screenshotToastHost")
            toast.setWindowFlags(
                Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
            )
            toast.setAttribute(Qt.WA_ShowWithoutActivating, True)
            toast.setAttribute(Qt.WA_TranslucentBackground, True)

            shell = QVBoxLayout(toast)
            shell.setContentsMargins(0, 0, 0, 0)

            panel = QFrame(toast)
            panel.setObjectName("screenshotToast")
            panel.setStyleSheet(
                "QFrame#screenshotToast { background-color: #1f1f1f; border: 1px solid #6b5a8e;"
                " border-radius: 10px; }"
                " QLabel { color: #e8e8e8; background: transparent; font-size: 12px;"
                " font-family: 'Segoe UI', Arial, sans-serif; }"
                " QPushButton { background-color: #4a3f63; color: #ffffff; border: none;"
                " border-radius: 7px; padding: 5px 12px; font-weight: bold; font-size: 11px; }"
                " QPushButton:hover { background-color: #6b5a8e; }"
            )
            row = QHBoxLayout(panel)
            row.setContentsMargins(14, 10, 12, 10)
            row.setSpacing(10)

            label = QLabel(panel)
            label.setObjectName("screenshotToastLabel")
            row.addWidget(label)

            copy_btn = QPushButton("📋 Copy path", panel)
            copy_btn.setCursor(Qt.PointingHandCursor)
            row.addWidget(copy_btn)

            open_btn = QPushButton("📂 Open folder", panel)
            open_btn.setCursor(Qt.PointingHandCursor)
            row.addWidget(open_btn)

            shell.addWidget(panel)

            self._screenshot_toast = toast
            self._screenshot_toast_label = label
            self._screenshot_toast_btn = copy_btn
            self._screenshot_toast_open_btn = open_btn
            self._screenshot_toast_timer = QTimer(toast)
            self._screenshot_toast_timer.setSingleShot(True)
            self._screenshot_toast_timer.timeout.connect(toast.hide)
            copy_btn.clicked.connect(self._copy_screenshot_dir)
            open_btn.clicked.connect(self._open_screenshot_dir)

        self._screenshot_toast_dir = directory
        self._screenshot_toast_file = screenshot_path if screenshot_path and os.path.isfile(screenshot_path) else None
        self._screenshot_toast_label.setText(f"📸 Screenshot saved in  {directory}")
        if hasattr(self, '_screenshot_toast_btn'):
            self._screenshot_toast_btn.setText("📋 Copy path")

        toast = self._screenshot_toast
        toast.adjustSize()

        # Anchor just above the camera button so it never spills off the bottom edge.
        anchor = getattr(self, 'btn_screenshot', None) or self.ui
        try:
            top_left = anchor.mapToGlobal(anchor.rect().topLeft())
            x = top_left.x() + anchor.width() - toast.width()
            y = top_left.y() - toast.height() - 8
        except Exception:
            geo = self.ui.geometry()
            x = geo.x() + (geo.width() - toast.width()) // 2
            y = geo.y() + geo.height() - toast.height() - 40
        toast.move(max(0, x), max(0, y))
        toast.show()
        toast.raise_()
        self._screenshot_toast_timer.start(5000)

    def _copy_screenshot_dir(self):
        directory = getattr(self, '_screenshot_toast_dir', None)
        if not directory:
            return
        QApplication.clipboard().setText(directory)
        if hasattr(self, '_screenshot_toast_btn'):
            self._screenshot_toast_btn.setText("✓ Copied")

    def _open_screenshot_dir(self):
        from steempeg.infra.paths import open_in_file_manager, reveal_in_file_manager

        directory = getattr(self, '_screenshot_toast_dir', None)
        screenshot_path = getattr(self, '_screenshot_toast_file', None)
        if screenshot_path and os.path.isfile(screenshot_path):
            reveal_in_file_manager(screenshot_path)
            return
        if directory and os.path.isdir(directory):
            open_in_file_manager(directory)
            return
        logging.error("Failed to open screenshots folder: %s", directory)

    def _init_preview_quality(self) -> None:
        from steempeg.ui.player import preview_quality as pq

        saved = self.load_user_settings().get(pq.SETTINGS_KEY, pq.DEFAULT_QUALITY)
        self._preview_quality_id = pq.normalize_quality_id(saved)

    def _apply_saved_preview_quality_to_player(self, retry: int = 0) -> None:
        from steempeg.ui.player import preview_quality as pq

        preset_id = pq.normalize_quality_id(getattr(self, "_preview_quality_id", pq.DEFAULT_QUALITY))
        player = getattr(self, "player", None)
        if (
            player
            and preset_id != pq.DEFAULT_QUALITY
            and pq.source_height(player) <= 0
            and retry < 20
        ):
            QTimer.singleShot(80, lambda: self._apply_saved_preview_quality_to_player(retry + 1))
            return
        if not pq.apply_mpv_preview_quality(player, preset_id):
            self._preview_quality_id = pq.DEFAULT_QUALITY
            if hasattr(self, "save_user_settings"):
                self.save_user_settings(pq.SETTINGS_KEY, pq.DEFAULT_QUALITY)

    def set_preview_quality(self, preset_id: str, *, persist: bool = True) -> None:
        from steempeg.ui.player import preview_quality as pq

        preset_id = pq.normalize_quality_id(preset_id)
        if preset_id == getattr(self, "_preview_quality_id", None):
            return
        self._preview_quality_id = preset_id
        if not pq.apply_mpv_preview_quality(getattr(self, "player", None), preset_id):
            self._preview_quality_id = pq.DEFAULT_QUALITY
            preset_id = pq.DEFAULT_QUALITY
        if persist:
            self.save_user_settings(pq.SETTINGS_KEY, preset_id)

    def show_preview_quality_menu(self) -> None:
        from PySide6.QtGui import QActionGroup
        from PySide6.QtWidgets import QMenu

        from steempeg.ui.player import preview_quality as pq

        menu = QMenu(self.ui)
        menu.setStyleSheet(pq.menu_stylesheet())

        title = menu.addAction("Preview quality")
        title.setEnabled(False)

        group = QActionGroup(menu)
        group.setExclusive(True)
        current = pq.normalize_quality_id(getattr(self, "_preview_quality_id", pq.DEFAULT_QUALITY))

        for preset in pq.PRESETS:
            action = menu.addAction(preset.label)
            action.setCheckable(True)
            action.setChecked(preset.id == current)
            action.setData(preset.id)
            group.addAction(action)

        def _on_quality_picked(action) -> None:
            if action is None:
                return
            pid = action.data()
            if pid:
                QTimer.singleShot(0, lambda p=str(pid): self.set_preview_quality(p))

        group.triggered.connect(_on_quality_picked)

        menu.addSeparator()
        footnote = menu.addAction("Does not affect export")
        footnote.setEnabled(False)

        anchor = getattr(self, "btn_preview_settings", None)
        if anchor is not None:
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        else:
            menu.exec()