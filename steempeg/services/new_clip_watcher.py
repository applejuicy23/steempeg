"""Watch library roots for Steam clips saved while Steempeg is running.

Steam saves a clip as a ``clip_<appid>_<date>`` folder and fills it in several
writes (chunks, ``session.mpd``, ``clip.pb``, ``thumbnail.jpg``). A clip is
announced only after its manifest exists and the folder has stopped changing
for ``SETTLE_SEC`` — otherwise the popup would open a half-written clip.

Only ``clip_`` folders count: ``bg_`` is the always-growing background
recording and ``fg_`` lives inside clip packages.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from steempeg.core.dash.discovery import find_mpd_paths, parse_duration_seconds

_log = logging.getLogger(__name__)

SETTLE_SEC = 3.0
POLL_MS = 1000
# A clip that never settles (Steam crashed mid-save) stops being polled.
GIVE_UP_SEC = 180.0
_CLIP_PREFIX = "clip_"


def list_clip_containers(library_root: str) -> list[str]:
    """Returns the folders under a library root where Steam drops clip folders."""
    if not library_root or not os.path.isdir(library_root):
        return []
    base = os.path.normpath(library_root)
    if os.path.basename(base).lower() == "clips":
        parent = os.path.dirname(base)
        if os.path.basename(parent).lower() == "gamerecordings":
            base = parent
    containers = [base]
    for sub in ("clips", "video"):
        sub_path = os.path.join(base, sub)
        if os.path.isdir(sub_path):
            containers.append(sub_path)
    return containers


def list_clip_folders(container: str) -> dict[str, str]:
    """Maps a case-folded key to the real path of every ``clip_*`` folder in a container."""
    found: dict[str, str] = {}
    try:
        with os.scandir(container) as entries:
            for entry in entries:
                if not entry.name.lower().startswith(_CLIP_PREFIX):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    path = os.path.normpath(entry.path)
                    found[os.path.normcase(path)] = path
    except OSError:
        pass
    return found


def read_clip_fingerprint(clip_path: str) -> tuple | None:
    """Sums file count, total size and newest mtime of a clip folder, or None if unreadable."""
    count = 0
    total = 0
    newest = 0.0
    try:
        for dirpath, _dirs, files in os.walk(clip_path):
            for name in files:
                try:
                    st = os.stat(os.path.join(dirpath, name))
                except OSError:
                    continue
                count += 1
                total += st.st_size
                newest = max(newest, st.st_mtime)
    except OSError:
        return None
    return count, total, newest


def clip_is_complete(clip_path: str) -> bool:
    """Checks that Steam has written the clip descriptor and a playable manifest."""
    if not os.path.isfile(os.path.join(clip_path, "clip.pb")):
        return False
    return bool(find_mpd_paths(clip_path))


@dataclass(frozen=True)
class NewClipInfo:
    """What the «New clip» popup shows about a freshly saved clip."""

    path: str
    app_id: str
    game_name: str
    icon_path: str
    thumbnail_path: str
    duration_sec: float | None


def read_clip_duration_sec(clip_path: str) -> float | None:
    """Reads the clip length from its first manifest, or None when it has none."""
    for mpd in find_mpd_paths(clip_path):
        try:
            with open(mpd, encoding="utf-8", errors="replace") as handle:
                seconds = parse_duration_seconds(handle.read())
        except OSError:
            continue
        if seconds:
            return float(seconds)
    return None


def describe_new_clip(
    clip_path: str,
    game_names_cache: dict[str, str] | None,
    cache_dir: str,
) -> NewClipInfo:
    """Collects game name, icon, thumbnail and duration for a clip folder.

    Uses only cached / local data so the popup never waits on the network.
    """
    parts = os.path.basename(clip_path).split("_")
    app_id = parts[1] if len(parts) >= 2 and parts[1].isdigit() else ""
    game_name = ""
    if app_id:
        game_name = (game_names_cache or {}).get(app_id, "")
        if not game_name:
            from steempeg.core.games import find_local_steam_game_name

            game_name = find_local_steam_game_name(app_id) or ""
    from steempeg.core.clip_thumbnails import find_clip_thumbnail

    icon_path = os.path.join(cache_dir, f"{app_id}.jpg") if app_id else ""
    return NewClipInfo(
        path=clip_path,
        app_id=app_id,
        game_name=game_name or (f"App {app_id}" if app_id else "Steam clip"),
        icon_path=icon_path if icon_path and os.path.isfile(icon_path) else "",
        thumbnail_path=find_clip_thumbnail(clip_path),
        duration_sec=read_clip_duration_sec(clip_path),
    )


class NewClipWatcher(QObject):
    """Emits ``new_clip_ready(path)`` once per clip saved after ``start()``."""

    new_clip_ready = Signal(str)

    def __init__(self, parent: QObject | None = None):
        """Creates an idle watcher; nothing is watched until ``start()``."""
        super().__init__(parent)
        self._fs = QFileSystemWatcher(self)
        self._fs.directoryChanged.connect(self._on_container_changed)
        self._known: set[str] = set()
        self._pending: dict[str, dict] = {}
        self._paused = False
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._check_pending)

    def start(self, library_roots: list[str]) -> None:
        """Snapshots existing clips and starts watching every container of the given roots."""
        self.stop()
        containers: list[str] = []
        for root in library_roots or []:
            for container in list_clip_containers(root):
                if container not in containers:
                    containers.append(container)
        for container in containers:
            self._known |= set(list_clip_folders(container))
        if containers:
            self._fs.addPaths(containers)
        _log.info(
            "New-clip watcher: %d container(s), %d known clip(s)",
            len(containers),
            len(self._known),
        )

    def stop(self) -> None:
        """Stops watching and forgets known and pending clips."""
        watched = self._fs.directories()
        if watched:
            self._fs.removePaths(watched)
        self._poll.stop()
        self._known.clear()
        self._pending.clear()

    def watched_containers(self) -> list[str]:
        """Returns the folders currently being watched."""
        return list(self._fs.directories())

    def is_paused(self) -> bool:
        """Tells whether new clips are currently being ignored."""
        return self._paused

    def set_paused(self, paused: bool) -> None:
        """Pauses or resumes announcements; clips saved while paused stay silent forever."""
        self._paused = bool(paused)
        if self._paused:
            self._pending.clear()
            self._poll.stop()
        _log.info("New-clip watcher: %s", "paused" if self._paused else "resumed")

    def _on_container_changed(self, container: str) -> None:
        """Queues clip folders that appeared in a container since the last look."""
        now = time.monotonic()
        for key, path in list_clip_folders(container).items():
            if key in self._known:
                continue
            self._known.add(key)
            if self._paused:
                continue
            self._pending[path] = {"since": now, "print": None, "stable_at": now}
            _log.info("New-clip watcher: saw %s, waiting for Steam to finish", path)
        if self._pending and not self._poll.isActive():
            self._poll.start()

    def _check_pending(self) -> None:
        """Announces pending clips that are complete and unchanged for ``SETTLE_SEC``."""
        now = time.monotonic()
        for clip, state in list(self._pending.items()):
            if not os.path.isdir(clip):
                self._pending.pop(clip, None)
                continue
            if now - state["since"] > GIVE_UP_SEC:
                _log.warning("New-clip watcher: %s never settled, skipping", clip)
                self._pending.pop(clip, None)
                continue
            fingerprint = read_clip_fingerprint(clip)
            if fingerprint != state["print"]:
                state["print"] = fingerprint
                state["stable_at"] = now
                continue
            if now - state["stable_at"] < SETTLE_SEC:
                continue
            if not clip_is_complete(clip):
                continue
            self._pending.pop(clip, None)
            _log.info("New-clip watcher: %s is ready", clip)
            self.new_clip_ready.emit(clip)
        if not self._pending:
            self._poll.stop()
