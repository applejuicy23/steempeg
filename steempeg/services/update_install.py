"""Apply a downloaded update on disk (replaces updater.bat file moves)."""
from __future__ import annotations

import logging
import os
import shutil

_PRESERVE_DIRS = frozenset({"logs", "cache", "_update_extracted"})


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
