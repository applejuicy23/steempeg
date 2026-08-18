"""Shared QComboBox popup styling — selected item outline + visible disabled rows."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QComboBox

from steempeg.ui import design_tokens as tok
from steempeg.ui.ui_density import COMFORT, UiDensity

# Force light ink — Windows light OS theme otherwise paints near-black Text
# on our dark custom popup (QSS alone is not always enough).
_POPUP_FG = tok.TEXT_TITLE  # #e8e8e8


def _popup_bg() -> str:
    return tok.BG_SHELL
_POPUP_ITEM_BG = "#333333"
_POPUP_SEL_BG = "#3a3350"
_POPUP_SEL_FG = "#ffffff"
_POPUP_DIS_FG = "#5a5a5a"


def combo_popup_item_rules(dense: UiDensity | None = None) -> str:
    """Popup list row chrome scaled with UI density (avoids fat lists on Deck)."""
    d = dense or COMFORT
    h = d.combo_popup_item_h
    pv = d.combo_popup_item_pad_v
    ph = d.combo_popup_item_pad_h
    radius = 6 if d.scale >= 0.5 else 4
    border = 2 if d.scale >= 0.45 else 1
    return f"""
    QComboBox QAbstractItemView {{
        background-color: {_popup_bg()};
        color: {_POPUP_FG};
        border: 2px solid #4a4a4a;
        border-radius: 10px;
        padding: {max(2, pv - 2)}px;
        outline: none;
        selection-background-color: transparent;
        selection-color: {_POPUP_SEL_FG};
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: {h}px;
        padding: {pv}px {ph}px;
        border-radius: {radius}px;
        margin: 1px 2px;
        background-color: {_POPUP_ITEM_BG};
        color: {_POPUP_FG};
        border: {border}px solid transparent;
    }}
    QComboBox QAbstractItemView::item:hover:enabled {{
        background-color: #404040;
        color: {_POPUP_SEL_FG};
        border: {border}px solid #6b5a8e;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: {_POPUP_SEL_BG};
        color: {_POPUP_SEL_FG};
        border: {border}px solid #b29ae7;
    }}
    QComboBox QAbstractItemView::item:selected:enabled {{
        background-color: {_POPUP_SEL_BG};
        color: {_POPUP_SEL_FG};
        border: {border}px solid #b29ae7;
    }}
    QComboBox QAbstractItemView::item:disabled {{
        background-color: #262626;
        color: {_POPUP_DIS_FG};
        border: {border}px solid #333333;
    }}
