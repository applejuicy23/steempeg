"""Temporary, new-recording-only metadata diagnostics for the v59 investigation."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

_tracked: dict[str, float] = {}
_snapshots_started: set[str] = set()
_log = logging.getLogger(__name__)


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def track(path: str) -> None:
    _tracked.setdefault(_key(path), time.monotonic())


def trace(path: str, stage: str, **values) -> None:
    started = _tracked.get(_key(path))
    if started is None:
        return
    _log.info(
        "New clip trace: %s",
        json.dumps(dict(stage=stage, path=path,
                        elapsed_ms=round((time.monotonic() - started) * 1000, 1),
                        **values), ensure_ascii=True, default=str),
    )


def start_file_snapshots(path: str) -> None:
    """Read local source metadata in a daemon; never touch Qt or modify files."""
    track(path)
    key = _key(path)
    if key in _snapshots_started:
        return
    _snapshots_started.add(key)

    def run():
        from steempeg.core.dash.discovery import find_mpd_paths
        from steempeg.library.scan import clip_folder_recorded_at

        started = time.monotonic()
        for delay in (0, 2, 8, 20):
            time.sleep(max(0, started + delay - time.monotonic()))
            probe_start = time.monotonic()
            try:
                manifests = []
                for manifest in find_mpd_paths(path)[:16]:
                    try:
                        stat = os.stat(manifest)
                        with open(manifest, encoding="utf-8", errors="replace") as handle:
                            header = handle.read(16384)
                        manifests.append(dict(
                            path=manifest, size=stat.st_size, mtime=stat.st_mtime,
                            duration_attributes=re.findall(
                                r'(?:mediaPresentationDuration|duration|type|start)\s*=\s*[\'"]([^\'"]*)',
                                header),
                            mpd_header=header[:1200],
                        ))
                    except OSError as exc:
                        manifests.append(dict(path=manifest, error=str(exc)))
                descriptor = os.path.join(path, "clip.pb")
                try:
                    stat = os.stat(descriptor)
                    descriptor_info = dict(size=stat.st_size, mtime=stat.st_mtime)
                except OSError as exc:
                    descriptor_info = dict(error=str(exc))
                stamp = clip_folder_recorded_at(path)
                trace(path, "source-files", snapshot_after_sec=delay,
                      folder_name=os.path.basename(path),
                      recorded_at_utc=stamp.isoformat() if stamp else None,
                      descriptor=descriptor_info, manifests=manifests,
                      probe_ms=round((time.monotonic() - probe_start) * 1000, 1))
            except Exception:
                _log.exception("New clip trace: source snapshot failed path=%s", path)

    threading.Thread(target=run, name="new-clip-trace", daemon=True).start()
