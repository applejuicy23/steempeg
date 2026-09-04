"""Application lifecycle and chrome, mixed into the main application.

These methods cover the status bar, the global event filter, window close and
exit cleanup, the About dialog, opening the logs, path elision and resetting
per-clip state. They run on the application instance and reach its widgets and
state through self.
"""
import logging
import os
import re
import sys

import psutil

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra import logging as log_util
from steempeg.infra import paths
from steempeg.infra.paths import get_resource_path
from steempeg.version import APP_VERSION_STR
from steempeg.ui.message_dialog import steempeg_information, steempeg_question, steempeg_warning


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


class _AboutEggLogo(QLabel):
    """About logo that quietly toggles logo ↔ Phibe Chupe on left click.

    A real subclass (not an instance monkey-patch) so Qt virtual dispatch
    always delivers mouse presses. The hit target stays opaque for mouse
    purposes so clicks cannot fall through a translucent About shell.
    """

    def __init__(self, normal: QPixmap, egg: QPixmap, parent=None):
        super().__init__(parent)
        self._normal = normal
        self._egg = egg
        self._egg_on = False
        if not normal.isNull():
            self.setPixmap(normal)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setFixedWidth(128)
        self.setMinimumHeight(120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Transparent look is fine; do not let clicks pierce the dialog.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._egg.isNull() and self._normal.isNull():
                event.accept()
                return
            self._egg_on = not self._egg_on
            pix = self._egg if self._egg_on and not self._egg.isNull() else self._normal
            if not pix.isNull():
                self.setPixmap(pix)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        event.accept()


class LifecycleMixin:
    def eventFilter(self, source, event):
        if getattr(self, '_is_closing', False):
            return False

        # Esc clears Clips/Rendered multi-select before anything else closes.
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride):
            if event.key() == Qt.Key.Key_Escape:
                if getattr(self, "is_fullscreen", False):
                    return False
                # Portable Choose-a-Clip sheet owns Esc (clear, then close).
                if getattr(self, "_portable_clip_picker_open", False):
                    return False
                if self._escape_targets_library(source) and hasattr(
                    self, "clear_library_item_selection"
                ):
                    if self.clear_library_item_selection():
                        if event.type() == QEvent.Type.ShortcutOverride:
                            event.accept()
                        return True

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

        # 1. Table (List) — Ctrl/Alt/Shift+LMB multi-select; RMB opens context menu only
        if hasattr(self.ui, 'table_clips') and source == self.ui.table_clips.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    self.show_clip_context_menu(event.position().toPoint())
                    return True
                if event.button() == Qt.LeftButton:
                    mods = event.modifiers()
                    if mods & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier):
                        if hasattr(self, "_table_apply_click_modifiers"):
                            self._table_apply_click_modifiers(
                                self.ui.table_clips, event.position().toPoint(), mods
                            )
                            return True
                    
        # 2. Grid — RMB opens menu; LMB multi-select is handled on cards / empty viewport
        if hasattr(self, 'grid_clips') and source == self.grid_clips.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    self.show_grid_context_menu(event.position().toPoint())
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
                    if mods & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier):
                        if hasattr(self, "_table_apply_click_modifiers"):
                            self._table_apply_click_modifiers(
                                self.table_rendered, event.position().toPoint(), mods
                            )
                            return True

        if hasattr(self, 'grid_rendered') and source == self.grid_rendered.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    if hasattr(self, 'show_rendered_grid_context_menu'):
                        self.show_rendered_grid_context_menu(event.position().toPoint())
                    return True
                if event.button() == Qt.LeftButton and hasattr(self, '_handle_rendered_grid_viewport_press'):
                    return self._handle_rendered_grid_viewport_press(event)
            if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.LeftButton:
                return True

        # Screenshots — photo tiles own click/open; kill IconMode rubber-band ghost.
        # Placeholders (no ScreenshotPhoto yet) need click handling here.
        if hasattr(self, "grid_screenshots") and source in (
            self.grid_screenshots,
            self.grid_screenshots.viewport(),
        ):
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                if hasattr(self, "_schedule_screenshots_grid_reflow"):
                    # Widen: reflow ASAP so 3→4 columns land. Narrow/show: debounce
                    # past intermediate chrome widths (avoids sticky 2-col gap).
                    delay = 0 if event.type() == QEvent.Type.Show else 80
                    if event.type() == QEvent.Type.Resize:
                        vp = self.grid_screenshots.viewport()
                        w = int(vp.width()) if vp is not None else 0
                        prev = int(getattr(self, "_screenshots_last_reflow_w", 0) or 0)
                        self._screenshots_last_reflow_w = w
                        if w > prev:
                            delay = 0
                    self._schedule_screenshots_grid_reflow(delay)
                    if event.type() == QEvent.Type.Show:
                        self._schedule_screenshots_grid_reflow(50)
                elif hasattr(self, "_schedule_screenshots_viewport_refresh"):
                    self._schedule_screenshots_viewport_refresh(50)
                return False
            if source != self.grid_screenshots.viewport():
                return False
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    item = self.grid_screenshots.itemAt(event.position().toPoint())
                    if item is not None and self.grid_screenshots.itemWidget(item) is None:
                        if hasattr(self, "_materialize_screenshot_item"):
                            self._materialize_screenshot_item(item)
                    if hasattr(self, "show_screenshots_grid_context_menu"):
                        self.show_screenshots_grid_context_menu(event.position().toPoint())
                    return True
                if event.button() == Qt.LeftButton:
                    item = self.grid_screenshots.itemAt(event.position().toPoint())
                    if item is None:
                        if hasattr(self, "_clear_screenshots_selection_visual"):
                            self._clear_screenshots_selection_visual()
                        return True
                    if self.grid_screenshots.itemWidget(item) is None:
                        # Bare placeholder: materialize, select, then hand the press to
                        # the new photo so paint-drag + release-open match live tiles.
                        if hasattr(self, "_materialize_screenshot_item"):
                            self._materialize_screenshot_item(item)
                        if hasattr(self, "_screenshot_grid_select_item"):
                            self._screenshot_grid_select_item(
                                item, event, force_single=True
                            )
                        photo = self.grid_screenshots.itemWidget(item)
                        if photo is not None and hasattr(photo, "begin_external_press"):
                            photo.begin_external_press(
                                event.globalPosition().toPoint()
                            )
                        else:
                            path = item.data(Qt.ItemDataRole.UserRole) or ""
                            if path and hasattr(self, "_on_screenshot_open"):
                                self._on_screenshot_open(str(path))
                        return True
            if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.LeftButton:
                return True

        return super().eventFilter(source, event)

    def _escape_targets_library(self, source) -> bool:
        """True when Esc should clear Clips Manager / Rendered selection."""
        libs = []
        for name in ("grid_clips", "grid_rendered", "table_rendered", "grid_screenshots"):
            w = getattr(self, name, None)
            if w is not None:
                libs.append(w)
                vp = getattr(w, "viewport", None)
                if callable(vp):
                    try:
                        libs.append(vp())
                    except Exception:
                        pass
        table = getattr(getattr(self, "ui", None), "table_clips", None)
        if table is not None:
            libs.append(table)
            try:
                libs.append(table.viewport())
            except Exception:
                pass
        left = getattr(getattr(self, "ui", None), "left_panel", None)
        if left is not None:
            libs.append(left)

        node = source
        while node is not None:
            if node in libs:
                return True
            try:
                node = node.parentWidget() if hasattr(node, "parentWidget") else None
            except RuntimeError:
                break
        # Focus may sit on a card child while the event source is the window.
        try:
            focus = QApplication.focusWidget() if QApplication.instance() else None
        except Exception:
            focus = None
        node = focus
        while node is not None:
            if node in libs:
                return True
            try:
                node = node.parentWidget() if hasattr(node, "parentWidget") else None
            except RuntimeError:
                break
        return False

    def _sync_mpv_surface_geometry(self, *args):
        """Re-pin the native mpv child after splitter / panel layout changes."""
        wrapper = getattr(self, "mpv_wrapper", None)
        if wrapper is not None:
            wrapper.update_geometry()

    def _install_mpv_geometry_hooks(self):
        # Windows formula: hook both splitters so the embed stays clipped while
        # the player panel moves. update_geometry early-outs on unchanged rects.
        for splitter in (
            getattr(self.ui, "main_splitter", None),
            getattr(self, "right_h_splitter", None),
        ):
            if splitter is not None:
                splitter.splitterMoved.connect(self._sync_mpv_surface_geometry)

    def set_status(self, text):
        """Updates the render status row (delegates to update_status_indicator when available)."""
        if hasattr(self, 'update_status_indicator'):
            if text.startswith("Screenshots: updated "):
                self.update_status_indicator(text, "accent")
                if hasattr(self, "_schedule_transient_status_clear"):
                    self._schedule_transient_status_clear()
                return
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
            try:
                self.player.pause = True
            except Exception:
                pass
            try:
                self.player.command('stop')
            except Exception:
                pass
            try:
                # Tear down libmpv so close doesn't race a dead core.
                self.player.terminate()
            except Exception:
                pass
            self.player = None

        if hasattr(self, '_stop_timeline_thumb_batch'):
            self._stop_timeline_thumb_batch()
        if hasattr(self, '_stop_library_scan'):
            self._stop_library_scan()
        if hasattr(self, '_stop_rendered_scan'):
            self._stop_rendered_scan()
        if hasattr(self, '_stop_clip_poster_backfill'):
            self._stop_clip_poster_backfill()
        if hasattr(self, '_stop_rendered_poster_backfill'):
            self._stop_rendered_poster_backfill()
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
                        from steempeg.infra.process import kill_process_tree

                        kill_process_tree(child.pid, label=child.name())
                        print(f"Zombie proccess killed: {child.name()}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"⚠️ Error with killing zombie pcorsalfgn: {e}")

        if hasattr(self, "_persist_render_queue"):
            self._persist_render_queue()

        # Shared panel snapshot so Desktop ↔ Portable see the same Export state.
        try:
            from steempeg.ui.portable.sheets import persist_render_settings

            persist_render_settings(self)
        except Exception:
            pass

        if hasattr(self, "_library_ui_persist_ready"):
            self._library_ui_persist_ready = True
        if hasattr(self, "_persist_library_ui_state"):
            self._persist_library_ui_state()

        if hasattr(self.ui, "main_splitter"):
            self.save_layout_setting("main_splitter_sizes", self.ui.main_splitter.sizes())
        if hasattr(self, "right_h_splitter"):
            sizes = self.right_h_splitter.sizes()
            if len(sizes) >= 2:
                open_w = int(sizes[1])
                if open_w > 48:
                    self.save_layout_setting("queue_panel_width", open_w)
                self.save_layout_setting("queue_panel_open", open_w > 48)
        # Desktop player↔settings dock — never write Like a Portable glue heights.
        if hasattr(self, "main_v_splitter"):
            portable_like = False
            if hasattr(self, "_desktop_render_layout_is_portable_like"):
                try:
                    portable_like = bool(self._desktop_render_layout_is_portable_like())
                except Exception:
                    portable_like = False
            if portable_like:
                pre = getattr(self, "_pre_portable_like_v_sizes", None)
                if pre and len(pre) >= 2 and int(pre[1]) > 80:
                    self.save_layout_setting(
                        "main_v_splitter_sizes", [int(pre[0]), int(pre[1])]
                    )
            elif hasattr(self, "_persist_desktop_main_v_splitter_sizes"):
                self._persist_desktop_main_v_splitter_sizes()

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
                        from steempeg.infra.process import kill_process_tree

                        kill_process_tree(child.pid, label=child.name())
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

    def show_settings_dialog(self):
        """App-wide Settings (library footer) — updates, shell, notify, hints, performance."""
        from steempeg.ui.settings_dialog import show_settings_dialog

        show_settings_dialog(self)
        # In case settings changed while dialog was open, re-evaluate Dev button gate.
        if hasattr(self, "_refresh_dev_button_visibility"):
            self._refresh_dev_button_visibility()

    def show_dev_dialog(self):
        """Developer Tools dialog (hidden unless dev_mode is enabled)."""
        from steempeg.ui.dev_mode_dialog import DevModeDialog

        dlg = DevModeDialog(self.cache_dir, parent=getattr(self, "ui", None))
        dlg.exec()

    def show_marker_settings(self):
        """Marker classes / CS2 pack / per-ID icon overrides."""
        from steempeg.ui.marker_settings_dialog import show_marker_settings_dialog

        show_marker_settings_dialog(self)

    def show_about_dialog(self):
        """ Frameless About dialog styled like the FFmpeg render-error window. """
        if getattr(self, '_about_is_open', False):
            return  # Block if already open
        self._about_is_open = True

        from steempeg.ui import ui_theme as ut

        link = ut.about_dialog_link_style()
        muted = ut.about_dialog_muted_span_color()

        dialog = QDialog(self.ui)
        dialog.setObjectName("SteempegAboutDialog")
        dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        # Make the window itself transparent so only the stylesheet's rounded rect is
        # painted; otherwise the square window background pokes out past the 8px radius.
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        from steempeg.ui.ui_density import scaled_dialog_size

        # Portable + Deck-class shells: scaled_dialog_size shrinks too hard for the
        # Report / Close row. Keep About wide enough for labels.
        if getattr(self, "_portable_shell", False):
            shell_w = 0
            try:
                shell_w = int(self.ui.width() or 0)
            except Exception:
                shell_w = 0
            if shell_w <= 1600:
                dialog.setFixedSize(720, 500)
            else:
                dialog.setFixedSize(*scaled_dialog_size(660, 480, parent=self.ui))
        else:
            dialog.setFixedSize(*scaled_dialog_size(620, 470, parent=self.ui))
        dialog.setStyleSheet(ut.about_dialog_stylesheet())

        shell_layout = QVBoxLayout(dialog)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        card = QWidget(dialog)
        card.setObjectName("AboutCard")
        # Required on WA_TranslucentBackground shells — without this the card
        # may not paint / hit-test, so clicks fall through to the main window
        # (stuck press cursor, Phibe egg never toggles).
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shell_layout.addWidget(card)

        main_layout = QHBoxLayout(card)
        main_layout.setContentsMargins(26, 26, 26, 22)
        main_layout.setSpacing(24)

        # --- Left: the program logo (smoothly scaled, never pixelated) ---
        logo_normal = _crisp_icon(get_resource_path("logo.png"), 120, dpr=1.0)
        logo_egg = _crisp_icon(get_resource_path("phibechipeegg.png"), 120, dpr=1.0)
        logo_label = _AboutEggLogo(logo_normal, logo_egg)
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
            f'<span style="color:{muted};">@applejuicy23</span>'
        )
        dev.setObjectName("AboutText")
        content.addWidget(dev)

        github_row = self._about_icon_row(
            "github.jpg",
            f'<b>GitHub:</b> <a href="https://github.com/applejuicy23/steempeg" '
            f'style="{link}">applejuicy23/steempeg</a>',
        )
        content.addLayout(github_row)
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
        # Portable: Check for updates lives in the title bar (Updates chip).
        # Desktop still has the left-panel Updates button.
        btn_row.addWidget(btn_close)
        content.addLayout(btn_row)

        main_layout.addLayout(content)

        def apply_ui_theme_chrome() -> None:
            """Live-retint if Settings switches theme while About is open."""
            dialog.setStyleSheet(ut.about_dialog_stylesheet())
            new_muted = ut.about_dialog_muted_span_color()
            dev.setText(
                'Developer: <b>Emily</b> 🎀 '
                f'<span style="color:{new_muted};">@applejuicy23</span>'
            )

        dialog.apply_ui_theme_chrome = apply_ui_theme_chrome  # type: ignore[attr-defined]

        try:
            dialog.exec()
        finally:
            self._about_is_open = False  # Release the lock when closed
            tb = getattr(getattr(self, "ui", None), "title_bar", None)
            if tb is not None and hasattr(tb, "clear_shell_tool_hover"):
                tb.clear_shell_tool_hover()
            else:
                # Desktop footer About path may have no title-bar shell tools.
                app = QApplication.instance()
                if app is not None:
                    while app.overrideCursor() is not None:
                        app.restoreOverrideCursor()
                    try:
                        app.setOverrideCursor(Qt.CursorShape.ArrowCursor)
                        app.restoreOverrideCursor()
                    except RuntimeError:
                        pass
                ui = getattr(self, "ui", None)
                if ui is not None:
                    try:
                        ui.unsetCursor()
                    except RuntimeError:
                        pass
                    from PySide6.QtGui import QCursor

                    try:
                        QCursor.setPos(QCursor.pos())
                    except RuntimeError:
                        pass


    def setup_logs_menu(self):
        """Attach a styled Logs dropdown to btn_logs."""
        if not hasattr(self.ui, 'btn_logs'):
            return
        from steempeg.ui import ui_theme as ut

        menu = QMenu(self.ui)
        menu.setStyleSheet(ut.logs_menu_stylesheet())

        action_app = menu.addAction("📄  App + FFmpeg logs")
        action_mpv = menu.addAction("🎬  MPV player log")
        action_folder = menu.addAction("📂  Open logs folder")
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
        self._logs_menu = menu

    def refresh_logs_menu_chrome(self) -> None:
        """Re-tint Logs ▾ popup when UI theme switches."""
        from steempeg.ui import ui_theme as ut

        menu = getattr(self, "_logs_menu", None)
        if menu is None and hasattr(self.ui, "btn_logs"):
            menu = self.ui.btn_logs.menu()
        if menu is not None:
            menu.setStyleSheet(ut.logs_menu_stylesheet())
            self._logs_menu = menu

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
            steempeg_warning(self.ui, "Logs", "App log file not found for this session.")

    def open_mpv_log(self):
        path = getattr(self, 'current_mpv_log_file', None)
        if path and os.path.exists(path):
            paths.open_in_file_manager(path)
            logging.info("Opened MPV log: %s", path)
        else:
            steempeg_warning(self.ui, "Logs", "MPV log file not found for this session.")

    def confirm_clear_logs(self):
        logs_dir = getattr(self, 'logs_dir', None)
        if not logs_dir or not os.path.isdir(logs_dir):
            return
        count, size = log_util.logs_folder_stats(logs_dir)
        if count == 0:
            steempeg_information(self.ui, "Clear logs", "The logs folder is already empty.")
            return
        if not steempeg_question(
            self.ui,
            "Clear old logs",
            f"Delete old log files in:\n{logs_dir}\n\n"
            f"Currently {count} file(s), {log_util.format_bytes(size)}.\n\n"
            "Logs from this session will be kept.",
        ):
            return
        keep = [
            getattr(self, 'current_log_file', None),
            getattr(self, 'current_mpv_log_file', None),
        ]
        removed, freed = log_util.clear_log_files(logs_dir, keep_paths=keep)
        logging.info("User cleared logs: removed %d file(s), freed %s", removed, log_util.format_bytes(freed))
        steempeg_information(
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
            steempeg_information(self.ui, "Clear cache", "The cache folder is already empty.")
            return
        if not steempeg_question(
            self.ui,
            "Clear cache",
            f"Delete everything in:\n{cache_dir}\n\n"
            f"{count} item(s), {log_util.format_bytes(size)}.\n\n"
            "Game icons, settings, and the saved render queue will be removed. "
            "They will be rebuilt on the next library scan.",
        ):
            return
        removed, freed = log_util.clear_directory_contents(cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        if hasattr(self, 'game_names_cache'):
            self.game_names_cache = {}
        if hasattr(self, 'game_icons_cache'):
            self.game_icons_cache = {}
        logging.info("User cleared cache: removed %d item(s), freed %s", removed, log_util.format_bytes(freed))
        steempeg_information(
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
        if hasattr(self, "_sync_start_render_enabled"):
            self._sync_start_render_enabled()
        else:
            self.ui.btn_start.setEnabled(False)
            self.ui.btn_start.setText(" Choose clip for render")
            if hasattr(self, "_apply_desktop_dash_render_icons"):
                self._apply_desktop_dash_render_icons()

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
            if hasattr(self, "_sync_queue_player_and_dash_chrome"):
                self._sync_queue_player_and_dash_chrome()
            elif hasattr(self, 'reset_bottom_summary'):
                self.reset_bottom_summary()
        if hasattr(self.ui, 'label_detailed_summary'):
            self.ui.label_detailed_summary.setText("Waiting for clip selection...")
        if hasattr(self.ui, 'label_location'):
            self.ui.label_location.setText("")
        path_row = getattr(self.ui, "output_path_row", None)
        if path_row is not None:
            path_row.hide()
            
        # 5. Hard-Block the Render Button — unless the queue still has pending work.
        if hasattr(self.ui, 'btn_start'):
            if hasattr(self, "_sync_start_render_enabled"):
                self._sync_start_render_enabled()
            else:
                self.ui.btn_start.setEnabled(False)