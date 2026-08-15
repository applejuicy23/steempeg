"""Serialize library filter memory for ``library_ui.json``.

Clips Manager keeps a rich ``saved_filter_state`` (Qt dates/times + checklists).
Rendered / Screenshots store simpler game (and type) checklists as sets or
``None`` meaning “all selected / no filter”.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, QTime


def _qdate_to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, QDate):
        if not value.isValid():
            return None
        return value.toString("yyyy-MM-dd")
    text = str(value).strip()
    return text or None


def _qtime_to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, QTime):
        if not value.isValid():
            return None
        return value.toString("HH:mm:ss")
    text = str(value).strip()
    return text or None


def _parse_qdate(value: Any) -> QDate | None:
    if value is None:
        return None
    if isinstance(value, QDate):
        return value if value.isValid() else None
    text = str(value).strip()
    if not text:
        return None
    qd = QDate.fromString(text, "yyyy-MM-dd")
    return qd if qd.isValid() else None


def _parse_qtime(value: Any) -> QTime | None:
    if value is None:
        return None
    if isinstance(value, QTime):
        return value if value.isValid() else None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("HH:mm:ss", "H:mm:ss", "HH:mm"):
        qt = QTime.fromString(text, fmt)
        if qt.isValid():
            return qt
    return None


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        name = str(item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def encode_clips_filters(saved: dict | None) -> dict | None:
    """JSON-safe clips filter blob, or ``None`` when inactive / cleared."""
    if not isinstance(saved, dict) or not saved.get("active"):
        return None
    games = _str_list(saved.get("games"))
    types = _str_list(saved.get("types"))
    health = _str_list(saved.get("health"))
    folders = _str_list(saved.get("folders"))
    if not games and not types and not health and not folders:
        # Active-but-empty is treated as “show nothing” in-session; do not
        # resurrect that trap across launches.
        return None
    payload: dict[str, Any] = {
        "active": True,
        "games": games,
        "types": types,
        "health": health,
        "folders": folders,
    }
    for key, encoder in (
        ("min_date", _qdate_to_str),
        ("max_date", _qdate_to_str),
        ("min_time", _qtime_to_str),
        ("max_time", _qtime_to_str),
        ("min_dur", _qtime_to_str),
        ("max_dur", _qtime_to_str),
    ):
        encoded = encoder(saved.get(key))
        if encoded is not None:
            payload[key] = encoded
    return payload


def decode_clips_filters(data: Any) -> dict | None:
    """Rebuild in-memory ``saved_filter_state`` from JSON."""
    if not isinstance(data, dict) or not data.get("active"):
        return None
    games = _str_list(data.get("games"))
    types = _str_list(data.get("types"))
    health = _str_list(data.get("health"))
    folders = _str_list(data.get("folders"))
    if not games and not types and not health and not folders:
        return None
    saved: dict[str, Any] = {
        "active": True,
        "games": games,
        "types": types,
        "health": health,
        "folders": folders,
    }
    for key, parser, fallback in (
        ("min_date", _parse_qdate, QDate.currentDate()),
        ("max_date", _parse_qdate, QDate.currentDate()),
        ("min_time", _parse_qtime, QTime(0, 0, 0)),
        ("max_time", _parse_qtime, QTime(23, 59, 59)),
        ("min_dur", _parse_qtime, QTime(0, 0, 0)),
        ("max_dur", _parse_qtime, QTime(0, 0, 0)),
    ):
        parsed = parser(data.get(key))
        saved[key] = parsed if parsed is not None else fallback
    return saved


def encode_name_set(selected: set[str] | None) -> list[str] | None:
    """``None`` = all selected; list = constrained checklist."""
    if selected is None:
        return None
    return sorted(_str_list(selected))


def decode_name_set(value: Any) -> set[str] | None:
    if value is None:
        return None
    names = _str_list(value)
    return set(names)


def encode_rendered_filters(
    games: set[str] | None, types: set[str] | None
) -> dict | None:
    if games is None and types is None:
        return None
    return {
        "games": encode_name_set(games),
        "types": encode_name_set(types),
    }


def decode_rendered_filters(data: Any) -> tuple[set[str] | None, set[str] | None]:
    if not isinstance(data, dict):
        return None, None
    return decode_name_set(data.get("games")), decode_name_set(data.get("types"))


def encode_screenshots_filters(games: set[str] | None) -> dict | None:
    if games is None:
        return None
    return {"games": encode_name_set(games)}


def decode_screenshots_filters(data: Any) -> set[str] | None:
    if not isinstance(data, dict):
        return None
    return decode_name_set(data.get("games"))
