"""Classify Steam clip folders by playback health.

Three tiers (never inferred from the FG/BG/CLIP prefix alone — always from on-disk
signals inside the folder tree):

  healthy  — Green:  original session.mpd (or session_fixed), valid inits, chunks on
                    disk, ffmpeg can open the manifest, no serious timeline defects.
  degraded — Yellow: alive but flawed — recovered-only manifest, missing audio,
                    A/V start offset, corrupt decode-timeline jump, manifest duration
                    wildly exceeds surviving chunks. Still previewable/renderable.
  dead     — Red:    unplayable trash — missing/corrupt video init, no video chunks,
                    manifest references files that are not on disk, ffmpeg cannot open.

Pure filesystem + optional ffprobe — no Qt.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional, Tuple

from steempeg.core.dash import mpd as mpd_util
from steempeg.core.dash.repair import (
    _CHUNK_SECONDS,
    _mdhd_timescale,
    _stream_chunk_numbers,
    _tfdt_base_time,
)

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_MIN_INIT_BYTES = 100
_AVSYNC_WARN_SEC = 1.0
_TIMELINE_JUMP_WARN_SEC = 30.0
_DECLARED_DURATION_FACTOR = 5.0


class ClipHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DEAD = "dead"


HEALTH_LABELS = {
    ClipHealth.HEALTHY: "Healthy",
    ClipHealth.DEGRADED: "Issues",
    ClipHealth.DEAD: "Dead",
}

HEALTH_COLORS = {
    ClipHealth.HEALTHY: "#4caf50",
    ClipHealth.DEGRADED: "#e6a817",
    ClipHealth.DEAD: "#c0392b",
}

HEALTH_ICON_FILES = {
    ClipHealth.HEALTHY: "success.png",
    ClipHealth.DEGRADED: "issue.png",
    ClipHealth.DEAD: "dead.png",
}

WARNING_ICON_FILE = "issue.png"

# Worst tier wins when a clip folder contains several fg_* segments.
_RANK = {ClipHealth.HEALTHY: 0, ClipHealth.DEGRADED: 1, ClipHealth.DEAD: 2}


@dataclass
class ClipHealthReport:
    level: ClipHealth
    issues: List[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return HEALTH_LABELS[self.level]

    @property
    def color(self) -> str:
        return HEALTH_COLORS[self.level]

    def summary(self) -> str:
        if not self.issues:
            return self.label
        return f"{self.label}: " + "; ".join(self.issues)


def _valid_init(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) >= _MIN_INIT_BYTES
    except OSError:
        return False


def _segment_start_seconds(folder: str, stream_idx: int, chunk_num: int) -> Optional[float]:
    init_path = os.path.join(folder, f"init-stream{stream_idx}.m4s")
    chunk_path = os.path.join(folder, f"chunk-stream{stream_idx}-{chunk_num:05d}.m4s")
    media_ts = _mdhd_timescale(init_path)
    base = _tfdt_base_time(chunk_path)
    if not media_ts or base is None:
        return None
    return base / media_ts


def _ffprobe_opens(mpd_path: str, timeout: float = 6.0) -> bool:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-i", mpd_path],
            creationflags=_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _iter_segment_dirs(clip_path: str) -> Iterable[Tuple[str, str, str]]:
    """Yield (folder, mpd_path, kind) for every manifest under clip_path.

    kind is one of: original, fixed, recovered.
  """
    seen_dirs = set()
    if not os.path.isdir(clip_path):
        return
    for root, _, files in os.walk(clip_path):
        if root in seen_dirs:
            continue
        if "session.mpd" in files:
            seen_dirs.add(root)
            yield root, os.path.join(root, "session.mpd"), "original"
        elif "session_fixed.mpd" in files:
            seen_dirs.add(root)
            yield root, os.path.join(root, "session_fixed.mpd"), "fixed"
        elif "session_recovered.mpd" in files:
            seen_dirs.add(root)
            yield root, os.path.join(root, "session_recovered.mpd"), "recovered"


def _has_video_chunks_anywhere(clip_path: str) -> bool:
    for root, _, files in os.walk(clip_path):
        if any(f.startswith("chunk-stream0-") and f.endswith(".m4s") for f in files):
            return True
    return False


def assess_segment_folder(folder: str, mpd_path: str, mpd_kind: str) -> ClipHealthReport:
    issues: List[str] = []

    init_v = os.path.join(folder, "init-stream0.m4s")
    if not _valid_init(init_v):
        return ClipHealthReport(
            ClipHealth.DEAD,
            ["Missing or corrupt video init segment (init-stream0.m4s)"],
        )

    v_nums = _stream_chunk_numbers(folder, 0)
    if not v_nums:
        return ClipHealthReport(ClipHealth.DEAD, ["No video chunks on disk"])

    init_a = os.path.join(folder, "init-stream1.m4s")
    a_nums = _stream_chunk_numbers(folder, 1)
    has_audio = bool(a_nums and _valid_init(init_a))

    if mpd_kind == "recovered":
        issues.append("Reconstructed manifest only (no original session.mpd)")

    if not has_audio:
        issues.append("No audio track on disk")

    try:
        with open(mpd_path, "r", encoding="utf-8") as f:
            mpd_content = f.read()
    except OSError:
        return ClipHealthReport(ClipHealth.DEAD, ["Cannot read manifest"])

    declared = mpd_util.parse_duration_seconds(mpd_content)
    surviving_sec = len(v_nums) * _CHUNK_SECONDS
    if declared and surviving_sec < 30 and declared > surviving_sec * _DECLARED_DURATION_FACTOR:
        issues.append(
            f"Manifest claims {int(declared)}s but only {len(v_nums)} video chunk(s) survive "
            f"(~{int(surviving_sec)}s on disk)"
        )

    if has_audio and len(a_nums) >= 1 and len(v_nums) >= 1:
        v_start = _segment_start_seconds(folder, 0, v_nums[0])
        a_start = _segment_start_seconds(folder, 1, a_nums[0])
        if v_start is not None and a_start is not None:
            gap = abs(a_start - v_start)
            if gap >= _AVSYNC_WARN_SEC:
                issues.append(
                    f"Audio/video start offset {gap:.1f}s "
                    f"(video ~{v_start:.1f}s, audio ~{a_start:.1f}s)"
                )

    if len(v_nums) >= 2:
        t0 = _segment_start_seconds(folder, 0, v_nums[0])
        t1 = _segment_start_seconds(folder, 0, v_nums[1])
        if t0 is not None and t1 is not None:
            jump = t1 - t0
            if jump > _TIMELINE_JUMP_WARN_SEC:
                issues.append(f"Corrupt decode timeline jump: {jump:.0f}s between first fragments")

    needs_probe = (
        mpd_kind == "recovered"
        or not has_audio
        or len(v_nums) <= 2
        or any("timeline jump" in i for i in issues)
        or any("claims" in i for i in issues)
    )
    if needs_probe and not _ffprobe_opens(mpd_path):
        return ClipHealthReport(ClipHealth.DEAD, ["Manifest cannot be opened (unplayable)"])

    if issues:
        return ClipHealthReport(ClipHealth.DEGRADED, issues)
    return ClipHealthReport(ClipHealth.HEALTHY, [])


def _worst(reports: List[ClipHealthReport]) -> ClipHealthReport:
    if not reports:
        return ClipHealthReport(ClipHealth.DEAD, ["No playable manifest"])
    return max(reports, key=lambda r: _RANK[r.level])


def assess_clip_health(clip_path: str) -> ClipHealthReport:
    """Assess the worst health across every DASH segment folder inside clip_path."""
    segments = list(_iter_segment_dirs(clip_path))
    if segments:
        reports = [assess_segment_folder(folder, mpd, kind) for folder, mpd, kind in segments]
        return _worst(reports)

    if _has_video_chunks_anywhere(clip_path):
        return ClipHealthReport(
            ClipHealth.DEAD,
            ["Video chunks present but no playable manifest"],
        )
    return ClipHealthReport(ClipHealth.DEAD, ["Empty or unreadable folder"])