"""


def apply_dark_combo_popup(
    combo: QComboBox,
    *,
    dense: UiDensity | None = None,
) -> None:
    """Force readable light text on dark combo popups (Windows light theme safe).

    Ensures ``QComboBox QAbstractItemView`` rules are present on the combo sheet
    (popup HWND often ignores ancestor dialog QSS) and overrides the view palette
    so OS light Text / WindowText cannot paint black on dark rows.
    """
    current = combo.styleSheet() or ""
    if "QAbstractItemView" not in current:
        combo.setStyleSheet(current + combo_popup_item_rules(dense))

    view = combo.view()
    if view is None:
        return

    bg = QColor(_popup_bg())
    fg = QColor(_POPUP_FG)
    item_bg = QColor(_POPUP_ITEM_BG)
    sel_bg = QColor(_POPUP_SEL_BG)
    sel_fg = QColor(_POPUP_SEL_FG)
    dis_fg = QColor(_POPUP_DIS_FG)

    pal = view.palette()
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        text = dis_fg if group == QPalette.ColorGroup.Disabled else fg
        pal.setColor(group, QPalette.ColorRole.Base, bg)
        pal.setColor(group, QPalette.ColorRole.AlternateBase, item_bg)
        pal.setColor(group, QPalette.ColorRole.Window, bg)
        pal.setColor(group, QPalette.ColorRole.Text, text)
        pal.setColor(group, QPalette.ColorRole.WindowText, text)
        pal.setColor(group, QPalette.ColorRole.Button, item_bg)
        pal.setColor(group, QPalette.ColorRole.ButtonText, text)
        pal.setColor(group, QPalette.ColorRole.Highlight, sel_bg)
        pal.setColor(group, QPalette.ColorRole.HighlightedText, sel_fg)
        pal.setColor(group, QPalette.ColorRole.BrightText, sel_fg)
    view.setPalette(pal)
    view.setAutoFillBackground(True)


# Default comfort popup (backward-compatible import for static QSS builders).
COMBO_POPUP_ITEM_RULES = combo_popup_item_rules(COMFORT)

SETTINGS_COMBO_FIELD_RULES = """
    QComboBox, QLineEdit {
        background-color: #383838; color: #ffffff;
        border: 2px solid #4a4a4a; border-radius: 12px;
        padding: 7px 10px; font-size: 13px; font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }
    QComboBox:hover, QLineEdit:hover { border: 2px solid #6b5a8e; }
    QComboBox:disabled, QLineEdit:disabled {
        background-color: #262626; color: #5a5a5a; border: 2px solid #333333;
    }
    QComboBox::drop-down:disabled { background-color: #1f1f1f; }
    QComboBox::drop-down {
        subcontrol-origin: padding; subcontrol-position: top right;
        width: 30px; background-color: #262626;
        border-left: 2px solid #4a4a4a;
        border-top-right-radius: 10px; border-bottom-right-radius: 10px;
    }
    QComboBox::down-arrow {
        width: 0; height: 0;
        border-left: 5px solid transparent; border-right: 5px solid transparent;
        border-top: 6px solid #cccccc;
    }
"""

def settings_combo_field_rules(dense: UiDensity | None = None) -> str:
    """Render-settings combo/line-edit chrome scaled for compact windows.

    Typeface matches Refresh (Segoe UI bold + footer_font); only the box densifies.
    """
    d = dense or COMFORT
    font = int(d.footer_font)
    if d.scale >= 0.85:
        # Comfort base already 13/bold; keep historical padding/chrome.
        return SETTINGS_COMBO_FIELD_RULES
    pad = "3px 6px"
    radius = 8
    drop_w = 22
    drop_r = 6
    border = 1
    arrow = 4
    min_h = max(18, int(getattr(d, "combo_min_h", 18) or 18))
    return f"""
    QComboBox, QLineEdit {{
        background-color: #383838; color: #ffffff;
        border: {border}px solid #4a4a4a; border-radius: {radius}px;
        padding: {pad}; font-size: {font}px; font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        min-height: {min_h}px;
    }}
    QComboBox:hover, QLineEdit:hover {{ border: {border}px solid #6b5a8e; }}
    QComboBox:disabled, QLineEdit:disabled {{
        background-color: #262626; color: #5a5a5a; border: {border}px solid #333333;
    }}
    QComboBox::drop-down:disabled {{ background-color: #1f1f1f; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: top right;
        width: {drop_w}px; background-color: #262626;
        border-left: {border}px solid #4a4a4a;
        border-top-right-radius: {drop_r}px; border-bottom-right-radius: {drop_r}px;
    }}
    QComboBox::down-arrow {{
        width: 0; height: 0;
        border-left: {arrow}px solid transparent; border-right: {arrow}px solid transparent;
        border-top: {arrow + 1}px solid #cccccc;
    }}
"""


# Slimmer popup for the compact combos (Sorting / Filter in the Clips Manager):
# flat rows, normal weight, row height matched to the collapsed combo box.
COMPACT_COMBO_POPUP_ITEM_RULES = f"""
    QComboBox QAbstractItemView {{
        background-color: {_popup_bg()};
        color: {_POPUP_FG};
        border: 2px solid #4a4a4a;
        border-radius: 10px;
        padding: 4px;
        outline: none;
        selection-background-color: transparent;
        selection-color: {_POPUP_SEL_FG};
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        font-weight: normal;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 24px;
        padding: 4px 10px 4px 6px;
        border-radius: 6px;
        margin: 1px 2px;
        background-color: transparent;
        color: {_POPUP_FG};
        border: 1px solid transparent;
        font-weight: normal;
    }}
    QComboBox QAbstractItemView::item:hover:enabled {{
        background-color: {_POPUP_SEL_BG};
        color: {_POPUP_SEL_FG};
        border: 1px solid #6b5a8e;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: {_POPUP_SEL_BG};
        color: {_POPUP_SEL_FG};
        border: 1px solid #b29ae7;
    }}
    QComboBox QAbstractItemView::item:selected:enabled {{
        background-color: {_POPUP_SEL_BG};
        color: {_POPUP_SEL_FG};
        border: 1px solid #b29ae7;
    }}
    QComboBox QAbstractItemView::item:disabled {{
        background-color: transparent;
        color: {_POPUP_DIS_FG};
        border: 1px solid transparent;
    }}
"""

COMPACT_COMBO_RULES = """
    QComboBox {
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-radius: 8px;
        padding: 4px 10px;
        font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        font-size: 13px;
        min-height: 24px;
    }
    QComboBox:hover { background-color: #404040; border: 2px solid #6b5a8e; }
    QComboBox:on { background-color: #383838; }
    QComboBox:disabled {
        background-color: #2f2f2f;
        color: #777777;
        border: 2px solid #3a3a3a;
    }
    QComboBox::drop-down { border: none; padding-right: 5px; background: transparent; }
"""


def compact_combo_field_rules(dense: UiDensity | None = None) -> str:
    """Clips Manager sort combo — same typeface as Refresh; chrome densifies."""
    d = dense or COMFORT
    if d.scale >= 0.85:
        return COMPACT_COMBO_RULES
    font = int(d.footer_font)
    pad = d.combo_pad
    min_h = max(18, int(d.combo_min_h))
    radius = max(6, min_h // 2)
    border = 1
    return f"""
    QComboBox {{
        background-color: #383838;
        color: #ffffff;
        border: {border}px solid #444444;
        border-radius: {radius}px;
        padding: {pad};
        font-weight: bold;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        font-size: {font}px;
        min-height: {min_h}px;
    }}
    QComboBox:hover {{ background-color: #404040; border: {border}px solid #6b5a8e; }}
    QComboBox:on {{ background-color: #383838; }}
    QComboBox:disabled {{
        background-color: #2f2f2f;
        color: #777777;
        border: {border}px solid #3a3a3a;
    }}
    QComboBox::drop-down {{ border: none; padding-right: 4px; background: transparent; }}
"""


def settings_panel_stylesheet(extra: str = "", dense: UiDensity | None = None) -> str:
    """QSS for the render settings tab widget (combos + popup chrome)."""
    return settings_combo_field_rules(dense) + combo_popup_item_rules(dense) + (extra or "")


def compact_combo_stylesheet(
    *,
    settings_popup: bool = False,
    dense: UiDensity | None = None,
) -> str:
    """Clips Manager combo chrome; ``settings_popup=True`` matches render panel lists."""
    if settings_popup:
        popup = combo_popup_item_rules(dense)
    elif dense is not None and dense.scale < 0.85:
        popup = combo_popup_item_rules(dense)
    else:
        popup = COMPACT_COMBO_POPUP_ITEM_RULES
    return compact_combo_field_rules(dense) + popup


def set_combo_item_enabled(
    combo: QComboBox,
    index: int,
    enabled: bool,
    *,
    tooltip: str = "",
) -> None:
    model = combo.model()
    if model is None:
        return
    item = model.item(index)
    if item is None:
        return
    item.setEnabled(enabled)
    if tooltip:
        item.setToolTip(tooltip)
    elif enabled:
        item.setToolTip("")


def set_combo_index_if_enabled(combo: QComboBox, index: int) -> bool:
    """Select ``index`` only when that row is enabled."""
    if index < 0 or index >= combo.count():
        return False
    model = combo.model()
    if model is not None:
        item = model.item(index)
        if item is not None and not item.isEnabled():
            return False
    combo.setCurrentIndex(index)
    return True


def find_enabled_combo_text(combo: QComboBox, text: str) -> int:
    """Like findText but skip disabled rows."""
    for i in range(combo.count()):
        if combo.itemText(i) == text:
            model = combo.model()
            if model is not None:
                item = model.item(i)
                if item is not None and not item.isEnabled():
                    return -1
            return i
    return -1
