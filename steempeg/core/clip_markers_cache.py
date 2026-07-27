"""Steempeg-owned timeline markers for Steam clips.

When Steam's ``timeline_*.json`` exists we never rewrite it (Steam may lock the
file). User markers go to ``<cache>/clip_markers/<key>.json``.

When a clip has **no** Steam timeline JSON (common for Cured / salvage / odd
folders), we create ``steempeg_timeline.json`` inside the clip folder and write
user markers there — same for every health state, not only Cured.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

# Lives in the clip folder; not named timeline_* so Steam's own search stays clean.
STEEMPEG_TIMELINE_NAME = "steempeg_timeline.json"


def _norm_key_path(path: str | None) -> str:
    if not path:
        return ""
    try:
        path = os.path.abspath(path)
    except OSError:
        pass
    return os.path.normcase(os.path.normpath(path))


def is_steam_timeline_json(path: str | None) -> bool:
    name = os.path.basename(path or "")
    return name.startswith("timeline_") and name.lower().endswith(".json")


def is_steempeg_timeline_json(path: str | None) -> bool:
    return os.path.basename(path or "") == STEEMPEG_TIMELINE_NAME


def steempeg_timeline_path(clip_path: str | None) -> str | None:
    if not clip_path:
        return None
    root = clip_path
    try:
        if os.path.isfile(root):
            root = os.path.dirname(root)
    except OSError:
        pass
    if not root or not os.path.isdir(root):
        return None
    return os.path.join(root, STEEMPEG_TIMELINE_NAME)


def _read_timeline_entries(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return list(data.get("entries") or [])
    except Exception as exc:
        _log.debug("timeline read failed (%s): %s", path, exc)
    return []


def _write_timeline_entries(path: str, entries: list[dict]) -> bool:
    try:
        payload = {"entries": entries, "steempeg": True}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except OSError as exc:
        _log.warning("timeline write failed (%s): %s", path, exc)
        return False


def ensure_steempeg_timeline_json(
    clip_path: str | None,
    cache_dir: str | None = None,
) -> str | None:
    """Create ``steempeg_timeline.json`` in the clip folder if missing.

    Migrates any prior ``clip_markers`` cache entries into the new file once.
    """
    path = steempeg_timeline_path(clip_path)
    if not path:
        return None

    if os.path.isfile(path):
        return path

    entries: list[dict] = []
    if cache_dir:
        cached = load_clip_markers_cache(cache_dir, clip_path=clip_path, json_path=None)
        for e in cached.get("entries") or []:
            # Steam-shaped entry for load_timeline_json.
            time_ms = int(e.get("time_ms", e.get("time", 0)) or 0)
            entries.append(
                {
                    "id": str(e.get("id", time_ms)),
                    "time": str(int(e.get("raw_time_ms", time_ms) or time_ms)),
                    "type": "usermarker",
                    "title": e.get("title") or "",
                    "description": e.get("description") or e.get("desc") or "",
                    "icon": e.get("icon") or "steam_marker",
                    "priority": 0,
                }
            )

    if not _write_timeline_entries(path, entries):
        return None
    _log.info("Created Steempeg timeline JSON: %s (%d markers)", path, len(entries))
    return path


def sync_user_markers_to_steempeg_timeline(
    json_path: str | None,
    markers: list[dict],
    *,
    offset_ms: int = 0,
) -> bool:
    """Rewrite usermarker entries in our timeline file from the live canvas list."""
    if not json_path or not is_steempeg_timeline_json(json_path):
        return False
    existing = _read_timeline_entries(json_path)
    kept = [e for e in existing if e.get("type") != "usermarker"]
    for m in markers:
        if m.get("icon_key") != "usermarker":
            continue
        time_ms = int(m.get("time_ms", 0) or 0)
        raw = m.get("raw_time_ms")
        try:
            raw_time = int(raw) if raw is not None else time_ms + int(offset_ms or 0)
        except (TypeError, ValueError):
            raw_time = time_ms + int(offset_ms or 0)
        kept.append(
            {
                "id": str(m.get("id", time_ms)),
                "time": str(raw_time),
                "type": "usermarker",
                "title": m.get("title") or "",
                "description": m.get("desc") or "",
                "icon": m.get("icon") or "steam_marker",
                "priority": 0,
            }
        )
    kept.sort(key=lambda e: int(e.get("time", 0) or 0))
    return _write_timeline_entries(json_path, kept)


def clip_markers_identity(*, clip_path: str | None = None, json_path: str | None = None) -> str:
    """Stable identity for a Steam clip folder / timeline JSON."""
    clip = _norm_key_path(clip_path)
    if clip:
        # Prefer the clip folder (video files remux/change; folder stays).
        if os.path.isfile(clip):
            clip = os.path.dirname(clip)
        return clip
    return _norm_key_path(json_path)


def clip_markers_sidecar_path(
    cache_dir: str,
    *,
    clip_path: str | None = None,
    json_path: str | None = None,
) -> str:
    ident = clip_markers_identity(clip_path=clip_path, json_path=json_path)
    if not ident:
        ident = "unknown"
    key = hashlib.sha256(ident.encode("utf-8")).hexdigest()[:20]
    folder = os.path.join(cache_dir, "clip_markers")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{key}.json")


def _empty_payload(ident: str, clip_path: str | None, json_path: str | None) -> dict:
    return {
        "identity": ident,
        "clip": _norm_key_path(clip_path) or None,
        "json": _norm_key_path(json_path) or None,
        "entries": [],
        "deleted_ids": [],
        "overrides": {},
    }


def load_clip_markers_cache(
    cache_dir: str | None,
    *,
    clip_path: str | None = None,
    json_path: str | None = None,
) -> dict:
    if not cache_dir:
        return _empty_payload(
            clip_markers_identity(clip_path=clip_path, json_path=json_path),
            clip_path,
            json_path,
        )
    path = clip_markers_sidecar_path(
        cache_dir, clip_path=clip_path, json_path=json_path
    )
    ident = clip_markers_identity(clip_path=clip_path, json_path=json_path)
    if not os.path.isfile(path):
        return _empty_payload(ident, clip_path, json_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_payload(ident, clip_path, json_path)
        # Identity mismatch → ignore (clip moved); keep file for forensics.
        if data.get("identity") and ident and data.get("identity") != ident:
            return _empty_payload(ident, clip_path, json_path)
        data.setdefault("entries", [])
        data.setdefault("deleted_ids", [])
        data.setdefault("overrides", {})
        data["identity"] = ident or data.get("identity") or ""
        return data
    except Exception as exc:
        _log.debug("clip markers cache read failed: %s", exc)
        return _empty_payload(ident, clip_path, json_path)


def save_clip_markers_cache(
    cache_dir: str | None,
    data: dict,
    *,
    clip_path: str | None = None,
    json_path: str | None = None,
) -> bool:
    if not cache_dir:
        return False
    ident = clip_markers_identity(clip_path=clip_path, json_path=json_path)
    path = clip_markers_sidecar_path(
        cache_dir, clip_path=clip_path, json_path=json_path
    )
    payload = {
        "identity": ident,
        "clip": _norm_key_path(clip_path) or data.get("clip"),
        "json": _norm_key_path(json_path) or data.get("json"),
        "entries": list(data.get("entries") or []),
        "deleted_ids": sorted({str(x) for x in (data.get("deleted_ids") or []) if x}),
        "overrides": dict(data.get("overrides") or {}),
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except OSError as exc:
        _log.warning("clip markers cache write failed: %s", exc)
        return False


def canvas_user_marker_entry(marker: dict) -> dict:
    """Serialize an in-memory usermarker for the Steempeg sidecar."""
    return {
        "id": str(marker.get("id", "")),
        "time_ms": int(marker.get("time_ms", 0) or 0),
        "raw_time_ms": int(
            marker.get("raw_time_ms", marker.get("time_ms", 0)) or 0
        ),
        "type": "usermarker",
        "title": marker.get("title") or "",
        "description": marker.get("desc") or "",
        "icon": marker.get("icon") or "steam_marker",
    }


def entry_to_canvas_marker(entry: dict) -> dict:
    time_ms = int(entry.get("time_ms", entry.get("time", 0)) or 0)
    raw = entry.get("raw_time_ms")
    try:
        raw_time_ms = int(raw) if raw is not None else time_ms
    except (TypeError, ValueError):
        raw_time_ms = time_ms
    return {
        "id": str(entry.get("id", time_ms)),
        "time_ms": time_ms,
        "raw_time_ms": raw_time_ms,
        "icon": entry.get("icon") or "steam_marker",
        "icon_key": "usermarker",
        "is_round": False,
        "title": entry.get("title") or "",
        "desc": entry.get("description") or entry.get("desc") or "",
        "steempeg_owned": True,
    }


def upsert_user_marker(
    cache_dir: str | None,
    marker: dict,
    *,
    clip_path: str | None = None,
    json_path: str | None = None,
) -> bool:
    data = load_clip_markers_cache(
        cache_dir, clip_path=clip_path, json_path=json_path
    )
    mid = str(marker.get("id", ""))
    entries = [e for e in data["entries"] if str(e.get("id")) != mid]
    entries.append(canvas_user_marker_entry(marker))
    entries.sort(key=lambda e: int(e.get("time_ms", 0) or 0))
    data["entries"] = entries
    # If we previously hid this id, un-hide it.
    data["deleted_ids"] = [x for x in data["deleted_ids"] if str(x) != mid]
    data.get("overrides", {}).pop(mid, None)
    return save_clip_markers_cache(
        cache_dir, data, clip_path=clip_path, json_path=json_path
    )


def update_user_marker_fields(
    cache_dir: str | None,
    marker: dict,
    *,
    clip_path: str | None = None,
    json_path: str | None = None,
) -> bool:
    """Persist title/desc — Steempeg-owned entry or override for a Steam-origin marker."""
    data = load_clip_markers_cache(
        cache_dir, clip_path=clip_path, json_path=json_path
    )
    mid = str(marker.get("id", ""))
    title = marker.get("title") or ""
    desc = marker.get("desc") or ""
    found = False
    for e in data["entries"]:
        if str(e.get("id")) == mid:
            e["title"] = title
            e["description"] = desc
            found = True
            break
    if not found:
        if marker.get("steempeg_owned"):
            data["entries"].append(canvas_user_marker_entry(marker))
        else:
            # Steam-origin: keep Steam JSON untouched; remember our edits here.
            data.setdefault("overrides", {})[mid] = {
                "title": title,
                "description": desc,
            }
    return save_clip_markers_cache(
        cache_dir, data, clip_path=clip_path, json_path=json_path
    )


def delete_user_marker(
    cache_dir: str | None,
    marker: dict,
    *,
    clip_path: str | None = None,
    json_path: str | None = None,
) -> bool:
    data = load_clip_markers_cache(
        cache_dir, clip_path=clip_path, json_path=json_path
    )
    mid = str(marker.get("id", ""))
    before = len(data["entries"])
    data["entries"] = [e for e in data["entries"] if str(e.get("id")) != mid]
    removed = len(data["entries"]) < before
    if not removed and not marker.get("steempeg_owned"):
        # Hide a Steam-origin usermarker without rewriting Steam's file.
        if mid and mid not in data["deleted_ids"]:
            data["deleted_ids"].append(mid)
    data.get("overrides", {}).pop(mid, None)
    return save_clip_markers_cache(
        cache_dir, data, clip_path=clip_path, json_path=json_path
    )


def merge_cached_user_markers(
    markers: list[dict],
    cache_dir: str | None,
    *,
    clip_path: str | None = None,
    json_path: str | None = None,
) -> list[dict]:
    """Apply deleted_ids / overrides and append Steempeg-owned usermarkers."""
    data = load_clip_markers_cache(
        cache_dir, clip_path=clip_path, json_path=json_path
    )
    deleted = {str(x) for x in data.get("deleted_ids") or []}
    overrides: dict[str, Any] = dict(data.get("overrides") or {})
    owned_ids = {str(e.get("id")) for e in data.get("entries") or []}

    out: list[dict] = []
    for m in markers:
        mid = str(m.get("id", ""))
        if m.get("icon_key") == "usermarker" and mid in deleted:
            continue
        # Prefer Steempeg-owned copy when both exist.
        if m.get("icon_key") == "usermarker" and mid in owned_ids:
            continue
        if mid in overrides and m.get("icon_key") == "usermarker":
            ov = overrides[mid] or {}
            m = dict(m)
            if "title" in ov:
                m["title"] = ov.get("title") or ""
            if "description" in ov:
                m["desc"] = ov.get("description") or ""
        out.append(m)

    for entry in data.get("entries") or []:
        out.append(entry_to_canvas_marker(entry))

    out.sort(key=lambda x: int(x.get("time_ms", 0) or 0))
    return out
