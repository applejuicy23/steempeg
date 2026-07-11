"""Parse fps / audio bitrate out of a Steam session.mpd via ffprobe.

Pure helpers - no Qt. They call ffprobe by name and rely on it being on PATH
(the app prepends ./bin to PATH at startup), with safe fallbacks on any error.
"""
import glob
import os
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


def _video_segment_bytes(folder_path: str) -> int:
    """Total bytes of stream0 (video) init + chunks on disk."""
    total = 0
    init = os.path.join(folder_path, "init-stream0.m4s")
    if os.path.isfile(init):
        total += os.path.getsize(init)
    for chunk in glob.glob(os.path.join(folder_path, "chunk-stream0-*.m4s")):
        try:
            if os.path.getsize(chunk) > 0:
                total += os.path.getsize(chunk)
        except OSError:
            pass
    return total


def estimate_video_bitrate_mbps(folder_path: str, duration_sec: float) -> float:
    """Average video Mbps from recorded segment bytes — matches what was actually written."""
    if duration_sec <= 0:
        return 0.0
    nbytes = _video_segment_bytes(folder_path)
    if nbytes < 1000:
        return 0.0
    return (nbytes * 8.0) / duration_sec / 1_000_000.0


def get_video_bitrate_mbps(mpd_path, default=0.0):
    """Return source video bitrate in Mbps from an .mpd, or ``default`` on failure."""
    folder = os.path.dirname(os.path.abspath(mpd_path))
    content = None
    try:
        with open(mpd_path, encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        pass

    duration = parse_duration_seconds(content) if content else None
    if duration and duration > 0:
        measured = estimate_video_bitrate_mbps(folder, duration)
        if measured > 0.1:
            return measured

    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=bit_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", mpd_path],
            creationflags=_NO_WINDOW, stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if out.isdigit() and int(out) > 0:
            if duration and duration > 0:
                measured = estimate_video_bitrate_mbps(folder, duration)
                if measured > 0.1:
                    return measured
            return int(out) / 1_000_000.0
    except Exception:
        pass

    if content:
        bws = _video_bandwidths_from_content(content)
        if bws:
            manifest_mbps = max(bws) / 1_000_000.0
            if duration and duration > 0:
                measured = estimate_video_bitrate_mbps(folder, duration)
                if measured > 0.1:
                    return min(manifest_mbps, measured)
            return manifest_mbps

    # Legacy manifests without mimeType on Representation — highest rep wins.
    if content:
        all_bws = [int(b) for b in re.findall(r'\bbandwidth="(\d+)"', content)]
        if all_bws:
            manifest_mbps = max(all_bws) / 1_000_000.0
            if duration and duration > 0:
                measured = estimate_video_bitrate_mbps(folder, duration)
                if measured > 0.1:
                    return min(manifest_mbps, measured)
            return manifest_mbps

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


def estimate_render_duration_sec(mpd_path: str, *, trim_duration_sec: float = -1.0) -> float:
    """Best-effort output duration for render progress (seconds).

    Steam manifests often lie (corrupt decode timeline → ffmpeg ``Duration:`` of
    10–15 min for a 2 min clip). Prefer counting surviving video chunks on disk.
    """
    if trim_duration_sec > 0:
        return trim_duration_sec

    folder = os.path.dirname(os.path.abspath(mpd_path))
    chunk_count = 0
    for chunk in glob.glob(os.path.join(folder, "chunk-stream0-*.m4s")):
        try:
            if os.path.getsize(chunk) > 0:
                chunk_count += 1
        except OSError:
            pass

    from steempeg.core.dash.repair import _CHUNK_SECONDS

    if chunk_count > 0:
        return chunk_count * _CHUNK_SECONDS

    try:
        with open(mpd_path, encoding="utf-8") as handle:
            declared = parse_duration_seconds(handle.read())
        if declared and declared > 0:
            return declared
    except OSError:
        pass
    return 0.0