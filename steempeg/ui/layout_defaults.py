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

# compact=True when layout_scale < 0.5 → width < 1400. Maximized 1080p (~1920)
# and 1440p (~2560) are well above this; compact is for actually-narrow shells
# (Deck, 1280-class, half-screen), not coarse 27″ FHD pixels.
COMPACT_DENSITY_WIDTH = LAYOUT_SCALE_MIN_WIDTH + (LAYOUT_SCALE_MAX_WIDTH - LAYOUT_SCALE_MIN_WIDTH) // 2
# Typical maximized 1080p (taskbar steals height, not width). Hard floor so PPI
# cannot pull this class into compact labels / Deck chrome.
FHD_SHELL_WIDTH = 1920

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
# Comfort bottom tall enough for neo + dash without feeling collapsed.
DEFAULT_MAIN_V_SPLITTER_SIZES = [720, 480]
DEFAULT_MAIN_V_SPLITTER_SIZES_COMPACT = [460, 260]

# Soft ceiling for the Desktop settings dock (player ↔ neo/dash).
MAIN_V_SPLITTER_MAX_BOTTOM_RATIO = 0.38
# HideWatcher / crushed-pane fallback target (~taller than the old 0.28).
MAIN_V_SPLITTER_RESTORE_BOTTOM_RATIO = 0.36

# [player area, render queue] when queue is empty (second value = 0)
DEFAULT_RIGHT_H_SPLITTER_SIZES = [1200, 0]

# Render Queue panel width when the queue is non-empty (list row: thumb + text + ✕).
# Wide enough that toolbar "Clear" and list titles are not crushed.
MIN_QUEUE_PANEL_WIDTH = 380
MIN_QUEUE_PANEL_WIDTH_COMPACT = 320
DEFAULT_QUEUE_PANEL_WIDTH = 380

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
# Clips Manager elevated panel ↔ About/Updates/Settings footer (verticalLayout_left).
# Matches Qt PM_LayoutVerticalSpacing on Windows; pin explicitly so player↔dash can mirror it.
LIBRARY_FOOTER_GAP = 6
# Queue list sits flush with the left footer (mega_pill); player column keeps RIGHT_PANEL_BOTTOM_INSET.
RENDER_QUEUE_BOTTOM_INSET = 0

# Player column stack (canvas ↔ #HudFrame) — runtime; see sync_player_layout_constants().
# Reunited (default): 0 spacing, 4px header canvas gap. Fractured: 8px / 0px.
PLAYER_COLUMN_SPACING = 0
PLAYER_HEADER_CANVAS_GAP = 4
# QSS 1px outline is drawn inside the fixed-height frame; reserve both edges so
# Healthy / Preview / gear / close plaques are not clipped (Reunited top-only
# still needs the extra px — content box shrinks either way).
PLAYER_HEADER_FRAME_BORDER_V = 2

PLAYER_LAYOUT_COLUMN_SPACING_REUNITED = 0
PLAYER_LAYOUT_COLUMN_SPACING_FRACTURED = 8
PLAYER_LAYOUT_HEADER_CANVAS_GAP_REUNITED = 4
PLAYER_LAYOUT_HEADER_CANVAS_GAP_FRACTURED = 0
# Header/footer corner radius (Reunited outer corners + Fractured panel plates).
PLAYER_LAYOUT_PANEL_RADIUS_PX = 6


def sync_player_layout_constants(mode: str) -> str:
    """Update module spacing/gap tokens from ``player_layout`` pref value."""
    from steempeg.ui.player_layout import (
        PLAYER_LAYOUT_FRACTURED,
        normalize_player_layout,
    )

    global PLAYER_COLUMN_SPACING, PLAYER_HEADER_CANVAS_GAP
    applied = normalize_player_layout(mode)
    if applied == PLAYER_LAYOUT_FRACTURED:
        PLAYER_COLUMN_SPACING = PLAYER_LAYOUT_COLUMN_SPACING_FRACTURED
        PLAYER_HEADER_CANVAS_GAP = PLAYER_LAYOUT_HEADER_CANVAS_GAP_FRACTURED
    else:
        PLAYER_COLUMN_SPACING = PLAYER_LAYOUT_COLUMN_SPACING_REUNITED
        PLAYER_HEADER_CANVAS_GAP = PLAYER_LAYOUT_HEADER_CANVAS_GAP_REUNITED
    return applied


