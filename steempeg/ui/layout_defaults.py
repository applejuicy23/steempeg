"""Startup layout — edit values here.

Set REMEMBER_LAYOUT_BETWEEN_SESSIONS = True if you want the app to save panel
sizes when you close it (settings.json in the cache folder). When False (default),
these constants are always used on launch.
"""

REMEMBER_LAYOUT_BETWEEN_SESSIONS = False

# Steam Deck LCD/OLED native resolution — design floor for the main window.
STEAM_DECK_WIDTH = 1280
STEAM_DECK_HEIGHT = 800
TARGET_MIN_WINDOW_WIDTH = STEAM_DECK_WIDTH
TARGET_MIN_WINDOW_HEIGHT = STEAM_DECK_HEIGHT

# Continuous layout scale: t=0 at Deck width, t=1 at comfort width and above.
LAYOUT_SCALE_MIN_WIDTH = STEAM_DECK_WIDTH  # full compact
LAYOUT_SCALE_MAX_WIDTH = 1520  # full comfort
LAYOUT_SCALE_MIN_HEIGHT = STEAM_DECK_HEIGHT
LAYOUT_SCALE_MAX_HEIGHT = 960

# Legacy cliff alias (~1360). Prefer layout_scale(); kept for call sites / docs.
COMPACT_LAYOUT_WIDTH = STEAM_DECK_WIDTH + 80

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


def clamp01(t: float) -> float:
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return float(t)


def lerp_int(a: int, b: int, t: float) -> int:
    """Interpolate integers; t=0 → a (compact), t=1 → b (comfort)."""
    return int(round(a + (b - a) * clamp01(t)))


def layout_scale(window_width: int) -> float:
    """Continuous shell scale: 0.0 = Deck compact, 1.0 = desktop comfort."""
    w = int(window_width or 0)
    if w <= 0:
        return 1.0
    if w <= LAYOUT_SCALE_MIN_WIDTH:
        return 0.0
    if w >= LAYOUT_SCALE_MAX_WIDTH:
        return 1.0
    return (w - LAYOUT_SCALE_MIN_WIDTH) / (LAYOUT_SCALE_MAX_WIDTH - LAYOUT_SCALE_MIN_WIDTH)


def height_layout_scale(window_height: int) -> float:
    """Vertical scale for bottom-pane caps; 0.0 at Deck height, 1.0 at comfort."""
    h = int(window_height or 0)
    if h <= 0:
        return 1.0
    if h <= LAYOUT_SCALE_MIN_HEIGHT:
        return 0.0
    if h >= LAYOUT_SCALE_MAX_HEIGHT:
        return 1.0
    return (h - LAYOUT_SCALE_MIN_HEIGHT) / (LAYOUT_SCALE_MAX_HEIGHT - LAYOUT_SCALE_MIN_HEIGHT)


def is_compact_layout(window_width: int) -> bool:
    """True when short labels / compact bool heuristics should win (scale < 0.5)."""
    return layout_scale(window_width) < 0.5


def left_panel_min_width(window_width: int) -> int:
    return lerp_int(
        MIN_LEFT_PANEL_WIDTH_COMPACT,
        MIN_LEFT_PANEL_WIDTH_COMFORT,
        layout_scale(window_width),
    )


def queue_panel_min_width(window_width: int) -> int:
    return lerp_int(
        MIN_QUEUE_PANEL_WIDTH_COMPACT,
        MIN_QUEUE_PANEL_WIDTH,
        layout_scale(window_width),
    )


# Soft floor for the player/settings column inside right_h_splitter.
PLAYER_COLUMN_FLOOR = 360


def horizontal_shell_chrome() -> int:
    """Non-content horizontal chrome (side insets + queue gutter + handle)."""
    return RIGHT_PANEL_SIDE_INSET * 2 + QUEUE_SPLITTER_GUTTER + 6


def affordable_queue_min_width(
    window_width: int,
    *,
    left_min: int | None = None,
    queue_open: bool = True,
) -> int:
    """Queue ``minimumWidth`` that cannot starve Clips Manager or the player.

    When the queue is closed, returns 0 so the nested splitter does not push
    the outer ``main_splitter`` left handle around.
    """
    if not queue_open:
        return 0
    ideal = queue_panel_min_width(window_width)
    left = int(left_min if left_min is not None else left_panel_min_width(window_width))
    win_w = int(window_width or 0)
    if win_w <= 0:
        return ideal
    rest = win_w - left - horizontal_shell_chrome()
    max_q = max(0, rest - PLAYER_COLUMN_FLOOR)
    return min(ideal, max_q)


def queue_panel_open_width(window_width: int, *, total_splitter: int = 0) -> int:
    """Preferred queue width when opening — lerp mins, capped ~25% of window."""
    t = layout_scale(window_width)
    ideal = lerp_int(MIN_QUEUE_PANEL_WIDTH_COMPACT, DEFAULT_QUEUE_PANEL_WIDTH, t)
    min_q = affordable_queue_min_width(window_width, queue_open=True)
    win_w = int(window_width or 0)
    max_by_pct = max(min_q, int(win_w * 0.25)) if win_w else ideal
    queue_w = max(min_q, min(ideal, max_by_pct))
    if total_splitter > 0:
        # Keep player column usable; allow shrinking below ideal min if needed.
        floor_q = min(min_q, max(0, total_splitter - PLAYER_COLUMN_FLOOR))
        queue_w = min(queue_w, max(floor_q, total_splitter - PLAYER_COLUMN_FLOOR))
    return max(0, int(queue_w))


def default_main_v_splitter_sizes(
    window_width: int = 0,
    window_height: int = 0,
) -> list[int]:
    """Lerp vertical split defaults; cap bottom pane on short windows."""
    tw = layout_scale(window_width) if window_width else 1.0
    th = height_layout_scale(window_height) if window_height else 1.0
    t = min(tw, th)
    top = lerp_int(
        DEFAULT_MAIN_V_SPLITTER_SIZES_COMPACT[0],
        DEFAULT_MAIN_V_SPLITTER_SIZES[0],
        t,
    )
    bottom = lerp_int(
        DEFAULT_MAIN_V_SPLITTER_SIZES_COMPACT[1],
        DEFAULT_MAIN_V_SPLITTER_SIZES[1],
        t,
    )
    h = int(window_height or 0)
    if h > 0:
        max_bottom = max(180, int(h * 0.35))
        if bottom > max_bottom:
            bottom = max_bottom
            top = max(h - bottom, 200)
    return [top, bottom]


def restore_v_splitter_sizes(splitter_height: int) -> list[int]:
    """Fallback when HideWatcher has no saved sizes — density-aware, not [750,250]."""
    total = max(int(splitter_height or 0), 1)
    bottom = min(max(int(total * 0.28), 180), int(total * 0.35))
    bottom = min(bottom, max(total - 200, 1))
    return [total - bottom, bottom]
