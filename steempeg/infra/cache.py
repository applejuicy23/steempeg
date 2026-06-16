"""Tiny JSON read/write helpers (used for the games-name cache and user settings).

Pure I/O - no Qt. Callers pass the file path; missing files and parse errors fall
back to a default / are skipped, just like the original code.
"""
import json
from pathlib import Path


def read_json(path, default=None):
    """Return parsed JSON from `path`, or `default` (-> {}) if missing/unreadable."""
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path, data):
    """Write `data` to `path` as pretty UTF-8 JSON. Best-effort (errors ignored)."""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)   # make sure the folder exists
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except OSError:
        pass