def _apply_player_chrome_stylesheets(app, *, immersive: bool, video_bg: str | None) -> None:
    """Header / video / footer QSS only — no density or pill rebake."""
    from PySide6.QtCore import Qt

    from steempeg.ui import ui_theme as ut
    from steempeg.ui.design_tokens import with_tooltip_style

    header = getattr(app, "player_header_frame", None)
    if header is not None:
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setStyleSheet(
            ut.player_header_stylesheet(force_outline=False if immersive else None)
        )

    vw = getattr(app, "video_wrapper", None)
    if vw is not None:
        # Reunited + with-lines: side borders close the chrome outline.
        # Desktop theatre / fullscreen: borderless black fill.
        # Portable theatre: black fill, but outline sides still follow the pref.
        vw.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if immersive:
            vw.setStyleSheet(
                ut.player_video_wrapper_stylesheet(
                    background="black", chrome_outline=False
                )
            )
        elif video_bg is not None:
            vw.setStyleSheet(
                ut.player_video_wrapper_stylesheet(background=video_bg)
            )
        else:
            vw.setStyleSheet(ut.player_video_wrapper_stylesheet())

    hud = getattr(app, "player_footer_frame", None)
    if hud is not None:
        extra = ""
        try:
            from steempeg.app import _PLAYBACK_BUTTONS_QSS

            extra = _PLAYBACK_BUTTONS_QSS
        except Exception:
            pass
        hud.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hud.setStyleSheet(
            with_tooltip_style(
                ut.player_footer_stylesheet(
                    force_outline=False if immersive else None
                )
                + extra
            )
        )


def restore_player_chrome_after_immersive(app) -> None:
    """Fast outline restore after desktop theatre exit (skip density / footer pills)."""
    from steempeg.ui.player_outline import player_outline_immersive

    immersive = player_outline_immersive(app)
    portable = bool(getattr(app, "_portable_shell", False))
    video_bg = "black" if immersive or (
        portable and getattr(app, "is_theater", False)
    ) else None
    _apply_player_chrome_stylesheets(app, immersive=immersive, video_bg=video_bg)


def apply_player_layout_mode(app, mode: str | None = None) -> str:
    """Apply Settings → Visual player layout (Reunited / Fractured) to the shell."""
    from steempeg.ui.player_header_layout import apply_player_header_density
    from steempeg.ui.player_layout import get_player_layout, set_player_layout
    from steempeg.ui.player_outline import player_outline_immersive

    applied = set_player_layout(mode if mode is not None else get_player_layout())

    top_wrap = getattr(app, "top_v_wrap", None)
    if top_wrap is not None:
        lay = top_wrap.layout()
        if lay is not None:
            lay.setSpacing(PLAYER_COLUMN_SPACING)

    dense = getattr(app, "_ui_density_player", None) or getattr(app, "_ui_density", None)
    try:
        apply_player_header_density(app, dense)
    except Exception:
        pass

    immersive = player_outline_immersive(app)
    # Portable keeps is_theater but still paints outline prefs; only the video
    # plane uses a black fill (same as desktop theatre stage).
    portable = bool(getattr(app, "_portable_shell", False))
    video_bg = "black" if immersive or (
        portable and getattr(app, "is_theater", False)
    ) else None

    _apply_player_chrome_stylesheets(app, immersive=immersive, video_bg=video_bg)

    refresh = getattr(app, "_refresh_player_footer_chrome", None)
    if callable(refresh):
        try:
            refresh(dense)
        except Exception:
            pass

    return applied

