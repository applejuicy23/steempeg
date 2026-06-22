"""Render queue data model — pure Python, no Qt.

Each RenderJob stores a snapshot of user-chosen export settings that can be edited
per queue item before the batch runner starts (stage 2+ UI).
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, List, Optional


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

    def refresh_output_path(self) -> str:
        """Recompute a collision-safe output path from current settings."""
        s = self.settings
        ext = ".mp3" if (s.audio_only and s.audio_format == "MP3") else (
            ".aac" if s.audio_only else ".mp4"
        )
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


def compute_unique_output_path(save_dir: str, base_filename: str, ext: str) -> str:
    base = (base_filename or "rendered").strip()
    for suffix in (".mp4", ".mp3", ".aac"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
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

    def _reindex(self) -> None:
        for i, job in enumerate(self._jobs, start=1):
            job.queue_index = i
