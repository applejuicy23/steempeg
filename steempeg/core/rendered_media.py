"""Helpers for exported / rendered flat media files (not Steam DASH folders)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess

_RENDERED_NAME_RE = re.compile(r"^clip_(\d+)_", re.IGNORECASE)


def file_identity(file_path: str) -> str:
    st = os.stat(file_path)
    norm = os.path.normcase(os.path.normpath(file_path))
    return f"{norm}|{st.st_mtime_ns}|{st.st_size}"


def parse_app_id_from_name(filename: str) -> str | None:
    stem = os.path.splitext(os.path.basename(filename))[0]
    m = _RENDERED_NAME_RE.match(stem)
    return m.group(1) if m else None


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
