"""Link Screenshots shelf tiles back to Clips Manager folders.

Signals (strongest first):
1. Beside-file sidecar ``*.steempeg.json`` with ``clip_path`` (written on capture)
2. Optional ``__clip|fg|bg_<app>_<date>_<time>`` suffix in Steempeg filenames
3. Steam userdata shots: app_id folder + filename wall-clock vs clip time window
4. Steempeg shots without clip id: sole library clip for the resolved app_id
   (or duration filter via ``_{ms}ms_`` when several clips share the game)

Unmapped / ambiguous Steam shots (no overlapping clip) and generic Steempeg
labels like ``Clip`` stay unresolved — UI disables or shows a short dialog.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from steempeg.core.rendered_media import (
    duration_from_source_clip,
    parse_app_id_from_clip_folder,
)
from steempeg.core.steam_screenshots import (
    _SCREENSHOT_NAME_RE as _STEAM_SHOT_NAME_RE,
    clip_folder_start_local,
)

# Steempeg capture names: ``{Game}_{ms}ms_{YYYYMMDD}_{HHMMSS}[__clipfolder].ext``
_STEEMPEG_SHOT_RE = re.compile(
    r"^(.+?)_(\d+)ms_(\d{8})_(\d{6})(?:__((?:clip|fg|bg)_\d+_\d{8}_\d{6}))?$",
    re.IGNORECASE,
)
_CLIP_BASENAME_RE = re.compile(
    r"^(?:clip|fg|bg)_\d+_\d{8}_\d{6}$",
    re.IGNORECASE,
)
_LIBRARY_DUR_RE = re.compile(
    r"^(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?$",
    re.IGNORECASE,
)
_GENERIC_GAMES = frozenset({"clip", "unknown", "unknown game"})

# Pad clip windows so Steam client clock skew still hits FG/CLIP sessions.
_STEAM_WINDOW_PAD_SEC = 90.0


def parse_library_duration_sec(raw: str | None) -> float | None:
    """Parse Clips Manager duration cell text (``5m 30s``, ``45s``, ``1h 2m``)."""
    text = str(raw or "").strip()
    if not text or text in {"--:--", "—", "-", "N/A"}:
        return None
    # Rare HH:MM:SS / seconds float from other panels.
    from steempeg.core.rendered_media import parse_media_duration_text

    probed = parse_media_duration_text(text)
    if probed is not None:
        return probed
    match = _LIBRARY_DUR_RE.match(text.replace(",", ""))
    if not match:
        return None
    try:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
    except (TypeError, ValueError):
        return None
    if hours == 0 and minutes == 0 and seconds == 0 and not any(match.groups()):
        return None
    total = hours * 3600 + minutes * 60 + seconds
    return float(total) if total > 0 else None


@dataclass(frozen=True)
class LibraryClipRef:
    """One Clips Manager row used for reverse screenshot matching."""

    path: str
    app_id: str = ""
    duration_sec: float | None = None
    game_name: str = ""


@dataclass(frozen=True)
class ScreenshotClipHint:
    """Parsed hints from a screenshot path / sidecar (no library lookup yet)."""

    clip_path: str = ""
    clip_folder: str = ""
    app_id: str = ""
    pos_ms: int | None = None
    game_name: str = ""
    source: str = ""  # "steam" | "steempeg" | ""
    steam_shot_local: datetime | None = None


def screenshot_sidecar_path(file_path: str) -> str:
    return f"{file_path}.steempeg.json"


def load_screenshot_clip_meta(file_path: str) -> dict | None:
    """Read optional beside-file meta written by ``take_screenshot``."""
    if not file_path:
        return None
    meta_path = screenshot_sidecar_path(file_path)
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_screenshot_clip_meta(
    file_path: str,
    *,
    clip_path: str = "",
    app_id: str = "",
    pos_ms: float | int | None = None,
    game_name: str = "",
) -> None:
    """Persist clip identity next to a freshly captured Steempeg PNG."""
    if not file_path:
        return
    payload: dict = {
        "kind": "screenshot",
        "clip_path": os.path.normpath(clip_path) if clip_path else "",
        "app_id": str(app_id or ""),
        "game_name": str(game_name or ""),
        "source_path": os.path.normpath(file_path),
    }
    if pos_ms is not None:
        try:
            payload["pos_ms"] = int(float(pos_ms))
        except (TypeError, ValueError):
            pass
    try:
        with open(screenshot_sidecar_path(file_path), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except OSError as exc:
        logging.debug("Could not write screenshot clip meta for %s: %s", file_path, exc)


def parse_steempeg_screenshot_name(filename: str) -> tuple[str, int | None, str]:
    """Return ``(game_name, pos_ms, clip_folder_basename)`` from a Steempeg shot name."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    match = _STEEMPEG_SHOT_RE.match(stem)
    if not match:
        return stem, None, ""
    game = (match.group(1) or "").strip() or stem
    try:
        pos_ms = int(match.group(2))
    except (TypeError, ValueError):
        pos_ms = None
    clip_folder = (match.group(5) or "").strip()
    return game, pos_ms, clip_folder


