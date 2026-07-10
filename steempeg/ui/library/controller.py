"""Clip library: grid/list view, context menus, scanning, filtering and metadata.

Mixed into the main application. These methods populate and refresh the clip
library, drive the right-click menus and clip deletion, handle sorting/filtering,
resolve game names and icons, and let the user choose the clips folder. They run on
the application instance and reach its widgets and state through self.
"""
import logging
import os
import re
import shutil
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QPoint, QSize, QTimer, QItemSelection, QItemSelectionModel
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QWidget,
    QWidgetAction,
)

from steempeg.ui.icon_assets import health_icon
from steempeg.core import games
from steempeg.core.clip_identity import (
    dedupe_steam_session_folders,
    folder_has_video_chunks,
    is_nested_same_session,
    steam_session_key,
)
from steempeg.core.clip_thumbnails import find_clip_thumbnail
from steempeg.core.dash import discovery, health, mpd
from steempeg.core.steam_paths import (
    default_clips_dialog_path,
    discover_steam_clips_folders,
    steam_id_from_clips_folder,
)
from steempeg.infra.locale_time import format_clip_date, format_clip_time, parse_clip_datetime_text
from steempeg.infra import cache as json_cache
from steempeg.ui.library.filters import FilterMenu
from steempeg.ui.library.grid_view import ClipCard


_LIBRARY_MENU_STYLE = """
    QMenu {
        background-color: #2d2d2d;
        color: #ffffff;
        border: 2px solid #444444;
        border-radius: 8px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 13px;
        font-weight: bold;
    }
    QMenu::item {
        padding: 6px 24px 6px 24px;
        border-radius: 4px;
        margin: 2px 4px;
    }
    QMenu::item:selected {
        background-color: #6b5a8e;
    }
    QMenu::separator {
        height: 1px;
        background-color: #444444;
        margin: 4px 10px;
    }
"""

_HEALTH_MENU_STYLE = _LIBRARY_MENU_STYLE + """
    QMenu::item {
        padding: 8px 28px 8px 12px;
    }
    /* Disabled rows must keep icon color (Healthy green / Issues amber / Dead red).
       Default QMenu greys out icons on setEnabled(False), which made the health
       glyph look B&W and sit in the far-left reserved icon column. */
    QMenu::item:disabled {
        color: #e0e0e0;
        background: transparent;
    }
"""


_FOLDERS_MENU_STYLE = """
    QMenu {
        background-color: #2d2d2d;
        color: #ffffff;
        border: 2px solid #444444;
        border-radius: 8px;
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 13px;
        font-weight: bold;
        padding: 4px 0;
    }
    QMenu::item {
        padding: 8px 28px 8px 20px;
        border-radius: 4px;
        margin: 2px 6px;
    }
    QMenu::item:selected {
        background-color: #3a324a;
        color: #b29ae7;
    }
    QMenu::separator {
        height: 1px;
        background: #444444;
        margin: 4px 10px;
    }
    QLabel#FolderRowLabel {
        color: #dddddd;
        font-size: 12px;
        font-weight: normal;
        background: transparent;
        padding: 2px 0;
    }
    QLabel#FolderRowLabel[missing="true"] {
        color: #d46a6a;
    }
    QPushButton#FolderRowRemove, QPushButton#FolderRowReplace {
        background-color: #333333;
        color: #cccccc;
        border: 1px solid #555555;
        border-radius: 10px;
        font-size: 11px;
        font-weight: bold;
        min-width: 20px;
        max-width: 20px;
        min-height: 20px;
        max-height: 20px;
        padding: 0;
    }
    QPushButton#FolderRowRemove:hover {
        background-color: #8a2525;
        border: 1px solid #a82e2e;
        color: #ffffff;
    }
    QPushButton#FolderRowRemove:pressed {
        background-color: #661a1a;
    }
    QPushButton#FolderRowReplace:hover {
        background-color: #3a324a;
        border: 1px solid #6b5a8e;
        color: #d4c4ff;
    }
    QPushButton#FolderRowReplace:pressed {
        background-color: #2d2640;
    }
"""


_CLIP_HEALTH_ROLE = Qt.UserRole + 2
_CLIP_HEALTH_ISSUES_ROLE = Qt.UserRole + 3


