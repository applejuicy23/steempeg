"""Shared Steempeg visual tokens — title bar, sheets, panels."""

# Shell
BG_SHELL = "#1e1e1e"
BG_TITLE_BAR = "#0d0d0d"
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

# Typography
FONT_UI = "'Cascadia UI', 'Segoe UI Variable', 'Segoe UI', sans-serif"
FONT_TITLE_SIZE = 10
FONT_SUBTITLE_SIZE = 10

# Layout
TITLE_BAR_HEIGHT = 30

# Experimental chrome color themes.
#   default : current look (near-black title bar over #1e1e1e shell)
#   exp1    : title bar only lifted to #1e1e1e, background unchanged
#   exp2    : darker overall — #222222 title bar over a #141414 background
CHROME_THEMES = {
    "default": {"title_bar": BG_TITLE_BAR, "app_bg": BG_SHELL},
    "exp1": {"title_bar": "#1e1e1e", "app_bg": "#1e1e1e"},
    "exp2": {"title_bar": "#222222", "app_bg": "#141414"},
}
DEFAULT_CHROME_THEME = "exp2"


def chrome_theme_colors(name: str) -> dict:
    """Return {'title_bar', 'app_bg'} for a theme name (falls back to default)."""
    return CHROME_THEMES.get(name, CHROME_THEMES[DEFAULT_CHROME_THEME])
