"""Linux remux bridge for Steam DASH manifests.

Distro/Homebrew libmpv lack DASH demux (``E dash`` only — mux, no read).
Windows Steempeg ships ``DE dash`` and plays ``.mpd`` natively.

On Linux we copy-remux once into ``cache/mpd_playback/*.mkv`` via the bundled
ffmpeg (BtbN, has demux). Cache hits are instant; cold remux is multi-second
for large clips.

Cache is capped (default 8 GiB, ``STEEMPEG_MPD_CACHE_GB``). Disable remux with
``STEEMPEG_MPD_REMUX=0`` (playback will fail on brew/distro libmpv).
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import threading

from steempeg.core.rendered_media import resolve_ffmpeg_exe
from steempeg.infra.paths import get_save_directory

_log = logging.getLogger(__name__)

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_remux_locks: dict[str, threading.Lock] = {}
_remux_locks_guard = threading.Lock()
_active_jobs: dict[str, "RemuxJob"] = {}
_active_jobs_guard = threading.Lock()
_DEFAULT_CACHE_MAX_BYTES = 8 * 1024**3
_DISK_HEADROOM_BYTES = 2 * 1024**3


def _lock_for_mpd(abs_mpd: str) -> threading.Lock:
    with _remux_locks_guard:
        lock = _remux_locks.get(abs_mpd)
        if lock is None:
            lock = threading.Lock()
            _remux_locks[abs_mpd] = lock
        return lock


def host_libmpv_needs_mpd_bridge() -> bool:
    """True when Linux playback must remux ``.mpd`` before libmpv can open it."""
    if sys.platform == "win32":
        return False
    return os.environ.get("STEEMPEG_MPD_REMUX", "1").strip() != "0"


def _cache_dir() -> str:
    out = os.path.join(get_save_directory(), "cache", "mpd_playback")
    os.makedirs(out, exist_ok=True)
    return out


def _cache_key(mpd_path: str) -> str:
    """Stable key for a Steam video folder (not MPD mtime).

    ``session_fixed.mpd`` is rewritten often by repair, which used to change the
    cache key every open and force a fresh multi‑hundred‑MB remux. Key by the
    chunk folder fingerprint instead so ``session.mpd`` / ``session_fixed.mpd``
    share one cache entry.
    """
    abs_path = os.path.abspath(mpd_path)
    folder = os.path.dirname(abs_path)
    parts = [folder]
    try:
        names = sorted(
            n
            for n in os.listdir(folder)
            if n.lower().endswith((".m4s", ".mp4"))
        )
        total = 0
        for name in names:
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
        parts.append(str(len(names)))
        parts.append(str(total))
        if names:
            parts.append(names[0])
            parts.append(names[-1])
    except OSError:
        parts.append(os.path.basename(abs_path))
    payload = "|".join(parts)
    return hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:20]


def _cache_max_bytes() -> int:
    raw = (os.environ.get("STEEMPEG_MPD_CACHE_GB") or "8").strip()
    try:
        return max(1, int(float(raw))) * 1024**3
    except ValueError:
        return _DEFAULT_CACHE_MAX_BYTES


def _disk_free_bytes(path: str) -> int:
    try:
        st = os.statvfs(path)
        return int(st.f_bavail) * int(st.f_frsize)
    except OSError:
        return 0


def _estimate_remux_bytes(abs_mpd: str) -> int:
    """Rough upper bound: sum of init/chunk media next to the manifest."""
    folder = os.path.dirname(abs_mpd)
    total = 0
    try:
        for name in os.listdir(folder):
            low = name.lower()
            if not (low.endswith(".m4s") or low.endswith(".mp4")):
                continue
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
    except OSError:
        pass
    # Fallback: assume a mid-size clip if we can't see chunks.
    return total if total > 1024 * 1024 else 512 * 1024 * 1024


def _list_cache_mkv(cache_dir: str) -> list[tuple[str, int, float]]:
    """(path, size, mtime) for finished remux files (skip .tmp)."""
    out: list[tuple[str, int, float]] = []
    try:
        for name in os.listdir(cache_dir):
            if not name.endswith(".mkv") or ".tmp" in name:
                continue
            path = os.path.join(cache_dir, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_size <= 1024:
                continue
            out.append((path, int(st.st_size), float(st.st_mtime)))
    except OSError:
        pass
    return out


def _prune_playback_cache(need_bytes: int = 0) -> None:
    """Keep remux cache under the size cap and leave disk headroom for *need_bytes*."""
    cache_dir = _cache_dir()
    max_bytes = _cache_max_bytes()
    entries = _list_cache_mkv(cache_dir)
    total = sum(sz for _, sz, _ in entries)
    # Oldest first.
    entries.sort(key=lambda t: t[2])

    def _free() -> int:
        return _disk_free_bytes(cache_dir)

    target_cache = max(0, max_bytes - max(0, need_bytes))
    min_free = need_bytes + _DISK_HEADROOM_BYTES

    while entries and (total > target_cache or _free() < min_free):
        path, size, _ = entries.pop(0)
        try:
            os.remove(path)
            total -= size
            _log.info(
                "Pruned MPD remux cache: %s (%.1f GiB freed, cache now ~%.1f GiB)",
                os.path.basename(path),
                size / (1024**3),
                total / (1024**3),
            )
        except OSError as exc:
            _log.debug("Prune failed for %s: %s", path, exc)


def _prepare_remux_paths(abs_mpd: str) -> tuple[str, str, int]:
    """Return ``(out_path, tmp_path, estimated_bytes)`` after prune/space checks."""
    need = _estimate_remux_bytes(abs_mpd)
    _prune_playback_cache(need_bytes=need)
    free = _disk_free_bytes(_cache_dir())
    if free < need + _DISK_HEADROOM_BYTES:
        raise RuntimeError(
            f"Not enough disk space for DASH remux "
            f"(need ~{need / (1024**3):.1f} GiB + headroom, free {free / (1024**3):.1f} GiB). "
            f"Free space or lower STEEMPEG_MPD_CACHE_GB."
        )
    out = os.path.join(_cache_dir(), f"{_cache_key(abs_mpd)}.mkv")
    tmp = out + ".tmp.mkv"
    try:
        if os.path.isfile(tmp):
            os.remove(tmp)
    except OSError:
        pass
    return out, tmp, need


class RemuxAborted(Exception):
    """Remux was cancelled because the user switched clips."""


class RemuxJob:
    """Background ffmpeg copy-remux; play the growing ``.tmp.mkv`` as soon as it has data."""

    def __init__(self, abs_mpd: str):
        self.abs_mpd = os.path.abspath(abs_mpd)
        self.job_key = _cache_key(self.abs_mpd)
        self.out, self.tmp, self.need = _prepare_remux_paths(self.abs_mpd)
        self._aborted = False
        self._finalized_path: str | None = None
        ffmpeg = resolve_ffmpeg_exe()
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            self.abs_mpd,
            "-map",
            "0",
            "-c",
            "copy",
            self.tmp,
        ]
        _log.info(
            "MPD playback remux (live): %s -> %s (est %.1f GiB)",
            self.abs_mpd,
            self.out,
            self.need / (1024**3),
        )
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=_NO_WINDOW,
            cwd=os.path.dirname(self.abs_mpd) or None,
        )

    def bytes_written(self) -> int:
        try:
            return int(os.path.getsize(self.tmp))
        except OSError:
            try:
                return int(os.path.getsize(self.out))
            except OSError:
                return 0

    def early_play_path(self, min_bytes: int = 4 * 1024 * 1024) -> str | None:
        """Path to the growing temp file once enough bytes exist for mpv to latch on."""
        if self._finalized_path:
            return self._finalized_path
        if os.path.isfile(self.out) and os.path.getsize(self.out) >= min_bytes:
            return self.out
        if self.bytes_written() >= min_bytes and os.path.isfile(self.tmp):
            return self.tmp
        return None

    def poll(self) -> int | None:
        return self.proc.poll()

    def finalize(self) -> str:
        """Wait for ffmpeg, promote tmp → cache path. Raises on failure/abort."""
        if self._finalized_path:
            return self._finalized_path
        try:
            if self._aborted and self.proc.poll() is None:
                raise RemuxAborted()

            stderr = ""
            if self.proc.poll() is None or self.proc.returncode is None:
                try:
                    _, stderr = self.proc.communicate(timeout=None)
                except Exception:
                    try:
                        stderr = (self.proc.stderr.read() if self.proc.stderr else "") or ""
                    except Exception:
                        stderr = ""
            rc = self.proc.returncode

            if os.path.isfile(self.out) and os.path.getsize(self.out) > 1024:
                self._finalized_path = self.out
                return self.out

            if rc == 0 and os.path.isfile(self.tmp) and os.path.getsize(self.tmp) > 1024:
                os.replace(self.tmp, self.out)
                _prune_playback_cache(need_bytes=0)
                self._finalized_path = self.out
                return self.out

            if self._aborted:
                raise RemuxAborted()

            err = (stderr or "").strip() or f"rc={rc}"
            try:
                if os.path.isfile(self.tmp):
                    os.remove(self.tmp)
            except OSError:
                pass
            if "No space left" in err or "ENOSPC" in err or "-28" in err:
                _prune_playback_cache(need_bytes=self.need)
                raise RuntimeError(
                    "DASH remux failed: disk full. Free space and retry. "
                    f"ffmpeg: {err}"
                )
            raise RuntimeError(f"DASH remux failed (need ffmpeg with dash demux): {err}")
        finally:
            with _active_jobs_guard:
                if _active_jobs.get(self.job_key) is self:
                    _active_jobs.pop(self.job_key, None)

    def abort(self) -> None:
        """Cancel an in-flight remux (user switched clips)."""
        self._aborted = True
        still_running = self.proc.poll() is None
        if still_running:
            try:
                self.proc.kill()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=2)
            except Exception:
                pass

        # If ffmpeg already finished cleanly, keep the cache instead of deleting.
        if self.proc.poll() == 0 and not self._finalized_path:
            try:
                if os.path.isfile(self.tmp) and os.path.getsize(self.tmp) > 1024:
                    os.replace(self.tmp, self.out)
                    self._finalized_path = self.out
            except OSError:
                pass

        if not self._finalized_path:
            try:
                if os.path.isfile(self.tmp):
                    os.remove(self.tmp)
            except OSError:
                pass

        with _active_jobs_guard:
            if _active_jobs.get(self.job_key) is self:
                _active_jobs.pop(self.job_key, None)


def remux_mpd_for_playback(mpd_path: str) -> str:
    """Return a seekable ``.mkv`` path for *mpd_path* (cached copy-remux).

    Raises on failure so callers can surface the error.
    """
    abs_mpd = os.path.abspath(mpd_path)
    cached = existing_playback_cache(abs_mpd)
    if cached:
        return cached

    job_key = _cache_key(abs_mpd)
    with _lock_for_mpd(job_key):
        cached = existing_playback_cache(abs_mpd)
        if cached:
            return cached
        with _active_jobs_guard:
            existing = _active_jobs.get(job_key)
        if existing is not None:
            if existing.poll() is None or existing._finalized_path:
                return existing.finalize()
        job = RemuxJob(abs_mpd)
        with _active_jobs_guard:
            _active_jobs[job_key] = job
        return job.finalize()


def start_remux_job(mpd_path: str) -> RemuxJob | str:
    """Begin a cold remux without waiting.

    Returns an existing cache path (str) if already warm, otherwise a live ``RemuxJob``.
    Reuses an in-flight job for the same clip folder (prefetch / switch race).
    """
    abs_mpd = os.path.abspath(mpd_path)
    cached = existing_playback_cache(abs_mpd)
    if cached:
        return cached
    job_key = _cache_key(abs_mpd)
    with _active_jobs_guard:
        existing = _active_jobs.get(job_key)
        if existing is not None:
            if existing._finalized_path:
                return existing._finalized_path
            return existing
        job = RemuxJob(abs_mpd)
        _active_jobs[job_key] = job
        return job

def existing_playback_cache(mpd_path: str) -> str | None:
    """Return cached remux path if present, else None (no ffmpeg work)."""
    abs_mpd = os.path.abspath(mpd_path)
    out = os.path.join(_cache_dir(), f"{_cache_key(abs_mpd)}.mkv")
    if os.path.isfile(out) and os.path.getsize(out) > 1024:
        return out
    return None


def existing_playback_cache_for_play(mpd_path: str) -> str | None:
    """Cache hit for *mpd_path*, or sibling ``session.mpd`` when playing ``session_fixed``.

    Discovery prefers ``session_fixed.mpd`` (repaired manifest). Remux cache is often
    already warm for the original ``session.mpd`` from an earlier open — reuse it so
    clip switches stay instant instead of re-remuxing the fixed copy from scratch.
    """
    hit = existing_playback_cache(mpd_path)
    if hit:
        return hit
    abs_mpd = os.path.abspath(mpd_path)
    if os.path.basename(abs_mpd).lower() != "session_fixed.mpd":
        return None
    sibling = os.path.join(os.path.dirname(abs_mpd), "session.mpd")
    if not os.path.isfile(sibling):
        return None
    return existing_playback_cache(sibling)


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
    warm = existing_playback_cache_for_play(media_path)
    if warm:
        return warm
    return remux_mpd_for_playback(media_path)
