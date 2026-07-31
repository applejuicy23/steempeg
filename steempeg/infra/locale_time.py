"""12-hour vs 24-hour time display — follows the OS locale (same idea as timezone)."""
from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache

from PySide6.QtCore import QDateTime, QLocale, QTime

_DATE_FMT = "%d %B %Y"
_TIME_12 = "%I:%M %p"
_TIME_24 = "%H:%M"


@lru_cache(maxsize=1)
def uses_24_hour_clock() -> bool:
    """True when the system short-time format has no AM/PM (e.g. ru-RU, de-DE)."""
    fmt = QLocale.system().timeFormat(QLocale.FormatType.ShortFormat)
    return "AP" not in fmt and "ap" not in fmt


def clip_time_strftime_fmt() -> str:
    return _TIME_24 if uses_24_hour_clock() else _TIME_12


def clip_datetime_strftime_fmt() -> str:
    """Full datetime with ``at`` between date and time (``11 May 2026 at 2:32 PM``)."""
    return f"{_DATE_FMT} at {clip_time_strftime_fmt()}"


def qt_time_display_format() -> str:
    return "HH:mm" if uses_24_hour_clock() else "hh:mm AP"


def format_clip_date(dt: datetime) -> str:
    return dt.strftime(_DATE_FMT)


def format_clip_time(dt: datetime) -> str:
    return dt.strftime(clip_time_strftime_fmt())


def format_clip_datetime(dt: datetime) -> str:
    return dt.strftime(clip_datetime_strftime_fmt())


def clip_datetime_parse_formats() -> tuple[str, ...]:
    # ``at`` form is canonical; comma / bare-space kept for older table cells / cache.
    return (
        f"{_DATE_FMT} at {_TIME_24}",
        f"{_DATE_FMT} at {_TIME_12}",
        f"{_DATE_FMT}, {_TIME_24}",
        f"{_DATE_FMT}, {_TIME_12}",
        f"{_DATE_FMT} {_TIME_24}",
        f"{_DATE_FMT} {_TIME_12}",
        _DATE_FMT,
    )


def parse_clip_datetime_text(text: str) -> QDateTime | None:
    raw = re.sub(r"\s+", " ", text.strip())
    # Normalize separators so both ``date at time`` and ``date, time`` parse.
    raw = re.sub(r",\s*", ", ", raw)
    raw = re.sub(r"\s+at\s+", " at ", raw, flags=re.IGNORECASE)
    for fmt in clip_datetime_parse_formats():
        try:
            dt = datetime.strptime(raw, fmt)
            return QDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
        except ValueError:
            continue
    return None
