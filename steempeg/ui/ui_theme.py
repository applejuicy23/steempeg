"""Steempeg UI theme family — Default, TrueDark, TrueDark OLED.

Central palette definitions; ``apply_ui_theme`` syncs ``design_tokens`` and
returns chrome colors for the main window shell.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from steempeg.ui import design_tokens as tok

KEY_UI_THEME = "ui_theme"

UI_THEME_DEFAULT = "default"
UI_THEME_TRUE_DARK = "truedark"
UI_THEME_TRUE_DARK_OLED = "truedark_oled"

UI_THEME_LABELS: tuple[tuple[str, str], ...] = (
    (UI_THEME_DEFAULT, "Default"),
    (UI_THEME_TRUE_DARK, "TrueDark"),
    (UI_THEME_TRUE_DARK_OLED, "TrueDark OLED"),
)


@dataclass(frozen=True)
class UiThemePalette:
    """Full surface palette for one UI theme."""

    name: str
    chrome_title_bar: str
    chrome_app_bg: str
    bg_shell: str
    bg_player_canvas: str
    bg_card: str
    bg_settings_panel: str
    bg_player_header: str
    bg_placeholder_canvas: str
    bg_elevated: str
    border_card: str
    border_panel: str
    border_default: str
    border_subtle: str
    tooltip_bg: str
    tooltip_border: str
    tooltip_fg: str
    neo_nav_hover_bg: str
    neo_nav_checked_bg: str
    neo_nav_idle: str
    neo_nav_hover_border: str
    neo_nav_checked_border: str
    settings_btn_bg: str
    settings_btn_border: str
    settings_btn_hover_bg: str
    settings_btn_pressed_bg: str
    button_secondary_bg: str
    button_secondary_border: str
    button_secondary_hover_bg: str
    button_secondary_pressed_bg: str
    button_disabled_bg: str
    button_disabled_border: str
    bg_player_footer: str
    bg_timeline_strip: str
    bg_clip_card_footer: str
    bg_clip_card_plate: str
    bg_library_toolbar: str
    bg_library_tab: str
    bg_view_toggle_track: str
    border_library_tab_idle: str
    border_library_tab_hover: str


# Default — matches shipped look (exp2 chrome + current token family).
_PALETTE_DEFAULT = UiThemePalette(
    name=UI_THEME_DEFAULT,
    chrome_title_bar="#222222",
    chrome_app_bg="#141414",
    bg_shell="#1e1e1e",
    bg_player_canvas="#2d2d2d",
    bg_card="#2d2d2d",
    bg_settings_panel="#2d2d2d",
    bg_player_header="#2d2d2d",
    bg_placeholder_canvas="#1e1e1e",
    bg_elevated="#2d2d2d",
    border_card="#383838",
    border_panel="#353535",
    border_default="#444444",
    border_subtle="#000000",
    # Light tip plate — readable on dark chrome (matches classic Windows light tip).
    tooltip_bg="#f0f0f0",
    tooltip_border="#c8c8c8",
    tooltip_fg="#1a1a1a",
    neo_nav_hover_bg="#383838",
    neo_nav_checked_bg="#252525",
    neo_nav_idle="#a0a0a0",
    neo_nav_hover_border="#5a4b7a",
    neo_nav_checked_border="#8e7cc3",
    settings_btn_bg="#303030",
    settings_btn_border="#3a3a3a",
    settings_btn_hover_bg="#262626",
    settings_btn_pressed_bg="#141414",
    button_secondary_bg="#383838",
    button_secondary_border="#444444",
    button_secondary_hover_bg="#404040",
    button_secondary_pressed_bg="#3a324a",
    button_disabled_bg="#222222",
    button_disabled_border="#2d2d2d",
    bg_player_footer="#2d2d2d",
    bg_timeline_strip="#1e1e1e",
    bg_clip_card_footer="#383838",
    bg_clip_card_plate="#1a1a1a",
    bg_library_toolbar="#2d2d2d",
    bg_library_tab="#2d2d2d",
    bg_view_toggle_track="#141414",
    border_library_tab_idle="#353535",
    border_library_tab_hover="#555555",
)

# TrueDark — darker unified family; elevated surfaces sit one step above shell.
_PALETTE_TRUE_DARK = UiThemePalette(
    name=UI_THEME_TRUE_DARK,
    chrome_title_bar="#1a1a1a",
    chrome_app_bg="#0f0f0f",
    bg_shell="#121212",
    bg_player_canvas="#1a1a1a",
    bg_card="#141414",
    bg_settings_panel="#161616",
    bg_player_header="#161616",
    bg_placeholder_canvas="#0f0f0f",
    bg_elevated="#161616",
    border_card="#262626",
    border_panel="#262626",
    border_default="#333333",
    border_subtle="#000000",
    # Near-black tip — TrueDark (not mid-gray #252525).
    tooltip_bg="#0a0a0a",
    tooltip_border="#222222",
    tooltip_fg="#e8e8e8",
    neo_nav_hover_bg="#252525",
    neo_nav_checked_bg="#1a1a1a",
    neo_nav_idle="#909090",
    neo_nav_hover_border="#5a4b7a",
    neo_nav_checked_border="#8e7cc3",
    settings_btn_bg="#1a1a1a",
    settings_btn_border="#2a2a2a",
    settings_btn_hover_bg="#222222",
    settings_btn_pressed_bg="#0f0f0f",
    button_secondary_bg="#1a1a1a",
    button_secondary_border="#2a2a2a",
    button_secondary_hover_bg="#252525",
    button_secondary_pressed_bg="#2a2438",
    button_disabled_bg="#121212",
    button_disabled_border="#1a1a1a",
    bg_player_footer="#161616",  # match bg_player_header — visible panel vs shell
    bg_timeline_strip="#0a0a0a",
    bg_clip_card_footer="#222222",
    bg_clip_card_plate="#141414",
    bg_library_toolbar="#161616",
    bg_library_tab="#161616",
    bg_view_toggle_track="#0f0f0f",
    border_library_tab_idle="#2a2a2a",
    border_library_tab_hover="#444444",
)

# TrueDark OLED — pure black shell/player canvas; cards stay slightly elevated.
_PALETTE_TRUE_DARK_OLED = UiThemePalette(
    name=UI_THEME_TRUE_DARK_OLED,
    chrome_title_bar="#000000",
    chrome_app_bg="#000000",
    bg_shell="#000000",
    bg_player_canvas="#000000",
    bg_card="#141414",
    bg_settings_panel="#141414",
    bg_player_header="#141414",
    bg_placeholder_canvas="#000000",
    bg_elevated="#141414",
    border_card="#222222",
    border_panel="#222222",
    border_default="#333333",
    border_subtle="#000000",
    # Pure black tip for OLED.
    tooltip_bg="#000000",
    tooltip_border="#141414",
    tooltip_fg="#e8e8e8",
    neo_nav_hover_bg="#1a1a1a",
    neo_nav_checked_bg="#111111",
    neo_nav_idle="#888888",
    neo_nav_hover_border="#5a4b7a",
    neo_nav_checked_border="#8e7cc3",
    settings_btn_bg="#1a1a1a",
    settings_btn_border="#2a2a2a",
    settings_btn_hover_bg="#141414",
    settings_btn_pressed_bg="#000000",
    button_secondary_bg="#1a1a1a",
    button_secondary_border="#333333",
    button_secondary_hover_bg="#222222",
    button_secondary_pressed_bg="#2a2438",
    button_disabled_bg="#0a0a0a",
    button_disabled_border="#1a1a1a",
    bg_player_footer="#000000",
    bg_timeline_strip="#141414",
    bg_clip_card_footer="#1a1a1a",
    bg_clip_card_plate="#141414",
    bg_library_toolbar="#141414",
    bg_library_tab="#141414",
    bg_view_toggle_track="#0a0a0a",
    border_library_tab_idle="#222222",
    border_library_tab_hover="#333333",
)

UI_THEMES: Final[dict[str, UiThemePalette]] = {
    UI_THEME_DEFAULT: _PALETTE_DEFAULT,
    UI_THEME_TRUE_DARK: _PALETTE_TRUE_DARK,
    UI_THEME_TRUE_DARK_OLED: _PALETTE_TRUE_DARK_OLED,
}

_active: UiThemePalette = _PALETTE_DEFAULT


def normalize_ui_theme(value: object | None) -> str:
    name = str(value or UI_THEME_DEFAULT).strip().lower()
    if name in UI_THEMES:
        return name
    return UI_THEME_DEFAULT


def get_ui_theme() -> str:
    return _active.name


def active_palette() -> UiThemePalette:
    return _active


def palette_for(name: str) -> UiThemePalette:
    return UI_THEMES.get(normalize_ui_theme(name), _PALETTE_DEFAULT)


def apply_palette(name: str) -> UiThemePalette:
    """Activate a theme palette and sync ``design_tokens`` module globals."""
    global _active
    palette = palette_for(name)
    _active = palette
    tok.sync_from_ui_theme(palette)
    return palette


def chrome_colors_for_active() -> dict[str, str]:
    p = _active
    return {"title_bar": p.chrome_title_bar, "app_bg": p.chrome_app_bg}


def splitter_handle_colors(*, vertical: bool = False) -> tuple[str, str]:
    """Idle + hover colors for shell splitter handles.

    Default keeps the classic gray bar (vertical hover stays purple). TrueDark /
    OLED use Emily's mid-gray family for all handles — never purple.
    """
    if _active.name == UI_THEME_DEFAULT:
        idle = "#444444"
        hover = "#b29ae7" if vertical else "#666666"
        return idle, hover
    # Emily screenshot gray — readable on TrueDark #0f0f0f / OLED #000.
    return ("#3E3E3E", "#555555")


def elevated_panel_stylesheet(*, object_name: str | None = None) -> str:
    """Library / queue / render dashboard card face."""
    p = _active
    selector = f"QFrame#{object_name}" if object_name else "QFrame"
    return (
        f"{selector} {{ background-color: {p.bg_elevated}; "
        f"border: 1px solid {p.border_panel}; border-radius: 12px; }}"
    )


def portable_render_chrome_colors() -> tuple[str, str]:
    """Fill + border for portable Queue panels and the Render control strip.

    Default keeps the classic mid-gray plate. TrueDark / OLED reuse the same
    elevated face as the desktop render dashboard (not pure black).
    """
    p = _active
    if p.name == UI_THEME_DEFAULT:
        return "#2d2d2d", "#383838"
    return p.bg_elevated, p.border_panel


def portable_queue_panel_stylesheet() -> str:
    """Portable Queue header + list rail."""
    bg, border = portable_render_chrome_colors()
    return f"""
QFrame#portableQueueHeader, QFrame#portableQueueList {{
    background-color: {bg};
    border: 1px solid {border};
    border-radius: 10px;
}}
"""


def portable_render_strip_stylesheet() -> str:
    """Portable Render management strip (progress + Start / Leave / …)."""
    bg, border = portable_render_chrome_colors()
    return f"""
