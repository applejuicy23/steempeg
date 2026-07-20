"""Shared QComboBox popup styling — selected item outline + visible disabled rows."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox

from steempeg.ui.ui_density import COMFORT, UiDensity


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
        background-color: #1e1e1e;
        color: #e0e0e0;
        border: 2px solid #4a4a4a;
        border-radius: 10px;
        padding: {max(2, pv - 2)}px;
        outline: none;
        selection-background-color: transparent;
        selection-color: #ffffff;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: {h}px;
        padding: {pv}px {ph}px;
        border-radius: {radius}px;
        margin: 1px 2px;
        background-color: #333333;
        color: #e0e0e0;
        border: {border}px solid transparent;
    }}
    QComboBox QAbstractItemView::item:hover:enabled {{
        background-color: #404040;
        color: #ffffff;
        border: {border}px solid #6b5a8e;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: #3a3350;
        color: #ffffff;
        border: {border}px solid #b29ae7;
    }}
    QComboBox QAbstractItemView::item:selected:enabled {{
        background-color: #3a3350;
        color: #ffffff;
        border: {border}px solid #b29ae7;
    }}
    QComboBox QAbstractItemView::item:disabled {{
        background-color: #262626;
        color: #5a5a5a;
        border: {border}px solid #333333;
    }}
"""


# Default comfort popup (backward-compatible import for static QSS builders).
COMBO_POPUP_ITEM_RULES = combo_popup_item_rules(COMFORT)

SETTINGS_COMBO_FIELD_RULES = """
    QComboBox, QLineEdit {
        background-color: #383838; color: #ffffff;
        border: 2px solid #4a4a4a; border-radius: 12px;
        padding: 7px 10px; font-size: 12px; font-weight: bold;
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

# Slimmer popup for the compact combos (Sorting / Filter in the Clips Manager):
# flat rows, normal weight, row height matched to the collapsed combo box.
COMPACT_COMBO_POPUP_ITEM_RULES = """
    QComboBox QAbstractItemView {
        background-color: #1e1e1e;
        color: #e0e0e0;
        border: 2px solid #4a4a4a;
        border-radius: 10px;
        padding: 4px;
        outline: none;
        selection-background-color: transparent;
        selection-color: #ffffff;
        font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;
        font-weight: normal;
    }
    QComboBox QAbstractItemView::item {
        min-height: 24px;
        padding: 4px 10px 4px 6px;
        border-radius: 6px;
        margin: 1px 2px;
        background-color: transparent;
        color: #e0e0e0;
        border: 1px solid transparent;
        font-weight: normal;
    }
    QComboBox QAbstractItemView::item:hover:enabled {
        background-color: #3a3350;
        color: #ffffff;
        border: 1px solid #6b5a8e;
    }
    QComboBox QAbstractItemView::item:selected {
        background-color: #3a3350;
        color: #ffffff;
        border: 1px solid #b29ae7;
    }
    QComboBox QAbstractItemView::item:selected:enabled {
        background-color: #3a3350;
        color: #ffffff;
        border: 1px solid #b29ae7;
    }
    QComboBox QAbstractItemView::item:disabled {
        background-color: transparent;
        color: #5a5a5a;
        border: 1px solid transparent;
    }
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
    QComboBox::drop-down { border: none; padding-right: 5px; background: transparent; }
"""


def settings_panel_stylesheet(extra: str = "", dense: UiDensity | None = None) -> str:
    """QSS for the render settings tab widget (combos + popup chrome)."""
    return SETTINGS_COMBO_FIELD_RULES + combo_popup_item_rules(dense) + (extra or "")


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
    return COMPACT_COMBO_RULES + popup


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
