import sys
import os
import subprocess
import re
import requests
from datetime import datetime
from PySide6.QtCore import Qt 
from PySide6.QtWidgets import QListWidgetItem
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread, Signal
from PySide6.QtGui import QIcon

def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)

def get_save_directory():
    """ Get the directory where the executable is launched to save rendered videos """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)

# BACKGROUND WORKER FOR RENDERING!
class RenderThread(QThread):
    # Signal to send text to the status bar
    progress_signal = Signal(str)  
    # Signal for completion: Success(bool), Error text, File path
    finished_signal = Signal(bool, str, str) 

    def __init__(self, cmd, working_dir, output_file):
        super().__init__()
        self.cmd = cmd
        self.working_dir = working_dir
        self.output_file = output_file
        # Cache to store game names so we don't spam the Steam API
        self.game_names_cache = {}

    def run(self):
        try:
            # CREATE_NO_WINDOW flag prevents the black CMD popup during render
            creation_flags = 0x08000000 if sys.platform == "win32" else 0
            
            # Using Popen instead of run to read FFmpeg console on the fly
            process = subprocess.Popen(
                self.cmd,
                shell=True,
                cwd=self.working_dir,
                creationflags=creation_flags,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='ignore'
            )

            total_duration = 0

            # Read FFmpeg output line by line
            for line in process.stdout:
                print(line.strip())
                # 1. Find total video duration
                if total_duration == 0:
                    dur_match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                    if dur_match:
                        h, m, s = float(dur_match.group(1)), float(dur_match.group(2)), float(dur_match.group(3))
                        total_duration = h * 3600 + m * 60 + s

                # 2. Find current render time and calculate percentage
                time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                if time_match and total_duration > 0:
                    h, m, s = float(time_match.group(1)), float(time_match.group(2)), float(time_match.group(3))
                    current_time = h * 3600 + m * 60 + s
                    percent = int((current_time / total_duration) * 100)
                    # Limit to 100% just in case
                    self.progress_signal.emit(f"Process.. ({min(percent, 100)}%)")

            process.wait()

            if process.returncode == 0:
                self.finished_signal.emit(True, "", self.output_file)
            else:
                self.finished_signal.emit(False, f"code {process.returncode}", "")

        except Exception as e:
            self.finished_signal.emit(False, str(e), "")