QFrame#portableRenderStrip {{
    background-color: {bg};
    border: 1px solid {border};
    border-radius: 10px;
}}
QFrame#portableRenderStrip QLabel {{
    background: transparent;
    border: none;
}}
"""


def portable_render_save_bar_stylesheet() -> str:
    """Full-width Save footer under the portable Render sheet."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, edge = "#141414", "#2a2a2a"
    else:
        # Match dialog shell — slightly under the elevated Queue/strip plates.
        bg, edge = p.chrome_app_bg, p.border_panel
    return (
        "QFrame#portableRenderSaveBar {"
        f" background-color: {bg}; border: none;"
        f" border-top: 1px solid {edge}; }}"
    )


def player_chrome_border_color() -> str:
    """Subtle 1px outline for player chrome — same edge as cards / panels.

    Reuses ``border_card`` in every theme (Default ``#383838``, TrueDark
    ``#262626``, OLED ``#222222``). Avoid ``border_default`` — that token is
    louder (``#333333`` on dark themes) and reads too bright on the player ring.
    """
    return _active.border_card


def player_header_stylesheet(*, force_outline: bool | None = None) -> str:
    """Player title bar — panel radius on header chrome (Reunited + Fractured).

    ``force_outline=False`` hides edges (theatre / fullscreen). Outline pref
    ``without_lines`` also hides; ``chrome_only`` closes the header as its own
    plate so sides never rely on the video plane.
    """
    from steempeg.ui.layout_defaults import PLAYER_LAYOUT_PANEL_RADIUS_PX
    from steempeg.ui.player_layout import PLAYER_LAYOUT_FRACTURED, get_player_layout
    from steempeg.ui.player_outline import (
        PLAYER_OUTLINE_CHROME_ONLY,
        get_player_outline,
        player_outline_shows_chrome,
    )

    p = _active
    show = player_outline_shows_chrome() if force_outline is None else bool(force_outline)
    edge = player_chrome_border_color() if show else p.bg_player_header
    fractured = get_player_layout() == PLAYER_LAYOUT_FRACTURED
    r = PLAYER_LAYOUT_PANEL_RADIUS_PX
    chrome_only = get_player_outline() == PLAYER_OUTLINE_CHROME_ONLY
    # Closed plate when Fractured, chrome-only, or lines are off (invisible edge).
    closed_plate = fractured or chrome_only or not show
    if closed_plate:
        return f"""
        QFrame#playerHeaderFrame {{
            background-color: {p.bg_player_header};
            border: 1px solid {edge};
            border-radius: {r}px;
        }}
    """
    # Reunited + with lines: top + sides only — canvas sides + footer close the box.
    return f"""
        QFrame#playerHeaderFrame {{
            background-color: {p.bg_player_header};
            border: 1px solid {edge};
            border-bottom: none;
            border-top-left-radius: {r}px;
            border-top-right-radius: {r}px;
            border-bottom-left-radius: 0px;
            border-bottom-right-radius: 0px;
        }}
    """


def player_video_wrapper_stylesheet(
    *,
    background: str = "transparent",
    chrome_outline: bool | None = None,
) -> str:
    """Video canvas wrapper — Reunited side borders close the chrome outline.

    Immersive paths pass ``chrome_outline=False`` (black fill, no border).
    Outline pref ``chrome_only`` / ``without_lines`` also suppress video sides.
    """
    from steempeg.ui.player_layout import PLAYER_LAYOUT_FRACTURED, get_player_layout
    from steempeg.ui.player_outline import player_outline_wraps_video

    if chrome_outline is None:
        chrome_outline = (
            get_player_layout() != PLAYER_LAYOUT_FRACTURED
            and player_outline_wraps_video()
        )
    if not chrome_outline:
        return f"background-color: {background}; border: none;"
    edge = player_chrome_border_color()
    return (
        f"background-color: {background}; "
        f"border-left: 1px solid {edge}; border-right: 1px solid {edge}; "
        f"border-top: none; border-bottom: none;"
    )


def player_placeholder_canvas_stylesheet() -> str:
    p = _active
    return f"""
        QFrame#playerPlaceholderCanvas {{
            background-color: {p.bg_placeholder_canvas};
            border-radius: 0px;
            border: none;
        }}
    """


def player_placeholder_card_stylesheet() -> str:
    p = _active
    card_border = "#3d3d45" if p.name == UI_THEME_DEFAULT else p.border_card
    return f"""
        QFrame#playerPlaceholderCard {{
            background-color: {p.bg_player_canvas};
            border: 1px solid {card_border};
            border-radius: 18px;
        }}
        QFrame#playerPlaceholderCard QLabel {{
            background: transparent;
            border: none;
        }}
    """


def footer_pill_stylesheet() -> str:
    p = _active
    return f"""
        QFrame {{
            background-color: {p.bg_elevated};
            border-radius: 16px;
            border: 1px solid {p.border_card};
            font-family: {tok.FONT_APP};
        }}
    """


def unified_button_stylesheet() -> str:
    p = _active
    return f"""
        QPushButton {{
            background-color: {p.button_secondary_bg};
            color: #ffffff;
            border: 2px solid {p.button_secondary_border};
            border-radius: 14px;
            font-family: {tok.FONT_APP};
            font-weight: bold;
            font-size: 13px;
            padding: 4px 12px;
            min-height: 24px;
            outline: none;
        }}
        QPushButton:hover {{ background-color: {p.button_secondary_hover_bg}; border: 2px solid #6b5a8e; }}
        QPushButton:pressed {{ background-color: {p.button_secondary_pressed_bg}; border: 2px solid #b29ae7; }}
        QPushButton:disabled {{
            background-color: {p.button_disabled_bg};
            color: #555555;
            border: 2px solid {p.button_disabled_border};
        }}
        QPushButton:focus, QPushButton:default {{
            background-color: {p.button_secondary_bg};
            color: #ffffff;
            border: 2px solid {p.button_secondary_border};
            outline: none;
        }}
        QPushButton::menu-indicator {{ image: none; }}
    """


def footer_button_stylesheet(dense) -> str:
    """Library footer row — density-aware secondary buttons."""
    p = _active
    r = dense.footer_radius
    return f"""
        QPushButton {{
            background-color: {p.button_secondary_bg};
            color: #ffffff;
            border: 2px solid {p.button_secondary_border};
            border-radius: {r}px;
            font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
            font-weight: bold;
            font-size: {dense.footer_font}px;
            padding: {dense.footer_pad};
            min-height: {dense.footer_min_h}px;
            outline: none;
        }}
        QPushButton:hover {{
            background-color: {p.button_secondary_hover_bg};
            border: 2px solid #6b5a8e;
        }}
        QPushButton:pressed {{
            background-color: {p.button_secondary_pressed_bg};
            border: 2px solid #b29ae7;
        }}
        QPushButton:disabled {{
            background-color: {p.button_disabled_bg};
            color: #555555;
            border: 2px solid {p.button_disabled_border};
        }}
        QPushButton:focus, QPushButton:default {{
            background-color: {p.button_secondary_bg};
            color: #ffffff;
            border: 2px solid {p.button_secondary_border};
            outline: none;
        }}
        QPushButton::menu-indicator {{ image: none; }}
    """


def split_footer_composite_stylesheet(dense, variant: str) -> str:
    """Choose Folder / Refresh composite — main + menu/add cells."""
    p = _active
    r = dense.footer_radius
    if variant == "folder":
        main_name, side_name = "FolderPickerMain", "FolderPickerAdd"
        side_text_size = 17 if not dense.compact else 14
        side_min = dense.footer_add_w
        side_max = dense.footer_add_w + 4
    else:
        main_name, side_name = "RefreshMain", "RefreshMenu"
        side_text_size = 12
        side_min = 24 if dense.compact else 28
        side_max = 28 if dense.compact else 32
    return f"""
    QPushButton#{main_name} {{
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        font-size: {dense.footer_font}px;
        font-weight: bold;
        background-color: {p.button_secondary_bg};
        color: #ffffff;
        border: 2px solid {p.button_secondary_border};
        border-right: none;
        border-top-left-radius: {r}px;
        border-bottom-left-radius: {r}px;
        border-top-right-radius: 0px;
        border-bottom-right-radius: 0px;
        padding: {dense.footer_pad};
        min-height: {dense.footer_min_h}px;
    }}
    QPushButton#{main_name}:hover {{
        background-color: {p.button_secondary_hover_bg};
        border: 2px solid #6b5a8e;
        border-right: none;
    }}
    QPushButton#{main_name}:pressed {{
        background-color: {p.button_secondary_pressed_bg};
        border: 2px solid #b29ae7;
        border-right: none;
    }}
    QPushButton#{side_name} {{
        background-color: {p.button_secondary_bg};
        color: #ffffff;
        border: 2px solid {p.button_secondary_border};
        border-left: 1px solid {p.border_default};
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        border-top-right-radius: {r}px;
        border-bottom-right-radius: {r}px;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        font-size: {side_text_size}px;
        font-weight: bold;
        min-width: {side_min}px;
        max-width: {side_max}px;
        padding: 2px 0;
        min-height: {dense.footer_min_h}px;
    }}
    QPushButton#{side_name}:hover {{
        background-color: {p.button_secondary_hover_bg};
        color: #d4c4ff;
        border: 2px solid #6b5a8e;
        border-left: 1px solid #6b5a8e;
    }}
    QPushButton#{side_name}:pressed {{
        background-color: {p.button_secondary_pressed_bg};
        border: 2px solid #b29ae7;
        border-left: 1px solid #b29ae7;
    }}
    """


def toolbar_icon_button_stylesheet(*, radius: int = 6, height: int = 32) -> str:
    """Compact square toolbar actions (History, Filter-adjacent)."""
    p = _active
    return f"""
        QPushButton {{
            background-color: {p.button_secondary_bg};
            color: #e0e0e0;
            border: 2px solid {p.button_secondary_border};
            border-radius: {radius}px;
            padding: 4px;
        }}
        QPushButton:hover {{
            background-color: {p.button_secondary_hover_bg};
            color: #ffffff;
            border: 2px solid #6b5a8e;
        }}
        QPushButton:pressed {{
            background-color: {p.button_secondary_pressed_bg};
            border: 2px solid #b29ae7;
        }}
        QPushButton:disabled {{
            background-color: {p.button_disabled_bg};
            color: #5a5a5a;
            border: 2px solid {p.button_disabled_border};
        }}
    """


