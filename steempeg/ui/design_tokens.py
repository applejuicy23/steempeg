"""Shared Steempeg visual tokens — title bar, sheets, panels."""

from __future__ import annotations

from pathlib import Path

import sys as _sys

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
#
# UI font preference (Settings → UI font, Selawik install, apply_ui_font_preference)
# is **Linux-only**. Windows always uses the classic Segoe-first stack and ignores
# ``ui_font`` in settings.json.
#
# Linux Auto: real Segoe UI files if present, else bundled Selawik (OFL).
# Latin fallbacks: Inter → Liberation Sans → Adwaita → Noto → DejaVu.
#
# Emoji (Linux): Twemoji (CBDT color) first. Never list Noto Color Emoji —
# Fedora/Bazzite ship COLRv1 which Qt paints blank. Mono Noto Emoji last-resort.
# Process-local fontconfig in linux_desktop.py also demotes COLRv1.
# Windows emoji stays Segoe UI Emoji via the OS.
_EMOJI_FAMILIES: tuple[str, ...] = (
    "Twemoji",
    "Noto Emoji",
    "Segoe UI Emoji",
)
_LATIN_FALLBACKS: tuple[str, ...] = (
    "Inter",
    "Liberation Sans",
    "Adwaita Sans",
    "Noto Sans",
)

KEY_UI_FONT = "ui_font"
UI_FONT_AUTO = "auto"
UI_FONT_SEGOE = "segoe"
UI_FONT_SELAWIK = "selawik"
UI_FONT_SYSTEM = "system"
UI_FONT_DEFAULT = UI_FONT_AUTO

UI_FONT_LABELS: tuple[tuple[str, str], ...] = (
    (UI_FONT_AUTO, "Auto (Segoe if available, else Selawik)"),
    (UI_FONT_SEGOE, "Segoe UI"),
    (UI_FONT_SELAWIK, "Selawik"),
    (UI_FONT_SYSTEM, "System default"),
)

FAMILY_SEGOE = "Segoe UI"
FAMILY_SELAWIK = "Selawik"

_ui_font_pref: str = UI_FONT_DEFAULT
_ui_font_system: bool = False
_selawik_qt_loaded: bool = False


def ui_font_preference_supported() -> bool:
    """True when Settings → UI font / Selawik preference applies (Linux only)."""
    return _sys.platform.startswith("linux")


# Tail after the primary face. Linux default primary is Selawik — fontconfig often
# aliases "Segoe UI" to Adwaita/Noto without shipping Segoe files.
_TAIL_FAMILIES: tuple[str, ...] = (
    *_LATIN_FALLBACKS,
    *_EMOJI_FAMILIES,
    "DejaVu Sans",
    "Arial",
)
# Windows / non-Linux: classic Segoe-first (no Selawik, no ui_font switching).
FONT_FAMILIES: tuple[str, ...] = (
    (FAMILY_SELAWIK, FAMILY_SEGOE, *_TAIL_FAMILIES)
    if ui_font_preference_supported()
    else (FAMILY_SEGOE, *_TAIL_FAMILIES)
)
FONT_UI_FAMILIES: tuple[str, ...] = (
    "Cascadia UI",
    "Segoe UI Variable",
    *FONT_FAMILIES,
)


def _css_families(*names: str, generic: str | None = "sans-serif") -> str:
    parts = [f"'{n}'" for n in names]
    if generic:
        parts.append(generic)
    return ", ".join(parts)


FONT_APP = _css_families(*FONT_FAMILIES)
FONT_SEMIBOLD = _css_families("Segoe UI Semibold", "Selawik Semibold", *FONT_FAMILIES)
FONT_UI = _css_families(*FONT_UI_FAMILIES)
# Drop-in CSS fragment for stylesheets that need the emoji-capable stack.
FONT_FAMILY_CSS = f"font-family: {FONT_APP}"
FONT_TITLE_SIZE = 10
FONT_SUBTITLE_SIZE = 10


