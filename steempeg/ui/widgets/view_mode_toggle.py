"""Shared View chrome (Render Queue).

Toolbar: one ghost icon chip showing the active mode. Popup: Grid / List tiles —
same interaction as Clips Manager Size (one button; selection updates the chip).

Count *text* stays per-surface: library ``• 253 Clips`` / Files / Shots;
Render Queue ``(N)`` only.

Widgets are separate layout siblings (not one composite) so portable sheets can
hide View/track while leaving the count in place and insert Folder/Refresh
between track and count.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui.icon_assets import (
    CARD_SIZE_GRID_TINT,
    card_size_grid_icon,
    card_size_grid_pixmap,
    view_mode_list_icon,
    view_mode_list_pixmap,
)
from steempeg.ui.ui_density import (
    COMFORT,
    VIEW_TOGGLE_SEG_NAME,
    UiDensity,
    toggle_segment_min_height,
    view_toggle_button_styles,
)

_TOOLBAR_GLYPH = CARD_SIZE_GRID_TINT
_POPUP_GLYPH_PX = 40
_GHOST_BTN_NAME = "ViewModeGhostBtn"
_GRID_KEY = "grid"
_LIST_KEY = "list"


def _font_css() -> str:
    return "font-family: " + tok.FONT_APP + ";"


def _ghost_button_style(*, radius: int = 6) -> str:
    """Minimal transparent chip — no purple plate, soft hover only."""
    return f"""
        QPushButton#{_GHOST_BTN_NAME} {{
            background-color: transparent;
            border: 1px solid transparent;
            border-radius: {radius}px;
            padding: 2px;
        }}
        QPushButton#{_GHOST_BTN_NAME}:hover {{
            background-color: rgba(178, 154, 231, 0.12);
            border: 1px solid #6b5a8e;
        }}
        QPushButton#{_GHOST_BTN_NAME}:pressed {{
            background-color: rgba(178, 154, 231, 0.22);
            border: 1px solid #b29ae7;
        }}
    """


def format_view_count(value) -> str:
    """Render Queue count style: ``(12)`` / ``(…)``."""
    if value is None:
        return "(0)"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "(0)"
        if text.startswith("(") and text.endswith(")"):
            return text
        return f"({text})"
    try:
        n = int(value)
    except (TypeError, ValueError):
        return f"({value})"
    return f"({n})"


def format_library_count(value, noun: str) -> str:
    """Library header count: ``• 253 Clips`` / ``• … Files`` / ``• 0 Shots``."""
    if value is None:
        return f"• 0 {noun}"
    if isinstance(value, str):
        text = value.strip() or "0"
        return f"• {text} {noun}"
    try:
        n = int(value)
    except (TypeError, ValueError):
        return f"• {value} {noun}"
    return f"• {n} {noun}"


class _ViewModeTile(QPushButton):
    """Popup tile — Grid or List glyph + label."""

    def __init__(self, mode_key: str, parent=None):
        super().__init__(parent)
        self._mode_key = mode_key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setFlat(True)
        self.setFixedSize(92, 88)
        self.setToolTip("List" if mode_key == _LIST_KEY else "Grid")

    def paintEvent(self, event) -> None:  # noqa: N802
        chrome = ut.card_size_popup_chrome()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = self.isChecked()
        hovered = self.underMouse()
        if selected:
            bg = QColor(chrome.tile_selected_bg)
            border = QColor(chrome.tile_selected_border)
        elif hovered:
            bg = QColor(chrome.tile_hover_bg)
            border = QColor(chrome.tile_hover_border)
        else:
            bg = QColor(chrome.tile_bg)
            border = QColor(chrome.tile_border)
        p.setPen(border)
        p.setBrush(bg)
        p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 8, 8)

        tint = chrome.glyph_selected if selected else chrome.glyph
        if self._mode_key == _LIST_KEY:
            glyph = view_mode_list_pixmap(_POPUP_GLYPH_PX, color=tint)
            label = "List"
        else:
            glyph = card_size_grid_pixmap("big", _POPUP_GLYPH_PX, color=tint)
            label = "Grid"
        if not glyph.isNull():
            gx = (self.width() - glyph.width()) // 2
            gy = 10
            p.drawPixmap(gx, gy, glyph)

        p.setPen(QColor(chrome.label_selected if selected else chrome.label))
        font = QFont(tok.FONT_APP)
        font.setBold(True)
        font.setPixelSize(11)
        p.setFont(font)
        p.drawText(
            QRectF(0, self.height() - 22, self.width(), 18),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            label,
        )
        p.end()


class _ViewModePopup(QFrame):
    """Emits ``grid`` / ``list`` when a tile is picked."""

    choice_picked = Signal(str)

    def __init__(self, current: str, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("ViewModePopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chrome = ut.card_size_popup_chrome()
        self.setStyleSheet(
            f"""
            QFrame#ViewModePopup {{
                background-color: {chrome.panel_bg};
                border: 1px solid {chrome.panel_border};
                border-radius: 10px;
            }}
            """
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        for key in (_GRID_KEY, _LIST_KEY):
            tile = _ViewModeTile(key, self)
            tile.setChecked(key == current)
            tile.clicked.connect(lambda _=False, k=key: self._pick(k))
            lay.addWidget(tile)

    def _pick(self, key: str) -> None:
        self.choice_picked.emit(key)
        self.hide()


class ViewModeChrome(QObject):
    """Owns View label + one mode chip + count. Grid/List live in a popup."""

    mode_changed = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial_mode: str = "grid",
        grid_only: bool = False,
        dense: UiDensity | None = None,
        initial_count: str | None = None,
    ):
        super().__init__(parent)
        self._density = dense if dense is not None else COMFORT
        self._grid_only = bool(grid_only)
        mode = initial_mode if initial_mode in ("list", "grid") else "grid"
        if self._grid_only:
            mode = "grid"
        self._mode = mode
        self._popup: _ViewModePopup | None = None

        self.lbl_view = QLabel("View", parent)
        self._apply_label_style(self.lbl_view)

        self.toggle_pill = QFrame(parent)
        self.toggle_pill.setObjectName("ViewModeChromeHost")
        self.toggle_pill.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.toggle_pill.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.toggle_pill.setStyleSheet(
            "QFrame#ViewModeChromeHost { background: transparent; border: none; }"
        )
        toggle_layout = QHBoxLayout(self.toggle_pill)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(0)

        self.btn_view_grid = QPushButton(self.toggle_pill)
        self.btn_view_grid.setObjectName(_GHOST_BTN_NAME)
        self.btn_view_grid.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_view_grid.setFlat(True)
        self.btn_view_grid.setAutoDefault(False)
        self.btn_view_grid.setDefault(False)
        self.btn_view_grid.setText("")
        self.btn_view_grid.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_view_grid.setProperty("legacySeg", VIEW_TOGGLE_SEG_NAME)
        self.btn_view_grid.clicked.connect(self._open_mode_popup)

        # Compat alias — List lives in the popup, not the toolbar.
        self.btn_view_list = QPushButton(self.toggle_pill)
        self.btn_view_list.setObjectName(VIEW_TOGGLE_SEG_NAME)
        self.btn_view_list.setProperty("legacySeg", VIEW_TOGGLE_SEG_NAME)
        self.btn_view_list.hide()

        self.toggle_style_active, self.toggle_style_inactive = view_toggle_button_styles(
            self._density
        )
        toggle_layout.addWidget(self.btn_view_grid)

        self.lbl_count = QLabel(
            initial_count if initial_count is not None else "(0)", parent
        )
        self._apply_count_style(self.lbl_count)

        self._apply_segment_metrics(self._density)
        self._sync_buttons()
        self.set_grid_only(self._grid_only)

    def add_to_layout(self, layout, *, include_count: bool = True) -> None:
        """Append View · chip · count in Render Queue order."""
        layout.addWidget(self.lbl_view)
        layout.addWidget(self.toggle_pill)
        if include_count:
            layout.addWidget(self.lbl_count)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str, *, emit: bool = True) -> None:
        if mode not in ("list", "grid"):
            return
        if self._grid_only:
            mode = "grid"
        changed = mode != self._mode
        self._mode = mode
        self._sync_buttons()
        if changed and emit:
            self.mode_changed.emit(mode)

    def set_grid_only(self, grid_only: bool) -> None:
        """Screenshots: same shell with a single Grid chip (no List popup)."""
        self._grid_only = bool(grid_only)
        self.btn_view_list.hide()
        if self._grid_only and self._mode != "grid":
            self._mode = "grid"
        self._sync_buttons()

    def set_count(self, value) -> None:
        """Set the count label. Strings are used as-is; numbers become RQ ``(N)``."""
        if isinstance(value, str):
            self.lbl_count.setText(value)
        else:
            self.lbl_count.setText(format_view_count(value))

    def apply_density(self, dense: UiDensity) -> None:
        self._density = dense
        self.lbl_view.setVisible(not dense.compact)
        self._apply_label_style(self.lbl_view)
        self._apply_count_style(self.lbl_count)
        self.toggle_style_active, self.toggle_style_inactive = view_toggle_button_styles(
            dense
        )
        self.toggle_pill.setStyleSheet(
            "QFrame#ViewModeChromeHost { background: transparent; border: none; }"
        )
        self._apply_segment_metrics(dense)
        self._sync_buttons()

    def sync_styles_from_mode(self) -> None:
        """Re-apply active/inactive styles for the current mode (after external style swap)."""
        self._sync_buttons()

    def _glyph_px(self) -> int:
        h = toggle_segment_min_height(self._density)
        return max(16, min(22, h - 4))

    def _apply_segment_metrics(self, dense: UiDensity) -> None:
        h = toggle_segment_min_height(dense)
        glyph = self._glyph_px()
        side = max(h, glyph + 6)
        self.btn_view_grid.setFixedSize(side, side)
        self.btn_view_grid.setIconSize(QSize(glyph, glyph))
        self.btn_view_grid.setStyleSheet(_ghost_button_style(radius=max(4, side // 4)))

    def _open_mode_popup(self) -> None:
        if self._grid_only:
            return
        if self._popup is not None:
            try:
                self._popup.hide()
                self._popup.deleteLater()
            except RuntimeError:
                pass
        popup = _ViewModePopup(self._mode)
        popup.choice_picked.connect(self.set_mode)
        self._popup = popup
        popup.adjustSize()
        origin = self.btn_view_grid.mapToGlobal(
            QPoint(0, self.btn_view_grid.height() + 4)
        )
        popup.move(origin)
        popup.show()

    def _sync_buttons(self) -> None:
        glyph_px = self._glyph_px()
        side = max(toggle_segment_min_height(self._density), glyph_px + 6)
        style = _ghost_button_style(radius=max(4, side // 4))
        list_on = self._mode == "list" and not self._grid_only
        self.btn_view_grid.setFixedSize(side, side)
        self.btn_view_grid.setStyleSheet(style)
        self.btn_view_grid.setText("")
        if list_on:
            self.btn_view_grid.setIcon(
                view_mode_list_icon(glyph_px, color=_TOOLBAR_GLYPH)
            )
            self.btn_view_grid.setToolTip("View — List")
        else:
            self.btn_view_grid.setIcon(
                card_size_grid_icon("big", glyph_px, color=_TOOLBAR_GLYPH)
            )
            self.btn_view_grid.setToolTip("View — Grid")
        self.btn_view_grid.setIconSize(QSize(glyph_px, glyph_px))
        self.btn_view_list.hide()

    def _apply_label_style(self, lbl: QLabel) -> None:
        d = self._density
        lbl.setStyleSheet(
            f"color: #777777; font-weight: bold; font-size: {d.toolbar_label_font}px;"
            f" border: none; background: transparent; {_font_css()}"
        )

    def _apply_count_style(self, lbl: QLabel) -> None:
        d = self._density
        lbl.setStyleSheet(
            f"color: #888888; font-weight: bold; font-size: {d.toolbar_label_font}px;"
            f" border: none; background: transparent; {_font_css()}"
        )
