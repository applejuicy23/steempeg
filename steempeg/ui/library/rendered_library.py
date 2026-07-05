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
    QMessageBox,
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
from steempeg.infra.locale_time import format_clip_date, format_clip_time
from steempeg.ui.library.grid_view import ClipCard
from steempeg.ui.library.library_styles import LIBRARY_GRID_STYLE, LIBRARY_TABLE_STYLE

RENDERED_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
RENDERED_AUDIO_EXTS = {".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg", ".opus"}
RENDERED_ALL_EXTS = RENDERED_VIDEO_EXTS | RENDERED_AUDIO_EXTS

_RENDERED_TYPE_FILTER_ROLE = Qt.ItemDataRole.UserRole + 5
_RENDERED_GAME_FILTER_ROLE = Qt.ItemDataRole.UserRole + 6
_HEALTH_SORT_INDICES = (5, 6)

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
        self._rendered_filter_games: set[str] | None = None
        self._clips_view_mode = "grid"
        self._rendered_view_mode = "grid"
        self._saved_clips_selection_path = ""
        self._saved_rendered_selection_path = ""
        self._library_ui_restored = False
        self._library_ui_persist_ready = False

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

        if hasattr(self, "_sync_sort_combo_for_panel"):
            self._sync_sort_combo_for_panel()

    def _show_add_library_panel_menu(self):
        from steempeg.ui.lifecycle import _LOGS_MENU_STYLE

        menu = QMenu(self.ui)
        menu.setStyleSheet(_LOGS_MENU_STYLE)
        rendered_action = menu.addAction("🎬  Rendered videos")
        if "rendered" in self._library_tabs:
            rendered_action.setEnabled(False)
        pos = self.btn_library_add.mapToGlobal(QPoint(0, self.btn_library_add.height()))
        action = menu.exec(pos)
        if action is rendered_action and action is not None:
            self.open_library_panel("rendered")

    def _sync_sort_combo_for_panel(self):
        if not hasattr(self, "combo_sort"):
            return
        rendered = self._library_panel_mode == "rendered"
        view = self.combo_sort.view()
        for i in _HEALTH_SORT_INDICES:
            view.setRowHidden(i, rendered)
        if rendered and self.combo_sort.currentIndex() in _HEALTH_SORT_INDICES:
            self.combo_sort.blockSignals(True)
            self.combo_sort.setCurrentIndex(0)
            self.combo_sort.blockSignals(False)

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
        if hasattr(self.ui, "table_clips"):
            self.ui.table_clips.blockSignals(True)
            self.ui.table_clips.clearSelection()
            self.ui.table_clips.setCurrentCell(-1, -1)
            self.ui.table_clips.blockSignals(False)
        if hasattr(self, "grid_clips"):
            self.grid_clips.blockSignals(True)
            self.grid_clips.clearSelection()
            self.grid_clips.blockSignals(False)
            if hasattr(self, "_sync_grid_card_visuals"):
                self._sync_grid_card_visuals()

    def _clear_rendered_selection_visual(self) -> None:
        if hasattr(self, "table_rendered"):
            self.table_rendered.blockSignals(True)
            self.table_rendered.clearSelection()
            self.table_rendered.setCurrentCell(-1, -1)
            self.table_rendered.blockSignals(False)
        if hasattr(self, "grid_rendered"):
            self.grid_rendered.blockSignals(True)
            self.grid_rendered.clearSelection()
            self.grid_rendered.blockSignals(False)
            self._sync_rendered_grid_card_visuals()

    def _restore_library_tab_selection(self, tab: str) -> None:
        """Re-paint the saved row highlight after a tab switch (preview keeps playing)."""
        if tab == "rendered":
            path = getattr(self, "_saved_rendered_selection_path", "")
            if path:
                self._highlight_rendered_path(path)
            else:
                self._clear_rendered_selection_visual()
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
                self.table_rendered.blockSignals(True)
                self.table_rendered.selectRow(row)
                self.table_rendered.setCurrentCell(row, 0)
                self.table_rendered.blockSignals(False)
                self._sync_rendered_grid_from_table()
                return True
        return False

    def open_library_panel(self, mode: str):
        if mode == "rendered":
            self._ensure_rendered_tab()
        self.set_library_panel(mode)

    def _ensure_rendered_tab(self):
        self._ensure_rendered_widgets()
        if "rendered" not in self._library_tabs:
            tab = self._make_library_tab_button("🎬 Rendered videos", "rendered")
            idx = self.library_tabs_host.count()
            self.library_tabs_host.insertWidget(idx, tab)
            self._library_tabs["rendered"] = tab
            if not getattr(self, "_restoring_library_state", False):
                self._persist_library_ui_state()

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
        self._library_panel_mode = mode
        for key, btn in self._library_tabs.items():
            btn.setStyleSheet(_LIBRARY_TAB_ACTIVE if key == mode else _LIBRARY_TAB_INACTIVE)
        if hasattr(self, "library_stack"):
            self.library_stack.setCurrentIndex(1 if mode == "rendered" else 0)
        if mode == "rendered":
            self._clear_clips_selection_visual()
            self.scan_rendered_outputs()
            self._apply_rendered_view_mode()
        else:
            self._clear_rendered_selection_visual()
            if hasattr(self, "grid_clips"):
                self.set_view_mode(self._clips_view_mode)
        self._sync_sort_combo_for_panel()
        if old_mode != mode:
            self._restore_library_tab_selection(mode)
        self._update_library_count_label()
        self._sync_library_mode_chrome()
        self._persist_library_ui_state()

    def _sync_library_mode_chrome(self):
        """Hide export settings while previewing finished media, not only on the tab."""
        show_bottom = self._should_show_render_dock()

        if hasattr(self, "bottom_v_wrap"):
            self.bottom_v_wrap.setVisible(show_bottom)
        if hasattr(self, "main_v_splitter") and not (
            getattr(self, "is_theater", False) or getattr(self, "is_fullscreen", False)
        ):
            sizes = self.main_v_splitter.sizes()
            total = sum(sizes) if sum(sizes) > 0 else self.main_v_splitter.height()
            total = max(int(total), 1)
            if show_bottom:
                if len(sizes) >= 2 and sizes[1] <= 0:
                    from steempeg.ui.layout_defaults import DEFAULT_MAIN_V_SPLITTER_SIZES
                    self.main_v_splitter.setSizes(DEFAULT_MAIN_V_SPLITTER_SIZES)
            else:
                self.main_v_splitter.setSizes([total, 0])

    def _is_previewing_rendered_media(self) -> bool:
        if getattr(self, "_rendered_media_path", None):
            return True
        path = getattr(self, "_preview_clip_path", None)
        if path and os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            return ext in RENDERED_ALL_EXTS
        return False

    def _should_show_render_dock(self) -> bool:
        if getattr(self, "is_theater", False) or getattr(self, "is_fullscreen", False):
            return False
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
            for batch in load_history(hist_path):
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
        companion = load_rendered_companion_meta(file_path)
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
        if app_id and hasattr(self, "get_game_icon"):
            self.get_game_icon(app_id)
            cache_icon = os.path.join(self.cache_dir, f"{app_id}.jpg")
            if os.path.isfile(cache_icon):
                return cache_icon
        if fallback and os.path.isfile(fallback):
            return fallback
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
        if panel_mode == "clips" and hasattr(self.ui, "table_clips") and self.ui.table_clips.currentRow() >= 0:
            cell = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0)
            if cell:
                clips_selected = cell.data(Qt.ItemDataRole.UserRole) or ""
        elif panel_mode == "rendered" and hasattr(self, "table_rendered") and self.table_rendered.currentRow() >= 0:
            cell = self.table_rendered.item(self.table_rendered.currentRow(), 0)
            if cell:
                rendered_selected = cell.data(Qt.ItemDataRole.UserRole) or ""

        preview_kind = ""
        preview_path = ""
        if getattr(self, "_rendered_media_path", None):
            preview_kind = "rendered"
            preview_path = self._rendered_media_path
        elif getattr(self, "_preview_clip_path", None):
            path = self._preview_clip_path
            if path and os.path.isfile(path):
                preview_kind = "rendered"
                preview_path = path
            elif path and os.path.isdir(path):
                preview_kind = "clip"
                preview_path = path

        rendered_tab_open = "rendered" in getattr(self, "_library_tabs", {})
        payload = {
            "library_panel_mode": getattr(self, "_library_panel_mode", "clips"),
            "clips_view_mode": getattr(self, "_clips_view_mode", "grid"),
            "rendered_view_mode": getattr(self, "_rendered_view_mode", "grid"),
            "rendered_tab_open": rendered_tab_open,
            "clips_selected_path": clips_selected,
            "rendered_selected_path": rendered_selected,
            "preview_kind": preview_kind,
            "preview_path": preview_path,
        }
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

    def _restore_library_ui_state(self):
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

        if getattr(self, "_library_ui_restored", False):
            if wants_rendered and "rendered" not in self._library_tabs:
                self._ensure_rendered_tab()
            return

        self._saved_clips_selection_path = state.get("clips_selected_path") or ""
        self._saved_rendered_selection_path = state.get("rendered_selected_path") or ""
        self._restoring_library_state = True
        try:
            clips_vm = state.get("clips_view_mode")
            rendered_vm = state.get("rendered_view_mode")
            if clips_vm in ("grid", "list"):
                self._clips_view_mode = clips_vm
            if rendered_vm in ("grid", "list"):
                self._rendered_view_mode = rendered_vm

            mode = state.get("library_panel_mode", "clips")
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
        preview_kind = state.get("preview_kind") or ""
        preview_path = (state.get("preview_path") or "").strip()
        mode = state.get("library_panel_mode", "clips")

        if preview_kind == "rendered" and preview_path and os.path.isfile(preview_path):
            self._select_rendered_path(preview_path, play=True)
        elif preview_kind == "clip" and preview_path and os.path.isdir(preview_path):
            self._select_clip_path(preview_path, play=True)
        elif mode == "rendered":
            rendered_path = (state.get("rendered_selected_path") or "").strip()
            if rendered_path:
                self._select_rendered_path(rendered_path, play=False)
        else:
            clips_path = (state.get("clips_selected_path") or "").strip()
            if clips_path:
                self._select_clip_path(clips_path, play=False)

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

        self.grid_rendered.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid_rendered.viewport().installEventFilter(self)
        self.table_rendered.viewport().installEventFilter(self)

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
        self._rendered_output_meta_index = self._build_rendered_output_meta_index()
        for full, mtime, size, ext in files:
            type_label = _rendered_type_label(ext)
            dt = datetime.fromtimestamp(mtime)
            date_str = format_clip_date(dt)
            time_str = format_clip_time(dt)
            basename = os.path.basename(full)
            display_title, icon_path, _thumb, is_unknown, game_filter_name = self._resolved_rendered_meta(full, basename)
            row = self.table_rendered.rowCount()
            self.table_rendered.insertRow(row)
            list_icon = QIcon(icon_path) if icon_path and os.path.isfile(icon_path) else QIcon()
            if is_unknown:
                from steempeg.infra.paths import get_resource_path
                unknown_icon = get_resource_path("unknown_icon.png")
                if os.path.isfile(unknown_icon):
                    list_icon = QIcon(unknown_icon)
            name_item = QTableWidgetItem(list_icon, f"   {display_title}")
            name_item.setData(Qt.ItemDataRole.UserRole, full)
            name_item.setData(_RENDERED_GAME_FILTER_ROLE, game_filter_name)
            self.table_rendered.setItem(row, 0, name_item)
            type_item = QTableWidgetItem(f"🎬 {type_label}")
            type_item.setData(_RENDERED_TYPE_FILTER_ROLE, type_label)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table_rendered.setItem(row, 1, type_item)
            date_item = QTableWidgetItem(f"{date_str}\n{time_str}")
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table_rendered.setItem(row, 2, date_item)
            size_item = QTableWidgetItem(_format_file_size(size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.table_rendered.setItem(row, 3, size_item)
            name_item.setToolTip(full)
            if self._row_hidden_by_rendered_filters(game_filter_name, type_label):
                self.table_rendered.setRowHidden(row, True)

        self.build_rendered_grid()
        self._update_library_count_label()

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

        if app_id and game_name:
            title = game_name if is_default_rendered_basename(stem, str(app_id)) else stem
        else:
            title = game_name or stem

        is_unknown = not bool(app_id)
        if app_id and not game_name and hasattr(self, "get_game_name"):
            game_name = self.get_game_name(str(app_id)) or ""

        thumb_path = ""
        ext = os.path.splitext(file_path)[1].lower()
        if ext in RENDERED_VIDEO_EXTS and hasattr(self, "cache_dir"):
            thumb_path = extract_poster_frame(file_path, self.cache_dir)
        game_filter_name = game_name if game_name else "Unknown"
        return title, icon_path, thumb_path, is_unknown, game_filter_name

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
            display_title, icon_path, thumb_path, is_unknown, _game_key = self._resolved_rendered_meta(
                file_path, os.path.basename(file_path)
            )
            badge = type_item.text().replace("🎬 ", "").strip() if type_item else "FILE"
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
                on_left_click=lambda ev, grid_item=item: self._rendered_grid_select_item(grid_item),
                on_right_click=lambda ev, grid_item=item: self._handle_rendered_grid_card_context_menu(grid_item, ev),
            )
            self.grid_rendered.setItemWidget(item, card)
            if self.table_rendered.isRowHidden(row):
                item.setHidden(True)

        self._sync_rendered_grid_from_table()

    def _sync_rendered_grid_card_visuals(self) -> None:
        """Paint selection border on rendered ClipCard widgets — current row only."""
        if not hasattr(self, "grid_rendered"):
            return
        highlight_row = -1
        if (
            getattr(self, "_library_panel_mode", "clips") == "rendered"
            and hasattr(self, "table_rendered")
        ):
            highlight_row = self.table_rendered.currentRow()
        for i in range(self.grid_rendered.count()):
            item = self.grid_rendered.item(i)
            card = self.grid_rendered.itemWidget(item)
            if isinstance(card, ClipCard):
                row = item.data(Qt.ItemDataRole.UserRole)
                card.set_selected(row == highlight_row and highlight_row >= 0)

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
        elif idx in (7, 8):
            rows.sort(key=lambda r: cell(r, 2))
            if idx == 8:
                rows.reverse()
        elif idx in (9, 10):
            rows.sort(key=lambda r: os.path.getsize(path(r)) if path(r) and os.path.exists(path(r)) else 0)
            if idx == 10:
                rows.reverse()
        elif idx in _HEALTH_SORT_INDICES:
            pass

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
        from steempeg.ui.library.rendered_filters import RenderedFilterMenu

        if hasattr(self, "rendered_filter_menu") and self.rendered_filter_menu:
            self.rendered_filter_menu.deleteLater()

        self.rendered_filter_menu = RenderedFilterMenu(self.ui)
        self.rendered_filter_menu.gather_statistics(self)
        self._position_rendered_filter_menu()
        self.rendered_filter_menu.show()
        QTimer.singleShot(0, self._position_rendered_filter_menu)

    def _position_rendered_filter_menu(self):
        menu = getattr(self, "rendered_filter_menu", None)
        if not menu or not hasattr(self, "btn_filter_pill"):
            return
        btn = self.btn_filter_pill
        menu_x = btn.mapToGlobal(QPoint(0, 0)).x()
        menu_y = btn.mapToGlobal(QPoint(0, btn.height())).y()
        menu.move(menu_x, menu_y)
        if hasattr(self, "btn_refresh"):
            footer_top = self.btn_refresh.mapToGlobal(QPoint(0, 0)).y()
            menu.set_content_max_height(max(160, footer_top - menu_y - 8))

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
        if hasattr(self, "_clear_clips_selection_visual"):
            self._clear_clips_selection_visual()
        self._saved_clips_selection_path = ""
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
        self._saved_rendered_selection_path = file_path or ""
        type_label = self.table_rendered.item(row, 1).text() if self.table_rendered.item(row, 1) else ""
        type_clean = type_label.replace("🎬 ", "").strip()
        date_str = self.table_rendered.item(row, 2).text() if self.table_rendered.item(row, 2) else ""
        size_str = self.table_rendered.item(row, 3).text() if self.table_rendered.item(row, 3) else ""

        self._preview_clip_path = file_path
        self._selected_queue_job_id = None
        self._rendered_media_path = file_path

        display_title, icon_path, _thumb, is_unknown, _game_key = self._resolved_rendered_meta(
            file_path, os.path.basename(file_path)
        )

        if hasattr(self, "custom_text_label"):
            unknown_tag = (
                " <span style='color: #888888;'>&nbsp;&nbsp;•&nbsp;&nbsp; Unknown</span>"
                if is_unknown else ""
            )
            header_html = (
                f"<b>{display_title}</b>{unknown_tag} <span style='color: #888;'>&nbsp;&nbsp;•&nbsp;&nbsp; "
                f"{type_clean} &nbsp;&nbsp;•&nbsp;&nbsp; {date_str} &nbsp;&nbsp;•&nbsp;&nbsp; {size_str}</span>"
            )
            self.custom_text_label.setText(header_html)
        if hasattr(self, "custom_icon_label"):
            self.custom_icon_label.setStyleSheet("background: transparent; border: none;")
            if icon_path and os.path.isfile(icon_path):
                from PySide6.QtGui import QPixmap
                self.custom_icon_label.setPixmap(QPixmap(icon_path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            elif is_unknown:
                from steempeg.infra.paths import get_resource_path
                from PySide6.QtGui import QPixmap
                unknown = get_resource_path("unknown_icon.png")
                if os.path.isfile(unknown):
                    self.custom_icon_label.setPixmap(QPixmap(unknown).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                else:
                    self.custom_icon_label.clear()
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
        if not clicked_path:
            return []
        return [clicked_path] if os.path.isfile(clicked_path) else []

    def _populate_rendered_context_menu(self, menu, file_paths: list[str]) -> None:
        count = len(file_paths)
        if count == 0:
            return
        action_open = menu.addAction("📂 Open in folder")
        action_delete = menu.addAction(
            "🗑️ Delete file" if count == 1 else f"🗑️ Delete files ({count})"
        )
        if count == 1:
            path = file_paths[0]
            action_open.triggered.connect(lambda: self.open_rendered_folder(path))
            action_delete.triggered.connect(lambda: self.delete_rendered_file(path))
        else:
            action_open.setEnabled(False)
            action_delete.triggered.connect(lambda: self.delete_rendered_files(file_paths))

    def show_rendered_grid_context_menu(self, pos) -> None:
        file_paths = self._context_menu_rendered_paths_grid(pos)
        if not file_paths:
            return
        from steempeg.ui.library.controller import _LIBRARY_MENU_STYLE

        menu = QMenu(self.grid_rendered)
        menu.setStyleSheet(_LIBRARY_MENU_STYLE)
        self._populate_rendered_context_menu(menu, file_paths)
        menu.exec(self.grid_rendered.viewport().mapToGlobal(pos))

    def show_rendered_table_context_menu(self, pos) -> None:
        file_paths = self._context_menu_rendered_paths_table(pos)
        if not file_paths:
            return
        from steempeg.ui.library.controller import _LIBRARY_MENU_STYLE

        menu = QMenu(self.table_rendered)
        menu.setStyleSheet(_LIBRARY_MENU_STYLE)
        self._populate_rendered_context_menu(menu, file_paths)
        menu.exec(self.table_rendered.viewport().mapToGlobal(pos))

    def _handle_rendered_grid_card_context_menu(self, item, event) -> None:
        viewport_pos = self.grid_rendered.viewport().mapFromGlobal(event.globalPosition().toPoint())
        self.show_rendered_grid_context_menu(viewport_pos)

    def open_rendered_folder(self, file_path: str) -> None:
        try:
            folder = os.path.dirname(file_path)
            if folder:
                os.startfile(folder)
        except Exception as exc:
            logging.error("Failed to open rendered folder: %s", exc)

    def delete_rendered_file(self, file_path: str) -> None:
        self.delete_rendered_files([file_path])

    def delete_rendered_files(self, file_paths: list[str]) -> None:
        paths = [p for p in file_paths if p and os.path.isfile(p)]
        if not paths:
            return
        msg = QMessageBox(self.ui)
        msg.setWindowTitle("Delete rendered file" if len(paths) == 1 else "Delete rendered files")
        msg.setText(
            "Delete this rendered file?" if len(paths) == 1 else f"Delete {len(paths)} rendered files?"
        )
        msg.setInformativeText("This cannot be undone.")
        msg.setIcon(QMessageBox.Icon.Warning)
        btn_delete = msg.addButton("🗑️ Delete", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() != btn_delete:
            return

        playing = getattr(self, "_rendered_media_path", None) or getattr(self, "_preview_clip_path", None)
        for file_path in paths:
            try:
                if playing and os.path.normpath(playing) == os.path.normpath(file_path):
                    if hasattr(self, "close_current_clip"):
                        self.close_current_clip()
                    elif hasattr(self, "player") and self.player:
                        self.player.pause = True
                os.remove(file_path)
                from steempeg.core.rendered_media import companion_meta_path

                meta_sidecar = companion_meta_path(file_path)
                if os.path.isfile(meta_sidecar):
                    os.remove(meta_sidecar)
            except Exception as exc:
                logging.error("Failed to delete rendered file %s: %s", file_path, exc)
                QMessageBox.critical(self.ui, "Error", f"Could not delete:\n{file_path}\n\n{exc}")
                return

        self._rendered_output_meta_index = None
        self.scan_rendered_outputs()
        self._persist_library_ui_state()

    # --- Hooks that branch when the rendered panel is active ---

    def set_view_mode(self, mode):
        if getattr(self, "_library_panel_mode", "clips") == "rendered":
            self._rendered_view_mode = mode
            self._apply_rendered_view_mode()
            self._persist_library_ui_state()
            return
        self._clips_view_mode = mode
        from steempeg.ui.library.controller import LibraryMixin
        LibraryMixin.set_view_mode(self, mode)
        self._persist_library_ui_state()

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
