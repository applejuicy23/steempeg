"""Update checking, downloading and installation, mixed into the main application."""
import logging
import os
import subprocess
import sys
import webbrowser

from PySide6.QtWidgets import QApplication, QMessageBox

from steempeg.infra.paths import get_save_directory
from steempeg.services.release_catalog import LocalBackup, ReleaseEntry, find_local_backups
from steempeg.services.update_job import UpdateJob, spawn_update_handler
from steempeg.ui import design_tokens as tok
from steempeg.ui.github_rate_limit_dialog import GitHubRateLimitDialog
from steempeg.ui.update_center import UpdateCenterDialog
from steempeg.ui.update_confirm_dialog import UpdateConfirmChoice, UpdateConfirmDialog
from steempeg.version import APP_VERSION_STR


class UpdaterMixin:
    def check_for_updates(self):
        """Open the Update Center to browse, install, or restore releases."""
        logging.info("--- UPDATER: Opening Update Center ---")
        try:
            self.set_status("Checking for updates...")
            self._open_update_center()
        except Exception as e:
            logging.error(f"UPDATER: Critical exception: {e}")
            QMessageBox.critical(self.ui, "Updater Error", f"Could not open Update Center:\n{e}")
        finally:
            self.set_status("Ready")
            logging.info("--- UPDATER: check_for_updates finished ---")

    def _open_update_center(self):
        exe_dir = os.path.dirname(sys.executable)
        backups = find_local_backups(exe_dir)
        theme = tok.chrome_theme_colors(getattr(self, "_chrome_theme", tok.DEFAULT_CHROME_THEME))

        while True:
            dlg = UpdateCenterDialog(
                local_backups=backups,
                parent=self.ui,
                bar_color=theme["title_bar"],
                bg_color=theme["app_bg"],
            )
            dlg.install_requested.connect(self._install_release_entry)
            dlg.restore_requested.connect(self._restore_local_backup)

            rate_limit_info = []

            def _capture_rate_limit(info):
                rate_limit_info.append(info)

            dlg.rate_limited.connect(_capture_rate_limit)
            dlg.exec()

            if not rate_limit_info:
                break

            limit_dlg = GitHubRateLimitDialog(
                rate_limit_info[0],
                parent=self.ui,
                bar_color=theme["title_bar"],
                bg_color=theme["app_bg"],
            )
            limit_dlg.exec()
            if not limit_dlg.timer_completed:
                break

    def _install_release_entry(self, entry: ReleaseEntry):
        if not entry.zip_url or not entry.zip_name:
            webbrowser.open(entry.html_url)
            return

        theme = tok.chrome_theme_colors(getattr(self, "_chrome_theme", tok.DEFAULT_CHROME_THEME))
        dlg = UpdateConfirmDialog(
            entry.version_str,
            parent=self.ui,
            bar_color=theme["title_bar"],
            bg_color=theme["app_bg"],
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        if dlg.choice == UpdateConfirmChoice.CANCEL:
            return

        keep_backup = dlg.choice == UpdateConfirmChoice.UPDATE_KEEP_BACKUP

        job = UpdateJob(
            url=entry.zip_url,
            asset_name=entry.zip_name,
            from_version=APP_VERSION_STR,
            target_version=entry.version_str,
            keep_backup=keep_backup,
            exe_dir=os.path.dirname(sys.executable),
            chrome_theme=getattr(self, "_chrome_theme", tok.DEFAULT_CHROME_THEME),
        )
        spawn_update_handler(job)
        QApplication.quit()
        sys.exit(0)

    def _restore_local_backup(self, backup: LocalBackup):
        self.restore_local_backup(backup.folder_name)

    def show_update_success(self, old_version, backup_folder):
        """Shows a nice window after a successful update."""
        msg = QMessageBox(self.ui)
        msg.setWindowTitle("Update Successful!")
        msg.setIcon(QMessageBox.Information)

        text = (
            f"<h3>Steempeg is updated!</h3>"
            f"<p>Successfully updated from <b>v{old_version}</b> to the latest version.</p>"
        )
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
