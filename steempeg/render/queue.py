"""Render queue data model — pure Python, no Qt.

Each RenderJob stores a snapshot of user-chosen export settings that can be edited
per queue item before the batch runner starts (stage 2+ UI).
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional

from steempeg.render.output_formats import KNOWN_OUTPUT_EXTENSIONS, output_extension


class JobStatus(Enum):
    QUEUED = "queued"
    RENDERING = "rendering"
    COMPLETED = "completed"
    ERROR = "error"


# UI colours for queue cards and the player header badge (stage 3+).
STATUS_COLORS = {
    JobStatus.QUEUED: "#ffcc00",
    JobStatus.RENDERING: "#ff9800",
    JobStatus.COMPLETED: "#4CAF50",
    JobStatus.ERROR: "#ff4444",
}

STATUS_HEADER_LABELS = {
    JobStatus.QUEUED: "In queue",
    JobStatus.RENDERING: "Rendering",
    JobStatus.COMPLETED: "Completed",
    JobStatus.ERROR: "Error",
}

PREVIEW_BADGE_TEXT = "Preview"
PREVIEW_BADGE_COLOR = "#ffffff"


@dataclass
class RenderJobSettings:
    """Editable render parameters captured from the settings panel."""

    quality_text: str = ""
    fps_text: str = ""
    bitrate_text: str = ""
    codec_text: str = ""
    encoder_codec: str = "libx264"
    encoder_display: str = ""
    audio_only: bool = False
    mute_audio: bool = False
    audio_format: str = "AAC"
    audio_bitrate_text: str = "192 kbps"
    output_basename: str = ""
    save_dir: str = ""
    trim_start_ms: int = 0
    trim_end_ms: int = 0
    is_trim_mode: bool = False
    custom_target_bitrate: int = 1500
    custom_target_height: int = -1
    size_slider_index: int = 0
    custom_fps: Optional[int] = None
    custom_vbitrate: Optional[float] = None
    custom_abitrate: Optional[int] = None
    orig_fps: int = 60
    orig_video_mbps: float = 0.0
    orig_audio_kbps: int = 192
    container_format: str = "MP4"
    output_preset: str = "Custom"


@dataclass
class RenderJob:
    clip_path: str
    game_name: str
    clip_date: str
    clip_time: str
    game_icon_path: str
    settings: RenderJobSettings
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: JobStatus = JobStatus.QUEUED
    queue_index: int = 0
    output_file: str = ""
    error_message: str = ""
    salvage_mpds: List[str] = field(default_factory=list)

    def refresh_output_path(self) -> str:
        """Recompute a collision-safe output path from current settings."""
        s = self.settings
        ext = output_extension(s.container_format, s.audio_only, s.audio_format)
        self.output_file = compute_unique_output_path(s.save_dir, s.output_basename, ext)
        return self.output_file


@dataclass
class ResolvedRenderParams:
    """Arguments ready for RenderThread."""

    all_mpds: List[str]
    quality_text: str
    output_file: str
    ffmpeg_exe: str
    save_dir: str
    selected_encoder: str
    video_bitrate: str
    fps_text: str
    audio_only: bool
    mute_audio: bool
    audio_format: str
    audio_bitrate_kbps: str
    target_scale_h: int
    trim_start_sec: float
    trim_duration_sec: float
    container_format: str = "MP4"


def compute_unique_output_path(save_dir: str, base_filename: str, ext: str) -> str:
    base = (base_filename or "rendered").strip()
    lower = base.lower()
    for suffix in KNOWN_OUTPUT_EXTENSIONS:
        if lower.endswith(suffix):
            base = base[: -len(suffix)]
            break
    candidate = os.path.join(save_dir, f"{base}{ext}")
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(save_dir, f"{base}_{counter}{ext}")
        counter += 1
    return candidate


def game_icon_path_for_clip(cache_dir: str, clip_path: str) -> str:
    folder = os.path.basename(clip_path)
    parts = folder.split("_")
    if len(parts) >= 2 and parts[1].isdigit():
        return os.path.join(cache_dir, f"{parts[1]}.jpg")
    return ""


class RenderQueue:
    """Ordered list of render jobs with basic queue operations."""

    def __init__(self) -> None:
        self._jobs: List[RenderJob] = []

    def __len__(self) -> int:
        return len(self._jobs)

    def __iter__(self) -> Iterator[RenderJob]:
        return iter(self._jobs)

    def __bool__(self) -> bool:
        return bool(self._jobs)

    @property
    def jobs(self) -> List[RenderJob]:
        return list(self._jobs)

    def add(self, job: RenderJob) -> RenderJob:
        job.status = JobStatus.QUEUED
        job.refresh_output_path()
        self._jobs.append(job)
        self._reindex()
        return job

    def remove(self, job_id: str) -> bool:
        before = len(self._jobs)
        self._jobs = [j for j in self._jobs if j.id != job_id]
        if len(self._jobs) < before:
            self._reindex()
            return True
        return False

    def clear(self) -> None:
        self._jobs.clear()

    def get(self, job_id: str) -> Optional[RenderJob]:
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None

    def move(self, from_index: int, to_index: int) -> bool:
        if from_index < 0 or from_index >= len(self._jobs):
            return False
        if to_index < 0 or to_index >= len(self._jobs):
            return False
        if from_index == to_index:
            return True
        job = self._jobs.pop(from_index)
        if from_index < to_index:
            to_index -= 1
        self._jobs.insert(to_index, job)
        self._reindex()
        return True

    def next_queued(self) -> Optional[RenderJob]:
        for job in self._jobs:
            if job.status == JobStatus.QUEUED:
                return job
        return None

    def pending_count(self) -> int:
        return sum(1 for j in self._jobs if j.status == JobStatus.QUEUED)

    def contains_clip(self, clip_path: str) -> bool:
        norm = os.path.normpath(clip_path)
        return any(os.path.normpath(j.clip_path) == norm for j in self._jobs)

    def find_by_clip_path(self, clip_path: str) -> Optional[RenderJob]:
        norm = os.path.normpath(clip_path)
        for job in self._jobs:
            if os.path.normpath(job.clip_path) == norm:
                return job
        return None

    def index_of(self, job_id: str) -> int:
        for i, job in enumerate(self._jobs):
            if job.id == job_id:
                return i
        return -1

    def reorder(self, source_id: str, target_id: str) -> bool:
        """Move a queued job before ``target_id``."""
        src_idx = self.index_of(source_id)
        tgt_idx = self.index_of(target_id)
        if src_idx < 0 or tgt_idx < 0 or src_idx == tgt_idx:
            return False
        src = self._jobs[src_idx]
        if src.status != JobStatus.QUEUED:
            return False
        tgt = self._jobs[tgt_idx]
        if tgt.status != JobStatus.QUEUED:
            return False
        return self.move(src_idx, tgt_idx)

    def reorder_after(self, source_id: str, after_id: str) -> bool:
        """Move a queued job to sit directly after ``after_id``."""
        src_idx = self.index_of(source_id)
        after_idx = self.index_of(after_id)
        if src_idx < 0 or after_idx < 0 or src_idx == after_idx:
            return False
        src = self._jobs[src_idx]
        if src.status != JobStatus.QUEUED:
            return False
        after = self._jobs[after_idx]
        if after.status != JobStatus.QUEUED:
            return False
        job = self._jobs.pop(src_idx)
        if src_idx < after_idx:
            after_idx -= 1
        self._jobs.insert(after_idx + 1, job)
        self._reindex()
        return True

    def to_json_list(self) -> List[Dict[str, Any]]:
        return [job_to_dict(j) for j in self._jobs]

    @classmethod
    def from_json_list(cls, data: List[Dict[str, Any]]) -> "RenderQueue":
        q = cls()
        for item in data or []:
            job = job_from_dict(item)
            if job and os.path.isdir(job.clip_path):
                q._jobs.append(job)
        q._reindex()
        return q

    def _reindex(self) -> None:
        for i, job in enumerate(self._jobs, start=1):
            job.queue_index = i


def settings_to_dict(s: RenderJobSettings) -> Dict[str, Any]:
    return asdict(s)


def settings_from_dict(data: Dict[str, Any]) -> RenderJobSettings:
    fields = asdict(RenderJobSettings())
    for key, value in (data or {}).items():
        if key in fields:
            fields[key] = value
    return RenderJobSettings(**fields)


def job_to_dict(job: RenderJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "clip_path": job.clip_path,
        "game_name": job.game_name,
        "clip_date": job.clip_date,
        "clip_time": job.clip_time,
        "game_icon_path": job.game_icon_path,
        "settings": settings_to_dict(job.settings),
        "status": job.status.value,
        "queue_index": job.queue_index,
        "output_file": job.output_file,
        "error_message": job.error_message,
    }


def job_from_dict(data: Dict[str, Any]) -> Optional[RenderJob]:
    if not data or not data.get("clip_path"):
        return None
    try:
        status = JobStatus(data.get("status", JobStatus.QUEUED.value))
    except ValueError:
        status = JobStatus.QUEUED
    settings = settings_from_dict(data.get("settings") or {})
    return RenderJob(
        clip_path=data["clip_path"],
        game_name=data.get("game_name", ""),
        clip_date=data.get("clip_date", ""),
        clip_time=data.get("clip_time", ""),
        game_icon_path=data.get("game_icon_path", ""),
        settings=settings,
        id=data.get("id") or uuid.uuid4().hex,
        status=status,
        queue_index=int(data.get("queue_index", 0)),
        output_file=data.get("output_file", ""),
        error_message=data.get("error_message", ""),
    )


def save_queue_to_file(path: str, queue: RenderQueue) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(queue.to_json_list(), f, indent=2)


def load_queue_from_file(path: str) -> RenderQueue:
    if not os.path.isfile(path):
        return RenderQueue()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return RenderQueue.from_json_list(data if isinstance(data, list) else [])
    except (OSError, json.JSONDecodeError, TypeError):
        return RenderQueue()
