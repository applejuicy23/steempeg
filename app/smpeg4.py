import sys
import os
import subprocess
import re
import psutil
import requests
import json
from datetime import datetime
from PySide6.QtCore import Qt, QFile, QThread, Signal, QTimer, QSize
from PySide6.QtCore import Qt 
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread, Signal
from PySide6.QtGui import QPixmap, QIcon


def get_resource_path(relative_path):
    """ Returns the absolute path to resources (needed for compiling to .exe via PyInstaller) """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)

def get_save_directory():
    """ Returns the default folder where the program is launched to save videos. """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)

class SteempegApp:
    def __init__(self):
        # 1. LOADING THE INTERFACE
        loader = QUiLoader()
        ui_file_path = get_resource_path("smpegui5.ui")
        ui_file = QFile(ui_file_path)
        
        if not ui_file.open(QFile.ReadOnly):
            return
            
        self.ui = loader.load(ui_file)
        ui_file.close()

        self.ui.setWindowTitle("Steempeg v4")
        
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
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir) # Create a cache folder if it doesn't exist
            
        self.json_cache_path = os.path.join(self.cache_dir, "games.json")
        self.game_names_cache = self.load_json_cache() # JSON
        self.game_icons_cache = {} # This is where we store downloaded images in memory
        
        # 3. CONFIGURING THE INTERFACE (TABLE AND COMBOBOXES)
        if hasattr(self.ui, 'table_clips'):
            # Adding columns through code
            self.ui.table_clips.setColumnCount(3)
            self.ui.table_clips.setHorizontalHeaderLabels(["Game Name", "Date", "Time"])
            
            self.ui.table_clips.setIconSize(QSize(16, 16)) #icon size

            self.ui.table_clips.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.ui.table_clips.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.ui.table_clips.setShowGrid(False)
            self.ui.table_clips.verticalHeader().setVisible(False)
            
            header = self.ui.table_clips.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents)

            self.ui.table_clips.itemSelectionChanged.connect(self.update_quality_options)
        
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
        self.ui.btn_start.clicked.connect(self.start_render_thread)
        self.ui.destination_button.clicked.connect(self.choose_destination)

        # We connect the "Final setup" update to all interface changes
        if hasattr(self.ui, 'combo_quality'): self.ui.combo_quality.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_bitrate'): self.ui.combo_bitrate.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_codec'): self.ui.combo_codec.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'combo_fps'): self.ui.combo_fps.currentTextChanged.connect(self.update_final_setup)
        if hasattr(self.ui, 'input_filename'): self.ui.input_filename.textChanged.connect(self.update_final_setup)

        # Connect the pause and cancel buttons (they are initially disabled)
        if hasattr(self.ui, 'btn_cancel'):
            self.ui.btn_cancel.setEnabled(False)
            self.ui.btn_cancel.clicked.connect(self.cancel_render)
            
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.clicked.connect(self.toggle_pause)

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

    def scan_clips(self):
        """ Scans a folder and fills a TABLE with pretty data"""
        if not hasattr(self.ui, 'table_clips'): return
        
        self.ui.table_clips.setRowCount(0) # Clear the table before scanning
        if not self.clips_folder or not os.path.exists(self.clips_folder):
            return

        try:
            items = os.listdir(self.clips_folder)
            for item_name in items:
                full_path = os.path.join(self.clips_folder, item_name)
                
                if os.path.isdir(full_path):
                    has_mpd = False
                    for root, dirs, files in os.walk(full_path):
                        if any(f.endswith(".mpd") for f in files):
                            has_mpd = True
                            break 
                    
                    if not has_mpd: continue 

                    parts = item_name.split("_")
                    
                    # Parsing Steam data
                    if len(parts) >= 4 and parts[1].isdigit():
                        app_id = parts[1]
                        game_name = self.get_game_name(app_id)
                        icon = self.get_game_icon(app_id) # Download the picture

                        try:
                            formatted_date = datetime.strptime(parts[2], "%Y%m%d").strftime("%d %B %Y")
                        except: formatted_date = parts[2]

                        try:
                            # Making time
                            formatted_time = datetime.strptime(parts[3], "%H%M%S").strftime("%H:%M:%S")
                        except: formatted_time = parts[3]
                    else:
                        game_name = item_name
                        formatted_date = "Unknown"
                        formatted_time = "Unknown"
                        icon = QIcon()

                    # adding to table
                    row_position = self.ui.table_clips.rowCount()
                    self.ui.table_clips.insertRow(row_position)
                    
                    # Column 0: Game Title + Image
                    item_game = QTableWidgetItem(icon, game_name)
                    item_game.setData(Qt.UserRole, item_name) # Hide the original folder name for FFmpeg
                    self.ui.table_clips.setItem(row_position, 0, item_game)
                    
                    # Column 1: Date
                    item_date = QTableWidgetItem(formatted_date)
                    self.ui.table_clips.setItem(row_position, 1, item_date)
                    
                    # Column 2: Time
                    item_time = QTableWidgetItem(formatted_time)
                    self.ui.table_clips.setItem(row_position, 2, item_time)
                    
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
        
    def get_all_mpd_paths(self, clip_name):
        """ Recursively finds all session.mpd files inside the clip folder """
        mpd_paths = []
        clip_dir = os.path.join(self.clips_folder, clip_name)
        if os.path.exists(clip_dir):
            for root, dirs, files in os.walk(clip_dir):
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
    
    def detect_gpu_and_set_encoder(self):
        """ Detects your PC hardware and suggests a suitable codec. """
        if not hasattr(self.ui, 'combo_encoder'): return
        self.ui.combo_encoder.clear()
        
        # List of available codecs. Name for UI&Command for FFmpeg
        encoders = [
            ("x264 (CPU)", "libx264"),
            ("NVENC (NVIDIA GPU)", "h264_nvenc"),
            ("AMF (AMD GPU)", "h264_amf"),
            ("QuickSync (Intel GPU)", "h264_qsv")
        ]
        
        for display_name, ffmpeg_code in encoders:
            self.ui.combo_encoder.addItem(display_name, ffmpeg_code)

        try:
            # Ask Windows for the name of the video card via wmic
            output = subprocess.check_output("wmic path win32_VideoController get name", shell=True, text=True)
            gpu_name = output.upper()

            # Select a codec based on the found word
            if "NVIDIA" in gpu_name: self.ui.combo_encoder.setCurrentIndex(1)
            elif "AMD" in gpu_name or "RADEON" in gpu_name: self.ui.combo_encoder.setCurrentIndex(2)
            elif "INTEL" in gpu_name: self.ui.combo_encoder.setCurrentIndex(3)
            else: self.ui.combo_encoder.setCurrentIndex(0) # Fallback to the processor
        except:
            self.ui.combo_encoder.setCurrentIndex(0)
    
    def update_quality_options(self):
        """ Reads the clip's XML data and prepares the UI for the render settings """
        if not hasattr(self.ui, 'table_clips'): return
        selected_row = self.ui.table_clips.currentRow()
        if selected_row < 0:
            self.ui.source_label.setText("Source:")
            self.ui.orig_res_label.setText("Original resolution:")
            return
            
        # Take the hidden folder name from the zero (first) column of the selected row
        clip_name = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
        
        # Automatically insert the file name into the text field
        if hasattr(self.ui, 'input_filename'):
            self.ui.input_filename.setText(f"{clip_name}_rendered")
            
        all_mpds = self.get_all_mpd_paths(clip_name)

        if not all_mpds:
            self.ui.source_label.setText("Source: No MPD files found")
            self.ui.orig_res_label.setText("Original resolution: Unknown")
            self.ui.combo_quality.clear()
            return

        # Update the label with the path to the sources
        source_dirs = [os.path.dirname(mpd) for mpd in all_mpds]
        unique_source_dirs = list(dict.fromkeys(source_dirs))
        
        self.ui.source_label.setWordWrap(True)
        self.ui.source_label.setText("Source:\n" + ",\n".join(unique_source_dirs))

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
            self.ui.orig_res_label.setText(f"Original resolution: {res_text}")
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
            
        self.update_final_setup()
    
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
    
    def update_final_setup(self):
        """Dynamically updates the Summary, Size, and Save Path."""
        # 1. Collecting current interface settings
        quality = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else ""
        fps = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else ""
        bitrate_text = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else ""
        codec_raw = self.ui.combo_codec.currentText() if hasattr(self.ui, 'combo_codec') else ""
        codec = codec_raw.split()[0] if codec_raw else ""
        encoder = self.ui.combo_encoder.currentText() if hasattr(self.ui, 'combo_encoder') else ""

        # 2. Update the Summary
        if hasattr(self.ui, 'label_summary'):
            summary_text = f"Summary: {quality.split()[0] if quality else 'Original'}, {fps}, {codec}, {encoder}"
            self.ui.label_summary.setText(summary_text)

        # 3. Calculate the Approximate Size
        if hasattr(self, 'current_clip_duration_sec') and self.current_clip_duration_sec > 0:
            
            fps_multiplier = 1.0
            if fps: # the fps variable is already set up at the beginning of the function
                try:
                    # We extract the number from the text, for example from "30 FPS"
                    selected_fps = int(re.search(r'(\d+)', fps).group(1))
                    orig_fps = getattr(self, 'current_orig_fps', 60)
                    # If we lowered the FPS, we calculate the coefficient 
                    if selected_fps < orig_fps and orig_fps > 0:
                        fps_multiplier = selected_fps / orig_fps
                except: pass

            if "Original" in bitrate_text:
                if hasattr(self, 'current_orig_bitrate') and self.current_orig_bitrate > 0:
            
                    orig_total_bitrate = (self.current_orig_bitrate * fps_multiplier) + 0.19 
                    
                    size_mb = (orig_total_bitrate * self.current_clip_duration_sec) / 8
                    if size_mb >= 1000:
                        size_str = f"Same as original (~{size_mb / 1024:.2f} GB)"
                    else:
                        size_str = f"Same as original (~{size_mb:.1f} MB)"
                else:
                    size_str = "Same as original"
            else:
                match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
                if match:
                    video_bitrate = float(match.group(1)) * fps_multiplier 
                    audio_bitrate = 0.19
                    total_bitrate = video_bitrate + audio_bitrate
                    size_mb = (total_bitrate * self.current_clip_duration_sec) / 8
                    if size_mb >= 1000:
                        size_str = f"~{size_mb / 1024:.2f} GB"
                    else:
                        size_str = f"~{size_mb:.1f} MB"
                else:
                    size_str = "Unknown"
        else:
            size_str = "Unknown"
            
        if hasattr(self.ui, 'label_approx_size'):
            self.ui.label_approx_size.setText(f"Approximate size: {size_str}")

        #4. Update Location
        save_dir = self.custom_destination if self.custom_destination else get_save_directory()
        filename = self.ui.input_filename.text().strip() if hasattr(self.ui, 'input_filename') else "rendered"
        if not filename.endswith(".mp4"): filename += ".mp4"
        
        full_path = os.path.join(save_dir, filename)
        if hasattr(self.ui, 'label_location'):
            self.ui.label_location.setText(f"Rendered video location: {full_path}")
        
        

    def start_render_thread(self):
        """ Prepares parameters and starts the background rendering thread """
        if not hasattr(self.ui, 'table_clips') or self.ui.table_clips.currentRow() < 0:
            QMessageBox.warning(self.ui, "Error", "Please select a clip from the list first!")
            return
            
        clip_name = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0).data(Qt.UserRole)
        all_mpds = self.get_all_mpd_paths(clip_name)
        
        if not all_mpds:
            QMessageBox.warning(self.ui, "Error", "session.mpd files not found inside this clip!")
            return

        save_dir = self.custom_destination if self.custom_destination else get_save_directory()
        
        # Read the desired file name from the text field
        custom_filename = f"{clip_name}_rendered" 
        if hasattr(self.ui, 'input_filename'):
            user_input = self.ui.input_filename.text().strip() 
            if user_input:
                custom_filename = user_input
                
        # Guarantee that the file will end in .mp4
        if not custom_filename.lower().endswith(".mp4"):
            custom_filename += ".mp4"
            
        output_file = os.path.join(save_dir, custom_filename)
        
        ffmpeg_exe = get_resource_path("ffmpeg.exe")
        if not os.path.exists(ffmpeg_exe):
            QMessageBox.critical(self.ui, "Error", "ffmpeg.exe not found!")
            return

        # Collecting settings from the UI
        quality_text = self.ui.combo_quality.currentText() if hasattr(self.ui, 'combo_quality') else "Original"
        fps_text = self.ui.combo_fps.currentText() if hasattr(self.ui, 'combo_fps') else "Original"
        
        # Get the basic video card codec (H.264)
        selected_encoder = self.ui.combo_encoder.currentData(Qt.UserRole) if hasattr(self.ui, 'combo_encoder') else "libx264"
        
        # if the user has selected H.265 in the new list, we convert the codec name
        if hasattr(self.ui, 'combo_codec'):
            if "H.265" in self.ui.combo_codec.currentText():
                selected_encoder = selected_encoder.replace("h264", "hevc").replace("libx264", "libx265")
                
        bitrate_text = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else "Original"
        video_bitrate = "12M"
        
        
        # Convert megabits to k for FFmpeg 
        if "Original" not in bitrate_text:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match:
                base_bitrate = float(match.group(1))
                
                # We calculate the same multiplier before rendering
                fps_multiplier = 1.0
                if fps_text:
                    try:
                        selected_fps = int(re.search(r'(\d+)', fps_text).group(1))
                        orig_fps = getattr(self, 'current_orig_fps', 60)
                        if selected_fps < orig_fps and orig_fps > 0:
                            fps_multiplier = selected_fps / orig_fps
                    except: pass
                
                # Multiply the bitrate by the coefficient and convert it into kb
                final_bitrate = int(base_bitrate * fps_multiplier * 1000)
                video_bitrate = f"{final_bitrate}k"

        # Enable process control buttons
        self.ui.btn_start.setEnabled(False) 
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(True)
        if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(True) 

        self.set_status("Initializing...")

        # Initialize and start an independent thread (so that the interface does not freeze)
        self.thread = RenderThread(all_mpds, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate, fps_text)
        self.thread.progress_signal.connect(self.set_status)
        self.thread.finished_signal.connect(self.on_render_finished)
        self.thread.start()

    def cancel_render(self):
        """ Cancel Button Handler """
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.set_status("Cancelling... Please wait")
            if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
            if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(False)
            self.thread.cancel() # Send a cancel signal to the thread

    def toggle_pause(self):
        """ Pause button handler """
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
        # Reset the buttons to their original state.
        self.ui.btn_start.setEnabled(True) 
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(False)
        if hasattr(self.ui, 'btn_pause'): 
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.setText("Pause")
            
        # Show the result to the user
        if success:
            self.set_status("Success")
            QMessageBox.information(self.ui, "Success!", f"Clip successfully saved to:\n{output_file}")
            self.set_status("Ready")
        elif "cancelled by user" in error_msg:
            self.set_status("Cancelled")
            QMessageBox.information(self.ui, "Cancelled", "Render was cancelled.")
            self.set_status("Ready")
        else:
            self.set_status(f"Error [{error_msg}]")
            QMessageBox.critical(self.ui, "Error", f"Failed to render video: {error_msg}")
            self.set_status("Ready")

