"""Library folder scan — pure Python, safe to run off the GUI thread."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set, Tuple

from steempeg.core import games
from steempeg.core.clip_identity import (
    dedupe_steam_session_folders,
    folder_has_video_chunks,
    is_steam_package_internal_child,
    nested_steam_session_keys,
    pick_best_session_folder,
    steam_session_key,
)
from steempeg.core.dash import health, repair
from steempeg.infra.locale_time import format_clip_date, format_clip_time


def clip_folder_recorded_at(clip_path: str | None) -> datetime | None:
    """UTC timestamp baked into a Steam clip folder name (``…_YYYYMMDD_HHMMSS``).

    Walks up a couple of parents so ``…/clip_…/vid`` still resolves.
    """
    if not clip_path:
        return None
    path = os.path.normpath(clip_path)
    for _ in range(4):
        folder = os.path.basename(path)
        parts = folder.split("_")
        if len(parts) >= 4 and parts[1].isdigit():
            try:
                dt = datetime.strptime(f"{parts[2]}_{parts[3]}", "%Y%m%d_%H%M%S")
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        parent = os.path.dirname(path)
        if not parent or parent == path:
            break
        path = parent
    return None


def clip_folder_default_sort_key(clip_path: str | None) -> float:
    """Stable newest-first key for Default sort / discovery.

    Prefer the Steam recording stamp in the folder name (does not drift when
    antivirus, posters, or Steam touch the directory). Fall back to filesystem
    mtime only for non-Steam / unstamped folders.
    """
    if not clip_path:
        return 0.0
    dt = clip_folder_recorded_at(clip_path)
    if dt is not None:
        return float(dt.timestamp())
    try:
        if os.path.exists(clip_path):
            return float(os.path.getmtime(clip_path))
    except OSError:
        pass
    return 0.0


@dataclass
class ScannedClip:
    full_path: str
    game_name: str
    rec_type: str
    date_display: str
    duration_str: str
    app_id: Optional[str]
    icon_disk_path: str
    use_unknown_icon: bool
    health_level: str
    health_issues: List[str] = field(default_factory=list)


@dataclass
class ScanFinishedStats:
    duplicate_count: int
    health_counts: Dict[str, int]
    library_roots: List[str]
    clip_count: int
    fast: bool


def folder_has_dash_recording(folder_path: str, max_depth: int = 4) -> bool:
    if not folder_path or not os.path.isdir(folder_path):
        return False
    base_depth = os.path.normpath(folder_path).count(os.sep)
    for root, dirs, files in os.walk(folder_path):
        depth = root.count(os.sep) - base_depth
        if depth > max_depth:
            dirs.clear()
            continue
        if any(name.endswith(".mpd") for name in files):
            return True
        if any("chunk-stream" in name for name in files):
            return True
    return False


def is_steam_clip_container_folder(folder_path: str) -> bool:
    if not folder_path or not os.path.isdir(folder_path):
        return False
    base = os.path.basename(folder_path).lower()
    if base.startswith(("clip_", "bg_", "fg_")):
        return False
    parts = base.split("_")
    if not (len(parts) == 3 and parts[0].isdigit() and len(parts[1]) == 8 and parts[2].isdigit()):
        return False
    for sub in ("clips", "video"):
        sub_path = os.path.join(folder_path, sub)
        if not os.path.isdir(sub_path):
            continue
        try:
            for item in os.listdir(sub_path):
                if item.lower().startswith(("clip_", "bg_", "fg_")):
                    return True
        except OSError:
            pass
    return False


def is_clip_library_root(folder_path: str) -> bool:
    if not folder_path or not os.path.isdir(folder_path):
        return False
    base = os.path.basename(folder_path).lower()
    if base in ("clips", "video", "gamerecordings"):
        return True
    try:
        entries = [
            name
            for name in os.listdir(folder_path)
            if os.path.isdir(os.path.join(folder_path, name))
        ]
    except OSError:
        return False
    if not entries:
        return False
    steam_like = [n for n in entries if n.lower().startswith(("clip_", "bg_", "fg_"))]
    return len(steam_like) == len(entries)


def looks_like_single_clip_folder(folder_path: str) -> bool:
    if is_steam_clip_container_folder(folder_path):
        return False
    if is_clip_library_root(folder_path):
        return False
    name = os.path.basename(folder_path).lower()
    if name.startswith(("clip_", "bg_", "fg_")):
        return True
    return folder_has_dash_recording(folder_path)


def collect_clip_roots(base_folder: str) -> Set[str]:
    if not base_folder or not os.path.exists(base_folder):
        return set()

    base_folder = os.path.normpath(base_folder)
    if os.path.basename(base_folder).lower() == "clips":
        parent = os.path.dirname(base_folder)
        if os.path.basename(parent).lower() == "gamerecordings":
            base_folder = parent

    base_name = os.path.basename(base_folder).lower()
    base_is_steam_package = base_name.startswith(("clip_", "bg_", "fg_"))

    roots: Set[str] = set()
    for sub in ("clips", "video"):
        sub_path = os.path.join(base_folder, sub)
        if os.path.exists(sub_path):
            for item in os.listdir(sub_path):
                full = os.path.join(sub_path, item)
                if not os.path.isdir(full):
                    continue
                # clip_…/video/fg_… is package payload, not a second library card.
                if base_is_steam_package and is_steam_package_internal_child(
                    base_name, item.lower()
                ):
                    continue
                roots.add(full)

    if looks_like_single_clip_folder(base_folder):
        if base_name not in ("gamerecordings", "clips", "video"):
            if not is_steam_clip_container_folder(base_folder):
                roots.add(base_folder)
    try:
        for item in os.listdir(base_folder):
            full = os.path.join(base_folder, item)
            if not os.path.isdir(full) or not item.lower().startswith(("clip_", "bg_", "fg_")):
                continue
            if base_is_steam_package and is_steam_package_internal_child(
                base_name, item.lower()
            ):
                continue
            roots.add(full)
    except OSError:
        pass
    return roots


def _path_under_any_root(path: str, roots: List[str]) -> bool:
    """True when ``path`` is equal to or nested under any library root."""
    if not roots:
        return True
    norm = os.path.normcase(os.path.normpath(path))
    for root in roots:
        if not root:
            continue
        r = os.path.normcase(os.path.normpath(root))
        if norm == r or norm.startswith(r + os.sep):
            return True
    return False


def discover_clip_paths(library_roots: List[str]) -> Tuple[List[str], int]:
    """Return sorted clip folder paths and duplicate count from session dedupe."""
    library_root_norms = {os.path.normpath(r) for r in library_roots}
    folders_to_check: Set[str] = set()
    for root in library_roots:
        folders_to_check.update(collect_clip_roots(root))

    sorted_folders = sorted(
        list(folders_to_check),
        key=lambda x: (
            -clip_folder_default_sort_key(x),
            os.path.normcase(os.path.normpath(x)),
        ),
    )
    sorted_folders, session_dupes = dedupe_steam_session_folders(sorted_folders)

    candidates: List[str] = []
    seen_clip_ids: Set[str] = set()
    duplicate_count = session_dupes

    for full_path in sorted_folders:
        if not os.path.exists(full_path):
            continue
        if os.path.normpath(full_path) in library_root_norms:
            continue

        folder_name = os.path.basename(full_path).lower()
        if folder_name in ("gamerecordings", "clips", "video"):
            continue
        if is_steam_clip_container_folder(full_path):
            continue
        if is_clip_library_root(full_path):
            continue
        is_steam_name = folder_name.startswith(("clip_", "bg_", "fg_"))
        if not is_steam_name and not folder_has_dash_recording(full_path):
            continue
        if "steempeg" in folder_name or folder_name in ["logs", "cache", "_update_extracted"]:
            continue

        session_key = steam_session_key(folder_name)
        dedupe_key = session_key or folder_name
        if dedupe_key in seen_clip_ids:
            duplicate_count += 1
            continue
        seen_clip_ids.add(dedupe_key)
        candidates.append(full_path)

    return candidates, duplicate_count


def discover_clip_paths_from_health_cache(
    health_cache: Dict[str, dict],
    library_roots: List[str],
) -> Tuple[List[str], int]:
    """Reuse last-known clip paths from ``clip_health_cache`` (no folder walk).

    Only keeps paths that still exist and sit under the configured library roots.
    Session dedupe matches a live scan so Skip does not resurrect duplicate peers.
    """
    existing: List[str] = []
    for raw in health_cache.keys():
        path = os.path.normpath(str(raw or ""))
        if not path or not os.path.isdir(path):
            continue
        if not _path_under_any_root(path, library_roots):
            continue
        existing.append(path)

    sorted_folders = sorted(
        existing,
        key=lambda x: (
            -clip_folder_default_sort_key(x),
            os.path.normcase(os.path.normpath(x)),
        ),
    )
    sorted_folders, session_dupes = dedupe_steam_session_folders(sorted_folders)

    candidates: List[str] = []
    seen_clip_ids: Set[str] = set()
    duplicate_count = session_dupes
    for full_path in sorted_folders:
        folder_name = os.path.basename(full_path).lower()
        session_key = steam_session_key(folder_name)
        dedupe_key = session_key or folder_name
        if dedupe_key in seen_clip_ids:
            duplicate_count += 1
            continue
        seen_clip_ids.add(dedupe_key)
        candidates.append(full_path)
    return candidates, duplicate_count


def _resolve_clip_health(
    full_path: str,
    health_cache: Dict[str, dict],
    *,
    fast: bool,
    force: bool = False,
) -> health.ClipHealthReport:
    norm = os.path.normpath(full_path)
    try:
        mtime = os.path.getmtime(full_path)
    except OSError:
        mtime = 0.0

    if not force:
        entry = health_cache.get(norm)
        if entry and entry.get("mtime") == mtime:
            try:
                level = health.ClipHealth(entry["level"])
            except ValueError:
                level = health.ClipHealth.DEAD
            return health.ClipHealthReport(level, list(entry.get("issues") or []))

    report = health.assess_clip_health(full_path, probe=not fast)
    health_cache[norm] = {
        "mtime": mtime,
        "level": report.level.value,
        "issues": report.issues,
    }
    return report


def _find_mpd(full_path: str) -> Tuple[bool, bool, Optional[str]]:
    has_mpd = False
    has_chunks = False
    mpd_path = None
    for root, _dirs, files in os.walk(full_path):
        for f in files:
            if f.endswith(".mpd"):
                has_mpd = True
                mpd_path = os.path.join(root, f)
                break
        if any("chunk-stream" in f for f in files):
            has_chunks = True
    return has_mpd, has_chunks, mpd_path


def _parse_duration_from_mpd(mpd_path: Optional[str], *, dead: bool) -> str:
    if not mpd_path:
        return "—" if dead else "--:--"
    try:
        with open(mpd_path, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(
            r'(?:mediaPresentationDuration|duration)="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"',
            content,
        )
        if not match:
            return "--:--"
        h = int(match.group(1)) if match.group(1) else 0
        m = int(match.group(2)) if match.group(2) else 0
        s = int(float(match.group(3))) if match.group(3) else 0
        if h == 0 and m == 0:
            return f"{s}s"
        if h == 0:
            return f"{m}m {s}s"
        return f"{h}h {m}m {s}s"
    except OSError:
        return "--:--"


def _resolve_game_name(
    app_id: str,
    game_names_cache: Dict[str, str],
    *,
    allow_network: bool = True,
) -> str:
    if app_id in game_names_cache:
        return game_names_cache[app_id]
    local = games.find_local_steam_game_name(app_id)
    if local:
        game_names_cache[app_id] = local
        return local
    if not allow_network:
        return f"Unknown Game ({app_id})"
    name = games.fetch_game_name(app_id)
    if name:
        game_names_cache[app_id] = name
        return name
    return f"Unknown Game ({app_id})"


def _resolve_icon_path(
    app_id: str,
    cache_dir: str,
    icons_cache: Dict[str, str] | None = None,
    *,
    allow_download: bool = True,
) -> str:
    if icons_cache is not None and app_id in icons_cache:
        return icons_cache[app_id]

    icon_path = os.path.join(cache_dir, f"{app_id}.jpg")
    if os.path.isfile(icon_path) and os.path.getsize(icon_path) > 100:
        if icons_cache is not None:
            icons_cache[app_id] = icon_path
        return icon_path
    if allow_download and games.download_icon(app_id, icon_path):
        if icons_cache is not None:
            icons_cache[app_id] = icon_path
        return icon_path
    if icons_cache is not None:
        icons_cache[app_id] = ""
    return ""


def scan_single_clip(
    full_path: str,
    *,
    cache_dir: str,
    health_cache: Dict[str, dict],
    game_names_cache: Dict[str, str],
    icons_cache: Dict[str, str] | None = None,
    fast: bool,
    allow_network: bool = True,
) -> Optional[ScannedClip]:
    has_mpd, has_chunks, mpd_path = _find_mpd(full_path)

    if has_chunks and not has_mpd:
        if allow_network and repair.recover_orphaned_clip(full_path):
            has_mpd, has_chunks, mpd_path = _find_mpd(full_path)

    if not has_mpd and not has_chunks:
        return None
    if not folder_has_video_chunks(full_path):
        return None

    health_report = _resolve_clip_health(full_path, health_cache, fast=fast)
    duration_str = _parse_duration_from_mpd(
        mpd_path, dead=health_report.level == health.ClipHealth.DEAD
    )

    folder_name = os.path.basename(full_path)
    parts = folder_name.split("_")

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

        raw_name = _resolve_game_name(
            app_id, game_names_cache, allow_network=allow_network
        )
        game_name = f"   {raw_name}"
        icon_disk_path = _resolve_icon_path(
            app_id,
            cache_dir,
            icons_cache,
            allow_download=allow_network,
        )
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

    date_display = f"{formatted_date}\n{formatted_time}" if formatted_time else formatted_date

    return ScannedClip(
        full_path=full_path,
        game_name=game_name,
        rec_type=rec_type,
        date_display=date_display,
        duration_str=duration_str,
        app_id=app_id,
        icon_disk_path=icon_disk_path,
        use_unknown_icon=use_unknown_icon,
        health_level=health_report.level.value,
        health_issues=list(health_report.issues),
    )


def run_library_scan(
    library_roots: List[str],
    *,
    cache_dir: str,
    health_cache: Dict[str, dict],
    game_names_cache: Dict[str, str],
    fast: bool,
    on_discovered: Callable[[int], None],
    on_clip: Callable[[ScannedClip, int, int], None],
    should_cancel: Callable[[], bool],
    from_cache: bool = False,
    known_paths: Set[str] | None = None,
) -> ScanFinishedStats:
    """Scan all library roots; invoke callbacks for progress (no Qt).

    fast=True skips ffprobe during health checks only. Game names and icons are
    still fetched from Steam when missing from cache (first launch, new app id),
    unless ``from_cache`` is set (known health-cache paths only, no Steam).

    ``known_paths`` — when set, only emit clips whose path is not already known
    (Skip: quiet append of newly appeared folders after snapshot restore).
    Also skips inferior clip_/bg_/fg_ siblings of a known session, and still
    emits a better sibling (e.g. CLIP replacing an already-listed FG).
    """
    on_discovered(0)
    if from_cache:
        candidates, duplicate_count = discover_clip_paths_from_health_cache(
            health_cache, library_roots
        )
    else:
        candidates, duplicate_count = discover_clip_paths(library_roots)

    if known_paths is not None:
        known = {os.path.normpath(p) for p in known_paths}
        known_by_session: Dict[str, str] = {}

        def _remember_session(key: str, path: str) -> None:
            existing = known_by_session.get(key)
            if existing is None:
                known_by_session[key] = path
                return
            best = pick_best_session_folder([existing, path])
            if best:
                known_by_session[key] = os.path.normpath(best)

        for path in known:
            key = steam_session_key(os.path.basename(path))
            if not key:
                continue
            _remember_session(key, path)
            # CLIP packages claim nested FG/BG stamps so Skip won't re-add them.
            for nested_key in nested_steam_session_keys(path):
                _remember_session(nested_key, path)

        filtered: List[str] = []
        for path in candidates:
            norm = os.path.normpath(path)
            if norm in known:
                continue
            key = steam_session_key(os.path.basename(path))
            if key and key in known_by_session:
                best = pick_best_session_folder([known_by_session[key], path])
                if not best or os.path.normpath(best) != norm:
                    # Known library entry already wins this session — skip.
                    continue
            filtered.append(path)
        candidates = filtered

    total = len(candidates)
    on_discovered(total)

    health_counts = {"healthy": 0, "issues": 0, "dead": 0}
    clip_count = 0
    icons_cache: Dict[str, str] = {}
    allow_network = not from_cache

    for index, full_path in enumerate(candidates, start=1):
        if should_cancel():
            break
        try:
            row = scan_single_clip(
                full_path,
                cache_dir=cache_dir,
                health_cache=health_cache,
                game_names_cache=game_names_cache,
                icons_cache=icons_cache,
                fast=fast,
                allow_network=allow_network,
            )
        except Exception as exc:
            logging.warning("Scan skipped %s: %s", full_path, exc)
            continue
        if row is None:
            continue

        if row.health_level == health.ClipHealth.HEALTHY.value:
            health_counts["healthy"] += 1
        elif row.health_level == health.ClipHealth.DEAD.value:
            health_counts["dead"] += 1
        else:
            health_counts["issues"] += 1

        clip_count += 1
        # Use clip_count (successful rows), not loop index — some candidates are skipped.
        on_clip(row, clip_count, total)

    return ScanFinishedStats(
        duplicate_count=duplicate_count,
        health_counts=health_counts,
        library_roots=list(library_roots),
        clip_count=clip_count,
        fast=fast,
    )
