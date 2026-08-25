"""Background timeline JSON discovery for clip open — keeps UI thread free."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime

from PySide6.QtCore import QThread, Signal

_log = logging.getLogger(__name__)


def timeline_offset_ms(json_path: str | None, mpd_path: str) -> int:
    """Align Steam timeline timestamps with the active MPD video folder."""
    if not json_path:
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


class TimelineMarkersLoadWorker(QThread):
    """Find timeline JSON off the GUI thread; parse/apply stays on the canvas."""

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
        self._mpd_path = mpd_path
        self._cache_dir = cache_dir

    def run(self) -> None:
        result: dict = {"clip_path": self._clip_path, "mpd_path": self._mpd_path}
        try:
            from steempeg.core.clip_markers_cache import (
                ensure_steempeg_timeline_json,
                find_clip_timeline_json,
                is_steam_timeline_json,
                is_steempeg_timeline_json,
            )

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

            result["json_path"] = json_path
            result["offset_ms"] = timeline_offset_ms(json_path, self._mpd_path)
            result["use_cache"] = bool(json_path and is_steam_timeline_json(json_path))
        except Exception as exc:
            _log.exception("Timeline markers load worker failed")
            result["error"] = str(exc)

        if not self.isInterruptionRequested():
            self.finished_load.emit(result)
