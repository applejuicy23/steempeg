"""Rendered videos folder scan — pure Python, safe to run off the GUI thread."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List

from steempeg.core import games
from steempeg.core.rendered_media import (
    is_default_rendered_basename,
    load_rendered_companion_meta,
    parse_app_id_from_clip_folder,
    parse_app_id_from_name,
)
from steempeg.infra.locale_time import format_clip_date, format_clip_time
from steempeg.library.scan import _resolve_game_name, _resolve_icon_path

RENDERED_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
RENDERED_AUDIO_EXTS = {".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg", ".opus"}
RENDERED_ALL_EXTS = RENDERED_VIDEO_EXTS | RENDERED_AUDIO_EXTS


@dataclass
class ScannedRenderedFile:
    full_path: str
    display_title: str
    icon_path: str
    is_unknown: bool
    game_filter_name: str
    type_label: str
    date_str: str
    time_str: str
    size_str: str
    needs_poster: bool


@dataclass
class RenderedScanStats:
    file_count: int
    scan_roots: List[str]


def _rendered_type_label(ext: str) -> str:
    return ext.lstrip(".").upper() or "FILE"


def _format_file_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def _lookup_source_meta(file_path: str, basename: str, meta_index: Dict[str, dict]) -> dict:
    companion = load_rendered_companion_meta(file_path)
    if companion:
        return companion
    norm = os.path.normcase(os.path.normpath(file_path))
    if norm in meta_index:
        return meta_index[norm]
    app_id = parse_app_id_from_name(basename)
    if app_id:
        return {"app_id": app_id}
    return {}


def _icon_path_for_rendered(
    app_id: str | None,
    cache_dir: str,
    fallback: str,
    icons_cache: Dict[str, str],
) -> str:
    if app_id:
        cached = _resolve_icon_path(str(app_id), cache_dir, icons_cache)
        if cached:
            return cached
    if fallback and os.path.isfile(fallback):
        return fallback
    return ""


def scan_single_rendered_file(
    full_path: str,
    mtime: float,
    size: int,
    ext: str,
    *,
    meta_index: Dict[str, dict],
    cache_dir: str,
    game_names_cache: Dict[str, str],
    icons_cache: Dict[str, str],
) -> ScannedRenderedFile:
    basename = os.path.basename(full_path)
    stem = os.path.splitext(basename)[0]
    source = _lookup_source_meta(full_path, basename, meta_index)

    app_id = source.get("app_id") or parse_app_id_from_name(basename)
    if not app_id and source.get("clip_path"):
        app_id = parse_app_id_from_clip_folder(source["clip_path"])

    icon_path = _icon_path_for_rendered(
        str(app_id) if app_id else None,
        cache_dir,
        source.get("game_icon_path", ""),
        icons_cache,
    )

    game_name = ""
    if app_id:
        game_name = _resolve_game_name(str(app_id), game_names_cache) or source.get("game_name") or ""
    elif source.get("game_name"):
        game_name = source["game_name"]

    if app_id and game_name:
        title = game_name if is_default_rendered_basename(stem, str(app_id)) else stem
    else:
        title = game_name or stem

    is_unknown = not bool(app_id)
    if app_id and not game_name:
        game_name = _resolve_game_name(str(app_id), game_names_cache) or ""

    dt = datetime.fromtimestamp(mtime)
    type_label = _rendered_type_label(ext)
    return ScannedRenderedFile(
        full_path=full_path,
        display_title=title,
        icon_path=icon_path,
        is_unknown=is_unknown,
        game_filter_name=game_name if game_name else "Unknown",
        type_label=type_label,
        date_str=format_clip_date(dt),
        time_str=format_clip_time(dt),
        size_str=_format_file_size(size),
        needs_poster=ext.lower() in RENDERED_VIDEO_EXTS,
    )


def discover_rendered_files(roots: List[str]) -> List[tuple[str, float, int, str]]:
    files: list[tuple[str, float, int, str]] = []
    seen: set[str] = set()
    for root in roots:
        try:
            for name in os.listdir(root):
                full = os.path.join(root, name)
                if not os.path.isfile(full):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in RENDERED_ALL_EXTS:
                    continue
                norm = os.path.normcase(os.path.normpath(full))
                if norm in seen:
                    continue
                seen.add(norm)
                mtime = os.path.getmtime(full)
                size = os.path.getsize(full)
                files.append((full, mtime, size, ext))
        except OSError as exc:
            logging.warning("Rendered scan failed for %s: %s", root, exc)
    files.sort(key=lambda row: row[1], reverse=True)
    return files


def run_rendered_scan(
    roots: List[str],
    meta_index: Dict[str, dict],
    cache_dir: str,
    game_names_cache: Dict[str, str],
    *,
    on_discovered: Callable[[int], None] | None = None,
    on_file: Callable[[ScannedRenderedFile, int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> RenderedScanStats:
    files = discover_rendered_files(roots)
    total = len(files)
    if on_discovered is not None:
        on_discovered(total)

    icons_cache: Dict[str, str] = {}
    for index, (full, mtime, size, ext) in enumerate(files, start=1):
        if should_cancel and should_cancel():
            break
        row = scan_single_rendered_file(
            full,
            mtime,
            size,
            ext,
            meta_index=meta_index,
            cache_dir=cache_dir,
            game_names_cache=game_names_cache,
            icons_cache=icons_cache,
        )
        if on_file is not None:
            on_file(row, index, total)

    return RenderedScanStats(file_count=total, scan_roots=list(roots))
