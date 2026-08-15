"""Optional volume / playback-speed boost ceilings.

Settings → Visual → Player controls. Defaults stay at today's caps
(100% volume, 5.0x speed) so nobody gets a surprise boost; opt in via
150%–500% volume or 8.0x / 10.0x speed.
"""
from __future__ import annotations

KEY_VOLUME_BOOST_CEILING = "volume_boost_ceiling"
KEY_SPEED_BOOST_CEILING = "speed_boost_ceiling"

# Volume slider percent (unity = 100).
VOLUME_CEILING_100 = 100
VOLUME_CEILING_150 = 150
VOLUME_CEILING_200 = 200
VOLUME_CEILING_300 = 300
VOLUME_CEILING_400 = 400
VOLUME_CEILING_500 = 500
VOLUME_CEILING_DEFAULT = VOLUME_CEILING_100

VOLUME_CEILING_LABELS: tuple[tuple[int, str], ...] = (
    (VOLUME_CEILING_100, "100%"),
    (VOLUME_CEILING_150, "150%"),
    (VOLUME_CEILING_200, "200%"),
    (VOLUME_CEILING_300, "300%"),
    (VOLUME_CEILING_400, "400%"),
    (VOLUME_CEILING_500, "500%"),
)

# Speed slider units (10 = 1.0x). Today's max is 50 = 5.0x.
SPEED_CEILING_5X = 50
SPEED_CEILING_8X = 80
SPEED_CEILING_10X = 100
SPEED_CEILING_DEFAULT = SPEED_CEILING_5X

# Painted tick / gradient hinge when speed ceiling is boosted past today's max.
SPEED_UNITY_VALUE = SPEED_CEILING_5X

SPEED_CEILING_LABELS: tuple[tuple[int, str], ...] = (
    (SPEED_CEILING_5X, "5.0x"),
    (SPEED_CEILING_8X, "8.0x"),
    (SPEED_CEILING_10X, "10.0x"),
)

_VOLUME_ALLOWED = frozenset(v for v, _ in VOLUME_CEILING_LABELS)
_SPEED_ALLOWED = frozenset(v for v, _ in SPEED_CEILING_LABELS)

_current_volume_ceiling: int = VOLUME_CEILING_DEFAULT
_current_speed_ceiling: int = SPEED_CEILING_DEFAULT


def normalize_volume_boost_ceiling(value: object | None) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return VOLUME_CEILING_DEFAULT
    if n in _VOLUME_ALLOWED:
        return n
    # Soft aliases / typos.
    if n in (1, 1000):
        return VOLUME_CEILING_100
    if 140 <= n <= 160:
        return VOLUME_CEILING_150
    if 180 <= n <= 220:
        return VOLUME_CEILING_200
    if 280 <= n <= 320:
        return VOLUME_CEILING_300
    if 380 <= n <= 420:
        return VOLUME_CEILING_400
    if 480 <= n <= 520:
        return VOLUME_CEILING_500
    if n <= 100:
        return VOLUME_CEILING_100
    return VOLUME_CEILING_DEFAULT


def normalize_speed_boost_ceiling(value: object | None) -> int:
    """Accept slider units (50/80/100) or float rates (5.0/8.0/10.0)."""
    if value is None:
        return SPEED_CEILING_DEFAULT
    text = str(value).strip().lower().replace("x", "").replace(" ", "")
    try:
        n = float(text)
    except (TypeError, ValueError):
        return SPEED_CEILING_DEFAULT
    # Float rate form: 5 / 5.0 / 8 / 10.
    if 4.5 <= n <= 5.5:
        return SPEED_CEILING_5X
    if 7.5 <= n <= 8.5:
        return SPEED_CEILING_8X
    if 9.5 <= n <= 10.5:
        return SPEED_CEILING_10X
    # Slider units.
    units = int(round(n))
    if units in _SPEED_ALLOWED:
        return units
    if units <= SPEED_CEILING_5X:
        return SPEED_CEILING_5X
    return SPEED_CEILING_DEFAULT


def get_volume_boost_ceiling() -> int:
    return _current_volume_ceiling


def get_speed_boost_ceiling() -> int:
    return _current_speed_ceiling


def set_volume_boost_ceiling(value: object | None) -> int:
    global _current_volume_ceiling
    _current_volume_ceiling = normalize_volume_boost_ceiling(value)
    return _current_volume_ceiling


def set_speed_boost_ceiling(value: object | None) -> int:
    global _current_speed_ceiling
    _current_speed_ceiling = normalize_speed_boost_ceiling(value)
    return _current_speed_ceiling


def load_player_boost_from_settings(settings: dict | None) -> tuple[int, int]:
    data = settings if isinstance(settings, dict) else {}
    vol = set_volume_boost_ceiling(
        data.get(KEY_VOLUME_BOOST_CEILING, VOLUME_CEILING_DEFAULT)
    )
    spd = set_speed_boost_ceiling(
        data.get(KEY_SPEED_BOOST_CEILING, SPEED_CEILING_DEFAULT)
    )
    return vol, spd
