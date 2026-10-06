"""Smart Deletor background work: find matching candidates, then delete them."""

from __future__ import annotations

import dataclasses
import logging
import os
import shutil
import time

from PySide6.QtCore import QThread, Signal

from steempeg.library.smart_delete import (
    KIND_CLIP,
    DeleteCandidate,
    DeleteRules,
    candidate_matches,
    folder_size_bytes,
)


class SmartDeleteScanWorker(QThread):
    """Apply rules; folder sizes are only walked for candidates that pass the rest."""

    progress = Signal(int, int)  # done, total
    finished_scan = Signal(object)  # list[DeleteCandidate]

    def __init__(self, candidates: list[DeleteCandidate], rules: DeleteRules, parent=None):
        super().__init__(parent)
        self._candidates = candidates
        self._rules = rules

    def run(self) -> None:
        now = time.time()
        sizeless = dataclasses.replace(self._rules, min_size_mb=None)
        survivors = [c for c in self._candidates if candidate_matches(c, sizeless, now=now)]
        total = len(survivors)
        out: list[DeleteCandidate] = []
        for i, cand in enumerate(survivors, start=1):
            if self.isInterruptionRequested():
                return
            if cand.size_bytes <= 0:
                cand.size_bytes = folder_size_bytes(cand.path)
            if candidate_matches(cand, self._rules, now=now):
                out.append(cand)
            if i % 8 == 0 or i == total:
                self.progress.emit(i, total)
        out.sort(key=lambda c: c.size_bytes, reverse=True)
        self.finished_scan.emit(out)


class SmartDeleteRunWorker(QThread):
    """Delete queued paths one by one — Recycle Bin by default, permanent on request."""

    item_started = Signal(str)
    item_finished = Signal(str, bool, str)  # path, ok, error

    def __init__(self, items: list[tuple[str, str]], *, permanent: bool, cache_dir=None, parent=None):
        super().__init__(parent)
        self._items = items  # (path, kind)
        self._permanent = permanent
        self._cache_dir = cache_dir

    def run(self) -> None:
        for path, kind in self._items:
            if self.isInterruptionRequested():
                return
            self.item_started.emit(path)
            try:
                self._delete_one(path, kind)
            except Exception as exc:
                logging.error("Smart Deletor failed on %s: %s", path, exc)
                self.item_finished.emit(path, False, str(exc))
                continue
            self.item_finished.emit(path, True, "")

    def _delete_one(self, path: str, kind: str) -> None:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        last_exc: Exception | None = None
        for attempt in range(6):
            try:
                if not self._permanent:
                    from steempeg.infra.recycle_bin import send_to_recycle_bin

                    send_to_recycle_bin(path)
                elif kind == KIND_CLIP:
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                last_exc = None
                break
            except OSError as exc:
                last_exc = exc
                if not os.path.exists(path):
                    last_exc = None
                    break
                time.sleep(0.05 * (attempt + 1))
        if last_exc is not None:
            raise last_exc
        if kind != KIND_CLIP:
            try:
                from steempeg.core.rendered_media import remove_rendered_companion_meta

                remove_rendered_companion_meta(path, cache_dir=self._cache_dir)
            except Exception:
                logging.debug("Rendered companion meta cleanup failed", exc_info=True)
