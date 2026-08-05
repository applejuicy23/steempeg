"""Date / time display — Settings override, else OS locale (same idea as timezone)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from PySide6.QtCore import QDateTime, QLocale

from steempeg.ui.settings_prefs import (
    CLOCK_12,
    CLOCK_24,
    CLOCK_AUTO,
    DATE_FMT_EU,
    DATE_FMT_ISO,
    DATE_FMT_SYSTEM,
    DATE_FMT_US,
    TZ_SYSTEM,
    load_clock_format,
    load_date_format,
    load_display_timezone,
    normalize_clock_format,
    normalize_date_format,
    normalize_display_timezone,
)

_DATE_FMT_LONG = "%d %B %Y"
_TIME_12 = "%I:%M %p"
_TIME_24 = "%H:%M"

_DATE_STRFTIME: dict[str, str] = {
    DATE_FMT_SYSTEM: _DATE_FMT_LONG,
    DATE_FMT_US: "%m/%d/%y",
    DATE_FMT_EU: "%d.%m.%Y",
    DATE_FMT_ISO: "%Y/%m/%d",
}

# Module cache — refreshed via configure_display_time() at startup / Save.
_cfg: dict[str, Any] = {
    "date_format": DATE_FMT_SYSTEM,
    "clock_format": CLOCK_AUTO,
    "timezone": TZ_SYSTEM,
}


def configure_display_time(settings: dict | None = None) -> None:
    """Apply date/clock/TZ prefs from settings.json (or defaults)."""
    _cfg["date_format"] = load_date_format(settings)
    _cfg["clock_format"] = load_clock_format(settings)
    _cfg["timezone"] = load_display_timezone(settings)
    _os_uses_24_hour_clock.cache_clear()


@lru_cache(maxsize=1)
def _os_uses_24_hour_clock() -> bool:
    """True when the system short-time format has no AM/PM (e.g. ru-RU, de-DE)."""
    fmt = QLocale.system().timeFormat(QLocale.FormatType.ShortFormat)
    return "AP" not in fmt and "ap" not in fmt


def uses_24_hour_clock() -> bool:
    clock = normalize_clock_format(_cfg.get("clock_format"))
    if clock == CLOCK_24:
        return True
    if clock == CLOCK_12:
        return False
    # Auto: follow date preset, else OS.
    date_fmt = normalize_date_format(_cfg.get("date_format"))
    if date_fmt == DATE_FMT_US:
        return False
    if date_fmt in (DATE_FMT_EU, DATE_FMT_ISO):
        return True
    return _os_uses_24_hour_clock()


def clip_date_strftime_fmt() -> str:
    date_fmt = normalize_date_format(_cfg.get("date_format"))
    return _DATE_STRFTIME.get(date_fmt, _DATE_FMT_LONG)


def clip_time_strftime_fmt() -> str:
    return _TIME_24 if uses_24_hour_clock() else _TIME_12


def clip_datetime_strftime_fmt() -> str:
    """Full datetime with ``at`` between date and time."""
    return f"{clip_date_strftime_fmt()} at {clip_time_strftime_fmt()}"


def qt_time_display_format() -> str:
    return "HH:mm" if uses_24_hour_clock() else "hh:mm AP"


def _resolve_zoneinfo(name: str):
    """Return a tzinfo for *name*, or None for system-local.

    Prefers ``zoneinfo`` when tzdata is installed; falls back to Qt
    ``QTimeZone`` (ships IANA data with PySide) so Windows works without
    the ``tzdata`` package.
    """
    if not name or normalize_display_timezone(name) == TZ_SYSTEM:
        return None
    raw = str(name).strip()
    if raw.upper() == "UTC":
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(raw)
    except Exception:
        pass
    try:
        from PySide6.QtCore import QTimeZone

        qtz = QTimeZone(raw.encode("ascii", errors="ignore"))
        if qtz.isValid():
            # Wrap via fixed offset at "now" is wrong for DST — convert
            # per-call in to_display_datetime instead.
            return ("qtimezone", raw)
    except Exception:
        pass
    return None


def to_display_datetime(dt: datetime) -> datetime:
    """Convert *dt* into the configured display timezone (naive → assume local)."""
    from datetime import timedelta

    resolved = _resolve_zoneinfo(str(_cfg.get("timezone") or TZ_SYSTEM))
    if dt.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        dt = dt.replace(tzinfo=local_tz)
    if resolved is None:
        return dt.astimezone()
    if isinstance(resolved, tuple) and resolved[0] == "qtimezone":
        try:
            from PySide6.QtCore import QDateTime, QTimeZone, Qt

            qtz = QTimeZone(resolved[1].encode("ascii", errors="ignore"))
            qdt = QDateTime.fromSecsSinceEpoch(int(dt.timestamp()), Qt.UTC)
            local = qdt.toTimeZone(qtz)
            offset = int(local.offsetFromUtc())
            return datetime(
                local.date().year(),
                local.date().month(),
                local.date().day(),
                local.time().hour(),
                local.time().minute(),
                local.time().second(),
                tzinfo=timezone(timedelta(seconds=offset)),
            )
        except Exception:
            return dt.astimezone()
    return dt.astimezone(resolved)


def format_clip_date(dt: datetime) -> str:
    return to_display_datetime(dt).strftime(clip_date_strftime_fmt())


def format_clip_time(dt: datetime) -> str:
    return to_display_datetime(dt).strftime(clip_time_strftime_fmt())


def format_clip_datetime(dt: datetime) -> str:
    return to_display_datetime(dt).strftime(clip_datetime_strftime_fmt())


def clip_datetime_parse_formats() -> tuple[str, ...]:
    # Accept every known date style × both clocks so filters survive format changes.
    dates = (
        _DATE_FMT_LONG,
        "%m/%d/%y",
        "%d.%m.%Y",
        "%Y/%m/%d",
        "%d %b %Y",
    )
    times = (_TIME_24, _TIME_12)
    out: list[str] = []
    for d in dates:
        for t in times:
            out.append(f"{d} at {t}")
            out.append(f"{d}, {t}")
            out.append(f"{d} {t}")
        out.append(d)
    return tuple(out)


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