def toolbar_text_button_stylesheet(*, radius: int = 6, font_px: int = 13, height: int = 32) -> str:
    """Labeled toolbar actions (Clear queue, etc.).

    Height is enforced on the widget (``setFixedHeight``), not via QSS min-height —
    padding + min-height double-counts and drops the button below Grid/List peers.
    """
    p = _active
    pad_v = max(0, (height - font_px - 4) // 2)  # 4px = 2px border top + bottom
    return f"""
        QPushButton {{
            background-color: {p.button_secondary_bg};
            color: #e0e0e0;
            border: 2px solid {p.button_secondary_border};
            border-radius: {radius}px;
            padding: {pad_v}px 12px;
            font-size: {font_px}px;
            font-weight: bold;
            font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        }}
        QPushButton:hover {{
            background-color: {p.button_secondary_hover_bg};
            color: #ffffff;
            border: 2px solid #6b5a8e;
        }}
        QPushButton:pressed {{
            background-color: {p.button_secondary_pressed_bg};
            border: 2px solid #b29ae7;
        }}
        QPushButton:disabled {{
            background-color: {p.button_disabled_bg};
            color: #5a5a5a;
            border: 2px solid {p.button_disabled_border};
        }}
    """


def library_tab_stylesheet(
    *,
    font_px: int,
    radius: int,
    active: bool,
    hover: bool,
) -> str:
    p = _active
    if active:
        border, color = "#6b5a8e", "#ffffff"
    elif hover:
        border, color = p.border_library_tab_hover, "#ffffff"
    else:
        border, color = p.border_library_tab_idle, "#aaaaaa"
    return f"""
    QFrame#libraryTab {{
        background-color: {p.bg_library_tab};
        border: 1px solid {border};
        border-radius: {radius}px;
    }}
    QLabel#libraryTabText {{
        color: {color};
        background: transparent;
        border: none;
        font-weight: bold;
        font-size: {font_px}px;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }}
    """


def add_library_panel_button_stylesheet(dense) -> str:
    p = _active
    sz = dense.add_tab_size
    return f"""
        QPushButton {{
            background-color: {p.bg_library_tab};
            color: #ffffff;
            border: 1px solid {p.border_library_tab_idle};
            border-radius: {dense.tab_radius}px;
            font-weight: 800;
            font-size: {18 if not dense.compact else 14}px;
            padding: 0px;
            min-width: {sz}px; max-width: {sz}px;
            min-height: {sz}px; max-height: {sz}px;
        }}
        QPushButton:hover {{
            background-color: {p.neo_nav_hover_bg};
            border-color: #6b5a8e;
        }}
    """


def timeline_strip_stylesheet() -> str:
    """Custom timeline scroll area — groove zone lighter than #HudFrame footer."""
    p = _active
    return f"""
        QScrollArea {{
            border: none;
            background: {p.bg_timeline_strip};
            border-radius: 8px;
            padding: 6px 12px 0px 12px;
        }}
        QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
    """


def clip_card_chrome() -> tuple[str, str, str]:
    """Footer fill, empty-thumb plate, idle border ring."""
    p = _active
    idle_border = p.border_default if p.name == UI_THEME_DEFAULT else p.border_card
    return p.bg_clip_card_footer, p.bg_clip_card_plate, idle_border


def queue_list_panel_stylesheet(*, object_name: str = "queueListContainer") -> str:
    """Render queue card list host — ClipCard plate tone in dark themes."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        return elevated_panel_stylesheet(object_name=object_name)
    selector = f"QFrame#{object_name}" if object_name else "QFrame"
    return (
        f"{selector} {{ background-color: {p.bg_clip_card_plate}; "
        f"border: 1px solid {p.border_card}; border-radius: 12px; }}"
    )


def queue_job_card_face(*, selected: bool = False, ready_tint: bool = False) -> str:
    """List-mode queue card fill — plate tone in TrueDark, legacy gray in Default."""
    p = _active
    if selected:
        return "#322a45"
    if ready_tint:
        return "rgba(255, 204, 0, 0.10)"
    if p.name == UI_THEME_DEFAULT:
        return "#2a2a2a"
    return p.bg_clip_card_plate


def queue_grid_footer_stylesheet(*, radius: int = 9) -> str:
    """Grid queue card metadata footer — matches library ClipCard footer."""
    footer, _, _ = clip_card_chrome()
    return f"""
        QWidget {{
            background-color: {footer};
            border: none;
            border-bottom-left-radius: {radius}px;
            border-bottom-right-radius: {radius}px;
        }}
    """


def dash_secondary_button_stylesheet(
    *,
    font: int = 13,
    radius: int = 8,
    pad: str = "6px 14px",
) -> str:
    """Render dash gray actions (Logs, Leave) — secondary button family."""
    p = _active
    return f"""
        QPushButton {{
            font-family: {tok.FONT_APP};
            font-size: {font}px;
            font-weight: bold;
            background-color: {p.button_secondary_bg};
            color: #ffffff;
            border: 2px solid {p.button_secondary_border};
            border-radius: {radius}px;
            padding: {pad};
            outline: none;
        }}
        QPushButton:hover {{
            background-color: {p.button_secondary_hover_bg};
            border: 2px solid #6b5a8e;
        }}
        QPushButton:pressed {{
            background-color: {p.button_secondary_pressed_bg};
            border: 2px solid #b29ae7;
        }}
        QPushButton:disabled {{
            background-color: {p.button_disabled_bg};
            color: #555555;
            border: 2px solid {p.button_disabled_border};
        }}
        QPushButton::menu-indicator {{ image: none; }}
    """


def neo_wrapper_stylesheet() -> str:
    p = _active
    radius = int(round(tok.RADIUS_NEO_PANEL))
    return (
        f"QWidget#neo_wrapper {{ background-color: {p.bg_card}; "
        f"border-radius: {radius}px; border: 1px solid {p.border_card}; }}"
    )


def neo_nav_pill_stylesheet() -> str:
    p = _active
    return f"""
        QPushButton {{
            background-color: transparent; color: {p.neo_nav_idle};
            border: 2px solid transparent; border-radius: 14px;
            padding: 10px 12px 10px 14px; text-align: left; font-size: 14px; font-weight: 700;
        }}
        QPushButton:hover {{
            background-color: {p.neo_nav_hover_bg};
            border: 2px solid {p.neo_nav_hover_border};
            color: #e0e0e0;
        }}
        QPushButton:checked {{
            background-color: {p.neo_nav_checked_bg};
            border: 2px solid {p.neo_nav_checked_border};
            color: #ffffff;
        }}
    """


def neo_settings_scroll_stylesheet() -> str:
    p = _active
    radius = int(round(tok.RADIUS_NEO_PANEL))
    bg = p.bg_settings_panel
    return f"""
        QScrollArea#neo_settings_scroll {{
            background-color: {bg};
            border: none;
            border-top-left-radius: {radius}px;
            border-bottom-left-radius: {radius}px;
            border-top-right-radius: 0px;
            border-bottom-right-radius: 0px;
            border-left: 1px solid {p.border_card};
        }}
        QScrollArea#neo_settings_scroll > QWidget {{
            background-color: {bg};
            border: none;
        }}
        QWidget#qt_scrollarea_viewport {{
            background-color: {bg};
            border: none;
        }}
    """


def neo_settings_tabs_stylesheet(extra: str = "") -> str:
    p = _active
    bg = p.bg_settings_panel
    btn = f"""
        QPushButton {{
            background-color: {p.settings_btn_bg}; color: #ffffff;
            border: 2px solid {p.settings_btn_border}; border-radius: 12px;
            padding: 7px 15px; font-weight: bold; font-family: 'Arial';
        }}
        QPushButton:hover {{ background-color: {p.settings_btn_hover_bg}; border: 2px solid #6b5a8e; }}
        QPushButton:pressed {{ background-color: {p.settings_btn_pressed_bg}; border: 2px solid #b29ae7; }}
    """
    return (
        f"QTabWidget {{ background-color: {bg}; border: none; }}\n"
        f"QTabWidget::pane {{ border: none; background-color: {bg}; }}\n"
        f"QTabWidget > QStackedWidget {{ background-color: {bg}; border: none; }}\n"
        f"QStackedWidget > QWidget {{ background-color: {bg}; }}\n"
        f"QLabel {{ color: #cccccc; font-weight: bold; background: transparent; font-family: 'Arial'; }}\n"
        + btn
        + (extra or "")
    )


def neo_tab_page_stylesheet(object_name: str) -> str:
    p = _active
    return f"QWidget#{object_name} {{ background-color: {p.bg_settings_panel}; border: none; }}"


def player_footer_stylesheet(*, force_outline: bool | None = None) -> str:
    """Player HUD — panel radius on footer chrome (Reunited + Fractured).

    Keep a real ``border`` (not ``border: none``): Qt QSS then clips the fill to
    ``border-radius``. Reunited + with-lines uses no top edge so header/canvas/footer
    read as one outlined block; Fractured / chrome-only / without-lines get a closed
    plate (invisible edge when lines are off).
    """
    from steempeg.ui.layout_defaults import PLAYER_LAYOUT_PANEL_RADIUS_PX
    from steempeg.ui.player_layout import PLAYER_LAYOUT_FRACTURED, get_player_layout
    from steempeg.ui.player_outline import (
        PLAYER_OUTLINE_CHROME_ONLY,
        get_player_outline,
        player_outline_shows_chrome,
    )

    p = _active
    footer_bg = p.bg_player_footer
    show = player_outline_shows_chrome() if force_outline is None else bool(force_outline)
    edge = player_chrome_border_color() if show else footer_bg
    fractured = get_player_layout() == PLAYER_LAYOUT_FRACTURED
    r = PLAYER_LAYOUT_PANEL_RADIUS_PX
    chrome_only = get_player_outline() == PLAYER_OUTLINE_CHROME_ONLY
    closed_plate = fractured or chrome_only or not show
    if closed_plate:
        return f"""
        #HudFrame {{
            background-color: {footer_bg};
            border: 1px solid {edge};
            border-radius: {r}px;
        }}
    """
    return f"""
        #HudFrame {{
            background-color: {footer_bg};
            border: 1px solid {edge};
            border-top: none;
            border-top-left-radius: 0px;
            border-top-right-radius: 0px;
            border-bottom-left-radius: {r}px;
            border-bottom-right-radius: {r}px;
        }}
    """


def player_chrome_pill_stylesheet(*, radius: int) -> str:
    """Theater / fullscreen / marker pill track — Default keeps legacy gray."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg = "#4e4e4e"
        border = "none"
    elif p.name == UI_THEME_TRUE_DARK:
        # Darker than bg_player_footer (#161616) so pills read as controls, not panel.
        bg = p.bg_timeline_strip
        border = f"1px solid {p.button_secondary_border}"
    else:
        bg = p.button_secondary_bg
        border = "none"
    return (
        f"QFrame {{ background-color: {bg}; border-radius: {radius}px; border: {border}; }}"
    )


def player_chrome_round_button_stylesheet(*, radius: int) -> str:
    """Volume / speed round mute buttons in the player footer."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, hover = "#4e4e4e", "#5a5a5a"
        border = "none"
    elif p.name == UI_THEME_TRUE_DARK:
        bg = p.bg_timeline_strip
        hover = p.neo_nav_hover_bg
        border = f"1px solid {p.button_secondary_border}"
    else:
        bg, hover = p.button_secondary_bg, p.button_secondary_hover_bg
        border = "none"
    return (
        f"QPushButton {{ background-color: {bg}; border-radius: {radius}px; border: {border}; }}"
        f" QPushButton:hover {{ background-color: {hover}; }}"
    )


def render_settings_plate_stylesheet(
    *,
    radius: int = 12,
    object_name: str | None = None,
) -> str:
    """Source Info stat blocks, Export summary card, and similar plates."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border = "#303030", "#3a3a3a"
    else:
        bg, border = p.bg_elevated, p.button_secondary_border
    selector = f"QFrame#{object_name}" if object_name else "QFrame"
    return (
        f"{selector} {{ background-color: {bg}; border: 1px solid {border}; "
        f"border-radius: {radius}px; }}"
    )


