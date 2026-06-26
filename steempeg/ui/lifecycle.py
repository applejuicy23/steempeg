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
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from steempeg.infra import paths
from steempeg.infra.paths import get_resource_path
from steempeg.version import APP_VERSION_STR


_ABOUT_DIALOG_STYLE = """
    QDialog {
        background-color: #202020;
        border: 1px solid #444444;
        border-radius: 8px;
    }
    QLabel { background: transparent; }
    QLabel#AboutTitle { color: #b29ae7; font-size: 22px; font-weight: bold; }
    QLabel#AboutDim { color: #888888; font-size: 11px; }
    QLabel#AboutText { color: #dddddd; font-size: 12px; }
    QLabel#AboutDisclaimer { color: #777777; font-size: 9px; font-style: italic; }
    QPushButton {
        background-color: #333333;
        color: white;
        border: 1px solid #555555;
        border-radius: 16px;
        padding: 6px 24px;
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
"""


def _crisp_icon(path, size, dpr=2.0):
    """Smoothly-scaled, HiDPI-aware icon so embedded logos aren't pixelated."""
    pix = QPixmap(path)
    if pix.isNull():
        return pix
    scaled = pix.scaled(
        int(size * dpr), int(size * dpr),
        Qt.KeepAspectRatio, Qt.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(dpr)
    return scaled


class LifecycleMixin:
    def eventFilter(self, source, event):
        if getattr(self, '_is_closing', False):
            return False

        # --- FLOATING PANEL RESIZE LOGIC ---
        if source == self.ui and event.type() == QEvent.Type.Resize:
            if getattr(self, 'is_fullscreen', False):
                if hasattr(self, '_position_immersive_esc_hint'):
                    self._position_immersive_esc_hint()
                if hasattr(self, 'align_fullscreen_hud'):
                    self.align_fullscreen_hud()
            return False

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
                    
        # 2. Disable right-click selection in the Grid; handle LMB selection on cards manually
        if hasattr(self, 'grid_clips') and source == self.grid_clips.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    click_pos = event.position().toPoint()
                    self.show_grid_context_menu(click_pos)
                    return True
                if event.button() == Qt.LeftButton and hasattr(self, '_handle_grid_viewport_press'):
                    return self._handle_grid_viewport_press(event)
            if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.LeftButton:
                return True

        return super().eventFilter(source, event)
    
    def set_status(self, text):
        """Updates the render status row (delegates to update_status_indicator when available)."""
        if hasattr(self, 'update_status_indicator'):
            state = "ready"
            if text == "Error!":
                state = "error"
            elif text == "Success":
                state = "success"
            elif text == "Cancelled":
                state = "error"
            elif "%" in text or text.endswith(".."):
                state = "rendering"
            self.update_status_indicator(text, state)
            return

        if hasattr(self.ui, 'label_status'):
            self.ui.label_status.setText(text.split('..')[0] + '..')

        if hasattr(self.ui, 'progress_render'):
            if text in ["Ready", "Success", "Cancelled", "Error!"]:
                self.ui.progress_render.setValue(0)
                if hasattr(self, 'label_pct'):
                    self.label_pct.setText("0%")
                if text != "Error!":
                    self.ui.label_status.setText(text)

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

        # Tear down the floating buffering window so it can't linger as a ghost.
        overlay = getattr(self, '_buffering_overlay', None)
        if overlay is not None:
            overlay.hide_loading()
            overlay.deleteLater()
            self._buffering_overlay = None

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

        if hasattr(self, "_persist_render_queue"):
            self._persist_render_queue()

        if hasattr(self.ui, "main_splitter"):
            self.save_layout_setting("main_splitter_sizes", self.ui.main_splitter.sizes())
        if hasattr(self, "right_h_splitter"):
            sizes = self.right_h_splitter.sizes()
            if len(sizes) >= 2 and sizes[1] > 0:
                self.save_layout_setting("queue_panel_width", sizes[1])

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
    
    def _about_icon_row(self, icon_file, html_text):
        """A crisp icon + clickable rich-text label, laid out in one row."""
        row = QHBoxLayout()
        row.setSpacing(8)

        icon = QLabel()
        pix = _crisp_icon(get_resource_path(icon_file), 18)
        if not pix.isNull():
            icon.setPixmap(pix)
        icon.setFixedWidth(20)
        icon.setAlignment(Qt.AlignVCenter)
        row.addWidget(icon)

        text = QLabel(html_text)
        text.setObjectName("AboutText")
        text.setOpenExternalLinks(True)
        text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        row.addWidget(text)
        row.addStretch()
        return row

    def show_about_dialog(self):
        """ Frameless About dialog styled like the FFmpeg render-error window. """
        if getattr(self, '_about_is_open', False):
            return  # Block if already open
        self._about_is_open = True

        link = "color:#b29ae7; text-decoration:none;"

        dialog = QDialog(self.ui)
        dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        dialog.setFixedSize(620, 470)
        dialog.setStyleSheet(_ABOUT_DIALOG_STYLE)

        main_layout = QHBoxLayout(dialog)
        main_layout.setContentsMargins(26, 26, 26, 22)
        main_layout.setSpacing(24)

        # --- Left: the program logo (smoothly scaled, never pixelated) ---
        logo_label = QLabel()
        logo_pix = _crisp_icon(get_resource_path("logo.png"), 120, dpr=1.0)
        if not logo_pix.isNull():
            logo_label.setPixmap(logo_pix)
        logo_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        logo_label.setFixedWidth(128)
        main_layout.addWidget(logo_label)

        # --- Right: the content column ---
        content = QVBoxLayout()
        content.setSpacing(9)

        title = QLabel(f"Steempeg v{APP_VERSION_STR}")
        title.setObjectName("AboutTitle")
        content.addWidget(title)

        build = QLabel(f"Build: v{APP_VERSION_STR}")
        build.setObjectName("AboutDim")
        content.addWidget(build)

        dev = QLabel(
            'Developer: <b>Emily</b> 🎀 '
            '<span style="color:#888888;">@applejuicy23</span>'
        )
        dev.setObjectName("AboutText")
        content.addWidget(dev)

        content.addLayout(self._about_icon_row(
            "github.jpg",
            f'<b>GitHub:</b> <a href="https://github.com/applejuicy23/steempeg" '
            f'style="{link}">applejuicy23/steempeg</a>',
        ))
        content.addLayout(self._about_icon_row(
            "steam.png",
            f'<b>Steam:</b> <a href="https://steamcommunity.com/id/applejuicy23/" '
            f'style="{link}">applejuicy23</a>',
        ))

        desc = QLabel(
            "A smart, elegant, and fast hardware-accelerated video renderer "
            "for Steam Clips."
        )
        desc.setObjectName("AboutText")
        desc.setWordWrap(True)
        content.addWidget(desc)

        powered = QLabel(
            'Powered by '
            f'<a href="https://github.com/ffmpeg/ffmpeg" style="{link}">FFmpeg</a>, '
            f'<a href="https://github.com/pyav-org/pyav" style="{link}">PyAV</a> &amp; '
            f'<a href="https://github.com/mpv-player/mpv" style="{link}">MPV</a>.'
        )
        powered.setObjectName("AboutText")
        powered.setWordWrap(True)
        powered.setOpenExternalLinks(True)
        powered.setTextInteractionFlags(Qt.TextBrowserInteraction)
        content.addWidget(powered)

        thanks = QLabel(
            "Special thanks to these projects — without them Steempeg "
            "simply wouldn't exist. 💜"
        )
        thanks.setObjectName("AboutDim")
        thanks.setWordWrap(True)
        content.addWidget(thanks)

        content.addStretch()

        disclaimer = QLabel(
            "Steempeg is an unofficial, community-created tool.\n"
            "Not affiliated with, associated with, authorized, or endorsed by "
            "Valve Corporation or Steam."
        )
        disclaimer.setObjectName("AboutDisclaimer")
        disclaimer.setWordWrap(True)
        content.addWidget(disclaimer)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(dialog.accept)
        btn_row.addWidget(btn_close)
        content.addLayout(btn_row)

        main_layout.addLayout(content)

        dialog.exec()
        self._about_is_open = False  # Release the lock when closed


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