"""Rendered media library — preview exported .mp4/.mp3/etc. from output folders."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from PySide6.QtCore import Qt, QPoint, QSize, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from steempeg.core.rendered_media import (
    canvas_markers_to_sidecar,
    extract_poster_frame,
    load_markers_sidecar,
    markers_to_canvas,
    parse_app_id_from_name,
    save_markers_sidecar,
)
from steempeg.infra.locale_time import format_clip_date, format_clip_time
from steempeg.infra.paths import get_resource_path
from steempeg.ui.library.grid_view import ClipCard
from steempeg.ui.library.library_styles import LIBRARY_GRID_STYLE, LIBRARY_TABLE_STYLE

_UNKNOWN_GAME_ICON = get_resource_path("attention.png")

RENDERED_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
RENDERED_AUDIO_EXTS = {".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg", ".opus"}
RENDERED_ALL_EXTS = RENDERED_VIDEO_EXTS | RENDERED_AUDIO_EXTS

_LIBRARY_TAB_INACTIVE = """
    QPushButton {
        background-color: #2d2d2d;
        color: #aaaaaa;
        border: 1px solid #353535;
        border-radius: 16px;
        font-weight: bold;
        font-size: 14px;
        padding: 8px 24px;
    }
    QPushButton:hover { color: #ffffff; border-color: #555555; }
"""
_LIBRARY_TAB_ACTIVE = """
    QPushButton {
        background-color: #2d2d2d;
        color: #ffffff;
        border: 1px solid #6b5a8e;
        border-radius: 16px;
        font-weight: bold;
        font-size: 14px;
        padding: 8px 24px;
    }
"""
_ADD_PANEL_BTN = """
    QPushButton {
        background-color: #2d2d2d;
        color: #ffffff;
        border: 1px solid #353535;
        border-radius: 16px;
        font-weight: 800;
        font-size: 18px;
        padding: 0px;
        min-width: 40px;
        max-width: 40px;
        min-height: 40px;
        max-height: 40px;
    }
    QPushButton:hover { background-color: #3a3a3a; border-color: #6b5a8e; }
"""


def _rendered_type_label(ext: str) -> str:
    ext = ext.lower()
    if ext in RENDERED_VIDEO_EXTS:
        return ext.lstrip(".").upper()
    if ext in RENDERED_AUDIO_EXTS:
        return ext.lstrip(".").upper()
    return ext.lstrip(".").upper() or "FILE"


def _format_file_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


class RenderedLibraryMixin:
    """Library panel for flat rendered media files (not Steam DASH folders)."""

    def _init_rendered_library_state(self):
        self._library_panel_mode = "clips"
        self._library_tabs: dict[str, QPushButton] = {}
        self._rendered_filter_types: set[str] | None = None
        self._clips_view_mode = "grid"
        self._rendered_view_mode = "grid"

    def _make_library_tab_button(self, label: str, mode: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(40)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(_LIBRARY_TAB_INACTIVE)
        btn.clicked.connect(lambda _checked=False, m=mode: self.set_library_panel(m))
        return btn

    def setup_library_tab_bar(self, cm_row: QHBoxLayout):
        """Chrome-like tab row with a + button to add panels."""
        self._init_rendered_library_state()
        self.library_tabs_host = QHBoxLayout()
        self.library_tabs_host.setSpacing(8)

        clips_tab = self._make_library_tab_button("📁 Clips Manager", "clips")
        self._library_tabs["clips"] = clips_tab
        self.library_tabs_host.addWidget(clips_tab)

        self.btn_library_add = QPushButton("+")
        self.btn_library_add.setFixedSize(40, 40)
        self.btn_library_add.setToolTip("Add library panel")
        self.btn_library_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_library_add.setStyleSheet(_ADD_PANEL_BTN)
        self.btn_library_add.clicked.connect(self._show_add_library_panel_menu)

        cm_row.addStretch()
        cm_row.addLayout(self.library_tabs_host)
        cm_row.addWidget(self.btn_library_add)
        cm_row.addStretch()

        if hasattr(self, "mega_top_pill"):
            self.mega_top_pill.hide()

        for key, btn in self._library_tabs.items():
            btn.setStyleSheet(_LIBRARY_TAB_ACTIVE if key == "clips" else _LIBRARY_TAB_INACTIVE)

    def _show_add_library_panel_menu(self):
        menu = QMenu(self.ui)
        menu.setStyleSheet("""
            QMenu { background-color: #2d2d2d; color: white; border: 1px solid #444; padding: 4px; }
            QMenu::item { padding: 8px 24px; border-radius: 4px; }
            QMenu::item:selected { background-color: #5138e6; }
            QMenu::item:disabled { color: #666666; }
        """)
        rendered_action = menu.addAction("🎬  Rendered videos")
        if "rendered" in self._library_tabs:
            rendered_action.setEnabled(False)
        pos = self.btn_library_add.mapToGlobal(QPoint(0, self.btn_library_add.height()))
        action = menu.exec(pos)
        if action is rendered_action and action is not None:
            self.open_library_panel("rendered")

    def open_library_panel(self, mode: str):
        if mode == "rendered":
            self._ensure_rendered_widgets()
            if "rendered" not in self._library_tabs:
                tab = self._make_library_tab_button("🎬 Rendered videos", "rendered")
                idx = self.library_tabs_host.count()
                self.library_tabs_host.insertWidget(idx, tab)
                self._library_tabs["rendered"] = tab
        self.set_library_panel(mode)

    def set_library_panel(self, mode: str):
        if mode not in self._library_tabs:
            return
        self._library_panel_mode = mode
        for key, btn in self._library_tabs.items():
            btn.setStyleSheet(_LIBRARY_TAB_ACTIVE if key == mode else _LIBRARY_TAB_INACTIVE)
        if hasattr(self, "library_stack"):
            self.library_stack.setCurrentIndex(1 if mode == "rendered" else 0)
        if mode == "rendered":
            self._rendered_filter_types = None
            self.scan_rendered_outputs()
            self._apply_rendered_view_mode()
        else:
            if hasattr(self, "grid_clips"):
                self.set_view_mode(self._clips_view_mode)
        self._update_library_count_label()

    def wrap_library_views_in_stack(self, views_layout: QVBoxLayout):
        """Move clips table/grid into page 0 of a stacked widget."""
        self.clips_page = QWidget()
        self.clips_page.setStyleSheet("background: transparent;")
        clips_layout = QVBoxLayout(self.clips_page)
        clips_layout.setContentsMargins(0, 0, 0, 0)
        clips_layout.setSpacing(0)
        views_layout.removeWidget(self.ui.table_clips)
        views_layout.removeWidget(self.grid_clips)
        clips_layout.addWidget(self.ui.table_clips)
        clips_layout.addWidget(self.grid_clips)
        self.library_stack = QStackedWidget()
        self.library_stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
        self.library_stack.addWidget(self.clips_page)
        views_layout.addWidget(self.library_stack)

    def _ensure_rendered_widgets(self):
        if hasattr(self, "table_rendered"):
            return

        self.rendered_page = QWidget()
        self.rendered_page.setStyleSheet("background: transparent;")
        rendered_layout = QVBoxLayout(self.rendered_page)
        rendered_layout.setContentsMargins(0, 0, 0, 0)
        rendered_layout.setSpacing(0)

        self.table_rendered = QTableWidget()
        self.table_rendered.setColumnCount(4)
        self.table_rendered.setHorizontalHeaderLabels(["Game Name", "Type", "Date", "Size"])
        self.table_rendered.setShowGrid(False)
        self.table_rendered.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_rendered.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_rendered.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_rendered.verticalHeader().setVisible(False)
        self.table_rendered.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table_rendered.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table_rendered.setWordWrap(False)
        self.table_rendered.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table_rendered.setFrameShape(QFrame.Shape.NoFrame)
        self.table_rendered.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table_rendered.verticalHeader().setDefaultSectionSize(46)
        self.table_rendered.setIconSize(QSize(26, 26))
        self.table_rendered.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        header = self.table_rendered.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionsClickable(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table_rendered.setColumnWidth(1, 100)
        self.table_rendered.setColumnWidth(2, 160)
        self.table_rendered.setColumnWidth(3, 100)
        self.table_rendered.setStyleSheet(LIBRARY_TABLE_STYLE)

        self.grid_rendered = QListWidget()
        self.grid_rendered.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid_rendered.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid_rendered.setSpacing(15)
        self.grid_rendered.setUniformItemSizes(True)
        self.grid_rendered.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grid_rendered.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.grid_rendered.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.grid_rendered.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.grid_rendered.setMovement(QListWidget.Movement.Static)
        self.grid_rendered.setStyleSheet(LIBRARY_GRID_STYLE)

        self.table_rendered.itemSelectionChanged.connect(self.update_rendered_selection)
        self.table_rendered.itemSelectionChanged.connect(self._sync_rendered_grid_from_table)
        self.grid_rendered.itemSelectionChanged.connect(self._on_rendered_grid_selection_changed)

        rendered_layout.addWidget(self.table_rendered)
        rendered_layout.addWidget(self.grid_rendered)
        self.library_stack.addWidget(self.rendered_page)

    def _collect_rendered_scan_roots(self) -> list[str]:
        roots: list[str] = []
        dest = (getattr(self, "custom_destination", "") or "").strip()
        if dest and os.path.isdir(dest):
            roots.append(os.path.normpath(dest))
        if hasattr(self, "get_save_directory"):
            default = os.path.join(self.get_save_directory(), "rendered_videos")
            if os.path.isdir(default):
                norm = os.path.normpath(default)
                if norm not in roots:
                    roots.append(norm)
        return roots

    def scan_rendered_outputs(self):
        if not hasattr(self, "table_rendered"):
            return
        self.table_rendered.setSortingEnabled(False)
        self.table_rendered.setRowCount(0)

        roots = self._collect_rendered_scan_roots()
        files: list[tuple[str, float, int, str]] = []
        seen: set[str] = set()
        for root in roots:
            try:
                for name in os.listdir(root):
                    full = os.path.join(root, name)
                    if not os.path.isfile(full):
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in RENDERED_ALL_EXTS:
                        continue
                    norm = os.path.normcase(os.path.normpath(full))
                    if norm in seen:
                        continue
                    seen.add(norm)
                    mtime = os.path.getmtime(full)
                    size = os.path.getsize(full)
                    files.append((full, mtime, size, ext))
            except OSError as exc:
                logging.warning("Rendered scan failed for %s: %s", root, exc)

        files.sort(key=lambda row: row[1], reverse=True)
        for full, mtime, size, ext in files:
            type_label = _rendered_type_label(ext)
            dt = datetime.fromtimestamp(mtime)
            date_str = format_clip_date(dt)
            time_str = format_clip_time(dt)
            basename = os.path.basename(full)
            display_title, icon_path, _thumb = self._resolved_rendered_meta(full, basename)
            row = self.table_rendered.rowCount()
            self.table_rendered.insertRow(row)
            icon = QIcon(icon_path) if icon_path and os.path.isfile(icon_path) else QIcon()
            name_item = QTableWidgetItem(icon, f"   {display_title}")
            name_item.setData(Qt.ItemDataRole.UserRole, full)
            self.table_rendered.setItem(row, 0, name_item)
            type_item = QTableWidgetItem(f"🎬 {type_label}")
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table_rendered.setItem(row, 1, type_item)
            date_item = QTableWidgetItem(f"{date_str}\n{time_str}")
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table_rendered.setItem(row, 2, date_item)
            size_item = QTableWidgetItem(_format_file_size(size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table_rendered.setItem(row, 3, size_item)
            name_item.setToolTip(full)
            if self._rendered_filter_types and type_label not in self._rendered_filter_types:
                self.table_rendered.setRowHidden(row, True)

        self.build_rendered_grid()
        self._update_library_count_label()

    def _resolved_rendered_meta(self, file_path: str, filename: str) -> tuple[str, str, str]:
        """Return (display_title, icon_path, thumb_path) for a rendered file."""
        basename = os.path.basename(filename) if filename else os.path.basename(file_path)
        app_id = parse_app_id_from_name(basename)
        title = os.path.splitext(basename)[0]
        icon_path = ""
        if app_id and hasattr(self, "get_game_name"):
            title = self.get_game_name(app_id) or title
            if hasattr(self, "get_game_icon"):
                self.get_game_icon(app_id)
                cache_icon = os.path.join(self.cache_dir, f"{app_id}.jpg")
                if os.path.isfile(cache_icon):
                    icon_path = cache_icon
        elif not app_id and os.path.isfile(_UNKNOWN_GAME_ICON):
            icon_path = _UNKNOWN_GAME_ICON

        thumb_path = ""
        ext = os.path.splitext(file_path)[1].lower()
        if ext in RENDERED_VIDEO_EXTS and hasattr(self, "cache_dir"):
            thumb_path = extract_poster_frame(file_path, self.cache_dir)
        return title, icon_path, thumb_path

    def build_rendered_grid(self):
        if not hasattr(self, "grid_rendered"):
            return
        self.grid_rendered.clear()
        for row in range(self.table_rendered.rowCount()):
            name_item = self.table_rendered.item(row, 0)
            type_item = self.table_rendered.item(row, 1)
            date_item = self.table_rendered.item(row, 2)
            size_item = self.table_rendered.item(row, 3)
            if not name_item:
                continue
            title = name_item.text()
            type_label = type_item.text() if type_item else "FILE"
            date_str = date_item.text() if date_item else ""
            size_str = size_item.text() if size_item else ""
            file_path = name_item.data(Qt.ItemDataRole.UserRole)
            display_title, icon_path, thumb_path = self._resolved_rendered_meta(
                file_path, os.path.basename(file_path)
            )
            badge = type_item.text().replace("🎬 ", "").strip() if type_item else "FILE"

            item = QListWidgetItem(self.grid_rendered)
            item.setSizeHint(QSize(260, 190))
            item.setData(Qt.ItemDataRole.UserRole, row)
            item.setData(Qt.ItemDataRole.UserRole + 1, file_path)

            card = ClipCard(
                display_title,
                f"{date_str} • {size_str}",
                badge,
                thumb_path,
                icon_path,
                row,
                health_color=None,
                on_left_click=lambda ev, grid_item=item: self._rendered_grid_select_item(grid_item),
            )
            self.grid_rendered.setItemWidget(item, card)
            if self.table_rendered.isRowHidden(row):
                item.setHidden(True)

        self._sync_rendered_grid_from_table()

    def _sync_rendered_grid_card_visuals(self) -> None:
        """Paint selection border on rendered ClipCard widgets."""
        if not hasattr(self, "grid_rendered"):
            return
        for i in range(self.grid_rendered.count()):
            item = self.grid_rendered.item(i)
            card = self.grid_rendered.itemWidget(item)
            if isinstance(card, ClipCard):
                card.set_selected(item.isSelected())

    def _update_library_count_label(self):
        if not hasattr(self, "lbl_clip_count"):
            return
        if self._library_panel_mode == "rendered" and hasattr(self, "table_rendered"):
            n = self.table_rendered.rowCount()
            hidden = sum(1 for r in range(n) if self.table_rendered.isRowHidden(r))
            visible = n - hidden
            self.lbl_clip_count.setText(f"• {visible} Files")
        elif hasattr(self.ui, "table_clips"):
            n = self.ui.table_clips.rowCount()
            self.lbl_clip_count.setText(f"• {n} Clips")

    def _apply_rendered_view_mode(self):
        mode = getattr(self, "_rendered_view_mode", "grid")
        if mode == "list":
            self.grid_rendered.hide()
            self.table_rendered.show()
            self.btn_view_list.setStyleSheet(self.toggle_style_active)
            self.btn_view_grid.setStyleSheet(self.toggle_style_inactive)
        else:
            self.table_rendered.hide()
            self.grid_rendered.show()
            self.grid_rendered.doItemsLayout()
            self.btn_view_list.setStyleSheet(self.toggle_style_inactive)
            self.btn_view_grid.setStyleSheet(self.toggle_style_active)

    def _sync_rendered_view_mode(self):
        self._apply_rendered_view_mode()

    def apply_rendered_sorting(self):
        if not hasattr(self, "table_rendered") or not hasattr(self, "combo_sort"):
            return
        idx = self.combo_sort.currentIndex()
        self.table_rendered.setSortingEnabled(False)
        rows = list(range(self.table_rendered.rowCount()))

        def cell(row, col):
            item = self.table_rendered.item(row, col)
            return item.text() if item else ""

        def path(row):
            item = self.table_rendered.item(row, 0)
            return item.data(Qt.ItemDataRole.UserRole) if item else ""

        if idx == 0:
            pass
        elif idx == 1:
            rows.sort(key=lambda r: cell(r, 0).lower())
        elif idx == 2:
            rows.sort(key=lambda r: cell(r, 0).lower(), reverse=True)
        elif idx == 3:
            rows.sort(key=lambda r: cell(r, 1).lower())
        elif idx == 4:
            rows.sort(key=lambda r: cell(r, 1).lower(), reverse=True)
        elif idx == 5:
            rows.sort(key=lambda r: cell(r, 2))
        elif idx == 6:
            rows.sort(key=lambda r: cell(r, 2), reverse=True)
        elif idx == 7:
            rows.sort(key=lambda r: os.path.getsize(path(r)) if path(r) and os.path.exists(path(r)) else 0)
        elif idx == 8:
            rows.sort(key=lambda r: os.path.getsize(path(r)) if path(r) and os.path.exists(path(r)) else 0, reverse=True)

        if idx != 0:
            data = []
            for row in rows:
                data.append([self.table_rendered.takeItem(row, col) for col in range(4)])
                hidden = self.table_rendered.isRowHidden(row)
                data[-1].append(hidden)
            self.table_rendered.setRowCount(0)
            for col_items in data:
                hidden = col_items.pop()
                row = self.table_rendered.rowCount()
                self.table_rendered.insertRow(row)
                for col, item in enumerate(col_items):
                    if item:
                        self.table_rendered.setItem(row, col, item)
                self.table_rendered.setRowHidden(row, hidden)

        self.build_rendered_grid()

    def show_rendered_filter_menu(self):
        menu = QMenu(self.ui)
        menu.setStyleSheet("""
            QMenu { background-color: #2d2d2d; color: white; border: 1px solid #444; padding: 4px; }
            QMenu::item { padding: 8px 24px; border-radius: 4px; }
            QMenu::item:selected { background-color: #5138e6; }
        """)
        all_action = menu.addAction("All formats")
        all_action.setCheckable(True)
        all_action.setChecked(self._rendered_filter_types is None)
        menu.addSeparator()
        type_actions = {}
        present_types: set[str] = set()
        for row in range(self.table_rendered.rowCount()):
            item = self.table_rendered.item(row, 1)
            if item:
                present_types.add(item.text())
        for type_label in sorted(present_types):
            act = menu.addAction(type_label)
            act.setCheckable(True)
            if self._rendered_filter_types is None:
                act.setChecked(True)
            else:
                act.setChecked(type_label in self._rendered_filter_types)
            type_actions[type_label] = act

        pos = self.btn_filter_pill.mapToGlobal(QPoint(0, self.btn_filter_pill.height()))
        menu.exec(pos)

        if all_action.isChecked():
            self._rendered_filter_types = None
        else:
            selected = {t for t, act in type_actions.items() if act.isChecked()}
            self._rendered_filter_types = selected if selected else None

        for row in range(self.table_rendered.rowCount()):
            type_item = self.table_rendered.item(row, 1)
            type_label = type_item.text() if type_item else ""
            hide = (
                self._rendered_filter_types is not None
                and type_label not in self._rendered_filter_types
            )
            self.table_rendered.setRowHidden(row, hide)

        self.build_rendered_grid()
        self._update_library_count_label()

    def refresh_rendered_library(self):
        self.scan_rendered_outputs()

    def _sync_rendered_grid_from_table(self):
        if not hasattr(self, "grid_rendered"):
            return
        selected_rows = {
            idx.row() for idx in self.table_rendered.selectionModel().selectedRows()
        }
        self.grid_rendered.blockSignals(True)
        for i in range(self.grid_rendered.count()):
            item = self.grid_rendered.item(i)
            row = item.data(Qt.ItemDataRole.UserRole)
            item.setSelected(row in selected_rows)
        self.grid_rendered.blockSignals(False)
        self._sync_rendered_grid_card_visuals()

    def _rendered_grid_select_item(self, item):
        self.grid_rendered.blockSignals(True)
        self.grid_rendered.clearSelection()
        item.setSelected(True)
        self.grid_rendered.blockSignals(False)
        row = item.data(Qt.ItemDataRole.UserRole)
        if row is not None:
            self.table_rendered.blockSignals(True)
            self.table_rendered.selectRow(row)
            self.table_rendered.blockSignals(False)
        self.update_rendered_selection()
        self._sync_rendered_grid_card_visuals()

    def _on_rendered_grid_selection_changed(self):
        if not self.grid_rendered.selectedItems():
            return
        item = self.grid_rendered.selectedItems()[0]
        self._rendered_grid_select_item(item)

    def update_rendered_selection(self):
        if self._library_panel_mode != "rendered":
            return
        if not hasattr(self, "table_rendered"):
            return
        row = self.table_rendered.currentRow()
        if row < 0:
            return

        if QApplication.keyboardModifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return

        name_item = self.table_rendered.item(row, 0)
        if not name_item:
            return
        file_path = name_item.data(Qt.ItemDataRole.UserRole)
        type_label = self.table_rendered.item(row, 1).text() if self.table_rendered.item(row, 1) else ""
        date_str = self.table_rendered.item(row, 2).text() if self.table_rendered.item(row, 2) else ""
        size_str = self.table_rendered.item(row, 3).text() if self.table_rendered.item(row, 3) else ""

        self._preview_clip_path = file_path
        self._selected_queue_job_id = None
        self._rendered_media_path = file_path

        display_title, icon_path, _thumb = self._resolved_rendered_meta(
            file_path, os.path.basename(file_path)
        )

        if hasattr(self, "custom_text_label"):
            header_html = (
                f"<b>{display_title}</b> <span style='color: #888;'>&nbsp;&nbsp;•&nbsp;&nbsp; "
                f"{type_label} &nbsp;&nbsp;•&nbsp;&nbsp; {date_str} &nbsp;&nbsp;•&nbsp;&nbsp; {size_str}</span>"
            )
            self.custom_text_label.setText(header_html)
        if hasattr(self, "custom_icon_label"):
            if icon_path and os.path.isfile(icon_path):
                from PySide6.QtGui import QPixmap
                self.custom_icon_label.setPixmap(QPixmap(icon_path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                self.custom_icon_label.clear()

        if hasattr(self, "btn_clip_health"):
            self.btn_clip_health.hide()

        if hasattr(self.ui, "btn_start"):
            self.ui.btn_start.setEnabled(False)
        if hasattr(self, "btn_close_clip"):
            self.btn_close_clip.show()
        if hasattr(self, "update_playback_badge"):
            self.update_playback_badge()

        if hasattr(self, "schedule_play_media_file"):
            self.schedule_play_media_file(file_path)
        elif hasattr(self, "play_media_file"):
            self.play_media_file(file_path)

    # --- Hooks that branch when the rendered panel is active ---

    def set_view_mode(self, mode):
        if getattr(self, "_library_panel_mode", "clips") == "rendered":
            self._rendered_view_mode = mode
            self._apply_rendered_view_mode()
            return
        self._clips_view_mode = mode
        from steempeg.ui.library.controller import LibraryMixin
        LibraryMixin.set_view_mode(self, mode)

    def apply_sorting(self):
        if getattr(self, "_library_panel_mode", "clips") == "rendered":
            self.apply_rendered_sorting()
            return
        from steempeg.ui.library.controller import LibraryMixin
        LibraryMixin.apply_sorting(self)

    def show_filter_menu(self):
        if getattr(self, "_library_panel_mode", "clips") == "rendered":
            self.show_rendered_filter_menu()
            return
        from steempeg.ui.library.controller import LibraryMixin
        LibraryMixin.show_filter_menu(self)

    def refresh_library(self):
        if getattr(self, "_library_panel_mode", "clips") == "rendered":
            self.refresh_rendered_library()
            return
        from steempeg.ui.library.controller import LibraryMixin
        LibraryMixin.refresh_library(self)
