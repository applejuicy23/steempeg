"""Update checking, downloading and installation, mixed into the main application."""
import logging
import os
import subprocess
import sys
import webbrowser

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

from steempeg.infra.paths import get_install_root, get_save_directory, open_path_with_default_app
from steempeg.services.release_catalog import (
    FetchError,
    LocalBackup,
    ReleaseEntry,
    find_local_backups,
    latest_release_version,
)
from steempeg.services.update_job import UpdateJob, spawn_update_handler
from steempeg.ui import design_tokens as tok
from steempeg.ui.github_rate_limit_dialog import GitHubRateLimitDialog
from steempeg.ui.message_dialog import (
    DialogButton,
    steempeg_alert_actions,
    steempeg_critical,
    steempeg_warning,
)
from steempeg.ui.update_center import UpdateCenterDialog
from steempeg.ui.update_confirm_dialog import UpdateConfirmChoice, UpdateConfirmDialog
from steempeg.version import APP_VERSION_FLOAT, APP_VERSION_STR


class _SilentUpdateCheckThread(QThread):
    """Background GitHub catalog probe — never opens UI by itself."""

    finished_ok = Signal(list)
    finished_noop = Signal()

    def run(self):
        try:
            from steempeg.services.release_catalog import (
                fetch_releases,
                load_releases_cache,
                releases_cache_is_fresh,
            )

            if releases_cache_is_fresh():
                cached = load_releases_cache()
                if cached:
                    self.finished_ok.emit(cached)
                    return
            releases = fetch_releases()
            self.finished_ok.emit(releases)
        except FetchError:
            self.finished_noop.emit()
        except Exception:
            logging.exception("UPDATER: silent update check failed")
            self.finished_noop.emit()