def detect_screenshot_source(file_path: str) -> str:
    """Heuristic source tag from path layout."""
    norm = os.path.normpath(file_path or "").replace("\\", "/").casefold()
    if "/760/remote/" in norm and "/screenshots/" in norm:
        return "steam"
    return "steempeg"


def steam_app_id_from_screenshot_path(file_path: str) -> str:
    """``…/userdata/<id>/760/remote/<app_id>/screenshots/<file>`` → app_id."""
    parts = os.path.normpath(file_path or "").replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        if part.casefold() != "screenshots" or i < 1:
            continue
        app_id = parts[i - 1]
        if app_id.isdigit():
            return app_id
    return ""


def steam_shot_local_from_filename(filename: str) -> datetime | None:
    match = _STEAM_SHOT_NAME_RE.match(os.path.basename(filename or ""))
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def collect_screenshot_clip_hint(
    file_path: str,
    *,
    source: str = "",
    app_id: str = "",
    game_name: str = "",
) -> ScreenshotClipHint:
    """Gather all path-local signals for a screenshot (no library scan)."""
    source_key = (source or detect_screenshot_source(file_path)).strip().lower()
    meta = load_screenshot_clip_meta(file_path) or {}
    clip_path = str(meta.get("clip_path") or "").strip()
    meta_app = str(meta.get("app_id") or "").strip()
    meta_game = str(meta.get("game_name") or "").strip()
    pos_ms: int | None = None
    if meta.get("pos_ms") is not None:
        try:
            pos_ms = int(float(meta["pos_ms"]))
        except (TypeError, ValueError):
            pos_ms = None

    game_from_name, name_pos, clip_folder = parse_steempeg_screenshot_name(file_path)
    if pos_ms is None:
        pos_ms = name_pos

    steam_app = steam_app_id_from_screenshot_path(file_path) if source_key == "steam" else ""
    steam_local = (
        steam_shot_local_from_filename(file_path) if source_key == "steam" else None
    )

    resolved_app = (
        str(app_id or "").strip()
        or meta_app
        or steam_app
        or (parse_app_id_from_clip_folder(clip_folder) if clip_folder else "")
        or (parse_app_id_from_clip_folder(os.path.basename(clip_path)) if clip_path else "")
    )
    resolved_game = (
        str(game_name or "").strip()
        or meta_game
        or (game_from_name if source_key != "steam" else "")
    )

    return ScreenshotClipHint(
        clip_path=os.path.normpath(clip_path) if clip_path else "",
        clip_folder=clip_folder,
        app_id=resolved_app,
        pos_ms=pos_ms,
        game_name=resolved_game,
        source=source_key,
        steam_shot_local=steam_local,
    )


def hint_suggests_related_clip(hint: ScreenshotClipHint) -> bool:
    """Cheap enable check for the Screenshots context-menu action."""
    if hint.clip_path or hint.clip_folder:
        return True
    if hint.source == "steam" and (hint.app_id or hint.steam_shot_local):
        return True
    game = (hint.game_name or "").strip().casefold()
    if hint.app_id and game not in _GENERIC_GAMES:
        return True
    if game and game not in _GENERIC_GAMES:
        return True
    return False


