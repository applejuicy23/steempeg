"""Resolve Steam client screenshot files for timeline screenshot markers.

Steam saves screenshots under::

    <Steam>/userdata/<steam_id>/760/remote/<app_id>/screenshots/

Filenames look like ``20260711152410_1.jpg`` (local ``YYYYMMDDHHMMSS`` + index).
"""
from __future__ import annotations

import glob
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from steempeg.core.steam_paths import (
    discover_steam_clips_folders,
    get_steam_path,
    steam_id_from_clips_folder,
)

_STEAM_ID_RE = re.compile(r"^\d{5,}$")
_CLIP_DT_RE = re.compile(r"^(?:clip|fg|bg)_(\d+)_(\d{8})_(\d{6})$", re.IGNORECASE)
_JSON_DT_RE = re.compile(r"(\d{8})_(\d{6})")
_SCREENSHOT_NAME_RE = re.compile(r"^(\d{14})_(\d+)\.(jpg|jpeg|png)$", re.IGNORECASE)


def steam_screenshots_dir(
    steam_id: str,
    app_id: str,
    *,
    steam_path: str | None = None,
) -> str:
    root = os.path.normpath(steam_path or get_steam_path())
    return os.path.join(root, "userdata", str(steam_id), "760", "remote", str(app_id), "screenshots")


def resolve_steam_id_for_clip(clip_path: str, library_roots: list[str] | None = None) -> str | None:
    """Best-effort Steam user id for a clip under Game Recording folders."""
    if clip_path:
        norm = os.path.normpath(clip_path)
        parts = norm.split(os.sep)
        for idx, part in enumerate(parts):
            if part.lower() != "userdata" or idx + 1 >= len(parts):
                continue
            candidate = parts[idx + 1]
            if _STEAM_ID_RE.match(candidate):
                return candidate

    seen: set[str] = set()
    for root in library_roots or []:
        if not root:
            continue
        sid = steam_id_from_clips_folder(root)
        if sid and sid not in seen:
            seen.add(sid)
            return sid

    for clips_root in discover_steam_clips_folders():
        sid = steam_id_from_clips_folder(clips_root)
        if sid and sid not in seen:
            return sid
    return None


def clip_folder_start_local(clip_path: str) -> datetime | None:
    """UTC start time from ``fg_<app>_<date>_<time>`` → local timezone."""
    utc = clip_folder_start_utc(clip_path)
    if utc is None:
        return None
    return utc.astimezone()


def clip_folder_start_utc(clip_path: str) -> datetime | None:
    """Recording start from clip folder name (UTC, as Steam stores it)."""
    if not clip_path:
        return None
    name = os.path.basename(os.path.normpath(clip_path))
    match = _CLIP_DT_RE.match(name)
    if not match:
        return None
    try:
        dt_utc = datetime.strptime(f"{match.group(2)}_{match.group(3)}", "%Y%m%d_%H%M%S")
        return dt_utc.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def timeline_json_start_utc(json_path: str) -> datetime | None:
    """UTC session start encoded in ``timeline_<app>_<date>_<time>.json``."""
    if not json_path:
        return None
    match = _JSON_DT_RE.search(os.path.basename(json_path))
    if not match:
        return None
    try:
        dt = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _naive_local(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def marker_shot_times(
    *,
    json_start_utc: datetime | None = None,
    raw_time_ms: float | None = None,
    clip_path: str | None = None,
    marker_time_ms: float | None = None,
) -> List[datetime]:
    """Local wall-clock targets for Steam screenshot filenames."""
    out: list[datetime] = []
    if json_start_utc is not None and raw_time_ms is not None:
        delta = timedelta(milliseconds=float(raw_time_ms))
        shot_utc = json_start_utc + delta
        out.append(shot_utc.astimezone())
        out.append(_naive_local(shot_utc.astimezone()))
    if clip_path and marker_time_ms is not None:
        delta = timedelta(milliseconds=float(marker_time_ms))
        utc = clip_folder_start_utc(clip_path)
        if utc is not None:
            out.append(utc.astimezone() + delta)
            out.append(_naive_local(utc.astimezone() + delta))
    deduped: list[datetime] = []
    seen: set[str] = set()
    for dt in out:
        key = _naive_local(dt).strftime("%Y%m%d%H%M%S")
        if key not in seen:
            seen.add(key)
            deduped.append(dt)
    return deduped


def _sort_screenshot_paths(paths: List[str]) -> List[str]:
    def sort_key(path: str) -> tuple:
        name = os.path.basename(path)
        m = _SCREENSHOT_NAME_RE.match(name)
        if not m:
            return (name, 0)
        return (m.group(1), int(m.group(2)))

    return sorted(paths, key=sort_key)


def find_steam_screenshot_files(
    *,
    steam_id: str,
    app_id: str,
    json_start_utc: datetime | None = None,
    raw_time_ms: float | None = None,
    clip_path: str | None = None,
    marker_time_ms: float | None = None,
    steam_path: str | None = None,
    tolerance_sec: float = 2.5,
) -> List[str]:
    """Return screenshot file paths closest to the marker moment (best first)."""
    folder = steam_screenshots_dir(steam_id, app_id, steam_path=steam_path)
    if not os.path.isdir(folder):
        return []

    targets = marker_shot_times(
        json_start_utc=json_start_utc,
        raw_time_ms=raw_time_ms,
        clip_path=clip_path,
        marker_time_ms=marker_time_ms,
    )
    if not targets:
        return []

    naive_targets = [_naive_local(target) for target in targets]

    found: list[str] = []
    seen: set[str] = set()
    for target in naive_targets:
        prefix = target.strftime("%Y%m%d%H%M%S")
        for path in _sort_screenshot_paths(glob.glob(os.path.join(folder, f"{prefix}_*"))):
            norm = os.path.normcase(path)
            if norm not in seen:
                seen.add(norm)
                found.append(path)
    if found:
        return found

    candidates: list[tuple[float, int, str]] = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []

    for name in names:
        match = _SCREENSHOT_NAME_RE.match(name)
        if not match:
            continue
        try:
            file_dt = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        except ValueError:
            continue
        best_delta = min(abs((file_dt - target).total_seconds()) for target in naive_targets)
        if best_delta <= tolerance_sec:
            candidates.append((best_delta, int(match.group(2)), os.path.join(folder, name)))

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [path for _, _, path in candidates]
