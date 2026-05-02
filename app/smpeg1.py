import sys
import os
import subprocess
import re
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
        self.ui.setWindowTitle("Steempeg v1")
        
        # Load and set the application icon
        icon_path = get_resource_path("testlogo.png")
        if os.path.exists(icon_path):
            self.ui.setWindowIcon(QIcon(icon_path))
        
        # Variable to store the selected folder path
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

        # Set base status on launch
        self.set_status("Ready")

        # Connect buttons and list events
        self.ui.btn_browse.clicked.connect(self.choose_folder)
        self.ui.btn_start.clicked.connect(self.start_render_thread)
        self.ui.list_clips.itemSelectionChanged.connect(self.update_quality_options)

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
        self.ui.list_clips.clear()
        # Look for folders starting with ¨clip_¨
        try:
            for item in os.listdir(self.clips_folder):
                full_path = os.path.join(self.clips_folder, item)
                if os.path.isdir(full_path) and item.startswith("clip_"):
                    self.ui.list_clips.addItem(item)
        except Exception:
            pass

    def get_mpd_path(self, clip_name):
        """ Helper method to find the session.mpd file """
        video_dir = os.path.join(self.clips_folder, clip_name, "video")
        if os.path.exists(video_dir):
            for item in os.listdir(video_dir):
                subfolder_path = os.path.join(video_dir, item)
                if os.path.isdir(subfolder_path):
                    potential_mpd = os.path.join(subfolder_path, "session.mpd")
                    if os.path.exists(potential_mpd):
                        return potential_mpd
        return None

    def update_quality_options(self):
        """ Read the XML and dynamically populate the combo box """
        selected_items = self.ui.list_clips.selectedItems()
        if not selected_items:
            return
            
        clip_name = selected_items[0].text()
        mpd_path = self.get_mpd_path(clip_name)
        
        self.ui.combo_quality.clear()
        self.ui.combo_quality.addItem("Original (Lossless)")

        if mpd_path:
            try:
                with open(mpd_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                    # Use Regex to find the height attribute in the XML
                    match = re.search(r'height="(\d+)"', content)
                    
                    if match:
                        original_height = int(match.group(1))
                        # Only add options that are equal or smaller than original
                        for preset_name, preset_height in self.all_qualities:
                            if preset_height <= original_height:
                                self.ui.combo_quality.addItem(preset_name)
            except Exception:
                pass
        
        # Select "Original" by default
        self.ui.combo_quality.setCurrentIndex(0)

    def start_render_thread(self):
        """ Prepare data and start the background thread for rendering """
        selected_item = self.ui.list_clips.currentItem()
        if not selected_item:
            QMessageBox.warning(self.ui, "Error", "Please select a clip from the list first!")
            return
            
        clip_name = selected_item.text()
        mpd_path = self.get_mpd_path(clip_name)
        
        if not mpd_path:
            QMessageBox.warning(self.ui, "Error", "session.mpd file not found inside this clip!")
            return

        # Output file saves exactly where the .exe is located
        output_file = os.path.join(get_save_directory(), f"{clip_name}_rendered.mp4")
        quality_text = self.ui.combo_quality.currentText()
        
        ffmpeg_exe = get_resource_path("ffmpeg.exe")
        
        if not os.path.exists(ffmpeg_exe):
            QMessageBox.critical(self.ui, "Error", "ffmpeg.exe not found!")
            return

        working_dir = os.path.dirname(mpd_path)

        # Dynamic command generation based on user selection
        if "Original" in quality_text:
            cmd = f'"{ffmpeg_exe}" -i "session.mpd" -c copy -y "{output_file}"'
        else:
            match = re.search(r'^(\d+)p', quality_text)
            if match:
                target_height = match.group(1)
                # Bitrate logic based on resolution to keep it optimal
                bitrate = "192k" if int(target_height) >= 1080 else "128k"
                crf_value = "23" if int(target_height) >= 1080 else "28"
                cmd = f'"{ffmpeg_exe}" -i "session.mpd" -vf scale=-1:{target_height} -c:v libx264 -preset fast -crf {crf_value} -c:a aac -b:a {bitrate} -y "{output_file}"'
            else:
                cmd = f'"{ffmpeg_exe}" -i "session.mpd" -c copy -y "{output_file}"'

        # Lock button and set status
        self.ui.btn_start.setEnabled(False) 
        self.set_status("Process.. (0%)")

        # Create worker and connect signals
        self.thread = RenderThread(cmd, working_dir, output_file)
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
