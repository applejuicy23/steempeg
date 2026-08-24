"""Player column chrome layout preference (Settings → Visual → Player layout).

* ``reunited`` — unified flush stack (header + canvas + footer), 0px gaps,
  4px painted header→canvas breathing room, 6px outer corner radius when outlines on.
* ``fractured`` — separated header / canvas / footer with 8px column spacing,
  full 6px corner radius on header and footer, no header canvas gap.

Outline borders are a separate pref (``player_outline``); this controls spacing.
"""
from __future__ import annotations

KEY_PLAYER_LAYOUT = "player_layout"

PLAYER_LAYOUT_REUNITED = "reunited"
PLAYER_LAYOUT_FRACTURED = "fractured"

PLAYER_LAYOUT_DEFAULT = PLAYER_LAYOUT_REUNITED

PLAYER_LAYOUT_LABELS: tuple[tuple[str, str], ...] = (
    (PLAYER_LAYOUT_REUNITED, "Reunited"),
    (PLAYER_LAYOUT_FRACTURED, "Fractured"),
)

_current_layout: str = PLAYER_LAYOUT_DEFAULT


def normalize_player_layout(value: object | None) -> str:
    raw = str(value or "").strip().lower()
    if raw == PLAYER_LAYOUT_FRACTURED:
        return PLAYER_LAYOUT_FRACTURED
    return PLAYER_LAYOUT_REUNITED


def get_player_layout() -> str:
    return _current_layout


def set_player_layout(layout: object | None) -> str:
    global _current_layout
    _current_layout = normalize_player_layout(layout)
    from steempeg.ui.layout_defaults import sync_player_layout_constants

    sync_player_layout_constants(_current_layout)
    return _current_layout


def load_player_layout_from_settings(settings: dict | None) -> str:
    raw = (settings or {}).get(KEY_PLAYER_LAYOUT, PLAYER_LAYOUT_DEFAULT)
    return set_player_layout(raw)
