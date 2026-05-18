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

# --- GLOBAL APP VERSION ---
APP_VERSION_STR = "17"
APP_VERSION_FLOAT = 17

if getattr(sys, 'frozen', False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))

os.environ["PATH"] = _base_dir + os.pathsep + os.environ["PATH"]

import mpv

from PySide6.QtCore import Qt, QFile, QThread, Signal, QTimer, QSize, QObject
from PySide6.QtCore import QUrl, QEvent
from PySide6.QtWidgets import QVBoxLayout, QApplication, QFileDialog, QMessageBox
from PySide6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QBrush
from PySide6.QtCore import Qt, Signal, QRect

def get_resource_path(relative_path):
    """ Smart file search for new ZIP-build (--onedir) """
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
        direct_path = os.path.join(base_dir, relative_path)
        if os.path.exists(direct_path):
            return direct_path
            
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative_path)
            
        return direct_path
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def get_save_directory():
    """ Returns the default folder where the program is launched to save videos. """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtCore import Qt, QRectF


class SteempegApp(QObject):
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
        self.custom_destination = "" # Custom save folder
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
            self.ui.table_clips.setStyleSheet("""
                QTableWidget { outline: 0; }
                QTableWidget::item { padding: 0px 5px; }
                QTableWidget::item:focus { outline: 0; border: none; }
                QTableWidget::item:selected {
                    background-color: #3d3d3d;
                    border: none;
                    color: #ffffff;
                }
            """)
            self.ui.table_clips.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.ui.table_clips.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.ui.table_clips.setShowGrid(False)
            self.ui.table_clips.verticalHeader().setVisible(False)
            
            # 2. ADJUST THE WIDTH
            header = self.ui.table_clips.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.Stretch)         
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents) 
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents) 
            header.setSectionResizeMode(3, QHeaderView.ResizeToContents) 
            
            self.ui.table_clips.itemSelectionChanged.connect(self.update_quality_options)

            # --- SMART RIGHT-CLICK (NO ROW SELECTION) ---
            self.ui.table_clips.viewport().installEventFilter(self)

        if hasattr(self.ui, 'settings_tabs'):
            self.ui.settings_tabs.setCurrentIndex(0)
        
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
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
        
        # 1. Create a new horizontal container
        browse_container = QWidget()
        browse_layout = QHBoxLayout(browse_container)
        browse_layout.setContentsMargins(0, 0, 0, 0)
        browse_layout.setSpacing(6)
        
        # 2. Extract the old 'Choose Folder' button from its parent layout
        old_browse_btn = self.ui.btn_browse
        parent_layout = old_browse_btn.parentWidget().layout()
        parent_layout.replaceWidget(old_browse_btn, browse_container)
        
        # 3. Create the new Refresh button
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setMinimumHeight(old_browse_btn.minimumHeight())
        self.btn_refresh.setToolTip("Rescan folder for new clips")
        self.btn_refresh.clicked.connect(self.scan_clips)
        

        # 4. Pack them both into the horizontal container (70% folder, 30% refresh)
        browse_layout.addWidget(old_browse_btn, 7)
        browse_layout.addWidget(self.btn_refresh, 3)
        
        self.ui.btn_browse.clicked.connect(self.choose_folder)
        self.ui.destination_button.clicked.connect(self.choose_destination)
        
        if hasattr(self.ui, 'btn_about'):
            self.ui.btn_about.clicked.connect(self.show_about_dialog)
        self.ui.btn_start.clicked.connect(self.start_render_thread)
            
        if hasattr(self.ui, 'btn_update_check'):
            self.ui.btn_update_check.clicked.connect(self.check_for_updates)

        self.ui.btn_start.clicked.connect(self.start_render_thread)
        self.ui.btn_start.setEnabled(False)

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
            loc_layout.addStretch() # MAGIC: Pushes everything to the left wall!

        # --- FIXING THE INTERFACE AND PLAYER ---
        # 1. Give the right panel some breathing room
        right_layout = self.ui.right_panel.layout()
        if right_layout:
            right_layout.setContentsMargins(12, 12, 12, 12) 
            right_layout.setSpacing(8)

        # 2: Taming MPV Player and creating a Border Wrapper
        from PySide6.QtWidgets import QFrame, QVBoxLayout
        
        # Create a simple transparent frame for our CSS border
        self.video_wrapper = QFrame()
        self.video_wrapper.setStyleSheet("background-color: transparent; border: none;")
        self.video_wrapper.installEventFilter(self)
        
        # Safely swap it into the UI
        parent_layout = self.ui.video_container.parentWidget().layout()
        parent_layout.replaceWidget(self.ui.video_container, self.video_wrapper)
        
        # Put the video inside with a 2-pixel margin so the border has space to draw
        wrap_layout = QVBoxLayout(self.video_wrapper)
        wrap_layout.setContentsMargins(2, 2, 2, 2)
        wrap_layout.setSpacing(0)
        wrap_layout.addWidget(self.ui.video_container)

        self.ui.video_container.setStyleSheet("background-color: #000000; border: none;")

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
                self.player_footer_frame.setStyleSheet("""
                    QFrame {
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
                
                # ROW 2: The Time Label AND Theater Button (Perfectly centered)
                time_layout = QHBoxLayout()
                
                # --- IRONCLAD CENTERING (3 EQUAL BLOCKS) ---
                
                # 1. LEFT BLOCK (Volume)
                left_wrap = QWidget()
                lw = QHBoxLayout(left_wrap)
                lw.setContentsMargins(0, 0, 0, 0)
                self.volume_control = VolumeControlWidget(self.player_footer_frame)
                self.volume_control.slider.valueChanged.connect(self.set_vlc_volume)
                lw.addWidget(self.volume_control, alignment=Qt.AlignLeft | Qt.AlignVCenter)
                
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
                self.pill_container.setStyleSheet("QFrame { background-color: #383838; border-radius: 20px; border: none; }")
                
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

                # Inject into the footer control bar
                rw.addStretch() 
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
                
                # Inject the gorgeous new container into the main UI
                right_layout.insertWidget(controls_index, self.player_footer_frame)
                self.custom_timeline.pause_requested.connect(self.on_timeline_press)
                self.custom_timeline.seek_requested.connect(self.on_timeline_seek)
                self.custom_timeline.resume_requested.connect(self.on_timeline_release)
                self.custom_timeline.trim_changed.connect(self.on_trim_changed) 
        
        # --- INITIALIZING THE MPV VIDEO PLAYER ---
        mpv_log_path = os.path.join(self.logs_dir, f"mpv_engine_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        self.player = mpv.MPV(
            wid=int(self.ui.video_container.winId()), 
            hwdec='auto',         
            keep_open='yes',      
            ao='wasapi',         
            log_file=mpv_log_path 
        )
        

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
        if hasattr(self.ui, 'combo_fps'): self.ui.combo_fps.currentTextChanged.connect(self.update_final_setup)
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

    # --- CONTEXT MENU LOGIC ---
    def show_clip_context_menu(self, pos):
        """ Displays a right-click context menu for the clips table. """
        from PySide6.QtWidgets import QMenu
        
        # 1. Check if user clicked on a valid row
        item = self.ui.table_clips.itemAt(pos)
        if not item:
            return

        # 2. Extract the physical path of the clicked clip
        selected_row = item.row()
        clip_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
        
        if not clip_path or not os.path.exists(clip_path):
            return

        # 3. Create and populate the menu
        menu = QMenu(self.ui.table_clips)
        menu.setStyleSheet("""
            QMenu { background-color: #2d2d2d; color: white; border: 1px solid #444; }
            QMenu::item { padding: 5px 20px 5px 20px; }
            QMenu::item:selected { background-color: #555; }
        """)
        
        action_open = menu.addAction("📂 Open in folder")
        menu.addSeparator()
        action_delete = menu.addAction("🗑️ Delete Clip")
        
        # 4. Connect actions
        action_open.triggered.connect(lambda: self.open_clip_folder(clip_path))
        action_delete.triggered.connect(lambda: self.delete_clip(clip_path))
        
        # 5. Show the menu exactly at the mouse cursor
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
                    self.ui.label_short_summary.setText("Select a clip to begin...")
                if hasattr(self.ui, 'label_detailed_summary'):
                    self.ui.label_detailed_summary.setText("Waiting for clip selection...")
                    
            except Exception as e:
                logging.error(f"Failed to delete clip: {e}")
                QMessageBox.critical(self.ui, "Error", f"Failed to delete the clip.\nIt might be in use by another program.\n\n{e}")

    def eventFilter(self, source, event):
        from PySide6.QtCore import QEvent, Qt
        
        # --- FLOATING PANEL RESIZE LOGIC ---
        if hasattr(self, 'video_wrapper') and source == self.video_wrapper and event.type() == QEvent.Type.Resize:
            if getattr(self, 'is_fullscreen', False) and hasattr(self, 'player_footer_frame'):
                # Dynamically compute bottom-center alignment boundaries with 40px padding
                w = self.video_wrapper.width()
                h = self.video_wrapper.height()
                footer_h = self.player_footer_frame.sizeHint().height()
                # Pin HUD firmly above the bottom monitor edge
                self.player_footer_frame.setGeometry(40, h - footer_h - 40, w - 80, footer_h)
            return False

        # 1. Check if the event happened inside the clips table (your old code continues here...)
        if hasattr(self.ui, 'table_clips') and source == self.ui.table_clips.viewport():
            
            # 2. Did the user press a mouse button?
            if event.type() == QEvent.Type.MouseButtonPress:
                
                # 3. Was it the RIGHT mouse button?
                if event.button() == Qt.RightButton:
                    
                    # Manually trigger our menu exactly where the mouse clicked
                    click_pos = event.position().toPoint()
                    self.show_clip_context_menu(click_pos)
                    
                    # MAGIC: Return True to block Qt from selecting the row!
                    return True 
                    
        return super().eventFilter(source, event)
    
    def set_status(self, text):
        """ Updates the status text and the progress bar """
        if hasattr(self.ui, 'label_status'):
            self.ui.label_status.setText(text)
            
        # If the interface has a progress bar, look for percentages in the text
        if hasattr(self.ui, 'progress_render'):
            # Reset to 0 at startup
            if text in ["Ready", "Success", "Cancelled"]:
                self.ui.progress_render.setValue(0)
                
            # We look for numbers between brackets and the % sign
            match = re.search(r'\((\d+)%\)', text)
            if match:
                self.ui.progress_render.setValue(int(match.group(1)))

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
    
    # VIDEO PLAYER CONTROLS
    def toggle_play(self):
        """ Toggles Play/Pause state in MPV and updates the button icon. """
        if not hasattr(self, 'player') or not self.player: 
            return
            
        # In MPV, 'path' is None if no video is currently loaded
        if getattr(self.player, 'path', None) is None: 
            return

        # Invert the current pause state
        self.player.pause = not self.player.pause
        
        # Update the button icon based on the new state
        if hasattr(self.ui, 'btn_play'):
            if self.player.pause:
                # Video is paused -> Show the PLAY button
                icon_path = get_resource_path("icon_play.png")
            else:
                # Video is playing -> Show the PAUSE button
                icon_path = get_resource_path("icon_pause.png")
                
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
    def toggle_theater_mode(self):
        """ Safely collapses side and bottom panels, aware of Fullscreen state, and swaps icon. """
        
        # 1. STATE MACHINE: If we are currently in Fullscreen, exit it elegantly first!
        if getattr(self, 'is_fullscreen', False):
            self.toggle_fullscreen() 
            
        self.is_theater = not getattr(self, 'is_theater', False)
        
        # 2. Hide the Left Panel (Clips Library)
        if hasattr(self.ui, 'table_clips'):
            left_wrapper = self.ui.table_clips.parentWidget()
            if left_wrapper and "Splitter" not in type(left_wrapper).__name__ and left_wrapper.objectName() != "centralwidget":
                left_wrapper.setVisible(not self.is_theater)
            else:
                self.ui.table_clips.setVisible(not self.is_theater)

        # 3. Hide the Settings Tabs (Middle Bottom)
        if hasattr(self.ui, 'settings_tabs'):
            self.ui.settings_tabs.setVisible(not self.is_theater)
            
        # 4. Hide the Render Footer (Very Bottom)
        if hasattr(self.ui, 'btn_start'):
            bottom_wrapper = self.ui.btn_start.parentWidget()
            if bottom_wrapper and "Splitter" not in type(bottom_wrapper).__name__ and bottom_wrapper.objectName() != "centralwidget":
                bottom_wrapper.setVisible(not self.is_theater)

        # 5. Hide the "Browse / Refresh" buttons
        if hasattr(self, 'btn_refresh'):
            browse_wrapper = self.btn_refresh.parentWidget()
            if browse_wrapper: browse_wrapper.setVisible(not self.is_theater)
            
        if hasattr(self.ui, 'btn_about'): self.ui.btn_about.setVisible(not self.is_theater)
        if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.setVisible(not self.is_theater)
                
        # 6. --- THE MAGIC SWAP ---
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
            
            # --- BUGFIX: Forcefully clear hover states by sending a fake Leave event ---
            from PySide6.QtCore import QEvent
            from PySide6.QtWidgets import QApplication
            self.btn_theater.clearFocus()
            QApplication.postEvent(self.btn_theater, QEvent(QEvent.Type.Leave))

        # --- TRUE HIGH-END FULLSCREEN SYSTEM ---
    def toggle_fullscreen(self):
        """ Completely isolates the video container, fully aware of Theater Mode states. """
        self.is_fullscreen = not getattr(self, 'is_fullscreen', False)
        
        if self.is_fullscreen:
            # --- ENTERING TRUE FULLSCREEN ---
            
            # Hide EVERYTHING explicitly using UI exact names
            if hasattr(self.ui, 'left_panel'): self.ui.left_panel.hide()
            if hasattr(self.ui, 'settings_tabs'): self.ui.settings_tabs.hide()
            if hasattr(self.ui, 'frame_status'): self.ui.frame_status.hide()
            if hasattr(self, 'player_header_frame'): self.player_header_frame.hide()

            # Also hide your custom specific buttons to be absolutely safe
            if hasattr(self.ui, 'btn_start'):
                bw = self.ui.btn_start.parentWidget()
                if bw and "Splitter" not in type(bw).__name__ and bw.objectName() != "centralwidget": bw.hide()
            if hasattr(self, 'btn_refresh'):
                rw = self.btn_refresh.parentWidget()
                if rw: rw.hide()
            if hasattr(self.ui, 'btn_about'): self.ui.btn_about.hide()
            if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.hide()

            # Hide splitter lines
            if hasattr(self.ui, 'main_splitter'):
                self.ui.main_splitter.handle(1).hide()

            # Strip margins
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

            # Engage Fullscreen
            self.ui.showFullScreen()

            # Elevate the HUD
            self.player_footer_frame.setParent(self.video_wrapper)
            self.player_footer_frame.setStyleSheet("""
                QFrame { 
                    background-color: rgba(24, 24, 24, 210); 
                    border-radius: 12px; 
                    border: 1px solid rgba(255, 255, 255, 20); 
                }
            """)
            self.player_footer_frame.show()
            self.player_footer_frame.raise_()

            self.wake_up_fullscreen_controls()
            
        else:
            # --- EXITING FULLSCREEN ---
            self.fs_timer.stop()
            self.ui.setCursor(Qt.ArrowCursor) 
            self.ui.showNormal()
            
            # --- SMART RESTORE (CHECKS THEATER MODE STATE) ---
            is_t = getattr(self, 'is_theater', False)
            
            # Restore major UI panels ONLY IF we are not in Theater mode
            if hasattr(self.ui, 'left_panel'): self.ui.left_panel.setVisible(not is_t)
            if hasattr(self.ui, 'settings_tabs'): self.ui.settings_tabs.setVisible(not is_t)
            if hasattr(self.ui, 'frame_status'): self.ui.frame_status.setVisible(not is_t)
            
            # Restore your specific wrappers ONLY IF we are not in Theater mode
            if hasattr(self.ui, 'btn_start'):
                bw = self.ui.btn_start.parentWidget()
                if bw and "Splitter" not in type(bw).__name__ and bw.objectName() != "centralwidget": bw.setVisible(not is_t)
            if hasattr(self, 'btn_refresh'):
                rw = self.btn_refresh.parentWidget()
                if rw: rw.setVisible(not is_t)
            if hasattr(self.ui, 'btn_about'): self.ui.btn_about.setVisible(not is_t)
            if hasattr(self.ui, 'btn_update_check'): self.ui.btn_update_check.setVisible(not is_t)

            # Headers and splitters are always visible in windowed mode
            if hasattr(self, 'player_header_frame'): self.player_header_frame.show()
            if hasattr(self.ui, 'main_splitter'): self.ui.main_splitter.handle(1).show()

            # Restore margins
            main_layout = self.ui.layout()
            if main_layout and hasattr(self, 'original_main_margins'):
                main_layout.setContentsMargins(self.original_main_margins)

            right_layout = self.ui.right_panel.layout()
            if right_layout and hasattr(self, 'original_right_margins'):
                right_layout.setContentsMargins(self.original_right_margins)
                right_layout.setSpacing(getattr(self, 'original_right_spacing', 8))

            # Dock the HUD back
            idx = getattr(self, 'controls_layout_index', -1)
            if right_layout and idx >= 0:
                right_layout.insertWidget(idx, self.player_footer_frame)
            else:
                right_layout.addWidget(self.player_footer_frame)

            self.player_footer_frame.setStyleSheet("QFrame { background-color: #2d2d2d; border-radius: 6px; border: none; }")
            self.player_footer_frame.show()
            
            # --- BUGFIX: Forcefully clear hover states by sending a fake Leave event ---
            from PySide6.QtCore import QEvent
            from PySide6.QtWidgets import QApplication
            
            if hasattr(self, 'btn_fullscreen'):
                self.btn_fullscreen.clearFocus()
                QApplication.postEvent(self.btn_fullscreen, QEvent(QEvent.Type.Leave))
                
            if hasattr(self, 'btn_theater'):
                self.btn_theater.clearFocus()
                QApplication.postEvent(self.btn_theater, QEvent(QEvent.Type.Leave))

    def wake_up_fullscreen_controls(self):
        """ Restores mouse arrow visibility and maps HUD controls layer on motion. """
        if not getattr(self, 'is_fullscreen', False): return
        
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
            # --- TURN OFF TRIM MODE (Cancel) ---
            self.custom_timeline.disable_trim_mode()
            
            # Hide the interactive border instantly
            if hasattr(self, 'video_overlay'):
                self.video_overlay.show_border = False
                self.video_overlay.update()
            
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
            
            # --- BUGFIX: Remove yellow border from the wrapper, NOT the container ---
            if hasattr(self, 'video_wrapper'):
                self.video_wrapper.setStyleSheet("background-color: transparent; border: none;")
        else:
            # --- TURN ON TRIM MODE ---
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

        # --- FORCE UI REFRESH ON TOGGLE ---
        # Instantly update the text logs and recalculate file sizes!
        self.update_final_setup()
        if hasattr(self.ui, 'combo_quality') and "Target File Size" in self.ui.combo_quality.currentText():
            self.setup_dynamic_slider()

    def on_timeline_press(self):
        """ Triggered when the user clicks on the timeline track. """
        if hasattr(self, 'player') and self.player:
            # Check if video is playing (if pause is False, it means it is playing)
            self.was_playing_before_drag = not self.player.pause
            
            # Pause the video while the user is dragging the playhead
            self.player.pause = True

    def on_timeline_seek(self, position_ms):
        """ Commands MPV to jump. The custom widget handles its own anti-snapback math. """
        if hasattr(self, 'player') and self.player:
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
        if hasattr(self, 'custom_timeline'):
            new_time = self.custom_timeline.visual_ms - 15000
            self.custom_timeline.force_jump(new_time)

    def skip_forward(self):
        """ Skips 15 seconds forward using the Independent Timeline Engine """
        if hasattr(self, 'custom_timeline'):
            new_time = self.custom_timeline.visual_ms + 15000
            self.custom_timeline.force_jump(new_time)

    def skip_back(self):
        """ Skips 15 seconds backward using the Independent Timeline Engine """
        if hasattr(self, 'custom_timeline'):
            new_time = self.custom_timeline.visual_ms - 15000
            self.custom_timeline.force_jump(new_time)

    def generate_and_play_preview(self):
        """ Instantly loads and plays the Steam .mpd playlist using MPV. No proxy needed! """ 
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            return

        # 1. STOP CURRENT PLAYBACK
        self._force_pause = False
        self.player.stop()

        # 2. GET THE CLIP FOLDER PATH
        clip_path = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).data(Qt.UserRole)
        all_mpds = self.get_all_mpd_paths(clip_path)
        if not all_mpds: 
            return

        mpd_path = all_mpds[0] 
        print(f"---> Feeding MPD directly to MPV: {mpd_path}")

        # 3. PREPARE THE CANVAS
        self.ui.video_container.setStyleSheet("background-color: black;") 

        # 4. FEED THE RAW STEAM DASH FILE DIRECTLY TO MPV
        abs_path = os.path.abspath(mpd_path).replace('\\', '/')
        self.player.play(abs_path) 
        
        # Ensure the video auto-plays
        self.player.pause = False


        # --- BACKGROUND THUMBNAIL BATCH GENERATION (THE MATRIX 2.0) ---
        if hasattr(self, 'thumb_thread') and self.thumb_thread.isRunning():
            self.thumb_thread.terminate()
            
        # Launch the Batch Generator (interval is set to 3 seconds inside by default)
        self.thumb_thread = ThumbnailBatchThread(abs_path, self.current_clip_duration_sec, interval=3)
        
        # ⚡ THE LAZY LOAD FIX: Tell the timeline where the folder is IMMEDIATELY!
        # It won't wait for FFmpeg to finish 100%. It will grab frames as they appear!
        if hasattr(self, 'custom_timeline'):
            self.custom_timeline.thumb_dir = self.thumb_thread.thumb_dir
                
        self.thumb_thread.start()

        # --- IMMEDIATELY UPDATE PLAY BUTTON ICON TO PAUSE ---
        if hasattr(self.ui, 'btn_play'):
            from PySide6.QtGui import QIcon
            icon_path = get_resource_path("icon_pause.png")
            self.ui.btn_play.setIcon(QIcon(icon_path))

    def update_ui_from_vlc(self):
        """ Updates UI and Timeline from MPV engine (name kept for compatibility) """
        if not hasattr(self, 'player') or not self.player:
            return
            
        # Safe check to prevent jumpiness after seeking
        if time.time() < getattr(self, '_ignore_vlc_until', 0):
            return

        try:
            # Fetch raw data from MPV
            duration_sec = self.player.duration
            time_sec = self.player.time_pos
            
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
            if getattr(self.player, 'eof_reached', False) or current_ms >= duration_ms - 100:
                self.player.pause = True # Pause playback
                self.player.seek(0, reference='absolute', precision='exact') # Rewind strictly to 0
                current_ms = 0 # Reset local counter
                
                # Snap the white playhead back to the start
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
            # Completely disable the trim border if the player is in fullscreen mode
            if getattr(self, 'is_fullscreen', False):
                if hasattr(self, 'video_wrapper'):
                    self.video_wrapper.setStyleSheet("background-color: transparent; border: none;")
            else:
                # Apply the yellow trim border only in normal and theater modes to the wrapper
                if hasattr(self, 'custom_timeline') and self.custom_timeline.is_trim_mode:
                    if self.custom_timeline.trim_start_ms <= current_ms <= self.custom_timeline.trim_end_ms:
                        # Precision yellow framing for active trim zones
                        if hasattr(self, 'video_wrapper'):
                            self.video_wrapper.setStyleSheet("background-color: transparent; border: 2px solid #ffcc00; border-radius: 4px;")
                    else:
                        if hasattr(self, 'video_wrapper'):
                            self.video_wrapper.setStyleSheet("background-color: transparent; border: none;")
                else:
                    if hasattr(self, 'video_wrapper'):
                        self.video_wrapper.setStyleSheet("background-color: transparent; border: none;")

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
        <p>Powered by <b>FFmpeg</b> & <b>MPV</b></p>

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

    def check_for_updates(self):
        """ Checks GitHub API for new releases with deep logging """
        import requests
        import webbrowser
        import re
        import logging

        CURRENT_VERSION = APP_VERSION_FLOAT
        logging.info("--- UPDATER: Button clicked! Starting check_for_updates ---")

        try:
            self.set_status("Checking for updates...")
            
            url = "https://api.github.com/repos/applejuicy23/steempeg/releases/latest"
            headers = {'User-Agent': 'Steempeg-Updater'}
            
            logging.info(f"UPDATER: Connecting to {url}...")
            
            # response API
            response = requests.get(url, headers=headers, timeout=5)
            logging.info(f"UPDATER: GitHub API responded with status code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                latest_name = data.get("name", "")
                tag_name = data.get("tag_name", "")
                release_url = data.get("html_url", "https://github.com/applejuicy23/steempeg/releases")
                
                logging.info(f"UPDATER: Found release - Name: '{latest_name}', Tag: '{tag_name}'")
                
                # find version
                match = re.search(r'v(\d+(?:\.\d+)?)', tag_name + " " + latest_name, re.IGNORECASE)
                
                if match:
                    latest_version = float(match.group(1))
                    logging.info(f"UPDATER: Parsed version: {latest_version} (Local Current: {CURRENT_VERSION})")
                    
                    if latest_version > CURRENT_VERSION:
                        logging.info("UPDATER: Showing 'Update Available' dialog.")
                        
                        download_url = None
                        asset_name = None
                        
                        # Look for our .zip archive in the release on GitHub
                        for asset in data.get("assets", []):
                            name = asset.get("name", "").lower()
                            if name.endswith(".zip"):
                                download_url = asset.get("browser_download_url")
                                asset_name = asset.get("name")
                                break
                        
                        msg = QMessageBox(self.ui)
                        msg.setWindowTitle("Update Available!")
                        msg.setIcon(QMessageBox.Information)
                        msg.setText(f"<h3>Great news!</h3><p>A new version is available: <b>{latest_name}</b></p><p>You are currently on v{CURRENT_VERSION}.</p>")
                        
                        btn_download = msg.addButton("🚀 Install Update", QMessageBox.ActionRole)
                        btn_cancel = msg.addButton("Maybe Later", QMessageBox.RejectRole)
                        
                        msg.exec()
                        
                        if msg.clickedButton() == btn_download:
                            if download_url:
                                # Start downloading the ZIP archive directly in the program!
                                self.start_downloading_update(download_url, asset_name)
                            else:
                                # If for some reason the ZIP file is not found, open the browser
                                webbrowser.open(release_url)
                            
                    elif latest_version == CURRENT_VERSION:
                        logging.info("UPDATER: Showing 'Latest Version' dialog.")
                        QMessageBox.information(self.ui, "Updater", f"You are using the latest public version of Steempeg (v{CURRENT_VERSION})! 🎉")
                        
                    else:
                        logging.info("UPDATER: Showing 'Developer Build' dialog.")
                        QMessageBox.information(
                            self.ui, 
                            "Developer Build", 
                            f"Wow! You are on a developer build (v{CURRENT_VERSION}).\n"
                            f"The latest public release on GitHub is only v{latest_version}.\n"
                            f"Keep up the great work! 🚀🎀\n"
                            f"Developer awaits your LOG to fix the bug!🌷"
                        )
                else:
                    logging.warning("UPDATER: Regex failed to find 'vX.X' in the release name/tag.")
                    QMessageBox.warning(self.ui, "Updater", "Could not parse the version number from the latest GitHub release.")
            
            elif response.status_code == 404:
                logging.warning("UPDATER: 404 Not Found. This means the repo is private or has 0 public releases.")
                QMessageBox.information(self.ui, "Updater", f"You are on the pioneer version (v{CURRENT_VERSION})! No public releases found yet. 🎉")
            
            elif response.status_code == 403:
                logging.warning(f"UPDATER: 403 Forbidden. GitHub API Rate Limit exceeded! Response: {response.text}")
                QMessageBox.warning(self.ui, "Updater", "GitHub API rate limit exceeded. Please try checking for updates later.")
                
            else:
                logging.error(f"UPDATER: Unexpected status code {response.status_code}. Response: {response.text}")
                QMessageBox.warning(self.ui, "Updater", f"Could not check for updates. GitHub API returned status: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
             logging.error(f"UPDATER: Network request failed: {e}")
             QMessageBox.critical(self.ui, "Updater Error", "Could not connect to GitHub. Check your internet connection!")
        except Exception as e:
            logging.error(f"UPDATER: Critical Python exception: {e}")
            QMessageBox.critical(self.ui, "Updater Error", f"An error occurred while checking for updates:\n{str(e)}")
        finally:
            self.set_status("Ready")
            logging.info("--- UPDATER: check_for_updates finished ---")

    def start_downloading_update(self, url, asset_name):
        """ Starts the background download and shows a progress bar """
        from PySide6.QtWidgets import QProgressDialog
        
        self.progress_dialog = QProgressDialog("Starting download...", "Cancel", 0, 100, self.ui)
        self.progress_dialog.setWindowTitle("Steempeg Updater")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setAutoClose(True)
        self.progress_dialog.setValue(0)
        self.progress_dialog.setMinimumWidth(400) # Making the window wider for text

        self.update_thread = UpdateDownloadThread(url, os.path.dirname(sys.executable), asset_name)
        self.update_thread.progress_signal.connect(self.update_download_progress)
        self.update_thread.finished_signal.connect(self.on_update_downloaded)
        
        self.update_thread = UpdateDownloadThread(url, os.path.dirname(sys.executable), asset_name)

        self.update_thread.progress_signal.connect(self.update_download_progress)
        self.update_thread.finished_signal.connect(self.on_update_downloaded)
        
        self.progress_dialog.canceled.connect(self.update_thread.cancel)
        self.update_thread.start()
        self.progress_dialog.show()

    def update_download_progress(self, percent, text):
        """ Dynamically updates the text and progress bar of the updater """
        self.progress_dialog.setLabelText(text)
        self.progress_dialog.setValue(percent)

    def show_update_success(self, old_version, backup_folder):
        """ Shows a nice window after a successful update """
        msg = QMessageBox(self.ui)
        msg.setWindowTitle("Update Successful!")
        msg.setIcon(QMessageBox.Information)
        
        text = f"<h3>Steempeg is updated!</h3><p>Successfully updated from <b>v{old_version}</b> to the latest version.</p>"
        if backup_folder and backup_folder != "None":
            text += f"<p>Your old version was saved in the folder:<br><code>{backup_folder}</code></p>"
            
        msg.setText(text)
        
        btn_ok = msg.addButton("Good!", QMessageBox.AcceptRole)
        btn_folder = None
        if backup_folder and backup_folder != "None":
            btn_folder = msg.addButton("📂 Open Backup Folder", QMessageBox.ActionRole)
            
        msg.exec()
        
        if btn_folder and msg.clickedButton() == btn_folder:
            import subprocess
            backup_path = os.path.abspath(os.path.join(get_save_directory(), backup_folder))
            if os.path.exists(backup_path):
                os.startfile(backup_path)

    # final_asset_name
    def on_update_downloaded(self, success, filepath, final_asset_name):
        """ Unpacks the ZIP, asks about a backup, and launches the BAT ninja. """
        if not success:
            if filepath: QMessageBox.warning(self.ui, "Update Failed", f"Could not download the update.\n{filepath}")
            return

        import zipfile
        import shutil

        current_exe = sys.executable
        exe_dir = os.path.dirname(current_exe)
        
        # The BAT file will now ALWAYS use the real global version of the client!
        CURRENT_VERSION = APP_VERSION_STR 

        # 1. Unzip the downloaded ZIP file into a temporary folder.
        extract_dir = os.path.join(exe_dir, "_update_extracted")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(filepath, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        except Exception as e:
            QMessageBox.critical(self.ui, "Extraction Error", f"Failed to unzip the update!\n{e}")
            return

        # Find the source folder inside the unpacked archive (in case the files are inside the Steempeg_v13 folder)
        extracted_items = os.listdir(extract_dir)
        if len(extracted_items) == 1 and os.path.isdir(os.path.join(extract_dir, extracted_items[0])):
            source_dir = os.path.join("_update_extracted", extracted_items[0])
        else:
            source_dir = "_update_extracted"

        # Looking for a new executable (smpeg13.exe)
        new_exe_name = "Steempeg.exe"
        full_source_path = os.path.join(exe_dir, source_dir)
        for file in os.listdir(full_source_path):
            if file.endswith(".exe") and "ffmpeg" not in file.lower() and "ffprobe" not in file.lower():
                new_exe_name = file
                break

        #2. Ask the user
        msg = QMessageBox(self.ui)
        msg.setWindowTitle("Update Ready to Install!")
        msg.setText("The new version has been downloaded and extracted.\nDo you want to replace the current files, or keep them as a backup?")
        msg.setIcon(QMessageBox.Question)
        
        btn_delete = msg.addButton("🗑️ Replace (Delete old)", QMessageBox.AcceptRole)
        btn_keep = msg.addButton("📦 Keep backup", QMessageBox.ActionRole)
        msg.exec()
        
        keep_old = (msg.clickedButton() == btn_keep)
        backup_folder_name = f"old_version_v{CURRENT_VERSION}" if keep_old else "None"
        is_backup_true = "True" if keep_old else "False"

        # 3. BAT-script
        pid = os.getpid()
        bat_path = os.path.join(exe_dir, "updater.bat")
        
        # We save the logs and cache folders so that the user does not lose their data!
        bat_content = f"""@echo off
        title Steempeg Updater
        echo Waiting for Steempeg to close completely...

        :wait_loop
        tasklist /FI "PID eq {pid}" | find "{pid}" > NUL
        if errorlevel 1 goto install
        timeout /t 1 /nobreak > NUL
        goto wait_loop

        :install
        echo Installing update...
        timeout /t 1 /nobreak > NUL

        if "{is_backup_true}"=="True" (
            echo Creating backup folder...
            mkdir "{backup_folder_name}"
            
            
            for %%I in (*.*) do if /I not "%%I"=="updater.bat" if /I not "%%I"=="{final_asset_name}.tmp" move "%%I" "{backup_folder_name}\" > NUL
            
            
            for /D %%D in (*) do (
                if /I not "%%D"=="{backup_folder_name}" if /I not "%%D"=="_update_extracted" if /I not "%%D"=="logs" if /I not "%%D"=="cache" move "%%D" "{backup_folder_name}\" > NUL
            )
        ) else (
            echo Cleaning old files...
            for %%I in (*.*) do if /I not "%%I"=="updater.bat" if /I not "%%I"=="{final_asset_name}.tmp" del /F /Q "%%I"
            for /D %%D in (*) do (
                if /I not "%%D"=="_update_extracted" if /I not "%%D"=="logs" if /I not "%%D"=="cache" rd /S /Q "%%D"
            )
        )

        echo Moving new files...
        xcopy /S /E /Y /C /I "{source_dir}\\*" ".\\" > NUL
        rd /S /Q "_update_extracted"
        del /F /Q "{final_asset_name}.tmp"

        echo Starting new version...
        start "" "{new_exe_name}" --updated-from {CURRENT_VERSION} --backup-folder "{backup_folder_name}"
        del "%~f0"
        """
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        env = os.environ.copy()
        env.pop('_MEIPASS2', None)
        env.pop('_MEIPASS', None)
        
        subprocess.Popen([bat_path], shell=True, cwd=exe_dir, creationflags=0x08000000, env=env)
        
        QApplication.quit()
        sys.exit(0)


    def scan_clips(self):
        """ Scans both 'clips' and 'video' folders and fills the TABLE with pretty data"""
        if not hasattr(self.ui, 'table_clips'): return
        self.ui.table_clips.setSortingEnabled(False) 
        self.ui.table_clips.setRowCount(0)
        
        if not self.clips_folder or not os.path.exists(self.clips_folder): return

        # If the user has chosen the "clips" folder the old-fashioned way, go up one level to gamerecordings
        base_folder = self.clips_folder
        if os.path.basename(base_folder).lower() == "clips":
            base_folder = os.path.dirname(base_folder)

        # Folders we will scan
        folders_to_check = [
            os.path.join(base_folder, "clips"),
            os.path.join(base_folder, "video")
        ]

        try:
            for search_dir in folders_to_check:
                if not os.path.exists(search_dir): continue

                items = os.listdir(search_dir)
                for item_name in items:
                    full_path = os.path.join(search_dir, item_name)
                    
                    if os.path.isdir(full_path):
                        has_mpd = False
                        has_chunks = False
                        for root, dirs, files in os.walk(full_path):
                            if any(f.endswith(".mpd") for f in files):
                                has_mpd = True
                                break 
                            # Checking if there are any "FG" without MPD
                            if any("chunk-stream" in f for f in files):
                                has_chunks = True

                        # If there are bits of food, but no MPD, we start resuscitation!
                        if has_chunks and not has_mpd:
                            recovered = self.recover_orphaned_clip(full_path)
                            if recovered:
                                has_mpd = True

                        if not has_mpd: continue

                        parts = item_name.split("_")
                        
                        # Parsing Steam data (bg_12345_20260508_200009)
                        if len(parts) >= 4 and parts[1].isdigit():
                            prefix = parts[0]
                            app_id = parts[1]
                            
                            # DETERMINE THE RECORD TYPE
                            # DETERMINE THE RECORD TYPE (Shortened to BG and FG)
                            # surely idk what is FG but i took it in account if anything!
                            if prefix == "clip": rec_type = "🎬 Clip"
                            elif prefix == "bg": rec_type = "📼 BG"
                            elif prefix == "fg": rec_type = "🎞️ FG"
                            else: rec_type = "📁 Unknown"

                            game_name = self.get_game_name(app_id)
                            icon = self.get_game_icon(app_id)

                            try: formatted_date = datetime.strptime(parts[2], "%Y%m%d").strftime("%d %B %Y")
                            except: formatted_date = parts[2]

                            try: formatted_time = datetime.strptime(parts[3], "%H%M%S").strftime("%H:%M:%S")
                            except: formatted_time = parts[3]

                        else:
                            rec_type = "📁 Folder"
                            game_name = item_name
                            formatted_date = "Unknown"
                            formatted_time = "Unknown"
                            icon = QIcon()

                        # adding to table
                        row_position = self.ui.table_clips.rowCount()
                        self.ui.table_clips.insertRow(row_position)
                        
                        # Column 0: Type
                        item_game = QTableWidgetItem(icon, game_name)
                        item_game.setData(Qt.UserRole, full_path) 
                        self.ui.table_clips.setItem(row_position, 0, item_game)
                        
                        # Column 1: Game Title + Image
                        item_type = QTableWidgetItem(rec_type)
                        item_type.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                        self.ui.table_clips.setItem(row_position, 1, item_type)
                        
                        # Column 2: Date
                        item_date = QTableWidgetItem(formatted_date)
                        self.ui.table_clips.setItem(row_position, 2, item_date)
                        
                        # Column 3: Time
                        item_time = QTableWidgetItem(formatted_time)
                        self.ui.table_clips.setItem(row_position, 3, item_time)

            self.ui.table_clips.setSortingEnabled(True)
                    
        except Exception as e:
            QMessageBox.critical(self.ui, "Scan Error", f"Error:\n{str(e)}")
    
    def choose_destination(self):
        """ Select a custom folder to save the finished video """
        folder = QFileDialog.getExistingDirectory(self.ui, "Select Destination Folder")
        if folder:
            self.custom_destination = folder
            self.ui.destination_button.setText(f"Destination: {folder}")
        else:
            self.custom_destination = ""
            self.ui.destination_button.setText("Choose destination")
        self.update_final_setup()

    def open_logs_folder(self): 
        """ Opens the logs folder in Windows. """
        if hasattr(self, 'logs_dir') and os.path.exists(self.logs_dir):
            os.startfile(self.logs_dir)
    def open_current_log(self):
        """ Opens the current log file directly. """
        if hasattr(self, 'current_log_file') and os.path.exists(self.current_log_file):
            os.startfile(self.current_log_file)
        
    def get_all_mpd_paths(self, clip_path):
        """ Recursively finds and FIXES session.mpd files before feeding them to MPV """
        mpd_paths = []
        if os.path.exists(clip_path):
            for root, dirs, files in os.walk(clip_path):
                if "session.mpd" in files:
                    original_mpd = os.path.join(root, "session.mpd")
                    fixed_mpd = self.fix_steam_manifest(original_mpd)
                    mpd_paths.append(fixed_mpd)
                elif "session_recovered.mpd" in files:
                    mpd_paths.append(os.path.join(root, "session_recovered.mpd"))
        return sorted(mpd_paths)

    def fix_steam_manifest(self, mpd_path):
        """
        Repairs Steam's rolling buffer manifests. maybe
        """
        import glob
        import re
        
        folder = os.path.dirname(mpd_path)
        chunks = glob.glob(os.path.join(folder, "chunk-stream0-*.m4s"))
        if not chunks: return mpd_path

        numbers = []
        for c in chunks:
            match = re.search(r'chunk-stream0-(\d+)\.m4s', os.path.basename(c))
            if match: numbers.append(int(match.group(1)))
            
        if not numbers: return mpd_path
        min_chunk = min(numbers)
        
        try:
            with open(mpd_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # --- THE ULTIMATE MAGIC FIX FOR DASH TIMESTAMPS ---
            # Video and Audio have DIFFERENT timescales. We must calculate offsets independently!
            def inject_offset(match):
                tag = match.group(0)
                ts_m = re.search(r'timescale="(\d+)"', tag)
                dur_m = re.search(r'duration="(\d+)"', tag)
                if ts_m and dur_m:
                    ts = int(ts_m.group(1))
                    dur = int(dur_m.group(1))
                    # Calculate proper offset for THIS specific track (Audio or Video)
                    track_offset = (min_chunk - 1) * dur
                    if 'presentationTimeOffset=' in tag:
                        return re.sub(r'presentationTimeOffset="\d+"', f'presentationTimeOffset="{track_offset}"', tag)
                    else:
                        return tag.replace('<SegmentTemplate ', f'<SegmentTemplate presentationTimeOffset="{track_offset}" ')
                return tag
            
            # Apply the function to every SegmentTemplate in the file independently
            content = re.sub(r'<SegmentTemplate\s+[^>]+>', inject_offset, content)

            # Fix 1: Update the startNumber for MPV/VLC
            content = re.sub(r'startNumber="\d+"', f'startNumber="{min_chunk}"', content)
            
            # Fix 2: ONLY adjust total duration if Steam actually deleted chunks
            if min_chunk > 1:
                ts_match = re.search(r'timescale="(\d+)"', content)
                dur_match = re.search(r'duration="(\d+)"', content)
                mpd_dur_match = re.search(r'mediaPresentationDuration="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"', content)

                if ts_match and dur_match and mpd_dur_match:
                    chunk_duration_sec = float(dur_match.group(1)) / float(ts_match.group(1))
                    deleted_sec = (min_chunk - 1) * chunk_duration_sec

                    h = float(mpd_dur_match.group(1)) if mpd_dur_match.group(1) else 0
                    m = float(mpd_dur_match.group(2)) if mpd_dur_match.group(2) else 0
                    s = float(mpd_dur_match.group(3)) if mpd_dur_match.group(3) else 0
                    original_total_sec = (h * 3600) + (m * 60) + s

                    new_total_sec = max(0.0, original_total_sec - deleted_sec)

                    new_h = int(new_total_sec // 3600)
                    new_m = int((new_total_sec % 3600) // 60)
                    new_s = new_total_sec % 60
                    new_pt = f"PT{new_h}H{new_m}M{new_s:.3f}S" if new_h > 0 else f"PT{new_m}M{new_s:.3f}S"

                    content = re.sub(r'mediaPresentationDuration="PT[^"]+"', f'mediaPresentationDuration="{new_pt}"', content)

            fixed_path = os.path.join(folder, "session_fixed.mpd")
            with open(fixed_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            return fixed_path
            
        except Exception as e:
            logging.error(f"Failed to fix manifest accurately: {e}")
            return mpd_path
    
    def recover_orphaned_clip(self, folder_path):
        """ Generates a valid session.mpd for orphaned chunks! """
        import glob
        import re
        import logging
        import os

        # --- CHECKING THE INIT FILE ---
        # Without this file, MPV will try to read empty space and the program will explode!
        init_v = os.path.join(folder_path, "init-stream0.m4s")
        if not os.path.exists(init_v) or os.path.getsize(init_v) < 100:
            logging.warning(f"Corpse skipped (No valid init-stream0): {folder_path}")
            return None 

        #1. Search all video chunks
        video_chunks = glob.glob(os.path.join(folder_path, "chunk-stream0-*.m4s"))
        if not video_chunks: return None 

        #2. Extract chunk numbers
        v_nums = []
        for c in video_chunks:
            # Check that the chunk is not empty (0 bytes = crash)
            if os.path.getsize(c) > 0:
                match = re.search(r'chunk-stream0-(\d+)\.m4s', os.path.basename(c))
                if match: v_nums.append(int(match.group(1)))

        if not v_nums: return None

        v_start = min(v_nums) 
        v_count = len(v_nums)
        duration_sec = v_count * 3.0 

        #3. Do the same for sound, but with strict checks
        a_start = v_start
        has_audio = False
        init_a = os.path.join(folder_path, "init-stream1.m4s")
        audio_chunks = glob.glob(os.path.join(folder_path, "chunk-stream1-*.m4s"))

        if audio_chunks and os.path.exists(init_a) and os.path.getsize(init_a) > 100:
            a_nums = []
            for c in audio_chunks:
                if os.path.getsize(c) > 0:
                    match = re.search(r'chunk-stream1-(\d+)\.m4s', os.path.basename(c))
                    if match: a_nums.append(int(match.group(1)))
            if a_nums:
                a_start = min(a_nums)
                has_audio = True

        # 4. Building Perfect XML with independent presentationTimeOffsets!
        # Video timescale is 1000, duration 3000
        v_offset = (v_start - 1) * 3000
        
        audio_block = ""
        if has_audio:
            # Audio timescale in Steam is ALWAYS 48000, duration 144000!
            a_offset = (a_start - 1) * 144000
            audio_block = f"""
            <AdaptationSet id="1" contentType="audio" segmentAlignment="true">
              <Representation id="1" bandwidth="192000" mimeType="audio/mp4">
                <SegmentTemplate presentationTimeOffset="{a_offset}" timescale="48000" duration="144000" startNumber="{a_start}" initialization="init-stream1.m4s" media="chunk-stream1-$Number%05d$.m4s" />
              </Representation>
            </AdaptationSet>"""

        mpd_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" profiles="urn:mpeg:dash:profile:isoff-live:2011" type="static" mediaPresentationDuration="PT{duration_sec}S">
  <Period id="0" start="PT0.000S">
    <AdaptationSet id="0" contentType="video" segmentAlignment="true">
      <Representation id="0" bandwidth="10000000" mimeType="video/mp4">
        <SegmentTemplate presentationTimeOffset="{v_offset}" timescale="1000" duration="3000" startNumber="{v_start}" initialization="init-stream0.m4s" media="chunk-stream0-$Number%05d$.m4s" />
      </Representation>
    </AdaptationSet>{audio_block}
  </Period>
</MPD>"""

        # 5. Save this miracle in a folder
        recovered_path = os.path.join(folder_path, "session_recovered.mpd")
        try:
            with open(recovered_path, 'w', encoding='utf-8') as f:
                f.write(mpd_xml.strip())
            logging.info(f"Recovered orphaned clip at {recovered_path}")
            return recovered_path
        except Exception as e:
            logging.error(f"Failed to write recovered MPD: {e}")
            return None
    
    def get_game_name(self, app_id):
        """ Smart name retrieval. JSON first, then Steam """
        app_id = str(app_id) 
        
        #1: Check our evergreen games.json file
        if app_id in self.game_names_cache:
            return self.game_names_cache[app_id]
            
        # 2. If the game is not there, go to Steam ONCE
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
            response = requests.get(url, timeout=3)
            data = response.json()
            if data and app_id in data and data[app_id].get("success"):
                game_name = data[app_id]["data"]["name"]
                
                # Remember FOREVER =)
                self.game_names_cache[app_id] = game_name
                self.save_json_cache() 
                
                return game_name
        except: pass
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
        """ Reads the games.json file to avoid tweaking Steam for names. """
        if os.path.exists(self.json_cache_path):
            try:
                with open(self.json_cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: return {}
        return {}

    def save_json_cache(self):
        """ Saves new game names to a file permanently. """
        try:
            with open(self.json_cache_path, 'w', encoding='utf-8') as f:
                json.dump(self.game_names_cache, f, ensure_ascii=False, indent=4)
        except: pass
    
    def load_user_settings(self):
        """ Loads user preferences, like the last used clips folder """
        settings_path = os.path.join(self.cache_dir, "settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: pass
        return {}

    def save_user_settings(self, key, value):
        """ Saves a specific preference to the settings file permanently """
        settings_path = os.path.join(self.cache_dir, "settings.json")
        settings = self.load_user_settings()
        settings[key] = value
        try:
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
        except: pass
    
    def get_game_icon(self, app_id):
        """ Scraper + API Fallback + VIP (for trash 2) for test"""
        app_id = str(app_id)
        
        # 1. RAM checking
        if app_id in self.game_icons_cache:
            return self.game_icons_cache[app_id]

        # 2. Check the cache folder on the disk
        icon_path = os.path.join(self.cache_dir, f"{app_id}.jpg")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            icon = QIcon(pixmap)
            self.game_icons_cache[app_id] = icon
            return icon
        
        # To avoid being tracked by a bot bruh
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'
        }
        
        icon_url = None

        # 3. VIP entrance for Trash 2 (CS2)
        if app_id == "730":
            icon_url = "https://shared.fastly.steamstatic.com/community_assets/images/apps/730/8dbc71957312bbd3baea65848b545be9eae2a355.jpg"
            
        # 4. Parse the latest community page
        if not icon_url:
            try:
                hub_url = f"https://steamcommunity.com/app/{app_id}"
                hub_response = requests.get(hub_url, headers=headers, timeout=5)
                if hub_response.status_code == 200:
                    # We are looking for any link to a square icon with a hash
                    regex = r'(https://[^"\'<>]*?images/apps/' + app_id + r'/[a-fA-F0-9]{32,40}\.jpg)'
                    match = re.search(regex, hub_response.text)
                    if match:
                        icon_url = match.group(1)
            except: pass

        # 5. Backup Plan. Steamcmd API (If the page is restricted)
        if not icon_url:
            try:
                info_url = f"https://api.steamcmd.net/v1/info/{app_id}"
                info_response = requests.get(info_url, headers=headers, timeout=7)
                if info_response.status_code == 200:
                    data = info_response.json().get("data", {}).get(app_id, {}).get("common", {})
                    icon_hash = data.get("clienticon") or data.get("icon")
                    if icon_hash:
                        icon_url = f"https://shared.fastly.steamstatic.com/community_assets/images/apps/{app_id}/{icon_hash}.jpg"
            except: pass

        # 6. Download the image
        if icon_url:
            try:
                img_response = requests.get(icon_url, headers=headers, timeout=5)
                if img_response.status_code == 200:
                    with open(icon_path, 'wb') as f:
                        f.write(img_response.content)
                        
                    pixmap = QPixmap(icon_path)
                    icon = QIcon(pixmap)
                    self.game_icons_cache[app_id] = icon
                    return icon
                else:
                    print(f"[!] The image was found, but Steam gave out {img_response.status_code} (broken link) for {app_id}")
            except Exception as e:
                print(f"[!] Error downloading image for {app_id}: {e}")
        else:
            print(f"[!] We couldn't find a link to the icon at all {app_id} in no way")
            
        return QIcon()
    
    def get_clip_size_and_duration(self, clip_path, mpd_content):
        """ Calculates the clip folder weight and parses the duration from MPD """
        # 1. Calculate the size of all files in the clip folder
        total_bytes = 0
        for dirpath, _, filenames in os.walk(clip_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_bytes += os.path.getsize(fp)
        
        # Convert to Mb or Gig
        size_mb = total_bytes / (1024 * 1024)
        if size_mb >= 1000:
            size_str = f"{size_mb / 1024:.2f} GB"
        else:
            size_str = f"{size_mb:.1f} MB"

        # 2. Find the time in session.mpd
        duration_str = "Unknown"
        time_match = re.search(r'mediaPresentationDuration="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"', mpd_content)
        
        if time_match:
            hours = int(time_match.group(1)) if time_match.group(1) else 0
            minutes = int(time_match.group(2)) if time_match.group(2) else 0
            seconds = float(time_match.group(3)) if time_match.group(3) else 0.0

            self.current_clip_duration_sec = (hours * 3600) + (minutes * 60) + seconds
            
            # Format at 00:00:00
            duration_str = f"{hours:02d}:{minutes:02d}:{int(seconds):02d}"
        
        self.current_clip_duration_str = duration_str 
        return size_str, duration_str
    
    def get_fps_from_mpd(self, mpd_path):
        """ extract FPS directly from the session.mpd manifest via ffprobe """
        ffprobe_exe = get_resource_path("ffprobe.exe")
        if not os.path.exists(ffprobe_exe):
            return 60 # Fallback if ffprobe is not found
            
        try:
            # Feed ffprobe the session.mpd file itself! It will find the necessary pieces on its own.
            cmd = f'"{ffprobe_exe}" -v error -select_streams v:0 -show_entries stream=avg_frame_rate -of default=noprint_wrappers=1:nokey=1 "{mpd_path}"'
            
            creation_flags = 0x08000000 if sys.platform == "win32" else 0
            
            output = subprocess.check_output(cmd, shell=False, creationflags=creation_flags, stderr=subprocess.DEVNULL, text=True).strip()
            
            if '/' in output:
                num, den = output.split('/')
                fps = round(float(num) / float(den))
            elif output:
                fps = round(float(output))
            else:
                fps = 60
                
            return int(fps)
        except:
            return 60
    
    def get_audio_bitrate_from_mpd(self, mpd_path):
        """ extract audio bitrate from the session.mpd manifest via ffprobe """
        ffprobe_exe = get_resource_path("ffprobe.exe")
        if not os.path.exists(ffprobe_exe): return 192
        try:
            cmd = f'"{ffprobe_exe}" -v error -select_streams a:0 -show_entries stream=bit_rate -of default=noprint_wrappers=1:nokey=1 "{mpd_path}"'
            creation_flags = 0x08000000 if sys.platform == "win32" else 0
            output = subprocess.check_output(cmd, shell=False, creationflags=creation_flags, stderr=subprocess.DEVNULL, text=True).strip()
            if output and output.isdigit():
                return int(output) // 1000 # Convert bps to kbps
            return 192
        except:
            return 192
    
    def detect_gpu_and_set_encoder(self):
        """ Detects your PC hardware and suggests a suitable codec. """
        if not hasattr(self.ui, 'combo_encoder'): return
        self.ui.combo_encoder.clear()
        
        ffmpeg_exe = get_resource_path("ffmpeg.exe")
        if not os.path.exists(ffmpeg_exe):
            self.ui.combo_encoder.addItem("CPU (Software)", "libx264")
            return

        encoders_to_test = [
            ("CPU (Software)", "libx264", "libx265"),
            ("NVENC (NVIDIA GPU)", "h264_nvenc", "hevc_nvenc"),
            ("AMF (AMD GPU)", "h264_amf", "hevc_amf"),
            ("QuickSync (Intel GPU)", "h264_qsv", "hevc_qsv")
        ]
        
        logging.info("Starting silent hardware encoder probe...")
        creation_flags = 0x08000000 if sys.platform == "win32" else 0

        for display_name, base_code, test_code in encoders_to_test:
            # Increased the size to 640x480 so that NVENC doesn't show off
            cmd = [
                ffmpeg_exe,
                "-y", "-f", "lavfi", "-i", "color=black:s=640x480:r=1",
                "-frames:v", "1",
                "-pix_fmt", "yuv420p",
                "-c:v", test_code
            ]
            
            if "nvenc" in test_code:
                cmd.extend(["-preset", "p1"])
            elif "qsv" in test_code:
                cmd.extend(["-preset", "veryfast"])
                
            cmd.extend(["-f", "null", "-"])
            
            try:
                # Now we capture stderr (the error text) to read it!
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=creation_flags
                )
                
                if result.returncode == 0:
                    self.ui.combo_encoder.addItem(display_name, base_code)
                    logging.info(f"[PROBE] Success: {test_code} is supported.")
                else:
                    # Let's decipher what exactly he cursed at
                    error_output = result.stderr.decode('utf-8', errors='ignore').strip()
                    # Take the last couple of lines from the error, that's usually the gist of it
                    last_lines = " | ".join(error_output.split('\n')[-3:]) 
                    logging.info(f"[PROBE] Failed: {test_code}. Reason: {last_lines}")
            except Exception as e:
                logging.error(f"[PROBE] Error testing {test_code}: {e}")

        if self.ui.combo_encoder.count() == 0:
            self.ui.combo_encoder.addItem("CPU (Software)", "libx264")
            
        if self.ui.combo_encoder.count() > 1:
            self.ui.combo_encoder.setCurrentIndex(1)
        else:
            self.ui.combo_encoder.setCurrentIndex(0)
    
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
        
        # --- 1. SAVE CURRENT USER SELECTION ---
        current_quality = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else ""
        current_fps = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else ""
        current_bitrate = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else ""
            
        # Extract the FULL path (for FFmpeg)
        clip_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
        
        # Extract ONLY the folder NAME (for example, bg_3513350_20260508) for the text field
        clip_folder_name = os.path.basename(clip_path)

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
        """ Refreshes lists and freezes settings if Original is selected. """
        if not hasattr(self.ui, 'combo_bitrate') or not hasattr(self.ui, 'combo_quality'):
            return 

        self.ui.combo_bitrate.clear()
        quality_text = self.ui.combo_quality.currentText()

        if "Original" in quality_text:
            # We write the bitrate beautifully
            if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                self.ui.combo_bitrate.addItem(f"~{int(self.current_orig_bitrate)} Mbps (Original Copy)")
            else:
                self.ui.combo_bitrate.addItem("Original Bitrate (Copy)")
                
            self.ui.combo_bitrate.setEnabled(False) 
            
            # Freeze FPS, Codec, and Encoder (because they are ignored when copying)
            if hasattr(self.ui, 'combo_fps'):
                self.ui.combo_fps.setCurrentIndex(0) # Force it to Original
                self.ui.combo_fps.setEnabled(False)
            if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(False)
            if hasattr(self.ui, 'combo_encoder'): self.ui.combo_encoder.setEnabled(False)
            
            return

        self.ui.combo_bitrate.setEnabled(True) 
        
        # Unfreeze the remaining menus so they can be edited
        if hasattr(self.ui, 'combo_fps'): self.ui.combo_fps.setEnabled(True)
        if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.setEnabled(True)
        if hasattr(self.ui, 'combo_encoder'): self.ui.combo_encoder.setEnabled(True)
        
        # Extract the height from a string ("1080p")
        match = re.search(r'^(\d+)p', quality_text)
        if not match: return
            
        res_key = f"{match.group(1)}p"
        added_any = False
        
        # We go through Steam presets and add only those that make sense
        for quality_level in ["Ultra", "High", "Medium", "Low"]:
            if res_key in self.steam_bitrate_presets.get(quality_level, {}):
                preset_bitrate = self.steam_bitrate_presets[quality_level][res_key]
                
                # Add a preset only if it is not much higher than the original bitrate
                if getattr(self, 'current_orig_bitrate', 0) == 0 or preset_bitrate <= (self.current_orig_bitrate + 5):
                    self.ui.combo_bitrate.addItem(f"{quality_level} - {preset_bitrate} Mbps")
                    added_any = True
        
        # If the original was very bad, add at least Low for rendering
        if not added_any and res_key in self.steam_bitrate_presets["Low"]:
            lowest_bitrate = self.steam_bitrate_presets["Low"][res_key]
            self.ui.combo_bitrate.addItem(f"Low - {lowest_bitrate} Mbps")
        
        self.ui.combo_bitrate.insertSeparator(self.ui.combo_bitrate.count())
        self.ui.combo_bitrate.addItem("⚙️ Custom Bitrate...")
    
    def refresh_slider_if_needed(self):
        """ Updates the monkeymeter if the user has switched FPS """
        if hasattr(self.ui, 'size_slider') and self.ui.size_slider.isVisible():
            self.on_slider_moved(self.ui.size_slider.value())

        
    def update_final_setup(self):
        """Dynamically updates the Detailed Summary, Size, and Save Path."""
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            if hasattr(self.ui, 'label_short_summary'):
                self.ui.label_short_summary.setText("Select a clip to begin...")
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
            # --- ВОТ ЭТА СТРОЧКА ПОТЕРЯЛАСЬ! ВЕРНИ ЕЁ! ---
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
                    video_bitrate = float(match.group(1)) * fps_multiplier 
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
            
            # Show auto-scaled resolution in the UI!
            scale_h = getattr(self, 'custom_target_height', -1)
            res_str = f"Auto: {scale_h}p" if scale_h > 0 else "Original"
            
            clean_mbps = int(round(val_mbps))
            video_bitrate_display = f"{clean_mbps} Mbps ({res_str})"
        elif "Custom" in bitrate_text:
            try:
                val = float(self.input_custom_vbitrate.text().replace(',', '.'))
                val = max(0.1, min(val, orig_v_bitrate))
                video_bitrate_display = f"⚙️ {val:.1f} Mbps"
            except:
                video_bitrate_display = f"{orig_v_bitrate:.1f} Mbps"
        elif "Original" in bitrate_text:
            video_bitrate_display = f"{orig_v_bitrate:.1f} Mbps"
        else:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match: 
                video_bitrate_display = f"{match.group(1)} Mbps"

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

        # 6. Short Summary ABOVE Ready (With dynamically added Video Bitrate)
        q_word = quality.split()[0] if quality.split() else "Unknown"
        enc_word = encoder.split()[0] if encoder.split() else "Unknown"
        
        if audio_only:
            short_text = f"AUDIO ONLY: {audio_format} {audio_bitrate_clean} - {final_filename}"
        elif mute_audio:
            short_text = f"VIDEO ONLY: {q_word}, {fps_display}, {video_bitrate_display}, {codec}, {enc_word}, {final_filename}"
        else:
            short_text = f"{q_word}, {fps_display}, {video_bitrate_display}, {codec}, {enc_word}, {audio_format} {audio_bitrate_clean} - {final_filename}"
            
        if hasattr(self.ui, 'label_short_summary'):
            self.ui.label_short_summary.setText(short_text)
            
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
            
        ffmpeg_exe = get_resource_path("ffmpeg.exe")
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
                video_bitrate = f"{int(val * 1000)}k"
            except: video_bitrate = f"{int(orig_v_bitrate * 1000)}k"
        elif "Original" not in bitrate_text:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match:
                base_bitrate = float(match.group(1))
                final_bitrate = int(base_bitrate * fps_multiplier * 1000)
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
        """ Ironclad math for Discord (Protection against FFmpeg overshoot AND crazy user inputs) """
        duration = self.get_effective_duration() 
        if duration <= 0: return
        
        orig_bitrate = getattr(self, 'current_orig_bitrate', 10)
        orig_mb = int((orig_bitrate * duration) / 8)
        if orig_mb < 1: orig_mb = 1
        
        actual_target_mb = target_mb
        
        # Soft clamping based on user intent
        if is_custom:
            if target_mb < 1: actual_target_mb = 1
            elif target_mb > orig_mb: actual_target_mb = orig_mb
        elif is_lossless:
            actual_target_mb = orig_mb # Force mathematically correct lossless MB
        
        audio_text = self.ui.combo_audio_bitrate.currentText() if hasattr(self.ui, 'combo_audio_bitrate') else "192 kbps"
        audio_kbps = 192
        if hasattr(self.ui, 'check_mute_audio') and self.ui.check_mute_audio.isChecked():
            audio_kbps = 0
        elif "Custom" in audio_text and hasattr(self, 'input_custom_abitrate'):
            try: audio_kbps = int(self.input_custom_abitrate.text())
            except: audio_kbps = getattr(self, 'current_orig_audio_bitrate', 192)
        else:
            match = re.search(r'(\d+)', audio_text)
            if match: audio_kbps = int(match.group(1))

        # --- THE ULTIMATE HARD CLAMP ---
        total_safe_kbps = ((actual_target_mb * 8192) / duration) * 0.96 
        target_video_kbps = int(total_safe_kbps - audio_kbps)
        
        # CRITICAL FIX: Never allow the bitrate to exceed the original video bitrate!
        max_allowed_kbps = int(orig_bitrate * 1000)
        if target_video_kbps > max_allowed_kbps:
            target_video_kbps = max_allowed_kbps
            # Reverse math: if we capped the kbps, we MUST shrink the MB to match reality!
            actual_target_mb = int(((target_video_kbps + audio_kbps) / 0.96 * duration) / 8192)
            if actual_target_mb < 1: actual_target_mb = 1
            
        if target_video_kbps < 100: target_video_kbps = 100 

        # FPS modifiers
        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        if "Custom" in fps_text and hasattr(self, 'input_custom_fps'):
            try: selected_fps = int(self.input_custom_fps.text())
            except: selected_fps = getattr(self, 'current_orig_fps', 60)
        else:
            try: selected_fps = int(re.search(r'(\d+)', fps_text).group(1))
            except: selected_fps = getattr(self, 'current_orig_fps', 60)

        effective_kbps = target_video_kbps
        if selected_fps <= 30: effective_kbps *= 1.5
        if selected_fps <= 15: effective_kbps *= 2.0

        # Smart Scaling
        target_h = -1 
        if is_lossless:
            color, warning = "#00ff00", "Lossless (Quality as original)"
        elif effective_kbps >= 10000:
            color, warning = "#00ff00", "1080p+ (Good)"
        elif effective_kbps >= 5000:
            color, warning = "#aaff00", "720p (Mid, but good)"
            target_h = 720
        elif effective_kbps >= 2000:
            color, warning = "#ffff00", "Auto-scaled to 480p to save pixels"
            target_h = 480
        elif effective_kbps >= 800:
            color, warning = "#ff8800", "Auto-scaled to 360p to save pixels"
            target_h = 360
        else:
            color, warning = "#ff4444", "Auto-scaled to 240p (VHS Quality)"
            target_h = 240

        self.custom_target_height = target_h 
            
        custom_tag = "⚙️ Custom " if is_custom else ""
        text = f"Target: <b>{custom_tag}{actual_target_mb} MB</b> | Safe Bitrate: {target_video_kbps} kbps<br>Quality: <span style='color:{color}'><b>{warning}</b></span>"
        
        self.ui.label_target_size.setText(text)
        self.custom_target_bitrate = target_video_kbps 
        self.update_final_setup()

        
        # 1. Subtract audio
        audio_text = self.ui.combo_audio_bitrate.currentText() if hasattr(self.ui, 'combo_audio_bitrate') else "192 kbps"
        audio_kbps = 192
        if hasattr(self.ui, 'check_mute_audio') and self.ui.check_mute_audio.isChecked():
            audio_kbps = 0
        elif "Custom" in audio_text and hasattr(self, 'input_custom_abitrate'):
            try: audio_kbps = int(self.input_custom_abitrate.text())
            except: audio_kbps = getattr(self, 'current_orig_audio_bitrate', 192)
        else:
            match = re.search(r'(\d+)', audio_text)
            if match: audio_kbps = int(match.group(1))

        # 2. STRICT MATH considering the capped size
        total_safe_kbps = ((actual_target_mb * 8192) / duration) * 0.96 
        target_video_kbps = int(total_safe_kbps - audio_kbps)
        if target_video_kbps < 100: target_video_kbps = 100 

        # 3. Smart monkeymeter & AUTO-SCALING 
        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        if "Custom" in fps_text and hasattr(self, 'input_custom_fps'):
            try: selected_fps = int(self.input_custom_fps.text())
            except: selected_fps = getattr(self, 'current_orig_fps', 60)
        else:
            try: selected_fps = int(re.search(r'(\d+)', fps_text).group(1))
            except: selected_fps = getattr(self, 'current_orig_fps', 60)

        effective_kbps = target_video_kbps
        if selected_fps <= 30: effective_kbps *= 1.5
        if selected_fps <= 15: effective_kbps *= 2.0

        # --- SMART AUTO-SCALING LOGIC ---
        target_h = -1 
        
        if is_lossless:
            color, warning = "#00ff00", "Lossless (Quality as original)"
        elif effective_kbps >= 10000:
            color, warning = "#00ff00", "1080p+ (Good)"
        elif effective_kbps >= 5000:
            color, warning = "#aaff00", "720p (Mid, but good)"
            target_h = 720
        elif effective_kbps >= 2000:
            color, warning = "#ffff00", "Auto-scaled to 480p to save pixels"
            target_h = 480
        elif effective_kbps >= 800:
            color, warning = "#ff8800", "Auto-scaled to 360p to save pixels"
            target_h = 360
        else:
            color, warning = "#ff4444", "Auto-scaled to 240p (VHS Quality)"
            target_h = 240

        self.custom_target_height = target_h
            
        custom_tag = "⚙️ Custom " if is_custom else ""
        text = f"Target: <b>{custom_tag}{actual_target_mb} MB</b> | Safe Bitrate: {target_video_kbps} kbps<br>Quality: <span style='color:{color}'><b>{warning}</b></span>"
        
        self.ui.label_target_size.setText(text)
        self.custom_target_bitrate = target_video_kbps 
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
        
        # Reset the buttons to their original state.
        if not getattr(self, '_is_rendering', False):
            self.ui.btn_start.setEnabled(True)
            
        self.update_final_setup()
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'): 
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.setText("Pause")
            
        # Show the result to the user
        if success:
            logging.info("=== RENDER SUCCESS ===")
            self.set_status("Success")
            
            # A CUSTOM SUCCESS WINDOW
            msg_box = QMessageBox(self.ui)
            msg_box.setWindowTitle("Success!")
            msg_box.setText(f"Clip successfully saved to:\n{output_file}")
            msg_box.setIcon(QMessageBox.Information)
            
            # Add your own buttons
            btn_folder = msg_box.addButton("Open Folder", QMessageBox.ActionRole)
            btn_play = msg_box.addButton("Play Video", QMessageBox.ActionRole)
            btn_ok = msg_box.addButton(QMessageBox.Ok)
            
            # Launch the window and wait for the user to click
            msg_box.exec()
            
            
            if msg_box.clickedButton() == btn_folder:
                self.open_rendered_folder(output_file)
                
            elif msg_box.clickedButton() == btn_play:
                import os
                file_path = os.path.abspath(output_file)
                os.startfile(file_path)

            if hasattr(self.ui, 'label_status'):
                self.ui.label_status.setText("Ready")
            if hasattr(self.ui, 'progress_render'):
                self.ui.progress_render.setValue(0)
            
            # Unlock the start button if it was locked
            if hasattr(self.ui, 'btn_start'):
                self.ui.btn_start.setEnabled(True)
                
        elif "cancelled by user" in error_msg:
            logging.warning("=== RENDER CANCELED ===")
            self.set_status("Cancelled")
            QMessageBox.information(self.ui, "Cancelled", "Render was cancelled.")
            self.set_status("Ready")
            
        else:
            logging.error(f"=== RENDER ERROR === \n{error_msg}")
            self.set_status("Error!") 
            
            msg_box = QMessageBox(self.ui)
            msg_box.setWindowTitle("Render Error")
            # We trim the error text so that the window doesn't stretch to fill the entire screen.
            short_error = error_msg[-500:] if len(error_msg) > 500 else error_msg
            msg_box.setText(f"Failed to render video!\n\nReason:\n{short_error}")
            msg_box.setIcon(QMessageBox.Critical)
            
            #LOG BUTTON LIVES ONLY HERE
            btn_log = msg_box.addButton("📄 Open Log File", QMessageBox.ActionRole)
            btn_ok = msg_box.addButton(QMessageBox.Ok)
            
            msg_box.exec()
            
            # Hardware opening of logs via Notepad
            if msg_box.clickedButton() == btn_log:
                import os
                import subprocess
                if hasattr(self, 'current_log_file') and os.path.exists(self.current_log_file):
                    log_path = os.path.abspath(self.current_log_file)
                    subprocess.Popen(["notepad.exe", log_path])
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

    

# BACKGROUND RENDER THREAD (PROTECTS UI FROM FREEZING)
class RenderThread(QThread):
    progress_signal = Signal(str)  
    finished_signal = Signal(bool, str, str) 

    def __init__(self, mpd_paths, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate, fps_text, audio_only, mute_audio, audio_format, audio_bitrate_kbps, target_scale_h=-1, trim_start_sec=-1.0, trim_duration_sec=-1.0):
        super().__init__()
        self.target_scale_h = target_scale_h 
        self.trim_start_sec = trim_start_sec
        self.trim_duration_sec = trim_duration_sec
        self.mpd_paths = mpd_paths
        self.quality_text = quality_text
        self.output_file = output_file
        self.ffmpeg_exe = ffmpeg_exe
        self.save_dir = save_dir
        
        self.selected_encoder = selected_encoder
        self.video_bitrate = video_bitrate
        self.fps_text = fps_text
        
        self.audio_only = audio_only
        self.mute_audio = mute_audio
        self.audio_format = audio_format
        self.audio_bitrate_kbps = audio_bitrate_kbps
        
        self.target_scale_h = target_scale_h
        
        self.is_cancelled = False
        self.is_paused = False
        self.current_process = None

    def cancel(self):
        """ Force kills the FFmpeg process. """
        self.is_cancelled = True
        if self.current_process:
            try:
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.current_process.pid)])
            except: pass

    def toggle_pause(self):
        """ Pauses or resumes FFmpeg at the OS level. """
        if not self.current_process:
            return False
            
        self.is_paused = not self.is_paused
        try:
            p = psutil.Process(self.current_process.pid)
            if self.is_paused: p.suspend()
            else: p.resume() 
        except:
            self.is_paused = not self.is_paused
            
        return self.is_paused

    def run(self):
        """ Main thread loop """
        temp_files = []
        concat_file = None
        try:
            creation_flags = 0x08000000 if sys.platform == "win32" else 0
            # Get the target extension (.mp4, .mp3, .aac) from the final output file
            _, ext = os.path.splitext(self.output_file)
            
            # STEP 1: Render each .mpd part
            for idx, mpd in enumerate(self.mpd_paths):
                if self.is_cancelled:
                    raise Exception("Render cancelled by user.")
                    
                # Use the correct extension for temporary files
                temp_mp4 = os.path.join(self.save_dir, f"temp_steempeg_part_{idx}{ext}")
                temp_files.append(temp_mp4)
                
                self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. (0%)")
                
                # Fix paths for FFmpeg (replace backslashes with forward slashes)
                safe_mpd = mpd.replace('\\', '/')

                fps_arg = ""
                if hasattr(self, 'fps_text') and "Original" not in self.fps_text:
                    match_fps = re.search(r'(\d+)', self.fps_text)
                    if match_fps:
                        fps_arg = f"-r {match_fps.group(1)} "
                

                
                
                # --- FFMPEG COMMAND GENERATION ---
                
                # 0. Inject Trim Arguments BEFORE the input for maximum seeking speed!
                trim_args = ""
                if self.trim_start_sec >= 0 and self.trim_duration_sec > 0:
                    trim_args = f"-ss {self.trim_start_sec:.3f} -t {self.trim_duration_sec:.3f} "
                
                # 1. Prepare the audio arguments
                if self.mute_audio:
                    base_audio = "-an" 
                else:
                    a_codec = "libmp3lame" if self.audio_format == "MP3" else "aac"
                    base_audio = f"-c:a {a_codec} -b:a {self.audio_bitrate_kbps}"

                # 2. Construct the final command based on video settings
                if self.audio_only:
                    cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vn {base_audio} -y "{temp_mp4}"'
                    
                elif "Original" in self.quality_text and "Target File" not in self.quality_text:
                    if self.mute_audio:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c:v copy -an -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c copy -y "{temp_mp4}"'
                        
                elif "Target File Size" in self.quality_text:
                    bitrate_val = int(self.video_bitrate.replace('k', ''))
                    bufsize = f"{bitrate_val * 2}k" 
                    
                    if self.target_scale_h > 0:
                        scale_filter = f"scale=-2:min(ih\\,{self.target_scale_h})"
                    else:
                        scale_filter = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
                    
                    cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vf "{scale_filter}" {fps_arg}-c:v {self.selected_encoder} -b:v {self.video_bitrate} -maxrate {self.video_bitrate} -bufsize {bufsize} {base_audio} -y "{temp_mp4}"'
                    
                else:
                    match = re.search(r'^(\d+)p', self.quality_text)
                    if match:
                        target_height = match.group(1)
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vf scale=-2:{target_height} {fps_arg}-c:v {self.selected_encoder} -b:v {self.video_bitrate} {base_audio} -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c copy -y "{temp_mp4}"'

                logging.debug(f"FFmpeg cmd for part {idx}: {cmd}")

                # Launch FFmpeg
                self.current_process = subprocess.Popen( 
                    cmd, shell=False, cwd=os.path.dirname(mpd),
                    creationflags=creation_flags, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', errors='ignore'
                )

                total_duration = 0
                last_ffmpeg_output = []

                # Read FFmpeg logs in real time
                for line in self.current_process.stdout:
                    if self.is_cancelled:
                        break
                        
                    clean_line = line.strip()
                    if clean_line:
                        # Collect the last 5 lines of logs for output in case of an error
                        logging.debug(f"[FFmpeg] {clean_line}")
                        last_ffmpeg_output.append(clean_line)
                        if len(last_ffmpeg_output) > 5:
                            last_ffmpeg_output.pop(0)
                            
                    # Parse the total duration of the video
                    if total_duration == 0:
                        dur_match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                        if dur_match:
                            h, m, s = float(dur_match.group(1)), float(dur_match.group(2)), float(dur_match.group(3))
                            total_duration = h * 3600 + m * 60 + s

                    # Parse the current render time to calculate percentages
                    time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                    if time_match and total_duration > 0:
                        h, m, s = float(time_match.group(1)), float(time_match.group(2)), float(time_match.group(3))
                        current_time = h * 3600 + m * 60 + s
                        percent = int((current_time / total_duration) * 100)
                        self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. ({min(percent, 100)}%)")

                self.current_process.wait()
                
                # Post-process checks
                if self.is_cancelled:
                    raise Exception("Render cancelled by user.")
                    
                if self.current_process.returncode != 0:
                    error_details = "\n".join(last_ffmpeg_output)

                    logging.error(f"FFmpeg ERROR in part {idx}:\n{error_details}")


                    raise Exception(f"Failed to render part {idx+1}.\nFFmpeg error:\n{error_details}")

            # Final check before gluing
            if self.is_cancelled:
                raise Exception("Render cancelled by user.")

            # --- FIX FOR 0 BYTES (BYPASS CONCAT FOR SINGLE FILES) ---
            # STAGE 2: Merging all rendered parts into one file
            if len(temp_files) == 1:
                # 99% of cases: No need to use the buggy 'concat' demuxer for a single file!
                self.progress_signal.emit("Finalizing...")
                import shutil
                
                # Directly move/rename the perfectly rendered temp file to the final destination!
                if os.path.exists(self.output_file):
                    os.remove(self.output_file)
                shutil.move(temp_files[0], self.output_file)
                
                self.finished_signal.emit(True, "", self.output_file)
            else:
                self.progress_signal.emit("Merging all parts...")
                concat_file = os.path.join(self.save_dir, "temp_concat_list.txt")
                
                # Create a text file with a list of chunks for FFmpeg
                with open(concat_file, "w", encoding="utf-8") as f:
                    for tmp in temp_files:
                        safe_path = tmp.replace('\\', '/')
                        f.write(f"file '{safe_path}'\n")

                # Run the merge without compression (-c copy)
                self.current_process = subprocess.Popen(
                    f'"{self.ffmpeg_exe}" -f concat -safe 0 -i "{concat_file}" -c copy -y "{self.output_file}"', 
                    shell=False, cwd=self.save_dir,
                    creationflags=creation_flags, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                self.current_process.wait()

                if self.is_cancelled:
                    raise Exception("Render cancelled by user.")

                if self.current_process.returncode == 0:
                    self.finished_signal.emit(True, "", self.output_file) # success
                else:
                    self.finished_signal.emit(False, "Merge failed.", "")

        except Exception as e:
            self.finished_signal.emit(False, str(e), "") # error
            
        finally:
            # STEP 3: CLEANING. Remove all temporary debris
            if concat_file and os.path.exists(concat_file):
                try: os.remove(concat_file)
                except: pass
            for tmp in temp_files:
                if os.path.exists(tmp):
                    try: os.remove(tmp)
                    except: pass

# BACKGROUND DOWNLOAD THREAD FOR UPDATER
class UpdateDownloadThread(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool, str, str)

    def __init__(self, url, save_dir, asset_name):
        super().__init__()
        self.url = url
        self.save_dir = save_dir
        self.asset_name = asset_name
        self.is_cancelled = False
        # Download the file with the .tmp appendix to avoid breaking anything
        self.dest_path = os.path.join(save_dir, f"{asset_name}.tmp")


    def cancel(self):
        self.is_cancelled = True

    def run(self):
        import requests
        import time
        try:
            response = requests.get(self.url, stream=True, timeout=10)
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            
            downloaded = 0
            start_time = time.time()
            
            with open(self.dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.is_cancelled: break
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            
                            # Counting megabytes and speed
                            elapsed = time.time() - start_time
                            speed_mbps = (downloaded / 1024 / 1024) / elapsed if elapsed > 0 else 0
                            down_mb = downloaded / 1024 / 1024
                            total_mb = total_size / 1024 / 1024
                            
                            label_text = f"Downloading update...\n{down_mb:.1f} MB / {total_mb:.1f} MB ({speed_mbps:.1f} MB/s)"
                            
                            # TO UI
                            self.progress_signal.emit(percent, label_text)
                            
            if self.is_cancelled:
                if os.path.exists(self.dest_path): os.remove(self.dest_path)
                self.finished_signal.emit(False, "", "")
            else:
                # Pass the path n the original name (for example.. smpeg11.exe)
                self.finished_signal.emit(True, self.dest_path, self.asset_name)
        except Exception as e:
            self.finished_signal.emit(False, str(e), "")

from PySide6.QtWidgets import QLabel

class ElidedLabel(QLabel):
    """ A smart label that dynamically elides text (adds ...) based on window size """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""

    def setText(self, text):
        self._full_text = text
        super().setText(text) # Let Qt know the preferred size
        self.setToolTip(text) # MAGIC: Hover over the cut text to see the full path!
        self.update()

    def minimumSizeHint(self):
        # Allow the layout to gracefully shrink this widget
        from PySide6.QtCore import QSize
        return QSize(50, super().minimumSizeHint().height())

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter
        from PySide6.QtCore import Qt
        painter = QPainter(self)
        metrics = self.fontMetrics()
        

        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, self.width())
        
        painter.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, elided)

import tempfile
import shutil
import subprocess
import os
import hashlib
from PySide6.QtCore import QThread, Signal

# --- BACKGROUND WORKER: JIT THUMBNAIL SNIPER ---
import hashlib
import tempfile
import shutil
import subprocess
import os
import glob
from PySide6.QtCore import QThread, Signal

# --- BACKGROUND WORKER: THUMBNAIL BATCH GENERATOR (THE MATRIX 2.0) ---
class ThumbnailBatchThread(QThread):
    """ Generates all thumbnails in the background ONCE, using GPU. Lightning fast UI! """
    finished_generation = Signal(str) 

    def __init__(self, mpd_path, duration_sec, interval=3, parent=None):
        super().__init__(parent)
        self.mpd_path = mpd_path
        self.duration_sec = duration_sec
        self.interval = interval # <--- 3 SECONDS DYNAMIC INTERVAL
        
        # Cache Isolation Magic (Now includes the interval in the folder name!)
        path_hash = hashlib.md5(mpd_path.encode('utf-8')).hexdigest()[:10]
        self.thumb_dir = os.path.join(tempfile.gettempdir(), f"steempeg_batch_{path_hash}_{self.interval}s")
        os.makedirs(self.thumb_dir, exist_ok=True)

    def run(self):
        existing_files = glob.glob(os.path.join(self.thumb_dir, "thumb_*.jpg"))
        expected_count = int(self.duration_sec // self.interval)
        
        # If we have at least 90% of expected frames, skip generation!
        if len(existing_files) >= expected_count * 0.9:
            self.finished_generation.emit(self.thumb_dir)
            return

        shutil.rmtree(self.thumb_dir, ignore_errors=True)
        os.makedirs(self.thumb_dir, exist_ok=True)

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-hwaccel", "auto",       
            "-threads", "2",          
            "-i", self.mpd_path,
            "-vf", f"fps=1/{self.interval}", # <--- USES THE 3 SECOND INTERVAL
            "-q:v", "7",              
            "-s", "160x90",           
            os.path.join(self.thumb_dir, "thumb_%04d.jpg") 
        ]
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        subprocess.run(cmd, startupinfo=startupinfo)
        self.finished_generation.emit(self.thumb_dir)

from PySide6.QtWidgets import QLabel, QFrame, QVBoxLayout, QWidget
from PySide6.QtCore import Qt, QPoint

# --- FLOATING TIMELINE PREVIEW WIDGET ---
class ThumbnailPreviewWidget(QWidget):
    """ A floating tooltip-like widget that shows a video frame and time on hover. """
    def __init__(self, parent=None):
        super().__init__(parent)
        # Make the window a "ghost" (stays on top, no borders, doesn't steal focus)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # Stylish container frame
        self.frame = QFrame()
        self.frame.setStyleSheet("QFrame { background-color: #181818; border: 1px solid #333; border-radius: 6px; }")
        self.frame_layout = QVBoxLayout(self.frame)
        self.frame_layout.setContentsMargins(4, 4, 4, 4)
        self.frame_layout.setSpacing(4)

        # Thumbnail image placeholder
        self.img_label = QLabel("No Frame")
        self.img_label.setFixedSize(160, 90) # Perfect 16:9 ratio
        self.img_label.setStyleSheet("background-color: #000000; border-radius: 4px; color: #555;")
        self.img_label.setAlignment(Qt.AlignCenter)

        # Timecode label
        self.time_label = QLabel("00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("background-color: #2d2d2d; border-radius: 4px; padding: 2px; color: white; font-weight: bold; font-size: 11px;")

        self.frame_layout.addWidget(self.img_label)
        self.frame_layout.addWidget(self.time_label)
        self.layout.addWidget(self.frame)
        self.hide()
        
    def update_info(self, time_str, is_in_trim, hover_ms, thumb_dir):
        """ Updates UI and instantly loads the pre-generated image. """
        self.time_label.setText(time_str)
        
        if is_in_trim:
            self.time_label.setStyleSheet("background-color: #2d2d2d; border-radius: 4px; padding: 2px; color: #ffcc00; font-weight: bold; font-size: 11px;")
        else:
            self.time_label.setStyleSheet("background-color: #2d2d2d; border-radius: 4px; padding: 2px; color: white; font-weight: bold; font-size: 11px;")

        # --- INSTANT IMAGE LOADING ---
        from PySide6.QtGui import QPixmap
        import os
        
        if thumb_dir and os.path.exists(thumb_dir):
            sec = int(hover_ms // 1000)
            # Math: 0-2s -> thumb_0001, 3-5s -> thumb_0002 (3 SECOND INTERVAL)
            index = (sec // 3) + 1 
            img_path = os.path.join(thumb_dir, f"thumb_{index:04d}.jpg")
            
            if os.path.exists(img_path):
                self.img_label.setPixmap(QPixmap(img_path))
                return
                
        # If still generating in the background...
        self.img_label.setPixmap(QPixmap())
        self.img_label.setText("Generating...")

    def set_image(self, img_path):
        """ Called when the sniper successfully extracts the frame. """
        from PySide6.QtGui import QPixmap
        self.img_label.setPixmap(QPixmap(img_path))

import time
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor
from PySide6.QtCore import Qt, Signal, QTimer, QRect

class CustomTimelineWidget(QWidget):
    """
    Independent Timeline Engine (60 FPS Smooth) with Smart Trim Hitboxes
    """
    pause_requested = Signal()        
    seek_requested = Signal(int)      
    resume_requested = Signal()
    trim_changed = Signal(int, int) 

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40) 
        self.duration_ms = 0

        self.setMouseTracking(True)
        self.preview_widget = ThumbnailPreviewWidget()

        self.visual_ms = 0.0  
        self.target_ms = 0.0  
        self.vlc_last_update_time = time.time()
        
        # Playback states
        self.is_playing = False
        self.user_seek_lock_time = 0 
        
        # Trim states
        self.is_trim_mode = False
        self.trim_start_ms = 0.0
        self.trim_end_ms = 0.0
        
        # Dragging states ('none', 'playhead', 'trim_l', 'trim_r')
        # Notice: 'trim_body' is removed to allow clicking inside the yellow bar!
        self.drag_state = 'none'
        
        self.last_frame_time = time.time()
        
        # 60 FPS System Clock Engine
        self.fps_timer = QTimer(self)
        self.fps_timer.timeout.connect(self.process_60fps_frame)
        self.fps_timer.start(16) 
        
        # Colors
        self.track_color = QColor(255, 255, 255, 40)
        self.fill_color = QColor("#b29ae7")
        self.handle_color = QColor(255, 255, 255)
        
        self.trim_body_color = QColor(255, 204, 0, 80) 
        self.trim_handle_color = QColor(255, 204, 0) 

        self.setMouseTracking(True)
        self.hover_x = -1.0
        self.is_hovering = False

    def set_duration(self, duration_ms):
        self.duration_ms = max(1, duration_ms)

    def set_vlc_time(self, vlc_ms, is_playing):
        self.is_playing = is_playing
        # Dragging trim handles should not freeze the playback cursor.
        if self.drag_state == 'playhead': return
        
        if vlc_ms != self.target_ms:
            self.target_ms = float(vlc_ms)
            self.vlc_last_update_time = time.time()

    def enable_trim_mode(self):
        """ Activates trim mode and creates a default 10-second yellow bar """
        if self.duration_ms <= 0: return
        self.is_trim_mode = True
        
        # Default 10 seconds from current cursor
        self.trim_start_ms = self.visual_ms
        self.trim_end_ms = self.trim_start_ms + 10000.0
        
        # Clamp to bounds
        if self.trim_end_ms > self.duration_ms:
            self.trim_end_ms = self.duration_ms
            self.trim_start_ms = max(0.0, self.trim_end_ms - 10000.0)
            
        self.trim_changed.emit(int(self.trim_start_ms), int(self.trim_end_ms))
        self.update()

    def disable_trim_mode(self):
        """ Deactivates trim mode """
        self.is_trim_mode = False
        self.update()

    def process_60fps_frame(self):
        """ The Ultimate Smooth Engine: Driven by system clock, synced with MPV """
        now = time.time()
        delta_ms = (now - self.last_frame_time) * 1000.0
        self.last_frame_time = now
        
        if self.drag_state == 'playhead' or self.duration_ms <= 0: return
        if now < self.user_seek_lock_time: return 

        if self.is_playing:
            # 1. Advance the playhead flawlessly using the high-precision system clock
            self.visual_ms += delta_ms
            
            # 2. Gently correct the position if we drift from MPV's true time
            drift = self.target_ms - self.visual_ms
            if abs(drift) > 1000:
                self.visual_ms = self.target_ms # Hard snap if way off
            else:
                self.visual_ms += drift * 0.1 # Micro-correction (invisible to the eye)
        else:
            # 3. Smooth glide to target when paused (Anti-Snapback)
            self.visual_ms += (self.target_ms - self.visual_ms) * 0.3

        self.visual_ms = max(0.0, min(self.visual_ms, float(self.duration_ms)))
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtCore import QRectF # REQUIRED FOR SUB-PIXEL SMOOTHNESS
        
        # Convert to floats for sub-pixel precision
        width = float(self.width())
        height = float(self.height())
        track_height = 12.0
        track_y = (height - track_height) / 2.0
        
        painter.fillRect(QRectF(0.0, track_y, width, track_height), self.track_color)
        
        if self.duration_ms <= 0: return
        
        # Smooth Played Region
        fill_width = (self.visual_ms / self.duration_ms) * width
        painter.fillRect(QRectF(0.0, track_y, fill_width, track_height), self.fill_color)
        
        # Smooth Trim Region (Yellow Box)
        if self.is_trim_mode:
            start_x = (self.trim_start_ms / self.duration_ms) * width
            end_x = (self.trim_end_ms / self.duration_ms) * width
            trim_w = end_x - start_x
            
            painter.fillRect(QRectF(start_x, track_y, trim_w, track_height), self.trim_body_color)
            painter.fillRect(QRectF(start_x, track_y - 2.0, 4.0, track_height + 4.0), self.trim_handle_color)
            painter.fillRect(QRectF(end_x - 4.0, track_y - 2.0, 4.0, track_height + 4.0), self.trim_handle_color)

        # 4. Ghost Playhead (Transparent hover preview)
        # Check all strict conditions: Must be hovering, NOT on a trim handle, and NOT dragging anything
        if getattr(self, 'is_hovering', False) and not getattr(self, 'is_hovering_trim_handle', False) and self.drag_state == 'none':
            ghost_w = 4.0
            ghost_x = max(0.0, min(self.hover_x - (ghost_w / 2.0), width - ghost_w))
            painter.fillRect(QRectF(ghost_x, track_y - 6.0, ghost_w, track_height + 12.0), QColor(255, 255, 255, 80))

        # The Mega Smooth Playhead (White Line)
        handle_w = 4.0
        handle_x = max(0.0, min(fill_width - (handle_w / 2.0), width - handle_w))
        painter.fillRect(QRectF(handle_x, track_y - 6.0, handle_w, track_height + 12.0), self.handle_color)

    def ms_to_x(self, ms):
        if self.duration_ms <= 0: return 0
        return (ms / self.duration_ms) * self.width()

    def x_to_ms(self, x):
        if self.width() <= 0: return 0
        return (max(0, min(x, self.width())) / self.width()) * self.duration_ms

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self.duration_ms <= 0: return
        
        x = event.position().x()
        y = event.position().y()
        ms = self.x_to_ms(x)
        
        track_height = 12
        track_y = (self.height() - track_height) // 2
        
        # --- SMART HITBOX ROUTING ---
        is_outside_track = (y < track_y) or (y > track_y + track_height)
        
        if self.is_trim_mode and not is_outside_track:
            start_x = self.ms_to_x(self.trim_start_ms)
            end_x = self.ms_to_x(self.trim_end_ms)
            
            hit_tolerance = 10 # Pixels of tolerance
            
            # Priority 1: Edges of the yellow trim bar
            if abs(x - start_x) <= hit_tolerance:
                self.drag_state = 'trim_l'
                return
            elif abs(x - end_x) <= hit_tolerance:
                self.drag_state = 'trim_r'
                return
                
        # Priority 2: If we click anywhere else (inside yellow body, outside track, etc), move playhead!
        self.drag_state = 'playhead'
        self.pause_requested.emit() 
        self.update_playhead(x)

    def mouseMoveEvent(self, event):
        from PySide6.QtCore import Qt, QPoint
        
        if self.duration_ms <= 0: return
        
        x = event.position().x()
        y = event.position().y()
        ms = self.x_to_ms(x)
        
        track_height = 12.0
        track_y = (self.height() - track_height) / 2.0
        
        # We define a generous vertical hitbox for the trim handles (+10px above and below)
        # so you don't have to aim perfectly at the 12px line to grab them!
        is_outside_trim_hitbox = (y < track_y - 10.0) or (y > track_y + track_height + 10.0)
        
        # --- HOVER & DYNAMIC CURSOR LOGIC ---
        self.hover_x = float(x)
        
        # The ghost playhead is now visible ANYWHERE inside the entire widget area!
        self.is_hovering = True 
        self.is_hovering_trim_handle = False    
        
        current_cursor = Qt.PointingHandCursor
        
        if self.is_trim_mode and not is_outside_trim_hitbox:
            start_x = self.ms_to_x(self.trim_start_ms)
            end_x = self.ms_to_x(self.trim_end_ms)
            hit_tolerance = 10 # Pixels
            
            # If hovering over the trim handles
            if abs(x - start_x) <= hit_tolerance or abs(x - end_x) <= hit_tolerance:
                current_cursor = Qt.SizeHorCursor
                self.is_hovering_trim_handle = True # Hide the ghost here to show arrows only!
                
        if self.drag_state in ['trim_l', 'trim_r']:
            current_cursor = Qt.SizeHorCursor
            self.is_hovering_trim_handle = True # Hide the ghost while dragging arrows
        elif self.drag_state == 'playhead':
            current_cursor = Qt.PointingHandCursor
            
        self.setCursor(current_cursor)
        
        # --- FLOATING PREVIEW LOGIC ---
        if hasattr(self, 'preview_widget'):
            hover_ms = max(0.0, min(ms, float(self.duration_ms)))
            
            sec = int(hover_ms // 1000)
            h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
            time_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
            
            is_in_trim = False
            if self.is_trim_mode and (self.trim_start_ms <= hover_ms <= self.trim_end_ms):
                is_in_trim = True
                
            # 1. Update UI and check cache
            current_thumb_dir = getattr(self, 'thumb_dir', None)
            self.preview_widget.update_info(time_str, is_in_trim, hover_ms, current_thumb_dir)
            self.preview_widget.show()
            
            # 2. Command the sniper to fetch THIS exact frame immediately!
            if hasattr(self, 'sniper_thread'):
                self.sniper_thread.request_frame(sec)

            # Edge Clamping Logic
            global_pos = self.mapToGlobal(QPoint(0, 0))
            target_x = global_pos.x() + int(x) - (self.preview_widget.width() // 2)
            target_y = global_pos.y() - self.preview_widget.height() - 5 
            
            min_x = global_pos.x()
            max_x = global_pos.x() + self.width() - self.preview_widget.width()
            clamped_x = max(min_x, min(target_x, max_x))
            
            self.preview_widget.move(clamped_x, target_y)
        
        # --- ACTUAL DRAG LOGIC ---
        if self.drag_state == 'none':
            self.update() 
            return
            
        if self.drag_state == 'playhead':
            self.update_playhead(x)
            
        elif self.drag_state == 'trim_l':
            self.trim_start_ms = min(ms, self.trim_end_ms - 1000) 
            self.trim_start_ms = max(0.0, self.trim_start_ms)
            self.update()
            
        elif self.drag_state == 'trim_r':
            self.trim_end_ms = max(ms, self.trim_start_ms + 1000)
            self.trim_end_ms = min(float(self.duration_ms), self.trim_end_ms)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton: return
        
        if self.drag_state == 'playhead':
            # --- STEAM-LIKE MICRO DELAY ---
            # Changed from 1.0s to 0.15s (150ms) for an ultra-responsive feel
            self.user_seek_lock_time = time.time() + 0.15 
            self.update_playhead(event.position().x())
            self.resume_requested.emit()
            
        elif self.drag_state in ['trim_l', 'trim_r']:
            self.trim_changed.emit(int(self.trim_start_ms), int(self.trim_end_ms))
            
        self.drag_state = 'none'

    def update_playhead(self, mouse_x):
        width = self.width()
        percentage = max(0.0, min(mouse_x / width, 1.0))
        self.visual_ms = float(percentage * self.duration_ms)
        self.target_ms = self.visual_ms 
        self.seek_requested.emit(int(self.visual_ms))
        self.update()
        
    def force_jump(self, new_position_ms):
        if self.duration_ms <= 0: return
        self.visual_ms = max(0.0, min(float(new_position_ms), float(self.duration_ms)))
        self.target_ms = self.visual_ms 
        
        # --- STEAM-LIKE MICRO DELAY ---
        self.user_seek_lock_time = time.time() + 0.15 
        self.seek_requested.emit(int(self.visual_ms))
        self.update()

    # --- ADD THIS RIGHT AFTER FORCE_JUMP ---
    def leaveEvent(self, event):
        """ Clears hover states, hides the ghost playhead, and hides the floating preview when the mouse leaves. """
        self.is_hovering = False
        self.hover_x = -1.0
        
        # --- HIDE THE FLOATING PREVIEW ---
        if hasattr(self, 'preview_widget'):
            self.preview_widget.hide()
            
        from PySide6.QtCore import Qt
        self.setCursor(Qt.ArrowCursor) # Revert to normal Windows arrow
        self.update() # Force repaint to erase the ghost
        
        super().leaveEvent(event)

from PySide6.QtCore import QObject, QEvent, Qt

# --- GLOBAL FULLSCREEN RADAR ---
class FullscreenEventFilter(QObject):
    """ Listens to global mouse movements and the ESC key to manage fullscreen UI. """
    def __init__(self, app_instance):
        super().__init__()
        self.app_instance = app_instance

    def eventFilter(self, obj, event):
        if not self.app_instance.is_fullscreen:
            return False

        # 1. Listen for ESC key to exit fullscreen
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.app_instance.toggle_fullscreen()
                return True # Block the event

        # 2. Listen for ANY mouse movement to wake up the UI
        elif event.type() == QEvent.Type.MouseMove:
            self.app_instance.wake_up_fullscreen_controls()

        return False
    
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSlider, QLabel

class VolumeControlWidget(QWidget):
    """ Smart YouTube-style expandable volume control with Mute Memory """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setFixedWidth(44) # Safe zone for the anti-aliased button
        self.setStyleSheet("background: transparent;")

        # State memory for the mute toggle
        self.previous_volume = 100
        self.is_muted = False

        # Preload both icons to swap them instantly
        self.icon_on = QIcon()
        self.icon_off = QIcon()
        
        path_on = get_resource_path("buttonvolume.png")
        path_off = get_resource_path("volumeoff.png")
        
        if os.path.exists(path_on): self.icon_on = QIcon(path_on)
        if os.path.exists(path_off): self.icon_off = QIcon(path_off)

        # 1. Round button (#4e4e4e) - Anchored to X=0
        self.btn_icon = QPushButton(self)
        self.btn_icon.setFixedSize(40, 40)
        self.btn_icon.move(0, 0)
        self.btn_icon.setCursor(Qt.PointingHandCursor)
        self.btn_icon.setStyleSheet("""
            QPushButton { background-color: #4e4e4e; border-radius: 20px; }
            QPushButton:hover { background-color: #5a5a5a; }
        """)
        
        if not self.icon_on.isNull():
            self.btn_icon.setIcon(self.icon_on)
            self.btn_icon.setIconSize(QSize(24, 24))
        else:
            self.btn_icon.setText("🔊") 

        # Bind the click event to our smart toggle function
        self.btn_icon.clicked.connect(self.toggle_mute)

        # 2. The Volume Slider - Starts at X=48
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setValue(100)
        self.slider.setFixedSize(80, 20)
        self.slider.move(48, 10) 
        
        line_path = get_resource_path("linevolume.png").replace("\\", "/")
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ height: 4px; border-image: url("{line_path}"); background: rgba(255, 255, 255, 50); border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: #b498e3; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: #b498e3; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }}
            QSlider::handle:horizontal:hover {{ transform: scale(1.2); background: #cbb5f2; }}
        """)

        # 3. Percentage Text 
        self.lbl_percent = QLabel("100%", self)
        self.lbl_percent.setFixedSize(45, 20)
        self.lbl_percent.move(136, 10)
        self.lbl_percent.setStyleSheet("color: white; font-size: 11px; font-weight: bold;")
        self.lbl_percent.setAlignment(Qt.AlignCenter)

        self.slider.hide()
        self.lbl_percent.hide()

        # 4. Smooth Expansion Animations
        self.anim = QPropertyAnimation(self, b"minimumWidth")
        self.anim.setDuration(200)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

        self.anim_max = QPropertyAnimation(self, b"maximumWidth")
        self.anim_max.setDuration(200)
        self.anim_max.setEasingCurve(QEasingCurve.OutCubic)

        self.slider.valueChanged.connect(self.update_text)

        self.slider.sliderReleased.connect(self.on_slider_released)

    def toggle_mute(self):
        """ Handles the button click to mute or restore volume """
        if self.is_muted or self.slider.value() == 0:
            # Unmute: Restore to previous volume (default to 100 if it was 0)
            restore_val = self.previous_volume if self.previous_volume > 0 else 100
            self.slider.setValue(restore_val)
        else:
            # Mute: Save current volume and drop to 0
            self.previous_volume = self.slider.value()
            self.slider.setValue(0)

    def update_text(self, val):
        """ Updates the text AND dynamically swaps the icon based on the slider value """
        self.lbl_percent.setText(f"{val}%")
        
        if val == 0:
            # Drop to zero -> Mute Icon
            if not self.icon_off.isNull(): self.btn_icon.setIcon(self.icon_off)
            else: self.btn_icon.setText("🔇")
            self.is_muted = True
        else:
            # Above zero -> Normal Icon
            if not self.icon_on.isNull(): self.btn_icon.setIcon(self.icon_on)
            else: self.btn_icon.setText("🔊")
            self.is_muted = False
            # Constantly remember the last non-zero volume!
            self.previous_volume = val 


    def enterEvent(self, event):
        """ Expands the volume widget and shows the slider """
        self.anim.stop()
        self.anim_max.stop()
        
        self.slider.show()
        self.lbl_percent.show()
        
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(185) 
        self.anim_max.setStartValue(self.width())
        self.anim_max.setEndValue(185)
        
        self.anim.start()
        self.anim_max.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """ Collapses the volume widget back to a button """
        # SAFETY CHECK: If the user is actively dragging the slider, DO NOT hide it!
        if self.slider.isSliderDown():
            super().leaveEvent(event)
            return
            
        self.anim.stop()
        self.anim_max.stop()
        
        # MAGIC RESTORED: We removed the instant .hide() calls here!
        # Now it will smoothly animate its width down to 44px first.
        
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(44) 
        self.anim_max.setStartValue(self.width())
        self.anim_max.setEndValue(44)
        
        self.anim.start()
        self.anim_max.start()
        
        # Hide the slider and text safely AFTER the 200ms animation finishes
        QTimer.singleShot(200, self.hide_items)
        
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        """ Ensures the widget collapses if the user released the mouse outside the widget area """
        super().mouseReleaseEvent(event)
        
        # If the mouse was released outside our hitbox, force collapse
        if not self.rect().contains(event.position().toPoint()):
            self.leaveEvent(event)
    def on_slider_released(self):
        """ Triggered when the user lets go of the slider. """
        # If the mouse is already outside the widget when released, collapse it smoothly!
        if not self.underMouse():
            self.anim.stop()
            self.anim_max.stop()
            
            self.anim.setStartValue(self.width())
            self.anim.setEndValue(44) 
            self.anim_max.setStartValue(self.width())
            self.anim_max.setEndValue(44)
            
            self.anim.start()
            self.anim_max.start()
            
            QTimer.singleShot(200, self.hide_items)

    def hide_items(self):
        if self.width() <= 48:
            self.slider.hide()
            self.lbl_percent.hide()

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
            
        window.ui.show()
        
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
def global_exception_handler(exc_type, exc_value, exc_traceback):
        import traceback
        error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print(f"CRITICAL FATAL CRASH:\n{error_msg}")
        try:
            import logging
            logging.critical(f"UNCAUGHT FATAL ERROR:\n{error_msg}")
        except: pass
sys.excepthook = global_exception_handler