def font_family_css() -> str:
    """Live ``font-family: …`` stack (read ``tok.FONT_APP`` / this helper at use time)."""
    return FONT_FAMILY_CSS


def normalize_ui_font(value: object | None) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "auto": UI_FONT_AUTO,
        "segoe": UI_FONT_SEGOE,
        "segoe ui": UI_FONT_SEGOE,
        "selawik": UI_FONT_SELAWIK,
        "system": UI_FONT_SYSTEM,
        "system default": UI_FONT_SYSTEM,
        "default": UI_FONT_AUTO,
    }
    return aliases.get(raw, UI_FONT_DEFAULT)


def _file_looks_like_segoe(path: str) -> bool:
    name = Path(path).name.lower()
    return "segoe" in name or name.startswith("segui")


def segoe_ui_available() -> bool:
    """True when a real Segoe UI font file exists (not a fontconfig alias)."""
    if not ui_font_preference_supported():
        try:
            from PySide6.QtGui import QFontDatabase

            return FAMILY_SEGOE in QFontDatabase.families()
        except Exception:
            return True
    try:
        import subprocess

        proc = subprocess.run(
            ["fc-match", "-f", "%{file}", "Segoe UI"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        path = (proc.stdout or "").strip()
        if path and _file_looks_like_segoe(path):
            return True
    except Exception:
        pass
    search_roots = (
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".local" / "share" / "fonts",
        Path.home() / ".fonts",
    )
    try:
        for root in search_roots:
            if not root.is_dir():
                continue
            for p in root.rglob("*"):
                if p.is_file() and _file_looks_like_segoe(str(p)):
                    return True
    except Exception:
        pass
    return False


def register_bundled_selawik_fonts() -> str:
    """Load bundled Selawik TTFs into this process via QFontDatabase.

    Linux only. Resolves the real family name (usually ``Selawik``). User-dir
    install in ``linux_desktop`` remains for other apps; this makes first launch
    work without a restart / fc-cache. No-op on Windows.
    """
    global FAMILY_SELAWIK, _selawik_qt_loaded
    if not ui_font_preference_supported():
        return FAMILY_SELAWIK
    if _selawik_qt_loaded:
        return FAMILY_SELAWIK
    try:
        from PySide6.QtGui import QFontDatabase

        from steempeg.infra.linux_desktop import bundled_selawik_dir, user_selawik_fonts_dir
    except Exception:
        return FAMILY_SELAWIK

    dirs: list[Path] = []
    bundled = bundled_selawik_dir()
    if bundled is not None:
        dirs.append(bundled)
    user_dir = user_selawik_fonts_dir()
    if user_dir.is_dir():
        dirs.append(user_dir)

    families: list[str] = []
    seen: set[str] = set()
    for folder in dirs:
        for ttf in sorted(folder.glob("*.ttf")):
            try:
                fid = QFontDatabase.addApplicationFont(str(ttf))
            except Exception:
                continue
            if fid < 0:
                continue
            try:
                names = QFontDatabase.applicationFontFamilies(fid)
            except Exception:
                names = []
            for name in names:
                if name and name not in seen:
                    seen.add(name)
                    families.append(name)
        if families:
            break

    _selawik_qt_loaded = True
    if families:
        preferred = next((n for n in families if n.lower() == "selawik"), families[0])
        FAMILY_SELAWIK = preferred
    return FAMILY_SELAWIK


def _rebuild_font_css() -> None:
    global FONT_APP, FONT_SEMIBOLD, FONT_UI, FONT_FAMILY_CSS, FONT_UI_FAMILIES
    global STYLE_PANEL_TITLE, STYLE_PANEL_SUBTITLE, STYLE_PANEL_HEADING
    global STYLE_HEADING, STYLE_SUBHEADING
    FONT_UI_FAMILIES = (
        "Cascadia UI",
        "Segoe UI Variable",
        *FONT_FAMILIES,
    )
    FONT_APP = _css_families(*FONT_FAMILIES)
    FONT_SEMIBOLD = _css_families("Segoe UI Semibold", "Selawik Semibold", *FONT_FAMILIES)
    FONT_UI = _css_families(*FONT_UI_FAMILIES)
    FONT_FAMILY_CSS = f"font-family: {FONT_APP}"
    try:
        STYLE_PANEL_TITLE
    except NameError:
        return
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
    STYLE_HEADING = STYLE_PANEL_TITLE.replace("20px", "14px")
    STYLE_SUBHEADING = STYLE_PANEL_SUBTITLE


def _system_ui_family() -> str:
    """Linux system sans — visibly different from Selawik / phantom Segoe aliases."""
    blocked = {"segoe ui", "selawik"}
    try:
        from PySide6.QtGui import QFont, QFontDatabase

        # Prefer Qt's platform default when it is not our branded faces.
        name = (QFont().defaultFamily() or "").strip()
        if name and name.lower() not in blocked:
            return name
        families = set(QFontDatabase.families())
        for candidate in (
            "Adwaita Sans",
            "Noto Sans",
            "Liberation Sans",
            "Ubuntu",
            "Cantarell",
            "DejaVu Sans",
        ):
            if candidate in families:
                return candidate
    except Exception:
        pass
    return "sans-serif"


def resolve_ui_font_families(pref: str | None = None) -> tuple[str, ...]:
    """Latin + emoji stack for the given preference (does not mutate globals).

    Linux only. Auto = real Segoe if files exist, else Selawik. Selawik forces
    Selawik. System uses the desktop sans (Adwaita/Noto/…) — visibly different.
    """
    if not ui_font_preference_supported():
        return (FAMILY_SEGOE, *_TAIL_FAMILIES)
    choice = normalize_ui_font(pref)
    tail = _TAIL_FAMILIES
    segoe = segoe_ui_available()
    if choice == UI_FONT_SYSTEM:
        # Real system face first — never emoji-only (QSS would paint Twemoji as UI).
        return (_system_ui_family(), *tail)
    if choice == UI_FONT_SEGOE:
        # Prefer Segoe only when real files exist; otherwise Selawik (not a phantom alias).
        primary = (FAMILY_SEGOE, FAMILY_SELAWIK) if segoe else (FAMILY_SELAWIK, FAMILY_SEGOE)
    elif choice == UI_FONT_SELAWIK:
        primary = (FAMILY_SELAWIK, FAMILY_SEGOE)
    else:
        # Auto: real Segoe if present, else Selawik.
        primary = (FAMILY_SEGOE, FAMILY_SELAWIK) if segoe else (FAMILY_SELAWIK, FAMILY_SEGOE)
    return (*primary, *tail)


def peek_saved_ui_font() -> str:
    """Read ``ui_font`` from settings.json (Linux only; Windows always Auto/Segoe)."""
    if not ui_font_preference_supported():
        return UI_FONT_DEFAULT
    try:
        from pathlib import Path

        from steempeg.infra.paths import get_save_directory

        path = Path(get_save_directory()) / "cache" / "settings.json"
        if path.is_file():
            import json

            blob = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(blob, dict):
                return normalize_ui_font(blob.get(KEY_UI_FONT))
    except Exception:
        pass
    return UI_FONT_DEFAULT


def apply_ui_font_preference(pref: str | None = None, *, app=None) -> str:
    """Rebuild FONT_* tokens and QApplication font. Returns the normalized pref.

    On Linux: honors Auto / Segoe / Selawik / System. On Windows: always classic
    Segoe-first and ignores ``pref`` / settings ``ui_font``.
    """
    global FONT_FAMILIES, _ui_font_pref, _ui_font_system

    if not ui_font_preference_supported():
        _ui_font_pref = UI_FONT_DEFAULT
        _ui_font_system = False
        FONT_FAMILIES = (FAMILY_SEGOE, *_TAIL_FAMILIES)
        _rebuild_font_css()
    else:
        register_bundled_selawik_fonts()
        choice = normalize_ui_font(pref if pref is not None else peek_saved_ui_font())
        _ui_font_pref = choice
        _ui_font_system = choice == UI_FONT_SYSTEM
        FONT_FAMILIES = resolve_ui_font_families(choice)
        _rebuild_font_css()

    from PySide6.QtWidgets import QApplication

    target = app or QApplication.instance()
    if target is not None:
        # Always pin via FONT_FAMILIES. Bare QFont() copies the *current* app
        # font under Qt — so System would stick on the previous Selawik face.
        target.setFont(ui_qfont(10))
        try:
            apply_app_tooltip_style(target)
        except Exception:
            pass
    return _ui_font_pref


def pin_ui_font(font, *, point_size: int | None = None, pixel_size: int | None = None, weight=None):
    """Retarget an existing QFont to the active UI stack (keeps size/weight unless set).

    Prefer this over ``setFamily("Segoe UI")`` — on Linux Segoe is often a
    fontconfig alias that paints Adwaita/Noto. On Windows this just pins Segoe.
    """
    from PySide6.QtGui import QFont

    if font is None:
        font = QFont()
    font.setFamilies(list(FONT_FAMILIES))
    if pixel_size is not None:
        font.setPixelSize(int(pixel_size))
    elif point_size is not None:
        font.setPointSize(int(point_size))
    if weight is not None:
        font.setWeight(weight)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    if ui_font_preference_supported():
        try:
            font.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
        except Exception:
            pass
    return font


def ui_qfont(point_size: int = 10, *, pixel_size: int | None = None, weight=None):
    """Application UI QFont using the active FONT_FAMILIES stack."""
    from PySide6.QtGui import QFont

    return pin_ui_font(QFont(), point_size=point_size, pixel_size=pixel_size, weight=weight)

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

# Canonical hover tip chrome — theme-aware (synced from ``ui_theme``).
# Default: light plate + dark ink. TrueDark / OLED: near-black + light ink.
# Apply on QApplication via ``apply_app_tooltip_style``. Bold ink.
TOOLTIP_BG = "#f0f0f0"
TOOLTIP_BORDER = "#c8c8c8"
TOOLTIP_FG = "#1a1a1a"
STYLE_TOOLTIP = (
    f"QToolTip {{"
    f" background-color: {TOOLTIP_BG};"
    f" color: {TOOLTIP_FG};"
    f" border: 1px solid {TOOLTIP_BORDER};"
    f" border-radius: 6px;"
    f" padding: 5px 9px;"
    f" font-family: {FONT_APP};"
    f" font-size: 12px;"
    f" font-weight: bold;"
    f"}}"
)

_TOOLTIP_QSS_RE = None


def _strip_tooltip_qss(qss: str) -> str:
    """Remove any QToolTip { … } block so theme refresh can re-append current tokens."""
    global _TOOLTIP_QSS_RE
    import re

    if _TOOLTIP_QSS_RE is None:
        _TOOLTIP_QSS_RE = re.compile(r"QToolTip\s*\{[^}]*\}", re.DOTALL)
    return _TOOLTIP_QSS_RE.sub("", qss or "").rstrip()


def with_tooltip_style(qss: str = "") -> str:
    """Append canonical tip chrome to a widget-local stylesheet.

    Widgets with their own ``setStyleSheet`` often get a native black Windows tip
    instead of the app-level QToolTip rules. Include STYLE_TOOLTIP in that sheet.
    Always replaces any existing QToolTip block so theme switches stay current.
    """
    body = _strip_tooltip_qss(qss or "")
    return f"{body}\n{STYLE_TOOLTIP}" if body else STYLE_TOOLTIP


def reattach_tooltip_style(widget) -> None:
    """Re-bake current ``STYLE_TOOLTIP`` onto a widget that already has local QSS."""
    if widget is None:
        return
    try:
        widget.setStyleSheet(with_tooltip_style(widget.styleSheet() or ""))
    except RuntimeError:
        pass


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
_TRIM_BUTTON_BODY = (
    "QPushButton {"
    "background-color: #957a35; color: #ffffff;"
    "border: 2px solid #cfa94a; border-radius: 15px;"
    "padding: 0 12px; font-weight: bold;"
    "}"
    "QPushButton:hover { background-color: #b09040; border: 2px solid #e0c06a; }"
    "QPushButton:pressed { background-color: #6b5520; }"
    "QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }"
)
_TRIM_CANCEL_BUTTON_BODY = (
    "QPushButton {"
    "background-color: #a52c2c; color: #ffffff;"
    "border: 2px solid #ff4444; border-radius: 15px;"
    "padding: 0 12px; font-weight: bold;"
    "}"
    "QPushButton:hover { background-color: #c03838; border: 2px solid #ff6666; }"
    "QPushButton:pressed { background-color: #6e1a1a; }"
    "QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }"
)
STYLE_TRIM_BUTTON = with_tooltip_style(_TRIM_BUTTON_BODY)
STYLE_TRIM_CANCEL_BUTTON = with_tooltip_style(_TRIM_CANCEL_BUTTON_BODY)


def _rebuild_trim_button_styles() -> None:
    global STYLE_TRIM_BUTTON, STYLE_TRIM_CANCEL_BUTTON
    STYLE_TRIM_BUTTON = with_tooltip_style(_TRIM_BUTTON_BODY)
    STYLE_TRIM_CANCEL_BUTTON = with_tooltip_style(_TRIM_CANCEL_BUTTON_BODY)


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
    try:
        from steempeg.ui import ui_theme as ut

        tip_qss = ut.tooltip_stylesheet()
    except Exception:
        tip_qss = STYLE_TOOLTIP
    block = f"/* steempeg-tooltip */\n{tip_qss}"
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

    tip_font = ui_qfont(12, weight=QFont.Weight.Bold)
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


def sync_from_ui_theme(palette) -> None:
    """Push active :class:`~steempeg.ui.ui_theme.UiThemePalette` into module tokens."""
    global BG_SHELL, BG_TITLE_BAR, BG_PLAYER_CANVAS, BG_CARD, BG_SETTINGS_PANEL
    global BORDER_SUBTLE, BORDER_DEFAULT, BORDER_CARD
    global TOOLTIP_BG, TOOLTIP_BORDER, TOOLTIP_FG, STYLE_TOOLTIP

    BG_SHELL = palette.bg_shell
    BG_TITLE_BAR = palette.chrome_title_bar
    BG_PLAYER_CANVAS = palette.bg_player_canvas
    BG_CARD = palette.bg_card
    BG_SETTINGS_PANEL = palette.bg_settings_panel
    BORDER_SUBTLE = palette.border_subtle
    BORDER_DEFAULT = palette.border_default
    BORDER_CARD = palette.border_card
    TOOLTIP_BG = palette.tooltip_bg
    TOOLTIP_BORDER = palette.tooltip_border
    TOOLTIP_FG = palette.tooltip_fg
    # Prefer ui_theme builder so QSS stays one source of truth.
    try:
        from steempeg.ui import ui_theme as ut

        STYLE_TOOLTIP = ut.tooltip_stylesheet()
    except Exception:
        STYLE_TOOLTIP = (
            f"QToolTip {{"
            f" background-color: {TOOLTIP_BG};"
            f" color: {TOOLTIP_FG};"
            f" border: 1px solid {TOOLTIP_BORDER};"
            f" border-radius: 6px;"
            f" padding: 5px 9px;"
            f" font-family: {FONT_APP};"
            f" font-size: 12px;"
            f" font-weight: bold;"
            f"}}"
        )
    _rebuild_trim_button_styles()
