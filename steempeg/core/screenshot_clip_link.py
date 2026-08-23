"""Link Screenshots shelf tiles back to Clips Manager folders.

Signals (strongest first):
1. Beside-file sidecar ``*.steempeg.json`` with ``clip_path`` (written on capture)
2. Optional ``__clip|fg|bg_<app>_<date>_<time>`` suffix in Steempeg filenames
3. Steam ``screenshots.vdf`` ``timelineid`` + ``timelinetime`` vs clip
   ``timelines/*.json`` + nested ``video/fg_*`` offset (authoritative for Steam)
4. Wall-clock vs **media** window (nested ``video/fg_*`` start + duration;
   Steam ``clip_*`` folder names are often near segment end — do not use as start)
5. Sole library clip for the resolved app_id (never dump the whole game library)

Ambiguous matches return at most a few overlapping candidates for a pick menu.
Unmapped shots and generic Steempeg labels like ``Clip`` stay unresolved —
UI disables or shows a short dialog.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from steempeg.core.rendered_media import (
    duration_from_source_clip,
    parse_app_id_from_clip_folder,
)
from steempeg.core.steam_screenshots import (
    _SCREENSHOT_NAME_RE as _STEAM_SHOT_NAME_RE,
    clip_has_timeline,
    clip_media_start_local,
    clip_timeline_offset_ms,
    lookup_steam_screenshot_vdf,
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

# Tiny skew only — a 90s pad previously marked "shot before clip start" as
# overlap, then seek clamped to 0:00 ("no screenshots at the beginning").
_STEAM_WINDOW_PAD_SEC = 3.0
# Ambiguous pick menu: never list the whole game library.
_MAX_RELATED_CLIP_CANDIDATES = 5
# Drop candidates farther than this from the shot (outside any window).
_MAX_CANDIDATE_DISTANCE_SEC = 12 * 3600.0
# Among overlapping known-duration clips, auto-pick when longest clearly wins.
_CLEAR_DURATION_RATIO = 1.5
_CLEAR_DURATION_EXTRA_SEC = 30.0
# Timeline ms containment pad (chunk boundaries / naming skew).
_TIMELINE_CONTAIN_PAD_MS = 2000.0


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
    steam_shot_local: datetime | None = None  # wall-clock from Steam *or* Steempeg name
    steam_timeline_id: str = ""
    steam_timeline_time_ms: int | None = None
    steam_creation: int | None = None


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


def steempeg_shot_local_from_filename(filename: str) -> datetime | None:
    """Wall-clock from ``…_{YYYYMMDD}_{HHMMSS}`` in a Steempeg capture name."""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    match = _STEEMPEG_SHOT_RE.match(stem)
    if not match:
        return None
    try:
        return datetime.strptime(f"{match.group(3)}{match.group(4)}", "%Y%m%d%H%M%S")
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
    shot_local = (
        steam_shot_local_from_filename(file_path)
        if source_key == "steam"
        else steempeg_shot_local_from_filename(file_path)
    )

    steam_timeline_id = ""
    steam_timeline_time_ms: int | None = None
    steam_creation: int | None = None
    if source_key == "steam" and file_path:
        vdf = lookup_steam_screenshot_vdf(file_path)
        if vdf:
            steam_timeline_id = str(vdf.get("timeline_id") or "").strip()
            raw_tt = vdf.get("timeline_time_ms")
            if raw_tt is not None:
                try:
                    steam_timeline_time_ms = int(raw_tt)
                except (TypeError, ValueError):
                    steam_timeline_time_ms = None
            raw_c = vdf.get("creation")
            if raw_c is not None:
                try:
                    steam_creation = int(raw_c)
                except (TypeError, ValueError):
                    steam_creation = None
            # Prefer VDF creation (unix local wall-clock) when filename is missing.
            if shot_local is None and steam_creation is not None and steam_creation > 0:
                try:
                    shot_local = datetime.fromtimestamp(steam_creation)
                except (OSError, OverflowError, ValueError):
                    pass
            if not steam_app and vdf.get("app_id"):
                steam_app = str(vdf.get("app_id") or "").strip()

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
        steam_shot_local=shot_local,
        steam_timeline_id=steam_timeline_id,
        steam_timeline_time_ms=steam_timeline_time_ms,
        steam_creation=steam_creation,
    )


def hint_suggests_related_clip(hint: ScreenshotClipHint) -> bool:
    """Cheap enable check for the Screenshots context-menu action."""
    if hint.clip_path or hint.clip_folder:
        return True
    if hint.source == "steam" and (
        hint.app_id
        or hint.steam_shot_local
        or hint.steam_timeline_id
        or hint.steam_timeline_time_ms is not None
    ):
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


def _duration_sec(clip: LibraryClipRef, *, allow_probe: bool = False) -> float | None:
    """Library duration cell first; optional MPD probe (disk — keep off UI hot paths)."""
    if clip.duration_sec is not None and clip.duration_sec > 0:
        return float(clip.duration_sec)
    if not allow_probe:
        return None
    return duration_from_source_clip(clip.path)


def _clip_start_naive(clip: LibraryClipRef) -> datetime | None:
    """Playable-media start (nested fg/bg when present), naive local."""
    start_local = clip_media_start_local(clip.path)
    if start_local is None:
        return None
    if start_local.tzinfo is not None:
        return start_local.replace(tzinfo=None)
    return start_local


def _time_mismatch_sec(clip: LibraryClipRef, shot_local: datetime) -> float | None:
    """Seconds outside the clip's padded media window (0 = shot falls inside).

    Lower is better. ``None`` when the clip has no parseable media start.

    Uses nested ``video/fg_*`` start when present — Steam ``clip_*`` folder
    names are often near the *end* of the segment, which previously made short
    nearby clips beat the long recording that actually contains the shot.

    Unknown duration: only treat as overlap within ``±pad`` of media start
    (never invent a multi-hour containment window).
    """
    start_naive = _clip_start_naive(clip)
    if start_naive is None:
        return None
    dur = _duration_sec(clip)
    pad = _STEAM_WINDOW_PAD_SEC
    offset = (shot_local - start_naive).total_seconds()
    if dur and dur > 0:
        span = float(dur)
        if offset < -pad:
            return -offset - pad
        if offset > span + pad:
            return offset - span - pad
        return 0.0
    # No duration → point window around media start only.
    if abs(offset) <= pad:
        return 0.0
    return abs(offset) - pad


def _overlap_rank_key(clip: LibraryClipRef) -> tuple:
    """Prefer known duration, then longer clips (story over 10s tests)."""
    dur = _duration_sec(clip)
    known = 1 if dur and dur > 0 else 0
    return (-known, -(float(dur) if dur and dur > 0 else 0.0), clip.path.casefold())


def _clips_for_app(clips: Sequence[LibraryClipRef], app_id: str) -> list[LibraryClipRef]:
    aid = str(app_id or "").strip()
    if not aid:
        return []
    return [c for c in clips if str(c.app_id or "").strip() == aid]


def _rank_clips_by_shot_time(
    clips: Sequence[LibraryClipRef], shot_local: datetime
) -> list[tuple[float, LibraryClipRef]]:
    ranked: list[tuple[float, LibraryClipRef]] = []
    for clip in clips:
        mismatch = _time_mismatch_sec(clip, shot_local)
        if mismatch is None:
            continue
        if mismatch > _MAX_CANDIDATE_DISTANCE_SEC:
            continue
        ranked.append((mismatch, clip))
    # Overlaps (0) first; among ties prefer longest known duration.
    ranked.sort(key=lambda item: (item[0],) + _overlap_rank_key(item[1]))
    return ranked


def _select_from_time_ranked(
    ranked: Sequence[tuple[float, LibraryClipRef]],
) -> list[str]:
    """Auto-pick a clear overlap winner, else a short ambiguous list.

    Never auto-opens a near-miss outside the padded media window — that was
    how a 10s test clip stolen Open related from a long story recording.
    """
    if not ranked:
        return []

    overlapping = [clip for mismatch, clip in ranked if mismatch <= 0.0]
    if not overlapping:
        return []

    overlapping.sort(key=_overlap_rank_key)
    if len(overlapping) == 1:
        return [overlapping[0].path]

    best = overlapping[0]
    second = overlapping[1]
    best_dur = _duration_sec(best) or 0.0
    second_dur = _duration_sec(second) or 0.0
    if best_dur > 0 and second_dur <= 0:
        return [best.path]
    if (
        best_dur > 0
        and second_dur > 0
        and best_dur >= second_dur * _CLEAR_DURATION_RATIO
        and best_dur >= second_dur + _CLEAR_DURATION_EXTRA_SEC
    ):
        return [best.path]

    return [c.path for c in overlapping[:_MAX_RELATED_CLIP_CANDIDATES]]


def _timeline_seek_sec(
    clip_path: str,
    timeline_id: str,
    timeline_time_ms: int,
    *,
    clip_duration_sec: float | None = None,
) -> float | None:
    """Playhead sec from VDF timelinetime − clip's timeline offset."""
    offset_ms = clip_timeline_offset_ms(clip_path, timeline_id)
    if offset_ms is None:
        return None
    seek = (float(timeline_time_ms) - float(offset_ms)) / 1000.0
    if seek < -(_TIMELINE_CONTAIN_PAD_MS / 1000.0):
        return None
    if seek < 0:
        return 0.0
    if clip_duration_sec is not None and clip_duration_sec > 0:
        if seek > float(clip_duration_sec) + (_TIMELINE_CONTAIN_PAD_MS / 1000.0):
            return None
        return min(float(seek), max(0.0, float(clip_duration_sec) - 0.05))
    return float(seek)


