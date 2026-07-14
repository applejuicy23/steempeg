"""Export containers, codecs, presets, and FFmpeg argument helpers.

Pure logic — no Qt. Uses only encoders that ship with stock FFmpeg (no libfdk_aac).
"""
from __future__ import annotations

from typing import Optional

from steempeg.render.encode_speed import video_encoder_extra_args  # noqa: F401 — re-export

CONTAINERS = ("MP4", "MKV", "MOV", "WebM")

VIDEO_CODEC_ITEMS = (
    "H.264 (AVC)",
    "H.265 (HEVC)",
    "AV1",
    "VP9",
)

AUDIO_FORMATS = (
    "AAC",
    "MP3",
    "Opus",
    "FLAC",
    "WAV",
    "Copy",
)

OUTPUT_PRESETS = {
    "Share": {
        "container": "MP4",
        "codec": "H.264 (AVC)",
        "audio": "AAC",
    },
    "Edit": {
        "container": "MKV",
        "codec": "H.265 (HEVC)",
        "audio": "FLAC",
    },
    "Web": {
        "container": "WebM",
        "codec": "VP9",
        "audio": "Opus",
    },
}

# Strip these from user basename before appending the real extension.
KNOWN_OUTPUT_EXTENSIONS = (
    ".mp4", ".mkv", ".mov", ".webm",
    ".mp3", ".aac", ".m4a", ".wav", ".flac", ".opus", ".ogg",
)

_LOSSLESS_AUDIO = frozenset({"FLAC", "WAV", "Copy"})


def normalize_container(name: str) -> str:
    key = (name or "MP4").strip().upper()
    if key == "WEBM":
        return "WebM"
    if key in ("MP4", "MKV", "MOV"):
        return key
    return "MP4"


def output_extension(container: str, audio_only: bool, audio_format: str) -> str:
    """File extension for the final render path."""
    fmt = (audio_format or "AAC").strip()
    if audio_only:
        return {
            "MP3": ".mp3",
            "AAC": ".aac",
            "Opus": ".opus",
            "FLAC": ".flac",
            "WAV": ".wav",
            "Copy": ".m4a",
        }.get(fmt, ".aac")
    return {
        "MP4": ".mp4",
        "MKV": ".mkv",
        "MOV": ".mov",
        "WebM": ".webm",
    }.get(normalize_container(container), ".mp4")


def audio_needs_bitrate(audio_format: str) -> bool:
    return (audio_format or "").strip() not in _LOSSLESS_AUDIO


def is_valid_output_combo(
    container: str,
    codec_text: str,
    audio_format: str,
    *,
    audio_only: bool = False,
    mute_audio: bool = False,
    stream_copy: bool = False,
) -> bool:
    """Return False for container/codec/audio pairs FFmpeg cannot mux sanely."""
    if mute_audio and not audio_only:
        return True

    c = normalize_container(container)
    codec = (codec_text or "").strip()
    audio = (audio_format or "AAC").strip()

    if audio_only:
        return audio in AUDIO_FORMATS

    if stream_copy and not audio_only:
        # Original copies Steam DASH chunks (H.264 + AAC) — WebM cannot remux them.
        return c != "WebM"

    if audio == "Copy":
        return True

    if c == "MP4":
        if "VP9" in codec:
            return False
        if audio in ("Opus", "FLAC", "WAV"):
            return False
        return True

    if c == "WebM":
        if "H.264" in codec or "H.265" in codec or "HEVC" in codec.upper():
            return False
        if audio in ("AAC", "MP3", "FLAC", "WAV"):
            return False
        return True

    # MKV / MOV — permissive
    return True


def resolve_video_encoder(codec_text: str, base_encoder: str, available_av1: bool = True) -> str:
    """Map UI video codec + hardware encoder pick to ffmpeg -c:v name."""
    base = str(base_encoder or "libx264")
    codec = (codec_text or "").strip()

    if "VP9" in codec:
        return "libvpx-vp9"

    if "AV1" in codec:
        if "nvenc" in base:
            return "av1_nvenc"
        if "amf" in base:
            return "av1_amf"
        if "qsv" in base:
            return "av1_qsv"
        return "libsvtav1" if available_av1 else "libx264"

    if "H.265" in codec or "HEVC" in codec.upper():
        return (
            base.replace("h264_nvenc", "hevc_nvenc")
            .replace("h264_amf", "hevc_amf")
            .replace("h264_qsv", "hevc_qsv")
            .replace("libx264", "libx265")
            .replace("h264", "hevc")
        )

    return (
        base.replace("hevc_nvenc", "h264_nvenc")
        .replace("hevc_amf", "h264_amf")
        .replace("hevc_qsv", "h264_qsv")
        .replace("libx265", "libx264")
        .replace("hevc", "h264")
    )


def build_audio_args(audio_format: str, audio_bitrate_kbps: str, mute_audio: bool) -> str:
    """ffmpeg audio segment for a single render pass."""
    if mute_audio:
        return "-an"

    fmt = (audio_format or "AAC").strip()
    if fmt == "Copy":
        return "-c:a copy"
    if fmt == "MP3":
        return f"-c:a libmp3lame -b:a {audio_bitrate_kbps}"
    if fmt == "Opus":
        return f"-c:a libopus -b:a {audio_bitrate_kbps}"
    if fmt == "FLAC":
        return "-c:a flac"
    if fmt == "WAV":
        return "-c:a pcm_s16le"
    # AAC default — ffmpeg built-in encoder (not libfdk_aac)
    return f"-c:a aac -b:a {audio_bitrate_kbps}"


def format_output_summary(
    container: str,
    codec_text: str,
    audio_format: str,
    *,
    audio_only: bool = False,
    mute_audio: bool = False,
) -> str:
    """Short line for queue cards / summaries."""
    c = normalize_container(container)
    codec = (codec_text or "").split()[0]
    if audio_only:
        return f"{c} • {audio_format} extract"
    if mute_audio:
        return f"{c} • {codec} • no audio"
    audio = (audio_format or "AAC").strip()
    return f"{c} • {codec} • {audio}"
