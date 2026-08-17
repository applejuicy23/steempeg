"""UI density: continuous scale between compact (Steam Deck ~1280×800) and comfort.

Panel splitter mins live in layout_defaults; this module covers chrome —
fonts, paddings, fixed control sizes, and short labels.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields

from steempeg.ui.layout_defaults import (
    FHD_SHELL_WIDTH,
    clamp01,
    lerp_int,
    shell_layout_scale,
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

    # Neo settings sidebar + content page-title glyph size
    neo_sidebar_w: int
    neo_nav_font: int
    neo_nav_pad: str  # T R B L (left = space before icon)
    neo_nav_icon: int  # sidebar + page-header glyph (16 comfort / 12 compact)
    neo_nav_icon_gap: int  # transparent pad after sidebar icon (icon→text)

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

    # Player header (title cluster + status/action chips)
    header_icon: int
    header_font: int
    header_pad_h: int
    header_pad_v: int
    header_chip: int  # preview settings / close
    header_chip_icon: int
    header_min_h: int
    header_status_pad: str  # Healthy / Preview chip CSS padding

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
    # T R B L — left pad breathes from tab edge; right keeps label off the border.
    neo_nav_pad="10px 12px 10px 14px",
    neo_nav_icon=16,
    neo_nav_icon_gap=8,
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
    # Pre-density-bump desktop strip (icon 24 / font 13 / pads 10×8 / chip 30).
    header_icon=24,
    header_font=13,
    header_pad_h=10,
    header_pad_v=8,
    header_chip=30,
    header_chip_icon=16,
    header_min_h=46,
    header_status_pad="3px 10px 3px 8px",
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
    neo_nav_pad="4px 4px 4px 8px",
    neo_nav_icon=12,
    neo_nav_icon_gap=5,
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
    header_icon=20,
    header_font=11,
    header_pad_h=6,
    header_pad_v=4,
    header_chip=26,
    header_chip_icon=14,
    header_min_h=34,
    header_status_pad="2px 8px 2px 6px",
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
    "screenshots": "📷 Screenshots",
    "queue": "🎬 Render Queue",
}
TAB_LABELS_COMPACT = {
    "clips": "📁 Clips",
    "rendered": "🎬 Rendered",
    "screenshots": "📷 Shots",
    "queue": "🎬 Queue",
}

NEO_NAV_COMFORT = [
    "Source Info",
    "Video Settings",
    "Audio Settings",
    "Export Settings",
    "Presets",
]
NEO_NAV_COMPACT = [
    "Source",
    "Video",
    "Audio",
    "Export",
    "Presets",
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


def scale_density_pixels(dense: UiDensity, factor: float) -> UiDensity:
    """Multiply discrete chrome pixel metrics by a PPI factor (pads too)."""
    if abs(factor - 1.0) < 0.02:
        return dense
    factor = max(0.65, min(1.25, float(factor)))

    def _px(v: int) -> int:
        return max(1, int(round(v * factor)))

    kwargs = {"compact": dense.compact, "scale": dense.scale}
    for f in fields(UiDensity):
        name = f.name
        if name in ("compact", "scale"):
            continue
        val = getattr(dense, name)
        if isinstance(val, int):
            kwargs[name] = _px(val)
        elif isinstance(val, str):
            parts = _PAD_TOKEN_RE.findall(val)
            if parts:
                kwargs[name] = " ".join(f"{_px(int(x))}px" for x in parts)
            else:
                kwargs[name] = val
        elif isinstance(val, tuple):
            kwargs[name] = tuple(_px(int(x)) for x in val)
        else:
            kwargs[name] = val
    return UiDensity(**kwargs)


def _ppi_pixel_factor(window_width: int, ppi_f: float) -> float:
    """Coarse-pixel shrink for DIP chrome — never a second compact lerp.

    Floor is 0.90. When the window is already full-comfort width (≥1520,
    including maximized 1080p), blend halfway to 1.0 so 27″ FHD (~82 PPI)
    is ~0.95 instead of stacking on a pulled-down ``t``.
    """
    f = float(ppi_f)
    t = shell_layout_scale(window_width)
    if t >= 1.0 and f < 1.0:
        f = 0.5 * f + 0.5
    return f


def density_for_width(window_width: int, *, widget=None, screen=None) -> UiDensity:
    """Chrome density: width chooses compact vs comfort; PPI mildly scales pixels.

    Two axes (do not multiply both on 1080p):

    * Small window (Deck / 1280 / half-screen) → ``shell_layout_scale`` toward
      compact. FHD-wide (≥1920) is always comfort ``t``.
    * Coarse pixels (big-inch FHD) → ``chrome_ppi_scale`` on DIP sizes only,
      damped when the window is already wide.
    """
    t = shell_layout_scale(window_width, widget=widget, screen=screen)
    if int(window_width or 0) >= FHD_SHELL_WIDTH:
        t = 1.0
    dense = lerp_density(t)
    from steempeg.ui.screen_metrics import chrome_ppi_scale

    return scale_density_pixels(
        dense, _ppi_pixel_factor(window_width, chrome_ppi_scale(widget, screen))
    )


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
# 16 lets comfort Grid/List be a true capsule (half of ~28px segment), matching RQ.
_TOGGLE_BTN_R_COMFORT = 16
_TOOLBAR_PILL_R_COMFORT = 20
VIEW_TOGGLE_TRACK_NAME = "viewToggleTrack"
VIEW_TOGGLE_SEG_NAME = "viewModeSeg"


def _toggle_pad_v(dense: UiDensity) -> int:
    parts = [int(x) for x in _PAD_TOKEN_RE.findall(dense.toggle_pad or "")]
    return parts[0] if parts else 4


def toggle_segment_min_height(dense: UiDensity) -> int:
    """Total Grid/List segment height (widget box, including padding).

    Render Queue language: comfort ≈ 12px type + 6px vertical pad + 4px chrome.
    Set in Python (not QSS min-height) so padding is not double-counted.
    """
    return dense.toggle_font + _toggle_pad_v(dense) * 2 + 4


def toggle_segment_radius(dense: UiDensity) -> int:
    """Half of the Grid/List segment height → capsule ends (RQ pill, not a rounded rect)."""
    h = toggle_segment_min_height(dense)
    return max(8, min(_TOGGLE_BTN_R_COMFORT, h // 2))


def toggle_track_radius(dense: UiDensity) -> int:
    return max(10, toggle_segment_radius(dense) + 2)


def toolbar_pill_radius(dense: UiDensity | None = None) -> int:
    if dense is None:
        return _TOOLBAR_PILL_R_COMFORT
    # Comfort 20 → compact ~14
    return max(12, lerp_int(14, _TOOLBAR_PILL_R_COMFORT, dense.scale))


def view_toggle_track_style(dense: UiDensity | None = None) -> str:
    """Dark track behind Grid/List. Object-name selector so parent QFrame sheets cannot square it."""
    d = dense if dense is not None else COMFORT
    r = toggle_track_radius(d)
    h = toggle_segment_min_height(d) + 4  # 2px layout margins on each side
    return (
        f"QFrame#{VIEW_TOGGLE_TRACK_NAME} {{"
        f" background-color: #141414; border-radius: {r}px; border: none;"
        f" min-height: {h}px;"
        f"}}"
    )


def view_toggle_button_styles(dense: UiDensity) -> tuple[str, str]:
    """Active / inactive Grid·List segment styles (RQ padding / type / capsule radius)."""
    r = toggle_segment_radius(dense)
    font = dense.toggle_font
    pad = dense.toggle_pad
    # Named selector beats ancestor QPushButton rules (footer/filter) that square Clips.
    active = (
        f"QPushButton#{VIEW_TOGGLE_SEG_NAME} {{"
        f" background-color: #5138e6; color: #ffffff; border-radius: {r}px;"
        f" font-weight: bold; font-size: {font}px; padding: {pad}; border: none;"
        f"}}"
    )
    inactive = (
        f"QPushButton#{VIEW_TOGGLE_SEG_NAME} {{"
        f" background-color: transparent; color: #888888; border-radius: {r}px;"
        f" font-weight: bold; font-size: {font}px; padding: {pad}; border: none;"
        f"}}"
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


def records_folder_button_label(dense: UiDensity) -> str:
    return "📂 Records" if dense.compact else "📂 Records folder…"


def screenshots_folder_button_label(dense: UiDensity) -> str:
    return "📂 Shots folder" if dense.compact else "📂 Screenshots folder…"


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
    """Shrink dialog footprint continuously toward Deck-class / low-PPI screens."""
    from PySide6.QtWidgets import QApplication

    win_w = 0
    host = parent
    if parent is not None and hasattr(parent, "width"):
        try:
            win_w = int(parent.width())
        except Exception:
            win_w = 0
    if win_w <= 0:
        aw = QApplication.activeWindow()
        if aw is not None:
            win_w = int(aw.width())
            host = aw
    t = shell_layout_scale(win_w, widget=host)
    # t=1 → no shrink; t=0 → full factor shrink
    scale = factor + (1.0 - factor) * t
    return max(300, int(width * scale)), max(240, int(height * scale))