def render_settings_source_row_stylesheet() -> str:
    """Per-directory source path rows in Source Info."""
    p = _active
    bg = "#252525" if p.name == UI_THEME_DEFAULT else p.bg_clip_card_plate
    return f"QFrame#srcRow {{ background-color: {bg}; border-radius: 10px; }}"


def render_settings_output_path_row_stylesheet() -> str:
    """Export tab destination directory chip — dark plate in TrueDark."""
    return render_settings_source_row_stylesheet().replace("srcRow", "outputPathRow")


def render_settings_output_path_label_stylesheet(*, font_px: int = 11) -> str:
    """Monospace export destination path ink."""
    return (
        f"background: transparent; border: none; color: #b29ae7; font-size: {font_px}px;"
        f" font-weight: bold; font-family: 'Consolas', monospace;"
    )


def render_settings_source_path_field_stylesheet(*, font_px: int = 11) -> str:
    """Read-only source path field on Source Info rows."""
    return (
        f"color: #b29ae7; font-size: {font_px}px; font-weight: bold;"
        f" font-family: 'Consolas', monospace; background: transparent; border: none;"
    )


def portable_queue_empty_panel_stylesheet() -> str:
    """Portable queue empty-state card."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border = "#262229", "#3d3d45"
    else:
        bg, border = p.bg_elevated, p.border_card
    return (
        f"QFrame#portableQueueEmptyPanel {{"
        f" background-color: {bg}; border: 1px solid {border}; border-radius: 18px; }}"
    )


def portable_queue_row_stylesheet(
    *,
    selected: bool,
    border: str,
    border_w: int,
    idle_border: str,
) -> str:
    """Portable Render sheet queue card chrome."""
    from steempeg.ui.queue_card_shared import STATUS_BORDER_READY

    ready = border == STATUS_BORDER_READY and not selected
    bg = queue_job_card_face(selected=selected, ready_tint=ready)
    hover = "#7a6aa8" if border == idle_border and not selected else border
    return f"""
