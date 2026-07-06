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
