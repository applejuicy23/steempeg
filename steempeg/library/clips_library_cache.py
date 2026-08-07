"""Persist the Clips Manager row list between sessions (Skip startup).

This is a UI snapshot — not a health recheck. Skip restores these rows as-is;
Refresh rebuilds them via a real folder scan.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from steempeg.core.dash import health as dash_health
from steempeg.infra import cache as json_cache
from steempeg.infra.locale_time import format_clip_date, format_clip_time
from steempeg.library.scan import (
    ScannedClip,
    clip_folder_recorded_at,
)

CACHE_FILENAME = "clips_library_cache.json"
CACHE_VERSION = 1


def clips_library_cache_path(cache_dir: str | None) -> str:
    return os.path.join(cache_dir or "", CACHE_FILENAME)


def scanned_clip_to_dict(row: ScannedClip) -> dict[str, Any]:
    return {
        "full_path": row.full_path,
        "game_name": row.game_name,
        "rec_type": row.rec_type,
        "date_display": row.date_display,
        "duration_str": row.duration_str,
        "app_id": row.app_id,
        "icon_disk_path": row.icon_disk_path or "",
        "use_unknown_icon": bool(row.use_unknown_icon),
        "health_level": row.health_level,
        "health_issues": list(row.health_issues or []),
    }


def scanned_clip_from_dict(data: dict[str, Any] | None) -> ScannedClip | None:
    if not isinstance(data, dict):
        return None
    path = str(data.get("full_path") or "").strip()
    if not path:
        return None
    app_id = data.get("app_id")
    if app_id is not None:
        app_id = str(app_id).strip() or None
    return ScannedClip(
        full_path=os.path.normpath(path),
        game_name=str(data.get("game_name") or "   Unknown"),
        rec_type=str(data.get("rec_type") or "🎞️ FG"),
        date_display=str(data.get("date_display") or "Unknown"),
        duration_str=str(data.get("duration_str") or "--:--"),
        app_id=app_id,
        icon_disk_path=str(data.get("icon_disk_path") or ""),
        use_unknown_icon=bool(data.get("use_unknown_icon")),
        health_level=str(data.get("health_level") or "healthy"),
        health_issues=[str(x) for x in (data.get("health_issues") or [])],
    )


def load_clips_library_cache(cache_dir: str | None) -> dict[str, Any]:
    path = clips_library_cache_path(cache_dir)
    payload = json_cache.read_json(path, default={})
    if not isinstance(payload, dict):
        return {}
    return payload


def save_clips_library_cache(
    cache_dir: str | None,
    *,
    library_roots: list[str],
    clips: list[ScannedClip],
) -> None:
    if not cache_dir:
        return
    payload = {
        "version": CACHE_VERSION,
        "saved_at": time.time(),
        "library_roots": [os.path.normpath(r) for r in library_roots if r],
        "clips": [scanned_clip_to_dict(row) for row in clips],
    }
    json_cache.write_json(clips_library_cache_path(cache_dir), payload)


def clear_clips_library_cache(cache_dir: str | None) -> None:
    path = clips_library_cache_path(cache_dir)
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def clips_from_library_cache(
    cache_dir: str | None,
    *,
    library_roots: list[str] | None = None,
    require_exists: bool = True,
) -> list[ScannedClip]:
    """Return snapshot rows. Optionally drop missing folders / off-root paths."""
    payload = load_clips_library_cache(cache_dir)
    raw_clips = payload.get("clips")
    if not isinstance(raw_clips, list):
        return []

    roots = [os.path.normpath(r) for r in (library_roots or []) if r]
    root_norms = {os.path.normcase(r) for r in roots}

    def _under_root(path: str) -> bool:
        if not root_norms:
            return True
        norm = os.path.normcase(os.path.normpath(path))
        for r in root_norms:
            if norm == r or norm.startswith(r + os.sep):
                return True
        return False

    out: list[ScannedClip] = []
    seen: set[str] = set()
    for entry in raw_clips:
        row = scanned_clip_from_dict(entry if isinstance(entry, dict) else None)
        if row is None:
            continue
        key = os.path.normcase(row.full_path)
        if key in seen:
            continue
        if require_exists and not os.path.isdir(row.full_path):
            continue
        if not _under_root(row.full_path):
            continue
        seen.add(key)
        out.append(row)
    return out


def _lightweight_row_from_path(
    full_path: str,
    *,
    cache_dir: str,
    health_cache: dict[str, dict],
    game_names_cache: dict[str, str],
) -> ScannedClip | None:
    """Build a display row from folder name + caches — no MPD / ffprobe / Steam / disk."""
    if not full_path:
        return None
    folder_name = os.path.basename(full_path)
    parts = folder_name.split("_")
    norm = os.path.normpath(full_path)
    entry = health_cache.get(norm) or health_cache.get(full_path) or {}
    level = str(entry.get("level") or dash_health.ClipHealth.HEALTHY.value)
    issues = [str(x) for x in (entry.get("issues") or [])]

    if len(parts) >= 4 and parts[1].isdigit():
        prefix = parts[0].lower()
        app_id = parts[1]
        if prefix == "clip":
            rec_type = "🎬 Clip"
        elif prefix == "bg":
            rec_type = "📼 BG"
        elif prefix == "fg":
            rec_type = "🎞️ FG"
        else:
            rec_type = "Unknown"
        raw_name = game_names_cache.get(app_id) or f"Unknown Game ({app_id})"
        game_name = f"   {raw_name}"
        icon_disk_path = os.path.join(cache_dir, f"{app_id}.jpg")
        if not (os.path.isfile(icon_disk_path) and os.path.getsize(icon_disk_path) > 100):
            icon_disk_path = ""
        use_unknown_icon = False
        try:
            dt_utc = clip_folder_recorded_at(full_path)
            if dt_utc is None:
                raise ValueError("no folder stamp")
            formatted_date = format_clip_date(dt_utc)
            formatted_time = format_clip_time(dt_utc)
        except Exception:
            try:
                formatted_date = format_clip_date(datetime.strptime(parts[2], "%Y%m%d"))
            except Exception:
                formatted_date = parts[2]
            try:
                formatted_time = format_clip_time(datetime.strptime(parts[3], "%H%M%S"))
            except Exception:
                formatted_time = ""
    else:
        rec_type = "🎞️ FG"
        game_name = "   Unknown"
        formatted_date = "Unknown"
        formatted_time = ""
        app_id = None
        icon_disk_path = ""
        use_unknown_icon = True

    date_display = (
        f"{formatted_date}\n{formatted_time}" if formatted_time else formatted_date
    )
    return ScannedClip(
        full_path=norm,
        game_name=game_name,
        rec_type=rec_type,
        date_display=date_display,
        duration_str="--:--",
        app_id=app_id,
        icon_disk_path=icon_disk_path,
        use_unknown_icon=use_unknown_icon,
        health_level=level,
        health_issues=issues,
    )


def seed_clips_from_health_cache(
    cache_dir: str | None,
    *,
    library_roots: list[str],
    health_cache: dict[str, dict],
    game_names_cache: dict[str, str],
) -> list[ScannedClip]:
    """Instant Skip seed when no session snapshot exists yet (no folder I/O)."""
    if not cache_dir:
        return []
    # String filter only — never ``isdir`` here (Skip must stay instantaneous).
    roots = [os.path.normpath(r) for r in library_roots if r]
    root_norms = {os.path.normcase(r) for r in roots}

    def _under_root(path: str) -> bool:
        if not root_norms:
            return True
        norm = os.path.normcase(os.path.normpath(path))
        for r in root_norms:
            if norm == r or norm.startswith(r + os.sep):
                return True
        return False

    paths: list[str] = []
    seen: set[str] = set()
    for raw in health_cache.keys():
        path = os.path.normpath(str(raw or ""))
        if not path or not _under_root(path):
            continue
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)

    rows: list[ScannedClip] = []
    for path in paths:
        row = _lightweight_row_from_path(
            path,
            cache_dir=cache_dir,
            health_cache=health_cache,
            game_names_cache=game_names_cache,
        )
        if row is not None:
            rows.append(row)
    return rows
