from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QFrame, QListWidget, QListWidgetItem
from steempeg.version import APP_VERSION_STR, APP_VERSION_FLOAT
from steempeg.render import bitrate
from steempeg.infra import cache
from steempeg.infra.logging import global_exception_handler
from steempeg.core.dash import mpd 
from steempeg.core import games
from steempeg.core.dash import discovery
from steempeg.core import capabilities
from steempeg.infra import paths
from steempeg.core.dash import repair
from steempeg.ui.player.surface import MPVWrapper
from steempeg.ui.player.fullscreen import FullscreenEventFilter
from steempeg.ui.player.controls.audio import VolumeControlWidget
from steempeg.ui.player.controls.speed import SpeedControlWidget
from steempeg.ui.player.thumbnails import ThumbnailBatchThread
from steempeg.ui.player.controls.timeline import CustomTimelineWidget
from steempeg.ui.library.grid_view import ClipCard
from steempeg.ui.library.filters import FilterMenu
from steempeg.ui.render_thread import RenderThread
from steempeg.services.updater import UpdateDownloadThread
from steempeg.ui.updater_mixin import UpdaterMixin





import sys
import os
import subprocess
import re
import psutil
import requests
import json
import time
import logging
from datetime import datetime


if getattr(sys, 'frozen', False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))

_bin_dir = os.path.join(_base_dir, "bin")
os.environ["PATH"] = _bin_dir + os.pathsep + _base_dir + os.pathsep + os.environ["PATH"]

import mpv

from PySide6.QtCore import Qt, QFile, QThread, Signal, QTimer, QSize, QObject
from PySide6.QtCore import QUrl, QEvent
from PySide6.QtWidgets import QVBoxLayout, QApplication, QFileDialog, QMessageBox
from PySide6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QBrush

from steempeg.ui.widgets import FlowLayout, BlockCombo, ElidedLabel, SmartSliderFilter, FilterPillButton

def get_resource_path(relative_path):
    return paths.get_resource_path(relative_path)


def get_save_directory():
    return paths.get_save_directory()

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt


from PySide6.QtWidgets import QPushButton
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt


    

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget, QCompleter
from PySide6.QtCore import Qt, QDate





