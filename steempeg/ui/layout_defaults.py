"""Startup layout — edit values here.

Set REMEMBER_LAYOUT_BETWEEN_SESSIONS = True if you want the app to save panel
sizes when you close it (settings.json in the cache folder). When False (default),
these constants are always used on launch.
"""

REMEMBER_LAYOUT_BETWEEN_SESSIONS = False

# Steam Deck LCD/OLED native resolution — design floor for the main window.
# Layout mins switch to "compact" at or below this class of width.
STEAM_DECK_WIDTH = 1280
STEAM_DECK_HEIGHT = 800
TARGET_MIN_WINDOW_WIDTH = STEAM_DECK_WIDTH
TARGET_MIN_WINDOW_HEIGHT = STEAM_DECK_HEIGHT

# Use compact panel mins when the window is Deck-sized (or a small QEMU window).
COMPACT_LAYOUT_WIDTH = STEAM_DECK_WIDTH + 80  # ~1360

# [Clips Manager width, player + queue area width]
# Comfort left pane fits two grid columns + full toolbar (~620).
# Compact left pane fits one grid column on a 1280px Deck window.
MIN_LEFT_PANEL_WIDTH_COMFORT = 620
MIN_LEFT_PANEL_WIDTH_COMPACT = 360
DEFAULT_MAIN_SPLITTER_SIZES = [MIN_LEFT_PANEL_WIDTH_COMFORT, 100000]
DEFAULT_MAIN_SPLITTER_SIZES_COMPACT = [MIN_LEFT_PANEL_WIDTH_COMPACT, 100000]

# [player area, bottom tabs] vertical split inside the right column
DEFAULT_MAIN_V_SPLITTER_SIZES = [750, 450]
DEFAULT_MAIN_V_SPLITTER_SIZES_COMPACT = [480, 220]

# [player area, render queue] when queue is empty (second value = 0)
DEFAULT_RIGHT_H_SPLITTER_SIZES = [1200, 0]

# Render Queue panel width when the queue is non-empty (list row: thumb + text + ✕)
MIN_QUEUE_PANEL_WIDTH = 420
MIN_QUEUE_PANEL_WIDTH_COMPACT = 280
DEFAULT_QUEUE_PANEL_WIDTH = 420

# "grid" or "list"
DEFAULT_LIBRARY_VIEW = "grid"

# "grid" or "list" — render queue cards
DEFAULT_QUEUE_VIEW = "list"

# Right column chrome — keep in sync with app.py right_layout / right_content_wrap.
RIGHT_PANEL_SIDE_INSET = 12
# Player column runs flush with the left tab row (top) and footer buttons (bottom) —
# no extra deep inset on the center panel (v36 change).
RIGHT_PANEL_BOTTOM_INSET = 0
RIGHT_PANEL_PLAYER_TOP_INSET = 0
QUEUE_SPLITTER_GUTTER = 10
LIBRARY_TAB_TO_TOOLBAR_SPACING = 5  # left_master_layout spacing (tab row → toolbar)
# Queue list sits flush with the left footer (mega_pill); player column keeps RIGHT_PANEL_BOTTOM_INSET.
RENDER_QUEUE_BOTTOM_INSET = 0

# Source Info stat grid width — right edge of settings-tab content ("red line").
SETTINGS_STAT_COL_W = 210
SETTINGS_STAT_GRID_GAP = 8
SETTINGS_CONTENT_WIDTH = SETTINGS_STAT_COL_W * 3 + SETTINGS_STAT_GRID_GAP * 2

# Render settings tab content inset (right pane beside neo sidebar).
SETTINGS_PAGE_MARGIN_LEFT = 16
SETTINGS_PAGE_MARGIN_TOP = 15
SETTINGS_PAGE_MARGIN_RIGHT = 8
SETTINGS_PAGE_MARGIN_BOTTOM = 8

# Horizontal splitters (Clips | editor, editor | queue) — matches Render Queue handle.
HORIZONTAL_SPLITTER_STYLESHEET = """
    QSplitter::handle {
        background-color: #444;
        margin: 0px 2px;
        border-radius: 2px;
    }
    QSplitter::handle:hover {
        background-color: #666;
    }
"""

# Custom title bar (see ui/window_chrome.py) — canonical value in design_tokens.
TITLE_BAR_HEIGHT = 28


def is_compact_layout(window_width: int) -> bool:
    """True when the shell should use Deck-sized panel minimums."""
    return int(window_width or 0) > 0 and int(window_width) <= COMPACT_LAYOUT_WIDTH


def left_panel_min_width(window_width: int) -> int:
    return (
        MIN_LEFT_PANEL_WIDTH_COMPACT
        if is_compact_layout(window_width)
        else MIN_LEFT_PANEL_WIDTH_COMFORT
    )


def queue_panel_min_width(window_width: int) -> int:
    return (
        MIN_QUEUE_PANEL_WIDTH_COMPACT
        if is_compact_layout(window_width)
        else MIN_QUEUE_PANEL_WIDTH
    )