# Vertical splitter (player ↔ neo/dash) — keep in sync with app.py + render_controller.
# Was 10+10 (thick dark band), then 4+4 (too tight vs left footer). Match LIBRARY_FOOTER_GAP.
MAIN_V_SPLIT_TOP_PAD = LIBRARY_FOOTER_GAP  # top_v_wrap bottom margin (below player footer)
MAIN_V_SPLIT_BOTTOM_PAD = LIBRARY_FOOTER_GAP  # bottom_v_wrap top margin (above neo / dash)
DESKTOP_BOTTOM_PANE_SPACING = 6  # neo ↔ Start/Pause/Cancel dash (Desktop only)
# Like a Portable, middle handle OFF: margin air gap (= clips ↔ About footer).
# Middle handle ON: pads zeroed; handle is the seam (see render_controller).
PORTABLE_LIKE_MIDDLE_GAP = LIBRARY_FOOTER_GAP

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
# Prefer ``horizontal_splitter_handle_qss()`` so TrueDark can lift idle gray.
def horizontal_splitter_handle_qss(
    idle: str = "#444444", hover: str = "#666666"
) -> str:
    return f"""
    QSplitter::handle {{
        background-color: {idle};
        margin: 0px 2px;
        border-radius: 2px;
    }}
    QSplitter::handle:hover {{
        background-color: {hover};
    }}
"""


def vertical_splitter_handle_qss(
    idle: str = "#444444", hover: str = "#b29ae7"
) -> str:
    return f"""
    QSplitter::handle {{
        background-color: {idle};
        margin: 0px 40px;
        border-radius: 2px;
        height: 4px;
    }}
    QSplitter::handle:hover {{
        background-color: {hover};
    }}
"""


HORIZONTAL_SPLITTER_STYLESHEET = horizontal_splitter_handle_qss()

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


def shell_layout_scale(window_width: int, *, widget=None, screen=None) -> float:
    """Width-only shell scale: 0 at Deck (~1280), 1 at ≥1520.

    Compact vs comfort is about whether the *window* is actually small.
    Coarse pixels (24–27″ FHD ~82–92 PPI) used to multiply this ``t`` by
    ``chrome_ppi_scale`` *and* shrink DIP chrome in ``density_for_width`` —
    maximized 1080p looked ~20% squashed. PPI is a separate mild pixel
    shrink; ``widget`` / ``screen`` stay for call-site compatibility.
    """
    _ = (widget, screen)
    w = int(window_width or 0)
    if w >= FHD_SHELL_WIDTH:
        return 1.0
    return layout_scale(window_width)


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


def is_compact_layout(window_width: int, *, widget=None, screen=None) -> bool:
    """True when short labels / compact bool heuristics should win (scale < 0.5).

    Cliff is ``COMPACT_DENSITY_WIDTH`` (~1400). FHD-class width (≥1920) never
    compact. ``widget`` / ``screen`` kept for call-site compatibility.
    """
    _ = (widget, screen)
    w = int(window_width or 0)
    if w <= 0 or w >= FHD_SHELL_WIDTH:
        return False
    return w < COMPACT_DENSITY_WIDTH


def left_panel_min_width(window_width: int, *, widget=None, screen=None) -> int:
    ideal = lerp_int(
        MIN_LEFT_PANEL_WIDTH_COMPACT,
        MIN_LEFT_PANEL_WIDTH_COMFORT,
        shell_layout_scale(window_width, widget=widget, screen=screen),
    )
    win_w = int(window_width or 0)
    if win_w > 0:
        # Hard cap: Clips Manager must not claim more than ~40% of the shell.
        ideal = min(ideal, max(MIN_LEFT_PANEL_WIDTH_COMPACT, int(win_w * 0.40)))
    return max(MIN_LEFT_PANEL_WIDTH_COMPACT, ideal)