def _rank_clips_by_timeline(
    clips: Sequence[LibraryClipRef],
    timeline_id: str,
    timeline_time_ms: int,
) -> list[tuple[float, LibraryClipRef, int, float | None]]:
    """Return (mismatch_ms, clip, offset_ms, dur) for clips on this timeline.

    mismatch_ms == 0 means timelinetime falls inside the clip media window.
    Probes MPD duration when the library cell is empty — Open related is
    user-initiated, so a short disk hit is acceptable.
    """
    tid = (timeline_id or "").strip()
    if not tid:
        return []
    ranked: list[tuple[float, LibraryClipRef, int, float | None]] = []
    for clip in clips:
        if not clip_has_timeline(clip.path, tid):
            continue
        offset_ms = clip_timeline_offset_ms(clip.path, tid)
        if offset_ms is None:
            continue
        dur = _duration_sec(clip, allow_probe=True)
        tt = float(timeline_time_ms)
        pad = _TIMELINE_CONTAIN_PAD_MS
        if dur is not None and dur > 0:
            end_ms = float(offset_ms) + float(dur) * 1000.0
            if tt < float(offset_ms) - pad:
                mismatch = float(offset_ms) - pad - tt
            elif tt > end_ms + pad:
                mismatch = tt - end_ms - pad
            else:
                mismatch = 0.0
        else:
            # No duration: only accept near the media start.
            delta = abs(tt - float(offset_ms))
            mismatch = 0.0 if delta <= pad else delta - pad
        if mismatch > _MAX_CANDIDATE_DISTANCE_SEC * 1000.0:
            continue
        ranked.append((mismatch, clip, offset_ms, dur))
    ranked.sort(key=lambda item: (item[0],) + _overlap_rank_key(item[1]))
    return ranked


