from steempeg.version import APP_VERSION_STR
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
from steempeg.ui.hide_watcher import HideWatcher
from steempeg.ui.widgets.combo_chrome import (
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


def _force_native_window_icon(widget, ico_path):
    """Push the .ico onto the realized HWND via WM_SETICON.

    Qt's setWindowIcon is not always enough on first launch: Windows caches the
    taskbar button icon per AppUserModelID, and on a cold cache the button shows
    the generic icon until a later run warms it up (the "icon only appears on the
    2nd/3rd launch" bug). Re-applying the icon directly to the native window after
    it is shown populates that cache immediately, on the very first launch.
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

        hwnd = int(widget.winId())
        # Big source (256) gives the taskbar a crisp downscale at any DPI; small
        # (32) feeds the title-bar / small taskbar icon.
        big = user32.LoadImageW(None, ico_path, IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
        small = user32.LoadImageW(None, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
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


class SteempegApp(RenderedLibraryMixin, LifecycleMixin, PlayerMixin, LibraryMixin, RenderMixin, SettingsMixin, UpdaterMixin, QObject):
    def _apply_playback_button_styles(self):
        """Playback buttons live under HudFrame; style them directly (not via right_panel)."""
        if not hasattr(self.ui, "btn_play"):
            return
        from PySide6.QtWidgets import QSizePolicy
        for btn in (self.ui.btn_play, self.ui.btn_skip_back, self.ui.btn_skip_forward):
            btn.setFlat(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(_PLAYBACK_BUTTONS_QSS)
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
        self._chrome_theme = _tok_boot.DEFAULT_CHROME_THEME

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
        icon_path = get_resource_path("logo.png")
        if os.path.exists(icon_path):
            self.ui.setWindowIcon(QIcon(icon_path))

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
        
        # --- Set default rendered_videos ---
        default_export_dir = os.path.join(get_save_directory(), "rendered_videos").replace('\\', '/')
        if not os.path.exists(default_export_dir):
            os.makedirs(default_export_dir, exist_ok=True)
        self.custom_destination = default_export_dir 
        # The button keeps a static "Save as…" label; the full path lives in the Output line.
            
        self.current_orig_bitrate = 0 # Bitrate of the selected original clip
        self.current_clip_duration_sec = 0
        self.render_queue = RenderQueue()
        self._selected_queue_job_id = None
        self._loading_queue_job = False
        self._queue_batch_active = False
        self.render_thread = None
        self._preview_clip_path = None
        self._clip_session_memory = {}

        
        # list of all supported resolutions for rendering
        self.all_qualities = [
            ("2160p (Best Quality)", 2160),
            ("1440p (Very good Quality)", 1440),
            ("1080p (Good Quality)", 1080),
            ("720p (Mid Quality)", 720),
            ("480p (Bad Quality)", 480),
            ("360p (Very bad Quality)", 360),
            ("260p (Worst Quality)", 260),
            ("144p (Old VHS tape)", 144)
        ]

        self.set_status("Ready")

        self.cache_dir = os.path.join(get_save_directory(), "cache")
        self.logs_dir = os.path.join(get_save_directory(), "logs")
        self.screenshots_dir = os.path.join(get_save_directory(), "Screenshots")

        if not os.path.exists(self.screenshots_dir):
            os.makedirs(self.screenshots_dir)

        if not os.path.exists(self.logs_dir):
            os.makedirs(self.logs_dir)

        self._session_ts = session_timestamp()
        self.current_log_file = setup_logging(self.logs_dir, APP_VERSION_STR, self._session_ts)
        self.current_mpv_log_file = mpv_log_path(self.logs_dir, self._session_ts)
        prune_old_logs(
            self.logs_dir,
            keep_paths=(self.current_log_file, self.current_mpv_log_file),
            max_files=40,
        )
        logging.info("Logs dir: %s", self.logs_dir)
        logging.info("Cache dir: %s", self.cache_dir)

        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir) # Create a cache folder if it doesn't exist
            
        self.json_cache_path = os.path.join(self.cache_dir, "games.json")
        self.game_names_cache = self.load_json_cache() # JSON
        self.game_icons_cache = {} # This is where we store downloaded images in memory
        if hasattr(self, "restore_salvage_verified_clips"):
            self.restore_salvage_verified_clips()

        # Apply the saved chrome color theme now that settings are reachable
        # (falls back to the built-in default theme when nothing is saved yet).
        from steempeg.ui import design_tokens as _tok_theme
        saved_theme = self.load_user_settings().get("chrome_theme", _tok_theme.DEFAULT_CHROME_THEME)
        self.apply_chrome_theme(saved_theme, persist=False)
        
        # 3. CONFIGURING THE INTERFACE (TABLE AND COMBOBOXES)
        if hasattr(self.ui, 'table_clips'):
            self.ui.table_clips.setColumnCount(4)
            # 1. CHANGE THE ORDER OF HEADINGS
            self.ui.table_clips.setHorizontalHeaderLabels(["Game Name", "Type", "Date", "Time"])
            self.ui.table_clips.setIconSize(QSize(16, 16))

            self.ui.table_clips.setFocusPolicy(Qt.NoFocus)
            self.ui.table_clips.viewport().setFocusPolicy(Qt.NoFocus)

            # GUI TABLE
            self.ui.table_clips.setStyleSheet("""
                QTableWidget { 
                    background: transparent; 
                    border: none; 
                    outline: none; 
                }
                QTableWidget::item { 
                    padding: 4px 12px; 
                    border-bottom: 1px solid #282828; 
                    color: #e0e0e0; 
                    font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', sans-serif;
                    font-size: 13px;
                    font-weight: 600; 
                }
                QTableWidget::item:hover { 
                    background-color: #303030; 
                }
                QTableWidget::item:selected { 
                    background-color: #3a2e54; 
                    color: #ffffff; 
                }
                
                
                QHeaderView {
                    background-color: transparent;
                    border: none;
                }
                QHeaderView::section {
                    background-color: #2a2a2a; 
                    color: #999999;
                    padding: 6px 14px;
                    border: 1px solid #353535; 
                    border-radius: 12px;
                    margin-right: 6px; 
                    margin-bottom: 6px; 
                    font-size: 12px;
                    font-weight: bold;
                }
                QHeaderView::section:hover {
                    background-color: #353535;
                    color: #ffffff;
                    border: 1px solid #555555;
                }
                QHeaderView::section:checked, QHeaderView::section:pressed {
                    background-color: #3a2e54; 
                    color: #b29ae7;
                    border: 1px solid #6b5a8e;
                }
                QHeaderView::up-arrow, QHeaderView::down-arrow {
                    width: 0px; height: 0px;
                }
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
            from PySide6.QtGui import QFont
            custom_font = QFont()
            custom_font.setFamilies(
                ["Segoe UI", "Noto Sans", "Twemoji", "Noto Emoji", "Noto Color Emoji", "DejaVu Sans"]
            )
            custom_font.setPointSize(10)
            custom_font.setWeight(QFont.DemiBold)
            self.ui.table_clips.setFont(custom_font)
            
            header.setSectionResizeMode(0, QHeaderView.Stretch)         
            header.setSectionResizeMode(1, QHeaderView.Interactive) # Switch to Interactive so they don't jump around when compressed.
            header.setSectionResizeMode(2, QHeaderView.Interactive) 
            header.setSectionResizeMode(3, QHeaderView.Interactive) 
            
            # Set the ideal width for the right columns
            self.ui.table_clips.setColumnWidth(1, 80)  # Type
            self.ui.table_clips.setColumnWidth(2, 130) # Date
            self.ui.table_clips.setColumnWidth(3, 100) # Duration
            
            self.ui.table_clips.itemSelectionChanged.connect(self.update_quality_options)
            self.ui.table_clips.itemSelectionChanged.connect(self.sync_grid_from_table_selection)
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
            mega_top_pill.setStyleSheet("""
                QFrame {
                    background-color: #2d2d2d;
                    border: 1px solid #353535;
                    border-radius: 20px;
                }
                QLabel { border: none; background: transparent; }
            """)

            # 2. Making the Text White
            lbl_view = qtw.QLabel("View")
            lbl_view.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")

            # 3. Create a List button (inactive) with white text.
            self.toggle_style_inactive = "background-color: transparent; color: #ffffff; border-radius: 12px; font-weight: bold; font-size: 12px; padding: 6px 16px; border: none;"

            # 4. Making the Clip Counter White
            self.lbl_clip_count = qtw.QLabel("• 0 Clips")
            self.lbl_clip_count.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px;")
            
            top_pill_layout = qtw.QHBoxLayout(mega_top_pill)
            top_pill_layout.setContentsMargins(16, 6, 16, 6) # Capsule Internal Padding
            top_pill_layout.setSpacing(14)
            self._top_pill_layout = top_pill_layout

            # "View" Text
            lbl_view = qtw.QLabel("View")
            self._lbl_view = lbl_view
            lbl_view.setStyleSheet("color: #777777; font-weight: bold; font-size: 13px;")

            # Grid / List Toggle
            self.toggle_pill = qtw.QFrame()
            self.toggle_pill.setStyleSheet("QFrame { background-color: #141414; border-radius: 14px; border: none; }")
            pill_layout = qtw.QHBoxLayout(self.toggle_pill)
            pill_layout.setContentsMargins(2, 2, 2, 2)
            pill_layout.setSpacing(0)

            self.btn_view_grid = qtw.QPushButton("Grid")
            self.btn_view_list = qtw.QPushButton("List")
            
            self.toggle_style_active = "background-color: #5138e6; color: white; border-radius: 12px; font-weight: bold; font-size: 12px; padding: 6px 16px; border: none;"
            self.toggle_style_inactive = "background-color: transparent; color: #888888; border-radius: 12px; font-weight: bold; font-size: 12px; padding: 6px 16px; border: none;"

            self.btn_view_list.setStyleSheet(self.toggle_style_inactive)
            self.btn_view_grid.setStyleSheet(self.toggle_style_active)
            self.btn_view_list.setCursor(qtc.Qt.PointingHandCursor)
            self.btn_view_grid.setCursor(qtc.Qt.PointingHandCursor)

            pill_layout.addWidget(self.btn_view_grid)
            pill_layout.addWidget(self.btn_view_list)

            # Counter
            self.lbl_clip_count = qtw.QLabel("• 0 Clips")
            self.lbl_clip_count.setStyleSheet("color: #777777; font-weight: bold; font-size: 13px;")

            # BREATHABLE FILTER PAD
            self.btn_filter_pill = FilterPillButton()
            
            # Creating the menu and setting up the click handler!
            self.filter_menu = FilterMenu(self.ui)
            self.btn_filter_pill.clicked.connect(self.show_filter_menu)
            
            # Lbuild the island
            top_pill_layout.addWidget(lbl_view)
            top_pill_layout.addWidget(self.toggle_pill)
            top_pill_layout.addWidget(self.lbl_clip_count)

            top_pill_layout.addWidget(self.btn_filter_pill)

            top_bar_layout.addWidget(mega_top_pill)

            # 2. KILLING A QT TABLE 
            from steempeg.ui.library.library_styles import LIBRARY_GRID_STYLE, LIBRARY_TABLE_STYLE

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

            self.ui.table_clips.setStyleSheet(LIBRARY_TABLE_STYLE)
            
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
            # We strictly fix the card sizes so they don't fly apart when hidden!
            self.grid_clips.setUniformItemSizes(True)
            self.grid_clips.setSelectionMode(qtw.QAbstractItemView.ExtendedSelection)
            self.grid_clips.setDragDropMode(qtw.QAbstractItemView.NoDragDrop)
            self.grid_clips.setMovement(qtw.QListView.Static)
            self.grid_clips.itemSelectionChanged.connect(self.on_grid_selection_changed)
            self.grid_clips.setStyleSheet(LIBRARY_GRID_STYLE)
            self.grid_clips.setVerticalScrollBarPolicy(qtc.Qt.ScrollBarAlwaysOff)

            original_parent_layout = self.ui.table_clips.parentWidget().layout()
            original_idx = -1
            if original_parent_layout:
                original_idx = original_parent_layout.indexOf(self.ui.table_clips)

            # 4. LIBRARY BLOCK
            self.library_views_container = qtw.QFrame()
            self.library_views_container.setStyleSheet("QFrame { background-color: #2d2d2d; border: 1px solid #353535; border-radius: 12px; }")
            views_layout = qtw.QVBoxLayout(self.library_views_container)
            views_layout.setContentsMargins(10, 10, 10, 10)
            
            self.wrap_library_views_in_stack(views_layout)

            from steempeg.ui.library.library_styles import install_library_scroll_sync

            install_library_scroll_sync(self)

            # 5. Putting It All Together
            self.left_master_layout = qtw.QVBoxLayout()
            self.left_master_layout.setContentsMargins(0, 0, 0, 0)
            self.left_master_layout.setSpacing(5)

            self.left_master_layout.addLayout(cm_row)
            self.left_master_layout.addLayout(top_bar_layout)
            self.left_master_layout.addWidget(self.library_views_container)
            
            # Insert our new mega-block back into the SAVED old layout.
            if original_parent_layout:
                if original_idx != -1: 
                    original_parent_layout.insertLayout(original_idx, self.left_master_layout)
                else: 
                    original_parent_layout.addLayout(self.left_master_layout)

            # 6. ✨ DYNAMIC TOGGLES UwU ✨
            from steempeg.ui.layout_defaults import DEFAULT_LIBRARY_VIEW

            self.btn_view_list.clicked.connect(lambda: self.set_view_mode("list"))
            self.btn_view_grid.clicked.connect(lambda: self.set_view_mode("grid"))
            self.set_view_mode(DEFAULT_LIBRARY_VIEW)

        # --- UI INJECTION: SORTING PANEL (NEXT TO FILTER BUTTON) ---
        from PySide6.QtWidgets import QLabel, QComboBox, QSizePolicy

        # 1. Create a text label (like the one in View)
        lbl_sorting = QLabel("Sorting")
        self._lbl_sorting = lbl_sorting
        lbl_sorting.setStyleSheet("color: #888888; font-weight: bold; font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; font-size: 13px;")

        # 2. Creating a stylish sorting dropdown list
        self.combo_sort = QComboBox()
        self.combo_sort.setCursor(Qt.PointingHandCursor)
        # Size to the widest entry, but allow shrink on Deck-class left panes
        # (compact min ~360). Popup still uses the full longest-entry width.
        self.combo_sort.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo_sort.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.combo_sort.setStyleSheet(compact_combo_stylesheet(settings_popup=True))

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
        self.combo_sort.setMaxVisibleItems(12)

        # Use the Source Info value font so the sort combo matches the rest of the UI.
        # An ancestor stylesheet font does NOT reliably style a non-editable combo's
        # painted text, so set family + weight + size explicitly on the widget.
        _sort_font = self.combo_sort.font()
        _sort_font.setFamily("Segoe UI")
        _sort_font.setBold(True)
        _sort_font.setPixelSize(13)
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
            self.ui.settings_tabs.setCurrentIndex(0)
            from PySide6.QtWidgets import QPushButton, QWidget, QHBoxLayout, QVBoxLayout, QFrame, QScrollArea, QSizePolicy
            from PySide6.QtCore import QObject, QEvent
            
            # 1. Hide the old tab bar
            self.ui.settings_tabs.tabBar().hide()
            
            # STEP 1
            # Apply transparency ONLY to the page itself using its ID, so as not to break the buttons inside
            for i in range(self.ui.settings_tabs.count()):
                widget = self.ui.settings_tabs.widget(i)
                if widget:
                    obj_name = widget.objectName()
                    if obj_name:
                        widget.setStyleSheet(f"QWidget#{obj_name} {{ background: transparent; border: none; }}")
                    else:
                        widget.setAttribute(Qt.WA_TranslucentBackground)
            
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
            self.neo_wrapper.setStyleSheet("QWidget#neo_wrapper { background-color: #2d2d2d; border-radius: 16px; border: 1px solid #383838; }")
            
            neo_layout = QHBoxLayout(self.neo_wrapper)
            neo_layout.setContentsMargins(0, 0, 0, 0)
            neo_layout.setSpacing(0)
            
            # 3. LEFT CIRCLE (Sidebar)
            sidebar_frame = QFrame()
            self._neo_sidebar = sidebar_frame
            sidebar_frame.setFixedWidth(220)
            sidebar_frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            sidebar_frame.setStyleSheet("""
                QFrame { background: transparent; border: none; border-right: 1px solid #383838; }
            """)
            sidebar_layout = QVBoxLayout(sidebar_frame)
            self._neo_sidebar_layout = sidebar_layout
            sidebar_layout.setAlignment(Qt.AlignTop)
            sidebar_layout.setContentsMargins(10, 15, 10, 15)
            sidebar_layout.setSpacing(10)
            
            pill_style = """
                QPushButton {
                    background-color: transparent; color: #a0a0a0;
                    border: 2px solid transparent; border-radius: 14px;
                    padding: 10px 15px; text-align: left; font-size: 14px; font-weight: 700;
                }
                QPushButton:hover { background-color: #383838; border: 2px solid #5a4b7a; color: #e0e0e0; }
                QPushButton:checked { background-color: #252525; border: 2px solid #8e7cc3; color: #ffffff; }
            """
            self._neo_nav_pill_style_template = True
            
            self.neo_nav_buttons = []
            custom_names = ["ℹ️  Source Info", "🎬  Video Settings", "🎵  Audio Settings", "🚀  Export Settings"]
            
            for i in range(self.ui.settings_tabs.count()):
                text = custom_names[i] if i < len(custom_names) else self.ui.settings_tabs.tabText(i)
                btn = QPushButton(text)
                btn.setCheckable(True)
                btn.setAutoExclusive(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(pill_style)
                btn.clicked.connect(lambda checked, idx=i: self.ui.settings_tabs.setCurrentIndex(idx))
                sidebar_layout.addWidget(btn)
                self.neo_nav_buttons.append(btn)
                
            if self.neo_nav_buttons:
                self.neo_nav_buttons[0].setChecked(True)
                
            self.ui.settings_tabs.currentChanged.connect(
                lambda idx: self.neo_nav_buttons[idx].setChecked(True) if idx < len(self.neo_nav_buttons) else None
            )
            # Make the scroll area size to the active page so short tabs don't get a phantom scrollbar
            self.ui.settings_tabs.currentChanged.connect(self.fit_settings_tab_to_page)
            
            neo_layout.addWidget(sidebar_frame)
            
            # 4. Right circle with scrol
            self.right_scroll = QScrollArea()
            self.right_scroll.setWidgetResizable(True)
            self.right_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            
            self.right_scroll.setStyleSheet("""
                QScrollArea { 
                    background: transparent; 
                    border: none;
                }
                QWidget#qt_scrollarea_viewport {
                    background: transparent;
                    border: none;
                }
                QScrollBar:vertical {
                    background: transparent;
                    width: 12px;
                    margin: 15px 5px 15px 0px;
                }
                QScrollBar::handle:vertical {
                    background: #5a4b7a;
                    min-height: 30px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #8e7cc3;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px; 
                }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                    background: none;
                }
            """)
            
            self.ui.settings_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.ui.settings_tabs.setStyleSheet("""
                QTabWidget { background: transparent; border: none; }
                QTabWidget::pane { border: none; background: transparent; }

                QLabel { color: #cccccc; font-weight: bold; background: transparent; font-family: 'Arial'; }
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
            # Rebuilding a QRegion mask via setMask() on every resize event reclips and
            # repaints the whole subtree, which shows up as vertical band artifacts
            # during a splitter drag. Debounce it so the mask is rebuilt once the drag
            # stops instead of on every pixel.
            #
            # Linux/XWayland+NVIDIA: skip entirely. Even a debounced setMask next to
            # an embedded mpv wid= surface shears the shell when the right splitter
            # grows the player into the queue (ghost chrome / black bands).
            if sys.platform == "win32":
                class RoundedCornerFilter(QObject):
                    def __init__(self, target):
                        super().__init__(target)
                        self._target = target
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
                            from PySide6.QtGui import QPainterPath, QRegion
                            path = QPainterPath()
                            path.addRoundedRect(
                                0.0, 0.0, float(obj.width()), float(obj.height()), 16.0, 16.0
                            )
                            obj.setMask(QRegion(path.toFillPolygon().toPolygon()))
                        except Exception:
                            pass

                self.corner_mask = RoundedCornerFilter(self.right_scroll)
                self.right_scroll.installEventFilter(self.corner_mask)
            
            neo_layout.addWidget(self.right_scroll)
            
            # 5. Placing our wrapper back in the original location without conflicts
            if parent_layout:
                if insert_idx != -1:
                    parent_layout.insertWidget(insert_idx, self.neo_wrapper)
                else:
                    parent_layout.addWidget(self.neo_wrapper)
        
        from steempeg.ui.render_panel import restyle_video_page, restyle_audio_page, restyle_source_page, restyle_export_page
        restyle_video_page(self.ui)
        restyle_audio_page(self.ui)
        restyle_source_page(self.ui)
        restyle_export_page(self.ui)

        # Give each render combo its OWN stylesheet so the field text matches the
        # Source Info value labels (Segoe UI, 14px, bold) instead of the app default.
        if hasattr(self.ui, 'settings_tabs'):
            from PySide6.QtWidgets import QComboBox as _QComboBox
            _combo_qss = settings_panel_stylesheet(
                "QComboBox { font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"
                " font-size: 13px; font-weight: bold; }"
            )
            for _combo in self.ui.settings_tabs.findChildren(_QComboBox):
                _combo.setStyleSheet(_combo_qss)
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
        pill_style = """
            QFrame { 
                background-color: #2d2d2d; 
                border-radius: 16px; 
                border: 1px solid #383838;
                font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
            }
        """
        
        unified_table_style = """
            QPushButton { 
                background-color: #383838; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 14px; 
                font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
                font-weight: bold; 
                font-size: 13px; 
                padding: 4px 12px; 
                min-height: 24px; 
            }
            QPushButton:hover { background-color: #404040; border: 2px solid #6b5a8e; }
            QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
            QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
            QPushButton::menu-indicator { image: none; }
        """

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
            
        # 5. Color the buttons and add cursors
        if btn_about:
            btn_about.setStyleSheet(unified_table_style)
            btn_about.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn_about.setCursor(Qt.PointingHandCursor)
        if btn_update:
            btn_update.setStyleSheet(unified_table_style)
            btn_update.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn_update.setCursor(Qt.PointingHandCursor)
            
        # 6. LAY OUT THE BUTTONS BY FLOORS (70/30 on top, 50/50 on the bottom)
        top_row.addWidget(self.folder_picker, 7)
        top_row.addWidget(self.btn_refresh, 3)
        
        if btn_about: bottom_row.addWidget(btn_about, 5)
        if btn_update: bottom_row.addWidget(btn_update, 5)
        
        # 7. RECOVERING SIGNALS (Presses)
        self.btn_refresh.main_btn.clicked.connect(self.refresh_library)
        if hasattr(self, "setup_refresh_menu"):
            self.setup_refresh_menu()
        self.folder_picker.main_btn.clicked.connect(self.choose_folder)
        self.folder_picker.add_btn.clicked.connect(self.show_folders_panel)
        if hasattr(self.ui, 'destination_button'):
            self.ui.destination_button.clicked.connect(self.choose_destination)
        if btn_about: btn_about.clicked.connect(self.show_about_dialog)
        if btn_update: btn_update.clicked.connect(self.check_for_updates)
        self.ui.btn_start.clicked.connect(self.start_render_thread)
        self.ui.btn_start.setEnabled(False)



        try:
            import PySide6.QtWidgets as qtw
            import PySide6.QtCore as qtc

            # 1. OUR ORIGINAL, BEAUTIFUL STYLES

            # Logs 
            btn_logs_style = """
                QPushButton { font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; font-size: 12px; font-weight: bold; background-color: #383838; color: #ffffff; border: 2px solid #444444; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #404040; border: 2px solid #6b5a8e; }
                QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
                QPushButton::menu-indicator { image: none; }
            """
            
            # Start (Green — OUR BENCHMARK)
            start_btn_style = """
                QPushButton { font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; font-size: 12px; font-weight: bold; background-color: #2e6b32; color: #ffffff; border: 2px solid #3e8e41; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #3e8e41; border: 2px solid #57c75b; }
                QPushButton:pressed { background-color: #235226; border: 2px solid #3e8e41; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
            """

            # Pause (Yellow-Orange Copy of the Green One)
            btn_pause_style = """
                QPushButton { font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; font-size: 12px; font-weight: bold; background-color: #8c7314; color: #ffffff; border: 2px solid #a88b11; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #a88b11; border: 2px solid #c9a716; }
                QPushButton:pressed { background-color: #6b570d; border: 2px solid #a88b11; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
                QPushButton::menu-indicator { image: none; }
            """
            
            # Cancellation (Red copy of the green one)
            btn_cancel_style = """
                QPushButton { font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; font-size: 12px; font-weight: bold; background-color: #8a2525; color: #ffffff; border: 2px solid #a82e2e; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #a82e2e; border: 2px solid #cc3939; }
                QPushButton:pressed { background-color: #661a1a; border: 2px solid #a82e2e; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
                QPushButton::menu-indicator { image: none; }
            """

            # FORCE INJECT STYLES DIRECTLY INTO BUTTONS
            if hasattr(self.ui, 'btn_start'): 
                self.ui.btn_start.setStyleSheet(start_btn_style)
            elif hasattr(self.ui, 'btn_render'): 
                self.ui.btn_render.setStyleSheet(start_btn_style)
                
            if hasattr(self.ui, 'btn_pause'): 
                self.ui.btn_pause.setStyleSheet(btn_pause_style)
                
            if hasattr(self.ui, 'btn_cancel'): 
                self.ui.btn_cancel.setStyleSheet(btn_cancel_style)
                
            if hasattr(self.ui, 'btn_logs'): 
                self.ui.btn_logs.setStyleSheet(btn_logs_style)

            # 2. Remove Padding from the Parent Element for Perfect Width Symmetry
            parent_widget = self.ui.btn_start.parentWidget() if hasattr(self.ui, 'btn_start') else None
            if parent_widget:
                parent_widget.setStyleSheet("background: transparent; border: none;")
                if parent_widget.layout():
                    # Resetting the outer margins so that the monolith aligns perfectly with the width of the top tabs.
                    parent_widget.layout().setContentsMargins(0, 0, 0, 0)

            # 3. Creating Our Single Monolithic Circle
            self.render_dashboard = qtw.QFrame()
            self.render_dashboard.setStyleSheet("""
                QFrame { background-color: #2d2d2d; border: 1px solid #353535; border-radius: 12px; }
                QLabel { border: none; background: transparent; }
            """)
            
            dash_layout = qtw.QVBoxLayout(self.render_dashboard)
            dash_layout.setContentsMargins(18, 16, 18, 16)
            dash_layout.setSpacing(12)

            _status_font = "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"

            header_block = qtw.QVBoxLayout()
            header_block.setSpacing(12)

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

                self.bottom_text_label = qtw.QLabel()
                self.bottom_text_label.setStyleSheet(
                    f"color: #e0e0e0; font-size: 14px; font-weight: bold; {_status_font}"
                )

                summary_left_layout.addWidget(self.bottom_icon_label, 0, qtc.Qt.AlignVCenter)
                summary_left_layout.addWidget(self.bottom_text_label, 0, qtc.Qt.AlignVCenter)
                top_row.addWidget(summary_left, 0, qtc.Qt.AlignVCenter)

                def reset_bottom_summary():
                    css_icon = get_resource_path("unknown_icon.png").replace('\\', '/')

                    self.bottom_icon_label.setStyleSheet(f"image: url('{css_icon}'); background: transparent; border: none;")
                    self.bottom_text_label.setText("<b>Select a clip to begin...</b>")

                    if hasattr(self, 'custom_icon_label') and hasattr(self, 'custom_text_label'):
                        self.custom_icon_label.setStyleSheet(f"image: url('{css_icon}'); background: transparent; border: none;")
                        self.custom_text_label.setText("Select a clip to preview...")

                    css_logo_main = get_resource_path("logo.png").replace('\\', '/')
                    if hasattr(self, 'place_logo') and hasattr(self, 'place_text'):
                        self.place_logo.setStyleSheet(f"image: url('{css_logo_main}'); background: transparent; border: none;")
                        self.place_text.setText("Please select a clip from the library")
                        self.place_text.setStyleSheet("color: #888888; font-size: 14px; font-weight: bold; margin-top: 15px;")

                self.reset_bottom_summary = reset_bottom_summary
                self.reset_bottom_summary()

            top_row.addStretch(1)

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
            btn_row.setSpacing(12) # Beautiful, even spacing between buttons
            
            # Strict Sequence
            buttons_queue = ['btn_start', 'btn_pause', 'btn_cancel', 'btn_logs']
            
            for btn_name in buttons_queue:
                if hasattr(self.ui, btn_name):
                    btn = getattr(self.ui, btn_name)
                    btn.setSizePolicy(qtw.QSizePolicy.Expanding, qtw.QSizePolicy.Fixed)
                    btn.setMinimumHeight(36) 
                    

                    # 1. Take the old button style
                    old_style = btn.styleSheet()
                    
                    # 2. Hardcode the 13px font, just like on the Refresh button!
                    btn.setStyleSheet(old_style + "\nQPushButton { font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif; font-size: 13px; font-weight: bold; }")
                    
                    btn_row.addWidget(btn)

            dash_layout.addLayout(btn_row)

            # 4. Container Assembly
            if parent_widget and parent_widget.layout():
                pl = parent_widget.layout()
                pl.setContentsMargins(0, 0, 0, 0)
                pl.setSpacing(0)
                pl.addWidget(self.render_dashboard)

            if hasattr(self, 'update_status_indicator'):
                self.update_status_indicator("Ready", "ready")

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
        from PySide6.QtWidgets import QFrame, QStackedLayout, QVBoxLayout, QLabel
        
        # --- 1. FAKE BLACK BACKGROUND (Fills the entire space) ---
        self.video_wrapper = QFrame()
        self.video_wrapper.setStyleSheet("background-color: transparent; border: none;") 
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
        
        # 2 Placeholder
        self.placeholder_frame = QFrame()
        self.placeholder_frame.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e; 
                border-radius: 0px; 
                border: 1px solid #333333;
            }
        """)
        place_layout = QVBoxLayout(self.placeholder_frame)
        place_layout.setAlignment(Qt.AlignCenter)
        
        self.place_logo = QLabel()
        logo_path = get_resource_path("logo.png")
        if os.path.exists(logo_path):
            from PySide6.QtGui import QPixmap
            self.place_logo.setPixmap(
                QPixmap(logo_path).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.place_logo.setAlignment(Qt.AlignCenter)
        
        self.place_text = QLabel("Please select a clip from the library")
        self.place_text.setStyleSheet("color: #888888; font-size: 14px; font-weight: bold; margin-top: 15px;")
        self.place_text.setAlignment(Qt.AlignCenter)
        
        place_layout.addWidget(self.place_logo)
        place_layout.addWidget(self.place_text)
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
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
        
        self.player_header_frame = QFrame()
        self.player_header_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border-radius: 6px;
            }
        """)
        header_layout = QHBoxLayout(self.player_header_frame)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(10)
        
        self.custom_icon_label = QLabel()
        self.custom_icon_label.setFixedSize(24, 24)
        self.custom_icon_label.setPixmap(QIcon(get_resource_path("unknown_icon.png")).pixmap(24, 24))
        
        self.custom_text_label = QLabel("Select a clip to preview...")
        self.custom_text_label.setStyleSheet("color: white; font-size: 13px; font-weight: bold;")
        
        header_layout.addWidget(self.custom_icon_label)
        header_layout.addWidget(self.custom_text_label)
        header_layout.addStretch()

        # Status chips (health + preview badge) | action chips (close, later: preview settings).
        from PySide6.QtWidgets import QFrame, QPushButton, QWidget

        self.player_header_status = QWidget()
        status_row = QHBoxLayout(self.player_header_status)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)

        self.btn_clip_health = QPushButton()
        self.btn_clip_health.setCursor(Qt.PointingHandCursor)
        self.btn_clip_health.hide()
        self.btn_clip_health.clicked.connect(self.show_clip_health_menu)
        status_row.addWidget(self.btn_clip_health)

        self.label_playback_badge = QLabel()
        self.label_playback_badge.setStyleSheet(
            "color: #ffffff; font-weight: bold; font-size: 12px;"
            "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"
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

        _HEADER_ACTION_CHIP = 30
        _HEADER_ACTION_ICON = 16
        _HEADER_CHIP = (
            "border-radius: 8px;"
            "padding: 0px;"
            "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"
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

        right_layout = self.ui.right_panel.layout()
        if right_layout:
            right_layout.insertWidget(0, self.player_header_frame)
            
        # Hide old labels from Qt Designer
        if hasattr(self.ui, 'label_player_header'):
            self.ui.label_player_header.hide()
        if hasattr(self.ui, 'label_player_icon'):
            self.ui.label_player_icon.hide()


        player_style = """
        QSlider#slider_timeline::groove:horizontal {
            border-radius: 2px;
            height: 4px;
            background: rgba(255, 255, 255, 50); 
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
            transform: scale(1.2);
            background: #1a9fff; 
        }
        """
        self.ui.right_panel.setStyleSheet(player_style)

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
                
                self.player_footer_frame.setStyleSheet("""
                    #HudFrame {
                        background-color: #2d2d2d;
                        border-radius: 6px;
                    }
                """ + _PLAYBACK_BUTTONS_QSS)
                
                v_layout = QVBoxLayout(self.player_footer_frame)
                v_layout.setContentsMargins(15, 12, 15, 12)
                v_layout.setSpacing(5)
                
                # ROW 1: The Custom Timeline
                if not hasattr(self, 'custom_timeline'):
                    self.custom_timeline = CustomTimelineWidget()
                    self.custom_timeline.canvas.marker_store.set_cache_dir(self.cache_dir)
                v_layout.addWidget(self.custom_timeline)
                v_layout.addSpacing(6)
                # ROW 2: The Time Label AND Theater Button (Perfectly centered)
                time_layout = QHBoxLayout()

                # --- IRONCLAD CENTERING (3 EQUAL BLOCKS) ---

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

                # 2. CENTER BLOCK (Timer)
                center_wrap = QWidget()
                cw = QHBoxLayout(center_wrap)
                cw.setContentsMargins(0, 0, 0, 0)
                self.ui.label_time.setParent(self.player_footer_frame)
                self.ui.label_time.setAlignment(Qt.AlignCenter)
                self.ui.label_time.setStyleSheet("color: #cccccc; font-size: 13px; font-weight: bold; background: transparent;")
                cw.addWidget(self.ui.label_time, alignment=Qt.AlignCenter)

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
                
                # Apply a slightly golden premium style
                self.btn_trim.setStyleSheet("background-color: #cfa94a; color: black; border-radius: 15px; padding: 0 12px; font-weight: bold;")
                
                # Try to load custom scissors icon
                trim_icon_path = get_resource_path("trim_icon.png")
                if os.path.exists(trim_icon_path):
                    self.btn_trim.setIcon(QIcon(trim_icon_path))
                    self.btn_trim.setText(" Trim")
                else:
                    self.btn_trim.setText("✂️ Trim")
                
                # --- THEATER & FULLSCREEN PILL CONTAINER ---
                self.pill_container = QFrame()
                # Elegant dark background with full border control
                self.pill_container.setStyleSheet("QFrame { background-color: #4e4e4e; border-radius: 20px; border: none; }")
                
                pill_layout = QHBoxLayout(self.pill_container)
                # Add outer padding inside the pill (5px left/right) and 4px spacing between buttons
                pill_layout.setContentsMargins(5, 0, 5, 0)
                pill_layout.setSpacing(4) 

                # 1. THEATER MODE BUTTON
                self.btn_theater = QPushButton()
                self.btn_theater.setFixedSize(40, 40) 
                self.btn_theater.setCursor(Qt.PointingHandCursor)
                self.btn_theater.setToolTip("Theater Mode")
                self.btn_theater.setStyleSheet("""
                    QPushButton { background: transparent; border-radius: 20px; border: none; } 
                    QPushButton:hover { background: rgba(255, 255, 255, 40); }
                """)
                
                t_icon_path = get_resource_path("theatremode.png")
                if os.path.exists(t_icon_path):
                    self.btn_theater.setIcon(QIcon(t_icon_path))
                    self.btn_theater.setIconSize(QSize(26, 26))
                else:
                    self.btn_theater.setText("🎦")

                # 2. FULLSCREEN MODE BUTTON
                self.btn_fullscreen = QPushButton()
                self.btn_fullscreen.setFixedSize(40, 40)
                self.btn_fullscreen.setCursor(Qt.PointingHandCursor)
                self.btn_fullscreen.setToolTip("Full Screen (Press ESC to exit)")
                self.btn_fullscreen.setStyleSheet("""
                    QPushButton { background: transparent; border-radius: 20px; border: none; } 
                    QPushButton:hover { background: rgba(255, 255, 255, 40); }
                """)
                
                fs_icon_path = get_resource_path("btn_fullscreen.png")
                if os.path.exists(fs_icon_path):
                    self.btn_fullscreen.setIcon(QIcon(fs_icon_path))
                    # --- OPTIMIZED ACCORDING TO SMPEGUI13.UI BALANCE ---
                    self.btn_fullscreen.setIconSize(QSize(22, 22)) 
                else:
                    self.btn_fullscreen.setText("🔲")

                # Connect button signals
                self.btn_theater.clicked.connect(self.toggle_theater_mode)
                self.btn_trim.clicked.connect(self.toggle_trim_state)
                self.btn_fullscreen.clicked.connect(self.toggle_fullscreen) 
                
                pill_layout.addWidget(self.btn_theater)
                pill_layout.addWidget(self.btn_fullscreen)

                # New Cropping Toolbar
                self.trim_tools_pill = QFrame()
                self.trim_tools_pill.setStyleSheet("QFrame { background-color: #4e4e4e; border-radius: 20px; border: none; }")
                
                trim_tools_layout = QHBoxLayout(self.trim_tools_pill)
                trim_tools_layout.setContentsMargins(5, 0, 5, 0)
                trim_tools_layout.setSpacing(4)
                
                btn_style = """
                    QPushButton { background: transparent; border-radius: 20px; border: none; } 
                    QPushButton:hover { background: rgba(255, 255, 255, 40); }
                    QPushButton:pressed { background: rgba(255, 255, 255, 60); }
                """
                
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

                # Inject into the footer control bar
                # New Marker Button
                self.btn_add_marker = QPushButton()
                self.btn_add_marker.setFixedSize(40, 40)
                self.btn_add_marker.setCursor(Qt.PointingHandCursor)
                self.btn_add_marker.setToolTip("Add User Marker")
                
                # Style just like the audio: transparent, no shitty outlines.
                btn_style_marker = """
                    QPushButton { background: transparent; border: none; }
                    QPushButton:hover { background: rgba(255, 255, 255, 30); border-radius: 6px; }
                    QPushButton:pressed { background: rgba(255, 255, 255, 50); }
                """
                self.btn_add_marker.setStyleSheet(btn_style_marker)
                
                icon_marker_btn = get_resource_path("pointuser.png")
                if os.path.exists(icon_marker_btn):
                    self.btn_add_marker.setIcon(QIcon(icon_marker_btn))
                    self.btn_add_marker.setIconSize(QSize(22, 22))
                else:
                    self.btn_add_marker.setText("📍")
                
                self.btn_add_marker.clicked.connect(self.add_user_marker)

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
                rw.addWidget(self.btn_add_marker, alignment=Qt.AlignVCenter) 
                rw.addWidget(self.btn_screenshot, alignment=Qt.AlignVCenter) 
                rw.addWidget(self.trim_tools_pill, alignment=Qt.AlignVCenter)
                rw.addWidget(self.btn_trim, alignment=Qt.AlignVCenter)
                rw.addWidget(self.pill_container, alignment=Qt.AlignVCenter)

                # Remember original layout index for seamless restoring
                self.controls_layout_index = controls_index

                # Glue the 3 blocks together with EQUAL weight (stretch=1) so the center is ABSOLUTE!
                time_layout.addWidget(left_wrap, 1)
                time_layout.addWidget(center_wrap, 1)
                time_layout.addWidget(right_wrap, 1)

                v_layout.addLayout(time_layout)
                
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

                # 3. Top Box (Player and Buttons)
                self.top_v_wrap = QWidget()
                top_v_layout = QVBoxLayout(self.top_v_wrap)
                # Add a 10px margin at the bottom (before the splitter)
                top_v_layout.setContentsMargins(0, 0, 0, 10) 
                top_v_layout.setSpacing(right_layout.spacing())

                # 4. Bottom Box (Tabs and Status)
                self.bottom_v_wrap = QWidget()
                bottom_v_layout = QVBoxLayout(self.bottom_v_wrap)
                # Add a 10px margin at the top (after the splitter)
                bottom_v_layout.setContentsMargins(0, 10, 0, 0) 
                bottom_v_layout.setSpacing(right_layout.spacing())

                # 5. Carefully arrange the components into two boxes.
                put_in_bottom = False
                for item in all_items:
                    #Now the splitter looks for both the tabs and our new wrapper.
                    if item.widget() == getattr(self.ui, 'settings_tabs', None) or item.widget() == getattr(self, 'neo_wrapper', None):
                        put_in_bottom = True
                    
                    target_layout = bottom_v_layout if put_in_bottom else top_v_layout
                    
                    # Transferring safely, preserving all proportions and springs
                    if item.widget(): target_layout.addWidget(item.widget())
                    elif item.layout(): target_layout.addLayout(item.layout())
                    elif item.spacerItem(): target_layout.addItem(item.spacerItem())

                from PySide6.QtWidgets import QSizePolicy
                from PySide6.QtCore import QObject, QEvent
                # 1. FIX PLAYER BUTTONS STRETCHING:
                # Force the video container to absorb 100% of extra vertical space.
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
                # Beautiful modern splitter handle
                
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
                    STEAM_DECK_WIDTH,
                    queue_panel_min_width,
                )
                from steempeg.ui.render_queue_panel import RenderQueuePanel

                queue_view = self.get_layout_setting("queue_view_mode", DEFAULT_QUEUE_VIEW)
                self.render_queue_panel = RenderQueuePanel(initial_view_mode=queue_view)
                self.render_queue_panel.setMinimumWidth(
                    queue_panel_min_width(self.ui.width() or STEAM_DECK_WIDTH)
                )
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
                self.right_h_splitter.setCollapsible(0, False)
                # Collapsible(1) toggled in _sync_queue_splitter_visibility:
                # False while jobs are open (prevent crush → DWM ghosts), True when empty.
                self.right_h_splitter.setCollapsible(1, True)
                self.right_h_splitter.setStyleSheet(self.ui.main_splitter.styleSheet())

                right_layout.addWidget(self.right_content_wrap)

                panel_idx = self.ui.main_splitter.indexOf(self.ui.right_panel)
                self.ui.right_panel.setParent(None)
                self.right_h_splitter.addWidget(self.ui.right_panel)
                self.right_h_splitter.addWidget(self.render_queue_panel)
                self.ui.main_splitter.insertWidget(panel_idx, self.right_h_splitter)
                self.right_h_splitter.setSizes(DEFAULT_RIGHT_H_SPLITTER_SIZES)

                if hasattr(self, "_load_persisted_render_queue"):
                    self._load_persisted_render_queue()
                    self._update_start_button_label()
                    self.refresh_render_queue_panel(sync_splitter=False)

                # Saving the new index for Fullscreen
                self.controls_layout_index = top_v_layout.indexOf(self.player_footer_frame)
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
        
        # We place our smart wrapper into the standard layout.
        layout = QVBoxLayout(self.ui.video_container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.mpv_wrapper = MPVWrapper()
        layout.addWidget(self.mpv_wrapper)
        
        
        self.aspect_frame = self.mpv_wrapper.aspect_frame
        self.mpv_screen = self.mpv_wrapper.mpv_screen

        # Windows: create embedded mpv immediately.
        # Linux/Bazzite: do NOT create libmpv at startup — even vo=null still
        # loads scripts and, with QT xcb + NVIDIA, the window can hard-freeze
        # (black, unkillable). Player is created lazily on first play().
        self._linux_mpv_vo_attached = False
        self.current_mpv_log_file = mpv_log_path_str
        if sys.platform == "win32":
            mpv_opts = {
                "panscan": 1.0,
                "keepaspect": "no",
                "keep_open": "yes",
                "log_file": mpv_log_path_str,
                "loglevel": "info",
                "wid": int(self.mpv_screen.winId()),
                "vo": "gpu",
                "hwdec": "auto",
                "ao": "wasapi",
            }
            self.player = mpv.MPV(**mpv_opts)
            try:
                self.player["af"] = "rubberband"
            except Exception as exc:
                logging.warning("mpv rubberband af unavailable: %s", exc)
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
            # You can set the icon programmatically too
            icon_path = get_resource_path("btn_fullscreen.png")
            if os.path.exists(icon_path):
                self.ui.btn_fullscreen.setIcon(QIcon(icon_path))
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

            # Prefer comfort sizes on big screens; Deck-class windows use compact.
            avail_w = self.ui.width() or STEAM_DECK_WIDTH
            default_sizes = (
                DEFAULT_MAIN_SPLITTER_SIZES_COMPACT
                if is_compact_layout(avail_w)
                else DEFAULT_MAIN_SPLITTER_SIZES
            )
            self.ui.main_splitter.setSizes(
                self.get_layout_setting("main_splitter_sizes", default_sizes)
            )
            self.ui.left_panel.setMinimumWidth(left_panel_min_width(avail_w))
            self._apply_responsive_layout_mins()

        self._apply_dark_shell()

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

    def _current_app_bg(self) -> str:
        """Background color for the current chrome theme."""
        from steempeg.ui import design_tokens as tok
        return tok.chrome_theme_colors(getattr(self, "_chrome_theme", "default"))["app_bg"]

    def _shell_stylesheet(self, bg_color: str) -> str:
        """Window stylesheet: dialog background + shared tooltip chrome."""
        return f"""
            QDialog#Dialog, QWidget#Dialog {{ background-color: {bg_color}; }}

            QToolTip {{
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 4px;
                font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
                font-size: 11px;
                font-weight: bold;
                padding: 4px 8px;
            }}
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

    def _apply_dark_shell(self):
        """Paint every major shell widget dark so unsettled layout never flashes white."""
        from steempeg.ui.layout_defaults import HORIZONTAL_SPLITTER_STYLESHEET

        dark = self._current_app_bg()
        shell = f"background-color: {dark};"
        for attr in ("left_panel", "right_panel"):
            panel = getattr(self.ui, attr, None)
            if panel is not None:
                panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                panel.setAutoFillBackground(True)
                panel.setStyleSheet(shell)
        splitter_qss = f"QSplitter {{ {shell} }} {HORIZONTAL_SPLITTER_STYLESHEET}"
        for splitter_attr in ("main_splitter", "right_h_splitter"):
            splitter = getattr(self.ui, splitter_attr, None) or getattr(self, splitter_attr, None)
            if splitter is not None:
                splitter.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                splitter.setStyleSheet(splitter_qss)

    def _sync_startup_layout(self):
        """Re-apply splitter sizes once the maximized window has real geometry."""
        self._ui_density = None  # force chrome density for the real window size
        self._apply_startup_splitter_sizes()
        if hasattr(self, "_restore_library_ui_state"):
            self._restore_library_ui_state()
            QTimer.singleShot(500, self._restore_library_ui_state)
        if hasattr(self, "_library_ui_persist_ready"):
            QTimer.singleShot(250, lambda: setattr(self, "_library_ui_persist_ready", True))
        self.refresh_render_queue_panel(sync_splitter=True)
        self._start_startup_scans_after_restore()

    def _start_startup_scans_after_restore(self) -> None:
        """Kick off initial library scans once the shell is stable."""
        if not getattr(self, "_start_startup_scans_pending", False):
            return
        self._start_startup_scans_pending = False

        def _start():
            # Clips first; Rendered is deferred until clips finishes.
            if getattr(self, "clips_folders", None):
                self._startup_library_scan_active = True
                self._defer_rendered_scan_until_clips_done = True
                self.scan_clips()
            elif hasattr(self, "scan_rendered_outputs"):
                self.scan_rendered_outputs()

        QTimer.singleShot(0, _start)

    def on_main_window_resized(self):
        """Keep panel minimums + chrome density in sync with window width."""
        # Mins must track live; density restyle is deferred so continuous
        # lerp doesn't thrash queue cards / DWM on every pixel.
        self._apply_responsive_layout_mins(apply_density=False)
        timer = getattr(self, "_density_resize_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer

            timer = QTimer(self.ui if hasattr(self, "ui") else None)
            timer.setSingleShot(True)
            timer.setInterval(120)
            timer.timeout.connect(self._flush_ui_density_after_resize)
            self._density_resize_timer = timer
        timer.start()

    def _flush_ui_density_after_resize(self):
        self._apply_responsive_layout_mins(apply_density=True)

    def _apply_responsive_layout_mins(self, *, apply_density: bool = True):
        """Lerp panel mins + chrome density with window width (no binary cliff)."""
        from steempeg.ui.layout_defaults import (
            left_panel_min_width,
            queue_panel_min_width,
        )
        from steempeg.ui.ui_density import chrome_equal, density_for_width

        w = int(self.ui.width() or 0)
        if w <= 0:
            return

        left_min = left_panel_min_width(w)
        queue_min = queue_panel_min_width(w)

        if hasattr(self.ui, "left_panel") and self.ui.left_panel is not None:
            self.ui.left_panel.setMinimumWidth(left_min)
        panel = getattr(self, "render_queue_panel", None)
        if panel is not None:
            panel.setMinimumWidth(queue_min)

        # Clamp splitter sizes to new mins without resetting to comfort defaults.
        self._clamp_splitters_to_mins(left_min=left_min, queue_min=queue_min)

        if not apply_density:
            return

        dense = density_for_width(w)
        prev = getattr(self, "_ui_density", None)
        # Ignore float scale — otherwise every resize pixel restyles the whole UI
        # and rebuilds queue cards (DWM ghosts + floating text scraps).
        if chrome_equal(prev, dense):
            return
        self._ui_density = dense
        self._apply_ui_density(dense)

    def _clamp_splitters_to_mins(self, *, left_min: int, queue_min: int) -> None:
        """Keep current splitter ratios; only ensure mins are satisfiable."""
        main = getattr(self.ui, "main_splitter", None)
        if main is not None:
            sizes = main.sizes()
            total = sum(sizes)
            if total > 0 and len(sizes) >= 2:
                left = max(left_min, sizes[0])
                right = total - left
                if right < 200:
                    left = max(left_min, total - 200)
                    right = total - left
                if left != sizes[0] or right != sizes[1]:
                    main.setSizes([left, right])

        rhs = getattr(self, "right_h_splitter", None)
        if rhs is not None and getattr(self, "render_queue_panel", None) is not None:
            sizes = rhs.sizes()
            total = sum(sizes) if sum(sizes) > 0 else rhs.width()
            if total > 0 and len(sizes) >= 2 and sizes[1] > 0:
                queue_w = max(queue_min, sizes[1])
                player_w = total - queue_w
                if player_w < 360:
                    queue_w = max(queue_min, total - 360)
                    player_w = total - queue_w
                if queue_w != sizes[1]:
                    rhs.setSizes([player_w, queue_w])

        v_split = getattr(self, "main_v_splitter", None)
        if v_split is not None:
            from steempeg.ui.layout_defaults import restore_v_splitter_sizes

            h = int(self.ui.height() or 0)
            sizes = v_split.sizes()
            total = sum(sizes) if sum(sizes) > 0 else v_split.height()
            if h > 0 and total > 0 and len(sizes) >= 2 and sizes[1] > 0:
                max_bottom = max(180, int(h * 0.35))
                if sizes[1] > max_bottom:
                    bottom = max_bottom
                    top = max(total - bottom, 200)
                    v_split.setSizes([top, bottom])
                elif sizes[1] < 120 and sizes[1] > 0:
                    # Extremely crushed bottom — nudge toward a sane restore ratio.
                    v_split.setSizes(restore_v_splitter_sizes(total))

    def _apply_ui_density(self, dense):
        """Resize fonts/paddings/labels along the continuous density scale."""
        from steempeg.ui.ui_density import (
            NEO_NAV_COMFORT,
            NEO_NAV_COMPACT,
            folder_button_label,
            tab_label,
            updates_button_label,
        )
        from steempeg.ui.widgets.combo_chrome import combo_popup_item_rules

        # --- Library tabs ---
        tabs = getattr(self, "_library_tabs", None) or {}
        for mode, tab in tabs.items():
            if hasattr(tab, "set_label"):
                tab.set_label(tab_label(mode, dense))
            if hasattr(tab, "apply_density"):
                tab.apply_density(dense)
        add_btn = getattr(self, "btn_library_add", None)
        if add_btn is not None:
            sz = dense.add_tab_size
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

        # --- Left toolbar ---
        outer = getattr(self, "_left_toolbar_outer", None)
        if outer is not None:
            outer.setContentsMargins(dense.toolbar_margin_h, 0, dense.toolbar_margin_h, 0)
        pill_lay = getattr(self, "_top_pill_layout", None)
        if pill_lay is not None:
            pill_lay.setContentsMargins(
                dense.toolbar_pad_h, dense.toolbar_pad_v, dense.toolbar_pad_h, dense.toolbar_pad_v
            )
            pill_lay.setSpacing(dense.toolbar_spacing)
        for attr in ("_lbl_view", "_lbl_sorting"):
            lbl = getattr(self, attr, None)
            if lbl is not None:
                lbl.setVisible(not dense.compact)
                lbl.setStyleSheet(
                    f"color: #777777; font-weight: bold; font-size: {dense.toolbar_label_font}px;"
                )
        count = getattr(self, "lbl_clip_count", None)
        if count is not None:
            count.setStyleSheet(
                f"color: #777777; font-weight: bold; font-size: {dense.toolbar_label_font}px;"
            )
        self.toggle_style_active = (
            f"background-color: #5138e6; color: white; border-radius: 10px; font-weight: bold; "
            f"font-size: {dense.toggle_font}px; padding: {dense.toggle_pad}; border: none;"
        )
        self.toggle_style_inactive = (
            f"background-color: transparent; color: #888888; border-radius: 10px; font-weight: bold; "
            f"font-size: {dense.toggle_font}px; padding: {dense.toggle_pad}; border: none;"
        )
        # Re-apply current view toggle styles
        mode = getattr(self, "_clips_view_mode", None) or getattr(self, "current_view_mode", "grid")
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
            combo_qss = f"""
                QComboBox {{
                    background-color: #383838; color: #ffffff; border: 2px solid #444444;
                    border-radius: 8px; padding: {dense.combo_pad}; font-weight: bold;
                    font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif; font-size: {dense.combo_font}px;
                    min-height: {dense.combo_min_h}px;
                }}
                QComboBox:hover {{ background-color: #404040; border: 2px solid #6b5a8e; }}
                QComboBox:on {{ background-color: #383838; }}
                QComboBox::drop-down {{ border: none; padding-right: 5px; background: transparent; }}
            """ + combo_popup_item_rules(dense)
            combo.setStyleSheet(combo_qss)
            fnt = combo.font()
            fnt.setPixelSize(dense.combo_font)
            combo.setFont(fnt)

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
        footer_style = f"""
            QPushButton {{
                background-color: #383838; color: #ffffff; border: 2px solid #444444;
                border-radius: {dense.footer_radius}px; font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
                font-weight: bold; font-size: {dense.footer_font}px; padding: {dense.footer_pad};
                min-height: {dense.footer_min_h}px;
            }}
            QPushButton:hover {{ background-color: #404040; border: 2px solid #6b5a8e; }}
            QPushButton:pressed {{ background-color: #3a324a; border: 2px solid #b29ae7; }}
            QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}
            QPushButton::menu-indicator {{ image: none; }}
        """
        self._footer_unified_style = footer_style
        btn_about = getattr(self.ui, "btn_about", None)
        btn_update = getattr(self.ui, "btn_update_check", None)
        if btn_about is not None:
            btn_about.setStyleSheet(footer_style)
        if btn_update is not None:
            btn_update.setStyleSheet(footer_style)
            btn_update.setText(updates_button_label(dense))
            btn_update.setToolTip("Check for updates")
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

        # --- Neo settings sidebar ---
        neo = getattr(self, "_neo_sidebar", None)
        if neo is not None:
            neo.setFixedWidth(dense.neo_sidebar_w)
        neo_lay = getattr(self, "_neo_sidebar_layout", None)
        if neo_lay is not None:
            m = int(round(6 + (10 - 6) * dense.scale))
            t = int(round(8 + (15 - 8) * dense.scale))
            neo_lay.setContentsMargins(m, t, m, t)
            neo_lay.setSpacing(int(round(6 + (10 - 6) * dense.scale)))
        nav_names = NEO_NAV_COMPACT if dense.compact else NEO_NAV_COMFORT
        pill = f"""
            QPushButton {{
                background-color: transparent; color: #a0a0a0;
                border: 2px solid transparent; border-radius: {10 if dense.compact else 14}px;
                padding: {dense.neo_nav_pad}; text-align: left;
                font-size: {dense.neo_nav_font}px; font-weight: 700;
            }}
            QPushButton:hover {{ background-color: #383838; border: 2px solid #5a4b7a; color: #e0e0e0; }}
            QPushButton:checked {{ background-color: #252525; border: 2px solid #8e7cc3; color: #ffffff; }}
        """
        for i, btn in enumerate(getattr(self, "neo_nav_buttons", []) or []):
            if i < len(nav_names):
                btn.setText(nav_names[i])
            btn.setStyleSheet(pill)

        # --- Player transport ---
        for btn, w, h in (
            (getattr(self.ui, "btn_skip_back", None), dense.skip_w, dense.skip_h),
            (getattr(self.ui, "btn_skip_forward", None), dense.skip_w, dense.skip_h),
            (getattr(self.ui, "btn_play", None), dense.play_w, dense.play_h),
        ):
            if btn is not None:
                btn.setMinimumSize(w, h)

        chip = dense.chrome_chip
        chip_r = chip // 2
        icon_sz = max(16, chip - 14)
        chip_qss = (
            f"QPushButton {{ background: transparent; border-radius: {chip_r}px; border: none; }}"
        )
        for attr in (
            "btn_theater",
            "btn_fullscreen",
            "btn_add_marker",
            "btn_screenshot",
            "btn_clipcut1",
            "btn_clipcut2",
            "btn_clipcutback",
        ):
            b = getattr(self, attr, None) or getattr(self.ui, attr, None)
            if b is not None and hasattr(b, "setFixedSize"):
                b.setFixedSize(chip, chip)
                b.setStyleSheet(chip_qss)
                if hasattr(b, "setIconSize") and not b.icon().isNull():
                    from PySide6.QtCore import QSize

                    b.setIconSize(QSize(icon_sz, icon_sz))

        for ctrl_attr in ("volume_control", "speed_control"):
            ctrl = getattr(self, ctrl_attr, None)
            if ctrl is not None and hasattr(ctrl, "apply_density"):
                ctrl.apply_density(dense)

        # Pill frames around theater/fullscreen stay circular-ish
        for pill_attr in ("pill_container", "trim_tools_pill"):
            frame = getattr(self, pill_attr, None)
            if frame is not None:
                frame.setStyleSheet(
                    f"QFrame {{ background-color: #4e4e4e; border-radius: {chip_r}px; border: none; }}"
                )

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

        # --- Render queue ---
        panel = getattr(self, "render_queue_panel", None)
        if panel is not None and hasattr(panel, "apply_density"):
            panel.apply_density(dense)

    def _apply_render_dashboard_density(self, dense) -> None:
        dash = getattr(self, "render_dashboard", None)
        if dash is None:
            return
        lay = dash.layout()
        if lay is not None:
            lay.setContentsMargins(
                dense.dash_margin_h,
                dense.dash_margin_v,
                dense.dash_margin_h,
                dense.dash_margin_v,
            )
            lay.setSpacing(dense.dash_spacing)
        _status_font = "font-family: 'Segoe UI', Arial, sans-serif;"
        bottom_text = getattr(self, "bottom_text_label", None)
        if bottom_text is not None:
            bottom_text.setStyleSheet(
                f"color: #e0e0e0; font-size: {dense.dash_font}px; font-weight: bold; {_status_font}"
            )
        status = getattr(self.ui, "label_status", None)
        if status is not None:
            status.setStyleSheet(
                f"background: transparent; border: none; font-size: {dense.dash_font}px; "
                f"font-weight: bold; {_status_font}"
            )
            status.setMinimumWidth(80 if dense.compact else 120)
        pct = getattr(self, "label_pct", None)
        if pct is not None:
            pct.setStyleSheet(
                f"color: #ffffff; font-weight: bold; font-size: {max(11, dense.dash_font - 1)}px; {_status_font}"
            )
        icon = getattr(self, "bottom_icon_label", None)
        if icon is not None:
            icon_sz = 20 if dense.compact else 24
            icon.setFixedSize(icon_sz, icon_sz)
        for btn_name in ("btn_start", "btn_pause", "btn_cancel", "btn_logs"):
            btn = getattr(self.ui, btn_name, None)
            if btn is not None:
                btn.setMinimumHeight(dense.dash_btn_h)

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
        compact = is_compact_layout(avail_w)
        default_main = (
            DEFAULT_MAIN_SPLITTER_SIZES_COMPACT if compact else DEFAULT_MAIN_SPLITTER_SIZES
        )
        # Prefer continuous left min when remembering is off / defaults.
        if not compact:
            default_main = [left_panel_min_width(avail_w), 100000]
        main_sizes = self.get_layout_setting("main_splitter_sizes", default_main)
        if hasattr(self.ui, "main_splitter"):
            self.ui.main_splitter.setSizes(main_sizes)
        self._apply_responsive_layout_mins()
        v_splitter = getattr(self, "main_v_splitter", None)
        if v_splitter is not None:
            default_v = default_main_v_splitter_sizes(avail_w, avail_h)
            v_sizes = self.get_layout_setting("main_v_splitter_sizes", default_v)
            # Cap remembered bottom pane on short screens.
            if avail_h > 0 and len(v_sizes) >= 2:
                max_bottom = max(180, int(avail_h * 0.35))
                if v_sizes[1] > max_bottom:
                    v_sizes = [max(avail_h - max_bottom, 200), max_bottom]
            v_splitter.setSizes(v_sizes)

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

    from PySide6.QtCore import Qt as _Qt

    if sys.platform != "win32" and os.environ.get("STEEMPEG_SOFT_GL", "0") == "1":
        try:
            QApplication.setAttribute(_Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Steempeg")
    app.setApplicationDisplayName("Steempeg")
    try:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.setDesktopFileName("steempeg")
    except Exception:
        pass
    if sys.platform != "win32":
        print(f"[steempeg] Qt platform={app.platformName()!r}", flush=True)

    # Color emoji fallbacks. Prefer Twemoji over Noto Color Emoji: Bazzite's
    # Noto is COLRv1, which Qt will pick then paint as blank (📁🎬 etc. vanish).
    try:
        from PySide6.QtGui import QFont

        _ui_font = QFont()
        _ui_font.setFamilies(
            [
                "Segoe UI",
                "Noto Sans",
                "Twemoji",
                "Noto Emoji",
                "Noto Color Emoji",
                "DejaVu Sans",
            ]
        )
        _ui_font.setPointSize(10)
        app.setFont(_ui_font)
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

    icon_path = get_resource_path("logo.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))


    try:
        window = SteempegApp()
        # Keep the lock alive for the process lifetime (prevent GC unlock).
        window._instance_lock = _instance_lock
        
        if getattr(window, 'ui', None) is None:
            QMessageBox.critical(None, "Interface Error", "Failed to build the main window!")
            sys.exit(1)
            
        if os.path.exists(icon_path):
            window.ui.setWindowIcon(QIcon(icon_path))

        from PySide6.QtCore import Qt
        if sys.platform == "win32":
            # Custom Win32 chrome: keep native frame styles, hide painted caption later.
            window.ui.setWindowFlags(
                Qt.WindowType.Window
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
            _min_w = min(TARGET_MIN_WINDOW_WIDTH, max(640, _avail.width()))
            _min_h = min(TARGET_MIN_WINDOW_HEIGHT, max(480, _avail.height()))
            window.ui.setMinimumSize(_min_w, _min_h)
            if sys.platform == "win32":
                # Inset; showMaximized() below fills the work area natively.
                window.ui.setGeometry(_avail.adjusted(80, 60, -80, -60))
            else:
                # Linux/XWayland+NVIDIA: never call showMaximized (hard-freeze).
                # Fake-maximize by filling the work area (taskbar still visible).
                window.ui.setGeometry(_avail)
            logging.info(
                "Primary screen %r avail=%sx%s",
                _screen.name(),
                _avail.width(),
                _avail.height(),
            )
        else:
            window.ui.setMinimumSize(TARGET_MIN_WINDOW_WIDTH, TARGET_MIN_WINDOW_HEIGHT)

        window.ui.show()
        window.ui.raise_()
        window.ui.activateWindow()
        try:
            wh = window.ui.windowHandle()
            if wh is not None:
                wh.requestActivate()
        except Exception:
            pass
        QApplication.processEvents()
        if sys.platform == "win32":
            window.ui.showMaximized()
        else:
            logging.info("Linux: fake-maximize via work-area geometry (no showMaximized)")
        QApplication.processEvents()
        window._sync_startup_layout()
        geo = window.ui.geometry()
        logging.info(
            "Main window shown (platform=%s visible=%s geo=%sx%s+%s+%s soft_gl=%s)",
            app.platformName(),
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
            from steempeg.ui.window_chrome import enable_frameless
            _force_native_window_icon(window.ui, icon_path)
            enable_frameless(window.ui)
            # Frameless / DWM refresh can drop the taskbar icon cache after an
            # in-place update — re-push WM_SETICON once the chrome is settled.
            _force_native_window_icon(window.ui, icon_path)
            tb = getattr(window.ui, "title_bar", None)
            if tb is not None:
                tb.sync_window_state()

        QTimer.singleShot(0, _apply_custom_shell_native)
        # Second pass: after the first paint / shell settle (post-update launches
        # sometimes need another poke before Windows shows the branded icon).
        QTimer.singleShot(400, lambda: _force_native_window_icon(window.ui, icon_path))
        if args.updated_from:
            QTimer.singleShot(800, lambda: _force_native_window_icon(window.ui, icon_path))
            QTimer.singleShot(1000, lambda: window.show_update_success(args.updated_from, args.backup_folder))
            
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
