"""Diagnostic trace for multi-folder clip discovery / session dedupe.

Writes ``logs/clip_discover_YYYYMMDD_HHMMSS.{json,txt}`` on every
``discover_clip_paths`` call so we can compare:

* primary folder alone
* primary + second folder

Enable always (default) or force-off with ``STEEMPEG_TRACE_CLIPS=0``.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any


def tracing_enabled() -> bool:
    raw = (os.environ.get("STEEMPEG_TRACE_CLIPS") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _logs_dir() -> str:
    try:
        from steempeg.infra.paths import get_install_root

        root = get_install_root()
    except Exception:
        root = os.getcwd()
    path = os.path.join(root, "logs")
    os.makedirs(path, exist_ok=True)
    return path


def _which_root(path: str, library_roots: list[str]) -> str | None:
    from steempeg.core.clip_identity import expand_library_root_aliases

    norm = os.path.normcase(os.path.normpath(path))
    for root in library_roots:
        if not root:
            continue
        for alias in expand_library_root_aliases(root):
            r = os.path.normcase(os.path.normpath(alias))
            if norm == r or norm.startswith(r + os.sep):
                return os.path.normpath(root)
    return None


class ClipDiscoverTrace:
    """Accumulate one discover pass, then flush to disk."""

    def __init__(self, library_roots: list[str]) -> None:
        self.library_roots = [os.path.normpath(r) for r in (library_roots or []) if r]
        self.collected_by_root: dict[str, list[str]] = {
            r: [] for r in self.library_roots
        }
        self.collected_orphan: list[str] = []
        self.after_session_dedupe: list[str] = []
        self.session_ignored: list[dict[str, Any]] = []
        self.session_groups: list[dict[str, Any]] = []
        self.filter_kept: list[dict[str, Any]] = []
        self.filter_skipped: list[dict[str, Any]] = []
        self.basename_dupes: list[dict[str, Any]] = []
        self.final_candidates: list[str] = []
        self.duplicate_count = 0
        self.notes: list[str] = []

    def note_collected(self, path: str) -> None:
        root = _which_root(path, self.library_roots)
        if root is not None:
            self.collected_by_root.setdefault(root, []).append(os.path.normpath(path))
        else:
            self.collected_orphan.append(os.path.normpath(path))

    def note_session_group(
        self,
        *,
        session_key: str,
        members: list[str],
        keeper: str | None,
        ignored: list[str],
        cross_folder: bool = False,
    ) -> None:
        self.session_groups.append(
            {
                "session_key": session_key,
                "members": [os.path.normpath(p) for p in members],
                "keeper": os.path.normpath(keeper) if keeper else None,
                "ignored": [os.path.normpath(p) for p in ignored],
                "cross_folder": bool(cross_folder),
                "member_roots": {
                    os.path.normpath(p): _which_root(p, self.library_roots)
                    for p in members
                },
            }
        )
        reason = (
            "cross_folder_lost_to_keeper"
            if cross_folder
            else "session_sibling_lost_to_keeper"
        )
        for path in ignored:
            self.session_ignored.append(
                {
                    "path": os.path.normpath(path),
                    "session_key": session_key,
                    "keeper": os.path.normpath(keeper) if keeper else None,
                    "root": _which_root(path, self.library_roots),
                    "cross_folder": bool(cross_folder),
                    "reason": reason,
                }
            )

    def note_after_session_dedupe(self, paths: list[str], ignored_count: int) -> None:
        self.after_session_dedupe = [os.path.normpath(p) for p in paths]
        self.duplicate_count = int(ignored_count)

    def note_filter_skip(self, path: str, reason: str) -> None:
        self.filter_skipped.append(
            {
                "path": os.path.normpath(path),
                "root": _which_root(path, self.library_roots),
                "reason": reason,
            }
        )

    def note_filter_keep(self, path: str, *, via: str) -> None:
        self.filter_kept.append(
            {
                "path": os.path.normpath(path),
                "root": _which_root(path, self.library_roots),
                "via": via,
            }
        )

    def note_basename_dupe(self, path: str, kept_name: str) -> None:
        self.basename_dupes.append(
            {
                "path": os.path.normpath(path),
                "root": _which_root(path, self.library_roots),
                "basename": kept_name,
                "reason": "same_basename_already_kept",
            }
        )
        self.duplicate_count += 1

    def note_final(self, paths: list[str], duplicate_count: int) -> None:
        self.final_candidates = [os.path.normpath(p) for p in paths]
        self.duplicate_count = int(duplicate_count)

    def add_note(self, text: str) -> None:
        self.notes.append(str(text))

    def flush(self) -> tuple[str, str] | None:
        if not tracing_enabled():
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(_logs_dir(), f"clip_discover_{stamp}")
        json_path = base + ".json"
        txt_path = base + ".txt"

        payload = {
            "stamp": stamp,
            "library_roots": self.library_roots,
            "root_count": len(self.library_roots),
            "collected_by_root": {
                root: sorted(paths) for root, paths in self.collected_by_root.items()
            },
            "collected_counts": {
                root: len(paths) for root, paths in self.collected_by_root.items()
            },
            "collected_orphan": self.collected_orphan,
            "session_groups": self.session_groups,
            "session_ignored": self.session_ignored,
            "after_session_dedupe": self.after_session_dedupe,
            "filter_kept": self.filter_kept,
            "filter_skipped": self.filter_skipped,
            "basename_dupes": self.basename_dupes,
            "final_candidates": self.final_candidates,
            "final_count": len(self.final_candidates),
            "duplicate_count": self.duplicate_count,
            "notes": self.notes,
        }

        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

        lines: list[str] = []
        lines.append(f"clip discover trace  {stamp}")
        lines.append(f"library_roots ({len(self.library_roots)}):")
        for i, root in enumerate(self.library_roots):
            tag = "PRIMARY" if i == 0 else f"extra#{i}"
            lines.append(f"  [{tag}] {root}")
        lines.append("")
        lines.append("=== collected under each root (before session dedupe) ===")
        for i, root in enumerate(self.library_roots):
            paths = sorted(self.collected_by_root.get(root) or [])
            tag = "PRIMARY" if i == 0 else f"extra#{i}"
            lines.append(f"[{tag}] count={len(paths)}  {root}")
            for p in paths:
                lines.append(f"  + {os.path.basename(p)}")
                lines.append(f"      {p}")
        if self.collected_orphan:
            lines.append(f"[orphan] count={len(self.collected_orphan)}")
            for p in self.collected_orphan:
                lines.append(f"  + {p}")
        lines.append("")
        lines.append("=== session dedupe groups (clip_/bg_/fg_ siblings) ===")
        if not self.session_groups:
            lines.append("(none / single-member only)")
        for g in self.session_groups:
            tag = " CROSS-FOLDER" if g.get("cross_folder") else ""
            lines.append(f"session {g['session_key']}{tag}")
            lines.append(f"  KEEP  {g['keeper']}")
            for p in g["ignored"]:
                lines.append(f"  DROP  {p}  (root={g['member_roots'].get(p)})")
        cross_sessions = sum(1 for g in self.session_groups if g.get("cross_folder"))
        lines.append("")
        lines.append(
            f"=== after session dedupe: {len(self.after_session_dedupe)} paths "
            f"(paths_dropped={len(self.session_ignored)}, "
            f"cross_folder_sessions={cross_sessions}, "
            f"duplicate_count={self.duplicate_count}) ==="
        )
        lines.append("")
        lines.append("=== filter pass (container / DASH / steempeg noise) ===")
        for row in self.filter_skipped:
            lines.append(
                f"  SKIP [{row['reason']}]  {os.path.basename(row['path'])}"
            )
            lines.append(f"       {row['path']}  root={row['root']}")
        for row in self.basename_dupes:
            lines.append(
                f"  SKIP [basename_dupe:{row['basename']}]  {row['path']}"
            )
        lines.append("")
        lines.append(
            f"=== FINAL candidates: {len(self.final_candidates)}  "
            f"duplicate_count={self.duplicate_count} ==="
        )
        for p in self.final_candidates:
            root = _which_root(p, self.library_roots)
            lines.append(f"  OK  {os.path.basename(p)}  root={root}")
            lines.append(f"      {p}")
        if self.notes:
            lines.append("")
            lines.append("=== notes ===")
            lines.extend(f"  - {n}" for n in self.notes)

        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

        logging.info(
            "Clip discover trace written: %s (+ .json) roots=%d final=%d dupes=%d",
            txt_path,
            len(self.library_roots),
            len(self.final_candidates),
            self.duplicate_count,
        )
        return json_path, txt_path