def related_clip_seek_offset_sec(
    file_path: str,
    clip_path: str = "",
    *,
    source: str = "",
    app_id: str = "",
    game_name: str = "",
    hint: ScreenshotClipHint | None = None,
    clip_duration_sec: float | None = None,
) -> float | None:
    """Approximate playhead offset (seconds) for Open related clip.

    Priority:
    1. Sidecar ``pos_ms`` (Steempeg capture) — authoritative playhead ms
    2. Filename ``_{ms}ms_`` (same parser as the hint)
    3. Steam VDF ``timelinetime`` − clip timeline offset (nested fg)
    4. Steam / Steempeg shot wall-clock minus **media** start (nested fg/bg)

    Returns ``None`` when the offset cannot be determined (open at 0).
    Soft-clamps wall-clock offsets when ``clip_duration_sec`` is known so a
    timezone/skew miss does not request a seek past EOF (UI clamps to end).
    Caller still waits for media duration before applying the seek.
    """
    if hint is None:
        if not file_path:
            return None
        hint = collect_screenshot_clip_hint(
            file_path, source=source, app_id=app_id, game_name=game_name
        )

    dur = float(clip_duration_sec) if clip_duration_sec and clip_duration_sec > 0 else None
    if dur is None and clip_path:
        probed = duration_from_source_clip(clip_path)
        if probed and probed > 0:
            dur = float(probed)

    if hint.pos_ms is not None and hint.pos_ms >= 0:
        # Sidecar / filename store millisecond playhead — never treat as seconds.
        return float(hint.pos_ms) / 1000.0

    if (
        clip_path
        and hint.steam_timeline_id
        and hint.steam_timeline_time_ms is not None
        and hint.steam_timeline_time_ms >= 0
    ):
        seek = _timeline_seek_sec(
            clip_path,
            hint.steam_timeline_id,
            hint.steam_timeline_time_ms,
            clip_duration_sec=dur,
        )
        if seek is not None:
            logging.info(
                "Related seek VDF: clip=%s timeline=%s tt_ms=%s media_off_ms=%s "
                "shot_time=%s seek_sec=%.2f",
                os.path.basename(clip_path),
                hint.steam_timeline_id,
                hint.steam_timeline_time_ms,
                clip_timeline_offset_ms(clip_path, hint.steam_timeline_id),
                hint.steam_shot_local.isoformat(sep=" ", timespec="seconds")
                if hint.steam_shot_local
                else "—",
                seek,
            )
            return seek

    if hint.steam_shot_local is not None and clip_path:
        start_local = clip_media_start_local(clip_path)
        if start_local is not None:
            start_naive = (
                start_local.replace(tzinfo=None)
                if start_local.tzinfo is not None
                else start_local
            )
            offset = (hint.steam_shot_local - start_naive).total_seconds()
            if offset < 0:
                if offset > -_STEAM_WINDOW_PAD_SEC:
                    return 0.0
                return None
            if dur is not None:
                if offset > dur + _STEAM_WINDOW_PAD_SEC:
                    return None
                return min(float(offset), max(0.0, dur - 0.05))
            return float(offset)

    return None


