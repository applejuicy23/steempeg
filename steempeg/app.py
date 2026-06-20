from steempeg.version import APP_VERSION_STR
from steempeg.ui.main_window import MainWindow
from steempeg.infra.logging import global_exception_handler, setup_logging
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
from steempeg.ui.library.controller import LibraryMixin
from steempeg.ui.player.controller import PlayerMixin
from steempeg.ui.lifecycle import LifecycleMixin
from steempeg.ui.hide_watcher import HideWatcher




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

import mpv

from PySide6.QtCore import Qt, QTimer, QSize, QObject
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtWidgets import QHeaderView, QAbstractItemView
from PySide6.QtGui import QIcon

from steempeg.ui.widgets import ElidedLabel, FilterPillButton

def get_resource_path(relative_path):
    return paths.get_resource_path(relative_path)


def get_save_directory():
    return paths.get_save_directory()

from PySide6.QtCore import Qt


from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt


    

from PySide6.QtCore import Qt





class SteempegApp(LifecycleMixin, PlayerMixin, LibraryMixin, RenderMixin, SettingsMixin, UpdaterMixin, QObject):
    def __init__(self):
        # 1. LOADING THE INTERFACE
        super().__init__()

        self.ui = MainWindow()


        self.ui.setStyleSheet("""
            QDialog#Dialog { background-color: #1e1e1e; }
            

            QToolTip {
                background-color: #2d2d2d; 
                color: #ffffff; 
                border: 1px solid #444444; 
                border-radius: 4px; 
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 11px;
                font-weight: bold;
                padding: 4px 8px;
            }
        """)
        
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
        self.clips_folder = "" # Current clip folder
        
        # --- Set default rendered_videos ---
        default_export_dir = os.path.join(get_save_directory(), "rendered_videos").replace('\\', '/')
        if not os.path.exists(default_export_dir):
            os.makedirs(default_export_dir, exist_ok=True)
        self.custom_destination = default_export_dir 
        
        # Let's write this path directly on the button in the interface
        if hasattr(self.ui, 'destination_button'):
            self.ui.destination_button.setText(f"Destination: {self.custom_destination}")
            
        self.current_orig_bitrate = 0 # Bitrate of the selected original clip
        self.current_clip_duration_sec = 0
        
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
        

            
        self.current_log_file = setup_logging(self.logs_dir, APP_VERSION_STR)

        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir) # Create a cache folder if it doesn't exist
            
        self.json_cache_path = os.path.join(self.cache_dir, "games.json")
        self.game_names_cache = self.load_json_cache() # JSON
        self.game_icons_cache = {} # This is where we store downloaded images in memory
        
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
                    font-family: 'Inter', 'Segoe UI', sans-serif;
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
            self.ui.table_clips.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.ui.table_clips.setShowGrid(False)
            self.ui.table_clips.verticalHeader().setVisible(False)
            self.ui.table_clips.setContextMenuPolicy(Qt.CustomContextMenu)
            self.ui.table_clips.customContextMenuRequested.connect(self.show_clip_context_menu)
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
            custom_font = QFont("Segoe UI", 10) 
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
            if hasattr(self.ui, 'table_clips'):
                from PySide6.QtCore import QTimer 
                self.ui.table_clips.horizontalHeader().sortIndicatorChanged.connect(
                    # Give the table 50 milliseconds to physically finish sorting the rows!
                    lambda *args: QTimer.singleShot(50, self.build_netflix_grid) if hasattr(self, 'build_netflix_grid') else None
                )

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

            #2. CREATE A BEAUTIFUL TABLET (Without a counter)
            cm_row = qtw.QHBoxLayout()
            cm_row.setContentsMargins(0, 0, 0, 10) 
            
            self.mega_top_pill = qtw.QFrame()
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

            # 3. PERFECT CENTERING IN THE PANEL
            cm_row.addStretch()
            cm_row.addWidget(self.mega_top_pill)
            cm_row.addStretch()

            # 4. INSERT IT INTO THE INTERFACE EXACTLY IN ITS PLACE
            target_layout.insertLayout(insert_idx, cm_row)

            # 1. MEGA-CAPSULE (All elements within a single floating island)
            # Container for external padding
            top_bar_layout = qtw.QHBoxLayout()
            top_bar_layout.setContentsMargins(12, 0, 12, 4) 
            
            mega_top_pill = qtw.QFrame()
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

            # "View" Text
            lbl_view = qtw.QLabel("View")
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
            self.ui.table_clips.setShowGrid(False)
            
            # (Sorting buttons at the top
            self.ui.table_clips.horizontalHeader().setVisible(True)
            self.ui.table_clips.horizontalHeader().setHighlightSections(False)
            self.ui.table_clips.horizontalHeader().setDefaultAlignment(qtc.Qt.AlignCenter)
            
            self.ui.table_clips.verticalHeader().setVisible(False)
            self.ui.table_clips.setFrameShape(qtw.QFrame.NoFrame)
            self.ui.table_clips.setHorizontalScrollBarPolicy(qtc.Qt.ScrollBarAlwaysOff)
            
            self.ui.table_clips.verticalHeader().setDefaultSectionSize(46) 
            self.ui.table_clips.setIconSize(qtc.QSize(26, 26)) 

            self.ui.table_clips.setStyleSheet("""
                QTableWidget { 
                    background: transparent; 
                    border: none; 
                    outline: none; 
                }
                QTableWidget::item { 
                    padding: 4px 12px; 
                    border-bottom: 1px solid #282828; 
                    color: #d1d1d1; 
                    font-size: 13px;
                    font-family: 'Segoe UI', Arial, sans-serif;
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
                    background-color: transparent; 
                    color: #d1d1d1; 
                    padding: 6px;
                    border: none;
                    border-bottom: 1px solid #333333; 
                    font-size: 13px;
                    font-weight: bold;
                }
                QHeaderView::section:hover {
                    color: #ffffff;
                }
                QHeaderView::section:checked {
                    color: #b29ae7;
                }
                QHeaderView::up-arrow, QHeaderView::down-arrow {
                    width: 0px; height: 0px; 
                }
            """)
            
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
            self.grid_clips.setContextMenuPolicy(Qt.CustomContextMenu)
            self.grid_clips.customContextMenuRequested.connect(self.show_grid_context_menu)
            self.grid_clips.viewport().installEventFilter(self)
            # We strictly fix the card sizes so they don't fly apart when hidden!
            self.grid_clips.setUniformItemSizes(True)
            # We allow only ONE clip to be selected at a time (to avoid frame bugs)
            self.grid_clips.setSelectionMode(qtw.QAbstractItemView.SingleSelection)
            
            # Boomerang Effect (Drag & Snap Back)
            self.grid_clips.setDragDropMode(qtw.QAbstractItemView.DragOnly)
            self.grid_clips.setMovement(qtw.QListView.Static)
            self.grid_clips.itemSelectionChanged.connect(self.on_grid_selection_changed)
            self.grid_clips.setStyleSheet("""
                QListWidget { background: transparent; border: none; outline: none; }
                
                QListWidget::item { 
                    border-top-left-radius: 0px; 
                    border-top-right-radius: 0px; 
                    border-bottom-left-radius: 12px; 
                    border-bottom-right-radius: 12px; 
                    border: 2px solid #444444; 
                    background-color: #2d2d2d; 
                    padding: 0px;
                    margin: 0px;
                } 
                QListWidget::item:selected { 
                    border: 3px solid #b29ae7; 
                }
                
                QScrollBar:vertical { border: none; background: transparent; width: 10px; margin: 2px; }
                QScrollBar::handle:vertical { background: #4e4e4e; min-height: 30px; border-radius: 4px; }
                QScrollBar::handle:vertical:hover { background: #b29ae7; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            """)

            original_parent_layout = self.ui.table_clips.parentWidget().layout()
            original_idx = -1
            if original_parent_layout:
                original_idx = original_parent_layout.indexOf(self.ui.table_clips)

            # 4. LIBRARY BLOCK
            self.library_views_container = qtw.QFrame()
            self.library_views_container.setStyleSheet("QFrame { background-color: #2d2d2d; border: 1px solid #353535; border-radius: 12px; }")
            views_layout = qtw.QVBoxLayout(self.library_views_container)
            views_layout.setContentsMargins(10, 10, 10, 10)
            
            views_layout.addWidget(self.ui.table_clips)
            views_layout.addWidget(self.grid_clips)

            # 5. Putting It All Together
            self.left_master_layout = qtw.QVBoxLayout()
            self.left_master_layout.setContentsMargins(0, 0, 0, 0)
            self.left_master_layout.setSpacing(16)
            
            self.left_master_layout.addLayout(top_bar_layout)
            self.left_master_layout.addWidget(self.library_views_container)
            
            # Insert our new mega-block back into the SAVED old layout.
            if original_parent_layout:
                if original_idx != -1: 
                    original_parent_layout.insertLayout(original_idx, self.left_master_layout)
                else: 
                    original_parent_layout.addLayout(self.left_master_layout)

            # 6. ✨ DYNAMIC TOGGLES UwU ✨
            # Set initial view mode to 'List' instead of 'Grid'
            self.grid_clips.hide()
            self.ui.table_clips.show()
            self.btn_view_list.setStyleSheet(self.toggle_style_active)
            self.btn_view_grid.setStyleSheet(self.toggle_style_inactive)

            
                    
            self.btn_view_list.clicked.connect(lambda: self.set_view_mode("list"))
            self.btn_view_grid.clicked.connect(lambda: self.set_view_mode("grid"))

        # --- UI INJECTION: SORTING PANEL (NEXT TO FILTER BUTTON) ---
        from PySide6.QtWidgets import QLabel, QComboBox

        # 1. Create a text label (like the one in View)
        lbl_sorting = QLabel("Sorting")
        lbl_sorting.setStyleSheet("color: #888888; font-weight: bold; font-family: 'Segoe UI'; font-size: 13px;")

        # 2. Creating a stylish sorting dropdown list
        self.combo_sort = QComboBox()
        self.combo_sort.setCursor(Qt.PointingHandCursor)
        self.combo_sort.setStyleSheet("""
            QComboBox {
                background-color: #383838; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 8px;
                padding: 4px 10px; 
                font-weight: bold; 
                font-family: 'Segoe UI'; 
                font-size: 13px; 
                min-height: 24px;
            }
            QComboBox:hover { background-color: #404040; border: 2px solid #6b5a8e; }
            QComboBox::drop-down { border: none; padding-right: 5px; }
            QComboBox QAbstractItemView {
                background-color: #252525; 
                color: white; 
                selection-background-color: #6b5a8e;
                border: 1px solid #444; 
                border-radius: 4px; 
                outline: none; 
                padding: 4px;
            }
        """)

        # 3. Adding elements with attractive icons
        self.combo_sort.addItem(QIcon(get_resource_path("defaultsort.png")), "Default (Don't touch)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort1.png")), "Game Name (A - Z)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort2.png")), "Game Name (Z - A)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort1.png")), "Type (A - Z)")
        self.combo_sort.addItem(QIcon(get_resource_path("lettersort2.png")), "Type (Z - A)")
        self.combo_sort.addItem(QIcon(get_resource_path("datesort1.png")), "Date (Oldest First)")
        self.combo_sort.addItem(QIcon(get_resource_path("datesort2.png")), "Date (Newest First)")
        self.combo_sort.addItem(QIcon(get_resource_path("durationsort1.png")), "Duration (Shortest)")
        self.combo_sort.addItem(QIcon(get_resource_path("durationsort2.png")), "Duration (Longest)")

        self.combo_sort.currentIndexChanged.connect(self.apply_sorting)

        # 4. Locate the filter button and elegantly assemble the panel to its LEFT.
        filter_btn = getattr(self, 'btn_filter_pill', None) or getattr(self.ui, 'btn_filter', None)
        if filter_btn and filter_btn.parentWidget() and filter_btn.parentWidget().layout():
            layout = filter_btn.parentWidget().layout()
            idx = layout.indexOf(filter_btn)
            
            # 4.1. Removing the old button from the main layout (to move it to the new group)
            layout.takeAt(idx)
            
            # 4.2. Creating a separate container for our Sort/Filter group
            from PySide6.QtWidgets import QHBoxLayout, QWidget
            group_widget = QWidget()
            group_layout = QHBoxLayout(group_widget)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(14)
            
            # 4.3. Placing elements into our new super-container
            group_layout.addWidget(lbl_sorting)
            group_layout.addWidget(self.combo_sort)
            
            
            group_layout.addWidget(filter_btn)
            
            # 4.4. Insert a spacer (Stretch) into the main layout to shift everything to the right.
            layout.insertStretch(idx)
            
            # 4.5. Inserting our assembled group back into the main layout
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
            sidebar_frame.setFixedWidth(220)
            sidebar_frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            sidebar_frame.setStyleSheet("""
                QFrame { background: transparent; border: none; border-right: 1px solid #383838; }
            """)
            sidebar_layout = QVBoxLayout(sidebar_frame)
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
                QPushButton:checked { background-color: #383838; border: 2px solid #8e7cc3; color: #ffffff; }
            """
            
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

                QComboBox, QLineEdit {
                    background-color: #383838; color: #ffffff;
                    border: 2px solid #4a4a4a; border-radius: 12px;
                    padding: 7px 10px; font-size: 12px; font-weight: bold; font-family: 'Segoe UI', Arial, sans-serif;
                }
                QComboBox:hover, QLineEdit:hover { border: 2px solid #6b5a8e; }
                QComboBox:focus, QComboBox:on, QLineEdit:focus { border: 2px solid #b29ae7; }
                QComboBox::drop-down {
                    subcontrol-origin: padding; subcontrol-position: top right;
                    width: 30px; background-color: #262626;
                    border-left: 2px solid #4a4a4a;
                    border-top-right-radius: 10px; border-bottom-right-radius: 10px;
                }
                QComboBox::down-arrow {
                    width: 0; height: 0;
                    border-left: 5px solid transparent; border-right: 5px solid transparent;
                    border-top: 6px solid #cccccc;
                }
                QComboBox QAbstractItemView {
                    background-color: #1e1e1e; color: #e0e0e0;
                    border: 2px solid #4a4a4a; border-radius: 10px; padding: 4px; outline: none;
                    selection-background-color: #4a4a4a; selection-color: #ffffff;
                    font-family: 'Segoe UI', Arial, sans-serif;
                }
                QComboBox QAbstractItemView::item {
                    min-height: 28px; padding: 7px 10px; border-radius: 6px;
                    margin: 2px 2px; background-color: #333333; color: #e0e0e0;
                }
                QComboBox QAbstractItemView::item:hover {
                    background-color: #4a4a4a; color: #ffffff;
                }

                QPushButton {
                    background-color: #303030; color: #ffffff;
                    border: 2px solid #3a3a3a; border-radius: 12px;
                    padding: 7px 15px; font-weight: bold; font-family: 'Arial';
                }
                QPushButton:hover { background-color: #262626; border: 2px solid #6b5a8e; }
                QPushButton:pressed { background-color: #141414; border: 2px solid #b29ae7; }
            """)
            
            # Place tabs in the scroll area
            self.right_scroll.setWidget(self.ui.settings_tabs)
            
            # --- SAFE MASK (QRegion) LIKE IN THE PLAYER ---
            class RoundedCornerFilter(QObject):
                def eventFilter(self, obj, event):
                    if event.type() == QEvent.Type.Resize:
                        if obj.width() > 0 and obj.height() > 0:
                            try:
                                from PySide6.QtGui import QPainterPath, QRegion
                                path = QPainterPath()
                                path.addRoundedRect(0.0, 0.0, float(obj.width()), float(obj.height()), 16.0, 16.0)
                                obj.setMask(QRegion(path.toFillPolygon().toPolygon()))
                            except Exception:
                                pass
                    return False
            
            self.corner_mask = RoundedCornerFilter(self.right_scroll)
            self.right_scroll.installEventFilter(self.corner_mask)
            
            neo_layout.addWidget(self.right_scroll)
            
            # 5. Placing our wrapper back in the original location without conflicts
            if parent_layout:
                if insert_idx != -1:
                    parent_layout.insertWidget(insert_idx, self.neo_wrapper)
                else:
                    parent_layout.addWidget(self.neo_wrapper)
        
        from steempeg.ui.render_panel import restyle_video_page, restyle_audio_page, restyle_source_page
        restyle_video_page(self.ui)
        restyle_audio_page(self.ui)
        restyle_source_page(self.ui)
        # Codec list
        if hasattr(self.ui, 'combo_codec'):
            self.ui.combo_codec.clear()
            self.ui.combo_codec.addItem("H.264 (AVC)")
            self.ui.combo_codec.addItem("H.265 (HEVC)")
            self.ui.combo_codec.setCurrentIndex(1) # Default is H.265
            
        # Update the bitrate list when changing resolution
        if hasattr(self.ui, 'combo_quality'):
            self.ui.combo_quality.currentTextChanged.connect(self.update_bitrate_options) 
        
        # 4. BINDING BUTTONS TO FUNCTIONS
        # --- UI INJECTION: COPY BUTTONS ---
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget, QSizePolicy
        
        copy_icon_path = get_resource_path("copyfile.png")
        
        # 1. Copy Button for Source
        if hasattr(self.ui, 'source_label'):
            src_container = QWidget()
            src_layout = QHBoxLayout(src_container)
            src_layout.setContentsMargins(0, 0, 0, 0)
            src_layout.setSpacing(6)
            
            self.ui.source_label.parentWidget().layout().replaceWidget(self.ui.source_label, src_container)
            
            self.btn_copy_src = QPushButton()
            self.btn_copy_src.setFixedSize(20, 20)
            self.btn_copy_src.setToolTip("Copy raw source paths")
            self.btn_copy_src.setStyleSheet("background: transparent; border: none;")
            self.btn_copy_src.setCursor(Qt.PointingHandCursor)
            
            if os.path.exists(copy_icon_path): 
                self.btn_copy_src.setIcon(QIcon(copy_icon_path))
            else: 
                self.btn_copy_src.setText("📋")
                
            self.btn_copy_src.clicked.connect(lambda: QApplication.clipboard().setText(getattr(self, 'current_source_raw_paths', "")))
            self.btn_copy_src.hide() # Hidden by default
            
            self.ui.source_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            src_layout.addWidget(self.ui.source_label)
            src_layout.addWidget(self.btn_copy_src, alignment=Qt.AlignTop)
            src_layout.addStretch()

        # 2. Copy Button for Rendered Video Location
        if hasattr(self.ui, 'label_location'):
            loc_container = QWidget()
            loc_layout = QHBoxLayout(loc_container)
            loc_layout.setContentsMargins(0, 0, 0, 0)
            loc_layout.setSpacing(6)
            
            self.ui.label_location.parentWidget().layout().replaceWidget(self.ui.label_location, loc_container)
            
            # --- replace standard label with our Smart Label ---
            smart_label = ElidedLabel()
            smart_label.setStyleSheet(self.ui.label_location.styleSheet())
            smart_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.ui.label_location.deleteLater() # Destroy the old label
            self.ui.label_location = smart_label # Hijack the variable!
            
            
            self.btn_copy_loc = QPushButton()
            self.btn_copy_loc.setFixedSize(20, 20)
            self.btn_copy_loc.setToolTip("Copy raw output path")
            self.btn_copy_loc.setStyleSheet("background: transparent; border: none;")
            self.btn_copy_loc.setCursor(Qt.PointingHandCursor)
            
            if os.path.exists(copy_icon_path): 
                self.btn_copy_loc.setIcon(QIcon(copy_icon_path))
            else: 
                self.btn_copy_loc.setText("📋")
                
            self.btn_copy_loc.clicked.connect(lambda: QApplication.clipboard().setText(getattr(self, 'current_output_file', "")))
            self.btn_copy_loc.hide() # Hidden by default
            
            loc_layout.addWidget(self.ui.label_location)
            loc_layout.addWidget(self.btn_copy_loc, alignment=Qt.AlignVCenter)

        # --- UI INJECTION: REFRESH BUTTON ---
        from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QSizePolicy
        
        # --- CIRCLE AND BUTTON STYLES ---
        pill_style = """
            QFrame { 
                background-color: #2d2d2d; 
                border-radius: 16px; 
                border: 1px solid #383838;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """
        
        unified_table_style = """
            QPushButton { 
                background-color: #383838; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 14px; 
                font-family: 'Segoe UI', Arial, sans-serif;
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
        mega_pill.setStyleSheet(pill_style)
        mega_layout = QVBoxLayout(mega_pill)
        mega_layout.setContentsMargins(6, 6, 6, 6) # Slightly increased the margins from the edges of the circle
        mega_layout.setSpacing(4) # Distance between floors

        #2. CREATE TWO FLOORS INSIDE THE CAPSULE
        top_row = QHBoxLayout()
        top_row.setSpacing(4) # Distance between buttons
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)
        
        mega_layout.addLayout(top_row)
        mega_layout.addLayout(bottom_row)

        #3. PUT THE MEGA-CAPSULE ON THE VERY TOP (INSTEAD OF THE OLD FOLDER BUTTON)
        old_browse_btn = self.ui.btn_browse
        if old_browse_btn.parentWidget() and old_browse_btn.parentWidget().layout():
            old_browse_btn.parentWidget().layout().replaceWidget(old_browse_btn, mega_pill)
            
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setToolTip("Rescan folder for new clips")
        
        #4. TEAR ABOUT AND UPDATE FROM THEIR OLD PLACES
        btn_about = getattr(self.ui, 'btn_about', None)
        btn_update = getattr(self.ui, 'btn_update_check', None)
        
        if btn_about and btn_about.parentWidget() and btn_about.parentWidget().layout():
            btn_about.parentWidget().layout().removeWidget(btn_about)
        if btn_update and btn_update.parentWidget() and btn_update.parentWidget().layout():
            btn_update.parentWidget().layout().removeWidget(btn_update)
            
        # 5. Color the buttons and add cursors
        old_browse_btn.setStyleSheet(unified_table_style)
        self.btn_refresh.setStyleSheet(unified_table_style)
        old_browse_btn.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        
        if btn_about:
            btn_about.setStyleSheet(unified_table_style)
            btn_about.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn_about.setCursor(Qt.PointingHandCursor)
        if btn_update:
            btn_update.setStyleSheet(unified_table_style)
            btn_update.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn_update.setCursor(Qt.PointingHandCursor)
            
        # 6. LAY OUT THE BUTTONS BY FLOORS (70/30 on top, 50/50 on the bottom)
        top_row.addWidget(old_browse_btn, 7)
        top_row.addWidget(self.btn_refresh, 3)
        
        if btn_about: bottom_row.addWidget(btn_about, 5)
        if btn_update: bottom_row.addWidget(btn_update, 5)
        
        # 7. RECOVERING SIGNALS (Presses)
        self.btn_refresh.clicked.connect(self.scan_clips)
        self.ui.btn_browse.clicked.connect(self.choose_folder)
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
                QPushButton { font-family: 'Segoe UI'; font-size: 12px; font-weight: bold; background-color: #383838; color: #ffffff; border: 2px solid #444444; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #404040; border: 2px solid #6b5a8e; }
                QPushButton:pressed { background-color: #3a324a; border: 2px solid #b29ae7; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
                QPushButton::menu-indicator { image: none; }
            """
            
            # Start (Green — OUR BENCHMARK)
            start_btn_style = """
                QPushButton { font-family: 'Segoe UI'; font-size: 12px; font-weight: bold; background-color: #2e6b32; color: #ffffff; border: 2px solid #3e8e41; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #3e8e41; border: 2px solid #57c75b; }
                QPushButton:pressed { background-color: #235226; border: 2px solid #3e8e41; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
            """

            # Pause (Yellow-Orange Copy of the Green One)
            btn_pause_style = """
                QPushButton { font-family: 'Segoe UI'; font-size: 12px; font-weight: bold; background-color: #8c7314; color: #ffffff; border: 2px solid #a88b11; border-radius: 8px; padding: 6px 14px; }
                QPushButton:hover { background-color: #a88b11; border: 2px solid #c9a716; }
                QPushButton:pressed { background-color: #6b570d; border: 2px solid #a88b11; }
                QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }
                QPushButton::menu-indicator { image: none; }
            """
            
            # Cancellation (Red copy of the green one)
            btn_cancel_style = """
                QPushButton { font-family: 'Segoe UI'; font-size: 12px; font-weight: bold; background-color: #8a2525; color: #ffffff; border: 2px solid #a82e2e; border-radius: 8px; padding: 6px 14px; }
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

            # TOP ROW 
            top_row = qtw.QHBoxLayout()
            
            if hasattr(self.ui, 'label_short_summary'):
                self.ui.label_short_summary.hide() 
                
                self.bottom_icon_label = qtw.QLabel()
                self.bottom_icon_label.setFixedSize(24, 24)
                
                self.bottom_text_label = qtw.QLabel()
                self.bottom_text_label.setStyleSheet("color: #e0e0e0; font-size: 13px;")
                
                top_row.addWidget(self.bottom_icon_label, 0, qtc.Qt.AlignVCenter)
                top_row.addWidget(self.bottom_text_label, 0, qtc.Qt.AlignVCenter)
                
                # Instant reset generator function
                def reset_bottom_summary():
                    css_icon = get_resource_path("unknown_icon.png").replace('\\', '/')
                    
                    # 1. Reset the bottom panel
                    self.bottom_icon_label.setStyleSheet(f"image: url('{css_icon}'); background: transparent; border: none;")
                    self.bottom_text_label.setText("<b>Select a clip to begin...</b>")
                    
                    # 2. Reset the top panel
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
            
            top_row.addStretch() 
            
            if hasattr(self.ui, 'label_status'):
                self.ui.label_status.setStyleSheet("color: #b29ae7; font-family: 'Segoe UI'; font-weight: bold; font-size: 12px;")
                self.ui.label_status.setAlignment(qtc.Qt.AlignRight | qtc.Qt.AlignVCenter)
                top_row.addWidget(self.ui.label_status)
            dash_layout.addLayout(top_row)

            # 2nd Row (6px Laser Line + Percentages)
            mid_row = qtw.QHBoxLayout()
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setTextVisible(False)
                self.ui.progress_render.setRange(0, 1000)
                self.ui.progress_render.setStyleSheet("""
                    QProgressBar { background-color: #414141; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; }
                    QProgressBar::chunk { background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #6b5a8e, stop:1 #b29ae7); border-radius: 3px; }
                """)
                mid_row.addWidget(self.ui.progress_render)
                
            if not hasattr(self, 'label_pct'):
                self.label_pct = qtw.QLabel("0%")
            self.label_pct.setStyleSheet("color: #ffffff; font-family: 'Segoe UI'; font-weight: bold; font-size: 13px; margin-left: 8px;")
            mid_row.addWidget(self.label_pct)
            dash_layout.addLayout(mid_row)

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
                    btn.setStyleSheet(old_style + "\nQPushButton { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; font-weight: bold; }")
                    
                    btn_row.addWidget(btn)

            dash_layout.addLayout(btn_row)

            # 4. Container Assembly
            if parent_widget and parent_widget.layout():
                parent_widget.layout().addWidget(self.render_dashboard)

        except Exception as e:
            print(f"Error building ultimate monolithic dashboard: {e}")
        
        
        # --- UI INJECTION: COPY BUTTONS ---
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget, QSizePolicy
        
        copy_icon_path = get_resource_path("copyfile.png")
        
        # 1. Copy Button for Source
        if hasattr(self.ui, 'source_label'):
            src_container = QWidget()
            src_layout = QHBoxLayout(src_container)
            src_layout.setContentsMargins(0, 0, 0, 0)
            src_layout.setSpacing(6) # Micro-gap between text and icon
            
            self.ui.source_label.parentWidget().layout().replaceWidget(self.ui.source_label, src_container)
            
            self.btn_copy_src = QPushButton()
            self.btn_copy_src.setFixedSize(20, 20)
            self.btn_copy_src.setToolTip("Copy raw source paths")
            self.btn_copy_src.setStyleSheet("background: transparent; border: none;")
            self.btn_copy_src.setCursor(Qt.PointingHandCursor)
            
            if os.path.exists(copy_icon_path): self.btn_copy_src.setIcon(QIcon(copy_icon_path))
            else: self.btn_copy_src.setText("📋")
                
            self.btn_copy_src.clicked.connect(lambda: QApplication.clipboard().setText(getattr(self, 'current_source_raw_paths', "")))
            self.btn_copy_src.hide() # Hidden by default (No clip = no button)
            
            self.ui.source_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            src_layout.addWidget(self.ui.source_label)
            src_layout.addWidget(self.btn_copy_src, alignment=Qt.AlignTop)
            src_layout.addStretch() # MAGIC: Pushes everything to the left wall!

        # 2. Copy Button for Rendered Video Location
        if hasattr(self.ui, 'label_location'):
            loc_container = QWidget()
            loc_layout = QHBoxLayout(loc_container)
            loc_layout.setContentsMargins(0, 0, 0, 0)
            loc_layout.setSpacing(6)
            
            self.ui.label_location.parentWidget().layout().replaceWidget(self.ui.label_location, loc_container)
            
            self.btn_copy_loc = QPushButton()
            self.btn_copy_loc.setFixedSize(20, 20)
            self.btn_copy_loc.setToolTip("Copy raw output path")
            self.btn_copy_loc.setStyleSheet("background: transparent; border: none;")
            self.btn_copy_loc.setCursor(Qt.PointingHandCursor)
            
            if os.path.exists(copy_icon_path): self.btn_copy_loc.setIcon(QIcon(copy_icon_path))
            else: self.btn_copy_loc.setText("📋")
                
            self.btn_copy_loc.clicked.connect(lambda: QApplication.clipboard().setText(getattr(self, 'current_output_file', "")))
            self.btn_copy_loc.hide() # Hidden by default (No clip = no button)
            
            self.ui.label_location.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            loc_layout.addWidget(self.ui.label_location)
            loc_layout.addWidget(self.btn_copy_loc, alignment=Qt.AlignVCenter)
            loc_layout.addStretch() # Pushes everything to the left wall!

        # --- FIXING THE INTERFACE AND PLAYER ---
        # 1. Give the right panel some breathing room
        right_layout = self.ui.right_panel.layout()
        if right_layout:
            right_layout.setContentsMargins(12, 12, 12, 12) 
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
            self.place_logo.setPixmap(QPixmap(logo_path).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.place_logo.setAlignment(Qt.AlignCenter)
        
        self.place_text = QLabel("Please select a clip from the library")
        self.place_text.setStyleSheet("color: #888888; font-size: 14px; font-weight: bold; margin-top: 15px;")
        self.place_text.setAlignment(Qt.AlignCenter)
        
        place_layout.addWidget(self.place_logo)
        place_layout.addWidget(self.place_text)
        self.video_stack.addWidget(self.placeholder_frame)
        
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

        
        
        from PySide6.QtWidgets import QPushButton
        self.btn_close_clip = QPushButton("❌")
        self.btn_close_clip.setFixedSize(24, 24)
        self.btn_close_clip.setCursor(Qt.PointingHandCursor)
        self.btn_close_clip.setToolTip("Close Clip")
        self.btn_close_clip.setStyleSheet("""
            QPushButton {
                background-color: transparent; 
                border: none;
                border-radius: 6px; 
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #9e3636; 
            }
            QPushButton:pressed {
                background-color: #6b2424; 
            }
        """)
        self.btn_close_clip.hide()
        self.btn_close_clip.clicked.connect(self.close_current_clip)
        
        header_layout.addWidget(self.btn_close_clip)

        right_layout = self.ui.right_panel.layout()
        if right_layout:
            right_layout.insertWidget(0, self.player_header_frame)
            
        # Hide old labels from Qt Designer
        if hasattr(self.ui, 'label_player_header'):
            self.ui.label_player_header.hide()
        if hasattr(self.ui, 'label_player_icon'):
            self.ui.label_player_icon.hide()


        player_style = """
        QPushButton#btn_play, QPushButton#btn_skip_back, QPushButton#btn_skip_forward {
            background-color: transparent;
            border: none;
            border-radius: 4px;
            padding: 5px;
        }
        QPushButton#btn_play:hover, QPushButton#btn_skip_back:hover, QPushButton#btn_skip_forward:hover {
            background-color: rgba(255, 255, 255, 25); 
        }
        QPushButton#btn_play:pressed, QPushButton#btn_skip_back:pressed, QPushButton#btn_skip_forward:pressed {
            background-color: rgba(255, 255, 255, 40);
        }

        
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
                """)
                
                v_layout = QVBoxLayout(self.player_footer_frame)
                v_layout.setContentsMargins(15, 12, 15, 12)
                v_layout.setSpacing(5)
                
                # ROW 1: The Custom Timeline
                if not hasattr(self, 'custom_timeline'):
                    self.custom_timeline = CustomTimelineWidget()
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
                h_layout.setSpacing(5) # Normal spacing
                h_layout.addStretch() # Pushes buttons to center
                
                self.ui.btn_skip_back.setParent(self.player_footer_frame)
                self.ui.btn_play.setParent(self.player_footer_frame)
                self.ui.btn_skip_forward.setParent(self.player_footer_frame)
                
                h_layout.addWidget(self.ui.btn_skip_back)
                h_layout.addWidget(self.ui.btn_play)
                h_layout.addWidget(self.ui.btn_skip_forward)
                
                h_layout.addStretch() # Pushes buttons to center
                
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
                self.main_v_splitter.setSizes([750, 250])     # Initial sizes
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
                right_layout.addWidget(self.main_v_splitter)

                # Saving the new index for Fullscreen
                self.controls_layout_index = top_v_layout.indexOf(self.player_footer_frame)
                self.custom_timeline.pause_requested.connect(self.on_timeline_press)
                self.custom_timeline.seek_requested.connect(self.on_timeline_seek)
                self.custom_timeline.resume_requested.connect(self.on_timeline_release)
                self.custom_timeline.trim_changed.connect(self.on_trim_changed) 
                self.custom_timeline.screenshot_requested.connect(self.take_screenshot)
                self.custom_timeline.add_marker_requested.connect(self.add_user_marker)
        
        # --- INITIALIZING THE MPV VIDEO PLAYER ---
        mpv_log_path = os.path.join(self.logs_dir, f"mpv_engine_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

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

        self.player = mpv.MPV(
            vo='gpu',
            panscan=1.0,
            keepaspect='no',
            wid=int(self.mpv_screen.winId()), 
            hwdec='auto',         
            keep_open='yes',      
            ao='wasapi',         
            log_file=mpv_log_path,
            loglevel='fatal'
        )
        self.player['af'] = 'rubberband'
        

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
            from PySide6.QtWidgets import QMenu
            log_menu = QMenu(self.ui)
            
            action_current = log_menu.addAction("📄 Open current log")
            action_folder = log_menu.addAction("📂 Open log folder")
            
            action_current.triggered.connect(self.open_current_log)
            action_folder.triggered.connect(self.open_logs_folder)
            
            # Attach the menu to the button
            self.ui.btn_logs.setMenu(log_menu)
        
        # We connect the "Final setup" update to all interface changes
        if hasattr(self.ui, 'combo_quality'): self.ui.combo_quality.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_bitrate'): self.ui.combo_bitrate.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_fps'): 
            self.ui.combo_fps.currentTextChanged.connect(self.update_final_setup)
            self.ui.combo_fps.currentTextChanged.connect(self.refresh_slider_if_needed)
            self.ui.combo_fps.currentTextChanged.connect(self.update_bitrate_options)
        self.ui.combo_fps.currentTextChanged.connect(self.refresh_slider_if_needed)
        if hasattr(self.ui, 'input_filename'): self.ui.input_filename.textChanged.connect(self.update_final_setup)

        if hasattr(self.ui, 'combo_encoder'):
            self.ui.combo_encoder.currentTextChanged.connect(self.update_final_setup)
        # Connect the pause and cancel buttons (they are initially disabled)
        if hasattr(self.ui, 'btn_cancel'):
            self.ui.btn_cancel.setEnabled(False)
            self.ui.btn_cancel.clicked.connect(self.cancel_render)
            
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.clicked.connect(self.toggle_pause)
        
        if hasattr(self.ui, 'combo_quality'): 
            self.ui.combo_quality.currentTextChanged.connect(self.on_quality_mode_changed)

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
        if hasattr(self.ui, 'combo_audio_bitrate'):
            self.ui.combo_audio_bitrate.currentTextChanged.connect(self.update_final_setup)
    
        # 5. AUTOMATIC DATA LOADING AT PROGRAM START
        self.detect_gpu_and_set_encoder()
        
        # 1. Check if the user has a manually saved folder preference
        user_settings = self.load_user_settings()
        saved_folder = user_settings.get("last_clips_folder", "")
        
        default_path = r"C:\Program Files (x86)\Steam\userdata\1077964895\gamerecordings\clips"
        
        if saved_folder and os.path.exists(saved_folder):
            self.clips_folder = saved_folder
        elif os.path.exists(default_path):
            self.clips_folder = default_path
            
        if self.clips_folder:
            self.scan_clips()
        
        if hasattr(self.ui, 'main_splitter'):
            self.ui.main_splitter.setSizes([300, 1300]) 
            
            
            

        # --- CUSTOM INPUTS: wire the overlay edit fields built by render_panel ---
        from PySide6.QtGui import QDoubleValidator, QIntValidator, QPixmap

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
                pix = QPixmap(get_resource_path("attention.png"))
                if not pix.isNull():
                    warn.setPixmap(pix.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
            pix_path = get_resource_path("attention.png")
            if os.path.exists(pix_path):
                self.warn_size.setPixmap(QPixmap(pix_path).scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.warn_size.hide()

            class InstantTooltipFilter(QObject):
                def eventFilter(self, obj, event):
                    if event.type() == QEvent.Type.Enter:
                        QToolTip.showText(event.globalPos(), obj.toolTip(), obj)
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
    
    os.environ["QT_MEDIA_BACKEND"] = "windows"
    

    parser = argparse.ArgumentParser()
    parser.add_argument('--updated-from', type=str, default="")
    parser.add_argument('--backup-folder', type=str, default="")
    args, unknown = parser.parse_known_args()


    try:
        import ctypes
        myappid = f'steempeg.app.v{APP_VERSION_STR}' 
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except: pass

    app = QApplication(sys.argv)

    icon_path = get_resource_path("logo.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))


    try:
        window = SteempegApp()
        
        if getattr(window, 'ui', None) is None:
            QMessageBox.critical(None, "Interface Error", "Failed to build the main window!")
            sys.exit(1)
            
        if os.path.exists(icon_path): 
            window.ui.setWindowIcon(QIcon(icon_path))
            
        # --- ADDING COLLAPSE AND EXPAND BUTTONS ---
        from PySide6.QtCore import Qt
        window.ui.setWindowFlags(window.ui.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        
    
        window.ui.showMaximized()
        
        if args.updated_from:
            QTimer.singleShot(1000, lambda: window.show_update_success(args.updated_from, args.backup_folder))
            
        sys.exit(app.exec())

    except Exception as e:
        # Now no mistake can hide =)))))))) =))))) dsfhnuijdfgbjiklgfvbjknlbfcvxjknml
        error_text = traceback.format_exc()
        print(error_text)
        try:
            import logging
            logging.critical("="*40)
            logging.critical("FATAL ERROR:")
            logging.critical(error_text)
            logging.critical("="*40)
        except:
            pass # If the logger has not yet been created
            
        QMessageBox.critical(None, "FATAL ERROR", f"APP ERROR:\n{error_text}")
sys.excepthook = global_exception_handler
if __name__ == "__main__":
    main()
