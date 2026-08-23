"""Resolve Steam client screenshot files for timeline screenshot markers.

Steam saves screenshots under::

    <Steam>/userdata/<steam_id>/760/remote/<app_id>/screenshots/

Filenames look like ``20260711152410_1.jpg`` (local ``YYYYMMDDHHMMSS`` + index).

``screenshots.vdf`` (``userdata/<id>/760/screenshots.vdf``) also stores
``timelineid`` + ``timelinetime`` (ms into that recording) — the reliable
signal for Open related clip.
"""
from __future__ import annotations

import glob
import logging
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
_VDF_FIELD_RE = re.compile(r'"([^"]+)"\s+"([^"]*)"')
# basename → {timeline_id, timeline_time_ms, creation, app_id}
_VDF_CACHE: dict[str, tuple[float, dict[str, dict]]] = {}


def steam_screenshots_dir(
    steam_id: str,
    app_id: str,
    *,
    steam_path: str | None = None,
) -> str:
    root = os.path.normpath(steam_path or get_steam_path())
    return os.path.join(root, "userdata", str(steam_id), "760", "remote", str(app_id), "screenshots")


_STEAM_SHOT_EXTS = {".jpg", ".jpeg", ".png"}
_APP_ID_DIR_RE = re.compile(r"^\d+$")


def iter_steam_library_screenshots(
    *,
    steam_path: str | None = None,
) -> List[dict]:
    """Walk Steam userdata screenshots for the unified Screenshots shelf.

    Yields dicts: ``path``, ``mtime``, ``steam_id``, ``app_id``.
    Skips ``thumbnails`` subfolders. No network / game-name resolution.
    """
    root = os.path.normpath(steam_path or get_steam_path())
    userdata = os.path.join(root, "userdata")
    if not os.path.isdir(userdata):
        return []

    out: list[dict] = []
    try:
        steam_ids = os.listdir(userdata)
    except OSError:
        return []

    for steam_id in steam_ids:
        if not _STEAM_ID_RE.match(steam_id):
            continue
        remote = os.path.join(userdata, steam_id, "760", "remote")
        if not os.path.isdir(remote):
            continue
        try:
            app_dirs = os.listdir(remote)
        except OSError:
            continue
        for app_id in app_dirs:
            if not _APP_ID_DIR_RE.match(app_id):
                continue
            folder = os.path.join(remote, app_id, "screenshots")
            if not os.path.isdir(folder):
                continue
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                # Steam keeps a thumbnails/ sibling — only take top-level images.
                if name.lower() == "thumbnails":
                    continue
                path = os.path.join(folder, name)
                if not os.path.isfile(path):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in _STEAM_SHOT_EXTS:
                    continue
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    mtime = 0.0
                out.append(
                    {
                        "path": os.path.normpath(path),
                        "mtime": float(mtime),
                        "steam_id": steam_id,
                        "app_id": app_id,
                    }
                )
    return out


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
    """UTC timestamp from the folder name → local timezone.

    Note: Steam ``clip_*`` folder names are often near the *end* of the saved
    segment. Prefer :func:`clip_media_start_local` for playhead / overlap math.
    """
    utc = clip_folder_start_utc(clip_path)
    if utc is None:
        return None
    return utc.astimezone()


def clip_folder_start_utc(clip_path: str) -> datetime | None:
    """Timestamp encoded in ``clip|fg|bg_<app>_<date>_<time>`` (UTC)."""
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


def nested_recording_folder(clip_path: str) -> str | None:
    """Nested ``video/fg_*`` / ``video/bg_*`` segment under a clip folder.

    Steam saves ``clip_<app>_<utc>`` with media under ``video/fg_*``. The clip
    folder timestamp is frequently ≈ media end (fg_start + duration); the
    nested ``fg_``/``bg_`` name is the actual recording start.
    """
    if not clip_path:
        return None
    norm = os.path.normpath(clip_path)
    base = os.path.basename(norm)
    lower = base.lower()
    # Already pointing at a recording segment.
    if _CLIP_DT_RE.match(base) and lower.startswith(("fg_", "bg_")):
        return norm
    video = os.path.join(norm, "video")
    if not os.path.isdir(video):
        return None
    try:
        names = os.listdir(video)
    except OSError:
        return None
    candidates: list[str] = []
    for name in names:
        if not name.lower().startswith(("fg_", "bg_")):
            continue
        if not _CLIP_DT_RE.match(name):
            continue
        candidates.append(os.path.join(video, name))
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def _start_key(path: str) -> datetime:
        return clip_folder_start_utc(path) or datetime.max.replace(tzinfo=timezone.utc)

    candidates.sort(key=_start_key)
    return candidates[0]


def clip_media_start_utc(clip_path: str) -> datetime | None:
    """Wall-clock start of playable media (nested fg/bg when present)."""
    nested = nested_recording_folder(clip_path)
    if nested:
        started = clip_folder_start_utc(nested)
        if started is not None:
            return started
    return clip_folder_start_utc(clip_path)


def clip_media_start_local(clip_path: str) -> datetime | None:
    """Local timezone media start for screenshot ↔ clip matching and seek."""
    utc = clip_media_start_utc(clip_path)
    if utc is None:
        return None
    return utc.astimezone()


def steam_id_from_screenshot_path(file_path: str) -> str:
    """``…/userdata/<steam_id>/760/remote/<app>/screenshots/…`` → steam_id."""
    parts = os.path.normpath(file_path or "").replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        if part.casefold() == "userdata" and i + 1 < len(parts):
            candidate = parts[i + 1]
            if _STEAM_ID_RE.match(candidate):
                return candidate
    return ""


