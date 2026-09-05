"""Video playback and the player surface, mixed into the main application.

These methods drive the mpv-backed player: opening and closing clips, play/pause,
volume and speed, the timeline and trim controls, fullscreen/theatre mode,
screenshots and markers. They run on the application instance and reach its widgets
and player through self.
"""
from steempeg.ui import design_tokens as tok
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime

from PySide6.QtCore import QEvent, QEventLoop, QObject, Qt, QPropertyAnimation, QTimer
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
from steempeg.ui.window_chrome import (
    collapse_content_insets,
    enable_frameless,
    force_full_redraw,
    poke_frame,
    refresh_dwm_chrome,
    restore_content_insets,
    set_window_transitions,
    soft_full_redraw,
)
from steempeg.ui.player.thumbnails import PreviewSniperWorker, ThumbnailBatchThread
from steempeg.ui.message_dialog import steempeg_information, steempeg_warning

_FS_TRACE = os.environ.get("STEEMPEG_FS_TRACE") == "1"


def _fstrace(msg, *args):
    if _FS_TRACE:
        logging.info("[fstrace] %.3f " + msg, time.perf_counter(), *args)


class _ScreenshotToastClickAwayFilter(QObject):
    """Dismiss the screenshot Tool toast on click-away / shell move / focus loss.

    The toast is a separate always-on-top-free ``Qt.Tool`` window (same family as
    the buffering pill), so it does not auto-close like ``Qt.Popup``. Filter
    clicks outside it and shell geometry/focus changes without eating the event.
    """

    def __init__(self, host):
        super().__init__(host.ui if getattr(host, "ui", None) is not None else None)
        self._host = host

    def eventFilter(self, obj, event):  # noqa: N802
        host = self._host
        toast = getattr(host, "_screenshot_toast", None)
        if toast is None:
            return False
        try:
            visible = toast.isVisible()
        except RuntimeError:
            return False
        if not visible:
            return False

        et = event.type()
        ui = getattr(host, "ui", None)

        if et == QEvent.Type.MouseButtonPress:
            if isinstance(obj, QWidget) and (obj is toast or toast.isAncestorOf(obj)):
                return False
            host._hide_screenshot_toast()
            return False

        if et == QEvent.Type.ApplicationDeactivate:
            host._hide_screenshot_toast()
            return False

        if et in (
            QEvent.Type.WindowDeactivate,
            QEvent.Type.Hide,
            QEvent.Type.Close,
            QEvent.Type.WindowStateChange,
        ):
            if ui is not None and obj is ui:
                host._hide_screenshot_toast()
            return False

        if et in (QEvent.Type.Move, QEvent.Type.Resize) and ui is not None and obj is ui:
            # Absolute-positioned Tool window; dragging/resizing leaves a ghost.
            host._hide_screenshot_toast()
            return False

        return False


