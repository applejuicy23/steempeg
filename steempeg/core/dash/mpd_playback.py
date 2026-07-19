"""Linux/libmpv bridge for Steam DASH manifests.

Distro ffmpeg and Homebrew libmpv often ship without the DASH *demuxer*
(``ffmpeg -formats`` shows ``E dash`` only). Windows Steempeg ships a build
with ``DE dash``, so ``.mpd`` plays natively there.

On platforms where libmpv cannot open ``.mpd``, we copy-remux once into a
seekable cache file (``-c copy`` is ~instant) and play that instead.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys

from steempeg.core.rendered_media import resolve_ffmpeg_exe
from steempeg.infra.paths import get_save_directory

_log = logging.getLogger(__name__)

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def host_libmpv_needs_mpd_bridge() -> bool:
    """True when embedded libmpv is unlikely to demux Steam ``.mpd`` files."""
    # Windows release bundles a DASH-capable stack. Elsewhere assume bridge.
    return sys.platform != "win32"


def _cache_dir() -> str:
    out = os.path.join(get_save_directory(), "cache", "mpd_playback")
    os.makedirs(out, exist_ok=True)
    return out


def _cache_key(mpd_path: str) -> str:
    abs_path = os.path.abspath(mpd_path)
    try:
        st = os.stat(abs_path)
        payload = f"{abs_path}|{st.st_mtime_ns}|{st.st_size}"
    except OSError:
        payload = abs_path
    return hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:20]


def remux_mpd_for_playback(mpd_path: str) -> str:
    """Return a seekable ``.mkv`` path for *mpd_path* (cached copy-remux).

    Raises on failure so callers can surface the error.
    """
    abs_mpd = os.path.abspath(mpd_path)
    out = os.path.join(_cache_dir(), f"{_cache_key(abs_mpd)}.mkv")
    if os.path.isfile(out) and os.path.getsize(out) > 1024:
        return out

    # Keep the Qt UI alive during the (usually sub-second) remux.
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:
        pass

    ffmpeg = resolve_ffmpeg_exe()
    if not os.path.isfile(ffmpeg) and ffmpeg == "ffmpeg":
        # still allow PATH lookup
        pass

    tmp = out + ".tmp.mkv"
    try:
        if os.path.isfile(tmp):
            os.remove(tmp)
    except OSError:
        pass

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        abs_mpd,
        "-map",
        "0",
        "-c",
        "copy",
        tmp,
    ]
    _log.info("MPD playback remux: %s -> %s", abs_mpd, out)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        creationflags=_NO_WINDOW,
        cwd=os.path.dirname(abs_mpd) or None,
    )
    if proc.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 1024:
        err = (proc.stderr or proc.stdout or "").strip() or f"rc={proc.returncode}"
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(f"DASH remux failed (need ffmpeg with dash demux): {err}")

    os.replace(tmp, out)
    return out


def resolve_playback_media_path(media_path: str) -> str:
    """Path that libmpv can open. Remuxes ``.mpd`` on Linux when needed."""
    if not media_path:
        return media_path
    if not host_libmpv_needs_mpd_bridge():
        return media_path
    if not media_path.lower().endswith(".mpd"):
        return media_path
    if not os.path.isfile(media_path):
        return media_path
    return remux_mpd_for_playback(media_path)
