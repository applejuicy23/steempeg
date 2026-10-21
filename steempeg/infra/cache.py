"""Tiny JSON read/write helpers (used for the games-name cache and user settings).

Pure I/O - no Qt. Callers pass the file path; missing files and parse errors fall
back to a default / are skipped, just like the original code.
"""
import json
import os
import time
import uuid
from pathlib import Path


def read_json(path, default=None):
    """Return parsed JSON from `path`, or `default` (-> {}) if missing/unreadable."""
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_text_atomic(path, text: str) -> None:
    """Writes UTF-8 text to a temp file next to `path`, then swaps it in.

    A crash mid-write leaves the old file intact instead of a truncated one.
    Raises OSError when the file cannot be written.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)   # make sure the folder exists
    # Unique per call so two writers of the same file never share a temp file.
    tmp_path = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    last_error = None
    # Windows refuses the replace while an antivirus or indexer briefly holds the target.
    for attempt in range(5):
        try:
            os.replace(tmp_path, path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    try:
        os.remove(tmp_path)
    except OSError:
        pass
    raise last_error


def write_json(path, data) -> bool:
    """Write `data` to `path` as pretty UTF-8 JSON. Returns False on failure."""
    try:
        text = json.dumps(data, ensure_ascii=False, indent=4)
    except (TypeError, ValueError):
        return False
    try:
        write_text_atomic(path, text)
        return True
    except OSError:
        return False