def _norm_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _find_by_basename(clips: Sequence[LibraryClipRef], folder_name: str) -> str:
    want = (folder_name or "").strip().casefold()
    if not want:
        return ""
    for clip in clips:
        if os.path.basename(clip.path).casefold() == want:
            return clip.path
    return ""


def _clip_in_library(clips: Sequence[LibraryClipRef], clip_path: str) -> str:
    if not clip_path:
        return ""
    want = _norm_key(clip_path)
    for clip in clips:
        if _norm_key(clip.path) == want:
            return clip.path
    # Sidecar may point at a still-valid folder not currently painted in the table.
    if os.path.isdir(clip_path):
        return os.path.normpath(clip_path)
    return ""


def _duration_sec(clip: LibraryClipRef) -> float | None:
    if clip.duration_sec is not None and clip.duration_sec > 0:
        return float(clip.duration_sec)
    return duration_from_source_clip(clip.path)


def _steam_time_matches(clip: LibraryClipRef, shot_local: datetime) -> bool:
    start_local = clip_folder_start_local(clip.path)
    if start_local is None:
        return False
    start_naive = (
        start_local.replace(tzinfo=None)
        if start_local.tzinfo is not None
        else start_local
    )
    dur = _duration_sec(clip)
    # Unknown duration: accept a generous same-day window from clip start.
    span = float(dur) if dur and dur > 0 else 6 * 3600.0
    pad = timedelta(seconds=_STEAM_WINDOW_PAD_SEC)
    lo = start_naive - pad
    hi = start_naive + timedelta(seconds=span) + pad
    return lo <= shot_local <= hi


def _clips_for_app(clips: Sequence[LibraryClipRef], app_id: str) -> list[LibraryClipRef]:
    aid = str(app_id or "").strip()
    if not aid:
        return []
    return [c for c in clips if str(c.app_id or "").strip() == aid]


def resolve_related_clip_paths(
    file_path: str,
    library_clips: Sequence[LibraryClipRef],
    *,
    source: str = "",
    app_id: str = "",
    game_name: str = "",
) -> list[str]:
    """Return related clip folder paths (best first). Empty = unresolved."""
    if not file_path:
        return []
    hint = collect_screenshot_clip_hint(
        file_path, source=source, app_id=app_id, game_name=game_name
    )
    clips = list(library_clips or [])

    exact = _clip_in_library(clips, hint.clip_path)
    if exact:
        return [exact]

    if hint.clip_folder:
        by_name = _find_by_basename(clips, hint.clip_folder)
        if by_name:
            return [by_name]

    if hint.source == "steam" and hint.steam_shot_local is not None:
        pool = _clips_for_app(clips, hint.app_id) if hint.app_id else list(clips)
        timed = [
            c.path
            for c in pool
            if _steam_time_matches(c, hint.steam_shot_local)
        ]
        if timed:
            return timed
        # Fall through to sole-app match when time window misses.

    if hint.app_id:
        same_game = _clips_for_app(clips, hint.app_id)
        if not same_game:
            return []
        if len(same_game) == 1:
            return [same_game[0].path]
        if hint.pos_ms is not None and hint.pos_ms >= 0:
            need = float(hint.pos_ms) / 1000.0
            long_enough: list[str] = []
            for clip in same_game:
                dur = _duration_sec(clip)
                if dur is None or dur + 1.0 >= need:
                    long_enough.append(clip.path)
            if len(long_enough) == 1:
                return long_enough
            if long_enough:
                return long_enough
        return [c.path for c in same_game]

    return []


def build_steempeg_screenshot_filename(
    game_name: str,
    pos_ms: float | int,
    *,
    clip_path: str = "",
    when: datetime | None = None,
) -> str:
    """Build a Steempeg screenshot basename (no directory)."""
    safe_game = re.sub(r'[\\/*?:"<>|]', "_", (game_name or "Clip").strip()) or "Clip"
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    base = f"{safe_game}_{int(pos_ms)}ms_{stamp}"
    folder = os.path.basename(os.path.normpath(clip_path)) if clip_path else ""
    if folder and _CLIP_BASENAME_RE.match(folder):
        return f"{base}__{folder}.png"
    return f"{base}.png"
