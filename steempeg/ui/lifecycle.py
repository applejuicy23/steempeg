"""Application lifecycle and chrome, mixed into the main application.

These methods cover the status bar, the global event filter, window close and
exit cleanup, the About dialog, opening the logs, path elision and resetting
per-clip state. They run on the application instance and reach its widgets and
state through self.
"""
import logging
import os
import re

import psutil

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, QItemSelectionModel
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra import logging as log_util
from steempeg.infra import paths
from steempeg.infra.paths import get_resource_path
from steempeg.version import APP_VERSION_STR


_LOGS_MENU_STYLE = """
    QMenu {
        background-color: #2d2d2d;
        color: #ffffff;
        border: 2px solid #444444;
        border-radius: 8px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 13px;
        font-weight: bold;
        padding: 4px 0;
    }
    QMenu::item {
        padding: 8px 28px 8px 20px;
        border-radius: 4px;
        margin: 2px 6px;
    }
    QMenu::item:selected {
        background-color: #3a324a;
        color: #b29ae7;
    }
    QMenu::separator {
        height: 1px;
        background: #444444;
        margin: 4px 10px;
    }
"""


_ABOUT_DIALOG_STYLE = """
    QWidget#AboutCard {
        background-color: #202020;
        border: 1px solid #444444;
        border-radius: 8px;
    }
    QLabel { background: transparent; }
    QLabel#AboutTitle { color: #b29ae7; font-size: 22px; font-weight: bold; }
    QLabel#AboutDim { color: #888888; font-size: 11px; }
    QLabel#AboutText { color: #dddddd; font-size: 12px; }
    QLabel#AboutDisclaimer {
        color: #8a8a8a;
        font-size: 10px;
        font-style: italic;
    }
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
    QPushButton#AboutReportBtn {
        background-color: #4a2525;
        border: 1px solid #7a3535;
        color: #ffffff;
    }
    QPushButton#AboutReportBtn:hover {
        background-color: #6a2e2e;
        border: 1px solid #9a4545;
    }
    QPushButton#AboutReportBtn:pressed {
        background-color: #3a1d1d;
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

        if hasattr(self, 'mpv_wrapper') and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
        ):
            tracked = (
                getattr(self.ui, 'right_panel', None),
                getattr(self, 'video_wrapper', None),
                getattr(self, 'aspect_frame', None),
                getattr(self.ui, 'video_container', None),
            )
            if source in tracked:
                self.mpv_wrapper.update_geometry()
            return False

        # 1. Disable right-click selection in the Table (List)
        if hasattr(self.ui, 'table_clips') and source == self.ui.table_clips.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    click_pos = event.position().toPoint()
                    self.show_clip_context_menu(click_pos)
                    return True
                if event.button() == Qt.LeftButton:
                    mods = event.modifiers()
                    if (mods & Qt.AltModifier) and not (mods & Qt.ShiftModifier):
                        index = self.ui.table_clips.indexAt(event.position().toPoint())
                        if index.isValid():
                            self.ui.table_clips.selectionModel().select(
                                index,
                                QItemSelectionModel.SelectionFlag.Toggle
                                | QItemSelectionModel.SelectionFlag.Rows,
                            )
                            self.ui.table_clips.setCurrentIndex(index)
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

        if hasattr(self, 'table_rendered') and source == self.table_rendered.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    if hasattr(self, 'show_rendered_table_context_menu'):
                        self.show_rendered_table_context_menu(event.position().toPoint())
                    return True
                if event.button() == Qt.LeftButton:
                    mods = event.modifiers()
                    if (mods & Qt.AltModifier) and not (mods & Qt.ShiftModifier):
                        index = self.table_rendered.indexAt(event.position().toPoint())
                        if index.isValid():
                            self.table_rendered.selectionModel().select(
                                index,
                                QItemSelectionModel.SelectionFlag.Toggle
                                | QItemSelectionModel.SelectionFlag.Rows,
                            )
                            self.table_rendered.setCurrentIndex(index)
                            return True

        if hasattr(self, 'grid_rendered') and source == self.grid_rendered.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    click_pos = event.position().toPoint()
                    if hasattr(self, 'show_rendered_grid_context_menu'):
                        self.show_rendered_grid_context_menu(click_pos)
                    return True
                if event.button() == Qt.LeftButton and hasattr(self, '_handle_rendered_grid_viewport_press'):
                    return self._handle_rendered_grid_viewport_press(event)
            if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.LeftButton:
                return True

        return super().eventFilter(source, event)
    
    def _sync_mpv_surface_geometry(self, *args):
        """Re-pin the native mpv child HWND after splitter drags move the player panel."""
        wrapper = getattr(self, "mpv_wrapper", None)
        if wrapper is not None:
            wrapper.update_geometry()

    def _install_mpv_geometry_hooks(self):
        for splitter in (
            getattr(self.ui, "main_splitter", None),
            getattr(self, "right_h_splitter", None),
        ):
            if splitter is not None:
                splitter.splitterMoved.connect(self._sync_mpv_surface_geometry)

    def set_status(self, text):
        """Updates the render status row (delegates to update_status_indicator when available)."""
        if hasattr(self, 'update_status_indicator'):
            state = "ready"
            if text == "Error!":
                state = "error"
            elif text == "Success":
                state = "success"
            elif text == "Cancelled":
                state = "cancelled"
            elif "%" in text:
                state = "rendering"
            elif text.endswith("..."):
                state = "busy"
            elif text.endswith(".."):
                state = "busy"
            self.update_status_indicator(text, state)

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

        if hasattr(self, '_stop_timeline_thumb_batch'):
            self._stop_timeline_thumb_batch()
        if hasattr(self, 'custom_timeline') and hasattr(self.custom_timeline, 'canvas'):
            sniper = getattr(self.custom_timeline.canvas, 'sniper', None)
            if sniper:
                sniper.kill_worker()
                
        # 2. Killing the frozen FFmpeg
        try:
            import os
            import subprocess

            current_process = psutil.Process()
            # We are looking for all child processes launched by our program.
            children = current_process.children(recursive=True)
            for child in children:
                # If the process is named ffmpeg or ffprobe, terminate it.
                if "ffmpeg" in child.name().lower() or "ffprobe" in child.name().lower():
                    try:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", str(child.pid)],
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                capture_output=True,
                                timeout=5,
                            )
                        else:
                            child.kill()
                        print(f"Zombie proccess killed: {child.name()}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"⚠️ Error with killing zombie pcorsalfgn: {e}")

        if hasattr(self, "_persist_render_queue"):
            self._persist_render_queue()

        if hasattr(self, "_library_ui_persist_ready"):
            self._library_ui_persist_ready = True
        if hasattr(self, "_persist_library_ui_state"):
            self._persist_library_ui_state()

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
        if hasattr(self, "_library_ui_persist_ready"):
            self._library_ui_persist_ready = True
        if hasattr(self, "_persist_library_ui_state"):
            self._persist_library_ui_state()
        print("CLEANING BEFORE CLOSING...")
        if hasattr(self, '_stop_timeline_thumb_batch'):
            self._stop_timeline_thumb_batch()
        if hasattr(self, 'custom_timeline') and hasattr(self.custom_timeline, 'canvas'):
            sniper = getattr(self.custom_timeline.canvas, 'sniper', None)
            if sniper:
                sniper.kill_worker()
        if hasattr(self, 'player') and self.player:
            try:
                self.player.command('stop')
                self.player.terminate()
            except: pass
            
        # Killing all zombie FFmpeg child processes
        try:
            import os
            import subprocess

            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            for child in children:
                if "ffmpeg" in child.name().lower() or "ffprobe" in child.name().lower():
                    try:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/F", "/T", "/PID", str(child.pid)],
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                capture_output=True,
                                timeout=5,
                            )
                        else:
                            child.kill()
                        print(f"Killed FFmpeg after exit: {child.name()}")
                    except Exception:
                        pass
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
        # Make the window itself transparent so only the stylesheet's rounded rect is
        # painted; otherwise the square window background pokes out past the 8px radius.
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dialog.setFixedSize(620, 470)
        dialog.setStyleSheet(_ABOUT_DIALOG_STYLE)

        shell_layout = QVBoxLayout(dialog)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        card = QWidget(dialog)
        card.setObjectName("AboutCard")
        shell_layout.addWidget(card)

        main_layout = QHBoxLayout(card)
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

        content.addSpacing(18)

        disclaimer = QLabel(
            "Steempeg is an unofficial, community-created tool.\n"
            "Not affiliated with, associated with, authorized, or endorsed by "
            "Valve Corporation or Steam."
        )
        disclaimer.setObjectName("AboutDisclaimer")
        disclaimer.setWordWrap(True)
        content.addWidget(disclaimer)

        content.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_report = QPushButton("🐛  Report a bug")
        btn_report.setObjectName("AboutReportBtn")
        btn_report.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_report.clicked.connect(self.show_report_dialog)
        btn_close = QPushButton("Close")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(dialog.accept)
        btn_row.addWidget(btn_report)
        btn_row.addWidget(btn_close)
        content.addLayout(btn_row)

        main_layout.addLayout(content)

        dialog.exec()
        self._about_is_open = False  # Release the lock when closed


    def setup_logs_menu(self):
        """Attach a styled Logs dropdown to btn_logs."""
        if not hasattr(self.ui, 'btn_logs'):
            return
        menu = QMenu(self.ui)
        menu.setStyleSheet(_LOGS_MENU_STYLE)

        action_app = menu.addAction("📄  App + FFmpeg logs")
        action_mpv = menu.addAction("🎬  MPV player log")
        action_folder = menu.addAction("📂  Open logs folder")
        menu.addSeparator()
        self._build_appearance_menu(menu)
        menu.addSeparator()
        action_clear_logs = menu.addAction("🧹  Clear old logs…")
        action_clear_cache = menu.addAction("🗑️  Clear cache…")
        menu.addSeparator()
        action_report = menu.addAction("🐛  Report a bug…")

        action_app.triggered.connect(self.open_current_log)
        action_mpv.triggered.connect(self.open_mpv_log)
        action_folder.triggered.connect(self.open_logs_folder)
        action_clear_logs.triggered.connect(self.confirm_clear_logs)
        action_clear_cache.triggered.connect(self.confirm_clear_cache)
        action_report.triggered.connect(self.show_report_dialog)

        self.ui.btn_logs.setMenu(menu)

    def _build_appearance_menu(self, parent_menu):
        """Experimental chrome color themes as a checkable submenu."""
        from PySide6.QtGui import QActionGroup

        submenu = parent_menu.addMenu("🎨  Appearance (Experiments)")
        submenu.setStyleSheet(_LOGS_MENU_STYLE)

        from steempeg.ui import design_tokens as tok
        current = tok.DEFAULT_CHROME_THEME
        if hasattr(self, "load_user_settings"):
            current = self.load_user_settings().get("chrome_theme", tok.DEFAULT_CHROME_THEME)

        group = QActionGroup(submenu)
        group.setExclusive(True)
        options = [
            ("default", "Default (black bar)"),
            ("exp1", "Experiment 1 — #1e1e1e title bar"),
            ("exp2", "Experiment 2 — #222222 bar + #141414 background"),
            ("exp3", "Experiment 3 — #2d2d2d bar + #1e1e1e background"),
            ("exp4", "Experiment 4 — #2d2d2d bar + #141414 background"),
        ]
        for name, label in options:
            act = submenu.addAction(label)
            act.setCheckable(True)
            act.setChecked(name == current)
            group.addAction(act)
            act.triggered.connect(lambda _=False, n=name: self.apply_chrome_theme(n))
        self._appearance_menu_group = group

    def show_report_dialog(self):
        from steempeg.ui.report_dialog import show_report_dialog
        show_report_dialog(self)

    def open_logs_folder(self):
        if hasattr(self, 'logs_dir'):
            paths.open_in_file_manager(self.logs_dir)

    def open_current_log(self):
        path = getattr(self, 'current_log_file', None)
        if path and os.path.exists(path):
            paths.open_in_file_manager(path)
            logging.info("Opened app log: %s", path)
        else:
            QMessageBox.warning(self.ui, "Logs", "App log file not found for this session.")

    def open_mpv_log(self):
        path = getattr(self, 'current_mpv_log_file', None)
        if path and os.path.exists(path):
            paths.open_in_file_manager(path)
            logging.info("Opened MPV log: %s", path)
        else:
            QMessageBox.warning(self.ui, "Logs", "MPV log file not found for this session.")

    def confirm_clear_logs(self):
        logs_dir = getattr(self, 'logs_dir', None)
        if not logs_dir or not os.path.isdir(logs_dir):
            return
        count, size = log_util.logs_folder_stats(logs_dir)
        if count == 0:
            QMessageBox.information(self.ui, "Clear logs", "The logs folder is already empty.")
            return
        reply = QMessageBox.question(
            self.ui,
            "Clear old logs",
            f"Delete old log files in:\n{logs_dir}\n\n"
            f"Currently {count} file(s), {log_util.format_bytes(size)}.\n\n"
            "Logs from this session will be kept.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        keep = [
            getattr(self, 'current_log_file', None),
            getattr(self, 'current_mpv_log_file', None),
        ]
        removed, freed = log_util.clear_log_files(logs_dir, keep_paths=keep)
        logging.info("User cleared logs: removed %d file(s), freed %s", removed, log_util.format_bytes(freed))
        QMessageBox.information(
            self.ui,
            "Clear logs",
            f"Removed {removed} log file(s) ({log_util.format_bytes(freed)} freed).",
        )

    def confirm_clear_cache(self):
        cache_dir = getattr(self, 'cache_dir', None)
        if not cache_dir or not os.path.isdir(cache_dir):
            return
        count, size = log_util.cache_folder_stats(cache_dir)
        if count == 0:
            QMessageBox.information(self.ui, "Clear cache", "The cache folder is already empty.")
            return
        reply = QMessageBox.question(
            self.ui,
            "Clear cache",
            f"Delete everything in:\n{cache_dir}\n\n"
            f"{count} item(s), {log_util.format_bytes(size)}.\n\n"
            "Game icons, settings, and the saved render queue will be removed. "
            "They will be rebuilt on the next library scan.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        removed, freed = log_util.clear_directory_contents(cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        if hasattr(self, 'game_names_cache'):
            self.game_names_cache = {}
        if hasattr(self, 'game_icons_cache'):
            self.game_icons_cache = {}
        logging.info("User cleared cache: removed %d item(s), freed %s", removed, log_util.format_bytes(freed))
        QMessageBox.information(
            self.ui,
            "Clear cache",
            f"Removed {removed} item(s) ({log_util.format_bytes(freed)} freed).",
        )


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
            self.ui.label_location.setText("—")
            
        # 5. Hard-Block the Render Button
        if hasattr(self.ui, 'btn_start'):
            self.ui.btn_start.setEnabled(False)