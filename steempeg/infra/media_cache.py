"""Disk media-cache helpers: size cap + purge clip sidecars on delete."""
from __future__ import annotations

import logging
import os
from typing import Iterable

_log = logging.getLogger(__name__)

# Preview / poster / remux leftovers — never touch settings.json / games.json.
_MEDIA_CACHE_SUBDIRS: tuple[str, ...] = (
    "clip_posters",
    "rendered_posters",
    "mpd_playback",
)


def _iter_files(root: str) -> Iterable[tuple[str, int, float]]:
    """Yield (path, size, mtime) for files under *root* (recursive)."""
    if not os.path.isdir(root):
        return
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            yield path, int(st.st_size), float(st.st_mtime)


def media_cache_bytes(cache_dir: str | None) -> int:
    if not cache_dir:
        return 0
    total = 0
    for sub in _MEDIA_CACHE_SUBDIRS:
        folder = os.path.join(cache_dir, sub)
        for _path, size, _mtime in _iter_files(folder) or ():
            total += size
    return total


def prune_media_cache(cache_dir: str | None, limit_gb: int) -> tuple[int, int]:
    """Delete oldest media-cache files until under *limit_gb*.

    ``limit_gb <= 0`` means unlimited (no prune). Returns ``(removed, freed_bytes)``.
    """
    if not cache_dir or limit_gb <= 0:
        return 0, 0
    max_bytes = int(limit_gb) * 1024**3
    entries: list[tuple[str, int, float]] = []
    for sub in _MEDIA_CACHE_SUBDIRS:
        folder = os.path.join(cache_dir, sub)
        for item in _iter_files(folder) or ():
            entries.append(item)
    total = sum(sz for _, sz, _ in entries)
    if total <= max_bytes:
        return 0, 0
    entries.sort(key=lambda t: t[2])  # oldest first
    removed = 0
    freed = 0
    while entries and total > max_bytes:
        path, size, _ = entries.pop(0)
        try:
            os.remove(path)
            removed += 1
            freed += size
            total -= size
        except OSError as exc:
            _log.debug("media cache prune skip %s: %s", path, exc)
    if removed:
        _log.info(
            "Pruned media cache: %d file(s), freed %.1f MB (cap %d GB)",
            removed,
            freed / (1024**2),
            limit_gb,
        )
    return removed, freed


def purge_clip_media_cache(cache_dir: str | None, clip_path: str | None) -> None:
    """Remove poster + marker sidecar for a clip (call before deleting the folder)."""
    if not cache_dir or not clip_path:
        return
    try:
        from steempeg.core.clip_thumbnails import clip_poster_cache_path

        poster = clip_poster_cache_path(cache_dir, clip_path)
        if poster and os.path.isfile(poster):
            os.remove(poster)
            _log.info("Purged clip poster cache: %s", os.path.basename(poster))
    except Exception as exc:
        _log.debug("clip poster purge skipped: %s", exc)

    try:
        from steempeg.core.clip_markers_cache import clip_markers_sidecar_path

        sidecar = clip_markers_sidecar_path(cache_dir, clip_path=clip_path)
        if sidecar and os.path.isfile(sidecar):
            os.remove(sidecar)
            _log.info("Purged clip markers cache: %s", os.path.basename(sidecar))
    except Exception as exc:
        _log.debug("clip markers purge skipped: %s", exc)
