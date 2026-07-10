"""Steam clip preview images: folder lookup and ffmpeg poster cache."""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys

from steempeg.core.dash import discovery, repair

_THUMB_NAMES = ("thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def find_clip_thumbnail(clip_path: str) -> str:
    """Return a preview image path for a clip folder, or '' if none found.

    Checks canonical Steam names in the clip root, then any image in the root,
    then one level of subfolders (some libraries nest thumbs).
    """
    if not clip_path or not os.path.isdir(clip_path):
        return ""

    clip_path = os.path.normpath(clip_path)

    for name in _THUMB_NAMES:
        candidate = os.path.join(clip_path, name)
        if os.path.isfile(candidate):
            return candidate

    try:
        for entry in os.listdir(clip_path):
            lower = entry.lower()
            if lower.endswith(_IMAGE_EXTS):
                return os.path.join(clip_path, entry)
    except OSError:
        return ""

    try:
        for entry in os.listdir(clip_path):
            sub = os.path.join(clip_path, entry)
            if not os.path.isdir(sub):
                continue
            for name in _THUMB_NAMES:
                candidate = os.path.join(sub, name)
                if os.path.isfile(candidate):
                    return candidate
            for sub_entry in os.listdir(sub):
                if sub_entry.lower().endswith(_IMAGE_EXTS):
                    return os.path.join(sub, sub_entry)
    except OSError:
        pass

    return ""


def _clip_folder_identity(clip_path: str) -> str:
    norm = os.path.normcase(os.path.normpath(clip_path))
    try:
        st = os.stat(clip_path)
        return f"{norm}|{st.st_mtime_ns}"
    except OSError:
        return norm


def clip_poster_cache_path(cache_dir: str, clip_path: str) -> str:
    key = hashlib.sha256(_clip_folder_identity(clip_path).encode("utf-8")).hexdigest()[:20]
    folder = os.path.join(cache_dir, "clip_posters")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{key}.jpg")


def _find_poster_mpd(clip_path: str) -> str:
    """Best playable manifest to sample a poster frame from."""
    mpds = discovery.find_mpd_paths(clip_path)
    if mpds:
        return mpds[0]

    if not os.path.isdir(clip_path):
        return ""

    for root, _dirs, files in os.walk(clip_path):
        if "session_fixed.mpd" in files:
            return os.path.join(root, "session_fixed.mpd")
        if "session_salvage.mpd" in files:
            return os.path.join(root, "session_salvage.mpd")
        if "session.mpd" in files:
            return repair.fix_steam_manifest(os.path.join(root, "session.mpd"))
    return ""


def extract_clip_poster_frame(clip_path: str, cache_dir: str) -> str:
    """Generate a cached JPEG poster from the clip manifest via ffmpeg."""
    if not clip_path or not cache_dir:
        return ""

    out_path = clip_poster_cache_path(cache_dir, clip_path)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_path

    mpd_path = _find_poster_mpd(clip_path)
    if not mpd_path or not os.path.isfile(mpd_path):
        return ""

    for seek in ("1", "0"):
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    seek,
                    "-i",
                    mpd_path,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    out_path,
                ],
                check=True,
                timeout=25,
                creationflags=_NO_WINDOW,
            )
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                return out_path
        except (OSError, subprocess.SubprocessError) as exc:
            logging.debug(
                "Clip poster extract failed for %s (seek=%ss): %s",
                clip_path,
                seek,
                exc,
            )
    return ""


def resolve_clip_thumbnail(
    clip_path: str,
    cache_dir: str | None = None,
    *,
    allow_generate: bool = False,
) -> str:
    """Folder thumbnail first, then cached/generated ffmpeg poster."""
    thumb = find_clip_thumbnail(clip_path)
    if thumb:
        return thumb
    if not cache_dir:
        return ""

    cached = clip_poster_cache_path(cache_dir, clip_path)
    if os.path.isfile(cached) and os.path.getsize(cached) > 0:
        return cached
    if not allow_generate:
        return ""
    return extract_clip_poster_frame(clip_path, cache_dir)
