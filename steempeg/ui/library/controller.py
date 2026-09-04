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

from PySide6.QtCore import Qt, QPoint, QSize, QTimer, QItemSelection, QItemSelectionModel
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QTableWidgetItem,
    QWidget,
    QWidgetAction,
)

from steempeg.ui.icon_assets import health_icon
from steempeg.ui import design_tokens as tok
from steempeg.core import games
from steempeg.core.clip_identity import (
    is_steam_package_internal_child,
    session_duplicate_paths_to_drop,
)
from steempeg.core.clip_thumbnails import (
    clip_poster_cache_path_nostat,
    resolve_clip_thumbnail,
)
from steempeg.ui.library.clip_poster_backfill import ClipPosterBackfillWorker
from steempeg.ui.library.scan_worker import LibraryScanWorker
from steempeg.ui.library.refresh_workers import (
    ClipDurationBackfillWorker,
    ClipHealthRecheckWorker,
    SteamIconsRefreshWorker,
    SteamNamesRefreshWorker,
)
from steempeg.library.scan import ScannedClip, clip_folder_default_sort_key
from steempeg.library.clips_library_cache import (
    clear_clips_library_cache,
    clips_from_library_cache,
    save_clips_library_cache,
    seed_clips_from_health_cache,
)
from steempeg.core.dash import discovery, health, mpd
from steempeg.ui.library.filters import clip_folder_sort_key
from steempeg.core.steam_paths import (
    default_clips_dialog_path,
    discover_steam_clips_folders,
    steam_id_from_clips_folder,
)
from steempeg.infra.locale_time import format_clip_date, format_clip_time, parse_clip_datetime_text
from steempeg.infra import cache as json_cache
from steempeg.infra.paths import get_resource_path
from steempeg.ui.library.filters import FilterMenu
from steempeg.ui.library.grid_view import ClipCard
from steempeg.ui.message_dialog import (
    steempeg_confirm_delete,
    steempeg_critical,
    steempeg_information,
    steempeg_question,
    steempeg_warning,
)
from steempeg.ui import ui_theme as ut


_CLIP_HEALTH_ROLE = Qt.UserRole + 2
_CLIP_HEALTH_ISSUES_ROLE = Qt.UserRole + 3
_CLIP_CURED_ROLE = Qt.UserRole + 4
_CLIP_CARD_SIZE = QSize(260, 190)
_CLIP_VIEWPORT_OVERSCAN_PX = 220
_CLIP_SCROLL_IDLE_MS = 120
# Once a card has been seen it stays (scroll-back should not hitch).
# Cap is only a RAM safety valve — farthest from the viewport go first.
_CLIP_MAX_LIVE_WIDGETS = 256


