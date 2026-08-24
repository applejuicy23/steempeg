"""Player chrome outline preference (Settings → Visual → Player outline).

* ``with_lines`` — stock borders (Reunited seam box / Fractured panel frames).
* ``without_lines`` — no visible chrome outline on header, canvas, or footer.
* ``chrome_only`` — header/footer outlines only; video plane never enclosed.
"""
from __future__ import annotations

KEY_PLAYER_OUTLINE = "player_outline"

PLAYER_OUTLINE_WITH_LINES = "with_lines"
PLAYER_OUTLINE_WITHOUT_LINES = "without_lines"
PLAYER_OUTLINE_CHROME_ONLY = "chrome_only"

PLAYER_OUTLINE_DEFAULT = PLAYER_OUTLINE_WITH_LINES

PLAYER_OUTLINE_LABELS: tuple[tuple[str, str], ...] = (
    (PLAYER_OUTLINE_WITH_LINES, "With lines"),
    (PLAYER_OUTLINE_WITHOUT_LINES, "Without lines"),
    (
        PLAYER_OUTLINE_CHROME_ONLY,
        "With lines, not wrapping the video",
    ),
)

_current_outline: str = PLAYER_OUTLINE_DEFAULT


def normalize_player_outline(value: object | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in (
        PLAYER_OUTLINE_WITHOUT_LINES,
        "none",
        "off",
        "no_lines",
        "without",
    ):
        return PLAYER_OUTLINE_WITHOUT_LINES
    if raw in (
        PLAYER_OUTLINE_CHROME_ONLY,
        "chrome_only",
        "chrome",
        "no_video",
        "not_wrapping",
    ):
        return PLAYER_OUTLINE_CHROME_ONLY
    return PLAYER_OUTLINE_WITH_LINES


def get_player_outline() -> str:
    return _current_outline


def set_player_outline(mode: object | None) -> str:
    global _current_outline
    _current_outline = normalize_player_outline(mode)
    return _current_outline


def load_player_outline_from_settings(settings: dict | None) -> str:
    raw = (settings or {}).get(KEY_PLAYER_OUTLINE, PLAYER_OUTLINE_DEFAULT)
    return set_player_outline(raw)


def player_outline_shows_chrome() -> bool:
    """True when header/footer may draw outline edges."""
    return get_player_outline() != PLAYER_OUTLINE_WITHOUT_LINES


def player_outline_wraps_video() -> bool:
    """True when the video plane closes a Reunited-style side outline."""
    return get_player_outline() == PLAYER_OUTLINE_WITH_LINES


def player_outline_immersive(app) -> bool:
    """True when chrome outlines must hide (fullscreen / desktop theatre).

    Portable reuses ``is_theater`` to collapse docks, but still honors outline prefs
    (otherwise Settings → Outline and stock lines never appear in Portable).
    """
    if getattr(app, "is_fullscreen", False):
        return True
    if getattr(app, "is_theater", False) and not getattr(app, "_portable_shell", False):
        return True
    return False
