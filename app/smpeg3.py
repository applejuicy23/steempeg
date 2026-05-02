import sys
import os
import subprocess
import re
import psutil
import requests
from datetime import datetime
from PySide6.QtCore import Qt 
from PySide6.QtWidgets import QListWidgetItem
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread, Signal
from PySide6.QtGui import QIcon

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
        ui_file_path = get_resource_path("smpegui4.ui")
        ui_file = QFile(ui_file_path)
        
        if not ui_file.open(QFile.ReadOnly):
            return
            
        self.ui = loader.load(ui_file)
        ui_file.close()

        self.ui.setWindowTitle("Steempeg v3")
        
        # Setting the application icon
        icon_path = get_resource_path("logo.png")
        if os.path.exists(icon_path):
            self.ui.setWindowIcon(QIcon(icon_path))

        # 2. DATABASE AND VARIABLES
        # Steam bitrate dictionary in megabits (Mbps) for different resolutions
        self.steam_bitrate_presets = {
            "Ultra": {"4320p": 120, "2160p": 50, "1440p": 32, "1080p": 24, "720p": 12},
            "High": {"4320p": 90, "2160p": 38, "1440p": 22, "1080p": 12, "720p": 7.5},
            "Medium": {"4320p": 60, "2160p": 28.5, "1440p": 16.5, "1080p": 9, "720p": 5.6},
            "Low": {"4320p": 40, "2160p": 19, "1440p": 11, "1080p": 6, "720p": 3.75}
        }

        self.game_names_cache = {} # Cache for game names to avoid spamming the Steam API
        self.clips_folder = "" # Current clip folder
        self.custom_destination = "" # Custom save folder
        self.current_orig_bitrate = 0 # Bitrate of the selected original clip

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
        
        # 3. BINDING BUTTONS TO FUNCTIONS
        self.ui.btn_browse.clicked.connect(self.choose_folder)
        self.ui.btn_start.clicked.connect(self.start_render_thread)
        self.ui.list_clips.itemSelectionChanged.connect(self.update_quality_options)
        
        # Update the bitrate list when changing resolution
        if hasattr(self.ui, 'combo_quality'):
            self.ui.combo_quality.currentTextChanged.connect(self.update_bitrate_options) 
            
        self.ui.destination_button.clicked.connect(self.choose_destination)

        # Connect the pause and cancel buttons (they are initially disabled)
        if hasattr(self.ui, 'btn_cancel'):
            self.ui.btn_cancel.setEnabled(False)
            self.ui.btn_cancel.clicked.connect(self.cancel_render)
            
        if hasattr(self.ui, 'btn_pause'):
            self.ui.btn_pause.setEnabled(False)
            self.ui.btn_pause.clicked.connect(self.toggle_pause)

        # 4. AUTOMATIC DATA LOADING AT PROGRAM START
        default_path = r"C:\Program Files (x86)\Steam\userdata\1077964895\gamerecordings\clips"
        if os.path.exists(default_path):
            self.clips_folder = default_path
            self.scan_clips()
        
        # Automatically detect the video card and set the default codec
        self.detect_gpu_and_set_encoder()

    def set_status(self, text):
        """ Safely update text in the status bar """
        if hasattr(self.ui, 'label_status'):
            self.ui.label_status.setText(text)

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
        """ Scans the selected folder, searches for .mpd files, and loads them into the UI list. """
        self.ui.list_clips.clear()
        if not self.clips_folder or not os.path.exists(self.clips_folder):
            return

        try:
            items = os.listdir(self.clips_folder)
            for item_name in items:
                full_path = os.path.join(self.clips_folder, item_name)
                
                if os.path.isdir(full_path):
                    # Smart search. Open the folder and search for .mpd.
                    has_mpd = False
                    for root, dirs, files in os.walk(full_path):
                        if any(f.endswith(".mpd") for f in files):
                            has_mpd = True
                            break # Нашли хотя бы один .mpd - супер, выходим из поиска!
                    
                    # If there are no video files inside, we skip this garbage
                    if not has_mpd:
                        continue 

                    parts = item_name.split("_")
                    
                    # Trying to decipher Steam system names (clip_1190000_... or timeline_1190000_...)
                    if len(parts) >= 4 and parts[1].isdigit():
                        app_id = parts[1]
                        date_str = parts[2]
                        time_str = parts[3]

                        game_name = self.get_game_name(app_id)

                        try:
                            date_obj = datetime.strptime(date_str, "%Y%m%d")
                            formatted_date = date_obj.strftime("%d %B %Y")
                        except: formatted_date = date_str

                        try:
                            time_obj = datetime.strptime(time_str, "%H%M%S")
                            formatted_time = time_obj.strftime("%H:%M:%S")
                        except: formatted_time = time_str

                        display_text = f"{game_name} - {formatted_date} - {formatted_time}"
                    else:
                        # If you named the folder yourself, or it is a non-standard format
                        display_text = f"{item_name}"

                    # Add to the interface
                    list_item = QListWidgetItem(display_text)
                    list_item.setData(Qt.UserRole, item_name)
                    self.ui.list_clips.addItem(list_item)
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
        """ Gets the game's pretty name via the Steam API using its ID. """
        if app_id in self.game_names_cache:
            return self.game_names_cache[app_id]
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
            response = requests.get(url, timeout=3)
            data = response.json()
            if data and str(app_id) in data and data[str(app_id)].get("success"):
                game_name = data[str(app_id)]["data"]["name"]
                self.game_names_cache[app_id] = game_name
                return game_name
        except:
            pass
        return f"Unknown Game ({app_id})"
    
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
        selected_items = self.ui.list_clips.selectedItems()
        if not selected_items:
            self.ui.source_label.setText("Source:")
            self.ui.orig_res_label.setText("Original resolution:")
            return
            
        clip_name = selected_items[0].data(Qt.UserRole)
        
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
                    height_match = re.search(r'\bheight="(\d+)"', content)
                    width_match = re.search(r'\bwidth="(\d+)"', content)
                    bandwidth_match = re.search(r'\bbandwidth="(\d+)"', content)
                    
                    if bandwidth_match:
                        # Переводим битрейт из байт в мегабиты
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
            self.ui.combo_quality.addItem("Original (Lossless)")

            for preset_name, preset_height in self.all_qualities:
                if preset_height <= max_height:
                    self.ui.combo_quality.addItem(preset_name)
            
            self.ui.combo_quality.setCurrentIndex(0)
            self.update_bitrate_options() # Calling a function to update bitrates
    
    def update_bitrate_options(self):
        """ Обновляет список доступных битрейтов в зависимости от выбранного разрешения """
        if not hasattr(self.ui, 'combo_bitrate') or not hasattr(self.ui, 'combo_quality'):
            return 

        self.ui.combo_bitrate.clear()
        quality_text = self.ui.combo_quality.currentText()

        # If the original is selected, the bitrate cannot be changed
        if "Original" in quality_text:
            self.ui.combo_bitrate.addItem("Original Bitrate (Copy)")
            self.ui.combo_bitrate.setEnabled(False) 
            return

        self.ui.combo_bitrate.setEnabled(True) 
        
        # Extract the height from a string ("1080p")
        match = re.search(r'^(\d+)p', quality_text)
        if not match: return
            
        res_key = f"{match.group(1)}p"
        added_any = False
        
        # We go through Steam presets and add only those that make sense
        for quality_level in ["Ultra", "High", "Medium", "Low"]:
            if res_key in self.steam_bitrate_presets[quality_level]:
                preset_bitrate = self.steam_bitrate_presets[quality_level][res_key]
                
                # Add a preset only if it is not much higher than the original bitrate
                if self.current_orig_bitrate == 0 or preset_bitrate <= (self.current_orig_bitrate + 5):
                    self.ui.combo_bitrate.addItem(f"{quality_level} - {preset_bitrate} Mbps")
                    added_any = True
        
        # If the original was very bad, add at least Low for rendering
        if not added_any and res_key in self.steam_bitrate_presets["Low"]:
            lowest_bitrate = self.steam_bitrate_presets["Low"][res_key]
            self.ui.combo_bitrate.addItem(f"Low - {lowest_bitrate} Mbps")

    def start_render_thread(self):
        """ Prepares parameters and starts the background rendering thread """
        selected_item = self.ui.list_clips.currentItem()
        if not selected_item:
            QMessageBox.warning(self.ui, "Error", "Please select a clip from the list first!")
            return
            
        clip_name = selected_item.data(Qt.UserRole)
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
        selected_encoder = self.ui.combo_encoder.currentData(Qt.UserRole) if hasattr(self.ui, 'combo_encoder') else "libx264"
        bitrate_text = self.ui.combo_bitrate.currentText() if hasattr(self.ui, 'combo_bitrate') else "Original"
        video_bitrate = "12M" 
        
        # Convert megabits to k for FFmpeg 
        if "Original" not in bitrate_text:
            match = re.search(r'-\s*([\d.]+)\s*Mbps', bitrate_text)
            if match:
                video_bitrate = f"{int(float(match.group(1)) * 1000)}k"

        # Enable process control buttons
        self.ui.btn_start.setEnabled(False) 
        if hasattr(self.ui, 'btn_cancel'): self.ui.btn_cancel.setEnabled(True)
        if hasattr(self.ui, 'btn_pause'): self.ui.btn_pause.setEnabled(True) 

        self.set_status("Initializing...")

        # Initialize and start an independent thread (so that the interface does not freeze)
        self.thread = RenderThread(all_mpds, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate)
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
        """ Обработчик кнопки Pause """
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

    def __init__(self, mpd_paths, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate):
        super().__init__()
        self.mpd_paths = mpd_paths
        self.quality_text = quality_text
        self.output_file = output_file
        self.ffmpeg_exe = ffmpeg_exe
        self.save_dir = save_dir
        
        self.selected_encoder = selected_encoder
        self.video_bitrate = video_bitrate
        
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

                # Generate a command for FFmpeg
                if "Original" in self.quality_text:
                    cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" -c copy -y "{temp_mp4}"'
                else:
                    match = re.search(r'^(\d+)p', self.quality_text)
                    if match:
                        target_height = match.group(1)
                        audio_bitrate = "192k" if int(target_height) >= 1080 else "128k"
                        # We assemble a command taking into account the selected codec and bitrate
                        cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" -vf scale=-1:{target_height} -c:v {self.selected_encoder} -b:v {self.video_bitrate} -c:a aac -b:a {audio_bitrate} -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" -i "{safe_mpd}" -c copy -y "{temp_mp4}"'

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
                self.finished_signal.emit(True, "", self.output_file) # Успех!
            else:
                self.finished_signal.emit(False, "Merge failed.", "")

        except Exception as e:
            self.finished_signal.emit(False, str(e), "") # Ошибка!
            
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
        myappid = 'steempeg.app.v3'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except: pass
        
    window = SteempegApp()
    window.ui.show()
    sys.exit(app.exec())