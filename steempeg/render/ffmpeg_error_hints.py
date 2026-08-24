"""Map FFmpeg / render stderr to short user-facing English hints.

Pure functions only — no Qt. The render-error dialog shows ``message``
prominently and keeps the raw log scrollable underneath.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class FFmpegErrorHint:
    """Classified render failure."""

    kind: str
    message: str


# Order matters: first match wins. Prefer concrete disk/encoder/path signals
# over vaguer memory / invalid-argument phrases that often co-occur.
_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "disk_full",
        re.compile(
            r"ENOSPC|no space left|disk quota|quota exceeded",
            re.IGNORECASE,
        ),
        "Your disk is full. Free up some space and try again.",
    ),
    (
        "gpu_out_of_memory",
        re.compile(
            r"CUDA[^\n]{0,80}out of memory|"
            r"NVENC[^\n]{0,80}out of memory|"
            r"out of memory[^\n]{0,40}(CUDA|NVENC|GPU)|"
            r"GPU[^\n]{0,40}out of memory|"
            r"nvenc[^\n]{0,60}(ENOMEM|not enough memory)",
            re.IGNORECASE,
        ),
        "Your GPU ran out of memory. Try a lower resolution or switch to a CPU encoder.",
    ),
    (
        "out_of_memory",
        re.compile(
            r"Cannot allocate memory|not enough memory|out of memory|"
            r"\bENOMEM\b|Memory allocation failed",
            re.IGNORECASE,
        ),
        "Not enough memory. Close other apps, lower resolution or bitrate, then try again.",
    ),
    (
        "encoder_not_found",
        re.compile(
            r"Unknown encoder|Encoder .+ not found|encoder not found|"
            r"No NVENC capable devices|Cannot load nvcuda|"
            r"Driver does not support the required nvenc|"
            r"OpenEncodeSessionEx failed|"
            r"Cannot create (CUDA|Vulkan) context",
            re.IGNORECASE,
        ),
        "This encoder isn't available. Update your GPU drivers or pick a different codec.",
    ),
    (
        "permission_denied",
        re.compile(
            r"Permission denied|Access is denied|\bEACCES\b|"
            r"Operation not permitted",
            re.IGNORECASE,
        ),
        "Permission denied writing the file. Check folder permissions or choose another save location.",
    ),
    (
        "no_such_file",
        re.compile(
            r"No such file or directory|cannot find the (file|path)|"
            r"The system cannot find the (file|path)|"
            r"does not exist|\bENOENT\b",
            re.IGNORECASE,
        ),
        "A file or folder was missing. The clip or output path may have moved.",
    ),
    (
        "invalid_argument",
        re.compile(
            r"Invalid argument|\bEINVAL\b|Invalid data found|"
            r"Error while opening encoder|"
            r"maybe incorrect parameters such as bit_rate",
            re.IGNORECASE,
        ),
        "FFmpeg rejected these encode settings. Try different quality, resolution, or codec options.",
    ),
)

GENERIC_HINT = FFmpegErrorHint(
    kind="generic",
    message="Render failed. Check the log below.",
)


def classify_ffmpeg_error(text: str | None) -> FFmpegErrorHint:
    """Return the best matching short hint for an FFmpeg / render error blob."""
    blob = (text or "").strip()
    if not blob:
        return GENERIC_HINT
    for kind, pattern, message in _RULES:
        if pattern.search(blob):
            return FFmpegErrorHint(kind=kind, message=message)
    return GENERIC_HINT


# Dev Mode / theme QA — one clean sample per classified kind.
_SIMULATE_SAMPLES: tuple[tuple[str, str], ...] = (
    (
        "disk_full",
        "ffmpeg version N-118201-g7f3a9c2\n"
        "[out#0/mp4 @ 000001a4f880] Error opening output "
        "C:/Records/clip_export.mp4: No space left on device\n"
        "Error opening output files: No space left on device\n"
        "Conversion failed!\n"
        "os error: ENOSPC\n",
    ),
    (
        "gpu_out_of_memory",
        "ffmpeg version N-118201-g7f3a9c2\n"
        "[h264_nvenc @ 000001a4f2c0] OpenEncodeSessionEx failed: out of memory "
        "(10)\n"
        "[h264_nvenc @ 000001a4f2c0] CUDA out of memory\n"
        "Error initializing output stream 0:0 -- Error while opening encoder\n"
        "Conversion failed!\n",
    ),
    (
        "out_of_memory",
        "ffmpeg version N-118201-g7f3a9c2\n"
        "[libx264 @ 000001a4f2c0] Error while opening encoder: Cannot allocate memory\n"
        "Error opening output files: Cannot allocate memory\n"
        "Conversion failed!\n",
    ),
    (
        "encoder_not_found",
        "ffmpeg version N-118201-g7f3a9c2\n"
        "Unknown encoder 'h264_nvenc'\n"
        "Error opening output file C:/Records/clip_export.mp4.\n"
        "Conversion failed!\n",
    ),
    (
        "permission_denied",
        "ffmpeg version N-118201-g7f3a9c2\n"
        "[out#0/mp4 @ 000001a4f880] Error opening output "
        "C:/Records/clip_export.mp4: Permission denied\n"
        "Error opening output files: Permission denied\n"
        "Conversion failed!\n",
    ),
    (
        "no_such_file",
        "ffmpeg version N-118201-g7f3a9c2\n"
        "[in#0 @ 000001a4f100] Error opening input: No such file or directory\n"
        "Error opening input file C:/Clips/missing_clip.mp4.\n"
        "Error opening input files: No such file or directory\n",
    ),
    (
        "invalid_argument",
        "ffmpeg version N-118201-g7f3a9c2\n"
        "[libx264 @ 000001a4f2c0] Error while opening encoder: Invalid argument\n"
        "Error initializing output stream 0:0 -- Error while opening encoder for "
        "output stream #0:0 - maybe incorrect parameters such as bit_rate, rate, "
        "width or height\n"
        "Conversion failed!\n",
    ),
    (
        "generic",
        "ffmpeg version N-118201-g7f3a9c2\n"
        "Input #0, mov, from 'C:/Clips/clip.mp4':\n"
        "  Duration: 00:01:12.00\n"
        "Something unexpected went wrong during encode.\n"
        "Conversion failed!\n",
    ),
)


def simulate_ffmpeg_error_samples() -> list[tuple[str, str]]:
    """``(kind, stderr_sample)`` pairs for Dev Mode dialog cycling."""
    return list(_SIMULATE_SAMPLES)


def next_simulate_sample(index: int) -> tuple[int, str, str]:
    """Return ``(next_index, kind, sample_text)`` cycling through samples."""
    samples = _SIMULATE_SAMPLES
    if not samples:
        return 0, GENERIC_HINT.kind, "Conversion failed!\n"
    i = index % len(samples)
    kind, text = samples[i]
    return (i + 1) % len(samples), kind, text