def queue_panel_min_width(window_width: int, *, widget=None, screen=None) -> int:
    return lerp_int(
        MIN_QUEUE_PANEL_WIDTH_COMPACT,
        MIN_QUEUE_PANEL_WIDTH,
        shell_layout_scale(window_width, widget=widget, screen=screen),
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
    widget=None,
    screen=None,
) -> int:
    """Queue ``minimumWidth`` that cannot starve Clips Manager or the player.

    When the queue is closed, returns 0 so the nested splitter does not push
    the outer ``main_splitter`` left handle around.
    """
    if not queue_open:
        return 0
    ideal = queue_panel_min_width(window_width, widget=widget, screen=screen)
    left = int(
        left_min
        if left_min is not None
        else left_panel_min_width(window_width, widget=widget, screen=screen)
    )
    win_w = int(window_width or 0)
    if win_w <= 0:
        return ideal
    rest = win_w - left - horizontal_shell_chrome()
    max_q = max(0, rest - PLAYER_COLUMN_FLOOR)
    return min(ideal, max_q)


def queue_panel_open_width(
    window_width: int,
    *,
    total_splitter: int = 0,
    widget=None,
    screen=None,
) -> int:
    """Preferred queue width when opening — lerp mins, capped ~25% of window."""
    t = shell_layout_scale(window_width, widget=widget, screen=screen)
    ideal = lerp_int(MIN_QUEUE_PANEL_WIDTH_COMPACT, DEFAULT_QUEUE_PANEL_WIDTH, t)
    min_q = affordable_queue_min_width(
        window_width, queue_open=True, widget=widget, screen=screen
    )
    win_w = int(window_width or 0)
    max_by_pct = max(min_q, int(win_w * 0.25)) if win_w else ideal
    queue_w = max(min_q, min(ideal, max_by_pct))
    if total_splitter > 0:
        # Keep player column usable; allow shrinking below ideal min if needed.
        floor_q = min(min_q, max(0, total_splitter - PLAYER_COLUMN_FLOOR))
        queue_w = min(queue_w, max(floor_q, total_splitter - PLAYER_COLUMN_FLOOR))
    return max(0, int(queue_w))


def main_v_splitter_max_bottom(window_height: int) -> int:
    """Pixel ceiling for the Desktop bottom dock on the given window height."""
    h = int(window_height or 0)
    if h <= 0:
        return 480
    return max(220, int(h * MAIN_V_SPLITTER_MAX_BOTTOM_RATIO))


def default_main_v_splitter_sizes(
    window_width: int = 0,
    window_height: int = 0,
    *,
    widget=None,
    screen=None,
) -> list[int]:
    """Lerp vertical split defaults; cap bottom pane on short windows."""
    tw = shell_layout_scale(window_width, widget=widget, screen=screen) if window_width else 1.0
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
        max_bottom = main_v_splitter_max_bottom(h)
        if bottom > max_bottom:
            bottom = max_bottom
            top = max(h - bottom, 200)
    return [top, bottom]


def scale_main_v_splitter_sizes(
    sizes,
    splitter_height: int,
    *,
    window_height: int = 0,
) -> list[int]:
    """Map remembered [top, bottom] onto the live splitter height."""
    total = max(int(splitter_height or 0), 1)
    if not sizes or len(sizes) < 2:
        return restore_v_splitter_sizes(total)
    prev_total = max(sum(int(x) for x in sizes[:2]), 1)
    bottom = max(180, int(total * (int(sizes[1]) / prev_total)))
    cap_h = int(window_height or 0) or total
    bottom = min(bottom, main_v_splitter_max_bottom(cap_h))
    bottom = min(bottom, max(total - 200, 1))
    return [total - bottom, bottom]


def restore_v_splitter_sizes(splitter_height: int) -> list[int]:
    """Fallback when HideWatcher has no saved sizes — density-aware, not [750,250]."""
    total = max(int(splitter_height or 0), 1)
    ratio = MAIN_V_SPLITTER_RESTORE_BOTTOM_RATIO
    bottom = min(max(int(total * ratio), 220), main_v_splitter_max_bottom(total))
    bottom = min(bottom, max(total - 200, 1))
    return [total - bottom, bottom]