QFrame#portableQueueRow {{
    background-color: {bg};
    border: {border_w}px solid {border};
    border-radius: 10px;
}}
QFrame#portableQueueRow:hover {{
    border-color: {hover};
}}
QFrame#portableQueueRow QLabel {{
    background: transparent;
    border: none;
    font-family: {tok.FONT_APP};
}}
"""


def marker_settings_field_stylesheet() -> str:
    """Marker Settings inputs — combo face tokens on dark themes."""
    from steempeg.ui.widgets.combo_chrome import combo_popup_item_rules

    c = combo_chrome_colors()
    return f"""
    QLineEdit, QComboBox {{
        background-color: {c.field_bg}; color: #f0f0f0; border: 1px solid {c.field_border};
        border-radius: 6px; padding: 6px 10px; font-size: 13px;
        font-family: {tok.FONT_APP};
        min-height: 30px;
        selection-background-color: {c.popup_sel_bg};
        selection-color: {c.popup_sel_fg};
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color: #6b5a8e; }}
    QComboBox:on {{ background-color: {c.field_bg}; color: #f0f0f0; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
""" + combo_popup_item_rules()


def marker_settings_list_stylesheet(*, item_padding: str = "6px 8px") -> str:
    """Marker Settings QListWidget plates."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border, hover, sel = "#242424", "#444444", "#333", "#3a3a3a"
    else:
        bg = p.bg_elevated
        border = p.border_card
        hover = p.neo_nav_hover_bg
        sel = "#3a3a3a"
    return f"""
    QListWidget {{
        background-color: {bg}; border: 1px solid {border}; border-radius: 8px;
        color: #eee; font-size: 13px; outline: none;
        font-family: {tok.FONT_APP};
    }}
    QListWidget::item {{
        padding: {item_padding}; margin: 2px 4px; border-radius: 6px;
        min-height: 22px;
    }}
    QListWidget::item:selected {{ background-color: {sel}; color: #ffffff; }}
    QListWidget::item:hover:!selected {{ background-color: {hover}; }}
"""


def marker_settings_list_host_stylesheet() -> str:
    """On-clip marker picker scroll host."""
    p = _active
    bg = "#242424" if p.name == UI_THEME_DEFAULT else p.bg_elevated
    border = "#444444" if p.name == UI_THEME_DEFAULT else p.border_card
    return f"""
    QScrollArea {{
        background-color: {bg}; border: none;
    }}
    QScrollArea > QWidget {{
        background-color: {bg};
    }}
    QWidget#markerListInner {{
        background-color: {bg}; border: 1px solid {border}; border-radius: 8px;
    }}
"""


def marker_settings_pick_row_stylesheet(*, selected: bool = False) -> str:
    """Selectable marker row in the On clip list."""
    p = _active
    if selected:
        bg = "#3a3a3a" if p.name == UI_THEME_DEFAULT else p.neo_nav_checked_bg
        fg = "#ffffff"
    else:
        bg = "transparent"
        fg = "#e8e8e8"
    hover = p.neo_nav_hover_bg if p.name != UI_THEME_DEFAULT else "#333333"
    if selected:
        return f"""
    QFrame#mkPick {{
        background-color: {bg}; border-radius: 6px;
    }}
    QFrame#mkPick QLabel {{
        color: {fg}; font-size: 13px; background: transparent;
        font-family: {tok.FONT_APP};
    }}
"""
    return f"""
    QFrame#mkPick {{
        background: transparent; border-radius: 6px;
    }}
    QFrame#mkPick:hover {{
        background-color: {hover};
    }}
    QFrame#mkPick QLabel {{
        color: {fg}; font-size: 13px; background: transparent;
        font-family: {tok.FONT_APP};
    }}
"""


def marker_settings_preview_plate_stylesheet() -> str:
    """Marker icon / screenshot preview wells."""
    p = _active
    bg = "#1a1a1a" if p.name == UI_THEME_DEFAULT else p.bg_clip_card_plate
    border = "#555555" if p.name == UI_THEME_DEFAULT else p.border_card
    return f"background: {bg}; border-radius: 8px; border: 1px solid {border};"


def dialog_btn_danger_stylesheet() -> str:
    """Steempeg modal danger actions — theme-aware disabled plate."""
    p = _active
    dis_bg = "#2a1818" if p.name == UI_THEME_DEFAULT else p.button_disabled_bg
    dis_border = "#444444" if p.name == UI_THEME_DEFAULT else p.button_disabled_border
    return f"""
    QPushButton {{
        background-color: #3a2222; color: #ff8a8a; border: 2px solid #8b3a3a;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: bold;
        font-family: {tok.FONT_APP};
    }}
    QPushButton:hover {{ background-color: #522828; color: #ffb3b3; border-color: #c44; }}
    QPushButton:pressed {{ background-color: #2a1818; }}
    QPushButton:disabled {{
        background-color: {dis_bg}; color: #666; border-color: {dis_border};
    }}
"""


def render_settings_target_readout_stylesheet() -> str:
    """Video Settings target-size readout chip."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border = "#303030", "#3a3a3a"
    else:
        bg, border = p.bg_elevated, p.button_secondary_border
    return (
        f"QLabel {{ background-color: {bg}; border: 1px solid {border};"
        f" border-radius: 10px; padding: 9px 13px; color: #cfcfcf;"
        f" font-size: 11px; font-weight: normal; line-height: 1.35;"
        f" font-family: {tok.FONT_APP}; }}"
    )


def render_settings_combo_overlay_stylesheet() -> str:
    """Custom-value overlay chip on active render combos."""
    bg = combo_chrome_colors().field_bg
    return (
        f"QFrame#customOverlay {{ background-color: {bg};"
        f" border-top-left-radius: 10px; border-bottom-left-radius: 10px; }}"
    )


@dataclass(frozen=True)
class ComboChromeColors:
    """QComboBox face + popup list tokens for the active UI theme."""

    field_bg: str
    field_border: str
    field_hover_bg: str
    drop_bg: str
    popup_bg: str
    popup_border: str
    popup_item_bg: str
    popup_item_hover: str
    popup_sel_bg: str
    popup_sel_fg: str
    popup_dis_fg: str
    popup_dis_bg: str


def combo_chrome_colors() -> ComboChromeColors:
    """Combo face and popup palette — Default unchanged; dark themes use timeline black."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        return ComboChromeColors(
            field_bg="#383838",
            field_border="#4a4a4a",
            field_hover_bg="#404040",
            drop_bg="#262626",
            popup_bg=p.bg_shell,
            popup_border="#4a4a4a",
            popup_item_bg="#333333",
            popup_item_hover="#404040",
            popup_sel_bg="#3a3350",
            popup_sel_fg="#ffffff",
            popup_dis_fg="#5a5a5a",
            popup_dis_bg="#262626",
        )
    return ComboChromeColors(
        field_bg=p.bg_timeline_strip,
        field_border=p.button_secondary_border,
        field_hover_bg=p.neo_nav_hover_bg,
        drop_bg=p.bg_elevated,
        popup_bg=p.bg_elevated,
        popup_border=p.button_secondary_border,
        popup_item_bg=p.bg_timeline_strip,
        popup_item_hover=p.neo_nav_hover_bg,
        popup_sel_bg="#3a3350",
        popup_sel_fg="#ffffff",
        popup_dis_fg="#5a5a5a",
        popup_dis_bg=p.button_disabled_bg,
    )


def render_settings_active_combo_colors() -> tuple[str, str, str]:
    """Enabled combo field fill, border, and drop-down cell (disabled rows unchanged)."""
    c = combo_chrome_colors()
    return c.field_bg, c.field_border, c.drop_bg


def settings_dialog_tabs_stylesheet() -> str:
    """Settings dialog tab bar + pane — matches active shell/card tokens."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        tab_bg = "#2a2a2a"
        tab_hover = "#353535"
    else:
        tab_bg = p.bg_elevated
        tab_hover = p.neo_nav_hover_bg
    return f"""
    QTabWidget::pane {{
        border: 1px solid {p.border_default}; border-radius: 8px;
        background: {p.bg_shell}; top: -1px;
    }}
    QTabBar::tab {{
        background: {tab_bg}; color: #aaa; padding: 8px 14px; margin-right: 4px;
        border-top-left-radius: 6px; border-top-right-radius: 6px;
        font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif;
        font-size: 12px; font-weight: bold;
    }}
    QTabBar::tab:selected {{ background: #4a3d66; color: #fff; }}
    QTabBar::tab:hover:!selected {{ background: {tab_hover}; color: #ddd; }}
"""


_MENU_FONT = "'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif"


@dataclass(frozen=True)
class MenuPopupColors:
    """QMenu popup palette — aligned with ``combo_chrome_colors`` on dark themes."""

    bg: str
    border: str
    fg: str
    item_hover_bg: str
    item_selected_bg: str
    item_selected_fg: str
    separator: str
    disabled_fg: str
    border_width: int
    accent_selected_bg: str
    accent_selected_fg: str


def menu_popup_colors() -> MenuPopupColors:
    """Theme-aware QMenu tokens — Default unchanged; TrueDark matches combo popups."""
    p = _active
    c = combo_chrome_colors()
    if p.name == UI_THEME_DEFAULT:
        return MenuPopupColors(
            bg="#2d2d2d",
            border="#444444",
            fg="#ffffff",
            item_hover_bg="#6b5a8e",
            item_selected_bg="#6b5a8e",
            item_selected_fg="#ffffff",
            separator="#444444",
            disabled_fg="#888888",
            border_width=2,
            accent_selected_bg="#3a324a",
            accent_selected_fg="#b29ae7",
        )
    return MenuPopupColors(
        bg=c.popup_bg,
        border=c.popup_border,
        fg="#e0e0e0",
        item_hover_bg=c.popup_item_hover,
        item_selected_bg=c.popup_sel_bg,
        item_selected_fg=c.popup_sel_fg,
        separator=c.popup_border,
        disabled_fg=c.popup_dis_fg,
        border_width=1,
        accent_selected_bg=p.button_secondary_pressed_bg,
        accent_selected_fg="#b29ae7",
    )


def menu_stylesheet(
    *,
    item_padding: str = "6px 24px 6px 24px",
    item_margin: str = "2px 4px",
    menu_padding: str = "0px",
    font_size: str = "13px",
    font_weight: str = "bold",
    selected_mode: str = "fill",
    extra: str = "",
    selector: str = "QMenu",
) -> str:
    """Shared QMenu QSS — Default preserves legacy gray; TrueDark uses elevated chocolate."""
    mc = menu_popup_colors()
    if selected_mode == "accent":
        sel_bg, sel_fg = mc.accent_selected_bg, mc.accent_selected_fg
    else:
        sel_bg, sel_fg = mc.item_selected_bg, mc.item_selected_fg
    return f"""
    {selector} {{
        background-color: {mc.bg};
        color: {mc.fg};
        border: {mc.border_width}px solid {mc.border};
        border-radius: 8px;
        font-family: {_MENU_FONT};
        font-size: {font_size};
        font-weight: {font_weight};
        padding: {menu_padding};
    }}
    {selector}::item {{
        padding: {item_padding};
        border-radius: 4px;
        margin: {item_margin};
    }}
    {selector}::item:selected {{
        background-color: {sel_bg};
        color: {sel_fg};
    }}
    {selector}::separator {{
        height: 1px;
        background-color: {mc.separator};
        margin: 4px 10px;
    }}
    {extra}
    """


def library_menu_stylesheet() -> str:
    """Refresh ▾, clip RMB, Apply ▾, and other standard action menus."""
    return menu_stylesheet()


def health_menu_stylesheet() -> str:
    """Clip/rendered health menus — keep colored icons on disabled rows."""
    return menu_stylesheet(
        item_padding="8px 28px 8px 12px",
        extra="""
    QMenu::item:disabled {
        color: #e0e0e0;
        background: transparent;
    }
    """,
    )


def tooltip_stylesheet() -> str:
    """Canonical QToolTip chrome for the active theme.

    Default: light plate + dark ink. TrueDark / OLED: near-black + light ink.
    Mirrored into ``design_tokens.STYLE_TOOLTIP`` via ``sync_from_ui_theme``.
    """
    p = _active
    return (
        "QToolTip {"
        f" background-color: {p.tooltip_bg};"
        f" color: {p.tooltip_fg};"
        f" border: 1px solid {p.tooltip_border};"
        " border-radius: 6px;"
        " padding: 5px 9px;"
        f" font-family: 'Segoe UI', {tok.FONT_APP};"
        " font-size: 12px;"
        " font-weight: bold;"
        "}"
    )


def floating_tooltip_label_stylesheet() -> str:
    """QLabel-as-ToolTip chrome (timeline scrub tip) — same tokens as QToolTip."""
    p = _active
    return (
        "QLabel {"
        f" background-color: {p.tooltip_bg};"
        f" color: {p.tooltip_fg};"
        f" border: 1px solid {p.tooltip_border};"
        " border-radius: 6px;"
        " padding: 5px 9px;"
        f" font-family: {tok.FONT_APP};"
        " font-size: 12px;"
        " font-weight: bold;"
        "}"
    )


def timeline_hover_preview_colors() -> tuple[str, str, str, str]:
    """Floating timeline hover thumb chrome — Default mid plate; TrueDark tip tokens.

    Returns ``(frame_bg, border, time_bg, time_fg)``. Digits stay light on the dark
    preview plate in every theme (Default's light ``tooltip_*`` plate is for text tips).
    """
    p = _active
    if p.name == UI_THEME_DEFAULT:
        return p.bg_timeline_strip, p.border_card, p.bg_player_header, "#ffffff"
    return p.tooltip_bg, p.tooltip_border, p.bg_elevated, p.tooltip_fg


def timeline_hover_preview_frame_stylesheet() -> str:
    """Outer frame around the hover thumb + timestamp row (1px themed edge)."""
    frame_bg, border, _, _ = timeline_hover_preview_colors()
    return (
        "QFrame {"
        f" background-color: {frame_bg};"
        f" border: 1px solid {border};"
        " border-radius: 5px;"
        "}"
    )


def timeline_hover_preview_time_stylesheet(*, in_trim: bool = False) -> str:
    """Timestamp digits under the hover thumb — Segoe/app chrome, not default tip font."""
    _, _, _, time_fg = timeline_hover_preview_colors()
    fg = "#ffcc00" if in_trim else time_fg
    return (
        "QLabel {"
        " background: transparent;"
        " border: none;"
        " padding: 0px;"
        f" color: {fg};"
        f" font-family: {tok.FONT_APP};"
        " font-size: 13px;"
        " font-weight: bold;"
        "}"
    )


def timeline_hover_preview_time_row_stylesheet() -> str:
    """Plate behind scissors + timestamp when the tip is in the yellow trim zone."""
    _, _, time_bg, _ = timeline_hover_preview_colors()
    return (
        "QWidget {"
        f" background-color: {time_bg};"
        " border: none;"
        " border-radius: 3px;"
        "}"
    )


def clip_info_popup_colors() -> tuple[str, str, str, str]:
    """Clip info popover plate + body text — Default mid plate; TrueDark elevated.

    Returns ``(bg, border, value_fg, muted_fg)``.
    """
    p = _active
    if p.name == UI_THEME_DEFAULT:
        return "#2c2b2e", "#5a5a5a", "#dcdde2", "#8a8a8a"
    return p.bg_elevated, p.border_panel, "#e0e0e0", "#8a8a8a"


def clip_info_popup_stylesheet() -> str:
    """Player-header Clip info QMenu plate — Default legacy; TrueDark near-black."""
    bg, border, _, _ = clip_info_popup_colors()
    return (
        "QMenu#clipInfoPopup {"
        f" background-color: {bg};"
        f" border: 1px solid {border};"
        " border-radius: 8px;"
        " padding: 0px;"
        "}"
    )


def folders_menu_stylesheet() -> str:
    """Choose-folder multi-path popup — menu chrome + embedded folder rows."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        row_bg, row_border = "#2a2a2a", "#4a4a4a"
        row_label = "#ffffff"
        btn_bg, btn_border = "#3f3f3f", "#5c5c5c"
    else:
        row_bg, row_border = p.bg_timeline_strip, p.button_secondary_border
        row_label = "#e0e0e0"
        btn_bg, btn_border = p.button_secondary_bg, p.button_secondary_border
    return menu_stylesheet(
        menu_padding="4px 0",
        item_padding="8px 28px 8px 20px",
        item_margin="2px 6px",
        extra=f"""
    QMenu::item {{
        background: transparent;
        border: none;
    }}
    QMenu::item:disabled {{
        color: {row_label};
        background: transparent;
        padding: 6px 20px 4px 20px;
        font-size: 13px;
        font-weight: bold;
    }}
    QWidget#FolderRowFrame {{
        background: transparent;
        border: none;
    }}
    QWidget#FolderRow {{
        background-color: {row_bg};
        border: 1px solid {row_border};
        border-radius: 12px;
    }}
    QLabel#FolderRowLabel {{
        color: {row_label};
        font-family: {_MENU_FONT};
        font-size: 13px;
        font-weight: bold;
        background: transparent;
        border: none;
        padding: 0;
    }}
    QLabel#FolderRowLabel[missing="true"] {{
        color: #d46a6a;
    }}
    QPushButton#FolderRowRemove, QPushButton#FolderRowReplace {{
        background-color: {btn_bg};
        border: 1px solid {btn_border};
        border-radius: 11px;
        min-width: 24px;
        max-width: 24px;
        min-height: 24px;
        max-height: 24px;
        padding: 0;
    }}
    QPushButton#FolderRowRemove:hover {{
        background-color: #8a2525;
        border: 1px solid #a82e2e;
    }}
    QPushButton#FolderRowRemove:pressed {{
        background-color: #661a1a;
        border: 1px solid #7a1f1f;
    }}
    QPushButton#FolderRowReplace:hover {{
        background-color: #4a3d66;
        border: 1px solid #6b5a8e;
    }}
    QPushButton#FolderRowReplace:pressed {{
        background-color: #3a324a;
        border: 1px solid #5a4b7a;
    }}
    """,
    )


def logs_menu_stylesheet() -> str:
    """Logs ▾ dropdown — purple accent on selected row."""
    return menu_stylesheet(
        menu_padding="4px 0",
        item_padding="8px 28px 8px 20px",
        item_margin="2px 6px",
        selected_mode="accent",
    )


def queue_menu_stylesheet() -> str:
    """Render queue card RMB menus."""
    mc = menu_popup_colors()
    disabled = "#777777" if _active.name == UI_THEME_DEFAULT else mc.disabled_fg
    return menu_stylesheet(
        menu_padding="4px 0",
        item_padding="8px 28px 8px 20px",
        item_margin="2px 6px",
        selected_mode="accent",
        extra=f"""
    QMenu::item:disabled {{
        color: {disabled};
    }}
    """,
    )


def preview_quality_menu_stylesheet() -> str:
    """Player header preview-quality dropdown."""
    mc = menu_popup_colors()
    return menu_stylesheet(
        menu_padding="4px 0px",
        item_padding="6px 28px 6px 16px",
        item_margin="2px 6px",
        extra=f"""
    QMenu::item:disabled {{
        color: {mc.disabled_fg};
        background: transparent;
        font-weight: normal;
        font-size: 11px;
        padding-top: 2px;
        padding-bottom: 8px;
    }}
    """,
    )


def compact_menu_stylesheet() -> str:
    """Minimal picker menus (e.g. multi-file screenshot list)."""
    return menu_stylesheet(
        item_padding="6px 24px",
        font_weight="normal",
    )


def filter_menu_container_stylesheet(*, radius: int) -> str:
    """Clips filter popup outer pill."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border = "#252525", "#3d3d3d"
    else:
        bg, border = p.bg_elevated, p.border_card
    return (
        f"QFrame#MainFilterContainer {{ background-color: {bg}; "
        f"border: 1px solid {border}; border-radius: {radius}px; }}"
    )


def filter_menu_capsule_stylesheet(*, radius: int, title_font: int) -> str:
    """Category mega-capsule inside the filter popup."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border = "#2d2d2d", "#383838"
    else:
        bg, border = p.bg_clip_card_plate, p.border_card
    return f"""
        QFrame#CategoryCapsule {{
            background-color: {bg};
            border: 1px solid {border};
            border-radius: {radius}px;
        }}
        QLabel#CategoryTitle {{
            color: #cccccc;
            border: none;
            background: transparent;
            font-size: {title_font}px;
            font-weight: bold;
            font-family: {_MENU_FONT};
        }}
    """


def filter_chip_button_stylesheet(
    *,
    font: int,
    pad_v: int,
    pad_h: int,
    min_h: int,
    radius: int,
    border: int,
) -> str:
    """Checkable game/type/health chips in the filter popup."""
    p = _active
    c = combo_chrome_colors()
    if p.name == UI_THEME_DEFAULT:
        bg, idle_fg = "#383838", "#aaaaaa"
        brd = "#444444"
        hover_bg, hover_brd = "#404040", "#555555"
        checked_bg, checked_brd = "#404040", "#6b5a8e"
        checked_hover_bg, checked_hover_brd = "#3a324a", "#b29ae7"
    else:
        bg, brd = c.field_bg, c.field_border
        idle_fg = "#aaaaaa"
        hover_bg, hover_brd = c.field_hover_bg, p.border_default
        checked_bg, checked_brd = c.field_hover_bg, "#6b5a8e"
        checked_hover_bg, checked_hover_brd = p.button_secondary_pressed_bg, "#b29ae7"
    return f"""
        QPushButton {{
            background-color: {bg};
            color: {idle_fg};
            border: {border}px solid {brd};
            border-radius: {radius}px;
            font-family: {_MENU_FONT};
            font-weight: bold;
            font-size: {font}px;
            padding: {pad_v}px {pad_h}px;
            min-height: {min_h}px;
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
            color: #ffffff;
            border: {border}px solid {hover_brd};
        }}
        QPushButton:checked {{
            background-color: {checked_bg};
            color: #ffffff;
            border: {border}px solid {checked_brd};
        }}
        QPushButton:checked:hover {{
            background-color: {checked_hover_bg};
            border: {border}px solid {checked_hover_brd};
        }}
    """


def filter_action_button_stylesheet(
    *,
    font: int,
    pad_v: int,
    pad_h: int,
    min_h: int,
    radius: int,
    border: int,
) -> str:
    """Apply / Clear row in the filter popup."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, brd = "#383838", "#444444"
        hover_bg, pressed_bg = "#404040", "#3a324a"
        dis_bg, dis_brd = "#222222", "#2d2d2d"
    else:
        bg, brd = p.button_secondary_bg, p.button_secondary_border
        hover_bg, pressed_bg = p.button_secondary_hover_bg, p.button_secondary_pressed_bg
        dis_bg, dis_brd = p.button_disabled_bg, p.button_disabled_border
    return f"""
        QPushButton {{
            background-color: {bg};
            color: #ffffff;
            border: {border}px solid {brd};
            border-radius: {radius}px;
            font-family: {_MENU_FONT};
            font-weight: bold;
            font-size: {font}px;
            padding: {pad_v}px {pad_h}px;
            min-height: {min_h}px;
        }}
        QPushButton:hover {{ background-color: {hover_bg}; border: {border}px solid #6b5a8e; }}
        QPushButton:pressed {{ background-color: {pressed_bg}; border: {border}px solid #b29ae7; }}
        QPushButton:disabled {{
            background-color: {dis_bg};
            color: #555555;
            border: {border}px solid {dis_brd};
        }}
        QPushButton::menu-indicator {{ image: none; }}
    """


def filter_date_time_input_stylesheet(
    *,
    font: int,
    pad_v: int,
    pad_h: int,
    min_h: int,
    radius: int,
    border: int,
    drop_w: int,
    spin_w: int,
    arrow_up: str,
    arrow_down: str,
    arrow_sz: int,
) -> str:
    """QDateEdit / QTimeEdit rows inside the filter popup."""
    p = _active
    c = combo_chrome_colors()
    if p.name == UI_THEME_DEFAULT:
        bg, brd = "#383838", "#444444"
        hover_bg, focus_bg = "#404040", "#3a324a"
        drop_bg = "#333333"
        cal_bg, cal_alt = "#252525", "#2d2d2d"
        cal_btn = "#383838"
    else:
        bg, brd = c.field_bg, c.field_border
        hover_bg, focus_bg = c.field_hover_bg, p.button_secondary_pressed_bg
        drop_bg = c.drop_bg
        cal_bg, cal_alt = c.popup_bg, c.popup_item_bg
        cal_btn = c.field_bg
    return f"""
        QDateEdit, QTimeEdit {{
            background-color: {bg};
            color: #ffffff;
            border: {border}px solid {brd};
            border-radius: {radius}px;
            font-family: {_MENU_FONT};
            font-weight: bold;
            font-size: {font}px;
            padding: {pad_v}px {pad_h}px;
            min-height: {min_h}px;
            max-height: {min_h + 2}px;
        }}
        QDateEdit:hover, QTimeEdit:hover {{
            background-color: {hover_bg};
            border: {border}px solid #6b5a8e;
        }}
        QDateEdit:focus, QTimeEdit:focus {{
            background-color: {focus_bg};
            border: {border}px solid #b29ae7;
        }}
        QDateEdit::drop-down {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: {drop_w}px;
            border-left: 1px solid {brd};
            border-top-right-radius: {radius - 1}px;
            border-bottom-right-radius: {radius - 1}px;
            background-color: {drop_bg};
        }}
        QTimeEdit::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: {spin_w}px;
            border-left: 1px solid {brd};
            border-bottom: 1px solid {brd};
            border-top-right-radius: {radius - 1}px;
            background-color: {drop_bg};
        }}
        QTimeEdit::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: {spin_w}px;
            border-left: 1px solid {brd};
            border-bottom-right-radius: {radius - 1}px;
            background-color: {drop_bg};
        }}
        QDateEdit::drop-down:hover, QTimeEdit::up-button:hover, QTimeEdit::down-button:hover {{
            background-color: #6b5a8e;
        }}
        QDateEdit::drop-down:pressed, QTimeEdit::up-button:pressed, QTimeEdit::down-button:pressed {{
            background-color: #b29ae7;
        }}
        QTimeEdit::up-arrow {{
            image: url("{arrow_up}");
            width: {arrow_sz}px; height: {arrow_sz}px;
        }}
        QTimeEdit::down-arrow, QDateEdit::down-arrow {{
            image: url("{arrow_down}");
            width: {arrow_sz}px; height: {arrow_sz}px;
        }}
        QCalendarWidget QWidget {{
            alternate-background-color: {cal_alt};
            background-color: {cal_bg};
            color: white;
        }}
        QCalendarWidget QToolButton {{
            color: white;
            background-color: {cal_btn};
            border-radius: 4px;
            padding: 2px;
        }}
        QCalendarWidget QToolButton:hover {{ background-color: #6b5a8e; }}
        QCalendarWidget QAbstractItemView:enabled {{
            color: white;
            background-color: {cal_bg};
            selection-background-color: #6b5a8e;
            selection-color: white;
            border-radius: 4px;
        }}
    """


def settings_density_line_edit_stylesheet(
    *,
    border: int,
    btn_r: int,
    field_font: int,
    ph: int,
) -> str:
    """Render panel filename field — combo face on dark themes."""
    c = combo_chrome_colors()
    p = _active
    if p.name == UI_THEME_DEFAULT:
        dis_bg, dis_border = "#262626", "#333333"
    else:
        dis_bg, dis_border = p.button_disabled_bg, p.button_disabled_border
    return (
        f"QLineEdit {{ background-color: {c.field_bg}; color: #ffffff;"
        f" border: {border}px solid {c.field_border}; border-radius: {btn_r}px;"
        f" font-family: {tok.FONT_APP}; font-weight: bold; font-size: {field_font}px;"
        f" padding: 0px {ph}px; }}"
        f" QLineEdit:hover {{ border: {border}px solid #6b5a8e; }}"
        f" QLineEdit:disabled {{ background-color: {dis_bg}; color: {c.popup_dis_fg};"
        f" border: {border}px solid {dis_border}; }}"
    )


def settings_density_push_button_stylesheet(
    *,
    border: int,
    btn_r: int,
    field_font: int,
    ph: int,
) -> str:
    """Render panel Save-as / destination row actions."""
    p = _active
    return (
        f"QPushButton {{ background-color: {p.button_secondary_bg}; color: #ffffff;"
        f" border: {border}px solid {p.button_secondary_border}; border-radius: {btn_r}px;"
        f" font-family: {tok.FONT_APP}; font-weight: bold; font-size: {field_font}px;"
        f" padding: 0px {ph}px; }}"
        f" QPushButton:hover {{ background-color: {p.button_secondary_hover_bg};"
        f" border: {border}px solid #6b5a8e; }}"
        f" QPushButton:pressed {{ background-color: {p.button_secondary_pressed_bg};"
        f" border: {border}px solid #b29ae7; }}"
    )


def settings_dialog_combo_stylesheet() -> str:
    """App Settings dialog QComboBox face — Default legacy gray; TrueDark combo tokens."""
    from steempeg.ui.widgets.combo_chrome import combo_popup_item_rules

    c = combo_chrome_colors()
    p = _active
    if p.name == UI_THEME_DEFAULT:
        dis_bg, dis_border, dis_fg = "#262626", "#333333", "#5a5a5a"
    else:
        dis_bg, dis_border = p.button_disabled_bg, p.button_disabled_border
        dis_fg = c.popup_dis_fg
    return f"""
    QComboBox {{
        background-color: {c.field_bg}; color: #ffffff;
        border: 2px solid {c.field_border}; border-radius: 8px;
        padding: 4px 10px; font-size: 12px; font-weight: bold;
        font-family: {tok.FONT_APP};
        min-height: 26px;
    }}
    QComboBox:hover {{ border: 2px solid #6b5a8e; }}
    QComboBox:disabled {{
        background-color: {dis_bg}; color: {dis_fg}; border: 2px solid {dis_border};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
""" + combo_popup_item_rules()


def settings_dialog_line_edit_stylesheet() -> str:
    """App Settings dialog QLineEdit — combo face on dark themes."""
    c = combo_chrome_colors()
    p = _active
    if p.name == UI_THEME_DEFAULT:
        dis_bg, dis_border, dis_fg = "#262626", "#333333", "#5a5a5a"
    else:
        dis_bg, dis_border = p.button_disabled_bg, p.button_disabled_border
        dis_fg = c.popup_dis_fg
    return f"""
    QLineEdit {{
        background-color: {c.field_bg}; color: #ffffff;
        border: 2px solid {c.field_border}; border-radius: 8px;
        padding: 4px 10px; font-size: 12px;
        font-family: {tok.FONT_APP};
        min-height: 26px;
    }}
    QLineEdit:hover {{ border: 2px solid #6b5a8e; }}
    QLineEdit:focus {{ border: 2px solid #8e7cc3; }}
    QLineEdit:disabled {{
        background-color: {dis_bg}; color: {dis_fg}; border: 2px solid {dis_border};
    }}
"""


def settings_dialog_secondary_button_stylesheet() -> str:
    """App Settings dialog secondary actions (Browse, Reset, Cancel, …)."""
    return dash_secondary_button_stylesheet(font=12, radius=8, pad="8px 16px")


def presets_line_edit_stylesheet(*, compact: bool = False) -> str:
    """Presets tab name / search fields."""
    c = combo_chrome_colors()
    pad = "6px 10px" if compact else "8px 10px"
    return (
        f"QLineEdit {{ background-color: {c.field_bg}; color: #e8e8e8;"
        f" border: 1px solid {c.field_border}; border-radius: 8px;"
        f" padding: {pad}; font-weight: bold; font-family: {tok.FONT_APP}; }}"
        f" QLineEdit:focus {{ border: 1px solid #8e7cc3; }}"
    )


def presets_list_widget_stylesheet() -> str:
    """Presets tab saved-preset list plate."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border, hover = "#2a2a2a", "#3a3a3a", "#383838"
    else:
        bg, border, hover = p.bg_elevated, p.button_secondary_border, p.neo_nav_hover_bg
    return (
        f"QListWidget {{ background-color: {bg}; border: 1px solid {border};"
        f" border-radius: 10px; color: #e0e0e0; padding: 4px; outline: none; }}"
        f" QListWidget::item {{ padding: 0px; border-radius: 8px; margin: 1px 0px; }}"
        f" QListWidget::item:selected {{ background-color: #4a3d66;"
        f" border: 1px solid #b29ae7; }}"
        f" QListWidget::item:hover:!selected {{ background-color: {hover}; }}"
    )


def presets_apply_split_stylesheet() -> str:
    """Preset row Apply ▾ split — matches RefreshButton secondary family."""
    p = _active
    side_border = p.border_default if p.name != UI_THEME_DEFAULT else "#555555"
    return f"""
    QPushButton#PresetApplyMain {{
        font-family: {tok.FONT_APP};
        font-size: 11px;
        font-weight: bold;
        background-color: {p.button_secondary_bg};
        color: #ffffff;
        border: 2px solid {p.button_secondary_border};
        border-right: none;
        border-top-left-radius: 12px;
        border-bottom-left-radius: 12px;
        border-top-right-radius: 0px;
        border-bottom-right-radius: 0px;
        padding: 0px 10px;
        min-height: 22px;
    }}
    QPushButton#PresetApplyMain:hover {{
        background-color: {p.button_secondary_hover_bg};
        border: 2px solid #6b5a8e;
        border-right: none;
    }}
    QPushButton#PresetApplyMain:pressed {{
        background-color: {p.button_secondary_pressed_bg};
        border: 2px solid #b29ae7;
        border-right: none;
    }}
    QPushButton#PresetApplyMenu {{
        background-color: {p.button_secondary_bg};
        color: #ffffff;
        border: 2px solid {p.button_secondary_border};
        border-left: 1px solid {side_border};
        border-top-left-radius: 0px;
        border-bottom-left-radius: 0px;
        border-top-right-radius: 12px;
        border-bottom-right-radius: 12px;
        font-family: {tok.FONT_APP};
        font-size: 12px;
        font-weight: bold;
        min-width: 22px;
        max-width: 26px;
        padding: 2px 0;
        min-height: 22px;
    }}
    QPushButton#PresetApplyMenu:hover {{
        background-color: {p.button_secondary_hover_bg};
        color: #d4c4ff;
        border: 2px solid #6b5a8e;
        border-left: 1px solid #6b5a8e;
    }}
    QPushButton#PresetApplyMenu:pressed {{
        background-color: {p.button_secondary_pressed_bg};
        border: 2px solid #b29ae7;
        border-left: 1px solid #b29ae7;
    }}
    """


def _frameless_card_dialog_colors() -> dict[str, str]:
    """Shared face colors for About / FFmpeg error frameless cards.

    Default keeps the shipped #202020 family. TrueDark / OLED follow active
    elevated-card tokens so the windows match the shell (not the old lighter plate).
    """
    p = _active
    if p.name == UI_THEME_DEFAULT:
        return {
            "card_bg": "#202020",
            "card_border": "#444444",
            "title": "#b29ae7",
            "dim": "#888888",
            "text": "#dddddd",
            "disclaimer": "#8a8a8a",
            "btn_bg": "#333333",
            "btn_border": "#555555",
            "btn_hover_bg": "#444444",
            "btn_hover_border": "#777777",
            "btn_pressed_bg": "#222222",
            "danger_bg": "#4a2525",
            "danger_border": "#7a3535",
            "danger_hover_bg": "#6a2e2e",
            "danger_hover_border": "#9a4545",
            "danger_pressed_bg": "#3a1d1d",
            "accent_bg": "#4a3d66",
            "accent_border": "#6b5a8e",
            "accent_fg": "#f0ecff",
            "accent_hover_bg": "#5a4d76",
            "accent_pressed_bg": "#3a324a",
            "error_title": "#ff4444",
            "error_desc": "#cccccc",
            "log_bg": "#141414",
            "log_fg": "#ff8888",
            "log_border": "#333333",
        }
    return {
        "card_bg": p.bg_shell,
        "card_border": p.border_card,
        "title": "#b29ae7",
        "dim": "#888888",
        "text": "#e0e0e0",
        "disclaimer": "#7a7a7a",
        "btn_bg": p.button_secondary_bg,
        "btn_border": p.button_secondary_border,
        "btn_hover_bg": p.button_secondary_hover_bg,
        "btn_hover_border": "#555555",
        "btn_pressed_bg": p.button_secondary_pressed_bg,
        "danger_bg": "#4a2525",
        "danger_border": "#7a3535",
        "danger_hover_bg": "#6a2e2e",
        "danger_hover_border": "#9a4545",
        "danger_pressed_bg": "#3a1d1d",
        "accent_bg": "#4a3d66",
        "accent_border": "#6b5a8e",
        "accent_fg": "#f0ecff",
        "accent_hover_bg": "#5a4d76",
        "accent_pressed_bg": "#3a324a",
        "error_title": "#ff5555",
        "error_desc": "#c8c8c8",
        "log_bg": p.chrome_app_bg,
        "log_fg": "#ff9999",
        "log_border": p.border_card,
    }


def about_dialog_stylesheet() -> str:
    """About frameless card — Default legacy plate; TrueDark elevated tokens."""
    c = _frameless_card_dialog_colors()
    return f"""
    QWidget#AboutCard {{
        background-color: {c["card_bg"]};
        border: 1px solid {c["card_border"]};
        border-radius: 8px;
    }}
    QLabel {{ background: transparent; }}
    QLabel#AboutTitle {{ color: {c["title"]}; font-size: 22px; font-weight: bold; }}
    QLabel#AboutDim {{ color: {c["dim"]}; font-size: 11px; }}
    QLabel#AboutText {{ color: {c["text"]}; font-size: 12px; }}
    QLabel#AboutDisclaimer {{
        color: {c["disclaimer"]};
        font-size: 10px;
        font-style: italic;
    }}
    QPushButton {{
        background-color: {c["btn_bg"]};
        color: white;
        border: 1px solid {c["btn_border"]};
        border-radius: 16px;
        padding: 6px 24px;
        font-weight: bold;
        font-size: 12px;
        min-height: 32px;
        outline: none;
    }}
    QPushButton:hover {{
        background-color: {c["btn_hover_bg"]};
        border: 1px solid {c["btn_hover_border"]};
    }}
    QPushButton:pressed {{
        background-color: {c["btn_pressed_bg"]};
    }}
    QPushButton#AboutReportBtn {{
        background-color: {c["danger_bg"]};
        border: 1px solid {c["danger_border"]};
        color: #ffffff;
    }}
    QPushButton#AboutReportBtn:hover {{
        background-color: {c["danger_hover_bg"]};
        border: 1px solid {c["danger_hover_border"]};
    }}
    QPushButton#AboutReportBtn:pressed {{
        background-color: {c["danger_pressed_bg"]};
    }}
    QPushButton#AboutUpdateBtn {{
        background-color: {c["accent_bg"]};
        border: 1px solid {c["accent_border"]};
        color: {c["accent_fg"]};
    }}
    QPushButton#AboutUpdateBtn:hover {{
        background-color: {c["accent_hover_bg"]};
        border: 1px solid #b29ae7;
    }}
    QPushButton#AboutUpdateBtn:pressed {{
        background-color: {c["accent_pressed_bg"]};
    }}
"""


def render_error_dialog_stylesheet() -> str:
    """FFmpeg / render-failed frameless card — Default legacy; TrueDark tokens."""
    c = _frameless_card_dialog_colors()
    return f"""
    QWidget#RenderErrorShell {{
        background-color: {c["card_bg"]};
        border: 1px solid {c["card_border"]};
        border-radius: 8px;
    }}
    QLabel#ErrorTitle {{
        color: {c["error_title"]};
        font-size: 18px;
        font-weight: bold;
    }}
    QLabel#ErrorDesc {{
        color: {c["error_desc"]};
        font-size: 13px;
    }}
    QLabel#ErrorHint {{
        color: {c["text"]};
        font-size: 13px;
        font-weight: bold;
    }}
    QPushButton#ErrorLogToggle {{
        background: transparent;
        color: {c["dim"]};
        border: none;
        border-radius: 0;
        padding: 0;
        font-weight: normal;
        font-size: 12px;
        min-height: 0;
        text-align: left;
    }}
    QPushButton#ErrorLogToggle:hover {{
        background: transparent;
        color: {c["text"]};
        border: none;
    }}
    QPushButton#ErrorLogToggle:pressed {{
        background: transparent;
        border: none;
    }}
    QTextEdit {{
        background-color: {c["log_bg"]};
        color: {c["log_fg"]};
        border: 1px solid {c["log_border"]};
        border-radius: 6px;
        padding: 8px;
        font-family: Consolas, monospace;
        font-size: 11px;
    }}
    QScrollBar:vertical {{ border: none; background: transparent; width: 12px; }}
    QScrollBar::handle:vertical {{ background: transparent; border: none; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    QPushButton {{
        background-color: {c["btn_bg"]};
        color: white;
        border: 1px solid {c["btn_border"]};
        border-radius: 16px;
        padding: 6px 20px;
        font-weight: bold;
        font-size: 12px;
        min-height: 32px;
        outline: none;
    }}
    QPushButton:hover {{
        background-color: {c["btn_hover_bg"]};
        border: 1px solid {c["btn_hover_border"]};
    }}
    QPushButton:pressed {{
        background-color: {c["btn_pressed_bg"]};
    }}
    QPushButton#LogBtn {{
        background-color: {c["danger_bg"]};
        border: 1px solid {c["danger_border"]};
    }}
    QPushButton#LogBtn:hover {{
        background-color: {c["danger_hover_bg"]};
        border: 1px solid {c["danger_hover_border"]};
    }}
    QPushButton#StopBtn {{
        background-color: {c["danger_bg"]};
        border: 1px solid {c["danger_border"]};
    }}
    QPushButton#StopBtn:hover {{
        background-color: {c["danger_hover_bg"]};
        border: 1px solid {c["danger_hover_border"]};
    }}
"""


def update_center_row_stylesheet(*, band: str, selected: bool, indent: bool) -> str:
    """Version list row chrome — Default legacy grays; TrueDark plate tokens."""
    p = _active
    if selected:
        if band == "ancient":
            return """
    QFrame#versionRow {
        background-color: #4a2a32;
        border: 1px solid #6b5a8e;
        border-radius: 8px;
    }
"""
        if band == "risky":
            return """
    QFrame#versionRow {
        background-color: #4a3a28;
        border: 1px solid #6b5a8e;
        border-radius: 8px;
    }
"""
        return """
    QFrame#versionRow {
        background-color: #3a324a;
        border: 1px solid #6b5a8e;
        border-radius: 8px;
    }
"""
    if band == "ancient":
        if indent:
            return """
    QFrame#versionRow {
        background-color: #322022;
        border: 1px solid #4a2830;
        border-radius: 6px;
    }
"""
        return """
    QFrame#versionRow {
        background-color: #3a2226;
        border: 1px solid #5a3038;
        border-radius: 8px;
    }
"""
    if band == "risky":
        if indent:
            return """
    QFrame#versionRow {
        background-color: #322818;
        border: 1px solid #4a3a20;
        border-radius: 6px;
    }
"""
        return """
    QFrame#versionRow {
        background-color: #3a2e22;
        border: 1px solid #5a4a28;
        border-radius: 8px;
    }
"""
    if p.name == UI_THEME_DEFAULT:
        if indent:
            return """
    QFrame#versionRow {
        background-color: #262626;
        border: 1px solid #333333;
        border-radius: 6px;
    }
"""
        return """
    QFrame#versionRow {
        background-color: #2a2a2a;
        border: 1px solid #353535;
        border-radius: 8px;
    }
"""
    if indent:
        bg, border, radius = p.bg_clip_card_plate, p.border_card, "6px"
    else:
        bg, border, radius = p.bg_elevated, p.border_card, "8px"
    return f"""
    QFrame#versionRow {{
        background-color: {bg};
        border: 1px solid {border};
        border-radius: {radius};
    }}
"""


def update_center_notes_stylesheet() -> str:
    """Release notes QTextEdit — Default legacy; TrueDark shell black."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border = "#1a1a1a", "#3d3d3d"
    else:
        bg, border = p.chrome_app_bg, p.border_card
    return f"""
    QTextEdit {{
        background-color: {bg};
        border: 1px solid {border};
        border-radius: 8px;
        color: {tok.TEXT_PRIMARY};
        font-family: {tok.FONT_APP};
        font-size: 13px;
        padding: 14px 16px;
        selection-background-color: #4a3d66;
        selection-color: #f0ecff;
    }}
"""


def update_center_btn_primary_stylesheet() -> str:
    """Update Center primary CTA — accent purple in all themes."""
    p = _active
    dis_bg = "#2a2a2a" if p.name == UI_THEME_DEFAULT else p.button_disabled_bg
    dis_border = "#444444" if p.name == UI_THEME_DEFAULT else p.button_disabled_border
    return f"""
    QPushButton {{
        background-color: #4a3d66; color: #f0ecff; border: 2px solid #6b5a8e;
        border-radius: 8px; padding: 6px 14px; font-size: 12px; font-weight: bold;
    }}
    QPushButton:hover {{ background-color: #5a4d76; border-color: #b29ae7; }}
    QPushButton:pressed {{ background-color: #3a324a; }}
    QPushButton:disabled {{ background-color: {dis_bg}; color: #666; border-color: {dis_border}; }}
"""


def update_center_btn_secondary_stylesheet() -> str:
    """Update Center secondary actions — TrueDark secondary button family."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border, hover = "#333333", "#555555", "#444444"
        dis_bg, dis_border = "#2a2a2a", "#444444"
        return f"""
    QPushButton {{
        background-color: {bg}; color: #ccc; border: 1px solid {border};
        border-radius: 8px; padding: 6px 14px; font-size: 12px;
    }}
    QPushButton:hover {{ background-color: {hover}; color: #fff; border-color: #6b5a8e; }}
    QPushButton:disabled {{ background-color: {dis_bg}; color: #666; border-color: {dis_border}; }}
"""
    # Card-plate fill reads darker on the dialog shell than button_secondary_bg alone.
    bg = p.bg_card
    border = p.button_secondary_border
    hover = p.button_secondary_hover_bg
    pressed = p.button_secondary_pressed_bg
    dis_bg = p.button_disabled_bg
    dis_border = p.button_disabled_border
    return f"""
    QPushButton {{
        font-family: {tok.FONT_APP};
        font-size: 12px;
        font-weight: bold;
        background-color: {bg};
        color: #ffffff;
        border: 2px solid {border};
        border-radius: 8px;
        padding: 6px 14px;
        outline: none;
    }}
    QPushButton:hover {{
        background-color: {hover};
        border: 2px solid #6b5a8e;
    }}
    QPushButton:pressed {{
        background-color: {pressed};
        border: 2px solid #b29ae7;
    }}
    QPushButton:disabled {{
        background-color: {dis_bg};
        color: #555555;
        border: 2px solid {dis_border};
    }}
    QPushButton::menu-indicator {{ image: none; }}
"""


def update_center_btn_current_stylesheet() -> str:
    """Update Center — installed version indicator (secondary plate, non-actionable)."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border = "#333333", "#555555"
        return f"""
    QPushButton {{
        background-color: {bg}; color: #ccc; border: 1px solid {border};
        border-radius: 8px; padding: 6px 14px; font-size: 12px;
    }}
    QPushButton:disabled {{ background-color: {bg}; color: #888; border-color: {border}; }}
"""
    bg = p.bg_card
    border = p.button_secondary_border
    return f"""
    QPushButton {{
        font-family: {tok.FONT_APP};
        font-size: 12px;
        font-weight: bold;
        background-color: {bg};
        color: #888888;
        border: 2px solid {border};
        border-radius: 8px;
        padding: 6px 14px;
        outline: none;
    }}
    QPushButton:disabled {{
        background-color: {bg};
        color: #888888;
        border: 2px solid {border};
    }}
    QPushButton::menu-indicator {{ image: none; }}
"""


def update_center_backup_frame_stylesheet() -> str:
    """Backup picker plate under the version list."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        bg, border = "#262626", "#3d3d3d"
    else:
        bg, border = p.bg_elevated, p.border_panel
    return f"""
    QFrame#updateBackupFrame {{
        background-color: {bg};
        border: 1px solid {border};
        border-radius: 8px;
    }}
"""


def update_center_ack_frame_stylesheet() -> str:
    """Risk acknowledgement strip before install."""
    return """
    QFrame#updateAckFrame {
        background-color: #3a324a;
        border: 1px solid #6b5a8e;
        border-radius: 8px;
    }
"""


def update_center_icon_btn_stylesheet() -> str:
    """Per-row info / expand icon buttons."""
    p = _active
    hover = "#454545" if p.name == UI_THEME_DEFAULT else p.neo_nav_hover_bg
    return f"""
    QPushButton {{
        background-color: transparent; color: #ccc; border: none;
        min-width: 20px; max-width: 20px;
        min-height: 20px; max-height: 20px; padding: 0;
    }}
    QPushButton:hover {{ background-color: {hover}; border-radius: 10px; }}
"""


def update_center_scroll_extras_stylesheet(*, bg_shell: str) -> str:
    """Scroll viewport + release list host fill."""
    return f"""
    {tok.dialog_scroll_stylesheet(bg_shell)}
    QWidget#releaseListHost {{ background-color: {bg_shell}; }}
"""


def render_history_surface_stylesheet() -> str:
    """Batch + job card faces for Render History."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        batch_bg, batch_border = "#2a2a2a", "#3d3d3d"
        job_bg, job_border = "#242424", "#353535"
    else:
        batch_bg, batch_border = p.bg_elevated, p.border_panel
        job_bg, job_border = p.bg_clip_card_plate, p.border_card
    return f"""
    QFrame#batchFrame {{
        background-color: {batch_bg};
        border: 1px solid {batch_border};
        border-radius: 10px;
    }}
    QFrame#jobFrame {{
        background-color: {job_bg};
        border: 1px solid {job_border};
        border-radius: 8px;
    }}
"""


def render_history_pill_button_stylesheet(*, bold: bool = True) -> str:
    """Clear all / Details / Source clip — toolbar secondary family."""
    weight = "bold" if bold else "normal"
    return toolbar_text_button_stylesheet(radius=8, font_px=13, height=32).replace(
        "font-weight: bold;",
        f"font-weight: {weight};",
        1,
    )


def render_history_close_button_stylesheet() -> str:
    """Footer Close — accent tint in Default; dark secondary in TrueDark."""
    p = _active
    if p.name == UI_THEME_DEFAULT:
        return """
    QPushButton {
        background-color: #3a324a; color: #e0d4ff; border: 1px solid #6b5a8e;
        border-radius: 8px; padding: 8px 16px; font-weight: bold;
    }
    QPushButton:hover { background-color: #4a3f5c; }
"""
    return f"""
    QPushButton {{
        background-color: {p.button_secondary_bg}; color: #e0e0e0;
        border: 2px solid {p.button_secondary_border};
        border-radius: 8px; padding: 8px 16px; font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: {p.button_secondary_hover_bg};
        color: #ffffff;
        border: 2px solid #6b5a8e;
    }}
    QPushButton:pressed {{
        background-color: {p.button_secondary_pressed_bg};
        border: 2px solid #b29ae7;
    }}
"""


def about_dialog_link_style() -> str:
    """Inline HTML link color for About (accent stays brand purple)."""
    return "color:#b29ae7; text-decoration:none;"


def about_dialog_muted_span_color() -> str:
    """Inline muted span color for About developer handle."""
    return _frameless_card_dialog_colors()["dim"]


def render_error_scrollbar_colors() -> tuple[str, str, str]:
    """Track / thumb / thumb-hover for the FFmpeg error log scroller."""
    c = _frameless_card_dialog_colors()
    if _active.name == UI_THEME_DEFAULT:
        return ("#141414", "#444444", "#666666")
    return (c["log_bg"], c["card_border"], "#666666")
