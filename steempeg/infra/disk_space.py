"""Linux DASH-remux disk checks (no Qt).

Windows plays Steam ``.mpd`` natively, so these guards are Linux / Steam Deck only.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass

WARN_FREE_BYTES = 2 * 1024**3
# Nearly-full large volumes can still have >2 GiB free (Emily's /var/home ~5.9 GiB
# at 95%). Cap so a 1 TB disk at 95% with tens of GiB free does not nag.
WARN_USED_RATIO = 0.95
WARN_USED_RATIO_MAX_FREE = 8 * 1024**3
REMUX_MARGIN_BYTES = 1 * 1024**3


def is_linux_disk_guard_enabled() -> bool:
    return sys.platform != "win32"


def _existing_path(path: str) -> str:
    p = os.path.abspath(path or ".")
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p if os.path.exists(p) else os.path.abspath(".")


def cache_volume_path() -> str:
    """Directory on the volume that holds ``cache/mpd_playback`` remux files."""
    from steempeg.infra.paths import get_save_directory

    root = get_save_directory()
    cache = os.path.join(root, "cache")
    mpd = os.path.join(cache, "mpd_playback")
    for candidate in (mpd, cache, root):
        if os.path.exists(candidate):
            return candidate
    return root


def free_bytes(path: str | None = None) -> int:
    """User-available bytes on the volume that contains *path* (0 on error)."""
    try:
        usage = shutil.disk_usage(_existing_path(path or cache_volume_path()))
        return int(usage.free)
    except OSError:
        return 0


def format_gib(n: int) -> str:
    return f"{max(0, n) / (1024**3):.1f} GiB"


@dataclass(frozen=True)
class DiskSpaceStatus:
    path: str
    total: int
    used: int
    free: int
    need_bytes: int = 0

    @property
    def low_free(self) -> bool:
        return self.free < WARN_FREE_BYTES

    @property
    def volume_nearly_full(self) -> bool:
        if self.total <= 0:
            return False
        used_ratio = self.used / self.total
        return used_ratio >= WARN_USED_RATIO and self.free < WARN_USED_RATIO_MAX_FREE

    @property
    def remux_tight(self) -> bool:
        return self.need_bytes > 0 and self.free < self.need_bytes + REMUX_MARGIN_BYTES

    @property
    def remux_cannot_fit(self) -> bool:
        return self.need_bytes > 0 and self.free < self.need_bytes

    @property
    def should_warn(self) -> bool:
        return self.low_free or self.volume_nearly_full or self.remux_tight


def probe_cache_volume(need_bytes: int = 0) -> DiskSpaceStatus:
    path = cache_volume_path()
    try:
        usage = shutil.disk_usage(_existing_path(path))
        total, used, free = int(usage.total), int(usage.used), int(usage.free)
    except OSError:
        total, used, free = 0, 0, 0
    return DiskSpaceStatus(
        path=path,
        total=total,
        used=used,
        free=free,
        need_bytes=max(0, int(need_bytes or 0)),
    )


def should_skip_linux_remux_prefetch(need_bytes: int = 0) -> bool:
    """True when a background remux would fight a low / full cache volume."""
    if not is_linux_disk_guard_enabled():
        return False
    status = probe_cache_volume(need_bytes)
    return status.should_warn or status.remux_cannot_fit


def looks_like_disk_full_error(exc_or_text: object) -> bool:
    text = str(exc_or_text or "").lower()
    return any(
        token in text
        for token in (
            "not enough disk space",
            "disk full",
            "no space left",
            "enospc",
        )
    )
