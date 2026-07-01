"""Format render-queue job metadata for list/grid cards."""
from __future__ import annotations

import os
import re

from steempeg.core.dash import discovery
from steempeg.render.queue import RenderJob, RenderJobSettings


def ms_to_clock(ms: int) -> str:
    total_sec = max(0, int(ms) // 1000)
    minutes, seconds = divmod(total_sec, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def clip_duration_label(clip_path: str) -> str:
    """Human-readable duration from the clip MPD, or '' if unknown."""
    if not clip_path or not os.path.isdir(clip_path):
        return ""
    mpds = discovery.find_mpd_paths(clip_path)
    if not mpds:
        return ""
    try:
        with open(mpds[0], encoding="utf-8") as handle:
            content = handle.read()
        seconds = discovery.parse_duration_seconds(content)
        if seconds is None or seconds <= 0:
            return ""
        total = int(seconds)
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"
    except OSError:
        return ""


def format_job_trim(settings: RenderJobSettings) -> str:
    if settings.is_trim_mode and settings.trim_end_ms > settings.trim_start_ms:
        start = ms_to_clock(settings.trim_start_ms)
        end = ms_to_clock(settings.trim_end_ms)
        return f"✂ {start} → {end}"
    return "Full clip"


def format_job_preset(settings: RenderJobSettings) -> str:
    if settings.audio_only:
        fmt = (settings.audio_format or "Audio").strip()
        br = (settings.audio_bitrate_text or "").strip()
        return f"{fmt} extract" + (f" • {br}" if br else "")

    parts: list[str] = []
    quality = (settings.quality_text or "").strip()
    fps = (settings.fps_text or "").strip()
    bitrate = (settings.bitrate_text or "").strip()
    codec = (settings.codec_text or "").strip()

    is_original = "Original" in quality or (
        "Original" in bitrate and not quality
    )

    if is_original:
        parts.append("Original")
    elif quality:
        parts.append(quality.split("(")[0].strip() or quality)

    if fps:
        short_fps = fps.split("(")[0].strip()
        if "fps" not in short_fps.lower():
            short_fps = f"{short_fps} FPS"
        parts.append(short_fps)

    if bitrate and "Original" not in bitrate:
        match = re.search(r"([\d.]+)\s*Mbps", bitrate)
        if match:
            parts.append(f"{match.group(1)} Mbps")
        else:
            chunk = bitrate.split("-")[0].strip()
            if chunk:
                parts.append(chunk)
    elif not is_original and "Original" in bitrate:
        parts.append("Original")

    if codec:
        if "H.265" in codec or "HEVC" in codec.upper():
            codec_short = "H.265"
        elif "H.264" in codec:
            codec_short = "H.264"
        else:
            codec_short = codec.split()[0] if codec else ""
        if codec_short and codec_short not in " ".join(parts):
            parts.append(codec_short)

    return " • ".join(parts) if parts else "—"


def format_job_datetime_line(job: RenderJob) -> str:
    """Date, clock time, and clip duration on one line (queue card row 2)."""
    date_line = (job.clip_date or "").replace("\n", " ").strip()
    time_str = (job.clip_time or "").strip()
    duration = clip_duration_label(job.clip_path)

    parts: list[str] = []
    if date_line:
        parts.append(date_line)
    if time_str and time_str not in date_line and time_str != duration:
        parts.append(time_str)
    if duration:
        joined = " • ".join(parts)
        if duration not in joined:
            parts.append(duration)
    return " • ".join(parts) if parts else "—"


def format_job_meta_line(job: RenderJob) -> str:
    """Alias kept for list cards — same as datetime line."""
    return format_job_datetime_line(job)


def format_job_output(job: RenderJob) -> str:
    path = (job.output_file or "").strip()
    if not path and job.settings.save_dir:
        base = (job.settings.output_basename or "rendered").strip()
        path = os.path.join(job.settings.save_dir, base)
    if path:
        return f"→ {path}"
    return "→ (output not set)"
