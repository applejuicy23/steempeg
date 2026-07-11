"""Encode speed / quality ladder — maps UI labels to ffmpeg flags per encoder family."""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_ENCODE_SPEED = "balanced"

_SPEED_IDS = frozenset({"ultrafast", "fast", "balanced", "quality", "maxquality"})


@dataclass(frozen=True)
class EncodeSpeedOption:
    id: str
    label: str


ENCODE_SPEED_OPTIONS: tuple[EncodeSpeedOption, ...] = (
    EncodeSpeedOption("ultrafast", "Ultra Fast"),
    EncodeSpeedOption("fast", "Fast"),
    EncodeSpeedOption("balanced", "Balanced"),
    EncodeSpeedOption("quality", "Quality"),
    EncodeSpeedOption("maxquality", "Max Quality"),
)


def normalize_encode_speed(speed_id: str | None) -> str:
    if speed_id in _SPEED_IDS:
        return speed_id
    return DEFAULT_ENCODE_SPEED


def encoder_family(encoder: str) -> str:
    enc = (encoder or "libx264").lower()
    if "nvenc" in enc:
        return "nvenc"
    if "amf" in enc:
        return "amf"
    if "qsv" in enc:
        return "qsv"
    if enc == "libsvtav1":
        return "svtav1"
    if enc == "libvpx-vp9":
        return "vp9"
    return "x264"


def encode_speed_hint(family: str) -> str:
    hints = {
        "nvenc": "NVENC presets p1 (fastest) → p7 (best quality)",
        "x264": "x264/x265 preset: ultrafast → veryslow",
        "svtav1": "SVT-AV1 preset: lower number = slower, better compression",
        "vp9": "VP9 deadline / cpu-used tradeoff",
        "amf": "AMD AMF quality: speed ↔ quality",
        "qsv": "Intel QuickSync preset",
    }
    return hints.get(family, "Encoder speed vs quality tradeoff")


_NVENC = {
    "ultrafast": "p1",
    "fast": "p3",
    "balanced": "p4",
    "quality": "p6",
    "maxquality": "p7",
}

_X264 = {
    "ultrafast": "ultrafast",
    "fast": "veryfast",
    "balanced": "medium",
    "quality": "slow",
    "maxquality": "veryslow",
}

_SVTAV1 = {
    "ultrafast": "12",
    "fast": "10",
    "balanced": "6",
    "quality": "4",
    "maxquality": "2",
}

_VP9 = {
    "ultrafast": ("realtime", "8"),
    "fast": ("realtime", "5"),
    "balanced": ("good", "2"),
    "quality": ("good", "1"),
    "maxquality": ("best", "0"),
}

_AMF = {
    "ultrafast": "speed",
    "fast": "speed",
    "balanced": "balanced",
    "quality": "quality",
    "maxquality": "quality",
}

_QSV = {
    "ultrafast": "veryfast",
    "fast": "faster",
    "balanced": "medium",
    "quality": "slow",
    "maxquality": "veryslow",
}


def video_encoder_extra_args(encoder: str, encode_speed: str | None = None) -> str:
    """Optional ffmpeg flags for the active encoder + speed preset."""
    speed = normalize_encode_speed(encode_speed)
    family = encoder_family(encoder)

    if family == "nvenc":
        return f"-preset {_NVENC[speed]} "
    if family == "x264":
        return f"-preset {_X264[speed]} "
    if family == "svtav1":
        return f"-preset {_SVTAV1[speed]} "
    if family == "vp9":
        deadline, cpu = _VP9[speed]
        return f"-deadline {deadline} -cpu-used {cpu} -row-mt 1 "
    if family == "amf":
        return f"-quality {_AMF[speed]} "
    if family == "qsv":
        return f"-preset {_QSV[speed]} "
    return ""