class LibraryMixin:
    # --- Clip health cache (mtime-keyed, persisted between sessions) ---
    def _clip_health_cache_path(self):
        return os.path.join(self.cache_dir, "clip_health_cache.json")

    def _ensure_clip_health_cache(self):
        if not hasattr(self, "_clip_health_cache"):
            self._clip_health_cache = json_cache.read_json(self._clip_health_cache_path(), default={})

    def _save_clip_health_cache(self):
        self._ensure_clip_health_cache()
        json_cache.write_json(self._clip_health_cache_path(), self._clip_health_cache)

    def _resolve_clip_health(
        self, full_path: str, *, fast: bool, force: bool = False
    ) -> health.ClipHealthReport:
        """Return clip health, using disk cache on fast rescans."""
        self._ensure_clip_health_cache()
        norm = os.path.normpath(full_path)
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            mtime = 0.0

        if not force:
            entry = self._clip_health_cache.get(norm)
            if entry and entry.get("mtime") == mtime:
                try:
                    level = health.ClipHealth(entry["level"])
                except ValueError:
                    level = health.ClipHealth.DEAD
                return health.ClipHealthReport(level, list(entry.get("issues") or []))

        report = health.assess_clip_health(full_path, probe=not fast)
        self._clip_health_cache[norm] = {
            "mtime": mtime,
            "level": report.level.value,
            "issues": report.issues,
        }
        self._save_clip_health_cache()
        return report

    def _collect_library_app_ids(self):
        """Unique Steam app ids currently listed in the clips table."""
        ids = set()
        if not hasattr(self.ui, "table_clips"):
            return ids
        for row in range(self.ui.table_clips.rowCount()):
            item = self.ui.table_clips.item(row, 0)
            if not item:
                continue
            clip_path = item.data(Qt.UserRole)
            if not clip_path:
                continue
            parts = os.path.basename(clip_path).split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                ids.add(parts[1])
        return ids

    def setup_refresh_menu(self):
        """Attach the Refresh ▾ dropdown (Steam icons, health re-check, …)."""
        btn = getattr(self, "btn_refresh", None)
        if btn is None or not hasattr(btn, "menu_btn"):
            return
        menu = QMenu(self.ui)
        menu.setStyleSheet(_LIBRARY_MENU_STYLE)

        action_icons = menu.addAction("🖼️  Refresh game icons from Steam…")
        action_names = menu.addAction("🏷️  Refresh game names from Steam…")
        menu.addSeparator()
        action_health = menu.addAction("🩺  Re-check clip health (ffprobe)…")

        action_icons.setToolTip(
            "Re-downloads icons for games in your library. Uses the Steam CDN — run only when icons look wrong."
        )
        action_names.setToolTip(
            "Re-fetches display names from the Steam store API. Uses network — run only when a title is wrong."
        )
        action_health.setToolTip(
            "Runs a full playback health pass (may call ffprobe per clip). Does not rescan folders."
        )

        action_icons.triggered.connect(self.refresh_steam_icons)
        action_names.triggered.connect(self.refresh_steam_names)
        action_health.triggered.connect(self.recheck_clip_health)

        def _show_menu():
            menu.exec(btn.menu_btn.mapToGlobal(QPoint(0, btn.menu_btn.height())))

        btn.menu_btn.clicked.connect(_show_menu)

    def refresh_steam_icons(self):
        """Re-download game icons for every app id in the current library list."""
        app_ids = sorted(self._collect_library_app_ids())
        if not app_ids:
            return
        self.game_icons_cache.clear()
        updated = 0
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for app_id in app_ids:
                icon_path = os.path.join(self.cache_dir, f"{app_id}.jpg")
                try:
                    if os.path.isfile(icon_path):
                        os.remove(icon_path)
                except OSError:
                    pass
                if games.download_icon(app_id, icon_path):
                    updated += 1
        finally:
            QApplication.restoreOverrideCursor()

        for row in range(self.ui.table_clips.rowCount()):
            item = self.ui.table_clips.item(row, 0)
            if not item:
                continue
            clip_path = item.data(Qt.UserRole)
            if not clip_path:
                continue
            parts = os.path.basename(clip_path).split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                item.setIcon(self.get_game_icon(parts[1], allow_download=False))

        if hasattr(self, "build_netflix_grid"):
            self.build_netflix_grid()
        if hasattr(self, "set_status"):
            self.set_status(
                f"Refreshed {updated} of {len(app_ids)} game icon(s) from Steam."
            )

    def refresh_steam_names(self):
        """Re-fetch game names from Steam for every app id in the library list."""
        app_ids = sorted(self._collect_library_app_ids())
        if not app_ids:
            return
        updated = 0
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for app_id in app_ids:
                name = games.fetch_game_name(app_id)
                if name:
                    self.game_names_cache[app_id] = name
                    updated += 1
        finally:
            QApplication.restoreOverrideCursor()
        self.save_json_cache()

        for row in range(self.ui.table_clips.rowCount()):
            item = self.ui.table_clips.item(row, 0)
            if not item:
                continue
            clip_path = item.data(Qt.UserRole)
            if not clip_path:
                continue
            parts = os.path.basename(clip_path).split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                app_id = parts[1]
                raw_name = self.get_game_name(app_id, allow_fetch=False)
                item.setText(f"   {raw_name}")

        if hasattr(self, "build_netflix_grid"):
            self.build_netflix_grid()
        if hasattr(self, "set_status"):
            self.set_status(
                f"Refreshed {updated} of {len(app_ids)} game name(s) from Steam."
            )

    def recheck_clip_health(self):
        """Full health pass for listed clips (ffprobe when needed). Keeps selection and filters."""
        if not hasattr(self.ui, "table_clips"):
            return
        rows = self.ui.table_clips.rowCount()
        if rows == 0:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for row in range(rows):
                item = self.ui.table_clips.item(row, 0)
                if not item:
                    continue
                clip_path = item.data(Qt.UserRole)
                if not clip_path or not os.path.isdir(clip_path):
                    continue
                report = self._resolve_clip_health(clip_path, fast=False, force=True)
                item.setData(_CLIP_HEALTH_ROLE, report.level.value)
                item.setData(_CLIP_HEALTH_ISSUES_ROLE, "\n".join(report.issues))
        finally:
            QApplication.restoreOverrideCursor()

        if hasattr(self, "build_netflix_grid"):
            self.build_netflix_grid()
        if hasattr(self, "update_clip_health_button"):
            self.update_clip_health_button()
        if hasattr(self, "set_status"):
            self.set_status(f"Re-checked health for {rows} clip(s).")

    @staticmethod
    def _folder_has_dash_recording(folder_path: str, max_depth: int = 4) -> bool:
        """True when a folder itself (within a few levels) contains DASH manifests/chunks."""
        if not folder_path or not os.path.isdir(folder_path):
            return False
        base_depth = os.path.normpath(folder_path).count(os.sep)
        for root, dirs, files in os.walk(folder_path):
            depth = root.count(os.sep) - base_depth
            if depth > max_depth:
                dirs.clear()
                continue
            if any(name.endswith(".mpd") for name in files):
                return True
            if any("chunk-stream" in name for name in files):
                return True
        return False

    @staticmethod
    def _is_steam_clip_container_folder(folder_path: str) -> bool:
        """Steam wrapper ``<appid>_<date>_<time>/clips/fg_…`` — not a clip itself."""
        if not folder_path or not os.path.isdir(folder_path):
            return False
        base = os.path.basename(folder_path).lower()
        if base.startswith(("clip_", "bg_", "fg_")):
            return False
        parts = base.split("_")
        if not (len(parts) == 3 and parts[0].isdigit() and len(parts[1]) == 8 and parts[2].isdigit()):
            return False
        for sub in ("clips", "video"):
            sub_path = os.path.join(folder_path, sub)
            if not os.path.isdir(sub_path):
                continue
            try:
                for item in os.listdir(sub_path):
                    if item.lower().startswith(("clip_", "bg_", "fg_")):
                        return True
            except OSError:
                pass
        return False

    @staticmethod
    def _is_clip_library_root(folder_path: str) -> bool:
        """Folder that groups recordings (``CLIPS``, ``clips``, …) — not a clip itself."""
        if not folder_path or not os.path.isdir(folder_path):
            return False
        base = os.path.basename(folder_path).lower()
        if base in ("clips", "video", "gamerecordings"):
            return True
        try:
            entries = [
                name
                for name in os.listdir(folder_path)
                if os.path.isdir(os.path.join(folder_path, name))
            ]
        except OSError:
            return False
        if not entries:
            return False
        steam_like = [n for n in entries if n.lower().startswith(("clip_", "bg_", "fg_"))]
        return len(steam_like) == len(entries)

    def _looks_like_single_clip_folder(self, folder_path: str) -> bool:
        if self._is_steam_clip_container_folder(folder_path):
            return False
        if self._is_clip_library_root(folder_path):
            return False
        name = os.path.basename(folder_path).lower()
        if name.startswith(("clip_", "bg_", "fg_")):
            return True
        return self._folder_has_dash_recording(folder_path)

    def _context_menu_clip_paths_table(self, pos) -> list:
        item = self.ui.table_clips.itemAt(pos)
        if not item:
            return []

        clicked_row = item.row()
        selected_rows = {idx.row() for idx in self.ui.table_clips.selectionModel().selectedRows()}
        if clicked_row in selected_rows and len(selected_rows) > 1:
            rows = sorted(selected_rows)
        else:
            rows = [clicked_row]

        paths = []
        seen = set()
        for row in rows:
            cell = self.ui.table_clips.item(row, 0)
            if not cell:
                continue
            path = cell.data(Qt.UserRole)
            if not path:
                continue
            norm = os.path.normpath(path)
            if norm in seen or not os.path.exists(path):
                continue
            seen.add(norm)
            paths.append(path)
        return paths

    def _context_menu_clip_paths_grid(self, pos) -> list:
        item = self.grid_clips.itemAt(pos)
        if not item:
            return []

        clicked_path = item.data(Qt.UserRole + 1)
        selected_items = self.grid_clips.selectedItems()
        selected_paths = [
            it.data(Qt.UserRole + 1) for it in selected_items if it.data(Qt.UserRole + 1)
        ]

        if clicked_path in selected_paths and len(selected_paths) > 1:
            candidates = selected_paths
        else:
            candidates = [clicked_path]

        paths = []
        seen = set()
        for path in candidates:
            if not path:
                continue
            norm = os.path.normpath(path)
            if norm in seen or not os.path.exists(path):
                continue
            seen.add(norm)
            paths.append(path)
        return paths

    def get_clip_health_report(self, clip_path) -> health.ClipHealthReport:
        """Return cached scan-time health for a clip path, or assess on demand."""
        if not clip_path or not hasattr(self.ui, "table_clips"):
            return health.assess_clip_health(clip_path or "")

        norm = os.path.normpath(clip_path)
        table = self.ui.table_clips
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if not item:
                continue
            row_path = item.data(Qt.UserRole)
            if row_path and os.path.normpath(row_path) == norm:
                level = item.data(_CLIP_HEALTH_ROLE)
                issues_raw = item.data(_CLIP_HEALTH_ISSUES_ROLE) or ""
                if level:
                    issues = [line for line in issues_raw.split("\n") if line]
                    try:
                        enum_level = health.ClipHealth(level)
                    except ValueError:
                        enum_level = health.ClipHealth.DEAD
                    return health.ClipHealthReport(enum_level, issues)
                break
        return health.assess_clip_health(clip_path)

    def _clip_is_dead(self, clip_path) -> bool:
        return self.get_clip_health_report(clip_path).level == health.ClipHealth.DEAD

    def _iter_dead_clip_paths(self) -> list:
        if not hasattr(self.ui, "table_clips"):
            return []
        paths = []
        seen = set()
        for row in range(self.ui.table_clips.rowCount()):
            item = self.ui.table_clips.item(row, 0)
            if not item:
                continue
            if item.data(_CLIP_HEALTH_ROLE) != health.ClipHealth.DEAD.value:
                continue
            path = item.data(Qt.UserRole)
            if not path:
                continue
            norm = os.path.normpath(path)
            if norm in seen:
                continue
            seen.add(norm)
            paths.append(path)
        return paths

    def delete_all_dead_clips(self):
        """Remove every clip classified as dead from disk and refresh the library."""
        dead_paths = self._iter_dead_clip_paths()
        if not dead_paths:
            QMessageBox.information(self.ui, "Dead Clips", "No dead clips in the library.")
            return

        reply = QMessageBox.question(
            self.ui,
            "Delete ALL Dead Clips",
            f"Permanently delete {len(dead_paths)} dead clip folder(s)?\n"
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        current = getattr(self, "_preview_clip_path", None)
        if current:
            current = os.path.normpath(current)

        failed = []
        for clip_path in dead_paths:
            norm = os.path.normpath(clip_path)
            try:
                if current and norm == current:
                    if hasattr(self, "close_current_clip"):
                        self.close_current_clip()
                    elif hasattr(self, "_clear_player_surface"):
                        self._clear_player_surface()
                    current = None
                if os.path.exists(clip_path):
                    shutil.rmtree(clip_path)
                    logging.info(f"Deleted dead clip folder: {clip_path}")
            except Exception as exc:
                logging.error(f"Failed to delete dead clip {clip_path}: {exc}")
                failed.append(os.path.basename(clip_path))

        self.scan_clips()

        if failed:
            QMessageBox.warning(
                self.ui,
                "Delete ALL Dead Clips",
                f"Deleted {len(dead_paths) - len(failed)} of {len(dead_paths)}.\n"
                f"Could not remove: {', '.join(failed)}",
            )
        else:
            QMessageBox.information(
                self.ui,
                "Delete ALL Dead Clips",
                f"Removed {len(dead_paths)} dead clip(s).",
            )

    def update_clip_health_button(self):
        if not hasattr(self, "btn_clip_health"):
            return

        if getattr(self, "_library_panel_mode", "clips") == "rendered":
            self.btn_clip_health.hide()
            return

        clip_path = None
        if hasattr(self, "_current_header_clip_path"):
            clip_path = self._current_header_clip_path()
        if not clip_path and hasattr(self.ui, "table_clips") and self.ui.table_clips.currentRow() >= 0:
            item = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0)
            if item:
                clip_path = item.data(Qt.UserRole)

        if not clip_path or (clip_path and os.path.isfile(clip_path)):
            self.btn_clip_health.hide()
            return

        report = self.get_clip_health_report(clip_path)
        color = report.color
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        self.btn_clip_health.setToolTip(report.summary())
        self.btn_clip_health.setIcon(health_icon(report.level, 18))
        self.btn_clip_health.setIconSize(QSize(18, 18))
        self.btn_clip_health.setText(f" {report.label}")
        self.btn_clip_health.setStyleSheet(
            f"QPushButton {{"
            f"background-color: rgba({r}, {g}, {b}, 0.22);"
            f"color: {color};"
            f"border: 2px solid {color};"
            f"border-radius: 8px;"
            f"font-weight: bold;"
            f"font-size: 13px;"
            f"padding: 2px 10px 2px 8px;"
            f"font-family: 'Segoe UI';"
            f"}}"
            f"QPushButton:hover {{ background-color: rgba({r}, {g}, {b}, 0.35); }}"
        )
        self.btn_clip_health.show()

    def show_clip_health_menu(self):
        clip_path = None
        if hasattr(self, "_current_header_clip_path"):
            clip_path = self._current_header_clip_path()
        if not clip_path and hasattr(self.ui, "table_clips") and self.ui.table_clips.currentRow() >= 0:
            item = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0)
            if item:
                clip_path = item.data(Qt.UserRole)
        if not clip_path:
            return

        report = self.get_clip_health_report(clip_path)
        menu = QMenu(self.ui)
        menu.setStyleSheet(_HEALTH_MENU_STYLE)

        # Title row as a widget: icon sits next to the label (not a reserved muted
        # left column), and keeps full color even though the row is non-clickable.
        title_host = QWidget(menu)
        title_row = QHBoxLayout(title_host)
        title_row.setContentsMargins(12, 8, 16, 8)
        title_row.setSpacing(8)
        title_icon = QLabel()
        title_icon.setPixmap(health_icon(report.level, 16).pixmap(16, 16))
        title_icon.setFixedSize(16, 16)
        title_lbl = QLabel(report.label)
        title_lbl.setStyleSheet(
            f"color: {report.color}; font-weight: bold; font-size: 13px;"
            f" font-family: 'Segoe UI'; background: transparent;"
        )
        title_row.addWidget(title_icon, 0, Qt.AlignVCenter)
        title_row.addWidget(title_lbl, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        title_act = QWidgetAction(menu)
        title_act.setDefaultWidget(title_host)
        # Keep enabled so Qt doesn't desaturate the row into greyscale.
        # No trigger is connected, so it still behaves like a visual header.
        title_act.setEnabled(True)
        menu.addAction(title_act)
        menu.addSeparator()

        if report.issues:
            for issue in report.issues:
                act = menu.addAction(f"• {issue}")
                act.setEnabled(False)
        else:
            act = menu.addAction("No issues detected.")
            act.setEnabled(False)

        if report.level == health.ClipHealth.DEAD:
            menu.addSeparator()
            force_act = menu.addAction("▶️ Force play (salvage)")
            force_act.setToolTip(
                "Best-effort attempt to decode surviving chunks. May show corrupted "
                "video, audio only, or nothing — the clip stays marked Dead."
            )
            force_act.triggered.connect(lambda: self.force_play_dead_clip(clip_path))

            delete_act = menu.addAction("🗑️ Delete clip")
            delete_act.triggered.connect(lambda: self.delete_clip(clip_path))

            dead_count = len(self._iter_dead_clip_paths())
            if dead_count > 0:
                menu.addSeparator()
                bulk_act = menu.addAction(f"🗑️ Delete ALL dead clips ({dead_count})")
                bulk_act.triggered.connect(self.delete_all_dead_clips)

        menu.exec(self.btn_clip_health.mapToGlobal(QPoint(0, self.btn_clip_health.height())))

    def force_play_dead_clip(self, clip_path: str) -> None:
        """Best-effort salvage preview for a dead clip (user-initiated gamble).

        Tries to synthesize a manifest from surviving chunks when none is playable,
        then forces playback bypassing the dead-clip guard. The clip's health is left
        untouched — a successful force-play does not re-classify it."""
        if not clip_path or not os.path.isdir(clip_path):
            return

        confirm = QMessageBox.question(
            self.ui,
            "Force play dead clip",
            "This clip is classified as Dead.\n\n"
            "Steempeg can rebuild a salvage manifest from surviving chunks. "
            "If this clip's own decoder header (init) is missing or corrupt, "
            "recovery needs one healthy donor clip of the same game already in your library. "
            "Without that donor, salvage usually cannot work.\n\n"
            "You may see garbled video, only audio, or nothing. "
            "If it plays, the clip stays labelled Dead but can be rendered.\n\n"
            "Try anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Always rebuild a fresh salvage manifest from the *decodable* data on disk
        # (valid init-stream0 + non-empty chunks). We deliberately ignore any stale
        # session_recovered.mpd — playing that when the init is corrupt just opens an
        # empty stream (0 frames / black). recover_orphaned_clip bails without a valid
        # init, so a None result means there is genuinely nothing to decode.
        mpd_override = self._build_salvage_manifest(clip_path)

        if not mpd_override:
            QMessageBox.warning(
                self.ui,
                "Nothing to salvage",
                "Could not recover this clip.\n\n"
                "Either there are no usable video chunks, or the decoder header is gone "
                "and no healthy donor clip of the same game is in your library.\n\n"
                "Add at least one working clip of this game, then try Force play (salvage) again. "
                "Without a same-game donor, this dead clip cannot be revived.",
            )
            return

        # Register so get_all_mpd_paths resolves the salvage manifest everywhere
        # (preview + render), then populate render settings from it so the revived
        # clip is renderable. Health stays Dead — this is an explicit user salvage.
        self._register_salvaged_clip(clip_path)
        self.generate_and_play_preview(clip_path, force=True, mpd_override=mpd_override)
        if hasattr(self, "_populate_quality_options_for_clip"):
            self._populate_quality_options_for_clip(clip_path)

    def _register_salvaged_clip(self, clip_path: str) -> None:
        """Remember a clip's built salvage manifests so they resolve for render."""
        if not hasattr(self, "_salvaged_clips"):
            self._salvaged_clips = {}
        mpds = []
        for root, _dirs, files in os.walk(clip_path):
            if "session_salvage.mpd" in files:
                mpds.append(os.path.join(root, "session_salvage.mpd"))
        if mpds:
            self._salvaged_clips[os.path.normpath(clip_path)] = sorted(mpds)

    def _is_salvaged_clip(self, clip_path: str) -> bool:
        return os.path.normpath(clip_path) in getattr(self, "_salvaged_clips", {})

    def _build_salvage_manifest(self, clip_path: str):
        """Write a scanner-invisible salvage manifest from orphaned chunks.

        For a folder whose own init-stream0 is missing/corrupt, borrow a valid init
        from a healthy clip of the same game (Steam records with consistent per-title
        encoder settings, so the SPS/PPS usually matches). The borrowed init is copied
        in as init-stream0-salvage.m4s (non-destructive) and referenced by the salvage
        manifest. Returns the manifest path, or None if there is nothing to decode."""
        from steempeg.core.dash import repair
        from steempeg.core.rendered_media import parse_app_id_from_clip_folder

        app_id = parse_app_id_from_clip_folder(os.path.basename(clip_path))
        donor_init = None  # resolved lazily, only if some folder needs it

        for root, _dirs, files in os.walk(clip_path):
            if not any(f.startswith("chunk-stream0-") and f.endswith(".m4s") for f in files):
                continue

            own_init = os.path.join(root, "init-stream0.m4s")
            own_ok = os.path.isfile(own_init) and os.path.getsize(own_init) >= 100

            try:
                if own_ok:
                    path = repair.recover_orphaned_clip(
                        root, out_name="session_salvage.mpd", probe_resolution=True,
                    )
                else:
                    if donor_init is None:
                        donor_init = self._find_donor_init(app_id, exclude=clip_path)
                    if not donor_init:
                        continue
                    borrowed = os.path.join(root, "init-stream0-salvage.m4s")
                    shutil.copy2(donor_init, borrowed)
                    logging.info("Salvage: borrowed init %s -> %s", donor_init, root)
                    path = repair.recover_orphaned_clip(
                        root,
                        out_name="session_salvage.mpd",
                        video_init_name="init-stream0-salvage.m4s",
                        require_valid_init=False,
                        probe_resolution=True,
                    )
            except Exception as exc:
                logging.warning("Salvage manifest build failed for %s: %s", root, exc)
                path = None
            if path:
                return path
        return None

    def _find_valid_init0(self, clip_path: str):
        """First valid (>=100B) init-stream0.m4s anywhere inside a clip folder."""
        for root, _dirs, files in os.walk(clip_path):
            if "init-stream0.m4s" in files:
                p = os.path.join(root, "init-stream0.m4s")
                try:
                    if os.path.getsize(p) >= 100:
                        return p
                except OSError:
                    continue
        return None

    def _find_donor_init(self, app_id, exclude: str = ""):
        """Find a valid init-stream0.m4s from a healthy clip of the same game."""
        if not app_id or not hasattr(self.ui, "table_clips"):
            return None
        exclude_norm = os.path.normpath(exclude) if exclude else ""
        for row in range(self.ui.table_clips.rowCount()):
            item = self.ui.table_clips.item(row, 0)
            if not item:
                continue
            path = item.data(Qt.UserRole)
            if not path or not os.path.isdir(path):
                continue
            if exclude_norm and os.path.normpath(path) == exclude_norm:
                continue
            from steempeg.core.rendered_media import parse_app_id_from_clip_folder
            if parse_app_id_from_clip_folder(os.path.basename(path)) != app_id:
                continue
            report = self.get_clip_health_report(path)
            if report.level == health.ClipHealth.DEAD:
                continue
            donor = self._find_valid_init0(path)
            if donor:
                logging.info("Donor init for %s found in %s", app_id, path)
                return donor
        return None

    def _populate_library_context_menu(self, menu, clip_paths: list):
        count = len(clip_paths)
        if count == 0:
            return

        any_dead = any(self._clip_is_dead(p) for p in clip_paths)
        all_dead = all(self._clip_is_dead(p) for p in clip_paths)

        if not all_dead:
            queue_label = "📋 Add to queue" if count == 1 else f"📋 Add to queue ({count})"
            action_queue = menu.addAction(queue_label)
            if any_dead:
                action_queue.setEnabled(False)
                action_queue.setToolTip("Dead clips cannot be queued")
            else:
                action_queue.triggered.connect(lambda: self.add_clips_to_render_queue(clip_paths))

        menu.addSeparator()
        action_open = menu.addAction("📂 Open in folder")
        action_delete = menu.addAction("🗑️ Delete Clip" if count == 1 else f"🗑️ Delete Clips ({count})")

        if count == 1:
            clip_path = clip_paths[0]
            action_open.triggered.connect(lambda: self.open_clip_folder(clip_path))
            action_delete.triggered.connect(lambda: self.delete_clip(clip_path))
        else:
            action_open.setEnabled(False)
            action_delete.setEnabled(False)

    def sync_grid_from_table_selection(self):
        """Mirror multi-selection from the list into the grid."""
        if getattr(self, "_library_panel_mode", "clips") != "clips":
            return
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'):
            return

        selected_rows = {idx.row() for idx in self.ui.table_clips.selectionModel().selectedRows()}

        self.grid_clips.blockSignals(True)
        self.grid_clips.clearSelection()
        for i in range(self.grid_clips.count()):
            item = self.grid_clips.item(i)
            if item.data(Qt.UserRole) in selected_rows:
                item.setSelected(True)
        self.grid_clips.blockSignals(False)
        self._sync_grid_card_visuals()
        row = self.ui.table_clips.currentRow()
        if row >= 0:
            cell = self.ui.table_clips.item(row, 0)
            if cell:
                self._saved_clips_selection_path = cell.data(Qt.UserRole) or ""

    def _sync_grid_card_visuals(self) -> None:
        """Paint selection on ClipCard widgets for every selected table row."""
        if not hasattr(self, 'grid_clips'):
            return
        selected_rows: set[int] = set()
        if (
            getattr(self, "_library_panel_mode", "clips") == "clips"
            and hasattr(self.ui, "table_clips")
        ):
            selected_rows = {
                idx.row() for idx in self.ui.table_clips.selectionModel().selectedRows()
            }
        for i in range(self.grid_clips.count()):
            item = self.grid_clips.item(i)
            card = self.grid_clips.itemWidget(item)
            if isinstance(card, ClipCard):
                row = item.data(Qt.UserRole)
                card.set_selected(row in selected_rows)

    def sync_table_from_grid_selection(self, *, keep_current_cell: bool = False) -> None:
        """Mirror multi-selection from the grid into the list."""
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'):
            return

        selected_items = self.grid_clips.selectedItems()
        table = self.ui.table_clips
        if not selected_items:
            table.blockSignals(True)
            table.clearSelection()
            table.blockSignals(False)
            return

        rows = sorted({
            item.data(Qt.UserRole)
            for item in selected_items
            if item.data(Qt.UserRole) is not None
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

    def _publish_grid_selection(self, *, update_preview: bool = True) -> None:
        """Mirror grid selection into the table; reload preview only on plain LMB clicks."""
        if getattr(self, "_library_panel_mode", "clips") != "clips":
            return
        if hasattr(self, "_clear_rendered_selection_visual"):
            self._clear_rendered_selection_visual()
        self._saved_rendered_selection_path = ""
        if not self.grid_clips.selectedItems():
            self.sync_table_from_grid_selection()
            self._sync_grid_card_visuals()
            return
        self.sync_table_from_grid_selection(keep_current_cell=not update_preview)
        self._sync_grid_card_visuals()
        if update_preview and hasattr(self.ui, 'table_clips') and self.ui.table_clips.currentRow() >= 0:
            self.update_quality_options()
        row = self.ui.table_clips.currentRow()
        if row >= 0:
            cell = self.ui.table_clips.item(row, 0)
            if cell:
                self._saved_clips_selection_path = cell.data(Qt.UserRole) or ""

    def _list_widget_item_index(self, list_widget, item) -> int:
        """Linear list index — QListWidget::row() is wrong in multi-column IconMode."""
        if item is None:
            return -1
        return list_widget.indexFromItem(item).row()

    @staticmethod
    def _event_modifiers(event=None):
        mods = QApplication.keyboardModifiers()
        if event is not None:
            mods |= event.modifiers()
        return mods

    _MULTI_SELECT_MODIFIERS = Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier
    _TOGGLE_SELECT_MODIFIERS = Qt.ControlModifier | Qt.AltModifier

    def _grid_select_item(self, item, event=None, *, force_single: bool = False) -> None:
        """LMB selection for grid cards — setItemWidget breaks default Qt hit-testing."""
        grid = self.grid_clips
        mods = self._event_modifiers(event)
        if force_single:
            mods = Qt.NoModifier

        is_multi = bool(mods & self._MULTI_SELECT_MODIFIERS) and not force_single
        update_preview = not is_multi
        idx = self._list_widget_item_index(grid, item)

        self._grid_select_in_progress = True
        try:
            grid.blockSignals(True)
            if mods & self._TOGGLE_SELECT_MODIFIERS:
                item.setSelected(not item.isSelected())
            elif mods & Qt.ShiftModifier:
                anchor_idx = getattr(self, '_grid_anchor_index', -1)
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

            if not (mods & self._MULTI_SELECT_MODIFIERS):
                self._grid_anchor_index = idx
                self._grid_anchor_item = item

            grid.blockSignals(False)
        finally:
            self._grid_select_in_progress = False

        self._publish_grid_selection(update_preview=update_preview)

    def _handle_grid_card_context_menu(self, item, event) -> None:
        # Right-click only opens the menu; it never changes the selection.
        # The menu resolves its target from the clip under the cursor (see
        # _context_menu_clip_paths_grid), so left-click stays the only way to select.
        # The card sends a position relative to itself, so map it back to the grid
        # viewport to pop the menu exactly where the cursor is (not the card center).
        viewport_pos = self.grid_clips.viewport().mapFromGlobal(event.globalPosition().toPoint())
        self.show_grid_context_menu(viewport_pos)

    def _handle_grid_viewport_press(self, event) -> bool:
        if event.button() != Qt.LeftButton:
            return False

        pos = event.position().toPoint()
        item = self.grid_clips.itemAt(pos)
        if item is None:
            # Clicking empty space inside the grid keeps the current selection
            # (the purple outline stays); only clicking another card changes it.
            return True

        self._grid_select_item(item, event)
        return True

    def show_grid_context_menu(self, pos):
        """ Pop-up menu for the grid """
        clip_paths = self._context_menu_clip_paths_grid(pos)
        if not clip_paths:
            return

        # Keep QMenu's own native popup flags (Qt.Popup). Overriding them with a
        # translucent frameless window made the menu a layered top-level that
        # wouldn't close on focus loss and slid behind the main window.
        menu = QMenu(self.grid_clips)
        menu.setStyleSheet(_LIBRARY_MENU_STYLE)

        self._populate_library_context_menu(menu, clip_paths)
        menu.exec(self.grid_clips.viewport().mapToGlobal(pos))

    def show_clip_context_menu(self, pos):
        """ Pop-up menu for a standard list (List/Table) """
        clip_paths = self._context_menu_clip_paths_table(pos)
        if not clip_paths:
            return

        # See show_grid_context_menu: keep the native Qt.Popup flags so the menu
        # closes correctly instead of lingering behind the window.
        menu = QMenu(self.ui.table_clips)
        menu.setStyleSheet(_LIBRARY_MENU_STYLE)

        self._populate_library_context_menu(menu, clip_paths)
        menu.exec(self.ui.table_clips.viewport().mapToGlobal(pos))

    def open_clip_folder(self, clip_path):
        """ Opens the clip's directory directly in Windows Explorer. """
        try:
            os.startfile(clip_path)
        except Exception as e:
            logging.error(f"Failed to open folder: {e}")

    def delete_clip(self, clip_path):
        """ Prompts for confirmation and deletes the clip folder permanently. """
        
        # 1. Double check with the user to prevent accidental deletion
        msg = QMessageBox(self.ui)
        msg.setWindowTitle("Delete Clip")
        msg.setText("Are you sure you want to delete this clip?")
        msg.setInformativeText("This will permanently delete the folder and all its contents.\nThis cannot be undone!")
        msg.setIcon(QMessageBox.Warning)
        
        btn_delete = msg.addButton("🗑️ Delete", QMessageBox.AcceptRole)
        btn_cancel = msg.addButton("Cancel", QMessageBox.RejectRole)
        
        msg.exec()
        
        if msg.clickedButton() == btn_delete:
            try:
                # 2. Stop MPV playback if the deleted clip is currently playing
                selected_row = self.ui.table_clips.currentRow()
                if selected_row >= 0:
                    playing_path = self.ui.table_clips.item(selected_row, 0).data(Qt.UserRole)
                    if playing_path == clip_path and hasattr(self, 'player'):
                        self.player.stop()
                        
                # 3. Nuke the folder from orbit
                shutil.rmtree(clip_path)
                logging.info(f"Deleted clip folder: {clip_path}")
                
                # 4. Refresh the UI
                self.scan_clips()
                
                if hasattr(self.ui, 'label_short_summary'):
                    if hasattr(self, 'reset_bottom_summary'): self.reset_bottom_summary()
                if hasattr(self.ui, 'label_detailed_summary'):
                    self.ui.label_detailed_summary.setText("Waiting for clip selection...")
                    
            except Exception as e:
                logging.error(f"Failed to delete clip: {e}")
                QMessageBox.critical(self.ui, "Error", f"Failed to delete the clip.\nIt might be in use by another program.\n\n{e}")

    def _load_clips_folders_from_settings(self):
        settings = self.load_user_settings()
        folders = settings.get("clips_folders")
        if folders is None:
            legacy = settings.get("last_clips_folder", "")
            folders = [legacy] if legacy else []
            # Do not persist an empty migrated list — that made _is_first_library_setup()
            # think the library was already configured and skipped Steam auto-discovery.
            if folders:
                self.save_user_settings("clips_folders", folders)
        self.clips_folders = [os.path.normpath(f) for f in folders if f]
        self.clips_folder = self.clips_folders[0] if self.clips_folders else ""
        self._update_folder_picker_label()

    def _save_clips_folders(self):
        self.save_user_settings("clips_folders", self.clips_folders)
        if self.clips_folders:
            self.save_user_settings("last_clips_folder", self.clips_folders[0])

    def _update_folder_picker_label(self):
        picker = getattr(self, "folder_picker", None)
        if picker is None:
            return
        folders = getattr(self, "clips_folders", [])
        # The + only exists once at least one folder is set; with no folders the user
        # must pick a main folder first via Choose Folder.
        picker.set_add_visible(bool(folders))
        if len(folders) <= 1:
            picker.set_folder_label("Choose Folder…")
        else:
            picker.set_folder_label(
                f"Choose Folder… ({len(folders)})",
                "Library folders:\n" + "\n".join(folders),
            )

    def _default_clips_dialog_path(self):
        return default_clips_dialog_path(getattr(self, "clips_folders", None))

    def _is_first_library_setup(self):
        """True when the user has never configured library folders (fresh install)."""
        settings = self.load_user_settings()
        if settings.get("user_cleared_library"):
            return False
        if settings.get("last_clips_folder"):
            return False
        folders = settings.get("clips_folders")
        if folders:
            return False
        return True

    def _should_auto_discover_steam_folders(self):
        """Auto-scan Steam clip paths when the library is empty and the user did not clear it."""
        if self.clips_folders:
            return False
        return self._is_first_library_setup()

    def auto_discover_steam_folders(self, save=True):
        """Scan Steam userdata for gamerecordings/clips paths. Returns newly found paths."""
        discovered = discover_steam_clips_folders()
        if not discovered:
            return []

        existing = {os.path.normpath(p) for p in getattr(self, "clips_folders", [])}
        new_paths = [p for p in discovered if p not in existing]
        if not new_paths and existing:
            return []

        if not self.clips_folders:
            self.clips_folders = list(discovered)
            self.clips_folder = self.clips_folders[0]
        else:
            self.clips_folders.extend(new_paths)

        self.clips_folder = self.clips_folders[0] if self.clips_folders else ""
        if save:
            self._save_clips_folders()
        self._update_folder_picker_label()
        return new_paths if existing else discovered

    def discover_steam_folders(self):
        """User action: merge any newly found Steam clip folders into the library."""
        from steempeg.core.steam_paths import get_steam_path

        before = {os.path.normpath(p) for p in getattr(self, "clips_folders", [])}
        added = self.auto_discover_steam_folders(save=True)
        after = {os.path.normpath(p) for p in getattr(self, "clips_folders", [])}

        if added:
            logging.info("Steam auto-discovery added %s folder(s): %s", len(added), added)
            self.scan_clips(announce_duplicates=True)
            QMessageBox.information(
                self.ui,
                "Steam folders found",
                f"Added {len(added)} Steam clips folder(s):\n\n" + "\n".join(added),
            )
            return

        discovered = discover_steam_clips_folders()
        if not discovered:
            steam = get_steam_path()
            QMessageBox.information(
                self.ui,
                "Steam folders",
                "No Steam Game Recording folders were found.\n\n"
                f"Looked under:\n{os.path.join(steam, 'userdata', '<Steam ID>', 'gamerecordings', 'clips')}",
            )
            return

        if before == after:
            QMessageBox.information(
                self.ui,
                "Steam folders",
                "All discovered Steam folders are already in your library.",
            )

    def choose_folder(self):
        """Pick the primary clips folder (first library root)."""
        folder = QFileDialog.getExistingDirectory(
            self.ui, "Select primary clips folder", self._default_clips_dialog_path()
        )
        if not folder:
            return
        folder = os.path.normpath(folder)
        if not self.clips_folders:
            self.clips_folders = [folder]
        else:
            if folder in self.clips_folders[1:]:
                self.clips_folders.remove(folder)
            self.clips_folders[0] = folder
        self.clips_folder = self.clips_folders[0]
        self.save_user_settings("user_cleared_library", False)
        self._save_clips_folders()
        self._update_folder_picker_label()
        self.scan_clips(announce_duplicates=True)

    def add_clips_folder(self):
        """Append another folder to the library scan list."""
        folder = QFileDialog.getExistingDirectory(
            self.ui, "Add clips folder", self._default_clips_dialog_path()
        )
        if not folder:
            return
        folder = os.path.normpath(folder)
        if folder in self.clips_folders:
            QMessageBox.information(self.ui, "Library folders", "That folder is already in the list.")
            return
        if not self.clips_folders:
            self.clips_folders = [folder]
            self.clips_folder = folder
        else:
            self.clips_folders.append(folder)
        self.save_user_settings("user_cleared_library", False)
        self._save_clips_folders()
        self._update_folder_picker_label()
        self.scan_clips(announce_duplicates=True)

    def remove_clips_folder(self, path):
        """Remove one library root and rescan."""
        if path in self.clips_folders:
            self.clips_folders.remove(path)
        self.clips_folder = self.clips_folders[0] if self.clips_folders else ""
        self._save_clips_folders()
        self._update_folder_picker_label()
        self.scan_clips()

    def clear_clips_folders(self):
        """Drop every saved library root."""
        if not self.clips_folders:
            return
        reply = QMessageBox.question(
            self.ui,
            "Clear library folders",
            "Remove all clips folders from the library?\n"
            "You can add them again with Choose Folder.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.clips_folders = []
        self.clips_folder = ""
        self.save_user_settings("user_cleared_library", True)
        self._save_clips_folders()
        self._update_folder_picker_label()
        self.scan_clips()

    def _folder_panel_row(self, menu, path, is_main):
        """One folder row for the dropdown: label, optional replace, and remove ✕."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 2, 6, 2)
        row_layout.setSpacing(6)

        exists = os.path.isdir(path)
        prefix = "★ " if is_main else ""
        display = path if len(path) <= 42 else "…" + path[-41:]
        label = QLabel(prefix + display)
        label.setObjectName("FolderRowLabel")
        tip = "Main folder\n" if is_main else ""
        steam_id = steam_id_from_clips_folder(path)
        if steam_id:
            tip += f"Steam ID: {steam_id}\n"
        label.setToolTip(tip + (path if exists else f"{path}\n(Folder not found on disk)"))
        if not exists:
            label.setProperty("missing", True)
        row_layout.addWidget(label, 1)

        if is_main:
            btn_replace = QPushButton("⟳")
            btn_replace.setObjectName("FolderRowReplace")
            btn_replace.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_replace.setToolTip("Replace main folder (keeps additional folders)")
            btn_replace.clicked.connect(
                lambda _checked=False: (menu.close(), self.choose_folder())
            )
            row_layout.addWidget(btn_replace)

        btn_x = QPushButton("✕")
        btn_x.setObjectName("FolderRowRemove")
        btn_x.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_x.setToolTip("Remove this folder")
        btn_x.clicked.connect(
            lambda _checked=False, p=path: (menu.close(), self.remove_clips_folder(p))
        )
        row_layout.addWidget(btn_x)

        action_row = QWidgetAction(menu)
        action_row.setDefaultWidget(row)
        menu.addAction(action_row)

    def show_folders_panel(self):
        """Dropdown panel (styled like Logs) listing the main + extra library folders."""
        if not self.clips_folders:
            menu = QMenu(self.folder_picker)
            menu.setStyleSheet(_FOLDERS_MENU_STYLE)
            action_discover = menu.addAction("🔍  Discover Steam folders…")
            action_discover.triggered.connect(self.discover_steam_folders)
            action_choose = menu.addAction("📂  Choose folder manually…")
            action_choose.triggered.connect(self.choose_folder)
            btn = self.folder_picker.add_btn
            size = menu.sizeHint()
            top_right = btn.mapToGlobal(btn.rect().topRight())
            pos = QPoint(top_right.x() - size.width(), top_right.y() - size.height())
            menu.exec(pos)
            return

        menu = QMenu(self.folder_picker)
        menu.setStyleSheet(_FOLDERS_MENU_STYLE)

        header = menu.addAction("Library folders")
        header.setEnabled(False)
        menu.addSeparator()

        for idx, path in enumerate(self.clips_folders):
            self._folder_panel_row(menu, path, is_main=(idx == 0))

        menu.addSeparator()
        action_discover = menu.addAction("🔍  Discover Steam folders…")
        action_discover.triggered.connect(self.discover_steam_folders)
        action_add = menu.addAction("➕  Add another folder…")
        action_add.triggered.connect(self.add_clips_folder)

        if len(self.clips_folders) > 1:
            action_clear = menu.addAction("🧹  Clear list")
            action_clear.triggered.connect(self.clear_clips_folders)

        # Open the panel directly above the + button: align the panel's bottom-right
        # corner with the + 's top-right corner so it grows upward, not off to the side.
        btn = self.folder_picker.add_btn
        size = menu.sizeHint()
        top_right = btn.mapToGlobal(btn.rect().topRight())
        pos = QPoint(top_right.x() - size.width(), top_right.y() - size.height())
        menu.exec(pos)

    def _collect_clip_roots(self, base_folder):
        """Return clip folder paths discovered under one library root."""
        if not base_folder or not os.path.exists(base_folder):
            return set()

        base_folder = os.path.normpath(base_folder)
        if os.path.basename(base_folder).lower() == "clips":
            parent = os.path.dirname(base_folder)
            if os.path.basename(parent).lower() == "gamerecordings":
                base_folder = parent

        roots = set()
        for sub in ("clips", "video"):
            sub_path = os.path.join(base_folder, sub)
            if os.path.exists(sub_path):
                for item in os.listdir(sub_path):
                    full = os.path.join(sub_path, item)
                    if os.path.isdir(full):
                        roots.add(full)

        if self._looks_like_single_clip_folder(base_folder):
            base_name = os.path.basename(base_folder).lower()
            if base_name not in ("gamerecordings", "clips", "video"):
                if not self._is_steam_clip_container_folder(base_folder):
                    roots.add(base_folder)
        try:
            for item in os.listdir(base_folder):
                full = os.path.join(base_folder, item)
                if not os.path.isdir(full) or not item.lower().startswith(("clip_", "bg_", "fg_")):
                    continue
                base_name = os.path.basename(base_folder).lower()
                if base_name.startswith(("clip_", "bg_", "fg_")) and is_nested_same_session(
                    base_name, item.lower()
                ):
                    continue
                roots.add(full)
        except Exception:
            pass
        return roots

    def fast_sync_grid(self):
        """ INSTANT GRID SYNCHRONIZATION """
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'): return

        grid = self.grid_clips
        table = self.ui.table_clips

        grid.setUpdatesEnabled(False)
        grid.blockSignals(True)

        # 1. Create a dictionary for quick lookup clip_path -> row_index in the table
        table_order = {}
        for row in range(table.rowCount()):
            t_item = table.item(row, 0)
            if t_item:
                clip_path = t_item.data(Qt.UserRole)
                # Saving the index and visibility status
                table_order[clip_path] = {'row': row, 'hidden': table.isRowHidden(row)}

        # 2. Gently update grid elements
        for i in range(grid.count()):
            item = grid.item(i)
            clip_path = item.data(Qt.UserRole + 1)
            hidden = True
            if clip_path and clip_path in table_order:
                info = table_order[clip_path]
                item.setText(f"{info['row']:06d}")
                item.setData(Qt.UserRole, info['row'])
                hidden = info['hidden']
            item.setHidden(hidden)
        # 3. Qt's built-in ultra-fast sort
        grid.sortItems(Qt.AscendingOrder)

        grid.blockSignals(False)
        grid.setUpdatesEnabled(True)

    # --- TRUE HIGH-END FULLSCREEN SYSTEM ---
    def refresh_library(self):
        """ Refresh button: wipe the active filter, deselect the current clip/queue job,
        reset the player + settings panel, then rescan the folder from scratch. """
        # 1. Drop the remembered filter so the menu reopens at defaults and nothing stays hidden
        self.saved_filter_state = None
        if getattr(self, 'filter_menu', None) is not None:
            try:
                self.filter_menu.deleteLater()
            except Exception:
                pass
            self.filter_menu = None

        # 2. Reset the selected clip, the player surface and every settings tab
        if hasattr(self, 'close_current_clip'):
            self.close_current_clip()

        # 3. Drop the queue selection (the queued jobs themselves are kept)
        self._selected_queue_job_id = None
        if hasattr(self, 'refresh_render_queue_panel'):
            self.refresh_render_queue_panel()

        # 4. Rescan folders (fast: cached health, no Steam network)
        self.scan_clips(fast=True)

    def scan_clips(self, announce_duplicates: bool = False, *, fast: bool = False):
        """Scans both standard Steam folders AND custom extracted folders.

        fast=True (Refresh button): rebuild the list from disk, use cached health and
        cached game icons/names only — no Steam API or icon downloads.
        """
        if not hasattr(self.ui, 'table_clips'): return
        self.ui.table_clips.setSortingEnabled(False) 
        self.ui.table_clips.setRowCount(0)
        
        if not getattr(self, "clips_folders", None):
            self._load_clips_folders_from_settings()

        library_roots = [f for f in self.clips_folders if f and os.path.exists(f)]
        library_root_norms = {os.path.normpath(r) for r in library_roots}
        if not library_roots:
            # No folders left (e.g. the user cleared them mid-session). The list was
            # already emptied above, but the grid is built separately and would keep
            # showing the previous scan's cards — wipe it and the count too. Steam's
            # default folder is only auto-scanned at startup when nothing is saved, so
            # searching again is an explicit action (Choose Folder / Refresh).
            if hasattr(self, 'build_netflix_grid'):
                self.build_netflix_grid()
            if hasattr(self, 'lbl_clip_count'):
                self.lbl_clip_count.setText("• 0 Clips")
            return

        folders_to_check = set()
        for root in library_roots:
            folders_to_check.update(self._collect_clip_roots(root))

        try:
            # Sort the chaotic set() by folder modification time
            sorted_folders = sorted(
                list(folders_to_check),
                key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0,
                reverse=True,
            )
            sorted_folders, session_dupes = dedupe_steam_session_folders(sorted_folders)

            health_counts = {"healthy": 0, "issues": 0, "dead": 0}
            seen_clip_ids = set()
            duplicate_count = session_dupes
            
            for full_path in sorted_folders:
                if not os.path.exists(full_path): continue
                if os.path.normpath(full_path) in library_root_norms:
                    continue

                folder_name = os.path.basename(full_path).lower()
                if folder_name in ("gamerecordings", "clips", "video"):
                    continue
                if self._is_steam_clip_container_folder(full_path):
                    continue
                if self._is_clip_library_root(full_path):
                    continue
                is_steam_name = folder_name.startswith(("clip_", "bg_", "fg_"))
                if not is_steam_name and not self._folder_has_dash_recording(full_path):
                    continue

                folder_name = os.path.basename(full_path).lower()
                if "steempeg" in folder_name or folder_name in ["logs", "cache", "_update_extracted"]:
                    continue

                # Same clip can live in two different library roots (a copy). The
                # session key (appid + date + time, prefix ignored) is the clip's
                # identity — keep the first occurrence (most recent by mtime).
                session_key = steam_session_key(folder_name)
                dedupe_key = session_key or folder_name
                if dedupe_key in seen_clip_ids:
                    duplicate_count += 1
                    continue
                seen_clip_ids.add(dedupe_key)
                
                has_mpd = False
                has_chunks = False
                mpd_path = None
                
                for root, dirs, files in os.walk(full_path):
                    for f in files:
                        if f.endswith(".mpd"):
                            has_mpd = True
                            mpd_path = os.path.join(root, f)
                            break 
                    if any("chunk-stream" in f for f in files):
                        has_chunks = True

                if has_chunks and not has_mpd:
                    recovered = self.recover_orphaned_clip(full_path)
                    if recovered: 
                        has_mpd = True
                        # Just in case, search for mpd again after recovery.
                        for root, dirs, files in os.walk(full_path):
                            for f in files:
                                if f.endswith(".mpd"):
                                    mpd_path = os.path.join(root, f)
                                    break 

                if not has_mpd and not has_chunks:
                    continue

                # Steam sometimes leaves empty fg_/clip_ shells (mpd only, no video).
                # Steam's own UI hides these; skip them here too.
                if not folder_has_video_chunks(full_path):
                    continue

                health_report = self._resolve_clip_health(full_path, fast=fast)
                if health_report.level == health.ClipHealth.HEALTHY:
                    health_counts["healthy"] += 1
                elif health_report.level == health.ClipHealth.DEAD:
                    health_counts["dead"] += 1
                else:
                    health_counts["issues"] += 1
                # MAGIC: Extracting Duration from MPD
                duration_str = "--:--"
                if mpd_path:
                    try:
                        with open(mpd_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            
                            match = re.search(r'(?:mediaPresentationDuration|duration)="PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?"', content)
                            if match:
                                h = int(match.group(1)) if match.group(1) else 0
                                m = int(match.group(2)) if match.group(2) else 0
                                s = int(float(match.group(3))) if match.group(3) else 0
                                
                                # Formatting for a Beautiful Look
                                if h == 0 and m == 0: duration_str = f"{s}s"
                                elif h == 0: duration_str = f"{m}m {s}s"
                                else: duration_str = f"{h}h {m}m {s}s"
                    except: pass
                elif health_report.level == health.ClipHealth.DEAD:
                    duration_str = "—"

                folder_name = os.path.basename(full_path)
                parts = folder_name.split("_")
                
                if len(parts) >= 4 and parts[1].isdigit():
                    prefix = parts[0].lower()
                    app_id = parts[1]
                    
                    if prefix == "clip": rec_type = "🎬 Clip"
                    elif prefix == "bg": rec_type = "📼 BG"
                    elif prefix == "fg": rec_type = "🎞️ FG"
                    else: rec_type = "Unknown"

                    raw_name = self.get_game_name(app_id, allow_fetch=not fast)
                    game_name = f"   {raw_name}" 
                    icon = self.get_game_icon(app_id, allow_download=not fast)

                    try:
                        # 1. Concatenate the date and time from the folder into a single string (YYYYMMDD_HHMMSS)
                        raw_datetime_str = f"{parts[2]}_{parts[3]}"
                        
                        # 2. We tell Python: "This is UTC time (Greenwich Mean Time)!"
                        dt_utc = datetime.strptime(raw_datetime_str, "%Y%m%d_%H%M%S")
                        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                        
                        # 3. Automatically convert to your time zone (Windows will automatically detect that you are in UTC+3)
                        dt_local = dt_utc.astimezone()
                        
                        # 4. Unpack back into beautiful formats for the interface
                        formatted_date = format_clip_date(dt_local)
                        formatted_time = format_clip_time(dt_local)
                    except Exception as e:
                        # If the folder is named incorrectly, use the old fallback option.
                        try: formatted_date = format_clip_date(datetime.strptime(parts[2], "%Y%m%d"))
                        except: formatted_date = parts[2]
                        try: formatted_time = format_clip_time(datetime.strptime(parts[3], "%H%M%S"))
                        except: formatted_time = ""


                else:
                    rec_type = "🎞️ FG"
                    game_name = "   Unknown"
                    formatted_date = "Unknown"
                    formatted_time = ""
                    icon = QIcon()
                    from steempeg.infra.paths import get_resource_path
                    unknown_icon = get_resource_path("unknown_icon.png")
                    if os.path.isfile(unknown_icon):
                        icon = QIcon(unknown_icon)

                row_position = self.ui.table_clips.rowCount()
                self.ui.table_clips.insertRow(row_position)
                
                item_game = QTableWidgetItem(icon, game_name)
                item_game.setData(Qt.UserRole, full_path)
                if game_name.strip().lower() == "unknown":
                    item_game.setToolTip(full_path)
                item_game.setData(_CLIP_HEALTH_ROLE, health_report.level.value)
                item_game.setData(_CLIP_HEALTH_ISSUES_ROLE, "\n".join(health_report.issues))
                self.ui.table_clips.setItem(row_position, 0, item_game)
                
                item_type = QTableWidgetItem(rec_type)
                item_type.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                self.ui.table_clips.setItem(row_position, 1, item_type)
                
                item_date = QTableWidgetItem(formatted_date)
                self.ui.table_clips.setItem(row_position, 2, item_date)

                date_display = f"{formatted_date}\n{formatted_time}" if formatted_time else formatted_date
                
                item_date = QTableWidgetItem(date_display)
                item_date.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter) 
                self.ui.table_clips.setItem(row_position, 2, item_date)

                # Column 3: DURATION
                item_duration = QTableWidgetItem(duration_str)
                item_duration.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                self.ui.table_clips.setItem(row_position, 3, item_duration)

            self.ui.table_clips.setSortingEnabled(True)
            self.ui.table_clips.horizontalHeader().setSectionsClickable(False)

            if hasattr(self, 'build_netflix_grid'):
                self.build_netflix_grid()
                
            if hasattr(self, 'lbl_clip_count'):
                self.lbl_clip_count.setText(f"• {self.ui.table_clips.rowCount()} Clips")

            # Show a one-time popup (not a sticky status) when the user just added a
            # folder that introduced duplicates. On startup/refresh/delete rescans we
            # stay silent — the status line would otherwise get stuck on this message.
            if announce_duplicates and duplicate_count:
                noun = "duplicate" if duplicate_count == 1 else "duplicates"
                QMessageBox.information(
                    self.ui,
                    "Duplicate clips ignored",
                    f"Ignored {duplicate_count} {noun} across folders.\n\n"
                    "The same clip was found in more than one library folder; only the "
                    "most recent copy is shown.",
                )

            logging.info(
                "Library scan: roots=%s clips=%d healthy=%d issues=%d dead=%d "
                "ignored_duplicates=%d fast=%s",
                library_roots,
                self.ui.table_clips.rowCount(),
                health_counts["healthy"],
                health_counts["issues"],
                health_counts["dead"],
                duplicate_count,
                fast,
            )
                
                    
        except Exception as e:
            logging.error(f"Scan Error: {e}")
    
    def get_clip_size_and_duration(self, clip_path, mpd_content):
        # total size of the clip folder
        size_mb = discovery.folder_size_bytes(clip_path) / (1024 * 1024)
        size_str = f"{size_mb / 1024:.2f} GB" if size_mb >= 1000 else f"{size_mb:.1f} MB"

        # duration: the parsing lives in mpd.py now, the display formatting stays here
        seconds = mpd.parse_duration_seconds(mpd_content)
        if seconds is None:
            self.current_clip_duration_sec = 0.0   # reset so no old time stays from the last clip
            duration_str = "Unknown"
        else:
            self.current_clip_duration_sec = seconds
            # show H:MM:SS when it is over an hour, otherwise just MM:SS
            total = int(seconds)
            h, m, s = total // 3600, (total % 3600) // 60, total % 60
            duration_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        self.current_clip_duration_str = duration_str
        return size_str, duration_str
    

    

    def on_grid_selection_changed(self):
        """Qt signal fallback — custom card clicks publish selection manually."""
        if getattr(self, '_grid_select_in_progress', False):
            return
        self._publish_grid_selection()

    def build_netflix_grid(self):
        """ Transforms rows from a hidden table into vibrant cards. """
        if not hasattr(self, 'grid_clips') or not hasattr(self.ui, 'table_clips'):
            return

        # Items get destroyed below — drop the stale Shift anchor or range-select breaks.
        self._grid_anchor_item = None
        self._grid_anchor_index = -1
        self.grid_clips.clear()
        
        for row in range(self.ui.table_clips.rowCount()):
            title_item = self.ui.table_clips.item(row, 0)
            date_item = self.ui.table_clips.item(row, 2)
            time_item = self.ui.table_clips.item(row, 3)
            
            title = title_item.text() if title_item else "Unknown"
            date_str = date_item.text() if date_item else "Today"
            time_str = time_item.text() if time_item else "00:00"
            clip_path = title_item.data(Qt.UserRole) if title_item else None
            health_color = None
            if title_item:
                level = title_item.data(_CLIP_HEALTH_ROLE)
                if level:
                    try:
                        health_color = health.HEALTH_COLORS[health.ClipHealth(level)]
                    except ValueError:
                        health_color = health.HEALTH_COLORS[health.ClipHealth.DEAD]
            
            icon_path = ""
            thumb_path = ""
            badge_text = "Clip"
            
            if clip_path:
                clip_folder_name = os.path.basename(clip_path)
                parts = clip_folder_name.split("_")

                if title.strip().lower() == "unknown":
                    badge_text = "FG"
                    from steempeg.infra.paths import get_resource_path
                    unknown_icon = get_resource_path("unknown_icon.png")
                    if os.path.isfile(unknown_icon):
                        icon_path = unknown_icon
                elif len(parts) > 0:
                    prefix = parts[0].upper()
                    if prefix in ["FG", "BG", "CLIP"]:
                        badge_text = prefix

                if not icon_path and len(parts) >= 2 and parts[1].isdigit():
                    icon_path = os.path.join(self.cache_dir, f"{parts[1]}.jpg")

                if os.path.exists(clip_path):
                    thumb_path = find_clip_thumbnail(clip_path)

            footer_right = "FG" if title.strip().lower() == "unknown" else f"{date_str} • {time_str}"
            is_unknown_clip = title.strip().lower() == "unknown"

            item = QListWidgetItem(self.grid_clips)
            item.setSizeHint(QSize(260, 190))
            item.setData(Qt.UserRole, row)
            item.setData(Qt.UserRole + 1, clip_path)

            card = ClipCard(
                title.strip(),
                footer_right,
                badge_text,
                thumb_path,
                icon_path,
                row,
                health_color=health_color,
                round_icon=is_unknown_clip,
                on_left_click=lambda ev, grid_item=item: self._grid_select_item(grid_item, ev),
                on_right_click=lambda ev, grid_item=item: self._handle_grid_card_context_menu(grid_item, ev),
            )
            self.grid_clips.setItemWidget(item, card)

            
            # SYNC VISIBILITY WITH TABLE
            if self.ui.table_clips.isRowHidden(row):
                item.setHidden(True)

        self.sync_grid_from_table_selection()

    def _position_filter_menu(self):
        """Place + size the filter popup relative to the live widget geometry.

        Split out so it can run again right after show(): on a fresh launch the
        maximized window hasn't fully settled when the menu is first built, so the
        button/footer global coords are stale and the panel comes out mis-sized
        ("slightly broken"). Re-running once the geometry is valid self-corrects it.
        """
        menu = getattr(self, 'filter_menu', None)
        if not menu or not hasattr(self, 'btn_filter_pill'):
            return
        button_bottom_left = self.btn_filter_pill.mapToGlobal(QPoint(0, self.btn_filter_pill.height()))
        x_shift = menu.width() - self.btn_filter_pill.width()
        menu_y = button_bottom_left.y() + 5
        menu.move(button_bottom_left.x() - x_shift + 10, menu_y)

        if hasattr(self, 'btn_refresh'):
            footer_top = self.btn_refresh.mapToGlobal(QPoint(0, 0)).y()
            menu.set_content_max_height(max(160, footer_top - menu_y - 8))

    def show_filter_menu(self):
        """ Calculates the coordinates and passes the ENTIRE PROGRAM (self) to the menu. """
        if not hasattr(self, 'btn_filter_pill'): return
        
        # 1. Forcefully destroy the old window to reset the Qt focus bug.
        if hasattr(self, 'filter_menu') and self.filter_menu:
            self.filter_menu.deleteLater()
            
        # 2. Creating a brand-new menu from scratch
        self.filter_menu = FilterMenu(self.ui)
        self.filter_menu.gather_statistics(self)

        # Best-effort placement before show, then correct once shown (handles the
        # first-launch case where the window geometry isn't settled yet).
        self._position_filter_menu()
        self.filter_menu.show()
        QTimer.singleShot(0, self._position_filter_menu)

    def apply_sorting(self):
        """ FAST INDEPENDENT SORTING ENGINE """
        if not hasattr(self.ui, 'table_clips'): return
        table = self.ui.table_clips
        sort_idx = self.combo_sort.currentIndex()
        
        
        # Freezing graphics and signals for instant speed
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        
        all_data = []
        for row in range(table.rowCount()):
            is_hidden = table.isRowHidden(row)
            row_items = [table.takeItem(row, col) for col in range(table.columnCount())]
            all_data.append({ 'table_items': row_items, 'orig_row': row, 'hidden': is_hidden })
            
        
        def get_sort_key(data):
            r = data['table_items']
            
            if sort_idx == 0: 
                # Read the actual modification date of the folder containing the clip
                clip_path = r[0].data(Qt.UserRole)
                if clip_path and os.path.exists(clip_path):
                    return os.path.getmtime(clip_path)
                return 0
                
            if sort_idx in (1, 2): # GAME NAME
                txt = r[0].text().lower() if r[0] else ""
                return re.sub(r'[^a-zа-я0-9]', '', txt)
                
            if sort_idx in (3, 4): # TYPE
                txt = r[1].text().lower() if r[1] else ""
                return re.sub(r'[^a-zа-я0-9]', '', txt)

            if sort_idx in (5, 6): # HEALTH
                level = r[0].data(_CLIP_HEALTH_ROLE) if r[0] else health.ClipHealth.HEALTHY.value
                rank = {
                    health.ClipHealth.HEALTHY.value: 2,
                    health.ClipHealth.DEGRADED.value: 1,
                    health.ClipHealth.DEAD.value: 0,
                }
                return rank.get(level, 1)
                
            if sort_idx in (7, 8): # DATE
                txt = re.sub(r'\s+', ' ', r[2].text().strip()) if r[2] else ""
                qdt = parse_clip_datetime_text(txt)
                if qdt is not None:
                    return qdt.toSecsSinceEpoch()
                return 0
                    
            if sort_idx in (9, 10): # DURATION
                txt = r[3].text() if r[3] else ""
                h = int(re.search(r'(\d+)h', txt).group(1)) if 'h' in txt else 0
                m = int(re.search(r'(\d+)m', txt).group(1)) if 'm' in txt else 0
                s = int(re.search(r'(\d+)s', txt).group(1)) if 's' in txt else 0
                return h * 3600 + m * 60 + s
                
            return data['orig_row']

       
        reverse = sort_idx in (0, 2, 4, 6, 8, 10)
        all_data.sort(key=get_sort_key, reverse=reverse)
        
        for new_row, data in enumerate(all_data):
            for col, item in enumerate(data['table_items']):
                table.setItem(new_row, col, item)
            table.setRowHidden(new_row, data['hidden'])
            
        table.blockSignals(False)
        table.setUpdatesEnabled(True)
        
        
        if hasattr(self, 'fast_sync_grid'):
            self.fast_sync_grid()

    

    # --- TRUE HIGH-END FULLSCREEN SYSTEM ---
    def get_game_name(self, app_id, *, allow_fetch: bool = True):
        app_id = str(app_id)
        # 1. Cache first
        if app_id in self.game_names_cache:
            return self.game_names_cache[app_id]
        if not allow_fetch:
            return f"Unknown Game ({app_id})"
        # 2. Otherwise, ask Steam once and remember
        name = games.fetch_game_name(app_id)
        if name:
            self.game_names_cache[app_id] = name
            self.save_json_cache()
            return name
        return f"Unknown Game ({app_id})"
    



    

    
    def get_game_icon(self, app_id, *, allow_download: bool = True):
        app_id = str(app_id)
        # 1. RAM cache
        if app_id in self.game_icons_cache:
            return self.game_icons_cache[app_id]
        # 2. disk cache, otherwise download
        icon_path = os.path.join(self.cache_dir, f"{app_id}.jpg")
        if not os.path.exists(icon_path):
            if not allow_download or not games.download_icon(app_id, icon_path):
                return QIcon()
        # 3. Build a Qt icon (this is Qt -> stays here) and cache it in RAM
        icon = QIcon(QPixmap(icon_path))
        self.game_icons_cache[app_id] = icon
        return icon

    def set_view_mode(self, mode):
        if mode == "list":
            self.grid_clips.hide()
            self.ui.table_clips.show()
            self.btn_view_list.setStyleSheet(self.toggle_style_active)
            self.btn_view_grid.setStyleSheet(self.toggle_style_inactive)
        else:
            self.ui.table_clips.hide()
            self.grid_clips.show()

            # HARD GEOMETRY RECALCULATION (Pictures won't fly away anymore!)
            self.grid_clips.doItemsLayout()

            self.btn_view_list.setStyleSheet(self.toggle_style_inactive)
            self.btn_view_grid.setStyleSheet(self.toggle_style_active)

            if self.grid_clips.selectedItems():
                self.grid_clips.scrollToItem(self.grid_clips.selectedItems()[0])