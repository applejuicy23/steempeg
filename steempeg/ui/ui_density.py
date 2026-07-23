"""UI density: continuous scale between compact (Steam Deck ~1280×800) and comfort.

Panel splitter mins live in layout_defaults; this module covers chrome —
fonts, paddings, fixed control sizes, and short labels.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields

from steempeg.ui.layout_defaults import (
    clamp01,
    is_compact_layout,
    layout_scale,
    lerp_int,
)

_PAD_TOKEN_RE = re.compile(r"(\d+)px")


@dataclass(frozen=True)
class UiDensity:
    compact: bool
    scale: float  # 0.0 compact … 1.0 comfort

    # Library tabs
    tab_height: int
    tab_font: int
    tab_pad_l: int
    tab_pad_r: int
    tab_radius: int
    add_tab_size: int

    # Left toolbar mega-capsule
    toolbar_margin_h: int
    toolbar_pad_h: int
    toolbar_pad_v: int
    toolbar_spacing: int
    toolbar_label_font: int
    toggle_pad: str  # "4px 8px"
    toggle_font: int
    filter_size: int
    combo_font: int
    combo_min_h: int
    combo_pad: str

    # Footer mega-pill
    footer_font: int
    footer_pad: str
    footer_min_h: int
    footer_radius: int
    footer_add_w: int

    # Neo settings sidebar
    neo_sidebar_w: int
    neo_nav_font: int
    neo_nav_pad: str

    # Queue
    queue_empty_w: int
    queue_thumb_w: int
    queue_thumb_h: int
    queue_tool_pad_h: int
    queue_btn_h: int

    # Render settings (Source / Video / Audio / Export)
    settings_stat_w: int
    settings_content_w: int
    settings_combo_w: int
    settings_title_font: int
    settings_page_margin: tuple  # L,T,R,B

    # Player transport
    skip_w: int
    skip_h: int
    play_w: int
    play_h: int
    chrome_chip: int  # theater / fullscreen / marker / etc.

    # Render status dashboard
    dash_margin_h: int
    dash_margin_v: int
    dash_spacing: int
    dash_font: int
    dash_btn_h: int

    # Combo popup list rows
    combo_popup_item_h: int
    combo_popup_item_pad_v: int
    combo_popup_item_pad_h: int


def _lerp_pad_str(a: str, b: str, t: float) -> str:
    """Lerp CSS padding strings like '6px 16px' or '10px 15px'."""
    ta = [int(x) for x in _PAD_TOKEN_RE.findall(a)]
    tb = [int(x) for x in _PAD_TOKEN_RE.findall(b)]
    if not ta or len(ta) != len(tb):
        return b if t >= 0.5 else a
    parts = [f"{lerp_int(x, y, t)}px" for x, y in zip(ta, tb)]
    return " ".join(parts)


def _lerp_margin_tuple(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(lerp_int(int(x), int(y), t) for x, y in zip(a, b))


COMFORT = UiDensity(
    compact=False,
    scale=1.0,
    tab_height=40,
    tab_font=14,
    tab_pad_l=14,
    tab_pad_r=6,
    tab_radius=16,
    add_tab_size=40,
    toolbar_margin_h=12,
    toolbar_pad_h=16,
    toolbar_pad_v=6,
    toolbar_spacing=14,
    toolbar_label_font=13,
    toggle_pad="6px 16px",
    toggle_font=12,
    filter_size=36,
    combo_font=13,
    combo_min_h=24,
    combo_pad="4px 10px",
    footer_font=13,
    footer_pad="4px 12px",
    footer_min_h=24,
    footer_radius=14,
    footer_add_w=40,
    neo_sidebar_w=220,
    neo_nav_font=14,
    neo_nav_pad="10px 15px",
    queue_empty_w=300,
    queue_thumb_w=128,
    queue_thumb_h=76,
    queue_tool_pad_h=16,
    queue_btn_h=32,
    settings_stat_w=210,
    settings_content_w=646,  # 210*3 + 8*2
    # Video/Audio: (content - grid16 - 2*(gap8+slot16)) // 2
    settings_combo_w=(646 - 16 - 2 * (8 + 16)) // 2,  # 291
    settings_title_font=15,
    settings_page_margin=(16, 15, 8, 8),
    skip_w=40,
    skip_h=48,
    play_w=80,
    play_h=48,
    chrome_chip=40,
    dash_margin_h=18,
    dash_margin_v=16,
    dash_spacing=12,
    dash_font=14,
    dash_btn_h=36,
    combo_popup_item_h=28,
    combo_popup_item_pad_v=7,
    combo_popup_item_pad_h=10,
)

COMPACT = UiDensity(
    compact=True,
    scale=0.0,
    tab_height=30,
    tab_font=11,
    tab_pad_l=8,
    tab_pad_r=4,
    tab_radius=12,
    add_tab_size=30,
    toolbar_margin_h=6,
    toolbar_pad_h=8,
    toolbar_pad_v=4,
    toolbar_spacing=6,
    toolbar_label_font=11,
    toggle_pad="3px 8px",
    toggle_font=11,
    filter_size=22,
    combo_font=13,
    combo_min_h=18,
    combo_pad="1px 5px",
    footer_font=10,
    footer_pad="2px 5px",
    footer_min_h=16,
    footer_radius=9,
    footer_add_w=26,
    neo_sidebar_w=118,
    neo_nav_font=10,
    neo_nav_pad="3px 5px",
    queue_empty_w=220,
    queue_thumb_w=80,
    queue_thumb_h=46,
    queue_tool_pad_h=6,
    queue_btn_h=24,
    # Fits center column with neo sidebar on Deck (~600px free): 118 + ~360
    settings_stat_w=108,
    settings_content_w=340,
    # Same Video/Audio formula as comfort, from compact content width.
    settings_combo_w=(340 - 16 - 2 * (8 + 16)) // 2,  # 138
    settings_title_font=11,
    settings_page_margin=(4, 4, 2, 2),
    skip_w=30,
    skip_h=36,
    play_w=58,
    play_h=36,
    chrome_chip=28,
    dash_margin_h=4,
    dash_margin_v=4,
    dash_spacing=3,
    dash_font=10,
    dash_btn_h=20,
    combo_popup_item_h=18,
    combo_popup_item_pad_v=2,
    combo_popup_item_pad_h=5,
)

# Short chrome labels used only in compact density.
TAB_LABELS_COMFORT = {
    "clips": "📁 Clips Manager",
    "rendered": "🎬 Rendered videos",
    "queue": "🎬 Render Queue",
}
TAB_LABELS_COMPACT = {
    "clips": "📁 Clips",
    "rendered": "🎬 Rendered",
    "queue": "🎬 Queue",
}

NEO_NAV_COMFORT = [
    "ℹ️  Source Info",
    "🎬  Video Settings",
    "🎵  Audio Settings",
    "🚀  Export Settings",
]
NEO_NAV_COMPACT = [
    "ℹ️  Source",
    "🎬  Video",
    "🎵  Audio",
    "🚀  Export",
]


def lerp_density(t: float) -> UiDensity:
    """Build chrome density between COMPACT (t=0) and COMFORT (t=1)."""
    t = clamp01(t)
    if t <= 0.0:
        return COMPACT
    if t >= 1.0:
        return COMFORT

    kwargs = {"compact": t < 0.5, "scale": t}
    for f in fields(UiDensity):
        name = f.name
        if name in ("compact", "scale"):
            continue
        a = getattr(COMPACT, name)
        b = getattr(COMFORT, name)
        if isinstance(a, int) and isinstance(b, int):
            kwargs[name] = lerp_int(a, b, t)
        elif isinstance(a, str) and isinstance(b, str):
            kwargs[name] = _lerp_pad_str(a, b, t)
        elif isinstance(a, tuple) and isinstance(b, tuple):
            kwargs[name] = _lerp_margin_tuple(a, b, t)
        else:
            kwargs[name] = b if t >= 0.5 else a
    return UiDensity(**kwargs)


def density_for_width(window_width: int) -> UiDensity:
    return lerp_density(layout_scale(window_width))


def chrome_equal(a: UiDensity | None, b: UiDensity | None) -> bool:
    """True when discrete chrome metrics match (ignore float ``scale``).

    Continuous layout_scale changes ``scale`` on every pixel of resize. Comparing
    full UiDensity would re-apply styles / rebuild queue cards constantly and
    thrash DWM next to the mpv surface.
    """
    if a is None or b is None:
        return False
    if a is b:
        return True
    for f in fields(UiDensity):
        if f.name == "scale":
            continue
        if getattr(a, f.name) != getattr(b, f.name):
            return False
    return True


# Sensible pill radii — Qt Style Sheets often fail/ignore absurd values like 999px.
_TOGGLE_BTN_R_COMFORT = 12
_TOOLBAR_PILL_R_COMFORT = 20


def _toggle_pad_v(dense: UiDensity) -> int:
    parts = [int(x) for x in _PAD_TOKEN_RE.findall(dense.toggle_pad or "")]
    return parts[0] if parts else 4


def toggle_segment_radius(dense: UiDensity) -> int:
    """Half of the approximate Grid/List segment height → capsule ends."""
    h = dense.toggle_font + _toggle_pad_v(dense) * 2 + 2
    return max(8, min(_TOGGLE_BTN_R_COMFORT, h // 2))


def toggle_track_radius(dense: UiDensity) -> int:
    return max(10, toggle_segment_radius(dense) + 2)


def toolbar_pill_radius(dense: UiDensity | None = None) -> int:
    if dense is None:
        return _TOOLBAR_PILL_R_COMFORT
    # Comfort 20 → compact ~14
    return max(12, lerp_int(14, _TOOLBAR_PILL_R_COMFORT, dense.scale))


def view_toggle_track_style(dense: UiDensity | None = None) -> str:
    """Dark track behind Grid/List."""
    d = dense if dense is not None else COMFORT
    r = toggle_track_radius(d)
    return (
        f"QFrame {{ background-color: #141414; border-radius: {r}px; border: none; }}"
    )


def view_toggle_button_styles(dense: UiDensity) -> tuple[str, str]:
    """Active / inactive Grid·List segment styles."""
    r = toggle_segment_radius(dense)
    active = (
        f"background-color: #5138e6; color: white; border-radius: {r}px; "
        f"font-weight: bold; font-size: {dense.toggle_font}px; "
        f"padding: {dense.toggle_pad}; border: none;"
    )
    inactive = (
        f"background-color: transparent; color: #888888; border-radius: {r}px; "
        f"font-weight: bold; font-size: {dense.toggle_font}px; "
        f"padding: {dense.toggle_pad}; border: none;"
    )
    return active, inactive


def toolbar_mega_pill_style(dense: UiDensity | None = None, *, object_name: str = "") -> str:
    """Outer floating island (library / queue toolbar). Prefer objectName to avoid cascade."""
    r = toolbar_pill_radius(dense)
    if object_name:
        return f"""
            QFrame#{object_name} {{
                background-color: #2d2d2d;
                border: 1px solid #353535;
                border-radius: {r}px;
            }}
            QFrame#{object_name} > QLabel {{
                border: none;
                background: transparent;
            }}
        """
    return f"""
        QFrame {{
            background-color: #2d2d2d;
            border: 1px solid #353535;
            border-radius: {r}px;
        }}
        QLabel {{ border: none; background: transparent; }}
    """


def tab_label(mode: str, dense: UiDensity) -> str:
    table = TAB_LABELS_COMPACT if dense.compact else TAB_LABELS_COMFORT
    return table.get(mode, mode)


def folder_button_label(folder_count: int, dense: UiDensity) -> str:
    if dense.compact:
        base = "📂 Folder"
    else:
        base = "📂 Choose Folder…"
    if folder_count > 1:
        return f"{base} ({folder_count})"
    return base


def updates_button_label(dense: UiDensity) -> str:
    return "🔄 Updates" if dense.compact else "🔄 Check for updates"


def settings_button_label(dense: UiDensity) -> str:
    return "⚙️ Settings"


def refresh_button_label(dense: UiDensity) -> str:
    return "🔄 Refresh"  # already short; keep emoji


def scaled_dialog_size(
    width: int,
    height: int,
    *,
    parent=None,
    factor: float = 0.82,
) -> tuple[int, int]:
    """Shrink dialog footprint continuously toward Deck-class screens."""
    from PySide6.QtWidgets import QApplication

    win_w = 0
    if parent is not None and hasattr(parent, "width"):
        try:
            win_w = int(parent.width())
        except Exception:
            win_w = 0
    if win_w <= 0:
        aw = QApplication.activeWindow()
        if aw is not None:
            win_w = int(aw.width())
    t = layout_scale(win_w)
    # t=1 → no shrink; t=0 → full factor shrink
    scale = factor + (1.0 - factor) * t
    return max(300, int(width * scale)), max(240, int(height * scale))
