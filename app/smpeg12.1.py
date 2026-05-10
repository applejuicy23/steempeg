import sys
import os
import subprocess
import re
import psutil
import requests
import json
import logging
from datetime import datetime

# === 1. БРОНЕБОЙНЫЙ ФИКС ДЛЯ VLC (МЕНЯЕМ ПАПКУ ПРИ ЗАПУСКЕ) ===
if getattr(sys, 'frozen', False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))

_vlc_dir = os.path.join(_base_dir, "vlc_engine")

if os.path.exists(_vlc_dir):
    os.environ['PYTHON_VLC_MODULE_PATH'] = _vlc_dir
    os.environ['VLC_PLUGIN_PATH'] = os.path.join(_vlc_dir, "plugins")
    
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(_vlc_dir)
        
    # ВОТ ЭТА МАГИЯ, КОТОРУЮ ТЫ ЗАБЫЛА ДОБАВИТЬ В ФАЙЛ!
    _old_cwd = os.getcwd()
    os.chdir(_vlc_dir)
    try:
        import vlc
    finally:
        os.chdir(_old_cwd)
else:
    import vlc
# =============================================================

from PySide6.QtCore import Qt, QFile, QThread, Signal, QTimer, QSize, QObject
from PySide6.QtCore import QUrl, QEvent
from PySide6.QtWidgets import QVBoxLayout, QApplication, QFileDialog, QMessageBox
from PySide6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QPixmap, QIcon

