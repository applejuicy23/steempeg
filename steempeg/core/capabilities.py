"""Detect which video encoders this machine's ffmpeg actually supports.

Pure logic - no Qt. Runs tiny throwaway ffmpeg encodes to see which encoders
work here, and relies on ffmpeg being on PATH (the app prepends ./bin at startup).
"""
import subprocess
import sys

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# (display name, codec to expose, codec used to test).
# we test the HEVC variant on purpose. if that works, plain H264 is safe too.
_ENCODERS = [
    ("CPU (Software)", "libx264", "libx265"),
    ("NVENC (NVIDIA GPU)", "h264_nvenc", "hevc_nvenc"),
    ("AMF (AMD GPU)", "h264_amf", "hevc_amf"),
    ("QuickSync (Intel GPU)", "h264_qsv", "hevc_qsv"),
]


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
    cmd += ["-f", "null", "-"]
    try:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        return result.returncode == 0
    except OSError:
        return False


def detect_supported_encoders():
    """Return a list of (display_name, codec) for every encoder that works here.
    CPU is always included as a fallback."""
    supported = [(name, expose) for name, expose, test in _ENCODERS if _encoder_works(test)]
    if not supported:
        supported = [("CPU (Software)", "libx264")]
    return supported