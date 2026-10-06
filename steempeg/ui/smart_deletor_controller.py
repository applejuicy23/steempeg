"""Smart Deletor glue: library tables → candidates → delete queue → library refresh."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QObject, Qt

from steempeg.library.smart_delete import (
    KIND_CLIP,
    KIND_RENDERED,
    DeleteCandidate,
    DeleteRules,
    format_size,
    parse_duration_text,
)

_CLIP_HEALTH_ROLE = Qt.ItemDataRole.UserRole + 2
_CLIP_CURED_ROLE = Qt.ItemDataRole.UserRole + 4
_RENDERED_THUMB_ROLE = Qt.ItemDataRole.UserRole + 7
_THUMB_RESOLVE_CAP = 200


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _health_str(value) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


class SmartDeletorController(QObject):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._panel = None
        self._scan_worker = None
        self._run_worker = None
        self._run_sizes: dict[str, int] = {}
        self._run_kinds: dict[str, str] = {}
        self._deleted: list[tuple[str, str]] = []
        self._failed: list[str] = []

    def attach(self, panel) -> None:
        self._panel = panel
        panel.find_requested.connect(self._on_find)
        panel.start_requested.connect(self._on_start)
        panel.cancel_requested.connect(self._on_cancel)
        panel.games_requested.connect(self._refresh_games)
        panel.preview_requested.connect(self._on_preview)
        panel.reveal_requested.connect(self._on_reveal)
        get_layout = getattr(self._app, "get_layout_setting", None)
        if callable(get_layout):
            panel.set_view_mode(str(get_layout("smart_deletor_view_mode", "list") or "list"))
        save_layout = getattr(self._app, "save_layout_setting", None)
        if callable(save_layout):
            panel.view_mode_changed.connect(
                lambda mode: save_layout("smart_deletor_view_mode", mode)
            )
        self._refresh_games()

    def _on_preview(self, path: str, kind: str) -> None:
        app = self._app
        try:
            if kind == KIND_CLIP and hasattr(app, "open_source_clip"):
                app.open_source_clip(path, play=True)
            elif kind != KIND_CLIP and hasattr(app, "open_in_rendered_videos"):
                app.open_in_rendered_videos(path, play=True)
        except Exception:
            logging.exception("Smart Deletor preview failed for %s", path)

    def _on_reveal(self, path: str, kind: str) -> None:
        app = self._app
        try:
            if kind == KIND_CLIP and hasattr(app, "open_clip_folder"):
                app.open_clip_folder(path)
            elif kind != KIND_CLIP and hasattr(app, "open_rendered_folder"):
                app.open_rendered_folder(path)
        except Exception:
            logging.exception("Smart Deletor open folder failed for %s", path)

    # --- collection --------------------------------------------------------

    def _clip_table(self):
        return getattr(getattr(self._app, "ui", None), "table_clips", None)

    def _rendered_rows(self) -> list:
        return list(getattr(self._app, "_library_rendered_rows", None) or [])

    def _refresh_games(self) -> None:
        if self._panel is None:
            return
        games: set[str] = set()
        table = self._clip_table()
        if table is not None:
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and item.text().strip():
                    games.add(item.text().strip())
        for scanned in self._rendered_rows():
            if (scanned.game_filter_name or "").strip():
                games.add(scanned.game_filter_name.strip())
        self._panel.set_games(sorted(games))

    def _collect_clips(self, rendered_sources: set[str]) -> list[DeleteCandidate]:
        from steempeg.library.scan import clip_folder_recorded_at

        table = self._clip_table()
        if table is None:
            return []
        selected = {idx.row() for idx in table.selectionModel().selectedRows()}
        out: list[DeleteCandidate] = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not path or not os.path.isdir(path):
                continue
            dur_item = table.item(row, 3)
            type_item = table.item(row, 1)
            recorded = clip_folder_recorded_at(path)
            out.append(
                DeleteCandidate(
                    path=path,
                    kind=KIND_CLIP,
                    title=item.text().strip(),
                    type_label=type_item.text().strip() if type_item else "",
                    game=item.text().strip(),
                    duration_sec=parse_duration_text(dur_item.text()) if dur_item else None,
                    health=(
                        "cured"
                        if item.data(_CLIP_CURED_ROLE)
                        else _health_str(item.data(_CLIP_HEALTH_ROLE))
                    ),
                    recorded_at=recorded.timestamp() if recorded else 0.0,
                    rendered=os.path.basename(os.path.normpath(path)).lower() in rendered_sources,
                    in_selection=row in selected,
                    in_filter=not table.isRowHidden(row),
                )
            )
        return out

    def _collect_rendered(self) -> list[DeleteCandidate]:
        table = getattr(self._app, "table_rendered", None)
        thumbs: dict[str, str] = {}
        hidden: set[str] = set()
        selected: set[str] = set()
        if table is not None:
            sel_rows = {idx.row() for idx in table.selectionModel().selectedRows()}
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is None:
                    continue
                key = _norm(str(item.data(Qt.ItemDataRole.UserRole) or ""))
                thumbs[key] = str(item.data(_RENDERED_THUMB_ROLE) or "")
                if table.isRowHidden(row):
                    hidden.add(key)
                if row in sel_rows:
                    selected.add(key)
        out: list[DeleteCandidate] = []
        for scanned in self._rendered_rows():
            if not os.path.isfile(scanned.full_path):
                continue
            key = _norm(scanned.full_path)
            out.append(
                DeleteCandidate(
                    path=scanned.full_path,
                    kind=KIND_RENDERED,
                    title=(scanned.display_title or "").strip()
                    or os.path.basename(scanned.full_path),
                    type_label=f"🎥 {scanned.type_label or 'Rendered'}",
                    game=(scanned.game_filter_name or "").strip(),
                    size_bytes=int(scanned.file_size or 0),
                    duration_sec=scanned.duration_sec,
                    health=_health_str(scanned.health_level),
                    recorded_at=float(scanned.file_mtime or 0.0),
                    thumb_path=thumbs.get(key, ""),
                    icon_path=scanned.icon_path,
                    in_selection=key in selected,
                    in_filter=key not in hidden,
                )
            )
        return out

    # --- find --------------------------------------------------------------

    def _on_find(self, rules: DeleteRules) -> None:
        panel = self._panel
        if panel is None or self._scan_worker is not None:
            return
        if rules.include_clips and getattr(self._app, "_clips_scan_active", False):
            panel.set_run_summary("Clips are still loading — try again in a moment")
            return
        needs_rendered = rules.include_rendered or rules.only_rendered
        rendered_rows = self._rendered_rows()
        if needs_rendered and not rendered_rows and hasattr(self._app, "scan_rendered_outputs"):
            self._app.scan_rendered_outputs()
            panel.set_run_summary("Loading Rendered Videos — press Find again in a moment")
            return

        rendered_sources = {
            (r.source_clip_name or "").lower() for r in rendered_rows if r.source_clip_name
        }
        candidates: list[DeleteCandidate] = []
        if rules.include_clips:
            candidates.extend(self._collect_clips(rendered_sources))
        if rules.include_rendered:
            candidates.extend(self._collect_rendered())

        from steempeg.ui.smart_deletor_workers import SmartDeleteScanWorker

        worker = SmartDeleteScanWorker(candidates, rules, parent=self)
        worker.progress.connect(lambda d, t: panel.set_scanning(True, d, t))
        worker.finished_scan.connect(self._on_scan_done)
        worker.finished.connect(worker.deleteLater)
        self._scan_worker = worker
        panel.set_scanning(True)
        worker.start()

    def _on_scan_done(self, results: list) -> None:
        self._scan_worker = None
        if self._panel is None:
            return
        from steempeg.core.clip_thumbnails import resolve_clip_thumbnail_ui_safe
        from steempeg.render.queue import game_icon_path_for_clip

        cache_dir = getattr(self._app, "cache_dir", None)
        for cand in results:
            if cand.kind == KIND_CLIP and not cand.icon_path and cache_dir:
                cand.icon_path = game_icon_path_for_clip(cache_dir, cand.path)
        for cand in results[:_THUMB_RESOLVE_CAP]:
            if cand.kind == KIND_CLIP and not cand.thumb_path:
                try:
                    cand.thumb_path = resolve_clip_thumbnail_ui_safe(cand.path, cache_dir)
                except Exception:
                    cand.thumb_path = ""
        self._panel.set_scanning(False)
        self._panel.set_results(results)

    # --- delete ------------------------------------------------------------

    def _on_start(self, items: list, permanent: bool) -> None:
        panel = self._panel
        if panel is None or self._run_worker is not None or not items:
            return
        from steempeg.ui.message_dialog import steempeg_confirm_delete

        n = len(items)
        noun = "item" if n == 1 else "items"
        if permanent:
            question = f"Permanently delete {n} {noun}?"
            detail = "Skips the Recycle Bin. This cannot be undone!"
            label = f"🗑️ Delete forever ({n})"
        else:
            question = f"Move {n} {noun} to the Recycle Bin?"
            detail = "You can restore them from the Recycle Bin later."
            label = f"🗑️ Move to Recycle Bin ({n})"
        if not steempeg_confirm_delete(
            self._app.ui, "Smart Deletor", question, detail=detail, delete_label=label
        ):
            return

        paths = [p for p, _k in items]
        if hasattr(self._app, "release_media_before_delete_any"):
            try:
                self._app.release_media_before_delete_any(paths)
            except Exception:
                logging.debug("Smart Deletor media release failed", exc_info=True)
        cache_dir = getattr(self._app, "cache_dir", None)
        for path, kind in items:
            if kind != KIND_CLIP:
                continue
            try:
                from steempeg.infra.media_cache import purge_clip_media_cache

                purge_clip_media_cache(cache_dir, path)
            except Exception:
                logging.debug("Clip media-cache purge failed", exc_info=True)

        self._run_kinds = {_norm(p): k for p, k in items}
        self._run_sizes = panel.candidate_sizes()
        self._deleted = []
        self._failed = []

        from steempeg.ui.smart_deletor_workers import SmartDeleteRunWorker

        worker = SmartDeleteRunWorker(items, permanent=permanent, cache_dir=cache_dir, parent=self)
        worker.item_started.connect(panel.mark_started)
        worker.item_finished.connect(self._on_item_finished)
        worker.finished.connect(self._on_run_done)
        worker.finished.connect(worker.deleteLater)
        self._run_worker = worker
        panel.set_running(True)
        logging.info("Smart Deletor: %s %d item(s)", "deleting" if permanent else "recycling", n)
        worker.start()

    def _on_item_finished(self, path: str, ok: bool, error: str) -> None:
        if self._panel is not None:
            self._panel.mark_finished(path, ok, error)
        kind = self._run_kinds.get(_norm(path), KIND_CLIP)
        if ok:
            self._deleted.append((path, kind))
        else:
            self._failed.append(path)
        done = len(self._deleted) + len(self._failed)
        if self._panel is not None:
            self._panel.set_run_summary(f"Deleting… {done}/{len(self._run_kinds)}")

    def _on_cancel(self) -> None:
        if self._run_worker is not None:
            self._run_worker.requestInterruption()

    def _on_run_done(self) -> None:
        cancelled = bool(self._run_worker and self._run_worker.isInterruptionRequested())
        self._run_worker = None
        freed = sum(self._run_sizes.get(_norm(p), 0) for p, _k in self._deleted)
        parts = [f"Deleted {len(self._deleted)}", f"{format_size(freed)} freed"]
        if self._failed:
            parts.append(f"{len(self._failed)} failed")
        if cancelled:
            parts.append("cancelled")
        if self._panel is not None:
            self._panel.set_running(False)
            self._panel.set_run_summary(" · ".join(parts))
        logging.info("Smart Deletor finished: %s", " · ".join(parts))
        self._apply_to_library()

    def _apply_to_library(self) -> None:
        app = self._app
        clips = [p for p, k in self._deleted if k == KIND_CLIP]
        rendered = [p for p, k in self._deleted if k == KIND_RENDERED]
        for path in clips:
            try:
                if hasattr(app, "_on_queue_source_removed"):
                    app._on_queue_source_removed(path)
                if hasattr(app, "_clear_salvage_verified"):
                    app._clear_salvage_verified(path)
                salvaged = getattr(app, "_salvaged_clips", None)
                if isinstance(salvaged, dict):
                    salvaged.pop(os.path.normpath(path), None)
            except Exception:
                logging.debug("Smart Deletor per-clip cleanup failed", exc_info=True)

        if clips:
            def _drop_from_ui() -> None:
                try:
                    if hasattr(app, "_remove_library_clip_paths_from_ui"):
                        app._remove_library_clip_paths_from_ui(clips)
                    live = getattr(app, "_clip_live_paths", None)
                    if isinstance(live, set):
                        for path in clips:
                            live.discard(_norm(path))
                    if hasattr(app, "reapply_saved_library_filters"):
                        app.reapply_saved_library_filters()
                    if hasattr(app, "_persist_clips_library_snapshot"):
                        app._persist_clips_library_snapshot()
                except Exception:
                    logging.exception("Smart Deletor library drop failed")

            if hasattr(app, "_fade_out_clip_cards"):
                app._fade_out_clip_cards(clips, _drop_from_ui)
            else:
                _drop_from_ui()

        if rendered:
            try:
                app._rendered_output_meta_index = None
                if hasattr(app, "scan_rendered_outputs"):
                    app.scan_rendered_outputs()
                if hasattr(app, "_persist_library_ui_state"):
                    app._persist_library_ui_state()
            except Exception:
                logging.exception("Smart Deletor rendered refresh failed")
