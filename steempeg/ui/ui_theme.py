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
    button_disabled_bg: str
    button_disabled_border: str


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
    tooltip_bg="#2c2b2e",
    tooltip_border="#5a5a5a",
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
    button_disabled_bg="#222222",
    button_disabled_border="#2d2d2d",
)

# TrueDark — darker unified family; card/settings/player share one elevated tone.
_PALETTE_TRUE_DARK = UiThemePalette(
    name=UI_THEME_TRUE_DARK,
    chrome_title_bar="#1a1a1a",
    chrome_app_bg="#0f0f0f",
    bg_shell="#121212",
    bg_player_canvas="#1a1a1a",
    bg_card="#1a1a1a",
    bg_settings_panel="#1a1a1a",
    bg_player_header="#1a1a1a",
    bg_placeholder_canvas="#0f0f0f",
    bg_elevated="#1a1a1a",
    border_card="#2a2a2a",
    border_panel="#2a2a2a",
    border_default="#333333",
    border_subtle="#000000",
    tooltip_bg="#252525",
    tooltip_border="#444444",
    neo_nav_hover_bg="#2a2a2a",
    neo_nav_checked_bg="#1f1f1f",
    neo_nav_idle="#909090",
    neo_nav_hover_border="#5a4b7a",
    neo_nav_checked_border="#8e7cc3",
    settings_btn_bg="#252525",
    settings_btn_border="#333333",
    settings_btn_hover_bg="#1f1f1f",
    settings_btn_pressed_bg="#0f0f0f",
    button_secondary_bg="#2a2a2a",
    button_secondary_border="#383838",
    button_disabled_bg="#1a1a1a",
    button_disabled_border="#252525",
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
    tooltip_bg="#1a1a1a",
    tooltip_border="#333333",
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
    button_disabled_bg="#0a0a0a",
    button_disabled_border="#1a1a1a",
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


def elevated_panel_stylesheet(*, object_name: str | None = None) -> str:
    """Library / queue / render dashboard card face."""
    p = _active
    selector = f"QFrame#{object_name}" if object_name else "QFrame"
    return (
        f"{selector} {{ background-color: {p.bg_elevated}; "
        f"border: 1px solid {p.border_panel}; border-radius: 12px; }}"
    )


def player_header_stylesheet() -> str:
    """Player title bar — rounded top only; squares off at canvas seam."""
    p = _active
    return f"""
        QFrame {{
            background-color: {p.bg_player_header};
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            border-bottom-left-radius: 0px;
            border-bottom-right-radius: 0px;
        }}
    """


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
        QPushButton:hover {{ background-color: #404040; border: 2px solid #6b5a8e; }}
        QPushButton:pressed {{ background-color: #3a324a; border: 2px solid #b29ae7; }}
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
        QScrollBar:vertical {{
            background: transparent;
            width: 12px;
            margin: 15px 5px 15px 0px;
        }}
        QScrollBar::handle:vertical {{
            background: #5a4b7a;
            min-height: 30px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: #8e7cc3;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
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


def player_footer_stylesheet() -> str:
    """Player HUD / control bar — rounded bottom only; squares off at canvas seam.

    Do not add ``border: none`` here: Qt QSS then skips clipping the fill to
    ``border-radius``, which squares off #HudFrame.
    """
    p = _active
    return f"""
        #HudFrame {{
            background-color: {p.bg_player_header};
            border-top-left-radius: 0px;
            border-top-right-radius: 0px;
            border-bottom-left-radius: 6px;
            border-bottom-right-radius: 6px;
        }}
    """


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
