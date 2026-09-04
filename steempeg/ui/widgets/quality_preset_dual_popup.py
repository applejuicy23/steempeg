"""Two-column Quality Preset popup — same chrome as Bitrate combo, two columns."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui import design_tokens as tok
from steempeg.ui.ui_density import COMFORT
from steempeg.ui.widgets.combo_chrome import _SECTION_FG, _combo_colors


def _active_dense():
    return COMFORT


def _dual_list_stylesheet() -> str:
    """Identical item chrome to ``combo_popup_item_rules`` (Bitrate popup)."""
    c = _combo_colors()
    d = _active_dense()
    h = d.combo_popup_item_h
    pv = d.combo_popup_item_pad_v
    ph = d.combo_popup_item_pad_h
    radius = 6 if d.scale >= 0.5 else 4
    border = 2 if d.scale >= 0.45 else 1
    return f"""
    QListWidget {{
        background: transparent;
        border: none;
        outline: none;
        color: {tok.TEXT_TITLE};
        font-family: {tok.FONT_APP};
        font-size: 13px;
        font-weight: bold;
        padding: 0px;
    }}
    QListWidget::item {{
        min-height: {h}px;
        padding: {pv}px {ph}px;
        border-radius: {radius}px;
        margin: 1px 2px;
        background-color: {c.popup_item_bg};
        color: {tok.TEXT_TITLE};
        border: {border}px solid transparent;
    }}
    QListWidget::item:hover {{
        background-color: {c.popup_item_hover};
        color: {c.popup_sel_fg};
        border: {border}px solid #6b5a8e;
    }}
    QListWidget::item:selected {{
        background-color: {c.popup_sel_bg};
        color: {c.popup_sel_fg};
        border: {border}px solid #b29ae7;
    }}
    """


def _row_outer_height() -> int:
    """Approximate painted height of one Bitrate-style combo row."""
    d = _active_dense()
    # min-height + vertical padding + margin + border
    return int(d.combo_popup_item_h + 2 * d.combo_popup_item_pad_v + 2 + 4)


class QualityPresetDualPopup(QFrame):
    """Frameless popup: left = Standard ladder, right = Target + Custom recipes."""

    def __init__(self, combo: QComboBox):
        super().__init__(None, Qt.WindowType.Popup)
        self._combo = combo
        self.setObjectName("QualityPresetDualPopup")
        c = _combo_colors()
        self.setStyleSheet(
            f"QFrame#QualityPresetDualPopup {{"
            f" background-color: {c.popup_bg};"
            f" border: 2px solid {c.popup_border};"
            f" border-radius: 10px; }}"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QHBoxLayout(self)
        # Match QComboBox popup padding from combo_popup_item_rules.
        d = _active_dense()
        pad = max(2, d.combo_popup_item_pad_v - 2)
        root.setContentsMargins(pad + 4, pad + 2, pad + 4, pad + 4)
        root.setSpacing(8)

        self._left = self._make_column("Standard")
        self._right = self._make_column("Custom")
        root.addWidget(self._left["host"], 1)
        root.addWidget(self._right["host"], 1)

        self._left["list"].itemClicked.connect(self._on_pick)
        self._right["list"].itemClicked.connect(self._on_pick)

    def _make_column(self, title: str) -> dict:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        # Same face as Presets tab section captions (Segoe UI Bold 11 / purple).
        ph = _active_dense().combo_popup_item_pad_h
        hdr = QLabel(title)
        hdr.setFont(tok.ui_qfont(11, weight=QFont.Weight.Bold))
        hdr.setContentsMargins(ph + 2, 0, 0, 0)
        hdr.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        hdr.setStyleSheet(
            f"QLabel {{ color: {_SECTION_FG.name()}; background: transparent; }}"
        )
        hdr.setFixedHeight(18)

        lst = QListWidget()
        lst.setStyleSheet(_dual_list_stylesheet())
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lst.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lst.setSpacing(0)
        lst.setUniformItemSizes(True)
        lst.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        lay.addWidget(hdr, 0)
        lay.addWidget(lst, 1)
        return {"host": host, "list": lst, "header": hdr}

    def rebuild(self) -> None:
        """Fill columns from the combo model (UserRole kinds)."""
        left = self._left["list"]
        right = self._right["list"]
        left.clear()
        right.clear()
        combo = self._combo
        current = combo.currentIndex()
        active_custom = (
            getattr(combo, "_steempeg_active_custom_preset", None) or ""
        ).strip()
        row_h = _row_outer_height()
        active_right_item: QListWidgetItem | None = None
        for i in range(combo.count()):
            meta = combo.itemData(i, Qt.ItemDataRole.UserRole)
            if not isinstance(meta, dict):
                continue
            kind = str(meta.get("kind") or "")
            if kind == "header":
                continue
            text = combo.itemText(i)
            name = str(meta.get("name") or "").strip()
            # ✓ only for explicitly applied Custom recipes (never Target).
            if kind == "custom" and active_custom and name == active_custom:
                starred = text.startswith("★ ")
                text = f"✓ ★ {name}" if starred else f"✓ {name}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setSizeHint(QSize(0, row_h))
            if kind in ("custom", "target"):
                right.addItem(item)
                if kind == "custom" and name == active_custom:
                    active_right_item = item
                elif i == current and active_right_item is None:
                    right.setCurrentItem(item)
            elif kind == "standard":
                left.addItem(item)
                if i == current:
                    left.setCurrentItem(item)
        # Prefer highlighting the checked Custom recipe over a drifted Standard row.
        if active_right_item is not None:
            right.setCurrentItem(active_right_item)
            left.clearSelection()

    def present(self) -> None:
        # Refresh QSS in case theme tokens changed since construct.
        sheet = _dual_list_stylesheet()
        self._left["list"].setStyleSheet(sheet)
        self._right["list"].setStyleSheet(sheet)
        c = _combo_colors()
        self.setStyleSheet(
            f"QFrame#QualityPresetDualPopup {{"
            f" background-color: {c.popup_bg};"
            f" border: 2px solid {c.popup_border};"
            f" border-radius: 10px; }}"
        )

        self.rebuild()
        combo = self._combo
        col_w = max(260, combo.width())
        width = col_w * 2 + 28
        left_n = self._left["list"].count()
        right_n = self._right["list"].count()
        rows = max(left_n, right_n, 1)
        row_h = _row_outer_height()
        # Header 18 + spacing 2 + rows — fit Bitrate-sized pills, no scroll.
        content_h = 18 + 2 + rows * row_h
        d = _active_dense()
        pad = max(2, d.combo_popup_item_pad_v - 2)
        height = content_h + (pad + 2) + (pad + 4) + 4

        screen = combo.screen()
        if screen is not None:
            geo = screen.availableGeometry()
            height = min(height, max(180, geo.height() - 48))
            need_scroll = content_h + 14 > height
            policy = (
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
                if need_scroll
                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._left["list"].setVerticalScrollBarPolicy(policy)
            self._right["list"].setVerticalScrollBarPolicy(policy)

        self.resize(width, height)

        below = combo.mapToGlobal(QPoint(0, combo.height()))
        if screen is not None:
            geo = screen.availableGeometry()
            x = min(below.x(), geo.right() - width - 4)
            x = max(geo.left() + 4, x)
            y = below.y() + 2
            if y + height > geo.bottom():
                y = max(geo.top() + 4, below.y() - height - 2)
            self.move(x, y)
        else:
            self.move(below)
        self.show()
        self.raise_()
        self.activateWindow()

    def deck_navigate(self, button_name: str) -> bool:
        """Gamepad nav while the dual popup is open. button_name: up/down/left/right."""
        left = self._left["list"]
        right = self._right["list"]
        active = self._deck_active_list()
        if button_name == "left":
            if active is right and left.count() > 0:
                row = max(0, min(left.count() - 1, active.currentRow()))
                right.clearSelection()
                left.setCurrentRow(row if row < left.count() else 0)
                left.scrollToItem(left.currentItem())
                self._deck_sync_combo_from_list(left)
            return True
        if button_name == "right":
            if active is left and right.count() > 0:
                row = max(0, min(right.count() - 1, active.currentRow()))
                left.clearSelection()
                right.setCurrentRow(row if row < right.count() else 0)
                right.scrollToItem(right.currentItem())
                self._deck_sync_combo_from_list(right)
            return True
        if button_name in ("up", "down") and active is not None and active.count() > 0:
            delta = -1 if button_name == "up" else 1
            row = active.currentRow()
            if row < 0:
                row = 0
            else:
                row = max(0, min(active.count() - 1, row + delta))
            active.setCurrentRow(row)
            active.scrollToItem(active.currentItem())
            self._deck_sync_combo_from_list(active)
            return True
        return True

    def deck_confirm(self) -> bool:
        """A — apply the highlighted row and close."""
        active = self._deck_active_list()
        if active is None:
            self.hide()
            return True
        item = active.currentItem()
        if item is None and active.count() > 0:
            active.setCurrentRow(0)
            item = active.currentItem()
        if item is not None:
            self._on_pick(item)
        else:
            self.hide()
        return True

    def _deck_active_list(self) -> QListWidget | None:
        left = self._left["list"]
        right = self._right["list"]
        if left.currentItem() is not None:
            return left
        if right.currentItem() is not None:
            return right
        if left.count() > 0:
            left.setCurrentRow(0)
            return left
        if right.count() > 0:
            right.setCurrentRow(0)
            return right
        return None

    def _deck_sync_combo_from_list(self, lst: QListWidget) -> None:
        item = lst.currentItem()
        if item is None:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is None:
            return
        combo = self._combo
        idx = int(idx)
        if combo.currentIndex() != idx:
            combo.setCurrentIndex(idx)

    def _on_pick(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is None:
            return
        combo = self._combo
        idx = int(idx)
        prev = combo.currentIndex()
        combo.setCurrentIndex(idx)
        text = combo.currentText()
        if idx == prev:
            combo.currentTextChanged.emit(text)
        self.hide()
        try:
            combo.activated.emit(idx)
        except Exception:
            pass


class DualColumnQualityCombo(QComboBox):
    """QComboBox whose dropdown is Standard | Custom side-by-side."""

    def showPopup(self) -> None:
        popup = getattr(self, "_steempeg_dual_popup", None)
        if popup is None:
            popup = QualityPresetDualPopup(self)
            self._steempeg_dual_popup = popup
        popup.present()

    def hidePopup(self) -> None:
        popup = getattr(self, "_steempeg_dual_popup", None)
        if popup is not None and popup.isVisible():
            popup.hide()
        # Skip super().hidePopup() — avoids native list flashing into the field.


def install_quality_preset_dual_popup(combo: QComboBox | None) -> None:
    """Promote ``combo_quality`` to the dual-column popup subclass."""
    if combo is None:
        return
    if isinstance(combo, DualColumnQualityCombo):
        return
    combo.__class__ = DualColumnQualityCombo
