"""Player header strip size preference (height / pads / chips; mild type).

Settings → Visual → Player header → Size: Small / Medium / Large.

Works *with* UI density: S/M/L scales the density ``header_*`` metrics.
Size is mostly strip height and padding; type stays near the Large baseline
(13 → 13 → 12). Large matches the pre-pref baseline; Medium is the product
default for new installs; upgrading stores without a saved pref map to Large
once.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from steempeg.ui.ui_density import UiDensity

KEY_PLAYER_HEADER_SIZE = "player_header_size"
KEY_PLAYER_HEADER_SIZE_REV = "player_header_size_rev"

# Rev 1 = first ship of S/M/L (migrate missing key → Large for existing stores).
PLAYER_HEADER_SIZE_REV_CURRENT = 1

PLAYER_HEADER_SMALL = "small"
PLAYER_HEADER_MEDIUM = "medium"
PLAYER_HEADER_LARGE = "large"

# New installs / explicit default in Settings.
PLAYER_HEADER_DEFAULT = PLAYER_HEADER_MEDIUM

PLAYER_HEADER_SIZE_LABELS: tuple[tuple[str, str], ...] = (
    (PLAYER_HEADER_SMALL, "Small"),
    (PLAYER_HEADER_MEDIUM, "Medium"),
    (PLAYER_HEADER_LARGE, "Large"),
)

# Keys that imply a settings store already existed before this pref.
_PRIOR_SETTINGS_HINTS: tuple[str, ...] = (
    "chrome_theme",
    "clip_card_style",
    "game_icon_shape",
    "player_header_layout",
    "timeline_strip_size",
    "date_format",
    "clock_format",
    "default_render_tab",
    "desktop_render_layout",
)


@dataclass(frozen=True)
class PlayerHeaderSizeScale:
    """Multipliers on density ``header_*`` fields (1.0 = Large / baseline)."""

    icon: float
    font: float
    pad_h: float
    pad_v: float
    chip: float
    chip_icon: float
    min_h: float
    status_pad: float


# Large ≈ today's density header metrics (icon 24 / font 13 / pads 10×8 / chip 30).
# S/M/L is mostly height / padding / chips; type stays near 13 (L 13 / M 13 / S 12).
_SCALES: dict[str, PlayerHeaderSizeScale] = {
    PLAYER_HEADER_LARGE: PlayerHeaderSizeScale(
        icon=1.0,
        font=1.0,
        pad_h=1.0,
        pad_v=1.0,
        chip=1.0,
        chip_icon=1.0,
        min_h=1.0,
        status_pad=1.0,
    ),
    # Medium: shorter strip via pad/min_h; same type as Large, mild icon/chip.
    PLAYER_HEADER_MEDIUM: PlayerHeaderSizeScale(
        icon=0.96,
        font=1.0,
        pad_h=0.85,
        pad_v=0.75,
        chip=0.97,
        chip_icon=0.94,
        min_h=0.87,
        status_pad=0.9,
    ),
    # Small: clear height drop; one-step type (13→12), gentle icon/chip.
    PLAYER_HEADER_SMALL: PlayerHeaderSizeScale(
        icon=0.92,
        font=12 / 13,
        pad_h=0.7,
        pad_v=0.55,
        chip=0.93,
        chip_icon=0.90,
        min_h=0.74,
        status_pad=0.8,
    ),
}

_current_size: str = PLAYER_HEADER_DEFAULT


def normalize_player_header_size(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in (PLAYER_HEADER_SMALL, PLAYER_HEADER_MEDIUM, PLAYER_HEADER_LARGE):
        return text
    if text in ("s", "sm", "compact", "thin", "short", "dense"):
        return PLAYER_HEADER_SMALL
    if text in ("m", "med", "normal", "default"):
        return PLAYER_HEADER_MEDIUM
    if text in ("l", "lg", "tall", "current", "baseline", "comfort"):
        return PLAYER_HEADER_LARGE
    return PLAYER_HEADER_DEFAULT


def get_player_header_size() -> str:
    return _current_size


def set_player_header_size(size: object | None) -> str:
    global _current_size
    _current_size = normalize_player_header_size(size)
    return _current_size


def scale_for(size: object | None = None) -> PlayerHeaderSizeScale:
    key = normalize_player_header_size(
        size if size is not None else _current_size
    )
    return _SCALES[key]


def scale_for_current() -> PlayerHeaderSizeScale:
    return scale_for(_current_size)


def _scale_pad_str(pad: str, factor: float) -> str:
    """Scale ``Npx`` tokens in a CSS-like pad string."""
    import re

    if abs(factor - 1.0) < 0.02:
        return pad

    def _one(m: re.Match[str]) -> str:
        return f"{max(1, int(round(int(m.group(1)) * factor)))}px"

    return re.sub(r"(\d+)px", _one, pad)


def apply_header_size_to_density(
    dense: UiDensity, size: object | None = None
) -> UiDensity:
    """Return ``dense`` with ``header_*`` metrics scaled by the S/M/L pref."""
    sc = scale_for(size)
    if (
        sc.icon == 1.0
        and sc.font == 1.0
        and sc.pad_h == 1.0
        and sc.pad_v == 1.0
        and sc.chip == 1.0
        and sc.chip_icon == 1.0
        and sc.min_h == 1.0
        and sc.status_pad == 1.0
    ):
        return dense

    def _px(v: int, factor: float, floor: int = 1) -> int:
        return max(floor, int(round(int(v) * factor)))

    return replace(
        dense,
        header_icon=_px(dense.header_icon, sc.icon, 16),
        header_font=_px(dense.header_font, sc.font, 11),
        header_pad_h=_px(dense.header_pad_h, sc.pad_h, 4),
        header_pad_v=_px(dense.header_pad_v, sc.pad_v, 2),
        header_chip=_px(dense.header_chip, sc.chip, 22),
        header_chip_icon=_px(dense.header_chip_icon, sc.chip_icon, 12),
        header_min_h=_px(dense.header_min_h, sc.min_h, 28),
        header_status_pad=_scale_pad_str(str(dense.header_status_pad), sc.status_pad),
    )


def migrate_player_header_size_in_settings(settings: dict | None) -> bool:
    """One-shot: missing pref on an existing store → Large (keep today's height)."""
    if not isinstance(settings, dict):
        return False
    try:
        rev = int(settings.get(KEY_PLAYER_HEADER_SIZE_REV) or 0)
    except (TypeError, ValueError):
        rev = 0
    if rev >= PLAYER_HEADER_SIZE_REV_CURRENT:
        return False
    if KEY_PLAYER_HEADER_SIZE not in settings:
        if any(k in settings for k in _PRIOR_SETTINGS_HINTS):
            settings[KEY_PLAYER_HEADER_SIZE] = PLAYER_HEADER_LARGE
        else:
            settings[KEY_PLAYER_HEADER_SIZE] = PLAYER_HEADER_DEFAULT
    else:
        settings[KEY_PLAYER_HEADER_SIZE] = normalize_player_header_size(
            settings.get(KEY_PLAYER_HEADER_SIZE)
        )
    settings[KEY_PLAYER_HEADER_SIZE_REV] = PLAYER_HEADER_SIZE_REV_CURRENT
    return True


def load_player_header_size_from_settings(settings: dict | None) -> str:
    data = settings if isinstance(settings, dict) else {}
    migrate_player_header_size_in_settings(data)
    raw = data.get(KEY_PLAYER_HEADER_SIZE, PLAYER_HEADER_DEFAULT)
    return set_player_header_size(raw)
