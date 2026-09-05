"""Linux remux bridge for Steam DASH manifests.

Older Homebrew / some distro libmpv stacks lack DASH demux (``E dash`` only —
mux, no read). Windows Steempeg ships ``DE dash`` and plays ``.mpd`` natively.
Bazzite/Fedora ``mpv-libs`` + matching lavf now have demux; v50 aims to open
``.mpd`` natively (live DASH like Windows) and retire this bridge.

Default through 49.x: remux into ``cache/mpd_playback/*.mkv`` via the bundled
ffmpeg (BtbN, has demux). Cache hits are instant; cold height remux is
multi-second for large clips (49.1 polish: faster preview encode + clearer UI).

Preview-quality gear (1080p / 360p / …) is keyed into the cache path. Source
uses a fast ``-c copy`` remux; lower presets scale during remux so libmpv
decodes the selected height (MPV ``vf`` alone is unreliable under Linux
hwdec / xv). Windows keeps native DASH + live ``vf`` and never enters this
bridge.

Cache is capped (default 8 GiB, ``STEEMPEG_MPD_CACHE_GB``).

``STEEMPEG_MPD_REMUX``:
  ``1`` / unset — always remux on Linux (production default through 49.x)
  ``0`` — never remux (native ``.mpd`` only; fails without demux)
  ``auto`` — experimental hybrid: native Source when lavf has demux;
             remux for height presets and when demux is missing
             (not the 49.x default; v50 goal is remux gone, not hybrid forever)
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
import threading

from steempeg.core.rendered_media import resolve_ffmpeg_exe
from steempeg.infra.logging import ffmpeg_cli_loglevel
from steempeg.infra.paths import get_save_directory

_log = logging.getLogger(__name__)

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_remux_locks: dict[str, threading.Lock] = {}
_remux_locks_guard = threading.Lock()
_active_jobs: dict[str, "RemuxJob"] = {}
_active_jobs_guard = threading.Lock()
_DEFAULT_CACHE_MAX_BYTES = 8 * 1024**3
_DISK_HEADROOM_BYTES = 2 * 1024**3
_VALID_QUALITY_IDS = frozenset({"source", "1080p", "720p", "480p", "360p"})
_dash_demux_cache: bool | None = None


def _lock_for_mpd(lock_key: str) -> threading.Lock:
    with _remux_locks_guard:
        lock = _remux_locks.get(lock_key)
        if lock is None:
            lock = threading.Lock()
            _remux_locks[lock_key] = lock
        return lock


def _remux_env_mode() -> str:
    """Return ``force``, ``off``, or ``auto`` from ``STEEMPEG_MPD_REMUX``."""
    raw = (os.environ.get("STEEMPEG_MPD_REMUX") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return "off"
    if raw in ("auto", "detect", "hybrid"):
        return "auto"
    return "force"


def _lavf_blob_has_dash_demux(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
    except OSError:
        return False
    return b"DASH seek" in blob or b"libavformat/dashdec.c" in blob


def _candidate_avformat_paths(libmpv_path: str | None) -> list[str]:
    """lavf files that libmpv is likely to load (siblings first, then ldd)."""
    out: list[str] = []
    seen: set[str] = set()

    def _add(path: str | None) -> None:
        if not path or not os.path.isfile(path):
            return
        real = os.path.realpath(path)
        if real in seen:
            return
        seen.add(real)
        out.append(real)

    if libmpv_path:
        lib_dir = os.path.dirname(os.path.abspath(libmpv_path))
        for name in (
            "libavformat.so.62",
            "libavformat.so.61",
            "libavformat.so.60",
            "libavformat.so",
        ):
            _add(os.path.join(lib_dir, name))
        try:
            for name in sorted(os.listdir(lib_dir)):
                if name.startswith("libavformat.so"):
                    _add(os.path.join(lib_dir, name))
        except OSError:
            pass
        try:
            ldd = subprocess.check_output(
                ["ldd", libmpv_path], text=True, stderr=subprocess.DEVNULL
            )
        except (OSError, subprocess.CalledProcessError):
            ldd = ""
        for line in ldd.splitlines():
            if "libavformat" not in line or "=>" not in line:
                continue
            path = line.split("=>", 1)[1].strip().split()[0]
            _add(path)

    for path in (
        "/usr/lib64/libavformat.so.62",
        "/usr/lib/libavformat.so.62",
        "/usr/lib/x86_64-linux-gnu/libavformat.so.62",
    ):
        _add(path)
    return out


def libmpv_has_dash_demux() -> bool:
    """True when the active/bundled lavf can demux Steam ``.mpd`` (dashdec)."""
    global _dash_demux_cache
    if _dash_demux_cache is not None:
        return _dash_demux_cache

    libmpv_path: str | None = None
    try:
        from steempeg.infra.libmpv_bootstrap import choose_libmpv

        libmpv_path = choose_libmpv()
    except Exception:
        libmpv_path = None

    for path in _candidate_avformat_paths(libmpv_path):
        if _lavf_blob_has_dash_demux(path):
            _dash_demux_cache = True
            _log.info("libmpv DASH demux: yes (%s)", path)
            return True

    _dash_demux_cache = False
    _log.info("libmpv DASH demux: no (libmpv=%s)", libmpv_path)
    return False


def host_libmpv_needs_mpd_bridge() -> bool:
    """True when Linux may use the remux bridge for Steam ``.mpd``.

    Remains True under ``STEEMPEG_MPD_REMUX=auto`` so quality-gear remux and
    sniper/timeline paths stay available; use ``should_remux_mpd_for_playback``
    to decide whether a given open must remux.
    """
    if sys.platform == "win32":
        return False
    return _remux_env_mode() != "off"


def should_remux_mpd_for_playback(quality_id: str | None = None) -> bool:
    """True when this open should remux ``.mpd`` before libmpv plays it."""
    if sys.platform == "win32":
        return False
    mode = _remux_env_mode()
    if mode == "off":
        return False
    if mode == "force":
        return True
    # auto / hybrid (experimental — 49.x default remains force remux)
    if not libmpv_has_dash_demux():
        return True
    return normalize_remux_quality_id(quality_id) != "source"


def normalize_remux_quality_id(quality_id: str | None) -> str:
    """Map preview-quality ids onto remux cache tags (unknown → source)."""
    q = (quality_id or "source").strip().lower()
    return q if q in _VALID_QUALITY_IDS else "source"


def max_height_for_quality(quality_id: str | None) -> int | None:
    """Pixel height cap for a remux quality tag, or None for source copy."""
    q = normalize_remux_quality_id(quality_id)
    if q == "source":
        return None
    match = re.fullmatch(r"(\d+)p", q)
    if not match:
        return None
    return int(match.group(1))


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


def _job_key(mpd_path: str, quality_id: str | None = None) -> str:
    q = normalize_remux_quality_id(quality_id)
    return f"{_cache_key(mpd_path)}|{q}"


def _cache_path(mpd_path: str, quality_id: str | None = None) -> str:
    """Finished remux path. Source keeps the legacy ``{key}.mkv`` name."""
    key = _cache_key(mpd_path)
    q = normalize_remux_quality_id(quality_id)
    if q == "source":
        name = f"{key}.mkv"
    else:
        name = f"{key}_{q}.mkv"
    return os.path.join(_cache_dir(), name)


def _cache_max_bytes() -> int:
    raw = (os.environ.get("STEEMPEG_MPD_CACHE_GB") or "8").strip()
    try:
        return max(1, int(float(raw))) * 1024**3
    except ValueError:
        return _DEFAULT_CACHE_MAX_BYTES


def _disk_free_bytes(path: str) -> int:
    from steempeg.infra.disk_space import free_bytes

    return free_bytes(path)


def estimate_remux_bytes(
    mpd_path: str, *, quality_id: str | None = None, max_height: int | None = None
) -> int:
    """Public size estimate for UI disk-space checks before a cold remux."""
    height = max_height
    if height is None:
        height = max_height_for_quality(quality_id)
    return _estimate_remux_bytes(os.path.abspath(mpd_path), max_height=height)


def remux_disk_plan(
    mpd_path: str, *, quality_id: str | None = None, max_height: int | None = None
) -> tuple[int, int]:
    """Prune remux cache for *mpd_path*, then return ``(need_bytes, free_bytes)``."""
    height = max_height
    if height is None:
        height = max_height_for_quality(quality_id)
    need = _estimate_remux_bytes(os.path.abspath(mpd_path), max_height=height)
    _prune_playback_cache(need_bytes=need)
    return need, _disk_free_bytes(_cache_dir())


def _estimate_remux_bytes(abs_mpd: str, *, max_height: int | None = None) -> int:
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
    if total < 1024 * 1024:
        total = 512 * 1024 * 1024
    if max_height and max_height > 0:
        # Scaled remux is smaller than a full copy; assume ~1440p source.
        factor = min(1.0, max(0.08, (float(max_height) / 1440.0) ** 2 * 1.25))
        return max(32 * 1024 * 1024, int(total * factor))
    return total


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


def _prepare_remux_paths(
    abs_mpd: str, *, quality_id: str | None = None, max_height: int | None = None
) -> tuple[str, str, int]:
    """Return ``(out_path, tmp_path, estimated_bytes)`` after prune/space checks."""
    height = max_height if max_height is not None else max_height_for_quality(quality_id)
    need = _estimate_remux_bytes(abs_mpd, max_height=height)
    _prune_playback_cache(need_bytes=need)
    free = _disk_free_bytes(_cache_dir())
    if free < need:
        raise RuntimeError(
            f"Not enough disk space for DASH remux "
            f"(need ~{need / (1024**3):.1f} GiB, free {free / (1024**3):.1f} GiB). "
            f"Free space or lower STEEMPEG_MPD_CACHE_GB."
        )
    out = _cache_path(abs_mpd, quality_id)
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
    """Background ffmpeg remux; play the growing ``.tmp.mkv`` as soon as it has data.

    Source quality uses stream copy. Height presets re-encode with a software
    scale so the cached file matches the player gear selection.
    """

    def __init__(
        self,
        abs_mpd: str,
        *,
        quality_id: str | None = None,
        max_height: int | None = None,
    ):
        self.abs_mpd = os.path.abspath(abs_mpd)
        self.quality_id = normalize_remux_quality_id(quality_id)
        if max_height is None:
            max_height = max_height_for_quality(self.quality_id)
        self.max_height = int(max_height) if max_height else None
        self.job_key = _job_key(self.abs_mpd, self.quality_id)
        self.out, self.tmp, self.need = _prepare_remux_paths(
            self.abs_mpd, quality_id=self.quality_id, max_height=self.max_height
        )
        self._aborted = False
        self._finalized_path: str | None = None
        ffmpeg = resolve_ffmpeg_exe()
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            ffmpeg_cli_loglevel(),
            "-y",
            "-i",
            self.abs_mpd,
        ]
        if self.max_height:
            h = int(self.max_height)
            # Preview-only encode: bias hard toward speed (49.1). Source stays
            # -c copy above. Fewer refs / no B-frames / higher CRF cut wall time
            # on 1080p cold remux without needing a usable archival encode.
            cmd.extend(
                [
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    # -2 already even-rounds width. force_original_aspect_ratio=decrease
                    # can yield odd widths (e.g. 853x480) and libx264 aborts with rc=187.
                    "-vf",
                    f"scale=-2:{h}:flags=fast_bilinear",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-tune",
                    "fastdecode",
                    "-crf",
                    "30",
                    "-threads",
                    "0",
                    "-g",
                    "48",
                    "-keyint_min",
                    "48",
                    "-x264-params",
                    "ref=1:bframes=0:me=dia:subme=0:trellis=0:weightp=0:"
                    "rc-lookahead=0:scenecut=0:aq-mode=0:mixed-refs=0:"
                    "fast-pskip=1:mbtree=0",
                    "-c:a",
                    "copy",
                ]
            )
            _log.info(
                "MPD playback remux (live, %s / %sp): %s -> %s (est %.1f GiB)",
                self.quality_id,
                h,
                self.abs_mpd,
                self.out,
                self.need / (1024**3),
            )
        else:
            cmd.extend(["-map", "0", "-c", "copy"])
            _log.info(
                "MPD playback remux (live, source copy): %s -> %s (est %.1f GiB)",
                self.abs_mpd,
                self.out,
                self.need / (1024**3),
            )
        cmd.append(self.tmp)
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


def remux_mpd_for_playback(
    mpd_path: str,
    *,
    quality_id: str | None = None,
    max_height: int | None = None,
) -> str:
    """Return a seekable ``.mkv`` path for *mpd_path* (cached remux).

    Raises on failure so callers can surface the error.
    """
    abs_mpd = os.path.abspath(mpd_path)
    qid = normalize_remux_quality_id(quality_id)
    cached = existing_playback_cache(abs_mpd, quality_id=qid)
    if cached:
        return cached

    job_key = _job_key(abs_mpd, qid)
    with _lock_for_mpd(job_key):
        cached = existing_playback_cache(abs_mpd, quality_id=qid)
        if cached:
            return cached
        with _active_jobs_guard:
            existing = _active_jobs.get(job_key)
        if existing is not None:
            if existing.poll() is None or existing._finalized_path:
                return existing.finalize()
        job = RemuxJob(abs_mpd, quality_id=qid, max_height=max_height)
        with _active_jobs_guard:
            _active_jobs[job_key] = job
        return job.finalize()


def start_remux_job(
    mpd_path: str,
    *,
    quality_id: str | None = None,
    max_height: int | None = None,
) -> RemuxJob | str:
    """Begin a cold remux without waiting.

    Returns an existing cache path (str) if already warm, otherwise a live ``RemuxJob``.
    Reuses an in-flight job for the same clip folder + quality (prefetch / switch race).
    """
    abs_mpd = os.path.abspath(mpd_path)
    qid = normalize_remux_quality_id(quality_id)
    cached = existing_playback_cache(abs_mpd, quality_id=qid)
    if cached:
        return cached
    job_key = _job_key(abs_mpd, qid)
    with _active_jobs_guard:
        existing = _active_jobs.get(job_key)
        if existing is not None:
            if existing._finalized_path:
                return existing._finalized_path
            return existing
        job = RemuxJob(abs_mpd, quality_id=qid, max_height=max_height)
        _active_jobs[job_key] = job
        return job


def existing_playback_cache(
    mpd_path: str, *, quality_id: str | None = None
) -> str | None:
    """Return cached remux path if present, else None (no ffmpeg work)."""
    abs_mpd = os.path.abspath(mpd_path)
    out = _cache_path(abs_mpd, quality_id)
    if os.path.isfile(out) and os.path.getsize(out) > 1024:
        return out
    return None


def existing_playback_cache_for_play(
    mpd_path: str, *, quality_id: str | None = None
) -> str | None:
    """Cache hit for *mpd_path*, or sibling ``session.mpd`` when playing ``session_fixed``.

    Discovery prefers ``session_fixed.mpd`` (repaired manifest). Remux cache is often
    already warm for the original ``session.mpd`` from an earlier open — reuse it so
    clip switches stay instant instead of re-remuxing the fixed copy from scratch.
    """
    hit = existing_playback_cache(mpd_path, quality_id=quality_id)
    if hit:
        return hit
    abs_mpd = os.path.abspath(mpd_path)
    if os.path.basename(abs_mpd).lower() != "session_fixed.mpd":
        return None
    sibling = os.path.join(os.path.dirname(abs_mpd), "session.mpd")
    if not os.path.isfile(sibling):
        return None
    return existing_playback_cache(sibling, quality_id=quality_id)


def resolve_playback_media_path(
    media_path: str, *, quality_id: str | None = None
) -> str:
    """Path that libmpv can open. Remuxes ``.mpd`` on Linux when needed."""
    if not media_path:
        return media_path
    if not should_remux_mpd_for_playback(quality_id):
        return media_path
    if not media_path.lower().endswith(".mpd"):
        return media_path
    if not os.path.isfile(media_path):
        return media_path
    warm = existing_playback_cache_for_play(media_path, quality_id=quality_id)
    if warm:
        return warm
    return remux_mpd_for_playback(media_path, quality_id=quality_id)
