"""Update checking, downloading and installation, mixed into the main application.

These methods drive the in-app updater: querying the release feed, prompting the user,
spawning an UpdateDownloadThread, reporting progress and applying the downloaded build.
They run on the application instance and reach its widgets and state through self.
"""
import logging
import os
import re
import shutil
import subprocess
import sys
import webbrowser
import zipfile

import requests

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from steempeg.infra.paths import get_save_directory
from steempeg.services.updater import UpdateDownloadThread
from steempeg.version import APP_VERSION_FLOAT, APP_VERSION_STR


class UpdaterMixin:
    def check_for_updates(self):
        """ Checks GitHub API for new releases with deep logging """

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
            backup_path = os.path.abspath(os.path.join(get_save_directory(), backup_folder))
            if os.path.exists(backup_path):
                os.startfile(backup_path)

    # final_asset_name
    def on_update_downloaded(self, success, filepath, final_asset_name):
        """ Unpacks the ZIP, asks about a backup, and launches the BAT ninja. """
        if not success:
            if filepath: QMessageBox.warning(self.ui, "Update Failed", f"Could not download the update.\n{filepath}")
            return


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


