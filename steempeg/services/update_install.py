"""Apply a downloaded update on disk (replaces updater.bat file moves)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile

_PRESERVE_DIRS = frozenset({"logs", "cache", "_update_extracted"})
_CREATE_NO_WINDOW = 0x08000000


def resolve_extract_source(extract_root: str) -> str:
    items = os.listdir(extract_root)
    if len(items) == 1 and os.path.isdir(os.path.join(extract_root, items[0])):
        return os.path.join(extract_root, items[0])
    return extract_root


def find_app_executable(directory: str) -> str:
    for name in os.listdir(directory):
        lower = name.lower()
        if name.endswith(".exe") and "ffmpeg" not in lower and "ffprobe" not in lower:
            return name
    return "Steempeg.exe"


def _should_preserve(name: str, *, backup_folder: str | None, tmp_asset: str | None) -> bool:
    if name in _PRESERVE_DIRS:
        return True
    if backup_folder and name == backup_folder:
        return True
    if tmp_asset and name == f"{tmp_asset}.tmp":
        return True
    if name.endswith(".bat"):
        return True
    return False


def apply_installed_update(
    exe_dir: str,
    source_dir: str,
    *,
    keep_backup: bool,
    from_version: str,
    tmp_asset_name: str | None = None,
) -> tuple[str, str]:
    """Replace live install files. Returns (new_exe_name, backup_folder_name)."""
    backup_folder_name = f"old_version_v{from_version}" if keep_backup else "None"
    backup_path = os.path.join(exe_dir, backup_folder_name) if keep_backup else None

    if keep_backup and backup_path:
        os.makedirs(backup_path, exist_ok=True)

    for name in list(os.listdir(exe_dir)):
        if _should_preserve(name, backup_folder=backup_folder_name if keep_backup else None, tmp_asset=tmp_asset_name):
            continue
        path = os.path.join(exe_dir, name)
        if keep_backup and backup_path:
            dest = os.path.join(backup_path, name)
            if os.path.exists(dest):
                if os.path.isdir(dest):
                    shutil.rmtree(dest, ignore_errors=True)
                else:
                    os.remove(dest)
            shutil.move(path, dest)
        else:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)

    for name in os.listdir(source_dir):
        src = os.path.join(source_dir, name)
        dst = os.path.join(exe_dir, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    new_exe_name = find_app_executable(source_dir)
    logging.info("UPDATE_INSTALL: installed %s (backup=%s)", new_exe_name, backup_folder_name)
    return new_exe_name, backup_folder_name


def _bat_path(path: str) -> str:
    """Escape a path for embedding in a generated .bat file."""
    return os.path.normpath(path).replace("%", "%%")


def write_deferred_install_bat(
    *,
    handler_pid: int,
    exe_dir: str,
    source_dir: str,
    extract_root: str,
    keep_backup: bool,
    from_version: str,
    new_exe_name: str,
    tmp_asset_name: str | None = None,
) -> str:
    """Write a temp .bat that waits for the handler to exit, then swaps files.

    The handler process loads PyInstaller extensions from exe_dir, so in-place
    install must run only after that process has fully terminated.
    """
    backup_folder = f"old_version_v{from_version}" if keep_backup else ""
    tmp_guard = f'if /I not "%%I"=="{tmp_asset_name}.tmp" ' if tmp_asset_name else ""
    bat_path = os.path.join(tempfile.gettempdir(), f"steempeg_install_{handler_pid}.bat")

    if keep_backup:
        remove_block = f"""if exist "{_bat_path(os.path.join(exe_dir, backup_folder))}" rd /S /Q "{_bat_path(os.path.join(exe_dir, backup_folder))}"
mkdir "{_bat_path(os.path.join(exe_dir, backup_folder))}"
for %%I in (*.*) do (
    {tmp_guard}move "%%I" "{_bat_path(os.path.join(exe_dir, backup_folder))}\\" > NUL 2>&1
)
for /D %%D in (*) do (
    if /I not "%%D"=="logs" if /I not "%%D"=="cache" if /I not "%%D"=="_update_extracted" if /I not "%%D"=="{backup_folder}" (
        if exist "%%D" move "%%D" "{_bat_path(os.path.join(exe_dir, backup_folder))}\\" > NUL 2>&1
    )
)"""
    else:
        remove_block = f"""for %%I in (*.*) do (
    {tmp_guard}del /F /Q "%%I" > NUL 2>&1
)
for /D %%D in (*) do (
    if /I not "%%D"=="logs" if /I not "%%D"=="cache" if /I not "%%D"=="_update_extracted" (
        if exist "%%D" rd /S /Q "%%D" > NUL 2>&1
    )
)"""

    backup_arg = backup_folder if keep_backup else "None"
    tmp_cleanup = f'if exist "{tmp_asset_name}.tmp" del /F /Q "{tmp_asset_name}.tmp" > NUL 2>&1' if tmp_asset_name else ""
    bat_content = f"""@echo off
title Steempeg Update
cd /D "{_bat_path(exe_dir)}"

:wait_loop
tasklist /FI "PID eq {handler_pid}" 2>NUL | find "{handler_pid}" >NUL
if errorlevel 1 goto do_install
timeout /t 1 /nobreak >NUL
goto wait_loop

:do_install
{remove_block}
robocopy "{_bat_path(source_dir)}" "{_bat_path(exe_dir)}" /E /IS /IT /NFL /NDL /NJH /NJS /NC /NS /NP > NUL
if exist "{_bat_path(extract_root)}" rd /S /Q "{_bat_path(extract_root)}"
{tmp_cleanup}
start "" "{new_exe_name}" --updated-from {from_version} --backup-folder {backup_arg}
del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as handle:
        handle.write(bat_content)
    logging.info("UPDATE_INSTALL: deferred install script %s", bat_path)
    return bat_path


def spawn_deferred_install(bat_path: str, exe_dir: str) -> None:
    subprocess.Popen(
        [bat_path],
        shell=True,
        cwd=exe_dir,
        creationflags=_CREATE_NO_WINDOW,
    )
