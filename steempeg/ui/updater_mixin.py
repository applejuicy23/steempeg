"""Update checking, downloading and installation, mixed into the main application.

These methods drive the in-app updater: querying the release feed, prompting the user,
spawning an UpdateDownloadThread, reporting progress and applying the downloaded build.
They run on the application instance and reach its widgets and state through self.
"""
import logging
import os
import shutil
import subprocess
import sys
import webbrowser
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from steempeg.infra.paths import get_save_directory
from steempeg.services.release_catalog import LocalBackup, ReleaseEntry, find_local_backups
from steempeg.services.updater import UpdateDownloadThread
from steempeg.ui import design_tokens as tok
from steempeg.ui.update_center import UpdateCenterDialog
from steempeg.version import APP_VERSION_STR


class UpdaterMixin:
    def check_for_updates(self):
        """Open the Update Center to browse, install, or restore releases."""
        logging.info("--- UPDATER: Opening Update Center ---")
        try:
            self.set_status("Checking for updates...")
            exe_dir = os.path.dirname(sys.executable)
            backups = find_local_backups(exe_dir)
            theme = tok.chrome_theme_colors(getattr(self, "_chrome_theme", tok.DEFAULT_CHROME_THEME))
            dlg = UpdateCenterDialog(
                local_backups=backups,
                parent=self.ui,
                bar_color=theme["title_bar"],
                bg_color=theme["app_bg"],
            )
            dlg.install_requested.connect(self._install_release_entry)
            dlg.restore_requested.connect(self._restore_local_backup)
            dlg.exec()
        except Exception as e:
            logging.error(f"UPDATER: Critical exception: {e}")
            QMessageBox.critical(self.ui, "Updater Error", f"Could not open Update Center:\n{e}")
        finally:
            self.set_status("Ready")
            logging.info("--- UPDATER: check_for_updates finished ---")

    def _install_release_entry(self, entry: ReleaseEntry):
        if not entry.zip_url or not entry.zip_name:
            webbrowser.open(entry.html_url)
            return
        self.start_downloading_update(entry.zip_url, entry.zip_name)

    def _restore_local_backup(self, backup: LocalBackup):
        self.restore_local_backup(backup.folder_name)

    def start_downloading_update(self, url, asset_name):
        """Starts the background download and shows a progress bar."""
        self.progress_dialog = QProgressDialog("Starting download...", "Cancel", 0, 100, self.ui)
        self.progress_dialog.setWindowTitle("Steempeg Updater")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setAutoClose(True)
        self.progress_dialog.setValue(0)
        self.progress_dialog.setMinimumWidth(400)

        self.update_thread = UpdateDownloadThread(url, os.path.dirname(sys.executable), asset_name)
        self.update_thread.progress_signal.connect(self.update_download_progress)
        self.update_thread.finished_signal.connect(self.on_update_downloaded)

        self.progress_dialog.canceled.connect(self.update_thread.cancel)
        self.update_thread.start()
        self.progress_dialog.show()

    def update_download_progress(self, percent, text):
        """Dynamically updates the text and progress bar of the updater."""
        self.progress_dialog.setLabelText(text)
        self.progress_dialog.setValue(percent)

    def show_update_success(self, old_version, backup_folder):
        """Shows a nice window after a successful update."""
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

    def restore_local_backup(self, backup_folder_name: str):
        """Swap the live install with a backed-up tree via restore.bat."""
        exe_dir = os.path.dirname(sys.executable)
        backup_path = os.path.join(exe_dir, backup_folder_name)
        if not os.path.isdir(backup_path):
            QMessageBox.warning(self.ui, "Restore Failed", f"Backup folder not found:\n{backup_folder_name}")
            return

        exe_name = os.path.basename(sys.executable)
        for file in os.listdir(backup_path):
            if file.endswith(".exe") and "ffmpeg" not in file.lower() and "ffprobe" not in file.lower():
                exe_name = file
                break

        staging_folder = f"pre_restore_v{APP_VERSION_STR}"
        pid = os.getpid()
        bat_path = os.path.join(exe_dir, "restore.bat")

        bat_content = f"""@echo off
title Steempeg Restore
echo Waiting for Steempeg to close completely...

:wait_loop
tasklist /FI "PID eq {pid}" | find "{pid}" > NUL
if errorlevel 1 goto restore
timeout /t 1 /nobreak > NUL
goto wait_loop

:restore
echo Moving current version aside...
if exist "{staging_folder}" rd /S /Q "{staging_folder}"
mkdir "{staging_folder}"

for %%I in (*.*) do if /I not "%%I"=="restore.bat" move "%%I" "{staging_folder}\" > NUL
for /D %%D in (*) do (
    if /I not "%%D"=="{backup_folder_name}" if /I not "%%D"=="{staging_folder}" if /I not "%%D"=="logs" if /I not "%%D"=="cache" move "%%D" "{staging_folder}\" > NUL
)

echo Restoring backup from {backup_folder_name}...
xcopy /S /E /Y /C /I "{backup_folder_name}\\*" ".\\" > NUL

echo Starting restored version...
start "" "{exe_name}"
del "%~f0"
"""
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        env = os.environ.copy()
        env.pop("_MEIPASS2", None)
        env.pop("_MEIPASS", None)

        subprocess.Popen([bat_path], shell=True, cwd=exe_dir, creationflags=0x08000000, env=env)
        QApplication.quit()
        sys.exit(0)

    def on_update_downloaded(self, success, filepath, final_asset_name):
        """Unpacks the ZIP, asks about a backup, and launches the BAT ninja."""
        if not success:
            if filepath:
                QMessageBox.warning(self.ui, "Update Failed", f"Could not download the update.\n{filepath}")
            return

        current_exe = sys.executable
        exe_dir = os.path.dirname(current_exe)

        CURRENT_VERSION = APP_VERSION_STR

        extract_dir = os.path.join(exe_dir, "_update_extracted")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(filepath, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
        except Exception as e:
            QMessageBox.critical(self.ui, "Extraction Error", f"Failed to unzip the update!\n{e}")
            return

        extracted_items = os.listdir(extract_dir)
        if len(extracted_items) == 1 and os.path.isdir(os.path.join(extract_dir, extracted_items[0])):
            source_dir = os.path.join("_update_extracted", extracted_items[0])
        else:
            source_dir = "_update_extracted"

        new_exe_name = "Steempeg.exe"
        full_source_path = os.path.join(exe_dir, source_dir)
        for file in os.listdir(full_source_path):
            if file.endswith(".exe") and "ffmpeg" not in file.lower() and "ffprobe" not in file.lower():
                new_exe_name = file
                break

        msg = QMessageBox(self.ui)
        msg.setWindowTitle("Update Ready to Install!")
        msg.setText(
            "The new version has been downloaded and extracted.\n"
            "Do you want to replace the current files, or keep them as a backup?"
        )
        msg.setIcon(QMessageBox.Question)

        btn_delete = msg.addButton("🗑️ Replace (Delete old)", QMessageBox.AcceptRole)
        btn_keep = msg.addButton("📦 Keep backup", QMessageBox.ActionRole)
        msg.exec()

        keep_old = msg.clickedButton() == btn_keep
        backup_folder_name = f"old_version_v{CURRENT_VERSION}" if keep_old else "None"
        is_backup_true = "True" if keep_old else "False"

        pid = os.getpid()
        bat_path = os.path.join(exe_dir, "updater.bat")

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
        env.pop("_MEIPASS2", None)
        env.pop("_MEIPASS", None)

        subprocess.Popen([bat_path], shell=True, cwd=exe_dir, creationflags=0x08000000, env=env)

        QApplication.quit()
        sys.exit(0)