class UpdaterMixin:
    def check_for_updates(self):
        """Open the Update Center to browse, install, or restore releases."""
        logging.info("--- UPDATER: Opening Update Center ---")
        tb = getattr(getattr(self, "ui", None), "title_bar", None)
        spin = getattr(tb, "btn_check_updates", None) if tb is not None else None
        # Prefer live render status over the update-check busy strip.
        rendering = bool(getattr(self, "_is_rendering", False))
        try:
            if spin is not None and hasattr(spin, "set_busy"):
                spin.set_busy(True)
            if not rendering:
                # Spinning purple update arrows (badge-sized) while the label
                # shows "Checking for updates..." — suppress queue badge like Loading.
                self._update_check_busy = True
                self.set_status("Checking for updates...")
            self._open_update_center()
        except Exception as e:
            logging.error(f"UPDATER: Critical exception: {e}")
            steempeg_critical(self.ui, "Updater Error", f"Could not open Update Center:\n{e}")
        finally:
            if spin is not None and hasattr(spin, "set_busy"):
                spin.set_busy(False)
            if tb is not None and hasattr(tb, "clear_shell_tool_hover"):
                tb.clear_shell_tool_hover()
            if not rendering:
                self._update_check_busy = False
                self.set_status("Ready")
            logging.info("--- UPDATER: check_for_updates finished ---")

    def schedule_silent_update_check(self, delay_ms: int = 2500) -> None:
        """Defer a quiet catalog check so the title-bar badge can appear."""
        from PySide6.QtCore import QTimer

        QTimer.singleShot(delay_ms, self._start_silent_update_check)

    def _start_silent_update_check(self) -> None:
        if getattr(self, "_silent_update_check_running", False):
            return
        self._silent_update_check_running = True
        thread = _SilentUpdateCheckThread(self.ui)
        self._silent_update_check_thread = thread
        thread.finished_ok.connect(self._on_silent_update_check_ok)
        thread.finished_noop.connect(self._on_silent_update_check_done)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_silent_update_check_done(self) -> None:
        self._silent_update_check_running = False

    def _on_silent_update_check_ok(self, releases: list) -> None:
        self._silent_update_check_running = False
        try:
            from steempeg.ui.settings_prefs import stamp_last_update_check

            stamp_last_update_check(self)
        except Exception:
            logging.exception("UPDATER: failed stamping last_update_check_ts")
        try:
            if not releases:
                self._set_title_bar_update_available(False)
                return
            latest = latest_release_version(releases)
            if latest > APP_VERSION_FLOAT + 0.001:
                latest_entry = releases[0]
                self._set_title_bar_update_available(
                    True, version=latest_entry.version_str
                )
            else:
                self._set_title_bar_update_available(False)
        except Exception:
            logging.exception("UPDATER: failed applying silent update result")
            self._set_title_bar_update_available(False)

    def _set_title_bar_update_available(
        self, available: bool, *, version: str | None = None
    ) -> None:
        tb = getattr(self.ui, "title_bar", None)
        if tb is None or not hasattr(tb, "set_update_available"):
            return
        tb.set_update_available(available, version=version)

    def _wire_title_bar_about_updates(self) -> None:
        tb = getattr(self.ui, "title_bar", None)
        if tb is None:
            return
        if getattr(tb, "_about_updates_wired", False):
            return
        tb._about_updates_wired = True
        if hasattr(tb, "about_requested"):
            tb.about_requested.connect(self.show_about_dialog)
        if hasattr(tb, "settings_requested"):
            tb.settings_requested.connect(self.show_settings_dialog)
        if hasattr(tb, "check_updates_requested"):
            tb.check_updates_requested.connect(self.check_for_updates)
        if hasattr(tb, "update_available_clicked"):
            tb.update_available_clicked.connect(self.check_for_updates)

    def _open_update_center(self):
        exe_dir = get_install_root()
        backups = find_local_backups(exe_dir)
        theme = tok.chrome_theme_colors(getattr(self, "_chrome_theme", tok.DEFAULT_CHROME_THEME))
        keep_prefs = None
        try:
            from steempeg.ui.settings_prefs import load_update_keep_when

            keep_prefs = load_update_keep_when(self.load_user_settings() or {})
        except Exception:
            logging.exception("UPDATER: failed loading keep prefs")

        while True:
            dlg = UpdateCenterDialog(
                local_backups=backups,
                parent=self.ui,
                bar_color=theme["title_bar"],
                bg_color=theme["app_bg"],
                settings_host=self,
                keep_prefs=keep_prefs,
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

        tb = getattr(getattr(self, "ui", None), "title_bar", None)
        if tb is not None and hasattr(tb, "clear_shell_tool_hover"):
            tb.clear_shell_tool_hover()
        self._clear_update_chrome_hover()

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
        accepted = dlg.exec() == dlg.DialogCode.Accepted
        # Nested confirm eats Leave on title-bar Updates / traffic lights.
        self._clear_update_chrome_hover()
        if not accepted:
            return

        if dlg.choice == UpdateConfirmChoice.CANCEL:
            return

        keep_backup = dlg.choice == UpdateConfirmChoice.UPDATE_KEEP_BACKUP

        from steempeg.ui.settings_prefs import load_update_keep_when

        try:
            keep = load_update_keep_when(self.load_user_settings() or {})
        except Exception:
            keep = {
                "videos": True,
                "settings": True,
                "render_history": True,
                "presets": True,
            }

        job = UpdateJob(
            url=entry.zip_url,
            asset_name=entry.zip_name,
            from_version=APP_VERSION_STR,
            target_version=entry.version_str,
            keep_backup=keep_backup,
            exe_dir=get_install_root(),
            chrome_theme=getattr(self, "_chrome_theme", tok.DEFAULT_CHROME_THEME),
            expected_size=entry.zip_size,
            expected_sha256=entry.zip_sha256,
            keep_videos=bool(keep.get("videos", True)),
            keep_settings=bool(keep.get("settings", True)),
            keep_render_history=bool(keep.get("render_history", True)),
            keep_presets=bool(keep.get("presets", True)),
        )
        spawn_update_handler(job)
        QApplication.quit()
        sys.exit(0)

    def _clear_update_chrome_hover(self) -> None:
        """Reset stuck hand-cursor / traffic-light hover after Update Center modals."""
        from steempeg.ui.widgets.dialog_chrome import SteempegDialog

        ui = getattr(self, "ui", None)
        tb = getattr(ui, "title_bar", None) if ui is not None else None
        if tb is not None:
            if hasattr(tb, "clear_shell_tool_hover"):
                tb.clear_shell_tool_hover()
            if hasattr(tb, "reset_traffic_lights"):
                tb.reset_traffic_lights()
        if ui is not None:
            try:
                ui.unsetCursor()
            except RuntimeError:
                pass
        for w in QApplication.topLevelWidgets():
            if isinstance(w, SteempegDialog):
                if hasattr(w, "reset_title_bar_chrome"):
                    w.reset_title_bar_chrome()
                try:
                    w.unsetCursor()
                except RuntimeError:
                    pass
        QApplication.restoreOverrideCursor()

    def _restore_local_backup(self, backup: LocalBackup):
        self.restore_local_backup(backup.folder_name)

    def show_update_success(self, old_version, backup_folder):
        """Shows a nice window after a successful update."""
        text = (
            f"<h3>Steempeg is updated!</h3>"
            f"<p>Successfully updated from <b>v{old_version}</b> to the latest version.</p>"
        )
        has_backup = bool(backup_folder and backup_folder != "None")
        if has_backup:
            text += (
                f"<p>Your old version was saved in the folder:<br><code>{backup_folder}</code></p>"
                "<p><small>Import rendered videos / Screenshots / cache from that backup, "
                "or restore the whole build via <b>Update Center</b>.</small></p>"
            )

        if has_backup:
            buttons = (
                DialogButton("Import from previous build", "secondary", accept=True),
                DialogButton("📂 Open Backup Folder", "secondary", accept=True),
                DialogButton("Good!", "primary", accept=True),
            )
        else:
            buttons = (DialogButton("Good!", "primary", accept=True),)

        clicked = steempeg_alert_actions(
            self.ui,
            "Update Successful!",
            text,
            buttons,
            rich_text=True,
            min_width=460,
        )

        if not has_backup:
            return

        backup_path = os.path.abspath(os.path.join(get_save_directory(), backup_folder))
        if clicked == 0:
            self._import_user_data_from_backup_path(backup_path, backup_folder)
        elif clicked == 1 and os.path.exists(backup_path):
            open_path_with_default_app(backup_path)

    def _import_user_data_from_backup_path(
        self, backup_path: str, backup_label: str = ""
    ) -> None:
        """Merge rendered_videos / Screenshots / cache from a backup into the live install."""
        from steempeg.services.backup_import import import_user_data_from_backup
        from steempeg.ui.message_dialog import steempeg_information
        from steempeg.ui.settings_prefs import load_update_keep_when

        if not backup_path or not os.path.isdir(backup_path):
            steempeg_warning(
                self.ui,
                "Import failed",
                f"Backup folder not found:\n{backup_label or backup_path}",
            )
            return

        try:
            keep = load_update_keep_when(self.load_user_settings() or {})
        except Exception:
            keep = None
        result = import_user_data_from_backup(
            backup_path, get_install_root(), keep=keep
        )
        folders = ", ".join(result.folders_touched) or "none"
        msg = (
            f"Copied {result.copied_files} file(s), "
            f"skipped {result.skipped_existing} existing.\n"
            f"Folders: {folders}."
        )
        if result.copied_files == 0 and result.skipped_existing == 0:
            msg = (
                "Nothing to import. That backup has no matching videos, "
                "Screenshots, or cache for the selected Keep when updating options "
                "(they may already be in the live install)."
            )
        if result.errors:
            msg += f"\n\n{len(result.errors)} error(s)."
        steempeg_information(self.ui, "Import from previous build", msg)
        if result.copied_files and hasattr(self, "scan_rendered_outputs"):
            try:
                self.scan_rendered_outputs()
            except Exception:
                pass

    def restore_local_backup(self, backup_folder_name: str):
        """Swap the live install with a backed-up tree (Windows .bat / Linux .sh)."""
        from steempeg.services.update_install import find_app_executable

        exe_dir = get_install_root()
        backup_path = os.path.join(exe_dir, backup_folder_name)
        if not os.path.isdir(backup_path):
            steempeg_warning(self.ui, "Restore Failed", f"Backup folder not found:\n{backup_folder_name}")
            return

        exe_name = find_app_executable(backup_path)
        staging_folder = f"pre_restore_v{APP_VERSION_STR}"
        pid = os.getpid()
        env = os.environ.copy()
        env.pop("_MEIPASS2", None)
        env.pop("_MEIPASS", None)

        if sys.platform == "win32":
            from steempeg.services.update_install import _bat_preserve_dir_guards

            dir_guards = _bat_preserve_dir_guards("%%D")
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
    if /I not "%%D"=="{backup_folder_name}" if /I not "%%D"=="{staging_folder}" {dir_guards} (
        echo %%D| findstr /I /B /C:"old_version_v" /C:"pre_restore_v" > NUL
        if errorlevel 1 move "%%D" "{staging_folder}\" > NUL
    )
)