class SteempegApp:
    def __init__(self):
        # Load the UI design without parent to make it the main window
        loader = QUiLoader()
        ui_file_path = get_resource_path("smpegui2.ui")
        ui_file = QFile(ui_file_path)
        
        if not ui_file.open(QFile.ReadOnly):
            return
            
        self.ui = loader.load(ui_file)
        ui_file.close()

        # Set window title
        self.ui.setWindowTitle("Steempeg v2")
        
        # Load and set the application icon
        icon_path = get_resource_path("testlogo.png")
        if os.path.exists(icon_path):
            self.ui.setWindowIcon(QIcon(icon_path))
        

        # 1. DEFINE VARIABLES FIRST 
        self.game_names_cache = {}
        self.clips_folder = ""

        # Master list of all available resolutions
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


        # 2. CONNECT BUTTONS AND UI EVENTS
        self.custom_destination = "" 
        
        self.set_status("Ready")
        self.ui.btn_browse.clicked.connect(self.choose_folder)
        self.ui.btn_start.clicked.connect(self.start_render_thread)
        self.ui.list_clips.itemSelectionChanged.connect(self.update_quality_options)
        self.ui.destination_button.clicked.connect(self.choose_destination) # <-- NEW: Connect destination button

        # 3. AUTO-LOAD STEAM PATH AND SCAN (Do this LAST)
        default_path = r"C:\Program Files (x86)\Steam\userdata\1077964895\gamerecordings\clips"
        if os.path.exists(default_path):
            self.clips_folder = default_path
            self.scan_clips()

    def set_status(self, text):
        """ Helper method to safely update the status bar """
        if hasattr(self.ui, 'label_status'):
            self.ui.label_status.setText(text)

    def choose_folder(self):
        # Define the exact Steam clips path as the primary target
        target_path = r"C:\Program Files (x86)\Steam\userdata\1077964895\gamerecordings\clips"
        
        # Fallback to C:\ if the specific path does not exist
        if not os.path.exists(target_path):
            target_path = "C:\\"

        # Open directory selection dialog
        folder = QFileDialog.getExistingDirectory(self.ui, "Select clips folder", target_path)
        
        if folder:
            self.clips_folder = folder
            self.scan_clips()

    def scan_clips(self):
            """ Parse clip folders, fetch game names, and populate the UI list (DEBUG VERSION) """
            self.ui.list_clips.clear()
            
            # DEBUG 1: Did we even get a path?
            if not self.clips_folder:
                QMessageBox.warning(self.ui, "Debug 1", "Path is empty. Did you select a folder?")
                return
                
            # DEBUG 2: Does the path actually exist on the PC?
            if not os.path.exists(self.clips_folder):
                QMessageBox.warning(self.ui, "Debug 2", f"Windows cannot find this path:\n{self.clips_folder}\n\nIs your Steam installed on another drive?")
                return

            try:
                items = os.listdir(self.clips_folder)
                
                # DEBUG 3: Is the folder literally empty?
                if len(items) == 0:
                    QMessageBox.information(self.ui, "Debug 3", "The folder exists, but it is completely empty!")
                    return

                added_count = 0
                for item_name in items:
                    full_path = os.path.join(self.clips_folder, item_name)
                    
                    # Check if it's a folder AND starts with 'clip_'
                    if os.path.isdir(full_path) and item_name.startswith("clip_"):
                        parts = item_name.split("_")
                        
                        if len(parts) >= 4:
                            app_id = parts[1]
                            date_str = parts[2]
                            time_str = parts[3]

                            game_name = self.get_game_name(app_id)

                            try:
                                date_obj = datetime.strptime(date_str, "%Y%m%d")
                                formatted_date = date_obj.strftime("%d %B %Y")
                            except ValueError:
                                formatted_date = date_str

                            try:
                                time_obj = datetime.strptime(time_str, "%H%M%S")
                                formatted_time = time_obj.strftime("%H:%M:%S")
                            except ValueError:
                                formatted_time = time_str

                            display_text = f"{game_name} - {formatted_date} - {formatted_time}"
                        else:
                            display_text = item_name

                        list_item = QListWidgetItem(display_text)
                        list_item.setData(Qt.UserRole, item_name)
                        
                        self.ui.list_clips.addItem(list_item)
                        added_count += 1
                
                # DEBUG 4: We found files, but none matched the rules!
                if added_count == 0:
                    # Show exactly what the program sees in that folder
                    sample_items = "\n".join(items[:5])
                    QMessageBox.warning(self.ui, "Debug 4", f"Found {len(items)} items, but NONE match our rules (must be a folder starting with 'clip_').\n\nFirst 5 items found:\n{sample_items}")

            except Exception as e:
                QMessageBox.critical(self.ui, "Scan Error", f"Something crashed:\n{str(e)}")
    
    def choose_destination(self):
        """ Allow user to pick a custom folder to save the rendered video """
        folder = QFileDialog.getExistingDirectory(self.ui, "Select Destination Folder")
        if folder:
            self.custom_destination = folder
            # Update button text to show the selected path
            self.ui.destination_button.setText(f"Destination: {folder}")
        else:
            # If user cancels, reset to default
            self.custom_destination = ""
            self.ui.destination_button.setText("Choose destination")
        
    def get_all_mpd_paths(self, clip_name):
            """ Recursively find ALL .mpd files inside the clip's folder """
            mpd_paths = []
            clip_dir = os.path.join(self.clips_folder, clip_name)
            
            if os.path.exists(clip_dir):
                # os.walk drills down into every single subfolder automatically
                for root, dirs, files in os.walk(clip_dir):
                    for file in files:
                        if file.endswith(".mpd"):
                            mpd_paths.append(os.path.join(root, file))
            return sorted(mpd_paths)
    
    def get_game_name(self, app_id):
        """ Fetch game name from Steam API or return from cache """
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
        except Exception:
            pass

        # Fallback if API fails or no internet connection
        return f"Unknown Game ({app_id})"
    
    def update_quality_options(self):
            """ Read all XMLs, populate combo box, and update multi-source labels """
            selected_items = self.ui.list_clips.selectedItems()
            if not selected_items:
                self.ui.source_label.setText("Source:")
                self.ui.orig_res_label.setText("Original resolution:")
                return
                
            clip_name = selected_items[0].data(Qt.UserRole)
            all_mpds = self.get_all_mpd_paths(clip_name)

            # 1. Process Source Label
            if not all_mpds:
                self.ui.source_label.setText("Source: No MPD files found")
                self.ui.orig_res_label.setText("Original resolution: Unknown")
                self.ui.combo_quality.clear()
                return

            # Extract only the folder paths and remove duplicates
            source_dirs = [os.path.dirname(mpd) for mpd in all_mpds]
            unique_source_dirs = list(dict.fromkeys(source_dirs))
            
            # Enable word wrap so long paths don't break the UI window
            self.ui.source_label.setWordWrap(True)
            self.ui.source_label.setText("Source:\n" + ",\n".join(unique_source_dirs))

            # 2. Process Resolutions
            unique_resolutions = set()
            max_height = 0

            for mpd_path in all_mpds:
                try:
                    with open(mpd_path, 'r', encoding='utf-8') as file:
                        content = file.read()
                        height_match = re.search(r'\bheight="(\d+)"', content)
                        width_match = re.search(r'\bwidth="(\d+)"', content)
                        
                        if height_match and width_match:
                            h = int(height_match.group(1))
                            w = int(width_match.group(1))
                            unique_resolutions.add(f"{w}x{h}")
                            if h > max_height:
                                max_height = h
                except Exception:
                    pass

            # Display unique resolutions joined by comma
            if unique_resolutions:
                res_text = ", ".join(sorted(list(unique_resolutions)))
                self.ui.orig_res_label.setText(f"Original resolution: {res_text}")
            else:
                self.ui.orig_res_label.setText("Original resolution: Unknown")
                max_height = 1080 # Fallback

            # 3. Populate Combo Box based on the LARGEST height found
            self.ui.combo_quality.clear()
            self.ui.combo_quality.addItem("Original (Lossless)")

            for preset_name, preset_height in self.all_qualities:
                if preset_height <= max_height:
                    self.ui.combo_quality.addItem(preset_name)
            
            self.ui.combo_quality.setCurrentIndex(0)
    
    def start_render_thread(self):
            """ Prepare data and pass it to the multi-stage background thread """
            selected_item = self.ui.list_clips.currentItem()
            if not selected_item:
                QMessageBox.warning(self.ui, "Error", "Please select a clip from the list first!")
                return
                
            clip_name = selected_item.data(Qt.UserRole)
            all_mpds = self.get_all_mpd_paths(clip_name)
            
            if not all_mpds:
                QMessageBox.warning(self.ui, "Error", "session.mpd files not found inside this clip!")
                return

            # Determine where to save the file
            save_dir = self.custom_destination if self.custom_destination else get_save_directory()
            output_file = os.path.join(save_dir, f"{clip_name}_rendered.mp4")
            
            ffmpeg_exe = get_resource_path("ffmpeg.exe")
            if not os.path.exists(ffmpeg_exe):
                QMessageBox.critical(self.ui, "Error", "ffmpeg.exe not found!")
                return

            quality_text = self.ui.combo_quality.currentText()

            self.ui.btn_start.setEnabled(False) 
            self.set_status("Initializing...")

            # Pass all the raw data to the thread. It will handle the multi-stage logic!
            self.thread = RenderThread(all_mpds, quality_text, output_file, ffmpeg_exe, save_dir)
            self.thread.progress_signal.connect(self.set_status)
            self.thread.finished_signal.connect(self.on_render_finished)
            self.thread.start()

    def on_render_finished(self, success, error_msg, output_file):
        """ Triggered when the thread finishes its execution """
        self.ui.btn_start.setEnabled(True) # Unlock button
        
        if success:
            self.set_status("Success")
            # MessageBox pauses execution until closed
            QMessageBox.information(self.ui, "Success!", f"Clip successfully saved to:\n{output_file}")
            # Reset status after closing
            self.set_status("Ready")
        else:
            self.set_status(f"Error [{error_msg}]")
            QMessageBox.critical(self.ui, "Error", f"Failed to render video: {error_msg}")
            self.set_status("Ready")

