"""Steempeg PRO encode knobs — constant quality, two-pass, 10-bit, preset, tune,
keyframe interval — as ffmpeg flags.

Pure logic — no Qt. Every helper takes the resolved ``-c:v`` encoder name and
answers per encoder family. AMF / QSV are left out: their CQP / 10-bit flags
depend on the GPU generation and could not be verified.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

from steempeg.render.encode_speed import encoder_family

RATE_BITRATE = "bitrate"
RATE_QUALITY = "quality"

RATE_CONTROL_OPTIONS: tuple[tuple[str, str], ...] = (
    (RATE_BITRATE, "Bitrate"),
    (RATE_QUALITY, "Constant quality"),
)


@dataclass(frozen=True)
class QualityScale:
    """Constant-quality range for one encoder family (lower = better, bigger)."""

    flag: str
    low: int
    high: int
    default: int


_QUALITY_SCALES: dict[str, QualityScale] = {
    "x264": QualityScale("CRF", 0, 51, 20),
    "x265": QualityScale("CRF", 0, 51, 22),
    "nvenc": QualityScale("CQ", 1, 51, 23),
    "svtav1": QualityScale("CRF", 1, 63, 30),
    "vp9": QualityScale("CRF", 0, 63, 31),
}


def pro_family(encoder: str) -> str:
    """``encoder_family`` with libx265 split out (its flags differ from x264)."""
    enc = (encoder or "").lower()
    if enc == "libx265":
        return "x265"
    return encoder_family(enc)


def normalize_rate_control(value: object | None) -> str:
    return RATE_QUALITY if str(value or "").strip().lower() == RATE_QUALITY else RATE_BITRATE


def quality_scale(encoder: str) -> QualityScale | None:
    return _QUALITY_SCALES.get(pro_family(encoder))


def supports_constant_quality(encoder: str) -> bool:
    return quality_scale(encoder) is not None


def clamp_quality(encoder: str, value: int | None) -> int:
    scale = quality_scale(encoder)
    if scale is None:
        return -1
    if value is None or int(value) < 0:
        return scale.default
    return max(scale.low, min(int(value), scale.high))


_QUALITY_STEPS: tuple[tuple[int, str], ...] = (
    (-6, "Near lossless"),
    (-4, "Very high"),
    (-2, "High"),
    (0, "Balanced"),
    (3, "Smaller file"),
    (6, "Small file"),
    (10, "Tiny file"),
)


def quality_choices(encoder: str) -> list[tuple[int, str]]:
    """``(value, label)`` rows around the family default, e.g. ``CRF 20 · Balanced``."""
    scale = quality_scale(encoder)
    if scale is None:
        return []
    rows: list[tuple[int, str]] = []
    seen: set[int] = set()
    for offset, name in _QUALITY_STEPS:
        value = max(scale.low, min(scale.default + offset, scale.high))
        if value in seen:
            continue
        seen.add(value)
        rows.append((value, f"{scale.flag} {value} · {name}"))
    return rows


def constant_quality_args(encoder: str, value: int | None) -> str:
    """Rate-control flags replacing ``-b:v`` for constant quality."""
    family = pro_family(encoder)
    q = clamp_quality(encoder, value)
    if q < 0:
        return ""
    if family == "nvenc":
        return f"-rc vbr -cq {q} -b:v 0 "
    if family == "vp9":
        return f"-crf {q} -b:v 0 "
    return f"-crf {q} "


def supports_two_pass(encoder: str) -> bool:
    return pro_family(encoder) in ("x264", "x265", "vp9", "nvenc")


def two_pass_runs_twice(encoder: str) -> bool:
    """NVENC does its lookahead pass inside one run (``-multipass fullres``)."""
    return pro_family(encoder) in ("x264", "x265", "vp9")


def single_run_two_pass_args(encoder: str) -> str:
    if pro_family(encoder) == "nvenc":
        return "-multipass fullres "
    return ""


def two_pass_log_prefix(work_dir: str, part_index: int) -> str:
    return os.path.join(work_dir, f"temp_steempeg_2pass_{part_index}")


def two_pass_args(encoder: str, pass_no: int, log_prefix: str) -> str:
    """``-pass`` flags for pass 1 / 2 (x265 takes them through ``-x265-params``)."""
    path = log_prefix.replace("\\", "/")
    if pro_family(encoder) == "x265":
        # x265-params splits on ':' — escape the drive colon.
        stats = f"{path}.log".replace(":", "\\:")
        return f'-x265-params "pass={pass_no}:stats={stats}" '
    return f'-pass {pass_no} -passlogfile "{path}" '


def remove_two_pass_logs(log_prefix: str) -> None:
    for leftover in glob.glob(glob.escape(log_prefix) + "*"):
        try:
            os.remove(leftover)
        except OSError:
            pass


_TEN_BIT_ARGS: dict[str, str] = {
    "libx264": "-pix_fmt yuv420p10le -profile:v high10 ",
    "libx265": "-pix_fmt yuv420p10le -profile:v main10 ",
    "hevc_nvenc": "-pix_fmt p010le -profile:v main10 ",
    "av1_nvenc": "-pix_fmt p010le ",
    "libsvtav1": "-pix_fmt yuv420p10le ",
    "libvpx-vp9": "-pix_fmt yuv420p10le -profile:v 2 ",
}


def supports_ten_bit(encoder: str) -> bool:
    return (encoder or "").lower() in _TEN_BIT_ARGS


def ten_bit_args(encoder: str) -> str:
    return _TEN_BIT_ARGS.get((encoder or "").lower(), "")


_X26X_PRESETS = (
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow", "placebo",
)
_PRESETS: dict[str, tuple[str, ...]] = {
    "x264": _X26X_PRESETS,
    "x265": _X26X_PRESETS,
    "nvenc": ("p1", "p2", "p3", "p4", "p5", "p6", "p7"),
    "svtav1": tuple(str(n) for n in range(12, -1, -1)),
}


def preset_choices(encoder: str) -> tuple[str, ...]:
    """Native ``-preset`` values, fastest first."""
    return _PRESETS.get(pro_family(encoder), ())


def supports_preset(encoder: str) -> bool:
    return bool(preset_choices(encoder))


def preset_args(encoder: str, preset: str | None) -> str:
    """Exact preset replacing the Encode speed mapping; empty when not valid here."""
    value = (preset or "").strip()
    if value and value in preset_choices(encoder):
        return f"-preset {value} "
    return ""


_TUNES: dict[str, tuple[tuple[str, str], ...]] = {
    "x264": (
        ("film", "Film"),
        ("animation", "Animation"),
        ("grain", "Grain"),
        ("stillimage", "Still image"),
        ("fastdecode", "Fast decode"),
        ("zerolatency", "Zero latency"),
    ),
    "x265": (
        ("animation", "Animation"),
        ("grain", "Grain"),
        ("fastdecode", "Fast decode"),
        ("zerolatency", "Zero latency"),
    ),
}


def tune_choices(encoder: str) -> tuple[tuple[str, str], ...]:
    return _TUNES.get(pro_family(encoder), ())


def supports_tune(encoder: str) -> bool:
    return bool(tune_choices(encoder))


def tune_args(encoder: str, tune: str | None) -> str:
    value = (tune or "").strip()
    if value and any(key == value for key, _ in tune_choices(encoder)):
        return f"-tune {value} "
    return ""


KEYINT_CHOICES: tuple[tuple[float, str], ...] = (
    (0.0, "Auto"),
    (0.5, "Every 0.5 s"),
    (1.0, "Every 1 s"),
    (2.0, "Every 2 s"),
    (5.0, "Every 5 s"),
    (10.0, "Every 10 s"),
)


def keyint_frames(seconds: float | None, fps: float) -> int:
    """GOP length in frames for ``-g``; 0 = encoder default."""
    try:
        sec = float(seconds or 0)
    except (TypeError, ValueError):
        return 0
    if sec <= 0 or fps <= 0:
        return 0
    return max(1, int(round(sec * fps)))


def keyint_args(frames: int) -> str:
    return f"-g {int(frames)} " if frames and frames > 0 else ""


def ten_bit_note(encoder: str) -> str:
    """Compatibility caveat shown next to the 10-bit toggle."""
    if (encoder or "").lower() == "libx264":
        return "10-bit H.264 won't play in browsers, Discord or most phones."
    return "Needs a newer player / device; Discord and phones may refuse it."
