"""Import user data from ``old_version_v*`` backup folders (Settings action)."""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass

_log = logging.getLogger(__name__)

# Folders to pull from a local update backup into the live install.
IMPORT_FOLDER_NAMES: tuple[str, ...] = (
    "rendered_videos",
    "Screenshots",
    "cache",
)


@dataclass(frozen=True)
class BackupImportResult:
    copied_files: int
    skipped_existing: int
    folders_touched: tuple[str, ...]
    errors: tuple[str, ...]


def _copy_tree_skip_existing(src: str, dst: str) -> tuple[int, int, list[str]]:
    """Copy files from *src* into *dst*; never overwrite an existing file."""
    copied = 0
    skipped = 0
    errors: list[str] = []
    if not os.path.isdir(src):
        return 0, 0, errors
    os.makedirs(dst, exist_ok=True)
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        dest_root = dst if rel in (".", "") else os.path.join(dst, rel)
        try:
            os.makedirs(dest_root, exist_ok=True)
        except OSError as exc:
            errors.append(f"{dest_root}: {exc}")
            continue
        for name in files:
            s = os.path.join(root, name)
            d = os.path.join(dest_root, name)
            if os.path.exists(d):
                skipped += 1
                continue
            try:
                shutil.copy2(s, d)
                copied += 1
            except OSError as exc:
                errors.append(f"{name}: {exc}")
    return copied, skipped, errors


def import_user_data_from_backup(
    backup_path: str,
    install_root: str,
    *,
    folders: tuple[str, ...] = IMPORT_FOLDER_NAMES,
) -> BackupImportResult:
    """Merge selected folders from a backup into the live install (skip existing)."""
    if not backup_path or not os.path.isdir(backup_path):
        return BackupImportResult(0, 0, (), ("Backup folder not found.",))
    if not install_root or not os.path.isdir(install_root):
        return BackupImportResult(0, 0, (), ("Install folder not found.",))

    total_copied = 0
    total_skipped = 0
    touched: list[str] = []
    errors: list[str] = []

    for name in folders:
        src = os.path.join(backup_path, name)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(install_root, name)
        copied, skipped, errs = _copy_tree_skip_existing(src, dst)
        if copied or skipped or os.path.isdir(src):
            touched.append(name)
        total_copied += copied
        total_skipped += skipped
        errors.extend(errs)
        _log.info(
            "Backup import %s → %s: copied=%s skipped=%s",
            src,
            dst,
            copied,
            skipped,
        )

    return BackupImportResult(
        copied_files=total_copied,
        skipped_existing=total_skipped,
        folders_touched=tuple(touched),
        errors=tuple(errors),
    )
