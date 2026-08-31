"""Export quality preset catalog — labels + heights for the Video settings combo.

4K uses Divine; 8K and anything taller uses Goddess. Bitrate tables may only
list known keys (through 4320p); taller Goddess steps scale from 4320 by area.

Also tags for the v48 categorized Quality Preset combo (Standard vs Custom).
"""
from __future__ import annotations

import re
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


def parse_quality_height(quality_text: str | None) -> int:
    """Extract ``2160`` from ``2160p (Divine Quality)``; 0 if Original / unknown."""
    text = quality_text or ""
    if "Original" in text and "Target" not in text:
        return 0
    if "Target File" in text:
        return 0
    m = re.search(r"(\d+)\s*p", text, flags=re.IGNORECASE)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def resolve_quality_for_source(
    quality_text: str,
    source_height: int,
    *,
    fallback: str | None = None,
) -> str:
    """Pick a quality label that does not upscale past *source_height*.

    Order: requested → *fallback* (if usable) → Original.
    """
    src = int(source_height) if source_height and source_height > 0 else 0
    text = (quality_text or "").strip()
    if not text:
        return original_quality_label(src or None)
    if "Original" in text and "Target" not in text:
        return original_quality_label(src or None) if src else text
    if "Target File" in text:
        return text

    want = parse_quality_height(text)
    if src <= 0 or want <= 0 or want <= src:
        return text

    fb = (fallback or "").strip()
    if fb and not fb.lower().startswith("original"):
        fb_h = parse_quality_height(fb)
        if fb_h <= 0:
            # Bare height token.
            try:
                fb_h = int(re.search(r"(\d+)", fb).group(1)) if re.search(r"(\d+)", fb) else 0
            except Exception:
                fb_h = 0
        if 0 < fb_h <= src:
            if parse_quality_height(fb) > 0 and "(" in fb:
                return fb
            return format_quality_item(fb_h)

    return original_quality_label(src)


def resolve_fps_for_source(fps_text: str, source_fps: int) -> str:
    """Clamp a preset FPS choice so it never exceeds the clip's FPS."""
    text = (fps_text or "").strip()
    src = int(source_fps) if source_fps and source_fps > 0 else 0
    if not text or "Original" in text:
        return f"{src} FPS (Original)" if src > 0 else (text or "60 FPS (Original)")
    m = re.search(r"(\d+)", text)
    if not m:
        return text
    try:
        want = int(m.group(1))
    except ValueError:
        return text
    if src > 0 and want > src:
        return f"{src} FPS (Original)"
    if "FPS" in text.upper():
        return text
    return f"{want} FPS"


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
