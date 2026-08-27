"""Shared QComboBox popup styling — selected item outline + visible disabled rows."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate

from steempeg.ui import design_tokens as tok
from steempeg.ui.ui_density import COMFORT, UiDensity

# Force light ink — Windows light OS theme otherwise paints near-black Text
# on our dark custom popup (QSS alone is not always enough).
_POPUP_FG = tok.TEXT_TITLE  # #e8e8e8
_SECTION_FG = QColor("#b29ae7")  # Presets tab Standard / Custom caption


class QualitySectionHeaderDelegate(QStyledItemDelegate):
    """Paint Quality Preset section rows (Standard / Custom) in Presets purple."""

    _HEADER_H = 20  # tight caption — not a full combo row

    def sizeHint(self, option, index):
        meta = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(meta, dict) and meta.get("kind") == "header":
            base = super().sizeHint(option, index)
            return base.__class__(base.width(), self._HEADER_H)
        return super().sizeHint(option, index)

    def paint(self, painter, option, index):
        meta = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(meta, dict) and meta.get("kind") == "header":
            painter.save()
            # Flat caption — no disabled grey plate / border.
            text = index.data(Qt.ItemDataRole.DisplayRole) or ""
            # Same stack as Presets section captions (Segoe UI / bold).
            font = tok.ui_qfont(11, weight=QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(_SECTION_FG)
            pad = 8
            painter.drawText(
                option.rect.adjusted(pad, 0, -pad, 0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                str(text),
            )
            painter.restore()
            return
        super().paint(painter, option, index)


def install_quality_section_header_delegate(combo: QComboBox) -> None:
    """One-shot: purple Standard / Custom captions in the Quality Preset popup."""
    if combo is None:
        return
    if getattr(combo, "_steempeg_quality_header_delegate", None) is not None:
        return
    delegate = QualitySectionHeaderDelegate(combo)
    combo.setItemDelegate(delegate)
    combo._steempeg_quality_header_delegate = delegate


def _combo_colors():
    from steempeg.ui import ui_theme as ut

    return ut.combo_chrome_colors()


def combo_popup_item_rules(dense: UiDensity | None = None) -> str:
    """Popup list row chrome scaled with UI density (avoids fat lists on Deck)."""
    c = _combo_colors()
    d = dense or COMFORT
    h = d.combo_popup_item_h
    pv = d.combo_popup_item_pad_v
    ph = d.combo_popup_item_pad_h
    radius = 6 if d.scale >= 0.5 else 4
    border = 2 if d.scale >= 0.45 else 1
    return f"""
    QComboBox QAbstractItemView {{
        background-color: {c.popup_bg};
        color: {_POPUP_FG};
        border: 2px solid {c.popup_border};
        border-radius: 10px;
        padding: {max(2, pv - 2)}px;
        outline: none;
        selection-background-color: transparent;
        selection-color: {c.popup_sel_fg};
        font-family: {tok.FONT_APP};
    }}
    QComboBox QAbstractItemView::item {{
        min-height: {h}px;
        padding: {pv}px {ph}px;
        border-radius: {radius}px;
        margin: 1px 2px;
        background-color: {c.popup_item_bg};
        color: {_POPUP_FG};
        border: {border}px solid transparent;
    }}
    QComboBox QAbstractItemView::item:hover:enabled {{
        background-color: {c.popup_item_hover};
        color: {c.popup_sel_fg};
        border: {border}px solid #6b5a8e;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: {c.popup_sel_bg};
        color: {c.popup_sel_fg};
        border: {border}px solid #b29ae7;
    }}
    QComboBox QAbstractItemView::item:selected:enabled {{
        background-color: {c.popup_sel_bg};
        color: {c.popup_sel_fg};
        border: {border}px solid #b29ae7;
    }}
    QComboBox QAbstractItemView::item:disabled {{
        background-color: {c.popup_dis_bg};
        color: {c.popup_dis_fg};
        border: {border}px solid {c.popup_border};
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

    c = _combo_colors()
    bg = QColor(c.popup_bg)
    fg = QColor(_POPUP_FG)
    item_bg = QColor(c.popup_item_bg)
    sel_bg = QColor(c.popup_sel_bg)
    sel_fg = QColor(c.popup_sel_fg)
    dis_fg = QColor(c.popup_dis_fg)

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
# Must stay live: Settings → UI font rebuilds FONT_APP; a frozen import-time
# string would keep the old face after Save.
class _LiveComboPopupRules:
    def __str__(self) -> str:
        return combo_popup_item_rules(COMFORT)

    def __add__(self, other) -> str:
        return str(self) + str(other)

    def __radd__(self, other) -> str:
        return str(other) + str(self)

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)


COMBO_POPUP_ITEM_RULES = _LiveComboPopupRules()

SETTINGS_COMBO_FIELD_RULES_TEMPLATE = """
    QComboBox, QLineEdit {
        background-color: #383838; color: #ffffff;
        border: 2px solid #4a4a4a; border-radius: 12px;
        padding: 7px 10px; font-size: 13px; font-weight: bold;
        font-family: <<FONT>>;
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


class _LiveSettingsComboFieldRules:
    def __str__(self) -> str:
        return SETTINGS_COMBO_FIELD_RULES_TEMPLATE.replace("<<FONT>>", tok.FONT_APP)

    def __add__(self, other) -> str:
        return str(self) + str(other)

    def __radd__(self, other) -> str:
        return str(other) + str(self)

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)


SETTINGS_COMBO_FIELD_RULES = _LiveSettingsComboFieldRules()


def settings_combo_field_rules(dense: UiDensity | None = None) -> str:
    """Render-settings combo/line-edit chrome scaled for compact windows.

    Typeface matches Refresh (Segoe UI bold + footer_font); only the box densifies.
    """
    from steempeg.ui import ui_theme as ut

    d = dense or COMFORT
    field_bg, field_border, drop_bg = ut.render_settings_active_combo_colors()
    c = ut.combo_chrome_colors()
    font = int(d.footer_font)
    p = ut.active_palette()
    if p.name == ut.UI_THEME_DEFAULT:
        dis_bg, dis_border, drop_dis, dis_fg = "#262626", "#333333", "#1f1f1f", "#5a5a5a"
    else:
        dis_bg, dis_border = p.button_disabled_bg, p.button_disabled_border
        drop_dis = p.button_disabled_bg
        dis_fg = c.popup_dis_fg
    if d.scale >= 0.85:
        # Comfort base already 13/bold; keep historical padding/chrome.
        return f"""
    QComboBox, QLineEdit {{
        background-color: {field_bg}; color: #ffffff;
        border: 2px solid {field_border}; border-radius: 12px;
        padding: 7px 10px; font-size: 13px; font-weight: bold;
        font-family: {tok.FONT_APP};
    }}
    QComboBox:hover, QLineEdit:hover {{ border: 2px solid #6b5a8e; }}
    QComboBox:disabled, QLineEdit:disabled {{
        background-color: {dis_bg}; color: {dis_fg}; border: 2px solid {dis_border};
    }}
    QComboBox::drop-down:disabled {{ background-color: {drop_dis}; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: top right;
        width: 30px; background-color: {drop_bg};
        border-left: 2px solid {field_border};
        border-top-right-radius: 10px; border-bottom-right-radius: 10px;
    }}
    QComboBox::down-arrow {{
        width: 0; height: 0;
        border-left: 5px solid transparent; border-right: 5px solid transparent;
        border-top: 6px solid #cccccc;
    }}
"""
    pad = "3px 6px"
    radius = 8
    drop_w = 22
    drop_r = 6
    border = 1
    arrow = 4
    min_h = max(18, int(getattr(d, "combo_min_h", 18) or 18))
    return f"""
    QComboBox, QLineEdit {{
        background-color: {field_bg}; color: #ffffff;
        border: {border}px solid {field_border}; border-radius: {radius}px;
        padding: {pad}; font-size: {font}px; font-weight: bold;
        font-family: {tok.FONT_APP};
        min-height: {min_h}px;
    }}
    QComboBox:hover, QLineEdit:hover {{ border: {border}px solid #6b5a8e; }}
    QComboBox:disabled, QLineEdit:disabled {{
        background-color: {dis_bg}; color: {dis_fg}; border: {border}px solid {dis_border};
    }}
    QComboBox::drop-down:disabled {{ background-color: {drop_dis}; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: top right;
        width: {drop_w}px; background-color: {drop_bg};
        border-left: {border}px solid {field_border};
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
def compact_combo_popup_item_rules() -> str:
    c = _combo_colors()
    return f"""
    QComboBox QAbstractItemView {{
        background-color: {c.popup_bg};
        color: {_POPUP_FG};
        border: 2px solid {c.popup_border};
        border-radius: 10px;
        padding: 4px;
        outline: none;
        selection-background-color: transparent;
        selection-color: {c.popup_sel_fg};
        font-family: {tok.FONT_APP};
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
        background-color: {c.popup_sel_bg};
        color: {c.popup_sel_fg};
        border: 1px solid #6b5a8e;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: {c.popup_sel_bg};
        color: {c.popup_sel_fg};
        border: 1px solid #b29ae7;
    }}
    QComboBox QAbstractItemView::item:selected:enabled {{
        background-color: {c.popup_sel_bg};
        color: {c.popup_sel_fg};
        border: 1px solid #b29ae7;
    }}
    QComboBox QAbstractItemView::item:disabled {{
        background-color: transparent;
        color: {c.popup_dis_fg};
        border: 1px solid transparent;
    }}
"""


COMPACT_COMBO_POPUP_ITEM_RULES = compact_combo_popup_item_rules()

_COMPACT_COMBO_RULES_TEMPLATE = """
    QComboBox {
        background-color: #383838;
        color: #ffffff;
        border: 2px solid #444444;
        border-radius: 8px;
        padding: 4px 10px;
        font-weight: bold;
        font-family: <<FONT>>;
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


class _LiveCompactComboRules:
    def __str__(self) -> str:
        return _COMPACT_COMBO_RULES_TEMPLATE.replace("<<FONT>>", tok.FONT_APP)

    def __add__(self, other) -> str:
        return str(self) + str(other)

    def __radd__(self, other) -> str:
        return str(other) + str(self)

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)


COMPACT_COMBO_RULES = _LiveCompactComboRules()


def compact_combo_field_rules(dense: UiDensity | None = None) -> str:
    """Clips Manager sort combo — same typeface as Refresh; chrome densifies."""
    from steempeg.ui import ui_theme as ut

    d = dense or COMFORT
    if ut.get_ui_theme() != ut.UI_THEME_DEFAULT:
        p = ut.active_palette()
        c = ut.combo_chrome_colors()
        font = int(d.footer_font)
        if d.scale >= 0.85:
            pad = "4px 10px"
            min_h = 24
            radius = 8
            border = 2
        else:
            pad = d.combo_pad
            min_h = max(18, int(d.combo_min_h))
            radius = max(6, min_h // 2)
            border = 1
        return f"""
    QComboBox {{
        background-color: {c.field_bg};
        color: #ffffff;
        border: {border}px solid {c.field_border};
        border-radius: {radius}px;
        padding: {pad};
        font-weight: bold;
        font-family: {tok.FONT_APP};
        font-size: {font}px;
        min-height: {min_h}px;
    }}
    QComboBox:hover {{
        background-color: {c.field_hover_bg};
        border: {border}px solid #6b5a8e;
    }}
    QComboBox:on {{ background-color: {c.field_bg}; }}
    QComboBox:disabled {{
        background-color: {p.button_disabled_bg};
        color: #777777;
        border: {border}px solid {p.button_disabled_border};
    }}
    QComboBox::drop-down {{ border: none; padding-right: 5px; background: transparent; }}
"""
    if d.scale >= 0.85:
        return str(COMPACT_COMBO_RULES)
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
        font-family: {tok.FONT_APP};
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
        popup = compact_combo_popup_item_rules()
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