def resolve_related_clip_paths(
    file_path: str,
    library_clips: Sequence[LibraryClipRef],
    *,
    source: str = "",
    app_id: str = "",
    game_name: str = "",
) -> list[str]:
    """Return related clip folder paths (best first). Empty = unresolved.

    Strong unique hits (sidecar / filename clip id) return a single path.
    Time-based matches auto-open when one media window clearly wins; otherwise
    at most ``_MAX_RELATED_CLIP_CANDIDATES`` overlapping paths. Never returns
    every library clip for an app_id.
    """
    if not file_path:
        return []
    hint = collect_screenshot_clip_hint(
        file_path, source=source, app_id=app_id, game_name=game_name
    )
    clips = list(library_clips or [])

    exact = _clip_in_library(clips, hint.clip_path)
    if exact:
        logging.info(
            "Related clip: sidecar/exact %s for %s",
            os.path.basename(exact),
            os.path.basename(file_path),
        )
        return [exact]

    if hint.clip_folder:
        by_name = _find_by_basename(clips, hint.clip_folder)
        if by_name:
            logging.info(
                "Related clip: folder name %s for %s",
                os.path.basename(by_name),
                os.path.basename(file_path),
            )
            return [by_name]

    pool = _clips_for_app(clips, hint.app_id) if hint.app_id else list(clips)

    # Steam VDF timelineid + timelinetime — only clips that actually contain
    # that moment. Never fall back to a June clip for an August screenshot.
    if (
        hint.steam_timeline_id
        and hint.steam_timeline_time_ms is not None
        and hint.steam_timeline_time_ms >= 0
    ):
        ranked_tl = _rank_clips_by_timeline(
            pool, hint.steam_timeline_id, hint.steam_timeline_time_ms
        )
        overlapping = [
            (mismatch, clip, off, dur)
            for mismatch, clip, off, dur in ranked_tl
            if mismatch <= 0.0
        ]
        if overlapping:
            overlapping.sort(key=lambda item: _overlap_rank_key(item[1]))
            selected_clips = [item[1] for item in overlapping]
            paths = _select_from_time_ranked([(0.0, c) for c in selected_clips])
            top = overlapping[: min(5, len(overlapping))]
            score_bits = []
            for _m, clip, off, dur in top:
                score_bits.append(
                    f"{os.path.basename(clip.path)}(off_ms={off},"
                    f"dur={dur if dur is not None else '—'})"
                )
            logging.info(
                "Related clip VDF-match for %s timeline=%s tt_ms=%s shot=%s → %s | %s",
                os.path.basename(file_path),
                hint.steam_timeline_id,
                hint.steam_timeline_time_ms,
                hint.steam_shot_local.isoformat(sep=" ", timespec="seconds")
                if hint.steam_shot_local
                else "—",
                [os.path.basename(p) for p in paths],
                "; ".join(score_bits),
            )
            return paths
        if ranked_tl:
            best_m, best_c, best_off, best_dur = ranked_tl[0]
            logging.info(
                "Related clip: no VDF containment for %s (nearest %s "
                "mismatch_ms=%.0f off_ms=%s dur=%s) — not opening a wrong clip",
                os.path.basename(file_path),
                os.path.basename(best_c.path),
                best_m,
                best_off,
                best_dur if best_dur is not None else "—",
            )
            return []
        logging.info(
            "Related clip: no library clip hosts timeline %s for %s",
            hint.steam_timeline_id,
            os.path.basename(file_path),
        )
        return []

    if hint.steam_shot_local is not None:
        probed_pool: list[LibraryClipRef] = []
        for clip in pool:
            if clip.duration_sec is not None and clip.duration_sec > 0:
                probed_pool.append(clip)
                continue
            dur = duration_from_source_clip(clip.path)
            probed_pool.append(
                LibraryClipRef(
                    path=clip.path,
                    app_id=clip.app_id,
                    duration_sec=dur,
                    game_name=clip.game_name,
                )
            )
        ranked = _rank_clips_by_shot_time(probed_pool, hint.steam_shot_local)
        selected = _select_from_time_ranked(ranked)
        if selected:
            top = ranked[: min(5, len(ranked))]
            score_bits = []
            for mismatch, clip in top:
                dur = _duration_sec(clip)
                start = clip_media_start_local(clip.path)
                start_s = (
                    start.isoformat(sep=" ", timespec="seconds") if start else "—"
                )
                score_bits.append(
                    f"{os.path.basename(clip.path)}(mismatch={mismatch:.1f}s,"
                    f"dur={dur if dur is not None else '—'},media_start={start_s})"
                )
            logging.info(
                "Related clip time-match for %s @ %s → %s | top: %s",
                os.path.basename(file_path),
                hint.steam_shot_local.isoformat(sep=" ", timespec="seconds"),
                [os.path.basename(p) for p in selected],
                "; ".join(score_bits),
            )
            return selected
        if ranked:
            best_m, best_c = ranked[0]
            logging.info(
                "Related clip: no overlap for %s (nearest %s mismatch=%.1fs)",
                os.path.basename(file_path),
                os.path.basename(best_c.path),
                best_m,
            )
        return []

    if hint.app_id:
        same_game = pool
        if not same_game:
            return []
        if len(same_game) == 1:
            return [same_game[0].path]
        if hint.pos_ms is not None and hint.pos_ms >= 0:
            need = float(hint.pos_ms) / 1000.0
            long_enough: list[LibraryClipRef] = []
            for clip in same_game:
                dur = _duration_sec(clip)
                if dur is None or dur + 1.0 >= need:
                    long_enough.append(clip)
            if len(long_enough) == 1:
                return [long_enough[0].path]
        return []

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
