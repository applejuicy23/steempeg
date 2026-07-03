"""Helpers for exported / rendered flat media files (not Steam DASH folders)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess

_RENDERED_NAME_RE = re.compile(r"^clip_(\d+)_", re.IGNORECASE)
_COMPANION_SUFFIX = ".steempeg.json"


def file_identity(file_path: str) -> str:
    st = os.stat(file_path)
    norm = os.path.normcase(os.path.normpath(file_path))
    return f"{norm}|{st.st_mtime_ns}|{st.st_size}"


def parse_app_id_from_name(filename: str) -> str | None:
    stem = os.path.splitext(os.path.basename(filename))[0]
    m = _RENDERED_NAME_RE.match(stem)
    return m.group(1) if m else None


def parse_app_id_from_clip_folder(folder_name: str) -> str | None:
    parts = os.path.basename(folder_name).split("_")
    if len(parts) >= 2 and parts[0].lower() == "clip" and parts[1].isdigit():
        return parts[1]
    return None


def is_default_rendered_basename(stem: str, app_id: str | None) -> bool:
    """True for Steam's default ``clip_<appid>_…_rendered`` export names."""
    if not app_id:
        return False
    low = stem.lower()
    return low.startswith(f"clip_{app_id}_") and low.endswith("_rendered")


def companion_meta_path(file_path: str) -> str:
    return file_path + _COMPANION_SUFFIX


def save_rendered_companion_meta(
    file_path: str,
    *,
    app_id: str | None = None,
    game_name: str = "",
    clip_path: str = "",
    game_icon_path: str = "",
) -> None:
    """Write ``<video>.steempeg.json`` so renamed exports keep their game metadata."""
    try:
        st = os.stat(file_path)
    except OSError:
        return
    payload = {
        "app_id": app_id or "",
        "game_name": game_name,
        "clip_path": clip_path,
        "game_icon_path": game_icon_path,
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
    }
    try:
        with open(companion_meta_path(file_path), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except OSError as exc:
        logging.debug("Could not write rendered companion meta for %s: %s", file_path, exc)


def load_rendered_companion_meta(file_path: str) -> dict | None:
    direct = companion_meta_path(file_path)
    if os.path.isfile(direct):
        try:
            with open(direct, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass

    folder = os.path.dirname(file_path) or "."
    try:
        st = os.stat(file_path)
    except OSError:
        return None
    try:
        for name in os.listdir(folder):
            if not name.endswith(_COMPANION_SUFFIX):
                continue
            meta_path = os.path.join(folder, name)
            try:
                with open(meta_path, encoding="utf-8") as handle:
                    data = json.load(handle)
                if (
                    isinstance(data, dict)
                    and data.get("size") == st.st_size
                    and data.get("mtime_ns") == st.st_mtime_ns
                ):
                    return data
            except (OSError, json.JSONDecodeError):
                continue
    except OSError:
        pass
    return None


def poster_cache_path(cache_dir: str, file_path: str) -> str:
    key = hashlib.sha256(file_identity(file_path).encode("utf-8")).hexdigest()[:20]
    folder = os.path.join(cache_dir, "rendered_posters")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{key}.jpg")


def extract_poster_frame(file_path: str, cache_dir: str) -> str:
    """Return a cached JPEG poster for a rendered file, generating via ffmpeg if needed."""
    out_path = poster_cache_path(cache_dir, file_path)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_path

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", "1", "-i", file_path,
                "-frames:v", "1", "-q:v", "3",
                out_path,
            ],
            check=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if os.path.isfile(out_path):
            return out_path
    except Exception as exc:
        logging.debug("Poster extract failed for %s: %s", file_path, exc)
    return ""


def markers_sidecar_path(cache_dir: str, file_path: str) -> str:
    key = hashlib.sha256(file_identity(file_path).encode("utf-8")).hexdigest()[:20]
    folder = os.path.join(cache_dir, "rendered_markers")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{key}.json")


def load_markers_sidecar(cache_dir: str, file_path: str) -> list[dict]:
    path = markers_sidecar_path(cache_dir, file_path)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("identity") != file_identity(file_path):
            return []
        return list(data.get("entries", []))
    except Exception:
        return []


def save_markers_sidecar(cache_dir: str, file_path: str, entries: list[dict]) -> None:
    path = markers_sidecar_path(cache_dir, file_path)
    payload = {
        "file": os.path.normpath(file_path),
        "identity": file_identity(file_path),
        "entries": entries,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def markers_to_canvas(markers: list[dict]) -> list[dict]:
    """Convert sidecar entries to internal timeline marker dicts."""
    out = []
    for entry in markers:
        try:
            time_ms = int(entry.get("time", 0))
        except (TypeError, ValueError):
            continue
        out.append({
            "id": str(entry.get("id", time_ms)),
            "time_ms": time_ms,
            "icon_key": entry.get("type", "usermarker"),
            "is_round": False,
            "title": entry.get("title", ""),
            "desc": entry.get("description", ""),
        })
    return out


def canvas_markers_to_sidecar(markers: list[dict]) -> list[dict]:
    out = []
    for m in markers:
        out.append({
            "id": str(m.get("id", "")),
            "time": str(int(m.get("time_ms", 0))),
            "type": m.get("icon_key", "usermarker"),
            "title": m.get("title", ""),
            "description": m.get("desc", ""),
            "icon": "steam_marker",
            "priority": 0,
        })
    out.sort(key=lambda e: int(e.get("time", 0)))
    return out
