"""Shared View + Grid/List chrome (Render Queue).

Minimal transparent icon chips — same language as Clips Size:
Grid → ``grid_high.png``, List → ``defaultsort.png``, plaque-purple when active.

Count *text* stays per-surface: library ``• 253 Clips`` / Files / Shots;
Render Queue ``(N)`` only.

Widgets are separate layout siblings (not one composite) so portable sheets can
hide View/track while leaving the count in place and insert Folder/Refresh
between track and count.
"""
from __future__ import annotations

from steempeg.ui import design_tokens as tok
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from steempeg.ui.icon_assets import (
    CARD_SIZE_GRID_TINT,
    card_size_grid_icon,
    view_mode_list_icon,
)
from steempeg.ui.ui_density import (
    COMFORT,
    VIEW_TOGGLE_SEG_NAME,
    UiDensity,
    toggle_segment_min_height,
    view_toggle_button_styles,
)

_IDLE_GLYPH = "#9a9a9a"
_ACTIVE_GLYPH = CARD_SIZE_GRID_TINT
_GHOST_BTN_NAME = "ViewModeGhostBtn"


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


class ViewModeChrome(QObject):
    """Owns View label + Grid/List icon chips + count."""

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
        toggle_layout.setSpacing(2)

        self.btn_view_grid = QPushButton(self.toggle_pill)
        self.btn_view_list = QPushButton(self.toggle_pill)
        for btn, tip in (
            (self.btn_view_grid, "Grid"),
            (self.btn_view_list, "List"),
        ):
            btn.setObjectName(_GHOST_BTN_NAME)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFlat(True)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setText("")
            btn.setToolTip(tip)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # Compat: some callers still read these (List restore / density).
        self.toggle_style_active, self.toggle_style_inactive = view_toggle_button_styles(
            self._density
        )
        # Keep legacy object-name alias for sheets that looked up ViewToggleSeg.
        self.btn_view_grid.setProperty("legacySeg", VIEW_TOGGLE_SEG_NAME)
        self.btn_view_list.setProperty("legacySeg", VIEW_TOGGLE_SEG_NAME)

        self.btn_view_grid.clicked.connect(lambda: self.set_mode("grid"))
        self.btn_view_list.clicked.connect(lambda: self.set_mode("list"))

        toggle_layout.addWidget(self.btn_view_grid)
        toggle_layout.addWidget(self.btn_view_list)

        self.lbl_count = QLabel(
            initial_count if initial_count is not None else "(0)", parent
        )
        self._apply_count_style(self.lbl_count)

        self._apply_segment_metrics(self._density)
        self._sync_buttons()
        self.set_grid_only(self._grid_only)

    def add_to_layout(self, layout, *, include_count: bool = True) -> None:
        """Append View · track · count in Render Queue order."""
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
        """Screenshots: same shell with a single Grid chip (no List)."""
        self._grid_only = bool(grid_only)
        if self._grid_only:
            self.btn_view_list.hide()
            self.btn_view_grid.show()
            if self._mode != "grid":
                self._mode = "grid"
            self._sync_buttons()
            return
        self.btn_view_list.show()
        self.btn_view_grid.show()
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
        self.toggle_style_active, self.toggle_style_inactive = view_toggle_button_styles(dense)
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
        style = _ghost_button_style(radius=max(4, side // 4))
        for btn in (self.btn_view_grid, self.btn_view_list):
            btn.setFixedSize(side, side)
            btn.setIconSize(QSize(glyph, glyph))
            btn.setStyleSheet(style)

    def _sync_buttons(self) -> None:
        glyph_px = self._glyph_px()
        side = max(toggle_segment_min_height(self._density), glyph_px + 6)
        style = _ghost_button_style(radius=max(4, side // 4))
        list_on = self._mode == "list" and not self._grid_only
        grid_color = _IDLE_GLYPH if list_on else _ACTIVE_GLYPH
        list_color = _ACTIVE_GLYPH if list_on else _IDLE_GLYPH
        for btn, icon in (
            (self.btn_view_grid, card_size_grid_icon("big", glyph_px, color=grid_color)),
            (self.btn_view_list, view_mode_list_icon(glyph_px, color=list_color)),
        ):
            btn.setFixedSize(side, side)
            btn.setStyleSheet(style)
            btn.setText("")
            btn.setIcon(icon)
            btn.setIconSize(QSize(glyph_px, glyph_px))
        self.btn_view_grid.setToolTip("Grid")
        self.btn_view_list.setToolTip("List")

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
