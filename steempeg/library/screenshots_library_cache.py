"""Persist the Screenshots grid between sessions (Skip startup).

UI snapshot only — Skip restores rows as-is; Refresh does a real folder walk.
Thumbs live under ``cache/screenshot_thumbs/`` so paint never decodes full PNGs.

v2: unified Steam + Steempeg shelf (``source``, ``app_id`` on rows).
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any

from steempeg.infra import cache as json_cache

CACHE_FILENAME = "screenshots_library_cache.json"
CACHE_VERSION = 2
THUMB_DIR = "screenshot_thumbs"
# ~2× the on-screen photo well so HiDPI + Smooth scale stay sharp.
THUMB_MAX_W = 384
THUMB_MAX_H = 216
THUMB_JPEG_QUALITY = 92
THUMB_GEN_VERSION = 2


def screenshots_library_cache_path(cache_dir: str | None) -> str:
    return os.path.join(cache_dir or "", CACHE_FILENAME)


def _thumb_key(file_path: str, mtime: float) -> str:
    norm = os.path.normcase(os.path.normpath(file_path))
    return hashlib.sha256(
        f"{norm}|{float(mtime):.6f}|{THUMB_MAX_W}x{THUMB_MAX_H}|v{THUMB_GEN_VERSION}".encode(
            "utf-8"
        )
    ).hexdigest()[:20]


def screenshot_thumb_path(cache_dir: str, file_path: str, mtime: float) -> str:
    """Stable thumb path keyed by file path + mtime (seconds)."""
    folder = os.path.join(cache_dir, THUMB_DIR)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{_thumb_key(file_path, mtime)}.jpg")


def screenshot_thumb_path_nostat(cache_dir: str, file_path: str, mtime: float) -> str:
    """Same as ``screenshot_thumb_path`` but does not create the folder."""
    return os.path.join(cache_dir, THUMB_DIR, f"{_thumb_key(file_path, mtime)}.jpg")


def save_screenshots_library_cache(
    cache_dir: str | None,
    *,
    folder: str,
    files: list[dict[str, Any]],
) -> None:
    if not cache_dir:
        return
    payload = {
        "version": CACHE_VERSION,
        "saved_at": time.time(),
        "folder": os.path.normpath(folder) if folder else "",
        "unified": True,
        "files": list(files),
    }
    json_cache.write_json(screenshots_library_cache_path(cache_dir), payload)


def clear_screenshots_library_cache(cache_dir: str | None) -> None:
    path = screenshots_library_cache_path(cache_dir)
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def files_from_screenshots_library_cache(
    cache_dir: str | None,
    *,
    folder: str | None = None,
) -> list[dict[str, Any]]:
    """Return snapshot rows. No screenshot-folder I/O."""
    path = screenshots_library_cache_path(cache_dir)
    payload = json_cache.read_json(path, default={})
    if not isinstance(payload, dict):
        return []

    version = int(payload.get("version") or 1)
    unified = bool(payload.get("unified")) or version >= 2
    # Legacy v1 caches were Steempeg-folder-only — require folder match.
    if not unified and folder:
        cached_folder = os.path.normcase(os.path.normpath(str(payload.get("folder") or "")))
        want = os.path.normcase(os.path.normpath(folder))
        if cached_folder and want and cached_folder != want:
            return []

    raw = payload.get("files")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        file_path = str(entry.get("full_path") or "").strip()
        if not file_path:
            continue
        try:
            mtime = float(entry.get("mtime") or 0.0)
        except (TypeError, ValueError):
            mtime = 0.0
        source = str(entry.get("source") or "steempeg").strip().lower() or "steempeg"
        if source not in ("steam", "steempeg"):
            source = "steempeg"
        out.append(
            {
                "full_path": os.path.normpath(file_path),
                "mtime": mtime,
                "game_name": str(entry.get("game_name") or ""),
                "source": source,
                "app_id": str(entry.get("app_id") or ""),
            }
        )
    return out
