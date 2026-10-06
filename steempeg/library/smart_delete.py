"""Smart Deletor: delete candidates and the user-picked rules that select them.

Pure data + matching — no Qt, safe on worker threads.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

KIND_CLIP = "clip"
KIND_RENDERED = "rendered"

HEALTH_DEAD = "dead"
HEALTH_DEGRADED = "degraded"


@dataclass
class DeleteCandidate:
    path: str
    kind: str  # KIND_CLIP / KIND_RENDERED
    title: str = ""
    type_label: str = ""  # library Type column, e.g. "🎬 Clip" / "🎞️ FG" / "📼 BG"
    game: str = ""
    size_bytes: int = 0
    duration_sec: float | None = None
    health: str = ""
    recorded_at: float = 0.0  # epoch seconds
    thumb_path: str = ""
    icon_path: str = ""
    rendered: bool = False  # clip has at least one rendered output
    in_selection: bool = False
    in_filter: bool = True

    @property
    def key(self) -> str:
        return os.path.normcase(os.path.normpath(self.path))


@dataclass
class DeleteRules:
    """Every enabled rule must match (AND). Disabled rules are ignored."""

    include_clips: bool = True
    include_rendered: bool = False
    min_size_mb: float | None = None
    max_duration_sec: float | None = None
    min_duration_sec: float | None = None
    health_dead: bool = False
    health_degraded: bool = False
    older_than_days: int | None = None
    games: set[str] = field(default_factory=set)
    only_rendered: bool = False
    only_selection: bool = False
    only_filter: bool = False

    def has_any_filter(self) -> bool:
        return any(
            (
                self.min_size_mb is not None,
                self.max_duration_sec is not None,
                self.min_duration_sec is not None,
                self.health_dead,
                self.health_degraded,
                self.older_than_days is not None,
                bool(self.games),
                self.only_rendered,
                self.only_selection,
                self.only_filter,
            )
        )


def candidate_matches(c: DeleteCandidate, rules: DeleteRules, *, now: float | None = None) -> bool:
    if c.kind == KIND_CLIP and not rules.include_clips:
        return False
    if c.kind == KIND_RENDERED and not rules.include_rendered:
        return False
    if rules.min_size_mb is not None and c.size_bytes < rules.min_size_mb * 1024 * 1024:
        return False
    if rules.max_duration_sec is not None:
        if c.duration_sec is None or c.duration_sec > rules.max_duration_sec:
            return False
    if rules.min_duration_sec is not None:
        if c.duration_sec is None or c.duration_sec < rules.min_duration_sec:
            return False
    if rules.health_dead or rules.health_degraded:
        wanted = set()
        if rules.health_dead:
            wanted.add(HEALTH_DEAD)
        if rules.health_degraded:
            wanted.add(HEALTH_DEGRADED)
        if c.health not in wanted:
            return False
    if rules.older_than_days is not None:
        if not c.recorded_at:
            return False
        age_s = (now if now is not None else time.time()) - c.recorded_at
        if age_s < rules.older_than_days * 86400:
            return False
    if rules.games and c.game not in rules.games:
        return False
    if rules.only_rendered and c.kind == KIND_CLIP and not c.rendered:
        return False
    if rules.only_selection and not c.in_selection:
        return False
    if rules.only_filter and not c.in_filter:
        return False
    return True


def folder_size_bytes(path: str) -> int:
    total = 0
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def parse_duration_text(text: str) -> float | None:
    """``1:23`` / ``1:02:03`` / ``45s`` → seconds."""
    raw = (text or "").strip().lower().rstrip("s")
    if not raw:
        return None
    try:
        parts = [float(p) for p in raw.split(":")]
    except ValueError:
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"
