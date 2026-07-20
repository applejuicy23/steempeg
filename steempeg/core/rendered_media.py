"""Helpers for exported / rendered flat media files (not Steam DASH folders)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
# Anything above ~48 h is almost certainly corrupt container metadata (Steam copy bugs).
MAX_SANE_MEDIA_DURATION_SEC = 48 * 3600

_RENDERED_NAME_RE = re.compile(r"^(?:clip|bg|fg)_(\d+)_", re.IGNORECASE)
_STEAM_CLIP_PREFIXES = ("clip", "bg", "fg")
_COMPANION_SUFFIX = ".steempeg.json"


def _bundled_bin_dir() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        # steempeg/core/rendered_media.py -> repo root
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "bin")


def resolve_ffprobe_exe() -> str:
    name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    bundled = os.path.join(_bundled_bin_dir(), name)
    return bundled if os.path.isfile(bundled) else "ffprobe"


def resolve_ffmpeg_exe() -> str:
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bundled = os.path.join(_bundled_bin_dir(), name)
    return bundled if os.path.isfile(bundled) else "ffmpeg"


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
    if len(parts) >= 2 and parts[0].lower() in _STEAM_CLIP_PREFIXES and parts[1].isdigit():
        return parts[1]
    return None


def is_default_rendered_basename(stem: str, app_id: str | None) -> bool:
    """True for Steam's default ``<clip|bg|fg>_<appid>_…_rendered`` export names."""
    if not app_id:
        return False
    low = stem.lower()
    for prefix in _STEAM_CLIP_PREFIXES:
        if low.startswith(f"{prefix}_{app_id}_") and low.endswith("_rendered"):
            return True
    return False


def companion_meta_path(file_path: str) -> str:
    return file_path + _COMPANION_SUFFIX


def is_sane_media_duration(sec: float | int | None) -> bool:
    if sec is None:
        return False
    try:
        val = float(sec)
    except (TypeError, ValueError):
        return False
    return 0.0 < val <= MAX_SANE_MEDIA_DURATION_SEC


_DURATION_HMS_RE = re.compile(
    r"^(?P<h>-?\d+):(?P<m>\d{1,2}):(?P<s>\d{1,2}(?:\.\d+)?)$"
)


def parse_media_duration_text(raw: str | None) -> float | None:
    """Parse ffprobe duration text: seconds float, or Matroska ``HH:MM:SS.nnn`` tags."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        val = float(text)
        return val if is_sane_media_duration(val) else None
    except ValueError:
        pass
    m = _DURATION_HMS_RE.match(text)
    if not m:
        return None
    try:
        hours = int(m.group("h"))
        minutes = int(m.group("m"))
        seconds = float(m.group("s"))
    except (TypeError, ValueError):
        return None
    if hours < 0 or minutes < 0 or seconds < 0:
        return None
    total = hours * 3600 + minutes * 60 + seconds
    return total if is_sane_media_duration(total) else None


def probe_matroska_tag_duration_sec(file_path: str) -> float | None:
    """MKV/WebM often store length only in ``TAG:DURATION`` (stream/format stay N/A)."""
    if not file_path or not os.path.isfile(file_path):
        return None
    try:
        out = subprocess.check_output(
            [
                resolve_ffprobe_exe(), "-v", "error",
                "-show_entries", "format_tags=DURATION:stream_tags=DURATION",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            creationflags=_NO_WINDOW,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
        )
    except Exception:
        return None
    for line in out.splitlines():
        val = parse_media_duration_text(line)
        if val is not None:
            return val
    return None


def probe_media_duration_sec(file_path: str) -> float | None:
    """Return a trustworthy duration in seconds (video stream first, then format, then tags)."""
    if not file_path or not os.path.isfile(file_path):
        return None
    for stream_sel in ("v:0", "a:0"):
        try:
            out = subprocess.check_output(
                [
                    resolve_ffprobe_exe(), "-v", "error", f"-select_streams", stream_sel,
                    "-show_entries", "stream=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path,
                ],
                creationflags=_NO_WINDOW,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=20,
            ).strip()
            val = parse_media_duration_text(out.splitlines()[0] if out else None)
            if val is not None:
                return val
        except Exception:
            pass
    try:
        out = subprocess.check_output(
            [
                resolve_ffprobe_exe(), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            creationflags=_NO_WINDOW,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
        ).strip()
        val = parse_media_duration_text(out.splitlines()[0] if out else None)
        if val is not None:
            return val
    except Exception:
        pass
    return probe_matroska_tag_duration_sec(file_path)


def duration_from_source_clip(clip_path: str) -> float | None:
    """Fallback duration from the Steam source folder (MPD / chunk count)."""
    if not clip_path or not os.path.isdir(clip_path):
        return None
    try:
        from steempeg.core.dash import discovery
        from steempeg.core.dash.mpd import estimate_render_duration_sec

        mpds = discovery.find_mpd_paths(clip_path)
        if not mpds:
            return None
        dur = estimate_render_duration_sec(mpds[0])
        return float(dur) if is_sane_media_duration(dur) else None
    except Exception:
        return None


def save_rendered_companion_meta(
    file_path: str,
    *,
    app_id: str | None = None,
    game_name: str = "",
    clip_path: str = "",
    game_icon_path: str = "",
    duration_sec: float | None = None,
    duration_stream_sec: float | None = None,
    duration_format_sec: float | None = None,
    expected_duration_sec: float | None = None,
    health: str | None = None,
    health_issues: list[str] | None = None,
    health_cured: bool | None = None,
    health_rules_version: int | None = None,
    stream_copy: bool | None = None,
) -> None:
    """Write ``<video>.steempeg.json`` so renamed exports keep their game metadata."""
    try:
        st = os.stat(file_path)
    except OSError:
        return
    existing: dict = {}
    direct = companion_meta_path(file_path)
    if os.path.isfile(direct):
        try:
            with open(direct, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                existing = data
        except (OSError, json.JSONDecodeError):
            pass

    payload = dict(existing)
    payload.update({
        "app_id": app_id or "",
        "game_name": game_name or "",
        "clip_path": clip_path or "",
        "game_icon_path": game_icon_path or "",
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
    })
    # Prefer explicit duration; else probe the output file; else source clip estimate.
    if duration_sec is None:
        duration_sec = probe_media_duration_sec(file_path)
    if not is_sane_media_duration(duration_sec) and (clip_path or existing.get("clip_path")):
        duration_sec = duration_from_source_clip(clip_path or existing.get("clip_path") or "")
    if is_sane_media_duration(duration_sec):
        payload["duration_sec"] = round(float(duration_sec), 3)
    if is_sane_media_duration(duration_stream_sec):
        payload["duration_stream_sec"] = round(float(duration_stream_sec), 3)
    if is_sane_media_duration(duration_format_sec):
        payload["duration_format_sec"] = round(float(duration_format_sec), 3)
    if is_sane_media_duration(expected_duration_sec):
        payload["expected_duration_sec"] = round(float(expected_duration_sec), 3)
    if health:
        payload["health"] = str(health)
    if health_issues is not None:
        payload["health_issues"] = list(health_issues)
    if health_cured is not None:
        payload["health_cured"] = bool(health_cured)
    if health_rules_version is not None:
        payload["health_rules_version"] = int(health_rules_version)
    if stream_copy is not None:
        payload["stream_copy"] = bool(stream_copy)
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
