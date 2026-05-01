import sys
import os
import subprocess
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile
from PySide6.QtGui import QIcon

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)

def get_save_dir():
    """ Gets the path to the folder where the .exe file is located (so that the video is saved nearby)) """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(__file__)

class SteempegApp(QDialog):
    def __init__(self):
        super().__init__()
        
        # Load the UI design
        loader = QUiLoader()
        ui_file_path = resource_path("smpegui.ui")
        ui_file = QFile(ui_file_path)
        
        if not ui_file.open(QFile.ReadOnly):
            print(f"Failed to open file: {ui_file_path}")
            return
            
        self.ui = loader.load(ui_file, self)
        ui_file.close()

        self.ui.setWindowTitle("Steempeg - Extract Clips")
        
        # Загружаем и устанавливаем логотип (testlogo.png)
        icon_path = resource_path("testlogo.png")
        if os.path.exists(icon_path):
            self.ui.setWindowIcon(QIcon(icon_path))
        
        # Variable to store the selected folder path
        self.clips_folder = ""

        # Setup quality options
        self.ui.combo_quality.clear()
        self.ui.combo_quality.addItems([
            "Original (No loss)", 
            "1080p (Good Quality)", 
            "720p (Mid Quality)"
        ])

        # Connect buttons to functions
        self.ui.btn_browse.clicked.connect(self.choose_folder)
        self.ui.btn_start.clicked.connect(self.run_render)

    def choose_folder(self):
        # Open directory selection dialog
        folder = QFileDialog.getExistingDirectory(self, "Select clips folder", r"C:\Program Files (x86)\Steam\userdata")
        
        if folder:
            self.clips_folder = folder
            self.scan_clips()

    def scan_clips(self):
        self.ui.list_clips.clear()
        # Look for folders starting with 'clip_'
        try:
            for item in os.listdir(self.clips_folder):
                full_path = os.path.join(self.clips_folder, item)
                if os.path.isdir(full_path) and item.startswith("clip_"):
                    self.ui.list_clips.addItem(item)
        except Exception as e:
            print(f"Error reading folder: {e}")

    def run_render(self):
        # Check if a clip is selected in the list
        selected_item = self.ui.list_clips.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Error", "Please select a clip from the list first!")
            return
            
        clip_name = selected_item.text()
        
        # 1. Enter the video folder
        video_dir = os.path.join(self.clips_folder, clip_name, "video")
        mpd_path = None
        
        # 2. Look inside the video folder for any subfolder (the fg_... one)
        if os.path.exists(video_dir):
            for item in os.listdir(video_dir):
                subfolder_path = os.path.join(video_dir, item)
                
                if os.path.isdir(subfolder_path):
                    potential_mpd = os.path.join(subfolder_path, "session.mpd")
                    if os.path.exists(potential_mpd):
                        mpd_path = potential_mpd
                        break 
        
        if not mpd_path:
            QMessageBox.warning(self, "Error", "session.mpd file not found inside this clip!")
            return

        # Output folder for the rendered video (saves exactly where the .exe is launched)
        output_file = os.path.join(get_save_dir(), f"{clip_name}_rendered.mp4")
        
        quality = self.ui.combo_quality.currentText()
        
        # Get FFmpeg from the bundled temp folder
        ffmpeg_exe = resource_path("ffmpeg.exe")
        
        if not os.path.exists(ffmpeg_exe):
            QMessageBox.critical(self, "Error", "ffmpeg.exe not found!")
            return

        working_dir = os.path.dirname(mpd_path)

        # Form the FFmpeg command
        if "Original" in quality:
            cmd = f'"{ffmpeg_exe}" -i "session.mpd" -c copy -y "{output_file}"'
        elif "1080p" in quality:
            cmd = f'"{ffmpeg_exe}" -i "session.mpd" -vf scale=-1:1080 -c:v libx264 -preset fast -crf 23 -c:a aac -b:a 192k -y "{output_file}"'
        elif "720p" in quality:
            cmd = f'"{ffmpeg_exe}" -i "session.mpd" -vf scale=-1:720 -c:v libx264 -preset fast -crf 28 -c:a aac -b:a 128k -y "{output_file}"'
        else:
            cmd = f'"{ffmpeg_exe}" -i "session.mpd" -c copy -y "{output_file}"'

        try:
            subprocess.run(cmd, shell=True, check=True, cwd=working_dir)
            QMessageBox.information(self, "Success!", f"Clip saved to:\n{output_file}")
        except subprocess.CalledProcessError:
            QMessageBox.critical(self, "Error", "Failed to render video. Please check the console.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SteempegApp()
    window.ui.show()
    sys.exit(app.exec())
