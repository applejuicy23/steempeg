"""Disk cache of timeline hover frames (PyAV sniper).

First visit: PyAV decode for the tip (unchanged hot path), then a cheap
tip-sized JPEG is written under ``cache/timeline_previews/`` *after* the tip
is shown. Later visits: load file — no re-decode.

Full source-res sync encode on the decode path was dropped — it added
~20–60 ms to every first hit (120 → 140–180). Tip-sized cache still makes
revisits lightning; UI already displays at tip size.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil

_log = logging.getLogger(__name__)

SUBDIR = "timeline_previews"
_JPEG_QUALITY = 85


def _norm_media_path(path: str) -> str:
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(path)).replace("\\", "/")


def media_fingerprint(media_path: str) -> str:
    """Stable id for a media file/manifest — path + mtime so rewrites miss."""
    norm = _norm_media_path(media_path)
    if not norm:
        return ""
    try:
        mtime = int(os.path.getmtime(media_path))
    except OSError:
        mtime = 0
    raw = f"{norm}|{mtime}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def preview_dir(cache_dir: str | None, media_path: str) -> str:
    fp = media_fingerprint(media_path)
    if not cache_dir or not fp:
        return ""
    return os.path.join(cache_dir, SUBDIR, fp)


def preview_path(cache_dir: str | None, media_path: str, sec: int) -> str:
    folder = preview_dir(cache_dir, media_path)
    if not folder:
        return ""
    return os.path.join(folder, f"s{max(0, int(sec)):05d}.jpg")


def load_preview_bytes(cache_dir: str | None, media_path: str, sec: int) -> bytes | None:
    path = preview_path(cache_dir, media_path, sec)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        if not data:
            return None
        # LRU touch for prune_media_cache (oldest-mtime first).
        try:
            os.utime(path, None)
        except OSError:
            pass
        return data
    except OSError as exc:
        _log.debug("timeline preview load miss %s: %s", path, exc)
        return None


def save_preview_qimage(
    cache_dir: str | None,
    media_path: str,
    sec: int,
    qimage,
) -> str | None:
    """Write a tip-sized JPEG for *sec* (call after tip emit — not on hot path)."""
    if qimage is None or getattr(qimage, "isNull", lambda: True)():
        return None
    path = preview_path(cache_dir, media_path, sec)
    if not path:
        return None
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        _log.debug("timeline preview mkdir failed %s: %s", folder, exc)
        return None
    if os.path.isfile(path):
        return path
    tmp = path + ".tmp"
    try:
        # quality 0–100; no PIL optimize pass — keep this off the tip latency budget.
        if not qimage.save(tmp, "JPG", _JPEG_QUALITY):
            raise OSError("QImage.save failed")
        os.replace(tmp, path)
        return path
    except Exception as exc:
        _log.debug("timeline preview save failed sec=%s: %s", sec, exc)
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return None


def purge_media_timeline_previews(
    cache_dir: str | None,
    media_or_clip_path: str | None,
) -> None:
    """Drop cached frames for a media file or a Steam clip folder."""
    if not cache_dir or not media_or_clip_path:
        return
    roots = [media_or_clip_path]
    if os.path.isdir(media_or_clip_path):
        for name in (
            "session_fixed.mpd",
            "session.mpd",
            "video.mpd",
            "dash.mpd",
        ):
            candidate = os.path.join(media_or_clip_path, name)
            if os.path.isfile(candidate):
                roots.append(candidate)
    for root in roots:
        folder = preview_dir(cache_dir, root)
        if folder and os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
            _log.info(
                "Purged timeline preview cache: %s",
                os.path.basename(folder),
            )