class LibraryMixin:
    def _sync_library_scrollbars(self, *, force_hide: bool = False) -> None:
        from steempeg.ui.library.library_styles import sync_library_scrollbars

        sync_library_scrollbars(self, force_hide=force_hide)

    # --- Clip health cache (mtime-keyed, persisted between sessions) ---
    def _clip_health_cache_path(self):
        return os.path.join(self.cache_dir, "clip_health_cache.json")

    def _ensure_clip_health_cache(self):
        if not hasattr(self, "_clip_health_cache"):
            self._clip_health_cache = json_cache.read_json(self._clip_health_cache_path(), default={})

    def _save_clip_health_cache(self):
        self._ensure_clip_health_cache()
        json_cache.write_json(self._clip_health_cache_path(), self._clip_health_cache)

    # --- Rendered export health cache (mtime+size keyed) ---
    def _rendered_health_cache_path(self):
        return os.path.join(self.cache_dir, "rendered_health_cache.json")

    def _ensure_rendered_health_cache(self):
        if not hasattr(self, "_rendered_health_cache"):
            self._rendered_health_cache = json_cache.read_json(
                self._rendered_health_cache_path(), default={}
            )

    def _save_rendered_health_cache(self):
        self._ensure_rendered_health_cache()
        json_cache.write_json(self._rendered_health_cache_path(), self._rendered_health_cache)

    def _store_rendered_health_cache(self, file_path: str, assessment) -> None:
        """Persist assess result keyed by path + mtime + size."""
        from steempeg.core.rendered_health import (
            RENDERED_HEALTH_RULES_VERSION,
            RenderedHealthAssessment,
        )

        if not file_path or not isinstance(assessment, RenderedHealthAssessment):
            return
        self._ensure_rendered_health_cache()
        norm = os.path.normpath(file_path)
        try:
            st = os.stat(file_path)
            mtime = st.st_mtime
            size = st.st_size
        except OSError:
            mtime, size = 0.0, 0
        self._rendered_health_cache[norm] = {
            "mtime": mtime,
            "size": size,
            "rules_version": RENDERED_HEALTH_RULES_VERSION,
            "level": assessment.report.level.value,
            "issues": list(assessment.report.issues),
            "duration_sec": assessment.duration_sec,
            "duration_stream_sec": assessment.duration_stream_sec,
            "duration_format_sec": assessment.duration_format_sec,
        }
        self._save_rendered_health_cache()

    def _seed_rendered_health_cache_row(self, row) -> None:
        """Seed cache from companion fields collected during rendered scan (no ffprobe)."""
        from steempeg.core.rendered_health import RenderedHealthAssessment

        level_raw = getattr(row, "health_level", "") or ""
        if not level_raw:
            return
        try:
            level = health.ClipHealth(level_raw)
        except ValueError:
            return
        if level == health.ClipHealth.CURED:
            level = (
                health.ClipHealth.DEGRADED
                if getattr(row, "health_issues", None)
                else health.ClipHealth.HEALTHY
            )
        assessment = RenderedHealthAssessment(
            health.ClipHealthReport(level, list(getattr(row, "health_issues", None) or [])),
            duration_stream_sec=getattr(row, "duration_stream_sec", None),
            duration_format_sec=getattr(row, "duration_format_sec", None),
            duration_sec=getattr(row, "duration_sec", None),
        )
        self._ensure_rendered_health_cache()
        norm = os.path.normpath(row.full_path)
        self._rendered_health_cache[norm] = {
            "mtime": float(getattr(row, "file_mtime", 0.0) or 0.0),
            "size": int(getattr(row, "file_size", 0) or 0),
            "level": assessment.report.level.value,
            "issues": list(assessment.report.issues),
            "duration_sec": assessment.duration_sec,
            "duration_stream_sec": assessment.duration_stream_sec,
            "duration_format_sec": assessment.duration_format_sec,
        }
        dirty = getattr(self, "_rendered_health_cache_dirty", 0) + 1
        self._rendered_health_cache_dirty = dirty
        if dirty >= 25:
            self._save_rendered_health_cache()
            self._rendered_health_cache_dirty = 0

    def _resolve_rendered_health(
        self, file_path: str, *, force: bool = False
    ):
        """Return RenderedHealthAssessment, using disk cache when mtime/size match."""
        from steempeg.core.rendered_health import (
            RENDERED_HEALTH_RULES_VERSION,
            RenderedHealthAssessment,
            assess_rendered_health,
        )
        from steempeg.core.rendered_media import (
            is_sane_media_duration,
            load_rendered_companion_meta,
        )

        if not file_path or not os.path.isfile(file_path):
            return RenderedHealthAssessment(
                health.ClipHealthReport(health.ClipHealth.DEAD, ["File missing or unreadable"]),
            )

        self._ensure_rendered_health_cache()
        norm = os.path.normpath(file_path)
        try:
            st = os.stat(file_path)
            mtime = st.st_mtime
            size = st.st_size
        except OSError:
            mtime, size = 0.0, 0

        if not force:
            entry = self._rendered_health_cache.get(norm)
            if (
                entry
                and entry.get("mtime") == mtime
                and entry.get("size") == size
                and entry.get("rules_version") == RENDERED_HEALTH_RULES_VERSION
            ):
                try:
                    level = health.ClipHealth(entry["level"])
                except ValueError:
                    level = health.ClipHealth.DEAD
                return RenderedHealthAssessment(
                    health.ClipHealthReport(level, list(entry.get("issues") or [])),
                    duration_stream_sec=entry.get("duration_stream_sec"),
                    duration_format_sec=entry.get("duration_format_sec"),
                    duration_sec=entry.get("duration_sec"),
                )

            meta = load_rendered_companion_meta(
                file_path, cache_dir=getattr(self, "cache_dir", None)
            ) or {}
            if (
                meta.get("mtime_ns") == getattr(st, "st_mtime_ns", None)
                and meta.get("size") == size
                and meta.get("health")
                and meta.get("health_rules_version") == RENDERED_HEALTH_RULES_VERSION
            ):
                issues = list(meta.get("health_issues") or [])
                try:
                    level = health.ClipHealth(str(meta.get("health")))
                    if level == health.ClipHealth.CURED:
                        level = (
                            health.ClipHealth.DEGRADED
                            if issues
                            else health.ClipHealth.HEALTHY
                        )
                except ValueError:
                    level = health.ClipHealth.HEALTHY
                assessment = RenderedHealthAssessment(
                    health.ClipHealthReport(level, issues),
                    duration_stream_sec=meta.get("duration_stream_sec"),
                    duration_format_sec=meta.get("duration_format_sec"),
                    duration_sec=meta.get("duration_sec"),
                )
                self._store_rendered_health_cache(file_path, assessment)
                return assessment

        expected = None
        meta = load_rendered_companion_meta(
            file_path, cache_dir=getattr(self, "cache_dir", None)
        ) or {}
        raw = meta.get("expected_duration_sec")
        if is_sane_media_duration(raw):
            expected = float(raw)
        assessment = assess_rendered_health(
            file_path,
            expected_duration_sec=expected,
            cache_dir=getattr(self, "cache_dir", None),
        )
        self._store_rendered_health_cache(file_path, assessment)
        return assessment

    def get_rendered_health_report(self, file_path: str):
        return self._resolve_rendered_health(file_path).report

    def get_rendered_display_health_report(self, file_path: str):
        from steempeg.core.rendered_health import display_report_from_companion
        from steempeg.core.rendered_media import load_rendered_companion_meta

        assessment = self._resolve_rendered_health(file_path)
        meta = load_rendered_companion_meta(
            file_path, cache_dir=getattr(self, "cache_dir", None)
        )
        return display_report_from_companion(meta, assessment.report)

    def _active_rendered_preview_path(self) -> str | None:
        """Flat export currently in the player (mp4/mkv/…), if any.

        Prefer this over DASH folder health — panel mode alone is not enough
        (tab switch / queue open can leave an export playing under Clips chrome).
        """
        from steempeg.ui.library.rendered_library import RENDERED_ALL_EXTS

        for candidate in (
            getattr(self, "_rendered_media_path", None),
            getattr(self, "_preview_clip_path", None),
        ):
            if not candidate or not os.path.isfile(candidate):
                continue
            ext = os.path.splitext(candidate)[1].lower()
            if ext in RENDERED_ALL_EXTS:
                return candidate
        return None

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
        """Attach the Refresh ▾ dropdown (this section + Clips-only Steam extras)."""
        btn = getattr(self, "btn_refresh", None)
        if btn is None or not hasattr(btn, "menu_btn"):
            return
        # Avoid stacking handlers if setup runs more than once.
        from steempeg.ui.signal_utils import safe_disconnect

        safe_disconnect(btn.menu_btn.clicked)

        def _show_menu():
            menu = QMenu(self.ui)
            menu.setStyleSheet(ut.library_menu_stylesheet())
            mode = getattr(self, "_library_panel_mode", "clips")

            if mode == "rendered":
                section_label = "🔄  Refresh Rendered videos"
                section_tip = "Rescan the Records / export folder only."
            elif mode == "screenshots":
                section_label = "🔄  Refresh Screenshots"
                section_tip = "Rescan the Screenshots folder only."
            else:
                section_label = "🔄  Refresh Clips Manager"
                section_tip = "Rescan Clips Manager folders only."

            action_section = menu.addAction(section_label)
            action_section.setToolTip(section_tip)
            action_section.triggered.connect(self.refresh_active_library_section)

            if mode == "clips":
                menu.addSeparator()
                action_icons = menu.addAction("🖼️  Refresh game icons from Steam…")
                action_names = menu.addAction("🏷️  Refresh game names from Steam…")
                menu.addSeparator()
                action_health = menu.addAction("🩺  Re-check clip health (ffprobe)…")

                action_icons.setToolTip(
                    "Re-downloads icons for games in your library. Uses the Steam CDN — "
                    "run only when icons look wrong."
                )
                action_names.setToolTip(
                    "Re-fetches display names from the Steam store API. Uses network — "
                    "run only when a title is wrong."
                )
                action_health.setToolTip(
                    "Runs a full playback health pass (may call ffprobe per clip). "
                    "Does not rescan folders."
                )
                action_icons.triggered.connect(self.refresh_steam_icons)
                action_names.triggered.connect(self.refresh_steam_names)
                action_health.triggered.connect(self.recheck_clip_health)
            elif mode == "rendered":
                menu.addSeparator()
                action_rh = menu.addAction("🩺  Re-check rendered health…")
                action_rh.setToolTip(
                    "Re-probe duration metadata for files in the Rendered videos list "
                    "(not a full A/V corruption scan)."
                )
                action_rh.triggered.connect(self.recheck_rendered_health)

            menu.exec(btn.menu_btn.mapToGlobal(QPoint(0, btn.menu_btn.height())))

        btn.menu_btn.clicked.connect(_show_menu)

    def refresh_active_library_section(self) -> None:
        """Rescan only the active library tab (Clips / Rendered / Screenshots)."""
        mode = getattr(self, "_library_panel_mode", "clips")
        if mode == "rendered":
            if hasattr(self, "set_status"):
                self.set_status("Refreshing Rendered videos…")
            if hasattr(self, "refresh_rendered_library"):
                self.refresh_rendered_library()
            return
        if mode == "screenshots":
            if hasattr(self, "set_status"):
                self.set_status("Refreshing Screenshots…")
            if hasattr(self, "refresh_screenshots_library"):
                self.refresh_screenshots_library(force=True)
            return
        if hasattr(self, "set_status"):
            self.set_status("Refreshing Clips Manager…")
        LibraryMixin.refresh_library(self)

    def refresh_all_libraries(self) -> None:
        """Rescan every library panel (Clips + Rendered + Screenshots)."""
        if hasattr(self, "set_status"):
            self.set_status("Refreshing all libraries…")
        # Clips — always (even if another tab is active).
        LibraryMixin.refresh_library(self)
        if hasattr(self, "refresh_rendered_library"):
            self.refresh_rendered_library()
        if hasattr(self, "refresh_screenshots_library"):
            self.refresh_screenshots_library(force=True)

    def _refresh_menu_busy(self) -> bool:
        for attr in (
            "_health_recheck_worker",
            "_steam_icons_worker",
            "_steam_names_worker",
            "_screenshot_names_worker",
        ):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                return True
        return False

    def _start_startup_steam_meta_refresh(self) -> None:
        """Full launch: refresh Steam icons then names after the clips list is up.

        Same workers as Refresh ▾ — background QThreads so the UI stays usable.
        Quiet: status/logs only, no modal dialogs.
        """
        if self._refresh_menu_busy():
            QTimer.singleShot(500, self._start_startup_steam_meta_refresh)
            return
        app_ids = sorted(self._collect_library_app_ids())
        if not app_ids:
            logging.info(
                "Startup Full: no library app ids for Steam icons/names refresh"
            )
            return
        logging.info(
            "Startup Full: refreshing %d game icon(s) then name(s) from Steam",
            len(app_ids),
        )
        self.refresh_steam_icons(quiet=True, chain_names=True)

    def refresh_steam_icons(self, *, quiet: bool = False, chain_names: bool = False):
        """Re-download game icons for every app id in the current library list."""
        if self._refresh_menu_busy():
            if hasattr(self, "set_status"):
                self.set_status("A library refresh job is already running…")
            return
        app_ids = sorted(self._collect_library_app_ids())
        if not app_ids:
            return
        self._steam_refresh_quiet = bool(quiet)
        self._steam_refresh_chain_names = bool(chain_names)
        self.game_icons_cache.clear()
        if hasattr(self, "set_status"):
            self.set_status(f"Refreshing game icons from Steam (0/{len(app_ids)})…")

        worker = SteamIconsRefreshWorker(app_ids, self.cache_dir, self.ui)
        self._steam_icons_worker = worker
        worker.progress.connect(self._on_steam_icons_progress)
        worker.finished_icons.connect(self._on_steam_icons_finished)
        worker.failed.connect(self._on_refresh_worker_failed)
        worker.start()

    def _on_steam_icons_progress(self, done: int, total: int) -> None:
        if hasattr(self, "set_status"):
            self.set_status(f"Refreshing game icons from Steam ({done}/{total})…")

    def _on_steam_icons_finished(self, payload: dict) -> None:
        self._steam_icons_worker = None
        quiet = bool(getattr(self, "_steam_refresh_quiet", False))
        chain = bool(getattr(self, "_steam_refresh_chain_names", False))
        self._steam_refresh_quiet = False
        self._steam_refresh_chain_names = False
        updated = int(payload.get("updated") or 0)
        total = int(payload.get("total") or 0)

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
        msg = f"Refreshed {updated} of {total} game icon(s) from Steam."
        if hasattr(self, "set_status"):
            self.set_status(msg)
        if quiet:
            logging.info("%s", msg)
        else:
            steempeg_information(self.ui, "Game icons", msg)
        if chain:
            QTimer.singleShot(0, lambda: self.refresh_steam_names(quiet=True))

    def refresh_steam_names(self, *, quiet: bool = False):
        """Re-fetch game names from Steam for every app id in the library list."""
        if self._refresh_menu_busy():
            if hasattr(self, "set_status"):
                self.set_status("A library refresh job is already running…")
            return
        app_ids = sorted(self._collect_library_app_ids())
        if not app_ids:
            return
        self._steam_refresh_quiet = bool(quiet)
        self._steam_refresh_chain_names = False
        if hasattr(self, "set_status"):
            self.set_status(f"Refreshing game names from Steam (0/{len(app_ids)})…")

        worker = SteamNamesRefreshWorker(app_ids, self.ui)
        self._steam_names_worker = worker
        worker.progress.connect(self._on_steam_names_progress)
        worker.finished_names.connect(self._on_steam_names_finished)
        worker.failed.connect(self._on_refresh_worker_failed)
        worker.start()

    def _on_steam_names_progress(self, done: int, total: int) -> None:
        if hasattr(self, "set_status"):
            self.set_status(f"Refreshing game names from Steam ({done}/{total})…")

    def _on_steam_names_finished(self, payload: dict) -> None:
        self._steam_names_worker = None
        quiet = bool(getattr(self, "_steam_refresh_quiet", False))
        self._steam_refresh_quiet = False
        self._steam_refresh_chain_names = False
        names = payload.get("names") or {}
        for app_id, name in names.items():
            self.game_names_cache[app_id] = name
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
        if hasattr(self, "apply_screenshot_game_names"):
            try:
                self.apply_screenshot_game_names(names)
            except Exception:
                logging.debug("Screenshot name apply after Steam refresh failed", exc_info=True)
        updated = int(payload.get("updated") or 0)
        total = int(payload.get("total") or 0)
        msg = f"Refreshed {updated} of {total} game name(s) from Steam."
        if hasattr(self, "set_status"):
            self.set_status(msg)
        if quiet:
            logging.info("%s", msg)
        else:
            steempeg_information(self.ui, "Game names", msg)

    def recheck_clip_health(self):
        """Full health pass for listed clips (ffprobe when needed). Off the UI thread."""
        if not hasattr(self.ui, "table_clips"):
            return
        if self._refresh_menu_busy():
            if hasattr(self, "set_status"):
                self.set_status("A library refresh job is already running…")
            return

        clip_paths = []
        for row in range(self.ui.table_clips.rowCount()):
            item = self.ui.table_clips.item(row, 0)
            if not item:
                continue
            clip_path = item.data(Qt.UserRole)
            if clip_path and os.path.isdir(clip_path):
                clip_paths.append(clip_path)
        if not clip_paths:
            return

        self._ensure_clip_health_cache()
        if hasattr(self, "set_status"):
            self.set_status(f"Re-checking clip health (0/{len(clip_paths)})…")

        worker = ClipHealthRecheckWorker(
            clip_paths, getattr(self, "_clip_health_cache", {}), self.ui
        )
        self._health_recheck_worker = worker
        worker.progress.connect(self._on_health_recheck_progress)
        worker.finished_recheck.connect(self._on_health_recheck_finished)
        worker.failed.connect(self._on_refresh_worker_failed)
        worker.start()

    def recheck_rendered_health(self) -> None:
        """Force-reprobe duration health for every file in the Rendered videos list."""
        if not hasattr(self, "table_rendered"):
            if hasattr(self, "_ensure_rendered_widgets"):
                self._ensure_rendered_widgets()
        table = getattr(self, "table_rendered", None)
        if table is None:
            return
        if self._refresh_menu_busy():
            if hasattr(self, "set_status"):
                self.set_status("A library refresh job is already running…")
            return

        paths: list[str] = []
        for row in range(table.rowCount()):
            cell = table.item(row, 0)
            if not cell:
                continue
            path = cell.data(Qt.ItemDataRole.UserRole)
            if path and os.path.isfile(path):
                paths.append(path)
        if not paths:
            if hasattr(self, "set_status"):
                self.set_status("No rendered files to check.")
            return

        if hasattr(self, "set_status"):
            self.set_status(f"Re-checking rendered health (0/{len(paths)})…")

        healthy = degraded = dead = cured = 0
        for i, path in enumerate(paths, start=1):
            assessment = self._resolve_rendered_health(path, force=True)
            level = assessment.report.level
            if level == health.ClipHealth.HEALTHY:
                healthy += 1
            elif level == health.ClipHealth.DEGRADED:
                degraded += 1
            elif level == health.ClipHealth.CURED:
                cured += 1
            else:
                dead += 1
            if hasattr(self, "set_status") and (i == len(paths) or i % 5 == 0):
                self.set_status(f"Re-checking rendered health ({i}/{len(paths)})…")
                QApplication.processEvents()

        if hasattr(self, "update_clip_health_button"):
            self.update_clip_health_button()
        if hasattr(self, "set_status"):
            self.set_status(
                f"Rendered health: {healthy} healthy · {degraded} issues · "
                f"{cured} cured · {dead} dead"
            )
        steempeg_information(
            self.ui,
            "Rendered health",
            f"Checked {len(paths)} file(s).\n\n"
            f"Healthy: {healthy}\n"
            f"Issues: {degraded}\n"
            f"Cured: {cured}\n"
            f"Dead: {dead}\n\n"
            "This checks duration metadata only — not mid-file A/V corruption.",
        )

    def _on_health_recheck_progress(self, done: int, total: int) -> None:
        if hasattr(self, "set_status"):
            self.set_status(f"Re-checking clip health ({done}/{total})…")

    def _on_health_recheck_finished(self, payload: dict) -> None:
        self._health_recheck_worker = None
        results = payload.get("results") or {}
        counts = payload.get("counts") or {}
        cache = payload.get("health_cache")
        if isinstance(cache, dict):
            self._clip_health_cache = cache
            self._save_clip_health_cache()

        for row in range(self.ui.table_clips.rowCount()):
            item = self.ui.table_clips.item(row, 0)
            if not item:
                continue
            clip_path = item.data(Qt.UserRole)
            if not clip_path:
                continue
            entry = results.get(os.path.normpath(clip_path))
            if not entry:
                continue
            level, issues = entry
            item.setData(_CLIP_HEALTH_ROLE, level)
            item.setData(_CLIP_HEALTH_ISSUES_ROLE, "\n".join(issues or []))

        if hasattr(self, "build_netflix_grid"):
            self.build_netflix_grid()
        if hasattr(self, "update_clip_health_button"):
            self.update_clip_health_button()

        checked = int(payload.get("checked") or len(results))
        healthy = int(counts.get(health.ClipHealth.HEALTHY.value, 0))
        cured = int(counts.get(health.ClipHealth.CURED.value, 0))
        issues_n = int(counts.get(health.ClipHealth.DEGRADED.value, 0))
        dead = int(counts.get(health.ClipHealth.DEAD.value, 0))
        status = (
            f"Re-checked {checked} clip(s) — "
            f"healthy {healthy + cured}, issues {issues_n}, dead {dead}."
        )
        if hasattr(self, "set_status"):
            self.set_status(status)

        body = (
            f"Checked {checked} clip(s).\n\n"
            f"Healthy: {healthy}\n"
            f"Cured: {cured}\n"
            f"Issues: {issues_n}\n"
            f"Dead: {dead}"
        )
        steempeg_information(self.ui, "Clip health re-check", body)

    def _on_refresh_worker_failed(self, message: str) -> None:
        quiet = bool(getattr(self, "_steam_refresh_quiet", False))
        chain = bool(getattr(self, "_steam_refresh_chain_names", False))
        self._steam_refresh_quiet = False
        self._steam_refresh_chain_names = False
        self._health_recheck_worker = None
        self._steam_icons_worker = None
        self._steam_names_worker = None
        if hasattr(self, "set_status"):
            self.set_status(f"Refresh failed: {message}")
        if quiet:
            logging.warning("Startup Steam refresh failed: %s", message)
            # Icons failed mid-Full chain — still try names.
            if chain:
                QTimer.singleShot(0, lambda: self.refresh_steam_names(quiet=True))
            return
        steempeg_information(
            self.ui,
            "Refresh failed",
            f"Something went wrong during the background refresh.\n\n{message}",
        )
    def _stop_library_scan(self):
        worker = getattr(self, "_library_scan_worker", None)
        if worker is not None:
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(5000)
            self._library_scan_worker = None

    def _stop_clip_poster_backfill(self):
        worker = getattr(self, "_clip_poster_worker", None)
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(3000)
        self._clip_poster_worker = None

    def _schedule_clip_poster_backfill(self, *, skip_ui_probe: bool = False):
        """Generate ffmpeg posters for clips with no thumbnail.jpg on disk.

        ``skip_ui_probe`` — Skip startup: don't ``isdir``/resolve 250+ library
        paths on the GUI thread; hand every row to the worker and let it decide.
        """
        if not hasattr(self, "cache_dir") or not hasattr(self.ui, "table_clips"):
            return

        missing = []
        for row in range(self.ui.table_clips.rowCount()):
            item = self.ui.table_clips.item(row, 0)
            if not item:
                continue
            clip_path = item.data(Qt.UserRole)
            if not clip_path:
                continue
            if skip_ui_probe:
                missing.append(clip_path)
                continue
            if not os.path.isdir(clip_path):
                continue
            if resolve_clip_thumbnail(clip_path, self.cache_dir, allow_generate=False):
                continue
            missing.append(clip_path)

        if not missing:
            return

        self._stop_clip_poster_backfill()
        self._clip_poster_worker = ClipPosterBackfillWorker(missing, self.cache_dir, self.ui)
        self._clip_poster_worker.poster_ready.connect(self._on_clip_poster_ready)
        self._clip_poster_worker.finished_batch.connect(self._on_clip_poster_batch_done)
        self._clip_poster_worker.start()

    def _on_clip_poster_ready(self, clip_path: str, thumb_path: str):
        if not hasattr(self, "grid_clips"):
            return
        norm = os.path.normpath(clip_path)
        for i in range(self.grid_clips.count()):
            item = self.grid_clips.item(i)
            if item is None:
                continue
            item_path = item.data(Qt.UserRole + 1)
            if not item_path or os.path.normpath(item_path) != norm:
                continue
            card = self.grid_clips.itemWidget(item)
            if card is not None and hasattr(card, "set_thumbnail"):
                card.set_thumbnail(thumb_path)
            # Keep DEAD dim after poster fill; clear no-preview dim via set_thumbnail.
            if card is not None and hasattr(card, "set_unavailable"):
                table = getattr(getattr(self, "ui", None), "table_clips", None)
                row = item.data(Qt.UserRole)
                is_dead = False
                if table is not None and isinstance(row, int):
                    title_item = table.item(row, 0)
                    if title_item is not None and not title_item.data(_CLIP_CURED_ROLE):
                        is_dead = title_item.data(_CLIP_HEALTH_ROLE) == health.ClipHealth.DEAD.value
                card.set_unavailable(dead=is_dead, no_preview=False)
            break

    def _on_clip_poster_batch_done(self):
        self._clip_poster_worker = None

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

        def _report_from_item(item):
            if not item:
                return None
            row_path = item.data(Qt.UserRole)
            if not row_path or os.path.normpath(row_path) != norm:
                return None
            level = item.data(_CLIP_HEALTH_ROLE)
            issues_raw = item.data(_CLIP_HEALTH_ISSUES_ROLE) or ""
            if not level:
                return None
            issues = [line for line in issues_raw.split("\n") if line]
            try:
                enum_level = health.ClipHealth(level)
            except ValueError:
                enum_level = health.ClipHealth.DEAD
            return health.ClipHealthReport(enum_level, issues)

        # Hot path: current row matches nearly every select/open.
        row = table.currentRow()
        if row >= 0:
            hit = _report_from_item(table.item(row, 0))
            if hit is not None:
                return hit

        for row in range(table.rowCount()):
            hit = _report_from_item(table.item(row, 0))
            if hit is not None:
                return hit
        return health.assess_clip_health(clip_path)

    def get_clip_display_health_report(self, clip_path) -> health.ClipHealthReport:
        """Filesystem health with a Cured overlay when salvage playback was validated."""
        report = self.get_clip_health_report(clip_path)
        if report.level == health.ClipHealth.DEAD and self._is_clip_cured(clip_path):
            issues = list(report.issues)
            issues.append("Salvage playback verified — clip is Cured")
            return health.ClipHealthReport(health.ClipHealth.CURED, issues)
        return report

    def _row_display_health_level(self, item) -> str:
        if item and item.data(_CLIP_CURED_ROLE):
            return health.ClipHealth.CURED.value
        return item.data(_CLIP_HEALTH_ROLE) or health.ClipHealth.HEALTHY.value

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
            if item.data(_CLIP_CURED_ROLE):
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
            steempeg_information(self.ui, "Dead Clips", "No dead clips in the library.")
            return

        if not steempeg_question(
            self.ui,
            "Delete ALL Dead Clips",
            f"Permanently delete {len(dead_paths)} dead clip folder(s)?",
            detail="This cannot be undone.",
        ):
            return

        if hasattr(self, "release_media_before_delete_any"):
            self.release_media_before_delete_any(dead_paths)

        failed = []
        for clip_path in dead_paths:
            try:
                if os.path.exists(clip_path):
                    shutil.rmtree(clip_path)
                    logging.info(f"Deleted dead clip folder: {clip_path}")
                    if hasattr(self, "_on_queue_source_removed"):
                        self._on_queue_source_removed(clip_path)
            except Exception as exc:
                logging.error(f"Failed to delete dead clip {clip_path}: {exc}")
                failed.append(os.path.basename(clip_path))

        self.scan_clips()

        if failed:
            steempeg_warning(
                self.ui,
                "Delete ALL Dead Clips",
                f"Deleted {len(dead_paths) - len(failed)} of {len(dead_paths)}.\n"
                f"Could not remove: {', '.join(failed)}",
            )
        else:
            steempeg_information(
                self.ui,
                "Delete ALL Dead Clips",
                f"Removed {len(dead_paths)} dead clip(s).",
            )

    def update_clip_health_button(self):
        if not hasattr(self, "btn_clip_health"):
            return

        # Flat exports (Rendered shelf / Open in Steempeg) — never DASH folder health.
        rendered_path = self._active_rendered_preview_path()
        if rendered_path:
            report = self.get_rendered_display_health_report(rendered_path)
            self._apply_clip_health_button_style(report)
            return

        clip_path = None
        if hasattr(self, "_current_header_clip_path"):
            clip_path = self._current_header_clip_path()
        if not clip_path and hasattr(self.ui, "table_clips") and self.ui.table_clips.currentRow() >= 0:
            item = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0)
            if item:
                clip_path = item.data(Qt.UserRole)

        # Files are not Steam DASH clips — hide rather than assess as empty folders.
        if not clip_path or os.path.isfile(clip_path):
            self.btn_clip_health.hide()
            return

        report = self.get_clip_display_health_report(clip_path)
        self._apply_clip_health_button_style(report)

    def _apply_clip_health_button_style(self, report) -> None:
        color = report.color
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        pad = getattr(self, "_player_header_status_pad", None) or "4px 12px 4px 10px"
        font_px = int(getattr(self, "_player_header_status_font", 13) or 13)
        icon_px = int(getattr(self, "_player_header_status_icon", 18) or 18)
        min_h = int(getattr(self, "_player_header_status_min_h", 30) or 30)
        self.btn_clip_health.setToolTip(report.summary())
        self.btn_clip_health.setIcon(health_icon(report.level, icon_px))
        self.btn_clip_health.setIconSize(QSize(icon_px, icon_px))
        self.btn_clip_health.setText(f" {report.label}")
        self.btn_clip_health.setMinimumHeight(min_h)
        self.btn_clip_health.setMinimumWidth(0)
        self.btn_clip_health.setMaximumWidth(16777215)
        try:
            from steempeg.ui.player_header_layout import player_header_chip_qfont

            self.btn_clip_health.setFont(player_header_chip_qfont(font_px))
        except Exception:
            pass
        self.btn_clip_health.setStyleSheet(
            f"QPushButton {{"
            f"background-color: rgba({r}, {g}, {b}, 0.22);"
            f"color: {color};"
            f"border: 2px solid {color};"
            f"border-radius: 8px;"
            f"font-weight: bold;"
            f"font-size: {font_px}px;"
            f"padding: {pad};"
            f"font-family: {tok.FONT_APP};"
            f"}}"
            f"QPushButton:hover {{ background-color: rgba({r}, {g}, {b}, 0.35); }}"
        )
        self.btn_clip_health.show()

    def show_clip_health_menu(self):
        rendered_path = self._active_rendered_preview_path()
        if rendered_path:
            self._show_rendered_health_menu(rendered_path)
            return

        clip_path = None
        if hasattr(self, "_current_header_clip_path"):
            clip_path = self._current_header_clip_path()
        if not clip_path and hasattr(self.ui, "table_clips") and self.ui.table_clips.currentRow() >= 0:
            item = self.ui.table_clips.item(self.ui.table_clips.currentRow(), 0)
            if item:
                clip_path = item.data(Qt.UserRole)
        if not clip_path or os.path.isfile(clip_path):
            return

        display = self.get_clip_display_health_report(clip_path)
        fs_report = self.get_clip_health_report(clip_path)
        menu = QMenu(self.ui)
        menu.setStyleSheet(ut.health_menu_stylesheet())

        # Title row as a widget: icon sits next to the label (not a reserved muted
        # left column), and keeps full color even though the row is non-clickable.
        title_host = QWidget(menu)
        title_row = QHBoxLayout(title_host)
        title_row.setContentsMargins(12, 8, 16, 8)
        title_row.setSpacing(8)
        title_icon = QLabel()
        title_icon.setPixmap(health_icon(display.level, 16).pixmap(16, 16))
        title_icon.setFixedSize(16, 16)
        title_lbl = QLabel(display.label)
        title_lbl.setStyleSheet(
            f"color: {display.color}; font-weight: bold; font-size: 13px;"
            f" font-family: {tok.FONT_APP}; background: transparent;"
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

        if display.issues:
            for issue in display.issues:
                act = menu.addAction(f"• {issue}")
                act.setEnabled(False)
        else:
            act = menu.addAction("No issues detected.")
            act.setEnabled(False)

        if fs_report.level == health.ClipHealth.DEAD:
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

    def _show_rendered_health_menu(self, file_path: str) -> None:
        display = self.get_rendered_display_health_report(file_path)
        assessment = self._resolve_rendered_health(file_path)
        menu = QMenu(self.ui)
        menu.setStyleSheet(ut.health_menu_stylesheet())

        title_host = QWidget(menu)
        title_row = QHBoxLayout(title_host)
        title_row.setContentsMargins(12, 8, 16, 8)
        title_row.setSpacing(8)
        title_icon = QLabel()
        title_icon.setPixmap(health_icon(display.level, 16).pixmap(16, 16))
        title_icon.setFixedSize(16, 16)
        title_lbl = QLabel(display.label)
        title_lbl.setStyleSheet(
            f"color: {display.color}; font-weight: bold; font-size: 13px;"
            f" font-family: {tok.FONT_APP}; background: transparent;"
        )
        title_row.addWidget(title_icon, 0, Qt.AlignVCenter)
        title_row.addWidget(title_lbl, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        title_act = QWidgetAction(menu)
        title_act.setDefaultWidget(title_host)
        title_act.setEnabled(True)
        menu.addAction(title_act)
        menu.addSeparator()

        if display.issues:
            for issue in display.issues:
                act = menu.addAction(f"• {issue}")
                act.setEnabled(False)
        else:
            act = menu.addAction("Duration metadata looks consistent.")
            act.setEnabled(False)

        scope = menu.addAction(
            "Scope: duration metadata only — not mid-file A/V corruption."
        )
        scope.setEnabled(False)

        stream_sec = assessment.duration_stream_sec or assessment.duration_sec
        fmt_sec = assessment.duration_format_sec
        if stream_sec or fmt_sec:
            menu.addSeparator()
            detail_parts = []
            if stream_sec:
                detail_parts.append(f"Stream {float(stream_sec):.2f}s")
            if fmt_sec:
                detail_parts.append(f"Container {float(fmt_sec):.2f}s")
            detail = menu.addAction(" · ".join(detail_parts))
            detail.setEnabled(False)

        if stream_sec and assessment.report.level != health.ClipHealth.DEAD:
            menu.addSeparator()
            fix_act = menu.addAction("Fix timeline length (sidecar only)")
            fix_act.setToolTip(
                "Rewrite the .steempeg.json duration so the purple bar matches "
                "stream length. Does not re-encode or repair broken A/V."
            )
            fix_act.triggered.connect(lambda: self.fix_rendered_duration(file_path))

            remux_act = menu.addAction("Remux shortest (container header)")
            remux_act.setToolTip(
                "ffmpeg -c copy -shortest: fix container duration vs real packets "
                "(frozen-tail / Original). Does not fix mid-file corruption."
            )
            remux_act.triggered.connect(lambda: self.remux_rendered_shortest(file_path))

        menu.exec(self.btn_clip_health.mapToGlobal(QPoint(0, self.btn_clip_health.height())))

    def fix_rendered_duration(self, file_path: str) -> None:
        """Rewrite companion duration_sec from stream probe and mark cured."""
        from steempeg.core.rendered_health import apply_assessment_to_companion
        from steempeg.core.rendered_media import is_sane_media_duration

        if not file_path or not os.path.isfile(file_path):
            return
        assessment = self._resolve_rendered_health(file_path, force=True)
        playable = assessment.duration_stream_sec or assessment.duration_sec
        if not is_sane_media_duration(playable):
            steempeg_warning(
                self.ui,
                "Fix duration",
                "Could not read a usable stream duration for this file.",
            )
            return
        apply_assessment_to_companion(
            file_path,
            assessment,
            cured=True,
            cache_dir=getattr(self, "cache_dir", None),
        )
        self._store_rendered_health_cache(file_path, assessment)
        self._refresh_rendered_playback_duration(file_path, float(playable))
        if hasattr(self, "update_clip_health_button"):
            self.update_clip_health_button()
        steempeg_information(
            self.ui,
            "Fix timeline length",
            f"Purple-bar / sidecar duration set to {float(playable):.2f}s.\n\n"
            "This does not repair video or audio content.",
        )

    def remux_rendered_shortest(self, file_path: str) -> None:
        """Remux with -shortest, re-assess, mark cured, reload preview if needed."""
        from steempeg.core.rendered_health import (
            apply_assessment_to_companion,
            remux_shortest,
        )
        from steempeg.core.rendered_media import is_sane_media_duration, resolve_ffmpeg_exe

        if not file_path or not os.path.isfile(file_path):
            return
        if not steempeg_question(
            self.ui,
            "Remux shortest",
            "Re-mux this file with ffmpeg -c copy -shortest?\n\n"
            "Rewrites the container so duration follows real packets "
            "(helps frozen-tail / bad Original headers).\n"
            "Does not re-encode and will not fix mid-file corruption.",
        ):
            return

        ffmpeg_exe = resolve_ffmpeg_exe()
        ok = remux_shortest(file_path, ffmpeg_exe=ffmpeg_exe)
        if not ok:
            steempeg_warning(
                self.ui,
                "Remux shortest",
                "Remux failed. The original file was left unchanged when possible.",
            )
            return

        assessment = self._resolve_rendered_health(file_path, force=True)
        apply_assessment_to_companion(
            file_path,
            assessment,
            cured=True,
            cache_dir=getattr(self, "cache_dir", None),
        )
        self._store_rendered_health_cache(file_path, assessment)
        playable = assessment.duration_stream_sec or assessment.duration_sec
        if is_sane_media_duration(playable):
            self._refresh_rendered_playback_duration(file_path, float(playable))
        playing = getattr(self, "_rendered_media_path", None)
        if playing and os.path.normpath(playing) == os.path.normpath(file_path):
            if hasattr(self, "play_media_file"):
                self.play_media_file(file_path)
        if hasattr(self, "update_clip_health_button"):
            self.update_clip_health_button()
        steempeg_information(
            self.ui,
            "Remux shortest",
            "Container remuxed and duration metadata re-checked.\n"
            "This does not repair mid-file A/V corruption.",
        )

    def _refresh_rendered_playback_duration(self, file_path: str, duration_sec: float) -> None:
        from steempeg.core.rendered_media import is_sane_media_duration

        if not is_sane_media_duration(duration_sec):
            return
        playing = getattr(self, "_rendered_media_path", None)
        if not playing or os.path.normpath(playing) != os.path.normpath(file_path):
            return
        self._rendered_duration_cache = (os.path.normpath(file_path), float(duration_sec))
        if hasattr(self, "_apply_playback_duration"):
            self._apply_playback_duration(float(duration_sec))

    def force_play_dead_clip(
        self, clip_path: str, *, skip_confirm: bool = False, skip_verify: bool = False
    ) -> None:
        """Best-effort salvage preview for a dead clip (user-initiated gamble).

        Tries to synthesize a manifest from surviving chunks when none is playable,
        then forces playback bypassing the dead-clip guard. The clip's health is left
        untouched — a successful force-play does not re-classify it."""
        if not clip_path or not os.path.isdir(clip_path):
            return

        from steempeg.ui.dead_clip_dialogs import (
            DeadClipSalvageDialog,
            DeadClipSalvageFailedDialog,
            dialog_theme,
        )

        if not skip_confirm:
            confirm = DeadClipSalvageDialog(parent=self.ui, **dialog_theme(self))
            if not (confirm.exec() and confirm.accepted_yes):
                return

        # Always rebuild a fresh salvage manifest from the *decodable* data on disk
        # (valid init-stream0 + non-empty chunks). We deliberately ignore any stale
        # session_recovered.mpd — playing that when the init is corrupt just opens an
        # empty stream (0 frames / black). recover_orphaned_clip bails without a valid
        # init, so a None result means there is genuinely nothing to decode.
        mpd_override = self._build_salvage_manifest(clip_path)

        if not mpd_override:
            DeadClipSalvageFailedDialog(parent=self.ui, **dialog_theme(self)).exec()
            return

        # Register so get_all_mpd_paths resolves the salvage manifest everywhere
        # (preview + render), then populate render settings from it so the revived
        # clip is renderable. Health stays Dead — this is an explicit user salvage.
        self._register_salvaged_clip(clip_path)
        if skip_verify or self._is_clip_cured(clip_path):
            self._salvage_verify_pending = None
            self._salvage_verify_shown = True
        else:
            self._salvage_verify_pending = os.path.normpath(clip_path)
            self._salvage_verify_shown = False
            self._reset_salvage_playback_evidence(clip_path)
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

    def _salvage_verified_cache_path(self) -> str:
        return os.path.join(self.cache_dir, "salvage_verified_cache.json")

    def _ensure_salvage_verified_cache(self) -> None:
        if not hasattr(self, "_salvage_verified_cache"):
            self._salvage_verified_cache = json_cache.read_json(
                self._salvage_verified_cache_path(), default={}
            )

    def _save_salvage_verified_cache(self) -> None:
        self._ensure_salvage_verified_cache()
        json_cache.write_json(self._salvage_verified_cache_path(), self._salvage_verified_cache)

    def _clip_folder_mtime(self, clip_path: str) -> float:
        try:
            return os.path.getmtime(clip_path)
        except OSError:
            return 0.0

    def _salvage_manifests_on_disk(self, clip_path: str) -> list[str]:
        mpds: list[str] = []
        for root, _dirs, files in os.walk(clip_path):
            if "session_salvage.mpd" in files:
                mpds.append(os.path.join(root, "session_salvage.mpd"))
        return sorted(mpds)

    def _salvage_verified_entry(self, clip_path: str) -> dict | None:
        self._ensure_salvage_verified_cache()
        norm = os.path.normpath(clip_path)
        entry = self._salvage_verified_cache.get(norm)
        if not entry or not entry.get("cured"):
            return None
        if not os.path.isdir(norm):
            return None
        mtime = self._clip_folder_mtime(norm)
        if not mtime:
            return None
        # Cured is user-verified — marker/thumbnail/cache writes must not revoke it.
        if entry.get("mtime") != mtime:
            entry = dict(entry)
            entry["mtime"] = mtime
            self._salvage_verified_cache[norm] = entry
            self._save_salvage_verified_cache()
        if self._salvage_manifests_on_disk(norm):
            self._register_salvaged_clip(norm)
        return entry

    def _is_clip_cured(self, clip_path: str) -> bool:
        entry = self._salvage_verified_entry(clip_path)
        return bool(entry and entry.get("cured"))

    def _is_salvage_verified(self, clip_path: str) -> bool:
        return self._is_clip_cured(clip_path)

    def _is_salvage_auto_play(self, clip_path: str) -> bool:
        entry = self._salvage_verified_entry(clip_path)
        return bool(entry and entry.get("auto_play"))

    def _reset_salvage_playback_evidence(self, clip_path: str) -> None:
        norm = os.path.normpath(clip_path)
        if not hasattr(self, "_salvage_playback_evidence"):
            self._salvage_playback_evidence = {}
        self._salvage_playback_evidence[norm] = {"max_time_pos": 0.0, "had_frame": False}

    def _record_salvage_playback_evidence(self, clip_path: str | None = None) -> None:
        pending = clip_path or getattr(self, "_salvage_verify_pending", None)
        if not pending:
            return
        norm = os.path.normpath(pending)
        evidence = getattr(self, "_salvage_playback_evidence", {}).get(norm)
        if evidence is None:
            return
        player = getattr(self, "player", None)
        if not player:
            return
        try:
            if bool(getattr(player, "idle_active", True)):
                return
            width = int(getattr(player, "width", 0) or 0)
            time_pos = float(getattr(player, "time_pos", 0) or 0)
            if width > 0:
                evidence["had_frame"] = True
            if time_pos > evidence.get("max_time_pos", 0.0):
                evidence["max_time_pos"] = time_pos
        except Exception:
            return

    def _validate_salvage_playback(self, clip_path: str) -> tuple[bool, str]:
        """Internal check that salvage playback is actually decoding."""
        player = getattr(self, "player", None)
        if not player:
            return False, "Player is not available."

        norm = os.path.normpath(clip_path)
        try:
            if bool(getattr(player, "idle_active", True)):
                return False, "Playback is idle."

            loaded = os.path.normpath(str(getattr(player, "path", "") or ""))
            salvage_mpds = [os.path.normpath(p) for p in self._salvage_manifests_on_disk(clip_path)]
            if salvage_mpds and loaded not in salvage_mpds:
                return False, "The salvage manifest is not the active media."

            width = int(getattr(player, "width", 0) or 0)
            time_pos = float(getattr(player, "time_pos", 0) or 0)
            evidence = getattr(self, "_salvage_playback_evidence", {}).get(norm, {})
            max_time = float(evidence.get("max_time_pos", 0.0) or 0.0)
            had_frame = bool(evidence.get("had_frame"))

            if width > 0 or had_frame:
                return True, ""
            if max(time_pos, max_time) >= 0.35:
                return True, ""
            return False, "No decoded playback was detected."
        except Exception as exc:
            return False, str(exc)

    def _mark_clip_cured(self, clip_path: str, *, auto_play: bool) -> None:
        norm = os.path.normpath(clip_path)
        self._ensure_salvage_verified_cache()
        self._salvage_verified_cache[norm] = {
            "mtime": self._clip_folder_mtime(clip_path),
            "auto_play": bool(auto_play),
            "cured": True,
        }
        self._save_salvage_verified_cache()
        self._register_salvaged_clip(clip_path)
        self._apply_cured_status_to_library_row(clip_path)

    def _apply_cured_status_to_library_row(self, clip_path: str) -> None:
        if not hasattr(self.ui, "table_clips"):
            return
        norm = os.path.normpath(clip_path)
        for row in range(self.ui.table_clips.rowCount()):
            item = self.ui.table_clips.item(row, 0)
            if not item:
                continue
            row_path = item.data(Qt.UserRole)
            if row_path and os.path.normpath(row_path) == norm:
                item.setData(_CLIP_CURED_ROLE, True)
                break
        if hasattr(self, "build_netflix_grid"):
            self.build_netflix_grid()
        if hasattr(self, "update_clip_health_button"):
            self.update_clip_health_button()

    def _sync_cured_role_on_item(self, item, clip_path: str) -> None:
        item.setData(_CLIP_CURED_ROLE, bool(self._is_clip_cured(clip_path)))

    def _mark_salvage_verified(self, clip_path: str, *, auto_play: bool) -> None:
        self._mark_clip_cured(clip_path, auto_play=auto_play)

    def _clear_salvage_verified(self, clip_path: str) -> None:
        norm = os.path.normpath(clip_path)
        self._ensure_salvage_verified_cache()
        if norm in self._salvage_verified_cache:
            del self._salvage_verified_cache[norm]
            self._save_salvage_verified_cache()

    def restore_salvage_verified_clips(self) -> None:
        """Rehydrate salvage manifests for cured clips saved from past sessions."""
        self._ensure_salvage_verified_cache()
        stale: list[str] = []
        changed = False
        for norm, entry in list(self._salvage_verified_cache.items()):
            if not entry.get("cured"):
                stale.append(norm)
                continue
            if not os.path.isdir(norm):
                stale.append(norm)
                continue
            mtime = self._clip_folder_mtime(norm)
            if not mtime:
                stale.append(norm)
                continue
            if entry.get("mtime") != mtime:
                entry = dict(entry)
                entry["mtime"] = mtime
                self._salvage_verified_cache[norm] = entry
                changed = True
            if self._salvage_manifests_on_disk(norm):
                self._register_salvaged_clip(norm)
        for norm in stale:
            del self._salvage_verified_cache[norm]
        if stale or changed:
            self._save_salvage_verified_cache()

    def _offer_salvage_verification(self, clip_path: str) -> None:
        if not clip_path or self._is_clip_cured(clip_path):
            self._salvage_verify_pending = None
            return

        from steempeg.ui.dead_clip_dialogs import DeadClipSalvageVerifyDialog, dialog_theme
        from steempeg.ui.message_dialog import steempeg_information, steempeg_warning

        dlg = DeadClipSalvageVerifyDialog(parent=self.ui, **dialog_theme(self))
        if dlg.exec() and dlg.accepted_yes:
            ok, reason = self._validate_salvage_playback(clip_path)
            if ok:
                self._mark_clip_cured(clip_path, auto_play=dlg.always_play_salvage())
                steempeg_information(
                    self.ui,
                    "Clip Cured",
                    "Salvage playback was verified.\n"
                    "This clip is now marked Cured and can be added to the render queue.",
                )
            else:
                steempeg_warning(
                    self.ui,
                    "Could not verify playback",
                    "Playback was not confirmed by the internal check, so this clip "
                    "was not marked Cured.\n\n"
                    f"{reason}",
                )
        self._salvage_verify_pending = None

    def _maybe_offer_salvage_verification(self) -> None:
        pending = getattr(self, "_salvage_verify_pending", None)
        if not pending or getattr(self, "_salvage_verify_shown", False):
            return
        try:
            player = getattr(self, "player", None)
            if not player or not getattr(player, "path", None):
                return
            playing = not bool(getattr(player, "idle_active", True))
            has_frame = bool(getattr(player, "width", 0))
        except Exception:
            return
        if not playing and not has_frame:
            return
        self._record_salvage_playback_evidence(clip_path=pending)
        self._salvage_verify_shown = True
        clip_path = pending
        self._salvage_verify_pending = None
        self._offer_salvage_verification(clip_path)

    def _clip_can_queue(self, clip_path: str) -> bool:
        if not self._clip_is_dead(clip_path):
            return True
        return self._is_clip_cured(clip_path)

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
        """Find a valid init-stream0.m4s for this game.

        Order: healthy same-game library clip → bundled ``assets/donors/<app_id>/``.
        """
        if not app_id:
            return None
        exclude_norm = os.path.normpath(exclude) if exclude else ""
        if hasattr(self.ui, "table_clips"):
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
                    logging.info("Donor init for %s found in library %s", app_id, path)
                    return donor

        from steempeg.core.dash.donors import find_bundled_donor_init

        bundled = find_bundled_donor_init(app_id)
        if bundled:
            logging.info("Donor init for %s using bundled pack", app_id)
            return bundled
        return None

    def _populate_library_context_menu(self, menu, clip_paths: list):
        count = len(clip_paths)
        if count == 0:
            return

        queueable = [p for p in clip_paths if self._clip_can_queue(p)]

        if queueable:
            count_q = len(queueable)
            queue_label = "📋 Add to queue" if count_q == 1 else f"📋 Add to queue ({count_q})"
            action_queue = menu.addAction(queue_label)
            if len(queueable) < len(clip_paths):
                action_queue.setToolTip(
                    "Unverified dead clips in the selection will be skipped"
                )
            action_queue.triggered.connect(
                lambda _checked=False, paths=list(queueable): self.add_clips_to_render_queue(paths)
            )

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
        prev = getattr(self, "_clips_visual_selected_rows", None)
        if prev == selected_rows:
            return
        # Only restyle cards that entered or left selection — full-grid paint
        # is noticeable on large libraries during select / tab restore.
        changed = selected_rows if prev is None else (prev | selected_rows)
        for i in range(self.grid_clips.count()):
            item = self.grid_clips.item(i)
            row = item.data(Qt.UserRole)
            if row not in changed:
                continue
            card = self.grid_clips.itemWidget(item)
            if isinstance(card, ClipCard):
                card.set_selected(row in selected_rows)
        self._clips_visual_selected_rows = set(selected_rows)

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

    def _schedule_clips_selection_preview(self) -> None:
        """Open/load the selected clip after press anim + selection chrome.

        Clip open (XML / remux / MPV) is slow; it must not run on the mouse-press
        stack or even on the same tick as selection chrome. Delay past
        CARD_PRESS_DURATION_MS so the press scale can paint; a generation token
        drops stale loads when the user spam-clicks.

        Multi-select modifiers are checked here (not inside the deferred tick) so
        releasing Ctrl/Shift before the timer fires cannot thrash the preview.
        """
        if QApplication.keyboardModifiers() & self._MULTI_SELECT_MODIFIERS:
            self.update_playback_badge()
            self._update_start_button_label()
            return
        self._clips_preview_gen = getattr(self, "_clips_preview_gen", 0) + 1
        gen = self._clips_preview_gen
        delay_ms = max(16, int(tok.CARD_PRESS_DURATION_MS))
        QTimer.singleShot(delay_ms, lambda g=gen: self._run_clips_selection_preview(g))

    def _show_pending_clip_open_loading(self) -> None:
        """Card busy feedback just before deferred open work runs."""
        if not hasattr(self, "set_clip_open_loading"):
            return
        if not hasattr(self.ui, "table_clips"):
            return
        row = self.ui.table_clips.currentRow()
        if row < 0:
            return
        cell = self.ui.table_clips.item(row, 0)
        if cell is None:
            return
        path = cell.data(Qt.UserRole)
        if not path:
            return
        # Resolve from this path — never pass a stale `_selected_queue_job_id`
        # from a previous queue card (that painted % on the wrong hosts).
        job_id = None
        if hasattr(self, "_resolve_queue_job_for_library_clip"):
            job = self._resolve_queue_job_for_library_clip(path)
            if job is not None:
                job_id = job.id
        self.set_clip_open_loading(path, job_id=job_id)
        # Paint spinner before synchronous XML / remux / MPV work blocks the UI.
        if hasattr(self, "grid_clips") and self.grid_clips is not None:
            try:
                self.grid_clips.viewport().repaint()
            except RuntimeError:
                pass

    def _cancel_pending_clips_preview(self) -> None:
        """Bump the open-generation token and clear any card open-spinner."""
        self._clips_preview_gen = getattr(self, "_clips_preview_gen", 0) + 1
        self._clips_quality_gen = getattr(self, "_clips_quality_gen", 0) + 1
        self._preview_post_open_gen = getattr(self, "_preview_post_open_gen", 0) + 1
        self._timeline_markers_load_gen = getattr(self, "_timeline_markers_load_gen", 0) + 1
        self._clip_size_label_gen = getattr(self, "_clip_size_label_gen", 0) + 1
        # Invalidate in-flight MPV/remux/reveal work from a superseded click.
        self._media_switch_gen = getattr(self, "_media_switch_gen", 0) + 1
        self._pending_preview_post_open = None
        self._pending_quality_populate = None
        self._pending_timeline_thumbs = None
        # Bumping media gen orphans the soft 800ms finish — clear BOTH gates here
        # or a cancelled rapid switch leaves _is_switching stuck and ignores clicks.
        self._is_switching = False
        self._awaiting_first_frame = False
        progressive = getattr(self, "_progressive_remux", None)
        if progressive is not None:
            try:
                _gen, job = progressive
                if hasattr(job, "abort"):
                    job.abort()
            except Exception:
                pass
            self._progressive_remux = None
        if hasattr(self, "_stop_timeline_thumb_batch"):
            try:
                self._stop_timeline_thumb_batch()
            except Exception:
                pass
        if hasattr(self, "_stop_timeline_markers_worker"):
            try:
                self._stop_timeline_markers_worker()
            except Exception:
                pass
        if hasattr(self, "clear_clip_open_loading"):
            self.clear_clip_open_loading()

    def _run_clips_selection_preview(self, gen: int) -> None:
        """Latest scheduled clip open wins; ignore superseded spam-clicks."""
        if gen != getattr(self, "_clips_preview_gen", 0):
            return
        # Spinner first (ends press-snapshot hide), then heavy open.
        self._show_pending_clip_open_loading()
        self.update_quality_options()

    def _defer_grid_select_item(self, item, event=None) -> None:
        """Schedule grid selection off the ClipCard mouse-press stack.

        Press anim + first paint must finish returning before table sync /
        purple ring / clip open. Capture modifiers now — keys may be released
        before the timer fires.
        """
        mods = self._event_modifiers(event)
        self._clips_card_select_gen = getattr(self, "_clips_card_select_gen", 0) + 1
        # Invalidate any pending open immediately so spam-clicks don't start a
        # stale load while the new selection is still queued.
        self._cancel_pending_clips_preview()
        gen = self._clips_card_select_gen
        QTimer.singleShot(
            0, lambda g=gen, it=item, m=mods: self._run_deferred_grid_select(g, it, m)
        )

    def _run_deferred_grid_select(self, gen: int, item, mods) -> None:
        if gen != getattr(self, "_clips_card_select_gen", 0):
            return
        try:
            if item is None or not hasattr(self, "grid_clips") or self.grid_clips is None:
                return
            # Drop stale callbacks after a library rebuild destroyed the item.
            _ = item.data(Qt.UserRole)
        except RuntimeError:
            return
        self._grid_select_item(item, mods=mods)

    def _publish_grid_selection(self, *, update_preview: bool = True) -> None:
        """Mirror grid selection into the table; reload preview only on plain LMB clicks."""
        if not self._clips_library_accepts_selection():
            return
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
        # Selection chrome first — do not wait on generate_and_play_preview.
        self._sync_grid_card_visuals()
        if hasattr(self, "grid_clips") and self.grid_clips is not None:
            # Paint the purple ring before the delayed clip open starts.
            self.grid_clips.viewport().repaint()
        row = self.ui.table_clips.currentRow()
        if row >= 0:
            cell = self.ui.table_clips.item(row, 0)
            if cell:
                self._saved_clips_selection_path = cell.data(Qt.UserRole) or ""
        if update_preview and hasattr(self.ui, 'table_clips') and self.ui.table_clips.currentRow() >= 0:
            self._schedule_clips_selection_preview()
        else:
            # Multi-select / no preview — drop any pending open from a prior plain click.
            self._cancel_pending_clips_preview()

    def _on_clips_table_item_clicked(self, item) -> None:
        """Re-click on the already-selected table row is a no-op (clip already open)."""
        return

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

    def _table_apply_click_modifiers(self, table, pos, mods) -> None:
        """Ctrl/Alt toggle or Shift-range select a table row (Ctrl/Alt/Shift+LMB)."""
        if table is None:
            return
        index = table.indexAt(pos)
        if not index.isValid():
            return
        sm = table.selectionModel()
        model = table.model()
        if sm is None or model is None:
            return
        if (mods & self._TOGGLE_SELECT_MODIFIERS) and not (mods & Qt.ShiftModifier):
            sm.select(
                index,
                QItemSelectionModel.SelectionFlag.Toggle
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            table.setCurrentIndex(index)
            return
        if mods & Qt.ShiftModifier:
            from PySide6.QtCore import QItemSelection

            anchor = table.currentIndex()
            if not anchor.isValid():
                anchor = index
            lo, hi = sorted((anchor.row(), index.row()))
            selection = QItemSelection()
            last_col = max(0, table.columnCount() - 1)
            for row in range(lo, hi + 1):
                if table.isRowHidden(row):
                    continue
                selection.select(model.index(row, 0), model.index(row, last_col))
            sm.select(
                selection,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            table.setCurrentIndex(index)

    def _grid_select_item(
        self, item, event=None, *, force_single: bool = False, mods=None
    ) -> None:
        """LMB selection for grid cards — setItemWidget breaks default Qt hit-testing."""
        if not self._clips_library_accepts_selection():
            return
        grid = self.grid_clips
        if mods is None:
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
                # Already the open clip — ignore the click (no reload) unless the
                # first-frame / switching gate is stuck (Linux rapid-switch hang).
                # Queue encode must not count as «open»: it used to stamp
                # ``_preview_clip_path`` while the idle poster stayed up, so this
                # guard swallowed every re-click until a queue card was activated.
                clip_path = item.data(Qt.UserRole + 1)
                if (
                    update_preview
                    and clip_path
                    and hasattr(self, "_norm_clip_path_key")
                    and self._norm_clip_path_key(clip_path)
                    == self._norm_clip_path_key(
                        getattr(self, "_preview_clip_path", None)
                    )
                ):
                    really_open = False
                    if hasattr(self, "_is_clip_actively_previewing"):
                        try:
                            really_open = bool(
                                self._is_clip_actively_previewing(clip_path)
                            )
                        except Exception:
                            really_open = False
                    elif hasattr(self, "_player_has_open_clip"):
                        try:
                            really_open = bool(self._player_has_open_clip())
                        except Exception:
                            really_open = False
                    stuck = bool(
                        getattr(self, "_is_switching", False)
                        or getattr(self, "_awaiting_first_frame", False)
                    )
                    if stuck:
                        logging.info(
                            "Same-clip re-click while switch stuck — "
                            "clearing gates and reopening: %s",
                            clip_path,
                        )
                        if hasattr(self, "_clear_preview_switch_gates"):
                            self._clear_preview_switch_gates()
                        else:
                            self._is_switching = False
                            self._awaiting_first_frame = False
                        # Fall through to reload so timeline/thumbs recover.
                    elif (
                        really_open
                        and hasattr(self, "_queue_is_active")
                        and self._queue_is_active()
                        and hasattr(self, "render_queue")
                        and self.render_queue.find_by_clip_path(clip_path)
                    ):
                        # Queued clip (including duplicates): let the normal
                        # selection path activate its remembered queue job.
                        logging.info(
                            "Same-clip library click while queued — "
                            "activating queue job: %s",
                            clip_path,
                        )
                    elif really_open:
                        logging.debug(
                            "Same-clip click ignored (already previewing): %s",
                            clip_path,
                        )
                        item.setSelected(True)
                        grid.blockSignals(False)
                        self._grid_select_in_progress = False
                        if hasattr(self, "_sync_grid_card_visuals"):
                            self._sync_grid_card_visuals()
                        return
                    else:
                        logging.info(
                            "Same-clip path stamped but player idle — opening: %s",
                            clip_path,
                        )
                        # Fall through to open for real.
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
        # RMB only opens the menu (multi-select is Ctrl/Alt/Shift+LMB).
        viewport_pos = self.grid_clips.viewport().mapFromGlobal(event.globalPosition().toPoint())
        self.show_grid_context_menu(viewport_pos)

    def _handle_grid_viewport_press(self, event) -> bool:
        if not self._clips_library_accepts_selection():
            return True
        if event.button() != Qt.LeftButton:
            return False

        pos = event.position().toPoint()
        item = self.grid_clips.itemAt(pos)
        if item is None:
            # Clicking empty space inside the grid keeps the current selection
            # (the purple outline stays); only clicking another card changes it.
            return True

        # Same deferred path as ClipCard — never load on the press stack.
        self._defer_grid_select_item(item, event)
        return True

    def show_grid_context_menu(self, pos):
        """ Pop-up menu for the grid """
        if not self._clips_library_accepts_selection():
            return
        clip_paths = self._context_menu_clip_paths_grid(pos)
        if not clip_paths:
            return

        # Keep QMenu's own native popup flags (Qt.Popup). Overriding them with a
        # translucent frameless window made the menu a layered top-level that
        # wouldn't close on focus loss and slid behind the main window.
        menu = QMenu(self.grid_clips)
        menu.setStyleSheet(ut.library_menu_stylesheet())

        self._populate_library_context_menu(menu, clip_paths)
        menu.exec(self.grid_clips.viewport().mapToGlobal(pos))

    def show_clip_context_menu(self, pos):
        """ Pop-up menu for a standard list (List/Table) """
        if not self._clips_library_accepts_selection():
            return
        clip_paths = self._context_menu_clip_paths_table(pos)
        if not clip_paths:
            return

        # See show_grid_context_menu: keep the native Qt.Popup flags so the menu
        # closes correctly instead of lingering behind the window.
        menu = QMenu(self.ui.table_clips)
        menu.setStyleSheet(ut.library_menu_stylesheet())

        self._populate_library_context_menu(menu, clip_paths)
        menu.exec(self.ui.table_clips.viewport().mapToGlobal(pos))

    def open_clip_folder(self, clip_path):
        """Open the clip folder in the file manager with the clip folder selected."""
        from steempeg.infra.paths import reveal_in_file_manager

        try:
            reveal_in_file_manager(clip_path)
        except Exception as e:
            logging.error(f"Failed to open folder: {e}")

    def delete_clip(self, clip_path):
        """ Prompts for confirmation and deletes the clip folder permanently. """
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
            "Delete Clip",
            "Are you sure you want to delete this clip?",
            detail="This will permanently delete the folder and all its contents.\nThis cannot be undone!",
        ):
            return

        try:
            # Must unload first — Windows won't delete a clip folder mpv still holds.
            if hasattr(self, "release_media_before_delete"):
                self.release_media_before_delete(clip_path)

            try:
                from steempeg.infra.media_cache import purge_clip_media_cache

                purge_clip_media_cache(getattr(self, "cache_dir", None), clip_path)
            except Exception:
                logging.exception("Clip media-cache purge failed")

            shutil.rmtree(clip_path)
            logging.info(f"Deleted clip folder: {clip_path}")
            if hasattr(self, "_on_queue_source_removed"):
                self._on_queue_source_removed(clip_path)
            norm = os.path.normpath(clip_path)
            if hasattr(self, "_clear_salvage_verified"):
                self._clear_salvage_verified(clip_path)
            if hasattr(self.ui, "table_clips"):
                for row in range(self.ui.table_clips.rowCount()):
                    item = self.ui.table_clips.item(row, 0)
                    if item and item.data(Qt.UserRole) and os.path.normpath(item.data(Qt.UserRole)) == norm:
                        item.setData(_CLIP_CURED_ROLE, False)
                        break
            salvaged = getattr(self, "_salvaged_clips", {})
            if norm in salvaged:
                del salvaged[norm]
            self.scan_clips()

            if hasattr(self.ui, 'label_short_summary'):
                if hasattr(self, "_sync_queue_player_and_dash_chrome"):
                    self._sync_queue_player_and_dash_chrome()
                elif hasattr(self, 'reset_bottom_summary'):
                    self.reset_bottom_summary()
            if hasattr(self.ui, 'label_detailed_summary'):
                self.ui.label_detailed_summary.setText("Waiting for clip selection...")

        except Exception as e:
            logging.error(f"Failed to delete clip: {e}")
            steempeg_critical(
                self.ui,
                "Error",
                f"Failed to delete the clip.\nIt might be in use by another program.\n\n{e}",
            )

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
        # Tab-aware footer owns the label when Rendered / Screenshots is active.
        if getattr(self, "_library_panel_mode", "clips") != "clips":
            if hasattr(self, "_sync_library_footer_for_mode"):
                self._sync_library_footer_for_mode()
            return
        picker = getattr(self, "folder_picker", None)
        if picker is None:
            return
        from steempeg.ui.ui_density import COMFORT, folder_button_label

        folders = getattr(self, "clips_folders", [])
        # The + only exists once at least one folder is set; with no folders the user
        # must pick a main folder first via Choose Folder.
        picker.set_add_visible(bool(folders))
        dense = getattr(self, "_ui_density", None) or COMFORT
        tip = ("Library folders:\n" + "\n".join(folders)) if len(folders) > 1 else ""
        picker.set_folder_label(folder_button_label(len(folders), dense), tip)

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
            # New Steam folders: Full scan (same as Choose/Add folder).
            self.scan_clips(announce_duplicates=True, fast=False)
            steempeg_information(
                self.ui,
                "Steam folders found",
                f"Added {len(added)} Steam clips folder(s):\n\n" + "\n".join(added),
            )
            return

        discovered = discover_steam_clips_folders()
        if not discovered:
            steam = get_steam_path()
            steempeg_information(
                self.ui,
                "Steam folders",
                "No Steam Game Recording folders were found.\n\n"
                f"Looked under:\n{os.path.join(steam, 'userdata', '<Steam ID>', 'gamerecordings', 'clips')}",
            )
            return

        if before == after:
            steempeg_information(
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
        # First / primary folder: Full scan (ffprobe + Steam meta).
        self.scan_clips(announce_duplicates=True, fast=False)

    def add_clips_folder(self):
        """Append another folder to the library scan list."""
        folder = QFileDialog.getExistingDirectory(
            self.ui, "Add clips folder", self._default_clips_dialog_path()
        )
        if not folder:
            return
        folder = os.path.normpath(folder)
        if folder in self.clips_folders:
            steempeg_information(self.ui, "Library folders", "That folder is already in the list.")
            return
        if not self.clips_folders:
            self.clips_folders = [folder]
            self.clips_folder = folder
        else:
            self.clips_folders.append(folder)
        self.save_user_settings("user_cleared_library", False)
        self._save_clips_folders()
        self._update_folder_picker_label()
        # New folder: Full scan so health + icons land once.
        self.scan_clips(announce_duplicates=True, fast=False)

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
        if not steempeg_question(
            self.ui,
            "Clear library folders",
            "Remove all clips folders from the library?",
            detail="You can add them again with Choose Folder.",
        ):
            return
        self.clips_folders = []
        self.clips_folder = ""
        self.save_user_settings("user_cleared_library", True)
        self._save_clips_folders()
        self._library_clip_rows = []
        clear_clips_library_cache(getattr(self, "cache_dir", None))
        self._update_folder_picker_label()
        self.scan_clips()

    def _folder_row_icon_button(
        self,
        icon_file: str,
        object_name: str,
        tooltip: str,
        callback,
    ) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName(object_name)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        icon_path = get_resource_path(icon_file)
        if os.path.isfile(icon_path):
            btn.setIcon(QIcon(icon_path))
            btn.setIconSize(QSize(15, 15))
        btn.clicked.connect(callback)
        return btn

    def _folder_panel_row(self, menu, path, is_main):
        """One folder row for the dropdown: label, optional replace, and remove ✕."""
        row = QWidget()
        row.setObjectName("FolderRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 7, 8, 7)
        row_layout.setSpacing(8)

        exists = os.path.isdir(path)
        prefix = "★ " if is_main else ""
        display = path if len(path) <= 42 else "…" + path[-41:]
        label = QLabel(prefix + display)
        label.setObjectName("FolderRowLabel")
        label.setFont(tok.ui_qfont(13, weight=QFont.Weight.Bold))
        tip = "Main folder\n" if is_main else ""
        steam_id = steam_id_from_clips_folder(path)
        if steam_id:
            tip += f"Steam ID: {steam_id}\n"
        label.setToolTip(tip + (path if exists else f"{path}\n(Folder not found on disk)"))
        if not exists:
            label.setProperty("missing", True)
        row_layout.addWidget(label, 1)

        if is_main:
            btn_replace = self._folder_row_icon_button(
                "clipcutback.png",
                "FolderRowReplace",
                "Replace main folder (keeps additional folders)",
                lambda _checked=False: (menu.close(), self.choose_folder()),
            )
            row_layout.addWidget(btn_replace)

        btn_x = self._folder_row_icon_button(
            "multiplier.png",
            "FolderRowRemove",
            "Remove this folder",
            lambda _checked=False, p=path: (menu.close(), self.remove_clips_folder(p)),
        )
        row_layout.addWidget(btn_x)

        frame = QWidget()
        frame.setObjectName("FolderRowFrame")
        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(12, 2, 12, 2)
        frame_layout.setSpacing(0)
        frame_layout.addWidget(row)

        action_row = QWidgetAction(menu)
        action_row.setDefaultWidget(frame)
        menu.addAction(action_row)

    def show_folders_panel(self):
        """Dropdown panel (styled like Logs) listing the main + extra library folders."""
        if not self.clips_folders:
            menu = QMenu(self.folder_picker)
            menu.setStyleSheet(ut.folders_menu_stylesheet())
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
        menu.setStyleSheet(ut.folders_menu_stylesheet())

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

        base_name = os.path.basename(base_folder).lower()
        base_is_steam_package = base_name.startswith(("clip_", "bg_", "fg_"))

        roots = set()
        for sub in ("clips", "video"):
            sub_path = os.path.join(base_folder, sub)
            if os.path.exists(sub_path):
                for item in os.listdir(sub_path):
                    full = os.path.join(sub_path, item)
                    if not os.path.isdir(full):
                        continue
                    if base_is_steam_package and is_steam_package_internal_child(
                        base_name, item.lower()
                    ):
                        continue
                    roots.add(full)

        if self._looks_like_single_clip_folder(base_folder):
            if base_name not in ("gamerecordings", "clips", "video"):
                if not self._is_steam_clip_container_folder(base_folder):
                    roots.add(base_folder)
        try:
            for item in os.listdir(base_folder):
                full = os.path.join(base_folder, item)
                if not os.path.isdir(full) or not item.lower().startswith(("clip_", "bg_", "fg_")):
                    continue
                if base_is_steam_package and is_steam_package_internal_child(
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
                # Sort key only — never visible. (Opacity-dimmed cards used to show
                # this as a ghost "000084" in the thumb area.)
                item.setText(f"{info['row']:06d}")
                item.setForeground(QBrush(QColor(0, 0, 0, 0)))
                item.setData(Qt.UserRole, info['row'])
                hidden = info['hidden']
            item.setHidden(hidden)
        # 3. Qt's built-in ultra-fast sort
        grid.sortItems(Qt.AscendingOrder)
        # Drop the sort-key text so it cannot bleed through translucent cards.
        for i in range(grid.count()):
            item = grid.item(i)
            if item is not None:
                item.setText("")

        grid.blockSignals(False)
        grid.setUpdatesEnabled(True)
        if hasattr(self, "sync_clip_card_edge_roles"):
            QTimer.singleShot(0, self.sync_clip_card_edge_roles)

    def _library_filter_row_matches(self, row: int, saved: dict) -> bool:
        """Whether table row ``row`` should stay visible under ``saved_filter_state``."""
        from steempeg.ui.library.filters import (
            FilterMenu,
            _library_root_for_clip,
            _row_display_health_level,
        )

        table = self.ui.table_clips
        item_game = table.item(row, 0)
        item_type = table.item(row, 1)
        item_date = table.item(row, 2)
        item_dur = table.item(row, 3)

        selected_games = set(saved.get("games") or [])
        selected_types = set(saved.get("types") or [])
        selected_health = set(saved.get("health") or [])
        selected_folders = list(saved.get("folders") or [])
        roots = list(getattr(self, "clips_folders", None) or [])

        if selected_games and item_game and item_game.text().strip() not in selected_games:
            return False
        if selected_types and item_type and item_type.text().strip() not in selected_types:
            return False
        if selected_health and item_game:
            if _row_display_health_level(item_game) not in selected_health:
                return False
        if selected_folders and item_game:
            clip_path = item_game.data(Qt.UserRole) or ""
            root = _library_root_for_clip(clip_path, roots)
            folder_keys = {
                os.path.normcase(os.path.normpath(p)) for p in selected_folders if p
            }
            if root is None or os.path.normcase(os.path.normpath(root)) not in folder_keys:
                return False

        min_date = saved.get("min_date")
        max_date = saved.get("max_date")
        min_time = saved.get("min_time")
        max_time = saved.get("max_time")
        min_dur_t = saved.get("min_dur")
        max_dur_t = saved.get("max_dur")
        min_time_sec = FilterMenu._qtime_to_sec(min_time) if min_time is not None else 0
        max_time_sec = (
            FilterMenu._qtime_to_sec(max_time) if max_time is not None else 24 * 3600 - 1
        )
        min_dur = FilterMenu._qtime_to_sec(min_dur_t) if min_dur_t is not None else 0
        max_dur = FilterMenu._qtime_to_sec(max_dur_t) if max_dur_t is not None else 0
        skip_duration = max_dur <= 0 and min_dur <= 0

        if item_date is not None:
            q_dt = FilterMenu._parse_row_datetime(item_date.text())
            if q_dt is not None:
                r_date = q_dt.date()
                if min_date is not None and hasattr(min_date, "isValid") and min_date.isValid():
                    if r_date < min_date:
                        return False
                if max_date is not None and hasattr(max_date, "isValid") and max_date.isValid():
                    if r_date > max_date:
                        return False
                r_time = (
                    q_dt.time().hour() * 3600
                    + q_dt.time().minute() * 60
                    + q_dt.time().second()
                )
                if r_time < min_time_sec or r_time > max_time_sec:
                    return False

        if item_dur is not None and not skip_duration:
            r_dur = FilterMenu._parse_row_duration(item_dur.text())
            if r_dur < min_dur or r_dur > max_dur:
                return False
        return True

    def reapply_saved_library_filters(self) -> None:
        """Push ``saved_filter_state`` onto table + grid (or show everything).

        Fixes the portable desync where the filter popup looks cleared (no saved
        active state / defaults) while rows stay hidden from an earlier Apply —
        ghost cards and a blank strip you can still click.
        """
        if not hasattr(self.ui, "table_clips"):
            return
        table = self.ui.table_clips
        saved = getattr(self, "saved_filter_state", None)
        active = bool(saved and saved.get("active"))

        table.setUpdatesEnabled(False)
        try:
            if not active:
                for row in range(table.rowCount()):
                    table.setRowHidden(row, False)
            else:
                for row in range(table.rowCount()):
                    table.setRowHidden(row, not self._library_filter_row_matches(row, saved))
                # Preview / queue selection may be outside the filter — keep those
                # cards visible so Choose-a-Clip doesn't scroll into empty space.
                sm = table.selectionModel()
                if sm is not None:
                    for idx in sm.selectedRows():
                        row = idx.row()
                        if table.isRowHidden(row):
                            table.setRowHidden(row, False)
        finally:
            table.setUpdatesEnabled(True)

        if hasattr(self, "fast_sync_grid"):
            self.fast_sync_grid()
        if hasattr(self, "_update_library_count_label"):
            self._update_library_count_label()

    def sync_library_filter_view(self) -> None:
        """Align grid visibility with remembered filters before showing the library."""
        self.reapply_saved_library_filters()

    # --- TRUE HIGH-END FULLSCREEN SYSTEM ---
    def refresh_library(self):
        """ Refresh button: wipe the active filter, deselect the current clip/queue job,
        reset the player + settings panel, then rescan the folder from scratch. """
        # 1. Drop the remembered filter so the menu reopens at defaults and nothing stays hidden
        self.saved_filter_state = None
        if hasattr(self, "_persist_library_filter_memory"):
            self._persist_library_filter_memory()
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
        if hasattr(self, "_clear_queue_selection"):
            self._clear_queue_selection()
        else:
            self._selected_queue_job_id = None
        if hasattr(self, "refresh_render_queue_panel"):
            self.refresh_render_queue_panel()

        # 4. Rescan folders. Progressive is launch-only — Refresh runs Full.
        self._stop_clip_poster_backfill()
        from steempeg.ui.settings_prefs import SCAN_PROGRESSIVE, load_startup_library_scan

        settings = {}
        if hasattr(self, "load_user_settings"):
            try:
                settings = self.load_user_settings() or {}
            except Exception:
                settings = {}
        if load_startup_library_scan(settings) == SCAN_PROGRESSIVE:
            # Same companion as On launch → Full: Steam icons/names after paint.
            self._startup_refresh_steam_meta = True
            self.scan_clips(fast=False)
        else:
            self.scan_clips(fast=True)

    def _insert_scanned_clip_row(self, row: ScannedClip) -> int:
        """Append one scanned clip to the hidden table (+ grid card). Returns row index."""
        rows = getattr(self, "_library_clip_rows", None)
        if rows is None:
            rows = []
            self._library_clip_rows = rows
        rows.append(row)

        table = self.ui.table_clips
        row_position = table.rowCount()
        table.insertRow(row_position)

        icon = QIcon()
        if row.use_unknown_icon:
            from steempeg.infra.paths import get_resource_path

            unknown_icon = get_resource_path("unknown_icon.png")
            if os.path.isfile(unknown_icon):
                icon = QIcon(unknown_icon)
        elif row.app_id:
            icon = self.get_game_icon(row.app_id, allow_download=False)
            if icon.isNull() and row.icon_disk_path and os.path.isfile(row.icon_disk_path):
                icon = self._icon_from_disk(row.icon_disk_path, row.app_id)

        item_game = QTableWidgetItem(icon, row.game_name)
        item_game.setData(Qt.UserRole, row.full_path)
        if row.game_name.strip().lower() == "unknown":
            item_game.setToolTip(row.full_path)
        item_game.setData(_CLIP_HEALTH_ROLE, row.health_level)
        item_game.setData(_CLIP_HEALTH_ISSUES_ROLE, "\n".join(row.health_issues))
        self._sync_cured_role_on_item(item_game, row.full_path)
        table.setItem(row_position, 0, item_game)

        item_type = QTableWidgetItem(row.rec_type)
        item_type.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        table.setItem(row_position, 1, item_type)

        item_date = QTableWidgetItem(row.date_display)
        item_date.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        table.setItem(row_position, 2, item_date)

        item_duration = QTableWidgetItem(row.duration_str)
        item_duration.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        table.setItem(row_position, 3, item_duration)

        self._append_grid_card_for_row(row_position)
        return row_position

    def _remove_library_clip_paths_from_ui(self, paths) -> int:
        """Drop listed clip folders from the table/grid/rows — disk untouched.

        Used when a better Steam session sibling appears (CLIP replaces FG/BG).
        Returns how many rows were removed.
        """
        norms = {os.path.normpath(p) for p in (paths or []) if p}
        if not norms or not hasattr(self, "ui") or not hasattr(self.ui, "table_clips"):
            return 0

        table = self.ui.table_clips
        rows_to_remove: list[int] = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            path = item.data(Qt.UserRole)
            if path and os.path.normpath(str(path)) in norms:
                rows_to_remove.append(row)
        if not rows_to_remove:
            return 0

        rows = getattr(self, "_library_clip_rows", None)
        if rows is not None:
            self._library_clip_rows = [
                r
                for r in rows
                if os.path.normpath(r.full_path) not in norms
            ]

        table.setUpdatesEnabled(False)
        try:
            for row in reversed(rows_to_remove):
                table.removeRow(row)
        finally:
            table.setUpdatesEnabled(True)

        if hasattr(self, "build_netflix_grid"):
            self.build_netflix_grid()
        if hasattr(self, "_update_library_count_label"):
            self._update_library_count_label()
        return len(rows_to_remove)

    def _purge_inferior_session_siblings(self) -> int:
        """Collapse clip_/bg_/fg_ duplicates already listed in the library UI."""
        table = getattr(getattr(self, "ui", None), "table_clips", None)
        if table is None:
            return 0
        paths: list[str] = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            path = item.data(Qt.UserRole)
            if path:
                paths.append(str(path))
        dropped = session_duplicate_paths_to_drop(paths)
        if not dropped:
            return 0
        removed = self._remove_library_clip_paths_from_ui(dropped)
        if removed:
            logging.info(
                "Library: removed %d inferior Steam session sibling(s) (FG/BG under CLIP)",
                removed,
            )
            self._persist_clips_library_snapshot()
        return removed

    def _clip_card_footer_text(self, title: str, date_raw: str, duration: str) -> str:
        """Grid footer: ``date\\ntime • duration`` (omit empty / placeholder duration)."""
        if title.strip().lower() == "unknown":
            return "FG"
        lines = (date_raw or "").split("\n", 1)
        date_line = (lines[0] if lines else "").strip() or "Today"
        time_line = lines[1].strip() if len(lines) > 1 else ""
        dur = (duration or "").strip()
        if dur in ("--:--", "—", "--"):
            dur = ""
        if time_line and dur:
            return f"{date_line}\n{time_line} • {dur}"
        if time_line:
            return f"{date_line}\n{time_line}"
        if dur:
            return f"{date_line} • {dur}"
        return date_line

    def _append_grid_card_for_row(self, row: int) -> None:
        """Add one grid card for ``row`` without rebuilding the whole grid."""
        if not hasattr(self, "grid_clips") or not hasattr(self.ui, "table_clips"):
            return

        table = self.ui.table_clips
        title_item = table.item(row, 0)
        if not title_item:
            return
        clip_path = title_item.data(Qt.UserRole)

        item = QListWidgetItem(self.grid_clips)
        item.setSizeHint(_CLIP_CARD_SIZE)
        item.setData(Qt.UserRole, row)
        item.setData(Qt.UserRole + 1, clip_path)
        if table.isRowHidden(row):
            item.setHidden(True)

        if getattr(self, "_clips_progressive_active", False):
            # Placeholder only — ClipCard waits for viewport materialize.
            return
        self._attach_clip_card_to_grid_item(item)

    def _attach_clip_card_to_grid_item(self, item: QListWidgetItem) -> ClipCard | None:
        """Build / attach a ClipCard for an existing grid item (materialize path)."""
        if not hasattr(self, "grid_clips") or not hasattr(self.ui, "table_clips"):
            return None
        if item is None:
            return None
        existing = self.grid_clips.itemWidget(item)
        if isinstance(existing, ClipCard):
            return existing

        try:
            row = int(item.data(Qt.UserRole))
        except (TypeError, ValueError):
            return None
        table = self.ui.table_clips
        if row < 0 or row >= table.rowCount():
            return None
        title_item = table.item(row, 0)
        date_item = table.item(row, 2)
        if not title_item:
            return None

        title = title_item.text() if title_item else "Unknown"
        date_raw = date_item.text() if date_item else "Today"
        time_item = table.item(row, 3)
        dur_str = time_item.text().strip() if time_item else ""
        footer_right = self._clip_card_footer_text(title.strip(), date_raw, dur_str)

        clip_path = title_item.data(Qt.UserRole) or item.data(Qt.UserRole + 1)
        health_color = None
        if title_item.data(_CLIP_CURED_ROLE):
            health_color = health.HEALTH_COLORS[health.ClipHealth.CURED]
        else:
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
            clip_folder_name = os.path.basename(str(clip_path))
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

            # Progressive / Skip: disk thumbs only — never ffmpeg-generate here.
            progressive = bool(getattr(self, "_clips_progressive_active", False))
            if progressive or getattr(self, "_scan_snapshot_restore", False):
                if progressive and os.path.exists(str(clip_path)):
                    thumb_path = resolve_clip_thumbnail(
                        str(clip_path), self.cache_dir, allow_generate=False
                    )
                else:
                    thumb_path = self._snapshot_local_poster_only(str(clip_path))
            elif os.path.exists(str(clip_path)):
                thumb_path = resolve_clip_thumbnail(
                    str(clip_path), self.cache_dir, allow_generate=False
                )

        is_unknown_clip = title.strip().lower() == "unknown"
        item.setData(Qt.UserRole + 1, clip_path)

        queue_membership = None
        queue_mode = (
            not hasattr(self, "_queue_is_active") or bool(self._queue_is_active())
        )
        if clip_path and hasattr(self, "render_queue") and queue_mode:
            jobs = self.render_queue.find_all_by_clip_path(clip_path)
            if jobs:
                from steempeg.render.queue import STATUS_COLORS

                queue_membership = [
                    (int(j.queue_index), STATUS_COLORS.get(j.status, "#ffcc00"))
                    for j in jobs
                ]

        card = ClipCard(
            title.strip(),
            footer_right,
            badge_text,
            thumb_path,
            icon_path,
            row,
            health_color=health_color,
            round_icon=is_unknown_clip,
            on_left_click=lambda ev, grid_item=item: self._defer_grid_select_item(grid_item, ev),
            on_right_click=lambda ev, grid_item=item: self._handle_grid_card_context_menu(grid_item, ev),
        )
        if queue_membership:
            card.set_queue_badge(membership=queue_membership)
        is_dead = False
        if title_item is not None and not title_item.data(_CLIP_CURED_ROLE):
            level = title_item.data(_CLIP_HEALTH_ROLE)
            is_dead = level == health.ClipHealth.DEAD.value
        has_thumb = bool(thumb_path and os.path.exists(thumb_path))
        if getattr(self, "_scan_snapshot_restore", False) and not getattr(
            self, "_clips_progressive_active", False
        ):
            card.set_unavailable(dead=is_dead, no_preview=False)
        else:
            card.set_unavailable(dead=is_dead, no_preview=not has_thumb)
        self.grid_clips.setItemWidget(item, card)

        live = getattr(self, "_clip_live_paths", None)
        if not isinstance(live, set):
            live = set()
            self._clip_live_paths = live
        if clip_path:
            live.add(os.path.normcase(os.path.normpath(str(clip_path))))
        return card

    def refresh_library_datetime_displays(self) -> None:
        """Reformat clip/rendered date cells from stamps — no folder rescan."""
        from datetime import datetime

        from steempeg.infra.locale_time import format_clip_date, format_clip_time
        from steempeg.library.scan import clip_folder_recorded_at
        from steempeg.ui.library.grid_view import ClipCard

        table = getattr(getattr(self, "ui", None), "table_clips", None)
        if table is not None:
            for row in range(table.rowCount()):
                name_item = table.item(row, 0)
                date_item = table.item(row, 2)
                if name_item is None or date_item is None:
                    continue
                path = name_item.data(Qt.UserRole)
                dt = clip_folder_recorded_at(path) if path else None
                if dt is None:
                    raw = (date_item.text() or "").replace("\n", " at ")
                    qdt = parse_clip_datetime_text(raw)
                    if qdt is None:
                        continue
                    dt = datetime(
                        qdt.date().year(),
                        qdt.date().month(),
                        qdt.date().day(),
                        qdt.time().hour(),
                        qdt.time().minute(),
                        qdt.time().second(),
                    )
                new_date = format_clip_date(dt)
                new_time = format_clip_time(dt)
                date_item.setText(f"{new_date}\n{new_time}")

                dur_item = table.item(row, 3)
                dur = dur_item.text() if dur_item else ""
                title = (name_item.text() or "").strip()
                footer = self._clip_card_footer_text(title, f"{new_date}\n{new_time}", dur)

                grid = getattr(self, "grid_clips", None)
                if grid is not None:
                    for i in range(grid.count()):
                        gitem = grid.item(i)
                        if gitem is None or gitem.data(Qt.UserRole) != row:
                            continue
                        card = grid.itemWidget(gitem)
                        if isinstance(card, ClipCard):
                            card.set_date_footer(footer)
                        break

        # Rendered videos — reformat from file mtime (stored or live).
        rendered = getattr(self, "table_rendered", None)
        if rendered is not None:
            for row in range(rendered.rowCount()):
                name_item = rendered.item(row, 0)
                date_item = rendered.item(row, 2)
                if name_item is None or date_item is None:
                    continue
                path = name_item.data(Qt.ItemDataRole.UserRole)
                mtime = date_item.data(Qt.ItemDataRole.UserRole)
                dt = None
                if mtime:
                    try:
                        dt = datetime.fromtimestamp(float(mtime))
                    except (TypeError, ValueError, OSError):
                        dt = None
                if dt is None and path and os.path.isfile(path):
                    try:
                        dt = datetime.fromtimestamp(os.path.getmtime(path))
                    except OSError:
                        dt = None
                if dt is None:
                    continue
                new_date = format_clip_date(dt)
                new_time = format_clip_time(dt)
                date_item.setText(f"{new_date}\n{new_time}")
                date_item.setData(Qt.ItemDataRole.UserRole, float(dt.timestamp()))
                size_item = rendered.item(row, 3)
                size_str = size_item.text() if size_item else ""
                is_unknown = (name_item.text() or "").strip().lower().startswith("unknown")
                footer = (
                    f"Unknown • {size_str}"
                    if is_unknown
                    else f"{new_date}\n{new_time} • {size_str}"
                )
                grid_r = getattr(self, "grid_rendered", None)
                if grid_r is not None:
                    for i in range(grid_r.count()):
                        gitem = grid_r.item(i)
                        if gitem is None or gitem.data(Qt.ItemDataRole.UserRole) != row:
                            continue
                        card = grid_r.itemWidget(gitem)
                        if card is not None and hasattr(card, "set_date_footer"):
                            card.set_date_footer(footer)
                        elif card is not None and hasattr(card, "date_lbl"):
                            card.date_lbl.setText(footer)
                        break

        self._refresh_selected_clip_header_datetime()

    def _refresh_selected_clip_header_datetime(self) -> None:
        """Update player header / Clip info date line for the active selection."""
        table = getattr(getattr(self, "ui", None), "table_clips", None)
        if table is None:
            return
        row = table.currentRow()
        if row < 0:
            return
        name_item = table.item(row, 0)
        date_item = table.item(row, 2)
        if name_item is None or date_item is None:
            return
        date_part, _, time_part = (date_item.text() or "").partition("\n")
        dur_item = table.item(row, 3)
        duration = dur_item.text() if dur_item else ""
        try:
            from steempeg.ui.player_header_layout import set_player_header_game_text

            set_player_header_game_text(
                self,
                title=(name_item.text() or "").strip(),
                date=date_part.strip(),
                time=time_part.strip(),
                duration=duration,
            )
        except Exception:
            logging.exception("header datetime refresh failed")

    def refresh_portable_clip_queue_badges(self) -> None:
        """Update queue # overlays on clip grid cards (desktop + portable)."""
        self.refresh_clip_queue_badges()

    def refresh_clip_queue_badges(self) -> None:
        """Update queue # overlays without rebuilding the grid.

        Hidden while Left (``_queue_scheme_deferred`` / not ``_queue_is_active``);
        restored on Resume when jobs still match.
        """
        grid = getattr(self, "grid_clips", None)
        if grid is None or not hasattr(self, "render_queue"):
            return
        from steempeg.render.queue import STATUS_COLORS
        from steempeg.ui.library.grid_view import ClipCard

        # Leave keeps jobs but drops queue-mode chrome — including ClipCard circles.
        show_badges = True
        if hasattr(self, "_queue_is_active"):
            show_badges = bool(self._queue_is_active())

        for i in range(grid.count()):
            item = grid.item(i)
            if item is None:
                continue
            card = grid.itemWidget(item)
            if not isinstance(card, ClipCard):
                continue
            clip_path = item.data(Qt.UserRole + 1)
            if not clip_path or not show_badges:
                card.set_queue_badge(None)
                continue
            jobs = self.render_queue.find_all_by_clip_path(clip_path)
            if not jobs:
                card.set_queue_badge(None)
            else:
                card.set_queue_badge(
                    membership=[
                        (int(j.queue_index), STATUS_COLORS.get(j.status, "#ffcc00"))
                        for j in jobs
                    ]
                )

    def _clip_grid_column_count(self) -> int:
        return self._clip_grid_column_count_for(getattr(self, "grid_clips", None))

    def _clip_grid_column_count_for(self, grid) -> int:
        if grid is None:
            return 1
        viewport_w = max(1, grid.viewport().width())
        spacing = max(0, int(grid.spacing()))
        # ClipCard cell is ~260 wide (sizeHint).
        cell = 260
        return max(1, (viewport_w + spacing) // (cell + spacing))

    def sync_clip_card_edge_roles(self) -> None:
        """SteempegUI: square shelf flush on top/bottom rows (Clips + Rendered)."""
        from steempeg.ui.clip_card_style import (
            CARD_STYLE_STEEMPEG_UI,
            get_clip_card_style,
        )
        from steempeg.ui.library.grid_view import ClipCard

        shelf = get_clip_card_style() == CARD_STYLE_STEEMPEG_UI

        for grid_name in ("grid_clips", "grid_rendered"):
            grid = getattr(self, grid_name, None)
            if grid is None:
                continue
            visible: list = []
            for i in range(grid.count()):
                item = grid.item(i)
                if item is None or item.isHidden():
                    continue
                card = grid.itemWidget(item)
                if isinstance(card, ClipCard):
                    visible.append(card)
            if not visible:
                continue
            if not shelf:
                # Square / Round ignore shelf roles — keep mid so a later
                # SteempegUI switch re-applies cleanly.
                for card in visible:
                    card.set_edge_role("mid")
                continue
            cols = self._clip_grid_column_count_for(grid)
            last_row = (len(visible) - 1) // cols
            for idx, card in enumerate(visible):
                row = idx // cols
                if last_row == 0:
                    role = "both"
                elif row == 0:
                    role = "top"
                elif row == last_row:
                    role = "bottom"
                else:
                    role = "mid"
                card.set_edge_role(role)

    def refresh_clip_card_styles(self, style: str | None = None) -> str:
        """Apply SteempegUI / Square / Round chrome across Clips + Rendered grids."""
        from steempeg.ui.clip_card_style import get_clip_card_style, set_clip_card_style
        from steempeg.ui.library.grid_view import ClipCard

        if style is not None:
            set_clip_card_style(style)
        applied = get_clip_card_style()
        for grid_name in ("grid_clips", "grid_rendered"):
            grid = getattr(self, grid_name, None)
            if grid is None:
                continue
            for i in range(grid.count()):
                item = grid.item(i)
                if item is None:
                    continue
                card = grid.itemWidget(item)
                if isinstance(card, ClipCard):
                    card.reapply_card_style()
        self.sync_clip_card_edge_roles()
        return applied

    def _sync_library_scan_interaction_lock(self, *, busy: bool) -> None:
        """Roskomnadzor mode: while clips are loading, freeze Queue + Clips Manager."""
        enabled = not busy
        wait_tip = "Wait until library finishes loading…"
        panel = getattr(self, "render_queue_panel", None)
        if panel is not None:
            try:
                panel.setEnabled(enabled)
            except RuntimeError:
                pass
        sidebar = getattr(self, "_portable_queue_sidebar", None)
        if sidebar is not None:
            try:
                sidebar.setEnabled(enabled)
            except RuntimeError:
                pass
        for name in ("btn_portable_render",):
            btn = getattr(self, name, None)
            if btn is not None:
                try:
                    btn.setEnabled(enabled)
                except RuntimeError:
                    pass
        # Choose a Clip stays clickable during scan so the user can open the sheet
        # and see the grayed library; grid/table remain locked below.
        for name in ("grid_clips", "table_clips"):
            w = getattr(self, name, None) or getattr(getattr(self, "ui", None), name, None)
            if w is not None:
                try:
                    w.setEnabled(enabled)
                except RuntimeError:
                    pass
        # Sorting + Filters are unsafe while the clips table is rebuilding.
        combo = getattr(self, "combo_sort", None)
        if combo is not None:
            try:
                combo.setEnabled(enabled)
                combo.setToolTip("" if enabled else wait_tip)
            except RuntimeError:
                pass
        pill = getattr(self, "btn_filter_pill", None)
        if pill is not None:
            try:
                pill.setEnabled(enabled)
                pill.setToolTip("Filters" if enabled else wait_tip)
            except RuntimeError:
                pass
        if busy:
            for attr in ("filter_menu", "rendered_filter_menu"):
                menu = getattr(self, attr, None)
                if menu is not None:
                    try:
                        menu.hide()
                        menu.deleteLater()
                    except RuntimeError:
                        pass
                    setattr(self, attr, None)
        try:
            from steempeg.ui.portable.chrome import sync_portable_library_scan_badge

            if busy:
                inserted = int(getattr(self, "_scan_inserted", 0) or 0)
                total = int(getattr(self, "_scan_total", 0) or 0)
                if total > 0 and inserted > 0:
                    pct = min(99.0, 100.0 * inserted / total)
                    sync_portable_library_scan_badge(self, percent=pct, searching=False)
                else:
                    sync_portable_library_scan_badge(self, searching=True)
            else:
                sync_portable_library_scan_badge(self, clear=True)
        except Exception:
            pass

    def _clips_library_accepts_selection(self) -> bool:
        return not getattr(self, "_clips_scan_active", False)

    def _library_scan_status_active(self, source: str) -> bool:
        """Only the visible library panel drives the footer — except during startup."""
        if getattr(self, "_startup_library_scan_active", False):
            if source == "clips" and getattr(self, "_clips_scan_active", False):
                return True
            if source == "rendered" and getattr(self, "_rendered_scan_active", False):
                return True
            return False
        return getattr(self, "_library_panel_mode", "clips") == source

    def _maybe_start_deferred_rendered_scan(self) -> None:
        if not getattr(self, "_defer_rendered_scan_until_clips_done", False):
            return
        self._defer_rendered_scan_until_clips_done = False
        if hasattr(self, "scan_rendered_outputs"):
            self.scan_rendered_outputs()

    def _on_scan_discovering(self, total: int, generation: int) -> None:
        if generation != getattr(self, "_scan_generation", 0):
            return
        # Progress should reflect real UI insert, not just worker scan speed.
        if total > 0:
            self._scan_total = int(total)
            self._scan_inserted = 0
        # Quiet Skip top-up: stay Ready until something new actually appears.
        if getattr(self, "_scan_append_new_only", False):
            if total <= 0:
                return
            if hasattr(self, "update_status_indicator"):
                self.update_status_indicator(
                    f"Found {total} new clip(s)", "busy", scan_phase="search"
                )
            return
        if hasattr(self, "update_status_indicator") and getattr(self, "_clips_scan_active", False):
            if total <= 0:
                self.update_status_indicator("Searching for clips…", "busy", scan_phase="search")
            else:
                self.update_status_indicator(f"Found {total} clips", "busy", scan_phase="search")
            try:
                from steempeg.ui.portable.chrome import sync_portable_library_scan_badge

                sync_portable_library_scan_badge(self, searching=True)
            except Exception:
                pass

    def _on_scan_clip_ready(self, row: ScannedClip, index: int, total: int, generation: int) -> None:
        if generation != getattr(self, "_scan_generation", 0):
            return
        # Insert in small batches on a timer so the UI stays smooth and clips appear
        # 1-by-1 instead of stalling then dropping big chunks.
        pending = getattr(self, "_scan_pending_rows", None)
        if pending is None:
            pending = []
            self._scan_pending_rows = pending
        pending.append((row, index, total))

        if not getattr(self, "_scan_flush_scheduled", False):
            self._scan_flush_scheduled = True
            QTimer.singleShot(0, lambda g=generation: self._flush_scanned_clips(g))

    def _flush_scanned_clips(self, generation: int) -> None:
        if generation != getattr(self, "_scan_generation", 0):
            self._scan_flush_scheduled = False
            self._scan_pending_rows = []
            self._scan_finalize_pending = None
            return

        self._scan_flush_scheduled = False
        pending = getattr(self, "_scan_pending_rows", [])
        if not pending:
            finalize = getattr(self, "_scan_finalize_pending", None)
            if finalize is not None:
                stats, gen, announce = finalize
                if gen == getattr(self, "_scan_generation", 0):
                    self._scan_finalize_pending = None
                    self._finalize_scan_finished(stats, gen, announce)
            return

        batch = 12 if getattr(self, "_scan_snapshot_restore", False) else 4
        inserted_before = int(getattr(self, "_scan_inserted", 0))
        n = min(batch, len(pending))
        last_row = None

        table = getattr(self.ui, "table_clips", None)
        grid = getattr(self, "grid_clips", None)
        if table is not None:
            table.setUpdatesEnabled(False)
        if grid is not None:
            grid.setUpdatesEnabled(False)
        try:
            for _ in range(n):
                row, index, total = pending.pop(0)
                if getattr(self, "_scan_append_new_only", False):
                    # Drop FG/BG already listed for this Steam session before CLIP lands
                    # (including CLIP packages whose nested FG stamp differs).
                    existing_rows = getattr(self, "_library_clip_rows", None) or []
                    existing_paths = [str(r.full_path) for r in existing_rows]
                    dropped = session_duplicate_paths_to_drop(
                        existing_paths + [row.full_path]
                    )
                    losers = [
                        p
                        for p in dropped
                        if os.path.normpath(p) != os.path.normpath(row.full_path)
                    ]
                    if losers:
                        self._remove_library_clip_paths_from_ui(losers)
                self._insert_scanned_clip_row(row)
                last_row = row
        finally:
            if table is not None:
                table.setUpdatesEnabled(True)
            if grid is not None:
                grid.setUpdatesEnabled(True)

        if (
            last_row is not None
            and hasattr(self, "update_status_indicator")
            and getattr(self, "_clips_scan_active", False)
            and not getattr(self, "_scan_append_new_only", False)
        ):
            inserted = inserted_before + n
            self._scan_inserted = inserted
            denom = int(getattr(self, "_scan_total", 0) or 0) or inserted or 1
            label = last_row.game_name.strip() or os.path.basename(last_row.full_path)
            pct = int(100 * inserted / denom) if denom else 0
            if inserted >= denom and getattr(self, "_scan_finalize_pending", None) is None:
                pct = min(pct, 99)
            verb = (
                "Restoring"
                if getattr(self, "_scan_snapshot_restore", False)
                else "Loading"
            )
            self.update_status_indicator(
                f"{verb} {inserted}/{denom} — {label} ({pct}%)",
                "busy",
                scan_phase="loading",
            )
            try:
                from steempeg.ui.portable.chrome import sync_portable_library_scan_badge

                sync_portable_library_scan_badge(self, percent=float(pct), searching=False)
            except Exception:
                pass

        if hasattr(self, "_update_library_count_label"):
            self._update_library_count_label()

        if pending:
            self._scan_flush_scheduled = True
            # Yield so maximize / density layout can paint between batches.
            delay = 0 if getattr(self, "_scan_snapshot_restore", False) else 20
            QTimer.singleShot(delay, lambda g=generation: self._flush_scanned_clips(g))
            return

        # pending is empty; finalization is handled at the top of this method.
        finalize = getattr(self, "_scan_finalize_pending", None)
        if finalize is not None:
            stats, gen, announce = finalize
            if gen == getattr(self, "_scan_generation", 0):
                self._scan_finalize_pending = None
                self._finalize_scan_finished(stats, gen, announce)

    def _on_scan_finished(self, stats, generation: int, announce_duplicates: bool) -> None:
        if generation != getattr(self, "_scan_generation", 0):
            return

        # Discovery count can include folders that fail health/parse; use the real total.
        if int(stats.clip_count) > 0:
            self._scan_total = int(stats.clip_count)

        # Do not mark the scan as finished until the UI insertion queue drains.
        # Otherwise unrelated "Ready" updates reset the progress bar mid-load.
        pending = getattr(self, "_scan_pending_rows", [])
        if pending or getattr(self, "_scan_flush_scheduled", False):
            self._scan_finalize_pending = (stats, generation, announce_duplicates)
            return

        self._finalize_scan_finished(stats, generation, announce_duplicates)

    def _finalize_scan_finished(self, stats, generation: int, announce_duplicates: bool) -> None:
        """Run the original scan-finished logic once both worker + UI insert are done."""

        worker = getattr(self, "_library_scan_worker", None)
        if worker is not None:
            self._ensure_clip_health_cache()
            self._clip_health_cache.update(worker.health_cache)
            self._save_clip_health_cache()
            for app_id, name in worker.game_names_cache.items():
                if app_id not in self.game_names_cache:
                    self.game_names_cache[app_id] = name
            if worker.game_names_cache:
                self.save_json_cache()
        self._library_scan_worker = None

        self.ui.table_clips.setSortingEnabled(True)
        self.ui.table_clips.horizontalHeader().setSectionsClickable(False)
        # Snapshot order is already the last-session order — never re-apply
        # Default sort on Skip restore (that alone made Skip feel like a rescan).
        snapshot_restore = bool(getattr(self, "_scan_snapshot_restore", False))
        if not snapshot_restore:
            LibraryMixin.apply_sorting(self)
            self.sync_grid_from_table_selection()
        else:
            if hasattr(self, "fast_sync_grid"):
                self.fast_sync_grid()

        quiet_append = bool(getattr(self, "_scan_append_new_only", False))
        do_steam_meta = bool(getattr(self, "_startup_refresh_steam_meta", False))
        if quiet_append:
            # CLIP often appears after FG for the same Steam session — drop the loser.
            self._purge_inferior_session_siblings()
        if (
            not quiet_append
            and not snapshot_restore
            and not getattr(self, "_clips_progressive_active", False)
        ):
            # Full startup will re-download all icons shortly — skip the
            # missing-only backfill (would race / duplicate CDN work).
            if not do_steam_meta:
                self._backfill_missing_game_icons()
            self._schedule_clip_poster_backfill()

        self._persist_clips_library_snapshot()
        self._scan_append_new_only = False
        self._scan_snapshot_restore = False
        want_append = bool(getattr(self, "_snapshot_append_new_after", False))
        self._snapshot_append_new_after = False

        if hasattr(self, "_update_library_count_label"):
            self._update_library_count_label()

        if not getattr(self, "_preview_clip_path", None):
            self._saved_clips_selection_path = ""
            if hasattr(self, "_clear_clips_selection_visual"):
                self._clear_clips_selection_visual()

        will_scan_rendered = getattr(self, "_defer_rendered_scan_until_clips_done", False)
        self._clips_scan_active = False
        self._sync_library_scan_interaction_lock(busy=False)
        if hasattr(self, "update_status_indicator"):
            if not will_scan_rendered:
                if getattr(self, "_startup_library_scan_active", False) and hasattr(self, "preload_render_history"):
                    self._startup_library_scan_active = False
                    self.preload_render_history(announce=True)
                else:
                    self.update_status_indicator("Ready", "ready")
            else:
                self.update_status_indicator("Clips loaded — scanning rendered files…", "busy", scan_phase="search")

        self._maybe_start_deferred_rendered_scan()

        if do_steam_meta:
            self._startup_refresh_steam_meta = False
            # List is up; icons then names follow on background workers.
            QTimer.singleShot(0, self._start_startup_steam_meta_refresh)

        QTimer.singleShot(0, self._sync_library_scrollbars)
        if (
            getattr(self, "_library_panel_mode", "") == "screenshots"
            and hasattr(self, "_schedule_screenshots_grid_reflow")
        ):
            # Scan unlock / scrollbar policy settle can leave IconMode at 2 cols.
            QTimer.singleShot(0, lambda: self._schedule_screenshots_grid_reflow(0))
            QTimer.singleShot(80, lambda: self._schedule_screenshots_grid_reflow(0))

        if snapshot_restore and want_append:
            # Quiet top-up long after paint — must not compete with first frame.
            QTimer.singleShot(2500, self._append_new_clips_only)
        if getattr(self, "_clips_progressive_active", False):
            pass  # Progressive: no duration/poster flood — Refresh does a full scan.
        elif snapshot_restore:
            QTimer.singleShot(400, self._schedule_clip_duration_backfill)
        elif not quiet_append:
            QTimer.singleShot(0, self._schedule_clip_duration_backfill)

        if announce_duplicates and stats.duplicate_count:
            noun = "duplicate" if stats.duplicate_count == 1 else "duplicates"
            steempeg_information(
                self.ui,
                "Duplicate clips ignored",
                f"Ignored {stats.duplicate_count} {noun} across folders.\n\n"
                "The same clip was found in more than one library folder; only the "
                "most recent copy is shown.",
            )

        if hasattr(self, "sync_library_filter_view"):
            self.sync_library_filter_view()

        logging.info(
            "Library scan: roots=%s clips=%d healthy=%d issues=%d dead=%d "
            "ignored_duplicates=%d fast=%s quiet_append=%s snapshot=%s",
            stats.library_roots,
            stats.clip_count,
            stats.health_counts.get("healthy", 0),
            stats.health_counts.get("issues", 0),
            stats.health_counts.get("dead", 0),
            stats.duplicate_count,
            stats.fast,
            quiet_append,
            snapshot_restore,
        )

    def _on_scan_error(self, message: str, generation: int) -> None:
        if generation != getattr(self, "_scan_generation", 0):
            return
        self._library_scan_worker = None
        self._startup_refresh_steam_meta = False
        logging.error("Library scan failed: %s", message)
        self._clips_scan_active = False
        self._sync_library_scan_interaction_lock(busy=False)
        if hasattr(self, "update_status_indicator"):
            self.update_status_indicator("Scan error", "error")
        QTimer.singleShot(0, self._sync_library_scrollbars)
        self._maybe_start_deferred_rendered_scan()

    def _persist_clips_library_snapshot(self) -> None:
        """Write the current Clips Manager list for Skip startup restores."""
        roots = [f for f in (getattr(self, "clips_folders", None) or []) if f]
        rows = list(getattr(self, "_library_clip_rows", None) or [])
        try:
            save_clips_library_cache(
                getattr(self, "cache_dir", None),
                library_roots=roots,
                clips=rows,
            )
        except Exception:
            logging.exception("Failed to save clips library snapshot")

    def _snapshot_local_poster_only(self, clip_path: str) -> str:
        """Skip paint: probe local poster cache only (no library-root I/O)."""
        cache_dir = getattr(self, "cache_dir", None)
        if not cache_dir or not clip_path:
            return ""
        try:
            candidate = clip_poster_cache_path_nostat(cache_dir, clip_path)
            if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                return candidate
        except OSError:
            pass
        return ""

    # ----- Progressive library load (viewport-lazy ClipCards) -----

    def _ensure_clips_viewport_lazy_hooks(self) -> None:
        """Install scroll-idle viewport refresh once (Screenshots pattern)."""
        grid = getattr(self, "grid_clips", None)
        if grid is None:
            return
        if getattr(self, "_clips_viewport_hooks_installed", False):
            return
        idle = QTimer(grid)
        idle.setSingleShot(True)
        idle.setInterval(_CLIP_SCROLL_IDLE_MS)
        idle.timeout.connect(self._clips_on_scroll_idle)
        self._clips_viewport_timer = idle
        self._clips_scroll_active = False
        self._clip_live_paths = set()
        bar = grid.verticalScrollBar()
        if bar is not None:
            bar.valueChanged.connect(self._on_clips_scroll)
            bar.rangeChanged.connect(self._on_clips_scroll_range)
        self._clips_viewport_hooks_installed = True

    def _on_clips_scroll_range(self, *_args) -> None:
        """Sheet open / layout grow — scrollbar appears without a wheel tick."""
        if not getattr(self, "_clips_progressive_active", False):
            return
        self._schedule_clips_viewport_refresh(50)

    def _stop_progressive_clips_discover(self) -> None:
        worker = getattr(self, "_progressive_clips_worker", None)
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(2000)
        self._progressive_clips_worker = None

    def start_progressive_clips_library(self) -> bool:
        """Paint Clips placeholders fast; materialize cards as the viewport scrolls."""
        if not hasattr(self, "ui") or not hasattr(self.ui, "table_clips"):
            return False

        if not getattr(self, "clips_folders", None):
            self._load_clips_folders_from_settings()
        library_roots = list(getattr(self, "clips_folders", None) or [])
        if not library_roots:
            return False

        self._ensure_clips_viewport_lazy_hooks()
        self._stop_library_scan()
        self._stop_progressive_clips_discover()
        self._stop_clip_poster_backfill()
        self._stop_clip_duration_backfill()
        self._scan_pending_rows = []
        self._scan_flush_scheduled = False
        self._scan_total = 0
        self._scan_inserted = 0
        self._scan_finalize_pending = None
        self._scan_append_new_only = False
        self._scan_snapshot_restore = False
        self._clips_progressive_active = True
        self._library_clip_rows = []
        self._saved_clips_selection_path = ""
        self._preview_clip_path = None
        self._clips_visual_selected_rows = set()
        self._clip_live_paths = set()
        if hasattr(self, "_clear_clips_selection_visual"):
            self._clear_clips_selection_visual()

        table = self.ui.table_clips
        grid = getattr(self, "grid_clips", None)
        table.setSortingEnabled(False)
        table.setRowCount(0)
        if grid is not None:
            self._grid_anchor_item = None
            self._grid_anchor_index = -1
            grid.clear()

        self._scan_generation = getattr(self, "_scan_generation", 0) + 1
        self._clips_scan_active = False
        self._sync_library_scan_interaction_lock(busy=False)
        self._ensure_clip_health_cache()

        if hasattr(self, "_update_library_count_label"):
            self._update_library_count_label()
        if hasattr(self, "update_status_indicator"):
            self.update_status_indicator("Ready", "ready")

        from steempeg.ui.library.progressive_clips_discover import (
            ProgressiveClipsDiscoverWorker,
        )

        worker = ProgressiveClipsDiscoverWorker(
            library_roots,
            getattr(self, "cache_dir", "") or "",
            getattr(self, "_clip_health_cache", {}) or {},
            getattr(self, "game_names_cache", {}) or {},
            prefer_session=True,
            parent=getattr(self, "ui", None),
        )
        self._progressive_clips_worker = worker
        worker.batch_ready.connect(self._on_progressive_clips_batch)
        worker.finished_ok.connect(self._on_progressive_clips_finished)
        worker.discover_failed.connect(self._on_progressive_clips_failed)
        worker.start()
        logging.info("Startup library scan: Progressive (viewport-lazy Clips)")
        return True

    def _on_progressive_clips_batch(self, rows) -> None:
        if not getattr(self, "_clips_progressive_active", False):
            return
        if not rows:
            return
        table = getattr(getattr(self, "ui", None), "table_clips", None)
        grid = getattr(self, "grid_clips", None)
        if table is None:
            return
        table.setUpdatesEnabled(False)
        if grid is not None:
            grid.setUpdatesEnabled(False)
        try:
            for row in rows:
                if not isinstance(row, ScannedClip):
                    continue
                path = os.path.normcase(os.path.normpath(row.full_path))
                if any(
                    path == os.path.normcase(os.path.normpath(root))
                    for root in (getattr(self, "clips_folders", None) or [])
                ):
                    continue
                self._insert_scanned_clip_row(row)
        finally:
            table.setUpdatesEnabled(True)
            if grid is not None:
                grid.setUpdatesEnabled(True)
        if hasattr(self, "fast_sync_grid"):
            self.fast_sync_grid()
        if hasattr(self, "_update_library_count_label"):
            self._update_library_count_label()
        self._schedule_clips_viewport_refresh(0)

    def _on_progressive_clips_finished(self, total: int) -> None:
        self._progressive_clips_worker = None
        if not getattr(self, "_clips_progressive_active", False):
            return
        table = getattr(getattr(self, "ui", None), "table_clips", None)
        if table is not None:
            table.setSortingEnabled(True)
            table.horizontalHeader().setSectionsClickable(False)
        if hasattr(self, "fast_sync_grid"):
            self.fast_sync_grid()
        self._purge_inferior_session_siblings()
        if hasattr(self, "sync_library_filter_view"):
            self.sync_library_filter_view()
        if hasattr(self, "_update_library_count_label"):
            self._update_library_count_label()
        QTimer.singleShot(0, self._sync_library_scrollbars)
        QTimer.singleShot(1500, self._persist_clips_library_snapshot)
        self._schedule_clips_viewport_refresh(0)
        if getattr(self, "_startup_library_scan_active", False) and hasattr(
            self, "preload_render_history"
        ):
            self._startup_library_scan_active = False
            self.preload_render_history(announce=False)
        elif hasattr(self, "update_status_indicator"):
            self.update_status_indicator("Ready", "ready")
        logging.info("Progressive Clips: %d placeholders ready", int(total or 0))

    def _on_progressive_clips_failed(self, message: str) -> None:
        self._progressive_clips_worker = None
        logging.warning("Progressive Clips discover failed: %s", message)
        if getattr(self, "_startup_library_scan_active", False):
            self._startup_library_scan_active = False
        if hasattr(self, "update_status_indicator"):
            self.update_status_indicator("Ready", "ready")

    def _on_clips_scroll(self, *_args) -> None:
        if not getattr(self, "_clips_progressive_active", False):
            return
        self._clips_scroll_active = True
        timer = getattr(self, "_clips_viewport_timer", None)
        if timer is not None:
            timer.start()

    def _clips_on_scroll_idle(self) -> None:
        self._clips_scroll_active = False
        self._clips_refresh_viewport()

    def _schedule_clips_viewport_refresh(self, delay_ms: int = 0) -> None:
        if not getattr(self, "_clips_progressive_active", False):
            return
        timer = getattr(self, "_clips_viewport_timer", None)
        if timer is None:
            QTimer.singleShot(max(0, int(delay_ms)), self._clips_refresh_viewport)
            return
        if delay_ms <= 0:
            timer.start(1)
        else:
            timer.start(int(delay_ms))

    def _clips_visible_items(self) -> list:
        grid = getattr(self, "grid_clips", None)
        if grid is None:
            return []
        vp = grid.viewport()
        if vp is None:
            return []
        area = vp.rect().adjusted(
            0, -_CLIP_VIEWPORT_OVERSCAN_PX, 0, _CLIP_VIEWPORT_OVERSCAN_PX
        )
        out = []
        for i in range(grid.count()):
            item = grid.item(i)
            if item is None or item.isHidden():
                continue
            idx = grid.indexFromItem(item)
            if not idx.isValid():
                continue
            if area.intersects(grid.visualRect(idx)):
                out.append(item)
        if grid.count() <= 0 or vp.height() <= 0:
            return out
        cols_fn = getattr(self, "_clip_grid_column_count_for", None)
        cols = int(cols_fn(grid)) if callable(cols_fn) else 6
        cols = max(1, cols)
        cell_h = max(1, _CLIP_CARD_SIZE.height() + max(0, int(grid.spacing())))
        rows = max(2, (vp.height() + _CLIP_VIEWPORT_OVERSCAN_PX) // cell_h + 1)
        expect = min(grid.count(), cols * rows)
        if len(out) >= expect:
            return out
        # Portable Choose a Clip: first row had visualRects, the rest still
        # (0,0,0,0) until layout — fill the first screen by index.
        seen = {id(item) for item in out}
        for i in range(expect):
            item = grid.item(i)
            if item is not None and not item.isHidden() and id(item) not in seen:
                out.append(item)
        return out

    def _materialize_clip_grid_item(self, item) -> ClipCard | None:
        if not getattr(self, "_clips_progressive_active", False):
            # Still allow one-shot materialize if a placeholder somehow remains.
            pass
        return self._attach_clip_card_to_grid_item(item)

    def _dematerialize_clip_grid_item(self, item) -> None:
        grid = getattr(self, "grid_clips", None)
        if grid is None or item is None:
            return
        card = grid.itemWidget(item)
        if card is None:
            return
        path = str(item.data(Qt.UserRole + 1) or "")
        grid.removeItemWidget(item)
        try:
            card.deleteLater()
        except RuntimeError:
            pass
        live = getattr(self, "_clip_live_paths", None)
        if isinstance(live, set) and path:
            live.discard(os.path.normcase(os.path.normpath(path)))

    def _clip_item_distance_from_viewport(self, grid, item, vp_rect) -> int:
        idx = grid.indexFromItem(item)
        if not idx.isValid():
            return 10**9
        vr = grid.visualRect(idx)
        if vr.bottom() < vp_rect.top():
            return vp_rect.top() - vr.bottom()
        if vr.top() > vp_rect.bottom():
            return vr.top() - vp_rect.bottom()
        return 0

    def _clips_refresh_viewport(self) -> None:
        """Materialize visible (+overscan) ClipCards; keep already-seen ones."""
        if getattr(self, "_clips_scroll_active", False):
            return
        if not getattr(self, "_clips_progressive_active", False):
            return
        grid = getattr(self, "grid_clips", None)
        if grid is None:
            return
        if getattr(self, "_library_panel_mode", "clips") != "clips":
            if not grid.isVisible():
                return
        try:
            grid.doItemsLayout()
        except Exception:
            pass

        visible = self._clips_visible_items()
        keep_keys: set[str] = set()
        for item in visible:
            path = str(item.data(Qt.UserRole + 1) or "")
            if path:
                keep_keys.add(os.path.normcase(os.path.normpath(path)))
            self._materialize_clip_grid_item(item)

        live = getattr(self, "_clip_live_paths", None)
        if not isinstance(live, set) or len(live) <= _CLIP_MAX_LIVE_WIDGETS:
            return

        # Already-seen cards stay. Only drop farthest extras if RAM cap is hit.
        vp = grid.viewport()
        vp_rect = vp.rect() if vp is not None else None
        index: dict[str, object] = {}
        for i in range(grid.count()):
            it = grid.item(i)
            if it is None:
                continue
            p = str(it.data(Qt.UserRole + 1) or "")
            if p:
                index[os.path.normcase(os.path.normpath(p))] = it

        candidates: list[tuple[int, object]] = []
        for key in list(live):
            if key in keep_keys:
                continue
            item = index.get(key)
            if item is None or item.isSelected():
                continue
            dist = (
                self._clip_item_distance_from_viewport(grid, item, vp_rect)
                if vp_rect is not None
                else 10**9
            )
            candidates.append((dist, item))
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        for _dist, item in candidates:
            live = getattr(self, "_clip_live_paths", None)
            if not isinstance(live, set) or len(live) <= _CLIP_MAX_LIVE_WIDGETS:
                break
            self._dematerialize_clip_grid_item(item)

    def restore_clips_from_session_cache(
        self,
        *,
        append_new: bool = True,
        require_exists: bool = False,
    ) -> bool:
        """Skip / Smart Launch: paint last session JSON immediately.

        No deep library walk and no ffprobe. ``require_exists`` drops rows whose
        folders are gone (Smart Launch when the fingerprint changed). Duration /
        new-clip top-ups happen silently afterward when ``append_new``.
        """
        if not hasattr(self, "ui") or not hasattr(self.ui, "table_clips"):
            return False

        if not getattr(self, "clips_folders", None):
            self._load_clips_folders_from_settings()
        library_roots = list(getattr(self, "clips_folders", None) or [])
        if not library_roots:
            return False

        # JSON first — Smart Launch may optionally recheck existence per row.
        clips = clips_from_library_cache(
            getattr(self, "cache_dir", None),
            library_roots=library_roots,
            require_exists=bool(require_exists),
        )
        if not clips:
            # Seed is a no-I/O Skip fallback. Smart Launch (changed) must not
            # resurrect health-cache ghosts — fall through to Quick instead.
            if require_exists:
                return False
            self._ensure_clip_health_cache()
            clips = seed_clips_from_health_cache(
                getattr(self, "cache_dir", None),
                library_roots=library_roots,
                health_cache=getattr(self, "_clip_health_cache", {}) or {},
                game_names_cache=getattr(self, "game_names_cache", {}) or {},
            )
        if not clips:
            return False

        self._stop_library_scan()
        self._stop_progressive_clips_discover()
        self._stop_clip_poster_backfill()
        self._stop_clip_duration_backfill()
        self._scan_pending_rows = []
        self._scan_flush_scheduled = False
        self._scan_total = 0
        self._scan_inserted = 0
        self._scan_finalize_pending = None
        self._scan_append_new_only = False
        self._scan_snapshot_restore = True
        self._clips_progressive_active = False
        self._clip_live_paths = set()
        self._snapshot_append_new_after = bool(append_new)
        self._library_clip_rows = []
        self._saved_clips_selection_path = ""
        self._preview_clip_path = None
        self._clips_visual_selected_rows = set()
        if hasattr(self, "_clear_clips_selection_visual"):
            self._clear_clips_selection_visual()

        table = self.ui.table_clips
        grid = getattr(self, "grid_clips", None)
        table.setSortingEnabled(False)
        table.setRowCount(0)
        if grid is not None:
            self._grid_anchor_item = None
            self._grid_anchor_index = -1
            grid.clear()

        self._scan_generation = getattr(self, "_scan_generation", 0) + 1
        self._clips_scan_active = False
        self._sync_library_scan_interaction_lock(busy=False)

        table.setUpdatesEnabled(False)
        if grid is not None:
            grid.setUpdatesEnabled(False)
        try:
            for row in clips:
                self._insert_scanned_clip_row(row)
        finally:
            table.setUpdatesEnabled(True)
            if grid is not None:
                grid.setUpdatesEnabled(True)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionsClickable(False)
        if hasattr(self, "fast_sync_grid"):
            self.fast_sync_grid()
        # Snapshot may still hold FG+CLIP pairs from older quiet appends.
        self._purge_inferior_session_siblings()

        self._scan_snapshot_restore = False
        want_append = bool(getattr(self, "_snapshot_append_new_after", False))
        self._snapshot_append_new_after = False

        if hasattr(self, "_update_library_count_label"):
            self._update_library_count_label()

        if getattr(self, "_startup_library_scan_active", False) and hasattr(
            self, "preload_render_history"
        ):
            self._startup_library_scan_active = False
            # Quiet — Skip/Smart already shows Ready; announcing "Loading render history…"
            # made startup feel like another 1–3s prepare after the window opened.
            self.preload_render_history(announce=False)
        elif hasattr(self, "update_status_indicator"):
            self.update_status_indicator("Ready", "ready")

        if hasattr(self, "sync_library_filter_view"):
            self.sync_library_filter_view()

        QTimer.singleShot(0, self._sync_library_scrollbars)
        logging.info(
            "Library snapshot: painted %d clips (append_new=%s, require_exists=%s)",
            len(clips),
            want_append,
            bool(require_exists),
        )

        # Snapshot rewrite is not needed before first paint — defer off the
        # critical path (same for duration / poster top-ups below).
        QTimer.singleShot(1500, self._persist_clips_library_snapshot)

        # Background only — UI already Ready.
        QTimer.singleShot(400, self._schedule_clip_duration_backfill)
        # Thumbs were skipped on paint (no W: I/O); resolve/generate off-thread.
        QTimer.singleShot(
            700,
            lambda: self._schedule_clip_poster_backfill(skip_ui_probe=True),
        )
        if want_append:
            QTimer.singleShot(2500, self._append_new_clips_only)
        return True

    def _stop_clip_duration_backfill(self) -> None:
        worker = getattr(self, "_clip_duration_worker", None)
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(3000)
        self._clip_duration_worker = None

    def _schedule_clip_duration_backfill(self) -> None:
        """Fill missing clip durations from MPD (Skip seed / sparse Refresh leftovers)."""
        if not hasattr(self, "ui") or not hasattr(self.ui, "table_clips"):
            return
        self._stop_clip_duration_backfill()
        paths: list[str] = []
        table = self.ui.table_clips
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            dur_item = table.item(row, 3)
            if name_item is None:
                continue
            path = name_item.data(Qt.UserRole)
            dur = (dur_item.text() if dur_item else "").strip()
            if not path:
                continue
            if dur and dur not in ("--:--", "—", "--"):
                continue
            paths.append(str(path))
        if not paths:
            return

        worker = ClipDurationBackfillWorker(paths, parent=self.ui)
        self._clip_duration_worker = worker
        worker.duration_ready.connect(self._on_clip_duration_ready)
        worker.finished_backfill.connect(self._on_clip_duration_backfill_finished)
        worker.failed.connect(
            lambda msg: logging.warning("Duration backfill failed: %s", msg)
        )
        worker.start()

    def _on_clip_duration_ready(self, clip_path: str, duration_str: str) -> None:
        if not hasattr(self, "ui") or not hasattr(self.ui, "table_clips"):
            return
        norm = os.path.normpath(clip_path)
        table = self.ui.table_clips
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            if name_item is None:
                continue
            path = name_item.data(Qt.UserRole)
            if not path or os.path.normpath(str(path)) != norm:
                continue
            dur_item = table.item(row, 3)
            if dur_item is None:
                dur_item = QTableWidgetItem()
                dur_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                table.setItem(row, 3, dur_item)
            dur_item.setText(duration_str)

            for stored in getattr(self, "_library_clip_rows", None) or []:
                if os.path.normpath(stored.full_path) == norm:
                    stored.duration_str = duration_str
                    break

            date_item = table.item(row, 2)
            date_raw = date_item.text() if date_item else ""
            title = (name_item.text() or "").strip()
            footer = self._clip_card_footer_text(title, date_raw, duration_str)
            if hasattr(self, "grid_clips"):
                for i in range(self.grid_clips.count()):
                    gitem = self.grid_clips.item(i)
                    if gitem is None:
                        continue
                    if os.path.normpath(str(gitem.data(Qt.UserRole + 1) or "")) != norm:
                        continue
                    card = self.grid_clips.itemWidget(gitem)
                    if card is not None and hasattr(card, "set_date_footer"):
                        card.set_date_footer(footer)
                    break
            break

    def _on_clip_duration_backfill_finished(self, updated: int) -> None:
        self._clip_duration_worker = None
        if updated:
            self._persist_clips_library_snapshot()
            logging.info("Filled %d clip duration(s) from MPD", updated)

    def _append_new_clips_only(self) -> None:
        """Quiet Skip follow-up: discover folders and parse only paths not already listed."""
        if getattr(self, "_clips_scan_active", False):
            return
        if not getattr(self, "clips_folders", None):
            self._load_clips_folders_from_settings()
        library_roots = [
            f for f in (getattr(self, "clips_folders", None) or []) if f and os.path.exists(f)
        ]
        if not library_roots:
            return

        known = {
            os.path.normpath(r.full_path)
            for r in (getattr(self, "_library_clip_rows", None) or [])
        }
        self._scan_generation = getattr(self, "_scan_generation", 0) + 1
        generation = self._scan_generation
        self._ensure_clip_health_cache()
        self._scan_pending_rows = []
        self._scan_flush_scheduled = False
        self._scan_total = 0
        self._scan_inserted = 0
        self._scan_finalize_pending = None
        self._scan_append_new_only = True
        self._scan_snapshot_restore = False
        self._clips_scan_active = True
        # Do not lock the whole UI for a quiet top-up.
        self._sync_library_scan_interaction_lock(busy=False)

        worker = LibraryScanWorker(
            library_roots,
            self.cache_dir,
            self._clip_health_cache,
            self.game_names_cache,
            fast=True,
            from_cache=False,
            known_paths=known,
            parent=self.ui,
        )
        self._library_scan_worker = worker
        worker.discovering.connect(
            lambda total: self._on_scan_discovering(total, generation)
        )
        worker.clip_ready.connect(
            lambda row, index, total: self._on_scan_clip_ready(
                row, index, total, generation
            )
        )
        worker.finished_scan.connect(
            lambda stats: self._on_scan_finished(stats, generation, False)
        )
        worker.scan_error.connect(
            lambda msg: self._on_scan_error(msg, generation)
        )
        worker.start()

    def scan_clips(
        self,
        announce_duplicates: bool = False,
        *,
        fast: bool = True,
        from_cache: bool = False,
    ):
        """Scan library roots on a background thread with live progress in the status bar.

        fast=True skips ffprobe during health checks only. Game names and icons are
        still fetched from Steam when missing from cache (first launch, new app id).
        Use Refresh ▾ → Re-check clip health for a full ffprobe pass.

        from_cache=True rebuilds rows from clip_health_cache paths (seed when no
        session snapshot exists yet). Prefer ``restore_clips_from_session_cache``
        for Settings → Skip.
        """
        if not hasattr(self.ui, "table_clips"):
            return

        self._stop_library_scan()
        self._stop_progressive_clips_discover()
        self._stop_clip_poster_backfill()
        self._stop_clip_duration_backfill()
        self._scan_pending_rows = []
        self._scan_flush_scheduled = False
        self._scan_total = 0
        self._scan_inserted = 0
        self._scan_finalize_pending = None
        self._scan_append_new_only = False
        self._scan_snapshot_restore = False
        self._clips_progressive_active = False
        self._clip_live_paths = set()
        self._library_clip_rows = []
        self._saved_clips_selection_path = ""
        self._preview_clip_path = None
        if hasattr(self, "_clear_clips_selection_visual"):
            self._clear_clips_selection_visual()
        self.ui.table_clips.setSortingEnabled(False)
        self.ui.table_clips.setRowCount(0)

        if hasattr(self, "grid_clips"):
            self._grid_anchor_item = None
            self._grid_anchor_index = -1
            self.grid_clips.clear()

        self._sync_library_scrollbars(force_hide=True)

        if not getattr(self, "clips_folders", None):
            self._load_clips_folders_from_settings()

        library_roots = [f for f in self.clips_folders if f and os.path.exists(f)]
        if not library_roots:
            if hasattr(self, "_update_library_count_label"):
                self._update_library_count_label()
            self._clips_scan_active = False
            self._sync_library_scan_interaction_lock(busy=False)
            if hasattr(self, "update_status_indicator"):
                self.update_status_indicator("Ready", "ready")
            self._sync_library_scrollbars()
            self._maybe_start_deferred_rendered_scan()
            return

        self._scan_generation = getattr(self, "_scan_generation", 0) + 1
        generation = self._scan_generation
        self._ensure_clip_health_cache()
        self._clips_scan_active = True
        self._sync_library_scan_interaction_lock(busy=True)

        if hasattr(self, "_update_library_count_label"):
            self._update_library_count_label()
        if hasattr(self, "update_status_indicator"):
            if from_cache:
                self.update_status_indicator(
                    "Restoring clips from cache…", "busy", scan_phase="search"
                )
            else:
                self.update_status_indicator(
                    "Searching for clips…", "busy", scan_phase="search"
                )

        worker = LibraryScanWorker(
            library_roots,
            self.cache_dir,
            self._clip_health_cache,
            self.game_names_cache,
            fast=fast,
            from_cache=from_cache,
            parent=self.ui,
        )
        self._library_scan_worker = worker
        worker.discovering.connect(
            lambda total: self._on_scan_discovering(total, generation)
        )
        worker.clip_ready.connect(
            lambda row, index, total: self._on_scan_clip_ready(row, index, total, generation)
        )
        worker.finished_scan.connect(
            lambda stats: self._on_scan_finished(stats, generation, announce_duplicates)
        )
        worker.scan_error.connect(
            lambda msg: self._on_scan_error(msg, generation)
        )
        worker.start()
    
    def get_clip_size_and_duration(self, clip_path, mpd_content, *, measure_size: bool = True):
        # Duration from XML is cheap; full folder walks block clip-open on long recordings.
        if measure_size:
            size_mb = discovery.folder_size_bytes(clip_path) / (1024 * 1024)
            size_str = f"{size_mb / 1024:.2f} GB" if size_mb >= 1000 else f"{size_mb:.1f} MB"
        else:
            size_str = "…"

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

    def _schedule_clip_folder_size_label(self, clip_path: str) -> None:
        """Measure folder size off the UI thread (can walk thousands of chunks)."""
        if not clip_path:
            return
        self._clip_size_label_gen = getattr(self, "_clip_size_label_gen", 0) + 1
        gen = self._clip_size_label_gen
        import threading

        def _worker():
            try:
                size_mb = discovery.folder_size_bytes(clip_path) / (1024 * 1024)
            except OSError:
                return
            size_str = (
                f"{size_mb / 1024:.2f} GB" if size_mb >= 1000 else f"{size_mb:.1f} MB"
            )
            # Context ``self`` (main thread) — bare singleShot from this worker
            # would run the label update on the wrong thread and never paint.
            QTimer.singleShot(
                0,
                self,
                lambda g=gen, p=clip_path, s=size_str: self._apply_clip_folder_size_str(
                    g, p, s
                ),
            )

        threading.Thread(
            target=_worker, name="steempeg-clip-size", daemon=True
        ).start()

    def _apply_clip_folder_size_str(self, gen: int, clip_path: str, size_str: str) -> None:
        if gen != getattr(self, "_clip_size_label_gen", 0):
            return
        want = (
            self._norm_clip_path_key(clip_path)
            if hasattr(self, "_norm_clip_path_key")
            else os.path.normpath(clip_path)
        )
        active = getattr(self, "_preview_clip_path", None) or getattr(
            self, "_last_export_clip_path", None
        )
        active_key = (
            self._norm_clip_path_key(active)
            if active and hasattr(self, "_norm_clip_path_key")
            else (os.path.normpath(active) if active else "")
        )
        if want and active_key and want != active_key:
            return
        if hasattr(self.ui, "label_size"):
            self.ui.label_size.setText(f"Size: {size_str}")
    

    

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
        self._clips_visual_selected_rows = set()
        self.grid_clips.clear()

        for row in range(self.ui.table_clips.rowCount()):
            self._append_grid_card_for_row(row)

        self.sync_grid_from_table_selection()
        QTimer.singleShot(0, self.sync_clip_card_edge_roles)
        QTimer.singleShot(0, self._sync_library_scrollbars)

    def _filter_popup_floor_y(self, menu_y: int) -> int:
        """Bottom Y the filter popup may grow down to (global coords).

        Desktop keeps Refresh in the footer mega-pill → that Y is the floor.
        Portable mounts Refresh into the *top* toolbar next to the filter pill,
        so using Refresh there would leave ~0px for Games and force the cramped
        mobile-looking popup. Fall back to the Clips Manager panel / window bottom.
        """
        candidates: list[int] = []

        refresh = getattr(self, "btn_refresh", None)
        if refresh is not None:
            try:
                ry = refresh.mapToGlobal(QPoint(0, 0)).y()
                # Only treat Refresh as the floor when it sits clearly below the popup.
                if ry > menu_y + 80:
                    candidates.append(ry)
            except RuntimeError:
                pass

        footer = getattr(self, "_footer_mega_pill", None)
        if footer is not None:
            try:
                if footer.isVisible():
                    fy = footer.mapToGlobal(QPoint(0, 0)).y()
                    if fy > menu_y + 40:
                        candidates.append(fy)
            except RuntimeError:
                pass

        panel = getattr(getattr(self, "ui", None), "left_panel", None)
        if panel is not None:
            try:
                br = panel.mapToGlobal(QPoint(0, panel.height()))
                if br.y() > menu_y + 40:
                    candidates.append(br.y())
            except RuntimeError:
                pass

        if candidates:
            return min(candidates)

        # Last resort: window that hosts the filter pill (sheet or main shell).
        host = self.btn_filter_pill.window() if hasattr(self, "btn_filter_pill") else None
        if host is not None:
            try:
                return host.mapToGlobal(QPoint(0, host.height())).y()
            except RuntimeError:
                pass
        return menu_y + 480

    def _filter_menu_density(self):
        """Density from Clips Manager footprint (sheet / left pane), not shell alone."""
        from steempeg.ui.ui_density import COMFORT, density_for_width

        dense = getattr(self, "_ui_density", None)
        panel = getattr(getattr(self, "ui", None), "left_panel", None)
        host = None
        if hasattr(self, "btn_filter_pill") and self.btn_filter_pill is not None:
            try:
                host = self.btn_filter_pill.window()
            except RuntimeError:
                host = None
        width = 0
        for w in (host, panel):
            if w is None:
                continue
            try:
                width = max(width, int(w.width() or 0))
            except RuntimeError:
                pass
        if width <= 0:
            return dense if dense is not None else COMFORT
        local = density_for_width(
            width, widget=host or panel or getattr(self, "ui", None)
        )
        if dense is None:
            return local
        # Roomier of the two — large Choose-a-Clip sheet → desktop filter chrome.
        if getattr(local, "scale", 0.0) >= getattr(dense, "scale", 0.0):
            return local
        return dense

    def _position_filter_menu(self, *, relayout: bool = True):
        """Place + size the filter popup relative to the live widget geometry.

        ``relayout=True`` picks stack vs 3-col. The post-show timer uses
        ``relayout=False`` so only position/ceiling refresh — no mode flash.
        """
        menu = getattr(self, 'filter_menu', None)
        if not menu or not hasattr(self, 'btn_filter_pill'):
            return
        button_bottom_left = self.btn_filter_pill.mapToGlobal(QPoint(0, self.btn_filter_pill.height()))
        menu_y = button_bottom_left.y() + 5

        floor_y = self._filter_popup_floor_y(menu_y)
        avail = max(160, floor_y - menu_y - 8)
        if relayout:
            menu.set_content_max_height(avail, relayout=True)
        elif not bool(getattr(menu, "_three_col", False)):
            # Stack may need a ceiling tweak after show; 3-col height is
            # deterministic — re-packing made Clear/Apply drift across opens.
            menu.set_content_max_height(avail, relayout=False)

        # Width may change with mode — compute X after sizing.
        x_shift = menu.width() - self.btn_filter_pill.width()
        menu_x = button_bottom_left.x() - x_shift + 10
        host = None
        try:
            host = self.btn_filter_pill.window()
        except RuntimeError:
            host = None

        three_col = bool(getattr(menu, "_three_col", False))
        # 3-col may be wider than Choose-a-Clip — clamp to the main program shell.
        clamp = host
        if three_col:
            shell = getattr(self, "ui", None)
            try:
                if shell is not None and int(shell.width() or 0) > int(
                    (host.width() if host is not None else 0) or 0
                ):
                    clamp = shell
            except RuntimeError:
                pass

        if clamp is not None:
            try:
                pad = 12 if three_col else 8
                min_x = clamp.mapToGlobal(QPoint(pad, 0)).x()
                max_x = clamp.mapToGlobal(
                    QPoint(max(pad, clamp.width() - menu.width() - pad), 0)
                ).x()
                if three_col:
                    # Keep the right edge near the filter pill.
                    pill_right = self.btn_filter_pill.mapToGlobal(
                        QPoint(self.btn_filter_pill.width(), 0)
                    ).x()
                    menu_x = pill_right - menu.width() + 12
                menu_x = max(min_x, min(menu_x, max_x))
            except RuntimeError:
                pass

        menu.move(menu_x, menu_y)

    def show_filter_menu(self):
        """ Calculates the coordinates and passes the ENTIRE PROGRAM (self) to the menu. """
        if not hasattr(self, 'btn_filter_pill'): return
        if getattr(self, "_clips_scan_active", False):
            return

        # 1. Forcefully destroy the old window to reset the Qt focus bug.
        if hasattr(self, 'filter_menu') and self.filter_menu:
            self.filter_menu.deleteLater()
            
        # 2. Creating a brand-new menu from scratch
        # Heal view↔memory desync before rebuilding pills (ghost hidden cards).
        if hasattr(self, "sync_library_filter_view"):
            self.sync_library_filter_view()
        self.filter_menu = FilterMenu(self.ui)
        self.filter_menu.gather_statistics(self)
        dense = self._filter_menu_density()
        if dense is not None and hasattr(self.filter_menu, "apply_density"):
            self.filter_menu.apply_density(dense)

        # Size + place while hidden, then show once — avoids stack↔3-col flash.
        self.filter_menu.setVisible(False)
        self._position_filter_menu(relayout=True)
        self.filter_menu.show()
        # Geometry settle: move/ceiling only, do not switch column mode.
        QTimer.singleShot(0, lambda: self._position_filter_menu(relayout=False))

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
                # Steam folder stamp (stable across Refresh); FS mtime only as fallback.
                clip_path = r[0].data(Qt.UserRole) if r[0] else ""
                return (
                    clip_folder_default_sort_key(clip_path),
                    os.path.normcase(os.path.normpath(str(clip_path or ""))),
                )
                
            if sort_idx in (1, 2): # GAME NAME
                txt = r[0].text().lower() if r[0] else ""
                return re.sub(r'[^a-zа-я0-9]', '', txt)
                
            if sort_idx in (3, 4): # TYPE
                txt = r[1].text().lower() if r[1] else ""
                return re.sub(r'[^a-zа-я0-9]', '', txt)

            if sort_idx in (5, 6): # HEALTH
                level = self._row_display_health_level(r[0]) if r[0] else health.ClipHealth.HEALTHY.value
                rank = {
                    health.ClipHealth.HEALTHY.value: 3,
                    health.ClipHealth.CURED.value: 2,
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

            if sort_idx in (11, 12):  # FOLDER (library root / parent dir)
                clip_path = r[0].data(Qt.UserRole) if r[0] else ""
                roots = getattr(self, "clips_folders", None) or []
                return clip_folder_sort_key(clip_path, roots)

            return data['orig_row']

       
        reverse = sort_idx in (0, 2, 4, 6, 8, 10, 12)
        if sort_idx == 0:
            # Newest stamp first, then stable path (avoid reverse=True flipping the path).
            def default_order(data):
                stamp, path_key = get_sort_key(data)
                return (-float(stamp), path_key)

            all_data.sort(key=default_order)
        else:
            all_data.sort(key=get_sort_key, reverse=reverse)
        
        for new_row, data in enumerate(all_data):
            for col, item in enumerate(data['table_items']):
                table.setItem(new_row, col, item)
            table.setRowHidden(new_row, data['hidden'])

        # Keep session snapshot rows aligned with the visible table order.
        rows = getattr(self, "_library_clip_rows", None)
        if rows:
            by_path = {os.path.normpath(r.full_path): r for r in rows}
            ordered: list[ScannedClip] = []
            seen: set[str] = set()
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                path = item.data(Qt.UserRole) if item else None
                if not path:
                    continue
                key = os.path.normpath(str(path))
                stored = by_path.get(key)
                if stored is not None and key not in seen:
                    ordered.append(stored)
                    seen.add(key)
            for stored in rows:
                key = os.path.normpath(stored.full_path)
                if key not in seen:
                    ordered.append(stored)
                    seen.add(key)
            self._library_clip_rows = ordered
            
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
        # 1b. Local Steam appmanifest (installed libraries)
        local = games.find_local_steam_game_name(app_id)
        if local:
            self.game_names_cache[app_id] = local
            self.save_json_cache()
            return local
        if not allow_fetch:
            return f"Unknown Game ({app_id})"
        # 2. Otherwise, ask Steam once and remember
        name = games.fetch_game_name(app_id)
        if name:
            self.game_names_cache[app_id] = name
            self.save_json_cache()
            return name
        return f"Unknown Game ({app_id})"
    



    

    
    def _icon_from_disk(self, icon_path: str, app_id: str | None = None) -> QIcon:
        pixmap = QPixmap(icon_path)
        if pixmap.isNull():
            return QIcon()
        from steempeg.ui.icon_shape import shaped_game_icon

        icon = shaped_game_icon(pixmap)
        if app_id:
            self.game_icons_cache[str(app_id)] = icon
        return icon

    def refresh_game_icon_shapes(self, shape: str | None = None) -> None:
        """Re-shape cached game icons after Settings → Visual change (in-place, no grid rebuild)."""
        import logging

        from steempeg.core.rendered_media import parse_app_id_from_clip_folder
        from steempeg.ui.icon_shape import get_icon_shape, set_icon_shape

        if shape is not None:
            set_icon_shape(shape)
        applied = get_icon_shape()
        logging.info("Game icon shape → %s", applied)

        cache = getattr(self, "game_icons_cache", None)
        if isinstance(cache, dict):
            cache.clear()

        if hasattr(self.ui, "table_clips"):
            table = self.ui.table_clips
            seen: set[str] = set()
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if not item:
                    continue
                clip_path = item.data(Qt.UserRole)
                app_id = None
                if clip_path:
                    app_id = parse_app_id_from_clip_folder(os.path.basename(str(clip_path)))
                if not app_id:
                    app_id = self._app_id_for_clip_path(clip_path)
                if not app_id or app_id in seen:
                    continue
                seen.add(app_id)
                icon = self.get_game_icon(app_id, allow_download=False)
                if not icon.isNull():
                    # Table rows only — grid is handled in a single pass below.
                    for r in range(table.rowCount()):
                        cell = table.item(r, 0)
                        if not cell:
                            continue
                        if self._app_id_for_clip_path(cell.data(Qt.UserRole)) != app_id:
                            continue
                        cell.setIcon(icon)
            try:
                table.viewport().update()
            except Exception as exc:
                logging.debug("clips table viewport update failed: %s", exc)

        try:
            self._refresh_grid_game_icon_shapes()
        except Exception:
            logging.exception("grid icon shape refresh failed")

        try:
            self._refresh_queue_game_icon_shapes()
        except Exception:
            logging.exception("queue icon shape refresh failed")

        try:
            self._refresh_header_game_icon_shapes()
        except Exception:
            logging.exception("header icon shape refresh failed")

        if hasattr(self, "table_rendered") and self.table_rendered is not None:
            try:
                from steempeg.ui.icon_shape import shaped_game_icon

                _icon_role = Qt.ItemDataRole.UserRole + 8
                for row in range(self.table_rendered.rowCount()):
                    item = self.table_rendered.item(row, 0)
                    if not item:
                        continue
                    path = item.data(_icon_role) or ""
                    if path and os.path.isfile(str(path)):
                        pix = QPixmap(str(path))
                        if not pix.isNull():
                            item.setIcon(shaped_game_icon(pix))
                self.table_rendered.viewport().update()
            except Exception as exc:
                logging.warning("rendered icon refresh failed: %s", exc)

    def _refresh_grid_game_icon_shapes(self) -> None:
        """Update existing ClipCard icon_label pixmaps without rebuilding the grid."""
        from steempeg.infra.paths import get_resource_path
        from steempeg.ui.icon_shape import (
            ICON_SHAPE_CIRCLE,
            get_icon_shape,
            shaped_game_icon_pixmap,
        )

        unknown = get_resource_path("unknown_icon.png")

        def _reshape_card(card, pix_path: str, *, force_circle: bool = False) -> None:
            if card is None or not hasattr(card, "icon_label"):
                return
            if not pix_path or not os.path.isfile(pix_path):
                pix_path = unknown
                force_circle = True
            if not pix_path or not os.path.isfile(pix_path):
                return
            src = QPixmap(pix_path)
            if src.isNull():
                return
            shape = (
                ICON_SHAPE_CIRCLE
                if force_circle or os.path.basename(pix_path).lower() == "unknown_icon.png"
                else get_icon_shape()
            )
            from steempeg.ui.icon_utils import apply_square_icon

            apply_square_icon(
                card.icon_label,
                shaped_game_icon_pixmap(src, 24, shape),
                24,
            )

        if hasattr(self, "grid_clips"):
            for idx in range(self.grid_clips.count()):
                item = self.grid_clips.item(idx)
                if item is None:
                    continue
                clip_path = item.data(Qt.UserRole + 1)
                app_id = self._app_id_for_clip_path(clip_path)
                icon_path = (
                    os.path.join(self.cache_dir, f"{app_id}.jpg") if app_id else ""
                )
                _reshape_card(self.grid_clips.itemWidget(item), icon_path)

        if hasattr(self, "grid_rendered") and hasattr(self, "table_rendered"):
            _icon_role = Qt.ItemDataRole.UserRole + 8
            for idx in range(self.grid_rendered.count()):
                item = self.grid_rendered.item(idx)
                if item is None:
                    continue
                icon_path = ""
                row = item.data(Qt.UserRole)
                if isinstance(row, int):
                    cell = self.table_rendered.item(row, 0)
                    if cell is not None:
                        icon_path = cell.data(_icon_role) or ""
                _reshape_card(self.grid_rendered.itemWidget(item), str(icon_path or ""))

    def _refresh_queue_game_icon_shapes(self) -> None:
        """Re-shape game icons on existing queue cards (no panel rebuild)."""
        from steempeg.infra.paths import get_resource_path
        from steempeg.ui.icon_shape import shaped_game_icon_pixmap
        from steempeg.ui.queue_card_shared import set_game_icon_label

        panel = getattr(self, "render_queue_panel", None)
        if panel is None:
            return
        for card in getattr(panel, "_card_widgets", []) or []:
            job = getattr(card, "_job", None)
            if job is None:
                continue
            if hasattr(card, "_game_icon"):
                set_game_icon_label(card._game_icon, job, size=28)
            icon_label = getattr(card, "_icon_label", None)
            if icon_label is None:
                continue
            icon_path = getattr(job, "game_icon_path", "") or ""
            unknown = get_resource_path("unknown_icon.png")
            pix_path = icon_path if icon_path and os.path.exists(icon_path) else unknown
            if pix_path and os.path.exists(pix_path):
                from steempeg.ui.icon_utils import apply_square_icon

                src = QPixmap(pix_path)
                shaped = shaped_game_icon_pixmap(src, 24) if not src.isNull() else None
                apply_square_icon(icon_label, shaped, 24)

    def _refresh_header_game_icon_shapes(self) -> None:
        """Re-shape player header / bottom summary / center place logo icons."""
        from steempeg.infra.paths import get_resource_path
        from steempeg.ui.icon_shape import (
            ICON_SHAPE_CIRCLE,
            shaped_game_icon_pixmap,
        )

        path = self._resolve_header_game_icon_path()
        unknown = get_resource_path("unknown_icon.png")
        if not path or not os.path.isfile(path):
            path = unknown
        is_unknown = os.path.basename(path).lower() == "unknown_icon.png"
        shape = ICON_SHAPE_CIRCLE if is_unknown else None

        from steempeg.ui.icon_utils import apply_square_icon
        from steempeg.ui.player_header_layout import player_header_icon_px

        header_icon_px = player_header_icon_px(self)
        for attr, size in (
            ("custom_icon_label", header_icon_px),
            ("bottom_icon_label", 24),
        ):
            label = getattr(self, attr, None)
            if label is None:
                continue
            label.setStyleSheet("background: transparent; border: none;")
            src = QPixmap(path)
            shaped = shaped_game_icon_pixmap(src, size, shape) if not src.isNull() else None
            apply_square_icon(label, shaped, size)

        place = getattr(self, "place_logo", None)
        if place is not None and place.isVisible():
            logo_path = get_resource_path("logo.png")
            place_path = path
            if is_unknown and logo_path and os.path.isfile(logo_path):
                place_path = logo_path
            place.setStyleSheet("background: transparent; border: none;")
            src = QPixmap(place_path)
            shaped = shaped_game_icon_pixmap(src, 80, shape) if not src.isNull() else None
            apply_square_icon(place, shaped, 80)

    def _icon_path_for_current_rendered(self) -> str:
        """Game icon path for the active Rendered-videos selection (if any)."""
        _icon_role = Qt.ItemDataRole.UserRole + 8
        _game_role = Qt.ItemDataRole.UserRole + 6
        table = getattr(self, "table_rendered", None)
        if table is not None:
            row = table.currentRow()
            if row >= 0:
                item = table.item(row, 0)
                if item is not None:
                    stored = item.data(_icon_role) or ""
                    if stored and os.path.isfile(str(stored)):
                        return str(stored)
                    if (item.data(_game_role) or "") == "Unknown":
                        from steempeg.infra.paths import get_resource_path

                        unknown = get_resource_path("unknown_icon.png")
                        return unknown if os.path.isfile(unknown) else ""

        file_path = getattr(self, "_rendered_media_path", None) or ""
        if file_path and hasattr(self, "_resolved_rendered_meta"):
            try:
                _title, icon_path, _thumb, is_unknown, _key = self._resolved_rendered_meta(
                    file_path, os.path.basename(str(file_path))
                )
            except Exception:
                icon_path = ""
                is_unknown = False
            if icon_path and os.path.isfile(str(icon_path)):
                return str(icon_path)
            if is_unknown:
                from steempeg.infra.paths import get_resource_path

                unknown = get_resource_path("unknown_icon.png")
                return unknown if os.path.isfile(unknown) else ""
        return ""

    def _resolve_header_game_icon_path(self) -> str:
        """Best path for the player header game icon (clips or rendered)."""
        panel = getattr(self, "_library_panel_mode", "clips")
        rendered_path = getattr(self, "_rendered_media_path", None)
        if panel == "rendered" or rendered_path:
            rendered_icon = self._icon_path_for_current_rendered()
            if rendered_icon:
                # Keep current_game_icon in sync so later refreshes stay correct.
                self.current_game_icon = rendered_icon
                return rendered_icon

        path = getattr(self, "current_game_icon", "") or ""
        if path and os.path.isfile(path):
            return path

        # Last resort: re-derive from sticky export clip / preview clip.
        clip_path = None
        if hasattr(self, "_current_header_clip_path"):
            try:
                clip_path = self._current_header_clip_path()
            except Exception:
                clip_path = None
        if not clip_path:
            clip_path = getattr(self, "_preview_clip_path", None)
        if clip_path:
            parts = os.path.basename(str(clip_path)).split("_")
            if len(parts) >= 2 and parts[1].isdigit():
                cache_icon = os.path.join(self.cache_dir, f"{parts[1]}.jpg")
                if os.path.isfile(cache_icon):
                    self.current_game_icon = cache_icon
                    return cache_icon
        return path or ""

    def _app_id_for_clip_path(self, clip_path: str | None) -> str | None:
        if not clip_path:
            return None
        parts = os.path.basename(clip_path).split("_")
        if len(parts) >= 4 and parts[1].isdigit():
            return parts[1]
        return None

    def _apply_game_icon_to_rows(self, app_id: str, icon: QIcon) -> None:
        if icon.isNull() or not hasattr(self.ui, "table_clips"):
            return

        app_id = str(app_id)
        table = self.ui.table_clips
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if not item:
                continue
            if self._app_id_for_clip_path(item.data(Qt.UserRole)) != app_id:
                continue
            item.setIcon(icon)

        if not hasattr(self, "grid_clips"):
            return
        for idx in range(self.grid_clips.count()):
            item = self.grid_clips.item(idx)
            if item is None:
                continue
            clip_path = item.data(Qt.UserRole + 1)
            if self._app_id_for_clip_path(clip_path) != app_id:
                continue
            card = self.grid_clips.itemWidget(item)
            if card is None or not hasattr(card, "icon_label"):
                continue
            icon_path = os.path.join(self.cache_dir, f"{app_id}.jpg")
            if os.path.isfile(icon_path):
                pixmap = QPixmap(icon_path)
                if not pixmap.isNull():
                    from steempeg.ui.icon_shape import shaped_game_icon_pixmap
                    from steempeg.ui.icon_utils import apply_square_icon

                    apply_square_icon(
                        card.icon_label,
                        shaped_game_icon_pixmap(pixmap, 24),
                        24,
                    )

    def _backfill_missing_game_icons(self) -> None:
        """Retry icon fetch for games that still show a blank list icon after scan."""
        if not hasattr(self.ui, "table_clips"):
            return

        missing: set[str] = set()
        for row in range(self.ui.table_clips.rowCount()):
            item = self.ui.table_clips.item(row, 0)
            if not item or not item.icon().isNull():
                continue
            app_id = self._app_id_for_clip_path(item.data(Qt.UserRole))
            if app_id:
                missing.add(app_id)

        if not missing:
            return

        for app_id in sorted(missing):
            icon = self.get_game_icon(app_id, allow_download=True)
            if not icon.isNull():
                self._apply_game_icon_to_rows(app_id, icon)

    def get_game_icon(self, app_id, *, allow_download: bool = True):
        app_id = str(app_id)
        cached = self.game_icons_cache.get(app_id)
        if cached is not None and not cached.isNull():
            return cached
        if app_id in getattr(games, "_FAILED_ICON_DOWNLOADS", ()):
            return QIcon()
        icon_path = os.path.join(self.cache_dir, f"{app_id}.jpg")
        if not os.path.isfile(icon_path) or os.path.getsize(icon_path) <= 100:
            if not allow_download or not games.download_icon(app_id, icon_path):
                return QIcon()
        icon = self._icon_from_disk(icon_path, app_id)
        if icon.isNull():
            self.game_icons_cache.pop(app_id, None)
        return icon

    def set_view_mode(self, mode, *, relayout: bool = True):
        if mode == "list":
            self.grid_clips.hide()
            self.ui.table_clips.show()
        else:
            self.ui.table_clips.hide()
            self.grid_clips.show()

            # HARD GEOMETRY RECALCULATION — only when the user flips List↔Grid
            # or geometry truly changed. Tab switches must not pay doItemsLayout.
            if relayout:
                self.grid_clips.doItemsLayout()

            if self.grid_clips.selectedItems():
                self.grid_clips.scrollToItem(self.grid_clips.selectedItems()[0])

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