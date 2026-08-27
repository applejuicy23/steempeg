"""Export quality preset catalog — labels + heights for the Video settings combo.

4K uses Divine; 8K and anything taller uses Goddess. Bitrate tables may only
list known keys (through 4320p); taller Goddess steps scale from 4320 by area.

Also tags for the v48 categorized Quality Preset combo (Standard vs Custom).
"""
from __future__ import annotations

from typing import Any

# Fixed ladder (tall → short). Extra Goddess heights are injected when the
# source clip is taller than the last known step.
_BASE_HEIGHTS: tuple[int, ...] = (
    4320,
    2160,
    1440,
    1080,
    720,
    480,
    360,
    260,
    144,
)

_LABEL_BY_HEIGHT: dict[int, str] = {
    2160: "Divine Quality",
    1440: "Very good Quality",
    1080: "Good Quality",
    720: "Mid Quality",
    480: "Bad Quality",
    360: "Very bad Quality",
    260: "Worst Quality",
    144: "Old VHS tape",
}

_GODDESS_MIN = 4320
_DIVINE_HEIGHT = 2160

# QComboBox itemData (UserRole) kinds for Video Settings → Quality Preset.
KIND_STANDARD = "standard"
KIND_CUSTOM = "custom"
KIND_TARGET = "target"
KIND_HEADER = "header"

TARGET_FILE_SIZE_LABEL = "🎯 Target File Size..."


def quality_tier_label(height: int) -> str:
    """Human tier name for a vertical resolution."""
    h = int(height)
    if h >= _GODDESS_MIN:
        return "Goddess Quality"
    if h == _DIVINE_HEIGHT:
        return "Divine Quality"
    return _LABEL_BY_HEIGHT.get(h, "Custom Quality")


def format_quality_item(height: int) -> str:
    """Combo row text, e.g. ``2160p (Divine Quality)``."""
    h = int(height)
    return f"{h}p ({quality_tier_label(h)})"


def build_quality_presets(source_height: int | None = None) -> list[tuple[str, int]]:
    """Return ``(label, height)`` rows tall→short for the quality combo.

    When ``source_height`` is set, only presets ≤ that height are returned (no
    upscale rows — a 1440p clip never lists 2160p/4320p). If the source is
    taller than the fixed ladder, the exact source height is inserted as a
    Goddess step (12K/16K/…).

    Callers must pass a real height (or a conservative fallback like 1080).
    Passing ``None`` / ``0`` still returns the full ladder for tests — UI code
    must not do that for live clips.
    """
    heights = list(_BASE_HEIGHTS)
    src = int(source_height) if source_height and source_height > 0 else 0
    if src > heights[0] and src not in heights:
        heights.insert(0, src)
    # Unique + descending
    heights = sorted(set(heights), reverse=True)
    if src > 0:
        heights = [h for h in heights if h <= src]
    return [(format_quality_item(h), h) for h in heights]


def original_quality_label(source_height: int | None = None) -> str:
    src = int(source_height) if source_height and source_height > 0 else 0
    if src > 0:
        return f"Original (Lossless, {src}p)"
    return "Original (Lossless)"


def quality_item_meta(
    *,
    kind: str,
    name: str = "",
    height: int | None = None,
) -> dict[str, Any]:
    """Payload stored on Quality Preset combo rows (``Qt.UserRole``)."""
    meta: dict[str, Any] = {"kind": str(kind or KIND_STANDARD)}
    if name:
        meta["name"] = str(name)
    if height is not None:
        meta["height"] = int(height)
    return meta


def bitrate_mbps_for(
    steam_bitrate_presets: dict,
    quality_level: str,
    height: int,
) -> float | None:
    """Look up Mbps for Ultra/High/Medium/Low; extrapolate above 4320p by area."""
    level = steam_bitrate_presets.get(quality_level) or {}
    key = f"{int(height)}p"
    if key in level:
        return float(level[key])
    h = int(height)
    if h <= _GODDESS_MIN:
        return None
    base = level.get("4320p")
    if base is None:
        return None
    # Pixel-area scale from 8K ladder point.
    return float(base) * ((h / float(_GODDESS_MIN)) ** 2)
