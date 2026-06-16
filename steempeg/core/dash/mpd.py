"""Parse fps / audio bitrate out of a Steam session.mpd via ffprobe.

Pure helpers - no Qt. They call ffprobe by name and rely on it being on PATH
(the app prepends ./bin to PATH at startup), with safe fallbacks on any error.
"""
import subprocess
import sys

# CREATE_NO_WINDOW on Windows so ffprobe doesn't flash a console window.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def get_fps(mpd_path, default=60):
    """Return the video fps from an .mpd manifest, or `default` on any failure."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", mpd_path],
            creationflags=_NO_WINDOW, stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if "/" in out:
            num, den = out.split("/")
            return round(float(num) / float(den))
        if out:
            return round(float(out))
    except Exception:
        pass
    return default


def get_audio_bitrate_kbps(mpd_path, default=192):
    """Return the audio bitrate in kbps from an .mpd manifest, or `default` on failure."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=bit_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", mpd_path],
            creationflags=_NO_WINDOW, stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if out.isdigit():
            return int(out) // 1000      # bps -> kbps
    except Exception:
        pass
    return default