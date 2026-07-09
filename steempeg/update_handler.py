"""Detached update process (--update-handler): download through launch."""
from __future__ import annotations

import logging
import os
import shutil
import sys
import zipfile

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from steempeg.infra.paths import get_resource_path
from steempeg.services.update_install import (
    find_app_executable,
    resolve_extract_source,
    spawn_deferred_install,
    write_deferred_install_bat,
)
from steempeg.services.update_job import UpdateJob, load_update_job
from steempeg.services.updater import UpdateDownloadThread
from steempeg.ui import design_tokens as tok
from steempeg.ui.update_progress_dialog import UpdateProgressDialog


def run_update_handler(job_path: str) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    job = load_update_job(job_path)
    os.chdir(job.exe_dir)

    app = QApplication(sys.argv)
    icon_path = get_resource_path("logo.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    theme = tok.chrome_theme_colors(job.chrome_theme)
    dialog = UpdateProgressDialog(
        f"v{job.target_version}",
        bar_color=theme["title_bar"],
        bg_color=theme["app_bg"],
    )
    dialog.show()

    state: dict = {"thread": None}

    def fail(message: str) -> None:
        dialog.set_phase("error")
        dialog.set_detail(message)
        QMessageBox.critical(dialog, "Update Failed", message)

    def on_download_done(success: bool, filepath: str, asset_name: str) -> None:
        if not success:
            if not filepath and not asset_name:
                app.quit()
                return
            fail(filepath or "Download was cancelled or failed.")
            return
        try:
            dialog.set_phase("extract", percent=72)
            dialog.set_detail("Unpacking release archive…")
            QApplication.processEvents()

            extract_root = os.path.join(job.exe_dir, "_update_extracted")
            if os.path.exists(extract_root):
                shutil.rmtree(extract_root, ignore_errors=True)
            os.makedirs(extract_root, exist_ok=True)
            with zipfile.ZipFile(filepath, "r") as archive:
                archive.extractall(extract_root)

            source_dir = resolve_extract_source(extract_root)
            new_exe_name = find_app_executable(source_dir)

            dialog.set_phase("install", percent=85)
            dialog.set_detail("Preparing file replacement…")
            QApplication.processEvents()

            bat_path = write_deferred_install_bat(
                handler_pid=os.getpid(),
                exe_dir=job.exe_dir,
                source_dir=source_dir,
                extract_root=extract_root,
                keep_backup=job.keep_backup,
                from_version=job.from_version,
                new_exe_name=new_exe_name,
                tmp_asset_name=asset_name,
            )
            spawn_deferred_install(bat_path, job.exe_dir)

            dialog.set_phase("launch")
            dialog.set_detail("Closing updater, then installing and starting Steempeg…")
            QApplication.processEvents()

            QTimer.singleShot(400, dialog.close)
            QTimer.singleShot(500, app.quit)
        except Exception as exc:
            logging.exception("UPDATE_HANDLER: install failed")
            fail(str(exc))

    thread = UpdateDownloadThread(job.url, job.exe_dir, job.asset_name)
    state["thread"] = thread

    def on_progress(percent: int, text: str) -> None:
        dialog.set_download_progress(percent, text)

    thread.progress_signal.connect(on_progress)
    thread.finished_signal.connect(on_download_done)
    dialog.cancel_requested.connect(thread.cancel)
    thread.start()

    return app.exec()