class PlayerMixin:
    def _discard_dead_linux_mpv(self) -> None:
        """Drop a ShutdownError'd libmpv handle so the next ensure recreates it."""
        player = getattr(self, "player", None)
        if player is None:
            return
        try:
            player.terminate()
        except Exception:
            pass
        self.player = None
        self._linux_mpv_vo_attached = False

    def _mpv_core_alive(self) -> bool:
        player = getattr(self, "player", None)
        if player is None:
            return False
        try:
            # Touches the core; raises ShutdownError when dead.
            _ = player.path
            return True
        except Exception:
            return False

    def _ensure_linux_mpv_vo(self) -> bool:
        """Create libmpv on Linux at first play (never at app startup).

        Prefer ``wid`` embed + ``vo=gpu`` with ``gpu-context=x11egl`` when the
        loaded libmpv talks to a real GPU (system NVIDIA/Mesa). Homebrew-linked
        libmpv pulls brew Mesa → llvmpipe / black embed, so fall back to ``x11``
        then ``xv`` there. ``vo=xv`` is last resort — mpv itself warns it looks bad.
        Set ``STEEMPEG_MPV_EXTERNAL=1`` to force a separate mpv window instead.
        """
        if sys.platform == "win32":
            return True

        import mpv as _mpv

        if getattr(self, "player", None) is not None and not self._mpv_core_alive():
            logging.warning("Linux mpv core dead — recreating")
            self._discard_dead_linux_mpv()

        soft = os.environ.get("STEEMPEG_SOFT_VIDEO", "0") == "1"
        if soft:
            os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
            os.environ.setdefault("GALLIUM_DRIVER", "llvmpipe")

        env_vo = (os.environ.get("STEEMPEG_VO") or "").strip()
        ao = (os.environ.get("STEEMPEG_AO") or "").strip() or ("null" if soft else "pulse")
        log_path = getattr(self, "current_mpv_log_file", None) or ""
        external = os.environ.get("STEEMPEG_MPV_EXTERNAL", "0") == "1"

        def _active_libmpv_path() -> str | None:
            cand = (os.environ.get("MPV_LIBRARY_PATH") or "").strip()
            if cand and os.path.isfile(cand):
                return os.path.realpath(cand)
            try:
                from steempeg.infra.libmpv_bootstrap import find_bundled_libmpv

                bundled = find_bundled_libmpv()
                if bundled:
                    return bundled
            except Exception:
                pass
            for path in (
                "/usr/lib64/libmpv.so.2",
                "/usr/lib/libmpv.so.2",
                "/usr/lib/x86_64-linux-gnu/libmpv.so.2",
            ):
                if os.path.isfile(path):
                    return os.path.realpath(path)
            return None

        def _lib_uses_brew_mesa(lib: str | None) -> bool:
            """True when *lib* resolves EGL/gallium via Homebrew (llvmpipe on NVIDIA)."""
            if not lib:
                return False
            try:
                out = subprocess.check_output(
                    ["ldd", lib], text=True, stderr=subprocess.DEVNULL
                )
            except (OSError, subprocess.CalledProcessError):
                return "linuxbrew" in lib
            return "linuxbrew" in out and (
                "libEGL" in out or "libgallium" in out or "mesa" in out.lower()
            )

        brew_mesa = _lib_uses_brew_mesa(_active_libmpv_path())
        if env_vo:
            vo_attempts = [env_vo]
        elif soft:
            vo_attempts = ["x11", "xv", "gpu", "null"]
        elif brew_mesa:
            # gpu → brew Mesa llvmpipe (black / melted CPU). Prefer x11 (cleaner) over xv.
            vo_attempts = ["x11", "xv"]
        else:
            vo_attempts = ["gpu", "x11", "xv"]

        if getattr(self, "player", None) is None:
            wid = None
            if not external and hasattr(self, "mpv_screen") and self.mpv_screen is not None:
                try:
                    # First create must not grab winId while the stack is on
                    # video_blank_frame — that parks the native child to 0x0 and
                    # NVIDIA/XWayland keeps a black surface while audio plays.
                    self._prepare_linux_embed_for_wid()
                    wid = int(self.mpv_screen.winId())
                except Exception as exc:
                    logging.warning("Linux mpv wid unavailable: %s", exc)

            modes = []
            if wid is not None:
                modes.append("embed")
            modes.append("external")

            last_exc = None
            from steempeg.ui.settings_prefs import (
                current_hwdec_preview,
                current_mpv_loglevel,
            )

            for mode in modes:
                for vo in vo_attempts:
                    # Legacy VOs + hwdec often paint garbage on XWayland; keep sw decode.
                    hwdec = current_hwdec_preview()
                    if vo in ("xv", "x11") and hwdec != "no":
                        hwdec = "no"
                    opts = {
                        "panscan": 1.0,
                        "keepaspect": "no" if mode == "embed" else "yes",
                        "keep_open": "yes",
                        "loglevel": current_mpv_loglevel(),
                        "hwdec": hwdec,
                        "ao": ao,
                        "osc": "no",
                        "input_default_bindings": "no",
                        "input_vo_keyboard": "no",
                        "load_scripts": "no",
                        "vo": vo,
                    }
                    # wid= embed under XWayland: force x11egl so gpu does not pick
                    # a Wayland context that paints beside the Qt window.
                    if vo == "gpu":
                        opts["gpu_context"] = (
                            os.environ.get("STEEMPEG_GPU_CONTEXT") or "x11egl"
                        ).strip() or "x11egl"
                    if log_path:
                        opts["log_file"] = log_path
                    if mode == "embed":
                        opts["wid"] = wid
                    else:
                        opts["force_window"] = "immediate"
                        opts["title"] = "Steempeg Player"
                    try:
                        self.player = _mpv.MPV(**opts)
                        logging.info(
                            "Linux mpv created: vo=%s mode=%s hwdec=%s brew_mesa=%s",
                            vo,
                            mode,
                            hwdec,
                            brew_mesa,
                        )
                        last_exc = None
                        break
                    except Exception as exc:
                        last_exc = exc
                        logging.warning(
                            "Linux mpv create failed vo=%s mode=%s: %s", vo, mode, exc
                        )
                        self.player = None
                if self.player is not None:
                    break

            if self.player is None:
                logging.error("Linux mpv create exhausted attempts: %s", last_exc)
                return False
            try:
                self.player["af"] = "rubberband"
            except Exception as exc:
                logging.warning("mpv rubberband af unavailable: %s", exc)
            self._linux_mpv_vo_attached = True
            if hasattr(self, "_apply_saved_preview_quality_to_player"):
                self._apply_saved_preview_quality_to_player()
            return True

        if getattr(self, "_linux_mpv_vo_attached", False):
            return True
        self._linux_mpv_vo_attached = True
        return True

    def _prepare_linux_embed_for_wid(self) -> None:
        """Map ``video_container`` and give the native child a real size before winId.

        Open paths park the embed under ``video_blank_frame`` (0x0 + hide). Creating
        libmpv there on NVIDIA/XWayland yields a black surface for the whole first
        clip even though mpv reports frames — the next loadfile reconfig "fixes" it.
        """
        if sys.platform == "win32":
            return
        stack = getattr(self, "video_stack", None)
        container = getattr(getattr(self, "ui", None), "video_container", None)
        if stack is not None and container is not None:
            try:
                if stack.currentWidget() is not container:
                    stack.setCurrentWidget(container)
            except Exception:
                pass
        wrapper = getattr(self, "mpv_wrapper", None)
        if wrapper is not None:
            try:
                if hasattr(wrapper, "prepare_native_embed"):
                    wrapper.prepare_native_embed()
                wrapper._last_video_rect = None
                if hasattr(wrapper, "update_geometry"):
                    wrapper.update_geometry()
            except Exception:
                pass
        screen = getattr(self, "mpv_screen", None)
        if screen is not None:
            try:
                screen.show()
            except Exception:
                pass

    def _kick_linux_embed_surface(self) -> None:
        """Re-apply embed geometry after the stack shows ``video_container``."""
        if sys.platform == "win32":
            return
        wrapper = getattr(self, "mpv_wrapper", None)
        if wrapper is None or not hasattr(wrapper, "update_geometry"):
            return
        try:
            wrapper._last_video_rect = None
            wrapper.update_geometry()
        except Exception as exc:
            logging.debug("Linux embed surface kick failed: %s", exc)

    def _clear_player_surface(self):
        """Stop mpv and return the player area to the empty placeholder.

        Does not touch library selection or the header — callers that need a full
        reset (close_current_clip) clear those separately.
        """
        self._force_pause = True
        self._eof_rewind_pending = 0
        self._restart_from_eof = False
        self._current_mpd_abs_path = None
        self._is_switching = False
        self._awaiting_first_frame = False
        self._pending_open_seek = None
        self._open_seek_timer_armed = False
        self._clear_remux_quality_hold()

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
            if hasattr(self.custom_timeline.canvas, "notify_markers_changed"):
                self.custom_timeline.canvas.notify_markers_changed(animate=True)
            else:
                self.custom_timeline.canvas.update()

        if hasattr(self, 'video_stack') and hasattr(self, 'placeholder_frame'):
            self.video_stack.setCurrentWidget(self.placeholder_frame)
        self._park_mpv_embed_when_not_showing()

        if hasattr(self.ui, 'label_time'):
            self.ui.label_time.setText("00:00 / 00:00")

        if hasattr(self.ui, 'btn_play'):
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))

    def _park_mpv_embed_when_not_showing(self):
        """Hide the native mpv HWND while the stack shows placeholder/blank."""
        wrapper = getattr(self, 'mpv_wrapper', None)
        if wrapper is not None and hasattr(wrapper, '_park_mpv_screen'):
            wrapper._park_mpv_screen()
        elif hasattr(self, 'mpv_screen') and self.mpv_screen is not None:
            self.mpv_screen.hide()

    def _set_shell_paint_frozen(self, frozen: bool):
        """Hold the last painted frame while the shell is torn down / rebuilt.

        The alternative to the gray cover: with updates disabled the window keeps
        showing its last good frame, so the panel churn (footer vanishing, video
        container swallowing its strip and being pushed back) never reaches the
        screen — instead of replacing it with a flat rectangle.
        """
        if bool(getattr(self, '_shell_paint_frozen', False)) == bool(frozen):
            return
        self._shell_paint_frozen = bool(frozen)
        try:
            self.ui.setUpdatesEnabled(not frozen)
            # The HUD is a Tool window parented to the shell: freezing the shell
            # propagates down to it, but thawing does not come back up to a
            # top-level child — it would stay shown-but-never-painted.
            footer = getattr(self, 'player_footer_frame', None)
            if footer is not None:
                footer.setUpdatesEnabled(not frozen)
        except RuntimeError:
            return
        if frozen:
            # Watchdog — a raising step must never leave the shell unpainted.
            self._shell_paint_thaw_gen = getattr(self, '_shell_paint_thaw_gen', 0) + 1
            gen = self._shell_paint_thaw_gen
            QTimer.singleShot(2000, lambda g=gen: self._thaw_shell_paint_if(g))
        else:
            self.ui.update()

    def _thaw_shell_paint_if(self, gen: int):
        if getattr(self, '_shell_paint_thaw_gen', 0) != gen:
            return
        self._set_shell_paint_frozen(False)

    def _freeze_mpv_surface(self, frozen: bool):
        """Hold the native embed still across an immersive transition."""
        wrapper = getattr(self, 'mpv_wrapper', None)
        if wrapper is None or not hasattr(wrapper, 'begin_transition'):
            return
        if frozen:
            wrapper.begin_transition()
        else:
            wrapper.end_transition()

    def _on_video_stack_page_changed(self, _index: int = 0):
        """Keep native embed parked whenever video_container is not the top page."""
        stack = getattr(self, 'video_stack', None)
        container = getattr(self.ui, 'video_container', None) if hasattr(self, 'ui') else None
        if stack is None or container is None:
            return
        if stack.currentWidget() is not container:
            self._park_mpv_embed_when_not_showing()

    def _reset_player_placeholder_default(self):
        """Restore the idle Steempeg poster (centered logo, no game icon overlay)."""
        if not hasattr(self, 'place_logo') or not hasattr(self, 'place_text'):
            return
        # Use a pixmap only and clear any stylesheet image — mixing the two stacked a
        # stretched game icon behind the logo and left a square halo around it.
        from steempeg.ui.icon_utils import apply_square_icon, app_logo_pixmap

        self.place_logo.setStyleSheet("background: transparent; border: none;")
        apply_square_icon(self.place_logo, app_logo_pixmap(80, dpr=1.0), 80)
        self.place_logo.show()
        self.place_text.setText("Please select a clip from the library")
        self.place_text.setStyleSheet(
            "color: #888888; font-size: 14px; font-weight: bold; margin-top: 15px;"
        )

    def _media_path_is_in_use(self, path: str) -> bool:
        """True if *path* (file or clip folder) is the active preview / playback."""
        if not path:
            return False
        norm = os.path.normpath(path)
        candidates = (
            getattr(self, "_preview_clip_path", None),
            getattr(self, "_active_play_media_path", None),
            getattr(self, "_rendered_media_path", None),
            getattr(self, "_current_mpd_abs_path", None),
            getattr(self, "_current_play_abs_path", None),
        )
        for candidate in candidates:
            if not candidate:
                continue
            cn = os.path.normpath(str(candidate))
            if cn == norm:
                return True
            # Clip folder ↔ file inside it (Steam clips, future screenshot folders, …)
            if cn.startswith(norm + os.sep) or norm.startswith(cn + os.sep):
                return True
        return False

    def release_media_before_delete(self, path: str) -> bool:
        """Unload playback if *path* is currently open, so Windows can delete it.

        Resets the player to the idle placeholder (Please select a clip…).
        Returns True when playback was cleared.
        """
        if not self._media_path_is_in_use(path):
            return False
        self.close_current_clip()
        # Give mpv a beat to drop file handles before the caller deletes on disk.
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        return True

    def release_media_before_delete_any(self, paths) -> bool:
        """Unload once if any of *paths* is the active preview / playback."""
        for path in paths or ():
            if self._media_path_is_in_use(path):
                return self.release_media_before_delete(path)
        return False

    def close_current_clip(self):
        """ Completely destroys the current clip and clears the interface. """
        # Explicit Close must always work — a stuck switch gate (or Dead export
        # that never finished opening) used to no-op the X forever.
        if getattr(self, "_is_switching", False) or getattr(
            self, "_awaiting_first_frame", False
        ):
            if hasattr(self, "_clear_preview_switch_gates"):
                self._clear_preview_switch_gates()
            else:
                self._is_switching = False
                self._awaiting_first_frame = False

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
            from steempeg.ui.player_header_layout import set_player_header_game_text

            set_player_header_game_text(
                self,
                "Select a clip to preview...",
                placeholder=True,
            )
        if hasattr(self, 'custom_icon_label'):
            from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap
            from steempeg.ui.icon_utils import apply_square_icon
            from steempeg.ui.player_header_layout import player_header_icon_px

            unknown = get_resource_path("unknown_icon.png")
            icon_px = player_header_icon_px(self)
            self.custom_icon_label.setStyleSheet("background: transparent; border: none;")
            src = QPixmap(unknown)
            shaped = (
                shaped_game_icon_pixmap(src, icon_px, ICON_SHAPE_CIRCLE)
                if not src.isNull()
                else None
            )
            apply_square_icon(self.custom_icon_label, shaped, icon_px)
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
        # Drop export dock when Screenshots (or rendered preview) no longer has a raw clip.
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()

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
            if hasattr(self, "_sync_queue_player_and_dash_chrome"):
                self._sync_queue_player_and_dash_chrome()
            elif hasattr(self, 'reset_bottom_summary'):
                self.reset_bottom_summary()
        if hasattr(self.ui, 'label_detailed_summary'):
            # Queue card switches call close_current_clip mid-activate; skip the
            # placeholder so Final Render Details doesn't flash "Waiting…" over
            # the real summary (SummaryLabel also clears sync — see render_panel).
            if not getattr(self, "_loading_queue_job", False):
                self.ui.label_detailed_summary.setText("Waiting for clip selection...")
        if hasattr(self.ui, 'label_location'):
            self.ui.label_location.setText("")
        path_row = getattr(self.ui, "output_path_row", None)
        if path_row is not None:
            path_row.hide()
            
        # Keep Start enabled when the queue still has work, even with no preview clip.
        if hasattr(self.ui, 'btn_start'):
            if hasattr(self, "_sync_start_render_enabled"):
                self._sync_start_render_enabled()
            else:
                self.ui.btn_start.setEnabled(False)

        self._reset_player_placeholder_default()


    def _ignore_playback_stall(self, seconds=0.5):
        """Suppress stall / stale-EOF handling briefly after seeks or clip switches.

        Playhead updates keep running — only EOF latch and stall overlay grace
        use this window (freezing the whole UI timer used to park the scrubber
        at 0 then teleport when grace ended).
        """
        until = time.time() + seconds
        self._playback_ignore_stall_until = until
        self._ignore_vlc_until = until
        self._playback_last_time_pos = None
        self._playback_stall_since = None
        self._playback_recover_at = None

    def _get_buffering_overlay(self):
        overlay = getattr(self, '_buffering_overlay', None)
        if overlay is None:
            from steempeg.ui.player.buffering_overlay import BufferingOverlay
            # Unowned Tool on Windows — parenting to the shell made every Buffering
            # flicker re-stack Steempeg over Explorer / browser tabs.
            overlay = BufferingOverlay(parent=None)
            self._buffering_overlay = overlay
        return overlay

    def _set_playback_loading(self, active, message="Buffering…"):
        # Windows: never mount the floating Buffering Tool while MPV is alive.
        # Owned/transient Tools (and even “unowned” ones Qt re-parents) re-stack
        # the Steempeg shell over Explorer / Zen whenever the pill flickers on
        # stall — only with a clip open. v46 used a child overlay (no Z steal).
        if sys.platform == "win32":
            overlay = getattr(self, '_buffering_overlay', None)
            if overlay is not None:
                try:
                    overlay.hide_loading()
                except RuntimeError:
                    pass
            self._playback_loading_active = False
            self._playback_recover_at = None
            return
        # Render the indicator in a SEPARATE top-level tool window, never as a Qt
        # child over the native mpv surface — that overlap was the root cause of the
        # splitter stutter. A floating window composites independently and is safe.
        app = QApplication.instance()
        if active and (
            (app is not None and app.applicationState() != Qt.ApplicationState.ApplicationActive)
            or self._main_shell_is_minimized()
            or getattr(self, "_portable_clip_picker_open", False)
            or getattr(self, "_portable_render_settings_open", False)
        ):
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
        """True only while mpv has paused to wait for cache.

        Do not use cache-buffering-state: on local files it often stays at 100
        (fully filled) during healthy playback, which would pin the overlay on.
        """
        if not hasattr(self, 'player') or not self.player:
            return False
        try:
            return bool(getattr(self.player, 'paused_for_cache', False))
        except Exception:
            return False

    def _playback_frame_interval_sec(self):
        """Nominal video frame duration from mpv, or None if unknown."""
        if not hasattr(self, 'player') or not self.player:
            return None
        fps = None
        for attr in ('estimated_vf_fps', 'container_fps'):
            try:
                val = getattr(self.player, attr, None)
                if val is not None and float(val) > 0:
                    fps = float(val)
                    break
            except Exception:
                continue
        if not fps:
            return None
        return 1.0 / fps

    def _playback_stall_threshold_sec(self):
        """How long time_pos may stay flat before we treat it as buffering.

        Low-FPS files advance time_pos only on frame boundaries (1s steps at
        1 FPS). A fixed 0.35s threshold false-triggers between every frame and
        the 0.2s continuous-recovery debounce can never clear it.
        """
        base = 0.35
        frame_interval = self._playback_frame_interval_sec()
        if frame_interval is None:
            return base
        # One frame + timer/jitter margin; never tighter than the DASH default.
        return max(base, frame_interval + 0.25)

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

        # Quality-gear remux hold owns the overlay until seek restore lands.
        if getattr(self, '_remux_quality_hold_active', False):
            msg = getattr(self, "_remux_quality_hold_message", None) or "Buffering…"
            self._set_playback_loading(True, msg)
            return

        # Growing remux still encoding after seek restore: mpv often sits in
        # paused_for_cache / flat time_pos. Stall logic would pin "Buffering…"
        # forever — _tick keeps Showing Preparing % instead.
        remux_pair = getattr(self, "_progressive_remux", None)
        if remux_pair is not None:
            try:
                _gen, job = remux_pair
                if job is not None and job.poll() is None:
                    return
            except Exception:
                pass

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
                jump = 0.0 if last_pos is None else abs(time_sec - last_pos)
                self._playback_last_time_pos = time_sec
                self._playback_stall_since = None
                if getattr(self, '_playback_loading_active', False):
                    # Low-FPS clocks jump once per frame then sit flat. Clear on a
                    # real frame step; keep the short debounce only for tiny drifts.
                    if jump >= 0.15:
                        self._set_playback_loading(False)
                    elif self._playback_recover_at is None:
                        self._playback_recover_at = now
                    elif now - self._playback_recover_at >= 0.2:
                        self._set_playback_loading(False)
                return

            stall_limit = self._playback_stall_threshold_sec()
            if self._playback_stall_since is None:
                self._playback_stall_since = now
            elif now - self._playback_stall_since >= stall_limit:
                self._set_playback_loading(True, "Buffering…")
        except Exception:
            pass

    def _clear_preview_switch_gates(self) -> None:
        """Drop spam-click / first-frame gates (never leave these stuck)."""
        self._is_switching = False
        self._awaiting_first_frame = False

    def _arm_preview_switch_watchdog(self, switch_gen: int) -> None:
        """Hard timeout so a missed first-frame reveal cannot ignore clicks forever.

        Linux remux/DASH opens are where guards have stuck in the wild; Windows
        gets a shorter shared watchdog that is still past the soft 800ms finish.
        """
        delay_ms = 2500 if sys.platform != "win32" else 1500
        QTimer.singleShot(
            delay_ms, lambda g=switch_gen: self._preview_switch_watchdog_fire(g)
        )

    def _preview_switch_watchdog_fire(self, switch_gen: int) -> None:
        if switch_gen != getattr(self, "_media_switch_gen", 0):
            return
        stuck_switch = bool(getattr(self, "_is_switching", False))
        stuck_await = bool(getattr(self, "_awaiting_first_frame", False))
        if not stuck_switch and not stuck_await:
            return
        mpv_alive = False
        try:
            mpv_alive = bool(self._mpv_has_media())
        except Exception:
            mpv_alive = False
        logging.warning(
            "Preview switch watchdog: clearing stuck gates "
            "(switching=%s awaiting=%s mpv_media=%s gen=%s)",
            stuck_switch,
            stuck_await,
            mpv_alive,
            switch_gen,
        )
        # Prefer the normal reveal path when mpv already has media so timeline
        # thumbs / deferred chrome still run.
        if stuck_await:
            self._first_frame_deadline = 0
            self._reveal_video_when_ready()
        if getattr(self, "_is_switching", False) or getattr(
            self, "_awaiting_first_frame", False
        ):
            if hasattr(self, "video_stack") and hasattr(self.ui, "video_container"):
                try:
                    self.video_stack.setCurrentWidget(self.ui.video_container)
                except Exception:
                    pass
            self._kick_linux_embed_surface()
            self._finish_preview_switch(switch_gen)
            clip = getattr(self, "_preview_clip_path", None)
            if clip and hasattr(self, "_maybe_start_thumbs_after_quality"):
                self._maybe_start_thumbs_after_quality(clip)

    def _reveal_video_when_ready(self):
        """Swap the placeholder for the live mpv surface once the first frame exists.

        Polls mpv's decoded frame width (preferred) or an advancing time_pos
        (audio often starts first). Hard deadline so a hidden/idle surface can
        never leave us stuck on the placeholder — or a ClipCard ~70% spinner —
        forever while the UI thread is busy.
        """
        if not getattr(self, '_awaiting_first_frame', False):
            return
        switch_gen = getattr(self, "_preview_switch_gen", None)
        if switch_gen is not None and switch_gen != getattr(self, "_media_switch_gen", 0):
            return

        # "width" is set once mpv has decoded a video frame — safest reveal.
        # time_pos advancing means demux/decode is alive (often audio-first on
        # DASH); drop the card overlay then so we never sit on a stuck 70% while
        # sound already plays behind a blank stack page.
        ready = False
        playback_alive = False
        try:
            if self.player and self.player.width:
                ready = True
        except Exception:
            ready = True  # never get wedged on a transient property error

        if not ready:
            try:
                pos = self.player.time_pos if self.player else None
                if pos is not None and float(pos) >= 0.0:
                    playback_alive = True
            except Exception:
                playback_alive = False

        # Linux: if demux already reports a path and play is underway, treat as
        # alive even when width/time_pos lag — unblocks chrome after remux cache hits.
        if not ready and not playback_alive and sys.platform != "win32":
            try:
                if self._mpv_has_media() and not getattr(self.player, "pause", True):
                    playback_alive = True
            except Exception:
                pass

        if playback_alive and getattr(self, "_clip_open_loading_hosts", None):
            # Overlay tracks "open", not "surface visible" — hide as soon as
            # media is actually playing so we never sit on a stuck ~70% while
            # sound already plays. Keep _opening_clip_path for spam-click guards.
            self._hide_clip_open_loading_hosts()
            self._clip_open_load_pct = 100

        if not ready and time.time() < getattr(self, '_first_frame_deadline', 0):
            if (
                hasattr(self, "update_clip_open_loading_progress")
                and getattr(self, "_clip_open_loading_hosts", None)
            ):
                buf = self._clip_open_mpv_buffer_percent()
                if buf is not None:
                    pct = 70 + int(buf * 0.25)
                else:
                    t0 = getattr(self, "_clip_open_play_t0", None)
                    if t0:
                        elapsed = max(0.0, time.time() - float(t0))
                        pct = min(92, 70 + int(elapsed * 40))
                    else:
                        pct = 70
                self.update_clip_open_loading_progress(pct)
            QTimer.singleShot(16, self._reveal_video_when_ready)
            return

        # Deadline hit with audio-only so far — still show the surface rather
        # than leave a blank page under a playing soundtrack.
        if not ready and playback_alive:
            ready = True
        if not ready and time.time() >= getattr(self, '_first_frame_deadline', 0):
            ready = True

        self._awaiting_first_frame = False
        if hasattr(self, 'video_stack') and hasattr(self.ui, 'video_container'):
            self.video_stack.setCurrentWidget(self.ui.video_container)
        self._kick_linux_embed_surface()
        if sys.platform != "win32":
            QTimer.singleShot(0, self._kick_linux_embed_surface)
        # Switching gate can clear as soon as the new picture is visible.
        self._finish_preview_switch(switch_gen)
        clip = getattr(self, "_preview_clip_path", None)
        if clip and hasattr(self, "_maybe_start_thumbs_after_quality"):
            self._maybe_start_thumbs_after_quality(clip)
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
        path = getattr(self, '_current_play_abs_path', None) or getattr(self, '_current_mpd_abs_path', None)
        if not path or not hasattr(self, 'player') or not self.player:
            return
        try:
            self._ignore_playback_stall(0.8)
            self._ensure_linux_mpv_vo()
            self.player.play(path)
            self.player.pause = True
            if hasattr(self.ui, 'btn_play'):
                self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))
            if hasattr(self, 'custom_timeline'):
                self.custom_timeline.force_jump(0)
        except Exception:
            pass

    def _sync_play_button_icon(self, *, paused: bool | None = None) -> None:
        """Keep the centre play/pause glyph aligned with mpv pause state."""
        if not hasattr(self.ui, "btn_play"):
            return
        if paused is None:
            try:
                paused = bool(getattr(self.player, "pause", True))
            except Exception:
                paused = True
        icon_path = (
            get_resource_path("icon_play.png")
            if paused
            else get_resource_path("icon_pause.png")
        )
        self.ui.btn_play.setIcon(QIcon(icon_path))

    # VIDEO PLAYER CONTROLS
    def toggle_play(self):
        """ Toggles Play/Pause state in MPV and updates the button icon. """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled():
            return
        if not getattr(self, 'player', None):
            return
        try:
            if getattr(self.player, 'path', None) is None:
                return
        except Exception:
            # Dead libmpv core — drop handle; next clip click recreates it.
            self._discard_dead_linux_mpv()
            return

        try:
            if self.player.pause:
                dur = self._playback_duration_sec()
                try:
                    pos = self.player.time_pos
                except Exception:
                    pos = None
                if dur and pos is not None and float(pos) >= float(dur) - 0.05:
                    self._restart_from_eof = True
                    self._ignore_playback_stall(0.5)
                    self._safe_mpv_seek(0)
                    if hasattr(self, 'custom_timeline'):
                        self.custom_timeline.force_jump(0)
                self.player.pause = False
            else:
                self._restart_from_eof = False
                self.player.pause = True
            self._sync_play_button_icon(paused=self.player.pause)
        except Exception as exc:
            logging.warning("toggle_play ignored (mpv dead?): %s", exc)
            self._discard_dead_linux_mpv()
                
    def set_vlc_volume(self, value):
        """Pass volume to MPV with a perceptual curve (slider may exceed 100% when boost is on)."""
        if hasattr(self, 'player') and self.player:
            if value > 0:
                # Unity at 100%; >100% soft-amps (e.g. 200% → ~141, 500% → ~224 mpv).
                perceived_volume = (value / 100.0) ** 0.5 * 100.0
            else:
                perceived_volume = 0.0

            # mpv clamps above volume-max (default ~130); raise for boost ceilings.
            try:
                from steempeg.ui.player_boost import get_volume_boost_ceiling

                ceil_pct = max(int(value) if value else 0, get_volume_boost_ceiling(), 100)
                needed_max = (ceil_pct / 100.0) ** 0.5 * 100.0
                cur_max = float(self.player["volume-max"] or 100.0)
                if cur_max + 0.5 < needed_max:
                    self.player["volume-max"] = needed_max
            except Exception:
                pass

            self.player.volume = perceived_volume
    def set_vlc_speed(self, value):
        """ Passes the speed value to MPV (MPV handles pitch correction automatically) """
        if hasattr(self, 'player') and self.player:
            # Slider units are tenths (10 = 1.0x); ceiling may be 50 / 80 / 100.
            speed_float = value / 10.0
            self.player.speed = speed_float
            # Keep the timeline's playhead interpolation in sync with the real rate,
            # otherwise the playhead jitters at non-1x speeds (e.g. 0.1x when zoomed in).
            if hasattr(self, 'custom_timeline') and hasattr(self.custom_timeline, 'canvas'):
                self.custom_timeline.canvas.playback_speed = speed_float

    def _keep_deprecated_library_pill_hidden(self):
        """Old Clips Manager title pill — only hide if still the orphaned legacy widget.

        The live Grid/List + Sorting toolbar is ``library_toolbar_pill``; do not hide it
        when leaving theatre/fullscreen (that used to wipe the sort/filter row).
        """
        pill = getattr(self, "mega_top_pill", None)
        toolbar = getattr(self, "library_toolbar_pill", None)
        # Legacy name accidentally pointed at the toolbar — never hide that.
        if pill is not None and pill is not toolbar:
            if pill.objectName() == "deprecatedLibraryPill":
                pill.hide()

    def _set_left_library_panel_visible(self, visible: bool):
        """Toggle the whole library column — do not show/hide tab children individually."""
        # Warm Clips Manager borrows left_panel into its sheet. Hiding it for
        # theatre/fullscreen would leave Add a Clip opening an empty dialog.
        if (
            not visible
            and hasattr(self.ui, "left_panel")
            and self._portable_clip_picker_owns_library()
        ):
            return
        if hasattr(self.ui, 'left_panel'):
            self.ui.left_panel.setVisible(visible)
        elif hasattr(self.ui, 'table_clips'):
            left_wrapper = self.ui.table_clips.parentWidget()
            if left_wrapper and "Splitter" not in type(left_wrapper).__name__ and left_wrapper.objectName() != "centralwidget":
                left_wrapper.setVisible(visible)
            else:
                self.ui.table_clips.setVisible(visible)
        self._keep_deprecated_library_pill_hidden()

    def _portable_clip_picker_owns_library(self) -> bool:
        """True when left_panel currently lives inside the warm Clips Manager sheet."""
        panel = getattr(getattr(self, "ui", None), "left_panel", None)
        dlg = getattr(self, "_portable_clip_picker_dlg", None)
        if panel is None or dlg is None:
            return False
        try:
            w = panel
            while w is not None:
                if w is dlg:
                    return True
                w = w.parentWidget()
        except RuntimeError:
            return False
        return False

    def apply_portable_theatre_shell(self):
        """Steam Deck / portable shell: theatre-only, no docks. Locked until shell changes."""
        self._portable_shell = True
        # Keep comfort chrome — Deck-narrow width must not lerp settings/combos down.
        if hasattr(self, "_apply_responsive_layout_mins"):
            self._apply_responsive_layout_mins(apply_density=True)
        tb = getattr(self, "title_bar", None) or getattr(
            getattr(self, "ui", None), "title_bar", None
        )
        if tb is not None and hasattr(tb, "set_shell_tools_visible"):
            tb.set_shell_tools_visible(True)
        if hasattr(self, "_refresh_dev_button_visibility"):
            self._refresh_dev_button_visibility()
        if getattr(self, "is_fullscreen", False):
            return
        if not getattr(self, "is_theater", False):
            self.toggle_theater_mode()
        if hasattr(self, "btn_theater"):
            self.btn_theater.hide()
        from steempeg.ui.portable import ensure_portable_chrome

        ensure_portable_chrome(self)

    def toggle_theater_mode(self):
        """ Safely collapses side and bottom panels, aware of Fullscreen state, and swaps icon. """
        # Portable shell stays in theatre — exit would bring docks/splitters back.
        if getattr(self, "_portable_shell", False) and getattr(self, "is_theater", False):
            return

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
            self._set_splitter_handle_visible(self.ui.main_splitter, not self.is_theater)

        # Exit: honour Screenshots / rendered-preview dock rules (don't force-show
        # neo+dash then hide them a tick later — that double-laid-out the shell).
        if self.is_theater:
            dock_visible = False
            self._render_dock_visible = False
        else:
            dock_visible = True
            if hasattr(self, "_should_show_render_dock"):
                try:
                    dock_visible = bool(self._should_show_render_dock())
                except Exception:
                    dock_visible = True
            self._render_dock_visible = dock_visible

        if hasattr(self, 'bottom_v_wrap'):
            self.bottom_v_wrap.setVisible(dock_visible)

        if hasattr(self.ui, 'settings_tabs'):
            self.ui.settings_tabs.setVisible(dock_visible)
        if hasattr(self, 'neo_wrapper'):
            self.neo_wrapper.setVisible(dock_visible)

        if hasattr(self.ui, 'btn_start'):
            bottom_wrapper = self.ui.btn_start.parentWidget()
            if bottom_wrapper and "Splitter" not in type(bottom_wrapper).__name__ and bottom_wrapper.objectName() != "centralwidget":
                bottom_wrapper.setVisible(dock_visible)
        if hasattr(self, 'render_dashboard'):
            self.render_dashboard.setVisible(dock_visible)
        if hasattr(self, 'render_queue_panel'):
            self.render_queue_panel.setVisible(not self.is_theater)
        if hasattr(self, 'right_h_splitter') and self.is_theater:
            sizes = self.right_h_splitter.sizes()
            total = sum(sizes) if sum(sizes) > 0 else 1
            self.right_h_splitter.setSizes([total, 0])
            # Remember original handle geometry so we can restore the exact
            # same thickness as the left splitter (it is not always equal to
            # QUEUE_SPLITTER_GUTTER).
            live_w = int(self.right_h_splitter.handleWidth() or 0)
            self._pre_theater_right_handle_width = live_w if live_w > 0 else 6
            handle = self._splitter_handle(self.right_h_splitter, 1)
            self._pre_theater_right_handle_visible = (
                handle.isVisible() if handle is not None else True
            )
            # Collapse the queue splitter handle itself — otherwise a thick dark
            # strip remains on the right and breaks symmetry with the left edge.
            self._hide_right_h_splitter_handle()

        footer = getattr(self, "_footer_mega_pill", None)
        if footer is not None:
            footer.setVisible(not self.is_theater)

        if hasattr(self.ui, 'btn_about'): self.ui.btn_about.setVisible(not self.is_theater)
        if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.setVisible(not self.is_theater)
        if hasattr(self.ui, 'btn_settings'): self.ui.btn_settings.setVisible(not self.is_theater)

        if hasattr(self, 'video_wrapper'):
            if self.is_theater:
                self.video_wrapper.setStyleSheet("background-color: black; border: none;")
            else:
                try:
                    from steempeg.ui import ui_theme as ut

                    self.video_wrapper.setStyleSheet(ut.player_video_wrapper_stylesheet())
                except Exception:
                    self.video_wrapper.setStyleSheet(
                        "background-color: transparent; border: none;"
                    )

        # Player↔dock gap: 10px only when the bottom dock is actually shown.
        if hasattr(self, 'top_v_wrap') and self.top_v_wrap.layout():
            portable_like = False
            if hasattr(self, "_desktop_render_layout_is_portable_like"):
                try:
                    portable_like = bool(self._desktop_render_layout_is_portable_like())
                except Exception:
                    portable_like = False
            if self.is_theater or portable_like:
                margin_bottom = 0
            else:
                margin_bottom = 10 if dock_visible else 0
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
            try:
                restored_width = int(restored_width) if restored_width is not None else 6
            except (TypeError, ValueError):
                restored_width = 6
            if restored_width <= 0:
                restored_width = 6
            self.right_h_splitter.setHandleWidth(restored_width)
            restored_visible = getattr(self, '_pre_theater_right_handle_visible', None)
            if restored_visible is None:
                restored_visible = True
            self._set_splitter_handle_visible(self.right_h_splitter, bool(restored_visible))

            # Theatre forced the queue to 0; that is not a user collapse. Mirror
            # fullscreen's _exit_immersive_layout restore latch so sync reopens
            # the pane when it was open before theatre.
            pre_h = getattr(self, "_pre_theater_h_sizes", None)
            was_open = (
                isinstance(pre_h, (list, tuple))
                and len(pre_h) >= 2
                and int(pre_h[1]) > 48
            )
            if was_open:
                self._queue_user_collapsed = False
                self._queue_splitter_restore_open = True
                try:
                    self.right_h_splitter.setSizes([int(x) for x in pre_h])
                except Exception:
                    pass
                if hasattr(self, "_persist_queue_panel_open"):
                    try:
                        self._persist_queue_panel_open(True)
                    except Exception:
                        pass

        # Theatre keeps the normal content padding (only true fullscreen goes flush).
        restore_content_insets(self.ui)

        # --- THE MAGIC SWAP ---
        if hasattr(self, 'btn_theater'):
            if hasattr(self, "_apply_theater_button_icon"):
                self._apply_theater_button_icon(closed=bool(self.is_theater))
            elif self.is_theater:
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
                if hasattr(self, "_sync_chrome_button_icon_size"):
                    self._sync_chrome_button_icon_size(self.btn_theater)

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

    @staticmethod
    def _splitter_handle(splitter, index: int = 1):
        """Return splitter handle or None (portable may be single-pane → no handle)."""
        if splitter is None:
            return None
        try:
            if splitter.count() <= index:
                return None
            return splitter.handle(index)
        except Exception:
            return None

    def _set_splitter_handle_visible(self, splitter, visible: bool, index: int = 1) -> None:
        handle = self._splitter_handle(splitter, index)
        if handle is not None:
            handle.setVisible(bool(visible))

    def _save_right_h_splitter_handle(self, width_attr: str, visible_attr: str) -> None:
        splitter = getattr(self, "right_h_splitter", None)
        if splitter is None:
            return
        # Never snapshot an already-collapsed immersive width (0) as the restore
        # target — that is how the player|queue seam stays missing after FS exit.
        live_w = int(splitter.handleWidth() or 0)
        if live_w <= 0:
            live_w = int(getattr(self, "_pre_theater_right_handle_width", 0) or 0)
        if live_w <= 0:
            live_w = 6
        setattr(self, width_attr, live_w)
        handle = self._splitter_handle(splitter, 1)
        # Width-0 handles report not visible; still restore as shown for desktop.
        visible = True
        if handle is not None and live_w > 0:
            visible = bool(handle.isVisible())
        setattr(self, visible_attr, visible)

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
        try:
            width = int(width) if width is not None else 6
        except (TypeError, ValueError):
            width = 6
        if width <= 0:
            width = 6
        if visible is None:
            visible = True
        splitter.setHandleWidth(width)
        self._set_splitter_handle_visible(splitter, bool(visible))

    def _hide_right_h_splitter_handle(self) -> None:
        splitter = getattr(self, "right_h_splitter", None)
        if splitter is None:
            return
        self._set_splitter_handle_visible(splitter, False)
        splitter.setHandleWidth(0)

    def _clamp_queue_panel_for_immersive(self, collapsed: bool) -> None:
        """Collapse queue without hide() so the right_h handle survives Qt layout."""
        panel = getattr(self, "render_queue_panel", None)
        if panel is None:
            return
        if collapsed:
            if getattr(self, "_pre_immersive_queue_max_width", None) is None:
                try:
                    self._pre_immersive_queue_max_width = int(panel.maximumWidth())
                except Exception:
                    self._pre_immersive_queue_max_width = 16777215
            panel.setMinimumWidth(0)
            panel.setMaximumWidth(0)
            return
        saved = getattr(self, "_pre_immersive_queue_max_width", None)
        try:
            panel.setMaximumWidth(16777215 if saved is None else max(int(saved), 0))
        except Exception:
            panel.setMaximumWidth(16777215)
        self._pre_immersive_queue_max_width = None

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
        # Keep queue mapped: hide() drops the right_h handle until a later open.
        self._clamp_queue_panel_for_immersive(True)

    def _exit_immersive_layout(self, is_theater=False):
        # Stay collapsed when landing back in theatre (portable shell); only
        # desktop exit must reopen the queue maxWidth clamp.
        self._clamp_queue_panel_for_immersive(bool(is_theater))
        if hasattr(self.ui, 'main_splitter') and hasattr(self, '_immersive_main_splitter_sizes'):
            self.ui.main_splitter.setSizes(self._immersive_main_splitter_sizes)
        if hasattr(self, 'main_v_splitter') and hasattr(self, '_immersive_v_splitter_sizes'):
            self.main_v_splitter.setSizes(self._immersive_v_splitter_sizes)
        if hasattr(self, 'right_h_splitter') and hasattr(self, '_immersive_h_splitter_sizes'):
            self.right_h_splitter.setSizes(self._immersive_h_splitter_sizes)
        if not is_theater and hasattr(self, '_sync_queue_splitter_visibility'):
            # Immersive exit restores pre-collapse sizes; allow one reopen pass
            # if that snapshot had the queue open and the user had not collapsed.
            imm_h = getattr(self, '_immersive_h_splitter_sizes', None)
            if (
                imm_h is not None
                and len(imm_h) >= 2
                and int(imm_h[1]) > 48
                and not bool(getattr(self, '_queue_user_collapsed', False))
            ):
                self._queue_splitter_restore_open = True
            self._sync_queue_splitter_visibility()

    def _immersive_screen_geometry(self):
        screen = self.ui.screen() or QApplication.primaryScreen()
        return screen.geometry() if screen else self.ui.geometry()

    def _enter_immersive_chrome(self):
        if hasattr(self.ui, "title_bar"):
            self.ui.title_bar.hide()
        enter_immersive_chrome(self.ui, self._immersive_screen_geometry())
        try:
            from steempeg.ui.window_chrome import refresh_windows_edge_resize

            refresh_windows_edge_resize(self.ui)
        except Exception:
            pass
        self.ui.raise_()
        self.ui.activateWindow()

    def _is_player_idle_placeholder(self) -> bool:
        """True when the stack shows the idle 'Please select a clip…' page."""
        return (
            hasattr(self, 'video_stack')
            and hasattr(self, 'placeholder_frame')
            and self.video_stack.currentWidget() is self.placeholder_frame
        )

    def _show_immersive_transition_cover(self):
        # The cover masks whatever the enter/exit switch still flashes. Disable via
        # Settings → Advanced → TEST NEW FULLSCREEN, or STEEMPEG_FS_COVER=0.
        try:
            from steempeg.ui.settings_prefs import immersive_transition_cover_enabled

            cover_on = immersive_transition_cover_enabled()
        except Exception:
            cover_on = os.environ.get("STEEMPEG_FS_COVER") != "0"
        if not cover_on:
            self._immersive_cover_gen = getattr(self, '_immersive_cover_gen', 0) + 1
            return
        if getattr(self, '_immersive_transition_cover', None) is None:
            cover = QWidget()
            cover.setObjectName('immersiveTransitionCover')
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
        # Generation so a stale failsafe from enter cannot uncover mid-exit.
        self._immersive_cover_gen = getattr(self, '_immersive_cover_gen', 0) + 1
        gen = self._immersive_cover_gen
        QTimer.singleShot(900, lambda g=gen: self._hide_immersive_transition_cover_if(g))

    def _hide_immersive_transition_cover_if(self, gen: int) -> None:
        if getattr(self, '_immersive_cover_gen', 0) != gen:
            return
        self._hide_immersive_transition_cover()

    def _hide_immersive_transition_cover(self):
        cover = getattr(self, '_immersive_transition_cover', None)
        if cover is not None:
            cover.hide()

    def _reassert_frameless_caption(self) -> None:
        """Force NCCALCSIZE + dark DWM so native Aero caption cannot paint a frame."""
        try:
            # Full style re-assert (not only SetWindowPos) — cold first maximize
            # after fullscreen otherwise paints Aero for a frame.
            enable_frameless(self.ui)
            poke_frame(self.ui)
            refresh_dwm_chrome(self.ui)
            # RedrawWindow erases straight through Qt's disabled updates, and Qt
            # then declines to repaint — the erased edges are the black/transparent
            # frame around the video. The thaw repaints everything anyway.
            if not getattr(self, '_shell_paint_frozen', False):
                soft_full_redraw(self.ui)
        except Exception:
            pass
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _warmup_frameless_caption_under_cover(self) -> None:
        """One-shot under the gray cover: show title bar + enable_frameless.

        First fullscreen EXIT is the first time DWM sees title_bar visible again
        after a maximize — that cold path flashes Aero. Priming it on ENTER (still
        covered) makes the first EXIT behave like the second.
        """
        if getattr(self, "_frameless_caption_warmed", False):
            return
        if os.name != "nt":
            self._frameless_caption_warmed = True
            return
        tb = getattr(self.ui, "title_bar", None)
        was_hidden = tb is not None and not tb.isVisible()
        try:
            if tb is not None:
                tb.show()
                tb.sync_window_state()
            self._reassert_frameless_caption()
            if tb is not None:
                tb.update()
            self.ui.repaint()
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        finally:
            if was_hidden and tb is not None:
                tb.hide()
            self._frameless_caption_warmed = True
            try:
                from steempeg.ui.window_chrome import refresh_windows_edge_resize

                refresh_windows_edge_resize(self.ui)
            except Exception:
                pass

    def _finish_fullscreen_enter(self):
        """Drop the transition cover once the restore animation is done + repainted."""
        try:
            if not getattr(self, 'is_fullscreen', False):
                set_window_transitions(self.ui, True)
                self._freeze_mpv_surface(False)
                self._set_shell_paint_frozen(False)
                return
            # Re-assert full-monitor geometry: clearing the maximized state queues a
            # restore to the old (small) normalGeometry which, with transitions disabled,
            # overrides the setGeometry done in enter_immersive_chrome. Applying it here
            # (after Qt processed the state change) makes the fullscreen size stick.
            # Linux: also re-assert WindowFullScreen — setGeometry alone is clamped to
            # the KDE/GNOME work area (panel strip left uncovered).
            geo = self._immersive_screen_geometry()
            self.ui.setGeometry(geo)
            if sys.platform != "win32":
                try:
                    if not (self.ui.windowState() & Qt.WindowState.WindowFullScreen):
                        self.ui.showFullScreen()
                    else:
                        self.ui.setGeometry(geo)
                except Exception:
                    pass
            # Place the embed once, now that the fullscreen geometry is final.
            self._freeze_mpv_surface(False)
            self.ui.raise_()
            self.ui.activateWindow()
            self.ui.update()
            force_full_redraw(self.ui)
            # Flush the paint before lifting the cover so the first visible frame is
            # the finished fullscreen layout (no transparent edges / animation tail).
            QApplication.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
            )
            # Prime caption suppress while still covered — kills first-exit Aero flash.
            self._warmup_frameless_caption_under_cover()
            if hasattr(self, 'player_footer_frame'):
                self.align_fullscreen_hud()
                self.player_footer_frame.show()
                self.player_footer_frame.raise_()
            # Restore native min/max/restore animations that were disabled for the switch.
            set_window_transitions(self.ui, True)
            self._show_immersive_esc_hint()
        finally:
            self._freeze_mpv_surface(False)
            if getattr(self, 'is_fullscreen', False) and hasattr(self, 'player_footer_frame'):
                self.align_fullscreen_hud()
                self.player_footer_frame.show()
                self.player_footer_frame.raise_()
                if self._is_player_idle_placeholder() and hasattr(self, 'fs_timer'):
                    self.fs_timer.stop()
            # Thaw last, so the first frame the user sees is the finished layout.
            self._set_shell_paint_frozen(False)
            self.ui.repaint()
            self._hide_immersive_transition_cover()
            if getattr(self, 'is_fullscreen', False):
                self.ui.activateWindow()
                self.ui.setCursor(Qt.CursorShape.ArrowCursor)

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
            # Dark pill like the FS HUD strip. Do NOT use WA_TranslucentBackground —
            # on Windows that drops QLabel stylesheet fills (text-only ghost).
            # Rounded corners via setMask, same pattern as align_fullscreen_hud.
            from steempeg.ui import ui_theme as ut

            font_px = 15
            hint = QLabel("Press ESC to exit full screen")
            hint.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.NoDropShadowWindowHint
            )
            hint.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            hint.setStyleSheet(ut.immersive_esc_hint_stylesheet(font_px=font_px))
            font = hint.font()
            font = tok.pin_ui_font(font)
            font.setBold(True)
            font.setPixelSize(font_px)
            hint.setFont(font)
            self._immersive_esc_hint = hint
        return self._immersive_esc_hint

    def _refresh_immersive_esc_hint_chrome(self) -> None:
        """Restyle the ESC pill after Default ↔ TrueDark (cached QLabel)."""
        hint = getattr(self, "_immersive_esc_hint", None)
        if hint is None:
            return
        try:
            from steempeg.ui import ui_theme as ut

            hint.setStyleSheet(ut.immersive_esc_hint_stylesheet(font_px=15))
        except RuntimeError:
            pass

    def _position_immersive_esc_hint(self):
        hint = getattr(self, '_immersive_esc_hint', None)
        if hint is None:
            return
        screen_geo = self._immersive_screen_geometry()
        hint.adjustSize()
        w, h = hint.width(), hint.height()
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(w), float(h), 16.0, 16.0)
        hint.setMask(QRegion(path.toFillPolygon().toPolygon()))
        hint.move(
            screen_geo.x() + max(0, (screen_geo.width() - w) // 2),
            screen_geo.y() + 36,
        )

    def _show_immersive_esc_hint(self):
        hint = self._get_immersive_esc_hint()
        self._refresh_immersive_esc_hint_chrome()
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

    def _restore_windowed_chrome(self):
        """Title bar + maximized/normal state back, before the layout rebuild.

        The title bar has to be visible first so WM_NCCALCSIZE re-applies the
        maximized inset — a restored maximized window otherwise overhangs the
        monitor and covers the taskbar.
        """
        if hasattr(self.ui, "title_bar"):
            self.ui.title_bar.show()
        try:
            from steempeg.ui.window_chrome import refresh_windows_edge_resize

            refresh_windows_edge_resize(self.ui)
        except Exception:
            pass
        # Soft-redraw during the switch can flash Aero chrome at the edges.
        self.ui._suppress_dwm_ghost_timer = True
        _fstrace("EXIT window state restore start")
        exit_immersive_chrome(self.ui)
        _fstrace("EXIT window state restore done")
        # showMaximized re-adds the native Aero caption for a frame or two.
        self._reassert_frameless_caption()
        if hasattr(self.ui, "title_bar"):
            self.ui.title_bar.sync_window_state()

    def _exit_immersive_mode(self):
        """Restore UI under a solid cover, then title bar — avoids MPV-only flash."""
        is_t = getattr(self, 'is_theater', False)
        _fstrace("EXIT begin (theatre=%s)", is_t)
        self._freeze_mpv_surface(True)

        self._show_immersive_transition_cover()
        self._set_shell_paint_frozen(True)
        # Same as enter: kill the SW_RESTORE/maximize cross-fade so exit is instant
        # under the cover (no torn animation / desktop bleed). Restored in finish_exit.
        set_window_transitions(self.ui, False)
        # Back to the windowed state *first*. Doing it after the rebuild meant every
        # panel and the video were laid out at monitor size and then again at the
        # final size — 9 mpv surface moves per exit, and the visible sequence of the
        # video container swallowing the footer strip before being pushed back.
        self._restore_windowed_chrome()
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
        footer = getattr(self, "_footer_mega_pill", None)
        if footer is not None:
            footer.setVisible(not is_t)
            if hasattr(self.ui, 'btn_about'):
                self.ui.btn_about.setVisible(not is_t)
            if hasattr(self.ui, 'btn_update_check'):
                self.ui.btn_update_check.setVisible(not is_t)
            if hasattr(self.ui, 'btn_settings'):
                self.ui.btn_settings.setVisible(not is_t)

        if hasattr(self, 'player_header_frame'):
            self.player_header_frame.show()
        if hasattr(self.ui, 'main_splitter'):
            self._set_splitter_handle_visible(self.ui.main_splitter, not is_t)
        if hasattr(self, 'main_v_splitter'):
            self._set_splitter_handle_visible(self.main_v_splitter, not is_t)

        if hasattr(self, 'top_v_wrap') and self.top_v_wrap.layout():
            margin_bottom = 0 if is_t else 10
            self.top_v_wrap.layout().setContentsMargins(0, 0, 0, margin_bottom)
        if hasattr(self, 'video_wrapper'):
            from steempeg.ui import ui_theme as ut

            self.video_wrapper.setStyleSheet(ut.player_video_wrapper_stylesheet())

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

        _fstrace("EXIT footer reparent start")
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
        from steempeg.ui.design_tokens import with_tooltip_style
        from steempeg.ui import ui_theme as ut

        # Same windowed HUD QSS as init (radius 6, themed fill) — not the floating FS HUD.
        footer.setStyleSheet(with_tooltip_style(ut.player_footer_stylesheet()))
        if hasattr(self, "_apply_playback_button_styles"):
            self._apply_playback_button_styles()
        if hasattr(self, "_refresh_player_footer_chrome"):
            self._refresh_player_footer_chrome()

        _fstrace("EXIT footer reparent done")
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

        _fstrace("EXIT panels restored, activating layouts")
        self._activate_window_layouts()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        _fstrace("EXIT layouts activated (already at final window size)")

        def finish_exit():
            gen = getattr(self, '_immersive_cover_gen', 0)
            try:
                self._activate_window_layouts()
                footer.show()
                _fstrace("EXIT footer shown")
                if right_layout:
                    right_layout.activate()
                if hasattr(self, 'btn_fullscreen'):
                    self.btn_fullscreen.clearFocus()
                    QApplication.postEvent(self.btn_fullscreen, QEvent(QEvent.Type.Leave))
                if hasattr(self, 'btn_theater'):
                    self.btn_theater.clearFocus()
                    QApplication.postEvent(self.btn_theater, QEvent(QEvent.Type.Leave))
                self._set_hide_watcher_suppressed(False)
                self.ui.right_panel.updateGeometry()
                # First EXIT is colder (DWM hasn't seen title_bar+maximize yet this
                # session unless enter warmup ran). Hold cover longer + double poke.
                first_exit = not getattr(self, "_fullscreen_exit_settled", False)
                settle_ms = 320 if first_exit else 140
                QTimer.singleShot(
                    settle_ms, lambda g=gen, first=first_exit: self._finish_exit_uncover(g, first)
                )
            except Exception:
                self.ui._suppress_dwm_ghost_timer = False
                set_window_transitions(self.ui, True)
                self._freeze_mpv_surface(False)
                self._set_shell_paint_frozen(False)
                self._hide_immersive_transition_cover()

        QTimer.singleShot(0, finish_exit)

    def _finish_exit_uncover(self, gen: int, first_exit: bool = False) -> None:
        if getattr(self, '_immersive_cover_gen', 0) != gen:
            self._freeze_mpv_surface(False)
            self._set_shell_paint_frozen(False)
            return
        # Layout has settled — place the embed once at its final rect.
        self._freeze_mpv_surface(False)
        try:
            self._reassert_frameless_caption()
            if first_exit:
                # Second pass after a tick — first maximize after FS still races once.
                QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                self._reassert_frameless_caption()
            if hasattr(self.ui, "title_bar") and self.ui.title_bar.isVisible():
                self.ui.title_bar.sync_window_state()
                self.ui.title_bar.update()
        finally:
            self._fullscreen_exit_settled = True
            self.ui._suppress_dwm_ghost_timer = False
            set_window_transitions(self.ui, True)
            # Thaw last, so the first frame the user sees is the finished layout.
            self._set_shell_paint_frozen(False)
            # Re-assert player|queue handle after uncover — styles applied while
            # frozen (or after handleWidth 0) can leave the right seam missing.
            if not getattr(self, "is_theater", False) and not getattr(
                self, "is_fullscreen", False
            ):
                try:
                    from steempeg.ui.portable_splitter_reveal import (
                        ensure_right_h_handle_chrome,
                    )

                    ensure_right_h_handle_chrome(self)
                except Exception:
                    self._restore_right_h_splitter_handle()
            self.ui.repaint()
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            self._hide_immersive_transition_cover()
            _fstrace("EXIT complete (thawed)")

    def toggle_fullscreen(self):
        """Immersive player mode: hide chrome inside the current window (no showFullScreen)."""
        
        if getattr(self, 'fullscreen_lock', False): return
        self.fullscreen_lock = True
        QTimer.singleShot(200, lambda: setattr(self, 'fullscreen_lock', False))

        self.is_fullscreen = not getattr(self, 'is_fullscreen', False)
        if hasattr(self, "_apply_fullscreen_button_icon"):
            self._apply_fullscreen_button_icon(fullscreen=self.is_fullscreen)

        if self.is_fullscreen:
            _fstrace("ENTER begin")
            self._freeze_mpv_surface(True)
            # --- ENTERING IMMERSIVE MODE (stay maximized / current window state) ---
            # Mask the whole transition with a solid cover: while growing the window
            # from the work area to the full monitor, Windows briefly paints the native
            # frame and leaves a stale "ghost" strip at the old bottom. The cover hides
            # all of that until the surface is rebuilt and repainted.
            self._show_immersive_transition_cover()

            came_from_theater = getattr(self, 'is_theater', False)
            if came_from_theater:
                self.is_theater = False
                if hasattr(self, "_apply_theater_button_icon"):
                    self._apply_theater_button_icon(closed=False)
                elif hasattr(self, 'btn_theater'):
                    icon_path = get_resource_path("theatremode.png")
                    if os.path.exists(icon_path):
                        self.btn_theater.setIcon(QIcon(icon_path))
                    else:
                        self.btn_theater.setText("🎦")
                    if hasattr(self, "_sync_chrome_button_icon_size"):
                        self._sync_chrome_button_icon_size(self.btn_theater)

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
                # Theatre already zeroed the right handle — copy the pre-theatre
                # snapshot so FS exit does not restore width 0.
                pre_w = int(getattr(self, "_pre_theater_right_handle_width", 0) or 0)
                self._immersive_right_h_handle_width = pre_w if pre_w > 0 else 6
                self._immersive_right_h_handle_visible = bool(
                    getattr(self, "_pre_theater_right_handle_visible", True)
                )
            elif hasattr(self, 'right_h_splitter'):
                self._save_right_h_splitter_handle(
                    '_immersive_right_h_handle_width',
                    '_immersive_right_h_handle_visible',
                )

            # Grow to the monitor *before* tearing the layout down, mirroring the
            # exit: the shell is then laid out once, at the final size. From
            # maximized this only claims the taskbar band, so the one frame that
            # is still painted here barely moves. Everything after is frozen.
            set_window_transitions(self.ui, False)
            self._enter_immersive_chrome()
            self._set_shell_paint_frozen(True)

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
            footer = getattr(self, "_footer_mega_pill", None)
            if footer is not None:
                footer.hide()
            if hasattr(self.ui, 'btn_about'): self.ui.btn_about.hide()
            if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.hide()
            if hasattr(self.ui, 'btn_settings'): self.ui.btn_settings.hide()

            if hasattr(self.ui, 'main_splitter'):
                self._set_splitter_handle_visible(self.ui.main_splitter, False)
            if hasattr(self, 'main_v_splitter'):
                self._set_splitter_handle_visible(self.main_v_splitter, False)
            
            if hasattr(self, 'bottom_v_wrap'): 
                self.bottom_v_wrap.hide()
            
            # Collapse the 10px margin that the splitter had
            if hasattr(self, 'top_v_wrap') and self.top_v_wrap.layout():
                self.top_v_wrap.layout().setContentsMargins(0, 0, 0, 0)
                
            # Set the background to black (removes gray bars at the edges of the video)
            if hasattr(self, 'video_wrapper'):
                from steempeg.ui import ui_theme as ut

                self.video_wrapper.setStyleSheet(
                    ut.player_video_wrapper_stylesheet(
                        background="black", chrome_outline=False
                    )
                )

            # Idle fullscreen: keep the native mpv HWND parked so it cannot cover
            # the "Please select a clip…" placeholder with an empty gray surface.
            if self._is_player_idle_placeholder():
                self._park_mpv_embed_when_not_showing()
            
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

            self._enter_immersive_layout()
            if hasattr(self, 'right_h_splitter'):
                self._hide_right_h_splitter_handle()
            # Resolve the immersive layout, then place the embed once. Leaving the
            # placement to the 120 ms finish step left the video sitting at its
            # windowed rect, framed by the black wrapper, for the first frames.
            self._activate_window_layouts()
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            self._freeze_mpv_surface(False)

            self.player_footer_frame.setParent(self.ui)
            self.player_footer_frame.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            
            self.player_footer_frame.setObjectName("HudFrame")
            from steempeg.ui.design_tokens import with_tooltip_style
            self.player_footer_frame.setStyleSheet(with_tooltip_style("""
                QFrame#HudFrame {
                    background-color: rgba(25, 25, 25, 200);
                    border-radius: 16px;
                    border: none;
                }
                QFrame#HudFrame QPushButton, QFrame#HudFrame QToolButton {
                    background-color: transparent;
                    border: none;
                }
            """))
            # Shown once, aligned, by _finish_fullscreen_enter. Showing it here too
            # meant two appearances (here, then again after the geometry re-assert),
            # which read as the floating panel blinking twice.
            _fstrace("ENTER footer promoted to floating HUD")

            if hasattr(self, 'wake_up_fullscreen_controls'):
                self.wake_up_fullscreen_controls()
            # Same gray-cover path for idle and with-clip — no fast un-maximize
            # animation that corrupts the restore size.
            QTimer.singleShot(120, self._finish_fullscreen_enter)
            
        else:
            # Fullscreen enter clears is_theater; portable must land back in theatre.
            # Re-flag it *before* the exit runs: otherwise the exit takes the desktop
            # restore path and re-shows every dock for a frame before the theatre
            # shell hides them again. Setting it here also lets
            # apply_portable_theatre_shell skip toggle_theater_mode, whose
            # pre-theatre splitter snapshot would capture the collapsed sizes.
            if getattr(self, "_portable_shell", False):
                self.is_theater = True
            self._exit_immersive_mode()
            if getattr(self, "_portable_shell", False):
                QTimer.singleShot(0, self.apply_portable_theatre_shell)
            # Desktop handle paint is deferred to _finish_exit_uncover so it runs
            # after shell thaw (painting while frozen left the right seam missing).

    
    def align_fullscreen_hud(self):
        """ Calculates global coordinates and aligns the floating panel. """
        if not getattr(self, 'is_fullscreen', False) or not hasattr(self, 'player_footer_frame'):
            return

        footer = self.player_footer_frame
        footer.adjustSize()
        w = self.ui.width()
        h = self.ui.height()
        footer_h = max(footer.sizeHint().height(), footer.size().height(), 120)

        # Get the global coordinates of the window itself.
        global_pos = self.ui.mapToGlobal(self.ui.rect().topLeft())

        hud_w = max(320, w - 80)
        hud_x = global_pos.x() + 40
        hud_y = global_pos.y() + h - footer_h - 15

        # Place the glass shard exactly in the center.
        footer.setGeometry(hud_x, hud_y, hud_w, footer_h)
        footer.show()
        footer.raise_()

        #Applying the Rounding Mask
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(hud_w), float(footer_h), 16.0, 16.0)
        region = QRegion(path.toFillPolygon().toPolygon())
        footer.setMask(region)
    def hide_floating_overlays(self) -> None:
        """Hide Tool/ToolTip chrome that does not follow main-window minimize.

        Buffering pill and screenshot toast are separate top-level windows so
        they don't recompose over mpv — but that also means they linger on the
        desktop when the shell is minimized. Call this from MainWindow state/hide.
        """
        overlay = getattr(self, "_buffering_overlay", None)
        if overlay is not None:
            overlay.hide_loading()
        self._playback_loading_active = False
        self._playback_recover_at = None
        self._hide_screenshot_toast()
        # Timeline hover Tools are owned by the shell — hide on focus loss so a
        # leftover tip cannot re-stack Steempeg over Explorer.
        tl = getattr(self, "custom_timeline", None)
        if tl is not None:
            try:
                pw = getattr(tl, "preview_widget", None)
                if pw is not None:
                    pw.hide()
                tip = getattr(getattr(tl, "canvas", None), "text_tooltip", None)
                if tip is None:
                    tip = getattr(tl, "text_tooltip", None)
                if tip is not None:
                    tip.hide()
            except RuntimeError:
                pass

    def _main_shell_is_minimized(self) -> bool:
        ui = getattr(self, "ui", None)
        try:
            return ui is not None and (ui.isMinimized() or not ui.isVisible())
        except RuntimeError:
            return True

    def hide_hud_on_minimize(self, state):

        # Floating Tools (Buffering / toast) must die the instant we lose focus —
        # otherwise a late show() mid Explorer-open re-stacks Steempeg on top.
        if state != Qt.ApplicationState.ApplicationActive:
            self.hide_floating_overlays()
            overlay = getattr(self, "_buffering_overlay", None)
            if overlay is not None and hasattr(overlay, "note_foreground_lost"):
                try:
                    overlay.note_foreground_lost()
                except RuntimeError:
                    pass
            if sys.platform == "win32":
                try:
                    from steempeg.infra.window_focus import on_shell_lost_foreground

                    on_shell_lost_foreground(self.ui)
                except Exception:
                    pass

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

        # Do not raise the floating HUD over an open QMenu — both are stays-on-top
        # Tool/Popup windows; a late raise_() buries the menu visually while the
        # popup grab still delivers clicks (invisible but clickable).
        popup = QApplication.activePopupWidget()
        tl = getattr(self, "custom_timeline", None)
        canvas = getattr(tl, "canvas", None) if tl is not None else None
        menu_open = popup is not None or (
            canvas is not None and getattr(canvas, "_context_menu_open", False)
        )
        
        self.ui.setCursor(Qt.ArrowCursor) 
        if hasattr(self, 'player_footer_frame'):
            if self.player_footer_frame.isHidden():
                # Align on the way in only: a freshly re-flagged Tool window would
                # otherwise flash at its layout-derived full width. On plain mouse
                # motion the HUD is already placed — leave its geometry alone.
                self.align_fullscreen_hud()
            self.player_footer_frame.show()
            if not menu_open:
                self.player_footer_frame.raise_()
            elif popup is not None:
                popup.raise_()
        # Same as desktop with a clip playing — auto-hide the bar. Idle (no clip)
        # keeps the floating HUD up: it is the only exit affordance on a gray canvas.
        if self._is_player_idle_placeholder():
            if hasattr(self, 'fs_timer'):
                self.fs_timer.stop()
            return
        self.fs_timer.start()           

    def sleep_fullscreen_controls(self):
        """ Completely terminates cursor rendering and hides controls layer after 3 seconds of stagnation. """
        if not getattr(self, 'is_fullscreen', False): return
        if self._is_player_idle_placeholder():
            # Do not blank the cursor / hide the bar — matches desktop expectation
            # that the player chrome stays present when nothing is loaded.
            if hasattr(self, 'player_footer_frame'):
                self.player_footer_frame.show()
                self.player_footer_frame.raise_()
            self.ui.setCursor(Qt.CursorShape.ArrowCursor)
            return

        # Marker / timeline QMenu (and any other popup) lives outside the HUD
        # Tool window — underMouse() is false while the cursor is on the menu,
        # and hiding the HUD would tear the menu down mid-interaction.
        # Also honor the canvas flag: on some Win32 stacks activePopupWidget()
        # can briefly miss a Tool-parented QMenu while it is still exec()'ing.
        if QApplication.activePopupWidget() is not None:
            self.fs_timer.start()
            return
        tl = getattr(self, "custom_timeline", None)
        canvas = getattr(tl, "canvas", None) if tl is not None else None
        if canvas is not None and getattr(canvas, "_context_menu_open", False):
            self.fs_timer.start()
            return
        
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
        from steempeg.ui.design_tokens import (
            STYLE_TRIM_BUTTON,
            STYLE_TRIM_CANCEL_BUTTON,
        )

        if active:
            cancel_icon_path = get_resource_path("cancel.png")
            if os.path.exists(cancel_icon_path):
                self.btn_trim.setIcon(QIcon(cancel_icon_path))
                self.btn_trim.setText(" Cancel")
            else:
                self.btn_trim.setIcon(QIcon())
                self.btn_trim.setText("❌ Cancel")
            self.btn_trim.setStyleSheet(STYLE_TRIM_CANCEL_BUTTON)
            # Visibility animated in sync_trim_tools_placement.
        else:
            trim_icon_path = get_resource_path("trim_icon.png")
            if os.path.exists(trim_icon_path):
                self.btn_trim.setIcon(QIcon(trim_icon_path))
                self.btn_trim.setText(" Trim")
            else:
                self.btn_trim.setIcon(QIcon())
                self.btn_trim.setText("✂️ Trim")
            self.btn_trim.setStyleSheet(STYLE_TRIM_BUTTON)
            self._apply_video_border(False)
        from steempeg.ui.player.controls.adaptive_trim_tools import (
            sync_trim_tools_placement,
        )

        sync_trim_tools_placement(self)

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

    def _deferred_apply_open_seek(self, attempts: int = 0) -> None:
        """Seek after Open related clip once MPV has duration + a playable first frame.

        Waits for a known duration before clamping — seeking with duration 0 / stale
        canvas length was clamping huge offsets (or EOF latches) to the end on the
        second open of the same screenshot.
        """
        pending = getattr(self, "_pending_open_seek", None)
        if not pending:
            self._open_seek_timer_armed = False
            return
        try:
            want_key = pending[0]
            seek_sec = float(pending[1])
            seek_gen = pending[2] if len(pending) > 2 else None
        except (TypeError, ValueError, IndexError):
            self._pending_open_seek = None
            self._open_seek_timer_armed = False
            return
        if seek_gen is not None and seek_gen != getattr(self, "_open_seek_gen", 0):
            # Superseded by a newer Open related clip request.
            self._open_seek_timer_armed = False
            return
        preview_key = self._norm_clip_path_key(
            getattr(self, "_preview_clip_path", None)
        )
        if want_key != preview_key:
            self._pending_open_seek = None
            self._open_seek_timer_armed = False
            return
        if (
            getattr(self, "_is_switching", False)
            or getattr(self, "_awaiting_first_frame", False)
            or not self._mpv_has_media()
        ):
            if attempts < 60:
                QTimer.singleShot(
                    50, lambda a=attempts + 1: self._deferred_apply_open_seek(a)
                )
            else:
                logging.debug("Open seek abandoned (player not ready)")
                self._pending_open_seek = None
                self._open_seek_timer_armed = False
            return

        if seek_sec <= 0:
            self._pending_open_seek = None
            self._open_seek_timer_armed = False
            return

        # Prefer a known duration so we never slam to EOF on a bad/unknown length.
        dur = self._playback_duration_sec()
        if dur is None or dur <= 0:
            if attempts < 60:
                QTimer.singleShot(
                    50, lambda a=attempts + 1: self._deferred_apply_open_seek(a)
                )
            else:
                logging.debug("Open seek abandoned (duration unknown)")
                self._pending_open_seek = None
                self._open_seek_timer_armed = False
            return

        target = max(0.0, float(seek_sec))
        # Guard against ms-treated-as-sec (and wall-clock blowups): past EOF by a
        # wide margin is not a valid capture offset — skip instead of clamp-to-end.
        if target > float(dur) + 2.0:
            # Classic unit mixup: value looks like milliseconds of a short-ish clip.
            as_sec = target / 1000.0
            if 0.0 <= as_sec <= float(dur) + 1.0:
                logging.info(
                    "Open seek %.2f looked like ms — using %.2fs", target, as_sec
                )
                target = as_sec
            else:
                logging.warning(
                    "Open seek %.2fs past duration %.2fs — skipping (not clamping to end)",
                    target,
                    dur,
                )
                self._pending_open_seek = None
                self._open_seek_timer_armed = False
                return
        target = min(target, max(0.0, float(dur) - 0.05))
        if target <= 0:
            self._pending_open_seek = None
            self._open_seek_timer_armed = False
            return

        self._pending_open_seek = None
        self._open_seek_timer_armed = False
        # Keep timeline length in sync before force_jump (stale 0 / prior clip).
        if hasattr(self, "custom_timeline"):
            try:
                self.custom_timeline.set_duration(int(float(dur) * 1000))
            except Exception:
                pass
        self._ignore_playback_stall(1.0)
        target_ms = int(target * 1000)
        timeline = getattr(self, "custom_timeline", None)
        if timeline is not None and hasattr(timeline, "force_jump"):
            timeline.force_jump(target_ms)
            logging.info("Related-clip seek to %.2fs (dur=%.2fs)", target, dur)
            return
        if self._safe_mpv_seek(target):
            logging.info("Related-clip seek to %.2fs (dur=%.2fs)", target, dur)

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

    def _mpv_has_media(self) -> bool:
        """True when mpv has a playable path (seek/pause are safe)."""
        player = getattr(self, "player", None)
        if not player:
            return False
        try:
            path = getattr(player, "path", None)
        except Exception:
            self._discard_dead_linux_mpv()
            return False
        return bool(path)

    def _safe_mpv_seek(self, position_sec: float, *, precision: str = "exact") -> bool:
        """Absolute seek that never raises — mpv COMMAND (-12) when idle/loading.

        Returns True if the seek was issued without error.
        """
        if not self._mpv_has_media():
            return False
        if getattr(self, "_is_switching", False) or getattr(self, "_awaiting_first_frame", False):
            return False
        player = self.player
        try:
            player.seek(float(position_sec), reference="absolute", precision=precision)
            return True
        except SystemError as exc:
            # libmpv MPV_ERROR_COMMAND (-12) — nothing loaded / demuxer not ready.
            logging.debug("mpv seek ignored: %s", exc)
            return False
        except Exception as exc:
            logging.debug("mpv seek failed: %s", exc)
            return False

    def on_timeline_press(self):
        """ Triggered when the user clicks on the timeline track. """
        if not self._mpv_has_media():
            self.was_playing_before_drag = False
            return
        try:
            self.was_playing_before_drag = not self.player.pause
            self.player.pause = True
        except Exception:
            self.was_playing_before_drag = False

    def on_timeline_seek(self, position_ms):
        """ Commands MPV to jump. """
        if not hasattr(self, 'custom_timeline') or not self.custom_timeline.isEnabled():
            return
        if self._safe_mpv_seek(position_ms / 1000.0):
            self._ignore_playback_stall(0.6)

    def on_timeline_release(self):
        """ Triggered when the user releases the mouse button after dragging. """
        if not self._mpv_has_media():
            return
        try:
            if getattr(self, 'was_playing_before_drag', False):
                self.player.pause = False
            if hasattr(self, 'is_muted'):
                self.player.mute = self.is_muted
        except Exception:
            pass

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
        canvas.current_clip_path = None
        canvas.current_offset_ms = 0
        canvas.rendered_media_path = None
        canvas._hover_preview_bucket = -1
        canvas._batch_thumbs_busy = False
        if hasattr(canvas, "notify_markers_changed"):
            canvas.notify_markers_changed(animate=True)
        else:
            canvas.update()

    def _begin_preview_switch(self) -> int:
        """Pause MPV and stop background workers before loading another file."""
        self._media_switch_gen = getattr(self, "_media_switch_gen", 0) + 1
        self._stop_timeline_markers_worker()
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
            # Drop the previous demuxer immediately so the last frame cannot linger
            # under the blank page while the next clip opens.
            try:
                self.player.command("stop")
            except Exception:
                try:
                    self.player.stop()
                except Exception:
                    pass

        if hasattr(self, "custom_timeline"):
            try:
                # Drop stale length so deferred related-clip seek cannot force_jump
                # against the previous clip's duration (clamp-to-end on reopen).
                self.custom_timeline.set_duration(0)
                # Hard-reset the stick — set_vlc_time alone used to no-op while
                # paused (1 FPS pause fix) and left the playhead at the old end.
                canvas = getattr(self.custom_timeline, "canvas", None)
                if canvas is not None:
                    canvas.visual_ms = 0.0
                    canvas.target_ms = 0.0
                    canvas.is_playing = False
                    canvas.vlc_last_update_time = time.time()
                else:
                    self.custom_timeline.set_vlc_time(0, False)
            except Exception:
                pass
        # Duration will be re-applied when the new media reports length.
        if hasattr(self, "current_clip_duration_sec"):
            self.current_clip_duration_sec = 0.0

        return self._media_switch_gen

    def _finish_preview_switch(self, switch_gen: int | None = None) -> None:
        """Clear the switching gate and apply deferred trim once duration is ready."""
        if switch_gen is not None and switch_gen != getattr(self, "_media_switch_gen", 0):
            return
        was_awaiting = bool(getattr(self, "_awaiting_first_frame", False))
        # Soft 800ms finish (and watchdog) must clear BOTH gates — awaiting alone
        # still blocks seeks, same-clip spam guards, and related-clip open.
        self._awaiting_first_frame = False
        if hasattr(self, "custom_timeline"):
            self.custom_timeline.setEnabled(True)
        self._is_switching = False
        if was_awaiting:
            logging.debug(
                "Preview switch finished while first-frame still pending (gen=%s)",
                switch_gen,
            )
            if hasattr(self, "video_stack") and hasattr(self.ui, "video_container"):
                try:
                    self.video_stack.setCurrentWidget(self.ui.video_container)
                except Exception:
                    pass
            self._kick_linux_embed_surface()
            if sys.platform != "win32":
                QTimer.singleShot(0, self._kick_linux_embed_surface)
        if hasattr(self, "clear_clip_open_loading"):
            self.clear_clip_open_loading()
        has_trim = bool(getattr(self, "_pending_trim_restore", None))
        if has_trim:
            QTimer.singleShot(50, self._deferred_apply_trim_restore)
        elif hasattr(self, "_loading_queue_job"):
            self._loading_queue_job = False
        # Related-clip screenshot seek — after first frame (and after trim restore).
        # Arm once: reveal + 800ms safety both call finish; don't stack seek chains.
        if getattr(self, "_pending_open_seek", None) and not getattr(
            self, "_open_seek_timer_armed", False
        ):
            self._open_seek_timer_armed = True
            QTimer.singleShot(
                150 if has_trim else 50, self._deferred_apply_open_seek
            )
        # Health badge / quality populate after first paint — markers load in parallel.
        self._flush_deferred_clip_open_work(switch_gen)

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
        """Duration for a flat export — trust the file, not trim/source sidecar guesses.

        Old companions often stored trim/source length as ``duration_sec``, which made
        the purple bar longer/shorter than playable media for every Rendered clip.
        """
        path = getattr(self, "_rendered_media_path", None)
        if not path:
            return None

        cache = getattr(self, "_rendered_duration_cache", None)
        if cache and cache[0] == os.path.normpath(path):
            return cache[1]

        meta = load_rendered_companion_meta(
            path, cache_dir=getattr(self, "cache_dir", None)
        ) or {}

        def _diverge(a: float, b: float) -> bool:
            diff = abs(a - b)
            if diff <= 0.75:
                return False
            return diff > max(0.75, min(a, b) * 0.02)

        # 1) Probe the file (stream first via ffprobe).
        probed = probe_media_duration_sec(path)

        # 2) MPV duration once ready — reject frozen-tail inflation vs probe.
        mpv_dur = None
        try:
            dur = self.player.duration
            if is_sane_media_duration(dur):
                mpv_dur = float(dur)
        except Exception:
            pass

        if probed is not None:
            if mpv_dur is not None and _diverge(probed, mpv_dur) and mpv_dur > probed:
                val = probed
            else:
                val = probed
            self._rendered_duration_cache = (os.path.normpath(path), val)
            return val

        if mpv_dur is not None:
            self._rendered_duration_cache = (os.path.normpath(path), mpv_dur)
            return mpv_dur

        # 3) Companion duration_sec only as last resort (may be a trim/source guess).
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
        # Target File Size may have been picked before duration arrived — finish the plan.
        try:
            q = ""
            if hasattr(self, "ui") and hasattr(self.ui, "combo_quality"):
                q = self.ui.combo_quality.currentText() or ""
            if "Target File Size" in q and hasattr(self, "setup_dynamic_slider"):
                self.setup_dynamic_slider()
        except Exception:
            pass
        # Steam clip: MPV/XML may report length after the open stack deferred thumbs.
        if not getattr(self, "_rendered_media_path", None):
            clip = getattr(self, "_preview_clip_path", None)
            if clip and hasattr(self, "_maybe_start_thumbs_after_quality"):
                self._maybe_start_thumbs_after_quality(clip)

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
            self._clear_preview_switch_gates()
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
            self._clear_preview_switch_gates()

    def _reap_timeline_thumb_thread(self, thread) -> None:
        """Drop a finished batch thread from the keep-alive list (safe to GC)."""
        dying = getattr(self, "_dying_thumb_threads", None)
        if not dying:
            return
        try:
            dying.remove(thread)
        except ValueError:
            pass

    def _stop_timeline_thumb_batch(self) -> None:
        thread = getattr(self, "thumb_thread", None)
        if not thread:
            return
        try:
            thread.finished_generation.disconnect(self._on_timeline_thumb_batch_done)
        except (TypeError, RuntimeError):
            pass
        thread.stop()
        # Non-blocking cancel must NOT drop the only Python ref while QThread is
        # still running — Qt aborts in Qt6Core (0xc0000409 / BEX64) on destroy.
        # Keep a strong ref until finished; see ThumbnailBatchThread.stop().
        dying = getattr(self, "_dying_thumb_threads", None)
        if dying is None:
            dying = []
            self._dying_thumb_threads = dying
        if thread not in dying:
            dying.append(thread)
            try:
                thread.finished.connect(
                    lambda t=thread: self._reap_timeline_thumb_thread(t)
                )
            except (TypeError, RuntimeError):
                pass
        if not thread.isRunning():
            self._reap_timeline_thumb_thread(thread)
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
        sniper_src = ""
        if hasattr(self, "custom_timeline"):
            current = getattr(self.custom_timeline, "current_video_path", "") or ""
            sniper_src = getattr(self.custom_timeline, "sniper_source_path", "") or current
        norm = PreviewSniperWorker._norm_media_path
        if norm(expected) not in (norm(current), norm(sniper_src)):
            logging.debug(
                "Ignored thumb batch for wrong clip (got %s, playing %s)",
                expected, current,
            )
            return
        if hasattr(self, "custom_timeline"):
            self.custom_timeline.thumb_dir = thumb_dir
            expected_src = getattr(sender, "mpd_path", "") or ""
            if expected_src and hasattr(self.custom_timeline, "canvas"):
                self.custom_timeline.canvas._thumb_dir_media_path = (
                    PreviewSniperWorker._norm_media_path(expected_src)
                )
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
            if hasattr(self.custom_timeline, "canvas"):
                self.custom_timeline.canvas._thumb_dir_media_path = (
                    PreviewSniperWorker._norm_media_path(abs_path)
                )
        self.thumb_thread.finished_generation.connect(self._on_timeline_thumb_batch_done)
        self.thumb_thread.start()

    def _maybe_start_thumbs_after_quality(self, clip_path: str) -> None:
        """Kick timeline batch once Source Info has duration (open path defers it)."""
        if self._norm_clip_path_key(clip_path) != self._norm_clip_path_key(
            getattr(self, "_preview_clip_path", None)
        ):
            return
        if getattr(self, "_is_switching", False):
            return
        clip_dur = float(getattr(self, "current_clip_duration_sec", 0) or 0)
        if clip_dur < 1.0:
            return
        play_path = getattr(self, "_current_play_abs_path", None) or getattr(
            self, "_current_mpd_abs_path", None
        )
        abs_path = getattr(self, "_current_mpd_abs_path", None) or play_path
        if not play_path:
            return
        from steempeg.core.dash.mpd_playback import host_libmpv_needs_mpd_bridge

        thumb_src = play_path
        if (
            host_libmpv_needs_mpd_bridge()
            and abs_path
            and str(abs_path).lower().endswith(".mpd")
        ):
            thumb_src = abs_path
        self._start_timeline_thumb_batch(thumb_src, clip_dur)

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

        # Same export already open — keep position (tab restore / re-select).
        # Mirrors Clips Manager skip-reopen of the current clip.
        if (
            not getattr(self, "_is_switching", False)
            and not getattr(self, "_awaiting_first_frame", False)
            and self._norm_clip_path_key(file_path)
            == self._norm_clip_path_key(getattr(self, "_active_play_media_path", None))
        ):
            logging.debug(
                "Rendered play skipped (already open): %s", file_path
            )
            self._preview_clip_path = file_path
            self._rendered_media_path = file_path
            return

        if hasattr(self, "get_rendered_health_report"):
            report = self.get_rendered_health_report(file_path)
            if report.level == health.ClipHealth.DEAD:
                logging.warning(
                    "Blocked dead rendered file playback: %s — %s",
                    file_path,
                    report.issues,
                )
                self._preview_clip_path = file_path
                self._rendered_media_path = file_path
                self._active_play_media_path = None
                # Stuck open-gates must not swallow Close on the next click.
                self._is_switching = False
                self._awaiting_first_frame = False
                self._clear_player_surface()
                if hasattr(self, "_reset_player_placeholder_default"):
                    self._reset_player_placeholder_default()
                # Keep header close (X) — poster is idle but this export is still selected.
                if hasattr(self, "set_player_header_clip_controls_visible"):
                    self.set_player_header_clip_controls_visible(True)
                if hasattr(self, "update_clip_health_button"):
                    self.update_clip_health_button()
                detail = (
                    "; ".join(report.issues[:3])
                    if report.issues
                    else "File cannot be opened."
                )
                steempeg_warning(
                    self.ui,
                    "Unplayable export",
                    "This rendered file is damaged or incomplete and cannot be played.",
                    detail=f"{detail}\n\nRe-render from the source clip, or delete this file.",
                )
                return

        from steempeg.ui.library.rendered_library import RENDERED_AUDIO_EXTS, RENDERED_VIDEO_EXTS
        from steempeg.core.rendered_media import load_markers_sidecar, markers_to_canvas

        switch_gen = self._begin_preview_switch()
        self._preview_switch_gen = switch_gen
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
        self._restart_from_eof = False

        if hasattr(self, "custom_timeline"):
            canvas = self.custom_timeline.canvas
            canvas.rendered_media_path = file_path
            if hasattr(self, "cache_dir"):
                canvas._markers_cache_dir = self.cache_dir
                sidecar_entries = load_markers_sidecar(self.cache_dir, file_path)
                canvas.markers.extend(markers_to_canvas(sidecar_entries))
            if hasattr(canvas, "notify_markers_changed"):
                canvas.notify_markers_changed(reveal=True)
            else:
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
            # Drop any DASH sniper override from a prior Steam clip preview.
            self.custom_timeline.sniper_source_path = ""
            self.custom_timeline.current_video_path = abs_path
            self.custom_timeline.thumb_dir = None
            self.custom_timeline.set_duration(0)

        logging.info("MPV play file: %s", abs_path)
        self._playback_last_time_pos = None
        self._playback_stall_since = None
        self._ignore_playback_stall(0.35)

        # Pre-seed timeline from probed file length — never trim/source sidecar guesses.
        seed_dur = probe_media_duration_sec(file_path)
        if is_sane_media_duration(seed_dur):
            self._apply_playback_duration(float(seed_dur))
            self._rendered_duration_cache = (os.path.normpath(file_path), float(seed_dur))

        try:
            self._ensure_linux_mpv_vo()
            self.player.play(abs_path)
            self.player.pause = False
        except Exception as exc:
            logging.error("MPV play file failed for %s: %s", abs_path, exc)
            self._clear_preview_switch_gates()
            return

        try:
            from steempeg.ui.player import preview_quality as pq

            pq.reset_source_height_cache()
        except Exception:
            pass
        QTimer.singleShot(80, self._apply_saved_preview_quality_to_player)

        if hasattr(self, "custom_timeline") and hasattr(self.custom_timeline, "canvas"):
            self.custom_timeline.canvas.playback_speed = float(getattr(self.player, "speed", 1.0) or 1.0)

        self._first_frame_deadline = time.time() + 0.6
        QTimer.singleShot(30, self._reveal_video_when_ready)
        # Soft finish + hard watchdog — rendered path previously lacked both, so a
        # stale _preview_switch_gen from a prior Steam open could leave awaiting stuck.
        QTimer.singleShot(800, lambda g=switch_gen: self._finish_preview_switch(g))
        self._arm_preview_switch_watchdog(switch_gen)

        if hasattr(self, "thumb_thread") and self.thumb_thread and self.thumb_thread.isRunning():
            self._stop_timeline_thumb_batch()

        QTimer.singleShot(80, lambda: self._poll_rendered_media_duration(file_path, switch_gen))

        if hasattr(self.ui, "btn_play"):
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_pause.png")))

        if hasattr(self, "update_clip_health_button"):
            self.update_clip_health_button()

    def _norm_clip_path_key(self, path: str | None) -> str:
        if not path:
            return ""
        try:
            return os.path.normcase(os.path.abspath(str(path)))
        except Exception:
            return str(path)

    def _is_clip_actively_previewing(self, clip_path: str) -> bool:
        """True when this Steam clip folder is already loaded and seekable."""
        if not clip_path:
            return False
        if getattr(self, "_rendered_media_path", None):
            return False
        if getattr(self, "_is_switching", False) or getattr(
            self, "_awaiting_first_frame", False
        ):
            return False
        want = self._norm_clip_path_key(clip_path)
        have = self._norm_clip_path_key(getattr(self, "_preview_clip_path", None))
        if not want or want != have:
            return False
        play = getattr(self, "_active_play_media_path", None)
        if not play:
            return False
        play_n = self._norm_clip_path_key(play)
        sep = os.sep
        if not (
            play_n == want
            or play_n.startswith(want + sep)
            or play_n.startswith(want + "/")
        ):
            return False
        return bool(self._mpv_has_media())

    def _stash_pending_open_seek(self, clip_path: str, seek_sec: float | None) -> None:
        """Queue a related-clip seek for after the next preview first-frame."""
        if seek_sec is None or float(seek_sec) <= 0:
            self._pending_open_seek = None
            self._open_seek_timer_armed = False
            return
        key = self._norm_clip_path_key(clip_path)
        gen = int(getattr(self, "_open_seek_gen", 0)) + 1
        self._open_seek_gen = gen
        self._pending_open_seek = (key, float(seek_sec), gen)
        self._open_seek_timer_armed = False

    def _seek_active_clip_to_sec(self, seek_sec: float) -> bool:
        """Seek the already-loaded preview without remounting MPV (second Open related)."""
        if seek_sec is None or float(seek_sec) <= 0:
            return False
        if not self._mpv_has_media():
            return False
        if getattr(self, "_is_switching", False) or getattr(
            self, "_awaiting_first_frame", False
        ):
            return False
        dur = self._playback_duration_sec()
        target = float(seek_sec)
        if dur is not None and dur > 0:
            if target > float(dur) + 2.0:
                as_sec = target / 1000.0
                if 0.0 <= as_sec <= float(dur) + 1.0:
                    target = as_sec
                else:
                    logging.warning(
                        "Active-clip seek %.2fs past duration %.2fs — skipped",
                        target,
                        dur,
                    )
                    return False
            target = min(target, max(0.0, float(dur) - 0.05))
        if target <= 0:
            return False
        if hasattr(self, "custom_timeline") and dur and dur > 0:
            try:
                self.custom_timeline.set_duration(int(float(dur) * 1000))
            except Exception:
                pass
        self._ignore_playback_stall(1.0)
        timeline = getattr(self, "custom_timeline", None)
        if timeline is not None and hasattr(timeline, "force_jump"):
            timeline.force_jump(int(target * 1000))
            logging.info("Related-clip seek (active) to %.2fs", target)
            return True
        ok = self._safe_mpv_seek(target)
        if ok:
            logging.info("Related-clip seek (active) to %.2fs", target)
        return ok

    def clear_clip_open_loading(self) -> None:
        """Hide open-spinner on library cards and queue rows."""
        self._opening_clip_path = None
        self._clip_open_play_t0 = None
        self._clip_open_load_pct = -1
        self._hide_clip_open_loading_hosts()

    def _hide_clip_open_loading_hosts(self) -> None:
        """Drop card/queue spinners without clearing the in-flight open path."""
        hosts = getattr(self, "_clip_open_loading_hosts", None)
        self._clip_open_loading_hosts = None
        if hosts:
            for host in hosts:
                try:
                    if hasattr(host, "set_loading"):
                        host.set_loading(False)
                except RuntimeError:
                    pass
            return
        grid = getattr(self, "grid_clips", None)
        if grid is not None:
            try:
                for i in range(grid.count()):
                    item = grid.item(i)
                    if item is None:
                        continue
                    card = grid.itemWidget(item)
                    if card is not None and hasattr(card, "set_loading"):
                        card.set_loading(False)
            except RuntimeError:
                pass
        panel = getattr(self, "render_queue_panel", None)
        if panel is not None:
            for card in getattr(panel, "_card_widgets", None) or ():
                if hasattr(card, "set_loading"):
                    try:
                        card.set_loading(False)
                    except RuntimeError:
                        pass
        sidebar = getattr(self, "_portable_queue_sidebar", None)
        if sidebar is not None:
            for row in getattr(sidebar, "_rows", {}).values():
                if hasattr(row, "set_loading"):
                    try:
                        row.set_loading(False)
                    except RuntimeError:
                        pass

    def _job_id_for_clip_open_loading(
        self, clip_path: str | None, job_id: str | None = None
    ) -> str | None:
        """Queue job id for open-spinner hosts — never reuse a stale selection.

        Explicit ``job_id=""`` / ``None`` with a non-queued path must not fall
        back to ``_selected_queue_job_id`` from a previous queue card.
        """
        if job_id is not None:
            jid = str(job_id).strip()
            if not jid:
                return None
            if clip_path and hasattr(self, "render_queue"):
                job = self.render_queue.get(jid)
                if job is None:
                    return None
                if os.path.normpath(job.clip_path or "") != os.path.normpath(
                    str(clip_path)
                ):
                    return None
            return jid
        if not clip_path:
            return None
        if hasattr(self, "_resolve_queue_job_for_library_clip"):
            job = self._resolve_queue_job_for_library_clip(clip_path)
            return str(job.id) if job is not None else None
        return None

    def _attach_library_open_loading_host(
        self, clip_path: str | None, *, percent: int | None, hosts: list
    ) -> None:
        """Ensure the Clips Manager ClipCard for ``clip_path`` is a loading host."""
        key = self._norm_clip_path_key(clip_path)
        if not key:
            return
        # Already bound and spinning.
        for host in hosts:
            if getattr(host, "_job_id", None):
                continue
            try:
                if hasattr(host, "is_loading") and host.is_loading():
                    return
            except RuntimeError:
                continue
        grid = getattr(self, "grid_clips", None)
        if grid is None:
            return
        pct = 0 if percent is None else percent
        # Prefer current progress if the open is mid-flight.
        last = int(getattr(self, "_clip_open_load_pct", -1) or -1)
        if last >= 0:
            pct = last
        try:
            for i in range(grid.count()):
                item = grid.item(i)
                if item is None:
                    continue
                path = item.data(Qt.UserRole + 1)
                if self._norm_clip_path_key(path) != key:
                    continue
                card = grid.itemWidget(item)
                if card is not None and hasattr(card, "set_loading"):
                    card.set_loading(True, percent=pct)
                    if card not in hosts:
                        hosts.insert(0, card)
                break
        except RuntimeError:
            pass

    def _attach_queue_open_loading_hosts(
        self, jid: str, *, percent: int | None, hosts: list
    ) -> None:
        """Append Render Queue / Portable sidebar hosts for ``jid`` into ``hosts``."""
        pct = 0 if percent is None else percent
        last = int(getattr(self, "_clip_open_load_pct", -1) or -1)
        if last >= 0:
            pct = last
        panel = getattr(self, "render_queue_panel", None)
        if panel is not None:
            for card in getattr(panel, "_card_widgets", None) or ():
                if getattr(card, "_job_id", None) == jid and hasattr(card, "set_loading"):
                    try:
                        card.set_loading(True, percent=pct)
                        hosts.append(card)
                    except RuntimeError:
                        pass
        sidebar = getattr(self, "_portable_queue_sidebar", None)
        if sidebar is not None:
            row = getattr(sidebar, "_rows", {}).get(jid)
            if row is not None and hasattr(row, "set_loading"):
                try:
                    row.set_loading(True, percent=pct)
                    hosts.append(row)
                except RuntimeError:
                    pass

    def _reconcile_clip_open_loading_hosts(
        self,
        *,
        job_id: str | None,
        percent: int | None = None,
        clip_path: str | None = None,
    ) -> None:
        """Re-bind library + queue hosts after highlight / panel rebuild."""
        jid = str(job_id).strip() if job_id else ""
        hosts = list(getattr(self, "_clip_open_loading_hosts", None) or [])
        kept: list = []
        for host in hosts:
            hid = getattr(host, "_job_id", None)
            if hid:
                if not jid or str(hid) != jid:
                    try:
                        if hasattr(host, "set_loading"):
                            host.set_loading(False)
                    except RuntimeError:
                        pass
                    continue
            kept.append(host)
        path = clip_path or getattr(self, "_opening_clip_path", None)
        self._attach_library_open_loading_host(path, percent=percent, hosts=kept)
        if jid and not any(getattr(h, "_job_id", None) == jid for h in kept):
            self._attach_queue_open_loading_hosts(jid, percent=percent, hosts=kept)
        self._clip_open_loading_hosts = kept or None

    def set_clip_open_loading(
        self,
        clip_path: str | None = None,
        *,
        job_id: str | None = None,
        percent: int | None = None,
    ) -> None:
        """Show spinner on the clip/queue banner that is opening into the player."""
        key = self._norm_clip_path_key(clip_path)
        jid = self._job_id_for_clip_open_loading(clip_path, job_id)
        # Same clip already spinning (deferred preview painted early) — keep it,
        # but still re-bind library + queue hosts (highlight / rebuild can drop them).
        if (
            key
            and key == self._norm_clip_path_key(getattr(self, "_opening_clip_path", None))
        ):
            if percent is not None and hasattr(self, "update_clip_open_loading_progress"):
                self.update_clip_open_loading_progress(percent)
            self._reconcile_clip_open_loading_hosts(
                job_id=jid, percent=percent, clip_path=clip_path
            )
            return

        self.clear_clip_open_loading()
        # clear_clip_open_loading nulls this — restore so in-flight open is trackable.
        if clip_path:
            self._opening_clip_path = clip_path
        hosts: list = []
        if key:
            self._attach_library_open_loading_host(
                clip_path, percent=percent, hosts=hosts
            )

        if jid:
            self._attach_queue_open_loading_hosts(jid, percent=percent, hosts=hosts)
        self._clip_open_loading_hosts = hosts or None

    def update_clip_open_loading_progress(self, percent: int | None) -> None:
        """Update % on whichever card is currently showing the open spinner."""
        if percent is None:
            return
        pct = max(0, min(100, int(percent)))
        last = int(getattr(self, "_clip_open_load_pct", -1) or -1)
        if pct < last:
            return
        self._clip_open_load_pct = pct
        hosts = getattr(self, "_clip_open_loading_hosts", None)
        if hosts:
            alive = []
            for host in hosts:
                try:
                    if hasattr(host, "is_loading") and not host.is_loading():
                        continue
                    if hasattr(host, "set_loading_progress"):
                        host.set_loading_progress(pct)
                    alive.append(host)
                except RuntimeError:
                    continue
            self._clip_open_loading_hosts = alive or None
            return
        # Fallback: full scan (hosts unset / rebuilt mid-open).
        grid = getattr(self, "grid_clips", None)
        if grid is not None:
            try:
                for i in range(grid.count()):
                    item = grid.item(i)
                    if item is None:
                        continue
                    card = grid.itemWidget(item)
                    if card is not None and getattr(card, "is_loading", lambda: False)():
                        if hasattr(card, "set_loading_progress"):
                            card.set_loading_progress(pct)
            except RuntimeError:
                pass
        panel = getattr(self, "render_queue_panel", None)
        if panel is not None:
            for card in getattr(panel, "_card_widgets", None) or ():
                if getattr(card, "is_loading", lambda: False)():
                    if hasattr(card, "set_loading_progress"):
                        try:
                            card.set_loading_progress(pct)
                        except RuntimeError:
                            pass
        sidebar = getattr(self, "_portable_queue_sidebar", None)
        if sidebar is not None:
            for row in getattr(sidebar, "_rows", {}).values():
                if getattr(row, "is_loading", lambda: False)():
                    if hasattr(row, "set_loading_progress"):
                        try:
                            row.set_loading_progress(pct)
                        except RuntimeError:
                            pass

    def _clip_open_mpv_buffer_percent(self) -> int | None:
        """mpv cache fill 0–99 while the first frame is still pending; ignore stuck 100%."""
        player = getattr(self, "player", None)
        if player is None:
            return None
        try:
            buf = getattr(player, "cache_buffering_state", None)
            if buf is None:
                return None
            buf = int(buf)
        except Exception:
            return None
        if 0 <= buf < 100:
            return buf
        return None

    def _nudge_clip_open_loading(self, percent: int) -> None:
        if hasattr(self, "update_clip_open_loading_progress"):
            self.update_clip_open_loading_progress(percent)

    def generate_and_play_preview(
        self, clip_path=None, trim_restore=None, force=False, mpd_override=None,
        remount=False,
    ):
        """ Instantly loads and plays the Steam .mpd playlist using MPV. No proxy needed!

        force=True bypasses the dead-clip guard for a best-effort "salvage" preview
        (may show corrupted video, audio only, or nothing — entirely on the user).
        remount=True restarts MPV even if the same folder is already opening.
        mpd_override plays a specific manifest directly (used for salvage manifests
        that the health/discovery scanners intentionally ignore)."""
        self._rendered_media_path = None
        if clip_path is None:
            if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
                return
            clip_path = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).data(Qt.UserRole)

        if not clip_path or not os.path.isdir(clip_path):
            return

        if hasattr(self, "_is_valid_clip_path") and not self._is_valid_clip_path(clip_path):
            logging.warning("Ignored invalid clip preview path: %s", clip_path)
            return

        # Drop a stale related-clip seek if this open is for a different folder.
        pending_seek = getattr(self, "_pending_open_seek", None)
        if pending_seek:
            want_key = self._norm_clip_path_key(clip_path)
            try:
                if pending_seek[0] != want_key:
                    self._pending_open_seek = None
                    self._open_seek_timer_armed = False
            except (TypeError, IndexError):
                self._pending_open_seek = None
                self._open_seek_timer_armed = False

        # Spam-click while this same open is already in flight — don't restart MPV/remux.
        # Pending related-clip seek (if any) is kept and applied when finish fires.
        want = self._norm_clip_path_key(clip_path)
        opening = self._norm_clip_path_key(getattr(self, "_opening_clip_path", None))
        if (
            want
            and want == opening
            and not mpd_override
            and not force
            and not remount
            and (
                getattr(self, "_is_switching", False)
                or getattr(self, "_awaiting_first_frame", False)
            )
        ):
            logging.info(
                "Preview skipped (open already in flight): %s "
                "(switching=%s awaiting=%s)",
                clip_path,
                bool(getattr(self, "_is_switching", False)),
                bool(getattr(self, "_awaiting_first_frame", False)),
            )
            return

        self._opening_clip_path = clip_path
        self._preview_clip_path = clip_path
        # Raw clip is active now — re-show dash/settings only when dock was hidden
        # (Screenshots / rendered-only). Skip geometry churn while already open.
        if hasattr(self, "_sync_library_mode_chrome"):
            if not getattr(self, "_render_dock_visible", False):
                self._sync_library_mode_chrome()
        self.set_clip_open_loading(clip_path, job_id=None)

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
                if hasattr(self, "clear_clip_open_loading"):
                    self.clear_clip_open_loading()
                self._is_switching = False
                self._awaiting_first_frame = False
                self._clear_player_surface()
                if hasattr(self, '_reset_player_placeholder_default'):
                    self._reset_player_placeholder_default()
                # Keep Close — user must be able to dismiss a Dead / blocked clip.
                if hasattr(self, "set_player_header_clip_controls_visible"):
                    self.set_player_header_clip_controls_visible(True)
                if hasattr(self.ui, 'btn_start'):
                    if hasattr(self, "_sync_start_render_enabled"):
                        self._sync_start_render_enabled()
                    else:
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

        # Clear previous clip chrome immediately (trim/markers/last frame).
        switch_gen = self._begin_preview_switch()
        self._preview_switch_gen = switch_gen
        self._is_switching = True
        self._force_pause = False

        # Blank page before open so the old picture cannot linger.
        self.ui.video_container.setStyleSheet("background-color: transparent;")
        self._awaiting_first_frame = True
        if hasattr(self, "video_stack") and hasattr(self, "video_blank_frame"):
            self.video_stack.setCurrentWidget(self.video_blank_frame)

        # 2. GET THE CLIP FOLDER PATH
        
        # STEP 1: FIND THE VIDEO FOLDER
        all_mpds = [mpd_override] if mpd_override else self.get_all_mpd_paths(clip_path)
        if not all_mpds:
            logging.warning("No MPD found for clip: %s", clip_path)
            self._clear_preview_switch_gates()
            self._pending_open_seek = None
            self._open_seek_timer_armed = False
            if hasattr(self, "clear_clip_open_loading"):
                self.clear_clip_open_loading()
            return

        mpd_path = all_mpds[0]
        abs_path = os.path.abspath(mpd_path).replace("\\", "/")

        # Linux: remux Steam .mpd when demux is missing (or quality gear needs encode).
        from steempeg.core.dash.mpd_playback import (
            existing_playback_cache_for_play,
            should_remux_mpd_for_playback,
        )

        pending_remux = False
        early_play_path = abs_path
        remux_qid, remux_h = self._remux_preview_quality_args()
        if should_remux_mpd_for_playback(remux_qid) and abs_path.lower().endswith(".mpd"):
            cached = existing_playback_cache_for_play(abs_path, quality_id=remux_qid)
            if cached:
                early_play_path = cached.replace("\\", "/")
                self._current_remux_quality_id = remux_qid
            else:
                pending_remux = True
                # Remux in background; play as soon as the file grows. Banner % tracks bytes.
                self._start_clip_remux_async(
                    switch_gen,
                    abs_path,
                    clip_path,
                    quality_id=remux_qid,
                    max_height=remux_h,
                )
        else:
            self._current_remux_quality_id = None
        if not pending_remux:
            self._nudge_clip_open_loading(48)

        # Cheap chrome before play — markers load in parallel; health badge after reveal.
        if hasattr(self, "set_player_header_clip_controls_visible"):
            self.set_player_header_clip_controls_visible(True)
        if hasattr(self, 'custom_timeline'):
            self.custom_timeline.setEnabled(True)

        # 3. Open media ASAP — timeline JSON discovery runs off-thread in parallel.
        logging.info("MPV play: %s (clip=%s)", mpd_path, clip_path)
        self._start_timeline_markers_load_early(switch_gen, clip_path, mpd_path)
        if pending_remux:
            self._defer_preview_post_open_work(switch_gen, clip_path, mpd_path)
            return

        play_path = early_play_path
        if play_path != abs_path:
            logging.info("MPV play via DASH remux cache: %s", play_path)
        self._start_clip_playback(switch_gen, abs_path, play_path, clip_path)
        # Health badge after first frame — markers already loading above.
        self._defer_preview_post_open_work(switch_gen, clip_path, mpd_path)

    def _defer_preview_post_open_work(
        self, switch_gen: int, clip_path: str, mpd_path: str
    ) -> None:
        """Queue health badge / quality work until the open surface is revealed."""
        self._preview_post_open_gen = getattr(self, "_preview_post_open_gen", 0) + 1
        self._pending_preview_post_open = (
            self._preview_post_open_gen,
            switch_gen,
            clip_path,
            mpd_path,
        )
        # Remux path may already have revealed; flush on next tick if idle.
        if not getattr(self, "_awaiting_first_frame", False) and not getattr(
            self, "_is_switching", False
        ):
            QTimer.singleShot(0, lambda g=switch_gen: self._flush_deferred_clip_open_work(g))

    def _stop_timeline_markers_worker(self, *, invalidate: bool = True) -> None:
        """Cancel an in-flight timeline JSON discovery for a superseded clip open."""
        if invalidate:
            self._timeline_markers_load_gen = getattr(self, "_timeline_markers_load_gen", 0) + 1
        worker = getattr(self, "_timeline_markers_worker", None)
        if worker is None:
            return
        try:
            worker.requestInterruption()
        except Exception:
            pass
        if worker.isRunning():
            try:
                worker.wait(50)
            except Exception:
                pass
        self._timeline_markers_worker = None

    def _start_timeline_markers_load_early(
        self, switch_gen: int, clip_path: str, mpd_path: str
    ) -> None:
        """Discover timeline JSON in parallel with MPV open — apply as soon as ready."""
        self._stop_timeline_markers_worker(invalidate=True)
        load_gen = getattr(self, "_timeline_markers_load_gen", 0)

        from steempeg.ui.player.timeline_markers_worker import TimelineMarkersLoadWorker

        worker = TimelineMarkersLoadWorker(
            clip_path,
            mpd_path,
            getattr(self, "cache_dir", None),
        )
        self._timeline_markers_worker = worker

        def _on_done(result: object, lg=load_gen, sg=switch_gen) -> None:
            if lg != getattr(self, "_timeline_markers_load_gen", 0):
                return
            if sg != getattr(self, "_media_switch_gen", 0):
                return
            self._apply_timeline_markers_load_result(result, switch_gen=sg)

        def _release(w=worker) -> None:
            if getattr(self, "_timeline_markers_worker", None) is w:
                self._timeline_markers_worker = None

        worker.finished_load.connect(_on_done)
        worker.finished.connect(_release)
        worker.start()

    def _apply_timeline_markers_load_result(
        self, result: object, *, switch_gen: int
    ) -> None:
        if not isinstance(result, dict):
            return
        if switch_gen != getattr(self, "_media_switch_gen", 0):
            return
        clip_path = result.get("clip_path")
        if self._norm_clip_path_key(clip_path) != self._norm_clip_path_key(
            getattr(self, "_preview_clip_path", None)
        ):
            return
        if not hasattr(self, "custom_timeline"):
            return

        canvas = self.custom_timeline.canvas
        canvas.rendered_media_path = None
        cache_dir = getattr(self, "cache_dir", None)
        json_path = result.get("json_path")
        offset_ms = int(result.get("offset_ms") or 0)

        if json_path:
            logging.debug("Timeline JSON: %s", json_path)
            logging.debug("Timeline offset: %d ms", offset_ms)
            use_cache = bool(result.get("use_cache"))
            canvas.load_timeline_json(
                json_path,
                offset_ms,
                clip_path=clip_path,
                cache_dir=cache_dir if use_cache else None,
                merge_marker_cache=use_cache,
            )
            app_id = canvas.current_app_id
            if app_id:
                canvas.marker_store.prefetch(
                    app_id,
                    on_ready=canvas.update,
                )
        else:
            logging.debug("No timeline JSON for clip: %s", clip_path)
            canvas.load_steempeg_markers_only(
                clip_path=clip_path,
                cache_dir=cache_dir,
            )

    def _flush_deferred_clip_open_work(self, switch_gen: int | None = None) -> None:
        """Run health badge / quality populate after first paint (keeps open responsive)."""
        if switch_gen is not None and switch_gen != getattr(self, "_media_switch_gen", 0):
            return
        pending_post = getattr(self, "_pending_preview_post_open", None)
        if pending_post:
            self._pending_preview_post_open = None
            post_gen, sg, clip_path, mpd_path = pending_post
            QTimer.singleShot(
                0,
                lambda g=post_gen, s=sg, p=clip_path, m=mpd_path: self._run_preview_post_open_work(
                    g, s, p, m
                ),
            )
        pending_quality = getattr(self, "_pending_quality_populate", None)
        if pending_quality and hasattr(self, "_run_quality_populate_after_open"):
            self._pending_quality_populate = None
            q_gen, clip_path, session = pending_quality
            QTimer.singleShot(
                0,
                lambda g=q_gen, p=clip_path, s=session: self._run_quality_populate_after_open(
                    g, p, s
                ),
            )
        pending_thumbs = getattr(self, "_pending_timeline_thumbs", None)
        if pending_thumbs:
            self._pending_timeline_thumbs = None
            sg, thumb_src, clip_dur = pending_thumbs
            if sg == getattr(self, "_media_switch_gen", 0):
                QTimer.singleShot(
                    0,
                    lambda src=thumb_src, dur=clip_dur: self._start_timeline_thumb_batch(
                        src, dur
                    ),
                )

    def _schedule_preview_post_open_work(
        self, switch_gen: int, clip_path: str, mpd_path: str
    ) -> None:
        """Compat: queue post-open work (same as defer)."""
        self._defer_preview_post_open_work(switch_gen, clip_path, mpd_path)

    def _run_preview_post_open_work(
        self, post_gen: int, switch_gen: int, clip_path: str, mpd_path: str
    ) -> None:
        if post_gen != getattr(self, "_preview_post_open_gen", 0):
            return
        if switch_gen != getattr(self, "_media_switch_gen", 0):
            return
        if self._norm_clip_path_key(clip_path) != self._norm_clip_path_key(
            getattr(self, "_preview_clip_path", None)
        ):
            return

        if hasattr(self, "update_playback_badge"):
            self.update_playback_badge()
        if hasattr(self, "update_clip_health_button"):
            self.update_clip_health_button()

    def _remux_preview_quality_args(self) -> tuple[str, int | None]:
        """Current player-gear quality for Linux remux cache keying."""
        from steempeg.core.dash.mpd_playback import (
            max_height_for_quality,
            normalize_remux_quality_id,
        )
        from steempeg.ui.player import preview_quality as pq

        raw = getattr(self, "_preview_quality_id", None)
        if not raw:
            try:
                raw = self.load_user_settings().get(pq.SETTINGS_KEY, pq.DEFAULT_QUALITY)
            except Exception:
                raw = pq.DEFAULT_QUALITY
        qid = normalize_remux_quality_id(pq.normalize_quality_id(raw))
        return qid, max_height_for_quality(qid)

    def _prefetch_clip_playback_media(self, clip_path: str) -> None:
        """Warm Linux DASH remux cache early without starting playback."""
        if sys.platform == "win32" or not clip_path:
            return
        try:
            from steempeg.core.dash.mpd_playback import (
                estimate_remux_bytes,
                existing_playback_cache_for_play,
                remux_mpd_for_playback,
                should_remux_mpd_for_playback,
            )
        except Exception:
            return
        try:
            mpds = self.get_all_mpd_paths(clip_path)
        except Exception:
            return
        if not mpds:
            return
        abs_path = os.path.abspath(mpds[0]).replace("\\", "/")
        qid, max_h = self._remux_preview_quality_args()
        if not should_remux_mpd_for_playback(qid):
            return
        if existing_playback_cache_for_play(abs_path, quality_id=qid):
            return
        try:
            from steempeg.infra.disk_space import should_skip_linux_remux_prefetch

            if should_skip_linux_remux_prefetch(
                estimate_remux_bytes(abs_path, quality_id=qid, max_height=max_h)
            ):
                logging.info("Prefetch remux skipped: low disk space (%s)", abs_path)
                return
        except Exception:
            pass
        inflight = getattr(self, "_prefetch_remux_paths", None)
        if inflight is None:
            inflight = set()
            self._prefetch_remux_paths = inflight
        inflight_key = f"{abs_path}|{qid}"
        if inflight_key in inflight:
            return
        inflight.add(inflight_key)

        import threading

        def _worker():
            try:
                remux_mpd_for_playback(abs_path, quality_id=qid, max_height=max_h)
            except Exception as exc:
                logging.debug("Prefetch remux failed for %s: %s", abs_path, exc)
            finally:
                inflight.discard(inflight_key)

        threading.Thread(target=_worker, name="steempeg-mpd-prefetch", daemon=True).start()

    def _start_clip_remux_async(
        self,
        switch_gen: int,
        abs_path: str,
        clip_path: str,
        *,
        quality_id: str | None = None,
        max_height: int | None = None,
        seek_after: float | None = None,
    ) -> None:
        """Cold remux without a loader: play the growing file as soon as it has data."""
        import threading

        from steempeg.core.dash.mpd_playback import (
            RemuxJob,
            normalize_remux_quality_id,
            start_remux_job,
        )

        qid = normalize_remux_quality_id(
            quality_id if quality_id is not None else self._remux_preview_quality_args()[0]
        )
        if max_height is None and qid != "source":
            max_height = self._remux_preview_quality_args()[1]
        self._current_remux_quality_id = qid

        prev = getattr(self, "_progressive_remux", None)
        if prev is not None:
            old_gen, old_job = prev
            # Abort superseded clip opens *or* an in-flight remux for a different quality.
            should_abort = False
            if old_gen != switch_gen and isinstance(old_job, RemuxJob):
                should_abort = True
            elif isinstance(old_job, RemuxJob) and getattr(old_job, "quality_id", "source") != qid:
                should_abort = True
            if should_abort and isinstance(old_job, RemuxJob):
                try:
                    old_job.abort()
                except Exception:
                    pass
            self._progressive_remux = None

        if sys.platform != "win32":
            try:
                from steempeg.core.dash.mpd_playback import remux_disk_plan
                from steempeg.ui.disk_space_warning import ensure_linux_disk_for_remux

                need, _free = remux_disk_plan(
                    abs_path, quality_id=qid, max_height=max_height
                )
                if not ensure_linux_disk_for_remux(self.ui, need_bytes=need):
                    self._clear_remux_quality_hold()
                    self._clear_preview_switch_gates()
                    if hasattr(self, "clear_clip_open_loading"):
                        self.clear_clip_open_loading()
                    return
            except Exception:
                logging.exception("Linux remux disk-space check failed")

        try:
            started = start_remux_job(abs_path, quality_id=qid, max_height=max_height)
        except Exception as exc:
            logging.error("DASH remux start failed for %s: %s", abs_path, exc)
            self._clear_remux_quality_hold()
            self._clear_preview_switch_gates()
            if hasattr(self, "clear_clip_open_loading"):
                self.clear_clip_open_loading()
            try:
                from steempeg.infra.disk_space import looks_like_disk_full_error
                from steempeg.ui.disk_space_warning import warn_linux_disk_remux_blocked

                if sys.platform != "win32" and looks_like_disk_full_error(exc):
                    warn_linux_disk_remux_blocked(self.ui, exc)
                else:
                    steempeg_warning(self.ui, "Clip prepare failed", str(exc)[:400])
            except Exception:
                pass
            return

        if isinstance(started, str):
            logging.info(
                "MPV play via DASH remux cache (%s): %s", qid, started
            )
            self._current_remux_quality_id = qid
            self._start_clip_playback(
                switch_gen,
                abs_path,
                started.replace("\\", "/"),
                clip_path,
                seek_after=seek_after,
            )
            return

        job: RemuxJob = started
        self._progressive_remux = (switch_gen, job)
        early_started = {"done": False}
        # Quality-gear restore into a growing libx264 .tmp.mkv is not seek-safe:
        # early-play at ~4 MiB (~6% of estimate) leaves mpv paused_for_cache /
        # eternal Buffering. Wait for finalize when a restore seek is needed.
        # Source -c copy (no height) may still early-play for cold opens.
        want_restore = seek_after is not None and float(seek_after) > 0.05
        is_encode = bool(getattr(job, "max_height", None))
        block_early_play = want_restore and is_encode

        def _on_ui(play_path: str = "", err_text: str = "", finished: bool = False) -> None:
            # Always drop a dead remux hold when this job ends, even if a newer
            # switch_gen won the race (otherwise Preparing sticks forever).
            if err_text and getattr(self, "_progressive_remux", None) == (switch_gen, job):
                self._progressive_remux = None
            if err_text:
                self._clear_remux_quality_hold()
                try:
                    if hasattr(self, "player") and self.player:
                        self.player.pause = False
                except Exception:
                    pass
            if switch_gen != getattr(self, "_media_switch_gen", 0):
                return
            if err_text:
                self._clear_preview_switch_gates()
                try:
                    from steempeg.infra.disk_space import looks_like_disk_full_error
                    from steempeg.ui.disk_space_warning import warn_linux_disk_remux_blocked

                    if sys.platform != "win32" and looks_like_disk_full_error(err_text):
                        warn_linux_disk_remux_blocked(self.ui, err_text)
                    else:
                        steempeg_warning(self.ui, "Clip prepare failed", err_text[:400])
                except Exception:
                    pass
                return
            if not play_path:
                return
            if finished:
                if getattr(self, "_progressive_remux", None) == (switch_gen, job):
                    self._progressive_remux = None
                if early_started["done"]:
                    self._current_play_abs_path = play_path
                    self._current_remux_quality_id = qid
                    if hasattr(self, "custom_timeline"):
                        self.custom_timeline.sniper_source_path = abs_path
                        self.custom_timeline.current_video_path = play_path
                    logging.info(
                        "DASH remux finished (already playing, %s): %s", qid, play_path
                    )
                    # Re-open finalized file so demuxer sees a complete mkv, then restore.
                    if want_restore:
                        self._start_clip_playback(
                            switch_gen,
                            abs_path,
                            play_path,
                            clip_path,
                            seek_after=seek_after,
                        )
                    elif getattr(self, "_remux_quality_hold_active", False):
                        self._clear_remux_quality_hold()
                        try:
                            self.player.pause = False
                        except Exception:
                            pass
                    else:
                        self._set_playback_loading(False)
                    return
                logging.info("MPV play via DASH remux cache (%s): %s", qid, play_path)
                self._current_remux_quality_id = qid
                self._start_clip_playback(
                    switch_gen,
                    abs_path,
                    play_path,
                    clip_path,
                    seek_after=seek_after,
                )
                return
            if early_started["done"]:
                return
            early_started["done"] = True
            logging.info("MPV play via growing remux (%s): %s", qid, play_path)
            self._current_remux_quality_id = qid
            self._start_clip_playback(
                switch_gen,
                abs_path,
                play_path,
                clip_path,
                seek_after=seek_after,
            )

        def _tick() -> None:
            if switch_gen != getattr(self, "_media_switch_gen", 0):
                try:
                    job.abort()
                except Exception:
                    pass
                return
            # Estimated remux progress for the clip banner + Preparing pill (%).
            # Keep Preparing for the whole encode (incl. after seek restore /
            # early-play) so stall detection cannot pin eternal Buffering.
            remux_still_running = job.poll() is None
            try:
                need = int(getattr(job, "need", 0) or 0)
                written = int(job.bytes_written() or 0)
                if need > 0:
                    pct = min(99, max(0, int(written * 100 / need)))
                    if hasattr(self, "update_clip_open_loading_progress"):
                        self.update_clip_open_loading_progress(pct)
                    show_prep = remux_still_running or getattr(
                        self, "_remux_quality_hold_active", False
                    )
                    if show_prep:
                        label = getattr(job, "quality_id", None) or qid
                        if label and label != "source":
                            msg = f"Preparing {label}… {pct}%"
                        else:
                            msg = f"Preparing… {pct}%"
                        self._remux_quality_hold_message = msg
                        self._set_playback_loading(True, msg)
            except Exception:
                pass
            if not early_started["done"] and not block_early_play:
                early = job.early_play_path()
                if early:
                    _on_ui(play_path=early.replace("\\", "/"))
            if remux_still_running:
                QTimer.singleShot(120, _tick)
                return

            def _finish_worker() -> None:
                play_path = ""
                err_text = ""
                try:
                    from steempeg.core.dash.mpd_playback import RemuxAborted

                    play_path = job.finalize().replace("\\", "/")
                except RemuxAborted:
                    return
                except Exception as abs_exc:
                    # Already playing the growing file — don't nuke UI / sniper path.
                    if early_started["done"]:
                        logging.debug(
                            "DASH remux finalize after early play: %s (%s)", abs_path, abs_exc
                        )
                        if switch_gen == getattr(self, "_media_switch_gen", 0):
                            QTimer.singleShot(0, lambda: self._set_playback_loading(False))
                        return
                    err_text = str(abs_exc)
                    logging.error("DASH playback remux failed for %s: %s", abs_path, abs_exc)
                if switch_gen != getattr(self, "_media_switch_gen", 0):
                    return
                QTimer.singleShot(
                    0,
                    lambda: _on_ui(play_path=play_path, err_text=err_text, finished=True),
                )

            threading.Thread(
                target=_finish_worker, name="steempeg-mpd-remux-fin", daemon=True
            ).start()

        QTimer.singleShot(80, _tick)

    def _start_clip_playback(
        self,
        switch_gen: int,
        abs_path: str,
        play_path: str,
        clip_path: str,
        *,
        seek_after: float | None = None,
    ) -> None:
        """Open *play_path* in mpv after switch/remux. No-op if a newer switch won."""
        if switch_gen != getattr(self, "_media_switch_gen", 0):
            return

        if hasattr(self, 'custom_timeline'):
            from steempeg.core.dash.mpd_playback import host_libmpv_needs_mpd_bridge

            sniper_src = play_path
            if host_libmpv_needs_mpd_bridge() and abs_path.lower().endswith(".mpd"):
                sniper_src = abs_path
            self.custom_timeline.sniper_source_path = sniper_src
            self.custom_timeline.current_video_path = play_path
            self.custom_timeline.thumb_dir = None

        # Remember the source so the EOF watchdog can reopen it if a rewind wedges
        # ffmpeg's DASH demuxer (see update_ui_from_vlc / _reopen_current_clip_paused).
        self._current_mpd_abs_path = abs_path
        self._current_play_abs_path = play_path
        self._eof_rewind_pending = 0
        self._restart_from_eof = False

        self._playback_last_time_pos = None
        self._playback_stall_since = None
        self._ignore_playback_stall(0.35)

        try:
            if not self._ensure_linux_mpv_vo():
                self._clear_preview_switch_gates()
                self._clear_remux_quality_hold()
                return
            self.player.play(play_path)
            # Quality-switch restore: stay paused at t=0 until seek lands (avoids
            # audible restart-from-start while Buffering is shown).
            want_seek = seek_after is not None and float(seek_after) > 0.05
            self.player.pause = bool(want_seek) or bool(
                getattr(self, "_remux_quality_hold_active", False)
            )
        except Exception as exc:
            logging.warning("MPV play failed (%s); recreating core once", exc)
            self._discard_dead_linux_mpv()
            try:
                if not self._ensure_linux_mpv_vo():
                    self._clear_preview_switch_gates()
                    self._clear_remux_quality_hold()
                    return
                self.player.play(play_path)
                want_seek = seek_after is not None and float(seek_after) > 0.05
                self.player.pause = bool(want_seek) or bool(
                    getattr(self, "_remux_quality_hold_active", False)
                )
            except Exception as exc2:
                logging.error("MPV play failed for %s: %s", play_path, exc2)
                self._discard_dead_linux_mpv()
                self._clear_preview_switch_gates()
                self._clear_remux_quality_hold()
                return

        if seek_after is not None and seek_after > 0.05:
            # Growing / just-opened remux often cannot seek yet — retry until PTS lands.
            self._schedule_remux_seek_restore(float(seek_after), switch_gen)
        elif getattr(self, "_remux_quality_hold_active", False):
            self._clear_remux_quality_hold()
            try:
                self.player.pause = False
            except Exception:
                pass

        self._clip_open_play_t0 = time.time()
        self._nudge_clip_open_loading(70)

        try:
            from steempeg.ui.player import preview_quality as pq

            pq.reset_source_height_cache()
        except Exception:
            pass
        QTimer.singleShot(80, self._apply_saved_preview_quality_to_player)

        # Keep the timeline interpolation in sync with mpv's current rate from the start
        # (the speed setting persists across clips), so the playhead doesn't jitter.
        if hasattr(self, 'custom_timeline') and hasattr(self.custom_timeline, 'canvas'):
            self.custom_timeline.canvas.playback_speed = float(getattr(self.player, 'speed', 1.0) or 1.0)

        # Reveal the live video only once the first frame is ready (see step 3).
        self._first_frame_deadline = time.time() + 0.6
        QTimer.singleShot(30, self._reveal_video_when_ready)

        # Timeline thumbs after first paint — never wait on ffmpeg batch stop here.
        clip_dur = float(getattr(self, 'current_clip_duration_sec', 0) or 0)
        if clip_dur < 1.0 and abs_path.lower().endswith(".mpd"):
            try:
                from steempeg.core.dash import mpd

                with open(abs_path, "r", encoding="utf-8") as mpd_file:
                    seeded = mpd.parse_duration_seconds(mpd_file.read())
                if is_sane_media_duration(seeded) and float(seeded) >= 1.0:
                    clip_dur = float(seeded)
                    self.current_clip_duration_sec = clip_dur
                    if hasattr(self, "custom_timeline"):
                        self.custom_timeline.set_duration(int(clip_dur * 1000))
            except OSError:
                pass
            except Exception as exc:
                logging.debug("MPD duration seed failed for %s: %s", abs_path, exc)
        if clip_dur >= 1.0:
            from steempeg.core.dash.mpd_playback import host_libmpv_needs_mpd_bridge

            thumb_src = play_path
            if host_libmpv_needs_mpd_bridge() and abs_path.lower().endswith(".mpd"):
                thumb_src = abs_path
            self._pending_timeline_thumbs = (switch_gen, thumb_src, clip_dur)
        elif hasattr(self, 'custom_timeline'):
            self.custom_timeline.thumb_dir = None
            self._set_timeline_batch_thumbs_busy(False)
            self._pending_timeline_thumbs = None
        
        # Soft finish clears switching; finish now also clears awaiting.
        QTimer.singleShot(800, lambda g=switch_gen: self._finish_preview_switch(g))
        # Hard watchdog — Linux remux-cache opens have left both gates stuck.
        self._arm_preview_switch_watchdog(switch_gen)

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
        if sys.platform != "win32" and not self._mpv_core_alive():
            self._discard_dead_linux_mpv()
            return
            
        # If the strip is off, prevent the timer from toggling it!
        if hasattr(self, 'custom_timeline') and not self.custom_timeline.isEnabled():
            return

        # After seek / clip switch: still drive the playhead, but skip EOF latch
        # so a stale eof_reached cannot pause / snap to end over the new seek.
        ignoring_stale = time.time() < getattr(self, '_ignore_vlc_until', 0)

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
                if getattr(self.player, 'eof_reached', False) and not ignoring_stale:
                    time_sec = duration_sec 
                else:
                    return
                    
            # Keep sub-ms for smooth extrapolation (int trunc made 16ms polls stair-step).
            current_ms = float(time_sec) * 1000.0
            current_ms = max(0.0, min(current_ms, float(duration_ms) if duration_ms > 0 else float(max_ms)))

            if hasattr(self, "_record_salvage_playback_evidence"):
                self._record_salvage_playback_evidence()

            canvas = getattr(getattr(self, 'custom_timeline', None), 'canvas', None)
            user_scrubbing = canvas is not None and canvas.drag_state == 'playhead'
            end_slop = 50
            if 0 < duration_ms < 5000:
                # Short clips: don't treat "near end" as EOF until MPV says so,
                # otherwise the playhead freezes short of the bar.
                end_slop = 15
            at_end = (
                getattr(self.player, 'eof_reached', False)
                or (duration_ms > 0 and current_ms >= duration_ms - end_slop)
            )

            if at_end and not ignoring_stale:
                # Snap to true end so the scrubber fills the purple bar (lost when
                # we switched from rewind-to-0 to pause-at-EOF in 39.3).
                current_ms = float(duration_ms) if duration_ms > 0 else current_ms
                restarting = bool(getattr(self, "_restart_from_eof", False))
                if restarting and duration_ms > 0 and current_ms < duration_ms - end_slop:
                    self._restart_from_eof = False
                    restarting = False
                if user_scrubbing:
                    pass
                elif restarting:
                    # User hit Play at EOF — seek is in flight; don't re-latch pause.
                    self._sync_play_button_icon(paused=False)
                else:
                    if not self.player.pause:
                        self.player.pause = True
                    self._sync_play_button_icon(paused=True)
                if (
                    not user_scrubbing
                    and hasattr(self, 'custom_timeline')
                    and duration_ms > 0
                ):
                    canvas = getattr(self.custom_timeline, 'canvas', None)
                    if canvas is not None:
                        canvas.visual_ms = float(duration_ms)
                        canvas.target_ms = float(duration_ms)
                        canvas.vlc_last_update_time = time.time()
            elif not ignoring_stale:
                self._eof_rewind_pending = 0
                self._restart_from_eof = False

            is_playing = not self.player.pause

            # Remux quality switch: keep stick + clock pinned until seek lands.
            # Buffering overlay: freeze wall-clock extrapolation (scroller must not
            # crawl while video is not actually advancing).
            hold_active = bool(getattr(self, "_remux_quality_hold_active", False))
            buffering_ui = bool(getattr(self, "_playback_loading_active", False))
            if hold_active:
                hold_sec = float(getattr(self, "_remux_quality_hold_seek", 0.0) or 0.0)
                current_ms = max(0.0, hold_sec * 1000.0)
                is_playing = False
            elif buffering_ui:
                canvas = getattr(getattr(self, "custom_timeline", None), "canvas", None)
                if canvas is not None:
                    current_ms = float(getattr(canvas, "visual_ms", current_ms) or current_ms)
                is_playing = False

            # Send the data to our smooth custom timeline (even during seek grace —
            # freezing here left the stick at 0 until grace ended, then teleported).
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
                    row = getattr(self, "_footer_controls_row", None)
                    if row is not None and hasattr(row, "refresh_center"):
                        row.refresh_center()
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
            'raw_time_ms': current_time + getattr(canvas, 'current_offset_ms', 0),
            'icon_key': 'usermarker',
            'is_round': False,
            'title': '',
            'desc': '',
            'steempeg_owned': True,
        }
        markers_list.append(internal_marker)
        markers_list.sort(key=lambda x: x.get('time_ms', 0))
        if hasattr(canvas, "notify_markers_changed"):
            canvas.notify_markers_changed()
        else:
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

        # 2. Persist: Steam timeline → app cache; missing Steam JSON → steempeg_timeline.json
        from steempeg.core.clip_markers_cache import (
            ensure_steempeg_timeline_json,
            is_steempeg_timeline_json,
            sync_user_markers_to_steempeg_timeline,
            upsert_user_marker,
        )

        clip_key = getattr(canvas, "current_clip_path", None) or getattr(
            self, "_preview_clip_path", None
        )
        if clip_key and not getattr(canvas, "current_clip_path", None):
            canvas.current_clip_path = clip_key

        json_path = getattr(canvas, "current_json_path", None)
        if clip_key and not is_steempeg_timeline_json(json_path):
            # No / non-steempeg timeline bound → create our file and use it.
            from steempeg.core.clip_markers_cache import is_steam_timeline_json

            if not is_steam_timeline_json(json_path):
                created = ensure_steempeg_timeline_json(
                    clip_key, cache_dir=getattr(self, "cache_dir", None)
                )
                if created:
                    json_path = created
                    canvas.current_json_path = created

        if is_steempeg_timeline_json(json_path):
            ok = sync_user_markers_to_steempeg_timeline(
                json_path,
                markers_list,
                offset_ms=int(getattr(canvas, "current_offset_ms", 0) or 0),
            )
            if not ok:
                logging.warning("Failed to persist user marker to %s", json_path)
            return

        if hasattr(self, "cache_dir") and self.cache_dir:
            canvas._markers_cache_dir = self.cache_dir
            ok = upsert_user_marker(
                self.cache_dir,
                internal_marker,
                clip_path=clip_key,
                json_path=json_path,
            )
            if not ok:
                logging.warning("Failed to persist user marker to Steempeg cache")
            elif not clip_key:
                logging.warning(
                    "User marker saved under unknown identity — no clip folder bound"
                )
        else:
            logging.warning("No cache_dir — user marker not persisted")
    def take_screenshot(self, target_ms=None):
        """ Takes a clean screenshot directly from MPV and saves it to the global folder. """
        if not hasattr(self, 'player') or not self.player: return
        
        # Ensure the global folder exists (just in case)
        try:
            from steempeg.ui.settings_prefs import resolve_screenshots_folder

            settings = {}
            if hasattr(self, "load_user_settings"):
                settings = self.load_user_settings() or {}
            self.screenshots_dir = resolve_screenshots_folder(settings)
        except Exception:
            if not hasattr(self, 'screenshots_dir') or not os.path.exists(self.screenshots_dir):
                self.screenshots_dir = os.path.join(get_save_directory(), "Screenshots")
                os.makedirs(self.screenshots_dir, exist_ok=True)
        if not os.path.isdir(self.screenshots_dir):
            os.makedirs(self.screenshots_dir, exist_ok=True)
            
        # Get the clip name (if selected) to add to the file name
        game_name = "Clip"
        clip_path = ""
        app_id = ""
        row = self.ui.table_clips.currentRow()
        if hasattr(self.ui, 'table_clips') and row >= 0:
            item = self.ui.table_clips.item(row, 0)
            if item:
                # Trim extra spaces from the ends of the name
                game_name = item.text().strip()
                # Replace characters forbidden in filenames with underscores.
                game_name = re.sub(r'[\\/*?:"<>|]', "_", game_name)
                clip_path = str(item.data(Qt.UserRole) or "").strip()
        if not clip_path:
            clip_path = str(getattr(self, "_preview_clip_path", None) or "").strip()
        if clip_path:
            from steempeg.core.rendered_media import parse_app_id_from_clip_folder

            app_id = parse_app_id_from_clip_folder(os.path.basename(clip_path)) or ""

        # Determine the time (if a marker was clicked, use its time; otherwise, use the player's time)
        pos_ms = float(target_ms) if target_ms is not None else (getattr(self.player, 'time_pos', 0) * 1000)

        from steempeg.core.screenshot_clip_link import (
            build_steempeg_screenshot_filename,
            save_screenshot_clip_meta,
        )

        filename = build_steempeg_screenshot_filename(
            game_name, pos_ms, clip_path=clip_path
        )
        filepath = os.path.join(self.screenshots_dir, filename).replace('\\', '/')

        need_seek = False
        original_pos = getattr(self.player, 'time_pos', 0) or 0
        original_pos_ms = float(original_pos) * 1000

        # If we right-click far away from the slider, we need to jump there for a split second
        if target_ms is not None and abs(target_ms - original_pos_ms) > 200:
            need_seek = self._safe_mpv_seek(pos_ms / 1000.0)
            if need_seek:
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
            self._safe_mpv_seek(original_pos_ms / 1000.0)

        if saved_ok:
            if clip_path:
                save_screenshot_clip_meta(
                    filepath,
                    clip_path=clip_path,
                    app_id=app_id,
                    pos_ms=pos_ms,
                    game_name=game_name,
                )
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
        from steempeg.ui import ui_theme as ut

        pick.setStyleSheet(ut.compact_menu_stylesheet())
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
        from steempeg.ui import ui_theme as ut

        pick.setStyleSheet(ut.compact_menu_stylesheet())
        for path in files:
            action = pick.addAction(os.path.basename(path))
            action.triggered.connect(
                lambda _checked=False, p=path: reveal_in_file_manager(p)
            )
        pick.exec(QCursor.pos())

    @staticmethod
    def _open_file_with_default_app(path: str) -> None:
        from steempeg.infra.paths import open_path_with_default_app

        if not path:
            return
        abs_path = os.path.abspath(path)
        try:
            # Linux: subprocess helpers with restored session env — not
            # QDesktopServices.openUrl(), which often returns True without opening
            # when DBus/XDG_RUNTIME_DIR are missing (Steam launch, Bazzite/KDE).
            open_path_with_default_app(abs_path)
        except OSError as exc:
            logging.error("Failed to open file %s: %s", abs_path, exc)

    def _hide_screenshot_toast(self) -> None:
        """Hide the screenshot toast and drop its click-away filter."""
        timer = getattr(self, "_screenshot_toast_timer", None)
        if timer is not None:
            timer.stop()
        toast = getattr(self, "_screenshot_toast", None)
        if toast is not None:
            try:
                toast.hide()
            except RuntimeError:
                pass
        self._uninstall_screenshot_toast_clickaway()

    def _install_screenshot_toast_clickaway(self) -> None:
        if getattr(self, "_screenshot_toast_clickaway_installed", False):
            return
        app = QApplication.instance()
        if app is None:
            return
        filt = getattr(self, "_screenshot_toast_clickaway", None)
        if filt is None:
            filt = _ScreenshotToastClickAwayFilter(self)
            self._screenshot_toast_clickaway = filt
        app.installEventFilter(filt)
        ui = getattr(self, "ui", None)
        if ui is not None:
            ui.installEventFilter(filt)
        self._screenshot_toast_clickaway_installed = True

    def _uninstall_screenshot_toast_clickaway(self) -> None:
        if not getattr(self, "_screenshot_toast_clickaway_installed", False):
            return
        filt = getattr(self, "_screenshot_toast_clickaway", None)
        app = QApplication.instance()
        if filt is not None:
            if app is not None:
                app.removeEventFilter(filt)
            ui = getattr(self, "ui", None)
            if ui is not None:
                try:
                    ui.removeEventFilter(filt)
                except RuntimeError:
                    pass
        self._screenshot_toast_clickaway_installed = False

    def _show_screenshot_toast(self, directory, *, screenshot_path=None):
        """Flash a small 'Screenshot saved in <dir>' toast with copy/open actions."""
        if self._main_shell_is_minimized():
            return
        directory = os.path.normpath(directory)

        toast = getattr(self, '_screenshot_toast', None)
        if toast is None:
            toast = QWidget(self.ui)
            toast.setObjectName("screenshotToastHost")
            # Tool (not ToolTip) without stays-on-top — stays under Clips Manager sheets.
            # Not Qt.Popup: we keep WA_ShowWithoutActivating so copy/open don't steal focus;
            # click-away is handled by _ScreenshotToastClickAwayFilter instead.
            toast.setWindowFlags(
                Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
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
                " font-family: " + tok.FONT_APP + "; }"
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
            self._screenshot_toast_timer.timeout.connect(self._hide_screenshot_toast)
            copy_btn.clicked.connect(self._copy_screenshot_dir)
            open_btn.clicked.connect(self._open_screenshot_dir)

        self._screenshot_toast_dir = directory
        self._screenshot_toast_file = screenshot_path if screenshot_path and os.path.isfile(screenshot_path) else None
        self._screenshot_toast_label.setText(f"📸 Screenshot saved in  {directory}")
        if hasattr(self, '_screenshot_toast_btn'):
            self._screenshot_toast_btn.setText("📋 Copy path")

        toast = self._screenshot_toast
        toast.adjustSize()
        if sys.platform == "win32":
            try:
                from steempeg.infra.window_focus import detach_tool_ownership

                detach_tool_ownership(toast)
            except Exception:
                pass

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
        # Do not raise_() — owned/transient Tools re-stack the Steempeg shell over
        # Explorer. Show without activating; ownership already detached above.
        toast.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if sys.platform == "win32":
            try:
                import ctypes

                toast.createWinId()
                hwnd = int(toast.winId())
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                    if not toast.isVisible():
                        toast.setVisible(True)
                else:
                    toast.show()
            except Exception:
                toast.show()
        else:
            toast.show()
        self._install_screenshot_toast_clickaway()
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
        if preset_id == pq.DEFAULT_QUALITY:
            pq.apply_mpv_preview_quality(player, preset_id)
            return
        if not player:
            return
        ok = pq.apply_mpv_preview_quality(player, preset_id)
        if ok:
            return
        # Height unknown / filter not ready yet — retry, do not wipe the setting.
        if retry < 25:
            QTimer.singleShot(100, lambda: self._apply_saved_preview_quality_to_player(retry + 1))

    def set_preview_quality(self, preset_id: str, *, persist: bool = True) -> None:
        from steempeg.ui.player import preview_quality as pq

        preset_id = pq.normalize_quality_id(preset_id)
        # Always re-apply from true decode height (cached), never from post-vf size.
        self._preview_quality_id = preset_id
        ok = pq.apply_mpv_preview_quality(getattr(self, "player", None), preset_id)
        if not ok and preset_id != pq.DEFAULT_QUALITY:
            # Defer once playback/dec-params settle — keep menu selection.
            QTimer.singleShot(120, lambda p=preset_id: self._retry_preview_quality(p))
        if persist:
            self.save_user_settings(pq.SETTINGS_KEY, preset_id)
        # Linux/Steam Deck remux path: gear must switch the quality-keyed mkv
        # (live MPV vf alone is a no-op on copy-remux under common hwdec/vo).
        self._maybe_rebind_linux_remux_preview_quality(preset_id)

    def _playing_linux_dash_remux(self) -> bool:
        """True when the open clip is a Linux remux of a Steam ``.mpd``."""
        from steempeg.core.dash.mpd_playback import host_libmpv_needs_mpd_bridge

        if not host_libmpv_needs_mpd_bridge():
            return False
        if hasattr(self, "_is_previewing_rendered_media") and self._is_previewing_rendered_media():
            return False
        mpd = getattr(self, "_current_mpd_abs_path", None) or ""
        return bool(mpd) and mpd.lower().endswith(".mpd")

    def _arm_remux_quality_hold(self, seek_sec: float, *, message: str | None = None) -> None:
        """Freeze timeline + Buffering overlay while a Linux remux quality switch runs."""
        seek_sec = max(0.0, float(seek_sec or 0.0))
        self._remux_quality_hold_active = True
        self._remux_quality_hold_seek = seek_sec
        self._remux_quality_hold_message = message or "Preparing…"
        self._remux_quality_hold_token = int(getattr(self, "_remux_quality_hold_token", 0) or 0) + 1
        hold_token = self._remux_quality_hold_token
        # Pin stick without emitting seek_requested (would yank the still-open file).
        timeline = getattr(self, "custom_timeline", None)
        canvas = getattr(timeline, "canvas", None) if timeline is not None else None
        if canvas is not None and float(getattr(canvas, "duration_ms", 0) or 0) > 0:
            ms = min(seek_sec * 1000.0, float(canvas.duration_ms))
            canvas.visual_ms = ms
            canvas.target_ms = ms
            canvas.is_playing = False
            canvas.vlc_last_update_time = time.time()
            # Block set_vlc_time / interpolation from fighting the pin.
            canvas.user_seek_lock_time = time.time() + 180.0
            try:
                canvas.update()
            except Exception:
                pass
            if hasattr(self.ui, "label_time"):
                dur_ms = int(float(canvas.duration_ms))
                def _fmt(ms_v: int) -> str:
                    s = max(0, ms_v) // 1000
                    return f"{(s % 3600) // 60:02d}:{s % 60:02d}"
                self.ui.label_time.setText(f"{_fmt(int(ms))} / {_fmt(dur_ms)}")
        try:
            if hasattr(self, "player") and self.player:
                self.player.pause = True
        except Exception:
            pass
        self._set_playback_loading(True, self._remux_quality_hold_message)
        # Hard safety: never leave Preparing/Buffering owned by a remux hold forever.
        QTimer.singleShot(
            180_000,
            lambda t=hold_token: self._remux_quality_hold_watchdog(t),
        )

    def _remux_quality_hold_watchdog(self, token: int) -> None:
        """Drop a stuck remux-quality overlay if seek restore never finishes."""
        if token != getattr(self, "_remux_quality_hold_token", 0):
            return
        if not getattr(self, "_remux_quality_hold_active", False):
            return
        logging.warning("Remux quality hold watchdog: clearing stuck Preparing/Buffering overlay")
        self._clear_remux_quality_hold()
        try:
            if hasattr(self, "player") and self.player:
                self.player.pause = False
        except Exception:
            pass

    def _clear_remux_quality_hold(self) -> None:
        """Release timeline pin / overlay owned by a remux quality switch."""
        was = bool(getattr(self, "_remux_quality_hold_active", False))
        self._remux_quality_hold_active = False
        self._remux_quality_hold_seek = None
        self._remux_quality_hold_message = None
        timeline = getattr(self, "custom_timeline", None)
        canvas = getattr(timeline, "canvas", None) if timeline is not None else None
        if canvas is not None:
            # Drop the long lock so normal sync resumes.
            canvas.user_seek_lock_time = 0.0
        if was:
            self._set_playback_loading(False)

    def _capture_preview_seek_sec(self) -> float:
        """Best current playhead for quality-switch restore (mpv, else timeline)."""
        seek_pos = 0.0
        try:
            seek_pos = float(getattr(self.player, "time_pos", 0) or 0)
        except Exception:
            seek_pos = 0.0
        timeline = getattr(self, "custom_timeline", None)
        canvas = getattr(timeline, "canvas", None) if timeline is not None else None
        if canvas is not None:
            try:
                visual_sec = float(getattr(canvas, "visual_ms", 0) or 0) / 1000.0
            except Exception:
                visual_sec = 0.0
            # Prefer timeline when mpv already reset / lagging after a prior reopen.
            if visual_sec > seek_pos + 0.35 or seek_pos < 0.25:
                seek_pos = max(seek_pos, visual_sec)
        return max(0.0, seek_pos)

    @staticmethod
    def _norm_media_path(path: str | None) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.normpath(str(path).replace("\\", "/")))

    def _mpv_path_matches_play_abs(self) -> bool:
        """True when libmpv's open path is the remux/play target (not the prior clip)."""
        want = self._norm_media_path(getattr(self, "_current_play_abs_path", None))
        if not want:
            return False
        player = getattr(self, "player", None)
        if not player:
            return False
        try:
            have = self._norm_media_path(getattr(player, "path", None))
        except Exception:
            return False
        return bool(have) and have == want

    def _schedule_remux_seek_restore(
        self,
        seek_sec: float,
        switch_gen: int,
        attempts: int = 0,
        *,
        path_ready: bool = False,
        seek_issued: bool = False,
    ) -> None:
        """Retry absolute seek after remux reopen until PTS is near the prior playhead.

        Must not trust ``time_pos`` until mpv's path matches the new play file —
        otherwise a stale position from the previous quality falsely "lands" the
        restore (attempts=0) and clears Preparing into eternal Buffering.
        """
        if switch_gen != getattr(self, "_media_switch_gen", 0):
            self._clear_remux_quality_hold()
            return
        seek_sec = float(seek_sec)
        if seek_sec <= 0.05:
            self._clear_remux_quality_hold()
            try:
                if hasattr(self, "player") and self.player:
                    self.player.pause = False
            except Exception:
                pass
            return

        def _retry(*, ready: bool = path_ready, issued: bool = seek_issued, delay: int = 50) -> None:
            QTimer.singleShot(
                delay,
                lambda: self._schedule_remux_seek_restore(
                    seek_sec,
                    switch_gen,
                    attempts + 1,
                    path_ready=ready,
                    seek_issued=issued,
                ),
            )

        if not self._mpv_has_media():
            if attempts < 160:
                _retry(ready=False, issued=False, delay=50)
            else:
                logging.warning(
                    "Remux quality seek restore abandoned (player not ready, want=%.2fs)",
                    seek_sec,
                )
                self._clear_remux_quality_hold()
                try:
                    if hasattr(self, "player") and self.player:
                        self.player.pause = False
                except Exception:
                    pass
            return

        # Wait until the *new* remux/cache path is actually open.
        if not self._mpv_path_matches_play_abs():
            if attempts < 200:
                _retry(ready=False, issued=False, delay=50)
            else:
                logging.warning(
                    "Remux quality seek restore abandoned (path mismatch, want=%.2fs path=%s)",
                    seek_sec,
                    getattr(self, "_current_play_abs_path", None),
                )
                self._clear_remux_quality_hold()
                try:
                    if hasattr(self, "player") and self.player:
                        self.player.pause = False
                except Exception:
                    pass
            return

        if not path_ready:
            # First tick with the new path loaded — ignore any leftover time_pos.
            _retry(ready=True, issued=False, delay=40)
            return

        remux = getattr(self, "_progressive_remux", None)
        remux_inflight = False
        if remux is not None:
            try:
                remux_inflight = remux[1].poll() is None
            except Exception:
                remux_inflight = False

        dur = self._playback_duration_sec() or 0.0
        # Incomplete growing files report a short duration — keep waiting.
        if dur > 0.5 and seek_sec > dur + 1.0 and remux_inflight:
            if attempts < 600:
                _retry(ready=True, issued=seek_issued, delay=100)
                return

        target = seek_sec
        if dur > 0.5:
            target = min(seek_sec, max(0.0, float(dur) - 0.05))

        # Bypass _safe_mpv_seek gates — quality rebind may still be settling first-frame.
        issued = False
        try:
            if self._mpv_has_media() and self._mpv_path_matches_play_abs():
                self.player.seek(float(target), reference="absolute", precision="exact")
                issued = True
        except Exception:
            try:
                self.player.time_pos = float(target)
                issued = True
            except Exception:
                issued = False

        if issued:
            seek_issued = True

        try:
            pos = float(getattr(self.player, "time_pos", 0) or 0)
        except Exception:
            pos = 0.0

        # Require at least one seek into the new file before accepting a land —
        # never treat the previous clip's time_pos as success.
        if (not seek_issued) or abs(pos - target) > 1.25:
            max_attempts = 600 if remux_inflight else 200
            if attempts < max_attempts:
                _retry(ready=True, issued=seek_issued, delay=50 if issued else 80)
                return
            logging.warning(
                "Remux quality seek restore gave up (want=%.2fs got=%.2fs)",
                target,
                pos,
            )

        landed = pos if seek_issued and abs(pos - target) <= 1.25 else target
        logging.info(
            "Remux quality seek restore %.2fs (got=%.2fs, attempts=%d)",
            target,
            pos,
            attempts,
        )
        timeline = getattr(self, "custom_timeline", None)
        canvas = getattr(timeline, "canvas", None) if timeline is not None else None
        if canvas is not None and float(getattr(canvas, "duration_ms", 0) or 0) > 0:
            ms = landed * 1000.0
            canvas.user_seek_lock_time = 0.0
            canvas.visual_ms = ms
            canvas.target_ms = ms
            canvas.vlc_last_update_time = time.time()
            try:
                canvas.update()
            except Exception:
                pass
        self._ignore_playback_stall(0.8)
        self._clear_remux_quality_hold()
        try:
            if hasattr(self, "player") and self.player:
                self.player.pause = False
        except Exception:
            pass

    def _maybe_rebind_linux_remux_preview_quality(self, preset_id: str) -> None:
        """Rebuild / switch remux cache when the player gear changes on Linux."""
        if not self._playing_linux_dash_remux():
            return
        from steempeg.core.dash.mpd_playback import (
            existing_playback_cache_for_play,
            max_height_for_quality,
            normalize_remux_quality_id,
            should_remux_mpd_for_playback,
        )

        qid = normalize_remux_quality_id(preset_id)
        cur_qid = getattr(self, "_current_remux_quality_id", None)
        want_remux = should_remux_mpd_for_playback(qid)
        # Native Source (auto + demux): cur_qid is None.
        if not want_remux and cur_qid is None:
            return
        if want_remux and cur_qid == qid:
            return

        mpd = os.path.abspath(self._current_mpd_abs_path).replace("\\", "/")
        clip_path = getattr(self, "_preview_clip_path", None) or mpd
        max_h = max_height_for_quality(qid)
        switch_gen = getattr(self, "_media_switch_gen", 0)
        seek_pos = self._capture_preview_seek_sec()
        hold_msg = "Buffering…" if qid == "source" else f"Preparing {qid}…"
        self._arm_remux_quality_hold(seek_pos, message=hold_msg)

        # Experimental auto: Source with demux → play the .mpd directly.
        if not want_remux:
            logging.info(
                "Preview quality source: native DASH %s (seek=%.2fs)",
                mpd,
                seek_pos,
            )
            self._current_remux_quality_id = None
            self._start_clip_playback(
                switch_gen,
                mpd,
                mpd,
                clip_path,
                seek_after=seek_pos,
            )
            return

        cached = existing_playback_cache_for_play(mpd, quality_id=qid)
        if cached:
            logging.info(
                "Preview quality %s: switching remux cache %s (seek=%.2fs)",
                qid,
                cached,
                seek_pos,
            )
            self._current_remux_quality_id = qid
            self._start_clip_playback(
                switch_gen,
                mpd,
                cached.replace("\\", "/"),
                clip_path,
                seek_after=seek_pos,
            )
            return

        logging.info(
            "Preview quality %s: remuxing DASH at %s (seek=%.2fs)",
            qid,
            f"{max_h}p" if max_h else "source",
            seek_pos,
        )
        # Claim the quality immediately so a second gear click does not fork jobs.
        self._current_remux_quality_id = qid
        self._start_clip_remux_async(
            switch_gen,
            mpd,
            clip_path,
            quality_id=qid,
            max_height=max_h,
            seek_after=seek_pos,
        )

    def _retry_preview_quality(self, preset_id: str, retry: int = 0) -> None:
        from steempeg.ui.player import preview_quality as pq

        if pq.normalize_quality_id(getattr(self, "_preview_quality_id", "")) != preset_id:
            return
        if pq.apply_mpv_preview_quality(getattr(self, "player", None), preset_id):
            return
        if retry < 15:
            QTimer.singleShot(100, lambda: self._retry_preview_quality(preset_id, retry + 1))

    def show_preview_quality_menu(self) -> None:
        if hasattr(self, "_is_previewing_rendered_media") and self._is_previewing_rendered_media():
            return
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