"""Bundled per-game DASH init donors for dead-clip salvage.

Steam Game Recording inits are codec passports tied to a specific encode
profile. There is no universal donor — only ``assets/donors/<app_id>/…``.

Fallback chain (caller owns library search):
  clip's own init → healthy same-game library clip → bundled donor → give up.
"""
from __future__ import annotations

import logging
import os

from steempeg.infra.paths import get_resource_path

_MIN_INIT_BYTES = 100
_VIDEO_INIT = "init-stream0.m4s"
_AUDIO_INIT = "init-stream1.m4s"


def bundled_donor_dir(app_id: str | int | None) -> str | None:
    """Absolute path to ``assets/donors/<app_id>/``, or None if app_id is empty."""
    if app_id is None:
        return None
    aid = str(app_id).strip()
    if not aid.isdigit():
        return None
    return get_resource_path(os.path.join("donors", aid))


def find_bundled_donor_init(
    app_id: str | int | None, *, stream: int = 0
) -> str | None:
    """Return a valid bundled init path for ``app_id``, or None.

    ``stream`` 0 = video (``init-stream0.m4s``), 1 = audio (``init-stream1.m4s``).
    """
    donor_dir = bundled_donor_dir(app_id)
    if not donor_dir or not os.path.isdir(donor_dir):
        return None
    name = _VIDEO_INIT if stream == 0 else _AUDIO_INIT
    path = os.path.join(donor_dir, name)
    try:
        if os.path.isfile(path) and os.path.getsize(path) >= _MIN_INIT_BYTES:
            logging.info("Bundled donor init for app_id=%s: %s", app_id, path)
            return path
    except OSError:
        return None
    return None


def list_bundled_donor_app_ids() -> list[str]:
    """Steam app_ids that have a bundled video init under ``assets/donors/``."""
    root = get_resource_path("donors")
    if not os.path.isdir(root):
        return []
    found: list[str] = []
    try:
        for name in sorted(os.listdir(root)):
            if not name.isdigit():
                continue
            init = os.path.join(root, name, _VIDEO_INIT)
            try:
                if os.path.isfile(init) and os.path.getsize(init) >= _MIN_INIT_BYTES:
                    found.append(name)
            except OSError:
                continue
    except OSError:
        return []
    return found