echo Restoring backup from {backup_folder_name}...
xcopy /S /E /Y /C /I "{backup_folder_name}\\*" ".\\" > NUL

echo Starting restored version...
start "" "{exe_name}"
del "%~f0"
"""
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)
            subprocess.Popen([bat_path], shell=True, cwd=exe_dir, creationflags=0x08000000, env=env)
        else:
            from steempeg.services.update_install import _PRESERVE_DIRS

            keep_tests = " || ".join(
                f'[[ "$item" == "{name}" ]]' for name in sorted(_PRESERVE_DIRS)
            )
            sh_path = os.path.join(exe_dir, "restore.sh")
            sh_content = f"""#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
while kill -0 {pid} 2>/dev/null; do sleep 0.4; done
sleep 0.4
rm -rf "{staging_folder}"
mkdir -p "{staging_folder}"
for item in * .[!.]* ..?*; do
  [[ -e "$item" ]] || continue
  [[ "$item" == "restore.sh" ]] && continue
  [[ "$item" == "{backup_folder_name}" ]] && continue
  [[ "$item" == "{staging_folder}" ]] && continue
  {keep_tests} && continue
  [[ "$item" == old_version_v* || "$item" == pre_restore_v* ]] && continue
  mv -- "$item" "{staging_folder}/"
done
cp -a "{backup_folder_name}"/. .
chmod +x "{exe_name}" Steempeg-linux Steempeg.sh Steempeg Steempeg-steamdeck 2>/dev/null || true
chmod +x bin/ffmpeg bin/ffprobe 2>/dev/null || true
if [[ -d venv/bin ]]; then chmod -R a+x venv/bin 2>/dev/null || true; fi
rm -f "$0"
exec ./"{exe_name}"
"""
            with open(sh_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(sh_content)
            os.chmod(sh_path, 0o755)
            subprocess.Popen(["/bin/bash", sh_path], cwd=exe_dir, start_new_session=True, env=env)

        QApplication.quit()
        sys.exit(0)
