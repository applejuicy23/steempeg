"""Shared QComboBox popup styling — selected item outline + visible disabled rows."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox

# Popup list: pill rows, purple ring on the active/selected row, muted disabled rows.
COMBO_POPUP_ITEM_RULES = """
    QComboBox QAbstractItemView {
        background-color: #1e1e1e;
        color: #e0e0e0;
        border: 2px solid #4a4a4a;
        border-radius: 10px;
        padding: 4px;
        outline: none;
        selection-background-color: transparent;
        selection-color: #ffffff;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
    QComboBox QAbstractItemView::item {
        min-height: 28px;
        padding: 7px 10px;
        border-radius: 6px;
        margin: 2px 2px;
        background-color: #333333;
        color: #e0e0e0;
        border: 2px solid transparent;
    }
    QComboBox QAbstractItemView::item:hover:enabled {
        background-color: #404040;
        color: #ffffff;
        border: 2px solid #6b5a8e;
    }
    QComboBox QAbstractItemView::item:selected {
        background-color: #3a3350;
        color: #ffffff;
        border: 2px solid #b29ae7;
    }
    QComboBox QAbstractItemView::item:selected:enabled {
        background-color: #3a3350;
        color: #ffffff;
        border: 2px solid #b29ae7;
    }
    QComboBox QAbstractItemView::item:disabled {
        background-color: #262626;
        color: #5a5a5a;
        border: 2px solid #333333;
    }
"""

SETTINGS_COMBO_FIELD_RULES = """
    QComboBox, QLineEdit {
        background-color: #383838; color: #ffffff;
        border: 2px solid #4a4a4a; border-radius: 12px;
        padding: 7px 10px; font-size: 12px; font-weight: bold;
        font-family: 'Segoe UI', Arial, sans-serif;
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

COMPACT_COMBO_RULES = """
    QComboBox {
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-radius: 8px;
        padding: 4px 10px;
        font-weight: bold;
        font-family: 'Segoe UI';
        font-size: 13px;
        min-height: 24px;
    }
    QComboBox:hover { background-color: #404040; border: 2px solid #6b5a8e; }
    QComboBox:on { background-color: #383838; }
    QComboBox::drop-down { border: none; padding-right: 5px; background: transparent; }
"""


def settings_panel_stylesheet(extra: str = "") -> str:
    """QSS for the render settings tab widget (combos + popup chrome)."""
    return SETTINGS_COMBO_FIELD_RULES + COMBO_POPUP_ITEM_RULES + (extra or "")


def compact_combo_stylesheet() -> str:
    return COMPACT_COMBO_RULES + COMBO_POPUP_ITEM_RULES


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
