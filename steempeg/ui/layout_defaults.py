"""Startup layout — edit values here.

Set REMEMBER_LAYOUT_BETWEEN_SESSIONS = True if you want the app to save panel
sizes when you close it (settings.json in the cache folder). When False (default),
these constants are always used on launch.
"""

REMEMBER_LAYOUT_BETWEEN_SESSIONS = False

# [Clips Manager width, player + queue area width]
DEFAULT_MAIN_SPLITTER_SIZES = [300, 1850]

# [player area, bottom tabs] vertical split inside the right column
DEFAULT_MAIN_V_SPLITTER_SIZES = [750, 450]

# [player area, render queue] when queue is empty (second value = 0)
DEFAULT_RIGHT_H_SPLITTER_SIZES = [1200, 0]

# Render Queue panel width when the queue is non-empty
DEFAULT_QUEUE_PANEL_WIDTH = 300

# "grid" or "list"
DEFAULT_LIBRARY_VIEW = "grid"