# --- BACKGROUND WORKER FOR RENDERING ---
class RenderThread(QThread):
    progress_signal = Signal(str)  
    finished_signal = Signal(bool, str, str) 

    def __init__(self, mpd_paths, quality_text, output_file, ffmpeg_exe, save_dir):
        super().__init__()
        self.mpd_paths = mpd_paths
        self.quality_text = quality_text
        self.output_file = output_file
        self.ffmpeg_exe = ffmpeg_exe
        self.save_dir = save_dir # Directory to store temporary files

    def run(self):
        temp_files = []
        concat_file = None
        try:
            creation_flags = 0x08000000 if sys.platform == "win32" else 0

            # STEP 1: Render each MPD to a temporary MP4 file
            for idx, mpd in enumerate(self.mpd_paths):
                temp_mp4 = os.path.join(self.save_dir, f"temp_steempeg_part_{idx}.mp4")
                temp_files.append(temp_mp4)
                
                self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. (0%)")

                # Generate render command for this specific part
                if "Original" in self.quality_text:
                    cmd = f'"{self.ffmpeg_exe}" -i "{mpd}" -c copy -y "{temp_mp4}"'
                else:
                    match = re.search(r'^(\d+)p', self.quality_text)
                    if match:
                        target_height = match.group(1)
                        bitrate = "192k" if int(target_height) >= 1080 else "128k"
                        crf_value = "23" if int(target_height) >= 1080 else "28"
                        # CPU encoding
                        cmd = f'"{self.ffmpeg_exe}" -i "{mpd}" -vf scale=-1:{target_height} -c:v libx264 -preset fast -crf {crf_value} -c:a aac -b:a {bitrate} -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" -i "{mpd}" -c copy -y "{temp_mp4}"'

                # Execute and track progress
                process = subprocess.Popen(
                    cmd, shell=True, cwd=os.path.dirname(mpd),
                    creationflags=creation_flags, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', errors='ignore'
                )

                total_duration = 0
                for line in process.stdout:
                    if total_duration == 0:
                        dur_match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                        if dur_match:
                            h, m, s = float(dur_match.group(1)), float(dur_match.group(2)), float(dur_match.group(3))
                            total_duration = h * 3600 + m * 60 + s

                    time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                    if time_match and total_duration > 0:
                        h, m, s = float(time_match.group(1)), float(time_match.group(2)), float(time_match.group(3))
                        current_time = h * 3600 + m * 60 + s
                        percent = int((current_time / total_duration) * 100)
                        self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. ({min(percent, 100)}%)")

                process.wait()
                if process.returncode != 0:
                    raise Exception(f"Failed to render part {idx+1}")

            # STEP 2: Concat all temporary MP4s into the final file
            self.progress_signal.emit("Merging all parts...")
            concat_file = os.path.join(self.save_dir, "temp_concat_list.txt")
            
            with open(concat_file, "w", encoding="utf-8") as f:
                for tmp in temp_files:
                    safe_path = tmp.replace('\\', '/')
                    f.write(f"file '{safe_path}'\n")

            # -c copy merges video instantly without losing quality
            concat_cmd = f'"{self.ffmpeg_exe}" -f concat -safe 0 -i "{concat_file}" -c copy -y "{self.output_file}"'
            concat_process = subprocess.run(
                concat_cmd, shell=True, cwd=self.save_dir,
                creationflags=creation_flags, capture_output=True, text=True
            )

            if concat_process.returncode == 0:
                self.finished_signal.emit(True, "", self.output_file)
            else:
                self.finished_signal.emit(False, f"Merge failed: {concat_process.stderr}", "")

        except Exception as e:
            self.finished_signal.emit(False, str(e), "")
            
        finally:
            # STEP 3: CLEANUP (Delete temp MP4s and the text file)
            if concat_file and os.path.exists(concat_file):
                try: os.remove(concat_file)
                except: pass
            for tmp in temp_files:
                if os.path.exists(tmp):
                    try: os.remove(tmp)
                    except: pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Force system to show custom icon in taskbar
    try:
        import ctypes
        myappid = 'steempeg.app.v1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass
        
    window = SteempegApp()
    window.ui.show()
    sys.exit(app.exec())