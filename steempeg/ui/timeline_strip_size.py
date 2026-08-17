"""Player timeline strip size preference (ruler ticks + digits, not the bar).

Settings → Visual: Small / Medium / Large. Large is the product default and
matches the pre-pref baseline (full-size track + tall ticks + 9pt digits).
S/M/L scale time labels and tick marks only — the scrubber / progress track
stays at Large's height. Upgrading installs without a saved pref also map
to Large once.
"""
from __future__ import annotations

from dataclasses import dataclass

KEY_TIMELINE_STRIP_SIZE = "timeline_strip_size"
KEY_TIMELINE_STRIP_SIZE_REV = "timeline_strip_size_rev"

# Rev 1 = first ship of S/M/L (migrate missing key → Large for existing stores).
TIMELINE_STRIP_SIZE_REV_CURRENT = 1

TIMELINE_STRIP_SMALL = "small"
TIMELINE_STRIP_MEDIUM = "medium"
TIMELINE_STRIP_LARGE = "large"

# New installs / explicit default in Settings (Large = pre-pref baseline).
TIMELINE_STRIP_DEFAULT = TIMELINE_STRIP_LARGE

TIMELINE_STRIP_LABELS: tuple[tuple[str, str], ...] = (
    (TIMELINE_STRIP_SMALL, "Small"),
    (TIMELINE_STRIP_MEDIUM, "Medium"),
    (TIMELINE_STRIP_LARGE, "Large"),
)

# Keys that imply a settings store already existed before this pref.
_PRIOR_SETTINGS_HINTS: tuple[str, ...] = (
    "chrome_theme",
    "clip_card_style",
    "game_icon_shape",
    "player_header_layout",
    "date_format",
    "clock_format",
    "default_render_tab",
    "desktop_render_layout",
)


@dataclass(frozen=True)
class TimelineStripMetrics:
    """Logical px for the seek strip + digit/tick ruler (pins stay above).

    ``track_h`` is the purple/gray scrubber and is the same at every size.
    Digits and tick marks are the S/M/L axis; charcoal pad may tighten
    slightly under smaller type so labels do not float in empty space.
    """

    track_h: float
    major_tick_h: int
    minor_tick_h: int
    tick_pen_w: float
    ruler_font_pt: int
    ruler_gap: int
    bottom_pad: int

    @property
    def chrome_below(self) -> int:
        """Dark ruler band under the scrubber (gap + major ticks + pad)."""
        return int(self.ruler_gap + self.major_tick_h + self.bottom_pad)


# Large = pre-pref / previous Large (track 13 + 11/5 ticks + 9pt). Track is
# constant. Medium ≈ v36.1 compact digits/ticks under that same bar. Small
# is one step smaller on ticks + type only.
_TRACK_H_LARGE = 13.0

_METRICS: dict[str, TimelineStripMetrics] = {
    TIMELINE_STRIP_LARGE: TimelineStripMetrics(
        track_h=_TRACK_H_LARGE,
        major_tick_h=11,
        minor_tick_h=5,
        tick_pen_w=1.0,
        ruler_font_pt=9,
        ruler_gap=4,
        bottom_pad=8,
    ),
    TIMELINE_STRIP_MEDIUM: TimelineStripMetrics(
        track_h=_TRACK_H_LARGE,
        major_tick_h=10,
        minor_tick_h=4,
        tick_pen_w=1.0,
        ruler_font_pt=8,
        ruler_gap=4,
        bottom_pad=7,
    ),
    TIMELINE_STRIP_SMALL: TimelineStripMetrics(
        track_h=_TRACK_H_LARGE,
        major_tick_h=8,
        minor_tick_h=3,
        tick_pen_w=1.0,
        ruler_font_pt=7,
        ruler_gap=3,
        bottom_pad=6,
    ),
}

_current_size: str = TIMELINE_STRIP_DEFAULT


def normalize_timeline_strip_size(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in (TIMELINE_STRIP_SMALL, TIMELINE_STRIP_MEDIUM, TIMELINE_STRIP_LARGE):
        return text
    if text in ("s", "sm", "compact", "thin", "short"):
        return TIMELINE_STRIP_SMALL
    if text in ("m", "med", "normal"):
        return TIMELINE_STRIP_MEDIUM
    if text in ("l", "lg", "tall", "current", "baseline", "default"):
        return TIMELINE_STRIP_LARGE
    return TIMELINE_STRIP_DEFAULT


def get_timeline_strip_size() -> str:
    return _current_size


def set_timeline_strip_size(size: object | None) -> str:
    global _current_size
    _current_size = normalize_timeline_strip_size(size)
    return _current_size


def metrics_for(size: object | None = None) -> TimelineStripMetrics:
    key = normalize_timeline_strip_size(
        size if size is not None else _current_size
    )
    return _METRICS[key]


def metrics_for_current() -> TimelineStripMetrics:
    return metrics_for(_current_size)


def migrate_timeline_strip_size_in_settings(settings: dict | None) -> bool:
    """One-shot: missing pref on an existing store → Large (keep today's height)."""
    if not isinstance(settings, dict):
        return False
    try:
        rev = int(settings.get(KEY_TIMELINE_STRIP_SIZE_REV) or 0)
    except (TypeError, ValueError):
        rev = 0
    if rev >= TIMELINE_STRIP_SIZE_REV_CURRENT:
        return False
    if KEY_TIMELINE_STRIP_SIZE not in settings:
        if any(k in settings for k in _PRIOR_SETTINGS_HINTS):
            settings[KEY_TIMELINE_STRIP_SIZE] = TIMELINE_STRIP_LARGE
        else:
            settings[KEY_TIMELINE_STRIP_SIZE] = TIMELINE_STRIP_DEFAULT
    else:
        settings[KEY_TIMELINE_STRIP_SIZE] = normalize_timeline_strip_size(
            settings.get(KEY_TIMELINE_STRIP_SIZE)
        )
    settings[KEY_TIMELINE_STRIP_SIZE_REV] = TIMELINE_STRIP_SIZE_REV_CURRENT
    return True


def load_timeline_strip_size_from_settings(settings: dict | None) -> str:
    data = settings if isinstance(settings, dict) else {}
    migrate_timeline_strip_size_in_settings(data)
    raw = data.get(KEY_TIMELINE_STRIP_SIZE, TIMELINE_STRIP_DEFAULT)
    return set_timeline_strip_size(raw)