class SteempegApp(UpdaterMixin, QObject):
    def __init__(self):
        # 1. LOADING THE INTERFACE
        super().__init__()
        loader = QUiLoader()
        ui_file_path = get_resource_path("smpegui13.ui")
        ui_file = QFile(ui_file_path)
        
        if not ui_file.open(QFile.ReadOnly):
            return
            
        self.ui = loader.load(ui_file)
        ui_file.close()

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
        

            
        # Create a log file with the date and time of launch
        log_filename = os.path.join(self.logs_dir, f"steempeg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self.current_log_file = log_filename
        logging.basicConfig(
            filename=log_filename,
            level=logging.DEBUG, # Everything here
            format='[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S',
            encoding='utf-8'
        )
        logging.info("="*40)
        logging.info(f"STEEMPEG {APP_VERSION_STR} RUNNING") 
        logging.info("="*40)

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

            def set_view_mode(mode):
                if mode == "list":
                    self.grid_clips.hide()
                    self.ui.table_clips.show()
                    self.btn_view_list.setStyleSheet(self.toggle_style_active)
                    self.btn_view_grid.setStyleSheet(self.toggle_style_inactive)
                else:
                    self.ui.table_clips.hide()
                    self.grid_clips.show()
                    
                    # HARD GEOMETRY RECALCULATION (Pictures won't fly away anymore!)
                    self.grid_clips.doItemsLayout()
                    
                    self.btn_view_list.setStyleSheet(self.toggle_style_inactive)
                    self.btn_view_grid.setStyleSheet(self.toggle_style_active)
                    
                    if self.grid_clips.selectedItems():
                        self.grid_clips.scrollToItem(self.grid_clips.selectedItems()[0])
                    
            self.btn_view_list.clicked.connect(lambda: set_view_mode("list"))
            self.btn_view_grid.clicked.connect(lambda: set_view_mode("grid"))

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
            self.neo_wrapper.setStyleSheet("background: transparent;")
            self.neo_wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            
            neo_layout = QHBoxLayout(self.neo_wrapper)
            neo_layout.setContentsMargins(0, 0, 0, 0)
            neo_layout.setSpacing(15)
            
            # 3. LEFT CIRCLE (Sidebar)
            sidebar_frame = QFrame()
            sidebar_frame.setFixedWidth(220)
            sidebar_frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            sidebar_frame.setStyleSheet("""
                QFrame { background-color: #2d2d2d; border-radius: 16px; border: 1px solid #383838; }
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
                    background-color: #2d2d2d; 
                    border-radius: 16px; 
                    border: 1px solid #383838;
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
                QTabWidget QLabel { color: #cccccc; font-weight: bold; background: transparent; }
                
                
                QTabWidget QPushButton {
                    background-color: #383838; color: #ffffff; 
                    border: 2px solid #444444; border-radius: 10px; 
                    padding: 6px 15px; font-weight: bold;
                }
                QTabWidget QPushButton:hover { background-color: #404040; border: 2px solid #6b5a8e; }
                QTabWidget QPushButton:pressed { background-color: #2d2d2d; border: 2px solid #b29ae7; }
                
                
                QTabWidget QComboBox, QTabWidget QLineEdit {
                    background-color: #383838; color: #ffffff; border: 2px solid #444444; 
                    border-radius: 12px; padding: 6px 14px; font-size: 12px; font-weight: bold;
                }
                QTabWidget QComboBox:hover, QTabWidget QLineEdit:hover { border: 2px solid #6b5a8e; background-color: #404040; }
                QTabWidget QComboBox:focus, QTabWidget QLineEdit:focus { border: 2px solid #b29ae7; background-color: #3a324a; }
                QTabWidget QComboBox::drop-down { border: none; width: 30px; }
                QTabWidget QComboBox::down-arrow {
                    image: none; border-left: 5px solid transparent; border-right: 5px solid transparent;
                    border-top: 5px solid #b29ae7; margin-right: 10px;
                }
                QTabWidget QComboBox QAbstractItemView {
                    background-color: #2d2d2d; color: #ffffff; border: 2px solid #b29ae7;
                    border-radius: 8px; selection-background-color: #b29ae7; selection-color: #111111; outline: none;
                }
                
               
                QTabWidget QCheckBox { color: #cccccc; font-weight: bold; spacing: 8px; background: transparent; }
                QTabWidget QCheckBox::indicator {
                    width: 20px; height: 20px; border-radius: 10px; border: 2px solid #444444; background-color: #383838;
                }
                QTabWidget QCheckBox::indicator:hover { border: 2px solid #6b5a8e; }
                QTabWidget QCheckBox::indicator:checked { background-color: #b29ae7; border: 2px solid #b29ae7; }
                
               
                QTabWidget QRadioButton { color: #cccccc; font-weight: bold; spacing: 8px; background: transparent; }
                QTabWidget QRadioButton::indicator {
                    width: 18px; height: 18px; border-radius: 9px; border: 2px solid #444444; background-color: #383838;
                }
                QTabWidget QRadioButton::indicator:hover { border: 2px solid #6b5a8e; }
                QTabWidget QRadioButton::indicator:checked { background-color: #b29ae7; border: 2px solid #b29ae7; }
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
        from PySide6.QtGui import QClipboard
        
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
        from PySide6.QtGui import QClipboard
        
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

                # 3. MAKE "HIDE" BUTTON COLLAPSE THE SPLITTER:
                # This event filter watches your existing settings_tabs. 
                # When your 'Hide' button hides the tabs, it snaps the splitter to 0!
                class HideWatcher(QObject):
                    def __init__(self, splitter):
                        super().__init__()
                        self.splitter = splitter
                        
                    def eventFilter(self, obj, event):
                        if event.type() == QEvent.Type.Hide:
                            self.splitter.setSizes([10000, 0]) # Collapse the bottom pane
                        elif event.type() == QEvent.Type.Show:
                            self.splitter.setSizes([750, 250]) # Expand the bottom pane back
                        return False # Do not block the actual hide/show event
                
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

        # --- UI INJECTION: INDEPENDENT BITRATE LABELS ---
        # Instead of stuffing multiple lines into one label, we create separate 
        # widgets so the Qt layout engine handles the vertical spacing perfectly
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
            
            
            

        # --- UI INJECTION: CUSTOM INPUTS ---
        from PySide6.QtWidgets import QLineEdit, QLabel, QHBoxLayout, QWidget, QSizePolicy
        from PySide6.QtGui import QDoubleValidator, QIntValidator, QPixmap
        
        # Helper function to inject custom input and warning icon next to ComboBox
        def inject_custom_input(combo_widget, placeholder):
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8) # Small gap between input and icon
            
            combo_widget.parentWidget().layout().replaceWidget(combo_widget, container)
            
            # Tell the ComboBox to aggressively expand and fill all available horizontal space!
            combo_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            
            line_edit = QLineEdit()
            line_edit.setPlaceholderText(placeholder)
            # Make the input box exactly 70px wide (no more, no less) so it doesn't stretch
            line_edit.setFixedWidth(70) 
            line_edit.hide() # Hidden by default
            
            warn_icon = QLabel()
            warn_icon.setFixedSize(16, 16)
            
            # Load the attention icon smoothly
            pix_path = get_resource_path("attention.png")
            if os.path.exists(pix_path):
                pixmap = QPixmap(pix_path)
                warn_icon.setPixmap(pixmap.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            warn_icon.hide() # Hidden by default
            
            # ---> APPLY THE INSTANT TOOLTIP MAGIC HERE <---
            if hasattr(self, 'instant_tooltip'):
                warn_icon.installEventFilter(self.instant_tooltip)
            
            # Add widgets to layout. 
            layout.addWidget(combo_widget)
            layout.addWidget(line_edit)
            layout.addWidget(warn_icon)
            
            # Show/hide logic
            combo_widget.currentTextChanged.connect(lambda t: (
                line_edit.setVisible("Custom" in t),
                warn_icon.setVisible(False) if "Custom" not in t else None
            ))
            return line_edit, warn_icon
    
        # Inject 3 inputs and unpack the labels
        if hasattr(self.ui, 'combo_fps'):
            self.input_custom_fps, self.warn_fps = inject_custom_input(self.ui.combo_fps, "FPS")
            self.input_custom_fps.setValidator(QIntValidator(1, 120))
            self.input_custom_fps.textChanged.connect(self.validate_custom_fps)
            
        if hasattr(self.ui, 'combo_bitrate'):
            self.input_custom_vbitrate, self.warn_vbitrate = inject_custom_input(self.ui.combo_bitrate, "Mbps")
            self.input_custom_vbitrate.setValidator(QDoubleValidator(0.1, 200.0, 2))
            self.input_custom_vbitrate.textChanged.connect(self.validate_custom_vbitrate)
            
        if hasattr(self.ui, 'combo_audio_bitrate'):
            self.input_custom_abitrate, self.warn_abitrate = inject_custom_input(self.ui.combo_audio_bitrate, "kbps")
            self.input_custom_abitrate.setValidator(QIntValidator(1, 500))
            self.input_custom_abitrate.textChanged.connect(self.validate_custom_abitrate)
    
        if hasattr(self, 'custom_timeline'):
                self.custom_timeline.setEnabled(False) # Disable clicks into empty space
                self.custom_timeline.set_duration(0)   # Reset time
                self.custom_timeline.force_jump(0)     # Position the playhead at 0
                self.custom_timeline.canvas.markers.clear()
                self.custom_timeline.canvas.update()
                
        if hasattr(self.ui, 'label_time'):
            self.ui.label_time.setText("00:00 / 00:00")
        
        QApplication.instance().applicationStateChanged.connect(self.hide_hud_on_minimize)
    
    # --- CONTEXT MENU LOGIC ---
    def show_grid_context_menu(self, pos):
        """ Pop-up menu for the grid """
        from PySide6.QtWidgets import QMenu
        from PySide6.QtCore import Qt
        import os
        
        # 1. Check if we clicked on an image in the grid.
        item = self.grid_clips.itemAt(pos)
        if not item:
            return

        # 2. Retrieve the video path from the hidden key
        clip_path = item.data(Qt.UserRole + 1)
        if not clip_path or not os.path.exists(clip_path):
            return

        # 3. Creating a menu and getting rid of the ugly Windows shadow
        menu = QMenu(self.grid_clips)
        menu.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        
        # Menu design
        menu.setStyleSheet("""
            QMenu { 
                background-color: #2d2d2d; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 8px; 
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
                font-weight: bold;
            }
            QMenu::item { 
                padding: 6px 24px 6px 24px; 
                border-radius: 4px;
                margin: 2px 4px;
            }
            QMenu::item:selected { 
                background-color: #6b5a8e; 
            }
            QMenu::separator {
                height: 1px;
                background-color: #444444;
                margin: 4px 10px;
            }
        """)
        
        action_open = menu.addAction("📂 Open in folder")
        menu.addSeparator()
        action_delete = menu.addAction("🗑️ Delete Clip")
        
        # 4. Linking to existing functions
        action_open.triggered.connect(lambda: self.open_clip_folder(clip_path))
        action_delete.triggered.connect(lambda: self.delete_clip(clip_path))
        
        # 5. Displaying the menu under the cursor
        menu.exec(self.grid_clips.viewport().mapToGlobal(pos))

    def show_clip_context_menu(self, pos):
        """ Pop-up menu for a standard list (List/Table) """
        from PySide6.QtWidgets import QMenu
        from PySide6.QtCore import Qt
        import os
        
        # 1. Check if we clicked on a valid row.
        item = self.ui.table_clips.itemAt(pos)
        if not item:
            return

        # 2. Retrieve the video path from the first cell (column) of the selected row.
        selected_row = item.row()
        clip_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
        
        if not clip_path or not os.path.exists(clip_path):
            return

        # 3. Creating a menu and getting rid of the ugly Windows shadow
        menu = QMenu(self.ui.table_clips)
        menu.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        
        # Your signature menu design
        menu.setStyleSheet("""
            QMenu { 
                background-color: #2d2d2d; 
                color: #ffffff; 
                border: 2px solid #444444; 
                border-radius: 8px; 
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
                font-weight: bold;
            }
            QMenu::item { 
                padding: 6px 24px 6px 24px; 
                border-radius: 4px;
                margin: 2px 4px;
            }
            QMenu::item:selected { 
                background-color: #6b5a8e; 
            }
            QMenu::separator {
                height: 1px;
                background-color: #444444;
                margin: 4px 10px;
            }
        """)
        
        action_open = menu.addAction("📂 Open in folder")
        menu.addSeparator()
        action_delete = menu.addAction("🗑️ Delete Clip")
        
        # 4. Linking to existing functions
        action_open.triggered.connect(lambda: self.open_clip_folder(clip_path))
        action_delete.triggered.connect(lambda: self.delete_clip(clip_path))
        
        # 5. Displaying the menu under the cursor
        menu.exec(self.ui.table_clips.viewport().mapToGlobal(pos))

    def open_clip_folder(self, clip_path):
        """ Opens the clip's directory directly in Windows Explorer. """
        try:
            os.startfile(clip_path)
        except Exception as e:
            logging.error(f"Failed to open folder: {e}")

    def delete_clip(self, clip_path):
        """ Prompts for confirmation and deletes the clip folder permanently. """
        import shutil
        
        # 1. Double check with the user to prevent accidental deletion
        msg = QMessageBox(self.ui)
        msg.setWindowTitle("Delete Clip")
        msg.setText("Are you sure you want to delete this clip?")
        msg.setInformativeText("This will permanently delete the folder and all its contents.\nThis cannot be undone!")
        msg.setIcon(QMessageBox.Warning)
        
        btn_delete = msg.addButton("🗑️ Delete", QMessageBox.AcceptRole)
        btn_cancel = msg.addButton("Cancel", QMessageBox.RejectRole)
        
        msg.exec()
        
        if msg.clickedButton() == btn_delete:
            try:
                # 2. Stop MPV playback if the deleted clip is currently playing
                selected_row = self.ui.table_clips.currentRow()
                if selected_row >= 0:
                    playing_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
                    if playing_path == clip_path and hasattr(self, 'player'):
                        self.player.stop()
                        
                # 3. Nuke the folder from orbit
                shutil.rmtree(clip_path)
                logging.info(f"Deleted clip folder: {clip_path}")
                
                # 4. Refresh the UI
                self.scan_clips()
                
                if hasattr(self.ui, 'label_short_summary'):
                    if hasattr(self, 'reset_bottom_summary'): self.reset_bottom_summary()
                if hasattr(self.ui, 'label_detailed_summary'):
                    self.ui.label_detailed_summary.setText("Waiting for clip selection...")
                    
            except Exception as e:
                logging.error(f"Failed to delete clip: {e}")
                QMessageBox.critical(self.ui, "Error", f"Failed to delete the clip.\nIt might be in use by another program.\n\n{e}")

    def eventFilter(self, source, event):
        from PySide6.QtCore import QEvent, QTimer
        
        if source == self.ui and event.type() == QEvent.Type.WindowStateChange:
            if not self.ui.isMaximized() and not getattr(self, 'is_fullscreen', False):
                if getattr(self, 'needs_geometry_restore', False) and hasattr(self, 'true_normal_geom'):
                    
                    def restore_geom():
                        if not getattr(self, 'is_fullscreen', False) and not self.ui.isMaximized():
                            self.ui.setGeometry(self.true_normal_geom)
                            
                    QTimer.singleShot(50, restore_geom)
                    self.needs_geometry_restore = False

        # --- FLOATING PANEL RESIZE LOGIC ---
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
                    
        # 2. Disable right-click selection in the Grid
        if hasattr(self, 'grid_clips') and source == self.grid_clips.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    click_pos = event.position().toPoint()
                    self.show_grid_context_menu(click_pos)
                    return True

        return super().eventFilter(source, event)
    
    def set_status(self, text):
        """ Updates the status text and the progress bar """
        if hasattr(self.ui, 'label_status'):
            self.ui.label_status.setText(text.split('..')[0] + '..')
            
        if hasattr(self.ui, 'progress_render'):
            # 0
            if text in ["Ready", "Success", "Cancelled", "Error!"]:
                self.ui.progress_render.setValue(0)
                if hasattr(self, 'label_pct'): self.label_pct.setText("0%")
                if text != "Error!": self.ui.label_status.setText(text)
                
            # Separating Logic: The bar consumes 0.1%, yet the text displays WHOLE numbers!
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
    
    def choose_folder(self):
        """ Opens a dialog for selecting a clips folder and remembers the choice. """
        target_path = getattr(self, 'clips_folder', "")
        
        if not target_path or not os.path.exists(target_path):
            target_path = r"C:\Program Files (x86)\Steam\userdata\1077964895\gamerecordings\clips"
            if not os.path.exists(target_path):
                target_path = "C:\\"

        folder = QFileDialog.getExistingDirectory(self.ui, "Select clips folder", target_path)
        if folder:
            self.clips_folder = folder
            self.save_user_settings("last_clips_folder", folder) # Save permanently!
            self.scan_clips()
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
                
        from PySide6.QtGui import QPixmap, QIcon
        
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
            from PySide6.QtGui import QIcon
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
            
            from PySide6.QtCore import QEvent
            self.btn_theater.clearFocus()
            QApplication.postEvent(self.btn_theater, QEvent(QEvent.Type.Leave))

    def show_filter_menu(self):
        """ Calculates the coordinates and passes the ENTIRE PROGRAM (self) to the menu. """
        if not hasattr(self, 'btn_filter_pill'): return
        
        # 1. Forcefully destroy the old window to reset the Qt focus bug.
        if hasattr(self, 'filter_menu') and self.filter_menu:
            self.filter_menu.deleteLater()
            
        # 2. Creating a brand-new menu from scratch
        self.filter_menu = FilterMenu(self.ui)
        self.filter_menu.gather_statistics(self)
        
        # 3. Positioning and showcasing
        button_bottom_left = self.btn_filter_pill.mapToGlobal(QPoint(0, self.btn_filter_pill.height()))
        x_shift = self.filter_menu.width() - self.btn_filter_pill.width()
        
        self.filter_menu.move(button_bottom_left.x() - x_shift + 10, button_bottom_left.y() + 5)
        self.filter_menu.show()

    def apply_sorting(self):
        """ FAST INDEPENDENT SORTING ENGINE """
        if not hasattr(self.ui, 'table_clips'): return
        table = self.ui.table_clips
        sort_idx = self.combo_sort.currentIndex()
        
        import re
        import os
        from datetime import datetime
        from PySide6.QtCore import Qt
        
        # Freezing graphics and signals for instant speed
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        
        all_data = []
        for row in range(table.rowCount()):
            is_hidden = table.isRowHidden(row)
            row_items = [table.takeItem(row, col) for col in range(table.columnCount())]
            all_data.append({ 'table_items': row_items, 'orig_row': row, 'hidden': is_hidden })
            
        
        def get_sort_key(data):
            r = data['table_items']
            
            if sort_idx == 0: 
                # Read the actual modification date of the folder containing the clip
                clip_path = r[0].data(Qt.UserRole)
                if clip_path and os.path.exists(clip_path):
                    return os.path.getmtime(clip_path)
                return 0
                
            if sort_idx in (1, 2): # GAME NAME
                txt = r[0].text().lower() if r[0] else ""
                return re.sub(r'[^a-zа-я0-9]', '', txt)
                
            if sort_idx in (3, 4): # TYPE
                txt = r[1].text().lower() if r[1] else ""
                return re.sub(r'[^a-zа-я0-9]', '', txt)
                
            if sort_idx in (5, 6): # DATE
                txt = re.sub(r'\s+', ' ', r[2].text().strip()) if r[2] else ""
                try: return datetime.strptime(txt, "%d %B %Y %I:%M %p").timestamp()
                except:
                    try: return datetime.strptime(txt, "%d %B %Y").timestamp()
                    except: return 0
                    
            if sort_idx in (7, 8): # DURATION
                txt = r[3].text() if r[3] else ""
                h = int(re.search(r'(\d+)h', txt).group(1)) if 'h' in txt else 0
                m = int(re.search(r'(\d+)m', txt).group(1)) if 'm' in txt else 0
                s = int(re.search(r'(\d+)s', txt).group(1)) if 's' in txt else 0
                return h * 3600 + m * 60 + s
                
            return data['orig_row']

       
        reverse = sort_idx in (0, 2, 4, 6, 8) 
        all_data.sort(key=get_sort_key, reverse=reverse)
        
        for new_row, data in enumerate(all_data):
            for col, item in enumerate(data['table_items']):
                table.setItem(new_row, col, item)
            table.setRowHidden(new_row, data['hidden'])
            
        table.blockSignals(False)
        table.setUpdatesEnabled(True)
        
        
        if hasattr(self, 'fast_sync_grid'):
            self.fast_sync_grid()

    def fast_sync_grid(self):
        """ INSTANT GRID SYNCHRONIZATION """
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'): return

        grid = self.grid_clips
        table = self.ui.table_clips

        grid.setUpdatesEnabled(False)
        grid.blockSignals(True)

        # 1. Create a dictionary for quick lookup clip_path -> row_index in the table
        table_order = {}
        for row in range(table.rowCount()):
            t_item = table.item(row, 0)
            if t_item:
                clip_path = t_item.data(Qt.UserRole)
                # Saving the index and visibility status
                table_order[clip_path] = {'row': row, 'hidden': table.isRowHidden(row)}

        # 2. Gently update grid elements 
        for i in range(grid.count()):
            item = grid.item(i)
            clip_path = item.data(Qt.UserRole + 1)
            
            if clip_path and clip_path in table_order:
                info = table_order[clip_path]
                
                item.setText(f"{info['row']:06d}")
                item.setData(Qt.UserRole, info['row']) 
                item.setHidden(info['hidden'])         
        # 3. Qt's built-in ultra-fast sort
        grid.sortItems(Qt.AscendingOrder)

        grid.blockSignals(False)
        grid.setUpdatesEnabled(True)

    # --- TRUE HIGH-END FULLSCREEN SYSTEM ---
    def toggle_fullscreen(self):
        """ Completely isolates the video container with Anti-Spam Lock & Black Background """
        
        if getattr(self, 'fullscreen_lock', False): return
        self.fullscreen_lock = True
        
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QEvent, Qt, QTimer
        from PySide6.QtGui import QIcon
        import os

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
            
            from PySide6.QtWidgets import QSizePolicy
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
            
        from PySide6.QtGui import QPainterPath, QRegion
        
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
        from PySide6.QtCore import Qt
        
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
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        
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
        
        from PySide6.QtWidgets import QToolTip
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
            from PySide6.QtGui import QIcon
            icon_path = get_resource_path("icon_pause.png")
            self.ui.btn_play.setIcon(QIcon(icon_path))
        

    def closeEvent(self, event):
        """ Triggered automatically when the window's red 'X' button is clicked """
        self._force_pause = True
        
        # 1. Kill the player if it is active.
        if hasattr(self, 'player') and self.player:
            self.player.pause = True 
            try:
                self.player.command('stop') 
            except:
                pass
                
        # 2. Killing the frozen FFmpeg
        try:
            import psutil
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

        event.accept()

    
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
                    from PySide6.QtGui import QIcon
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
    def on_app_exit(self):
        """ Global Intercept: Triggers when the entire program closes. """
        print("CLEANING BEFORE CLOSING...")
        if hasattr(self, 'player') and self.player:
            try:
                self.player.command('stop')
                self.player.terminate()
            except: pass
            
        # Killing all zombie FFmpeg child processes
        try:
            import psutil
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            for child in children:
                if "ffmpeg" in child.name().lower() or "ffprobe" in child.name().lower():
                    child.kill()
                    print(f"Killed FFmpeg after exit: {child.name()}")
        except: pass
    
    def show_about_dialog(self):
        """ Shows the About dialog"""
        if getattr(self, '_about_is_open', False): 
            return # Block if already open
        self._about_is_open = True
        
        msg_box = QMessageBox(self.ui)
        msg_box.setWindowTitle("About Steempeg")
        
        # Logo of the window itself
        icon_path = get_resource_path("logo.png")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            msg_box.setIconPixmap(pixmap)
        else:
            msg_box.setIcon(QMessageBox.Information)

        # Prepare 100% working absolute paths for icons within HTML
        # Use QUrl so Qt knows exactly where the images are located, even within an .exe file
        github_icon = QUrl.fromLocalFile(get_resource_path("github.jpg")).toString()
        steam_icon = QUrl.fromLocalFile(get_resource_path("steam.png")).toString()

        about_text = f"""
        <h3>Steempeg v{APP_VERSION_STR}</h3>
        <p><b>Build:</b> v{APP_VERSION_STR}</p>
        <p><b>Developer:</b> Emily 🎀 <span style="color: #888888; font-size: 10pt;">@applejuicy23</span></p>

        <p><img src="{github_icon}" width="16" height="16" align="middle"> <b>GitHub:</b> <a href="https://github.com/applejuicy23/steempeg">applejuicy23/steempeg</a></p>
        <p><img src="{steam_icon}" width="16" height="16" align="middle"> <b>Steam:</b> <a href="https://steamcommunity.com/id/applejuicy23/">applejuicy23</a></p>

        <p>A smart, elegant, and fast hardware-accelerated video renderer for Steam Clips.</p>
        <p>Powered by <b>FFmpeg,</b> <b>PyAV</b> & <b>MPV</b></p>

        <p style="font-size: 8pt; color: #777777; margin-top: 15px;">
        <i>Steempeg is an unofficial, community-created tool.<br>
        Not affiliated with, associated with, authorized, or endorsed by Valve Corporation or Steam.</i>
        </p>
        """
        
        msg_box.setText(about_text)
        msg_box.setTextInteractionFlags(Qt.TextBrowserInteraction)

        msg_box.setStandardButtons(QMessageBox.Close)
        msg_box.exec()
        
        self._about_is_open = False # Release the lock when closed

    

    

    

   

    


    def scan_clips(self):
        """ Scans both standard Steam folders AND custom extracted folders """
        if not hasattr(self.ui, 'table_clips'): return
        self.ui.table_clips.setSortingEnabled(False) 
        self.ui.table_clips.setRowCount(0)
        
        if not self.clips_folder or not os.path.exists(self.clips_folder): return

        base_folder = os.path.normpath(self.clips_folder)
        if os.path.basename(base_folder).lower() == "clips":
            base_folder = os.path.dirname(base_folder)

        folders_to_check = set()
        
        # Scenario 1: Standard Steam Structure (gamerecordings/clips & gamerecordings/video)
        for sub in ["clips", "video"]:
            sub_path = os.path.join(base_folder, sub)
            if os.path.exists(sub_path):
                for item in os.listdir(sub_path):
                    full = os.path.join(sub_path, item)
                    if os.path.isdir(full): folders_to_check.add(full)
                    
        # Scenario 2: selected the W:\SteamLibrary folder itself directly
        folders_to_check.add(base_folder)
        try:
            for item in os.listdir(base_folder):
                full = os.path.join(base_folder, item)
                if os.path.isdir(full) and item.lower().startswith(("clip_", "bg_", "fg_")):
                    folders_to_check.add(full)
        except Exception: pass

        try:
            # Sort the chaotic set() by folder modification time
            sorted_folders = sorted(list(folders_to_check), key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True)
            
            for full_path in sorted_folders:
                if not os.path.exists(full_path): continue

                folder_name = os.path.basename(full_path).lower()
                # We strictly allow only Steam clips!
                if not folder_name.startswith(("clip_", "bg_", "fg_")):
                    continue

                folder_name = os.path.basename(full_path).lower()
                if "steempeg" in folder_name or folder_name in ["logs", "cache", "_update_extracted"]:
                    continue
                
                has_mpd = False
                has_chunks = False
                mpd_path = None
                
                for root, dirs, files in os.walk(full_path):
                    for f in files:
                        if f.endswith(".mpd"):
                            has_mpd = True
                            mpd_path = os.path.join(root, f)
                            break 
                    if any("chunk-stream" in f for f in files):
                        has_chunks = True

                if has_chunks and not has_mpd:
                    recovered = self.recover_orphaned_clip(full_path)
                    if recovered: 
                        has_mpd = True
                        # Just in case, search for mpd again after recovery.
                        for root, dirs, files in os.walk(full_path):
                            for f in files:
                                if f.endswith(".mpd"):
                                    mpd_path = os.path.join(root, f)
                                    break 

                if not has_mpd: continue

                # MAGIC: Extracting Duration from MPD
                duration_str = "--:--"
                if mpd_path:
                    try:
                        import re
                        with open(mpd_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            
                            match = re.search(r'(?:mediaPresentationDuration|duration)="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"', content)
                            if match:
                                h = int(match.group(1)) if match.group(1) else 0
                                m = int(match.group(2)) if match.group(2) else 0
                                s = int(float(match.group(3))) if match.group(3) else 0
                                
                                # Formatting for a Beautiful Look
                                if h == 0 and m == 0: duration_str = f"{s}s"
                                elif h == 0: duration_str = f"{m}m {s}s"
                                else: duration_str = f"{h}h {m}m {s}s"
                    except: pass

                folder_name = os.path.basename(full_path)
                parts = folder_name.split("_")
                
                if len(parts) >= 4 and parts[1].isdigit():
                    prefix = parts[0].lower()
                    app_id = parts[1]
                    
                    if prefix == "clip": rec_type = "🎬 Clip"
                    elif prefix == "bg": rec_type = "📼 BG"
                    elif prefix == "fg": rec_type = "🎞️ FG"
                    else: rec_type = "Unknown"

                    raw_name = self.get_game_name(app_id)
                    game_name = f"   {raw_name}" 
                    icon = self.get_game_icon(app_id)

                    try:
                        from datetime import timezone
                        # 1. Concatenate the date and time from the folder into a single string (YYYYMMDD_HHMMSS)
                        raw_datetime_str = f"{parts[2]}_{parts[3]}"
                        
                        # 2. We tell Python: "This is UTC time (Greenwich Mean Time)!"
                        dt_utc = datetime.strptime(raw_datetime_str, "%Y%m%d_%H%M%S")
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                        
                        # 3. Automatically convert to your time zone (Windows will automatically detect that you are in UTC+3)
                        dt_local = dt_utc.astimezone()
                        
                        # 4. Unpack back into beautiful formats for the interface
                        formatted_date = dt_local.strftime("%d %B %Y")
                        formatted_time = dt_local.strftime("%I:%M %p")
                    except Exception as e:
                        # If the folder is named incorrectly, use the old fallback option.
                        try: formatted_date = datetime.strptime(parts[2], "%Y%m%d").strftime("%d %B %Y")
                        except: formatted_date = parts[2]
                        try: formatted_time = datetime.strptime(parts[3], "%H%M%S").strftime("%I:%M %p")
                        except: formatted_time = ""


                else:
                    rec_type = "Folder"
                    game_name = folder_name
                    formatted_date = "Unknown"
                    icon = QIcon()

                row_position = self.ui.table_clips.rowCount()
                self.ui.table_clips.insertRow(row_position)
                
                item_game = QTableWidgetItem(icon, game_name)
                item_game.setData(Qt.UserRole, full_path) 
                self.ui.table_clips.setItem(row_position, 0, item_game)
                
                item_type = QTableWidgetItem(rec_type)
                item_type.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                self.ui.table_clips.setItem(row_position, 1, item_type)
                
                item_date = QTableWidgetItem(formatted_date)
                self.ui.table_clips.setItem(row_position, 2, item_date)

                date_display = f"{formatted_date}\n{formatted_time}" if formatted_time else formatted_date
                
                item_date = QTableWidgetItem(date_display)
                item_date.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter) 
                self.ui.table_clips.setItem(row_position, 2, item_date)

                # Column 3: DURATION
                item_duration = QTableWidgetItem(duration_str)
                item_duration.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                self.ui.table_clips.setItem(row_position, 3, item_duration)

            self.ui.table_clips.setSortingEnabled(True)

            self.ui.table_clips.horizontalHeader().sectionClicked.connect(lambda: QTimer.singleShot(50, self.sync_grid_to_table))

            if hasattr(self, 'build_netflix_grid'):
                self.build_netflix_grid()
                
            if hasattr(self, 'lbl_clip_count'):
                self.lbl_clip_count.setText(f"• {self.ui.table_clips.rowCount()} Clips")
                
                    
        except Exception as e:
            import logging
            logging.error(f"Scan Error: {e}")
    
    def add_user_marker(self, target_ms=None):
        """ Sets a tag according to Gaben's GOST standard and saves it to JSON. """
        import time, json, os
        
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
                import re
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
    def choose_destination(self):
        """ Select a custom folder to save the finished video """
        folder = QFileDialog.getExistingDirectory(self.ui, "Select Destination Folder")
        if folder:
            self.custom_destination = folder
            self.ui.destination_button.setText(f"Destination: {folder}")
        else:
            # If we change our minds and click Cancel, we return to our cool folder
            default_export_dir = os.path.join(get_save_directory(), "rendered_videos").replace('\\', '/')
            if not os.path.exists(default_export_dir):
                os.makedirs(default_export_dir, exist_ok=True)
            self.custom_destination = default_export_dir
            self.ui.destination_button.setText(f"Destination: {default_export_dir}")
            
        self.update_final_setup()

    def open_logs_folder(self):
        if hasattr(self, 'logs_dir'):
            paths.open_in_file_manager(self.logs_dir)

    def open_current_log(self):
        if hasattr(self, 'current_log_file'):
            paths.open_in_file_manager(self.current_log_file)
        
    def get_all_mpd_paths(self, clip_path):
        return discovery.find_mpd_paths(clip_path)

    def fix_steam_manifest(self, mpd_path):
        return repair.fix_steam_manifest(mpd_path)

    def recover_orphaned_clip(self, folder_path):
        return repair.recover_orphaned_clip(folder_path)
    
    def get_game_name(self, app_id):
        app_id = str(app_id)
        # 1. сначала кэш
        if app_id in self.game_names_cache:
            return self.game_names_cache[app_id]
        # 2. иначе спросить Steam один раз и запомнить
        name = games.fetch_game_name(app_id)
        if name:
            self.game_names_cache[app_id] = name
            self.save_json_cache()
            return name
        return f"Unknown Game ({app_id})"
    
    def on_audio_only_toggled(self, checked):
        """ Disables video settings if audio-only mode is active """
        if checked and hasattr(self.ui, 'check_mute_audio'):
            self.ui.check_mute_audio.blockSignals(True)
            self.ui.check_mute_audio.setChecked(False)
            self.ui.check_mute_audio.blockSignals(False)
            
        if hasattr(self.ui, 'tab_video'): 
            self.ui.tab_video.setEnabled(not checked) # Freeze entire Video Tab
        self.update_final_setup()

    def on_mute_audio_toggled(self, checked):
        """ Disables audio settings if video-only mode is active """
        if checked and hasattr(self.ui, 'check_audio_only'):
            self.ui.check_audio_only.blockSignals(True)
            self.ui.check_audio_only.setChecked(False)
            self.ui.check_audio_only.blockSignals(False)
            
        if hasattr(self.ui, 'tab_audio'): 
            self.ui.tab_audio.setEnabled(not checked) # Freeze entire Audio Tab
        self.update_final_setup()
    
    def load_json_cache(self):
        return cache.read_json(self.json_cache_path)

    def save_json_cache(self):
        cache.write_json(self.json_cache_path, self.game_names_cache)

    def load_user_settings(self):
        return cache.read_json(os.path.join(self.cache_dir, "settings.json"))

    def save_user_settings(self, key, value):
        """ Saves a specific preference to the settings file permanently """
        path = os.path.join(self.cache_dir, "settings.json")
        settings = cache.read_json(path)
        settings[key] = value
        cache.write_json(path, settings)
    
    def get_game_icon(self, app_id):
        app_id = str(app_id)
        # 1. RAM-кэш
        if app_id in self.game_icons_cache:
            return self.game_icons_cache[app_id]
        # 2. диск-кэш, иначе скачиваем
        icon_path = os.path.join(self.cache_dir, f"{app_id}.jpg")
        if not os.path.exists(icon_path):
            if not games.download_icon(app_id, icon_path):
                return QIcon()
        # 3. строим Qt-иконку (это Qt -> остаётся тут) и кэшируем в RAM
        icon = QIcon(QPixmap(icon_path))
        self.game_icons_cache[app_id] = icon
        return icon

    def get_clip_size_and_duration(self, clip_path, mpd_content):
        # total size of the clip folder
        size_mb = discovery.folder_size_bytes(clip_path) / (1024 * 1024)
        size_str = f"{size_mb / 1024:.2f} GB" if size_mb >= 1000 else f"{size_mb:.1f} MB"

        # duration: the parsing lives in mpd.py now, the display formatting stays here
        seconds = mpd.parse_duration_seconds(mpd_content)
        if seconds is None:
            self.current_clip_duration_sec = 0.0   # reset so no old time stays from the last clip
            duration_str = "Unknown"
        else:
            self.current_clip_duration_sec = seconds
            # show H:MM:SS when it is over an hour, otherwise just MM:SS
            total = int(seconds)
            h, m, s = total // 3600, (total % 3600) // 60, total % 60
            duration_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        self.current_clip_duration_str = duration_str
        return size_str, duration_str
    
    def get_fps_from_mpd(self, mpd_path):
        return mpd.get_fps(mpd_path)

    def get_audio_bitrate_from_mpd(self, mpd_path):
        return mpd.get_audio_bitrate_kbps(mpd_path)
    
    def detect_gpu_and_set_encoder(self):
        """Probe the hardware encoders and fill the encoder dropdown."""
        if not hasattr(self.ui, 'combo_encoder'):
            return
        self.ui.combo_encoder.clear()

        logging.info("Starting silent hardware encoder probe...")
        encoders = capabilities.detect_supported_encoders()
        logging.info(f"Probe done. Available: {[name for name, _ in encoders]}")
        for display_name, codec in encoders:
            self.ui.combo_encoder.addItem(display_name, codec)

        # default to the first hardware encoder if there is one, otherwise CPU
        self.ui.combo_encoder.setCurrentIndex(1 if self.ui.combo_encoder.count() > 1 else 0)
    

    def on_grid_selection_changed(self):
        """ Select in Grid -> Quietly select in List -> List automatically updates the player """
        selected_items = getattr(self, 'grid_clips', None) and self.grid_clips.selectedItems()
        if not selected_items: return
        
        # In the Qt.UserRole card we have a ready-made string index (number)!
        row_idx = selected_items[0].data(Qt.UserRole)
        
        if hasattr(self.ui, 'table_clips'):
            # Check if this row is already selected
            if self.ui.table_clips.currentRow() != row_idx:
                # Just move the focus. The table itself will trigger the player exactly once!
                self.ui.table_clips.selectRow(row_idx)

    def build_netflix_grid(self):
        """ Transforms rows from a hidden table into vibrant cards. """
        import PySide6.QtWidgets as qtw
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'):
            return
            
        self.grid_clips.clear()
        
        for row in range(self.ui.table_clips.rowCount()):
            title_item = self.ui.table_clips.item(row, 0)
            date_item = self.ui.table_clips.item(row, 2)
            time_item = self.ui.table_clips.item(row, 3)
            
            title = title_item.text() if title_item else "Unknown"
            date_str = date_item.text() if date_item else "Today"
            time_str = time_item.text() if time_item else "00:00"
            clip_path = title_item.data(Qt.UserRole) if title_item else None
            
            icon_path = ""
            thumb_path = ""
            badge_text = "Clip"
            
            if clip_path:
                clip_folder_name = os.path.basename(clip_path)
                parts = clip_folder_name.split("_")
                
                # Extract the clip type
                if len(parts) > 0:
                    prefix = parts[0].upper()
                    if prefix in ["FG", "BG", "CLIP"]: badge_text = prefix
                    
                if len(parts) >= 2 and parts[1].isdigit():
                    icon_path = os.path.join(self.cache_dir, f"{parts[1]}.jpg")
                    
                if os.path.exists(clip_path):
                    # Check "thumbnail.jpg" directly without scanning the folder
                    direct_thumb = os.path.join(clip_path, "thumbnail.jpg")
                    if os.path.exists(direct_thumb):
                        thumb_path = direct_thumb
                    else:
                        # Fallback option (in case the file has a different name)
                        # Only then do we use the resource-intensive os.listdir
                        for file in os.listdir(clip_path):
                            if file.endswith((".jpg", ".png", ".jpeg")):
                                thumb_path = os.path.join(clip_path, file)
                                break

            # Create the custom card
            card = ClipCard(title, f"{date_str} • {time_str}", badge_text, thumb_path, icon_path, row)
            
            item = qtw.QListWidgetItem(self.grid_clips)
            item.setSizeHint(qtc.QSize(260, 190))

            item.setData(Qt.UserRole, row) # Save row index for selection logic
            item.setData(Qt.UserRole + 1, clip_path) 
            self.grid_clips.setItemWidget(item, card)

            
            # SYNC VISIBILITY WITH TABLE
            if self.ui.table_clips.isRowHidden(row):
                item.setHidden(True)

    

    def update_quality_options(self):
        """ Reads the clip's XML data and prepares the UI for the render settings """
        if not hasattr(self.ui, 'table_clips'): return
        selected_row = self.ui.table_clips.currentRow()
        if selected_row < 0:
            self.ui.source_label.setText("Source:")
            self.ui.orig_res_label.setText("Original Resolution:")
            # Set default empty states for our new widgets
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate:")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate:")
            return
        if hasattr(self, 'grid_clips'):
            self.grid_clips.blockSignals(True) # To Avoid Conflicts
            for i in range(self.grid_clips.count()):
                item = self.grid_clips.item(i)
                # Verify the card's hidden index against the selected row in the table.
                if item.data(Qt.UserRole) == selected_row:
                    item.setSelected(True)
                    self.grid_clips.scrollToItem(item)# Automatically scroll to the desired tile!
                else:
                    item.setSelected(False)
            self.grid_clips.blockSignals(False)
        
        # --- 1. SAVE CURRENT USER SELECTION ---
        current_quality = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else ""
        current_fps = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else ""
        current_bitrate = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else ""
            
        # Extract the FULL path (for FFmpeg)
        clip_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
        

        
        # Extract ONLY the folder NAME (for example, bg_3513350_20260508) for the text field
        clip_folder_name = os.path.basename(clip_path)

        parts = clip_folder_name.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            self.current_game_icon = os.path.join(self.cache_dir, f"{parts[1]}.jpg")
        else:
            self.current_game_icon = ""

        ## Automatically insert a neat file name
        if hasattr(self.ui, 'input_filename'):
            self.ui.input_filename.setText(f"{clip_folder_name}_rendered")
            
        # Search for mpd files by full path
        all_mpds = self.get_all_mpd_paths(clip_path)

        if not all_mpds:
            self.ui.source_label.setText("Source: No MPD files found")
            self.ui.orig_res_label.setText("Original resolution: Unknown")
            # Update our new widgets
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate: Unknown")
            self.ui.combo_quality.clear()
            if hasattr(self, 'btn_copy_src'): self.btn_copy_src.hide()
            return

        # Update the label with the path to the sources
        source_dirs = [os.path.dirname(mpd) for mpd in all_mpds]
        unique_source_dirs = list(dict.fromkeys(source_dirs))
        
        # Save FULL raw paths to memory so our COPY button can copy them completely!
        self.current_source_raw_paths = "\n".join(unique_source_dirs)
        
        # Local helper to cleanly cut long HTML paths
        def elide_html_path(path, max_len=75):
            if len(path) <= max_len: return path
            half = (max_len - 5) // 2
            return path[:half] + "[...]" + path[-half:]
        
        # Apply the cut [...] only for the visual UI
        formatted_sources = "<br>".join([f"{i+1}. {elide_html_path(p)}" for i, p in enumerate(unique_source_dirs)])
        self.ui.source_label.setText(f"Source:<br><span style='font-size:8pt; color:#aaaaaa;'>{formatted_sources}</span>")
        
        # Show the copy button now that we have a valid path!
        if hasattr(self, 'btn_copy_src'): 
            self.btn_copy_src.show()

        # Reading bitrait
        orig_audio_bitrate = self.get_audio_bitrate_from_mpd(all_mpds[0]) if all_mpds else 192
        self.current_orig_audio_bitrate = orig_audio_bitrate

        if hasattr(self.ui, 'combo_audio_bitrate'):
            self.ui.combo_audio_bitrate.blockSignals(True)
            self.ui.combo_audio_bitrate.clear()
            
            bitrates = [
                (320, "320 kbps (Best Quality)"),
                (256, "256 kbps (High Quality)"),
                (192, "192 kbps (Good Quality)"),
                (128, "128 kbps (Standard)"),
                (64, "64 kbps (Bad)"),
                (32, "32 kbps (Very bad)")
            ]
            
            self.ui.combo_audio_bitrate.addItem(f"{orig_audio_bitrate} kbps (Original)")
            
            # We add to the list only those that do not exceed the original (with a small margin)
            for val, text in bitrates:
                if val <= orig_audio_bitrate + 15: 
                    self.ui.combo_audio_bitrate.addItem(text)
            
            self.ui.combo_audio_bitrate.insertSeparator(self.ui.combo_audio_bitrate.count())
            self.ui.combo_audio_bitrate.addItem("⚙️ Custom Audio...")

            self.ui.combo_audio_bitrate.blockSignals(False)
        
        unique_resolutions = set()
        max_height = 0
        self.current_orig_bitrate = 0

        # Parsing session.mpd to find the original resolution and bitrate
        for mpd_path in all_mpds:
            try:
                with open(mpd_path, 'r', encoding='utf-8') as file:
                    content = file.read()

                    # Call our function to calculate the size and time
                    clip_full_path = os.path.dirname(mpd_path)
                    size_str, duration_str = self.get_clip_size_and_duration(clip_full_path, content)
                    
                    if hasattr(self.ui, 'label_size'):
                        self.ui.label_size.setText(f"Size: {size_str}")
                    if hasattr(self.ui, 'label_duration'):
                        self.ui.label_duration.setText(f"Time: {duration_str}")

                    #1. Trying to find FPS in an XML file (the fastest way)
                    fps_match = re.search(r'\bframeRate="(\d+)(?:/\d+)?"', content)
                    if fps_match:
                        self.current_orig_fps = int(fps_match.group(1))
                    else:
                        # 2. Call ffprobe and let it READ THE MPD FILE!
                        self.current_orig_fps = self.get_fps_from_mpd(mpd_path)
                        
                    #UPDATE YOUR LABEL
                    if hasattr(self.ui, 'label_fps'):
                        self.ui.label_fps.setText(f"FPS: {self.current_orig_fps}")
                    
                    height_match = re.search(r'\bheight="(\d+)"', content)
                    width_match = re.search(r'\bwidth="(\d+)"', content)
                    bandwidth_match = re.search(r'\bbandwidth="(\d+)"', content)
                    
                    if bandwidth_match:
                        # Converting bitrate from bytes to mb
                        self.current_orig_bitrate = int(bandwidth_match.group(1)) / 1000000
                    
                    if height_match and width_match:
                        h = int(height_match.group(1))
                        w = int(width_match.group(1))
                        unique_resolutions.add(f"{w}x{h}")
                        if h > max_height: max_height = h
            except: pass

        if unique_resolutions:
            res_text = ", ".join(sorted(list(unique_resolutions)))
            audio_kbps = getattr(self, 'current_orig_audio_bitrate', 192)
            
            # Keep only the resolution here
            self.ui.orig_res_label.setText(f"Original resolution: {res_text}")
            
            # Populate Video Bitrate independently (Removed the '~' symbol!)
            if hasattr(self.ui, 'label_vbitrate'):
                if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                    rounded_bitrate = int(round(self.current_orig_bitrate))
                    self.ui.label_vbitrate.setText(f"Video Bitrate: {rounded_bitrate} Mbps")
                else:
                    self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            
            # Populate Audio Bitrate independently
            if hasattr(self.ui, 'label_abitrate'):
                self.ui.label_abitrate.setText(f"Audio Bitrate: {audio_kbps} kbps")
                
        else:
            self.ui.orig_res_label.setText("Original resolution: Unknown")
            if hasattr(self.ui, 'label_vbitrate'): self.ui.label_vbitrate.setText("Video Bitrate: Unknown")
            if hasattr(self.ui, 'label_abitrate'): self.ui.label_abitrate.setText("Audio Bitrate: Unknown")
            max_height = 1080

        # Fill in the drop-down list of resolutions (cutting off those that are larger than the original)
        if hasattr(self.ui, 'combo_quality'):
            self.ui.combo_quality.clear()
            
            # Dynamic Original Title (eg: Original (Lossless, 1440p))
            if max_height > 0:
                self.ui.combo_quality.addItem(f"Original (Lossless, {max_height}p)")
            else:
                self.ui.combo_quality.addItem("Original (Lossless)")

            for preset_name, preset_height in self.all_qualities:
                if preset_height <= max_height:
                    self.ui.combo_quality.addItem(preset_name)
            
            self.ui.combo_quality.setCurrentIndex(0)
            self.ui.combo_quality.insertSeparator(self.ui.combo_quality.count())
            self.ui.combo_quality.addItem("🎯 Target File Size...")
            self.update_bitrate_options() # Calling a function to update bitrates
        
        if hasattr(self.ui, 'combo_fps'):
            self.ui.combo_fps.clear()
            
            # Take FPS from the clip
            fps_val = getattr(self, 'current_orig_fps', 60)
            
            if fps_val >= 60:
                self.ui.combo_fps.addItem(f"{fps_val} FPS (Original)")
                self.ui.combo_fps.addItem("30 FPS")
                self.ui.combo_fps.addItem("15 FPS")
            elif fps_val >= 30:
                self.ui.combo_fps.addItem(f"{fps_val} FPS (Original)")
                self.ui.combo_fps.addItem("15 FPS")
            else:
                self.ui.combo_fps.addItem(f"{fps_val} FPS (Original)")

            self.ui.combo_fps.insertSeparator(self.ui.combo_fps.count())
            self.ui.combo_fps.addItem("⚙️ Custom FPS...")

            self.ui.combo_fps.setCurrentIndex(0)
        else:
            print("ERROR: Widget combo_fps not found! Check objectName in Qt Designer.")
        
        # 2. RESTORE USER SELECTION (IF IT STILL EXISTS)
        if current_quality and hasattr(self.ui, 'combo_quality'):
            index = self.ui.combo_quality.findText(current_quality)
            if index >= 0: self.ui.combo_quality.setCurrentIndex(index)
            
        if current_fps and hasattr(self.ui, 'combo_fps'):
            index = self.ui.combo_fps.findText(current_fps)
            if index >= 0: self.ui.combo_fps.setCurrentIndex(index)
            
        if current_bitrate and hasattr(self.ui, 'combo_bitrate'):
            index = self.ui.combo_bitrate.findText(current_bitrate)
            if index >= 0: self.ui.combo_bitrate.setCurrentIndex(index)

        # Unlock start button safely
        if not getattr(self, '_is_rendering', False):
            self.ui.btn_start.setEnabled(True)

        self.ui.btn_start.setEnabled(True)
        self.update_final_setup()

        # --- PLAYER HEADER DATA ---
        game_item = self.ui.table_clips.item(selected_row, 0)
        game_name = game_item.text()
        game_icon = game_item.icon()
        
        clip_date = self.ui.table_clips.item(selected_row, 2).text()
        clip_time = self.ui.table_clips.item(selected_row, 3).text()
        
        # Updating our correct software panel
        if hasattr(self, 'custom_text_label'):
            header_html = f"<b>{game_name}</b> <span style='color: #888;'>&nbsp;&nbsp;•&nbsp;&nbsp; {clip_date} &nbsp;&nbsp;•&nbsp;&nbsp; {clip_time}</span>"
            self.custom_text_label.setText(header_html)
            
        if hasattr(self, 'custom_icon_label'):
            self.custom_icon_label.setPixmap(game_icon.pixmap(24, 24))

        # Automatically load and play the new clip. This overwrites the stuck frame of the previous clip!
        self.generate_and_play_preview()
        
    
    def update_bitrate_options(self):
        """ Refreshes lists, applies FPS math visually, and freezes settings if Original is selected. """
        if not hasattr(self.ui, 'combo_bitrate') or not hasattr(self.ui, 'combo_quality'):
            return 
            
        # --- SAVE CURRENT SELECTION (so it doesn't get lost when changing FPS) ---
        current_selection = self.ui.combo_bitrate.currentText()
        selected_level = current_selection.split(" - ")[0] if " - " in current_selection else ""

        self.ui.combo_bitrate.blockSignals(True)
        self.ui.combo_bitrate.clear()
        quality_text = self.ui.combo_quality.currentText()

        if "Original" in quality_text:
            if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                self.ui.combo_bitrate.addItem(f"~{int(self.current_orig_bitrate)} Mbps (Original Copy)")
            else:
                self.ui.combo_bitrate.addItem("Original Bitrate (Copy)")
                
            self.ui.combo_bitrate.setEnabled(False) 
            if hasattr(self.ui, 'combo_fps'):
                self.ui.combo_fps.setCurrentIndex(0) 
                self.ui.combo_fps.setEnabled(False)
            if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(False)
            if hasattr(self.ui, 'combo_encoder'): self.ui.combo_encoder.setEnabled(False)
            self.ui.combo_bitrate.blockSignals(False)
            self.update_final_setup()
            return

        self.ui.combo_bitrate.setEnabled(True) 
        if hasattr(self.ui, 'combo_fps'): self.ui.combo_fps.setEnabled(True)
        if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(True)
        if hasattr(self.ui, 'combo_encoder'): self.ui.combo_encoder.setEnabled(True)
        
        match = re.search(r'^(\d+)p', quality_text)
        if not match: 
            self.ui.combo_bitrate.blockSignals(False)
            return
            
        res_key = f"{match.group(1)}p"
        added_any = False
        
        # Calculating the FPS Multiplier for Visuals
        fps_multiplier = 1.0
        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        orig_fps = getattr(self, 'current_orig_fps', 60)
        
        if "Custom" in fps_text and hasattr(self, 'input_custom_fps'):
            try: selected_fps = int(self.input_custom_fps.text())
            except: selected_fps = orig_fps
        else:
            try: selected_fps = int(re.search(r'(\d+)', fps_text).group(1))
            except: selected_fps = orig_fps
            
        if selected_fps < orig_fps and orig_fps > 0:
            fps_multiplier = selected_fps / orig_fps

        for quality_level in ["Ultra", "High", "Medium", "Low"]:
            if res_key in self.steam_bitrate_presets.get(quality_level, {}):
                preset_bitrate = self.steam_bitrate_presets[quality_level][res_key]
                
                if getattr(self, 'current_orig_bitrate', 0) == 0 or preset_bitrate <= (self.current_orig_bitrate + 5):
                    # We're multiplying right here just for the sake of appearance in the ComboBox!
                    scaled_bitrate = preset_bitrate * fps_multiplier
                    
                    display_val = f"{scaled_bitrate:.1f}".rstrip('0').rstrip('.') if scaled_bitrate % 1 != 0 else str(int(scaled_bitrate))
                    
                    self.ui.combo_bitrate.addItem(f"{quality_level} - {display_val} Mbps")
                    added_any = True
        
        if not added_any and res_key in self.steam_bitrate_presets["Low"]:
            lowest_bitrate = self.steam_bitrate_presets["Low"][res_key] * fps_multiplier
            display_val = f"{lowest_bitrate:.1f}".rstrip('0').rstrip('.') if lowest_bitrate % 1 != 0 else str(int(lowest_bitrate))
            self.ui.combo_bitrate.addItem(f"Low - {display_val} Mbps")
        
        self.ui.combo_bitrate.insertSeparator(self.ui.combo_bitrate.count())
        self.ui.combo_bitrate.addItem("⚙️ Custom Bitrate...")
        
        # --- RESTORING SELECTION ---
        if selected_level:
            for i in range(self.ui.combo_bitrate.count()):
                if self.ui.combo_bitrate.itemText(i).startswith(selected_level):
                    self.ui.combo_bitrate.setCurrentIndex(i)
                    break

        self.ui.combo_bitrate.blockSignals(False)
        self.update_final_setup()
    
    def refresh_slider_if_needed(self):
        """ Updates the monkeymeter if the user has switched FPS """
        if hasattr(self.ui, 'size_slider') and self.ui.size_slider.isVisible():
            self.on_slider_moved(self.ui.size_slider.value())

        
    def update_final_setup(self):
        """Dynamically updates the Detailed Summary, Size, and Save Path."""
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            if hasattr(self.ui, 'label_short_summary'):
                if hasattr(self, 'reset_bottom_summary'): self.reset_bottom_summary()
            if hasattr(self.ui, 'label_detailed_summary'):
                self.ui.label_detailed_summary.setText("Waiting for clip selection...")
            if hasattr(self.ui, 'label_status'):
                self.ui.label_status.setText("Ready")
                
            if hasattr(self, 'btn_copy_loc'): self.btn_copy_loc.hide()
            return

        #1: Read everything from the UI
        quality = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else ""
        fps = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else ""
        bitrate_text = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else ""
        codec_raw = self.ui.combo_codec.currentText() if hasattr(self.ui, 'combo_codec') else ""
        codec = codec_raw.split()[0] if codec_raw else "Unknown"
        encoder = self.ui.combo_encoder.currentText() if hasattr(self.ui, 'combo_encoder') else ""

        audio_only = self.ui.check_audio_only.isChecked() if hasattr(self.ui, 'check_audio_only') else False
        mute_audio = self.ui.check_mute_audio.isChecked() if hasattr(self.ui, 'check_mute_audio') else False
        audio_format = self.ui.combo_audio_format.currentText() if hasattr(self.ui, 'combo_audio_format') else "AAC"
        audio_bitrate = self.ui.combo_audio_bitrate.currentText() if hasattr(self.ui, 'combo_audio_bitrate') else "192 kbps"

        # 2. Calculate the file extension
        ext = ".mp3" if (audio_only and audio_format == "MP3") else (".aac" if audio_only else ".mp4")

        # 3. OVERWRITE PROTECTION 
        save_dir = self.custom_destination if self.custom_destination else get_save_directory()
        base_filename = self.ui.input_filename.text().strip() if hasattr(self.ui, 'input_filename') else "rendered"
        
        for e in [".mp4", ".mp3", ".aac"]:
            if base_filename.lower().endswith(e): base_filename = base_filename[:-4]

        test_path = os.path.join(save_dir, f"{base_filename}{ext}")
        counter = 1
        while os.path.exists(test_path):
            test_path = os.path.join(save_dir, f"{base_filename}_{counter}{ext}")
            counter += 1
            
        full_path = test_path
        final_filename = os.path.basename(full_path)
        self.current_output_file = full_path

        if hasattr(self.ui, 'label_location'):
            self.ui.label_location.setText(f"Output: {full_path}")
            
        if hasattr(self, 'btn_copy_loc') and full_path:
            self.btn_copy_loc.show()
            

        # 4. Collecting texts & Smart Math
        duration = self.get_effective_duration() # Use trimmed duration for math!
        
        # Format the beautiful "Clip time: ✂️ 00:10 - 01:50" string
        if hasattr(self, 'custom_timeline') and self.custom_timeline.is_trim_mode:
            start_s = self.custom_timeline.trim_start_ms / 1000.0
            end_s = self.custom_timeline.trim_end_ms / 1000.0
            
            s_h = int(start_s // 3600)
            s_m = int((start_s % 3600) // 60)
            s_s = int(start_s % 60)
            
            e_h = int(end_s // 3600)
            e_m = int((end_s % 3600) // 60)
            e_s = int(end_s % 60)
            
            if s_h > 0 or e_h > 0:
                duration_str = f"✂️ {s_h:02d}:{s_m:02d}:{s_s:02d} - {e_h:02d}:{e_m:02d}:{e_s:02d}"
            else:
                duration_str = f"✂️ {s_m:02d}:{s_s:02d} - {e_m:02d}:{e_s:02d}"
        else:
            duration_str = getattr(self, 'current_clip_duration_str', "Unknown")
        
        # Calculating the size using the EFFECTIVE duration
        size_str = "Unknown"
        fps_multiplier = 1.0
        if fps:
            if "Custom" in fps and hasattr(self, 'input_custom_fps'):
                try: selected_fps = int(self.input_custom_fps.text())
                except: selected_fps = getattr(self, 'current_orig_fps', 60)
            else:
                try: selected_fps = int(re.search(r'(\d+)', fps).group(1))
                except: selected_fps = getattr(self, 'current_orig_fps', 60)
                
            orig_fps = getattr(self, 'current_orig_fps', 60)
            if selected_fps < orig_fps and orig_fps > 0:
                fps_multiplier = selected_fps / orig_fps

        if duration > 0:
            if "Target File Size" in quality:
                if hasattr(self, 'dynamic_stops') and hasattr(self.ui, 'size_slider'):
                    target_mb = self.dynamic_stops[self.ui.size_slider.value()]
                    size_str = f"~{target_mb / 1024:.2f} GB (Target)" if target_mb >= 1000 else f"~{target_mb} MB (Target)"
            elif "Original" in bitrate_text:
                if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                    orig_total_bitrate = (self.current_orig_bitrate * fps_multiplier) + 0.19 
                    size_mb = (orig_total_bitrate * duration) / 8 
                    size_str = f"Same as original (~{size_mb / 1024:.2f} GB)" if size_mb >= 1000 else f"Same as original (~{size_mb:.1f} MB)"
                else:
                    size_str = "Same as original"
            else:
                match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
                if match:
                    video_bitrate = float(match.group(1)) 
                    audio_bitrate_val = float(audio_bitrate.split(' ')[0]) / 1000 if ' ' in audio_bitrate else 0.19
                    if mute_audio: audio_bitrate_val = 0
                    total_bitrate = video_bitrate + audio_bitrate_val
                    size_mb = (total_bitrate * duration) / 8 
                    size_str = f"~{size_mb / 1024:.2f} GB" if size_mb >= 1000 else f"~{size_mb:.1f} MB"

        if audio_only:
            sound_info = f"{audio_format} {audio_bitrate.split(' ')[0]} kbps"
            other_info = ">> EXTRACT AUDIO ONLY (NO VIDEO)"
        elif mute_audio:
            sound_info = "None"
            other_info = ">> NO SOUND (MUTED)"
        else:
            sound_info = audio_bitrate
            other_info = "Normal Render"

        # 5. Smart Detailed Summary in Export Settings
        
        # --- CLEAN PARSING FOR UI DISPLAY ---
        
        # Parse Video Bitrate for UI
        video_bitrate_display = "Unknown"
        orig_v_bitrate = getattr(self, 'current_orig_bitrate', 10.0)

        if "Target File Size" in quality:
            val_mbps = getattr(self, 'custom_target_bitrate', 1500) / 1000
            scale_h = getattr(self, 'custom_target_height', -1)
            res_str = f"Auto: {scale_h}p" if scale_h > 0 else "Original"
            clean_mbps = int(round(val_mbps))
            video_bitrate_display = f"{clean_mbps} Mbps ({res_str})"
        elif "Custom" in bitrate_text:
            try:
                val = float(self.input_custom_vbitrate.text().replace(',', '.'))
                val = max(0.1, min(val, orig_v_bitrate))
                # Multiply by the FPS drop
                video_bitrate_display = f"⚙️ {val * fps_multiplier:.1f} Mbps"
            except:
                video_bitrate_display = f"{orig_v_bitrate * fps_multiplier:.1f} Mbps"
        elif "Original" in bitrate_text:
            video_bitrate_display = f"{orig_v_bitrate * fps_multiplier:.1f} Mbps"
        else:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match: 
                video_bitrate_display = f"{float(match.group(1)):.1f} Mbps"

        # Parse Audio Bitrate for UI
        orig_a_bitrate = getattr(self, 'current_orig_audio_bitrate', 192)
        if "Custom" in audio_bitrate:
            try:
                val = int(self.input_custom_abitrate.text())
                val = max(1, min(val, orig_a_bitrate))
                audio_bitrate_clean = f"⚙️ {val} kbps"
            except:
                audio_bitrate_clean = f"{orig_a_bitrate} kbps"
        else:
            # Clean up "(Original Copy)" just "192 kbps"
            audio_bitrate_clean = audio_bitrate.split('(')[0].strip() if audio_bitrate else "192 kbps"

        # Parse FPS for UI (includes the word "FPS" inside)
        orig_fps = getattr(self, 'current_orig_fps', 60)
        if "Custom" in fps:
            max_allowed = min(60, orig_fps)
            try:
                val = int(self.input_custom_fps.text())
                val = max(1, min(val, max_allowed))
                fps_display = f"⚙️ {val} FPS"
            except:
                fps_display = f"{max_allowed} FPS"
        else:
            val_str = fps.split(' ')[0] if fps else "Unknown"
            fps_display = f"{val_str} FPS" if val_str != "Unknown" else "Unknown"

        # Clean strings
        q_clean = quality.split('(')[0].strip() if quality else "Unknown"
        enc_clean = encoder if encoder else "Unknown"

        # Construct the final detailed text block 
        if audio_only:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Format: {audio_format}\n"
                f"Sound: {audio_format}, {audio_bitrate_clean}\n"
                f"Other settings: >> EXTRACT AUDIO ONLY (NO VIDEO)\n"
                f"Est. File Size: {size_str}"
            )
        elif mute_audio:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Quality: {q_clean}\n"
                f"FPS: {fps_display}\n"
                f"Bitrate: {video_bitrate_display}\n"
                f"Codec: {codec}\n"
                f"Encoder: {enc_clean}\n"
                f"Other settings: >> NO SOUND (MUTED)\n"
                f"Est. File Size: {size_str}"
            )
        else:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Quality: {q_clean}\n"
                f"FPS: {fps_display}\n"
                f"Bitrate: {video_bitrate_display}\n"
                f"Codec: {codec}\n"
                f"Encoder: {enc_clean}\n"
                f"Sound: {audio_format}, {audio_bitrate_clean}\n"
                f"Other settings: Normal Render\n"
                f"Est. File Size: {size_str}"
            )
            
        if hasattr(self.ui, 'label_detailed_summary'):
            self.ui.label_detailed_summary.setText(detailed_text)

        # 6. Short Summary ABOVE Ready 
        q_word = quality.split()[0] if quality.split() else "Unknown"
        
        game_name = "Steam Clip"
        if hasattr(self.ui, 'table_clips') and self.ui.table_clips.currentRow() >= 0:
            game_name = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).text().strip()
            
        game_icon = getattr(self, 'current_game_icon', '')
        unknown_icon_path = get_resource_path("unknown_icon.png")
        target_icon = game_icon if (game_icon and os.path.exists(game_icon)) else unknown_icon_path

        if audio_only:
            text_part = f"<span style='font-size: 14px;'><b>{game_name} &nbsp;•&nbsp; AUDIO ONLY: {audio_format} {audio_bitrate_clean}</b></span>"
        elif mute_audio:
            text_part = f"<span style='font-size: 14px;'><b>{game_name} &nbsp;•&nbsp; {q_word}, {fps_display} &nbsp;•&nbsp; {video_bitrate_display} &nbsp;•&nbsp; {codec} (Muted)</b></span>"
        else:
            text_part = f"<span style='font-size: 14px;'><b>{game_name} &nbsp;•&nbsp; {q_word}, {fps_display} &nbsp;•&nbsp; {video_bitrate_display} &nbsp;•&nbsp; {codec}</b></span>"
            
        # GIVE ORDER TO OUR NEW CSS WIDGETS
        if hasattr(self, 'bottom_text_label'):
            self.bottom_text_label.setText(text_part)
            icon_css = target_icon.replace('\\', '/')
            self.bottom_icon_label.setStyleSheet(f"image: url('{icon_css}'); background: transparent; border: none;")
            
            # We are updating the TOP panel of the player!
            if hasattr(self, 'custom_text_label') and hasattr(self, 'custom_icon_label'):
                self.custom_icon_label.setStyleSheet(f"image: url('{icon_css}'); background: transparent; border: none;")
                

            # CONNECTING THE MAIN BOSS: Updating the CENTRAL plug!
            if hasattr(self, 'place_logo') and hasattr(self, 'place_text'):
                self.place_logo.setStyleSheet(f"image: url('{icon_css}'); background: transparent; border: none;")
                self.place_text.setText(f"Ready to play: {game_name}") 
                self.place_text.setStyleSheet("color: #a0a0a0; font-size: 15px; font-weight: bold; margin-top: 15px;")
            
        if hasattr(self.ui, 'label_status'):
            self.ui.label_status.setText("Ready")
    
    def validate_custom_fps(self, text):
        """ Validates FPS input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_fps.hide()
            self.update_final_setup()
            return
            
        try:
            val = int(text)
            orig_fps = getattr(self, 'current_orig_fps', 60)
            max_allowed = min(60, orig_fps)
            
            if val > max_allowed:
                self.warn_fps.setToolTip(f"The maximum FPS of the original video is {max_allowed} FPS. Higher values will be capped!")
                self.warn_fps.show()
            elif val < 1:
                self.warn_fps.setToolTip("FPS cannot be less than 1.")
                self.warn_fps.show()
            else:
                self.warn_fps.hide()
        except:
            self.warn_fps.hide()
            
        self.update_final_setup() # Live UI update

    def validate_custom_vbitrate(self, text):
        """ Validates video bitrate input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_vbitrate.hide()
            self.update_final_setup()
            return
            
        try:
            val = float(text.replace(',', '.'))
            orig_v_bitrate = getattr(self, 'current_orig_bitrate', 10.0)
            
            if val > orig_v_bitrate:
                self.warn_vbitrate.setToolTip(f"The maximum bitrate of the original video is {orig_v_bitrate:.1f} Mbps. Higher values will be capped!")
                self.warn_vbitrate.show()
            elif val < 0.1:
                self.warn_vbitrate.setToolTip("Video bitrate cannot be less than 0.1 Mbps.")
                self.warn_vbitrate.show()
            else:
                self.warn_vbitrate.hide()
        except:
            self.warn_vbitrate.hide()
            
        self.update_final_setup() # Live UI update

    def validate_custom_abitrate(self, text):
        """ Validates audio bitrate input and shows warning icon if boundaries are exceeded """
        if not text.strip():
            self.warn_abitrate.hide()
            self.update_final_setup()
            return
            
        try:
            val = int(text)
            orig_a_bitrate = getattr(self, 'current_orig_audio_bitrate', 192)
            
            if val > orig_a_bitrate:
                self.warn_abitrate.setToolTip(f"The maximum audio bitrate of the original file is {orig_a_bitrate} kbps. Higher values will be capped!")
                self.warn_abitrate.show()
            elif val < 1:
                self.warn_abitrate.setToolTip("Audio bitrate cannot be less than 1 kbps.")
                self.warn_abitrate.show()
            else:
                self.warn_abitrate.hide()
        except:
            self.warn_abitrate.hide()
            
        self.update_final_setup() # Live UI update

    def start_render_thread(self):
        """ Prepares parameters and starts the background rendering thread """
        if getattr(self, '_is_rendering', False):
            return
        
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            QMessageBox.warning(self.ui, "Error", "Please select a clip from the list first!")
            return
            
        clip_name = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).data(Qt.UserRole)
        all_mpds = self.get_all_mpd_paths(clip_name)
        
        if not all_mpds:
            QMessageBox.warning(self.ui, "Error", "session.mpd files not found inside this clip!")
            return

        save_dir = self.custom_destination if self.custom_destination else get_save_directory()
        
        # We take the protected file name that we generated in update_final_setup
        output_file = getattr(self, 'current_output_file', "")
        if not output_file: 
            return # Empty Path Protection
            
        ffmpeg_exe = os.path.join(_bin_dir, "ffmpeg.exe")
        if not os.path.exists(ffmpeg_exe):
            QMessageBox.critical(self.ui, "Error", "ffmpeg.exe not found!")
            return

        # Read the basic video settings
        quality_text = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else "Original"
        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        bitrate_text = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else "Original"
        
        # Get the codec and encoder
        selected_encoder = self.ui.combo_encoder.currentData(Qt.UserRole) if hasattr(self.ui, 'combo_encoder') else "libx264"
        if hasattr(self.ui, 'combo_codec') and "H.265" in self.ui.combo_codec.currentText():
            selected_encoder = selected_encoder.replace("h264", "hevc").replace("libx264", "libx265")

        # Read the audio settings
        audio_only = self.ui.check_audio_only.isChecked() if hasattr(self.ui, 'check_audio_only') else False
        mute_audio = self.ui.check_mute_audio.isChecked() if hasattr(self.ui, 'check_mute_audio') else False
        audio_format = self.ui.combo_audio_format.currentText() if hasattr(self.ui, 'combo_audio_format') else "AAC"

        # --- SMART TRIM EXTRACTION ---
        trim_start_sec = -1.0
        trim_duration_sec = -1.0
        
        if hasattr(self, 'custom_timeline') and self.custom_timeline.is_trim_mode:
            trim_start_sec = self.custom_timeline.trim_start_ms / 1000.0
            trim_duration_sec = (self.custom_timeline.trim_end_ms - self.custom_timeline.trim_start_ms) / 1000.0
            logging.info(f"TRIM MODE ACTIVE: Start at {trim_start_sec}s, Duration: {trim_duration_sec}s")
        
        # --- SMART PARSING & CLAMPING ---
        #1: Read and Protect FPS
        fps_multiplier = 1.0
        orig_fps = getattr(self, 'current_orig_fps', 60)
        max_allowed_fps = min(60, orig_fps) # No higher than 60, no higher than the original!
        
        if "Custom" in fps_text:
            try:
                val = int(self.input_custom_fps.text().strip())
                val = max(1, min(val, max_allowed_fps)) 
                fps_text = f"{val} FPS"
                fps_multiplier = val / orig_fps if orig_fps > 0 else 1.0
            except: fps_text = f"{max_allowed_fps} FPS" # Foolproof protection
        else:
            try:
                selected_fps = int(re.search(r'(\d+)', fps_text).group(1))
                fps_multiplier = selected_fps / orig_fps if orig_fps > 0 else 1.0
            except: pass

        #2: Read and Protect Video Bitrate
        video_bitrate = "12M"
        orig_v_bitrate = getattr(self, 'current_orig_bitrate', 10.0)
        target_scale_h = -1 

        if "Target File Size" in quality_text:
            video_bitrate = f"{getattr(self, 'custom_target_bitrate', 1500)}k"
            target_scale_h = getattr(self, 'custom_target_height', -1)
        elif "Custom" in bitrate_text:
            try:
                val_text = self.input_custom_vbitrate.text().replace(',', '.')
                val = float(val_text.strip())
                val = max(0.1, min(val, orig_v_bitrate)) 
                final_bitrate = int(val * fps_multiplier * 1000)
                if final_bitrate < 100: final_bitrate = 100
                video_bitrate = f"{final_bitrate}k"
            except: 
                final_bitrate = int(orig_v_bitrate * fps_multiplier * 1000)
                if final_bitrate < 100: final_bitrate = 100
                video_bitrate = f"{final_bitrate}k"
        elif "Original" not in bitrate_text:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match:
                base_bitrate = float(match.group(1))
                final_bitrate = int(base_bitrate * 1000)
                if final_bitrate < 100: final_bitrate = 100 
                video_bitrate = f"{final_bitrate}k"

        #3: Read and Protect Audio Bitrate
        audio_bitrate_kbps = "192k"
        orig_a_bitrate = getattr(self, 'current_orig_audio_bitrate', 192)
        
        if "Custom" in self.ui.combo_audio_bitrate.currentText():
            try:
                val = int(self.input_custom_abitrate.text().strip())
                val = max(1, min(val, orig_a_bitrate))
                audio_bitrate_kbps = f"{val}k"
            except: audio_bitrate_kbps = f"{orig_a_bitrate}k"
        elif self.ui.combo_audio_bitrate.currentText():
            audio_bitrate_kbps = self.ui.combo_audio_bitrate.currentText().split(' ')[0] + "k"

        # Turn interface buttons on/off
        self.ui.btn_start.setEnabled(False) 
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(True)
        if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(True) 

        self.set_status("Initializing...")
        logging.info(f"--- RENDER STARTED ---")

        # --- LOCK THE RENDER ENGINE ---
        self._is_rendering = True

        logging.info(f"Source: {clip_name}")
        logging.info(f"Saving in: {output_file}")
        logging.info(f"Settings: Quality={quality_text}, FPS={fps_text}, Bitrate={video_bitrate}, Codec={selected_encoder}, AudioOnly={audio_only}, Muted={mute_audio}")

        try:
            self.thread = RenderThread(all_mpds, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate, fps_text, audio_only, mute_audio, audio_format, audio_bitrate_kbps, target_scale_h, trim_start_sec, trim_duration_sec)
            self.thread.progress_signal.connect(self.set_status)
            self.thread.finished_signal.connect(self.on_render_finished)
            self.thread.start()
        except Exception as e:
            logging.error(f"Thread Start Error: {e}")
            self.set_status("Error!")
            self.ui.btn_start.setEnabled(True)
            if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
            if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(False)
            QMessageBox.critical(self.ui, "Thread Error", f"Could not start render:\n{e}")
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
    def on_quality_mode_changed(self, text):
        """ Hides or shows the slider and target inputs depending on the mode """
        is_target_mode = "Target File Size" in text
        
        if hasattr(self.ui, 'size_slider'):
            self.ui.size_slider.setVisible(is_target_mode)
            
        if hasattr(self, 'size_container'):
            self.size_container.setVisible(is_target_mode)
            
        if is_target_mode:
            self.setup_dynamic_slider()

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
            
    def on_custom_size_changed(self, text):
        """ Live updates when typing a custom MB value with idiot-proof protection """
        if not text.strip():
            self.warn_size.hide()
            return
            
        try:
            target_mb = int(text)
            
            # --- Use EFFECTIVE duration for correct calculation! ---
            duration = self.get_effective_duration()
            orig_bitrate = getattr(self, 'current_orig_bitrate', 10)
            orig_mb = int((orig_bitrate * duration) / 8)
            if orig_mb < 1: orig_mb = 1
            
            # Idiot-proof protection lol
            if target_mb < 1:
                self.warn_size.setToolTip("Oops! Minimum size is 1 MB, otherwise the video will turn to dust")
                self.warn_size.show()
            elif target_mb > orig_mb:
                self.warn_size.setToolTip(f"No need to inflate the file! Maximum for this clip: {orig_mb} MB.\n The program will automatically cap the value to this limit.")
                self.warn_size.show()
            else:
                self.warn_size.hide()
                
            self.calculate_strict_target(target_mb, is_custom=True)
        except: 
            self.warn_size.hide()

    def setup_dynamic_slider(self):
        """ Generates strict slider steps and adds Lossless & Custom modes """
        duration = self.get_effective_duration() 
        if duration <= 0: return
            
        # Dynamically calculate the maximum MB for the current trimmed duration
        orig_mb = (getattr(self, 'current_orig_bitrate', 10) * duration) / 8 
        if orig_mb < 1: orig_mb = 1
        
        anchors = [10, 25, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, 4000, 5000]
        self.dynamic_stops = [size for size in anchors if size < orig_mb]
        
        self.dynamic_stops.append(int(orig_mb)) # Lossless
        self.dynamic_stops.append(-1) # Custom
        
        self.ui.size_slider.blockSignals(True)
        self.ui.size_slider.setMinimum(0)
        self.ui.size_slider.setMaximum(len(self.dynamic_stops) - 1)
        # Always snap to the new Lossless value when the trim changes
        self.ui.size_slider.setValue(len(self.dynamic_stops) - 2) 
        self.ui.size_slider.blockSignals(False)
        
        self.on_slider_moved(self.ui.size_slider.value())

    def calculate_strict_target(self, target_mb, is_lossless=False, is_custom=False):
        """Read the controls, run the bitrate math, show the result."""
        duration = self.get_effective_duration()

        # --- read inputs from the UI ---
        orig_video_mbps = getattr(self, 'current_orig_bitrate', 10)

        audio_text = self.ui.combo_audio_bitrate.currentText() if hasattr(self.ui, 'combo_audio_bitrate') else "192 kbps"
        if hasattr(self.ui, 'check_mute_audio') and self.ui.check_mute_audio.isChecked():
            audio_kbps = 0
        elif "Custom" in audio_text and hasattr(self, 'input_custom_abitrate'):
            try:
                audio_kbps = int(self.input_custom_abitrate.text())
            except ValueError:
                audio_kbps = getattr(self, 'current_orig_audio_bitrate', 192)
        else:
            match = re.search(r'(\d+)', audio_text)
            audio_kbps = int(match.group(1)) if match else 192

        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        if "Custom" in fps_text and hasattr(self, 'input_custom_fps'):
            try:
                fps = int(self.input_custom_fps.text())
            except ValueError:
                fps = getattr(self, 'current_orig_fps', 60)
        else:
            try:
                fps = int(re.search(r'(\d+)', fps_text).group(1))
            except (AttributeError, ValueError):
                fps = getattr(self, 'current_orig_fps', 60)

        # --- run the pure math ---
        plan = bitrate.plan_bitrate(duration, orig_video_mbps, target_mb, audio_kbps, fps,
                                    is_lossless=is_lossless, is_custom=is_custom)
        if plan is None:
            return

        # --- show the result ---
        self.custom_target_height = plan.height
        self.custom_target_bitrate = plan.video_kbps
        custom_tag = "⚙️ Custom " if is_custom else ""
        self.ui.label_target_size.setText(
            f"Target: <b>{custom_tag}{plan.target_mb} MB</b> | Safe Bitrate: {plan.video_kbps} kbps<br>"
            f"Quality: <span style='color:{plan.color}'><b>{plan.label}</b></span>"
        )
        self.update_final_setup()

    def on_slider_moved(self, index):
        """ Handles slider logic and reveals custom input if needed """
        target_mb = self.dynamic_stops[index]
        
        if target_mb == -1:
            self.input_custom_size.show()
            if self.input_custom_size.text():
                self.on_custom_size_changed(self.input_custom_size.text())
            else:
                self.ui.label_target_size.setText("Target: <b>--- MB</b> (Type specific size)<br>Quality: <span style='color:#aaaaaa'><b>Waiting for input...</b></span>")
        else:
            self.input_custom_size.hide()
            if hasattr(self, 'warn_size'): self.warn_size.hide() 
            self.calculate_strict_target(target_mb, is_lossless=(index == len(self.dynamic_stops) - 2))


    def cancel_render(self):
        """ Cancel Button Handler """
        logging.warning("User cancelled rendering (Cancel)")
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.set_status("Cancelling... Please wait")
            if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
            if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(False)
            self.thread.cancel() # Send a cancel signal to the thread

    def toggle_pause(self):
        """ Pause button handler """
        logging.info("User Paused/Resumed rendering")
        if hasattr(self, 'thread') and self.thread.isRunning():
            is_paused = self.thread.toggle_pause() # Send a pause signal to the thread
            
            # Change the button text depending on the status
            if is_paused:
                if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setText("Resume")
                self.set_status("Paused...")
            else:
                if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setText("Pause")
                self.set_status("Process...")

    def on_render_finished(self, success, error_msg, output_file):
        """ Fires when the background rendering thread exits. """
        self._is_rendering = False
        
        # Unlocking the UI
        if hasattr(self.ui, 'btn_start'): self.ui.btn_start.setEnabled(True)
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'): 
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.setText("Pause")
            
        self.update_final_setup()
        
        # Show the result to the user
        if success:
            logging.info("=== RENDER SUCCESS ===")
            
            # 1. Set to 100% before the window appears
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setValue(100)
                self.ui.progress_render.setFormat("100%")
            if hasattr(self.ui, 'label_status'):
                self.ui.label_status.setText("Success!")
            
            # A CUSTOM SUCCESS WINDOW
            msg_box = QMessageBox(self.ui)
            msg_box.setWindowTitle("Success!")
            msg_box.setText(f"Clip successfully saved to:\n{output_file}")
            msg_box.setIcon(QMessageBox.Information)
            
            btn_folder = msg_box.addButton("Open Folder", QMessageBox.ActionRole)
            btn_play = msg_box.addButton("Play Video", QMessageBox.ActionRole)
            btn_ok = msg_box.addButton(QMessageBox.Ok)
            
            # The code pauses here. The user sees 100% in the background and a window.
            msg_box.exec()
            
            # Handling User Selection
            if msg_box.clickedButton() == btn_folder:
                self.open_rendered_folder(output_file)
                
            elif msg_box.clickedButton() == btn_play:
                import os
                file_path = os.path.abspath(output_file)
                os.startfile(file_path)

            # 2. RESET PROGRESS ONLY AFTER CLOSING THE WINDOW
            if hasattr(self.ui, 'label_status'):
                self.ui.label_status.setText("Ready")
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setValue(0)
                self.ui.progress_render.setFormat("0%")
                
        elif "cancelled by user" in error_msg.lower():
            logging.warning("=== RENDER CANCELED ===")
            if hasattr(self.ui, 'label_status'): self.ui.label_status.setText("Cancelled")
            QMessageBox.information(self.ui, "Cancelled", "Render was cancelled.")
            
            # Reset to Ready after closing the cancellation window
            if hasattr(self.ui, 'label_status'): self.ui.label_status.setText("Ready")
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setValue(0)
                self.ui.progress_render.setFormat("0%")
            
        else:
            import os
            logging.error(f"=== RENDER ERROR === \n{error_msg}")
            if hasattr(self.ui, 'label_status'): self.ui.label_status.setText("Error!") 
            
            # --- STEEMPEG CUSTOM ERROR WINDOW ---
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton

            from PySide6.QtGui import QPixmap

            dialog = QDialog(self.ui)
            dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
            # Make the window wider so that the image and logs fit comfortably.
            dialog.setFixedSize(780, 420)
            
            dialog.setStyleSheet("""
                QDialog { 
                    background-color: #202020; 
                    border: 1px solid #444444; 
                    border-radius: 8px; 
                }
                QLabel#ErrorTitle { 
                    color: #ff4444; 
                    font-size: 18px; 
                    font-weight: bold; 
                }
                QLabel#ErrorDesc { 
                    color: #cccccc; 
                    font-size: 13px; 
                }
                QTextEdit { 
                    background-color: #141414; 
                    color: #ff8888; 
                    border: 1px solid #333333; 
                    border-radius: 6px; 
                    padding: 8px; 
                    font-family: Consolas, monospace; 
                    font-size: 11px; 
                }
                
                QScrollBar:vertical { border: none; background: #141414; width: 12px; margin: 2px; border-radius: 4px; }
                QScrollBar::handle:vertical { background: #444444; min-height: 20px; border-radius: 4px; }
                QScrollBar::handle:vertical:hover { background: #666666; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
                
                QPushButton { 
                    background-color: #333333; 
                    color: white; 
                    border: 1px solid #555555; 
                    border-radius: 16px; 
                    padding: 6px 20px; 
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
                
                QPushButton#LogBtn { 
                    background-color: #4a2525; 
                    border: 1px solid #7a3535; 
                }
                QPushButton#LogBtn:hover { 
                    background-color: #6a2e2e; 
                    border: 1px solid #9a4545; 
                }
            """)
            
            # --- MAIN LAYER (Horizontal) ---
            main_layout = QHBoxLayout(dialog)
            main_layout.setContentsMargins(20, 20, 20, 20)
            main_layout.setSpacing(20)

            # --- LEFT SIDE: Sad Image ---
            pic_label = QLabel()
            pixmap = QPixmap(get_resource_path("saderror.png"))
            
            if not pixmap.isNull():
                # Shrinking a huge image to 240 pixels in width with beautiful anti-aliasing
                scaled_pixmap = pixmap.scaledToWidth(240, Qt.TransformationMode.SmoothTransformation)
                pic_label.setPixmap(scaled_pixmap)
            else:
                pic_label.setText("Sad pic\nnot found =(")
                pic_label.setStyleSheet("color: gray; font-size: 12px;")
                
            pic_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            main_layout.addWidget(pic_label)

            # --- RIGHT SIDE: Text, Logs, and Buttons ---
            content_layout = QVBoxLayout()
            content_layout.setSpacing(15)

            # 1. HEADER (without the crooked icon—text only)
            title_layout = QVBoxLayout()
            title_layout.setSpacing(2)

            title_lbl = QLabel("Render Failed")
            title_lbl.setObjectName("ErrorTitle")
            desc_lbl = QLabel("FFmpeg encountered a critical error during processing.")
            desc_lbl.setObjectName("ErrorDesc")
            
            title_layout.addWidget(title_lbl)
            title_layout.addWidget(desc_lbl)
            content_layout.addLayout(title_layout)

            # 2. LOGS FIELD
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            short_error = error_msg[-2000:] if len(error_msg) > 2000 else error_msg
            text_edit.setText(short_error)
            content_layout.addWidget(text_edit)

            # 3. Control Buttons
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            btn_log = QPushButton("📄 Open Log File")
            btn_log.setObjectName("LogBtn")
            btn_log.setCursor(Qt.CursorShape.PointingHandCursor)
            
            btn_ok = QPushButton("Close")
            btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
            
            btn_layout.addWidget(btn_log)
            btn_layout.addWidget(btn_ok)
            
            content_layout.addLayout(btn_layout)
            
           # Bringing Everything Together in the Main Window
            main_layout.addLayout(content_layout)
            
            def open_log_and_close():
                import subprocess
                import os
                if hasattr(self, 'current_log_file') and os.path.exists(self.current_log_file):
                    log_path = os.path.abspath(self.current_log_file)
                    subprocess.Popen(["notepad.exe", log_path])
                dialog.accept()
                
            btn_log.clicked.connect(open_log_and_close)
            btn_ok.clicked.connect(dialog.accept)

            dialog.exec()
            
            # --- RESTORING THE INTERFACE TO NORMAL ---
            if hasattr(self.ui, 'label_status'): self.ui.label_status.setText("Ready")
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setValue(0)
                self.ui.progress_render.setFormat("0%")
    def open_rendered_folder(self, file_path):
        """ Opens Windows Explorer and automatically highlights the rendered file! """
        import subprocess
        import os
        
        try:
            if os.path.exists(file_path):
                # Magic Windows command to open folder AND select the specific file
                subprocess.run(['explorer', '/select,', os.path.normpath(file_path)])
            else:
                # Fallback: Just open the directory if the file is somehow missing
                folder_dir = os.path.dirname(file_path)
                if folder_dir and os.path.exists(folder_dir):
                    os.startfile(folder_dir)
        except Exception as e:
            print(f"Failed to open folder: {e}")

    







import os
import PySide6.QtWidgets as qtw
import PySide6.QtCore as qtc
import PySide6.QtGui as qtg


# --- BACKGROUND WORKER: JIT THUMBNAIL SNIPER ---
import hashlib
import tempfile
import shutil
import subprocess
import os
import glob
from PySide6.QtCore import QThread, Signal

# --- SMART PREVIEW SNIPER 5.0 (RADAR RADIAL PRELOADER) ---
import os
import io
import re
import time
import av
import xml.etree.ElementTree as ET
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage, QPixmap



from PySide6.QtCore import QObject, QEvent





from PySide6.QtWidgets import QScrollArea, QSizePolicy


    
from PySide6.QtWidgets import QLabel, QFrame, QVBoxLayout, QWidget
from PySide6.QtCore import Qt, QPoint



from PySide6.QtCore import QObject, QEvent, Qt



  
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSlider, QLabel



from PySide6.QtCore import QObject, QEvent



    

if __name__ == "__main__":
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
            QMessageBox.critical(None, "Interface Error", "Failed to load smpegui13.ui!")
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
