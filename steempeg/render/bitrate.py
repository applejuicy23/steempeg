"""Bitrate math for size-targeted exports (e.g. fitting a clip under an upload limit).

Pure functions only - no Qt, no widgets. The UI reads values from the controls,
calls plan_bitrate(), and shows the result. This is the "ironclad" math that keeps
FFmpeg from overshooting the requested size.
"""
from dataclasses import dataclass

_SAFETY = 0.96          # headroom so the real file lands under the target
_MIN_VIDEO_KBPS = 100

# Reference video bitrates (Mbps) per resolution height, mirroring the app's
# Steam-style presets. These let us judge quality relative to the resolution we
# actually encode at (so 12 Mbps reads as "soft" at 1440p but "good" at 1080p),
# instead of using a flat bitrate threshold that ignores the pixel count.
_TIERS = [2160, 1440, 1080, 720, 480, 360, 260, 144]
_GOOD_MBPS = {2160: 38, 1440: 22, 1080: 12, 720: 7.5, 480: 4, 360: 2, 260: 1.0, 144: 0.3}
_MID_MBPS = {2160: 28.5, 1440: 16.5, 1080: 9, 720: 5.6, 480: 2.5, 360: 1.2, 260: 0.6, 144: 0.2}
_OK_MBPS = {2160: 19, 1440: 11, 1080: 6, 720: 3.75, 480: 1.5, 360: 0.8, 260: 0.4, 144: 0.1}


def _snap_native(height):
    """Round a raw pixel height down to the nearest known resolution tier."""
    for tier in _TIERS:
        if height >= tier:
            return tier
    return _TIERS[-1]


def estimate_quality(native_height, effective_mbps):
    """Estimate how the output will look given the source resolution.

    Picks the encode resolution (keep native, or downscale only when the bitrate
    can't even keep native watchable) and a quality tier scaled to that
    resolution. Returns (height, color, label) where height is -1 to keep the
    original resolution or a downscale target.
    """
    native = _snap_native(native_height) if native_height and native_height > 0 else 1080
    candidates = [t for t in _TIERS if t <= native]

    # Keep the highest resolution (up to native) that the bitrate can still serve
    # at a watchable level; only drop down when a resolution can't even reach the
    # "OK" bar. Retaining pixels usually beats a tiny "Good"-tier thumbnail.
    encode_h = next((t for t in candidates if effective_mbps >= _OK_MBPS[t]), candidates[-1])

    if effective_mbps >= _GOOD_MBPS[encode_h]:
        tier, color = "Good", "#00ff00"
    elif effective_mbps >= _MID_MBPS[encode_h]:
        tier, color = "Decent", "#aaff00"
    else:
        tier, color = "Soft", "#ffff00"

    if encode_h < native:
        label = f"Auto-scaled to {encode_h}p ({tier})"
        if tier == "Soft":
            color = "#ff8800"
        return encode_h, color, label
    return -1, color, f"{encode_h}p ({tier})"


@dataclass
class BitratePlan:
    target_mb: int      # final size target (after clamping)
    video_kbps: int     # safe video bitrate
    height: int         # -1 = keep original height, else downscale to this
    color: str          # hex color for the UI quality label
    label: str          # human-readable quality note


def plan_bitrate(duration_s, orig_video_mbps, target_mb, audio_kbps, fps,
                 is_lossless=False, is_custom=False, native_height=0):
    """Pick a safe video bitrate (and downscale) to fit `target_mb`.

    Returns a BitratePlan, or None if duration is unusable.
    orig_video_mbps: source video bitrate in Mbps. audio_kbps and result are in kbps.
    native_height: source resolution height (px) used to scale the quality label.
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

    # Quality tier / auto-downscale, judged against the source resolution.
    if is_lossless:
        height, color, label = -1, "#00ff00", "Lossless (Quality as original)"
    else:
        height, color, label = estimate_quality(native_height, effective / 1000.0)

    return BitratePlan(target_mb, video_kbps, height, color, label)