# BACKGROUND RENDER THREAD (PROTECTS UI FROM FREEZING)
class RenderThread(QThread):
    progress_signal = Signal(str)  
    finished_signal = Signal(bool, str, str) 

    def __init__(self, mpd_paths, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate, fps_text):
        super().__init__()
        self.mpd_paths = mpd_paths
        self.quality_text = quality_text
        self.output_file = output_file
        self.ffmpeg_exe = ffmpeg_exe
        self.save_dir = save_dir
        
        self.selected_encoder = selected_encoder
        self.video_bitrate = video_bitrate
        self.fps_text = fps_text
        
        # Control flags
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
            
            # STEP 1: Render each .mpd part into a separate .mp4
            for idx, mpd in enumerate(self.mpd_paths):
                if self.is_cancelled:
                    raise Exception("Render cancelled by user.")
                    
                temp_mp4 = os.path.join(self.save_dir, f"temp_steempeg_part_{idx}.mp4")
                temp_files.append(temp_mp4)
                
                self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. (0%)")
                
                # Fix paths for FFmpeg (replace backslashes with forward slashes)
                safe_mpd = mpd.replace('\\', '/')

                fps_arg = ""
                if hasattr(self, 'fps_text') and "Original" not in self.fps_text:
                    match_fps = re.search(r'(\d+)', self.fps_text)
                    if match_fps:
                        fps_arg = f"-r {match_fps.group(1)} "
                
                # Generate a command for FFmpeg
                if "Original" in self.quality_text:
                    cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" {fps_arg}-c copy -y "{temp_mp4}"'
                else:
                    match = re.search(r'^(\d+)p', self.quality_text)
                    if match:
                        target_height = match.group(1)
                        audio_bitrate = "192k" if int(target_height) >= 1080 else "128k"
                        # Insert fps_arg into the compression command
                        cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" -vf scale=-1:{target_height} {fps_arg}-c:v {self.selected_encoder} -b:v {self.video_bitrate} -c:a aac -b:a {audio_bitrate} -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" {fps_arg}-c copy -y "{temp_mp4}"'

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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    try:
        import ctypes
        myappid = 'steempeg.app.v4'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except: pass
        
    try:
        import traceback
        window = SteempegApp()
        
        # Protection if the UI file is not found or is corrupted
        if getattr(window, 'ui', None) is None:
            QMessageBox.critical(None, "Interface Error", "Failed to load smpegui5.ui! Check if the file is located next to the script and that the name matches.")
            sys.exit(1)
            
        window.ui.show()
        sys.exit(app.exec())
    except Exception as e:
        # Now no mistake can hide =)))))))) =))))) dsfhnuijdfgbjiklgfvbjknlbfcvxjknml
        error_text = traceback.format_exc()
        print(error_text)
        QMessageBox.critical(None, "Critical error", f"The program crashed on startup:\n{error_text}")