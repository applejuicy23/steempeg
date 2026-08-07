"""Persist the Rendered videos list between sessions (Skip startup).

UI snapshot only — Skip restores rows as-is; Refresh does a real folder walk.
"""
from __future__ import annotations

import os
import time
from typing import Any

from steempeg.infra import cache as json_cache
from steempeg.library.rendered_scan import ScannedRenderedFile

CACHE_FILENAME = "rendered_library_cache.json"
CACHE_VERSION = 1


def rendered_library_cache_path(cache_dir: str | None) -> str:
    return os.path.join(cache_dir or "", CACHE_FILENAME)


def scanned_rendered_to_dict(row: ScannedRenderedFile) -> dict[str, Any]:
    return {
        "full_path": row.full_path,
        "display_title": row.display_title,
        "icon_path": row.icon_path or "",
        "is_unknown": bool(row.is_unknown),
        "game_filter_name": row.game_filter_name,
        "type_label": row.type_label,
        "date_str": row.date_str,
        "time_str": row.time_str,
        "size_str": row.size_str,
        "needs_poster": bool(row.needs_poster),
        "source_clip_name": row.source_clip_name or "",
        "file_mtime": float(row.file_mtime or 0.0),
        "file_size": int(row.file_size or 0),
        "health_level": row.health_level or "",
        "health_issues": list(row.health_issues or []),
        "duration_sec": row.duration_sec,
        "duration_stream_sec": row.duration_stream_sec,
        "duration_format_sec": row.duration_format_sec,
    }


def scanned_rendered_from_dict(data: dict[str, Any] | None) -> ScannedRenderedFile | None:
    if not isinstance(data, dict):
        return None
    path = str(data.get("full_path") or "").strip()
    if not path:
        return None
    issues = data.get("health_issues")
    return ScannedRenderedFile(
        full_path=os.path.normpath(path),
        display_title=str(data.get("display_title") or os.path.basename(path)),
        icon_path=str(data.get("icon_path") or ""),
        is_unknown=bool(data.get("is_unknown")),
        game_filter_name=str(data.get("game_filter_name") or "Unknown"),
        type_label=str(data.get("type_label") or "FILE"),
        date_str=str(data.get("date_str") or ""),
        time_str=str(data.get("time_str") or ""),
        size_str=str(data.get("size_str") or ""),
        needs_poster=bool(data.get("needs_poster")),
        source_clip_name=str(data.get("source_clip_name") or ""),
        file_mtime=float(data.get("file_mtime") or 0.0),
        file_size=int(data.get("file_size") or 0),
        health_level=str(data.get("health_level") or ""),
        health_issues=[str(x) for x in issues] if isinstance(issues, list) else None,
        duration_sec=_opt_float(data.get("duration_sec")),
        duration_stream_sec=_opt_float(data.get("duration_stream_sec")),
        duration_format_sec=_opt_float(data.get("duration_format_sec")),
    )


def _opt_float(raw) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def save_rendered_library_cache(
    cache_dir: str | None,
    *,
    scan_roots: list[str],
    files: list[ScannedRenderedFile],
) -> None:
    if not cache_dir:
        return
    payload = {
        "version": CACHE_VERSION,
        "saved_at": time.time(),
        "scan_roots": [os.path.normpath(r) for r in scan_roots if r],
        "files": [scanned_rendered_to_dict(row) for row in files],
    }
    json_cache.write_json(rendered_library_cache_path(cache_dir), payload)


def clear_rendered_library_cache(cache_dir: str | None) -> None:
    path = rendered_library_cache_path(cache_dir)
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def files_from_rendered_library_cache(
    cache_dir: str | None,
    *,
    require_exists: bool = False,
) -> list[ScannedRenderedFile]:
    """Return snapshot rows. ``require_exists`` is off for Skip (no export I/O)."""
    path = rendered_library_cache_path(cache_dir)
    payload = json_cache.read_json(path, default={})
    if not isinstance(payload, dict):
        return []
    raw = payload.get("files")
    if not isinstance(raw, list):
        return []
    out: list[ScannedRenderedFile] = []
    for entry in raw:
        row = scanned_rendered_from_dict(entry if isinstance(entry, dict) else None)
        if row is None:
            continue
        if require_exists and not os.path.isfile(row.full_path):
            continue
        out.append(row)
    return out
