from steempeg.version import APP_VERSION_STR
from steempeg.ui import design_tokens as tok
from steempeg.ui.main_window import MainWindow
from steempeg.infra.logging import global_exception_handler, setup_logging, session_timestamp, mpv_log_path, prune_old_logs
from steempeg.infra import paths
from steempeg.ui.player.surface import MPVWrapper
from steempeg.ui.player.fullscreen import FullscreenEventFilter
from steempeg.ui.player.controls.audio import VolumeControlWidget
from steempeg.ui.player.controls.speed import SpeedControlWidget
from steempeg.ui.player.controls.timeline import CustomTimelineWidget
from steempeg.ui.library.filters import FilterMenu
from steempeg.ui.updater_mixin import UpdaterMixin
from steempeg.ui.settings.controller import SettingsMixin
from steempeg.ui.render_controller import RenderMixin
from steempeg.render.queue import RenderQueue
from steempeg.ui.library.controller import LibraryMixin
from steempeg.ui.library.rendered_library import RenderedLibraryMixin
from steempeg.ui.player.controller import PlayerMixin
from steempeg.ui.lifecycle import LifecycleMixin
from steempeg.ui.splitter_rules import SplitterRulesMixin
from steempeg.ui.hide_watcher import HideWatcher
from steempeg.ui.widgets.combo_chrome import (
    apply_dark_combo_popup,
    compact_combo_stylesheet,
    settings_panel_stylesheet,
)




import sys
import os
import logging
from datetime import datetime


