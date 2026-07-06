"""Parse fps / audio bitrate out of a Steam session.mpd via ffprobe.

Pure helpers - no Qt. They call ffprobe by name and rely on it being on PATH
(the app prepends ./bin to PATH at startup), with safe fallbacks on any error.
"""
import subprocess
import sys
import re

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

_VIDEO_REP_BW = re.compile(
    r'<Representation\b[^>]*\bbandwidth="(\d+)"[^>]*\bmimeType="video/',
    re.IGNORECASE,
)
_VIDEO_REP_BW_ALT = re.compile(
    r'<Representation\b[^>]*\bmimeType="video/[^"]*"[^>]*\bbandwidth="(\d+)"',
    re.IGNORECASE,
)


def _video_bandwidths_from_content(content: str) -> list[int]:
    """Peak bandwidth values from video Representations only (bps)."""
    bws = [int(m.group(1)) for m in _VIDEO_REP_BW.finditer(content)]
    bws.extend(int(m.group(1)) for m in _VIDEO_REP_BW_ALT.finditer(content))
    return bws


def get_video_bitrate_mbps(mpd_path, default=0.0):
    """Return source video bitrate in Mbps from an .mpd, or ``default`` on failure."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=bit_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", mpd_path],
            creationflags=_NO_WINDOW, stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if out.isdigit() and int(out) > 0:
            return int(out) / 1_000_000.0
    except Exception:
        pass

    content = None
    try:
        with open(mpd_path, encoding="utf-8") as handle:
            content = handle.read()
        bws = _video_bandwidths_from_content(content)
        if bws:
            return max(bws) / 1_000_000.0
    except OSError:
        pass

    # Legacy manifests without mimeType on Representation — highest rep wins.
    if content:
        all_bws = [int(b) for b in re.findall(r'\bbandwidth="(\d+)"', content)]
        if all_bws:
            return max(all_bws) / 1_000_000.0

    return default


def parse_duration_seconds(mpd_content):
    """Parse clip duration in seconds from an .mpd's mediaPresentationDuration,
    or None if absent. Pure - regex only."""
    m = re.search(
        r'mediaPresentationDuration="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"',
        mpd_content,
    )
    if not m:
        return None
    hours = int(m.group(1)) if m.group(1) else 0
    minutes = int(m.group(2)) if m.group(2) else 0
    seconds = float(m.group(3)) if m.group(3) else 0.0
    return hours * 3600 + minutes * 60 + seconds