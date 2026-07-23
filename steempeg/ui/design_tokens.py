"""Shared Steempeg visual tokens — title bar, sheets, panels."""

# Shell
BG_SHELL = "#1e1e1e"
BG_TITLE_BAR = "#0d0d0d"
# Idle player "Please select a clip…" chip fill (canvas stays #1e1e1e / black).
BG_PLAYER_CANVAS = "#2d2d2d"
BORDER_SUBTLE = "#000000"
BORDER_DEFAULT = "#444444"

# Text
TEXT_PRIMARY = "#cccccc"
TEXT_MUTED = "#858585"
TEXT_TITLE = "#e8e8e8"

# Brand
ACCENT_PRIMARY = "#b29ae7"
ACCENT_HOVER = "#6b5a8e"

# macOS-style window controls
TRAFFIC_CLOSE = "#ff5f57"
TRAFFIC_CLOSE_HOVER = "#ff3b30"
TRAFFIC_MINIMIZE = "#febc2e"
TRAFFIC_MINIMIZE_HOVER = "#e5a500"
TRAFFIC_MAXIMIZE = "#28c840"
TRAFFIC_MAXIMIZE_HOVER = "#1aad2e"

# Typography — FONT_APP matches render panel, About, and queue cards.
# Segoe/Cascadia on Windows; Noto/DejaVu + Twemoji on Linux/SteamOS/Bazzite.
# Twemoji BEFORE DejaVu / Noto Color Emoji: stylesheets that only list Segoe
# paint blank emoji, and COLRv1 Noto Color Emoji is selected then drawn empty by Qt.
_EMOJI = "'Twemoji', 'Noto Emoji', 'Segoe UI Emoji'"
FONT_APP = f"'Segoe UI', 'Noto Sans', {_EMOJI}, 'DejaVu Sans', Arial, sans-serif"
FONT_SEMIBOLD = (
    f"'Segoe UI Semibold', 'Segoe UI', 'Noto Sans', {_EMOJI}, 'DejaVu Sans', Arial, sans-serif"
)
FONT_UI = (
    "'Cascadia UI', 'Segoe UI Variable', 'Segoe UI', "
    f"'Noto Sans', {_EMOJI}, 'DejaVu Sans', sans-serif"
)
# Drop-in CSS fragment for stylesheets that need the emoji-capable stack.
FONT_FAMILY_CSS = f"font-family: {FONT_APP}"
FONT_TITLE_SIZE = 10
FONT_SUBTITLE_SIZE = 10

STYLE_PANEL_TITLE = (
    f"color: {TEXT_TITLE}; font-family: {FONT_APP}; font-size: 20px; font-weight: bold; "
    "background: transparent;"
)
STYLE_PANEL_SUBTITLE = (
    f"color: {TEXT_PRIMARY}; font-family: {FONT_APP}; font-size: 12px; background: transparent;"
)
STYLE_PANEL_HEADING = (
    f"color: {TEXT_TITLE}; font-family: {FONT_APP}; font-size: 18px; font-weight: bold; "
    "background: transparent;"
)

# Legacy aliases (prefer STYLE_PANEL_* in new UI).
STYLE_HEADING = STYLE_PANEL_TITLE.replace("20px", "14px")
STYLE_SUBHEADING = STYLE_PANEL_SUBTITLE

# Layout
TITLE_BAR_HEIGHT = 30

# Experimental chrome color themes.
#   default : current look (near-black title bar over #1e1e1e shell)
#   exp1    : title bar only lifted to #1e1e1e, background unchanged
#   exp2    : darker overall — #222222 title bar over a #141414 background
#   exp3    : lifted bar — #2d2d2d title bar over #1e1e1e background
#   exp4    : lifted bar, dark shell — #2d2d2d title bar over #141414 background
CHROME_THEMES = {
    "default": {"title_bar": BG_TITLE_BAR, "app_bg": BG_SHELL},
    "exp1": {"title_bar": "#1e1e1e", "app_bg": "#1e1e1e"},
    "exp2": {"title_bar": "#222222", "app_bg": "#141414"},
    "exp3": {"title_bar": "#2d2d2d", "app_bg": "#1e1e1e"},
    "exp4": {"title_bar": "#2d2d2d", "app_bg": "#141414"},
}
DEFAULT_CHROME_THEME = "exp2"


def chrome_theme_colors(name: str) -> dict:
    """Return {'title_bar', 'app_bg'} for a theme name (falls back to default)."""
    return CHROME_THEMES.get(name, CHROME_THEMES[DEFAULT_CHROME_THEME])
