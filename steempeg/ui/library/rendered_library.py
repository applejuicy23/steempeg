"""Rendered media library — preview exported .mp4/.mp3/etc. from output folders."""
from __future__ import annotations

from steempeg.ui import design_tokens as tok

import logging
import os
import re
from datetime import datetime

from PySide6.QtCore import Qt, QPoint, QSize, QTimer, QItemSelection, QItemSelectionModel
from PySide6.QtGui import QFont, QIcon, QPixmap
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

from steempeg.infra import cache
from steempeg.core.rendered_media import (
    canvas_markers_to_sidecar,
    extract_poster_frame,
    is_default_rendered_basename,
    load_markers_sidecar,
    load_rendered_companion_meta,
    markers_to_canvas,
    parse_app_id_from_clip_folder,
    parse_app_id_from_name,
    save_markers_sidecar,
)
from steempeg.infra.locale_time import to_display_datetime
from steempeg.library.rendered_scan import ScannedRenderedFile
from steempeg.library.rendered_library_cache import (
    files_from_rendered_library_cache,
    save_rendered_library_cache,
)
from steempeg.library.screenshots_library_cache import (
    files_from_screenshots_library_cache,
    save_screenshots_library_cache,
    screenshot_thumb_path_nostat,
)
from steempeg.ui.library.rendered_poster_backfill import RenderedPosterBackfillWorker
from steempeg.ui.library.rendered_scan_worker import RenderedScanWorker
from steempeg.ui.library.filters import clip_folder_sort_key
from steempeg.ui.library.grid_view import ClipCard
from steempeg.ui.library.screenshot_photo import (
    SCREENSHOT_PHOTO_H,
    SCREENSHOT_PHOTO_SIZE,
    SCREENSHOT_PHOTO_W,
    ScreenshotPhoto,
)
from steempeg.ui.library.library_tab import LibraryTabWidget
from steempeg.ui.library.library_styles import (
    install_library_vertical_scrollbar,
    library_grid_stylesheet,
    library_table_stylesheet,
)
from steempeg.ui.message_dialog import (
    steempeg_confirm_delete,
    steempeg_information,
    steempeg_question,
    steempeg_warning,
)

RENDERED_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
RENDERED_AUDIO_EXTS = {".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg", ".opus"}
RENDERED_ALL_EXTS = RENDERED_VIDEO_EXTS | RENDERED_AUDIO_EXTS

_RENDERED_TYPE_FILTER_ROLE = Qt.ItemDataRole.UserRole + 5
_RENDERED_GAME_FILTER_ROLE = Qt.ItemDataRole.UserRole + 6
_RENDERED_THUMB_ROLE = Qt.ItemDataRole.UserRole + 7
_RENDERED_ICON_ROLE = Qt.ItemDataRole.UserRole + 8
_HEALTH_SORT_INDICES = (5, 6)
_FOLDER_SORT_INDICES = (11, 12)
_TYPE_SORT_INDICES = (3, 4)
_DURATION_SORT_INDICES = (9, 10)
# Screenshots: keep Default / Game / Date; hide Type, Health, Duration, Folder.
_SCREENSHOT_HIDDEN_SORT = (
    _TYPE_SORT_INDICES + _HEALTH_SORT_INDICES + _DURATION_SORT_INDICES + _FOLDER_SORT_INDICES
)
# Global sort indices (shared with Clips combo) shown on the Screenshots tab.
_SCREENSHOTS_SORT_DEFS: tuple[tuple[int, str, str], ...] = (
    (0, "defaultsort.png", "Default"),
    (1, "lettersort1.png", "Game Name (A - Z)"),
    (2, "lettersort2.png", "Game Name (Z - A)"),
    (7, "datesort1.png", "Date (Oldest First)"),
    (8, "datesort2.png", "Date (Newest First)"),
)
_FULL_SORT_DEFS: tuple[tuple[str, str], ...] = (
    ("defaultsort.png", "Default"),
    ("lettersort1.png", "Game Name (A - Z)"),
    ("lettersort2.png", "Game Name (Z - A)"),
    ("lettersort1.png", "Type (A - Z)"),
    ("lettersort2.png", "Type (Z - A)"),
    ("nohealth.png", "Bad health first"),
    ("health.png", "Good health first"),
    ("datesort1.png", "Date (Oldest First)"),
    ("datesort2.png", "Date (Newest First)"),
    ("durationsort1.png", "Duration (Shortest)"),
    ("durationsort2.png", "Duration (Longest)"),
    ("lettersort1.png", "Folder (A - Z)"),
    ("lettersort2.png", "Folder (Z - A)"),
)


def _screenshots_local_sort_index(global_idx: int) -> int:
    for i, (gidx, _icon, _label) in enumerate(_SCREENSHOTS_SORT_DEFS):
        if gidx == int(global_idx):
            return i
    return len(_SCREENSHOTS_SORT_DEFS) - 1
_SHOT_GAME_ROLE = Qt.ItemDataRole.UserRole + 1
_SHOT_MTIME_ROLE = Qt.ItemDataRole.UserRole + 2
_SHOT_SOURCE_ROLE = Qt.ItemDataRole.UserRole + 3  # "steam" | "steempeg"
_SHOT_APP_ID_ROLE = Qt.ItemDataRole.UserRole + 4
_SHOT_THUMB_ROLE = Qt.ItemDataRole.UserRole + 5  # cached thumb path (may be unset)
# Filename sanitizer turns : * ? " < > | \ / into _; never map these labels to a game.
_GENERIC_SCREENSHOT_GAMES = frozenset({"clip", "unknown", "unknown game"})
# Viewport lazy load: overscan past the visible rect, debounce after scroll stops.
_SHOT_VIEWPORT_OVERSCAN_PX = 220
_SHOT_SCROLL_IDLE_MS = 120
_SHOT_MAX_LIVE_WIDGETS = 96

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
# Catalog of optional library panels. When every entry is open, the + control shows −.
_LIBRARY_PANEL_DEFS = (
    ("clips", "📁  Clips Manager"),
    ("rendered", "🎬  Rendered videos"),
    ("screenshots", "📷  Screenshots"),
    # ("queue", "📋  Render Queue"),  # future
)

_SCREENSHOT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _parse_screenshot_game_name(filename: str) -> str:
    """Game prefix from ``{Game}_{ms}ms_{YYYYMMDD}_{HHMMSS}[__clipfolder].ext`` names."""
    from steempeg.core.screenshot_clip_link import parse_steempeg_screenshot_name

    game, _pos_ms, _clip_folder = parse_steempeg_screenshot_name(filename)
    return game or os.path.splitext(os.path.basename(filename))[0]