if getattr(sys, 'frozen', False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_bin_dir = os.path.join(_base_dir, "bin")
os.environ["PATH"] = _bin_dir + os.pathsep + _base_dir + os.pathsep + os.environ["PATH"]

# libmpv aborts/segfaults if LC_NUMERIC is a non-C locale (SteamOS/Deck default).
os.environ.setdefault("LC_NUMERIC", "C")
try:
    import locale as _locale

    _locale.setlocale(_locale.LC_NUMERIC, "C")
except Exception:
    pass

# Must run before ``import mpv``: ctypes.find_library ignores PATH on Linux.
from steempeg.infra.libmpv_bootstrap import bootstrap_libmpv

bootstrap_libmpv()

import mpv

from PySide6.QtCore import Qt, QTimer, QSize, QObject
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtWidgets import QHeaderView, QAbstractItemView
from PySide6.QtGui import QIcon

from steempeg.ui.widgets import AnimatedRenderBar, ElidedLabel, FilterPillButton

def get_resource_path(relative_path):
    return paths.get_resource_path(relative_path)


def _is_enabled_setting(value) -> bool:
    """Parse settings flag values that may arrive as bool/str/int."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _force_native_window_icon(widget, ico_path):
    """Push the .ico onto the realized HWND via WM_SETICON (+ class icons).

    Qt's setWindowIcon is not always enough on first launch: Windows caches the
    taskbar button icon per AppUserModelID, and on a cold cache the button shows
    the generic icon until a later run warms it up (the "icon only appears on the
    2nd/3rd launch" bug). Re-applying the icon directly to the native window after
    it is shown populates that cache immediately, on the very first launch.

    Dev launches under ``python.exe`` are worse: a later FRAMECHANGED (frameless
    chrome) makes Explorer fall back to the host process icon (blank document).
    Setting both WM_SETICON and the window-class HICON after chrome settle fixes it.
    """
    if os.name != 'nt' or not ico_path or not os.path.exists(ico_path):
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SendMessageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
        ]

        WM_SETICON = 0x0080
        ICON_SMALL, ICON_BIG = 0, 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        GCLP_HICON = -14
        GCLP_HICONSM = -34

        hwnd = int(widget.winId())
        # Prefer exact sizes; fall back to the ico's default face if LoadImage fails.
        big = user32.LoadImageW(None, ico_path, IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
        if not big:
            big = user32.LoadImageW(None, ico_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        small = user32.LoadImageW(None, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if not small:
            small = big
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
        # Class icons survive FRAMECHANGED better than per-window WM_SETICON alone
        # when the process is still python.exe / pythonw.exe.
        set_class = getattr(user32, "SetClassLongPtrW", None) or getattr(
            user32, "SetClassLongW", None
        )
        if set_class is not None:
            if big:
                set_class(hwnd, GCLP_HICON, big)
            if small:
                set_class(hwnd, GCLP_HICONSM, small)
    except Exception:
        pass


def get_save_directory():
    return paths.get_save_directory()

from PySide6.QtCore import Qt


from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt


    

from PySide6.QtCore import Qt


_PLAYBACK_BUTTONS_QSS = """
QPushButton#btn_play, QPushButton#btn_skip_back, QPushButton#btn_skip_forward {
    background-color: transparent;
    border: none;
    outline: none;
    padding: 0px;
    margin: 0px;
}
QPushButton#btn_play:hover, QPushButton#btn_skip_back:hover, QPushButton#btn_skip_forward:hover,
QPushButton#btn_play:pressed, QPushButton#btn_skip_back:pressed, QPushButton#btn_skip_forward:pressed,
QPushButton#btn_play:focus, QPushButton#btn_skip_back:focus, QPushButton#btn_skip_forward:focus {
    background-color: transparent;
    border: none;
    outline: none;
}
"""

_PLAYER_SLIDER_QSS = """
QSlider#slider_timeline::groove:horizontal {
    border-radius: 2px;
    height: 4px;
    background: rgba(255, 255, 255, 50);
}
QSlider#slider_timeline {
    margin-left: 15px;
    margin-right: 5px;
}
QSlider#slider_timeline::sub-page:horizontal {
    background: #1a9fff;
    border-radius: 2px;
}
QSlider#slider_timeline::handle:horizontal {
    background: #ffffff;
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
QSlider#slider_timeline::handle:horizontal:hover {
    background: #1a9fff;
}
"""


class SteempegApp(RenderedLibraryMixin, LifecycleMixin, SplitterRulesMixin, PlayerMixin, LibraryMixin, RenderMixin, SettingsMixin, UpdaterMixin, QObject):
    def _refresh_dev_button_visibility(self) -> None:
        """Show/hide footer Dev button from cache/settings.json dev_mode."""
        btn_dev = getattr(getattr(self, "ui", None), "btn_dev", None)
        if btn_dev is None:
            return
        enabled = False
        try:
            settings = self.load_user_settings() or {}
            if isinstance(settings, dict):
                enabled = _is_enabled_setting(settings.get("dev_mode", False))
        except Exception:
            enabled = False
        btn_dev.setVisible(enabled)

    def _apply_playback_button_styles(self):
        """Playback buttons live under HudFrame; style them directly (not via right_panel)."""
        if not hasattr(self.ui, "btn_play"):
            return
        from PySide6.QtWidgets import QSizePolicy
        from steempeg.ui.design_tokens import with_tooltip_style
        from steempeg.ui.widgets.press_feedback import install_press_feedback

        tip_qss = with_tooltip_style(_PLAYBACK_BUTTONS_QSS)
        for btn in (self.ui.btn_play, self.ui.btn_skip_back, self.ui.btn_skip_forward):
            btn.setFlat(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(tip_qss)
            install_press_feedback(btn)
        self.ui.btn_skip_back.setMinimumSize(40, 48)
        self.ui.btn_skip_back.setMaximumSize(40, 48)
        self.ui.btn_skip_forward.setMinimumSize(40, 48)
        self.ui.btn_skip_forward.setMaximumSize(40, 48)
        self.ui.btn_play.setMinimumSize(80, 48)
        self.ui.btn_play.setMaximumSize(80, 48)
        self.ui.btn_play.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _install_animated_render_bar(self, parent=None):
        """Swap designer QProgressBar for AnimatedRenderBar (safe to call more than once)."""
        if not hasattr(self.ui, 'progress_render'):
            return self.ui.progress_render if hasattr(self.ui, 'progress_render') else None
        bar = self.ui.progress_render
        if isinstance(bar, AnimatedRenderBar):
            if parent is not None:
                bar.setParent(parent)
            return bar

        old = bar
        bar = AnimatedRenderBar(parent or old.parentWidget())
        bar.setObjectName("progress_render")
        old_parent = old.parentWidget()
        layout = old_parent.layout() if old_parent else None
        if layout is not None:
            idx = layout.indexOf(old)
            if idx >= 0:
                layout.removeWidget(old)
                layout.insertWidget(idx, bar)
        old.hide()
        old.deleteLater()
        self.ui.progress_render = bar
        return bar

    def __init__(self):
        # 1. LOADING THE INTERFACE
        super().__init__()

        self.ui = MainWindow(app_host=self)
        self._install_animated_render_bar()

        # Chrome color theme (built-in default until saved settings load at startup).
        from steempeg.ui import design_tokens as _tok_boot
        from steempeg.ui.ui_theme import UI_THEME_DEFAULT

        self._chrome_theme = _tok_boot.DEFAULT_CHROME_THEME
        self._ui_theme = UI_THEME_DEFAULT
        self._ui_theme_applied = False

        from PySide6.QtGui import QColor, QPalette
        self.ui.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        dark = QColor(self._current_app_bg())
        palette = self.ui.palette()
        palette.setColor(QPalette.ColorRole.Window, dark)
        self.ui.setPalette(palette)
        self.ui.setAutoFillBackground(True)

        self.ui.setStyleSheet(self._shell_stylesheet(self._current_app_bg()))
        
        # Custom SteempegTitleBar shows the visible label; the native window title
        # still feeds the taskbar hover / Alt-Tab tooltip, so give it the app name.
        self.ui.setWindowTitle(f"Steempeg v{APP_VERSION_STR}")
        
        # Setting the application icon
        from steempeg.ui.icon_utils import app_window_icon

        _win_icon = app_window_icon()
        if not _win_icon.isNull():
            self.ui.setWindowIcon(_win_icon)

        # 2. DATABASE AND VARIABLES
        # Steam bitrate dictionary in megabits (Mbps) for different resolutions
        self.steam_bitrate_presets = {
            "Ultra": {"4320p": 120, "2160p": 50, "1440p": 32, "1080p": 24, "720p": 12, "480p": 6, "360p": 3, "260p": 1.5, "144p": 0.5},
            "High": {"4320p": 90, "2160p": 38, "1440p": 22, "1080p": 12, "720p": 7.5, "480p": 4, "360p": 2, "260p": 1.0, "144p": 0.3},
            "Medium": {"4320p": 60, "2160p": 28.5, "1440p": 16.5, "1080p": 9, "720p": 5.6, "480p": 2.5, "360p": 1.2, "260p": 0.6, "144p": 0.2},
            "Low": {"4320p": 40, "2160p": 19, "1440p": 11, "1080p": 6, "720p": 3.75, "480p": 1.5, "360p": 0.8, "260p": 0.4, "144p": 0.1}
        }

        self.game_names_cache = {} # Cache for game names to avoid spamming the Steam API
        self.game_icons_cache = {} # Cache for downloaded Steam images
        self.clips_folder = ""
        self.clips_folders = []
        
        # --- Export destination (default rendered_videos; Main Settings may override) ---
        from steempeg.ui.settings_prefs import apply_export_folder, default_export_dir

        _default_export = default_export_dir()
        self.custom_destination = _default_export
        # The button keeps a static "Save as…" label; the full path lives in the Output line.
            
        self.current_orig_bitrate = 0 # Bitrate of the selected original clip
        self.current_clip_duration_sec = 0
        self.render_queue = RenderQueue()
        self._selected_queue_job_id = None
        self._loading_queue_job = False
        self._queue_batch_active = False
        self._queue_scheme_deferred = False
        self._queue_resume_job_id = None
        # Library card preview while queue mode is on — header/dash follow the
        # playing clip instead of Ready job #1 until a queue card is activated.
        self._queue_library_preview_diversion = False
        self.render_thread = None
        self._preview_clip_path = None
        # Last successful export clip — Completed plaque in normal / deferred mode
        # (single Start Render never inserts a COMPLETED job into render_queue).
        self._completed_plaque_clip_path = None
        self._clip_session_memory = {}

        
        # Export quality ladder (Divine 4K / Goddess 8K+); rebuilt per clip when taller.
        from steempeg.render.quality_presets import build_quality_presets

        self.all_qualities = build_quality_presets()

        self.set_status("Ready")

        self.cache_dir = os.path.join(get_save_directory(), "cache")
        self.logs_dir = os.path.join(get_save_directory(), "logs")
        self.screenshots_dir = os.path.join(get_save_directory(), "Screenshots")

        if not os.path.exists(self.screenshots_dir):
            os.makedirs(self.screenshots_dir)

        if not os.path.exists(self.logs_dir):
            os.makedirs(self.logs_dir)

        self._session_ts = session_timestamp()
        # Load prefs early so log level / date / FFmpeg apply from the first line.
        early_settings = {}
        try:
            early_path = os.path.join(self.cache_dir, "settings.json")
            if os.path.isfile(early_path):
                from steempeg.infra import cache as _cache

                early_settings = _cache.read_json(early_path) or {}
        except Exception:
            early_settings = {}
        try:
            from steempeg.ui.settings_prefs import (
                configure_runtime_prefs,
                load_app_log_level,
                load_media_cache_limit_gb,
                resolve_screenshots_folder,
            )

            app_level = load_app_log_level(early_settings)
        except Exception:
            app_level = "debug"
            configure_runtime_prefs = None  # type: ignore
            load_media_cache_limit_gb = None  # type: ignore
            resolve_screenshots_folder = None  # type: ignore

        self.current_log_file = setup_logging(
            self.logs_dir, APP_VERSION_STR, self._session_ts, level=app_level
        )
        self.current_mpv_log_file = mpv_log_path(self.logs_dir, self._session_ts)
        prune_old_logs(
            self.logs_dir,
            keep_paths=(self.current_log_file, self.current_mpv_log_file),
            max_files=40,
        )
        if configure_runtime_prefs is not None:
            try:
                configure_runtime_prefs(early_settings)
            except Exception:
                logging.exception("configure_runtime_prefs failed")
        logging.info("Logs dir: %s", self.logs_dir)
        logging.info("Cache dir: %s", self.cache_dir)

        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir) # Create a cache folder if it doesn't exist

        if load_media_cache_limit_gb is not None:
            try:
                from steempeg.infra.media_cache import prune_media_cache

                prune_media_cache(
                    self.cache_dir, load_media_cache_limit_gb(early_settings)
                )
            except Exception:
                logging.exception("media cache prune at startup failed")

        if resolve_screenshots_folder is not None:
            try:
                self.screenshots_dir = resolve_screenshots_folder(early_settings)
            except Exception:
                pass
        if not os.path.exists(self.screenshots_dir):
            os.makedirs(self.screenshots_dir)

        self.json_cache_path = os.path.join(self.cache_dir, "games.json")
        self.game_names_cache = self.load_json_cache() # JSON
        self.game_icons_cache = {} # This is where we store downloaded images in memory
        try:
            from steempeg.ui.icon_shape import load_icon_shape_from_settings
            from steempeg.ui.clip_card_style import (
                KEY_CLIP_CARD_STYLE,
                KEY_CLIP_CARD_STYLE_REV,
                load_clip_card_style_from_settings,
                migrate_clip_card_style_in_settings,
            )
            from steempeg.ui.player_header_layout import load_header_layout_from_settings
            from steempeg.ui.player_layout import load_player_layout_from_settings
            from steempeg.ui.player_outline import load_player_outline_from_settings
            from steempeg.ui.player_header_size import (
                KEY_PLAYER_HEADER_SIZE,
                KEY_PLAYER_HEADER_SIZE_REV,
                load_player_header_size_from_settings,
                migrate_player_header_size_in_settings,
            )
            from steempeg.ui.timeline_strip_size import (
                KEY_TIMELINE_STRIP_SIZE,
                KEY_TIMELINE_STRIP_SIZE_REV,
                load_timeline_strip_size_from_settings,
                migrate_timeline_strip_size_in_settings,
            )
            from steempeg.ui.player_boost import load_player_boost_from_settings

            _settings0 = self.load_user_settings() or {}
            load_icon_shape_from_settings(_settings0)
            if migrate_clip_card_style_in_settings(_settings0):
                if KEY_CLIP_CARD_STYLE in _settings0:
                    self.save_user_settings(
                        KEY_CLIP_CARD_STYLE, _settings0[KEY_CLIP_CARD_STYLE]
                    )
                self.save_user_settings(
                    KEY_CLIP_CARD_STYLE_REV, _settings0[KEY_CLIP_CARD_STYLE_REV]
                )
            load_clip_card_style_from_settings(_settings0)
            load_header_layout_from_settings(_settings0)
            load_player_layout_from_settings(_settings0)
            load_player_outline_from_settings(_settings0)
            if migrate_player_header_size_in_settings(_settings0):
                if KEY_PLAYER_HEADER_SIZE in _settings0:
                    self.save_user_settings(
                        KEY_PLAYER_HEADER_SIZE, _settings0[KEY_PLAYER_HEADER_SIZE]
                    )
                self.save_user_settings(
                    KEY_PLAYER_HEADER_SIZE_REV,
                    _settings0[KEY_PLAYER_HEADER_SIZE_REV],
                )
            load_player_header_size_from_settings(_settings0)
            if migrate_timeline_strip_size_in_settings(_settings0):
                if KEY_TIMELINE_STRIP_SIZE in _settings0:
                    self.save_user_settings(
                        KEY_TIMELINE_STRIP_SIZE, _settings0[KEY_TIMELINE_STRIP_SIZE]
                    )
                self.save_user_settings(
                    KEY_TIMELINE_STRIP_SIZE_REV,
                    _settings0[KEY_TIMELINE_STRIP_SIZE_REV],
                )
            load_timeline_strip_size_from_settings(_settings0)
            load_player_boost_from_settings(_settings0)
            from steempeg.ui.settings_prefs import (
                KEY_PERMANENT_EXPORT_FOLDER,
                apply_export_folder,
                resolve_permanent_export_folder,
                sync_export_folder_to_settings,
            )

            _export = resolve_permanent_export_folder(_settings0)
            apply_export_folder(self, _export, persist=False)
            # One-shot migrate: seed permanent_export_folder from resolved path.
            if KEY_PERMANENT_EXPORT_FOLDER not in _settings0:
                sync_export_folder_to_settings(self, _export)
        except Exception:
            pass
        if hasattr(self, "restore_salvage_verified_clips"):
            self.restore_salvage_verified_clips()

        # Apply saved UI font then theme (theme QSS reads FONT_APP).
        # UI font preference is Linux-only; Windows stays classic Segoe-first.
        try:
            from steempeg.ui.design_tokens import (
                KEY_UI_FONT,
                apply_ui_font_preference,
                ui_font_preference_supported,
            )

            if ui_font_preference_supported():
                apply_ui_font_preference(
                    self.load_user_settings().get(KEY_UI_FONT),
                    app=QApplication.instance(),
                )
            else:
                apply_ui_font_preference(app=QApplication.instance())
        except Exception:
            pass
        from steempeg.ui.ui_theme import KEY_UI_THEME, UI_THEME_DEFAULT, normalize_ui_theme

        saved_ui = normalize_ui_theme(
            self.load_user_settings().get(KEY_UI_THEME, UI_THEME_DEFAULT)
        )
        self.apply_ui_theme(saved_ui, persist=False)
        
        # 3. CONFIGURING THE INTERFACE (TABLE AND COMBOBOXES)
        if hasattr(self.ui, 'table_clips'):
            self.ui.table_clips.setColumnCount(4)
            # 1. CHANGE THE ORDER OF HEADINGS
            self.ui.table_clips.setHorizontalHeaderLabels(["Game Name", "Type", "Date", "Time"])
            self.ui.table_clips.setIconSize(QSize(16, 16))

            self.ui.table_clips.setFocusPolicy(Qt.NoFocus)
            self.ui.table_clips.viewport().setFocusPolicy(Qt.NoFocus)

            # GUI TABLE
            self.ui.table_clips.setStyleSheet(f"""
                QTableWidget {{ 
                    background: transparent; 
                    border: none; 
                    outline: none; 
                }}
                QTableWidget::item {{ 
                    padding: 4px 12px; 
                    border-bottom: 1px solid #282828; 
                    color: #e0e0e0; 
                    font-family: {tok.FONT_APP};
                    font-size: 13px;
                    font-weight: 600; 
                }}
                QTableWidget::item:hover {{ 
                    background-color: #303030; 
                }}
                QTableWidget::item:selected {{ 
                    background-color: #3a2e54; 
                    color: #ffffff; 
                }}
                
                
                QHeaderView {{
                    background-color: transparent;
                    border: none;
                }}
                QHeaderView::section {{
                    background-color: #2a2a2a; 
                    color: #999999;
                    padding: 6px 14px;
                    border: 1px solid #353535; 
                    border-radius: 12px;
                    margin-right: 6px; 
                    margin-bottom: 6px; 
                    font-size: 12px;
                    font-weight: bold;
                }}
                QHeaderView::section:hover {{
                    background-color: #353535;
                    color: #ffffff;
                    border: 1px solid #555555;
                }}
                QHeaderView::section:checked, QHeaderView::section:pressed {{
                    background-color: #3a2e54; 
                    color: #b29ae7;
                    border: 1px solid #6b5a8e;
                }}
                QHeaderView::up-arrow, QHeaderView::down-arrow {{
                    width: 0px; height: 0px;
                }}
            """)
            self.ui.table_clips.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.ui.table_clips.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.ui.table_clips.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.ui.table_clips.setShowGrid(False)
            self.ui.table_clips.verticalHeader().setVisible(False)
            # CustomContextMenu policy suppresses the native menu; the actual menu is
            # shown from the right-press eventFilter (lifecycle.py) so selection never
            # changes. Connecting customContextMenuRequested too would open a 2nd menu.
            self.ui.table_clips.setContextMenuPolicy(Qt.CustomContextMenu)
            # 2. ADJUST THE WIDTH
            header = self.ui.table_clips.horizontalHeader()

            header.setStretchLastSection(False)
            header.setMinimumSectionSize(40) # Allow shrinking the 'Game Name' column to the size of a single icon!
            self.ui.table_clips.setMinimumWidth(80) # Allow the splitter to collapse the entire table to zero!

            # 1. KILLING UGLY LINE BREAKS
            self.ui.table_clips.setWordWrap(False) # Text will never jump to the second line again!
            self.ui.table_clips.setTextElideMode(Qt.ElideRight) # Replace the truncated segment with aesthetic "..."

            self.ui.table_clips.verticalHeader().setSectionResizeMode(QHeaderView.Fixed) 
            self.ui.table_clips.verticalHeader().setDefaultSectionSize(48)
            
            
            # 2. Enter Bold Text
            from steempeg.ui.design_tokens import ui_qfont
            from PySide6.QtGui import QFont

            custom_font = ui_qfont(10, weight=QFont.Weight.DemiBold)
            self.ui.table_clips.setFont(custom_font)
            
            header.setSectionResizeMode(0, QHeaderView.Stretch)         
            header.setSectionResizeMode(1, QHeaderView.Interactive) # Switch to Interactive so they don't jump around when compressed.
            header.setSectionResizeMode(2, QHeaderView.Interactive) 
            header.setSectionResizeMode(3, QHeaderView.Interactive) 
            
            # Set the ideal width for the right columns
            self.ui.table_clips.setColumnWidth(1, 80)  # Type
            self.ui.table_clips.setColumnWidth(2, 130) # Date
            self.ui.table_clips.setColumnWidth(3, 100) # Duration
            
            # Paint ClipCard / list selection first; defer slow clip open to next tick.
            self.ui.table_clips.itemSelectionChanged.connect(self.sync_grid_from_table_selection)
            self.ui.table_clips.itemSelectionChanged.connect(self._schedule_clips_selection_preview)
            # Re-clicking the already-selected row does not fire selectionChanged —
            # still reopen so the card spinner / player switch has something to do.
            self.ui.table_clips.itemClicked.connect(self._on_clips_table_item_clicked)
            if hasattr(self, "update_clip_health_button"):
                self.ui.table_clips.itemSelectionChanged.connect(self.update_clip_health_button)
            if hasattr(self.ui, 'table_clips'):
                from PySide6.QtCore import QTimer 
                self.ui.table_clips.horizontalHeader().sortIndicatorChanged.connect(
                    # Give the table 50 milliseconds to physically finish sorting the rows!
                    lambda *args: QTimer.singleShot(50, self.build_netflix_grid) if hasattr(self, 'build_netflix_grid') else None
                )
                # Disable clicking on column headers - custom sorting via combo_sort is used instead
                self.ui.table_clips.horizontalHeader().setSectionsClickable(False)

            # --- SMART RIGHT-CLICK (NO ROW SELECTION) ---
            self.ui.table_clips.viewport().installEventFilter(self)
            self.ui.table_clips.installEventFilter(self)
            
            # Attaching an event listener to the main window
            self.ui.installEventFilter(self)
            
            QApplication.instance().aboutToQuit.connect(self.on_app_exit)

            import PySide6.QtWidgets as qtw
            import PySide6.QtCore as qtc

            #1: Hiding the old, ugly text from Qt Designer
            if hasattr(self.ui, 'label_13'):
                self.ui.label_13.hide()
                target_layout = self.ui.label_13.parentWidget().layout()
                insert_idx = target_layout.indexOf(self.ui.label_13)
            else:
                target_layout = self.ui.right_panel.layout()
                insert_idx = 0

            cm_row = qtw.QHBoxLayout()
            cm_row.setContentsMargins(0, 0, 0, 4)
            cm_row.setSpacing(8)

            # Legacy title pill (unused — tabs replaced it). Keep orphaned & hidden.
            self.mega_top_pill = qtw.QFrame()
            self.mega_top_pill.setObjectName("deprecatedLibraryPill")
            self.mega_top_pill.hide()
            self.mega_top_pill.setStyleSheet("""
                QFrame {
                    background-color: #2d2d2d;
                    border: 1px solid #353535;
                    border-radius: 16px; 
                }
            """)
            
            # Layer inside our tablet
            pill_layout = qtw.QHBoxLayout(self.mega_top_pill)
            pill_layout.setContentsMargins(24, 8, 24, 8) 
            
            # Only Folder Icon + Text
            self.lbl_cm = qtw.QLabel("📁 Clips Manager")
            self.lbl_cm.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 14px; border: none; background: transparent;")
            
            # Put the text into the tablet
            pill_layout.addWidget(self.lbl_cm)

            # 3. Tab row (Clips Manager + add-panel +) replaces the single centered pill
            self.setup_library_tab_bar(cm_row)

            # 1. MEGA-CAPSULE (All elements within a single floating island)
            # Container for external padding
            top_bar_layout = qtw.QHBoxLayout()
            top_bar_layout.setContentsMargins(12, 0, 12, 0)
            self._left_toolbar_outer = top_bar_layout
            
            mega_top_pill = qtw.QFrame()
            self.library_toolbar_pill = mega_top_pill
            mega_top_pill.setObjectName("libraryToolbarPill")
            from steempeg.ui.ui_density import (
                COMFORT as _DENSITY_COMFORT,
                toolbar_mega_pill_style,
            )
            from steempeg.ui.layout_defaults import (
                DEFAULT_LIBRARY_VIEW,
                LIBRARY_FOOTER_GAP,
                LIBRARY_TAB_TO_TOOLBAR_SPACING,
            )
            from steempeg.ui.widgets.view_mode_toggle import ViewModeChrome

            mega_top_pill.setStyleSheet(
                toolbar_mega_pill_style(_DENSITY_COMFORT, object_name="libraryToolbarPill")
            )

            top_pill_layout = qtw.QHBoxLayout(mega_top_pill)
            top_pill_layout.setContentsMargins(16, 6, 16, 6)  # Capsule Internal Padding
            # Match Render Queue View-plug spacing (View · track · count).
            top_pill_layout.setSpacing(8)
            self._top_pill_layout = top_pill_layout

            # View · Grid/List · • N Clips — RQ pill on the toggle; library count wording
            self.view_mode_chrome = ViewModeChrome(
                mega_top_pill,
                initial_mode=DEFAULT_LIBRARY_VIEW,
                dense=_DENSITY_COMFORT,
                initial_count="• 0 Clips",
            )
            self._lbl_view = self.view_mode_chrome.lbl_view
            self.toggle_pill = self.view_mode_chrome.toggle_pill
            self.btn_view_grid = self.view_mode_chrome.btn_view_grid
            self.btn_view_list = self.view_mode_chrome.btn_view_list
            self.lbl_clip_count = self.view_mode_chrome.lbl_count
            self.toggle_style_active = self.view_mode_chrome.toggle_style_active
            self.toggle_style_inactive = self.view_mode_chrome.toggle_style_inactive
            self.view_mode_chrome.add_to_layout(top_pill_layout)

            # BREATHABLE FILTER PAD
            self.btn_filter_pill = FilterPillButton()
            
            # Creating the menu and setting up the click handler!
            self.filter_menu = FilterMenu(self.ui)
            self.btn_filter_pill.clicked.connect(self.show_filter_menu)
            
            top_pill_layout.addWidget(self.btn_filter_pill)

            top_bar_layout.addWidget(mega_top_pill)

            # 2. KILLING A QT TABLE 
            from steempeg.ui.library.library_styles import (
                library_grid_stylesheet,
                library_table_stylesheet,
            )

            self.ui.table_clips.setShowGrid(False)
            
            # (Sorting buttons at the top
            self.ui.table_clips.horizontalHeader().setVisible(True)
            self.ui.table_clips.horizontalHeader().setHighlightSections(False)
            self.ui.table_clips.horizontalHeader().setDefaultAlignment(qtc.Qt.AlignCenter)
            
            self.ui.table_clips.verticalHeader().setVisible(False)
            self.ui.table_clips.setFrameShape(qtw.QFrame.NoFrame)
            self.ui.table_clips.setHorizontalScrollBarPolicy(qtc.Qt.ScrollBarAlwaysOff)
            self.ui.table_clips.setVerticalScrollBarPolicy(qtc.Qt.ScrollBarAlwaysOff)
            
            self.ui.table_clips.verticalHeader().setDefaultSectionSize(46) 
            self.ui.table_clips.setIconSize(qtc.QSize(26, 26)) 

            self.ui.table_clips.setStyleSheet(library_table_stylesheet())
            
            header = self.ui.table_clips.horizontalHeader()
            header.setStretchLastSection(False) 
            self.ui.table_clips.setColumnCount(4)
            self.ui.table_clips.setHorizontalHeaderLabels(["Game Name", "Type", "Date", "Duration"])

            # 1. Killing off wonky interactivity
            header.setSectionResizeMode(0, QHeaderView.Stretch) # Stretches behind the splitter
            header.setSectionResizeMode(1, QHeaderView.Fixed)   # Type – stone
            header.setSectionResizeMode(2, QHeaderView.Fixed)   # Date - stone
            header.setSectionResizeMode(3, QHeaderView.Fixed)   # Duration - stone
            
            header.setStretchLastSection(False)

            # 2. Assign the ideal width to fixed columns once.
            self.ui.table_clips.setColumnWidth(1, 100) # Type
            self.ui.table_clips.setColumnWidth(2, 160) # Date
            self.ui.table_clips.setColumnWidth(3, 100) # Duration

            # 3. NETFLIX-GRID
            self.grid_clips = qtw.QListWidget()
            self.grid_clips.setViewMode(qtw.QListWidget.IconMode)
            self.grid_clips.setResizeMode(qtw.QListWidget.Adjust)
            self.grid_clips.setSpacing(15)
            # Menu is shown from ClipCard.on_right_click (cards) and the viewport
            # right-press eventFilter (empty area). A customContextMenuRequested
            # connection on top of those would pop a duplicate menu.
            self.grid_clips.setContextMenuPolicy(Qt.CustomContextMenu)
            self.grid_clips.viewport().installEventFilter(self)
            self.grid_clips.installEventFilter(self)
            # We strictly fix the card sizes so they don't fly apart when hidden!
            self.grid_clips.setUniformItemSizes(True)
            self.grid_clips.setSelectionMode(qtw.QAbstractItemView.ExtendedSelection)
            self.grid_clips.setDragDropMode(qtw.QAbstractItemView.NoDragDrop)
            self.grid_clips.setMovement(qtw.QListView.Static)
            self.grid_clips.itemSelectionChanged.connect(self.on_grid_selection_changed)
            self.grid_clips.setStyleSheet(library_grid_stylesheet())
            self.grid_clips.setVerticalScrollBarPolicy(qtc.Qt.ScrollBarAlwaysOff)

            original_parent_layout = self.ui.table_clips.parentWidget().layout()
            original_idx = -1
            if original_parent_layout:
                original_idx = original_parent_layout.indexOf(self.ui.table_clips)

            # 4. LIBRARY BLOCK
            self.library_views_container = qtw.QFrame()
            from steempeg.ui import ui_theme as ut
            self.library_views_container.setStyleSheet(ut.elevated_panel_stylesheet())
            views_layout = qtw.QVBoxLayout(self.library_views_container)
            views_layout.setContentsMargins(10, 10, 10, 10)
            
            self.wrap_library_views_in_stack(views_layout)

            from steempeg.ui.library.library_styles import install_library_scroll_sync

            install_library_scroll_sync(self)

            # 5. Putting It All Together
            self.left_master_layout = qtw.QVBoxLayout()
            self.left_master_layout.setContentsMargins(0, 0, 0, 0)
            self.left_master_layout.setSpacing(LIBRARY_TAB_TO_TOOLBAR_SPACING)

            self.left_master_layout.addLayout(cm_row)
            self.left_master_layout.addLayout(top_bar_layout)
            self.left_master_layout.addWidget(self.library_views_container)
            
            # Insert our new mega-block back into the SAVED old layout.
            if original_parent_layout:
                # Pin clips ↔ About footer gap (same token as player↔dash air).
                original_parent_layout.setSpacing(LIBRARY_FOOTER_GAP)
                if original_idx != -1: 
                    original_parent_layout.insertLayout(original_idx, self.left_master_layout)
                else: 
                    original_parent_layout.addLayout(self.left_master_layout)

            # 6. View mode — chrome already owns Grid/List clicks
            self.view_mode_chrome.mode_changed.connect(self.set_view_mode)
            self.set_view_mode(DEFAULT_LIBRARY_VIEW)

        # --- UI INJECTION: SORTING PANEL (NEXT TO FILTER BUTTON) ---
        from PySide6.QtWidgets import QLabel, QComboBox, QSizePolicy

        # 1. Create a text label (like the one in View)
        lbl_sorting = QLabel("Sorting")
        self._lbl_sorting = lbl_sorting
        lbl_sorting.setStyleSheet("color: #888888; font-weight: bold; font-family: " + tok.FONT_APP + "; font-size: 13px;")

        # 2. Creating a stylish sorting dropdown list
        self.combo_sort = QComboBox()
        self.combo_sort.setCursor(Qt.PointingHandCursor)
        # Size to the widest entry, but allow shrink on Deck-class left panes
        # (compact min ~360). Popup still uses the full longest-entry width.
        self.combo_sort.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo_sort.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.combo_sort.setStyleSheet(compact_combo_stylesheet(settings_popup=True))
        apply_dark_combo_popup(self.combo_sort)

        # 3. Adding elements with attractive icons
        self.combo_sort.addItem(QIcon(get_resource_path("defaultsort.png")), "Default")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort1.png")), "Game Name (A - Z)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort2.png")), "Game Name (Z - A)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort1.png")), "Type (A - Z)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort2.png")), "Type (Z - A)")
        self.combo_sort.addItem(QIcon(get_resource_path("nohealth.png")), "Bad health first")
        self.combo_sort.addItem(QIcon(get_resource_path("health.png")), "Good health first")
        self.combo_sort.addItem(QIcon(get_resource_path("datesort1.png")), "Date (Oldest First)")
        self.combo_sort.addItem(QIcon(get_resource_path("datesort2.png")), "Date (Newest First)")
        self.combo_sort.addItem(QIcon(get_resource_path("durationsort1.png")), "Duration (Shortest)")
        self.combo_sort.addItem(QIcon(get_resource_path("durationsort2.png")), "Duration (Longest)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort1.png")), "Folder (A - Z)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort2.png")), "Folder (Z - A)")
        self.combo_sort.setMaxVisibleItems(14)

        # Same face as Refresh: bold UI stack 13px. QSS alone does not reliably
        # style a non-editable combo's painted text, so set it on the widget.
        from PySide6.QtGui import QFont as _QF
        from steempeg.ui.design_tokens import pin_ui_font

        _sort_font = pin_ui_font(
            self.combo_sort.font(), pixel_size=13, weight=_QF.Weight.Bold
        )
        self.combo_sort.setFont(_sort_font)

        # The compact field stays narrow, but the popup must be wide enough for the
        # longest entry (+ icon) so rows never elide to "Game Na...(A - Z)".
        _fm = self.combo_sort.fontMetrics()
        _longest = max(
            (_fm.horizontalAdvance(self.combo_sort.itemText(i)) for i in range(self.combo_sort.count())),
            default=0,
        )
        self.combo_sort.view().setMinimumWidth(_longest + 78)

        self.combo_sort.currentIndexChanged.connect(self.apply_sorting)

        # 4. Locate the filter button and elegantly assemble the panel to its LEFT.
        filter_btn = getattr(self, 'btn_filter_pill', None) or getattr(self.ui, 'btn_filter', None)
        if filter_btn and filter_btn.parentWidget() and filter_btn.parentWidget().layout():
            layout = filter_btn.parentWidget().layout()
            idx = layout.indexOf(filter_btn)
            
            # 4.1. Removing the old button from the main layout (to move it to the new group)
            layout.takeAt(idx)
            
            # 4.2. Creating a separate container for our Sort/Filter group
            from PySide6.QtWidgets import QHBoxLayout, QWidget, QFrame
            group_widget = QWidget()
            group_widget.setStyleSheet("background: transparent;")
            group_layout = QHBoxLayout(group_widget)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(0)
            self._sort_filter_group_layout = group_layout

            # 4.3. Placing elements into our new super-container
            group_layout.addWidget(lbl_sorting)
            group_layout.addSpacing(14)
            self._sort_label_spacing_idx = group_layout.count() - 1
            group_layout.addWidget(self.combo_sort)
            group_layout.addSpacing(2)
            group_layout.addWidget(filter_btn)

            # 4.4. Push the sorting/filter group to the right with a single stretch.
            layout.insertStretch(idx)
            layout.insertWidget(idx + 1, group_widget)

            
        # "Hide" Arch-Shaped Insert Button
        if hasattr(self.ui, 'settings_tabs'):
            from PySide6.QtWidgets import QPushButton, QWidget, QHBoxLayout, QVBoxLayout, QFrame, QScrollArea, QSizePolicy
            from PySide6.QtCore import QObject, QEvent

            # Hierarchy: nav/card face (BG_CARD) → curved divider → settings (BG_SETTINGS_PANEL).
            _neo_card = tok.BG_CARD
            _neo_settings = tok.BG_SETTINGS_PANEL
            _neo_border = tok.BORDER_CARD
            _neo_radius = float(tok.RADIUS_NEO_PANEL)
            _neo_r_px = int(round(_neo_radius))
            
            # 1. Hide the old tab bar
            self.ui.settings_tabs.tabBar().hide()
            
            # STEP 1
            # Opaque shell fill on each page (not transparent — Windows can paint that black).
            for i in range(self.ui.settings_tabs.count()):
                widget = self.ui.settings_tabs.widget(i)
                if widget:
                    obj_name = widget.objectName()
                    if obj_name:
                        widget.setStyleSheet(
                            f"QWidget#{obj_name} {{ background-color: {_neo_settings}; border: none; }}"
                        )
                    else:
                        widget.setStyleSheet(
                            f"background-color: {_neo_settings}; border: none;"
                        )
            
            # --- REMEMBERING THE OLD LOCATION ---
            parent_widget = self.ui.settings_tabs.parentWidget()
            parent_layout = parent_widget.layout() if parent_widget else None
            insert_idx = -1
            if parent_layout:
                insert_idx = parent_layout.indexOf(self.ui.settings_tabs)
                if insert_idx != -1:
                    parent_layout.removeWidget(self.ui.settings_tabs)
            
            self.ui.settings_tabs.setParent(None)
            
            # 2. MAIN CONTAINER

            self.neo_wrapper = QWidget()
            self.neo_wrapper.setObjectName("neo_wrapper")
            self.neo_wrapper.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.neo_wrapper.setStyleSheet(
                f"QWidget#neo_wrapper {{ background-color: {_neo_card}; "
                f"border-radius: {_neo_r_px}px; border: 1px solid {_neo_border}; }}"
            )
            
            neo_layout = QHBoxLayout(self.neo_wrapper)
            neo_layout.setContentsMargins(0, 0, 0, 0)
            neo_layout.setSpacing(0)
            
            # 3. Neo-nav rail — icons stay; no heavy slab fill / rect border (divider is
            # the curved left edge of the settings host against this card face).
            sidebar_frame = QFrame()
            self._neo_sidebar = sidebar_frame
            sidebar_frame.setObjectName("neo_sidebar")
            sidebar_frame.setFixedWidth(220)
            sidebar_frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            sidebar_frame.setStyleSheet(
                "QFrame#neo_sidebar { background: transparent; border: none; }"
            )
            sidebar_layout = QVBoxLayout(sidebar_frame)
            self._neo_sidebar_layout = sidebar_layout
            sidebar_layout.setAlignment(Qt.AlignTop)
            sidebar_layout.setContentsMargins(10, 15, 10, 15)
            sidebar_layout.setSpacing(10)
            
            pill_style = """
                QPushButton {
                    background-color: transparent; color: #a0a0a0;
                    border: 2px solid transparent; border-radius: 14px;
                    padding: 10px 12px 10px 14px; text-align: left; font-size: 14px; font-weight: 700;
                }
                QPushButton:hover { background-color: #383838; border: 2px solid #5a4b7a; color: #e0e0e0; }
                QPushButton:checked { background-color: #252525; border: 2px solid #8e7cc3; color: #ffffff; }
            """
            self._neo_nav_pill_style_template = True
            
            self.neo_nav_buttons = []
            from steempeg.ui.icon_assets import neo_nav_tab_icon
            from steempeg.ui.ui_density import NEO_NAV_COMFORT

            # Presets tab must exist before neo buttons are counted.
            from steempeg.ui.render_panel import ensure_presets_tab

            _presets_page = ensure_presets_tab(self.ui)
            _presets_page.setStyleSheet(
                f"QWidget#tab_presets {{ background-color: {_neo_settings}; border: none; }}"
            )

            _neo_icon_sz = 16
            _neo_icon_gap = 8
            for i in range(self.ui.settings_tabs.count()):
                text = NEO_NAV_COMFORT[i] if i < len(NEO_NAV_COMFORT) else self.ui.settings_tabs.tabText(i)
                btn = QPushButton(text)
                btn.setCheckable(True)
                btn.setAutoExclusive(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(pill_style)
                btn.setIcon(neo_nav_tab_icon(i, _neo_icon_sz, trailing_gap=_neo_icon_gap))
                btn.setIconSize(QSize(_neo_icon_sz + _neo_icon_gap, _neo_icon_sz))
                btn.clicked.connect(lambda checked, idx=i: self.ui.settings_tabs.setCurrentIndex(idx))
                sidebar_layout.addWidget(btn)
                self.neo_nav_buttons.append(btn)
                
            if self.neo_nav_buttons:
                # After Presets tab exists — honour Settings → Default Render panel tab.
                from steempeg.ui.settings_prefs import apply_default_render_tab

                apply_default_render_tab(self)
                
            self.ui.settings_tabs.currentChanged.connect(
                lambda idx: self.neo_nav_buttons[idx].setChecked(True) if idx < len(self.neo_nav_buttons) else None
            )
            # Make the scroll area size to the active page so short tabs don't get a phantom scrollbar
            self.ui.settings_tabs.currentChanged.connect(self.fit_settings_tab_to_page)
            
            neo_layout.addWidget(sidebar_frame)
            
            # 4. Settings content host — opaque shell gray (not #000 void / not transparent).
            self.right_scroll = QScrollArea()
            self.right_scroll.setObjectName("neo_settings_scroll")
            self.right_scroll.setWidgetResizable(True)
            self.right_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.right_scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.right_scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

            # Left radii only (= divider curve). Right edge stays square so the opaque
            # settings fill reaches the card edge; neo_wrapper's outer mask clips TR/BR.
            # (Rounding the host's right corners here re-opens the light card bleed.)
            self.right_scroll.setStyleSheet(f"""
                QScrollArea#neo_settings_scroll {{
                    background-color: {_neo_settings};
                    border: none;
                    border-top-left-radius: {_neo_r_px}px;
                    border-bottom-left-radius: {_neo_r_px}px;
                    border-top-right-radius: 0px;
                    border-bottom-right-radius: 0px;
                    border-left: 1px solid {_neo_border};
                }}
                QScrollArea#neo_settings_scroll > QWidget {{
                    background-color: {_neo_settings};
                    border: none;
                }}
                QWidget#qt_scrollarea_viewport {{
                    background-color: {_neo_settings};
                    border: none;
                }}
            """)
            from steempeg.ui.widgets.vertical_scrollbar import (
                ensure_steempg_vertical_scrollbar,
                settings_scrollbar_chrome,
            )

            ensure_steempg_vertical_scrollbar(
                self.right_scroll, chrome=settings_scrollbar_chrome()
            )
            # Palette lock — Windows light theme must not paint the viewport black/white.
            from PySide6.QtGui import QColor, QPalette

            _vp = self.right_scroll.viewport()
            if _vp is not None:
                _vp.setAutoFillBackground(True)
                _pal = _vp.palette()
                _qc = QColor(_neo_settings)
                for _group in (
                    QPalette.ColorGroup.Active,
                    QPalette.ColorGroup.Inactive,
                    QPalette.ColorGroup.Disabled,
                ):
                    _pal.setColor(_group, QPalette.ColorRole.Window, _qc)
                    _pal.setColor(_group, QPalette.ColorRole.Base, _qc)
                _vp.setPalette(_pal)
            
            self.ui.settings_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.ui.settings_tabs.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.ui.settings_tabs.setStyleSheet(f"""
                QTabWidget {{ background-color: {_neo_settings}; border: none; }}
                QTabWidget::pane {{ border: none; background-color: {_neo_settings}; }}
                QTabWidget > QStackedWidget {{ background-color: {_neo_settings}; border: none; }}
                QStackedWidget > QWidget {{ background-color: {_neo_settings}; }}

                QLabel {{ color: #cccccc; font-weight: bold; background: transparent; font-family: 'Arial'; }}
            """ + settings_panel_stylesheet("""
                QPushButton {
                    background-color: #303030; color: #ffffff;
                    border: 2px solid #3a3a3a; border-radius: 12px;
                    padding: 7px 15px; font-weight: bold; font-family: 'Arial';
                }
                QPushButton:hover { background-color: #262626; border: 2px solid #6b5a8e; }
                QPushButton:pressed { background-color: #141414; border: 2px solid #b29ae7; }
            """))
            
            # Place tabs in the scroll area
            self.right_scroll.setWidget(self.ui.settings_tabs)
            
            # --- SAFE MASK (QRegion), applied after the resize settles ---
            # Outer card mask on neo_wrapper clips all four corners (same radius as
            # stylesheet). Settings host mask rounds LEFT corners only — the nav↔
            # content curve — while keeping the right edge rectangular so the TR/BR
            # fill stays opaque. A full 4-corner mask on right_scroll used to punch
            # holes that let the lighter card face bleed through as 1px crumbs.
            # Debounced: setMask on every resize reclips/repaints the subtree.
            #
            # Linux/XWayland+NVIDIA: skip entirely. Even a debounced setMask next to
            # an embedded mpv wid= surface shears the shell when the right splitter
            # grows the player into the queue (ghost chrome / black bands).
            if sys.platform == "win32":
                from PySide6.QtCore import QRectF
                from PySide6.QtGui import QPainterPath, QRegion

                class _DebouncedRegionMask(QObject):
                    def __init__(self, target, radius: float, *, left_only: bool = False):
                        super().__init__(target)
                        self._target = target
                        self._radius = float(radius)
                        self._left_only = bool(left_only)
                        self._timer = QTimer(self)
                        self._timer.setSingleShot(True)
                        self._timer.timeout.connect(self._apply_mask)

                    def eventFilter(self, obj, event):
                        if event.type() == QEvent.Type.Resize:
                            self._timer.start(60)
                        return False

                    def _apply_mask(self):
                        obj = self._target
                        if obj is None or obj.width() <= 0 or obj.height() <= 0:
                            return
                        try:
                            w = float(obj.width())
                            h = float(obj.height())
                            r = min(self._radius, w * 0.5, h * 0.5)
                            path = QPainterPath()
                            if self._left_only:
                                # Square right edge; arc only TL / BL (divider curve).
                                path.moveTo(w, 0.0)
                                path.lineTo(w, h)
                                path.lineTo(r, h)
                                path.arcTo(QRectF(0.0, h - 2.0 * r, 2.0 * r, 2.0 * r), 270.0, -90.0)
                                path.lineTo(0.0, r)
                                path.arcTo(QRectF(0.0, 0.0, 2.0 * r, 2.0 * r), 180.0, -90.0)
                                path.closeSubpath()
                            else:
                                # Exact bounds — inset masks leave 1px parent crumbs at TR/BR.
                                path.addRoundedRect(QRectF(0.0, 0.0, w, h), r, r)
                            obj.setMask(QRegion(path.toFillPolygon().toPolygon()))
                        except Exception:
                            pass

                self.corner_mask = _DebouncedRegionMask(
                    self.right_scroll, _neo_radius, left_only=True
                )
                self.right_scroll.installEventFilter(self.corner_mask)
                self._neo_wrapper_mask = _DebouncedRegionMask(
                    self.neo_wrapper, _neo_radius, left_only=False
                )
                self.neo_wrapper.installEventFilter(self._neo_wrapper_mask)
            
            neo_layout.addWidget(self.right_scroll)
            
            # 5. Placing our wrapper back in the original location without conflicts
            if parent_layout:
                if insert_idx != -1:
                    parent_layout.insertWidget(insert_idx, self.neo_wrapper)
                else:
                    parent_layout.addWidget(self.neo_wrapper)
        
        from steempeg.ui.render_panel import (
            restyle_video_page,
            restyle_audio_page,
            restyle_source_page,
            restyle_export_page,
            restyle_presets_page,
        )
        restyle_video_page(self.ui)
        restyle_audio_page(self.ui)
        restyle_source_page(self.ui)
        restyle_export_page(self.ui)
        restyle_presets_page(self.ui, self)

        # Give each render combo its OWN stylesheet so the field text matches the
        # Source Info value labels (Segoe UI, 14px, bold) instead of the app default.
        if hasattr(self.ui, 'settings_tabs'):
            from PySide6.QtWidgets import QComboBox as _QComboBox
            _combo_qss = settings_panel_stylesheet(
                "QComboBox { font-family: " + tok.FONT_APP + ";"
                " font-size: 13px; font-weight: bold; }"
            )
            for _combo in self.ui.settings_tabs.findChildren(_QComboBox):
                _combo.setStyleSheet(_combo_qss)
                apply_dark_combo_popup(_combo)
        # Collapse non-active settings pages so the scroll area fits the visible page
        if hasattr(self, 'fit_settings_tab_to_page'):
            self.fit_settings_tab_to_page()
        if hasattr(self, 'populate_output_format_combos'):
            self.populate_output_format_combos()
        # Update the bitrate list when changing resolution
        if hasattr(self.ui, 'combo_quality'):
            self.ui.combo_quality.currentTextChanged.connect(self.update_bitrate_options) 
        
        # 4. BINDING BUTTONS TO FUNCTIONS
        # --- UI INJECTION: COPY BUTTONS ---
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget, QSizePolicy
        
        copy_icon_path = get_resource_path("copyfile.png")

        # 1. Source paths now render as per-directory rows with their own copy buttons
        #    (SourcePathsBox in render_panel) — no single wrapper button needed here.

        # 2. Copy button on the output path row (Export tab)
        if hasattr(self.ui, 'output_path_row'):
            path_row = self.ui.output_path_row
            path_layout = path_row.layout()
            if path_layout is not None and not hasattr(self, 'btn_copy_loc'):
                if hasattr(self.ui, 'label_location') and not isinstance(
                    self.ui.label_location, ElidedLabel
                ):
                    smart_label = ElidedLabel()
                    smart_label.setStyleSheet(self.ui.label_location.styleSheet())
                    smart_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                    old = self.ui.label_location
                    path_layout.replaceWidget(old, smart_label)
                    old.deleteLater()
                    self.ui.label_location = smart_label

                self.btn_copy_loc = QPushButton()
                self.btn_copy_loc.setFixedSize(22, 22)
                self.btn_copy_loc.setToolTip("Copy output path")
                self.btn_copy_loc.setStyleSheet(
                    "QPushButton { background: transparent; border: none; border-radius: 6px; }"
                    " QPushButton:hover { background: rgba(255, 255, 255, 28); }"
                )
                self.btn_copy_loc.setCursor(Qt.PointingHandCursor)

                if os.path.exists(copy_icon_path):
                    self.btn_copy_loc.setIcon(QIcon(copy_icon_path))
                else:
                    self.btn_copy_loc.setText("📋")

                self.btn_copy_loc.clicked.connect(
                    lambda: QApplication.clipboard().setText(
                        getattr(self, 'current_output_file', "")
                    )
                )
                path_layout.addWidget(self.btn_copy_loc, 0, Qt.AlignVCenter)

        # --- UI INJECTION: REFRESH BUTTON ---
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QSizePolicy
        
        # --- CIRCLE AND BUTTON STYLES ---
        pill_style = f"""
            QFrame {{ 
                background-color: #2d2d2d; 
                border-radius: 16px; 
                border: 1px solid #383838;
                font-family: {tok.FONT_APP};
            }}
        """
        
        unified_table_style = """
            QPushButton { 
                background-color: #383838; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 14px; 
                font-family: <<FONT>>;
                font-weight: bold; 
                font-size: 13px; 
                padding: 4px 12px; 
                min-height: 24px;
                outline: none;
            }
            QPushButton:hover { background-color: #404040; border: 2px solid #6b5a8e; }
            QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
            QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
            QPushButton:focus, QPushButton:default {
                background-color: #383838; color: #ffffff; border: 2px solid #444444; outline: none;
            }
            QPushButton::menu-indicator { image: none; }
        """.replace("<<FONT>>", tok.FONT_APP)

        # 1. CREATE ONE COMMON MEGA-CAPSULATE
        mega_pill = QFrame()
        self._footer_mega_pill = mega_pill
        mega_pill.setStyleSheet(pill_style)
        mega_layout = QVBoxLayout(mega_pill)
        mega_layout.setContentsMargins(6, 6, 6, 6) # Slightly increased the margins from the edges of the circle
        mega_layout.setSpacing(4) # Distance between floors
        self._footer_mega_layout = mega_layout
        self._footer_unified_style = unified_table_style

        #2. CREATE TWO FLOORS INSIDE THE CAPSULE
        top_row = QHBoxLayout()
        top_row.setSpacing(4) # Distance between buttons
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)
        
        mega_layout.addLayout(top_row)
        mega_layout.addLayout(bottom_row)

        #3. PUT THE MEGA-CAPSULE ON THE VERY TOP (INSTEAD OF THE OLD FOLDER BUTTON)
        from steempeg.ui.widgets.folder_picker_button import FolderPickerButton
        from steempeg.ui.widgets.refresh_button import RefreshButton

        old_browse_btn = self.ui.btn_browse
        if old_browse_btn.parentWidget() and old_browse_btn.parentWidget().layout():
            old_browse_btn.parentWidget().layout().replaceWidget(old_browse_btn, mega_pill)
        # replaceWidget orphans the original button but leaves it parented/visible in the
        # left panel — hide it so it doesn't float as a phantom "Choose Folder" up top.
        old_browse_btn.hide()
        old_browse_btn.setParent(None)
        old_browse_btn.deleteLater()

        self.folder_picker = FolderPickerButton()
            
        self.btn_refresh = RefreshButton()
        
        #4. TEAR ABOUT AND UPDATE FROM THEIR OLD PLACES
        btn_about = getattr(self.ui, 'btn_about', None)
        btn_update = getattr(self.ui, 'btn_update_check', None)
        
        if btn_about and btn_about.parentWidget() and btn_about.parentWidget().layout():
            btn_about.parentWidget().layout().removeWidget(btn_about)
        if btn_update and btn_update.parentWidget() and btn_update.parentWidget().layout():
            btn_update.parentWidget().layout().removeWidget(btn_update)

        from steempeg.ui.ui_density import settings_button_label
        from steempeg.ui.ui_density import density_for_width

        btn_settings = QPushButton(settings_button_label(density_for_width(self.ui.width(), widget=self.ui)))
        btn_settings.setObjectName("btn_settings")
        self.ui.btn_settings = btn_settings
            
        # 5. Color the buttons and add cursors
        if btn_about:
            self._apply_library_footer_button(btn_about, unified_table_style)
        if btn_update:
            self._apply_library_footer_button(btn_update, unified_table_style)
        self._apply_library_footer_button(btn_settings, unified_table_style)
            
        # 6. LAY OUT THE BUTTONS BY FLOORS (About · Updates · Settings)
        top_row.addWidget(self.folder_picker, 7)
        top_row.addWidget(self.btn_refresh, 3)
        
        if btn_about: bottom_row.addWidget(btn_about, 1)
        if btn_update: bottom_row.addWidget(btn_update, 1)
        bottom_row.addWidget(btn_settings, 1)

        # Dev Mode button (hidden unless dev_mode is true in settings.json)
        btn_dev = QPushButton("Dev")
        btn_dev.setObjectName("btn_dev")
        btn_dev.setToolTip("Developer Tools")
        self._apply_library_footer_button(btn_dev, unified_table_style)
        btn_dev.setVisible(False)
        self.ui.btn_dev = btn_dev
        bottom_row.addWidget(btn_dev, 1)
        self._refresh_dev_button_visibility()

        # 7. RECOVERING SIGNALS (Presses)
        self.btn_refresh.main_btn.clicked.connect(self.refresh_library)
        if hasattr(self, "setup_refresh_menu"):
            self.setup_refresh_menu()
        # Folder button is rewired by `_sync_library_footer_for_mode` per tab.
        self.folder_picker.main_btn.clicked.connect(self.choose_folder)
        self.folder_picker.add_btn.clicked.connect(self.show_folders_panel)
        if hasattr(self, "_sync_library_footer_for_mode"):
            self._sync_library_footer_for_mode()
        if hasattr(self.ui, 'destination_button'):
            self.ui.destination_button.clicked.connect(self.choose_destination)
        if btn_about: btn_about.clicked.connect(self.show_about_dialog)
        if btn_update: btn_update.clicked.connect(self.check_for_updates)
        btn_settings.clicked.connect(self.show_settings_dialog)
        btn_dev.clicked.connect(self.show_dev_dialog)
        if hasattr(self, "_wire_title_bar_about_updates"):
            self._wire_title_bar_about_updates()
        self.ui.btn_start.clicked.connect(self.start_render_thread)
        self.ui.btn_start.setEnabled(False)



        try:
            import PySide6.QtWidgets as qtw
            import PySide6.QtCore as qtc

            # 1. OUR ORIGINAL, BEAUTIFUL STYLES

            # Logs / Start / Pause / Cancel — density reapplies font + padding later.
            self._dash_btn_style_logs = (
                "QPushButton {{ font-family: <<FONT>>; "
                "font-size: {font}px; font-weight: bold; background-color: #383838; color: #ffffff; "
                "border: 2px solid #444444; border-radius: {radius}px; padding: {pad}; }}"
                "QPushButton:hover {{ background-color: #404040; border: 2px solid #6b5a8e; }}"
                "QPushButton:pressed {{ background-color: #3a324a; border: 2px solid #b29ae7; }}"
                "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
                "QPushButton::menu-indicator {{ image: none; }}"
            )
            self._dash_btn_style_start = (
                "QPushButton {{ font-family: <<FONT>>; "
                "font-size: {font}px; font-weight: bold; background-color: #2e6b32; color: #ffffff; "
                "border: 2px solid #3e8e41; border-radius: {radius}px; padding: {pad}; }}"
                "QPushButton:hover {{ background-color: #3e8e41; border: 2px solid #57c75b; }}"
                "QPushButton:pressed {{ background-color: #235226; border: 2px solid #3e8e41; }}"
                "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
            )
            self._dash_btn_style_pause = (
                "QPushButton {{ font-family: <<FONT>>; "
                "font-size: {font}px; font-weight: bold; background-color: #8c7314; color: #ffffff; "
                "border: 2px solid #a88b11; border-radius: {radius}px; padding: {pad}; }}"
                "QPushButton:hover {{ background-color: #a88b11; border: 2px solid #c9a716; }}"
                "QPushButton:pressed {{ background-color: #6b570d; border: 2px solid #a88b11; }}"
                "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
                "QPushButton::menu-indicator {{ image: none; }}"
            )
            self._dash_btn_style_cancel = (
                "QPushButton {{ font-family: <<FONT>>; "
                "font-size: {font}px; font-weight: bold; background-color: #8a2525; color: #ffffff; "
                "border: 2px solid #a82e2e; border-radius: {radius}px; padding: {pad}; }}"
                "QPushButton:hover {{ background-color: #a82e2e; border: 2px solid #cc3939; }}"
                "QPushButton:pressed {{ background-color: #661a1a; border: 2px solid #a82e2e; }}"
                "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
                "QPushButton::menu-indicator {{ image: none; }}"
            )
            self._dash_btn_style_render_settings = (
                "QPushButton {{ font-family: <<FONT>>; "
                "font-size: {font}px; font-weight: bold; background-color: #5a4b7a; color: #ffffff; "
                "border: 2px solid #8e7cc3; border-radius: {radius}px; padding: {pad}; }}"
                "QPushButton:hover {{ background-color: #6b5a8e; border: 2px solid #b29ae7; }}"
                "QPushButton:pressed {{ background-color: #3a324a; border: 2px solid #8e7cc3; }}"
                "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
            )

            # FORCE INJECT STYLES DIRECTLY INTO BUTTONS
            if hasattr(self.ui, 'btn_start'): 
                self.ui.btn_start.setStyleSheet(self._fmt_dash_btn(self._dash_btn_style_start))
                self.ui.btn_start.setMinimumSize(0, 0)
            elif hasattr(self.ui, 'btn_render'): 
                self.ui.btn_render.setStyleSheet(self._fmt_dash_btn(self._dash_btn_style_start))
                
            if hasattr(self.ui, 'btn_pause'): 
                self.ui.btn_pause.setStyleSheet(self._fmt_dash_btn(self._dash_btn_style_pause))
                self.ui.btn_pause.setMinimumSize(0, 0)
                
            if hasattr(self.ui, 'btn_cancel'): 
                self.ui.btn_cancel.setStyleSheet(self._fmt_dash_btn(self._dash_btn_style_cancel))
                self.ui.btn_cancel.setMinimumSize(0, 0)

            if hasattr(self, "_apply_desktop_dash_render_icons"):
                self._apply_desktop_dash_render_icons()
            if hasattr(self, "_update_start_button_label"):
                self._update_start_button_label()
                
            if hasattr(self.ui, 'btn_logs'): 
                self.ui.btn_logs.setStyleSheet(self._fmt_dash_btn(self._dash_btn_style_logs))
                self.ui.btn_logs.setMinimumSize(0, 0)

            # 2. Remove Padding from the Parent Element for Perfect Width Symmetry
            parent_widget = self.ui.btn_start.parentWidget() if hasattr(self.ui, 'btn_start') else None
            if parent_widget:
                parent_widget.setStyleSheet("background: transparent; border: none;")
                if parent_widget.layout():
                    # Resetting the outer margins so that the monolith aligns perfectly with the width of the top tabs.
                    parent_widget.layout().setContentsMargins(0, 0, 0, 0)

            # 3. Creating Our Single Monolithic Circle
            self.render_dashboard = qtw.QFrame()
            self.render_dashboard.setObjectName("renderDashboard")
            from steempeg.ui import ui_theme as ut
            self.render_dashboard.setStyleSheet(
                ut.elevated_panel_stylesheet(object_name="renderDashboard")
                + " QFrame#renderDashboard QLabel { border: none; background: transparent; }"
            )
            
            dash_layout = qtw.QVBoxLayout(self.render_dashboard)
            dash_layout.setContentsMargins(18, 16, 18, 16)
            dash_layout.setSpacing(12)

            _status_font = "font-family: " + tok.FONT_APP + ";"

            header_block = qtw.QVBoxLayout()
            header_block.setSpacing(12)
            self._dash_header_block = header_block

            top_row = qtw.QHBoxLayout()
            top_row.setSpacing(4)

            if hasattr(self.ui, 'label_short_summary'):
                self.ui.label_short_summary.hide()

                summary_left = qtw.QWidget()
                summary_left_layout = qtw.QHBoxLayout(summary_left)
                summary_left_layout.setContentsMargins(0, 0, 0, 2)
                summary_left_layout.setSpacing(8)

                self.bottom_icon_label = qtw.QLabel()
                self.bottom_icon_label.setFixedSize(24, 24)

                self.bottom_text_label = ElidedLabel()
                self.bottom_text_label.setStyleSheet(
                    f"color: #e0e0e0; font-size: 14px; font-weight: bold; {_status_font}"
                )
                self.bottom_text_label.setMinimumWidth(0)
                self.bottom_text_label.setSizePolicy(
                    qtw.QSizePolicy.Policy.Expanding, qtw.QSizePolicy.Policy.Preferred
                )

                summary_left_layout.addWidget(self.bottom_icon_label, 0, qtc.Qt.AlignVCenter)
                summary_left_layout.addWidget(self.bottom_text_label, 1, qtc.Qt.AlignVCenter)
                summary_left.setMinimumWidth(0)
                summary_left.setSizePolicy(
                    qtw.QSizePolicy.Policy.Expanding, qtw.QSizePolicy.Policy.Preferred
                )
                top_row.addWidget(summary_left, 1, qtc.Qt.AlignVCenter)

                def reset_bottom_summary():
                    # Prefer setPixmap in a square slot — CSS ``image:`` stretches
                    # into whatever geometry the label has (ovals on HD layouts).
                    from PySide6.QtGui import QPixmap
                    from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap
                    from steempeg.ui.icon_utils import apply_square_icon, app_logo_pixmap

                    unknown = get_resource_path("unknown_icon.png")
                    unknown_pix = shaped_game_icon_pixmap(QPixmap(unknown), 24, ICON_SHAPE_CIRCLE)
                    self.bottom_icon_label.setStyleSheet("background: transparent; border: none;")
                    apply_square_icon(self.bottom_icon_label, unknown_pix, 24)
                    self.bottom_text_label.setText("Select a clip to continue...")

                    if hasattr(self, 'custom_icon_label') and hasattr(self, 'custom_text_label'):
                        self.custom_icon_label.setStyleSheet("background: transparent; border: none;")
                        from steempeg.ui.player_header_layout import (
                            player_header_icon_px,
                            set_player_header_game_text,
                        )

                        hdr_px = player_header_icon_px(self)
                        hdr_pix = shaped_game_icon_pixmap(
                            QPixmap(unknown), hdr_px, ICON_SHAPE_CIRCLE
                        )
                        apply_square_icon(self.custom_icon_label, hdr_pix, hdr_px)
                        set_player_header_game_text(
                            self,
                            "Choose a clip to preview...",
                            placeholder=True,
                        )

                    if hasattr(self, 'place_logo') and hasattr(self, 'place_text'):
                        self.place_logo.setStyleSheet("background: transparent; border: none;")
                        apply_square_icon(self.place_logo, app_logo_pixmap(80, dpr=1.0), 80)
                        self.place_text.setText("Please select a clip from the library")
                        self.place_text.setStyleSheet("color: #888888; font-size: 14px; font-weight: bold; margin-top: 15px;")

                self.reset_bottom_summary = reset_bottom_summary
                self.reset_bottom_summary()

            _PCT_COL_WIDTH = 40
            _STATUS_ROW_H = 24
            _STATUS_DOT_SIZE = 12

            self.status_dot = qtw.QLabel()
            self.status_dot.setFixedSize(_STATUS_DOT_SIZE, _STATUS_DOT_SIZE)
            self.status_dot.setAlignment(qtc.Qt.AlignCenter)
            self.status_dot.setStyleSheet(
                f"background-color: #4CAF50; border-radius: {_STATUS_DOT_SIZE // 2}px;"
            )

            # Dot sits in the same 40px column as "0%" so they stack vertically.
            dot_col = qtw.QWidget()
            dot_col.setFixedSize(_PCT_COL_WIDTH, _STATUS_ROW_H)
            dot_col_layout = qtw.QHBoxLayout(dot_col)
            dot_col_layout.setContentsMargins(0, 0, 0, 0)
            dot_col_layout.setSpacing(0)
            dot_col_layout.addStretch()
            dot_col_layout.addWidget(self.status_dot, 0, qtc.Qt.AlignCenter)
            dot_col_layout.addStretch()

            ready_cluster = qtw.QWidget()
            ready_cluster.setFixedHeight(_STATUS_ROW_H)
            ready_cluster_layout = qtw.QHBoxLayout(ready_cluster)
            ready_cluster_layout.setContentsMargins(0, 0, 0, 0)
            ready_cluster_layout.setSpacing(4)

            if hasattr(self.ui, 'label_status'):
                status_label = qtw.QLabel("Ready", ready_cluster)
                status_label.setObjectName("label_status")
                status_label.setStyleSheet(
                    f"background: transparent; border: none; font-size: 14px; font-weight: bold; {_status_font}"
                )
                status_label.setAlignment(qtc.Qt.AlignRight | qtc.Qt.AlignVCenter)
                status_label.setMinimumWidth(120)
                status_label.setMaximumWidth(280)
                self.ui.label_status.deleteLater()
                self.ui.label_status = status_label
                ready_cluster_layout.addWidget(status_label, 0, qtc.Qt.AlignVCenter)

            ready_cluster_layout.addWidget(dot_col, 0, qtc.Qt.AlignVCenter)
            top_row.addWidget(ready_cluster, 0, qtc.Qt.AlignVCenter)

            header_block.addLayout(top_row)

            progress_row = qtw.QHBoxLayout()
            progress_row.setSpacing(8)

            if hasattr(self.ui, 'progress_render'):
                bar = self._install_animated_render_bar(self.render_dashboard)
                progress_row.addWidget(bar, 1)

            if not hasattr(self, 'label_pct'):
                self.label_pct = qtw.QLabel("0%")
            self.label_pct.setFixedWidth(_PCT_COL_WIDTH)
            self.label_pct.setAlignment(qtc.Qt.AlignHCenter | qtc.Qt.AlignVCenter)
            self.label_pct.setStyleSheet(
                f"color: #ffffff; font-weight: bold; font-size: 13px; {_status_font}"
            )
            progress_row.addWidget(self.label_pct, 0)

            header_block.addLayout(progress_row)
            dash_layout.addLayout(header_block)

            # BOTTOM ROW: PERFECTLY ALIGNED, FULL-WIDTH BUTTONS
            btn_row = qtw.QHBoxLayout()
            btn_row.setContentsMargins(0, 0, 0, 0)
            btn_row.setSpacing(12)
            self._dash_btn_row = btn_row
            
            # Strict Sequence — Start, optional Render Settings (Like a Portable), Pause…
            buttons_queue = ['btn_start', 'btn_pause', 'btn_cancel', 'btn_logs']
            
            for btn_name in buttons_queue:
                if hasattr(self.ui, btn_name):
                    btn = getattr(self.ui, btn_name)
                    btn.setSizePolicy(qtw.QSizePolicy.Expanding, qtw.QSizePolicy.Fixed)
                    btn.setMinimumHeight(36) 
                    

                    # 1. Take the old button style
                    old_style = btn.styleSheet()
                    
                    # 2. Hardcode the 13px font, just like on the Refresh button!
                    btn.setStyleSheet(old_style + "\nQPushButton { font-family: " + tok.FONT_APP + "; font-size: 13px; font-weight: bold; }")
                    
                    btn_row.addWidget(btn)
                    if btn_name == "btn_start" and not getattr(self, "_portable_shell", False):
                        self._ensure_dash_render_settings_button()
                        settings_btn = getattr(self, "btn_render_settings", None)
                        if settings_btn is not None:
                            btn_row.addWidget(settings_btn)

            dash_layout.addLayout(btn_row)

            # 4. Container Assembly
            if parent_widget and parent_widget.layout():
                pl = parent_widget.layout()
                pl.setContentsMargins(0, 0, 0, 0)
                pl.setSpacing(0)
                pl.addWidget(self.render_dashboard)

            if hasattr(self, 'update_status_indicator'):
                self.update_status_indicator("Ready", "ready")
            if hasattr(self, "apply_desktop_render_layout"):
                self.apply_desktop_render_layout()

        except Exception as e:
            print(f"Error building ultimate monolithic dashboard: {e}")
        
        
        # --- FIXING THE INTERFACE AND PLAYER ---
        # 1. Give the right panel some breathing room
        from steempeg.ui.layout_defaults import (
            RIGHT_PANEL_BOTTOM_INSET,
            RIGHT_PANEL_SIDE_INSET,
        )

        right_layout = self.ui.right_panel.layout()
        if right_layout:
            # Side/bottom inset; top inset lives on the player wrap so the queue tab
            # can align with Clips Manager without losing player breathing room.
            right_layout.setContentsMargins(
                RIGHT_PANEL_SIDE_INSET, 0, 0, RIGHT_PANEL_BOTTOM_INSET,
            )
            right_layout.setSpacing(8)

        # 2: Taming MPV Player and creating a Border Wrapper
        from PySide6.QtWidgets import QFrame, QStackedLayout, QVBoxLayout, QLabel, QSizePolicy
        from steempeg.ui import ui_theme as ut

        # --- 1. FAKE BLACK BACKGROUND (Fills the entire space) ---
        self.video_wrapper = QFrame()
        self.video_wrapper.setObjectName("playerVideoWrapper")
        self.video_wrapper.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.video_wrapper.setStyleSheet(ut.player_video_wrapper_stylesheet())
        self.video_wrapper.installEventFilter(self)
        
        parent_layout = self.ui.video_container.parentWidget().layout()
        parent_layout.replaceWidget(self.ui.video_container, self.video_wrapper)
        
        # A layout that keeps the actual video strictly centered
        wrapper_layout = QVBoxLayout(self.video_wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- 2. LIVE VIDEO CONTAINER (Strictly 16:9) ---
        self.aspect_frame = QFrame()
        # Default 3px transparent border to prevent video flickering during cropping.
        self.aspect_frame.setStyleSheet("background-color: #000000; border: none; border-radius: 0px;")
        wrapper_layout.addWidget(self.aspect_frame)
        
        # 3. STACK WITH PLAYER AND PLUG
        self.video_stack = QStackedLayout(self.aspect_frame)
        self.video_stack.setContentsMargins(3, 3, 3, 3) # Offset to avoid hitting the frame
        
        # The Real Player
        self.ui.video_container.setStyleSheet("background-color: transparent; border: none;")
        self.video_stack.addWidget(self.ui.video_container)
        
        # Placeholder canvas (near-black) + centered info chip for logo/text.
        self.placeholder_frame = QFrame()
        self.placeholder_frame.setStyleSheet(ut.player_placeholder_canvas_stylesheet())
        self.placeholder_frame.setObjectName("playerPlaceholderCanvas")
        place_layout = QVBoxLayout(self.placeholder_frame)
        place_layout.setContentsMargins(24, 24, 24, 24)
        place_layout.setAlignment(Qt.AlignCenter)

        self.place_card = QFrame()
        self.place_card.setObjectName("playerPlaceholderCard")
        self.place_card.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self.place_card.setStyleSheet(ut.player_placeholder_card_stylesheet())
        card_lay = QVBoxLayout(self.place_card)
        card_lay.setContentsMargins(28, 22, 28, 22)
        card_lay.setSpacing(12)
        card_lay.setAlignment(Qt.AlignCenter)

        self.place_logo = QLabel()
        from steempeg.ui.icon_utils import apply_square_icon, app_logo_pixmap

        apply_square_icon(self.place_logo, app_logo_pixmap(80, dpr=1.0), 80)

        self.place_text = QLabel("Please select a clip from the library")
        self.place_text.setStyleSheet(
            "color: #888888; font-size: 14px; font-weight: bold;"
        )
        self.place_text.setAlignment(Qt.AlignCenter)

        card_lay.addWidget(self.place_logo, 0, Qt.AlignCenter)
        card_lay.addWidget(self.place_text, 0, Qt.AlignCenter)
        place_layout.addWidget(self.place_card, 0, Qt.AlignCenter)
        self.video_stack.addWidget(self.placeholder_frame)

        # A plain black page shown only during the brief load gap (between selecting a
        # clip and mpv's first decoded frame). It hides the native mpv surface so a
        # stale/last frame can't flash, WITHOUT exposing the "Ready to play" poster.
        self.video_blank_frame = QFrame()
        self.video_blank_frame.setStyleSheet("QFrame { background-color: #000000; border: none; }")
        self.video_stack.addWidget(self.video_blank_frame)

        # When starting, show MAP 2 (Stub)
        self.video_stack.setCurrentWidget(self.placeholder_frame)

        # --- CREATE A TOP PANEL  ---
        # Title cluster: icon + game name + info chip. SteempegUI = left;
        # Steam-like = centered via spacers. Status/actions stay right.
        # Portable injects "| Choose a Clip" after the title cluster only.
        from PySide6.QtCore import QEvent, QObject
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget
        from steempeg.ui.design_tokens import with_tooltip_style

        self.player_header_frame = QFrame()
        self.player_header_frame.setObjectName("playerHeaderFrame")
        self.player_header_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.player_header_frame.setStyleSheet(ut.player_header_stylesheet())
        from steempeg.ui.ui_density import COMFORT as _HDR_COMFORT

        from steempeg.ui.layout_defaults import (
            PLAYER_HEADER_CANVAS_GAP,
            PLAYER_HEADER_FRAME_BORDER_V,
        )

        # Fixed height = filled header (chips + pads) + painted canvas gap + QSS
        # border room; empty placeholder must match.
        _hdr_min_h = max(
            int(_HDR_COMFORT.header_chip) + 2 * int(_HDR_COMFORT.header_pad_v),
            int(_HDR_COMFORT.header_min_h),
            int(_HDR_COMFORT.header_icon) + 2 * int(_HDR_COMFORT.header_pad_v),
        ) + PLAYER_HEADER_CANVAS_GAP + int(PLAYER_HEADER_FRAME_BORDER_V)
        self.player_header_frame.setFixedHeight(_hdr_min_h)
        self.player_header_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        header_layout = QHBoxLayout(self.player_header_frame)
        header_layout.setContentsMargins(
            int(_HDR_COMFORT.header_pad_h),
            int(_HDR_COMFORT.header_pad_v),
            int(_HDR_COMFORT.header_pad_h),
            int(_HDR_COMFORT.header_pad_v) + PLAYER_HEADER_CANVAS_GAP,
        )
        header_layout.setSpacing(max(6, int(_HDR_COMFORT.header_pad_h)))

        self.player_header_title = QWidget()
        self.player_header_title.setObjectName("playerHeaderTitle")
        self.player_header_title.setMinimumHeight(
            max(int(_HDR_COMFORT.header_icon), int(_HDR_COMFORT.header_chip))
        )
        title_row = QHBoxLayout(self.player_header_title)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        self.custom_icon_label = QLabel()
        from PySide6.QtGui import QPixmap
        from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap
        from steempeg.ui.icon_utils import apply_square_icon

        _hdr_icon = int(_HDR_COMFORT.header_icon)
        apply_square_icon(
            self.custom_icon_label,
            shaped_game_icon_pixmap(
                QPixmap(get_resource_path("unknown_icon.png")), _hdr_icon, ICON_SHAPE_CIRCLE
            ),
            _hdr_icon,
        )

        self.custom_text_label = QLabel("Select a clip to preview...")
        self.custom_text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.custom_text_label.setTextFormat(Qt.TextFormat.RichText)
        from steempeg.ui import design_tokens as _hdr_tok
        from steempeg.ui.player_header_layout import player_header_title_qfont

        _hdr_font_px = int(_HDR_COMFORT.header_font)
        self.custom_text_label.setFont(player_header_title_qfont(_hdr_font_px))
        self.custom_text_label.setStyleSheet(
            f"color: white; font-size: {_hdr_font_px}px; font-weight: 700;"
            f"font-family: {_hdr_tok.FONT_APP};"
            "background: transparent; border: none;"
        )

        from steempeg.ui.icon_assets import playinfo_icons

        # Match title-bar About/Settings: glyph in a circular hover hitbox.
        _INFO_HIT = max(20, int(_HDR_COMFORT.header_chip) - 8)
        _INFO_ICON = max(14, int(_HDR_COMFORT.header_chip_icon))
        _INFO_HIT_R = _INFO_HIT // 2
        self._player_header_info_icon_idle, self._player_header_info_icon_hot = playinfo_icons(
            _INFO_ICON
        )
        self.btn_player_header_info = QPushButton()
        self.btn_player_header_info.setObjectName("playerHeaderInfo")
        self.btn_player_header_info.setFixedSize(_INFO_HIT, _INFO_HIT)
        self.btn_player_header_info.setIcon(self._player_header_info_icon_idle)
        self.btn_player_header_info.setIconSize(QSize(_INFO_ICON, _INFO_ICON))
        self.btn_player_header_info.setFlat(True)
        self.btn_player_header_info.setCursor(Qt.PointingHandCursor)
        self.btn_player_header_info.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_player_header_info.setAccessibleName("Clip info")
        self.btn_player_header_info.setToolTip("No clip selected")
        self.btn_player_header_info.setEnabled(False)
        # Hidden until a clip is open — empty header shows placeholder text only.
        self.btn_player_header_info.hide()
        self.btn_player_header_info.clicked.connect(self.show_player_header_clip_info_popup)
        self.btn_player_header_info.setStyleSheet(with_tooltip_style(
            "QPushButton#playerHeaderInfo {"
            "background: transparent;"
            "border: none;"
            "padding: 0px;"
            "margin: 0px;"
            "text-align: center;"
            "}"
            "QPushButton#playerHeaderInfo:hover {"
            f"background-color: rgba(255, 255, 255, 0.08);"
            f"border-radius: {_INFO_HIT_R}px;"
            "}"
            "QPushButton#playerHeaderInfo:pressed {"
            f"background-color: rgba(255, 255, 255, 0.12);"
            f"border-radius: {_INFO_HIT_R}px;"
            "}"
            "QPushButton#playerHeaderInfo:disabled {"
            "background-color: transparent;"
            "}"
        ))

        class _HeaderInfoHoverFilter(QObject):
            def eventFilter(self, obj, event):
                owner = self.parent()
                et = event.type()
                if et == QEvent.Type.Enter:
                    if owner is not None and hasattr(owner, "refresh_player_header_info"):
                        owner.refresh_player_header_info()
                btn = getattr(owner, "btn_player_header_info", None) if owner else None
                idle = getattr(owner, "_player_header_info_icon_idle", None) if owner else None
                hot = getattr(owner, "_player_header_info_icon_hot", None) if owner else None
                if (
                    btn is not None
                    and obj is btn
                    and idle is not None
                    and hot is not None
                    and btn.isEnabled()
                ):
                    if et in (QEvent.Type.Enter, QEvent.Type.MouseButtonPress):
                        btn.setIcon(hot)
                    elif et == QEvent.Type.Leave:
                        btn.setIcon(idle)
                    elif et == QEvent.Type.MouseButtonRelease:
                        btn.setIcon(hot if btn.underMouse() else idle)
                return False

        self._header_info_hover_filter = _HeaderInfoHoverFilter(self)
        self.btn_player_header_info.installEventFilter(self._header_info_hover_filter)

        title_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.custom_icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.custom_text_label, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.btn_player_header_info, 0, Qt.AlignmentFlag.AlignVCenter)

        from steempeg.ui.player_header_layout import (
            apply_player_header_layout,
            ensure_header_spacers,
            set_player_header_game_text,
        )

        left_sp, right_sp = ensure_header_spacers(self)
        header_layout.addWidget(left_sp)
        header_layout.addWidget(self.player_header_title)
        header_layout.addWidget(right_sp)
        set_player_header_game_text(
            self,
            "Select a clip to preview...",
            placeholder=True,
        )
        apply_player_header_layout(self)

        # Status chips (health + preview badge) | action chips (close, later: preview settings).
        self.player_header_status = QWidget()
        status_row = QHBoxLayout(self.player_header_status)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)

        self.btn_clip_health = QPushButton()
        self.btn_clip_health.setCursor(Qt.PointingHandCursor)
        self.btn_clip_health.hide()
        self.btn_clip_health.clicked.connect(self.show_clip_health_menu)
        status_row.addWidget(self.btn_clip_health)

        # Chip (not plain QLabel) so In queue can show the same queue.png as portable.
        self.label_playback_badge = QPushButton()
        self.label_playback_badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.label_playback_badge.setCursor(Qt.CursorShape.ArrowCursor)
        self.label_playback_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.label_playback_badge.hide()
        status_row.addWidget(self.label_playback_badge)

        self.player_header_divider = QFrame()
        self.player_header_divider.setFrameShape(QFrame.Shape.VLine)
        self.player_header_divider.setFixedWidth(1)
        self.player_header_divider.setStyleSheet(
            "color: #555555; background-color: #555555; margin: 4px 2px;"
        )
        self.player_header_divider.hide()

        self.player_header_actions = QWidget()
        actions_row = QHBoxLayout(self.player_header_actions)
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(6)

        from steempeg.ui.icon_assets import close_clip_icon, preview_settings_icon

        _HEADER_ACTION_CHIP = int(_HDR_COMFORT.header_chip)
        _HEADER_ACTION_ICON = int(_HDR_COMFORT.header_chip_icon)
        _HEADER_CHIP = (
            "border-radius: 8px;"
            "padding: 0px;"
            "font-family: " + tok.FONT_APP + ";"
        )

        self.btn_preview_settings = QPushButton()
        self.btn_preview_settings.setFixedSize(_HEADER_ACTION_CHIP, _HEADER_ACTION_CHIP)
        self.btn_preview_settings.setIcon(preview_settings_icon(_HEADER_ACTION_ICON))
        self.btn_preview_settings.setIconSize(QSize(_HEADER_ACTION_ICON, _HEADER_ACTION_ICON))
        self.btn_preview_settings.setCursor(Qt.PointingHandCursor)
        self.btn_preview_settings.setToolTip("Preview quality")
        self.btn_preview_settings.setStyleSheet(
            "QPushButton {"
            "background-color: rgba(74, 159, 216, 0.18);"
            "color: #4a9fd8;"
            "border: 2px solid #4a9fd8;"
            + _HEADER_CHIP +
            "}"
            "QPushButton:hover { background-color: rgba(74, 159, 216, 0.32); }"
            "QPushButton:pressed { background-color: rgba(74, 159, 216, 0.45); }"
        )
        self.btn_preview_settings.clicked.connect(self.show_preview_quality_menu)
        actions_row.addWidget(self.btn_preview_settings)

        self.btn_close_clip = QPushButton()
        self.btn_close_clip.setFixedSize(_HEADER_ACTION_CHIP, _HEADER_ACTION_CHIP)
        self.btn_close_clip.setIcon(close_clip_icon(_HEADER_ACTION_ICON))
        self.btn_close_clip.setIconSize(QSize(_HEADER_ACTION_ICON, _HEADER_ACTION_ICON))
        self.btn_close_clip.setCursor(Qt.PointingHandCursor)
        self.btn_close_clip.setToolTip("Close clip")
        self.btn_close_clip.setStyleSheet(
            "QPushButton {"
            "background-color: rgba(224, 85, 85, 0.18);"
            "color: #e05555;"
            "border: 2px solid #e05555;"
            + _HEADER_CHIP +
            "}"
            "QPushButton:hover { background-color: rgba(224, 85, 85, 0.32); }"
            "QPushButton:pressed { background-color: rgba(224, 85, 85, 0.45); }"
        )
        self.btn_close_clip.clicked.connect(self.close_current_clip)
        actions_row.addWidget(self.btn_close_clip)
        self.player_header_actions.hide()

        header_layout.addWidget(self.player_header_status)
        header_layout.addWidget(self.player_header_divider)
        header_layout.addWidget(self.player_header_actions)
        # Status/actions exist now — re-apply so Steam-like dock mirror + sync
        # filters attach to the right dock (first apply ran before these).
        apply_player_header_layout(self)

        right_layout = self.ui.right_panel.layout()
        if right_layout:
            right_layout.insertWidget(0, self.player_header_frame)
            
        # Hide old labels from Qt Designer
        if hasattr(self.ui, 'label_player_header'):
            self.ui.label_player_header.hide()
        if hasattr(self.ui, 'label_player_icon'):
            self.ui.label_player_icon.hide()


        self.ui.right_panel.setStyleSheet(_PLAYER_SLIDER_QSS)

        # --- SETTING UP BUTTON ICONS ---
        #1: Erase old text
        self.ui.btn_play.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ui.btn_skip_back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ui.btn_skip_forward.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.ui.btn_play.setText("")
        self.ui.btn_skip_back.setText("")
        self.ui.btn_skip_forward.setText("")

        # 2. Assign start images (pay attention to the exact file names!)
        self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))
        self.ui.btn_skip_back.setIcon(QIcon(get_resource_path("less15.png")))
        self.ui.btn_skip_forward.setIcon(QIcon(get_resource_path("more15.png")))
        
        # 3. Make them larger so that all the beauty is clearly visible (you can play with the numbers 32, 32)
        self.ui.btn_play.setIconSize(QSize(32, 32))
        self.ui.btn_skip_back.setIconSize(QSize(32, 32))
        self.ui.btn_skip_forward.setIconSize(QSize(32, 32))

        # --- NEXT-GEN TIMELINE & CONTROLS UI REBUILD ---
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QFrame
        
        # 1. Mercilessly destroy the old Windows slider
        if hasattr(self.ui, 'slider_timeline'):
            self.ui.slider_timeline.setParent(None)
            self.ui.slider_timeline.deleteLater()
            delattr(self.ui, 'slider_timeline')

        # 2. Adjust button sizes (Make Play button bigger and bolder)
        self.ui.btn_play.setIconSize(QSize(48, 48))
        self.ui.btn_skip_back.setIconSize(QSize(32, 32))
        self.ui.btn_skip_forward.setIconSize(QSize(32, 32))

        # 3. Locate the original horizontal layout to hijack it
        right_layout = self.ui.right_panel.layout()
        if right_layout:
            controls_index = -1
            for i in range(right_layout.count()):
                item = right_layout.itemAt(i)
                if item.layout() and item.layout().objectName() == "layout_player_controls":
                    controls_index = i
                    break
                    
            if controls_index != -1:
                old_controls_layout = right_layout.itemAt(controls_index).layout()
                
                # Extract our widgets from the old layout
                while old_controls_layout.count():
                    item = old_controls_layout.takeAt(0)
                    if item.widget():
                        item.widget().setParent(None) 
                        
                # 4. Create a styled QFrame container for the footer (matches the header panel)
                self.player_footer_frame = QFrame()
                self.player_footer_frame.setObjectName("HudFrame")
                self.player_footer_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                
                # Hard height limit (so the panel doesn't bulge like in the photo)
                from PySide6.QtWidgets import QSizePolicy
                self.player_footer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
                
                from steempeg.ui.design_tokens import with_tooltip_style
                self.player_footer_frame.setStyleSheet(with_tooltip_style(
                    ut.player_footer_stylesheet() + _PLAYBACK_BUTTONS_QSS
                ))
                
                v_layout = QVBoxLayout(self.player_footer_frame)
                v_layout.setContentsMargins(15, 12, 15, 12)
                v_layout.setSpacing(5)
                
                # ROW 1: The Custom Timeline
                if not hasattr(self, 'custom_timeline'):
                    self.custom_timeline = CustomTimelineWidget()
                    self.custom_timeline.canvas.marker_store.set_cache_dir(self.cache_dir)
                v_layout.addWidget(self.custom_timeline)
                v_layout.addSpacing(6)
                # ROW 2: Volume/Speed | pinned timer | tools — timer never leaves center
                from steempeg.ui.player.controls.center_pinned_row import CenterPinnedRow

                # 1. LEFT BLOCK (Volume & Speed)
                left_wrap = QWidget()
                lw = QHBoxLayout(left_wrap)
                lw.setContentsMargins(0, 0, 0, 0)
                lw.setSpacing(10) # Gap between volume and speed buttons

                self.volume_control = VolumeControlWidget(self.player_footer_frame)
                self.volume_control.slider.valueChanged.connect(self.set_vlc_volume)

                self.speed_control = SpeedControlWidget(self.player_footer_frame)
                self.speed_control.slider.valueChanged.connect(self.set_vlc_speed)

                lw.addWidget(self.volume_control, alignment=Qt.AlignLeft | Qt.AlignVCenter)
                lw.addWidget(self.speed_control, alignment=Qt.AlignLeft | Qt.AlignVCenter)
                lw.addStretch() # Pushes both buttons nicely to the left!

                # 2. CENTER (Timer) — overlaid on geometric midpoint by CenterPinnedRow
                self.ui.label_time.setAlignment(Qt.AlignCenter)
                self.ui.label_time.setStyleSheet(
                    "color: #cccccc; font-size: 13px; font-weight: bold; background: transparent;"
                )
                self.ui.label_time.setMinimumWidth(170)

                # 3. RIGHT BLOCK (Theater + trim buttons)
                right_wrap = QWidget()
                rw = QHBoxLayout(right_wrap)
                rw.setContentsMargins(0, 0, 0, 0)
                rw.setSpacing(10) # Space between buttons

                from PySide6.QtWidgets import QPushButton

                # --- TRIM BUTTON (DUAL PURPOSE) ---
                self.btn_trim = QPushButton()
                self.btn_trim.setParent(self.player_footer_frame)
                self.btn_trim.setFixedHeight(30)
                self.btn_trim.setCursor(Qt.PointingHandCursor)
                
                # Dark fill + bright gold border (same language as portable Render).
                from steempeg.ui.design_tokens import STYLE_TRIM_BUTTON
                self.btn_trim.setStyleSheet(STYLE_TRIM_BUTTON)
                
                # Try to load custom scissors icon
                trim_icon_path = get_resource_path("trim_icon.png")
                if os.path.exists(trim_icon_path):
                    self.btn_trim.setIcon(QIcon(trim_icon_path))
                    self.btn_trim.setText(" Trim")
                else:
                    self.btn_trim.setText("✂️ Trim")
                
                # --- THEATER & FULLSCREEN PILL CONTAINER ---
                from steempeg.ui.ui_density import COMFORT as _COMFORT

                _pill_chip_r = _COMFORT.chrome_chip // 2
                self.pill_container = QFrame()
                self.pill_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                self.pill_container.setStyleSheet(
                    ut.player_chrome_pill_stylesheet(radius=_pill_chip_r)
                )
                
                pill_layout = QHBoxLayout(self.pill_container)
                # Add outer padding inside the pill (5px left/right) and 4px spacing between buttons
                pill_layout.setContentsMargins(5, 0, 5, 0)
                pill_layout.setSpacing(4) 

                # 1. THEATER MODE BUTTON
                self.btn_theater = QPushButton()
                self.btn_theater.setFixedSize(40, 40) 
                self.btn_theater.setCursor(Qt.PointingHandCursor)
                self.btn_theater.setToolTip("Theater Mode")
                from steempeg.ui.design_tokens import with_tooltip_style
                _pill_btn_qss = with_tooltip_style("""
                    QPushButton { background: transparent; border-radius: 20px; border: none; }
                    QPushButton:hover { background: rgba(255, 255, 255, 40); }
                """)
                self.btn_theater.setStyleSheet(_pill_btn_qss)
                
                self._apply_theater_button_icon(closed=False)
                if self.btn_theater.icon().isNull():
                    self.btn_theater.setText("🎦")

                # 2. FULLSCREEN MODE BUTTON
                self.btn_fullscreen = QPushButton()
                self.btn_fullscreen.setFixedSize(40, 40)
                self.btn_fullscreen.setCursor(Qt.PointingHandCursor)
                self.btn_fullscreen.setStyleSheet(_pill_btn_qss)
                self._apply_fullscreen_button_icon(fullscreen=False)
                if self.btn_fullscreen.icon().isNull():
                    self.btn_fullscreen.setText("🔲")

                # Connect button signals
                self.btn_theater.clicked.connect(self.toggle_theater_mode)
                self.btn_trim.clicked.connect(self.toggle_trim_state)
                self.btn_fullscreen.clicked.connect(self.toggle_fullscreen) 
                
                pill_layout.addWidget(self.btn_theater)
                pill_layout.addWidget(self.btn_fullscreen)

                # New Cropping Toolbar
                self.trim_tools_pill = QFrame()
                self.trim_tools_pill.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                self.trim_tools_pill.setStyleSheet(
                    ut.player_chrome_pill_stylesheet(radius=_pill_chip_r)
                )
                
                trim_tools_layout = QHBoxLayout(self.trim_tools_pill)
                trim_tools_layout.setContentsMargins(5, 0, 5, 0)
                trim_tools_layout.setSpacing(4)
                
                btn_style = with_tooltip_style("""
                    QPushButton { background: transparent; border-radius: 20px; border: none; }
                    QPushButton:hover { background: rgba(255, 255, 255, 40); }
                    QPushButton:pressed { background: rgba(255, 255, 255, 60); }
                """)
                
                self.btn_clipcut1 = QPushButton()
                self.btn_clipcut1.setFixedSize(40, 40)
                self.btn_clipcut1.setCursor(Qt.PointingHandCursor)
                self.btn_clipcut1.setToolTip("Set Start (Cut Left)")
                self.btn_clipcut1.setStyleSheet(btn_style)
                icon1 = get_resource_path("clipcut1.png")
                if os.path.exists(icon1):
                    self.btn_clipcut1.setIcon(QIcon(icon1))
                    self.btn_clipcut1.setIconSize(QSize(22, 22))
                else:
                    self.btn_clipcut1.setText("⬅️")

                self.btn_clipcut2 = QPushButton()
                self.btn_clipcut2.setFixedSize(40, 40)
                self.btn_clipcut2.setCursor(Qt.PointingHandCursor)
                self.btn_clipcut2.setToolTip("Set End (Cut Right)")
                self.btn_clipcut2.setStyleSheet(btn_style)
                icon2 = get_resource_path("clipcut2.png")
                if os.path.exists(icon2):
                    self.btn_clipcut2.setIcon(QIcon(icon2))
                    self.btn_clipcut2.setIconSize(QSize(22, 22))
                else:
                    self.btn_clipcut2.setText("➡️")

                self.btn_clipcutback = QPushButton()
                self.btn_clipcutback.setFixedSize(40, 40)
                self.btn_clipcutback.setCursor(Qt.PointingHandCursor)
                self.btn_clipcutback.setToolTip("Jump to Start")
                self.btn_clipcutback.setStyleSheet(btn_style)
                iconback = get_resource_path("clipcutback.png")
                if os.path.exists(iconback):
                    self.btn_clipcutback.setIcon(QIcon(iconback))
                    self.btn_clipcutback.setIconSize(QSize(22, 22))
                else:
                    self.btn_clipcutback.setText("⏪")

                trim_tools_layout.addWidget(self.btn_clipcut1)
                trim_tools_layout.addWidget(self.btn_clipcut2)
                trim_tools_layout.addWidget(self.btn_clipcutback)
                
                self.trim_tools_pill.hide() # Hide at startup so it doesn't get in the way.
                
                # Integrating our brilliant Uno =)) logic!
                self.btn_clipcut1.clicked.connect(self.set_trim_start_to_playhead)
                self.btn_clipcut2.clicked.connect(self.set_trim_end_to_playhead)
                self.btn_clipcutback.clicked.connect(self.jump_to_trim_start)

                # Marker pill: add mark + Marker Settings (like theater/fullscreen pill)
                from steempeg.ui.design_tokens import with_tooltip_style
                btn_style_marker = with_tooltip_style("""
                    QPushButton { background: transparent; border: none; }
                    QPushButton:hover { background: rgba(255, 255, 255, 30); border-radius: 6px; }
                    QPushButton:pressed { background: rgba(255, 255, 255, 50); }
                """)
                _pill_inner = with_tooltip_style("""
                    QPushButton { background: transparent; border-radius: 20px; border: none; }
                    QPushButton:hover { background: rgba(255, 255, 255, 40); }
                """)

                self.marker_pill = QFrame()
                self.marker_pill.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                self.marker_pill.setStyleSheet(
                    ut.player_chrome_pill_stylesheet(radius=_pill_chip_r)
                )
                marker_pill_layout = QHBoxLayout(self.marker_pill)
                marker_pill_layout.setContentsMargins(5, 0, 5, 0)
                marker_pill_layout.setSpacing(4)

                self.btn_add_marker = QPushButton()
                self.btn_add_marker.setFixedSize(40, 40)
                self.btn_add_marker.setCursor(Qt.PointingHandCursor)
                self.btn_add_marker.setToolTip("Add User Marker")
                self.btn_add_marker.setStyleSheet(_pill_inner)
                icon_marker_btn = get_resource_path("pointuser.png")
                if os.path.exists(icon_marker_btn):
                    self.btn_add_marker.setIcon(QIcon(icon_marker_btn))
                    self.btn_add_marker.setIconSize(QSize(22, 22))
                else:
                    self.btn_add_marker.setText("📍")
                self.btn_add_marker.clicked.connect(self.add_user_marker)

                self.btn_marker_settings = QPushButton()
                self.btn_marker_settings.setFixedSize(40, 40)
                self.btn_marker_settings.setCursor(Qt.PointingHandCursor)
                self.btn_marker_settings.setToolTip("Marker settings")
                self.btn_marker_settings.setStyleSheet(_pill_inner)
                settings_icon = get_resource_path("markersettings.png")
                if os.path.exists(settings_icon):
                    self.btn_marker_settings.setIcon(QIcon(settings_icon))
                    self.btn_marker_settings.setIconSize(QSize(22, 22))
                else:
                    self.btn_marker_settings.setText("⚙")
                self.btn_marker_settings.clicked.connect(self.show_marker_settings)

                marker_pill_layout.addWidget(self.btn_add_marker)
                marker_pill_layout.addWidget(self.btn_marker_settings)

                # NEW CAMERA BUTTON
                self.btn_screenshot = QPushButton()
                self.btn_screenshot.setFixedSize(40, 40)
                self.btn_screenshot.setCursor(Qt.PointingHandCursor)
                self.btn_screenshot.setToolTip("Take Screenshot")
                self.btn_screenshot.setStyleSheet(btn_style_marker)
                
                icon_camera = get_resource_path("camera.png")
                if os.path.exists(icon_camera):
                    self.btn_screenshot.setIcon(QIcon(icon_camera))
                    self.btn_screenshot.setIconSize(QSize(22, 22))
                else:
                    self.btn_screenshot.setText("📸")
                
                self.btn_screenshot.clicked.connect(lambda: self.take_screenshot())

                # ASSEMBLING THE PANEL 
                rw.addStretch() 
                rw.addWidget(self.marker_pill, alignment=Qt.AlignVCenter) 
                rw.addWidget(self.btn_screenshot, alignment=Qt.AlignVCenter) 
                rw.addWidget(self.trim_tools_pill, alignment=Qt.AlignVCenter)
                rw.addWidget(self.btn_trim, alignment=Qt.AlignVCenter)
                rw.addWidget(self.pill_container, alignment=Qt.AlignVCenter)

                # Remember original layout index for seamless restoring
                self.controls_layout_index = controls_index

                self._footer_controls_row = CenterPinnedRow(
                    left_wrap, self.ui.label_time, right_wrap, self.player_footer_frame
                )
                v_layout.addWidget(self._footer_controls_row)
                from steempeg.ui.player.controls.adaptive_trim_tools import (
                    ensure_adaptive_trim_hook,
                    sync_trim_tools_placement,
                )

                ensure_adaptive_trim_hook(self)
                sync_trim_tools_placement(self)
                
                # ROW 3: The Playback Buttons (Centered horizontally)
                
                # Reverting the playback buttons back to their normal, clean sizes
                self.ui.btn_play.setIconSize(QSize(48, 48))
                self.ui.btn_skip_back.setIconSize(QSize(32, 32))
                self.ui.btn_skip_forward.setIconSize(QSize(32, 32))

                self.ui.btn_play.setToolTip("Play / Pause")
                self.ui.btn_skip_back.setToolTip("Skip Back 15s")
                self.ui.btn_skip_forward.setToolTip("Skip Forward 15s")
                
                # --- ENABLE FINGER CURSORS ---
                self.ui.btn_play.setCursor(Qt.PointingHandCursor)
                self.ui.btn_skip_back.setCursor(Qt.PointingHandCursor)
                self.ui.btn_skip_forward.setCursor(Qt.PointingHandCursor)
                
                h_layout = QHBoxLayout()
                h_layout.setSpacing(8)
                h_layout.addStretch() # Pushes buttons to center
                
                self.ui.btn_skip_back.setParent(self.player_footer_frame)
                self.ui.btn_play.setParent(self.player_footer_frame)
                self.ui.btn_skip_forward.setParent(self.player_footer_frame)
                
                h_layout.addWidget(self.ui.btn_skip_back)
                h_layout.addWidget(self.ui.btn_play)
                h_layout.addWidget(self.ui.btn_skip_forward)
                
                h_layout.addStretch() # Pushes buttons to center
                
                self._apply_playback_button_styles()
                
                v_layout.addLayout(h_layout)
                
                from PySide6.QtWidgets import QSplitter, QWidget, QVBoxLayout
                # 1. Original button insert
                right_layout.insertWidget(controls_index, self.player_footer_frame)

                
                # THE PERFECT SPLITTER

                # 2. Vacuum absolutely everything out of the right-hand panel
                all_items = []
                while right_layout.count():
                    all_items.append(right_layout.takeAt(0))

                self.main_v_splitter = QSplitter(Qt.Vertical)

                from steempeg.ui.layout_defaults import (
                    DESKTOP_BOTTOM_PANE_SPACING,
                    MAIN_V_SPLIT_BOTTOM_PAD,
                    MAIN_V_SPLIT_TOP_PAD,
                    PLAYER_COLUMN_SPACING,
                )

                # 3. Top Box (Player and Buttons)
                self.top_v_wrap = QWidget()
                top_v_layout = QVBoxLayout(self.top_v_wrap)
                # Breath before the splitter handle (not a thick dark band).
                top_v_layout.setContentsMargins(0, 0, 0, MAIN_V_SPLIT_TOP_PAD)
                top_v_layout.setSpacing(PLAYER_COLUMN_SPACING)

                # 4. Bottom Box (Tabs and Status)
                self.bottom_v_wrap = QWidget()
                bottom_v_layout = QVBoxLayout(self.bottom_v_wrap)
                bottom_v_layout.setContentsMargins(0, MAIN_V_SPLIT_BOTTOM_PAD, 0, 0)
                # Neo ↔ dash gap (tighter than right_panel's generic 8).
                bottom_v_layout.setSpacing(DESKTOP_BOTTOM_PANE_SPACING)

                # 5. Carefully arrange the components into two boxes.
                put_in_bottom = False
                for item in all_items:
                    # Neo / tabs / dash — dash alone must count too (Like a Portable
                    # may have already parked neo before this vacuum runs).
                    w = item.widget()
                    if w is not None and w in (
                        getattr(self.ui, "settings_tabs", None),
                        getattr(self, "neo_wrapper", None),
                        getattr(self, "render_dashboard", None),
                    ):
                        put_in_bottom = True
                    
                    target_layout = bottom_v_layout if put_in_bottom else top_v_layout
                    
                    # Transferring safely, preserving all proportions and springs
                    if item.widget(): target_layout.addWidget(item.widget())
                    elif item.layout(): target_layout.addLayout(item.layout())
                    elif item.spacerItem(): target_layout.addItem(item.spacerItem())

                from PySide6.QtWidgets import QSizePolicy
                from PySide6.QtCore import QObject, QEvent
                # 1. FIX PLAYER BUTTONS STRETCHING:
                # video_container lives inside video_wrapper — stretch the wrapper or
                # leftover top-pane height pools under the timeline as a dark band.
                vw = getattr(self, "video_wrapper", None)
                if vw is not None:
                    vw.setSizePolicy(
                        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
                    )
                    top_v_layout.setStretchFactor(vw, 1)
                else:
                    top_v_layout.setStretchFactor(self.ui.video_container, 1)

                # 2. FIX STATUS BAR EXPANDING:
                # Prevent the bottom status bar from becoming huge when tabs hide.
                if hasattr(self.ui, 'frame_status'):
                    self.ui.frame_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                
                
                if hasattr(self, 'neo_wrapper'):
                    bottom_v_layout.setStretchFactor(self.neo_wrapper, 1)
                elif hasattr(self.ui, 'settings_tabs'):
                    bottom_v_layout.setStretchFactor(self.ui.settings_tabs, 1)


                
                self.hide_watcher = HideWatcher(self.main_v_splitter)
                if hasattr(self.ui, 'settings_tabs'):
                    self.ui.settings_tabs.installEventFilter(self.hide_watcher)

                # 6. Assembling the Splitter
                self.main_v_splitter.addWidget(self.top_v_wrap)
                self.main_v_splitter.addWidget(self.bottom_v_wrap)
                
                self.main_v_splitter.setCollapsible(0, False) # The player is immortal
                self.main_v_splitter.setCollapsible(1, True)  # Tabs can be collapsed/hidden
                from steempeg.ui.layout_defaults import (
                    STEAM_DECK_HEIGHT,
                    STEAM_DECK_WIDTH,
                    default_main_v_splitter_sizes,
                )

                _avail_h = self.ui.height() or STEAM_DECK_HEIGHT
                _avail_w = self.ui.width() or STEAM_DECK_WIDTH
                self.main_v_splitter.setSizes(
                    default_main_v_splitter_sizes(_avail_w, _avail_h)
                )
                self.main_v_splitter.splitterMoved.connect(
                    self._on_main_v_splitter_moved
                )
                # Theme-aware handle first; layout sync may hide it (Like a Portable).
                try:
                    from steempeg.ui.layout_defaults import vertical_splitter_handle_qss
                    from steempeg.ui.ui_theme import splitter_handle_colors

                    idle, hover = splitter_handle_colors(vertical=True)
                    self.main_v_splitter.setStyleSheet(
                        vertical_splitter_handle_qss(idle, hover)
                    )
                except Exception:
                    self.main_v_splitter.setStyleSheet("""
                    QSplitter::handle {
                        background-color: #444444;
                        margin: 0px 40px;
                        border-radius: 2px;
                        height: 4px;
                    }
                    QSplitter::handle:hover {
                        background-color: #b29ae7;
                    }
                """)
                # Like a Portable: park neo + glue dash now that the v-splitter exists.
                if hasattr(self, "apply_desktop_render_layout"):
                    self.apply_desktop_render_layout()

                # 7. Place the splitter back into the CLEAN right-hand panel.
                self.right_content_wrap = QWidget()
                self.right_content_wrap.setAttribute(Qt.WA_StyledBackground, True)
                self.right_content_wrap.setStyleSheet("background: transparent;")
                right_content_layout = QVBoxLayout(self.right_content_wrap)
                from steempeg.ui.layout_defaults import (
                    QUEUE_SPLITTER_GUTTER,
                    RIGHT_PANEL_PLAYER_TOP_INSET,
                )
                # Player top inset + gutter before the queue splitter.
                right_content_layout.setContentsMargins(
                    0, RIGHT_PANEL_PLAYER_TOP_INSET, QUEUE_SPLITTER_GUTTER, 0,
                )
                right_content_layout.setSpacing(0)
                right_content_layout.addWidget(self.main_v_splitter)

                from steempeg.ui.layout_defaults import (
                    DEFAULT_QUEUE_VIEW,
                    DEFAULT_RIGHT_H_SPLITTER_SIZES,
                )
                from steempeg.ui.render_queue_panel import RenderQueuePanel

                queue_view = self.get_layout_setting("queue_view_mode", DEFAULT_QUEUE_VIEW)
                self.render_queue_panel = RenderQueuePanel(initial_view_mode=queue_view)
                self.render_queue_panel._app = self
                # Closed at startup (sizes […, 0]); keep min at 0 until the pane opens
                # so nested mins cannot fight Clips Manager on the outer splitter.
                self.render_queue_panel.setMinimumWidth(0)
                self.render_queue_panel.job_selected.connect(self.on_queue_job_selected)
                self.render_queue_panel.job_remove_requested.connect(self.remove_queue_job)
                self.render_queue_panel.job_reorder_requested.connect(self.reorder_queue_job)
                self.render_queue_panel.job_reorder_after_requested.connect(self.reorder_queue_job_after)
                self.render_queue_panel.clear_queue_requested.connect(self.clear_render_queue)
                self.render_queue_panel.history_requested.connect(self.show_render_queue_history)
                self.render_queue_panel.view_mode_changed.connect(
                    lambda mode: self.save_layout_setting("queue_view_mode", mode)
                )
                dismissed = bool(
                    self.load_user_settings().get("render_queue_empty_hint_dismissed", False)
                )
                self.render_queue_panel.set_empty_hint_dismissed(dismissed)
                self.render_queue_panel.empty_hint_dismissed_changed.connect(
                    lambda checked: self.save_user_settings(
                        "render_queue_empty_hint_dismissed", bool(checked)
                    )
                )

                self.right_h_splitter = QSplitter(Qt.Horizontal)
                self.right_h_splitter.setObjectName("right_h_splitter")
                self.right_h_splitter.setHandleWidth(6)
                self.right_h_splitter.setChildrenCollapsible(True)
                self.right_h_splitter.setStyleSheet(self.ui.main_splitter.styleSheet())
                self.right_h_splitter.splitterMoved.connect(self._on_right_h_splitter_moved)

                right_layout.addWidget(self.right_content_wrap)

                panel_idx = self.ui.main_splitter.indexOf(self.ui.right_panel)
                self.ui.right_panel.setParent(None)
                self.ui.right_panel.setMinimumWidth(0)
                self.right_h_splitter.addWidget(self.ui.right_panel)
                self.right_h_splitter.addWidget(self.render_queue_panel)
                # After addWidget — setCollapsible before children is Index out of range.
                # Player column may collapse to 0 so the two handles can "kiss"
                # (Clips | Queue with no middle scrap). False here + a 360px floor
                # made the right handle constantly bounce back.
                self.right_h_splitter.setCollapsible(0, True)
                self.right_h_splitter.setCollapsible(1, True)
                self.ui.main_splitter.insertWidget(panel_idx, self.right_h_splitter)
                # Allow Clips to push the whole right column away (kiss from the left).
                self.ui.main_splitter.setChildrenCollapsible(True)
                self.ui.main_splitter.setCollapsible(0, True)
                self.ui.main_splitter.setCollapsible(1, True)
                self.ui.main_splitter.splitterMoved.connect(self._on_main_splitter_moved)
                self.right_h_splitter.setSizes(DEFAULT_RIGHT_H_SPLITTER_SIZES)
                self.install_splitter_rules()
                try:
                    from steempeg.ui.splitter_telemetry import install_splitter_telemetry

                    install_splitter_telemetry(self)
                except Exception:
                    logging.debug("splitter telemetry install skipped", exc_info=True)

                if hasattr(self, "_load_persisted_render_queue"):
                    self._load_persisted_render_queue()
                    self._update_start_button_label()
                    # Restore last-session open/closed — do not force open yet.
                    # Geometry settle (_ensure_startup_queue_open) applies width.
                    self._restore_queue_panel_collapsed_from_settings()
                    self.refresh_render_queue_panel(sync_splitter=True)

                # Shared Desktop/Portable panel snapshot (render_export_settings).
                try:
                    from steempeg.ui.portable.sheets import ensure_render_settings_restored

                    ensure_render_settings_restored(self)
                except Exception:
                    pass

                # Saving the new index for Fullscreen
                self.controls_layout_index = top_v_layout.indexOf(self.player_footer_frame)
                try:
                    from steempeg.ui.layout_defaults import apply_player_layout_mode

                    apply_player_layout_mode(self)
                except Exception:
                    pass
                self._refresh_player_footer_chrome(_COMFORT)
                self.custom_timeline.pause_requested.connect(self.on_timeline_press)
                self.custom_timeline.seek_requested.connect(self.on_timeline_seek)
                self.custom_timeline.resume_requested.connect(self.on_timeline_release)
                self.custom_timeline.trim_changed.connect(self.on_trim_changed) 
                self.custom_timeline.screenshot_requested.connect(self.take_screenshot)
                self.custom_timeline.add_marker_requested.connect(self.add_user_marker)
                self.custom_timeline.open_steam_screenshot_requested.connect(
                    self.open_steam_screenshot_for_marker
                )
                self.custom_timeline.open_steam_screenshot_folder_requested.connect(
                    self.open_steam_screenshot_folder_for_marker
                )
        
        # --- INITIALIZING THE MPV VIDEO PLAYER ---
        mpv_log_path_str = self.current_mpv_log_file
        logging.info("MPV log: %s", mpv_log_path_str)

        # Clean up any junk, if present
        if self.ui.video_container.layout():
            QWidget().setLayout(self.ui.video_container.layout())
            
        self.ui.video_container.setStyleSheet("background-color: transparent; border: none;")
        # UI file pins min height 280 — that makes the embed overflow when the
        # player column is crushed. Allow the surface to shrink with the layout.
        self.ui.video_container.setMinimumSize(0, 0)
        
        # We place our smart wrapper into the standard layout.
        layout = QVBoxLayout(self.ui.video_container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.mpv_wrapper = MPVWrapper()
        self.mpv_wrapper.setMinimumSize(0, 0)
        from PySide6.QtWidgets import QSizePolicy as _QSizePolicy
        self.mpv_wrapper.setSizePolicy(
            _QSizePolicy.Policy.Expanding, _QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.mpv_wrapper)
        
        
        self.aspect_frame = self.mpv_wrapper.aspect_frame
        self.mpv_screen = self.mpv_wrapper.mpv_screen
        if hasattr(self, 'video_stack'):
            self.video_stack.currentChanged.connect(self._on_video_stack_page_changed)
            self._on_video_stack_page_changed()

        # Windows: create embedded mpv immediately.
        # Linux/Bazzite: do NOT create libmpv at startup — even vo=null still
        # loads scripts and, with QT xcb + NVIDIA, the window can hard-freeze
        # (black, unkillable). Player is created lazily on first play().
        self._linux_mpv_vo_attached = False
        self.current_mpv_log_file = mpv_log_path_str
        if sys.platform == "win32":
            from steempeg.ui.settings_prefs import (
                current_hwdec_preview,
                current_mpv_loglevel,
            )

            mpv_opts = {
                "panscan": 1.0,
                "keepaspect": "no",
                "keep_open": "yes",
                "log_file": mpv_log_path_str,
                "loglevel": current_mpv_loglevel(),
                "wid": int(self.mpv_screen.winId()),
                "vo": "gpu",
                "hwdec": current_hwdec_preview(),
                "ao": "wasapi",
            }
            self.player = mpv.MPV(**mpv_opts)
            try:
                self.player["af"] = "rubberband"
            except Exception as exc:
                logging.warning("mpv rubberband af unavailable: %s", exc)
            # Embedded wid= HWND must not activate the shell when it eats input —
            # otherwise opening Explorer while a clip plays can leave Steempeg on top.
            try:
                from steempeg.infra.window_focus import mark_embed_noactivate

                mark_embed_noactivate(self.mpv_screen)
            except Exception:
                logging.debug("mpv embed noactivate failed", exc_info=True)
            self._init_preview_quality()
            self._apply_saved_preview_quality_to_player()
        else:
            self.player = None
            logging.info("Linux mpv: lazy create (no libmpv until first play)")
            self._init_preview_quality()
        self._install_mpv_geometry_hooks()

        # --- FULLSCREEN SYSTEM INITIALIZATION ---
        self.is_fullscreen = False
        
        # 1. Setup the 3-second sleep timer
        self.fs_timer = QTimer(self)
        self.fs_timer.setInterval(3000) # 3 seconds
        self.fs_timer.timeout.connect(self.sleep_fullscreen_controls)
        
        # 2. Install the Global Radar to catch mouse moves and ESC
        self.fs_filter = FullscreenEventFilter(self)
        QApplication.instance().installEventFilter(self.fs_filter)
        
        # 3. Connect the Fullscreen button (make sure this name matches your Qt Designer button!)
        if hasattr(self.ui, 'btn_fullscreen'):
            self._apply_fullscreen_button_icon(
                fullscreen=bool(getattr(self, "is_fullscreen", False))
            )
            self.ui.btn_fullscreen.clicked.connect(self.toggle_fullscreen)


        # Button connections 
        if hasattr(self.ui, 'btn_play'):
            self.ui.btn_play.clicked.connect(self.toggle_play)
            self.ui.btn_skip_back.clicked.connect(self.skip_backward)
            self.ui.btn_skip_forward.clicked.connect(self.skip_forward)

        self.vlc_timer = QTimer(self.ui)
        self.vlc_timer.setInterval(16) # Update the interface every 200 milliseconds
        self.vlc_timer.timeout.connect(self.update_ui_from_vlc)
        self.vlc_timer.start() # Let it always work in the background



        

        if hasattr(self.ui, 'btn_logs'):
            self.setup_logs_menu()
        
        # We connect the "Final setup" update to all interface changes
        if hasattr(self.ui, 'combo_quality'):
            self.ui.combo_quality.currentTextChanged.connect(self.on_quality_mode_changed)
        if hasattr(self.ui, 'btn_quality_original_help'):
            self.ui.btn_quality_original_help.setToolTip(
                "Original preset warning — click for details.\n"
                "Fast stream copy without re-encoding may produce wrong output duration "
                "if the Steam DASH chunks are slightly broken."
            )
            self.ui.btn_quality_original_help.clicked.connect(self.show_original_help_popup)
            self.init_original_help_state()
        if hasattr(self.ui, 'combo_bitrate'): self.ui.combo_bitrate.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_codec'):
            self.ui.combo_codec.currentTextChanged.connect(self.update_final_setup)
            self.ui.combo_codec.currentTextChanged.connect(self._mark_output_preset_custom)
            self.ui.combo_codec.currentTextChanged.connect(self.refresh_output_format_availability)
            self.ui.combo_codec.currentTextChanged.connect(self.refresh_encode_speed_options)
        if hasattr(self.ui, 'combo_fps'):
            self.ui.combo_fps.currentTextChanged.connect(self.update_final_setup)
            self.ui.combo_fps.currentTextChanged.connect(self.refresh_slider_if_needed)
            self.ui.combo_fps.currentTextChanged.connect(self.update_bitrate_options)
        if hasattr(self.ui, 'input_filename'): self.ui.input_filename.textChanged.connect(self._on_output_filename_changed)

        if hasattr(self.ui, 'combo_encoder'):
            self.ui.combo_encoder.currentTextChanged.connect(self.update_final_setup)
            self.ui.combo_encoder.currentTextChanged.connect(self.refresh_encode_speed_options)
            self.ui.combo_encoder.currentTextChanged.connect(self._mark_output_preset_custom)
        if hasattr(self.ui, 'combo_encode_speed'):
            self.ui.combo_encode_speed.currentTextChanged.connect(self.update_final_setup)
            self.ui.combo_encode_speed.currentTextChanged.connect(self._mark_output_preset_custom)
        # Connect the pause and cancel buttons (they are initially disabled)
        if hasattr(self.ui, 'btn_cancel'):
            self.ui.btn_cancel.setEnabled(False)
            self.ui.btn_cancel.clicked.connect(self.cancel_render)
            
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.clicked.connect(self.toggle_pause)

        # Hide the size slider and its text when the program starts
        if hasattr(self.ui, 'size_slider'):
            self.ui.size_slider.setVisible(False)
            self.ui.size_slider.valueChanged.connect(self.on_slider_moved)

        self._setup_bitrate_labels()

        self._setup_custom_target_size()
        
        if hasattr(self.ui, 'check_audio_only'):
            self.ui.check_audio_only.toggled.connect(self.on_audio_only_toggled)
        if hasattr(self.ui, 'check_mute_audio'):
            self.ui.check_mute_audio.toggled.connect(self.on_mute_audio_toggled)
        if hasattr(self.ui, 'combo_audio_format'):
            self.ui.combo_audio_format.currentTextChanged.connect(self.update_final_setup)
            self.ui.combo_audio_format.currentTextChanged.connect(self._mark_output_preset_custom)
            self.ui.combo_audio_format.currentTextChanged.connect(self.refresh_output_format_availability)
            self.ui.combo_audio_format.currentTextChanged.connect(self.refresh_slider_if_needed)
        if hasattr(self.ui, 'combo_audio_bitrate'):
            self.ui.combo_audio_bitrate.currentTextChanged.connect(self.update_final_setup)
            self.ui.combo_audio_bitrate.currentTextChanged.connect(self.refresh_slider_if_needed)
        if hasattr(self.ui, 'combo_container'):
            self.ui.combo_container.currentTextChanged.connect(self.update_final_setup)
            self.ui.combo_container.currentTextChanged.connect(self._mark_output_preset_custom)
            self.ui.combo_container.currentTextChanged.connect(self.refresh_output_format_availability)
        if hasattr(self.ui, 'combo_output_preset'):
            self.ui.combo_output_preset.currentTextChanged.connect(self.on_output_preset_changed)
    
        # 5. AUTOMATIC DATA LOADING AT PROGRAM START
        self.detect_gpu_and_set_encoder()
        
        # 1. Load saved library folder roots (migrates legacy last_clips_folder)
        self._load_clips_folders_from_settings()

        # First launch only: auto-discover every Steam userdata/*/gamerecordings/clips.
        # If the user later clears the list, we do not re-scan until they ask.
        if self._should_auto_discover_steam_folders():
            discovered = self.auto_discover_steam_folders(save=True)
            if discovered:
                logging.info(
                    "Steam auto-discovery on first launch: %s folder(s)",
                    len(discovered),
                )

        # Keep the folder-picker (+ button / label) in sync with whatever roots we
        # ended up with. Auto-detected paths never went through choose_folder(), so
        # _update_folder_picker_label must run here too.
        self._update_folder_picker_label()

        # Defer startup scans until the window geometry and library UI state are
        # restored. Starting background scans here caused:
        # - the library tab bar to "snap" when Rendered videos was restored
        # - the footer dashboard to resize while clips were being inserted
        # - cross-panel status updates (clips vs rendered) fighting each other
        self._start_startup_scans_pending = True

        if hasattr(self.ui, 'main_splitter'):
            from steempeg.ui.layout_defaults import (
                DEFAULT_MAIN_SPLITTER_SIZES,
                DEFAULT_MAIN_SPLITTER_SIZES_COMPACT,
                STEAM_DECK_WIDTH,
                is_compact_layout,
                left_panel_min_width,
            )

            # Prefer comfort sizes on big screens; Deck-class / low-PPI use compact.
            avail_w = self.ui.width() or STEAM_DECK_WIDTH
            default_sizes = (
                DEFAULT_MAIN_SPLITTER_SIZES_COMPACT
                if is_compact_layout(avail_w, widget=self.ui)
                else DEFAULT_MAIN_SPLITTER_SIZES
            )
            self.ui.main_splitter.setSizes(
                self.get_layout_setting("main_splitter_sizes", default_sizes)
            )
            self.ui.left_panel.setMinimumWidth(left_panel_min_width(avail_w, widget=self.ui))
            self._apply_responsive_layout_mins()

        self._apply_dark_shell()
        self._refresh_ui_theme_surfaces()

        # --- CUSTOM INPUTS: wire the overlay edit fields built by render_panel ---
        from PySide6.QtGui import QDoubleValidator, QIntValidator

        from steempeg.ui.icon_assets import warning_pixmap

        def _wire_custom(input_attr, warn_attr, validator, slot):
            edit = getattr(self.ui, input_attr, None)
            if edit is None:
                return
            warn = getattr(self.ui, warn_attr, None)
            setattr(self, input_attr, edit)
            setattr(self, warn_attr, warn)
            edit.setValidator(validator)
            edit.textChanged.connect(slot)
            if warn is not None:
                pix = warning_pixmap(16)
                if not pix.isNull():
                    warn.setPixmap(pix)
                if hasattr(self, 'instant_tooltip'):
                    warn.installEventFilter(self.instant_tooltip)

        _wire_custom('input_custom_fps', 'warn_fps', QIntValidator(1, 120), self.validate_custom_fps)
        _wire_custom('input_custom_vbitrate', 'warn_vbitrate', QDoubleValidator(0.1, 200.0, 2), self.validate_custom_vbitrate)
        _wire_custom('input_custom_abitrate', 'warn_abitrate', QIntValidator(1, 500), self.validate_custom_abitrate)
    
        if hasattr(self, 'custom_timeline'):
                self.custom_timeline.setEnabled(False) # Disable clicks into empty space
                self.custom_timeline.set_duration(0)   # Reset time
                self.custom_timeline.force_jump(0)     # Position the playhead at 0
                self.custom_timeline.canvas.markers.clear()
                self.custom_timeline.canvas.update()
                
        if hasattr(self.ui, 'label_time'):
            self.ui.label_time.setText("00:00 / 00:00")
        
        QApplication.instance().applicationStateChanged.connect(self.hide_hud_on_minimize)

    def set_player_header_clip_controls_visible(self, visible: bool) -> None:
        """Show divider + close chip when a clip is open in the player."""
        for widget in (
            getattr(self, "player_header_divider", None),
            getattr(self, "player_header_actions", None),
        ):
            if widget is not None:
                widget.setVisible(bool(visible))
        # Preview quality is for Steam/DASH clips only — finished exports have no
        # adaptive streams to pick, so hide the gear on Rendered videos playback.
        btn_q = getattr(self, "btn_preview_settings", None)
        if btn_q is not None:
            show_q = bool(visible)
            if show_q and hasattr(self, "_is_previewing_rendered_media"):
                try:
                    show_q = not bool(self._is_previewing_rendered_media())
                except Exception:
                    show_q = True
            btn_q.setVisible(show_q)
        self.refresh_player_header_info(has_clip=bool(visible))
        # Steam-like: keep ``|`` / title at bar midpoint when the right dock
        # appears or disappears (Healthy / gear / close).
        try:
            from steempeg.ui.player_header_layout import (
                ensure_header_center_sync,
                sync_header_center_mirror,
            )

            ensure_header_center_sync(self)
            sync_header_center_mirror(self)
        except Exception:
            pass

    def _source_info_tooltip_text(self) -> str:
        """Build clip facts from Source Info labels / header meta (hover + click popup)."""
        from steempeg.ui.player_header_layout import (
            join_clip_date_time,
            plain_header_title,
        )

        ui = getattr(self, "ui", None)
        if ui is None:
            return "No clip selected"

        lines: list[str] = []
        meta = getattr(self, "_player_header_meta", None) or {}
        title = str(meta.get("title") or "").strip()
        if not title or meta.get("placeholder"):
            name_lbl = getattr(self, "custom_text_label", None)
            if name_lbl is not None:
                title = plain_header_title(name_lbl.text() or "")
        if title and "select a clip" not in title.lower():
            lines.append(title)

        datetime_line = join_clip_date_time(
            str(meta.get("date") or ""),
            str(meta.get("time") or ""),
        )
        if datetime_line:
            lines.append(f"Date: {datetime_line}")
        dur_meta = str(meta.get("duration") or "").strip()
        if dur_meta and dur_meta not in ("-", "—"):
            if dur_meta.lower().startswith("time:"):
                dur_meta = dur_meta.split(":", 1)[1].strip()
            if dur_meta:
                lines.append(f"Duration: {dur_meta}")
        for part in meta.get("extra") or ():
            p = str(part or "").strip()
            if p:
                lines.append(p)

        specs = (
            ("Resolution", "orig_res_label"),
            ("Video Bitrate", "label_vbitrate"),
            ("Audio Bitrate", "label_abitrate"),
            ("Duration", "label_duration"),
            ("FPS", "label_fps"),
            ("Size", "label_size"),
        )
        # Skip the game-title line (index 0): titles may contain ``:`` and must
        # not pollute caption dedupe (e.g. "Hatsune Miku: Project DIVA…").
        seen_caps = {
            ln.split(":", 1)[0].strip().lower()
            for ln in lines[1:]
            if ":" in ln
        }
        for caption, attr in specs:
            if caption.lower() in seen_caps:
                continue
            lbl = getattr(ui, attr, None)
            if lbl is None or not hasattr(lbl, "text"):
                continue
            val = (lbl.text() or "").strip()
            if not val or val in ("-", "—"):
                continue
            # label_duration is ``Time: 3m`` — normalize to Duration for the tip.
            if attr == "label_duration" and val.lower().startswith("time:"):
                val = val.split(":", 1)[1].strip()
                if not val or val in ("-", "—"):
                    continue
                lines.append(f"Duration: {val}")
                seen_caps.add("duration")
                continue
            # Strip ``Label:`` prefixes from Source Info widgets.
            for prefix in (
                "Original resolution:",
                "Original Resolution:",
                "Video Bitrate:",
                "Audio Bitrate:",
                "FPS:",
                "Size:",
                "Time:",
            ):
                if val.lower().startswith(prefix.lower()):
                    val = val[len(prefix):].strip()
                    break
            if not val or val in ("-", "—"):
                continue
            lines.append(f"{caption}: {val}")
            seen_caps.add(caption.lower())

        src = getattr(ui, "source_label", None)
        paths: list[str] = []
        if src is not None:
            try:
                from PySide6.QtWidgets import QLabel, QLineEdit

                for field in src.findChildren(QLineEdit):
                    t = (field.text() or "").strip()
                    if t:
                        paths.append(t)
                if not paths:
                    for field in src.findChildren(QLabel):
                        t = (field.text() or "").strip()
                        if not t or t.lower().rstrip(":") == "source":
                            continue
                        paths.append(t)
            except RuntimeError:
                paths = []
            if not paths and hasattr(src, "text"):
                raw = (src.text() or "").strip()
                if raw and raw.lower() not in ("source:", "source: -", "source:-"):
                    if raw.lower().startswith("source:"):
                        raw = raw.split(":", 1)[1].strip()
                    if raw and raw not in ("-", "—"):
                        paths.append(raw)
        if paths:
            lines.append("Source:")
            lines.extend(paths)

        return "\n".join(lines) if lines else "No clip selected"

    def show_player_header_clip_info_popup(self) -> None:
        """Lightweight popup with quick clip params, anchored under the playinfo chip."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QFont, QPixmap
        from PySide6.QtWidgets import (
            QHBoxLayout,
            QLabel,
            QMenu,
            QToolTip,
            QVBoxLayout,
            QWidget,
            QWidgetAction,
        )

        from steempeg.ui import design_tokens as tok
        from steempeg.ui import ui_theme as ut
        from steempeg.ui.icon_shape import shaped_game_icon_pixmap

        btn = getattr(self, "btn_player_header_info", None)
        if btn is None or not btn.isEnabled():
            return

        text = self._source_info_tooltip_text()
        if not text or text == "No clip selected":
            return

        existing = getattr(self, "_clip_info_popup", None)
        if existing is not None:
            try:
                if existing.isVisible():
                    existing.close()
                    self._clip_info_popup = None
                    return
            except RuntimeError:
                self._clip_info_popup = None

        QToolTip.hideText()

        menu = QMenu(btn)
        self._clip_info_popup = menu
        menu.setObjectName("clipInfoPopup")
        menu.setStyleSheet(ut.clip_info_popup_stylesheet())
        _, _, info_value_fg, info_muted_fg = ut.clip_info_popup_colors()

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        host.setMinimumWidth(348)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(14, 12, 14, 12)
        # Same rhythm as Original preset warning: 8px between title and body.
        lay.setSpacing(8)

        from steempeg.ui.player_header_layout import (
            player_header_font_px,
            player_header_title_qfont,
        )
        # Same face as the player-header game name (Hatsune Miku title).
        heading_font = player_header_title_qfont(player_header_font_px(self))
        heading_qss = (
            f"color: #ffffff; font-weight: 700; font-size: {heading_font.pixelSize()}px;"
            f" font-family: {tok.FONT_APP}; background: transparent;"
        )
        heading = QLabel("Clip info")
        heading.setFont(heading_font)
        heading.setStyleSheet(heading_qss)
        lay.addWidget(heading)

        lines = [ln for ln in text.split("\n") if ln.strip()]
        # Resolve game title from header meta — never via colon-split of tip lines.
        meta = getattr(self, "_player_header_meta", None) or {}
        title_line = str(meta.get("title") or "").strip()
        if not title_line or meta.get("placeholder"):
            name_lbl = getattr(self, "custom_text_label", None)
            if name_lbl is not None:
                from steempeg.ui.player_header_layout import plain_header_title

                title_line = plain_header_title(name_lbl.text() or "")
        if title_line and "select a clip" in title_line.lower():
            title_line = ""
        # Tip text still starts with the title when present — drop it so it is
        # not re-parsed as a fake Label/value row.
        _META_CAPS = {
            "date",
            "duration",
            "resolution",
            "video bitrate",
            "audio bitrate",
            "fps",
            "size",
        }
        if title_line and lines and lines[0] == title_line:
            lines = lines[1:]
        elif title_line and lines:
            # Tip title may differ slightly from meta; drop non-meta first line
            # so a colon-bearing name is never shown again as a field row.
            first = lines[0]
            cap0 = (
                first.split(":", 1)[0].strip().lower() if ":" in first else ""
            )
            if cap0 not in _META_CAPS and first.strip() != "Source:" and cap0 != "source":
                lines = lines[1:]
        elif not title_line and lines:
            first = lines[0]
            cap0 = (
                first.split(":", 1)[0].strip().lower() if ":" in first else ""
            )
            if ":" not in first or (cap0 and cap0 not in _META_CAPS and cap0 != "source"):
                title_line = lines.pop(0)

        rows: list[tuple[str, str]] = []
        source_paths: list[str] = []
        in_source = False
        for line in lines:
            if in_source:
                source_paths.append(line)
                continue
            if line.strip() == "Source:":
                in_source = True
                continue
            if ":" in line:
                cap, val = line.split(":", 1)
                cap_s, val_s = cap.strip(), val.strip()
                if cap_s.lower() in _META_CAPS:
                    rows.append((cap_s, val_s))
                else:
                    rows.append(("", line.strip()))
            else:
                rows.append(("", line.strip()))

        if title_line:
            _ICON_SZ = 24
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(8)

            from steempeg.ui.icon_utils import apply_square_icon

            icon_lbl = QLabel()
            icon_lbl.setStyleSheet("background: transparent; border: none;")
            src_pix = QPixmap()
            icon_path = getattr(self, "current_game_icon", "") or ""
            if icon_path and os.path.isfile(icon_path):
                src_pix = QPixmap(icon_path)
            if src_pix.isNull():
                header_icon = getattr(self, "custom_icon_label", None)
                if header_icon is not None:
                    try:
                        hdr = header_icon.pixmap()
                        if hdr is not None and not hdr.isNull():
                            src_pix = hdr
                    except RuntimeError:
                        pass
            if src_pix.isNull():
                unknown = get_resource_path("unknown_icon.png")
                if unknown and os.path.isfile(unknown):
                    src_pix = QPixmap(unknown)
            shaped = (
                shaped_game_icon_pixmap(src_pix, _ICON_SZ)
                if not src_pix.isNull()
                else None
            )
            apply_square_icon(icon_lbl, shaped, _ICON_SZ)
            title_row.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

            name = QLabel(title_line)
            name.setWordWrap(True)
            name.setFont(heading_font)
            name.setStyleSheet(heading_qss)
            title_row.addWidget(name, 1)
            lay.addLayout(title_row)

        for cap, val in rows:
            if not val and not cap:
                continue
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)
            if cap:
                cap_lbl = QLabel(f"{cap}:")
                # Export Settings Final Render Details keys (Clip time / Quality / Bitrate).
                cap_lbl.setStyleSheet(
                    f"color: {info_muted_fg}; background: transparent; "
                    f"font-size: 13px; font-family: {tok.FONT_APP};"
                )
                cap_lbl.setMinimumWidth(96)
                row.addWidget(cap_lbl, 0)
            val_lbl = QLabel(val)
            val_lbl.setWordWrap(True)
            val_lbl.setStyleSheet(
                f"color: {info_value_fg}; font-size: 11px;"
                f" font-family: {tok.FONT_APP}; background: transparent;"
            )
            row.addWidget(val_lbl, 1)
            lay.addLayout(row)

        if source_paths:
            src_cap = QLabel("Source:")
            src_cap.setStyleSheet(
                f"color: {info_muted_fg}; background: transparent; "
                f"font-size: 13px; font-family: {tok.FONT_APP};"
            )
            lay.addWidget(src_cap)
            path_font = QFont("Cascadia Mono")
            if not path_font.exactMatch():
                path_font = QFont("Consolas")
            if not path_font.exactMatch():
                path_font = QFont("Courier New")
            path_font.setStyleHint(QFont.StyleHint.Monospace)
            path_font.setFixedPitch(True)
            path_font.setPointSize(9)
            for path in source_paths:
                path_lbl = QLabel(path)
                path_lbl.setWordWrap(True)
                path_lbl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                path_lbl.setFixedWidth(320)
                path_lbl.setFont(path_font)
                path_lbl.setStyleSheet(
                    f"color: {info_muted_fg}; background: transparent;"
                )
                lay.addWidget(path_lbl)

        act = QWidgetAction(menu)
        act.setDefaultWidget(host)
        menu.addAction(act)

        def _clear_ref(*_args):
            if getattr(self, "_clip_info_popup", None) is menu:
                self._clip_info_popup = None

        menu.aboutToHide.connect(_clear_ref)
        menu.exec(btn.mapToGlobal(QPoint(0, btn.height() + 4)))

    def refresh_player_header_info(self, *, has_clip: bool | None = None) -> None:
        """Show/hide the header Clip info chip and refresh its tooltip.

        When no clip is selected the chip is hidden entirely (not merely
        disabled) so the empty header is only the placeholder text.
        """
        btn = getattr(self, "btn_player_header_info", None)
        if btn is None:
            return
        if has_clip is None:
            actions = getattr(self, "player_header_actions", None)
            has_clip = bool(actions is not None and actions.isVisible())
        tip = self._source_info_tooltip_text() if has_clip else "No clip selected"
        idle = getattr(self, "_player_header_info_icon_idle", None)
        if not has_clip or tip == "No clip selected":
            btn.hide()
            btn.setEnabled(False)
            btn.setToolTip("No clip selected")
            if idle is not None:
                btn.setIcon(idle)
        else:
            btn.show()
            btn.setEnabled(True)
            btn.setToolTip(tip)
            if idle is not None and not btn.underMouse():
                btn.setIcon(idle)

    def refresh_player_header_layout(self, layout: str | None = None) -> None:
        """Apply Settings → Visual header layout (spacers + title meta) without restart."""
        from steempeg.ui.player_header_layout import (
            apply_player_header_layout,
            refresh_player_header_text,
            set_header_layout,
        )

        if layout is not None:
            set_header_layout(layout)
        apply_player_header_layout(self)
        refresh_player_header_text(self)
        self.refresh_player_header_info()

    def refresh_player_header_size(self, size: str | None = None) -> str:
        """Apply Settings → Visual player header S/M/L without restart."""
        from steempeg.ui.player_header_layout import apply_player_header_density
        from steempeg.ui.player_header_size import (
            get_player_header_size,
            set_player_header_size,
        )

        if size is not None:
            set_player_header_size(size)
        applied = get_player_header_size()
        dense = getattr(self, "_ui_density_player", None) or getattr(
            self, "_ui_density", None
        )
        try:
            apply_player_header_density(self, dense)
        except Exception:
            logging.exception("Player header size apply failed for %s", applied)
        # Portable queue chips re-read sized density for height / icon.
        try:
            from steempeg.ui.portable import chrome as portable_chrome

            if getattr(self, "btn_portable_add_clip", None) is not None:
                portable_chrome.refresh_portable_header_size(self)
        except Exception:
            pass
        return applied

    def refresh_player_layout_mode(self, mode: str | None = None) -> str:
        """Apply Settings → Visual player layout (Reunited / Fractured) without restart."""
        from steempeg.ui.layout_defaults import apply_player_layout_mode
        from steempeg.ui.player_layout import get_player_layout, set_player_layout

        if mode is not None:
            set_player_layout(mode)
        try:
            return apply_player_layout_mode(self, get_player_layout())
        except Exception:
            logging.exception("Player layout apply failed for %s", get_player_layout())
            return get_player_layout()

    def refresh_player_outline_mode(self, mode: str | None = None) -> str:
        """Apply Settings → Visual player outline without restart."""
        from steempeg.ui.layout_defaults import apply_player_layout_mode
        from steempeg.ui.player_outline import get_player_outline, set_player_outline

        if mode is not None:
            set_player_outline(mode)
        try:
            apply_player_layout_mode(self)
        except Exception:
            logging.exception("Player outline apply failed for %s", get_player_outline())
        return get_player_outline()

    def refresh_timeline_strip_size(self, size: str | None = None) -> str:
        """Apply Settings → Visual timeline strip S/M/L without restart."""
        from steempeg.ui.timeline_strip_size import (
            get_timeline_strip_size,
            set_timeline_strip_size,
        )

        if size is not None:
            set_timeline_strip_size(size)
        applied = get_timeline_strip_size()
        timeline = getattr(self, "custom_timeline", None)
        if timeline is not None and hasattr(timeline, "apply_strip_size"):
            try:
                timeline.apply_strip_size(applied)
            except Exception:
                logging.exception("Timeline strip size apply failed for %s", applied)
        return applied

    def refresh_markers_on_strip(self, enabled: bool | None = None) -> bool:
        """Apply Settings → Visual markers-on-strip overlay without restart."""
        from steempeg.ui.settings_prefs import (
            current_markers_on_strip,
            set_markers_on_strip,
        )

        if enabled is not None:
            set_markers_on_strip(enabled)
        applied = current_markers_on_strip()
        timeline = getattr(self, "custom_timeline", None)
        if timeline is not None and hasattr(timeline, "apply_strip_size"):
            try:
                # Re-apply metrics so TRACK_Y / canvas height follow the overlay flag.
                timeline.apply_strip_size()
            except Exception:
                logging.exception("Markers-on-strip apply failed for %s", applied)
        return applied

    def refresh_player_boost_ceilings(
        self,
        volume: int | None = None,
        speed: int | None = None,
    ) -> tuple[int, int]:
        """Apply Settings → Visual volume/speed boost ceilings without restart."""
        from steempeg.ui.player_boost import (
            get_speed_boost_ceiling,
            get_volume_boost_ceiling,
            set_speed_boost_ceiling,
            set_volume_boost_ceiling,
        )

        if volume is not None:
            set_volume_boost_ceiling(volume)
        if speed is not None:
            set_speed_boost_ceiling(speed)
        applied_vol = get_volume_boost_ceiling()
        applied_spd = get_speed_boost_ceiling()
        vol = getattr(self, "volume_control", None)
        if vol is not None and hasattr(vol, "apply_volume_ceiling"):
            try:
                vol.apply_volume_ceiling(applied_vol)
                # Re-push to mpv so a live ceiling change (or clamp) takes effect.
                if hasattr(self, "set_vlc_volume"):
                    self.set_vlc_volume(vol.slider.value())
            except Exception:
                logging.exception(
                    "Volume boost ceiling apply failed for %s", applied_vol
                )
        spd = getattr(self, "speed_control", None)
        if spd is not None and hasattr(spd, "apply_speed_ceiling"):
            try:
                spd.apply_speed_ceiling(applied_spd)
                if hasattr(self, "set_vlc_speed"):
                    self.set_vlc_speed(spd.slider.value())
            except Exception:
                logging.exception(
                    "Speed boost ceiling apply failed for %s", applied_spd
                )
        return applied_vol, applied_spd

    def _current_app_bg(self) -> str:
        """Background color for the current chrome theme."""
        from steempeg.ui import design_tokens as tok
        from steempeg.ui import ui_theme as ut

        if getattr(self, "_ui_theme_applied", False):
            return ut.chrome_colors_for_active()["app_bg"]
        return tok.chrome_theme_colors(getattr(self, "_chrome_theme", "default"))["app_bg"]

    def _shell_stylesheet(self, bg_color: str) -> str:
        """Window stylesheet: dialog background (+ tip chrome mirrored for safety)."""
        from steempeg.ui import design_tokens as tok

        return f"""
            QDialog#Dialog, QWidget#Dialog {{ background-color: {bg_color}; }}

            {tok.STYLE_TOOLTIP}
        """

    def apply_chrome_theme(self, name: str, persist: bool = True) -> None:
        """Switch the title bar / background color theme live."""
        from PySide6.QtGui import QColor, QPalette
        from steempeg.ui import design_tokens as tok

        if name not in tok.CHROME_THEMES:
            name = tok.DEFAULT_CHROME_THEME
        self._chrome_theme = name
        colors = tok.chrome_theme_colors(name)
        app_bg = colors["app_bg"]
        bar_bg = colors["title_bar"]

        palette = self.ui.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(app_bg))
        self.ui.setPalette(palette)
        self.ui.setStyleSheet(self._shell_stylesheet(app_bg))
        try:
            from steempeg.ui.design_tokens import apply_app_tooltip_style

            apply_app_tooltip_style()
        except Exception:
            pass

        # Shell wrappers created by install_title_bar (appShell + appContent).
        for attr, obj_name in (
            ("_custom_chrome_shell", "appShell"),
            ("_custom_content_wrap", "appContent"),
        ):
            widget = getattr(self.ui, attr, None)
            if widget is not None:
                widget.setStyleSheet(f"QWidget#{obj_name} {{ background-color: {app_bg}; }}")

        title_bar = getattr(self.ui, "title_bar", None)
        if title_bar is not None and hasattr(title_bar, "set_bar_color"):
            title_bar.set_bar_color(bar_bg)

        self._apply_dark_shell()

        if persist:
            self.save_user_settings("chrome_theme", name)

    def apply_ui_theme(self, name: str, persist: bool = True, *, preview: bool = False) -> None:
        """Switch Default / TrueDark / TrueDark OLED — tokens + shell surfaces."""
        from PySide6.QtGui import QColor, QPalette
        from steempeg.ui import ui_theme as ut
        from steempeg.ui.design_tokens import apply_app_tooltip_style

        name = ut.normalize_ui_theme(name)
        ut.apply_palette(name)
        self._ui_theme = name
        self._ui_theme_applied = True
        setattr(self.ui, "_ui_theme_applied", True)

        if name == ut.UI_THEME_DEFAULT:
            from steempeg.ui import design_tokens as tok

            self._chrome_theme = tok.DEFAULT_CHROME_THEME

        colors = ut.chrome_colors_for_active()
        app_bg = colors["app_bg"]
        bar_bg = colors["title_bar"]

        for attr, obj_name in (
            ("_custom_chrome_shell", "appShell"),
            ("_custom_content_wrap", "appContent"),
        ):
            widget = getattr(self.ui, attr, None)
            if widget is not None:
                widget.setStyleSheet(f"QWidget#{obj_name} {{ background-color: {app_bg}; }}")

        title_bar = getattr(self.ui, "title_bar", None)
        if title_bar is not None and hasattr(title_bar, "set_bar_color"):
            title_bar.set_bar_color(bar_bg)

        self._apply_dark_shell()
        self._refresh_ui_theme_surfaces(preview=preview)
        # App-level tip chrome (and palette ToolTipBase/Text) — also during live preview.
        try:
            apply_app_tooltip_style()
        except Exception:
            pass

        if preview:
            return

        from steempeg.ui.ui_density import COMFORT

        dense = getattr(self, "_ui_density", None) or COMFORT
        # Re-apply density chrome so footer composites, neo nav, queue, and render
        # panel combos pick up the new theme (Default stock QSS vs TrueDark tokens).
        self._apply_ui_density(dense)
        try:
            from steempeg.ui.layout_defaults import apply_player_layout_mode

            apply_player_layout_mode(self)
        except Exception:
            pass

        palette = self.ui.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(app_bg))
        self.ui.setPalette(palette)
        self.ui.setStyleSheet(self._shell_stylesheet(app_bg))
        try:
            apply_app_tooltip_style()
        except Exception:
            pass

        if persist:
            self.save_user_settings(ut.KEY_UI_THEME, name)

    def finalize_ui_theme_shell(self) -> None:
        """Root shell QSS after live preview — skips surface re-tint."""
        from PySide6.QtGui import QColor, QPalette

        from steempeg.ui import ui_theme as ut
        from steempeg.ui.design_tokens import apply_app_tooltip_style

        name = ut.get_ui_theme()
        colors = ut.chrome_colors_for_active()
        app_bg = colors["app_bg"]

        if name == ut.UI_THEME_DEFAULT:
            dense = getattr(self, "_ui_density", None)
            if dense is not None:
                self._apply_ui_density(dense)
                return

        palette = self.ui.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(app_bg))
        self.ui.setPalette(palette)
        self.ui.setStyleSheet(self._shell_stylesheet(app_bg))
        try:
            apply_app_tooltip_style()
        except Exception:
            pass

    @staticmethod
    def _fmt_dash_btn(
        template: str, *, font: int = 12, radius: int = 8, pad: str = "6px 14px"
    ) -> str:
        # Replace <<FONT>> before .format — raw placeholder makes Qt drop the whole QSS.
        return template.replace("<<FONT>>", tok.FONT_APP).format(
            font=font, radius=radius, pad=pad
        )

    def _refresh_dash_secondary_button_styles(self, dense) -> None:
        """Logs + Leave (non-deferred) — secondary button family in dark themes."""
        from steempeg.ui import ui_theme as ut

        pad = "1px 8px" if dense.compact else "6px 14px"
        radius = max(8, dense.dash_btn_h // 2)
        font = dense.dash_font

        btn_logs = getattr(self.ui, "btn_logs", None)
        if btn_logs is not None:
            btn_logs.setMinimumSize(0, 0)
            btn_logs.setFixedHeight(dense.dash_btn_h)
            if ut.get_ui_theme() != ut.UI_THEME_DEFAULT:
                btn_logs.setStyleSheet(
                    ut.dash_secondary_button_stylesheet(font=font, radius=radius, pad=pad)
                )
            else:
                template = getattr(self, "_dash_btn_style_logs", None)
                if template:
                    btn_logs.setStyleSheet(
                        self._fmt_dash_btn(template, font=font, radius=radius, pad=pad)
                    )

        leave_btn = getattr(self, "_btn_queue_leave_resume", None)
        if leave_btn is not None:
            try:
                leave_btn.setFixedHeight(dense.dash_btn_h)
                if hasattr(self, "_paint_desktop_queue_leave_resume"):
                    has_jobs = bool(getattr(self, "render_queue", None)) and len(
                        self.render_queue
                    ) > 0
                    deferred = bool(getattr(self, "_queue_scheme_deferred", False)) and has_jobs
                    self._paint_desktop_queue_leave_resume(leave_btn, deferred=deferred)
            except RuntimeError:
                self._btn_queue_leave_resume = None

    def _refresh_library_view_styles(self) -> None:
        """Re-tint clips + rendered list/grid chrome from active tokens."""
        from steempeg.ui.library.library_styles import (
            library_grid_stylesheet,
            library_table_stylesheet,
        )

        grid_qss = library_grid_stylesheet()
        table_qss = library_table_stylesheet()
        for attr in ("grid_clips", "grid_rendered"):
            view = getattr(self, attr, None)
            if view is not None:
                view.setStyleSheet(grid_qss)
        ui = getattr(self, "ui", None)
        if ui is not None and hasattr(ui, "table_clips"):
            ui.table_clips.setStyleSheet(table_qss)
        if hasattr(self, "table_rendered"):
            self.table_rendered.setStyleSheet(table_qss)

    def _refresh_open_settings_dialogs(self) -> None:
        """Live-tint open Settings and other themeable dialogs during theme preview / Save."""
        from PySide6.QtWidgets import QApplication, QDialog

        for widget in QApplication.topLevelWidgets():
            if not isinstance(widget, QDialog) or not widget.isVisible():
                continue
            apply = getattr(widget, "apply_ui_theme_chrome", None)
            if not callable(apply):
                continue
            try:
                apply()
            except Exception:
                pass

    def _refresh_ui_theme_surfaces(self, *, preview: bool = False) -> None:
        """Re-tint major chrome widgets after a UI theme switch (no layout/mask changes)."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPalette
        from steempeg.ui import ui_theme as ut
        from steempeg.ui.design_tokens import with_tooltip_style
        from steempeg.ui.widgets.combo_chrome import settings_panel_stylesheet

        # Clip info is built once at open — close so the next show picks up tokens.
        clip_info = getattr(self, "_clip_info_popup", None)
        if clip_info is not None:
            try:
                clip_info.close()
            except RuntimeError:
                pass
            self._clip_info_popup = None

        p = ut.active_palette()

        neo = getattr(self, "neo_wrapper", None)
        if neo is not None:
            neo.setStyleSheet(ut.neo_wrapper_stylesheet())

        scroll = getattr(self, "right_scroll", None)
        if scroll is not None:
            scroll.setStyleSheet(ut.neo_settings_scroll_stylesheet())
            from steempeg.ui.widgets.vertical_scrollbar import (
                ensure_steempg_vertical_scrollbar,
                settings_scrollbar_chrome,
            )

            ensure_steempg_vertical_scrollbar(
                scroll, chrome=settings_scrollbar_chrome()
            )
            vp = scroll.viewport()
            if vp is not None:
                vp.setAutoFillBackground(True)
                pal = vp.palette()
                qc = QColor(p.bg_settings_panel)
                for group in (
                    QPalette.ColorGroup.Active,
                    QPalette.ColorGroup.Inactive,
                    QPalette.ColorGroup.Disabled,
                ):
                    pal.setColor(group, QPalette.ColorRole.Window, qc)
                    pal.setColor(group, QPalette.ColorRole.Base, qc)
                vp.setPalette(pal)

        if hasattr(self.ui, "settings_tabs"):
            self.ui.settings_tabs.setStyleSheet(
                ut.neo_settings_tabs_stylesheet(settings_panel_stylesheet())
            )
            for i in range(self.ui.settings_tabs.count()):
                page = self.ui.settings_tabs.widget(i)
                if page is None:
                    continue
                obj = page.objectName()
                if obj:
                    page.setStyleSheet(ut.neo_tab_page_stylesheet(obj))
                else:
                    page.setStyleSheet(
                        f"background-color: {p.bg_settings_panel}; border: none;"
                    )

        for btn in getattr(self, "neo_nav_buttons", []) or []:
            btn.setStyleSheet(ut.neo_nav_pill_stylesheet())

        header = getattr(self, "player_header_frame", None)
        if header is not None:
            from steempeg.ui.player_outline import player_outline_immersive

            immersive = player_outline_immersive(self)
            header.setStyleSheet(
                ut.player_header_stylesheet(
                    force_outline=False if immersive else None
                )
            )

        vw = getattr(self, "video_wrapper", None)
        if vw is not None:
            from steempeg.ui.player_outline import player_outline_immersive

            immersive = player_outline_immersive(self)
            portable_theatre = bool(
                getattr(self, "_portable_shell", False)
                and getattr(self, "is_theater", False)
            )
            if immersive:
                vw.setStyleSheet(
                    ut.player_video_wrapper_stylesheet(
                        background="black",
                        chrome_outline=False,
                    )
                )
            elif portable_theatre:
                vw.setStyleSheet(
                    ut.player_video_wrapper_stylesheet(background="black")
                )
            else:
                vw.setStyleSheet(ut.player_video_wrapper_stylesheet())

        placeholder = getattr(self, "placeholder_frame", None)
        if placeholder is not None:
            placeholder.setStyleSheet(ut.player_placeholder_canvas_stylesheet())

        place_card = getattr(self, "place_card", None)
        if place_card is not None:
            place_card.setStyleSheet(ut.player_placeholder_card_stylesheet())

        lib = getattr(self, "library_views_container", None)
        if lib is not None:
            lib.setStyleSheet(ut.elevated_panel_stylesheet())

        dash = getattr(self, "render_dashboard", None)
        if dash is not None:
            dash.setStyleSheet(
                ut.elevated_panel_stylesheet(object_name="renderDashboard")
                + " QFrame#renderDashboard QLabel { border: none; background: transparent; }"
            )

        footer = getattr(self, "_footer_mega_pill", None)
        if footer is not None:
            footer.setStyleSheet(ut.footer_pill_stylesheet())

        dense = getattr(self, "_ui_density", None)
        from steempeg.ui.ui_density import COMFORT, toolbar_mega_pill_style

        if dense is None:
            dense = COMFORT

        self._apply_library_footer_theme(dense)

        lib_pill = getattr(self, "library_toolbar_pill", None)
        if lib_pill is not None:
            lib_pill.setStyleSheet(
                toolbar_mega_pill_style(dense, object_name="libraryToolbarPill")
            )

        chrome = getattr(self, "view_mode_chrome", None)
        if chrome is not None:
            panel = getattr(self, "_library_panel_mode", "clips")
            mode = getattr(self, "_clips_view_mode", None) or getattr(
                self, "current_view_mode", "grid"
            )
            if panel == "rendered":
                mode = getattr(self, "_rendered_view_mode", "grid")
            elif panel == "screenshots":
                mode = "grid"
            chrome.set_mode(mode, emit=False)
            chrome.set_grid_only(panel == "screenshots")
            chrome.apply_density(dense)
            self.toggle_style_active = chrome.toggle_style_active
            self.toggle_style_inactive = chrome.toggle_style_inactive

        tabs = getattr(self, "_library_tabs", None) or {}
        for tab in tabs.values():
            if hasattr(tab, "_apply_style"):
                tab._apply_style()

        self._apply_library_add_button_theme(dense)

        filt = getattr(self, "btn_filter_pill", None)
        if filt is not None and hasattr(filt, "apply_density"):
            filt.apply_density(dense)

        for menu_attr in ("filter_menu", "rendered_filter_menu", "screenshots_filter_menu"):
            menu = getattr(self, menu_attr, None)
            if menu is not None and hasattr(menu, "apply_density"):
                try:
                    menu.apply_density(dense)
                except Exception:
                    pass

        from steempeg.ui.widgets.combo_chrome import apply_dark_combo_popup, compact_combo_stylesheet

        combo = getattr(self, "combo_sort", None)
        if combo is not None:
            combo.setStyleSheet(compact_combo_stylesheet(settings_popup=True, dense=dense))
            apply_dark_combo_popup(combo, dense=dense)

        self._refresh_dash_secondary_button_styles(dense)

        if hasattr(self, "refresh_logs_menu_chrome"):
            try:
                self.refresh_logs_menu_chrome()
            except Exception:
                pass

        timeline = getattr(self, "custom_timeline", None)
        if timeline is not None and hasattr(timeline, "_apply_timeline_chrome_stylesheet"):
            timeline._apply_timeline_chrome_stylesheet()
            canvas = getattr(timeline, "canvas", None)
            if canvas is not None:
                canvas.update()
            overview = timeline.horizontalScrollBar()
            if overview is not None:
                overview.update()

        queue_panel = getattr(self, "render_queue_panel", None)
        if queue_panel is not None and hasattr(queue_panel, "apply_ui_theme_chrome"):
            try:
                queue_panel.apply_ui_theme_chrome()
            except Exception:
                pass

        # Portable Render sheet — Queue rail + management strip (even if parked).
        for attr in ("_portable_render_strip", "_portable_queue_sidebar"):
            w = getattr(self, attr, None)
            if w is not None and hasattr(w, "apply_ui_theme_chrome"):
                try:
                    w.apply_ui_theme_chrome()
                except Exception:
                    pass
        sheet = getattr(self, "_portable_render_sheet_dlg", None)
        if sheet is not None and hasattr(sheet, "apply_ui_theme_chrome"):
            try:
                sheet.apply_ui_theme_chrome()
            except Exception:
                pass

        hud = getattr(self, "player_footer_frame", None)
        if hud is not None:
            from steempeg.ui.player_outline import player_outline_immersive

            immersive = player_outline_immersive(self)
            hud.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            hud.setStyleSheet(
                with_tooltip_style(
                    ut.player_footer_stylesheet(
                        force_outline=False if immersive else None
                    )
                    + _PLAYBACK_BUTTONS_QSS
                )
            )

        self._refresh_player_footer_chrome(dense)

        if hasattr(self, "_refresh_immersive_esc_hint_chrome"):
            try:
                self._refresh_immersive_esc_hint_chrome()
            except Exception:
                pass

        from steempeg.ui.render_panel import (
            apply_render_panel_theme_chrome,
            apply_settings_panel_density,
        )

        apply_render_panel_theme_chrome(self.ui)
        apply_settings_panel_density(self.ui, dense)

        if hasattr(self, "refresh_export_presets_list"):
            try:
                self.refresh_export_presets_list()
            except Exception:
                pass

        self._refresh_library_view_styles()

        if hasattr(self, "refresh_clip_card_styles"):
            try:
                # Re-bake plate/footer/border from active theme tokens — edge-role
                # sync alone skips reapply when row roles are unchanged.
                self.refresh_clip_card_styles()
            except Exception:
                pass

        grid_shots = getattr(self, "grid_screenshots", None)
        if grid_shots is not None:
            try:
                for i in range(grid_shots.count()):
                    item = grid_shots.item(i)
                    if item is None:
                        continue
                    w = grid_shots.itemWidget(item)
                    if w is not None:
                        w.update()
            except Exception:
                pass

        self._refresh_open_settings_dialogs()

    def _refresh_player_footer_chrome(self, dense=None) -> None:
        """Re-tint volume/speed round buttons and footer pill clusters."""
        from steempeg.ui import ui_theme as ut
        from steempeg.ui.design_tokens import (
            STYLE_TRIM_BUTTON,
            STYLE_TRIM_CANCEL_BUTTON,
            reattach_tooltip_style,
            with_tooltip_style,
        )
        from steempeg.ui.ui_density import COMFORT

        if dense is None:
            dense = getattr(self, "_ui_density", None) or COMFORT

        chip = int(getattr(dense, "chrome_chip", 40) or 40)
        chip_r = chip // 2

        for ctrl_attr in ("volume_control", "speed_control"):
            ctrl = getattr(self, ctrl_attr, None)
            if ctrl is not None and hasattr(ctrl, "apply_density"):
                ctrl.apply_density(dense)

        for pill_attr in ("pill_container", "trim_tools_pill", "marker_pill"):
            frame = getattr(self, pill_attr, None)
            if frame is not None:
                frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                frame.setStyleSheet(ut.player_chrome_pill_stylesheet(radius=chip_r))

        # Local QSS embeds QToolTip — re-bake after theme switch.
        _pill_inner = with_tooltip_style(
            "QPushButton { background: transparent; border-radius: 20px; border: none; }\n"
            "QPushButton:hover { background: rgba(255, 255, 255, 40); }"
        )
        _pill_pressed = with_tooltip_style(
            "QPushButton { background: transparent; border-radius: 20px; border: none; }\n"
            "QPushButton:hover { background: rgba(255, 255, 255, 40); }\n"
            "QPushButton:pressed { background: rgba(255, 255, 255, 60); }"
        )
        for attr in ("btn_theater", "btn_fullscreen"):
            btn = getattr(self, attr, None)
            if btn is not None:
                try:
                    btn.setStyleSheet(_pill_inner)
                except RuntimeError:
                    pass
        for attr in (
            "btn_clipcut1",
            "btn_clipcut2",
            "btn_clipcutback",
            "btn_screenshot",
            "btn_marker_settings",
        ):
            btn = getattr(self, attr, None)
            if btn is not None:
                try:
                    btn.setStyleSheet(_pill_pressed)
                except RuntimeError:
                    pass
        for attr in ("btn_add_marker",):
            btn = getattr(self, attr, None)
            if btn is not None:
                try:
                    btn.setStyleSheet(_pill_inner)
                except RuntimeError:
                    pass

        btn_trim = getattr(self, "btn_trim", None)
        if btn_trim is not None:
            try:
                tl = getattr(self, "custom_timeline", None)
                cancel = bool(tl is not None and getattr(tl, "is_trim_mode", False))
                if not cancel:
                    cancel = "cancel" in (btn_trim.text() or "").strip().lower()
                btn_trim.setStyleSheet(
                    STYLE_TRIM_CANCEL_BUTTON if cancel else STYLE_TRIM_BUTTON
                )
            except RuntimeError:
                pass

        info = getattr(self, "btn_player_header_info", None)
        if info is not None:
            reattach_tooltip_style(info)

        help_btn = getattr(getattr(self, "ui", None), "btn_preset_help", None)
        if help_btn is not None:
            reattach_tooltip_style(help_btn)

        tl = getattr(self, "custom_timeline", None)
        if tl is not None and hasattr(tl, "apply_tooltip_theme"):
            try:
                tl.apply_tooltip_theme()
            except Exception:
                pass

        for attr in ("btn_add_clip", "btn_portable_render", "btn_render"):
            btn = getattr(self, attr, None)
            if btn is not None:
                reattach_tooltip_style(btn)

    def _apply_dark_shell(self):
        """Paint every major shell widget dark so unsettled layout never flashes white."""
        dark = self._current_app_bg()
        shell = f"background-color: {dark};"
        for attr in ("left_panel", "right_panel"):
            panel = getattr(self.ui, attr, None)
            if panel is not None:
                panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                panel.setAutoFillBackground(True)
                panel.setStyleSheet(shell)
        # Theme-aware visible handles first; Like a Portable may hide them after.
        try:
            from steempeg.ui.portable_splitter_reveal import (
                paint_desktop_splitter_handles,
                sync_portable_splitter_reveal,
            )

            paint_desktop_splitter_handles(self)
            sync_portable_splitter_reveal(self)
        except Exception:
            from steempeg.ui.layout_defaults import HORIZONTAL_SPLITTER_STYLESHEET

            splitter_qss = f"QSplitter {{ {shell} }} {HORIZONTAL_SPLITTER_STYLESHEET}"
            for splitter_attr in ("main_splitter", "right_h_splitter", "main_v_splitter"):
                splitter = getattr(self.ui, splitter_attr, None) or getattr(
                    self, splitter_attr, None
                )
                if splitter is not None:
                    splitter.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                    splitter.setStyleSheet(splitter_qss)

    def _sync_startup_layout(self):
        """Re-apply splitter sizes once the maximized window has real geometry."""
        self._ui_density = None  # force chrome density for the real window size
        self._apply_startup_splitter_sizes()
        self._refresh_player_footer_chrome()
        if hasattr(self, "apply_desktop_render_layout"):
            self.apply_desktop_render_layout()
        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()
        if hasattr(self, "_restore_library_ui_state"):
            self._restore_library_ui_state()
            # Second restore runs under the startup settle veil (post-maximize),
            # not as a naked 500ms flash of tab/footer chrome after show.
            if not getattr(self, "_startup_settle_active", False):
                QTimer.singleShot(500, self._restore_library_ui_state)
        if hasattr(self, "_library_ui_persist_ready"):
            QTimer.singleShot(250, lambda: setattr(self, "_library_ui_persist_ready", True))
        self.refresh_render_queue_panel(sync_splitter=True)
        self._ensure_startup_queue_open()
        self._start_startup_scans_after_restore()

    def _persist_queue_panel_open(self, open_: bool) -> None:
        """Remember Render Queue open/closed (always, even when full layout recall is off)."""
        if hasattr(self, "save_layout_setting"):
            self.save_layout_setting("queue_panel_open", bool(open_))

    def _restore_queue_panel_collapsed_from_settings(self) -> None:
        """Seed ``_queue_user_collapsed`` from last session before splitter sync."""
        jobs = getattr(self, "render_queue", None)
        if jobs is None or len(jobs) == 0:
            self._queue_user_collapsed = False
            self._queue_sync_had_jobs = False
            return
        # Jobs already exist from disk — not a fresh enqueue this session.
        self._queue_sync_had_jobs = True
        saved = None
        if hasattr(self, "get_layout_setting"):
            saved = self.get_layout_setting("queue_panel_open", None)
        if saved is None:
            # Legacy installs: open when jobs exist (previous always-open behavior).
            self._queue_user_collapsed = False
            return
        self._queue_user_collapsed = not bool(saved)

    def _queue_panel_should_open_on_startup(self) -> bool:
        """True when last session left Render Queue open (or legacy: jobs exist)."""
        jobs = getattr(self, "render_queue", None)
        if jobs is None or len(jobs) == 0:
            return False
        saved = None
        if hasattr(self, "get_layout_setting"):
            saved = self.get_layout_setting("queue_panel_open", None)
        if saved is None:
            return True
        return bool(saved)

    def _ensure_startup_queue_open(self) -> None:
        """Restore Render Queue open/closed after geometry settles.

        Early open against a fake splitter total stretches to ~half the column
        once the window maximizes; always re-apply the saved pixel width here
        when the pane should be open.
        """
        if getattr(self, "_portable_shell", False):
            return
        if getattr(self, "is_theater", False) or getattr(self, "is_fullscreen", False):
            return
        jobs = getattr(self, "render_queue", None)
        if jobs is None or len(jobs) == 0:
            return
        # Mark had-jobs so a later refresh does not treat this as a fresh enqueue.
        self._queue_sync_had_jobs = True
        if not self._queue_panel_should_open_on_startup():
            self._queue_user_collapsed = True
            rhs = getattr(self, "right_h_splitter", None)
            if rhs is not None:
                total = sum(rhs.sizes()) or int(rhs.width() or 0) or 1
                rhs.setSizes([max(int(total), 1), 0])
            if hasattr(self, "sync_queue_minimum"):
                self.sync_queue_minimum()
            return
        self._queue_user_collapsed = False
        panel = getattr(self, "render_queue_panel", None)
        if panel is not None:
            panel.show()
        if hasattr(self, "_open_queue_in_right_splitter"):
            self._open_queue_in_right_splitter()

    def _start_startup_scans_after_restore(self) -> None:
        """Kick off initial library scans once the shell is stable."""
        if not getattr(self, "_start_startup_scans_pending", False):
            return
        self._start_startup_scans_pending = False

        settings = {}
        if hasattr(self, "load_user_settings"):
            try:
                settings = self.load_user_settings() or {}
            except Exception:
                settings = {}
        from steempeg.ui.settings_prefs import (
            SCAN_CACHE,
            SCAN_FULL,
            SCAN_SMART,
            load_startup_library_scan,
        )

        mode = load_startup_library_scan(settings)

        def _restore_session_side_libraries(*, restored_clips: bool) -> None:
            """Paint Rendered + Screenshots from session JSON (Skip / Smart)."""
            restored_rendered = False
            if hasattr(self, "restore_rendered_from_session_cache"):
                restored_rendered = bool(self.restore_rendered_from_session_cache())
            restored_shots = False
            if hasattr(self, "restore_screenshots_from_session_cache"):
                # Defer past showMaximized — sync paint of a unified Steam
                # shelf (thousands of cards) blocked the window for minutes.
                # Startup settle veil stays up past this tick so chrome does
                # not flash while placeholders land.
                def _restore_shots():
                    nonlocal restored_shots
                    restored_shots = bool(
                        self.restore_screenshots_from_session_cache()
                    )
                    if (
                        not restored_clips
                        and restored_shots
                        and hasattr(self, "update_status_indicator")
                        and not getattr(self, "_startup_library_scan_active", False)
                    ):
                        self.update_status_indicator("Ready", "ready")

                QTimer.singleShot(300, _restore_shots)
            # Clips restore clears startup + Ready itself when it succeeds.
            if not restored_clips:
                self._startup_library_scan_active = False
                if hasattr(self, "update_status_indicator"):
                    if restored_rendered or restored_shots:
                        self.update_status_indicator("Ready", "ready")
                    elif getattr(self, "clips_folders", None):
                        self.update_status_indicator(
                            "Ready — no library snapshot", "ready"
                        )
                    else:
                        self.update_status_indicator(
                            "Ready — no library folders", "ready"
                        )

        def _start_cache_style(*, append_new: bool, require_exists: bool, label: str) -> bool:
            logging.info("Startup library scan: %s", label)
            self._defer_rendered_scan_until_clips_done = False
            restored_clips = False
            if getattr(self, "clips_folders", None):
                self._startup_library_scan_active = True
                if hasattr(self, "restore_clips_from_session_cache"):
                    restored_clips = bool(
                        self.restore_clips_from_session_cache(
                            append_new=append_new,
                            require_exists=require_exists,
                        )
                    )
            _restore_session_side_libraries(restored_clips=restored_clips)
            return restored_clips

        def _start():
            # Clips first; Rendered is deferred until clips finishes (Quick/Full).
            if mode == SCAN_CACHE:
                _start_cache_style(
                    append_new=True,
                    require_exists=False,
                    label="Skip (session snapshot)",
                )
                return

            if mode == SCAN_SMART:
                from steempeg.library.clips_library_cache import (
                    library_fingerprint_unchanged,
                )

                roots = list(getattr(self, "clips_folders", None) or [])
                unchanged = False
                if roots:
                    try:
                        unchanged = library_fingerprint_unchanged(
                            getattr(self, "cache_dir", None),
                            roots,
                        )
                    except Exception:
                        logging.debug(
                            "Smart Launch fingerprint check failed",
                            exc_info=True,
                        )
                        unchanged = False

                if unchanged:
                    _start_cache_style(
                        append_new=False,
                        require_exists=False,
                        label="Smart Launch (unchanged — session snapshot)",
                    )
                    return

                # Fingerprint missing/corrupt or roots changed: paint cache first,
                # drop gone folders, then quietly append only new clip paths.
                restored = False
                if roots and hasattr(self, "restore_clips_from_session_cache"):
                    restored = _start_cache_style(
                        append_new=True,
                        require_exists=True,
                        label="Smart Launch (changed — snapshot + incremental)",
                    )
                if restored:
                    return

                logging.info(
                    "Startup library scan: Smart Launch (no snapshot — Quick)"
                )
                if roots:
                    self._startup_library_scan_active = True
                    self._defer_rendered_scan_until_clips_done = True
                    self.scan_clips(fast=True)
                elif hasattr(self, "scan_rendered_outputs"):
                    self.scan_rendered_outputs()
                if hasattr(self, "restore_screenshots_from_session_cache"):
                    QTimer.singleShot(300, self.restore_screenshots_from_session_cache)
                return

            # Full: after folders + ffprobe, also refresh Steam icons/names
            # (same as Refresh ▾) once the list is painted — see library controller.
            self._startup_refresh_steam_meta = mode == SCAN_FULL
            if getattr(self, "clips_folders", None):
                self._startup_library_scan_active = True
                self._defer_rendered_scan_until_clips_done = True
                if mode == SCAN_FULL:
                    logging.info(
                        "Startup library scan: Full "
                        "(folders + ffprobe + Steam icons/names)"
                    )
                else:
                    logging.info(
                        "Startup library scan: Quick (folders + cached health)"
                    )
                self.scan_clips(fast=(mode != SCAN_FULL))
            elif hasattr(self, "scan_rendered_outputs"):
                self._startup_refresh_steam_meta = False
                self.scan_rendered_outputs()
            # Screenshots: after show + processEvents settle (not singleShot(0)).
            if hasattr(self, "restore_screenshots_from_session_cache"):
                QTimer.singleShot(300, self.restore_screenshots_from_session_cache)

        # Skip / Smart: paint synchronously while the window is still hidden so the
        # first frame is already Ready (no post-show "Loading render history…").
        # Quick/Full: defer one tick so maximize geometry can settle first.
        if mode in (SCAN_CACHE, SCAN_SMART):
            _start()
        else:
            QTimer.singleShot(0, _start)

    def on_main_window_resized(self):
        """Keep panel minimums + chrome density in sync with window width."""
        # Mins must track live; density restyle is deferred so continuous
        # lerp doesn't thrash queue cards / DWM on every pixel.
        self._apply_responsive_layout_mins(apply_density=False)
        timer = getattr(self, "_density_resize_timer", None)
        defer_ms = int(getattr(self, "_density_resize_defer_ms", 120) or 120)
        # While the startup veil is up, keep density flushing immediately so the
        # post-maximize restyle lands under the cover — not 120ms after unveil.
        if not getattr(self, "_startup_settle_active", False):
            self._density_resize_defer_ms = 120
        if timer is None:
            from PySide6.QtCore import QTimer

            timer = QTimer(self.ui if hasattr(self, "ui") else None)
            timer.setSingleShot(True)
            timer.timeout.connect(self._flush_ui_density_after_resize)
            self._density_resize_timer = timer
        timer.setInterval(max(0, defer_ms))
        timer.start()

    def _flush_ui_density_after_resize(self):
        self._apply_responsive_layout_mins(apply_density=True)

    def _apply_responsive_layout_mins(self, *, apply_density: bool = True):
        """Lerp panel mins + chrome density with window width + physical PPI."""
        from steempeg.ui.layout_defaults import left_panel_min_width
        from steempeg.ui.ui_density import chrome_equal, density_for_width

        w = int(self.ui.width() or 0)
        if w <= 0:
            if apply_density:
                self._refresh_player_footer_chrome()
            from steempeg.ui.player.controls.adaptive_trim_tools import (
                sync_trim_tools_placement,
            )

            sync_trim_tools_placement(self)
            return

        host = self.ui
        left_min = left_panel_min_width(w, widget=host)

        if hasattr(self.ui, "left_panel") and self.ui.left_panel is not None:
            self.ui.left_panel.setMinimumWidth(left_min)
        # Queue min: Clips-style floor when open, PANE_FREED when shut — never a
        # blind 0 (that let the list/toolbar squash past MIN_QUEUE_*).
        if hasattr(self, "sync_queue_minimum"):
            self.sync_queue_minimum()

        # Clamp splitter sizes to new mins without resetting to comfort defaults.
        self._clamp_splitters_to_mins(left_min=left_min)

        if not apply_density:
            from steempeg.ui.player.controls.adaptive_trim_tools import (
                sync_trim_tools_placement,
            )

            sync_trim_tools_placement(self)
            return

        # Portable has no splitters / Deck density — keep comfort chrome. Only the
        # Render + Clips Manager sheet *windows* scale to the shell footprint.
        if getattr(self, "_portable_shell", False):
            from steempeg.ui.ui_density import COMFORT

            dense = COMFORT
        else:
            dense = density_for_width(w, widget=host)
        prev = getattr(self, "_ui_density", None)
        # Ignore float scale — otherwise every resize pixel restyles the whole UI
        # and rebuilds queue cards (DWM ghosts + floating text scraps).
        if chrome_equal(prev, dense):
            from steempeg.ui.player.controls.adaptive_trim_tools import (
                sync_trim_tools_placement,
            )

            sync_trim_tools_placement(self)
            return
        self._ui_density = dense
        self._apply_ui_density(dense)
        from steempeg.ui.player.controls.adaptive_trim_tools import (
            sync_trim_tools_placement,
        )

        sync_trim_tools_placement(self)

    def _on_main_splitter_moved(self, _pos: int = 0, _index: int = 0) -> None:
        """Debounce kiss-snap when Clips pushes into the player column."""
        self._on_right_h_splitter_moved()

    def _on_main_v_splitter_moved(self, _pos: int = 0, _index: int = 0) -> None:
        """Debounce-persist Desktop player↔settings dock height (not Like a Portable glue)."""
        if hasattr(self, "_desktop_render_layout_is_portable_like"):
            try:
                if self._desktop_render_layout_is_portable_like():
                    return
            except Exception:
                pass
        timer = getattr(self, "_main_v_persist_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer

            timer = QTimer(self.ui if hasattr(self, "ui") else None)
            timer.setSingleShot(True)
            timer.setInterval(150)
            timer.timeout.connect(self._persist_desktop_main_v_splitter_sizes)
            self._main_v_persist_timer = timer
        timer.start()

    def _desktop_v_splitter_sizes_are_persistable(self, sizes) -> bool:
        """True when sizes look like a real Desktop neo dock, not dash-only glue."""
        if not sizes or len(sizes) < 2:
            return False
        if getattr(self, "is_theater", False) or getattr(self, "is_fullscreen", False):
            return False
        if getattr(self, "_portable_shell", False):
            return False
        if hasattr(self, "_desktop_render_layout_is_portable_like"):
            try:
                if self._desktop_render_layout_is_portable_like():
                    return False
            except Exception:
                pass
        bottom = int(sizes[1])
        if bottom <= 80:
            return False
        dash_h = 120
        if hasattr(self, "_dash_only_bottom_height"):
            try:
                dash_h = max(int(self._dash_only_bottom_height()), 1)
            except Exception:
                dash_h = 120
        # Glue / near-glue must not overwrite the Desktop preference.
        if bottom <= dash_h + 48:
            return False
        return True

    def _persist_desktop_main_v_splitter_sizes(self, sizes=None) -> None:
        """Save It's a Desktop v-dock sizes; ignore Portable-like glue heights."""
        v_split = getattr(self, "main_v_splitter", None)
        if v_split is None or not hasattr(self, "save_layout_setting"):
            return
        live = list(sizes) if sizes is not None else list(v_split.sizes())
        if not self._desktop_v_splitter_sizes_are_persistable(live):
            return
        self.save_layout_setting(
            "main_v_splitter_sizes", [int(live[0]), int(live[1])]
        )

    def _apply_desktop_main_v_splitter_sizes(self) -> None:
        """Restore saved Desktop v-dock (or a tall default) onto main_v_splitter."""
        from steempeg.ui.layout_defaults import (
            default_main_v_splitter_sizes,
            scale_main_v_splitter_sizes,
        )

        v_split = getattr(self, "main_v_splitter", None)
        if v_split is None:
            return
        if hasattr(self, "_desktop_render_layout_is_portable_like"):
            try:
                if self._desktop_render_layout_is_portable_like():
                    return
            except Exception:
                pass
        ui = getattr(self, "ui", None)
        avail_w = int((ui.width() if ui is not None else 0) or 0)
        avail_h = int((ui.height() if ui is not None else 0) or 0)
        default_v = default_main_v_splitter_sizes(avail_w, avail_h, widget=ui)
        saved = default_v
        if hasattr(self, "get_layout_setting"):
            try:
                saved = self.get_layout_setting("main_v_splitter_sizes", default_v)
            except Exception:
                saved = default_v
        total = sum(v_split.sizes()) if sum(v_split.sizes()) > 0 else int(v_split.height() or 0)
        total = max(int(total), 1)
        v_split.setSizes(
            scale_main_v_splitter_sizes(saved, total, window_height=avail_h or total)
        )

    def _desktop_v_splitter_looks_minimal(self) -> bool:
        """True when the bottom dock is crushed / dash-height (not a real neo pane)."""
        v_split = getattr(self, "main_v_splitter", None)
        if v_split is None:
            return False
        sizes = v_split.sizes()
        if not sizes or len(sizes) < 2:
            return True
        bottom = int(sizes[1])
        if bottom <= 0:
            return True
        dash_h = 120
        if hasattr(self, "_dash_only_bottom_height"):
            try:
                dash_h = max(int(self._dash_only_bottom_height()), 1)
            except Exception:
                dash_h = 120
        return bottom <= dash_h + 48

    def _on_right_h_splitter_moved(self, _pos: int = 0, _index: int = 0) -> None:
        """Debounced snap: collapse queue / player scraps after drag ends.

        Never arm the timer while a handle drag is live — mid-hold free→close→reopen
        used to get ``sync_queue_minimum`` floor slapped on after 100ms pauses
        («свиток» then sudden min-open). Snap is scheduled from drag-end instead.
        """
        if getattr(self, "_splitter_dragging", False):
            return
        timer = getattr(self, "_right_h_snap_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer

            timer = QTimer(self.ui if hasattr(self, "ui") else None)
            timer.setSingleShot(True)
            timer.setInterval(100)
            timer.timeout.connect(self._snap_right_h_splitter_after_drag)
            self._right_h_snap_timer = timer
        timer.start()

    def _snap_right_h_splitter_after_drag(self) -> None:
        """Finish a near-kiss: zero scrap panes. Never inflate the player back."""
        if getattr(self, "_splitter_dragging", False):
            return
        rhs = getattr(self, "right_h_splitter", None)
        panel = getattr(self, "render_queue_panel", None)
        if rhs is None or panel is None:
            return
        if getattr(self, "is_theater", False) or getattr(self, "is_fullscreen", False):
            return
        sizes = rhs.sizes()
        if len(sizes) < 2:
            return
        total = sum(sizes) if sum(sizes) > 0 else int(rhs.width() or 0)
        player_w = int(sizes[0])
        queue_w = int(sizes[1])
        if total <= 0:
            return

        # Queue dragged shut → fully close.
        if queue_w <= 0 or queue_w < 48:
            if queue_w != 0:
                rhs.setSizes([max(int(total), 1), 0])
            jobs = getattr(self, "render_queue", None)
            if jobs is not None and len(jobs) > 0:
                self._queue_user_collapsed = True
            if hasattr(self, "_persist_queue_panel_open"):
                self._persist_queue_panel_open(False)
            # Player scrap with the queue already shut → finish the kiss. Zeroing
            # the whole column instead used to take the right handle down with
            # it, leaving no way to pull the queue back out.
            sizes = rhs.sizes()
            player_w = int(sizes[0]) if len(sizes) >= 2 else 0
            if 0 < player_w < 48:
                self.kiss_right_column_shut()
            self.sync_queue_minimum()
            return

        self._queue_user_collapsed = False
        if hasattr(self, "_persist_queue_panel_open"):
            self._persist_queue_panel_open(True)
        # Player scrap between Clips handle and Queue handle → complete the kiss.
        if 0 < player_w < 48:
            rhs.setSizes([0, max(int(total), 1)])
        else:
            # Remember the open width the user just left (always, not only on quit).
            live_q = int(rhs.sizes()[1]) if len(rhs.sizes()) >= 2 else queue_w
            if live_q > 48:
                self.save_layout_setting("queue_panel_width", live_q)
        self.sync_queue_minimum()
        # Leave/Resume is explicit only (button or queue-card click) — never
        # auto-Resume from resizing or reopening the right splitter.

    def _clamp_splitters_to_mins(self, *, left_min: int | None = None) -> None:
        """Keep Clips floor only — never re-inflate a kissed-away player column."""
        from steempeg.ui.layout_defaults import left_panel_min_width

        if left_min is None:
            w = int(self.ui.width() or 0) if getattr(self, "ui", None) else 0
            left_min = left_panel_min_width(w, widget=getattr(self, "ui", None)) if w else 360

        rhs = getattr(self, "right_h_splitter", None)
        # Only snap microscopic queue scraps shut. Do NOT push player back up to
        # PLAYER_COLUMN_FLOOR — that was the constant bounce/lag on kiss.
        if rhs is not None:
            sizes = rhs.sizes()
            total = sum(sizes) if sum(sizes) > 0 else int(rhs.width() or 0)
            if total > 0 and len(sizes) >= 2 and 0 < sizes[1] < 48:
                rhs.setSizes([max(int(total), 1), 0])

        main = getattr(self.ui, "main_splitter", None)
        if main is not None:
            sizes = main.sizes()
            total = sum(sizes)
            if total > 0 and len(sizes) >= 2:
                left = int(sizes[0])
                # Soft Clips floor only when the right column still has room.
                # Allow a full kiss (right ≈ 0) without yanking left back.
                if left < left_min and sizes[1] > 48:
                    left = min(left_min, max(0, total - 48))
                    right = total - left
                    if left != sizes[0] or right != sizes[1]:
                        main.setSizes([left, right])

        v_split = getattr(self, "main_v_splitter", None)
        if v_split is not None:
            from steempeg.ui.layout_defaults import (
                main_v_splitter_max_bottom,
                restore_v_splitter_sizes,
            )

            h = int(self.ui.height() or 0)
            sizes = v_split.sizes()
            total = sum(sizes) if sum(sizes) > 0 else v_split.height()
            portable_like = False
            if hasattr(self, "_desktop_render_layout_is_portable_like"):
                try:
                    portable_like = bool(self._desktop_render_layout_is_portable_like())
                except Exception:
                    portable_like = False
            if (
                not portable_like
                and h > 0
                and total > 0
                and len(sizes) >= 2
                and sizes[1] > 0
            ):
                max_bottom = main_v_splitter_max_bottom(h)
                if sizes[1] > max_bottom:
                    bottom = max_bottom
                    top = max(total - bottom, 200)
                    v_split.setSizes([top, bottom])
                elif sizes[1] < 160 and sizes[1] > 0:
                    # Extremely crushed bottom — nudge toward a sane restore ratio.
                    v_split.setSizes(restore_v_splitter_sizes(total))

    def _open_queue_in_right_splitter(self) -> None:
        """Open the queue pane to the last saved width (else layout default)."""
        from steempeg.ui.layout_defaults import (
            PLAYER_COLUMN_FLOOR,
            queue_panel_min_width,
            queue_panel_open_width,
        )

        rhs = getattr(self, "right_h_splitter", None)
        panel = getattr(self, "render_queue_panel", None)
        if rhs is None or panel is None:
            return
        sizes = rhs.sizes()
        # Prefer live width once the shell has geometry; fall back to size sum.
        live = int(rhs.width() or 0)
        summed = int(sum(sizes) if sizes else 0)
        total = max(live, summed, 1)
        win_w = int(self.ui.width() or 0) if getattr(self, "ui", None) else 0
        ideal = queue_panel_open_width(win_w, total_splitter=total) if win_w else 380
        min_q = queue_panel_min_width(win_w, widget=getattr(self, "ui", None)) if win_w else 320
        saved = self.get_layout_setting("queue_panel_width", None)
        queue_w = ideal
        if saved is not None:
            try:
                saved_w = int(saved)
            except (TypeError, ValueError):
                saved_w = 0
            # Restore last open width — do not clamp down to the default ideal
            # (that made every launch ignore a wider drag from last session).
            if saved_w > 48:
                queue_w = max(min_q, saved_w)
        max_q = max(0, total - PLAYER_COLUMN_FLOOR)
        if max_q < 80:
            # Not enough room inside the right column — do not steal from Clips.
            return
        queue_w = max(min_q, min(int(queue_w), max_q))
        rhs.setSizes([total - queue_w, queue_w])
        # Clips-style floor while open (cleared again if the pane is shut).
        if hasattr(self, "sync_queue_minimum"):
            self.sync_queue_minimum()
        # Persist the width we actually applied (after max_q clamp).
        if queue_w > 48:
            self.save_layout_setting("queue_panel_width", int(queue_w))
    def _player_chrome_icon_size(self, dense=None) -> int:
        """Theater / fullscreen / trim chip glyph size — identical for all of them.

        Comfort chip 40 → 22px; compact 28 → 15px. Linear so restoring a wide
        window actually grows the glyph again (the old max(14, chip-18) floor
        left icons stuck at 14px until ~1520px wide).
        """
        if dense is None:
            dense = getattr(self, "_ui_density", None)
        chip = int(getattr(dense, "chrome_chip", 40) or 40)
        return max(12, int(round(chip * 22 / 40)))

    def _sync_chrome_button_icon_size(self, btn, icon_sz: int | None = None) -> None:
        if btn is None or not hasattr(btn, "setIconSize"):
            return
        if btn.icon().isNull():
            return
        from PySide6.QtCore import QSize

        sz = int(icon_sz if icon_sz is not None else self._player_chrome_icon_size())
        btn.setIconSize(QSize(sz, sz))

    def _apply_theater_button_icon(self, *, closed: bool = False) -> None:
        """Theatre icon: same height as fullscreen, full purple plate (may be wider)."""
        btn = getattr(self, "btn_theater", None)
        if btn is None:
            return
        from PySide6.QtCore import QSize
        from steempeg.ui.icon_assets import theater_mode_icon

        sz = self._player_chrome_icon_size()
        icon = theater_mode_icon(sz, closed=closed)
        btn.setIcon(icon)
        sizes = icon.availableSizes()
        if sizes:
            btn.setIconSize(sizes[0])
        else:
            btn.setIconSize(QSize(sz, sz))

    def _apply_fullscreen_button_icon(self, *, fullscreen: bool | None = None) -> None:
        """Enter vs exit fullscreen glyph — same chrome size as theater/trim chips."""
        btn = getattr(self, "btn_fullscreen", None)
        if btn is None:
            ui = getattr(self, "ui", None)
            btn = getattr(ui, "btn_fullscreen", None) if ui is not None else None
        if btn is None:
            return
        if fullscreen is None:
            fullscreen = bool(getattr(self, "is_fullscreen", False))
        asset = "btn_exit_fullscreen.png" if fullscreen else "btn_fullscreen.png"
        path = get_resource_path(asset)
        if os.path.exists(path):
            btn.setIcon(QIcon(path))
            btn.setText("")
            self._sync_chrome_button_icon_size(btn)
        elif not fullscreen:
            enter = get_resource_path("btn_fullscreen.png")
            if os.path.exists(enter):
                btn.setIcon(QIcon(enter))
                btn.setText("")
                self._sync_chrome_button_icon_size(btn)
        btn.setToolTip(
            "Exit Full Screen (Press ESC)"
            if fullscreen
            else "Full Screen (Press ESC to exit)"
        )

    def _apply_ui_density(self, dense):
        """Apply one density to every pane (portable / forced comfort path)."""
        self._ui_density = dense
        self._ui_density_library = dense
        self._ui_density_player = dense
        self._ui_density_queue = dense
        self._apply_library_density(dense)
        self._apply_player_density(dense)
        self._apply_queue_density(dense)

    def _apply_library_footer_button(self, btn, style: str) -> None:
        """About / Check for updates / Settings — no QDialog default/focus ring."""
        from PySide6.QtWidgets import QSizePolicy

        btn.setStyleSheet(style)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoDefault(False)
        btn.setDefault(False)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _library_footer_style_for_density(self, dense):
        """Secondary footer-row QSS — stock gray on Default, theme tokens on TrueDark."""
        from steempeg.ui import ui_theme as ut

        if ut.get_ui_theme() != ut.UI_THEME_DEFAULT:
            return ut.footer_button_stylesheet(dense)
        return f"""
            QPushButton {{
                background-color: #383838; color: #ffffff; border: 2px solid #444444;
                border-radius: {dense.footer_radius}px; font-family: {tok.FONT_APP};
                font-weight: bold; font-size: {dense.footer_font}px; padding: {dense.footer_pad};
                min-height: {dense.footer_min_h}px; outline: none;
            }}
            QPushButton:hover {{ background-color: #404040; border: 2px solid #6b5a8e; }}
            QPushButton:pressed {{ background-color: #3a324a; border: 2px solid #b29ae7; }}
            QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}
            QPushButton:focus, QPushButton:default {{
                background-color: #383838; color: #ffffff; border: 2px solid #444444; outline: none;
            }}
            QPushButton::menu-indicator {{ image: none; }}
        """

    def _apply_library_footer_theme(self, dense) -> None:
        """About / Settings / Folder / Refresh — theme-aware footer chrome."""
        from steempeg.ui.ui_density import (
            folder_button_label,
            settings_button_label,
            updates_button_label,
        )

        footer_style = self._library_footer_style_for_density(dense)
        self._footer_unified_style = footer_style
        btn_about = getattr(self.ui, "btn_about", None)
        btn_update = getattr(self.ui, "btn_update_check", None)
        btn_settings = getattr(self.ui, "btn_settings", None)
        if btn_about is not None:
            self._apply_library_footer_button(btn_about, footer_style)
        if btn_update is not None:
            self._apply_library_footer_button(btn_update, footer_style)
            btn_update.setText(updates_button_label(dense))
            btn_update.setToolTip("Check for updates")
        if btn_settings is not None:
            self._apply_library_footer_button(btn_settings, footer_style)
            btn_settings.setText(settings_button_label(dense))
            btn_settings.setToolTip("Settings")
        btn_dev = getattr(self.ui, "btn_dev", None)
        if btn_dev is not None:
            self._apply_library_footer_button(btn_dev, footer_style)
        picker = getattr(self, "folder_picker", None)
        if picker is not None and hasattr(picker, "apply_density"):
            picker.apply_density(dense)
            folders = getattr(self, "clips_folders", None) or []
            n = len(folders) if folders else 0
            if hasattr(self, "update_folder_button_label"):
                self.update_folder_button_label()
            else:
                picker.set_folder_label(folder_button_label(max(n, 1) if n else 0, dense))
        refresh = getattr(self, "btn_refresh", None)
        if refresh is not None and hasattr(refresh, "apply_density"):
            refresh.apply_density(dense)

    def _apply_library_add_button_theme(self, dense) -> None:
        """Library + tab — stock gray on Default, elevated tab tone on TrueDark."""
        from steempeg.ui import ui_theme as ut

        add_btn = getattr(self, "btn_library_add", None)
        if add_btn is None:
            return
        sz = dense.add_tab_size
        if ut.get_ui_theme() != ut.UI_THEME_DEFAULT:
            add_btn.setStyleSheet(ut.add_library_panel_button_stylesheet(dense))
            return
        add_btn.setFixedSize(sz, sz)
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2d2d2d; color: #ffffff; border: 1px solid #353535;
                border-radius: {dense.tab_radius}px; font-weight: 800;
                font-size: {18 if not dense.compact else 14}px; padding: 0px;
                min-width: {sz}px; max-width: {sz}px;
                min-height: {sz}px; max-height: {sz}px;
            }}
            QPushButton:hover {{ background-color: #3a3a3a; border-color: #6b5a8e; }}
        """)

    def _apply_library_density(self, dense):
        """Clips Manager + footer chrome from the left pane's density."""
        from steempeg.ui.ui_density import tab_label

        # --- Library tabs ---
        tabs = getattr(self, "_library_tabs", None) or {}
        for mode, tab in tabs.items():
            if hasattr(tab, "set_label"):
                tab.set_label(tab_label(mode, dense))
            if hasattr(tab, "apply_density"):
                tab.apply_density(dense)
        self._apply_library_add_button_theme(dense)

        # --- Left toolbar ---
        outer = getattr(self, "_left_toolbar_outer", None)
        if outer is not None:
            outer.setContentsMargins(dense.toolbar_margin_h, 0, dense.toolbar_margin_h, 0)
        pill_lay = getattr(self, "_top_pill_layout", None)
        if pill_lay is not None:
            pill_lay.setContentsMargins(
                dense.toolbar_pad_h, dense.toolbar_pad_v, dense.toolbar_pad_h, dense.toolbar_pad_v
            )
            # Match Render Queue View-plug spacing (View · track · count).
            pill_lay.setSpacing(6 if dense.compact else 8)
        for attr in ("_lbl_view", "_lbl_sorting"):
            lbl = getattr(self, attr, None)
            if lbl is not None:
                lbl.setVisible(not dense.compact)
                if attr == "_lbl_sorting":
                    lbl.setStyleSheet(
                        f"color: #777777; font-weight: bold; font-size: {dense.toolbar_label_font}px;"
                    )
        from steempeg.ui.ui_density import toolbar_mega_pill_style

        lib_pill = getattr(self, "library_toolbar_pill", None)
        if lib_pill is not None:
            lib_pill.setStyleSheet(
                toolbar_mega_pill_style(dense, object_name="libraryToolbarPill")
            )
        chrome = getattr(self, "view_mode_chrome", None)
        if chrome is not None:
            # Keep chrome mode in sync with the active panel before restyle.
            mode = getattr(self, "_clips_view_mode", None) or getattr(
                self, "current_view_mode", "grid"
            )
            panel = getattr(self, "_library_panel_mode", "clips")
            if panel == "rendered":
                mode = getattr(self, "_rendered_view_mode", "grid")
            elif panel == "screenshots":
                mode = "grid"
            chrome.set_mode(mode, emit=False)
            chrome.set_grid_only(panel == "screenshots")
            chrome.apply_density(dense)
            self.toggle_style_active = chrome.toggle_style_active
            self.toggle_style_inactive = chrome.toggle_style_inactive
        else:
            count = getattr(self, "lbl_clip_count", None)
            if count is not None:
                count.setStyleSheet(
                    f"color: #888888; font-weight: bold; font-size: {dense.toolbar_label_font}px;"
                )
            from steempeg.ui.ui_density import (
                view_toggle_button_styles,
                view_toggle_track_style,
            )

            toggle_track = getattr(self, "toggle_pill", None)
            if toggle_track is not None:
                toggle_track.setStyleSheet(view_toggle_track_style(dense))
            self.toggle_style_active, self.toggle_style_inactive = view_toggle_button_styles(dense)
            mode = getattr(self, "_clips_view_mode", None) or getattr(
                self, "current_view_mode", "grid"
            )
            if hasattr(self, "btn_view_grid") and hasattr(self, "btn_view_list"):
                if mode == "list":
                    self.btn_view_list.setStyleSheet(self.toggle_style_active)
                    self.btn_view_grid.setStyleSheet(self.toggle_style_inactive)
                else:
                    self.btn_view_grid.setStyleSheet(self.toggle_style_active)
                    self.btn_view_list.setStyleSheet(self.toggle_style_inactive)

        filt = getattr(self, "btn_filter_pill", None)
        if filt is not None and hasattr(filt, "apply_density"):
            filt.apply_density(dense)

        combo = getattr(self, "combo_sort", None)
        if combo is not None:
            combo.setStyleSheet(compact_combo_stylesheet(settings_popup=True, dense=dense))
            apply_dark_combo_popup(combo, dense=dense)
            fnt = combo.font()
            from steempeg.ui.design_tokens import pin_ui_font
            from PySide6.QtGui import QFont as _QF

            fnt = pin_ui_font(
                fnt, pixel_size=int(dense.footer_font), weight=_QF.Weight.Bold
            )
            combo.setFont(fnt)
            if hasattr(self, "_sync_sort_combo_for_panel"):
                self._sync_sort_combo_for_panel()

        # List view fixed columns: Deck can't fit Type+Date+Duration at comfort widths.
        table = getattr(self.ui, "table_clips", None)
        if table is not None and table.columnCount() >= 4:
            if dense.compact:
                table.setColumnWidth(1, 0)  # Type — hide
                table.setColumnHidden(1, True)
                table.setColumnWidth(2, 110)  # Date
                table.setColumnWidth(3, 70)  # Duration
            else:
                table.setColumnHidden(1, False)
                table.setColumnWidth(1, 100)
                table.setColumnWidth(2, 160)
                table.setColumnWidth(3, 100)

        # --- Footer ---
        self._apply_library_footer_theme(dense)

    def _apply_player_density(self, dense):
        """Player column + export settings chrome from the center pane's density."""
        from steempeg.ui.ui_density import NEO_NAV_COMFORT, NEO_NAV_COMPACT

        # --- Neo settings sidebar ---
        neo = getattr(self, "_neo_sidebar", None)
        if neo is not None:
            if getattr(self, "_portable_neo_chrome_on", False):
                from steempeg.ui.portable.sheets import _PORTABLE_NEO_SIDEBAR_W

                neo.setFixedWidth(_PORTABLE_NEO_SIDEBAR_W)
            else:
                neo.setFixedWidth(dense.neo_sidebar_w)
        neo_lay = getattr(self, "_neo_sidebar_layout", None)
        if neo_lay is not None:
            if getattr(self, "_portable_neo_chrome_on", False):
                from steempeg.ui.portable.sheets import _PORTABLE_NEO_SIDEBAR_MARGINS

                neo_lay.setContentsMargins(*_PORTABLE_NEO_SIDEBAR_MARGINS)
            else:
                m = int(round(6 + (10 - 6) * dense.scale))
                t = int(round(8 + (15 - 8) * dense.scale))
                neo_lay.setContentsMargins(m, t, m, t)
                neo_lay.setSpacing(int(round(6 + (10 - 6) * dense.scale)))
        nav_names = NEO_NAV_COMPACT if dense.compact else NEO_NAV_COMFORT
        from steempeg.ui import ui_theme as ut

        pill = ut.neo_nav_pill_stylesheet()
        from steempeg.ui.icon_assets import neo_nav_tab_icon

        icon_sz = max(10, int(getattr(dense, "neo_nav_icon", 16) or 16))
        icon_gap = max(0, int(getattr(dense, "neo_nav_icon_gap", 8) or 0))
        icon_qsize = QSize(icon_sz + icon_gap, icon_sz)
        for i, btn in enumerate(getattr(self, "neo_nav_buttons", []) or []):
            if i < len(nav_names):
                btn.setText(nav_names[i])
            btn.setIcon(neo_nav_tab_icon(i, icon_sz, trailing_gap=icon_gap))
            btn.setIconSize(icon_qsize)
            btn.setStyleSheet(pill)

        # --- Player transport ---
        for btn, w, h in (
            (getattr(self.ui, "btn_skip_back", None), dense.skip_w, dense.skip_h),
            (getattr(self.ui, "btn_skip_forward", None), dense.skip_w, dense.skip_h),
            (getattr(self.ui, "btn_play", None), dense.play_w, dense.play_h),
        ):
            if btn is not None:
                btn.setMinimumSize(w, h)

        # Player header title cluster / status / action chips (was fixed 24/8/30).
        try:
            from steempeg.ui.player_header_layout import apply_player_header_density

            apply_player_header_density(self, dense)
        except Exception:
            pass

        try:
            from steempeg.ui.layout_defaults import apply_player_layout_mode

            apply_player_layout_mode(self)
        except Exception:
            pass

        chip = dense.chrome_chip
        chip_r = chip // 2
        # Same face for theater + fullscreen + trim chips. Scale with the chip
        # (was max(14, chip-18) which froze icons at 14px until ~1520px wide).
        icon_sz = self._player_chrome_icon_size(dense)
        chip_qss = f"""
            QPushButton {{
                background: transparent;
                border-radius: {chip_r}px;
                border: none;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 40);
            }}
            QPushButton:pressed {{
                background: rgba(255, 255, 255, 60);
            }}
        """
        marker_qss = f"""
            QPushButton {{
                background: transparent;
                border: none;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 30);
                border-radius: {max(6, chip_r // 3)}px;
            }}
            QPushButton:pressed {{
                background: rgba(255, 255, 255, 50);
            }}
        """
        for attr in (
            "btn_theater",
            "btn_fullscreen",
            "btn_clipcut1",
            "btn_clipcut2",
            "btn_clipcutback",
        ):
            b = getattr(self, attr, None) or getattr(self.ui, attr, None)
            if b is not None and hasattr(b, "setFixedSize"):
                b.setFixedSize(chip, chip)
                b.setStyleSheet(chip_qss)
                if attr == "btn_theater" and hasattr(self, "_apply_theater_button_icon"):
                    self._apply_theater_button_icon(
                        closed=bool(getattr(self, "is_theater", False))
                    )
                elif attr == "btn_fullscreen" and hasattr(
                    self, "_apply_fullscreen_button_icon"
                ):
                    self._apply_fullscreen_button_icon(
                        fullscreen=bool(getattr(self, "is_fullscreen", False))
                    )
                else:
                    self._sync_chrome_button_icon_size(b, icon_sz)

        for attr in ("btn_add_marker", "btn_marker_settings", "btn_screenshot"):
            b = getattr(self, attr, None) or getattr(self.ui, attr, None)
            if b is not None and hasattr(b, "setFixedSize"):
                b.setFixedSize(chip, chip)
                if attr in ("btn_add_marker", "btn_marker_settings"):
                    b.setStyleSheet(chip_qss)
                else:
                    b.setStyleSheet(marker_qss)
                self._sync_chrome_button_icon_size(b, icon_sz)

        for ctrl_attr in ("volume_control", "speed_control"):
            ctrl = getattr(self, ctrl_attr, None)
            if ctrl is not None and hasattr(ctrl, "apply_density"):
                ctrl.apply_density(dense)

        # Pill frames around theater/fullscreen / markers stay circular-ish
        from steempeg.ui import ui_theme as ut

        for pill_attr in ("pill_container", "trim_tools_pill", "marker_pill"):
            frame = getattr(self, pill_attr, None)
            if frame is not None:
                frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                frame.setStyleSheet(ut.player_chrome_pill_stylesheet(radius=chip_r))

        # Sync press-feedback rest sizes after transport icon/min changes.
        from steempeg.ui.widgets.press_feedback import install_press_feedback

        for attr in ("btn_play", "btn_skip_back", "btn_skip_forward"):
            b = getattr(self.ui, attr, None)
            if b is not None:
                install_press_feedback(b).sync_rest_icon_size()

        # --- Render settings (Source / Video / Audio / Export) ---
        from steempeg.ui.render_panel import apply_settings_panel_density

        apply_settings_panel_density(self.ui, dense)
        if hasattr(self, "right_scroll") and self.right_scroll is not None:
            from PySide6.QtCore import Qt as _Qt

            self.right_scroll.setHorizontalScrollBarPolicy(
                _Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )

        # --- Render status dashboard ---
        self._apply_render_dashboard_density(dense)

    def _apply_queue_density(self, dense):
        """Render queue chrome from the right pane's density."""
        panel = getattr(self, "render_queue_panel", None)
        if panel is not None and hasattr(panel, "apply_density"):
            panel.apply_density(dense)

    def _apply_render_dashboard_density(self, dense) -> None:
        dash = getattr(self, "render_dashboard", None)
        if dash is None:
            return
        if not dash.objectName():
            dash.setObjectName("renderDashboard")
        lay = dash.layout()
        if lay is not None:
            lay.setContentsMargins(
                dense.dash_margin_h,
                dense.dash_margin_v,
                dense.dash_margin_h,
                dense.dash_margin_v,
            )
            lay.setSpacing(dense.dash_spacing)
        # Gap between summary row and progress bar — was stuck at 12px forever.
        header = getattr(self, "_dash_header_block", None)
        if header is not None:
            header.setSpacing(dense.dash_spacing)
        btn_row = getattr(self, "_dash_btn_row", None)
        if btn_row is not None:
            btn_row.setSpacing(8 if dense.compact else 12)
        # Keep a stable card radius (not tied to button height).
        dash_r = 10 if dense.compact else 12
        from steempeg.ui import ui_theme as ut

        if ut.get_ui_theme() != ut.UI_THEME_DEFAULT:
            dash.setStyleSheet(
                ut.elevated_panel_stylesheet(object_name="renderDashboard")
                + " QFrame#renderDashboard QLabel { border: none; background: transparent; }"
            )
        else:
            dash.setStyleSheet(
                f"QFrame#renderDashboard {{ background-color: #2d2d2d; border: 1px solid #353535; "
                f"border-radius: {dash_r}px; }}"
                f"QFrame#renderDashboard QLabel {{ border: none; background: transparent; }}"
            )
        _status_font = "font-family: " + tok.FONT_APP + ";"
        bottom_text = getattr(self, "bottom_text_label", None)
        if bottom_text is not None:
            bottom_text.setStyleSheet(
                f"color: #e0e0e0; font-size: {dense.dash_font}px; font-weight: bold; {_status_font}"
            )
            if dense.compact:
                bottom_text.setMaximumHeight(dense.dash_font + 6)
            else:
                bottom_text.setMaximumHeight(16777215)
        # Preserve Ready/Rendering colour — density used to wipe it to default white.
        status_color = getattr(self, "_status_indicator_color", None)
        if not status_color:
            dot = getattr(self, "status_dot", None)
            cur = (dot.styleSheet() if dot is not None else "") or ""
            status_color = "#4CAF50"
            if "background-color:" in cur:
                try:
                    status_color = cur.split("background-color:")[1].split(";")[0].strip()
                except Exception:
                    pass
        status = getattr(self.ui, "label_status", None)
        if status is not None:
            status.setStyleSheet(
                f"background: transparent; border: none; font-size: {dense.dash_font}px; "
                f"font-weight: bold; color: {status_color}; {_status_font}"
            )
            status.setMinimumWidth(48 if dense.compact else 120)
        pct = getattr(self, "label_pct", None)
        if pct is not None:
            pct.setStyleSheet(
                f"color: #ffffff; font-weight: bold; font-size: {max(9, dense.dash_font - 1)}px; {_status_font}"
            )
        icon = getattr(self, "bottom_icon_label", None)
        if icon is not None:
            icon_sz = 14 if dense.compact else 24
            icon.setFixedSize(icon_sz, icon_sz)
        dot = getattr(self, "status_dot", None)
        if dot is not None:
            if getattr(self, "_update_check_busy", False) and hasattr(
                self, "_paint_status_dot_update_spin"
            ):
                self._paint_status_dot_update_spin(
                    getattr(self, "_status_indicator_color", "#a871ff")
                )
            elif (
                getattr(self, "_clips_scan_active", False)
                or getattr(self, "_rendered_scan_active", False)
            ) and hasattr(self, "_paint_status_dot_loading_wave"):
                self._paint_status_dot_loading_wave(
                    getattr(self, "_status_indicator_color", "#a871ff")
                )
            elif (
                hasattr(self, "_sync_dash_queue_status_chrome")
                and self._sync_dash_queue_status_chrome()
            ):
                pass  # queue Ready / Completed / index badge restored
            else:
                dot_sz = 8 if dense.compact else 12
                dot.setFixedSize(dot_sz, dot_sz)
                dot.setStyleSheet(
                    f"background-color: {status_color}; border-radius: {dot_sz // 2}px;"
                )

        pad = "1px 8px" if dense.compact else "6px 14px"
        radius = max(8, dense.dash_btn_h // 2)
        font = dense.dash_font
        style_map = {
            "btn_start": getattr(self, "_dash_btn_style_start", None),
            "btn_pause": getattr(self, "_dash_btn_style_pause", None),
            "btn_cancel": getattr(self, "_dash_btn_style_cancel", None),
        }
        for btn_name, template in style_map.items():
            btn = getattr(self.ui, btn_name, None)
            if btn is None:
                continue
            btn.setMinimumSize(0, 0)
            btn.setFixedHeight(dense.dash_btn_h)
            if template:
                btn.setStyleSheet(
                    self._fmt_dash_btn(template, font=font, radius=radius, pad=pad)
                )
        self._refresh_dash_secondary_button_styles(dense)
        settings_btn = getattr(self, "btn_render_settings", None)
        settings_style = getattr(self, "_dash_btn_style_render_settings", None)
        if settings_btn is not None and settings_style:
            settings_btn.setFixedHeight(dense.dash_btn_h)
            settings_btn.setStyleSheet(
                self._fmt_dash_btn(settings_style, font=font, radius=radius, pad=pad)
            )
        if hasattr(self, "_sync_queue_scheme_chrome"):
            self._sync_queue_scheme_chrome()
        if hasattr(self, "_sync_dash_queue_status_chrome"):
            self._sync_dash_queue_status_chrome()
        if hasattr(self, "_pin_dash_queue_header_buttons"):
            self._pin_dash_queue_header_buttons()
        if hasattr(self, "apply_desktop_render_layout"):
            self.apply_desktop_render_layout()

    def _apply_startup_splitter_sizes(self):
        from steempeg.ui.layout_defaults import (
            DEFAULT_MAIN_SPLITTER_SIZES,
            DEFAULT_MAIN_SPLITTER_SIZES_COMPACT,
            STEAM_DECK_HEIGHT,
            STEAM_DECK_WIDTH,
            default_main_v_splitter_sizes,
            is_compact_layout,
            left_panel_min_width,
        )

        avail_w = self.ui.width() or STEAM_DECK_WIDTH
        avail_h = self.ui.height() or STEAM_DECK_HEIGHT
        compact = is_compact_layout(avail_w, widget=self.ui)
        default_main = (
            DEFAULT_MAIN_SPLITTER_SIZES_COMPACT if compact else DEFAULT_MAIN_SPLITTER_SIZES
        )
        # Prefer continuous left min when remembering is off / defaults.
        if not compact:
            default_main = [left_panel_min_width(avail_w, widget=self.ui), 100000]
        main_sizes = self.get_layout_setting("main_splitter_sizes", default_main)
        if hasattr(self.ui, "main_splitter"):
            self.ui.main_splitter.setSizes(main_sizes)
        self._apply_responsive_layout_mins()
        v_splitter = getattr(self, "main_v_splitter", None)
        if v_splitter is not None:
            portable_like = False
            if hasattr(self, "_desktop_render_layout_is_portable_like"):
                try:
                    portable_like = bool(self._desktop_render_layout_is_portable_like())
                except Exception:
                    portable_like = False
            if portable_like and hasattr(self, "_sync_portable_like_dock_chrome"):
                # Don't restore a tall neo dock height — glue dash height instead.
                self._sync_portable_like_dock_chrome()
            else:
                from steempeg.ui.layout_defaults import (
                    main_v_splitter_max_bottom,
                    scale_main_v_splitter_sizes,
                )

                default_v = default_main_v_splitter_sizes(
                    avail_w, avail_h, widget=self.ui
                )
                v_sizes = self.get_layout_setting("main_v_splitter_sizes", default_v)
                total = (
                    sum(v_splitter.sizes())
                    if sum(v_splitter.sizes()) > 0
                    else int(v_splitter.height() or avail_h or 0)
                )
                total = max(int(total), 1)
                # Prefer remembered proportions; fall back to tall defaults.
                if (
                    not v_sizes
                    or len(v_sizes) < 2
                    or int(v_sizes[1]) <= 80
                ):
                    v_sizes = default_v
                scaled = scale_main_v_splitter_sizes(
                    v_sizes, total, window_height=avail_h or total
                )
                # Extra guard: never cold-start at a near-dash stub height.
                max_bottom = main_v_splitter_max_bottom(avail_h or total)
                if scaled[1] < 200:
                    bottom = min(max(int(default_v[1]), 260), max_bottom)
                    bottom = min(bottom, max(total - 200, 1))
                    scaled = [total - bottom, bottom]
                v_splitter.setSizes(scaled)

    def _setup_bitrate_labels(self):
        # --- UI INJECTION: INDEPENDENT BITRATE LABELS ---
        # Instead of stuffing multiple lines into one label, we create separate
        # widgets so the Qt layout engine handles the vertical spacing perfectly
        return
        if hasattr(self.ui, 'orig_res_label'):
            from PySide6.QtWidgets import QLabel

            parent_layout = self.ui.orig_res_label.parentWidget().layout()

            # Find the exact index of orig_res_label to insert right below it
            insert_index = -1
            for i in range(parent_layout.count()):
                if parent_layout.itemAt(i).widget() == self.ui.orig_res_label:
                    insert_index = i
                    break

            if insert_index != -1:
                # 1. Create the Video Bitrate label
                self.ui.label_vbitrate = QLabel("Video Bitrate:")
                self.ui.label_vbitrate.setStyleSheet(self.ui.orig_res_label.styleSheet())
                parent_layout.insertWidget(insert_index + 1, self.ui.label_vbitrate)

                # 2. Create the Audio Bitrate label
                self.ui.label_abitrate = QLabel("Audio Bitrate:")
                self.ui.label_abitrate.setStyleSheet(self.ui.orig_res_label.styleSheet())
                parent_layout.insertWidget(insert_index + 2, self.ui.label_abitrate)
    def _setup_custom_target_size(self):
        # --- UI INJECTION: STRICT CUSTOM TARGET SIZE ---
        if hasattr(self.ui, 'label_target_size'):
            from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QSizePolicy, QLabel, QToolTip
            from PySide6.QtGui import QIntValidator, QPixmap
            from PySide6.QtCore import QObject, QEvent

            self.size_container = QWidget()
            size_layout = QHBoxLayout(self.size_container)
            size_layout.setContentsMargins(0, 0, 0, 0)
            size_layout.setSpacing(6)

            self.ui.label_target_size.parentWidget().layout().replaceWidget(self.ui.label_target_size, self.size_container)
            self.ui.label_target_size.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

            self.input_custom_size = QLineEdit()
            self.input_custom_size.setPlaceholderText("MB")
            self.input_custom_size.setFixedWidth(60)
            self.input_custom_size.setValidator(QIntValidator(1, 999999))
            self.input_custom_size.hide()
            self.input_custom_size.textChanged.connect(self.on_custom_size_changed)

            self.warn_size = QLabel()
            self.warn_size.setFixedSize(16, 16)
            from steempeg.ui.icon_assets import warning_pixmap
            _warn_pix = warning_pixmap(16)
            if not _warn_pix.isNull():
                self.warn_size.setPixmap(_warn_pix)
            self.warn_size.hide()

            class InstantTooltipFilter(QObject):
                def eventFilter(self, obj, event):
                    if event.type() == QEvent.Type.Enter:
                        QToolTip.showText(event.globalPosition().toPoint(), obj.toolTip(), obj)
                    elif event.type() == QEvent.Type.Leave:
                        QToolTip.hideText()
                    return False

            self.instant_tooltip = InstantTooltipFilter()
            self.warn_size.installEventFilter(self.instant_tooltip)

            size_layout.addWidget(self.ui.label_target_size)
            size_layout.addWidget(self.input_custom_size)
            size_layout.addWidget(self.warn_size)
            size_layout.addStretch()

            self.ui.label_target_size.setVisible(True)
            self.size_container.setVisible(False)


import os


# --- BACKGROUND WORKER: JIT THUMBNAIL SNIPER ---
import os

# --- SMART PREVIEW SNIPER 5.0 (RADAR RADIAL PRELOADER) ---
import os



from PySide6.QtCore import QObject







    
from PySide6.QtCore import Qt



from PySide6.QtCore import QObject, Qt



  
from PySide6.QtCore import QTimer



from PySide6.QtCore import QObject



    

def main():
    import sys
    import os
    import argparse
    import traceback

    # Toast / protocol click: restore the running window and exit (no Qt).
    if sys.platform == "win32" and any(
        a == "--raise-existing" or str(a).startswith("steempeg:")
        for a in sys.argv[1:]
    ):
        from steempeg.infra.window_focus import raise_steempeg_window

        raise SystemExit(0 if raise_steempeg_window() else 1)

    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QIcon
    from PySide6.QtCore import QTimer
    
    if sys.platform == "win32":
        os.environ.setdefault("QT_MEDIA_BACKEND", "windows")
    

    parser = argparse.ArgumentParser()
    parser.add_argument('--updated-from', type=str, default="")
    parser.add_argument('--backup-folder', type=str, default="")
    parser.add_argument('--update-handler', action='store_true')
    parser.add_argument('--job', type=str, default="")
    args, unknown = parser.parse_known_args()

    if args.update_handler:
        from steempeg.update_handler import run_update_handler
        sys.exit(run_update_handler(args.job))


    if sys.platform == "win32":
        try:
            import ctypes
            # MUST stay constant across versions. A version-specific AppUserModelID makes
            # Windows treat every update as a brand-new app with no cached icon, so the
            # taskbar falls back to the generic icon until the cache catches up — this was
            # the long-standing "icon disappears after update" bug.
            myappid = 'Steempeg.SteempegApp'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
        # Detach the black cmd.exe host when launched via python.exe / Code Runner.
        # Logs still go to files. Keep a console with STEEMPEG_KEEP_CONSOLE=1.
        if os.environ.get("STEEMPEG_KEEP_CONSOLE", "0") != "1":
            try:
                import ctypes

                if ctypes.windll.kernel32.FreeConsole():
                    # After FreeConsole, any print/logging to the old stdio can make
                    # the CRT AllocConsole a fresh black window (often two flashes
                    # around the first portable paint). Park stdio on the null device.
                    _devnull = open(os.devnull, "w", encoding="utf-8", errors="ignore")
                    sys.stdout = _devnull
                    sys.stderr = _devnull
            except Exception:
                pass

    # Linux: default to xcb (XWayland). libmpv wid= embed needs an X11 window;
    # plain Wayland often maps the shell then stalls (this packaged freeze).
    # Override: STEEMPEG_QT_PLATFORM=wayland|xcb
    #
    # Do NOT auto-enable STEEMPEG_SOFT_GL / llvmpipe — that software-renders the
    # whole 1440p shell on CPU and melts the machine. Optional escape hatch only:
    #   STEEMPEG_SOFT_GL=1
    # NVIDIA + XWayland: disable Qt's GLX integration so widgets stay on the
    # cheap raster path (avoids the hard-freeze without llvmpipe).
    if sys.platform != "win32":
        forced = (os.environ.get("STEEMPEG_QT_PLATFORM") or "").strip()
        if forced:
            os.environ["QT_QPA_PLATFORM"] = forced
        else:
            os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
        nvidia = (
            os.path.exists("/proc/driver/nvidia/version")
            or os.path.exists("/dev/nvidia0")
            or os.path.isdir("/sys/module/nvidia")
        )
        if (
            nvidia
            and os.environ.get("QT_QPA_PLATFORM", "").startswith("xcb")
            and "QT_XCB_GL_INTEGRATION" not in os.environ
        ):
            os.environ["QT_XCB_GL_INTEGRATION"] = "none"
        if os.environ.get("STEEMPEG_SOFT_GL", "0") == "1":
            os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
            os.environ.setdefault("GALLIUM_DRIVER", "llvmpipe")
            os.environ.setdefault("QT_OPENGL", "software")
        from steempeg.infra.linux_desktop import prepare_linux_qt_environment

        prepare_linux_qt_environment()

    from PySide6.QtCore import Qt as _Qt

    if sys.platform != "win32" and os.environ.get("STEEMPEG_SOFT_GL", "0") == "1":
        try:
            QApplication.setAttribute(_Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Steempeg")
    app.setApplicationDisplayName("Steempeg")
    if sys.platform != "win32":
        from steempeg.infra.linux_desktop import apply_linux_qt_app, install_linux_desktop_entry

        apply_linux_qt_app(app)
        install_linux_desktop_entry()
    try:
        from steempeg.ui.design_tokens import apply_app_tooltip_style

        apply_app_tooltip_style(app)
    except Exception:
        pass
    if sys.platform != "win32" and os.environ.get("STEEMPEG_KEEP_CONSOLE", "0") == "1":
        print(f"[steempeg] Qt platform={app.platformName()!r}", flush=True)

    # Linux: UI + color-emoji stack (Auto/Selawik/System via apply_ui_font_preference).
    # Windows: classic Segoe-first only — ui_font preference is ignored.
    try:
        from steempeg.ui.design_tokens import apply_ui_font_preference

        apply_ui_font_preference(app=app)
    except Exception:
        pass

    from steempeg.infra.single_instance import try_acquire_instance_lock
    from steempeg.ui.already_running_dialog import AlreadyRunningDialog

    _instance_lock, _got_lock = try_acquire_instance_lock()
    if not _got_lock:
        dlg = AlreadyRunningDialog()
        dlg.exec()
        if not dlg.run_anyway:
            sys.exit(0)
        # Second instance: do not hold a lock (primary keeps it).
        _instance_lock = None

    from steempeg.ui.icon_utils import app_window_icon

    _app_icon = app_window_icon()
    icon_path = get_resource_path("logo.ico" if sys.platform == "win32" else "logo.png")
    if not os.path.isfile(icon_path):
        icon_path = get_resource_path("logo.png")
    if not _app_icon.isNull():
        app.setWindowIcon(_app_icon)

    from PySide6.QtWidgets import QDialog
    from steempeg.ui.shell_chooser import (
        ShellChooserDialog,
        UI_SHELL_PORTABLE,
        resolve_startup_ui_shell,
        save_ui_shell,
    )

    # Steam Deck: Portable by default (no chooser). Else ask unless "Don't ask again".
    ui_shell = resolve_startup_ui_shell()
    if ui_shell is None:
        chooser = ShellChooserDialog()
        if chooser.exec() != QDialog.DialogCode.Accepted or not chooser.chosen_shell:
            sys.exit(0)
        ui_shell = chooser.chosen_shell
        # Cards use PointingHand — without a resync the hand sticks on the
        # whole portable/desktop shell until the mouse moves (or About closes).
        from steempeg.ui.window_chrome import force_app_cursor_resync

        force_app_cursor_resync()
        QTimer.singleShot(0, force_app_cursor_resync)
    else:
        save_ui_shell(ui_shell)

    try:
        window = SteempegApp()
        # Keep the lock alive for the process lifetime (prevent GC unlock).
        window._instance_lock = _instance_lock
        window._ui_shell = ui_shell
        
        if getattr(window, 'ui', None) is None:
            QMessageBox.critical(None, "Interface Error", "Failed to build the main window!")
            sys.exit(1)
            
        if not _app_icon.isNull():
            window.ui.setWindowIcon(_app_icon)

        from PySide6.QtCore import Qt
        if sys.platform == "win32":
            # Custom Win32 chrome: keep native frame styles, hide painted caption later.
            # WindowSystemMenuHint keeps Alt+F4 / Alt+Space wired to the shell HWND.
            # NonModal: QDialog defaults must not keep the shell above other apps.
            window.ui.setWindowModality(Qt.WindowModality.NonModal)
            window.ui.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowMinimizeButtonHint
                | Qt.WindowType.WindowMaximizeButtonHint
                | Qt.WindowType.WindowCloseButtonHint
            )
        else:
            # Frameless QWidget + SteempegTitleBar (drag via startSystemMove).
            # Skip setModal — MainWindow is QWidget on Linux, not QDialog.
            window.ui.setWindowModality(Qt.WindowModality.NonModal)
            window.ui.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowMinimizeButtonHint
                | Qt.WindowType.WindowMaximizeButtonHint
                | Qt.WindowType.WindowCloseButtonHint
            )

        # Pre-size to the screen work area BEFORE showing.
        window._apply_dark_shell()
        from steempeg.ui.layout_defaults import (
            TARGET_MIN_WINDOW_HEIGHT,
            TARGET_MIN_WINDOW_WIDTH,
        )

        _screen = app.primaryScreen()
        if _screen is not None:
            _avail = _screen.availableGeometry()
            # Portable + Desktop share the Deck floor (1280×800). On smaller
            # work areas the min clamps to the screen so the shell still fits.
            _min_w = min(TARGET_MIN_WINDOW_WIDTH, max(640, _avail.width()))
            _min_h = min(TARGET_MIN_WINDOW_HEIGHT, max(480, _avail.height()))
            window.ui.setMinimumSize(_min_w, _min_h)
            # Match the work area immediately so the first paint is never an
            # inset "half screen" that then jumps after showMaximized settles.
            window.ui.setGeometry(_avail)
            # __init__ applied Deck/compact density while the HWND was still
            # tiny. Restyle for the real width BEFORE the first show — otherwise
            # the first paint is a shrunk UI on a fullscreen window, and a brief
            # UI stall freezes that frame as "(Not Responding)".
            window._ui_density = None
            window._density_resize_defer_ms = 0
            window._apply_startup_splitter_sizes()
            logging.info(
                "Primary screen %r avail=%sx%s",
                _screen.name(),
                _avail.width(),
                _avail.height(),
            )
            try:
                from steempeg.ui.screen_metrics import describe_screen

                logging.info("Display metrics: %s", describe_screen(screen=_screen))
            except Exception:
                logging.exception("Display metrics: failed to read PPI")
        else:
            window.ui.setMinimumSize(TARGET_MIN_WINDOW_WIDTH, TARGET_MIN_WINDOW_HEIGHT)

        # Portable: enter theatre BEFORE the first paint so desktop chrome never flashes.
        if ui_shell == UI_SHELL_PORTABLE:
            window.apply_portable_theatre_shell()

        # Hide the painted caption before the first ShowWindow — otherwise Windows
        # briefly maps a native-framed "Steempeg" HWND, then frameless leaves a
        # translucent stub at the top of the monitor.
        if sys.platform == "win32":
            from steempeg.ui.window_chrome import enable_frameless

            # Frameless FRAMECHANGED first — then stamp the icon so Explorer does
            # not fall back to the python.exe blank-document taskbar face.
            enable_frameless(window.ui)
            _force_native_window_icon(window.ui, icon_path)

        # Finish density / library restore / Skip paint WHILE STILL HIDDEN.
        # Showing first painted an empty "0 Clips" shell that then jumped —
        # and FRAMECHANGED settle looked like the half-done window closing.
        from steempeg.ui.startup_settle import (
            begin_startup_settle,
            kick_startup_settle_after_show,
        )
        from steempeg.ui.settings_prefs import (
            SCAN_CACHE,
            SCAN_SMART,
            load_startup_library_scan,
        )

        # Skip / Smart: opaque veil covers post-maximize chrome thrash (crooked
        # footer / Ready badge). Quick/Full: settle pass only — no «Preparing
        # workspace…» flash (that thrash was mainly a cache-path issue).
        _settle_settings = {}
        if hasattr(window, "load_user_settings"):
            try:
                _settle_settings = window.load_user_settings() or {}
            except Exception:
                _settle_settings = {}
        _settle_mode = load_startup_library_scan(_settle_settings)
        _use_settle_veil = _settle_mode in (SCAN_CACHE, SCAN_SMART)
        begin_startup_settle(window, use_veil=_use_settle_veil)
        window._sync_startup_layout()
        try:
            from PySide6.QtCore import QEventLoop

            # Bound the pump — unbounded processEvents can drain screenshot/thumb
            # timers for minutes before the window ever reaches "shown".
            QApplication.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 50
            )
        except Exception:
            QApplication.processEvents()

        if sys.platform == "win32":
            # Maximize on the *first* show. Showing the inset normal state first
            # and maximizing right after gives Windows no state change to record,
            # so the first green-button restore snaps with no DWM transition —
            # every later toggle animates because that first one seeded it.
            window.ui.showMaximized()
        else:
            # Linux/XWayland+NVIDIA: never call showMaximized (hard-freeze).
            window.ui.show()
            logging.info("Linux: fake-maximize via work-area geometry (no showMaximized)")

        def _bring_main_to_front():
            # Qt alone is often ignored under Windows focus-stealing rules when
            # launched from another process. Win32 path is a no-op on Linux.
            window.ui.raise_()
            window.ui.activateWindow()
            try:
                wh = window.ui.windowHandle()
                if wh is not None:
                    wh.requestActivate()
            except Exception:
                pass
            try:
                from steempeg.infra.window_focus import force_widget_foreground

                force_widget_foreground(window.ui)
            except Exception:
                logging.debug("startup bring-to-front failed", exc_info=True)

        _bring_main_to_front()
        if sys.platform != "win32":
            try:
                from steempeg.ui.disk_space_warning import (
                    schedule_linux_low_disk_startup_warning,
                )

                schedule_linux_low_disk_startup_warning(window)
            except Exception:
                logging.exception("Linux disk-space warning failed to schedule")
        # One coherent post-maximize settle under the veil — do NOT thrash
        # splitters / queue open / density on staggered 0ms/50ms timers (that
        # was the Ready-badge + footer jump). Reveal when pass + density flush
        # finish (or STARTUP_SETTLE_TIMEOUT_MS failsafe).
        kick_startup_settle_after_show(window)
        try:
            from PySide6.QtCore import QEventLoop

            QApplication.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 50
            )
        except Exception:
            QApplication.processEvents()
        # Geometry after maximize can still settle one tick later — re-claim
        # foreground after first paint (launcher / terminal may still hold focus).
        _bring_main_to_front()
        QTimer.singleShot(0, _bring_main_to_front)
        # Belt-and-suspenders: strip any stuck WS_EX_TOPMOST after the startup
        # focus flashes settle (otherwise Explorer stays under Steempeg).
        if sys.platform == "win32":
            def _clear_startup_topmost():
                try:
                    from steempeg.infra.window_focus import clear_widget_topmost

                    clear_widget_topmost(window.ui)
                except Exception:
                    pass

            QTimer.singleShot(100, _clear_startup_topmost)
            QTimer.singleShot(500, _clear_startup_topmost)
        if ui_shell == UI_SHELL_PORTABLE:
            # Theatre under the veil; one late re-assert after settle reveal.
            window.apply_portable_theatre_shell()
            QTimer.singleShot(600, window.apply_portable_theatre_shell)
            # Prewarm Clips/Render sheets off the critical path (map-suppressed —
            # no translucent HWND flash). First open stays snappy.
            from steempeg.ui.portable.chrome import prewarm_portable_sheets
            from steempeg.ui.window_chrome import force_app_cursor_resync

            QTimer.singleShot(500, lambda: prewarm_portable_sheets(window))
            # Shell chooser (or any startup modal) can leave PointingHand stuck
            # over the empty theatre — resync after first paint.
            QTimer.singleShot(0, force_app_cursor_resync)
            QTimer.singleShot(50, force_app_cursor_resync)
        if hasattr(window, "schedule_silent_update_check"):
            # Quiet badge probe — never auto-installs; user still chooses backup/update.
            # Interval: Settings → Check for updates (Off / Every launch / Daily / Weekly).
            from steempeg.ui.settings_prefs import should_run_silent_update_check

            try:
                _upd_settings = window.load_user_settings() or {}
            except Exception:
                _upd_settings = {}
            if should_run_silent_update_check(_upd_settings):
                window.schedule_silent_update_check(2800)

        # Small-screen tip after chrome settles — Desktop only (chooser already
        # warns inline; Portable is built for cramped screens).
        if ui_shell != UI_SHELL_PORTABLE:
            from steempeg.ui.settings_dialog import maybe_show_small_screen_warning

            QTimer.singleShot(
                900,
                lambda: maybe_show_small_screen_warning(window, ui_shell),
            )

        geo = window.ui.geometry()
        logging.info(
            "Main window shown (platform=%s shell=%s visible=%s geo=%sx%s+%s+%s soft_gl=%s)",
            app.platformName(),
            ui_shell,
            window.ui.isVisible(),
            geo.width(),
            geo.height(),
            geo.x(),
            geo.y(),
            os.environ.get("STEEMPEG_SOFT_GL", "0") == "1",
        )
        if app.platformName() == "xcb":
            logging.warning(
                "UI is on xcb/XWayland — native maximize/minimize may hard-freeze on NVIDIA"
            )

        def _apply_custom_shell_native():
            from steempeg.ui.window_chrome import ensure_startup_maximized

            # Maximize / FRAMECHANGED can wipe WM_SETICON — re-stamp after.
            ensure_startup_maximized(window.ui)
            _force_native_window_icon(window.ui, icon_path)
            tb = getattr(window.ui, "title_bar", None)
            if tb is not None:
                tb.sync_window_state()

        # Second pass after maximize settles (icon + NCCALCSIZE); caption already
        # stripped before the first show above.
        QTimer.singleShot(0, _apply_custom_shell_native)
        # Second pass: after the first paint / shell settle (post-update launches
        # sometimes need another poke before Windows shows the branded icon).
        QTimer.singleShot(400, lambda: _force_native_window_icon(window.ui, icon_path))
        from steempeg.ui.window_chrome import ensure_startup_maximized as _ensure_max

        QTimer.singleShot(450, lambda: _ensure_max(window.ui))
        QTimer.singleShot(500, lambda: _force_native_window_icon(window.ui, icon_path))
        if args.updated_from:
            QTimer.singleShot(800, lambda: _force_native_window_icon(window.ui, icon_path))

            def _post_update_ui():
                _ensure_max(window.ui)
                window.show_update_success(args.updated_from, args.backup_folder)
                _ensure_max(window.ui)

            QTimer.singleShot(1000, _post_update_ui)

        sys.exit(app.exec())

    except Exception as e:
        # Now no mistake can hide =)))))))) =))))) dsfhnuijdfgbjiklgfvbjknlbfcvxjknml
        error_text = traceback.format_exc()
        print(error_text)
        try:
            # Do NOT "import logging" here — it shadows the module-level import and
            # breaks logging.info(...) earlier in main (UnboundLocalError).
            logging.critical("=" * 40)
            logging.critical("FATAL ERROR:")
            logging.critical(error_text)
            logging.critical("=" * 40)
        except Exception:
            pass

        QMessageBox.critical(None, "FATAL ERROR", f"APP ERROR:\n{error_text}")
sys.excepthook = global_exception_handler
if __name__ == "__main__":
    main()