def screenshots_vdf_path(
    steam_id: str,
    *,
    steam_path: str | None = None,
) -> str:
    root = os.path.normpath(steam_path or get_steam_path())
    return os.path.join(root, "userdata", str(steam_id), "760", "screenshots.vdf")


def _parse_screenshots_vdf(vdf_path: str) -> dict[str, dict]:
    """Map screenshot basename → meta from Steam ``screenshots.vdf``."""
    out: dict[str, dict] = {}
    try:
        text = open(vdf_path, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        logging.debug("Could not read screenshots.vdf %s: %s", vdf_path, exc)
        return out

    # Entries are brace blocks with "filename" / "timelineid" / "timelinetime".
    pos = 0
    while True:
        fn_idx = text.find('"filename"', pos)
        if fn_idx < 0:
            break
        # Bound the entry: walk back to the nearest "{" before filename, then
        # take a fixed window (entries are small).
        brace = text.rfind("{", 0, fn_idx)
        if brace < 0:
            pos = fn_idx + 10
            continue
        block = text[brace : brace + 1200]
        fields = dict(_VDF_FIELD_RE.findall(block))
        rel = (fields.get("filename") or "").replace("\\", "/")
        base = os.path.basename(rel)
        if not base:
            pos = fn_idx + 10
            continue
        timeline_id = (fields.get("timelineid") or "").strip()
        timeline_time_ms: int | None = None
        raw_tt = fields.get("timelinetime")
        if raw_tt is not None and str(raw_tt).strip() != "":
            try:
                timeline_time_ms = int(float(raw_tt))
            except (TypeError, ValueError):
                timeline_time_ms = None
        creation: int | None = None
        raw_c = fields.get("creation")
        if raw_c is not None and str(raw_c).strip() != "":
            try:
                creation = int(float(raw_c))
            except (TypeError, ValueError):
                creation = None
        app_id = (fields.get("gameid") or "").strip()
        if not app_id and "/" in rel:
            app_id = rel.split("/", 1)[0]
        out[base.casefold()] = {
            "filename": base,
            "timeline_id": timeline_id,
            "timeline_time_ms": timeline_time_ms,
            "creation": creation,
            "app_id": app_id,
        }
        pos = fn_idx + 10
    return out


def load_screenshots_vdf_index(
    steam_id: str,
    *,
    steam_path: str | None = None,
) -> dict[str, dict]:
    """Cached basename → VDF meta for one Steam user."""
    if not steam_id:
        return {}
    path = screenshots_vdf_path(steam_id, steam_path=steam_path)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    cached = _VDF_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    index = _parse_screenshots_vdf(path)
    _VDF_CACHE[path] = (mtime, index)
    return index


def lookup_steam_screenshot_vdf(file_path: str) -> dict | None:
    """Return VDF meta for a Steam screenshot file, or ``None``."""
    if not file_path:
        return None
    steam_id = steam_id_from_screenshot_path(file_path)
    if not steam_id:
        return None
    index = load_screenshots_vdf_index(steam_id)
    if not index:
        return None
    return index.get(os.path.basename(file_path).casefold())


def clip_has_timeline(clip_path: str, timeline_id: str) -> bool:
    """True when ``clip_path/timelines/<timeline_id>.json`` exists."""
    tid = (timeline_id or "").strip()
    if not clip_path or not tid:
        return False
    return os.path.isfile(os.path.join(clip_path, "timelines", f"{tid}.json"))


def clip_timeline_offset_ms(clip_path: str, timeline_id: str = "") -> int | None:
    """Ms from timeline JSON start to playable media start (same math as the player).

    Both Steam timeline and ``fg_*`` names are UTC wall-clock stamps; subtract
    as naive datetimes (timezone cancels).
    """
    if not clip_path:
        return None
    tid = (timeline_id or "").strip()
    if not tid:
        # Prefer the clip's own timelines/*.json when id not provided.
        timelines = os.path.join(clip_path, "timelines")
        if os.path.isdir(timelines):
            try:
                for name in os.listdir(timelines):
                    if name.lower().startswith("timeline_") and name.lower().endswith(
                        ".json"
                    ):
                        tid = os.path.splitext(name)[0]
                        break
            except OSError:
                tid = ""
    if not tid:
        return None

    nested = nested_recording_folder(clip_path)
    video_name = os.path.basename(nested or clip_path)
    json_match = _JSON_DT_RE.search(tid)
    video_match = _JSON_DT_RE.search(video_name)
    if not json_match or not video_match:
        return None
    try:
        json_dt = datetime.strptime(
            json_match.group(1) + json_match.group(2), "%Y%m%d%H%M%S"
        )
        video_dt = datetime.strptime(
            video_match.group(1) + video_match.group(2), "%Y%m%d%H%M%S"
        )
    except ValueError:
        return None
    return int((video_dt - json_dt).total_seconds() * 1000)


def timeline_id_start_utc(timeline_id: str) -> datetime | None:
    """UTC start encoded in ``timeline_<app><YYYYMMDD>_<HHMMSS>``."""
    match = _JSON_DT_RE.search(timeline_id or "")
    if not match:
        return None
    try:
        dt = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=timezone.utc)
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
        # Playhead is relative to media start (nested fg/bg), not clip folder name.
        utc = clip_media_start_utc(clip_path)
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
