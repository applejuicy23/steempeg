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


def _short_codec(codec_text: str) -> str:
    codec = (codec_text or "").strip()
    if not codec:
        return ""
    if "H.265" in codec or "HEVC" in codec.upper():
        return "H.265"
    if "H.264" in codec or "AVC" in codec.upper():
        return "H.264"
    if codec.startswith("AV1"):
        return "AV1"
    if codec.startswith("VP9"):
        return "VP9"
    return codec.split()[0]


def _short_preset(settings: RenderJobSettings) -> str:
    quality = (settings.quality_text or "").strip()
    if "Target File Size" in quality:
        return "Target size"
    if "Original" in quality:
        return "Original"
    match = re.match(r"^(\d+p)", quality)
    if match:
        return match.group(1)
    if quality:
        return quality.split("(")[0].strip()
    return ""


def _short_fps(settings: RenderJobSettings) -> str:
    fps = (settings.fps_text or "").strip()
    if not fps:
        return ""
    if settings.custom_fps is not None and "Custom" in fps:
        return f"{settings.custom_fps} fps"
    match = re.search(r"(\d+)", fps)
    return f"{match.group(1)} fps" if match else ""


def _short_bitrate_original(settings: RenderJobSettings) -> str:
    mbps = float(settings.orig_video_mbps or 0.0)
    if mbps > 0:
        s = f"{mbps:.1f}".rstrip("0").rstrip(".")
        return f"{s} Mbps"
    match = re.search(r"([\d.]+)\s*Mbps", settings.bitrate_text or "")
    if match:
        return f"{match.group(1)} Mbps"
    return ""


def _short_bitrate(settings: RenderJobSettings) -> str:
    bitrate = (settings.bitrate_text or "").strip()
    quality = (settings.quality_text or "").strip()
    if "Original" in quality or "Original" in bitrate:
        return ""
    if "Custom" in bitrate and settings.custom_vbitrate is not None:
        s = f"{settings.custom_vbitrate:.1f}".rstrip("0").rstrip(".")
        return f"{s} Mbps"
    match = re.search(r"([\d.]+)\s*Mbps", bitrate)
    if match:
        return f"{match.group(1)} Mbps"
    if "Target File Size" in quality and settings.custom_target_bitrate:
        mbps = settings.custom_target_bitrate / 1000
        s = f"{mbps:.1f}".rstrip("0").rstrip(".")
        return f"{s} Mbps"
    return ""


def format_job_preset(settings: RenderJobSettings) -> str:
    """One compact line for queue cards: preset · fps · bitrate · codec."""
    if settings.audio_only:
        audio = (settings.audio_format or "Audio").strip()
        br = (settings.audio_bitrate_text or "").strip()
        if br and audio not in ("FLAC", "WAV", "Copy"):
            match = re.search(r"(\d+)", br)
            br_bit = f"{match.group(1)}k" if match else br.split()[0]
            return f"{audio} only · {br_bit}"
        return f"{audio} only"

    is_original = "Original" in (settings.quality_text or "") and "Target" not in (
        settings.quality_text or ""
    )

    parts: list[str] = []
    preset = _short_preset(settings)
    if preset:
        parts.append(preset)

    fps = _short_fps(settings)
    if fps:
        parts.append(fps)

    if is_original:
        br = _short_bitrate_original(settings)
    else:
        br = _short_bitrate(settings)
    if br:
        parts.append(br)

    codec = _short_codec(settings.codec_text)
    if codec:
        parts.append(codec)

    if settings.mute_audio:
        parts.append("muted")

    return " · ".join(parts) if parts else "—"


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
        return f"📁 {path}"
    return "📁 (output not set)"