# === 2. УМНЫЙ ПОИСК РЕСУРСОВ И FFMPEG ===
def get_resource_path(relative_path):
    """ Умный поиск файлов для новой ZIP-сборки (--onedir) """
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

        self.ui.setWindowTitle("Steempeg v12.1")
        
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
        logging.info("STEEMPEG 12.1 RUNNING")
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
        self.ui.btn_browse.clicked.connect(self.choose_folder)
        self.ui.destination_button.clicked.connect(self.choose_destination)
        
        if hasattr(self.ui, 'btn_about'):
            self.ui.btn_about.clicked.connect(self.show_about_dialog)
        self.ui.btn_start.clicked.connect(self.start_render_thread)
            
        if hasattr(self.ui, 'btn_update_check'):
            self.ui.btn_update_check.clicked.connect(self.check_for_updates)

        self.ui.btn_start.clicked.connect(self.start_render_thread)
        self.ui.btn_start.setEnabled(False)

        # --- FIXING THE INTERFACE AND PLAYER ---
        # 1. Give the right panel some breathing room
        right_layout = self.ui.right_panel.layout()
        if right_layout:
            right_layout.setContentsMargins(12, 12, 12, 12) 
            right_layout.setSpacing(8)

        #2: Taming VLC Player 
        self.ui.video_container.setStyleSheet("background-color: #000000; border: none;")
        

        # --- CREATE A TOP PANEL  ---
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel
        
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
        
        # Use NEW safe variable names to avoid conflicts       
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
            
        # Hide old labels from Qt Designer, if they are still there
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

        # --- INITIALIZING THE VLC VIDEO PLAYER ---
        
        #1. Create the VLC core 
        self.vlc_instance = vlc.Instance("--no-xlib", "--quiet")
        self.player = self.vlc_instance.media_player_new()

        # 2. Link VLC directly to your black square (video_container)
        # In Windows, we pass the widget's physical window ID (winId)
        self.player.set_hwnd(int(self.ui.video_container.winId()))
        
        # --- INITIALIZING THE VLC VIDEO PLAYER ---
        
        #1. Create the VLC core 
        self.vlc_instance = vlc.Instance("--no-xlib", "--quiet")
        self.player = self.vlc_instance.media_player_new()

        # 2. Link VLC directly to your black square (video_container)
        # In Windows, we pass the widget's physical window ID (winId)
        self.player.set_hwnd(int(self.ui.video_container.winId()))


        # Button connections 
        if hasattr(self.ui, 'btn_play'):
            self.ui.btn_play.clicked.connect(self.toggle_play)
            self.ui.btn_skip_back.clicked.connect(self.skip_backward)
            self.ui.btn_skip_forward.clicked.connect(self.skip_forward)

        self.vlc_timer = QTimer(self.ui)
        self.vlc_timer.setInterval(200) # Update the interface every 200 milliseconds
        self.vlc_timer.timeout.connect(self.update_ui_from_vlc)
        self.vlc_timer.start() # Let it always work in the background

        if hasattr(self.ui, 'slider_timeline'):
            # We leave only the connection "user dragged the slider - scroll the video"
            self.ui.slider_timeline.sliderMoved.connect(self.set_player_position)
            self.ui.slider_timeline.installEventFilter(self)

        

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
            # Connect the signal ONCE when the program starts
            self.ui.size_slider.valueChanged.connect(self.on_slider_moved)
            
        if hasattr(self.ui, 'label_target_size'):
            self.ui.label_target_size.setVisible(False)
        
        if hasattr(self.ui, 'check_audio_only'):
            self.ui.check_audio_only.toggled.connect(self.on_audio_only_toggled)
        if hasattr(self.ui, 'check_mute_audio'):
            self.ui.check_mute_audio.toggled.connect(self.on_mute_audio_toggled)
        if hasattr(self.ui, 'combo_audio_format'):
            self.ui.combo_audio_format.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_audio_bitrate'):
            self.ui.combo_audio_bitrate.currentTextChanged.connect(self.update_final_setup)
    
        # 5. AUTOMATIC DATA LOADING AT PROGRAM START
        # Automatically detect the video card and set the default codec BEFORE scanning clips
        self.detect_gpu_and_set_encoder()
        
        default_path = r"C:\Program Files (x86)\Steam\userdata\1077964895\gamerecordings\clips"
        if os.path.exists(default_path):
            self.clips_folder = default_path
            self.scan_clips()

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

    def choose_folder(self):
        """ Opens a dialog for selecting a folder with Steam clips. """
        target_path = r"C:\Program Files (x86)\Steam\userdata\1077964895\gamerecordings\clips"
        if not os.path.exists(target_path):
            target_path = "C:\\"

        folder = QFileDialog.getExistingDirectory(self.ui, "Select clips folder", target_path)
        if folder:
            self.clips_folder = folder
            self.scan_clips()
    
    # VIDEO PLAYER CONTROLS
    def toggle_play(self):
        """ Play / Pause toggle for VLC """
        if not self.player.get_media():
            self.generate_and_play_preview()
            return

        state = self.player.get_state()
        
        # If the video ends, start it again from the beginning
        if state == vlc.State.Ended:
            self.player.stop()
            self.player.play()
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_pause.png")))
            return

        if self.player.is_playing():
            self.player.pause()
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))
        else:
            self.player.play()
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_pause.png")))

    def set_player_position(self, position):
        """ When the user drags the slider, VLC rewinds. """
        if hasattr(self, 'player') and self.player:
            state = self.player.get_state()
            
            # when rewinding a dead video
            if state == vlc.State.Ended:
                self.player.stop()
                self.player.play()
                self.player.set_time(position)
                self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_pause.png")))
            else:
                self.player.set_time(position)

    def skip_backward(self):
        """ Rewind 15 seconds """
        if hasattr(self, 'player') and self.player:
            state = self.player.get_state()
            
            if state == vlc.State.Ended:
                self.player.stop()
                self.player.play()
                length = self.player.get_length()
                if length > 15000:
                    self.player.set_time(length - 15000)
               
                self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_pause.png")))
                return

            current_time = self.player.get_time()
            if current_time > 0:
                self.player.set_time(max(0, current_time - 15000))

    def skip_forward(self):
        """ Fast forward 15 seconds """
        if hasattr(self, 'player') and self.player:
            state = self.player.get_state()
            if state == vlc.State.Ended:
                return 
            
            current_time = self.player.get_time()
            length = self.player.get_length()
            if current_time >= 0 and length > 0:
                self.player.set_time(min(length, current_time + 15000))

    def generate_and_play_preview(self):
        """ Instantly loads and plays the Steam .mpd playlist using VLC. No proxy needed! """ 
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
        print(f"---> Feeding MPD directly to VLC: {mpd_path}")

        # 3. PREPARE THE CANVAS
        self.ui.video_container.setStyleSheet("background-color: black;") 

        # 4. FEED THE RAW STEAM DASH FILE DIRECTLY TO VLC
        abs_path = os.path.abspath(mpd_path)
        media = self.vlc_instance.media_new(abs_path)
        self.player.set_media(media)
        
        # 5. PLAY INSTANTLY
        self.player.play()
        
        # 6. UPDATE UI
        if hasattr(self.ui, 'btn_play'):
            self.ui.btn_play.setEnabled(True)
            self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_pause.png")))

    def update_ui_from_vlc(self):
        """ Safely updates the slider from the Qt thread with auto-reset at 00:00 """
        if not hasattr(self, 'player') or not self.player: return
        
        state = self.player.get_state()
        length = self.player.get_length() 
        current_time = self.player.get_time() 

        last_time = getattr(self, '_last_vlc_time', -1)
        if current_time == last_time and current_time > 0 and self.player.is_playing():
            self._frozen_ticks = getattr(self, '_frozen_ticks', 0) + 1
        else:
            self._frozen_ticks = 0
            self._last_vlc_time = current_time

        # We consider a video dead if:
        # 1. It's actually Ended
        # 2. OR time stands still for more than 3 ticks and we're at the very end of the video (closer than 2 seconds)
        is_dead = (state == vlc.State.Ended) or (self._frozen_ticks >= 3 and length - current_time < 2000)

        # 1. IF THE VIDEO HAS ENDED (RESET TO THE BEGINNING) 
        if is_dead:
            self._frozen_ticks = 0 # Reset the detector
            
            # Stop, start from the beginning and immediately pause
            self.player.stop()
            self.player.play()
            self.player.pause()
            
            # Change the button to Play
            if hasattr(self.ui, 'btn_play'):
                self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))
                
            # We reset the interface in 00:00
            if length > 0:
                self.ui.slider_timeline.blockSignals(True)
                self.ui.slider_timeline.setValue(0)
                self.ui.slider_timeline.blockSignals(False)
                
                tot_sec = length // 1000
                t_h = tot_sec // 3600
                t_m = (tot_sec % 3600) // 60
                t_s = tot_sec % 60
                
                if t_h > 0:
                    total_str = f"{t_h:02d}:{t_m:02d}:{t_s:02d}"
                    zero_str = "00:00:00"
                else:
                    total_str = f"{t_m:02d}:{t_s:02d}"
                    zero_str = "00:00"
                    
                if hasattr(self.ui, 'label_time'):
                    self.ui.label_time.setText(f"{zero_str} / {total_str}")
            return 

        # 2. DURING NORMAL PLAYBACK
        if length > 0 and current_time >= 0:
            self.ui.slider_timeline.blockSignals(True)
            self.ui.slider_timeline.setRange(0, length)
            self.ui.slider_timeline.setValue(current_time)
            self.ui.slider_timeline.blockSignals(False)
            
            cur_sec = current_time // 1000
            tot_sec = length // 1000
            
            t_h = tot_sec // 3600
            t_m = (tot_sec % 3600) // 60
            t_s = tot_sec % 60
            
            c_h = cur_sec // 3600
            c_m = (cur_sec % 3600) // 60
            c_s = cur_sec % 60
            
            if t_h > 0:
                current_str = f"{c_h:02d}:{c_m:02d}:{c_s:02d}"
                total_str = f"{t_h:02d}:{t_m:02d}:{t_s:02d}"
            else:
                current_str = f"{c_m:02d}:{c_s:02d}"
                total_str = f"{t_m:02d}:{t_s:02d}"
                
            if hasattr(self.ui, 'label_time'):
                self.ui.label_time.setText(f"{current_str} / {total_str}")

        
    def on_player_error(self, error, error_string):
        print(f"\nFATAL PLAYER ERROR: {error} | {error_string}\n")
        logging.error(f"PLAYER ERROR: {error} - {error_string}")


    def update_ui_from_vlc(self):
        """ Safely updates the slider from the Qt thread with auto-reset at 00:00 """
        if not hasattr(self, 'player') or not self.player: return
        
        state = self.player.get_state()
        length = self.player.get_length() 
        current_time = self.player.get_time() 

        # Fires on the next tick after the player is restarted
        if getattr(self, '_force_pause', False):
            if state == vlc.State.Playing:
                self.player.pause()
                self.player.set_time(0) 
                self._force_pause = False
            return

        last_time = getattr(self, '_last_vlc_time', -1)
        
        # We measure "freezing" only if the player is in Playing mode
        if state == vlc.State.Playing and current_time == last_time and current_time > 0:
            self._frozen_ticks = getattr(self, '_frozen_ticks', 0) + 1
        else:
            self._frozen_ticks = 0
            self._last_vlc_time = current_time

        # Checking. if the video is dead only if we are very close to the end
        is_near_end = (length > 0) and (length - current_time < 2000)
        
        is_dead = (state == vlc.State.Ended) or \
                  (state == vlc.State.Stopped and is_near_end) or \
                  (self._frozen_ticks >= 3 and is_near_end)

        # --- 1. IF THE VIDEO HAS ENDED (RESET TO THE BEGINNING) ---
        if is_dead:
            self._frozen_ticks = 0 
            
            # Restart the player to reset VLC internal bugs
            self.player.stop()
            self.player.play()
            self._force_pause = True # We'll pause it next tick
            
            # Change the button to Play
            if hasattr(self.ui, 'btn_play'):
                self.ui.btn_play.setIcon(QIcon(get_resource_path("icon_play.png")))
                
            # Reset the interface at 00:00
            if length > 0:
                self.ui.slider_timeline.blockSignals(True)
                self.ui.slider_timeline.setValue(0)
                self.ui.slider_timeline.blockSignals(False)
                
                tot_sec = length // 1000
                t_h = tot_sec // 3600
                t_m = (tot_sec % 3600) // 60
                t_s = tot_sec % 60
                
                if t_h > 0:
                    total_str = f"{t_h:02d}:{t_m:02d}:{t_s:02d}"
                    zero_str = "00:00:00"
                else:
                    total_str = f"{t_m:02d}:{t_s:02d}"
                    zero_str = "00:00"
                    
                if hasattr(self.ui, 'label_time'):
                    self.ui.label_time.setText(f"{zero_str} / {total_str}")
            return 

        # --- 2. DURING NORMAL PLAYBACK ---
        if length > 0 and current_time >= 0:
            self.ui.slider_timeline.blockSignals(True)
            self.ui.slider_timeline.setRange(0, length)
            self.ui.slider_timeline.setValue(current_time)
            self.ui.slider_timeline.blockSignals(False)
            
            cur_sec = current_time // 1000
            tot_sec = length // 1000
            
            t_h = tot_sec // 3600
            t_m = (tot_sec % 3600) // 60
            t_s = tot_sec % 60
            
            c_h = cur_sec // 3600
            c_m = (cur_sec % 3600) // 60
            c_s = cur_sec % 60
            
            if t_h > 0:
                current_str = f"{c_h:02d}:{c_m:02d}:{c_s:02d}"
                total_str = f"{t_h:02d}:{t_m:02d}:{t_s:02d}"
            else:
                current_str = f"{c_m:02d}:{c_s:02d}"
                total_str = f"{t_m:02d}:{t_s:02d}"
                
            if hasattr(self.ui, 'label_time'):
                self.ui.label_time.setText(f"{current_str} / {total_str}")

    
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
        <h3>Steempeg v12.1.0</h3>
        <p><b>Build:</b> 12.1.0 (Next-Gen II hotfix)</p>
        <p><b>Developer:</b> Emily 🎀 <span style="color: #888888; font-size: 10pt;">@applejuicy23</span></p>

        <p><img src="{github_icon}" width="16" height="16" align="middle"> <b>GitHub:</b> <a href="https://github.com/applejuicy23/steempeg">applejuicy23/steempeg</a></p>
        <p><img src="{steam_icon}" width="16" height="16" align="middle"> <b>Steam:</b> <a href="https://steamcommunity.com/id/applejuicy23/">applejuicy23</a></p>

        <p>A smart, elegant, and fast hardware-accelerated video renderer for Steam Clips.</p>
        <p>Powered by <b>FFmpeg</b> & <b>VLC</b></p>

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

        CURRENT_VERSION = 12.1
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
        msg.setWindowTitle("Update Successful! 🎉")
        msg.setIcon(QMessageBox.Information)
        
        text = f"<h3>Steempeg is updated!</h3><p>Successfully updated from <b>v{old_version}</b> to the latest version.</p>"
        if backup_folder and backup_folder != "None":
            text += f"<p>Your old version was saved in the folder:<br><code>{backup_folder}</code></p>"
            
        msg.setText(text)
        
        btn_ok = msg.addButton("Awesome!", QMessageBox.AcceptRole)
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
        CURRENT_VERSION = "12.0" # The current version should be here

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
                        for root, dirs, files in os.walk(full_path):
                            if any(f.endswith(".mpd") for f in files):
                                has_mpd = True
                                break 
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
        """ Recursively finds all session.mpd files inside the GIVEN FOLDER PATH """
        mpd_paths = []
        if os.path.exists(clip_path):
            for root, dirs, files in os.walk(clip_path):
                for file in files:
                    if file.endswith(".mpd"):
                        mpd_paths.append(os.path.join(root, file))
        return sorted(mpd_paths)
    
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
            self.ui.orig_res_label.setText("Original resolution:")
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
            self.ui.combo_quality.clear()
            return

        # Update the label with the path to the sources
        source_dirs = [os.path.dirname(mpd) for mpd in all_mpds]
        unique_source_dirs = list(dict.fromkeys(source_dirs))
        
        formatted_sources = "<br>".join([f"{i+1}. {p}" for i, p in enumerate(unique_source_dirs)])
        self.ui.source_label.setText(f"Source:<br><span style='font-size:8pt; color:#aaaaaa;'>{formatted_sources}</span>")

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
            
            self.ui.combo_audio_bitrate.addItem(f"{orig_audio_bitrate} kbps (Original Copy)")
            
            # We add to the list only those that do not exceed the original (with a small margin)
            for val, text in bitrates:
                if val <= orig_audio_bitrate + 15: 
                    self.ui.combo_audio_bitrate.addItem(text)
                    
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
            
            # Display rounded original video bitrate and exact audio bitrate
            audio_kbps = getattr(self, 'current_orig_audio_bitrate', 192)
            
            if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                rounded_bitrate = int(round(self.current_orig_bitrate))
                self.ui.orig_res_label.setText(f"Original resolution: {res_text} (~{rounded_bitrate} Mbps Video, {audio_kbps} kbps Audio)")
            else:
                self.ui.orig_res_label.setText(f"Original resolution: {res_text} ({audio_kbps} kbps Audio)")
        else:
            self.ui.orig_res_label.setText("Original resolution: Unknown")
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
            self.ui.label_location.setText(f"Rendered video location: {full_path}")

        #4. Collecting texts
        duration_str = getattr(self, 'current_clip_duration_str', "Unknown")
        
        # Calculating the size
        size_str = "Unknown"
        fps_multiplier = 1.0
        if fps:
            try:
                selected_fps = int(re.search(r'(\d+)', fps).group(1))
                orig_fps = getattr(self, 'current_orig_fps', 60)
                if selected_fps < orig_fps and orig_fps > 0:
                    fps_multiplier = selected_fps / orig_fps
            except: pass

        if hasattr(self, 'current_clip_duration_sec') and self.current_clip_duration_sec > 0:
            if "Target File Size" in quality:
                if hasattr(self, 'dynamic_stops') and hasattr(self.ui, 'size_slider'):
                    target_mb = self.dynamic_stops[self.ui.size_slider.value()]
                    size_str = f"~{target_mb / 1024:.2f} GB (Target)" if target_mb >= 1000 else f"~{target_mb} MB (Target)"
            elif "Original" in bitrate_text:
                if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
                    orig_total_bitrate = (self.current_orig_bitrate * fps_multiplier) + 0.19 
                    size_mb = (orig_total_bitrate * self.current_clip_duration_sec) / 8
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
                    size_mb = (total_bitrate * self.current_clip_duration_sec) / 8
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
        q_clean = quality.split('(')[0].strip() if quality else "Unknown"
        fps_clean = fps.split(' ')[0] if fps else "Unknown"
        enc_clean = encoder if encoder else "Unknown"

        if audio_only:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Format: {audio_format}\n"
                f"Bitrate: {audio_bitrate}\n"
                f"Other settings: >> EXTRACT AUDIO ONLY (NO VIDEO)"
            )
        elif mute_audio:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Quality: {q_clean}\n"
                f"FPS: {fps_clean}\n"
                f"Codec: {codec}\n"
                f"Encoder: {enc_clean}\n"
                f"Other settings: >> NO SOUND (MUTED)"
            )
        else:
            detailed_text = (
                f"Clip time: {duration_str}\n"
                f"Quality: {q_clean}\n"
                f"FPS: {fps_clean}\n"
                f"Codec: {codec}\n"
                f"Encoder: {enc_clean}\n"
                f"Sound: {sound_info}\n"
                f"Other settings: {other_info}"
            )
            
        if hasattr(self.ui, 'label_detailed_summary'):
            self.ui.label_detailed_summary.setText(detailed_text)

        # 6. Short Summary ABOVE Ready 
        q_word = quality.split()[0] if quality.split() else "Unknown"
        fps_word = fps.split()[0] if fps.split() else "Unknown"
        enc_word = encoder.split()[0] if encoder.split() else "Unknown"
        
        if audio_only:
            audio_bitrate_clean = audio_bitrate.split()[0] if audio_bitrate else "192"
            short_text = f"AUDIO ONLY: {audio_format} {audio_bitrate_clean} kbps - {final_filename}"
        elif mute_audio:
            short_text = f"{q_word}, {fps_word}FPS, {codec}, {enc_word} (MUTED) - {final_filename}"
        else:
            audio_bitrate_clean = audio_bitrate.split()[0] if audio_bitrate else "192"
            short_text = f"{q_word}, {fps_word}FPS, {codec}, {enc_word}, {audio_format} {audio_bitrate_clean} kbps - {final_filename}"
            
        if hasattr(self.ui, 'label_short_summary'):
            self.ui.label_short_summary.setText(short_text)
            
        if hasattr(self.ui, 'label_status'):
            self.ui.label_status.setText("Ready")
        
        

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
        
        # Convert "320 kbps (Best)" to "320k"
        audio_bitrate_kbps = "192k"
        if hasattr(self.ui, 'combo_audio_bitrate') and self.ui.combo_audio_bitrate.currentText():
            audio_bitrate_kbps = self.ui.combo_audio_bitrate.currentText().split(' ')[0] + "k"

        # Counting bitrait video
        video_bitrate = "12M"
        if "Target File Size" in quality_text:
            video_bitrate = f"{getattr(self, 'custom_target_bitrate', 1500)}k"
        elif "Original" not in bitrate_text:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match:
                base_bitrate = float(match.group(1))
                fps_multiplier = 1.0
                if fps_text:
                    try:
                        selected_fps = int(re.search(r'(\d+)', fps_text).group(1))
                        orig_fps = getattr(self, 'current_orig_fps', 60)
                        if selected_fps < orig_fps and orig_fps > 0:
                            fps_multiplier = selected_fps / orig_fps
                    except: pass
                final_bitrate = int(base_bitrate * fps_multiplier * 1000)
                video_bitrate = f"{final_bitrate}k"

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
            self.thread = RenderThread(all_mpds, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate, fps_text, audio_only, mute_audio, audio_format, audio_bitrate_kbps)
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
        """ Hides or shows the slider depending on the mode """
        is_target_mode = "Target File Size" in text
        
        if hasattr(self.ui, 'size_slider'):
            self.ui.size_slider.setVisible(is_target_mode)
        if hasattr(self.ui, 'label_target_size'):
            self.ui.label_target_size.setVisible(is_target_mode)
            
        if is_target_mode:
            self.setup_dynamic_slider()

    def setup_dynamic_slider(self):
        """ Generates slider steps based on the size of the original clip """
        if not hasattr(self, 'current_clip_duration_sec') or self.current_clip_duration_sec <= 0:
            return
            
        # Calculate the approximate original size in MB
        orig_mb = (getattr(self, 'current_orig_bitrate', 10) * self.current_clip_duration_sec) / 8
        
        # universal "anchors" (in mbytes)
        anchors = [10, 25, 50, 100, 250, 500, 1024, 2048, 3072, 4096, 5120]
        
        # We leave only those that are smaller than the original
        self.dynamic_stops = [size for size in anchors if size < orig_mb]
        self.dynamic_stops.append(int(orig_mb))
        
        # --- ELEGANT SIGNAL BLOCKING ---
        # Freeze signals so the slider doesn't panic when changing min/max
        self.ui.size_slider.blockSignals(True)
        
        self.ui.size_slider.setMinimum(0)
        self.ui.size_slider.setMaximum(len(self.dynamic_stops) - 1)
        self.ui.size_slider.setValue(len(self.dynamic_stops) - 1)
        
        # Unfreeze signals
        self.ui.size_slider.blockSignals(False)
        
        # Call the function manually once to update the text
        self.on_slider_moved(self.ui.size_slider.value())

    def on_slider_moved(self, index):
        """ Calculates bitrate and predicts visual quality based on FPS. """
        target_mb = self.dynamic_stops[index]
        duration = self.current_clip_duration_sec
        
        # Calculating raw bitrate
        target_bitrate_kbps = int((target_mb * 8192) / duration) - 128
        if target_bitrate_kbps < 100: target_bitrate_kbps = 100 

        # Read the selected FPS (it critically affects jackals!)
        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "60"
        try:
            selected_fps = int(re.search(r'(\d+)', fps_text).group(1))
        except:
            selected_fps = 60

        # Effective bitrate: the lower the FPS, the more data is available per frame
        effective_kbps = target_bitrate_kbps
        if selected_fps <= 30: effective_kbps *= 1.5
        if selected_fps <= 15: effective_kbps *= 2.0

        # Smart "monkeymeter =)"
        if target_mb == self.dynamic_stops[-1]:
            color = "#00ff00"
            warning = "Lossless (Quality as original)"
        elif effective_kbps >= 10000:
            color = "#00ff00"
            warning = "Looks like 1080p+ (Good)"
        elif effective_kbps >= 5000:
            color = "#aaff00"
            warning = "Looks like 720p (Mid, but still good)"
        elif effective_kbps >= 2000:
            color = "#ffff00"
            warning = "Looks like 480p (Bad, but tolerable)"
        elif effective_kbps >= 800:
            color = "#ff8800"
            warning = "Looks like 360p (Back to 90s)"
        else:
            color = "#ff4444"
            warning = "Looks like 144p (VHS)"
            
        text = f"Target: <b>{target_mb} MB</b> | Bitrate: {target_bitrate_kbps} kbps<br>Quality: <span style='color:{color}'><b>{warning}</b></span>"
        self.ui.label_target_size.setText(text)

        # Save the estimated bitrate for FFmpeg
        self.custom_target_bitrate = target_bitrate_kbps
        
        # We force the bottom block "Final setup" to update!
        self.update_final_setup()



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
            
            # Check which button was pressed
            if msg_box.clickedButton() == btn_folder:
                import subprocess
                import os
                # Get a clean, absolute path for Windows
                file_path = os.path.abspath(output_file)
                # pass the command as a listPython will definitely not get confused
                subprocess.Popen(["explorer", f"/select,{file_path}"])
                
            elif msg_box.clickedButton() == btn_play:
                import os
                file_path = os.path.abspath(output_file)
                # os.startfile also likes absolute paths :D
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
            
           
            btn_log = msg_box.addButton("📄 Open Log File", QMessageBox.ActionRole)
            btn_ok = msg_box.addButton(QMessageBox.Ok)
            
            msg_box.exec()
            
            # If the user clicked "Open Log File", we call our function
            # Check which button was pressed
            if msg_box.clickedButton() == btn_folder:
                import subprocess
                import os
                file_path = os.path.abspath(output_file)
                # Wrap the path in extra quotes so that Explorer isn't afraid of spaces
                subprocess.Popen(["explorer", f'/select,"{file_path}"'])
    def eventFilter(self, source, event):
        """ Intercepts mouse clicks on the slider so that it jumps exactly to the click location. """
        from PySide6.QtCore import QEvent, Qt
        
        if hasattr(self.ui, 'slider_timeline') and source == self.ui.slider_timeline:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    # We calculate the percentage where the user clicked and convert it into a slider value
                    click_x = event.position().x()
                    width = source.width()
                    val = source.minimum() + ((source.maximum() - source.minimum()) * click_x) / width
                    
                    # Place a circle where you clicked and force VLC to rewind the video
                    source.setValue(int(val))
                    self.set_player_position(int(val))
                    return True # We tell Qt that we handled the click ourselves
                    
        # For all other events we call the standard handler
        return super().eventFilter(source, event)
    

