"""Import user data from ``old_version_v*`` backup folders (Settings action)."""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from typing import Mapping

_log = logging.getLogger(__name__)

# Folders to pull from a local update backup into the live install.
IMPORT_FOLDER_NAMES: tuple[str, ...] = (
    "rendered_videos",
    "Screenshots",
    "cache",
)

# Keep when updating → folder-level import map (best-effort first slice).
# Settings / render history / presets live under cache/ or settings.json;
# full selective migrate is TODO (file-level merge).
_KEEP_VIDEO_FOLDERS: tuple[str, ...] = ("rendered_videos", "Screenshots")
_KEEP_CACHE_FOLDER: str = "cache"


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


def folders_for_keep_prefs(keep: Mapping[str, bool] | None) -> tuple[str, ...]:
    """Map Update Center Keep when updating prefs to import folder names.

    Videos → rendered_videos + Screenshots.
    Settings / Render history / Presets → whole ``cache`` (best-effort; file-level TODO).
    """
    if keep is None:
        return IMPORT_FOLDER_NAMES
    folders: list[str] = []
    if keep.get("videos", True):
        folders.extend(_KEEP_VIDEO_FOLDERS)
    # cache holds settings.json, render_queue.json, export-related prefs, etc.
    if (
        keep.get("settings", True)
        or keep.get("render_history", True)
        or keep.get("presets", True)
    ):
        folders.append(_KEEP_CACHE_FOLDER)
    # De-dupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for name in folders:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


def import_user_data_from_backup(
    backup_path: str,
    install_root: str,
    *,
    folders: tuple[str, ...] | None = None,
    keep: Mapping[str, bool] | None = None,
) -> BackupImportResult:
    """Merge selected folders from a backup into the live install (skip existing)."""
    if folders is None:
        folders = folders_for_keep_prefs(keep) if keep is not None else IMPORT_FOLDER_NAMES
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
