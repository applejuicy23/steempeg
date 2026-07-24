"""Detect which video encoders this machine's ffmpeg actually supports.

Pure logic - no Qt. Runs tiny throwaway ffmpeg encodes to see which encoders
work here, and relies on ffmpeg being on PATH (the app prepends ./bin at startup).
"""
import os
import subprocess
import sys

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Hardware first — CPU is a last-resort fallback, never the preferred default.
# (display name, codec to expose in the UI, codecs to probe — any success counts).
_HW_ENCODERS = [
    ("NVENC (NVIDIA GPU)", "h264_nvenc", ("hevc_nvenc", "h264_nvenc")),
    ("AMF (AMD GPU)", "h264_amf", ("hevc_amf", "h264_amf")),
    ("QuickSync (Intel GPU)", "h264_qsv", ("hevc_qsv", "h264_qsv")),
]
_CPU_ENCODER = ("CPU (Software)", "libx264")

_OPTIONAL_VIDEO_CODECS = [
    ("AV1", ("libsvtav1", "av1_nvenc", "av1_amf", "av1_qsv")),
    ("VP9", ("libvpx-vp9",)),
]

_SOFTWARE_CODECS = frozenset({"libx264", "libx265", "libsvtav1", "libvpx-vp9"})


def _encoder_works(test_code):
    """Try encoding a single black frame with test_code. True if ffmpeg accepts it."""
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:s=640x480:r=1",
        "-frames:v", "1", "-pix_fmt", "yuv420p", "-c:v", test_code,
    ]
    if "nvenc" in test_code:
        cmd += ["-preset", "p1"]
    elif "qsv" in test_code:
        cmd += ["-preset", "veryfast"]
    elif "amf" in test_code:
        cmd += ["-quality", "speed"]
    elif test_code == "libvpx-vp9":
        cmd += ["-b:v", "1M"]
    elif test_code == "libsvtav1":
        cmd += ["-preset", "10"]
    cmd += ["-f", "null", "-"]
    try:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        return result.returncode == 0
    except OSError:
        return False


def is_software_encoder(codec: str | None) -> bool:
    """True for CPU / software encoders (never preferred when HW exists)."""
    raw = (codec or "").strip().lower()
    return not raw or raw in _SOFTWARE_CODECS or raw.startswith("lib")


def detect_supported_encoders():
    """Return ``(display_name, codec)`` rows: hardware first, CPU always last.

    Prefer NVENC / AMF / QuickSync whenever the probe succeeds. CPU is only the
    fallback — never the implied default when a GPU encoder is available.
    """
    # Opt out with STEEMPEG_PROBE_HWENC=0 if a throwaway nvenc probe misbehaves
    # with a given driver (rare). Default is on — otherwise Linux only shows CPU.
    if sys.platform != "win32" and os.environ.get("STEEMPEG_PROBE_HWENC", "1") == "0":
        return [_CPU_ENCODER]

    supported = []
    for name, expose, probes in _HW_ENCODERS:
        # Accept H.264 OR HEVC success — some drivers expose only one variant.
        if any(_encoder_works(code) for code in probes):
            supported.append((name, expose))

    # Always offer software encode as the last resort.
    supported.append(_CPU_ENCODER)
    return supported


def preferred_encoder_index(encoders: list[tuple[str, str]]) -> int:
    """Index of the first hardware encoder, or CPU if that is all we have."""
    for i, (_name, codec) in enumerate(encoders):
        if not is_software_encoder(codec):
            return i
    return 0


def detect_optional_video_codecs():
    """Return codec labels (AV1, VP9) that this ffmpeg build can encode."""
    found = []
    for label, tests in _OPTIONAL_VIDEO_CODECS:
        if any(_encoder_works(code) for code in tests):
            found.append(label)
    return found


def av1_encoder_available() -> bool:
    return any(_encoder_works(code) for code in ("libsvtav1", "av1_nvenc", "av1_amf", "av1_qsv"))
