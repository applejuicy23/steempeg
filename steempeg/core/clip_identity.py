"""Steam Game Recording folder naming: session keys and deduplication helpers."""
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Tuple

_PREFIX_RANK = {"clip": 0, "bg": 1, "fg": 2}


def parse_steam_folder_name(folder_name: str) -> Optional[Tuple[str, str, str, str]]:
    """Parse ``clip_<appid>_<YYYYMMDD>_<HHMMSS>`` (also bg_/fg_)."""
    parts = folder_name.lower().split("_")
    if len(parts) < 4 or not parts[1].isdigit():
        return None
    if len(parts[2]) != 8 or not parts[2].isdigit() or not parts[3].isdigit():
        return None
    return parts[0], parts[1], parts[2], parts[3]


def steam_session_key(folder_name: str) -> Optional[str]:
    """Identity shared by clip_/bg_/fg_ folders for the same recording moment."""
    parsed = parse_steam_folder_name(folder_name)
    if not parsed:
        return None
    _prefix, app_id, date_part, time_part = parsed
    return f"{app_id}_{date_part}_{time_part}"


def steam_prefix_rank(folder_name: str) -> int:
    parsed = parse_steam_folder_name(folder_name)
    if not parsed:
        return 99
    return _PREFIX_RANK.get(parsed[0], 99)


def is_nested_same_session(parent_name: str, child_name: str) -> bool:
    """True when ``child`` is a clip/bg/fg folder for the same session inside ``parent``."""
    parent_key = steam_session_key(parent_name)
    child_key = steam_session_key(child_name)
    return bool(parent_key and child_key and parent_key == child_key)


def is_steam_package_internal_child(parent_name: str, child_name: str) -> bool:
    """True when ``child`` is a Steam session folder nested inside another.

    Steam clip packages keep the source recording under ``clip_…/video/fg_…``.
    The outer CLIP stamp is when the clip was saved; the inner FG stamp is the
    original recording — they often differ, so session-key equality is too strict.
    """
    if not parse_steam_folder_name(parent_name):
        return False
    return parse_steam_folder_name(child_name) is not None


def nested_steam_session_keys(folder_path: str) -> List[str]:
    """Session keys of clip_/bg_/fg_ folders under ``video/`` or ``clips/``.

    Used to link a saved CLIP package to its source FG/BG (and any top-level copy).
    """
    if not folder_path or not os.path.isdir(folder_path):
        return []
    keys: List[str] = []
    seen: set[str] = set()
    for sub in ("video", "clips"):
        sub_path = os.path.join(folder_path, sub)
        if not os.path.isdir(sub_path):
            continue
        try:
            entries = os.listdir(sub_path)
        except OSError:
            continue
        for item in entries:
            key = steam_session_key(item)
            if not key or key in seen:
                continue
            full = os.path.join(sub_path, item)
            if not os.path.isdir(full):
                continue
            seen.add(key)
            keys.append(key)
    return keys


def folder_has_video_chunks(folder_path: str) -> bool:
    """True when the tree contains at least one video DASH chunk."""
    if not folder_path or not os.path.isdir(folder_path):
        return False
    for root, _dirs, files in os.walk(folder_path):
        if any(
            name.startswith("chunk-stream0-") and name.endswith(".m4s")
            for name in files
        ):
            return True
    return False


def pick_best_session_folder(candidates: Iterable[str]) -> Optional[str]:
    """Choose one folder per session: has video > clip > bg > fg, then newest mtime."""
    best_path: Optional[str] = None
    best_has_video = False
    best_rank = 99
    best_mtime = -1.0
    for path in candidates:
        name = os.path.basename(path)
        has_video = folder_has_video_chunks(path)
        rank = steam_prefix_rank(name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        if has_video and not best_has_video:
            better = True
        elif has_video == best_has_video:
            if rank < best_rank:
                better = True
            elif rank == best_rank and mtime > best_mtime:
                better = True
            else:
                better = False
        else:
            better = False
        if better or best_path is None:
            best_path = path
            best_has_video = has_video
            best_rank = rank
            best_mtime = mtime
    return best_path


def _merge_session_groups_via_clip_packages(
    steam_groups: Dict[str, List[str]],
    folder_paths: List[str],
) -> Dict[str, List[str]]:
    """Union session keys when a CLIP/BG/FG package nests another session folder.

    Example: ``clip_…_224607`` contains ``video/fg_…_224328`` while Steam also
    keeps ``video/fg_…_224328`` at the library root — same recording, two stamps.
    """
    parent: Dict[str, str] = {key: key for key in steam_groups}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for path in folder_paths:
        own = steam_session_key(os.path.basename(path))
        if not own or own not in steam_groups:
            continue
        for nested_key in nested_steam_session_keys(path):
            if nested_key not in steam_groups:
                continue
            union(own, nested_key)

    merged: Dict[str, List[str]] = {}
    for key, group in steam_groups.items():
        merged.setdefault(find(key), []).extend(group)
    return merged


def dedupe_steam_session_folders(folder_paths: List[str]) -> Tuple[List[str], int]:
    """Collapse clip_/bg_/fg_ siblings to a single best folder.

    Groups by app+timestamp, then merges groups when a Steam package folder
    nests another session (CLIP saved from an FG often uses a newer stamp).

    Returns (deduped_paths, ignored_duplicate_count). Non-Steam folders pass through.
    """
    steam_groups: dict[str, list[str]] = {}
    passthrough: list[str] = []

    for path in folder_paths:
        key = steam_session_key(os.path.basename(path))
        if key is None:
            passthrough.append(path)
            continue
        steam_groups.setdefault(key, []).append(path)

    steam_groups = _merge_session_groups_via_clip_packages(steam_groups, folder_paths)

    deduped: list[str] = list(passthrough)
    ignored = 0
    for _key, group in steam_groups.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue
        chosen = pick_best_session_folder(group)
        if chosen:
            deduped.append(chosen)
            ignored += len(group) - 1

    # Preserve newest-first ordering from the caller (mtime sort).
    order = {os.path.normpath(p): i for i, p in enumerate(folder_paths)}
    deduped.sort(key=lambda p: order.get(os.path.normpath(p), len(folder_paths)))
    return deduped, ignored


def session_duplicate_paths_to_drop(folder_paths: List[str]) -> List[str]:
    """Paths that lose to a better clip_/bg_/fg_ sibling in the same list."""
    if not folder_paths:
        return []
    keepers, _ignored = dedupe_steam_session_folders(list(folder_paths))
    keep = {os.path.normpath(p) for p in keepers}
    dropped: List[str] = []
    seen: set[str] = set()
    for path in folder_paths:
        norm = os.path.normpath(path)
        if norm in keep or norm in seen:
            continue
        seen.add(norm)
        dropped.append(path)
    return dropped
