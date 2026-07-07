"""Startup layout — edit values here.

Set REMEMBER_LAYOUT_BETWEEN_SESSIONS = True if you want the app to save panel
sizes when you close it (settings.json in the cache folder). When False (default),
these constants are always used on launch.
"""

REMEMBER_LAYOUT_BETWEEN_SESSIONS = False

# [Clips Manager width, player + queue area width]
# Left pane is clamped to a 620px minimum (two grid columns + full toolbar) in app.py.
# QSplitter.setSizes distributes proportionally, so the oversized second value forces
# the left pane down to its 620 minimum on launch (the compact 2-column look) while the
# player area soaks up the rest, regardless of monitor width / DPI.
DEFAULT_MAIN_SPLITTER_SIZES = [620, 100000]

# [player area, bottom tabs] vertical split inside the right column
DEFAULT_MAIN_V_SPLITTER_SIZES = [750, 450]

# [player area, render queue] when queue is empty (second value = 0)
DEFAULT_RIGHT_H_SPLITTER_SIZES = [1200, 0]

# Render Queue panel width when the queue is non-empty (list row: thumb + text + ✕)
MIN_QUEUE_PANEL_WIDTH = 420
DEFAULT_QUEUE_PANEL_WIDTH = 420

# "grid" or "list"
DEFAULT_LIBRARY_VIEW = "grid"

# "grid" or "list" — render queue cards
DEFAULT_QUEUE_VIEW = "list"

# Right column chrome — keep in sync with app.py right_layout / right_content_wrap.
RIGHT_PANEL_SIDE_INSET = 12
RIGHT_PANEL_BOTTOM_INSET = 12
RIGHT_PANEL_PLAYER_TOP_INSET = 12  # player only; queue tab row aligns with Clips Manager
QUEUE_SPLITTER_GUTTER = 10
LIBRARY_TAB_TO_TOOLBAR_SPACING = 5  # left_master_layout spacing (tab row → toolbar)
# Queue list sits flush with the left footer (mega_pill); player column keeps RIGHT_PANEL_BOTTOM_INSET.
RENDER_QUEUE_BOTTOM_INSET = 0

# Source Info stat grid width — right edge of settings-tab content ("red line").
SETTINGS_STAT_COL_W = 210
SETTINGS_STAT_GRID_GAP = 8
SETTINGS_CONTENT_WIDTH = SETTINGS_STAT_COL_W * 3 + SETTINGS_STAT_GRID_GAP * 2

# Render settings tab content inset (right pane beside neo sidebar).
# Top aligns with sidebar nav top inset; left adds breathing room from the divider.
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

# Custom title bar (see ui/window_chrome.py) — keep in sync with design_tokens.
TITLE_BAR_HEIGHT = 36
