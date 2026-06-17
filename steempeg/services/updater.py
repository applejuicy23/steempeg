"""Background worker that downloads an application update and reports progress.

Receives the download URL, target directory and asset name through its constructor
and emits progress and completion signals; it holds no reference to the application.
"""
import os
import time

import requests

from PySide6.QtCore import QThread, Signal


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