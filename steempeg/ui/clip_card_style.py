"""ClipCard corner style preference (Clips / Rendered / Choose a Clip grids).

Three modes (Settings → Visual), default SteempegUI:

* ``steempeg_ui`` — shelf / row edge roles: first row flat top + round bottom;
  middle rows fully round; last row round top + flat bottom
* ``square`` — square top, round bottom on every card
* ``round`` — round top and round bottom everywhere (no shelf variation)
"""
from __future__ import annotations

KEY_CLIP_CARD_STYLE = "clip_card_style"
KEY_CLIP_CARD_STYLE_REV = "clip_card_style_rev"

# Rev 1 = mislabeled geometry (Round≈shelf, SteempegUI≈square-outer join, Square≈all-sharp).
# Rev 2 = product meanings above.
CLIP_CARD_STYLE_REV_CURRENT = 2

CARD_STYLE_SQUARE = "square"
CARD_STYLE_STEEMPEG_UI = "steempeg_ui"
CARD_STYLE_ROUND = "round"

CARD_STYLE_DEFAULT = CARD_STYLE_STEEMPEG_UI

CARD_STYLE_LABELS: tuple[tuple[str, str], ...] = (
    (CARD_STYLE_STEEMPEG_UI, "SteempegUI"),
    (CARD_STYLE_SQUARE, "Square"),
    (CARD_STYLE_ROUND, "Round"),
)

# Outer chrome / footer soft radii (px) — match legacy ClipCard language.
OUTER_RADIUS = 12
FOOTER_SOFT_RADIUS = 9

_current_style: str = CARD_STYLE_DEFAULT

# v1 saved values → v2 product names (Emily's label mapping of the wrong UI).
_V1_TO_V2: dict[str, str] = {
    CARD_STYLE_ROUND: CARD_STYLE_STEEMPEG_UI,  # Round label was shelf
    CARD_STYLE_STEEMPEG_UI: CARD_STYLE_SQUARE,  # SteempegUI label was square-ish
    CARD_STYLE_SQUARE: CARD_STYLE_STEEMPEG_UI,  # all-sharp was neither → default
}


def normalize_clip_card_style(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in (CARD_STYLE_SQUARE, CARD_STYLE_STEEMPEG_UI, CARD_STYLE_ROUND):
        return text
    # Friendly aliases
    if text in ("steempeg", "steempegui", "ui", "default", "current", "shelf"):
        return CARD_STYLE_STEEMPEG_UI
    if text in ("circle", "rounded", "full"):
        return CARD_STYLE_ROUND
    if text in ("sharp", "flat", "classic", "square_top"):
        return CARD_STYLE_SQUARE
    return CARD_STYLE_DEFAULT


def get_clip_card_style() -> str:
    return _current_style


def set_clip_card_style(style: object | None) -> str:
    global _current_style
    _current_style = normalize_clip_card_style(style)
    return _current_style


def migrate_clip_card_style_in_settings(settings: dict | None) -> bool:
    """Rewrite v1 mislabeled prefs in-place. Returns True if settings were changed."""
    if not isinstance(settings, dict):
        return False
    try:
        rev = int(settings.get(KEY_CLIP_CARD_STYLE_REV) or 0)
    except (TypeError, ValueError):
        rev = 0
    if rev >= CLIP_CARD_STYLE_REV_CURRENT:
        return False
    raw = settings.get(KEY_CLIP_CARD_STYLE, None)
    if raw is None:
        # Never saved — keep default; stamp rev so we don't remap later.
        settings[KEY_CLIP_CARD_STYLE_REV] = CLIP_CARD_STYLE_REV_CURRENT
        return True
    old = normalize_clip_card_style(raw)
    new = _V1_TO_V2.get(old, CARD_STYLE_DEFAULT)
    settings[KEY_CLIP_CARD_STYLE] = new
    settings[KEY_CLIP_CARD_STYLE_REV] = CLIP_CARD_STYLE_REV_CURRENT
    return True


def load_clip_card_style_from_settings(settings: dict | None) -> str:
    data = settings if isinstance(settings, dict) else {}
    migrate_clip_card_style_in_settings(data)
    raw = data.get(KEY_CLIP_CARD_STYLE, CARD_STYLE_DEFAULT)
    return set_clip_card_style(raw)
