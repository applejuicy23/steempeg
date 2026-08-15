"""Shared Steempeg visual tokens — title bar, sheets, panels."""

# Shell
BG_SHELL = "#1e1e1e"
BG_TITLE_BAR = "#0d0d0d"
# Idle player "Please select a clip…" chip fill (canvas stays #1e1e1e / black).
BG_PLAYER_CANVAS = "#2d2d2d"
# Queue / neo-nav card face — same family as player canvas chips.
BG_CARD = BG_PLAYER_CANVAS
# Render settings content (right of neo-nav) — same family as player chrome / cards.
BG_SETTINGS_PANEL = "#2d2d2d"
# Neo-nav + settings host shared corner radius (stylesheet + QRegion must match).
RADIUS_NEO_PANEL = 20
BORDER_SUBTLE = "#000000"
BORDER_DEFAULT = "#444444"
# Neo-nav ↔ settings divider / card outline.
BORDER_CARD = "#383838"

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

# Canonical hover tip chrome — match Portable title-bar «Check for updates»
# (sampled: bg ≈ #2c2b2e, text ≈ #dcdde2). One style for Desktop + Portable
# + every platform; apply on QApplication. Bold ink — Emily's preferred weight.
TOOLTIP_BG = "#2c2b2e"
TOOLTIP_BORDER = "#5a5a5a"
TOOLTIP_FG = "#dcdde2"
STYLE_TOOLTIP = (
    f"QToolTip {{"
    f" background-color: {TOOLTIP_BG};"
    f" color: {TOOLTIP_FG};"
    f" border: 1px solid {TOOLTIP_BORDER};"
    f" border-radius: 6px;"
    f" padding: 5px 9px;"
    f" font-family: 'Segoe UI', {FONT_APP};"
    f" font-size: 12px;"
    f" font-weight: bold;"
    f"}}"
)


def with_tooltip_style(qss: str = "") -> str:
    """Append canonical tip chrome to a widget-local stylesheet.

    Widgets with their own ``setStyleSheet`` often get a native black Windows tip
    instead of the app-level QToolTip rules. Include STYLE_TOOLTIP in that sheet.
    """
    body = (qss or "").rstrip()
    if "QToolTip" in body:
        return body
    return f"{body}\n{STYLE_TOOLTIP}" if body else STYLE_TOOLTIP


def dialog_scroll_stylesheet(bg: str | None = None) -> str:
    """Opaque scroll fill — never ``transparent`` (Windows light theme leaks in)."""
    color = bg or BG_SHELL
    return (
        f"QScrollArea {{ background-color: {color}; border: none; }}\n"
        f"QScrollArea > QWidget {{ background-color: {color}; }}"
    )


def apply_dialog_scroll_bg(scroll, color: str | None = None) -> None:
    """Force dark QScrollArea + viewport (stylesheet + palette; ignore OS theme)."""
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QFrame

    bg = color or BG_SHELL
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(dialog_scroll_stylesheet(bg))
    vp = scroll.viewport()
    if vp is None:
        return
    vp.setAutoFillBackground(True)
    pal = vp.palette()
    qc = QColor(bg)
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        pal.setColor(group, QPalette.ColorRole.Window, qc)
        pal.setColor(group, QPalette.ColorRole.Base, qc)
    vp.setPalette(pal)


# Trim / Cancel — same language as portable Render (dark fill + bright border).
# Gold idle / red cancel; hover brightens fill + border like ``_RENDER_STYLE``.
# Fill sits closer to the bright border than earlier eclipse-dark gold/red.
STYLE_TRIM_BUTTON = with_tooltip_style(
    "QPushButton {"
    "background-color: #957a35; color: #ffffff;"
    "border: 2px solid #cfa94a; border-radius: 15px;"
    "padding: 0 12px; font-weight: bold;"
    "}"
    "QPushButton:hover { background-color: #b09040; border: 2px solid #e0c06a; }"
    "QPushButton:pressed { background-color: #6b5520; }"
    "QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }"
)

STYLE_TRIM_CANCEL_BUTTON = with_tooltip_style(
    "QPushButton {"
    "background-color: #a52c2c; color: #ffffff;"
    "border: 2px solid #ff4444; border-radius: 15px;"
    "padding: 0 12px; font-weight: bold;"
    "}"
    "QPushButton:hover { background-color: #c03838; border: 2px solid #ff6666; }"
    "QPushButton:pressed { background-color: #6e1a1a; }"
    "QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }"
)


def apply_app_tooltip_style(app=None) -> None:
    """Force the shared QToolTip chrome on the QApplication (all shells/platforms).

    Window-level stylesheets do not reliably style tip popups (separate HWND).
    Palette + ``QToolTip.setFont`` keep fill/ink/weight consistent even when
    Windows paints a native black tip for some widgets.
    """
    from PySide6.QtGui import QColor, QFont, QPalette
    from PySide6.QtWidgets import QApplication, QToolTip

    target = app or QApplication.instance()
    if target is None:
        return
    current = target.styleSheet() or ""
    import re

    cleaned = re.sub(
        r"/\* steempeg-tooltip \*/.*?QToolTip\s*\{[^}]*\}",
        "",
        current,
        flags=re.DOTALL,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    block = f"/* steempeg-tooltip */\n{STYLE_TOOLTIP}"
    target.setStyleSheet(f"{cleaned}\n{block}" if cleaned else block)

    tip_bg = QColor(TOOLTIP_BG)
    tip_fg = QColor(TOOLTIP_FG)
    palette = target.palette()
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, tip_bg)
        palette.setColor(group, QPalette.ColorRole.ToolTipText, tip_fg)
    target.setPalette(palette)

    tip_font = QFont("Segoe UI", 12)
    tip_font.setWeight(QFont.Weight.Bold)
    tip_font.setStyleHint(QFont.StyleHint.SansSerif)
    QToolTip.setFont(tip_font)


# Legacy aliases (prefer STYLE_PANEL_* in new UI).
STYLE_HEADING = STYLE_PANEL_TITLE.replace("20px", "14px")
STYLE_SUBHEADING = STYLE_PANEL_SUBTITLE

# Whole-card press (ScreenshotPhoto / ClipCard) — scale about center while held.
CARD_PRESS_SCALE = 0.94
CARD_PRESS_DURATION_MS = 75

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
