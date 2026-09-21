"""Background timeline JSON discovery + parse for clip open — keeps UI free."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

from PySide6.QtCore import QThread, Signal

_log = logging.getLogger(__name__)


def timeline_offset_ms(json_path: str | None, mpd_path: str) -> int:
    """Align Steam timeline timestamps with the active MPD video folder."""
    if not json_path or not mpd_path:
        return 0
    json_name = os.path.basename(json_path)
    video_folder_name = os.path.basename(os.path.dirname(mpd_path))
    json_match = re.search(r"(\d{8})_(\d{6})", json_name)
    video_match = re.search(r"(\d{8})_(\d{6})", video_folder_name)
    if not (json_match and video_match):
        return 0
    try:
        j_str = json_match.group(1) + json_match.group(2)
        v_str = video_match.group(1) + video_match.group(2)
        json_dt = datetime.strptime(j_str, "%Y%m%d%H%M%S")
        video_dt = datetime.strptime(v_str, "%Y%m%d%H%M%S")
        return int((video_dt - json_dt).total_seconds() * 1000)
    except Exception as exc:
        _log.debug("Timeline offset calc failed: %s", exc)
        return 0


def _is_self_kill_event(title, desc="") -> bool:
    blob = f"{title or ''} {desc or ''}".lower()
    return (
        "killed yourself" in blob
        or "kill yourself" in blob
        or "you killed yourself" in blob
        or ("suicide" in blob and "assist" not in blob)
    )


def _parse_event_to_icon(type_, title, desc):
    t_low = (title or "").lower()
    d_low = (desc or "").lower()

    if type_ == "usermarker":
        return "usermarker", False
    if type_ == "screenshot":
        return "screenshot", False
    if type_ in ("error", "restrict"):
        return "restrict", False

    round_match = re.search(r"start of round (\d+)", t_low)
    if round_match:
        return round_match.group(1), True

    if "bomb planted" in t_low:
        return "bomb", False
    if "bomb exploded" in t_low or "explosion" in t_low:
        return "explosion", False
    if "bomb defused" in t_low or "defuse" in t_low:
        return "defuse", False
    if "killed yourself" in t_low or "kill yourself" in t_low:
        return "death", False
    if "killed by" in t_low:
        return "death", False

    if "kill" in t_low:
        if "knife" in d_low:
            return "knife", False
        if "zeus" in d_low or "taser" in d_low:
            return "tazer", False
        if "he grenade" in d_low or "grenade" in d_low:
            return "grenade", False
        if "fire" in d_low or "molotov" in d_low or "incendiary" in d_low:
            return "firemolotov", False
        if "flashbang" in d_low:
            return "flashbang", False
        if "smoke" in d_low:
            return "smoke", False
        return "kill", False

    return "point", False


def _build_timeline_payload(
    json_path: str,
    offset_ms: int,
    *,
    clip_path: str | None,
    cache_dir: str | None,
    merge_marker_cache: bool,
) -> dict:
    """Parse Steam/Steempeg timeline JSON into canvas-ready lists (no Qt)."""
    from steempeg.core.clip_markers_cache import (
        is_steempeg_timeline_json,
        merge_cached_user_markers,
    )
    from steempeg.core.steam_screenshots import timeline_json_start_utc
    from steempeg.services.steam_markers import app_id_from_clip_paths

    markers: list[dict] = []
    mode_segments: list[tuple] = []
    clip_ranges: list[tuple] = []
    remembered_ids: list[str] = []

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", []) if isinstance(data, dict) else []
    steempeg_file = is_steempeg_timeline_json(json_path)

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_time = int(entry.get("time", 0) or 0)
        time_ms = raw_time - offset_ms
        if time_ms < 0:
            continue

        type_ = entry.get("type", "")
        title = entry.get("title", "")
        desc = entry.get("description", "")
        m_id = str(entry.get("id", ""))

        if type_ not in ("event", "screenshot", "error", "restrict", "usermarker"):
            continue

        icon_key, is_round = _parse_event_to_icon(type_, title, desc)
        if icon_key == "screenshot" and not title:
            title = "A screenshot"

        marker = {
            "id": m_id,
            "time_ms": time_ms,
            "raw_time_ms": raw_time,
            "icon": entry.get("icon", ""),
            "icon_key": icon_key,
            "is_round": is_round,
            "title": title,
            "desc": desc,
            "self_kill": _is_self_kill_event(title, desc),
        }
        if icon_key == "usermarker" and steempeg_file:
            marker["steempeg_owned"] = True
        markers.append(marker)

    if merge_marker_cache:
        try:
            markers = merge_cached_user_markers(
                markers,
                cache_dir,
                clip_path=clip_path,
                json_path=json_path,
            )
        except Exception as exc:
            _log.debug("Clip markers cache merge: %s", exc)

    for m in markers:
        if m.get("icon"):
            remembered_ids.append(str(m.get("icon") or ""))
        if m.get("icon_key"):
            remembered_ids.append(str(m.get("icon_key") or ""))

    raw_gm = sorted(
        (int(e.get("time", 0) or 0), int(e.get("mode", 0) or 0))
        for e in entries
        if isinstance(e, dict) and e.get("type") == "gamemode"
    )
    start_mode = 0
    gm: list[tuple[int, int]] = []
    for raw_t, mode in raw_gm:
        t = raw_t - offset_ms
        if t <= 0:
            start_mode = mode
        else:
            gm.append((t, mode))
    gm = [(0, start_mode)] + gm
    for i, (t, mode) in enumerate(gm):
        end = gm[i + 1][0] if i + 1 < len(gm) else 10**12
        if end > t:
            mode_segments.append((t, end, mode))

    clip_lead = 2000
    feat: list[tuple[int, int]] = []
    for ev in entries:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "event" and int(ev.get("possible_clip", 0) or 0) >= 3:
            t = max(0, int(ev.get("time", 0) or 0) - offset_ms - clip_lead)
            dur = int(ev.get("duration", 0) or 0)
            if dur > 0:
                feat.append((t, t + dur))
    feat.sort()
    for a, b in feat:
        if clip_ranges and a <= clip_ranges[-1][1]:
            clip_ranges[-1] = (clip_ranges[-1][0], max(clip_ranges[-1][1], b))
        else:
            clip_ranges.append((a, b))

    return {
        "markers": markers,
        "mode_segments": mode_segments,
        "clip_ranges": clip_ranges,
        "remembered_ids": remembered_ids,
        "json_start_utc": timeline_json_start_utc(json_path),
        "app_id": app_id_from_clip_paths(json_path, clip_path),
    }


class TimelineMarkersLoadWorker(QThread):
    """Find + parse timeline JSON off the GUI thread; UI only paints the result."""

    finished_load = Signal(object)

    def __init__(
        self,
        clip_path: str,
        mpd_path: str,
        cache_dir: str | None,
        parent=None,
    ):
        super().__init__(parent)
        self._clip_path = clip_path
        self._mpd_path = mpd_path or ""
        self._cache_dir = cache_dir

    def run(self) -> None:
        result: dict = {"clip_path": self._clip_path, "mpd_path": self._mpd_path}
        try:
            from steempeg.core.clip_markers_cache import (
                ensure_steempeg_timeline_json,
                find_clip_timeline_json,
                is_steam_timeline_json,
                is_steempeg_timeline_json,
                merge_cached_user_markers,
            )
            from steempeg.services.steam_markers import app_id_from_clip_paths

            if self.isInterruptionRequested():
                return

            mpd_path = self._mpd_path
            if not mpd_path:
                # Open kicked us before UI finished MPD walk — find one for offset.
                try:
                    from steempeg.core.dash import discovery

                    paths = discovery.find_mpd_paths(self._clip_path) or []
                    if paths:
                        mpd_path = paths[0]
                        result["mpd_path"] = mpd_path
                except Exception:
                    _log.debug("Markers worker MPD probe failed", exc_info=True)

            json_path = find_clip_timeline_json(self._clip_path)
            if not json_path or (
                not is_steam_timeline_json(json_path)
                and not is_steempeg_timeline_json(json_path)
            ):
                created = ensure_steempeg_timeline_json(
                    self._clip_path, cache_dir=self._cache_dir
                )
                if created:
                    json_path = created

            if self.isInterruptionRequested():
                return

            result["json_path"] = json_path
            result["offset_ms"] = timeline_offset_ms(json_path, mpd_path)
            use_cache = bool(json_path and is_steam_timeline_json(json_path))
            result["use_cache"] = use_cache
            result["app_id"] = app_id_from_clip_paths(json_path, self._clip_path)

            if json_path and os.path.isfile(json_path):
                # Heavy read+parse off UI — this was the 1–2s stall after video started.
                payload = _build_timeline_payload(
                    json_path,
                    int(result["offset_ms"] or 0),
                    clip_path=self._clip_path,
                    cache_dir=self._cache_dir if use_cache else None,
                    merge_marker_cache=use_cache,
                )
                result.update(payload)
            else:
                # No Steam/Steempeg file — still restore user cache markers.
                try:
                    markers = merge_cached_user_markers(
                        [],
                        self._cache_dir,
                        clip_path=self._clip_path,
                        json_path=json_path,
                    )
                except Exception:
                    markers = []
                result["markers"] = markers
                result["mode_segments"] = []
                result["clip_ranges"] = []
                result["remembered_ids"] = []
                result["json_start_utc"] = None
        except Exception as exc:
            _log.exception("Timeline markers load worker failed")
            result["error"] = str(exc)

        if not self.isInterruptionRequested():
            self.finished_load.emit(result)
