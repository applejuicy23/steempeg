"""Constant-quality size probe — encode a few short slices, measure the bitrate.

CRF / CQ output size depends on the picture, so it cannot be computed from the
settings. Instead encode ``SAMPLE_COUNT`` slices spread over the clip with the
real render flags and extrapolate. Pure logic + subprocess — no Qt.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from typing import Callable

from steempeg.render import pro_encoding as pro
from steempeg.render.encode_speed import video_encoder_extra_args
from steempeg.render.queue import ResolvedRenderParams

SAMPLE_SEC = 2.0
SAMPLE_COUNT = 3
_SAMPLE_SPOTS = (0.15, 0.5, 0.85)


def sample_windows(start_sec: float, length_sec: float) -> list[tuple[float, float]]:
    """``(seek, duration)`` slices spread over ``[start, start + length]``."""
    if length_sec <= 0:
        return []
    dur = min(SAMPLE_SEC, length_sec / SAMPLE_COUNT)
    if dur < 0.2:
        return [(max(0.0, start_sec), length_sec)]
    out: list[tuple[float, float]] = []
    for spot in _SAMPLE_SPOTS[:SAMPLE_COUNT]:
        seek = start_sec + max(0.0, min(length_sec - dur, length_sec * spot - dur / 2))
        out.append((seek, dur))
    return out


def sample_args(
    params: ResolvedRenderParams, mpd: str, seek: float, dur: float, out_path: str
) -> list[str]:
    """Video-only encode of one slice with the job's real rate / preset / pixel flags."""
    enc = params.selected_encoder
    flags = (
        pro.preset_args(enc, params.preset)
        or video_encoder_extra_args(enc, params.encode_speed)
    )
    flags += pro.tune_args(enc, params.tune) + pro.keyint_args(params.keyint_frames)
    flags += pro.constant_quality_args(enc, params.quality_value)
    if params.ten_bit:
        flags += pro.ten_bit_args(enc)
    args = [
        params.ffmpeg_exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-fflags", "+igndts",
        "-ss", f"{seek:.3f}", "-t", f"{dur:.3f}",
        "-i", mpd.replace("\\", "/"),
    ]
    match = re.match(r"^(\d+)p", params.quality_text or "")
    if match:
        args += ["-vf", f"scale=-2:{match.group(1)}"]
    if "Original" not in (params.fps_text or ""):
        fps = re.search(r"(\d+)", params.fps_text or "")
        if fps:
            args += ["-r", fps.group(1)]
    args += ["-c:v", enc, *flags.split(), "-an", "-f", "matroska", "-y", out_path]
    return args


def measure_video_mbps(
    params: ResolvedRenderParams,
    mpd: str,
    start_sec: float,
    length_sec: float,
    *,
    on_process: Callable[[subprocess.Popen | None], None] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> float | None:
    """Average video Mbps over the sample slices; ``None`` on failure / cancel."""
    windows = sample_windows(start_sec, length_sec)
    if not windows:
        return None
    flags = 0x08000000 if sys.platform == "win32" else 0
    total_bytes = 0
    total_sec = 0.0
    with tempfile.TemporaryDirectory(prefix="steempeg_cq_") as tmp:
        for i, (seek, dur) in enumerate(windows):
            if cancelled():
                return None
            out = os.path.join(tmp, f"slice_{i}.mkv")
            try:
                proc = subprocess.Popen(
                    sample_args(params, mpd, seek, dur, out),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                )
            except OSError:
                return None
            if on_process:
                on_process(proc)
            try:
                code = proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                proc.kill()
                return None
            finally:
                if on_process:
                    on_process(None)
            if code != 0 or cancelled() or not os.path.exists(out):
                return None
            total_bytes += os.path.getsize(out)
            total_sec += dur
    if total_sec <= 0 or total_bytes <= 0:
        return None
    return total_bytes * 8 / total_sec / 1_000_000
