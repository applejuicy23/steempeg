"""Shared View + Grid/List track chrome (Render Queue language).

Used by the library toolbar (Clips / Rendered / Screenshots) and Render Queue
so the Grid/List track reads as one design: rounder RQ pill, same density.

Count *text* stays per-surface: library ``• 253 Clips`` / Files / Shots;
Render Queue ``(N)`` only.

Widgets are separate layout siblings (not one composite) so portable sheets can
hide View/track while leaving the count in place and insert Folder/Refresh
between track and count.
"""
from __future__ import annotations

from steempeg.ui import design_tokens as tok
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from steempeg.ui.ui_density import (
    COMFORT,
    VIEW_TOGGLE_SEG_NAME,
    VIEW_TOGGLE_TRACK_NAME,
    UiDensity,
    toggle_segment_min_height,
    view_toggle_button_styles,
    view_toggle_track_style,
)

def _font_css() -> str:
    return "font-family: " + tok.FONT_APP + ";"


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
    """Owns View label + Grid/List track + count; RQ pill metrics on the toggle."""

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
        self.toggle_pill.setObjectName(VIEW_TOGGLE_TRACK_NAME)
        self.toggle_pill.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.toggle_pill.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.toggle_pill.setStyleSheet(view_toggle_track_style(self._density))
        toggle_layout = QHBoxLayout(self.toggle_pill)
        toggle_layout.setContentsMargins(2, 2, 2, 2)
        toggle_layout.setSpacing(0)

        self.btn_view_grid = QPushButton("Grid", self.toggle_pill)
        self.btn_view_list = QPushButton("List", self.toggle_pill)
        for btn in (self.btn_view_grid, self.btn_view_list):
            btn.setObjectName(VIEW_TOGGLE_SEG_NAME)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFlat(True)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.toggle_style_active, self.toggle_style_inactive = view_toggle_button_styles(
            self._density
        )
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

    # --- Layout helpers -----------------------------------------------------

    def add_to_layout(self, layout, *, include_count: bool = True) -> None:
        """Append View · track · count in Render Queue order."""
        layout.addWidget(self.lbl_view)
        layout.addWidget(self.toggle_pill)
        if include_count:
            layout.addWidget(self.lbl_count)

    # --- Public API ---------------------------------------------------------

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
        """Screenshots: same track shell with a single Grid segment (no List)."""
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
        self.toggle_pill.setStyleSheet(view_toggle_track_style(dense))
        self._apply_segment_metrics(dense)
        self._sync_buttons()

    def sync_styles_from_mode(self) -> None:
        """Re-apply active/inactive styles for the current mode (after external style swap)."""
        self._sync_buttons()

    # --- Internals ----------------------------------------------------------

    def _apply_segment_metrics(self, dense: UiDensity) -> None:
        """Lock Grid/List to RQ pill height so a crowded library toolbar cannot squash them."""
        h = toggle_segment_min_height(dense)
        font_px = dense.toggle_font
        for btn in (self.btn_view_grid, self.btn_view_list):
            btn.setMinimumHeight(h)
            fnt = btn.font()
            fnt = tok.pin_ui_font(fnt)
            fnt.setBold(True)
            fnt.setPixelSize(font_px)
            btn.setFont(fnt)

    def _sync_buttons(self) -> None:
        active = self.toggle_style_active
        inactive = self.toggle_style_inactive
        if self._mode == "list" and not self._grid_only:
            self.btn_view_list.setStyleSheet(active)
            self.btn_view_grid.setStyleSheet(inactive)
        else:
            self.btn_view_grid.setStyleSheet(active)
            self.btn_view_list.setStyleSheet(inactive)

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
