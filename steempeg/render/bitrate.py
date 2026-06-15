"""Bitrate math for size-targeted exports (e.g. fitting a clip under an upload limit).

Pure functions only - no Qt, no widgets. The UI reads values from the controls,
calls plan_bitrate(), and shows the result. This is the "ironclad" math that keeps
FFmpeg from overshooting the requested size.
"""
from dataclasses import dataclass

_SAFETY = 0.96          # headroom so the real file lands under the target
_MIN_VIDEO_KBPS = 100


@dataclass
class BitratePlan:
    target_mb: int      # final size target (after clamping)
    video_kbps: int     # safe video bitrate
    height: int         # -1 = keep original height, else downscale to this
    color: str          # hex color for the UI quality label
    label: str          # human-readable quality note


def plan_bitrate(duration_s, orig_video_mbps, target_mb, audio_kbps, fps,
                 is_lossless=False, is_custom=False):
    """Pick a safe video bitrate (and downscale) to fit `target_mb`.

    Returns a BitratePlan, or None if duration is unusable.
    orig_video_mbps: source video bitrate in Mbps. audio_kbps and result are in kbps.
    """
    if duration_s <= 0:
        return None

    orig_mb = max(1, int(orig_video_mbps * duration_s / 8))

    # Clamp the requested size to the chosen mode.
    if is_custom:
        target_mb = max(1, min(target_mb, orig_mb))
    elif is_lossless:
        target_mb = orig_mb

    # Budget the whole file, reserve room for audio, keep a safety margin.
    video_kbps = int(target_mb * 8192 / duration_s * _SAFETY - audio_kbps)

    # Never exceed the source bitrate; if we cap it, shrink the MB to match reality.
    max_kbps = int(orig_video_mbps * 1000)
    if video_kbps > max_kbps:
        video_kbps = max_kbps
        target_mb = max(1, int((video_kbps + audio_kbps) / _SAFETY * duration_s / 8192))

    video_kbps = max(video_kbps, _MIN_VIDEO_KBPS)

    # Lower fps can spend fewer bits for the same perceived quality.
    effective = video_kbps
    if fps <= 30:
        effective *= 1.5
    if fps <= 15:
        effective *= 2.0

    # Quality tier / auto-downscale.
    if is_lossless:
        height, color, label = -1, "#00ff00", "Lossless (Quality as original)"
    elif effective >= 10000:
        height, color, label = -1, "#00ff00", "1080p+ (Good)"
    elif effective >= 5000:
        height, color, label = 720, "#aaff00", "720p (Mid, but good)"
    elif effective >= 2000:
        height, color, label = 480, "#ffff00", "Auto-scaled to 480p to save pixels"
    elif effective >= 800:
        height, color, label = 360, "#ff8800", "Auto-scaled to 360p to save pixels"
    else:
        height, color, label = 240, "#ff4444", "Auto-scaled to 240p (VHS Quality)"

    return BitratePlan(target_mb, video_kbps, height, color, label)