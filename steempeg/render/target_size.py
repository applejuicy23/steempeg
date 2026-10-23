"""Recompute a saved Target File Size for the clip that is about to render.

The panel used to store only a bitrate. A preset or a queue job then kept that
bitrate on a clip of a different length, so the file was no longer the size
the user asked for. The requested megabytes travel with the job and this
module turns them back into a bitrate for the clip in hand.
"""
from __future__ import annotations

import os
import re

from steempeg.core.dash import discovery
from steempeg.render.bitrate import BitratePlan, plan_bitrate
from steempeg.render.output_formats import audio_needs_bitrate
from steempeg.render.queue import RenderJob, RenderJobSettings


def audio_kbps_for_saved_target(settings: RenderJobSettings) -> int:
    """Audio budget in kbps, matching the panel's Target File Size math."""
    if settings.mute_audio:
        return 0
    fmt = (settings.audio_format or "AAC").strip()
    orig = int(settings.orig_audio_kbps or 192)
    if fmt == "WAV":
        return min(1411, max(orig * 4, 384))
    if fmt == "FLAC":
        return min(960, max(orig * 3, 256))
    if not audio_needs_bitrate(fmt):
        return orig
    if "Custom" in (settings.audio_bitrate_text or "") and settings.custom_abitrate is not None:
        return max(1, min(int(settings.custom_abitrate), orig))
    match = re.search(r"(\d+)", settings.audio_bitrate_text or "")
    return int(match.group(1)) if match else orig


def _fps_for_plan(settings: RenderJobSettings) -> int:
    """FPS the size plan uses when it decides whether to downscale."""
    orig = int(settings.orig_fps or 60)
    text = settings.fps_text or ""
    if "Custom" in text and settings.custom_fps is not None:
        return max(1, min(int(settings.custom_fps), min(60, orig)))
    match = re.search(r"(\d+)", text)
    if match and "Original" not in text:
        return int(match.group(1))
    return orig


def plan_for_saved_target(
    settings: RenderJobSettings,
    duration_s: float,
    native_height: int,
) -> BitratePlan | None:
    """Bitrate plan for a stored megabyte target, or None when there is nothing to recompute.

    Lossless ignores the stored megabytes and uses this clip's own size.
    A custom target is clamped to the new clip, same as typing it in the panel.
    """
    if settings.orig_video_mbps <= 0 or duration_s <= 0:
        return None
    audio_kbps = audio_kbps_for_saved_target(settings)
    fps = _fps_for_plan(settings)
    if settings.custom_target_lossless:
        return plan_bitrate(
            duration_s,
            settings.orig_video_mbps,
            1,
            audio_kbps,
            fps,
            is_lossless=True,
            native_height=native_height,
        )
    target_mb = int(settings.custom_target_mb or 0)
    if target_mb <= 0:
        return None
    return plan_bitrate(
        duration_s,
        settings.orig_video_mbps,
        target_mb,
        audio_kbps,
        fps,
        is_custom=True,
        native_height=native_height,
    )


def _clip_duration_and_height(job: RenderJob) -> tuple[float, int]:
    """Seconds to encode and the tallest video height declared in the manifests."""
    settings = job.settings
    if settings.is_trim_mode and settings.trim_end_ms > settings.trim_start_ms:
        duration = (settings.trim_end_ms - settings.trim_start_ms) / 1000.0
    else:
        duration = 0.0
    height = 0
    salvage = [path for path in (getattr(job, "salvage_mpds", []) or []) if os.path.isfile(path)]
    manifests = salvage or discovery.find_mpd_paths(job.clip_path)
    for path in manifests:
        try:
            with open(path, encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            continue
        if duration <= 0:
            seconds = discovery.parse_duration_seconds(content)
            if seconds is not None and seconds > 0:
                duration = float(seconds)
        for match in re.finditer(r'\bheight="(\d+)"', content):
            height = max(height, int(match.group(1)))
    return duration, height


def retarget_job_file_size(job: RenderJob) -> None:
    """Write a fresh bitrate when this job asks for a file size rather than a bitrate.

    Older jobs have no megabyte target. Their stored bitrate is left as-is.
    """
    settings = job.settings
    if "Target File Size" not in (settings.quality_text or ""):
        return
    if not settings.custom_target_lossless and int(settings.custom_target_mb or 0) <= 0:
        return
    duration, height = _clip_duration_and_height(job)
    plan = plan_for_saved_target(settings, duration, height)
    if plan is None:
        return
    settings.custom_target_bitrate = plan.video_kbps
    settings.custom_target_height = plan.height