# BACKGROUND RENDER THREAD (PROTECTS UI FROM FREEZING)
class RenderThread(QThread):
    progress_signal = Signal(str)  
    finished_signal = Signal(bool, str, str) 

    def __init__(self, mpd_paths, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate, fps_text, audio_only, mute_audio, audio_format, audio_bitrate_kbps):
        super().__init__()
        self.mpd_paths = mpd_paths
        self.quality_text = quality_text
        self.output_file = output_file
        self.ffmpeg_exe = ffmpeg_exe
        self.save_dir = save_dir
        
        self.selected_encoder = selected_encoder
        self.video_bitrate = video_bitrate
        self.fps_text = fps_text
        
        # Save audio settings
        self.audio_only = audio_only
        self.mute_audio = mute_audio
        self.audio_format = audio_format
        self.audio_bitrate_kbps = audio_bitrate_kbps
        
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
                
                # 1. Prepare the audio arguments
                if self.mute_audio:
                    base_audio = "-an" # Completely disable audio
                else:
                    a_codec = "libmp3lame" if self.audio_format == "MP3" else "aac"
                    base_audio = f"-c:a {a_codec} -b:a {self.audio_bitrate_kbps}"

                # 2. Construct the final command based on video settings
                if self.audio_only:
                    # "AUDIO ONLY" MODE (-vn disables video processing)
                    cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" -vn {base_audio} -y "{temp_mp4}"'
                    
                elif "Original" in self.quality_text and "Target File" not in self.quality_text:
                    # "ORIGINAL" MODE (Copy video stream, either copy or mute audio)
                    if self.mute_audio:
                        cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" {fps_arg}-c:v copy -an -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" {fps_arg}-c copy -y "{temp_mp4}"'
                        
                elif "Target File Size" in self.quality_text:
                    # "TARGET FILE SIZE" MODE
                    # scale=trunc(iw/2)*2... protects against the processor's "odd pixel" error
                    cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" {fps_arg}-c:v {self.selected_encoder} -b:v {self.video_bitrate} {base_audio} -y "{temp_mp4}"'
                    
                else:
                    # "STANDARD PRESETS" MODE (1080p, 720p...)
                    match = re.search(r'^(\d+)p', self.quality_text)
                    if match:
                        target_height = match.group(1)
                        cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" -vf scale=-2:{target_height} {fps_arg}-c:v {self.selected_encoder} -b:v {self.video_bitrate} {base_audio} -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" {fps_arg}-c copy -y "{temp_mp4}"'

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

            # STAGE 2: Merging all rendered parts into one file
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

if __name__ == "__main__":
    os.environ["QT_MEDIA_BACKEND"] = "windows"
    app = QApplication(sys.argv)
    
    try:
        import ctypes
        myappid = 'steempeg.app.v12.1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except: pass
        
    try:
        import traceback
        import argparse 
        
        # Read the updater's hidden arguments
        parser = argparse.ArgumentParser()
        parser.add_argument('--updated-from', type=str, default="")
        parser.add_argument('--backup-folder', type=str, default="")
        args, unknown = parser.parse_known_args()

        window = SteempegApp()
        
        # Protection if the UI file is not found or is corrupted
        if getattr(window, 'ui', None) is None:
            QMessageBox.critical(None, "Interface Error", "Failed to load smpegui13.ui!")
            sys.exit(1)
            
        window.ui.show()
        
        # If the program started after the update, show the dialog!
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