def _normalize_screenshot_game_key(name: str) -> str:
    """Collapse filename-safe vs Steam display names for matching.

    ``Hatsune Miku_ Project DIVA Mega Mix+`` and
    ``Hatsune Miku: Project DIVA Mega Mix+`` become the same key.
    ``Tom & Jerry`` and ``Tom and Jerry`` also collapse together.
    """
    text = str(name or "").strip().casefold()
    if not text:
        return ""
    text = text.replace("&", " and ")
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def match_screenshot_game_in_cache(
    game_name: str, cache: dict | None
) -> tuple[str, str]:
    """Map a Steempeg screenshot game label to ``(app_id, canonical_name)``.

    Exact (casefold) first, then punctuation/underscore-normalized equality,
    then a conservative prefix/contains match for truncated names.
    Generic labels like ``Clip`` never match.
    """
    raw = str(game_name or "").strip()
    if not raw:
        return "", ""
    folded = raw.casefold()
    if folded in _GENERIC_SCREENSHOT_GAMES:
        return "", ""
    want = _normalize_screenshot_game_key(raw)
    if not want or want in _GENERIC_SCREENSHOT_GAMES:
        return "", ""

    exact_id = ""
    exact_name = ""
    norm_id = ""
    norm_name = ""
    fuzzy: list[tuple[int, str, str]] = []

    for app_id, cached_name in (cache or {}).items():
        aid = str(app_id or "").strip()
        label = str(cached_name or "").strip()
        if not aid or not label:
            continue
        if label.casefold() == folded:
            exact_id, exact_name = aid, label
            break
        got = _normalize_screenshot_game_key(label)
        if not got:
            continue
        if got == want:
            if not norm_id:
                norm_id, norm_name = aid, label
            continue
        shorter, longer = (want, got) if len(want) <= len(got) else (got, want)
        if len(shorter) < 12:
            continue
        if longer.startswith(shorter) or shorter in longer:
            fuzzy.append((abs(len(got) - len(want)), aid, label))

    if exact_id:
        return exact_id, exact_name
    if norm_id:
        return norm_id, norm_name
    if fuzzy:
        fuzzy.sort(key=lambda row: row[0])
        _delta, aid, label = fuzzy[0]
        return aid, label
    return "", ""


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
        self._library_tabs: dict[str, LibraryTabWidget] = {}
        self._rendered_filter_types: set[str] | None = None
        self._rendered_filter_games: set[str] | None = None
        self._screenshots_filter_games: set[str] | None = None
        self._screenshots_filter_folders: set[str] | None = None
        self._clips_view_mode = "grid"
        self._rendered_view_mode = "grid"
        self._saved_clips_selection_path = ""
        self._saved_rendered_selection_path = ""
        self._library_ui_restored = False
        self._library_ui_persist_ready = False
        self._library_filters_hydrated = False
        self._rendered_scan_generation = 0
        self._defer_rendered_scan_until_clips_done = False
        self._clips_scan_active = False
        self._rendered_scan_active = False
        self._startup_library_scan_active = False
        # Independent sort choice per library tab (survives tab switches + restart).
        self._sort_index_by_panel = {
            "clips": 0,
            "rendered": 0,
            "screenshots": 8,  # Date newest — matches previous scan order
        }
        # Last sort index actually applied to each panel's data (skip rebuild on tab switch).
        self._sort_applied_by_panel: dict[str, int] = {}
        self._sort_combo_mode: str | None = None
        self._library_rendered_rows: list[ScannedRenderedFile] = []
        # Screenshots viewport lazy-load (placeholders until visible).
        self._screenshots_scroll_active = False
        self._screenshots_viewport_timer: QTimer | None = None
        self._screenshot_live_paths: set[str] = set()

    def _make_library_tab_button(self, label: str, mode: str) -> LibraryTabWidget:
        from steempeg.ui.ui_density import COMFORT, tab_label

        dense = getattr(self, "_ui_density", None) or COMFORT
        tab = LibraryTabWidget(tab_label(mode, dense), mode)
        tab.apply_density(dense)
        tab.activated.connect(self.set_library_panel)
        tab.close_requested.connect(self._close_library_tab)
        return tab

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

        if hasattr(self, "library_toolbar_pill"):
            pass  # live toolbar — never hide
        elif hasattr(self, "mega_top_pill"):
            self.mega_top_pill.hide()

        for key, tab in self._library_tabs.items():
            tab.set_active(key == "clips")

        self._sync_library_add_button()

        if hasattr(self, "_sync_sort_combo_for_panel"):
            self._sync_sort_combo_for_panel()

    def _sync_library_add_button(self):
        """Show + while a panel can still be added; flip to − when the catalog is full."""
        if not hasattr(self, "btn_library_add"):
            return
        total = len(_LIBRARY_PANEL_DEFS)
        open_count = len(self._library_tabs)
        if open_count >= total:
            self.btn_library_add.setText("−")
            self.btn_library_add.setToolTip("Remove library panel")
        else:
            self.btn_library_add.setText("+")
            self.btn_library_add.setToolTip("Add or remove library panels")

    def _show_add_library_panel_menu(self):
        from steempeg.ui import ui_theme as ut

        menu = QMenu(self.ui)
        menu.setStyleSheet(ut.logs_menu_stylesheet())
        actions: dict = {}
        can_remove = len(self._library_tabs) > 1

        for mode, label in _LIBRARY_PANEL_DEFS:
            if mode in self._library_tabs:
                if can_remove:
                    act = menu.addAction(f"−  {label}")
                    actions[act] = ("close", mode)
            else:
                act = menu.addAction(f"+  {label}")
                actions[act] = ("open", mode)

        if not actions:
            return

        pos = self.btn_library_add.mapToGlobal(QPoint(0, self.btn_library_add.height()))
        chosen = menu.exec(pos)
        if chosen not in actions:
            return
        kind, mode = actions[chosen]
        if kind == "open":
            self.open_library_panel(mode)
        else:
            self._close_library_tab(mode)

    def _sync_sort_combo_for_panel(self):
        if not hasattr(self, "combo_sort"):
            return
        mode = getattr(self, "_library_panel_mode", "clips")
        if mode == "screenshots":
            self._ensure_screenshots_sort_combo()
            return
        self._ensure_full_sort_combo()
        view = self.combo_sort.view()
        for i in range(self.combo_sort.count()):
            view.setRowHidden(i, False)
        if mode == "rendered":
            for i in _HEALTH_SORT_INDICES:
                view.setRowHidden(i, True)

    def _rebuild_sort_combo_items(
        self, items: tuple[tuple[str, str], ...], *, mode_key: str
    ) -> None:
        from steempeg.infra.paths import get_resource_path

        combo = self.combo_sort
        if getattr(self, "_sort_combo_mode", None) == mode_key and combo.count() == len(
            items
        ):
            return
        combo.blockSignals(True)
        try:
            combo.clear()
            for icon_name, label in items:
                combo.addItem(QIcon(get_resource_path(icon_name)), label)
            combo.setMaxVisibleItems(max(14, len(items)))
            view = combo.view()
            if view is not None:
                fm = combo.fontMetrics()
                longest = max(
                    (fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())),
                    default=0,
                )
                view.setMinimumWidth(longest + 78)
            self._sort_combo_mode = mode_key
        finally:
            combo.blockSignals(False)

    def _ensure_full_sort_combo(self) -> None:
        self._rebuild_sort_combo_items(_FULL_SORT_DEFS, mode_key="full")

    def _ensure_screenshots_sort_combo(self) -> None:
        shot_items = tuple((icon, label) for _g, icon, label in _SCREENSHOTS_SORT_DEFS)
        self._rebuild_sort_combo_items(shot_items, mode_key="screenshots")

    def _screenshots_global_sort_index(self) -> int:
        if not hasattr(self, "combo_sort"):
            return 8
        local = int(self.combo_sort.currentIndex())
        if getattr(self, "_sort_combo_mode", None) == "screenshots":
            if 0 <= local < len(_SCREENSHOTS_SORT_DEFS):
                return int(_SCREENSHOTS_SORT_DEFS[local][0])
            return 8
        idx = local
        if idx not in {g for g, _, _ in _SCREENSHOTS_SORT_DEFS}:
            return 8
        return idx

    def _sort_indices_valid_for_panel(self, mode: str) -> set[int]:
        hidden = set()
        if mode == "screenshots":
            hidden = set(_SCREENSHOT_HIDDEN_SORT)
        elif mode == "rendered":
            hidden = set(_HEALTH_SORT_INDICES)
        total = self.combo_sort.count() if hasattr(self, "combo_sort") else 13
        return {i for i in range(total) if i not in hidden}

    def _stash_sort_for_panel(self, mode: str) -> None:
        if not hasattr(self, "combo_sort") or not mode:
            return
        if not hasattr(self, "_sort_index_by_panel"):
            self._sort_index_by_panel = {}
        if mode == "screenshots":
            self._sort_index_by_panel[mode] = self._screenshots_global_sort_index()
        else:
            self._sort_index_by_panel[mode] = int(self.combo_sort.currentIndex())

    def _restore_sort_for_panel(self, mode: str) -> None:
        if not hasattr(self, "combo_sort") or not mode:
            return
        if not hasattr(self, "_sort_index_by_panel"):
            self._sort_index_by_panel = {"clips": 0, "rendered": 0, "screenshots": 8}
        idx = int(self._sort_index_by_panel.get(mode, 0))
        valid = self._sort_indices_valid_for_panel(mode)
        if idx not in valid:
            idx = 8 if mode == "screenshots" else 0
            self._sort_index_by_panel[mode] = idx
        if mode == "screenshots":
            local = _screenshots_local_sort_index(idx)
            if self.combo_sort.currentIndex() == local:
                return
            self.combo_sort.blockSignals(True)
            self.combo_sort.setCurrentIndex(local)
            self.combo_sort.blockSignals(False)
            return
        if self.combo_sort.currentIndex() == idx:
            return
        self.combo_sort.blockSignals(True)
        self.combo_sort.setCurrentIndex(idx)
        self.combo_sort.blockSignals(False)

    def _remember_current_panel_sort(self) -> None:
        mode = getattr(self, "_library_panel_mode", "clips")
        self._stash_sort_for_panel(mode)

    def _stash_library_tab_selection(self, tab: str) -> None:
        if tab == "rendered" and hasattr(self, "table_rendered"):
            row = self.table_rendered.currentRow()
            if row >= 0:
                cell = self.table_rendered.item(row, 0)
                if cell:
                    self._saved_rendered_selection_path = cell.data(Qt.ItemDataRole.UserRole) or ""
            else:
                self._saved_rendered_selection_path = ""
        elif tab == "clips" and hasattr(self.ui, "table_clips"):
            row = self.ui.table_clips.currentRow()
            if row >= 0:
                cell = self.ui.table_clips.item(row, 0)
                if cell:
                    self._saved_clips_selection_path = cell.data(Qt.ItemDataRole.UserRole) or ""
            else:
                self._saved_clips_selection_path = ""

    def _clear_clips_selection_visual(self) -> None:
        selected_rows: set[int] = set()
        if hasattr(self, "grid_clips"):
            for item in self.grid_clips.selectedItems():
                row = item.data(Qt.ItemDataRole.UserRole)
                if row is not None:
                    selected_rows.add(int(row))
        if hasattr(self.ui, "table_clips"):
            self.ui.table_clips.blockSignals(True)
            self.ui.table_clips.clearSelection()
            self.ui.table_clips.setCurrentCell(-1, -1)
            self.ui.table_clips.blockSignals(False)
        if hasattr(self, "grid_clips"):
            self.grid_clips.blockSignals(True)
            self.grid_clips.clearSelection()
            self.grid_clips.blockSignals(False)
            # Only repaint cards that were selected — full-grid sync is slow on tab switch.
            if selected_rows:
                for i in range(self.grid_clips.count()):
                    item = self.grid_clips.item(i)
                    if item is None:
                        continue
                    row = item.data(Qt.ItemDataRole.UserRole)
                    if row not in selected_rows:
                        continue
                    card = self.grid_clips.itemWidget(item)
                    if card is not None and hasattr(card, "set_selected"):
                        card.set_selected(False)
        self._clips_visual_selected_rows = set()

    def _clear_rendered_selection_visual(self) -> None:
        if hasattr(self, "table_rendered"):
            self.table_rendered.blockSignals(True)
            self.table_rendered.clearSelection()
            self.table_rendered.setCurrentCell(-1, -1)
            self.table_rendered.blockSignals(False)
        if hasattr(self, "grid_rendered"):
            self.grid_rendered.blockSignals(True)
            self.grid_rendered.clearSelection()
            self.grid_rendered.setCurrentItem(None)
            self.grid_rendered.blockSignals(False)
            self._sync_rendered_grid_card_visuals()

    def library_has_item_selection(self) -> bool:
        """True when Clips / Rendered / Screenshots has one or more selected cards."""
        grid = getattr(self, "grid_clips", None)
        if grid is not None and grid.selectedItems():
            return True
        table = getattr(getattr(self, "ui", None), "table_clips", None)
        if table is not None:
            sm = table.selectionModel()
            if sm is not None and sm.hasSelection():
                return True
        rgrid = getattr(self, "grid_rendered", None)
        if rgrid is not None and rgrid.selectedItems():
            return True
        rtable = getattr(self, "table_rendered", None)
        if rtable is not None:
            sm = rtable.selectionModel()
            if sm is not None and sm.hasSelection():
                return True
        sgrid = getattr(self, "grid_screenshots", None)
        if sgrid is not None and sgrid.selectedItems():
            return True
        return False

    def clear_library_item_selection(self) -> bool:
        """Esc: drop Ctrl/Shift multi-select (and single select). Returns True if cleared."""
        if not self.library_has_item_selection():
            return False
        if hasattr(self, "_clear_clips_selection_visual"):
            self._clear_clips_selection_visual()
        if hasattr(self, "_clear_rendered_selection_visual"):
            self._clear_rendered_selection_visual()
        if hasattr(self, "_clear_screenshots_selection_visual"):
            self._clear_screenshots_selection_visual()
        return True

    def _restore_library_tab_selection(self, tab: str) -> None:
        """Re-paint the saved row highlight after a tab switch (preview keeps playing)."""
        if tab == "rendered":
            path = getattr(self, "_saved_rendered_selection_path", "")
            if path:
                self._highlight_rendered_path(path)
            else:
                self._clear_rendered_selection_visual()
        elif tab == "screenshots":
            # Screenshots grid selection is independent; do not re-paint Clips.
            return
        else:
            path = getattr(self, "_saved_clips_selection_path", "")
            if path:
                self._highlight_clip_path(path)
            else:
                self._clear_clips_selection_visual()

    def _highlight_clip_path(self, clip_path: str) -> bool:
        """Select clip in table/grid for display only — does not change preview or other panel."""
        if not self._is_valid_clip_path(clip_path) or not hasattr(self.ui, "table_clips"):
            return False
        norm = os.path.normpath(clip_path)
        for row in range(self.ui.table_clips.rowCount()):
            cell = self.ui.table_clips.item(row, 0)
            if not cell:
                continue
            row_path = cell.data(Qt.ItemDataRole.UserRole)
            if row_path and os.path.normpath(row_path) == norm:
                self.ui.table_clips.blockSignals(True)
                self.ui.table_clips.selectRow(row)
                self.ui.table_clips.setCurrentCell(row, 0)
                self.ui.table_clips.blockSignals(False)
                if hasattr(self, "sync_grid_from_table_selection"):
                    self.sync_grid_from_table_selection()
                return True
        return False

    def _highlight_rendered_path(self, file_path: str) -> bool:
        """Select rendered row in table/grid for display only."""
        if not file_path or not hasattr(self, "table_rendered"):
            return False
        norm = os.path.normpath(file_path)
        for row in range(self.table_rendered.rowCount()):
            cell = self.table_rendered.item(row, 0)
            if not cell:
                continue
            row_path = cell.data(Qt.ItemDataRole.UserRole)
            if row_path and os.path.normpath(row_path) == norm:
                sm = self.table_rendered.selectionModel()
                self.table_rendered.blockSignals(True)
                if sm is not None:
                    sm.blockSignals(True)
                try:
                    self.table_rendered.selectRow(row)
                    self.table_rendered.setCurrentCell(row, 0)
                finally:
                    if sm is not None:
                        sm.blockSignals(False)
                    self.table_rendered.blockSignals(False)
                self._sync_rendered_grid_from_table()
                return True
        return False

    def _close_library_tab(self, mode: str):
        if mode not in self._library_tabs:
            return
        if len(self._library_tabs) <= 1:
            return
        tab = self._library_tabs.pop(mode)
        self.library_tabs_host.removeWidget(tab)
        tab.deleteLater()
        self._sync_library_add_button()
        if self._library_panel_mode == mode:
            fallback = "clips" if "clips" in self._library_tabs else next(iter(self._library_tabs))
            self.set_library_panel(fallback)
        else:
            self._persist_library_ui_state()

    def open_library_panel(self, mode: str):
        self._ensure_library_tab(mode)
        self.set_library_panel(mode)

    def _ensure_library_tab(self, mode: str):
        if mode in self._library_tabs:
            return
        labels = dict(_LIBRARY_PANEL_DEFS)
        if mode not in labels:
            return
        if mode == "rendered":
            self._ensure_rendered_widgets()
        elif mode == "screenshots":
            self._ensure_screenshots_widgets()
        tab = self._make_library_tab_button(labels[mode], mode)
        order = [m for m, _ in _LIBRARY_PANEL_DEFS]
        insert_idx = sum(1 for m in order[: order.index(mode)] if m in self._library_tabs)
        self.library_tabs_host.insertWidget(insert_idx, tab)
        self._library_tabs[mode] = tab
        self._sync_library_add_button()
        if not getattr(self, "_restoring_library_state", False):
            self._persist_library_ui_state()

    def _ensure_rendered_tab(self):
        self._ensure_library_tab("rendered")

    def _wants_rendered_library_ui(self, state: dict) -> bool:
        return bool(
            state.get("rendered_tab_open")
            or state.get("library_panel_mode") == "rendered"
            or state.get("preview_kind") == "rendered"
        )

    def set_library_panel(self, mode: str):
        if mode not in self._library_tabs:
            return
        old_mode = getattr(self, "_library_panel_mode", "clips")
        if old_mode != mode:
            self._stash_library_tab_selection(old_mode)
            self._stash_sort_for_panel(old_mode)
            # Trim belongs to a clip preview; leaving the Clips tab must drop the trim
            # handles/button so they don't linger over a rendered preview.
            if old_mode == "clips" and hasattr(self, "cancel_trim_mode"):
                self.cancel_trim_mode()
        self._library_panel_mode = mode
        for key, tab in self._library_tabs.items():
            tab.set_active(key == mode)
        if hasattr(self, "sync_filter_pill_badge"):
            self.sync_filter_pill_badge()
        if hasattr(self, "library_stack"):
            self.library_stack.setCurrentIndex(self._library_stack_index_for(mode))
        if mode == "rendered":
            self._clear_clips_selection_visual()
            self._clear_screenshots_selection_visual()
            self._ensure_rendered_widgets()
            # Tab flip: show list/grid only — doItemsLayout freezes large shelves.
            self._apply_rendered_view_mode(relayout=False)
        elif mode == "screenshots":
            self._clear_clips_selection_visual()
            self._clear_rendered_selection_visual()
            self._ensure_screenshots_widgets()
            # Startup restore opens this tab before session-cache paint; a full
            # Steam+Steempeg refresh here freezes the UI for minutes (8k+ cards).
            if not getattr(self, "_restoring_library_state", False):
                self.refresh_screenshots_library(force=False)
            else:
                self._schedule_screenshots_viewport_refresh(50)
            # Hide/show can leave a stale IconMode wrap at the same width —
            # force one deferred reflow (not two).
            self._screenshots_last_reflow_w = None
            self._schedule_screenshots_grid_reflow(50)
        else:
            self._clear_rendered_selection_visual()
            self._clear_screenshots_selection_visual()
            if hasattr(self, "grid_clips"):
                # Same as Open related: keep cards where they are; no full relayout.
                from steempeg.ui.library.controller import LibraryMixin

                LibraryMixin.set_view_mode(
                    self, getattr(self, "_clips_view_mode", "grid"), relayout=False
                )
            if hasattr(self, "_schedule_clips_viewport_refresh"):
                self._schedule_clips_viewport_refresh(50)
        self._sync_library_view_toggle_for_mode()
        self._sync_sort_combo_for_panel()
        if old_mode != mode:
            self._restore_sort_for_panel(mode)
            self._restore_library_tab_selection(mode)
            # Re-sort only when this panel's data isn't already in the combo order.
            # Full apply_rendered_sorting rebuilds every grid card — too slow on tab flip.
            want = (
                self._screenshots_global_sort_index()
                if mode == "screenshots" and hasattr(self, "_screenshots_global_sort_index")
                else int(self.combo_sort.currentIndex())
                if hasattr(self, "combo_sort")
                else 0
            )
            last = getattr(self, "_sort_applied_by_panel", {}).get(mode)
            if last != want and hasattr(self, "apply_sorting"):
                self.apply_sorting()
        self._update_library_count_label()
        self._sync_library_mode_chrome()
        self._sync_library_footer_for_mode()
        if hasattr(self, "update_final_setup") and not (
            hasattr(self, "_is_previewing_rendered_media") and self._is_previewing_rendered_media()
        ):
            # Defer summary rebuild — sync update_final_setup on every tab flip
            # fights splitter glue and feels like UI-thread lag.
            if hasattr(self, "_schedule_update_final_setup"):
                self._schedule_update_final_setup(0)
            else:
                self.update_final_setup()
            if hasattr(self, "_update_start_button_label"):
                self._update_start_button_label()
        self._schedule_persist_library_ui_state()

    def _library_stack_index_for(self, mode: str) -> int:
        if not hasattr(self, "library_stack"):
            return 0
        if mode == "rendered":
            self._ensure_rendered_widgets()
            idx = self.library_stack.indexOf(self.rendered_page)
            return idx if idx >= 0 else 0
        if mode == "screenshots":
            self._ensure_screenshots_widgets()
            idx = self.library_stack.indexOf(self.screenshots_page)
            return idx if idx >= 0 else 0
        idx = self.library_stack.indexOf(getattr(self, "clips_page", None))
        return idx if idx >= 0 else 0

    def _sync_library_footer_for_mode(self) -> None:
        """Swap Choose Folder / Refresh chrome to match the active library tab."""
        from steempeg.ui.ui_density import (
            COMFORT,
            folder_button_label,
            records_folder_button_label,
            screenshots_folder_button_label,
        )

        mode = getattr(self, "_library_panel_mode", "clips")
        dense = (
            getattr(self, "_ui_density", None)
            or COMFORT
        )
        picker = getattr(self, "folder_picker", None)
        refresh = getattr(self, "btn_refresh", None)

        if picker is not None:
            from steempeg.ui.signal_utils import safe_disconnect

            safe_disconnect(picker.main_btn.clicked)
            safe_disconnect(picker.add_btn.clicked)

            if mode == "rendered":
                path = getattr(self, "custom_destination", "") or ""
                tip = path or "Export / Records folder"
                picker.set_folder_label(records_folder_button_label(dense), tip)
                picker.set_add_visible(False)
                picker.main_btn.clicked.connect(self.choose_records_folder)
            elif mode == "screenshots":
                folder = self._screenshots_folder_path()
                tip = folder or "Screenshots folder"
                picker.set_folder_label(screenshots_folder_button_label(dense), tip)
                picker.set_add_visible(False)
                picker.main_btn.clicked.connect(self.choose_screenshots_folder)
            else:
                folders = getattr(self, "clips_folders", []) or []
                tip = ("Library folders:\n" + "\n".join(folders)) if len(folders) > 1 else ""
                picker.set_folder_label(folder_button_label(len(folders), dense), tip)
                picker.set_add_visible(bool(folders))
                picker.main_btn.clicked.connect(self.choose_folder)
                picker.add_btn.clicked.connect(self.show_folders_panel)

        if refresh is not None:
            # Keep the ▾ split on every tab (hiding it made Refresh stretch weirdly).
            if hasattr(refresh, "set_menu_visible"):
                refresh.set_menu_visible(True)
            refresh.main_btn.setToolTip(
                "Rescan Clips Manager, Rendered videos, and Screenshots"
            )
            if hasattr(refresh, "menu_btn"):
                if mode == "rendered":
                    refresh.menu_btn.setToolTip(
                        "Refresh Rendered videos only… (and health re-check)"
                    )
                elif mode == "screenshots":
                    refresh.menu_btn.setToolTip("Refresh Screenshots only…")
                else:
                    refresh.menu_btn.setToolTip(
                        "Refresh Clips Manager only… (and Steam icons / names / health)"
                    )

    def _sync_library_mode_chrome(self):
        """Hide export settings while previewing finished media, not only on the tab."""
        show_bottom = self._should_show_render_dock()
        prev_show = getattr(self, "_render_dock_visible", None)
        self._render_dock_visible = show_bottom

        portable_like = False
        if hasattr(self, "_desktop_render_layout_is_portable_like"):
            try:
                portable_like = bool(self._desktop_render_layout_is_portable_like())
            except Exception:
                portable_like = False

        # Desktop: player wrapper reserves a 10px gap above the splitter handle.
        # Like a Portable: gap lives on bottom_v_wrap (or the middle handle) — keep
        # top_v_wrap flush so library sync cannot fight portable glue.
        if hasattr(self, "top_v_wrap") and self.top_v_wrap.layout() is not None:
            m = self.top_v_wrap.layout().contentsMargins()
            if portable_like:
                self.top_v_wrap.layout().setContentsMargins(
                    m.left(), m.top(), m.right(), 0
                )
            else:
                self.top_v_wrap.layout().setContentsMargins(
                    m.left(), m.top(), m.right(), 10 if show_bottom else 0
                )

        immersive = getattr(self, "is_theater", False) or getattr(
            self, "is_fullscreen", False
        )
        # Theatre / fullscreen own dock visibility — don't fight their layout
        # (Like a Portable glue + bottom show/hide made theatre enter ragged).
        if immersive:
            self._render_dock_visible = False
            return

        # Snapshot a usable dock height before mode-hide. Suppress HideWatcher so its
        # Hide/Show setSizes cannot race Like a Portable glue / our restore.
        hw = getattr(self, "hide_watcher", None)
        if (
            not show_bottom
            and prev_show is not False
            and hasattr(self, "main_v_splitter")
        ):
            try:
                cur = list(self.main_v_splitter.sizes())
            except RuntimeError:
                cur = []
            if len(cur) >= 2 and cur[1] > 0:
                self._render_dock_saved_sizes = cur

        if hw is not None and hasattr(hw, "set_suppressed"):
            hw.set_suppressed(True)
        try:
            if hasattr(self, "bottom_v_wrap"):
                self.bottom_v_wrap.setVisible(show_bottom)
            if hasattr(self, "main_v_splitter") and not immersive:
                sizes = self.main_v_splitter.sizes()
                total = sum(sizes) if sum(sizes) > 0 else self.main_v_splitter.height()
                total = max(int(total), 1)
                if show_bottom:
                    # Only restore when leaving a mode-hide (Screenshots / rendered
                    # preview), NOT on every sync while the user collapsed by hand.
                    if (
                        prev_show is False
                        and len(sizes) >= 2
                        and sizes[1] <= 0
                    ):
                        saved = getattr(self, "_render_dock_saved_sizes", None)
                        if portable_like and hasattr(
                            self, "_glue_portable_like_dash_open"
                        ):
                            self._portable_like_dash_closed = False
                            self._glue_portable_like_dash_open()
                        elif (
                            saved
                            and len(saved) >= 2
                            and saved[1] > 0
                        ):
                            self.main_v_splitter.setSizes(saved)
                        elif hasattr(self, "_apply_desktop_main_v_splitter_sizes"):
                            self._apply_desktop_main_v_splitter_sizes()
                        else:
                            from steempeg.ui.layout_defaults import (
                                restore_v_splitter_sizes,
                            )

                            self.main_v_splitter.setSizes(
                                restore_v_splitter_sizes(total)
                            )
                        self._render_dock_saved_sizes = None
                else:
                    self.main_v_splitter.setSizes([total, 0])
        finally:
            if hw is not None and hasattr(hw, "set_suppressed"):
                hw.set_suppressed(
                    bool(portable_like)
                    or bool(getattr(self, "_portable_shell", False))
                )

        # Classic Desktop: if neo was left in the Like-a-Portable garage, the
        # bottom dock shows a tall empty black void above the dash — reclaim it.
        if show_bottom and hasattr(self, "_ensure_docked_neo_visible_for_context"):
            try:
                self._ensure_docked_neo_visible_for_context()
            except Exception:
                pass

        # Like a Portable: clip select / mode sync can leave a tall bottom pane
        # (inflated dash height or unlocked glue). Re-pin buttons and re-glue.
        if (
            show_bottom
            and portable_like
            and not immersive
            and not getattr(self, "_portable_like_dash_closed", False)
        ):
            if hasattr(self, "_pin_dash_queue_header_buttons"):
                try:
                    self._pin_dash_queue_header_buttons()
                except Exception:
                    pass
            if hasattr(self, "_glue_portable_like_dash_open"):
                try:
                    self._glue_portable_like_dash_open()
                except Exception:
                    pass

        # Clip select / Screenshots dock hide-show churns geometry; IconMode wrap
        # must recalculate against the settled library width (empty right gap).
        if (
            getattr(self, "_library_panel_mode", "") == "screenshots"
            and prev_show is not None
            and prev_show != show_bottom
        ):
            self._schedule_screenshots_grid_reflow(0)
            self._schedule_screenshots_grid_reflow(80)

    def _is_previewing_rendered_media(self) -> bool:
        if getattr(self, "_rendered_media_path", None):
            return True
        path = getattr(self, "_preview_clip_path", None)
        if path and os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            return ext in RENDERED_ALL_EXTS
        return False

    def _has_active_raw_clip(self) -> bool:
        """True when a Clips Manager Steam clip (folder / .mpd) is the active preview.

        Screenshots tab clears the Clips grid highlight but keeps the player on the
        loaded clip — export chrome must stay available in that case.
        """
        if getattr(self, "_rendered_media_path", None):
            return False
        path = getattr(self, "_preview_clip_path", None)
        if not path:
            return False
        try:
            if os.path.isdir(path):
                return True
            if os.path.isfile(path) and path.lower().endswith(".mpd"):
                return True
        except OSError:
            return False
        return False

    def _render_dock_kept_alive(self) -> bool:
        """True while the user still needs Start / Pause / Cancel / Logs.

        Render Queue open (any jobs) or an in-flight single/batch render must keep
        the bottom dock visible even on the Rendered Videos tab. Theatre and
        fullscreen still hide it via ``_should_show_render_dock``.
        """
        if getattr(self, "_is_rendering", False):
            return True
        if getattr(self, "_queue_batch_active", False):
            return True
        rq = getattr(self, "render_queue", None)
        return bool(rq) and len(rq) > 0

    def _should_show_render_dock(self) -> bool:
        if getattr(self, "is_theater", False) or getattr(self, "is_fullscreen", False):
            return False
        if self._render_dock_kept_alive():
            return True
        # Loaded Clips Manager .mpd keeps dash + settings even on Screenshots tab.
        if self._has_active_raw_clip():
            return True
        # Screenshots-only (no raw clip): nothing to export — hide the dock.
        if getattr(self, "_library_panel_mode", "clips") == "screenshots":
            return False
        # Idle Rendered Videos / finished-export preview: hide settings + controls.
        return not self._is_previewing_rendered_media()

    def _meta_from_render_job(self, job) -> dict:
        clip_name = os.path.basename(job.clip_path or "")
        app_id = parse_app_id_from_name(clip_name) or parse_app_id_from_clip_folder(clip_name)
        return {
            "app_id": app_id or "",
            "game_name": getattr(job, "game_name", "") or "",
            "clip_path": getattr(job, "clip_path", "") or "",
            "game_icon_path": getattr(job, "game_icon_path", "") or "",
        }

    def _build_rendered_output_meta_index(self) -> dict[str, dict]:
        index: dict[str, dict] = {}
        for job in getattr(self, "render_queue", []):
            out = getattr(job, "output_file", "") or ""
            if out:
                index[os.path.normcase(os.path.normpath(out))] = self._meta_from_render_job(job)
        try:
            from steempeg.render.queue_history import load_history

            hist_path = os.path.join(self.cache_dir, "render_queue_history.json")
            batches = getattr(self, "_render_history_cache", None)
            if batches is None:
                batches = load_history(hist_path)
                self._render_history_cache = batches
            for batch in batches:
                for jdict in batch.jobs:
                    out = jdict.get("output_file")
                    if not out:
                        continue
                    from steempeg.render.queue_history import parse_history_job

                    job, _status = parse_history_job(jdict)
                    if job:
                        index[os.path.normcase(os.path.normpath(out))] = self._meta_from_render_job(job)
        except Exception as exc:
            logging.debug("Rendered output meta index skipped: %s", exc)
        return index

    def _lookup_rendered_source_meta(self, file_path: str, basename: str) -> dict:
        companion = load_rendered_companion_meta(
            file_path, cache_dir=getattr(self, "cache_dir", None)
        )
        if companion:
            return companion

        norm = os.path.normcase(os.path.normpath(file_path))
        index = getattr(self, "_rendered_output_meta_index", None)
        if index is None:
            index = self._build_rendered_output_meta_index()
            self._rendered_output_meta_index = index
        if norm in index:
            return index[norm]

        app_id = parse_app_id_from_name(basename)
        if app_id:
            return {"app_id": app_id}
        return {}

    def _game_icon_path_for_rendered(self, app_id: str | None, fallback: str = "") -> str:
        if fallback and os.path.isfile(fallback):
            return fallback
        if app_id:
            cache_icon = os.path.join(self.cache_dir, f"{app_id}.jpg")
            if os.path.isfile(cache_icon) and os.path.getsize(cache_icon) > 100:
                return cache_icon
        return ""

    def _library_ui_path(self) -> str:
        return os.path.join(self.cache_dir, "library_ui.json")

    def _load_library_ui_state(self) -> dict:
        path = self._library_ui_path()
        data = cache.read_json(path)
        if data:
            return data
        legacy = {}
        if hasattr(self, "load_user_settings"):
            legacy = self.load_user_settings().get("library_ui") or {}
        if legacy:
            try:
                cache.write_json(path, legacy)
            except OSError:
                pass
        return legacy

    def _persist_library_ui_state(self):
        if getattr(self, "_restoring_library_state", False):
            return
        if not getattr(self, "_library_ui_persist_ready", False):
            return
        if not hasattr(self, "save_user_settings"):
            return

        clips_selected = ""
        rendered_selected = ""
        panel_mode = getattr(self, "_library_panel_mode", "clips")
        if panel_mode == "rendered" and hasattr(self, "table_rendered") and self.table_rendered.currentRow() >= 0:
            cell = self.table_rendered.item(self.table_rendered.currentRow(), 0)
            if cell:
                rendered_selected = cell.data(Qt.ItemDataRole.UserRole) or ""

        preview_kind = ""
        preview_path = ""
        if getattr(self, "_rendered_media_path", None):
            preview_kind = "rendered"
            preview_path = self._rendered_media_path

        rendered_tab_open = "rendered" in getattr(self, "_library_tabs", {})
        screenshots_tab_open = "screenshots" in getattr(self, "_library_tabs", {})
        self._remember_current_panel_sort()
        sorts = getattr(self, "_sort_index_by_panel", {}) or {}
        payload = {
            "library_panel_mode": getattr(self, "_library_panel_mode", "clips"),
            "clips_view_mode": getattr(self, "_clips_view_mode", "grid"),
            "rendered_view_mode": getattr(self, "_rendered_view_mode", "grid"),
            "rendered_tab_open": rendered_tab_open,
            "screenshots_tab_open": screenshots_tab_open,
            "clips_selected_path": clips_selected,
            "rendered_selected_path": rendered_selected,
            "preview_kind": preview_kind,
            "preview_path": preview_path,
            "clips_sort_index": int(sorts.get("clips", 0)),
            "rendered_sort_index": int(sorts.get("rendered", 0)),
            "screenshots_sort_index": int(sorts.get("screenshots", 8)),
        }
        payload.update(self._library_filter_memory_payload())
        try:
            cache.write_json(self._library_ui_path(), payload)
        except OSError as exc:
            logging.warning("Could not save library_ui.json: %s", exc)
        self.save_user_settings("library_ui", payload)
        logging.info(
            "Saved library_ui (rendered_tab_open=%s, mode=%s)",
            payload["rendered_tab_open"],
            payload["library_panel_mode"],
        )

    def _schedule_persist_library_ui_state(self, delay_ms: int = 180) -> None:
        """Debounce library_ui.json + settings writes off the click/tab stack."""
        if getattr(self, "_restoring_library_state", False):
            return
        if not getattr(self, "_library_ui_persist_ready", False):
            return
        timer = getattr(self, "_library_ui_persist_timer", None)
        if timer is None:
            timer = QTimer(getattr(self, "ui", None))
            timer.setSingleShot(True)
            timer.timeout.connect(self._persist_library_ui_state)
            self._library_ui_persist_timer = timer
        timer.start(max(0, int(delay_ms)))

    def _library_filter_memory_payload(self) -> dict:
        """Filter-memory keys for ``library_ui.json`` (omit = cleared / all-on)."""
        from steempeg.ui.library import filter_persist as fpersist

        payload: dict = {}
        clips = fpersist.encode_clips_filters(getattr(self, "saved_filter_state", None))
        if clips:
            payload["clips_filters"] = clips
        rendered = fpersist.encode_rendered_filters(
            getattr(self, "_rendered_filter_games", None),
            getattr(self, "_rendered_filter_types", None),
        )
        if rendered:
            payload["rendered_filters"] = rendered
        shots = fpersist.encode_screenshots_filters(
            getattr(self, "_screenshots_filter_games", None),
            getattr(self, "_screenshots_filter_folders", None),
        )
        if shots:
            payload["screenshots_filters"] = shots
        return payload

    def _hydrate_library_filters_from_state(self, state: dict | None) -> None:
        """Load filter memory into session attrs (before library paint / scan)."""
        from steempeg.ui.library import filter_persist as fpersist

        data = state if isinstance(state, dict) else {}
        self.saved_filter_state = fpersist.decode_clips_filters(data.get("clips_filters"))
        rgames, types = fpersist.decode_rendered_filters(data.get("rendered_filters"))
        self._rendered_filter_games = rgames
        self._rendered_filter_types = types
        sgames, folders = fpersist.decode_screenshots_filters(
            data.get("screenshots_filters")
        )
        self._screenshots_filter_games = sgames
        self._screenshots_filter_folders = folders
        if hasattr(self, "sync_filter_pill_badge"):
            QTimer.singleShot(0, self.sync_filter_pill_badge)

    def _persist_library_filter_memory(self) -> None:
        """Write filter memory without waiting for the full UI-persist gate.

        Used after Apply / Clear so Clear wipes disk even during the short
        startup window where tab/view restore still holds the gate closed.
        """
        if getattr(self, "_restoring_library_state", False):
            return
        if not hasattr(self, "save_user_settings"):
            return
        state = dict(self._load_library_ui_state() or {})
        for key in ("clips_filters", "rendered_filters", "screenshots_filters"):
            state.pop(key, None)
        state.update(self._library_filter_memory_payload())
        try:
            cache.write_json(self._library_ui_path(), state)
        except OSError as exc:
            logging.warning("Could not save library filter memory: %s", exc)
        self.save_user_settings("library_ui", state)

    def _restore_library_ui_state(self):
        # Filter memory can hydrate before the tab host exists — Skip paint may
        # race the first restore retry.
        if not getattr(self, "_library_filters_hydrated", False):
            early = self._load_library_ui_state()
            if early:
                self._hydrate_library_filters_from_state(early)
                self._library_filters_hydrated = True

        if not hasattr(self, "library_stack") or not hasattr(self, "library_tabs_host"):
            QTimer.singleShot(50, self._restore_library_ui_state)
            return
        state = self._load_library_ui_state()
        if not state:
            return

        logging.info(
            "Restore library_ui (rendered_tab_open=%s, mode=%s)",
            state.get("rendered_tab_open"),
            state.get("library_panel_mode", "clips"),
        )

        wants_rendered = self._wants_rendered_library_ui(state)
        if wants_rendered and "rendered" not in self._library_tabs:
            self._ensure_rendered_tab()
            logging.info(
                "Restored Rendered videos tab (panel_mode=%s)",
                state.get("library_panel_mode", "clips"),
            )

        wants_shots = bool(
            state.get("screenshots_tab_open")
            or state.get("library_panel_mode") == "screenshots"
        )
        if wants_shots and "screenshots" not in self._library_tabs:
            self._ensure_library_tab("screenshots")

        if getattr(self, "_library_ui_restored", False):
            if wants_rendered and "rendered" not in self._library_tabs:
                self._ensure_rendered_tab()
            return

        self._saved_clips_selection_path = ""
        self._saved_rendered_selection_path = state.get("rendered_selected_path") or ""
        self._restoring_library_state = True
        try:
            clips_vm = state.get("clips_view_mode")
            rendered_vm = state.get("rendered_view_mode")
            if clips_vm in ("grid", "list"):
                self._clips_view_mode = clips_vm
            if rendered_vm in ("grid", "list"):
                self._rendered_view_mode = rendered_vm

            if not hasattr(self, "_sort_index_by_panel"):
                self._sort_index_by_panel = {}
            for key, field, default in (
                ("clips", "clips_sort_index", 0),
                ("rendered", "rendered_sort_index", 0),
                ("screenshots", "screenshots_sort_index", 8),
            ):
                raw = state.get(field)
                try:
                    self._sort_index_by_panel[key] = int(raw) if raw is not None else default
                except (TypeError, ValueError):
                    self._sort_index_by_panel[key] = default

            mode = state.get("library_panel_mode", "clips")
            try:
                from steempeg.ui.settings_prefs import load_remember_library_tab

                settings = {}
                if hasattr(self, "load_user_settings"):
                    settings = self.load_user_settings() or {}
                if not load_remember_library_tab(settings):
                    mode = "clips"
            except Exception:
                pass
            if mode == "rendered" and "rendered" in getattr(self, "_library_tabs", {}):
                self.open_library_panel("rendered")
            elif mode in getattr(self, "_library_tabs", {}):
                self.open_library_panel(mode)

            QTimer.singleShot(
                0,
                lambda s=dict(state): self._restore_library_selections(s),
            )
            self._library_ui_restored = True
        finally:
            self._restoring_library_state = False

    def _restore_library_selections(self, state: dict):
        """Restore rendered-tab highlight only — clips start clean until the user picks one."""
        if hasattr(self, "_clear_clips_selection_visual"):
            self._clear_clips_selection_visual()
        self._saved_clips_selection_path = ""
        if hasattr(self, "_preview_clip_path"):
            self._preview_clip_path = None

        preview_kind = state.get("preview_kind") or ""
        preview_path = (state.get("preview_path") or "").strip()
        mode = state.get("library_panel_mode", "clips")

        if preview_kind == "rendered" and preview_path and os.path.isfile(preview_path):
            self._select_rendered_path(preview_path, play=False)
        elif mode == "rendered":
            rendered_path = (state.get("rendered_selected_path") or "").strip()
            if rendered_path:
                self._select_rendered_path(rendered_path, play=False)

        if hasattr(self, "_sync_library_mode_chrome"):
            self._sync_library_mode_chrome()

    def _is_valid_clip_path(self, clip_path: str) -> bool:
        if not clip_path or not os.path.isdir(clip_path):
            return False
        norm = os.path.normpath(clip_path)
        if os.path.basename(norm).lower() in ("gamerecordings", "clips", "video"):
            return False
        for root in getattr(self, "clips_folders", []):
            if root and norm == os.path.normpath(root):
                return False
        if hasattr(self, "_is_steam_clip_container_folder") and self._is_steam_clip_container_folder(clip_path):
            return False
        if hasattr(self, "_is_clip_library_root") and self._is_clip_library_root(clip_path):
            return False
        return self._looks_like_single_clip_folder(clip_path)

    def _select_clip_path(self, clip_path: str, *, play: bool) -> bool:
        if not self._is_valid_clip_path(clip_path):
            return False
        if hasattr(self, "_clear_rendered_selection_visual"):
            self._clear_rendered_selection_visual()
        self._saved_rendered_selection_path = ""
        if not self._highlight_clip_path(clip_path):
            return False
        if play and hasattr(self, "update_quality_options"):
            self.update_quality_options()
        return True

    def _select_rendered_path(self, file_path: str, *, play: bool) -> bool:
        if not file_path or not hasattr(self, "table_rendered"):
            return False
        if hasattr(self, "_clear_clips_selection_visual"):
            self._clear_clips_selection_visual()
        self._saved_clips_selection_path = ""
        if not self._highlight_rendered_path(file_path):
            return False
        if play:
            self.update_rendered_selection()
        return True

    def register_new_rendered_output(self, file_path: str) -> bool:
        """Insert one freshly exported file into Rendered videos without a full rescan."""
        if not file_path or not os.path.isfile(file_path):
            return False
        self._ensure_rendered_widgets()
        norm = os.path.normcase(os.path.normpath(file_path))
        for row in range(self.table_rendered.rowCount()):
            cell = self.table_rendered.item(row, 0)
            if not cell:
                continue
            row_path = cell.data(Qt.ItemDataRole.UserRole)
            if row_path and os.path.normcase(os.path.normpath(row_path)) == norm:
                return True

        from steempeg.library.rendered_scan import RENDERED_ALL_EXTS, scan_single_rendered_file

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in RENDERED_ALL_EXTS:
            return False

        try:
            stat = os.stat(file_path)
        except OSError:
            return False

        icons_cache = self._seed_rendered_icons_cache() if hasattr(self, "_seed_rendered_icons_cache") else {}
        scanned = scan_single_rendered_file(
            file_path,
            stat.st_mtime,
            stat.st_size,
            ext,
            meta_index={},
            cache_dir=self.cache_dir,
            game_names_cache=self.game_names_cache,
            icons_cache=icons_cache,
        )
        table_row = self._insert_rendered_file_row(scanned)
        if table_row >= 0:
            self._append_rendered_grid_card_for_row(table_row)
        if hasattr(self, "_update_library_count_label"):
            self._update_library_count_label()
        if table_row >= 0 and scanned.needs_poster and hasattr(self, "_schedule_rendered_poster_backfill"):
            self._schedule_rendered_poster_backfill()
        return table_row >= 0

    def open_in_rendered_videos(self, file_path: str, *, play: bool = True) -> bool:
        """Switch to Rendered videos, select the file, and optionally start preview."""
        if not file_path or not os.path.isfile(file_path):
            return False
        self.open_library_panel("rendered")
        if self._select_rendered_path(file_path, play=play):
            return True
        if hasattr(self, "register_new_rendered_output"):
            if self.register_new_rendered_output(file_path):
                return self._select_rendered_path(file_path, play=play)
        from steempeg.ui.message_dialog import steempeg_warning

        steempeg_warning(
            self.ui,
            "Rendered videos",
            "This file is not in the library scan folders.\n\n"
            "Check that it still exists and that your export folder in render settings "
            "matches where the file was saved.",
        )
        return False

    def open_source_clip(
        self,
        clip_path: str,
        *,
        play: bool = True,
        seek_sec: float | None = None,
    ) -> bool:
        """Switch to Clips Manager and select the original Steam clip folder.

        ``seek_sec`` — optional playhead offset after the clip finishes loading
        (screenshot → related clip). ``None`` / non-positive → open at start.
        """
        from steempeg.ui.message_dialog import steempeg_warning

        if not clip_path or not self._is_valid_clip_path(clip_path):
            steempeg_warning(
                self.ui,
                "Source clip",
                "The original clip folder was not found.\n\n"
                "It may have been moved or deleted from your library folders.",
            )
            return False

        # Light tab flip — skip grid relayout / sort / selection restore thrash.
        self._show_clips_panel_for_source_jump()

        # Already on this clip: seek in place (fixes lag + second-open EOF snap).
        if (
            play
            and seek_sec is not None
            and float(seek_sec) > 0
            and hasattr(self, "_is_clip_actively_previewing")
            and self._is_clip_actively_previewing(clip_path)
        ):
            if hasattr(self, "_clear_rendered_selection_visual"):
                self._clear_rendered_selection_visual()
            self._saved_rendered_selection_path = ""
            self._highlight_clip_path(clip_path)
            if hasattr(self, "_seek_active_clip_to_sec"):
                self._seek_active_clip_to_sec(float(seek_sec))
            if hasattr(self, "_persist_library_ui_state"):
                self._persist_library_ui_state()
            return True

        # Stash before select — update_quality_options opens the clip synchronously.
        if hasattr(self, "_stash_pending_open_seek"):
            self._stash_pending_open_seek(clip_path, seek_sec)
        elif seek_sec is not None and float(seek_sec) > 0:
            key = (
                self._norm_clip_path_key(clip_path)
                if hasattr(self, "_norm_clip_path_key")
                else os.path.normcase(os.path.normpath(clip_path))
            )
            self._pending_open_seek = (key, float(seek_sec))
        else:
            self._pending_open_seek = None
        if self._select_clip_path(clip_path, play=play):
            if hasattr(self, "_persist_library_ui_state"):
                self._persist_library_ui_state()
            return True
        self._pending_open_seek = None
        if hasattr(self, "_open_seek_timer_armed"):
            self._open_seek_timer_armed = False
        steempeg_warning(
            self.ui,
            "Source clip",
            "Could not select this clip in the library.\n\n"
            "Make sure its folder is still in your Clips Manager scan list.",
        )
        return False

    def _show_clips_panel_for_source_jump(self) -> None:
        """Switch to Clips without grid relayout, sort, or selection restore.

        Open related clip already knows the target path — a full ``set_library_panel``
        freezes the UI on large libraries (doItemsLayout + restore + sort) before
        play/seek even starts.
        """
        self._ensure_library_tab("clips")
        old_mode = getattr(self, "_library_panel_mode", "clips")
        if old_mode == "clips":
            return
        if old_mode in self._library_tabs:
            self._stash_library_tab_selection(old_mode)
            self._stash_sort_for_panel(old_mode)
        self._library_panel_mode = "clips"
        for key, tab in self._library_tabs.items():
            tab.set_active(key == "clips")
        if hasattr(self, "library_stack"):
            self.library_stack.setCurrentIndex(self._library_stack_index_for("clips"))
        self._clear_rendered_selection_visual()
        self._clear_screenshots_selection_visual()
        # Keep existing list/grid visibility — do not call set_view_mode (relayout).
        self._sync_library_view_toggle_for_mode()
        self._sync_sort_combo_for_panel()
        self._restore_sort_for_panel("clips")
        self._update_library_count_label()
        self._sync_library_mode_chrome()
        self._sync_library_footer_for_mode()
        if hasattr(self, "update_final_setup") and not (
            hasattr(self, "_is_previewing_rendered_media")
            and self._is_previewing_rendered_media()
        ):
            self.update_final_setup()
            if hasattr(self, "_update_start_button_label"):
                self._update_start_button_label()

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
        self.table_rendered.setFont(tok.ui_qfont(10, weight=QFont.Weight.DemiBold))
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
        self.table_rendered.setStyleSheet(library_table_stylesheet())
        install_library_vertical_scrollbar(self.table_rendered)

        self.grid_rendered = QListWidget()
        self.grid_rendered.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid_rendered.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid_rendered.setSpacing(15)
        self.grid_rendered.setUniformItemSizes(True)
        self.grid_rendered.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid_rendered.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.grid_rendered.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.grid_rendered.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.grid_rendered.setMovement(QListWidget.Movement.Static)
        self.grid_rendered.setStyleSheet(library_grid_stylesheet())
        install_library_vertical_scrollbar(self.grid_rendered)

        self.table_rendered.itemSelectionChanged.connect(self.update_rendered_selection)
        self.table_rendered.itemSelectionChanged.connect(self._sync_rendered_grid_from_table)
        self.grid_rendered.itemSelectionChanged.connect(self._on_rendered_grid_selection_changed)

        self.grid_rendered.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid_rendered.viewport().installEventFilter(self)
        self.table_rendered.viewport().installEventFilter(self)
        self.grid_rendered.installEventFilter(self)
        self.table_rendered.installEventFilter(self)

        rendered_layout.addWidget(self.table_rendered)
        rendered_layout.addWidget(self.grid_rendered)
        self.library_stack.addWidget(self.rendered_page)

        self.table_rendered.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_rendered.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _screenshots_folder_path(self) -> str:
        try:
            from steempeg.ui.settings_prefs import resolve_screenshots_folder

            settings = {}
            if hasattr(self, "load_user_settings"):
                settings = self.load_user_settings() or {}
            return resolve_screenshots_folder(settings)
        except Exception:
            from steempeg.infra.paths import get_save_directory

            return os.path.join(get_save_directory(), "Screenshots")

    def _ensure_screenshots_widgets(self):
        if hasattr(self, "grid_screenshots"):
            return

        self.screenshots_page = QWidget()
        self.screenshots_page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self.screenshots_page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.grid_screenshots = QListWidget()
        self.grid_screenshots.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid_screenshots.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid_screenshots.setWrapping(True)
        self.grid_screenshots.setSpacing(14)
        self.grid_screenshots.setUniformItemSizes(True)
        # Extended multi-select for paint-drag; keep rubber-band ghost off
        # (SelectionRectVisible False + viewport MouseMove swallow in lifecycle).
        self.grid_screenshots.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid_screenshots.setSelectionRectVisible(False)
        self.grid_screenshots.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.grid_screenshots.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.grid_screenshots.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.grid_screenshots.setMovement(QListWidget.Movement.Static)
        self.grid_screenshots.setDragEnabled(False)
        from steempeg.ui.library.library_styles import (
            LIBRARY_SCROLLBAR_VERTICAL,
            install_library_vertical_scrollbar,
        )

        # Transparent cells — ScreenshotPhoto draws the framed image itself.
        self.grid_screenshots.setStyleSheet(
            """
            QListWidget { background: transparent; border: none; outline: none; }
            QListWidget::item {
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QListWidget::item:selected { background: transparent; }
            QListWidget::item:focus { outline: none; }
            """
            + LIBRARY_SCROLLBAR_VERTICAL
        )
        install_library_vertical_scrollbar(self.grid_screenshots)
        # Start hidden; sync_screenshots_vertical_scrollbar switches to AlwaysOn
        # once content overflows (stable wrap width — no AsNeeded 3→2 sticky).
        self.grid_screenshots.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_screenshots.itemSelectionChanged.connect(self._on_screenshots_grid_selection_changed)
        self.grid_screenshots.viewport().installEventFilter(self)
        self.grid_screenshots.installEventFilter(self)
        self._screenshots_grid_anchor_index = -1
        self._screenshots_grid_select_in_progress = False
        self._last_opened_screenshot_path = ""
        self._screenshot_live_paths = set()
        self._screenshots_scroll_active = False
        idle = QTimer(self.grid_screenshots)
        idle.setSingleShot(True)
        idle.setInterval(_SHOT_SCROLL_IDLE_MS)
        idle.timeout.connect(self._screenshots_on_scroll_idle)
        self._screenshots_viewport_timer = idle
        bar = self.grid_screenshots.verticalScrollBar()
        if bar is not None:
            bar.valueChanged.connect(self._on_screenshots_scroll)

        lay.addWidget(self.grid_screenshots)
        if hasattr(self, "library_stack"):
            self.library_stack.addWidget(self.screenshots_page)

    def _clear_screenshots_selection_visual(self) -> None:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return
        grid.blockSignals(True)
        grid.clearSelection()
        grid.setCurrentItem(None)
        grid.blockSignals(False)
        self._sync_screenshot_photo_visuals()

    def _attach_screenshot_photo(
        self,
        item: QListWidgetItem,
        path: str,
        thumb_path: str = "",
        *,
        title: str = "",
        mtime: float = 0.0,
        source: str = "steempeg",
        app_id: str = "",
    ) -> ScreenshotPhoto:
        label = (title or "").strip() or os.path.splitext(os.path.basename(path))[0]
        source_key = (source or "steempeg").strip().lower()
        source_label = "Steam" if source_key == "steam" else "Steempeg"
        subtitle = source_label
        if mtime:
            try:
                from datetime import datetime

                dt = to_display_datetime(datetime.fromtimestamp(float(mtime)))
                when = dt.strftime("%d %b %Y")
                subtitle = f"{source_label} · {when}"
            except (OSError, OverflowError, ValueError, TypeError):
                subtitle = source_label
        icon_path = ""
        resolved_id = self._screenshot_app_id_for_game_label(
            label, app_id=app_id, source=source_key
        )
        if resolved_id:
            icon_path = self._screenshot_icon_path_for_app_id(resolved_id)
        photo = ScreenshotPhoto(
            "",
            title=label,
            subtitle=subtitle,
            game_icon_path=icon_path,
            source=source_key,
            on_left_click=lambda ev, grid_item=item: self._screenshot_grid_select_item(
                grid_item, ev, force_single=True
            ),
            on_right_click=lambda ev, grid_item=item: self._handle_screenshot_photo_context_menu(
                grid_item, ev
            ),
            on_activate=lambda p=path: self._on_screenshot_open(p),
            on_drag_over=lambda gp: self._screenshot_paint_select_at(gp),
        )
        self.grid_screenshots.setItemWidget(item, photo)
        opened = os.path.normpath(path) == os.path.normpath(
            getattr(self, "_last_opened_screenshot_path", "") or ""
        )
        photo.set_opened(opened)
        if thumb_path:
            photo.set_thumbnail(thumb_path)
        elif item.data(_SHOT_THUMB_ROLE):
            photo.set_thumbnail(str(item.data(_SHOT_THUMB_ROLE)))
        key = self._screenshot_path_key(path)
        live = getattr(self, "_screenshot_live_paths", None)
        if not isinstance(live, set):
            live = set()
            self._screenshot_live_paths = live
        live.add(key)
        return photo

    def _dematerialize_screenshot_item(self, item: QListWidgetItem) -> None:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None or item is None:
            return
        photo = grid.itemWidget(item)
        if photo is None:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        grid.removeItemWidget(item)
        photo.deleteLater()
        # Keep UniformItemSizes / IconMode wrap on the photo cell, not a stale
        # widget footprint after removeItemWidget.
        item.setSizeHint(SCREENSHOT_PHOTO_SIZE)
        if path:
            live = getattr(self, "_screenshot_live_paths", None)
            if isinstance(live, set):
                live.discard(self._screenshot_path_key(path))

    def _materialize_screenshot_item(
        self, item: QListWidgetItem, *, load_thumb: bool = True
    ) -> ScreenshotPhoto | None:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None or item is None:
            return None
        existing = grid.itemWidget(item)
        if isinstance(existing, ScreenshotPhoto):
            return existing
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not path:
            return None
        try:
            mtime = float(item.data(_SHOT_MTIME_ROLE) or 0.0)
        except (TypeError, ValueError):
            mtime = 0.0
        game = str(item.data(_SHOT_GAME_ROLE) or "") or _parse_screenshot_game_name(path)
        source = str(item.data(_SHOT_SOURCE_ROLE) or "steempeg")
        app_id = str(item.data(_SHOT_APP_ID_ROLE) or "")
        game, app_id = self._enrich_steempeg_screenshot_identity(
            path, game, app_id, source=source
        )
        item.setData(_SHOT_GAME_ROLE, game)
        item.setData(_SHOT_APP_ID_ROLE, app_id)
        thumb = str(item.data(_SHOT_THUMB_ROLE) or "")
        item.setSizeHint(SCREENSHOT_PHOTO_SIZE)
        photo = self._attach_screenshot_photo(
            item,
            path,
            thumb,
            title=game,
            mtime=mtime,
            source=source,
            app_id=app_id,
        )
        if load_thumb and not thumb:
            self._queue_screenshot_thumb_for_item(item)
        return photo

    def _screenshot_path_key(self, path: str) -> str:
        return os.path.normcase(os.path.normpath(str(path or "")))

    def _schedule_screenshots_grid_reflow(self, delay_ms: int = 0) -> None:
        """Debounce IconMode wrap against the current viewport width."""
        timer = getattr(self, "_screenshots_reflow_timer", None)
        if timer is None:
            grid = getattr(self, "grid_screenshots", None)
            timer = QTimer(grid if grid is not None else self.ui)
            timer.setSingleShot(True)
            timer.timeout.connect(self._reflow_screenshots_grid)
            self._screenshots_reflow_timer = timer
        timer.start(max(0, int(delay_ms)))

    def _reflow_screenshots_grid(self) -> None:
        """Force Screenshots IconMode to re-wrap columns for the live width.

        After tab hide/show, splitter widen/narrow, clip-select chrome, or
        scrollbar policy settle, QListWidget Adjust can keep a stale wrap
        (empty right gap, or failing to grow 3→4 when the pane gets wider).
        """
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return
        if getattr(self, "_library_panel_mode", "") != "screenshots" and not grid.isVisible():
            return

        from steempeg.ui.library.library_styles import sync_screenshots_vertical_scrollbar

        # Reserve scrollbar gutter before measuring wrap width (AlwaysOn when needed).
        sync_screenshots_vertical_scrollbar(grid)

        vp_w = int(grid.viewport().width()) if grid.viewport() is not None else 0
        last_w = getattr(self, "_screenshots_last_reflow_w", None)
        # Same width + already laid out → skip doItemsLayout (huge on 8k shelves).
        if (
            last_w is not None
            and last_w == vp_w
            and vp_w > 0
            and grid.count() > 0
        ):
            if hasattr(self, "_schedule_screenshots_viewport_refresh"):
                self._schedule_screenshots_viewport_refresh(0)
            return

        bar = grid.verticalScrollBar()
        scroll_val = int(bar.value()) if bar is not None else 0

        spacing = max(0, int(grid.spacing()))
        # Explicit cell size + wrapping toggle invalidates Qt's IconMode cache
        # more reliably than spacing nudge alone when width *increases*.
        grid.setGridSize(QSize(SCREENSHOT_PHOTO_W + spacing, SCREENSHOT_PHOTO_H + spacing))
        grid.setWrapping(False)
        grid.setWrapping(True)
        grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        # Spacing nudge still helps after zero-delta geometry restore.
        grid.setSpacing(spacing + 1)
        grid.setSpacing(spacing)
        try:
            grid.doItemsLayout()
        except Exception:
            pass
        self._screenshots_last_reflow_w = vp_w

        # Column count may change overflow → keep AlwaysOn/Off in sync.
        sync_screenshots_vertical_scrollbar(grid)
        if bar is not None:
            bar.setValue(scroll_val)

        if hasattr(self, "_schedule_screenshots_viewport_refresh"):
            self._schedule_screenshots_viewport_refresh(0)

    def _rebuild_screenshot_path_index(self) -> None:
        index: dict[str, QListWidgetItem] = {}
        grid = getattr(self, "grid_screenshots", None)
        if grid is not None:
            for i in range(grid.count()):
                item = grid.item(i)
                if item is None:
                    continue
                path = item.data(Qt.ItemDataRole.UserRole) or ""
                if path:
                    index[self._screenshot_path_key(str(path))] = item
        self._screenshot_items_by_path = index

    def _on_screenshots_scroll(self, *_args) -> None:
        """While scrolling: pause thumb work; after idle: load visible tiles only."""
        self._screenshots_scroll_active = True
        # Don't flood decode work mid-fling.
        self._pending_cached_screenshot_thumbs = []
        self._screenshot_thumb_chunk_scheduled = False
        worker = getattr(self, "_screenshot_thumb_worker", None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
        timer = getattr(self, "_screenshots_viewport_timer", None)
        if timer is not None:
            timer.start()

    def _screenshots_on_scroll_idle(self) -> None:
        self._screenshots_scroll_active = False
        self._screenshots_refresh_viewport()

    def _schedule_screenshots_viewport_refresh(self, delay_ms: int = 0) -> None:
        timer = getattr(self, "_screenshots_viewport_timer", None)
        if timer is None:
            QTimer.singleShot(max(0, int(delay_ms)), self._screenshots_refresh_viewport)
            return
        if delay_ms <= 0:
            timer.start(1)
        else:
            timer.start(int(delay_ms))

    def _screenshots_visible_items(self) -> list[QListWidgetItem]:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return []
        vp = grid.viewport()
        if vp is None:
            return []
        area = vp.rect().adjusted(
            0, -_SHOT_VIEWPORT_OVERSCAN_PX, 0, _SHOT_VIEWPORT_OVERSCAN_PX
        )
        out: list[QListWidgetItem] = []
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None or item.isHidden():
                continue
            idx = grid.indexFromItem(item)
            if not idx.isValid():
                continue
            if area.intersects(grid.visualRect(idx)):
                out.append(item)
        return out

    def _screenshots_refresh_viewport(self) -> None:
        """Materialize visible (+overscan) tiles; drop far widgets; load their thumbs."""
        if getattr(self, "_screenshots_scroll_active", False):
            return
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return
        if getattr(self, "_library_panel_mode", "") != "screenshots":
            # Still allow refresh when restoring into an open tab; otherwise skip.
            if not grid.isVisible():
                return

        # IconMode needs a layout pass before visualRect is trustworthy.
        try:
            grid.doItemsLayout()
        except Exception:
            pass

        visible = self._screenshots_visible_items()
        keep_keys: set[str] = set()
        for item in visible:
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if path:
                keep_keys.add(self._screenshot_path_key(path))
            self._materialize_screenshot_item(item, load_thumb=False)

        # Dematerialize widgets outside the window (cap live QWidget count).
        live = getattr(self, "_screenshot_live_paths", None)
        if isinstance(live, set) and live:
            index = getattr(self, "_screenshot_items_by_path", None)
            if not isinstance(index, dict):
                self._rebuild_screenshot_path_index()
                index = getattr(self, "_screenshot_items_by_path", {}) or {}
            for key in list(live):
                if key in keep_keys:
                    continue
                item = index.get(key)
                if item is not None and not item.isSelected():
                    self._dematerialize_screenshot_item(item)

        # Soft cap: if somehow too many live, drop oldest non-visible.
        live = getattr(self, "_screenshot_live_paths", None)
        if isinstance(live, set) and len(live) > _SHOT_MAX_LIVE_WIDGETS:
            index = getattr(self, "_screenshot_items_by_path", {}) or {}
            for key in list(live):
                if len(live) <= _SHOT_MAX_LIVE_WIDGETS:
                    break
                if key in keep_keys:
                    continue
                item = index.get(key)
                if item is not None:
                    self._dematerialize_screenshot_item(item)

        self._sync_screenshot_photo_visuals()
        self._load_thumbs_for_visible_screenshots(visible)

    def _queue_screenshot_thumb_for_item(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not path:
            return
        existing = str(item.data(_SHOT_THUMB_ROLE) or "")
        if existing and os.path.isfile(existing):
            self._apply_screenshot_thumb(item, existing)
            return
        cache_dir = getattr(self, "cache_dir", None) or ""
        if not cache_dir:
            return
        try:
            mtime = float(item.data(_SHOT_MTIME_ROLE) or 0.0)
        except (TypeError, ValueError):
            mtime = 0.0
        candidate = screenshot_thumb_path_nostat(cache_dir, path, mtime)
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            item.setData(_SHOT_THUMB_ROLE, candidate)
            self._schedule_cached_screenshot_thumbs([(path, candidate)])
        else:
            pending_miss = getattr(self, "_viewport_thumb_missing", None)
            if not isinstance(pending_miss, list):
                pending_miss = []
                self._viewport_thumb_missing = pending_miss
            pending_miss.append((path, mtime))

    def _load_thumbs_for_visible_screenshots(
        self, items: list[QListWidgetItem] | None = None
    ) -> None:
        if getattr(self, "_screenshots_scroll_active", False):
            return
        if items is None:
            items = self._screenshots_visible_items()
        self._viewport_thumb_missing = []
        for item in items:
            self._queue_screenshot_thumb_for_item(item)
        missing = list(getattr(self, "_viewport_thumb_missing", None) or [])
        self._viewport_thumb_missing = []
        if missing:
            # Replace any full-shelf backfill with viewport-only work.
            self._schedule_screenshot_thumb_backfill(missing)

    def _schedule_cached_screenshot_thumbs(
        self, entries: list[tuple[str, str]]
    ) -> None:
        """Apply already-on-disk thumbs in small UI chunks (viewport paths only)."""
        if not entries or getattr(self, "_screenshots_scroll_active", False):
            return
        pending = getattr(self, "_pending_cached_screenshot_thumbs", None)
        if not isinstance(pending, list):
            pending = []
        pending.extend(entries)
        self._pending_cached_screenshot_thumbs = pending
        if getattr(self, "_screenshot_thumb_chunk_scheduled", False):
            return
        self._screenshot_thumb_chunk_scheduled = True
        QTimer.singleShot(16, self._apply_cached_screenshot_thumbs_chunk)

    def _apply_cached_screenshot_thumbs_chunk(self) -> None:
        if getattr(self, "_screenshots_scroll_active", False):
            self._pending_cached_screenshot_thumbs = []
            self._screenshot_thumb_chunk_scheduled = False
            return
        pending = getattr(self, "_pending_cached_screenshot_thumbs", None) or []
        if not pending:
            self._screenshot_thumb_chunk_scheduled = False
            return
        chunk = pending[:64]
        del pending[:64]
        self._pending_cached_screenshot_thumbs = pending
        for file_path, thumb_path in chunk:
            self._apply_screenshot_thumb_by_path(file_path, thumb_path)
        if pending:
            QTimer.singleShot(16, self._apply_cached_screenshot_thumbs_chunk)
        else:
            self._screenshot_thumb_chunk_scheduled = False

    def _apply_screenshot_thumb_by_path(self, file_path: str, thumb_path: str) -> None:
        if not file_path or not thumb_path:
            return
        index = getattr(self, "_screenshot_items_by_path", None)
        if not isinstance(index, dict):
            self._rebuild_screenshot_path_index()
            index = getattr(self, "_screenshot_items_by_path", {}) or {}
        item = index.get(self._screenshot_path_key(file_path))
        if item is not None:
            item.setData(_SHOT_THUMB_ROLE, thumb_path)
            self._apply_screenshot_thumb(item, thumb_path)

    def _invalidate_screenshot_game_lookup_memo(self) -> None:
        self._screenshot_game_to_app_id = {}
        self._invalidate_screenshot_norm_app_id_map()

    def _screenshot_app_id_for_game_name(self, game_name: str) -> str:
        """Best-effort app_id from games.json (Steempeg shots only store game name)."""
        app_id, _canonical = self._screenshot_identity_for_game_name(game_name)
        return app_id

    def _screenshot_app_id_for_game_label(
        self, game_name: str, *, app_id: str = "", source: str = "steempeg"
    ) -> str:
        """Resolve app_id from games.json, grid item data, or a Steam sibling."""
        aid = str(app_id or "").strip()
        label = str(game_name or "").strip()
        if aid:
            return aid
        if label:
            aid = self._screenshot_app_id_for_game_name(label)
            if aid:
                return aid
        norm = _normalize_screenshot_game_key(label)
        if not norm:
            return ""
        memo = getattr(self, "_screenshot_norm_to_app_id", None)
        if isinstance(memo, dict):
            cached = str(memo.get(norm) or "").strip()
            if cached:
                return cached
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return ""
        found = ""
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            row_name = str(item.data(_SHOT_GAME_ROLE) or "").strip()
            row_id = str(item.data(_SHOT_APP_ID_ROLE) or "").strip()
            if not row_id:
                continue
            row_norm = _normalize_screenshot_game_key(row_name)
            if row_norm and row_norm == norm:
                found = row_id
                break
        if found and isinstance(memo, dict):
            memo[norm] = found
        return found

    def _invalidate_screenshot_norm_app_id_map(self) -> None:
        self._screenshot_norm_to_app_id = {}

    def _collect_screenshot_games_catalog(self) -> dict[str, dict]:
        """Canonical game → {app_id, count, max_mtime, norm} from the live grid."""
        grid = getattr(self, "grid_screenshots", None)
        catalog: dict[str, dict] = {}
        if grid is None:
            return catalog
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            raw_name = str(item.data(_SHOT_GAME_ROLE) or "").strip() or "Unknown"
            source = str(item.data(_SHOT_SOURCE_ROLE) or "steempeg")
            app_id = str(item.data(_SHOT_APP_ID_ROLE) or "").strip()
            game, app_id = self._resolve_screenshot_row_identity(
                raw_name, app_id, source=source
            )
            if not app_id:
                app_id = self._screenshot_app_id_for_game_label(
                    game, app_id="", source=source
                )
            canon = (game or raw_name).strip() or "Unknown"
            try:
                mtime = float(item.data(_SHOT_MTIME_ROLE) or 0.0)
            except (TypeError, ValueError):
                mtime = 0.0
            norm = _normalize_screenshot_game_key(canon)
            rec = catalog.get(canon)
            if rec is None:
                rec = {"app_id": app_id, "count": 0, "max_mtime": 0.0, "norm": norm}
                catalog[canon] = rec
            rec["count"] = int(rec.get("count") or 0) + 1
            rec["max_mtime"] = max(float(rec.get("max_mtime") or 0.0), mtime)
            if app_id and not rec.get("app_id"):
                rec["app_id"] = app_id
        by_norm: dict[str, str] = {}
        for rec in catalog.values():
            aid = str(rec.get("app_id") or "").strip()
            norm = str(rec.get("norm") or "").strip()
            if aid and norm:
                by_norm.setdefault(norm, aid)
        for rec in catalog.values():
            if not rec.get("app_id"):
                norm = str(rec.get("norm") or "").strip()
                sibling = by_norm.get(norm, "")
                if sibling:
                    rec["app_id"] = sibling
        return catalog

    def _sort_screenshot_game_catalog_items(
        self, catalog: dict[str, dict]
    ) -> list[tuple[str, dict]]:
        idx = self._screenshots_global_sort_index()

        def name_key(row: tuple[str, dict]) -> str:
            return row[0].lower()

        def count_key(row: tuple[str, dict]) -> int:
            return int(row[1].get("count") or 0)

        def recent_key(row: tuple[str, dict]) -> float:
            return float(row[1].get("max_mtime") or 0.0)

        items = list(catalog.items())
        if idx == 1:
            items.sort(key=name_key)
        elif idx == 2:
            items.sort(key=name_key, reverse=True)
        elif idx == 7:
            items.sort(key=recent_key)
        elif idx == 8:
            items.sort(key=recent_key, reverse=True)
        else:
            items.sort(key=name_key)
        return items

    def _screenshot_identity_for_game_name(self, game_name: str) -> tuple[str, str]:
        """Return ``(app_id, canonical Steam name)`` for a filename/display label."""
        name = str(game_name or "").strip()
        if not name:
            return "", ""
        memo = getattr(self, "_screenshot_game_to_app_id", None)
        if not isinstance(memo, dict):
            memo = {}
            self._screenshot_game_to_app_id = memo
        key = name.casefold()
        cached = memo.get(key)
        if isinstance(cached, tuple) and len(cached) == 2:
            return str(cached[0] or ""), str(cached[1] or "")
        if isinstance(cached, str):
            # Older memo stored app_id only.
            aid = cached.strip()
            return aid, (self._screenshot_game_name_for_app_id(aid) if aid else "")
        cache = getattr(self, "game_names_cache", None) or {}
        found_id, found_name = match_screenshot_game_in_cache(name, cache)
        if not found_id and not cache:
            # games.json not loaded yet — don't cache a miss.
            return "", ""
        memo[key] = (found_id, found_name)
        return found_id, found_name

    def _resolve_screenshot_row_identity(
        self, game: str, app_id: str, *, source: str = "steempeg"
    ) -> tuple[str, str]:
        """Fill missing Steempeg app_id + prefer the games.json display name."""
        label = str(game or "").strip()
        aid = str(app_id or "").strip()
        source_key = (source or "steempeg").strip().lower()
        if source_key != "steam":
            if not aid and label:
                aid, canonical = self._screenshot_identity_for_game_name(label)
                if canonical and not self._is_screenshot_placeholder_name(
                    canonical, aid
                ):
                    label = canonical
            elif aid:
                canonical = self._screenshot_game_name_for_app_id(aid)
                if canonical and not self._is_screenshot_placeholder_name(
                    canonical, aid
                ):
                    # Filename sanitizer turns ``:`` into ``_`` — same game, nicer label.
                    # Generic ``Clip`` / ``Unknown`` also upgrade when we know app_id
                    # (sidecar or ``__clip_<appid>_…`` suffix).
                    if (
                        not label
                        or self._is_screenshot_placeholder_name(label, aid)
                        or _normalize_screenshot_game_key(label)
                        == _normalize_screenshot_game_key(canonical)
                    ):
                        label = canonical
        elif aid and (
            not label or self._is_screenshot_placeholder_name(label, aid)
        ):
            label = self._screenshot_game_name_for_app_id(aid)
        return label, aid

    def _enrich_steempeg_screenshot_identity(
        self,
        path: str,
        game: str,
        app_id: str,
        *,
        source: str = "steempeg",
    ) -> tuple[str, str]:
        """Merge sidecar / ``__clipfolder`` app_id, then games.json reverse-lookup."""
        source_key = (source or "steempeg").strip().lower()
        label = str(game or "").strip()
        aid = str(app_id or "").strip()
        if source_key != "steam" and path:
            try:
                from steempeg.core.screenshot_clip_link import (
                    collect_screenshot_clip_hint,
                )

                hint = collect_screenshot_clip_hint(
                    path, source=source_key, app_id=aid, game_name=label
                )
                if hint.app_id:
                    aid = str(hint.app_id).strip() or aid
                hint_game = str(hint.game_name or "").strip()
                if hint_game and (
                    not label
                    or label.casefold() in _GENERIC_SCREENSHOT_GAMES
                    or self._is_screenshot_placeholder_name(label, aid)
                ):
                    label = hint_game
            except Exception:
                logging.debug(
                    "Screenshot identity hint failed for %s", path, exc_info=True
                )
        return self._resolve_screenshot_row_identity(label, aid, source=source_key)

    def _backfill_steempeg_screenshot_identities(self) -> int:
        """Re-resolve Steempeg rows after games.json fills; update live cards."""
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return 0
        filters = getattr(self, "_screenshots_filter_games", None)
        touched = 0
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            source = str(item.data(_SHOT_SOURCE_ROLE) or "steempeg")
            if source.strip().lower() == "steam":
                continue
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            old_name = str(item.data(_SHOT_GAME_ROLE) or "").strip()
            old_id = str(item.data(_SHOT_APP_ID_ROLE) or "").strip()
            game, app_id = self._enrich_steempeg_screenshot_identity(
                path, old_name, old_id, source=source
            )
            if game == old_name and app_id == old_id:
                # Still try the logo if we already knew the app but the widget
                # was painted before cache/{appid}.jpg existed.
                resolved_id = app_id or self._screenshot_app_id_for_game_label(
                    old_name, app_id="", source=source
                )
                if resolved_id:
                    photo = grid.itemWidget(item)
                    if isinstance(photo, ScreenshotPhoto):
                        icon = self._screenshot_icon_path_for_app_id(resolved_id)
                        if icon:
                            photo.set_game_icon(icon)
                continue
            item.setData(_SHOT_GAME_ROLE, game)
            item.setData(_SHOT_APP_ID_ROLE, app_id)
            touched += 1
            if isinstance(filters, set) and old_name and old_name in filters:
                filters.discard(old_name)
                if game:
                    filters.add(game)
            photo = grid.itemWidget(item)
            if isinstance(photo, ScreenshotPhoto):
                if game:
                    photo.set_title(game)
                resolved_id = app_id or self._screenshot_app_id_for_game_label(
                    game, app_id="", source=source
                )
                if resolved_id:
                    icon = self._screenshot_icon_path_for_app_id(resolved_id)
                    if icon:
                        photo.set_game_icon(icon)
        if touched:
            self._apply_screenshots_filters(refresh_viewport=False)
            menu = getattr(self, "screenshots_filter_menu", None)
            if (
                menu is not None
                and menu.isVisible()
                and hasattr(menu, "gather_statistics")
            ):
                menu.gather_statistics(self)
        return touched

    def _screenshot_game_name_for_app_id(self, app_id: str) -> str:
        """Resolve display name: games.json → local appmanifest → ``App {id}``.

        No network on the UI thread — Steam API backfill runs async after scan.
        """
        from steempeg.core import games as games_mod

        aid = str(app_id or "").strip()
        if not aid:
            return "Unknown"
        cache = getattr(self, "game_names_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self.game_names_cache = cache
        name = cache.get(aid)
        if name and not games_mod.is_unresolved_game_name(name, aid):
            return str(name).strip()
        local = games_mod.find_local_steam_game_name(aid)
        if local:
            cache[aid] = local
            # Persist later with scan/backfill finish — avoid write storms while painting.
            return local
        return f"App {aid}"

    def _screenshot_icon_path_for_app_id(self, app_id: str) -> str:
        """Local game logo path only (cache jpg or Steam librarycache). No download."""
        aid = str(app_id or "").strip()
        if not aid:
            return ""
        memo = getattr(self, "_screenshot_icon_path_memo", None)
        if not isinstance(memo, dict):
            memo = {}
            self._screenshot_icon_path_memo = memo
        if aid in memo:
            return memo[aid]

        cache_dir = getattr(self, "cache_dir", None) or ""
        if cache_dir:
            cache_icon = os.path.join(cache_dir, f"{aid}.jpg")
            if os.path.isfile(cache_icon) and os.path.getsize(cache_icon) > 100:
                memo[aid] = cache_icon
                return cache_icon

        try:
            from steempeg.core import games as games_mod

            local = games_mod.find_local_steam_icon(aid)
        except Exception:
            local = None
        if local and os.path.isfile(local):
            if cache_dir:
                dest = os.path.join(cache_dir, f"{aid}.jpg")
                try:
                    if not os.path.isfile(dest) or os.path.getsize(dest) <= 100:
                        import shutil

                        shutil.copy2(local, dest)
                    if os.path.isfile(dest) and os.path.getsize(dest) > 100:
                        memo[aid] = dest
                        return dest
                except OSError:
                    pass
            memo[aid] = local
            return local

        memo[aid] = ""
        return ""

    def _is_screenshot_placeholder_name(self, name: str, app_id: str = "") -> bool:
        from steempeg.core import games as games_mod

        text = str(name or "").strip()
        if text.casefold() in _GENERIC_SCREENSHOT_GAMES:
            return True
        return games_mod.is_unresolved_game_name(name, app_id)

    def _collect_steempeg_screenshot_rows(self, folder: str) -> list[dict]:
        rows: list[dict] = []
        if not folder or not os.path.isdir(folder):
            return rows
        try:
            names = os.listdir(folder)
        except OSError as exc:
            logging.warning("Screenshots scan failed for %s: %s", folder, exc)
            return rows
        for name in names:
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in _SCREENSHOT_EXTS:
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0.0
            game = _parse_screenshot_game_name(path)
            game, app_id = self._enrich_steempeg_screenshot_identity(
                path, game, "", source="steempeg"
            )
            rows.append(
                {
                    "full_path": os.path.normpath(path),
                    "mtime": float(mtime),
                    "game_name": game,
                    "source": "steempeg",
                    "app_id": app_id,
                }
            )
        return rows

    def _collect_steam_screenshot_rows(self) -> list[dict]:
        """Deprecated sync helper — prefer ``_start_steam_screenshots_scan``."""
        # Kept for rare debug call sites; do not use on the UI startup path.
        rows: list[dict] = []
        try:
            from steempeg.core.steam_screenshots import iter_steam_library_screenshots

            entries = iter_steam_library_screenshots()
        except Exception as exc:
            logging.warning("Steam screenshots scan failed: %s", exc)
            return rows
        return self._steam_entries_to_rows(entries)

    def _sync_screenshot_photo_visuals(self) -> None:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return
        selected = grid.selectedItems()
        opened_norm = os.path.normpath(getattr(self, "_last_opened_screenshot_path", "") or "")
        # Only live (materialized) tiles — placeholders have no widget.
        live = getattr(self, "_screenshot_live_paths", None)
        index = getattr(self, "_screenshot_items_by_path", None)
        if isinstance(live, set) and isinstance(index, dict) and live:
            items_iter = (index.get(k) for k in live)
        else:
            items_iter = (grid.item(i) for i in range(grid.count()))
        for item in items_iter:
            if item is None:
                continue
            photo = grid.itemWidget(item)
            if not isinstance(photo, ScreenshotPhoto):
                continue
            photo.set_selected(item in selected)
            path = item.data(Qt.ItemDataRole.UserRole) or ""
            photo.set_opened(bool(path) and os.path.normpath(str(path)) == opened_norm)

    def _on_screenshots_grid_selection_changed(self) -> None:
        if getattr(self, "_screenshots_grid_select_in_progress", False):
            return
        self._sync_screenshot_photo_visuals()
        self._update_library_count_label()

    def _screenshot_paint_select_at(self, global_pos: QPoint) -> None:
        """Add-select the card under the cursor (paint / rubber-band style)."""
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return
        vp = grid.viewport()
        if vp is None:
            return
        local = vp.mapFromGlobal(global_pos)
        if not vp.rect().contains(local):
            return
        item = grid.itemAt(local)
        if item is None or item.isHidden():
            return
        if grid.itemWidget(item) is None and hasattr(self, "_materialize_screenshot_item"):
            self._materialize_screenshot_item(item)
        if item.isSelected():
            # Still refresh chrome if we just materialized a selected placeholder.
            photo = grid.itemWidget(item)
            if isinstance(photo, ScreenshotPhoto):
                photo.set_selected(True)
            return

        self._screenshots_grid_select_in_progress = True
        try:
            grid.blockSignals(True)
            item.setSelected(True)
            grid.blockSignals(False)
        finally:
            self._screenshots_grid_select_in_progress = False

        photo = grid.itemWidget(item)
        if isinstance(photo, ScreenshotPhoto):
            photo.set_selected(True)
        self._update_library_count_label()

    def _screenshot_grid_select_item(
        self, item, event=None, *, force_single: bool = False
    ) -> None:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None or item is None:
            return
        mods = (
            self._event_modifiers(event)
            if hasattr(self, "_event_modifiers")
            else Qt.KeyboardModifier.NoModifier
        )
        if force_single:
            mods = Qt.KeyboardModifier.NoModifier

        multi_mods = getattr(
            self,
            "_MULTI_SELECT_MODIFIERS",
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier
            | Qt.KeyboardModifier.AltModifier,
        )
        toggle_mods = getattr(
            self,
            "_TOGGLE_SELECT_MODIFIERS",
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
        )
        idx = (
            self._list_widget_item_index(grid, item)
            if hasattr(self, "_list_widget_item_index")
            else grid.row(item)
        )

        self._screenshots_grid_select_in_progress = True
        try:
            grid.blockSignals(True)
            if mods & toggle_mods:
                item.setSelected(not item.isSelected())
            elif mods & Qt.KeyboardModifier.ShiftModifier:
                anchor_idx = getattr(self, "_screenshots_grid_anchor_index", -1)
                if anchor_idx < 0:
                    anchor_idx = idx
                lo, hi = sorted((anchor_idx, idx))
                grid.clearSelection()
                for i in range(lo, hi + 1):
                    row_item = grid.item(i)
                    if row_item and not row_item.isHidden():
                        row_item.setSelected(True)
            else:
                grid.clearSelection()
                item.setSelected(True)

            if not (mods & multi_mods):
                self._screenshots_grid_anchor_index = idx

            grid.blockSignals(False)
        finally:
            self._screenshots_grid_select_in_progress = False

        self._sync_screenshot_photo_visuals()
        self._update_library_count_label()

    def _handle_screenshot_photo_context_menu(self, item, event) -> None:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None or item is None:
            return
        viewport_pos = grid.viewport().mapFromGlobal(event.globalPosition().toPoint())
        self.show_screenshots_grid_context_menu(viewport_pos)

    def _context_menu_screenshot_paths(self, pos) -> list[str]:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return []
        hit = grid.itemAt(pos)
        selected = list(grid.selectedItems())
        if hit is not None and hit in selected and len(selected) > 1:
            items = selected
        elif hit is not None:
            items = [hit]
        else:
            items = selected
        paths: list[str] = []
        seen: set[str] = set()
        for item in items:
            path = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not path:
                continue
            norm = os.path.normpath(str(path))
            if norm in seen or not os.path.isfile(str(path)):
                continue
            seen.add(norm)
            paths.append(str(path))
        return paths

    def show_screenshots_grid_context_menu(self, pos) -> None:
        paths = self._context_menu_screenshot_paths(pos)
        if not paths:
            return
        from steempeg.ui import ui_theme as ut

        menu = QMenu(self.grid_screenshots)
        menu.setStyleSheet(ut.library_menu_stylesheet())
        action_open = menu.addAction("📂 Open")
        action_folder = menu.addAction("📁 Open folder")
        action_related = menu.addAction("🎬 Open related clip")
        if len(paths) == 1:
            path = paths[0]
            action_open.triggered.connect(
                lambda _checked=False, p=path: self._on_screenshot_open(p)
            )
            action_folder.triggered.connect(
                lambda _checked=False, p=path: self._on_screenshot_open_folder(p)
            )
            action_related.setEnabled(self._screenshot_related_clip_action_enabled(path))
            action_related.triggered.connect(
                lambda _checked=False, p=path: self._on_screenshot_open_related_clip(p)
            )
        else:
            action_open.setEnabled(False)
            action_folder.setEnabled(False)
            action_related.setEnabled(False)
        menu.exec(self.grid_screenshots.viewport().mapToGlobal(pos))

    def _library_clip_refs_for_screenshot_link(self) -> list:
        """Clips Manager rows as ``LibraryClipRef`` for screenshot → clip matching."""
        from steempeg.core.rendered_media import parse_app_id_from_clip_folder
        from steempeg.core.screenshot_clip_link import LibraryClipRef

        refs: list[LibraryClipRef] = []
        table = getattr(getattr(self, "ui", None), "table_clips", None)
        if table is None:
            return refs
        for row in range(table.rowCount()):
            cell = table.item(row, 0)
            if cell is None:
                continue
            path = cell.data(Qt.ItemDataRole.UserRole)
            if not path:
                continue
            path_s = os.path.normpath(str(path))
            app_id = parse_app_id_from_clip_folder(os.path.basename(path_s)) or ""
            game_name = (cell.text() or "").strip()
            duration_sec = None
            dur_item = table.item(row, 3)
            if dur_item is not None:
                from steempeg.core.screenshot_clip_link import parse_library_duration_sec

                duration_sec = parse_library_duration_sec(dur_item.text())
            refs.append(
                LibraryClipRef(
                    path=path_s,
                    app_id=str(app_id or ""),
                    duration_sec=duration_sec,
                    game_name=game_name,
                )
            )
        return refs

    def _screenshot_item_for_path(self, path: str):
        grid = getattr(self, "grid_screenshots", None)
        if grid is None or not path:
            return None
        index = getattr(self, "_screenshot_items_by_path", None)
        if isinstance(index, dict):
            key = self._screenshot_path_key(path)
            hit = index.get(key)
            if hit is not None:
                return hit
        want = os.path.normcase(os.path.normpath(path))
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            row_path = item.data(Qt.ItemDataRole.UserRole) or ""
            if os.path.normcase(os.path.normpath(str(row_path))) == want:
                return item
        return None

    def _screenshot_related_clip_action_enabled(self, path: str) -> bool:
        from steempeg.core.screenshot_clip_link import (
            collect_screenshot_clip_hint,
            hint_suggests_related_clip,
        )

        item = self._screenshot_item_for_path(path)
        source = ""
        app_id = ""
        game = ""
        if item is not None:
            source = str(item.data(_SHOT_SOURCE_ROLE) or "")
            app_id = str(item.data(_SHOT_APP_ID_ROLE) or "")
            game = str(item.data(_SHOT_GAME_ROLE) or "")
        hint = collect_screenshot_clip_hint(
            path, source=source, app_id=app_id, game_name=game
        )
        return hint_suggests_related_clip(hint)

    def _open_related_clip_from_screenshot(
        self,
        clip_path: str,
        screenshot_path: str,
        *,
        source: str = "",
        app_id: str = "",
        game_name: str = "",
        hint=None,
    ) -> bool:
        """Open a library clip and seek to the screenshot's capture time when known."""
        from steempeg.core.screenshot_clip_link import related_clip_seek_offset_sec

        clip_dur = None
        if hasattr(self, "current_clip_duration_sec"):
            try:
                cand = float(getattr(self, "current_clip_duration_sec", 0) or 0)
                if (
                    cand > 0
                    and hasattr(self, "_is_clip_actively_previewing")
                    and self._is_clip_actively_previewing(clip_path)
                ):
                    clip_dur = cand
            except (TypeError, ValueError):
                clip_dur = None
        if clip_dur is None:
            # Library duration cell — avoid probing MPD on the UI thread.
            table = getattr(getattr(self, "ui", None), "table_clips", None)
            if table is not None:
                from steempeg.core.screenshot_clip_link import parse_library_duration_sec

                want = os.path.normcase(os.path.normpath(clip_path))
                for row in range(table.rowCount()):
                    cell = table.item(row, 0)
                    if cell is None:
                        continue
                    row_path = cell.data(Qt.ItemDataRole.UserRole)
                    if not row_path:
                        continue
                    if os.path.normcase(os.path.normpath(str(row_path))) != want:
                        continue
                    dur_item = table.item(row, 3)
                    if dur_item is not None:
                        clip_dur = parse_library_duration_sec(dur_item.text())
                    break

        seek_sec = related_clip_seek_offset_sec(
            screenshot_path,
            clip_path,
            source=source,
            app_id=app_id,
            game_name=game_name,
            hint=hint,
            clip_duration_sec=clip_dur,
        )
        from steempeg.core.steam_screenshots import clip_media_start_local

        media_start = clip_media_start_local(clip_path)
        shot_s = "—"
        if hint is not None and getattr(hint, "steam_shot_local", None) is not None:
            shot_s = hint.steam_shot_local.isoformat(sep=" ", timespec="seconds")
        logging.info(
            "Open related clip %s ← %s media_start=%s shot_time=%s seek_sec=%s "
            "(library_dur=%s timeline=%s tt_ms=%s)",
            os.path.basename(clip_path),
            os.path.basename(screenshot_path),
            media_start.isoformat(sep=" ", timespec="seconds") if media_start else "—",
            shot_s,
            f"{seek_sec:.2f}" if seek_sec is not None else "None",
            f"{clip_dur:.2f}" if clip_dur is not None else "None",
            getattr(hint, "steam_timeline_id", "") or "—",
            getattr(hint, "steam_timeline_time_ms", None),
        )
        return self.open_source_clip(clip_path, play=True, seek_sec=seek_sec)

    def _on_screenshot_open_related_clip(self, path: str) -> None:
        """Resolve screenshot → clip, switch to Clips, load preview at capture time."""
        from steempeg.core.screenshot_clip_link import (
            collect_screenshot_clip_hint,
            resolve_related_clip_paths,
        )
        from steempeg.ui.message_dialog import steempeg_information

        if not path or not os.path.isfile(path):
            return
        item = self._screenshot_item_for_path(path)
        source = str(item.data(_SHOT_SOURCE_ROLE) or "") if item else ""
        app_id = str(item.data(_SHOT_APP_ID_ROLE) or "") if item else ""
        game = str(item.data(_SHOT_GAME_ROLE) or "") if item else ""
        hint = collect_screenshot_clip_hint(
            path, source=source, app_id=app_id, game_name=game
        )
        # Sidecar / known folder: skip building LibraryClipRef for every table row.
        if hint.clip_path and self._is_valid_clip_path(hint.clip_path):
            self._open_related_clip_from_screenshot(
                hint.clip_path,
                path,
                source=source,
                app_id=app_id,
                game_name=game,
                hint=hint,
            )
            return
        if hint.clip_folder:
            by_name = ""
            table = getattr(getattr(self, "ui", None), "table_clips", None)
            want = hint.clip_folder.strip().casefold()
            if table is not None and want:
                for row in range(table.rowCount()):
                    cell = table.item(row, 0)
                    if cell is None:
                        continue
                    row_path = cell.data(Qt.ItemDataRole.UserRole)
                    if not row_path:
                        continue
                    if os.path.basename(str(row_path)).casefold() == want:
                        by_name = os.path.normpath(str(row_path))
                        break
            if by_name and self._is_valid_clip_path(by_name):
                self._open_related_clip_from_screenshot(
                    by_name,
                    path,
                    source=source,
                    app_id=app_id,
                    game_name=game,
                    hint=hint,
                )
                return

        matches = resolve_related_clip_paths(
            path,
            self._library_clip_refs_for_screenshot_link(),
            source=source,
            app_id=app_id,
            game_name=game,
        )
        # Prefer library-valid folders; drop missing paths.
        matches = [p for p in matches if self._is_valid_clip_path(p)]
        if not matches:
            steempeg_information(
                self.ui,
                "Related clip",
                "No related clip was found for this screenshot.\n\n"
                "Steempeg shots need a clip link (new captures store it) or a "
                "single matching game in Clips Manager. Steam shots match only "
                "when a library clip's media window actually contains that "
                "moment (Steam may still have the shot on a timeline that was "
                "never saved as a clip).",
            )
            return
        if len(matches) == 1:
            self._open_related_clip_from_screenshot(
                matches[0],
                path,
                source=source,
                app_id=app_id,
                game_name=game,
                hint=hint,
            )
            return

        # Ambiguous: let Emily pick (same pattern as multi Steam screenshot files).
        from PySide6.QtGui import QCursor
        from steempeg.ui import ui_theme as ut

        pick = QMenu(self.ui)
        pick.setStyleSheet(ut.library_menu_stylesheet())
        for clip_path in matches:
            label = os.path.basename(clip_path)
            action = pick.addAction(f"🎮  {label}")
            action.triggered.connect(
                lambda _checked=False, p=clip_path: self._open_related_clip_from_screenshot(
                    p, path, source=source, app_id=app_id, game_name=game, hint=hint
                )
            )
        pick.exec(QCursor.pos())

    def _on_screenshot_open(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            return
        self._last_opened_screenshot_path = os.path.normpath(path)
        self._sync_screenshot_photo_visuals()
        if hasattr(self, "_open_file_with_default_app"):
            self._open_file_with_default_app(path)
        else:
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception as exc:
                logging.warning("Could not open screenshot %s: %s", path, exc)

    def _on_screenshot_open_folder(self, path: str) -> None:
        from steempeg.infra.paths import reveal_in_file_manager

        try:
            reveal_in_file_manager(path)
        except Exception as exc:
            logging.warning("Could not reveal screenshot %s: %s", path, exc)

    def choose_records_folder(self) -> None:
        """Change the export / Records folder from the Rendered tab footer."""
        old = os.path.normpath(getattr(self, "custom_destination", "") or "")
        if hasattr(self, "choose_destination"):
            self.choose_destination()
        new = os.path.normpath(getattr(self, "custom_destination", "") or "")
        if new and old and new != old:
            # Full migrate UX is v44/45 — ask but keep it soft for now.
            try:
                move = steempeg_question(
                    self.ui,
                    "Move existing exports?",
                    "Records folder changed.\n\n"
                    "Move existing rendered files into the new folder?\n\n"
                    "Yes = remember for later (migrate not built yet).\n"
                    "No = just change the path; files stay where they are.",
                )
                if move:
                    steempeg_information(
                        self.ui,
                        "Move exports",
                        "File move isn’t in this spike yet — path is updated. "
                        "Migrate lands with the v44/45 library chrome overhaul.",
                    )
            except Exception:
                pass
        if hasattr(self, "refresh_rendered_library"):
            self.refresh_rendered_library()
        self._sync_library_footer_for_mode()

    def choose_screenshots_folder(self) -> None:
        """Pick the folder used for Steempeg screenshots (Settings key)."""
        from PySide6.QtWidgets import QFileDialog
        from steempeg.ui.settings_prefs import (
            KEY_SCREENSHOTS_FOLDER,
            normalize_screenshots_folder,
            resolve_screenshots_folder,
        )

        settings = {}
        if hasattr(self, "load_user_settings"):
            settings = self.load_user_settings() or {}
        start = resolve_screenshots_folder(settings)
        folder = QFileDialog.getExistingDirectory(
            self.ui, "Select Screenshots Folder", start
        )
        if not folder:
            return
        folder = normalize_screenshots_folder(folder)
        if hasattr(self, "save_user_settings"):
            self.save_user_settings(KEY_SCREENSHOTS_FOLDER, folder)
        self.screenshots_dir = folder
        self.refresh_screenshots_library(force=True)
        self._sync_library_footer_for_mode()

    def refresh_screenshots_library(self, *, force: bool = True) -> None:
        """Rescan Screenshots: Steempeg folder now, Steam userdata in background.

        Never walks Steam on the UI thread — that blocked launch for 8k+ shots.
        Grid gets light placeholders; ``ScreenshotPhoto`` + thumbs only for the
        visible viewport (scroll-driven).
        """
        self._ensure_screenshots_widgets()
        folder = self._screenshots_folder_path()
        if not force and getattr(self, "_screenshots_scanned_folder", None) == folder:
            if self.grid_screenshots.count() > 0:
                # Tab flip only — filters already applied; re-walking 8k rows to
                # setHidden is pure UI lag.
                self._update_library_count_label()
                self._schedule_screenshots_viewport_refresh(50)
                return

        self._stop_steam_screenshots_scan()
        self._stop_screenshot_thumb_backfill()
        self._stop_screenshot_game_name_backfill()
        self._invalidate_screenshot_norm_app_id_map()
        self._pending_cached_screenshot_thumbs = []
        self._screenshot_thumb_chunk_scheduled = False
        self._screenshot_live_paths = set()
        self._screenshots_viewport_primed = False
        self.grid_screenshots.clear()
        self._screenshot_items_by_path = {}
        self._screenshot_seen_paths = set()
        self._screenshots_last_reflow_w = None

        steempeg_rows = self._collect_steempeg_screenshot_rows(folder)
        steempeg_rows.sort(key=lambda t: float(t.get("mtime") or 0.0), reverse=True)
        self._paint_screenshot_rows(steempeg_rows, rebuild_index=True)

        self._screenshots_scanned_folder = folder
        if not hasattr(self, "_sort_applied_by_panel"):
            self._sort_applied_by_panel = {}
        if hasattr(self, "combo_sort"):
            self._sort_applied_by_panel["screenshots"] = self._screenshots_global_sort_index()
        if self._screenshots_global_sort_index() != 0:
            self.apply_screenshots_sorting()
        self._apply_screenshots_filters(refresh_viewport=False)
        self._update_library_count_label()
        n_local = len(steempeg_rows)
        if hasattr(self, "set_status"):
            self.set_status(
                f"Screenshots: {n_local} Steempeg · scanning Steam…"
            )
        if steempeg_rows:
            self._screenshots_viewport_primed = True
            self._schedule_screenshots_viewport_refresh(0)
            self._schedule_screenshots_grid_reflow(0)
        else:
            self._screenshots_viewport_primed = False
        self._start_steam_screenshots_scan()

    def _paint_screenshot_rows(
        self, rows: list[dict], *, rebuild_index: bool = False
    ) -> None:
        """Append light QListWidget placeholders (no ScreenshotPhoto / QPixmap)."""
        grid = getattr(self, "grid_screenshots", None)
        if grid is None or not rows:
            if rebuild_index:
                self._rebuild_screenshot_path_index()
            return
        seen = getattr(self, "_screenshot_seen_paths", None)
        if not isinstance(seen, set):
            seen = set()
            self._screenshot_seen_paths = seen
        index = getattr(self, "_screenshot_items_by_path", None)
        if not isinstance(index, dict):
            index = {}
            self._screenshot_items_by_path = index

        grid.setUpdatesEnabled(False)
        try:
            for row in rows:
                path = str(row.get("full_path") or "")
                if not path:
                    continue
                key = self._screenshot_path_key(path)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    mtime = float(row.get("mtime") or 0.0)
                except (TypeError, ValueError):
                    mtime = 0.0
                game = str(row.get("game_name") or "") or _parse_screenshot_game_name(path)
                source = str(row.get("source") or "steempeg")
                app_id = str(row.get("app_id") or "")
                game, app_id = self._enrich_steempeg_screenshot_identity(
                    path, game, app_id, source=source
                )
                item = self._make_screenshot_item(
                    path, mtime, game, source=source, app_id=app_id
                )
                grid.addItem(item)
                index[key] = item
        finally:
            grid.setUpdatesEnabled(True)
        if rebuild_index:
            self._rebuild_screenshot_path_index()

    def _stop_steam_screenshots_scan(self) -> None:
        worker = getattr(self, "_steam_screenshots_worker", None)
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(2000)
        self._steam_screenshots_worker = None
        self._pending_steam_screenshot_rows = []
        self._steam_screenshot_chunk_scheduled = False

    def _start_steam_screenshots_scan(self) -> None:
        self._stop_steam_screenshots_scan()
        from steempeg.ui.library.steam_screenshots_scan import SteamScreenshotsScanWorker

        worker = SteamScreenshotsScanWorker(
            game_names_cache=getattr(self, "game_names_cache", None) or {},
            parent=getattr(self, "ui", None),
        )
        self._steam_screenshots_worker = worker
        worker.batch_ready.connect(self._on_steam_screenshots_batch)
        worker.scan_failed.connect(self._on_steam_screenshots_scan_failed)
        worker.finished_ok.connect(self._on_steam_screenshots_scan_finished)
        worker.start()

    def _steam_entries_to_rows(self, entries: list[dict]) -> list[dict]:
        rows: list[dict] = []
        for entry in entries:
            path = str(entry.get("path") or entry.get("full_path") or "")
            if not path:
                continue
            app_id = str(entry.get("app_id") or "")
            raw_game = str(entry.get("game_name") or "").strip()
            if app_id and (
                not raw_game or self._is_screenshot_placeholder_name(raw_game, app_id)
            ):
                game = self._screenshot_game_name_for_app_id(app_id)
            else:
                game = raw_game or (
                    self._screenshot_game_name_for_app_id(app_id) if app_id else "Unknown"
                )
            try:
                mtime = float(entry.get("mtime") or 0.0)
            except (TypeError, ValueError):
                mtime = 0.0
            rows.append(
                {
                    "full_path": os.path.normpath(path),
                    "mtime": mtime,
                    "game_name": game,
                    "source": "steam",
                    "app_id": app_id,
                }
            )
        return rows

    def _on_steam_screenshots_batch(self, entries: list) -> None:
        if not isinstance(entries, list) or not entries:
            return
        rows = self._steam_entries_to_rows(entries)
        pending = getattr(self, "_pending_steam_screenshot_rows", None)
        if not isinstance(pending, list):
            pending = []
            self._pending_steam_screenshot_rows = pending
        pending.extend(rows)
        if not getattr(self, "_steam_screenshot_chunk_scheduled", False):
            self._steam_screenshot_chunk_scheduled = True
            QTimer.singleShot(16, self._flush_steam_screenshot_chunk)

    def _flush_steam_screenshot_chunk(self) -> None:
        pending = getattr(self, "_pending_steam_screenshot_rows", None) or []
        if not pending:
            self._steam_screenshot_chunk_scheduled = False
            # Cache-restore path (no live worker): persist once Steam cards are in.
            if getattr(self, "_steam_screenshots_worker", None) is None:
                QTimer.singleShot(0, lambda: self._finish_steam_screenshots_merge(0))
            return
        chunk = pending[:120]
        del pending[:120]
        self._pending_steam_screenshot_rows = pending
        self._paint_screenshot_rows(chunk, rebuild_index=False)
        # Don't refresh_viewport here — that would reset the idle timer every batch
        # and starve visible tiles until all 8k placeholders land.
        self._apply_screenshots_filters(refresh_viewport=False)
        self._update_library_count_label()
        if getattr(self, "_library_panel_mode", "") == "screenshots" and hasattr(
            self, "set_status"
        ):
            n = self.grid_screenshots.count() if self.grid_screenshots is not None else 0
            self.set_status(f"Screenshots: {n} · loading Steam…")
        # First batch: fill what the user can already see. Later batches only
        # extend the scroll range (placeholders); no rematerialize storm.
        if not getattr(self, "_screenshots_viewport_primed", False):
            self._screenshots_viewport_primed = True
            self._schedule_screenshots_viewport_refresh(0)
        if pending:
            QTimer.singleShot(16, self._flush_steam_screenshot_chunk)
        else:
            self._steam_screenshot_chunk_scheduled = False
            if getattr(self, "_steam_screenshots_worker", None) is None:
                QTimer.singleShot(0, lambda: self._finish_steam_screenshots_merge(0))
            else:
                self._schedule_screenshots_viewport_refresh(50)

    def _on_steam_screenshots_scan_failed(self, message: str) -> None:
        logging.warning("Steam screenshots scan failed: %s", message)
        if hasattr(self, "set_status"):
            n = self.grid_screenshots.count() if getattr(self, "grid_screenshots", None) else 0
            self.set_status(f"Screenshots: {n} (Steam scan failed)")

    def _on_steam_screenshots_scan_finished(self, total: int) -> None:
        worker = getattr(self, "_steam_screenshots_worker", None)
        if worker is not None:
            try:
                cache_changed = False
                for app_id, name in (worker.game_names_cache or {}).items():
                    aid = str(app_id)
                    if not aid or not name:
                        continue
                    if self._is_screenshot_placeholder_name(str(name), aid):
                        continue
                    cache = getattr(self, "game_names_cache", None)
                    if not isinstance(cache, dict):
                        cache = {}
                        self.game_names_cache = cache
                    if cache.get(aid) != name:
                        cache[aid] = str(name)
                        cache_changed = True
                if cache_changed:
                    self._invalidate_screenshot_game_lookup_memo()
                if hasattr(self, "save_json_cache"):
                    try:
                        self.save_json_cache()
                    except Exception:
                        pass
            except Exception:
                logging.debug("Steam screenshot name merge failed", exc_info=True)
        self._steam_screenshots_worker = None
        # Let in-flight UI chunks drain, then persist + final status.
        QTimer.singleShot(50, lambda n=int(total or 0): self._finish_steam_screenshots_merge(n))

    def _finish_steam_screenshots_merge(self, steam_total: int) -> None:
        if getattr(self, "_steam_screenshot_chunk_scheduled", False) or (
            getattr(self, "_pending_steam_screenshot_rows", None) or []
        ):
            QTimer.singleShot(
                50, lambda n=steam_total: self._finish_steam_screenshots_merge(n)
            )
            return
        if getattr(self, "_steam_screenshots_finish_busy", False):
            return
        self._steam_screenshots_finish_busy = True
        try:
            self._rebuild_screenshot_path_index()
            self._backfill_steempeg_screenshot_identities()
            folder = self._screenshots_folder_path()
            self._screenshots_scanned_folder = folder
            snapshot = self._collect_screenshot_grid_snapshot()
            self._persist_screenshots_library_snapshot(folder, snapshot)
            steem_n = sum(
                1
                for row in snapshot
                if str(row.get("source") or "").lower() != "steam"
            )
            steam_n = len(snapshot) - steem_n
            if hasattr(self, "set_status"):
                self.set_status(
                    f"Screenshots: {len(snapshot)} file"
                    f"{'s' if len(snapshot) != 1 else ''}"
                    f" ({steem_n} Steempeg · {steam_n} Steam)"
                )
            logging.info(
                "Screenshots refresh done: total=%d steempeg=%d steam_emitted=%d",
                len(snapshot),
                steem_n,
                steam_total,
            )
            self._schedule_screenshots_viewport_refresh(50)
            self._schedule_screenshots_grid_reflow(50)
            self._schedule_screenshot_game_name_backfill()
            if self._screenshots_global_sort_index() != 0:
                self.apply_screenshots_sorting()
        finally:
            self._steam_screenshots_finish_busy = False

    def _collect_screenshot_grid_snapshot(self) -> list[dict]:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return []
        out: list[dict] = []
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not path:
                continue
            try:
                mtime = float(item.data(_SHOT_MTIME_ROLE) or 0.0)
            except (TypeError, ValueError):
                mtime = 0.0
            out.append(
                {
                    "full_path": path,
                    "mtime": mtime,
                    "game_name": str(item.data(_SHOT_GAME_ROLE) or ""),
                    "source": str(item.data(_SHOT_SOURCE_ROLE) or "steempeg"),
                    "app_id": str(item.data(_SHOT_APP_ID_ROLE) or ""),
                }
            )
        return out

    def _make_screenshot_item(
        self,
        path: str,
        mtime: float,
        game: str,
        *,
        source: str = "steempeg",
        app_id: str = "",
    ) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(_SHOT_MTIME_ROLE, float(mtime))
        item.setData(_SHOT_GAME_ROLE, game)
        item.setData(_SHOT_SOURCE_ROLE, (source or "steempeg").strip().lower() or "steempeg")
        item.setData(_SHOT_APP_ID_ROLE, str(app_id or ""))
        item.setToolTip(path)
        item.setSizeHint(SCREENSHOT_PHOTO_SIZE)
        return item

    def _apply_screenshot_thumb(self, item: QListWidgetItem, thumb_path: str) -> None:
        if not item or not thumb_path:
            return
        item.setData(_SHOT_THUMB_ROLE, thumb_path)
        grid = getattr(self, "grid_screenshots", None)
        photo = grid.itemWidget(item) if grid is not None else None
        if isinstance(photo, ScreenshotPhoto):
            photo.set_thumbnail(thumb_path)
            return
        # Placeholder still — thumb waits until the tile is materialized.

    def _persist_screenshots_library_snapshot(
        self, folder: str, files: list[dict]
    ) -> None:
        try:
            save_screenshots_library_cache(
                getattr(self, "cache_dir", None),
                folder=folder or "",
                files=files,
            )
        except Exception:
            logging.exception("Failed to save screenshots library snapshot")

    def _stop_screenshot_thumb_backfill(self, *, wait_ms: int = 3000) -> None:
        worker = getattr(self, "_screenshot_thumb_worker", None)
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            if wait_ms > 0:
                worker.wait(int(wait_ms))
        if worker.isRunning():
            # Still busy — leave the handle; finished_batch clears it.
            return
        self._screenshot_thumb_worker = None

    def _schedule_screenshot_thumb_backfill(
        self, entries: list[tuple[str, float]]
    ) -> None:
        cache_dir = getattr(self, "cache_dir", None)
        if not cache_dir or not entries:
            return
        if getattr(self, "_screenshots_scroll_active", False):
            # Scroll in progress — retry after idle debounce fires viewport refresh.
            return
        # Dedupe + keep only paths that still matter (visible / about to show).
        seen: set[str] = set()
        trimmed: list[tuple[str, float]] = []
        for path, mtime in entries:
            key = self._screenshot_path_key(path)
            if not key or key in seen:
                continue
            seen.add(key)
            trimmed.append((path, mtime))
        if not trimmed:
            return
        worker = getattr(self, "_screenshot_thumb_worker", None)
        if worker is not None and worker.isRunning():
            # Don't block the UI waiting on JPEG work — queue for when it exits.
            worker.requestInterruption()
            self._pending_viewport_backfill = trimmed
            return
        self._screenshot_thumb_worker = None
        from steempeg.ui.library.screenshot_thumb_backfill import (
            ScreenshotThumbBackfillWorker,
        )

        new_worker = ScreenshotThumbBackfillWorker(
            trimmed, cache_dir, parent=getattr(self, "ui", None)
        )
        self._screenshot_thumb_worker = new_worker
        new_worker.thumb_ready.connect(self._on_screenshot_thumb_ready)
        new_worker.finished_batch.connect(self._on_screenshot_thumb_backfill_finished)
        new_worker.start()

    def _on_screenshot_thumb_ready(self, file_path: str, thumb_path: str) -> None:
        if getattr(self, "_screenshots_scroll_active", False):
            # Stash path on the item for when scrolling stops; skip pixmap decode.
            index = getattr(self, "_screenshot_items_by_path", None)
            if isinstance(index, dict):
                item = index.get(self._screenshot_path_key(file_path))
                if item is not None:
                    item.setData(_SHOT_THUMB_ROLE, thumb_path)
            return
        self._apply_screenshot_thumb_by_path(file_path, thumb_path)

    def _on_screenshot_thumb_backfill_finished(self) -> None:
        self._screenshot_thumb_worker = None
        pending = getattr(self, "_pending_viewport_backfill", None)
        if pending:
            self._pending_viewport_backfill = None
            if not getattr(self, "_screenshots_scroll_active", False):
                self._schedule_screenshot_thumb_backfill(list(pending))

    def restore_screenshots_from_session_cache(self) -> bool:
        """Skip startup: paint last Screenshots session JSON — no folder walk.

        Steempeg rows paint immediately; Steam rows from the snapshot append in
        UI chunks so 8k+ cards never hitch the first frame.
        """
        folder = self._screenshots_folder_path()
        rows = files_from_screenshots_library_cache(
            getattr(self, "cache_dir", None),
            folder=folder,
        )
        if not rows:
            return False

        self._ensure_screenshots_widgets()
        self._stop_steam_screenshots_scan()
        self._stop_screenshot_thumb_backfill()
        self._stop_screenshot_game_name_backfill()
        self._pending_cached_screenshot_thumbs = []
        self._screenshot_thumb_chunk_scheduled = False
        self._screenshot_live_paths = set()
        self._screenshots_viewport_primed = False
        self.grid_screenshots.clear()
        self._screenshot_items_by_path = {}
        self._screenshot_seen_paths = set()

        steempeg_rows: list[dict] = []
        steam_rows: list[dict] = []
        for row in rows:
            source = str(row.get("source") or "steempeg").strip().lower()
            if source == "steam":
                steam_rows.append(row)
            else:
                steempeg_rows.append(row)

        steempeg_rows.sort(key=lambda t: float(t.get("mtime") or 0.0), reverse=True)
        steam_rows.sort(key=lambda t: float(t.get("mtime") or 0.0), reverse=True)
        self._paint_screenshot_rows(steempeg_rows, rebuild_index=True)

        self._screenshots_scanned_folder = folder if steam_rows else None
        if not hasattr(self, "_sort_applied_by_panel"):
            self._sort_applied_by_panel = {}
        if hasattr(self, "combo_sort"):
            self._sort_applied_by_panel["screenshots"] = (
                self._screenshots_global_sort_index()
            )
        if self._screenshots_global_sort_index() != 0:
            self.apply_screenshots_sorting()
        self._apply_screenshots_filters(refresh_viewport=False)
        self._update_library_count_label()
        logging.info(
            "Skip: painted %d Steempeg screenshots from session snapshot"
            " (%d Steam queued)",
            len(steempeg_rows),
            len(steam_rows),
        )
        if steempeg_rows:
            self._screenshots_viewport_primed = True
            self._schedule_screenshots_viewport_refresh(0)
            self._schedule_screenshots_grid_reflow(0)
        else:
            self._screenshots_viewport_primed = False
        if steam_rows:
            self._pending_steam_screenshot_rows = list(steam_rows)
            self._steam_screenshot_chunk_scheduled = True
            # After show settles — chunked placeholder append, viewport fills tiles.
            QTimer.singleShot(100, self._flush_steam_screenshot_chunk)
        elif not steempeg_rows:
            return False
        else:
            # Steempeg-only snapshot: still try to resolve any Steam leftovers later.
            QTimer.singleShot(200, self._schedule_screenshot_game_name_backfill)
        return True

    def _collect_unresolved_screenshot_app_ids(self) -> list[str]:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return []
        missing: set[str] = set()
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            app_id = str(item.data(_SHOT_APP_ID_ROLE) or "").strip()
            if not app_id:
                continue
            game = str(item.data(_SHOT_GAME_ROLE) or "").strip()
            if self._is_screenshot_placeholder_name(game, app_id):
                missing.add(app_id)
        return sorted(missing)

    def _stop_screenshot_game_name_backfill(self) -> None:
        worker = getattr(self, "_screenshot_names_worker", None)
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(1500)
        self._screenshot_names_worker = None

    def _schedule_screenshot_game_name_backfill(self) -> None:
        """Quiet Steam API fill for screenshot app ids missing from games.json."""
        if getattr(self, "_library_panel_mode", "") not in ("screenshots", "clips", "rendered"):
            # Still OK to run when screenshots tab exists after restore.
            pass
        worker = getattr(self, "_screenshot_names_worker", None)
        if worker is not None and worker.isRunning():
            return
        # Don't fight a manual Clips "Refresh game names" job.
        other = getattr(self, "_steam_names_worker", None)
        if other is not None and other.isRunning():
            QTimer.singleShot(1500, self._schedule_screenshot_game_name_backfill)
            return

        app_ids = self._collect_unresolved_screenshot_app_ids()
        if not app_ids:
            return

        from steempeg.ui.library.refresh_workers import SteamNamesRefreshWorker

        worker = SteamNamesRefreshWorker(app_ids, parent=getattr(self, "ui", None))
        self._screenshot_names_worker = worker
        worker.finished_names.connect(self._on_screenshot_game_names_finished)
        worker.failed.connect(self._on_screenshot_game_names_failed)
        if hasattr(self, "set_status") and getattr(self, "_library_panel_mode", "") == "screenshots":
            self.set_status(
                f"Screenshots: resolving {len(app_ids)} game name"
                f"{'s' if len(app_ids) != 1 else ''}…"
            )
        worker.start()

    def _on_screenshot_game_names_failed(self, message: str) -> None:
        self._screenshot_names_worker = None
        logging.warning("Screenshot game-name backfill failed: %s", message)

    def _on_screenshot_game_names_finished(self, payload: dict) -> None:
        self._screenshot_names_worker = None
        names = (payload or {}).get("names") or {}
        if not names:
            return
        cache = getattr(self, "game_names_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self.game_names_cache = cache
        for app_id, name in names.items():
            aid = str(app_id)
            label = str(name or "").strip()
            if not aid or not label:
                continue
            cache[aid] = label
        self._invalidate_screenshot_game_lookup_memo()
        if hasattr(self, "save_json_cache"):
            try:
                self.save_json_cache()
            except Exception:
                pass
        updated = self.apply_screenshot_game_names(names)
        updated += self._backfill_steempeg_screenshot_identities()
        if updated and hasattr(self, "set_status") and getattr(
            self, "_library_panel_mode", ""
        ) == "screenshots":
            self.set_status(f"Screenshots: updated {updated} game name(s)")

    def apply_screenshot_game_names(self, names: dict) -> int:
        """Apply app_id→name map to screenshot cards + filter selection. Returns rows touched."""
        if not names:
            return 0
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return 0
        normalized = {
            str(aid): str(name).strip()
            for aid, name in names.items()
            if str(aid).strip() and str(name or "").strip()
        }
        if not normalized:
            return 0

        filters = getattr(self, "_screenshots_filter_games", None)
        touched = 0
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            app_id = str(item.data(_SHOT_APP_ID_ROLE) or "").strip()
            new_name = normalized.get(app_id)
            if not new_name:
                continue
            old_name = str(item.data(_SHOT_GAME_ROLE) or "").strip()
            if old_name == new_name:
                # Still refresh live icon if we now have a cache logo.
                photo = grid.itemWidget(item)
                if isinstance(photo, ScreenshotPhoto):
                    resolved_id = app_id or self._screenshot_app_id_for_game_label(
                        old_name or new_name, app_id=app_id
                    )
                    icon = self._screenshot_icon_path_for_app_id(resolved_id)
                    if icon:
                        photo.set_game_icon(icon)
                continue
            item.setData(_SHOT_GAME_ROLE, new_name)
            touched += 1
            if isinstance(filters, set) and old_name in filters:
                filters.discard(old_name)
                filters.add(new_name)
            photo = grid.itemWidget(item)
            if isinstance(photo, ScreenshotPhoto):
                photo.set_title(new_name)
                resolved_id = app_id or self._screenshot_app_id_for_game_label(new_name)
                icon = self._screenshot_icon_path_for_app_id(resolved_id)
                if icon:
                    photo.set_game_icon(icon)

        if touched:
            self._apply_screenshots_filters(refresh_viewport=False)
            menu = getattr(self, "screenshots_filter_menu", None)
            if menu is not None and menu.isVisible() and hasattr(menu, "gather_statistics"):
                menu.gather_statistics(self)
            folder = self._screenshots_folder_path()
            snapshot = self._collect_screenshot_grid_snapshot()
            self._persist_screenshots_library_snapshot(folder, snapshot)
            self._update_library_count_label()
        return touched

    def apply_screenshots_sorting(self):
        grid = getattr(self, "grid_screenshots", None)
        if grid is None or not hasattr(self, "combo_sort"):
            return
        if getattr(self, "_screenshots_sorting", False):
            return
        self._screenshots_sorting = True
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._apply_screenshots_sorting_body(grid)
        finally:
            QApplication.restoreOverrideCursor()
            self._screenshots_sorting = False

    def _apply_screenshots_sorting_body(self, grid: QListWidget) -> None:
        idx = self._screenshots_global_sort_index()

        # Keep a path near the current viewport so mid-library sorts don't jump to top.
        anchor_path = ""
        for item in self._screenshots_visible_items():
            anchor_path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if anchor_path:
                break

        # Drop only live photo widgets (cap ~96) — never walk all rows for this.
        live = getattr(self, "_screenshot_live_paths", None)
        if isinstance(live, set) and live:
            index = getattr(self, "_screenshot_items_by_path", None)
            if not isinstance(index, dict):
                self._rebuild_screenshot_path_index()
                index = getattr(self, "_screenshot_items_by_path", {}) or {}
            for key in list(live):
                item = index.get(key)
                if item is not None:
                    self._dematerialize_screenshot_item(item)
        self._screenshot_live_paths = set()

        n = grid.count()
        payload: list[tuple[QListWidgetItem, str, float, str, str]] = []
        payload_reserve = payload.append
        for i in range(n):
            item = grid.item(i)
            if item is None:
                continue
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            game = str(item.data(_SHOT_GAME_ROLE) or "")
            source = str(item.data(_SHOT_SOURCE_ROLE) or "steempeg")
            try:
                mtime = float(item.data(_SHOT_MTIME_ROLE) or 0.0)
            except (TypeError, ValueError):
                mtime = 0.0
            payload_reserve((item, path, mtime, game, source))

        def game_key(entry: tuple[QListWidgetItem, str, float, str, str]) -> str:
            return (entry[3] or "").lower()

        def date_key(entry: tuple[QListWidgetItem, str, float, str, str]) -> float:
            return float(entry[2] or 0.0)

        def default_key(entry: tuple[QListWidgetItem, str, float, str, str]) -> tuple:
            source_rank = 0 if (entry[4] or "steempeg").strip().lower() != "steam" else 1
            return (source_rank, -date_key(entry))

        if idx in (1, 2):
            payload.sort(key=game_key, reverse=(idx == 2))
        elif idx == 7:
            payload.sort(key=date_key)
        elif idx == 8:
            payload.sort(key=date_key, reverse=True)
        else:
            payload.sort(key=default_key)

        grid.setUpdatesEnabled(False)
        try:
            # takeItem(0) in a loop is O(n²) and freezes multi-k libraries.
            # Taking from the end is O(n); items stay owned by us until re-add.
            for i in range(n - 1, -1, -1):
                grid.takeItem(i)
            for item, _path, _mtime, _game, _source in payload:
                grid.addItem(item)
        finally:
            grid.setUpdatesEnabled(True)

        self._rebuild_screenshot_path_index()
        self._screenshot_seen_paths = set(
            (getattr(self, "_screenshot_items_by_path", None) or {}).keys()
        )
        if not hasattr(self, "_sort_applied_by_panel"):
            self._sort_applied_by_panel = {}
        self._sort_applied_by_panel["screenshots"] = idx
        self._apply_screenshots_filters(refresh_viewport=False)

        if anchor_path:
            key = self._screenshot_path_key(anchor_path)
            anchor_item = (getattr(self, "_screenshot_items_by_path", None) or {}).get(
                key
            )
            if anchor_item is not None and not anchor_item.isHidden():
                # PySide6 on Linux requires QModelIndex; QListWidgetItem is rejected.
                anchor_index = grid.indexFromItem(anchor_item)
                if anchor_index.isValid():
                    grid.scrollTo(
                        anchor_index,
                        QAbstractItemView.ScrollHint.PositionAtCenter,
                    )

        self._schedule_screenshots_viewport_refresh(0)

    def _row_hidden_by_screenshots_filters(
        self, game_name: str, source: str = "steempeg"
    ) -> bool:
        games = getattr(self, "_screenshots_filter_games", None)
        folders = getattr(self, "_screenshots_filter_folders", None)
        if games is not None and (game_name or "Unknown") not in games:
            return True
        if folders is not None:
            src = (source or "steempeg").strip().lower() or "steempeg"
            if src not in folders:
                return True
        return False

    def _remap_screenshots_filter_game_names(self) -> None:
        """Keep persisted Games-filter keys in sync with canonical Steam names."""
        games = getattr(self, "_screenshots_filter_games", None)
        if not isinstance(games, set) or not games:
            return
        remapped: set[str] = set()
        changed = False
        for name in games:
            new_name, _aid = self._resolve_screenshot_row_identity(
                name, "", source="steempeg"
            )
            label = (new_name or name).strip() or name
            remapped.add(label)
            if label != name:
                changed = True
        if changed:
            self._screenshots_filter_games = remapped

    def _apply_screenshots_filters(self, *, refresh_viewport: bool = True) -> None:
        grid = getattr(self, "grid_screenshots", None)
        if grid is None:
            return
        self._remap_screenshots_filter_game_names()
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            game = str(item.data(_SHOT_GAME_ROLE) or "").strip() or "Unknown"
            source = str(item.data(_SHOT_SOURCE_ROLE) or "steempeg")
            item.setHidden(self._row_hidden_by_screenshots_filters(game, source))
        self._update_library_count_label()
        if refresh_viewport:
            self._schedule_screenshots_viewport_refresh(16)

    def show_screenshots_filter_menu(self):
        from steempeg.ui.library.screenshots_filters import ScreenshotsFilterMenu

        if hasattr(self, "screenshots_filter_menu") and self.screenshots_filter_menu:
            self.screenshots_filter_menu.deleteLater()

        self.screenshots_filter_menu = ScreenshotsFilterMenu(self.ui)
        self.screenshots_filter_menu.gather_statistics(self)
        dense = (
            self._filter_menu_density()
            if hasattr(self, "_filter_menu_density")
            else getattr(self, "_ui_density", None)
        )
        if dense is not None and hasattr(self.screenshots_filter_menu, "apply_density"):
            self.screenshots_filter_menu.apply_density(dense)
        self._position_screenshots_filter_menu()
        self.screenshots_filter_menu.show()
        QTimer.singleShot(0, self._position_screenshots_filter_menu)

    def _position_screenshots_filter_menu(self):
        menu = getattr(self, "screenshots_filter_menu", None)
        if not menu or not hasattr(self, "btn_filter_pill"):
            return
        button_bottom_left = self.btn_filter_pill.mapToGlobal(
            QPoint(0, self.btn_filter_pill.height())
        )
        x_shift = menu.width() - self.btn_filter_pill.width()
        menu_y = button_bottom_left.y() + 5
        menu.move(button_bottom_left.x() - x_shift + 10, menu_y)

        floor_y = self._filter_popup_floor_y(menu_y) if hasattr(self, "_filter_popup_floor_y") else menu_y + 400
        menu.set_content_max_height(max(160, floor_y - menu_y - 8))

    def _on_screenshot_item_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        if path:
            self._on_screenshot_open(str(path))

    def _seed_rendered_icons_cache(self) -> dict[str, str]:
        """Reuse game icons already fetched during the Clips Manager scan."""
        seeded: dict[str, str] = {}
        app_ids: set[str] = set()
        if hasattr(self, "_collect_library_app_ids"):
            app_ids.update(str(a) for a in self._collect_library_app_ids())
        if hasattr(self, "game_icons_cache"):
            app_ids.update(str(a) for a in self.game_icons_cache)
        for app_id in app_ids:
            path = os.path.join(self.cache_dir, f"{app_id}.jpg")
            if os.path.isfile(path) and os.path.getsize(path) > 100:
                seeded[app_id] = path
        return seeded

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

    def _stop_rendered_scan(self):
        worker = getattr(self, "_rendered_scan_worker", None)
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(5000)
        self._rendered_scan_worker = None

    def _stop_rendered_poster_backfill(self):
        worker = getattr(self, "_rendered_poster_worker", None)
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(3000)
        self._rendered_poster_worker = None

    def _finish_startup_library_scan_status(self, *, text: str = "Ready", state: str = "ready") -> None:
        """Drop startup scan flags; preload render history before the final Ready."""
        self._rendered_scan_active = False
        was_startup = bool(getattr(self, "_startup_library_scan_active", False))
        if was_startup:
            self._startup_library_scan_active = False
        if not hasattr(self, "update_status_indicator"):
            return
        # After clips+rendered, warm history in RAM off the UI thread.
        if was_startup and state == "ready" and hasattr(self, "preload_render_history"):
            self.preload_render_history(announce=True)
            return
        if was_startup or self._library_scan_status_active("rendered"):
            self.update_status_indicator(text, state)

    def scan_rendered_outputs(self):
        self._ensure_rendered_widgets()
        if not hasattr(self, "table_rendered"):
            if getattr(self, "_startup_library_scan_active", False):
                self._finish_startup_library_scan_status()
            return

        self._stop_rendered_scan()
        self._stop_rendered_poster_backfill()
        self._saved_rendered_selection_path = ""
        self._clear_rendered_selection_visual()

        self.table_rendered.setSortingEnabled(False)
        self.table_rendered.setRowCount(0)
        if hasattr(self, "grid_rendered"):
            self._rendered_grid_anchor_index = -1
            self.grid_rendered.clear()
        self._library_rendered_rows = []

        self._sync_library_scrollbars(force_hide=True)

        roots = self._collect_rendered_scan_roots()
        if not roots:
            self._finish_startup_library_scan_status()
            self._update_library_count_label()
            QTimer.singleShot(0, self._sync_library_scrollbars)
            return

        self._rendered_scan_active = True
        self._rendered_output_meta_index = self._build_rendered_output_meta_index()
        self._rendered_scan_generation = getattr(self, "_rendered_scan_generation", 0) + 1
        generation = self._rendered_scan_generation

        self._update_library_count_label()
        if hasattr(self, "update_status_indicator") and self._library_scan_status_active("rendered"):
            self.update_status_indicator("Searching rendered files…", "busy", scan_phase="search")

        worker = RenderedScanWorker(
            roots,
            self._rendered_output_meta_index,
            self.cache_dir,
            self.game_names_cache,
            icons_cache=self._seed_rendered_icons_cache(),
            parent=getattr(self, "ui", None),
        )
        self._rendered_scan_worker = worker
        worker.discovering.connect(
            lambda total: self._on_rendered_scan_discovering(total, generation)
        )
        worker.file_ready.connect(
            lambda row, index, total: self._on_rendered_file_ready(row, index, total, generation)
        )
        worker.finished_scan.connect(
            lambda stats: self._on_rendered_scan_finished(stats, generation)
        )
        worker.scan_error.connect(
            lambda msg: self._on_rendered_scan_error(msg, generation)
        )
        worker.start()

    def _on_rendered_scan_discovering(self, total: int, generation: int) -> None:
        if generation != getattr(self, "_rendered_scan_generation", 0):
            return
        if not hasattr(self, "update_status_indicator"):
            return
        if not self._library_scan_status_active("rendered"):
            return
        if total <= 0:
            self.update_status_indicator("Searching rendered files…", "busy", scan_phase="search")
        else:
            self.update_status_indicator(f"Found {total} files", "busy", scan_phase="search")

    def _on_rendered_file_ready(
        self, row: ScannedRenderedFile, index: int, total: int, generation: int
    ) -> None:
        if generation != getattr(self, "_rendered_scan_generation", 0):
            return
        self._library_rendered_rows.append(row)
        table_row = self._insert_rendered_file_row(row)
        if table_row >= 0:
            self._append_rendered_grid_card_for_row(table_row)
        label = row.display_title.strip() or os.path.basename(row.full_path)
        pct = int(100 * index / total) if total else 0
        if row.source_clip_name:
            status_line = f"Loading {index}/{total} — {label} · {row.source_clip_name} ({pct}%)"
        else:
            status_line = f"Loading {index}/{total} — {label} ({pct}%)"
        if hasattr(self, "update_status_indicator") and self._library_scan_status_active("rendered"):
            self.update_status_indicator(
                status_line,
                "busy",
                scan_phase="loading",
            )
        if hasattr(self, "_seed_rendered_health_cache_row"):
            self._seed_rendered_health_cache_row(row)
        self._update_library_count_label()

    def _on_rendered_scan_finished(self, stats, generation: int) -> None:
        if generation != getattr(self, "_rendered_scan_generation", 0):
            return

        worker = getattr(self, "_rendered_scan_worker", None)
        if worker is not None:
            for app_id, name in worker.game_names_cache.items():
                if app_id not in self.game_names_cache:
                    self.game_names_cache[app_id] = name
            if worker.game_names_cache:
                self.save_json_cache()
        self._rendered_scan_worker = None

        if hasattr(self, "table_rendered"):
            self.table_rendered.setSortingEnabled(True)
            self.table_rendered.horizontalHeader().setSectionsClickable(False)
        if hasattr(self, "apply_rendered_sorting"):
            self.apply_rendered_sorting()
        else:
            self._sync_rendered_grid_from_table()
        self._persist_rendered_library_snapshot()
        self._schedule_rendered_poster_backfill()
        self._update_library_count_label()

        self._finish_startup_library_scan_status()

        if hasattr(self, "_save_rendered_health_cache") and getattr(
            self, "_rendered_health_cache_dirty", 0
        ):
            self._save_rendered_health_cache()
            self._rendered_health_cache_dirty = 0

        QTimer.singleShot(0, self._sync_library_scrollbars)

        logging.info(
            "Rendered scan: roots=%s files=%d",
            stats.scan_roots,
            stats.file_count,
        )

    def _persist_rendered_library_snapshot(self) -> None:
        """Write the current Rendered list for Skip startup restores."""
        try:
            save_rendered_library_cache(
                getattr(self, "cache_dir", None),
                scan_roots=self._collect_rendered_scan_roots()
                if hasattr(self, "_collect_rendered_scan_roots")
                else [],
                files=list(getattr(self, "_library_rendered_rows", None) or []),
            )
        except Exception:
            logging.exception("Failed to save rendered library snapshot")

    def restore_rendered_from_session_cache(self) -> bool:
        """Skip startup: paint last Rendered session JSON — no export-folder walk."""
        files = files_from_rendered_library_cache(
            getattr(self, "cache_dir", None),
            require_exists=False,
        )
        if not files:
            return False

        self._ensure_rendered_widgets()
        if not hasattr(self, "table_rendered"):
            return False

        self._stop_rendered_scan()
        self._stop_rendered_poster_backfill()
        self._saved_rendered_selection_path = ""
        self._clear_rendered_selection_visual()

        self.table_rendered.setSortingEnabled(False)
        self.table_rendered.setRowCount(0)
        if hasattr(self, "grid_rendered"):
            self._rendered_grid_anchor_index = -1
            self.grid_rendered.clear()

        self._library_rendered_rows = list(files)
        self._rendered_scan_generation = getattr(self, "_rendered_scan_generation", 0) + 1
        self._rendered_scan_active = False

        table = self.table_rendered
        grid = getattr(self, "grid_rendered", None)
        table.setUpdatesEnabled(False)
        if grid is not None:
            grid.setUpdatesEnabled(False)
        try:
            for row in files:
                table_row = self._insert_rendered_file_row(row)
                if table_row >= 0:
                    self._append_rendered_grid_card_for_row(table_row)
                if hasattr(self, "_seed_rendered_health_cache_row"):
                    self._seed_rendered_health_cache_row(row)
        finally:
            table.setUpdatesEnabled(True)
            if grid is not None:
                grid.setUpdatesEnabled(True)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionsClickable(False)
        if hasattr(self, "apply_rendered_sorting"):
            self.apply_rendered_sorting()
        else:
            self._sync_rendered_grid_from_table()

        self._update_library_count_label()
        logging.info("Skip: painted %d rendered files from session snapshot", len(files))
        if not hasattr(self, "_sort_applied_by_panel"):
            self._sort_applied_by_panel = {}
        if hasattr(self, "combo_sort"):
            self._sort_applied_by_panel["rendered"] = int(self.combo_sort.currentIndex())
        # Quiet poster top-up later (may touch export paths).
        QTimer.singleShot(900, self._schedule_rendered_poster_backfill)
        QTimer.singleShot(0, self._sync_library_scrollbars)
        return True

    def _on_rendered_scan_error(self, message: str, generation: int) -> None:
        if generation != getattr(self, "_rendered_scan_generation", 0):
            return
        self._rendered_scan_worker = None
        logging.error("Rendered scan failed: %s", message)
        self._finish_startup_library_scan_status(text="Scan error", state="error")
        QTimer.singleShot(0, self._sync_library_scrollbars)

    def _insert_rendered_file_row(self, scanned: ScannedRenderedFile) -> int:
        if not hasattr(self, "table_rendered"):
            return -1

        icon_path = scanned.icon_path
        list_icon = QIcon()
        if icon_path and os.path.isfile(icon_path):
            from steempeg.ui.icon_shape import shaped_game_icon

            pix = QPixmap(icon_path)
            if not pix.isNull():
                list_icon = shaped_game_icon(pix)
        if list_icon.isNull() and not scanned.is_unknown:
            app_id = parse_app_id_from_name(os.path.basename(scanned.full_path))
            if not app_id and scanned.source_clip_name:
                app_id = parse_app_id_from_clip_folder(scanned.source_clip_name)
            if app_id:
                synced = self._seed_rendered_icons_cache()
                if app_id in synced:
                    icon_path = synced[app_id]
                    from steempeg.ui.icon_shape import shaped_game_icon

                    pix = QPixmap(icon_path)
                    if not pix.isNull():
                        list_icon = shaped_game_icon(pix)
        if scanned.is_unknown:
            from steempeg.infra.paths import get_resource_path
            from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon

            unknown_icon = get_resource_path("unknown_icon.png")
            if os.path.isfile(unknown_icon):
                pix = QPixmap(unknown_icon)
                if not pix.isNull():
                    list_icon = shaped_game_icon(pix, ICON_SHAPE_CIRCLE)

        row = self.table_rendered.rowCount()
        self.table_rendered.insertRow(row)
        name_item = QTableWidgetItem(list_icon, f"   {scanned.display_title}")
        name_item.setData(Qt.ItemDataRole.UserRole, scanned.full_path)
        name_item.setData(_RENDERED_GAME_FILTER_ROLE, scanned.game_filter_name)
        name_item.setData(_RENDERED_THUMB_ROLE, "")
        name_item.setData(_RENDERED_ICON_ROLE, icon_path or "")
        name_item.setToolTip(scanned.full_path)
        self.table_rendered.setItem(row, 0, name_item)

        type_item = QTableWidgetItem(f"🎬 {scanned.type_label}")
        type_item.setData(_RENDERED_TYPE_FILTER_ROLE, scanned.type_label)
        type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.table_rendered.setItem(row, 1, type_item)

        date_item = QTableWidgetItem(f"{scanned.date_str}\n{scanned.time_str}")
        date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        try:
            date_item.setData(Qt.ItemDataRole.UserRole, float(scanned.file_mtime))
        except (TypeError, ValueError):
            pass
        self.table_rendered.setItem(row, 2, date_item)

        size_item = QTableWidgetItem(scanned.size_str)
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.table_rendered.setItem(row, 3, size_item)

        if self._row_hidden_by_rendered_filters(scanned.game_filter_name, scanned.type_label):
            self.table_rendered.setRowHidden(row, True)
        return row

    def _schedule_rendered_poster_backfill(self) -> None:
        if not hasattr(self, "table_rendered") or not hasattr(self, "cache_dir"):
            return

        missing: list[str] = []
        for row in range(self.table_rendered.rowCount()):
            name_item = self.table_rendered.item(row, 0)
            if not name_item:
                continue
            file_path = name_item.data(Qt.ItemDataRole.UserRole)
            if not file_path:
                continue
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in RENDERED_VIDEO_EXTS:
                continue
            if name_item.data(_RENDERED_THUMB_ROLE):
                continue
            missing.append(file_path)

        if not missing:
            return

        self._stop_rendered_poster_backfill()
        self._rendered_poster_worker = RenderedPosterBackfillWorker(
            missing, self.cache_dir, getattr(self, "ui", None)
        )
        self._rendered_poster_worker.poster_ready.connect(self._on_rendered_poster_ready)
        self._rendered_poster_worker.finished_batch.connect(self._on_rendered_poster_batch_done)
        self._rendered_poster_worker.start()

    def _on_rendered_poster_ready(self, file_path: str, thumb_path: str) -> None:
        if not hasattr(self, "table_rendered"):
            return
        norm = os.path.normpath(file_path)
        for row in range(self.table_rendered.rowCount()):
            name_item = self.table_rendered.item(row, 0)
            if not name_item:
                continue
            item_path = name_item.data(Qt.ItemDataRole.UserRole)
            if not item_path or os.path.normpath(item_path) != norm:
                continue
            name_item.setData(_RENDERED_THUMB_ROLE, thumb_path)
            if hasattr(self, "grid_rendered"):
                for i in range(self.grid_rendered.count()):
                    grid_item = self.grid_rendered.item(i)
                    if grid_item is None:
                        continue
                    if grid_item.data(Qt.ItemDataRole.UserRole + 1) != item_path:
                        continue
                    card = self.grid_rendered.itemWidget(grid_item)
                    if card is not None and hasattr(card, "set_thumbnail"):
                        card.set_thumbnail(thumb_path)
                    break
            break

    def _on_rendered_poster_batch_done(self) -> None:
        self._rendered_poster_worker = None

    def _append_rendered_grid_card_for_row(self, row: int) -> None:
        if not hasattr(self, "grid_rendered") or not hasattr(self, "table_rendered"):
            return
        name_item = self.table_rendered.item(row, 0)
        type_item = self.table_rendered.item(row, 1)
        date_item = self.table_rendered.item(row, 2)
        size_item = self.table_rendered.item(row, 3)
        if not name_item:
            return

        display_title = name_item.text().strip()
        date_str = date_item.text() if date_item else ""
        size_str = size_item.text() if size_item else ""
        file_path = name_item.data(Qt.ItemDataRole.UserRole)
        thumb_path = name_item.data(_RENDERED_THUMB_ROLE) or ""
        icon_path = name_item.data(_RENDERED_ICON_ROLE) or ""
        badge = type_item.text().replace("🎬 ", "").strip() if type_item else "FILE"
        is_unknown = (name_item.data(_RENDERED_GAME_FILTER_ROLE) or "Unknown") == "Unknown"

        if is_unknown:
            from steempeg.infra.paths import get_resource_path

            unknown_icon = get_resource_path("unknown_icon.png")
            if os.path.isfile(unknown_icon):
                icon_path = unknown_icon

        footer = f"Unknown • {size_str}" if is_unknown else f"{date_str} • {size_str}"

        item = QListWidgetItem(self.grid_rendered)
        item.setSizeHint(QSize(260, 190))
        item.setData(Qt.ItemDataRole.UserRole, row)
        item.setData(Qt.ItemDataRole.UserRole + 1, file_path)

        card = ClipCard(
            display_title,
            footer,
            badge,
            thumb_path,
            icon_path,
            row,
            health_color=None,
            round_icon=is_unknown,
            on_left_click=lambda ev, grid_item=item: self._defer_rendered_grid_select_item(
                grid_item, ev
            ),
            on_right_click=lambda ev, grid_item=item: self._handle_rendered_grid_card_context_menu(grid_item, ev),
        )
        self.grid_rendered.setItemWidget(item, card)
        if self.table_rendered.isRowHidden(row):
            item.setHidden(True)


    def _row_hidden_by_rendered_filters(self, game_name: str, type_label: str) -> bool:
        if self._rendered_filter_games is not None and game_name not in self._rendered_filter_games:
            return True
        if self._rendered_filter_types is not None and type_label not in self._rendered_filter_types:
            return True
        return False

    def _apply_rendered_filters(self):
        if not hasattr(self, "table_rendered"):
            return
        for row in range(self.table_rendered.rowCount()):
            name_item = self.table_rendered.item(row, 0)
            type_item = self.table_rendered.item(row, 1)
            game_name = name_item.data(_RENDERED_GAME_FILTER_ROLE) if name_item else "Unknown"
            type_label = type_item.data(_RENDERED_TYPE_FILTER_ROLE) if type_item else ""
            self.table_rendered.setRowHidden(
                row, self._row_hidden_by_rendered_filters(str(game_name or "Unknown"), str(type_label or ""))
            )
        self.build_rendered_grid()
        self._update_library_count_label()

    def _resolved_rendered_meta(self, file_path: str, filename: str) -> tuple[str, str, str, bool, str]:
        """Return (display_title, icon_path, thumb_path, is_unknown, game_filter_name)."""
        basename = os.path.basename(filename) if filename else os.path.basename(file_path)
        stem = os.path.splitext(basename)[0]
        source = self._lookup_rendered_source_meta(file_path, basename)

        app_id = source.get("app_id") or parse_app_id_from_name(basename)
        if not app_id and source.get("clip_path"):
            app_id = parse_app_id_from_clip_folder(source["clip_path"])

        icon_path = self._game_icon_path_for_rendered(
            str(app_id) if app_id else None,
            source.get("game_icon_path", ""),
        )

        game_name = ""
        if app_id and hasattr(self, "get_game_name"):
            game_name = self.get_game_name(str(app_id)) or source.get("game_name") or ""
        elif source.get("game_name"):
            game_name = source["game_name"]
        game_name = str(game_name or "").strip()

        if app_id and game_name:
            title = game_name if is_default_rendered_basename(stem, str(app_id)) else stem
        else:
            title = game_name or stem

        # Sidecar/filename may carry game_name without app_id — still not «Unknown».
        if app_id and not game_name and hasattr(self, "get_game_name"):
            game_name = (self.get_game_name(str(app_id)) or "").strip()
        is_unknown = not bool(game_name)

        thumb_path = ""
        ext = os.path.splitext(file_path)[1].lower()
        if ext in RENDERED_VIDEO_EXTS and hasattr(self, "cache_dir"):
            thumb_path = extract_poster_frame(file_path, self.cache_dir)
        game_filter_name = game_name if game_name else "Unknown"
        return title, icon_path, thumb_path, is_unknown, game_filter_name

    def build_rendered_grid(self):
        if not hasattr(self, "grid_rendered"):
            return
        self._rendered_grid_anchor_index = -1
        self.grid_rendered.clear()
        for row in range(self.table_rendered.rowCount()):
            self._append_rendered_grid_card_for_row(row)
        self._sync_rendered_grid_from_table()
        if hasattr(self, "sync_clip_card_edge_roles"):
            QTimer.singleShot(0, self.sync_clip_card_edge_roles)

    def _sync_rendered_grid_card_visuals(self) -> None:
        """Paint selection border on every selected rendered row."""
        if not hasattr(self, "grid_rendered"):
            return
        selected_rows: set[int] = set()
        if (
            getattr(self, "_library_panel_mode", "clips") == "rendered"
            and hasattr(self, "table_rendered")
        ):
            selected_rows = {
                idx.row() for idx in self.table_rendered.selectionModel().selectedRows()
            }
        for i in range(self.grid_rendered.count()):
            item = self.grid_rendered.item(i)
            card = self.grid_rendered.itemWidget(item)
            if isinstance(card, ClipCard):
                row = item.data(Qt.ItemDataRole.UserRole)
                card.set_selected(row in selected_rows)

    def _update_library_count_label(self):
        if not hasattr(self, "lbl_clip_count"):
            return

        from steempeg.ui.widgets.view_mode_toggle import format_library_count

        mode = getattr(self, "_library_panel_mode", "clips")
        chrome = getattr(self, "view_mode_chrome", None)

        def _set(value, noun: str):
            text = format_library_count(value, noun)
            if chrome is not None:
                chrome.set_count(text)
            else:
                self.lbl_clip_count.setText(text)

        if mode == "rendered":
            if getattr(self, "_rendered_scan_active", False):
                if hasattr(self, "table_rendered"):
                    n = self.table_rendered.rowCount()
                    hidden = sum(1 for r in range(n) if self.table_rendered.isRowHidden(r))
                    visible = n - hidden
                    _set(visible if visible > 0 else "…", "Files")
                else:
                    _set("…", "Files")
            elif getattr(self, "_clips_scan_active", False) or (
                getattr(self, "_startup_library_scan_active", False)
                and not getattr(self, "_rendered_scan_active", False)
            ):
                _set("…", "Files")
            elif hasattr(self, "table_rendered"):
                n = self.table_rendered.rowCount()
                hidden = sum(1 for r in range(n) if self.table_rendered.isRowHidden(r))
                visible = n - hidden
                _set(visible, "Files")
            else:
                _set(0, "Files")
            return

        if mode == "screenshots":
            grid = getattr(self, "grid_screenshots", None)
            if grid is None:
                _set(0, "Shots")
                return
            n = grid.count()
            visible = sum(
                1
                for i in range(n)
                if (item := grid.item(i)) is not None and not item.isHidden()
            )
            _set(visible, "Shots")
            return

        if not hasattr(self.ui, "table_clips"):
            return
        table = self.ui.table_clips
        n = table.rowCount()
        # Honour row-hidden state from Apply Filters (same as Rendered files).
        visible = sum(1 for r in range(n) if not table.isRowHidden(r))
        if getattr(self, "_clips_scan_active", False):
            _set(visible if visible > 0 else "…", "Clips")
        else:
            _set(visible, "Clips")

    def _apply_rendered_view_mode(self, *, relayout: bool = True):
        mode = getattr(self, "_rendered_view_mode", "grid")
        if mode == "list":
            self.grid_rendered.hide()
            self.table_rendered.show()
        else:
            self.table_rendered.hide()
            self.grid_rendered.show()
            if relayout:
                self.grid_rendered.doItemsLayout()

        chrome = getattr(self, "view_mode_chrome", None)
        if chrome is not None:
            chrome.set_mode(mode, emit=False)
        elif mode == "list":
            self.btn_view_list.setStyleSheet(self.toggle_style_active)
            self.btn_view_grid.setStyleSheet(self.toggle_style_inactive)
        else:
            self.btn_view_list.setStyleSheet(self.toggle_style_inactive)
            self.btn_view_grid.setStyleSheet(self.toggle_style_active)

        QTimer.singleShot(0, self._sync_library_scrollbars)

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

        reordered = False
        if idx == 0:
            pass
        elif idx == 1:
            rows.sort(key=lambda r: cell(r, 0).lower())
            reordered = True
        elif idx == 2:
            rows.sort(key=lambda r: cell(r, 0).lower(), reverse=True)
            reordered = True
        elif idx == 3:
            rows.sort(key=lambda r: cell(r, 1).lower())
            reordered = True
        elif idx == 4:
            rows.sort(key=lambda r: cell(r, 1).lower(), reverse=True)
            reordered = True
        elif idx in (7, 8):
            rows.sort(key=lambda r: cell(r, 2))
            if idx == 8:
                rows.reverse()
            reordered = True
        elif idx in (9, 10):
            rows.sort(key=lambda r: os.path.getsize(path(r)) if path(r) and os.path.exists(path(r)) else 0)
            if idx == 10:
                rows.reverse()
            reordered = True
        elif idx in _FOLDER_SORT_INDICES:
            roots = getattr(self, "clips_folders", None) or []
            rows.sort(key=lambda r: clip_folder_sort_key(path(r), roots), reverse=(idx == 12))
            reordered = True
        elif idx in _HEALTH_SORT_INDICES:
            pass

        if reordered:
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
            # Grid cards follow table order — only rebuild after a real reorder.
            self.build_rendered_grid()
        else:
            self._sync_rendered_grid_from_table()

        if not hasattr(self, "_sort_applied_by_panel"):
            self._sort_applied_by_panel = {}
        self._sort_applied_by_panel["rendered"] = int(idx)

    def show_rendered_filter_menu(self):
        from steempeg.ui.library.rendered_filters import RenderedFilterMenu

        if hasattr(self, "rendered_filter_menu") and self.rendered_filter_menu:
            self.rendered_filter_menu.deleteLater()

        self.rendered_filter_menu = RenderedFilterMenu(self.ui)
        self.rendered_filter_menu.gather_statistics(self)
        dense = (
            self._filter_menu_density()
            if hasattr(self, "_filter_menu_density")
            else getattr(self, "_ui_density", None)
        )
        if dense is not None and hasattr(self.rendered_filter_menu, "apply_density"):
            self.rendered_filter_menu.apply_density(dense)
        self._position_rendered_filter_menu()
        self.rendered_filter_menu.show()
        QTimer.singleShot(0, self._position_rendered_filter_menu)

    def _position_rendered_filter_menu(self):
        # Same placement math as Clips ``_position_filter_menu``.
        menu = getattr(self, "rendered_filter_menu", None)
        if not menu or not hasattr(self, "btn_filter_pill"):
            return
        button_bottom_left = self.btn_filter_pill.mapToGlobal(
            QPoint(0, self.btn_filter_pill.height())
        )
        x_shift = menu.width() - self.btn_filter_pill.width()
        menu_y = button_bottom_left.y() + 5
        menu.move(button_bottom_left.x() - x_shift + 10, menu_y)

        floor_y = self._filter_popup_floor_y(menu_y)
        menu.set_content_max_height(max(160, floor_y - menu_y - 8))

    def refresh_rendered_library(self):
        self._rendered_output_meta_index = None
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

    def _sync_rendered_table_from_grid_selection(self, *, keep_current_cell: bool = False) -> None:
        if not hasattr(self, "grid_rendered") or not hasattr(self, "table_rendered"):
            return

        selected_items = self.grid_rendered.selectedItems()
        table = self.table_rendered
        if not selected_items:
            table.blockSignals(True)
            table.clearSelection()
            table.blockSignals(False)
            return

        rows = sorted({
            item.data(Qt.ItemDataRole.UserRole)
            for item in selected_items
            if item.data(Qt.ItemDataRole.UserRole) is not None
        })

        selection = QItemSelection()
        for row in rows:
            if row < 0 or row >= table.rowCount():
                continue
            selection.select(
                table.model().index(row, 0),
                table.model().index(row, table.columnCount() - 1),
            )

        table.blockSignals(True)
        table.selectionModel().clearSelection()
        if not selection.isEmpty():
            table.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.Select)
            current_row = table.currentRow()
            if not keep_current_cell or current_row not in rows:
                table.setCurrentCell(rows[0], 0)
        table.blockSignals(False)

    def _cancel_pending_rendered_preview(self) -> None:
        """Bump the open-generation token and stop any debounced export play."""
        self._rendered_preview_gen = getattr(self, "_rendered_preview_gen", 0) + 1
        timer = getattr(self, "_rendered_play_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        self._pending_rendered_play_path = None

    def _schedule_rendered_selection_preview(self) -> None:
        """Open the selected export after press anim + purple-ring chrome.

        Same idea as Clips Manager ``_schedule_clips_selection_preview``: header /
        MPV work must not run on the mouse-press stack or the same tick as the
        press scale paint.
        """
        multi = getattr(
            self,
            "_MULTI_SELECT_MODIFIERS",
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier
            | Qt.KeyboardModifier.AltModifier,
        )
        if QApplication.keyboardModifiers() & multi:
            if hasattr(self, "update_playback_badge"):
                self.update_playback_badge()
            return
        self._rendered_preview_gen = getattr(self, "_rendered_preview_gen", 0) + 1
        gen = self._rendered_preview_gen
        delay_ms = max(16, int(tok.CARD_PRESS_DURATION_MS))
        QTimer.singleShot(delay_ms, lambda g=gen: self._run_rendered_selection_preview(g))

    def _run_rendered_selection_preview(self, gen: int) -> None:
        if gen != getattr(self, "_rendered_preview_gen", 0):
            return
        if getattr(self, "_library_panel_mode", "clips") != "rendered":
            return
        if hasattr(self, "update_rendered_selection"):
            self.update_rendered_selection()

    def _defer_rendered_grid_select_item(self, item, event=None) -> None:
        """Schedule rendered-grid selection off the ClipCard mouse-press stack.

        Press anim + first paint must finish returning before table sync /
        purple ring / export open. Capture modifiers now — keys may be released
        before the timer fires.
        """
        if hasattr(self, "_event_modifiers"):
            mods = self._event_modifiers(event)
        else:
            mods = QApplication.keyboardModifiers()
            if event is not None:
                mods |= event.modifiers()
        self._rendered_card_select_gen = getattr(self, "_rendered_card_select_gen", 0) + 1
        self._cancel_pending_rendered_preview()
        gen = self._rendered_card_select_gen
        QTimer.singleShot(
            0,
            lambda g=gen, it=item, m=mods: self._run_deferred_rendered_grid_select(
                g, it, m
            ),
        )

    def _run_deferred_rendered_grid_select(self, gen: int, item, mods) -> None:
        if gen != getattr(self, "_rendered_card_select_gen", 0):
            return
        try:
            if item is None or not hasattr(self, "grid_rendered") or self.grid_rendered is None:
                return
            # Drop stale callbacks after a library rebuild destroyed the item.
            _ = item.data(Qt.ItemDataRole.UserRole)
        except RuntimeError:
            return
        self._rendered_grid_select_item(item, mods=mods)

    def _publish_rendered_grid_selection(self, *, update_preview: bool = True) -> None:
        if getattr(self, "_library_panel_mode", "clips") != "rendered":
            return
        if hasattr(self, "_clear_clips_selection_visual"):
            self._clear_clips_selection_visual()
        self._saved_clips_selection_path = ""
        if not self.grid_rendered.selectedItems():
            self._sync_rendered_table_from_grid_selection()
            self._sync_rendered_grid_card_visuals()
            self._cancel_pending_rendered_preview()
            return
        self._sync_rendered_table_from_grid_selection(keep_current_cell=not update_preview)
        # Selection chrome first — do not wait on header / MPV open.
        self._sync_rendered_grid_card_visuals()
        if hasattr(self, "grid_rendered") and self.grid_rendered is not None:
            try:
                self.grid_rendered.viewport().repaint()
            except RuntimeError:
                pass
        if update_preview and hasattr(self, "update_rendered_selection"):
            self._schedule_rendered_selection_preview()
        else:
            self._cancel_pending_rendered_preview()

    def _rendered_grid_select_item(
        self, item, event=None, *, force_single: bool = False, mods=None
    ) -> None:
        grid = self.grid_rendered
        if mods is None:
            mods = (
                self._event_modifiers(event)
                if hasattr(self, "_event_modifiers")
                else QApplication.keyboardModifiers()
            )
        if force_single:
            mods = Qt.NoModifier

        is_multi = bool(mods & self._MULTI_SELECT_MODIFIERS) and not force_single
        update_preview = not is_multi
        idx = self._list_widget_item_index(grid, item)

        self._rendered_grid_select_in_progress = True
        try:
            grid.blockSignals(True)
            if mods & self._TOGGLE_SELECT_MODIFIERS:
                item.setSelected(not item.isSelected())
            elif mods & Qt.ShiftModifier:
                anchor_idx = getattr(self, '_rendered_grid_anchor_index', -1)
                if anchor_idx < 0:
                    anchor_idx = idx
                lo, hi = sorted((anchor_idx, idx))
                grid.clearSelection()
                for i in range(lo, hi + 1):
                    row_item = grid.item(i)
                    if row_item and not row_item.isHidden():
                        row_item.setSelected(True)
            else:
                # Already the open export — ignore the click (no reload).
                # Mirrors Clips Manager ``_grid_select_item`` skip-reopen.
                file_path = item.data(Qt.ItemDataRole.UserRole + 1)
                if (
                    update_preview
                    and file_path
                    and hasattr(self, "_norm_clip_path_key")
                    and self._norm_clip_path_key(file_path)
                    == self._norm_clip_path_key(
                        getattr(self, "_active_play_media_path", None)
                        or getattr(self, "_rendered_media_path", None)
                        or getattr(self, "_preview_clip_path", None)
                    )
                ):
                    item.setSelected(True)
                    grid.blockSignals(False)
                    self._rendered_grid_select_in_progress = False
                    self._sync_rendered_grid_card_visuals()
                    return
                grid.clearSelection()
                item.setSelected(True)

            if not (mods & self._MULTI_SELECT_MODIFIERS):
                self._rendered_grid_anchor_index = idx

            grid.blockSignals(False)
        finally:
            self._rendered_grid_select_in_progress = False

        self._publish_rendered_grid_selection(update_preview=update_preview)

    def _handle_rendered_grid_viewport_press(self, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        pos = event.position().toPoint()
        item = self.grid_rendered.itemAt(pos)
        if item is None:
            # Empty space keeps the current selection (same as Clips Manager).
            return True

        # Same deferred path as ClipCard — never open on the press stack.
        self._defer_rendered_grid_select_item(item, event)
        return True

    def _on_rendered_grid_selection_changed(self):
        if getattr(self, '_rendered_grid_select_in_progress', False):
            return
        self._publish_rendered_grid_selection()

    def update_rendered_selection(self):
        if self._library_panel_mode != "rendered":
            return
        if hasattr(self, "_clear_clips_selection_visual"):
            self._clear_clips_selection_visual()
        self._saved_clips_selection_path = ""
        if not hasattr(self, "table_rendered"):
            return
        row = self.table_rendered.currentRow()
        if row < 0:
            return

        if QApplication.keyboardModifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier
            | Qt.KeyboardModifier.AltModifier
        ):
            return

        name_item = self.table_rendered.item(row, 0)
        if not name_item:
            return
        file_path = name_item.data(Qt.ItemDataRole.UserRole)
        self._saved_rendered_selection_path = file_path or ""
        type_label = self.table_rendered.item(row, 1).text() if self.table_rendered.item(row, 1) else ""
        type_clean = type_label.replace("🎬 ", "").strip()
        date_str = self.table_rendered.item(row, 2).text() if self.table_rendered.item(row, 2) else ""
        size_str = self.table_rendered.item(row, 3).text() if self.table_rendered.item(row, 3) else ""

        already_open = (
            hasattr(self, "_norm_clip_path_key")
            and bool(file_path)
            and self._norm_clip_path_key(file_path)
            == self._norm_clip_path_key(
                getattr(self, "_active_play_media_path", None)
                or getattr(self, "_rendered_media_path", None)
            )
        )

        self._preview_clip_path = file_path
        self._rendered_media_path = file_path
        queue_active = hasattr(self, "_queue_is_active") and self._queue_is_active()
        if hasattr(self, "_clear_queue_selection"):
            self._clear_queue_selection()
        else:
            self._selected_queue_job_id = None
        # Render Queue active: keep the render control panel on the queue head /
        # encode target. Finished exports are preview-only — do not divert dash
        # identity chrome the way Clips Manager does for Steam clips.
        if queue_active:
            self._queue_library_preview_diversion = False

        display_title, icon_path, _thumb, is_unknown, _game_key = self._resolved_rendered_meta(
            file_path, os.path.basename(file_path)
        )

        if hasattr(self, "custom_text_label"):
            from steempeg.ui.player_header_layout import set_player_header_game_text

            extra: list[str] = []
            if is_unknown:
                extra.append("Unknown")
            if type_clean:
                extra.append(type_clean)
            if size_str:
                extra.append(size_str)
            date_part = date_str
            time_part = ""
            if "\n" in date_str:
                bits = date_str.split("\n", 1)
                date_part = bits[0].strip()
                time_part = bits[1].strip()
            set_player_header_game_text(
                self,
                display_title,
                date=date_part,
                time=time_part,
                extra=extra,
            )
        if hasattr(self, "custom_icon_label"):
            from steempeg.ui.icon_utils import apply_square_icon
            from steempeg.ui.player_header_layout import player_header_icon_px

            icon_px = player_header_icon_px(self)
            self.custom_icon_label.setStyleSheet("background: transparent; border: none;")
            if icon_path and os.path.isfile(icon_path):
                from PySide6.QtGui import QPixmap
                from steempeg.ui.icon_shape import shaped_game_icon_pixmap

                self.current_game_icon = icon_path
                src = QPixmap(icon_path)
                shaped = shaped_game_icon_pixmap(src, icon_px) if not src.isNull() else None
                apply_square_icon(self.custom_icon_label, shaped, icon_px)
            elif is_unknown:
                from steempeg.infra.paths import get_resource_path
                from PySide6.QtGui import QPixmap
                from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap

                unknown = get_resource_path("unknown_icon.png")
                self.current_game_icon = unknown if os.path.isfile(unknown) else ""
                if os.path.isfile(unknown):
                    src = QPixmap(unknown)
                    shaped = (
                        shaped_game_icon_pixmap(src, icon_px, ICON_SHAPE_CIRCLE)
                        if not src.isNull()
                        else None
                    )
                    apply_square_icon(self.custom_icon_label, shaped, icon_px)
                else:
                    apply_square_icon(self.custom_icon_label, None, icon_px)
            else:
                self.current_game_icon = ""
                apply_square_icon(self.custom_icon_label, None, icon_px)

        if hasattr(self, "btn_clip_health"):
            if hasattr(self, "update_clip_health_button"):
                self.update_clip_health_button()
            else:
                self.btn_clip_health.hide()

        if hasattr(self.ui, "btn_start"):
            self._sync_start_render_enabled()
        if hasattr(self, "set_player_header_clip_controls_visible"):
            self.set_player_header_clip_controls_visible(True)
        if hasattr(self, "update_playback_badge"):
            self.update_playback_badge()
        if queue_active and not getattr(self, "_is_rendering", False):
            # Re-bind Ready / summary to the queue job, not this export's metadata.
            if hasattr(self, "_sync_dash_queue_status_chrome"):
                self._sync_dash_queue_status_chrome()

        if not already_open:
            if hasattr(self, "schedule_play_media_file"):
                self.schedule_play_media_file(file_path)
            elif hasattr(self, "play_media_file"):
                self.play_media_file(file_path)
            # Match Clips Manager: a newly selected item starts at zoom 1.0.
            if hasattr(self, "custom_timeline"):
                self.custom_timeline.set_zoom_state(1.0, 0)
        self._sync_library_mode_chrome()
        self._persist_library_ui_state()

    # --- Rendered shelf context menu (open folder / delete) ---

    def _context_menu_rendered_paths_table(self, pos) -> list[str]:
        item = self.table_rendered.itemAt(pos)
        if not item:
            return []
        clicked_row = item.row()
        selected_rows = {idx.row() for idx in self.table_rendered.selectionModel().selectedRows()}
        rows = sorted(selected_rows) if clicked_row in selected_rows and len(selected_rows) > 1 else [clicked_row]
        paths: list[str] = []
        seen: set[str] = set()
        for row in rows:
            cell = self.table_rendered.item(row, 0)
            if not cell:
                continue
            path = cell.data(Qt.ItemDataRole.UserRole)
            if not path:
                continue
            norm = os.path.normpath(path)
            if norm in seen or not os.path.isfile(path):
                continue
            seen.add(norm)
            paths.append(path)
        return paths

    def _context_menu_rendered_paths_grid(self, pos) -> list[str]:
        item = self.grid_rendered.itemAt(pos)
        if not item:
            return []
        clicked_path = item.data(Qt.ItemDataRole.UserRole + 1)
        selected_items = self.grid_rendered.selectedItems()
        selected_paths = [
            it.data(Qt.ItemDataRole.UserRole + 1) for it in selected_items if it.data(Qt.ItemDataRole.UserRole + 1)
        ]

        if clicked_path in selected_paths and len(selected_paths) > 1:
            candidates = selected_paths
        else:
            candidates = [clicked_path]

        paths: list[str] = []
        seen: set[str] = set()
        for path in candidates:
            if not path:
                continue
            norm = os.path.normpath(path)
            if norm in seen or not os.path.isfile(path):
                continue
            seen.add(norm)
            paths.append(path)
        return paths

    def _populate_rendered_context_menu(self, menu, file_paths: list[str]) -> None:
        count = len(file_paths)
        if count == 0:
            return
        action_open = menu.addAction("📂 Open in folder")
        if count == 1:
            path = file_paths[0]
            meta = self._lookup_rendered_source_meta(path, os.path.basename(path))
            clip_path = (meta.get("clip_path") or "").strip()
            action_source = None
            if clip_path and self._is_valid_clip_path(clip_path):
                action_source = menu.addAction("🎮 Open source clip")
        action_delete = menu.addAction(
            "🗑️ Delete file" if count == 1 else f"🗑️ Delete files ({count})"
        )
        paths_for_delete = list(file_paths)
        if count == 1:
            path = file_paths[0]
            action_open.triggered.connect(lambda _checked=False, p=path: self.open_rendered_folder(p))
            if action_source is not None:
                action_source.triggered.connect(
                    lambda _checked=False, p=clip_path: self.open_source_clip(p)
                )
        else:
            action_open.setEnabled(False)
        action_delete.triggered.connect(
            lambda _checked=False, paths=paths_for_delete: self.delete_rendered_files(paths)
        )

    def show_rendered_grid_context_menu(self, pos) -> None:
        file_paths = self._context_menu_rendered_paths_grid(pos)
        if not file_paths:
            return
        from steempeg.ui import ui_theme as ut

        menu = QMenu(self.grid_rendered)
        menu.setStyleSheet(ut.library_menu_stylesheet())
        self._populate_rendered_context_menu(menu, file_paths)
        menu.exec(self.grid_rendered.viewport().mapToGlobal(pos))

    def show_rendered_table_context_menu(self, pos) -> None:
        file_paths = self._context_menu_rendered_paths_table(pos)
        if not file_paths:
            return
        from steempeg.ui import ui_theme as ut

        menu = QMenu(self.table_rendered)
        menu.setStyleSheet(ut.library_menu_stylesheet())
        self._populate_rendered_context_menu(menu, file_paths)
        menu.exec(self.table_rendered.viewport().mapToGlobal(pos))

    def _handle_rendered_grid_card_context_menu(self, item, event) -> None:
        # RMB only opens the menu (multi-select is Ctrl/Alt/Shift+LMB).
        viewport_pos = self.grid_rendered.viewport().mapFromGlobal(
            event.globalPosition().toPoint()
        )
        self.show_rendered_grid_context_menu(viewport_pos)

    def open_rendered_folder(self, file_path: str) -> None:
        from steempeg.infra.paths import reveal_in_file_manager

        try:
            reveal_in_file_manager(file_path)
        except Exception as exc:
            logging.error("Failed to open rendered folder: %s", exc)

    def _rendered_delete_confirm_copy(self, paths: list[str]) -> tuple[str, str, str]:
        """Title, message, and detail for a rendered-file delete confirmation."""
        if len(paths) == 1:
            name = os.path.basename(paths[0])
            return (
                "Delete rendered file",
                f'Delete "{name}"?',
                "This cannot be undone.",
            )

        max_names = 15
        lines = [f"• {os.path.basename(path)}" for path in paths[:max_names]]
        if len(paths) > max_names:
            lines.append(f"… and {len(paths) - max_names} more")
        detail = "\n".join(lines) + "\n\nThis cannot be undone."
        return (
            "Delete rendered files",
            f"Permanently delete {len(paths)} rendered files?",
            detail,
        )

    def delete_rendered_file(self, file_path: str) -> None:
        self.delete_rendered_files([file_path])

    def delete_rendered_files(self, file_paths: list[str]) -> None:
        paths = [p for p in file_paths if p and os.path.isfile(p)]
        if not paths:
            return
        title, message, detail = self._rendered_delete_confirm_copy(paths)
        confirm = True
        try:
            from steempeg.ui.settings_prefs import load_confirm_before_delete

            settings = {}
            if hasattr(self, "load_user_settings"):
                settings = self.load_user_settings() or {}
            confirm = load_confirm_before_delete(settings)
        except Exception:
            confirm = True
        if confirm and not steempeg_confirm_delete(
            self.ui,
            title,
            message,
            detail=detail,
            delete_label=f"🗑️ Delete ({len(paths)})" if len(paths) > 1 else "🗑️ Delete",
        ):
            return

        # Unload first if any target is the active preview — Windows locks open files.
        if hasattr(self, "release_media_before_delete_any"):
            self.release_media_before_delete_any(paths)

        failed: list[str] = []
        for file_path in paths:
            try:
                os.remove(file_path)
                from steempeg.core.rendered_media import remove_rendered_companion_meta

                remove_rendered_companion_meta(
                    file_path, cache_dir=getattr(self, "cache_dir", None)
                )
            except Exception as exc:
                logging.error("Failed to delete rendered file %s: %s", file_path, exc)
                failed.append(os.path.basename(file_path))

        self._rendered_output_meta_index = None
        self.scan_rendered_outputs()
        self._persist_library_ui_state()

        if failed:
            steempeg_warning(
                self.ui,
                "Delete rendered files",
                f"Deleted {len(paths) - len(failed)} of {len(paths)} file(s).",
                detail="Could not remove:\n" + "\n".join(f"• {name}" for name in failed),
            )

    # --- Hooks that branch when the rendered panel is active ---

    def set_view_mode(self, mode):
        if getattr(self, "_library_panel_mode", "clips") == "screenshots":
            # Screenshots is Grid-only (Emily 13 Aug) — ignore List.
            self._sync_library_view_toggle_for_mode()
            return
        if getattr(self, "_library_panel_mode", "clips") == "rendered":
            self._rendered_view_mode = mode
            self._apply_rendered_view_mode(relayout=True)
            self._schedule_persist_library_ui_state()
            return
        self._clips_view_mode = mode
        from steempeg.ui.library.controller import LibraryMixin
        LibraryMixin.set_view_mode(self, mode, relayout=True)
        self._schedule_persist_library_ui_state()

    def _sync_library_view_toggle_for_mode(self) -> None:
        """Screenshots: Grid-only in the RQ track shell. Clips/Rendered: both segments."""
        mode = getattr(self, "_library_panel_mode", "clips")
        chrome = getattr(self, "view_mode_chrome", None)
        if chrome is not None:
            chrome.set_grid_only(mode == "screenshots")
            if mode == "screenshots":
                chrome.set_mode("grid", emit=False)
            elif mode == "rendered":
                chrome.set_mode(getattr(self, "_rendered_view_mode", "grid"), emit=False)
            else:
                chrome.set_mode(getattr(self, "_clips_view_mode", "grid"), emit=False)
            self.toggle_style_active = chrome.toggle_style_active
            self.toggle_style_inactive = chrome.toggle_style_inactive
            return
        list_btn = getattr(self, "btn_view_list", None)
        grid_btn = getattr(self, "btn_view_grid", None)
        if list_btn is None or grid_btn is None:
            return
        if mode == "screenshots":
            list_btn.hide()
            grid_btn.show()
            grid_btn.setStyleSheet(self.toggle_style_active)
            list_btn.setStyleSheet(self.toggle_style_inactive)
            return
        list_btn.show()
        grid_btn.show()
        if mode == "rendered":
            self._apply_rendered_view_mode()
        else:
            current = getattr(self, "_clips_view_mode", "grid")
            if current == "list":
                list_btn.setStyleSheet(self.toggle_style_active)
                grid_btn.setStyleSheet(self.toggle_style_inactive)
            else:
                grid_btn.setStyleSheet(self.toggle_style_active)
                list_btn.setStyleSheet(self.toggle_style_inactive)

    def apply_sorting(self):
        self._remember_current_panel_sort()
        mode = getattr(self, "_library_panel_mode", "clips")
        if mode == "rendered":
            self.apply_rendered_sorting()
            self._persist_library_ui_state()
            return
        if mode == "screenshots":
            self.apply_screenshots_sorting()
            if not hasattr(self, "_sort_applied_by_panel"):
                self._sort_applied_by_panel = {}
            if hasattr(self, "combo_sort"):
                self._sort_applied_by_panel["screenshots"] = (
                    self._screenshots_global_sort_index()
                )
            menu = getattr(self, "screenshots_filter_menu", None)
            if menu is not None and menu.isVisible() and hasattr(menu, "gather_statistics"):
                menu.gather_statistics(self)
            self._persist_library_ui_state()
            return
        from steempeg.ui.library.controller import LibraryMixin
        LibraryMixin.apply_sorting(self)
        if not hasattr(self, "_sort_applied_by_panel"):
            self._sort_applied_by_panel = {}
        if hasattr(self, "combo_sort"):
            self._sort_applied_by_panel["clips"] = int(self.combo_sort.currentIndex())
        self._persist_library_ui_state()

    def show_filter_menu(self):
        mode = getattr(self, "_library_panel_mode", "clips")
        if mode == "rendered":
            self.show_rendered_filter_menu()
            return
        if mode == "screenshots":
            self.show_screenshots_filter_menu()
            return
        from steempeg.ui.library.controller import LibraryMixin
        LibraryMixin.show_filter_menu(self)

    def refresh_library(self):
        """Main Refresh button: rescan every library tab."""
        self.refresh_all_libraries()
