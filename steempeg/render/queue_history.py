"""Persisted history of completed render-queue batches."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from steempeg.render.queue import JobStatus, RenderQueue, job_from_dict, job_to_dict


MAX_BATCHES = 50


@dataclass
class RenderBatchRecord:
    id: str
    started_at: str
    finished_at: str
    cancelled: bool
    jobs: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def completed_count(self) -> int:
        return sum(1 for j in self.jobs if j.get("status") == JobStatus.COMPLETED.value)

    @property
    def error_count(self) -> int:
        return sum(1 for j in self.jobs if j.get("status") == JobStatus.ERROR.value)

    @property
    def cancelled_count(self) -> int:
        return sum(1 for j in self.jobs if j.get("status") == "cancelled")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cancelled": self.cancelled,
            "jobs": self.jobs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional["RenderBatchRecord"]:
        if not data or not data.get("id"):
            return None
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            jobs = []
        return cls(
            id=str(data["id"]),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            cancelled=bool(data.get("cancelled", False)),
            jobs=jobs,
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def snapshot_queue_batch(
    queue: RenderQueue,
    *,
    started_at: str,
    cancelled: bool = False,
) -> RenderBatchRecord:
    """Capture the current queue as a history batch (queued jobs → cancelled if batch aborted)."""
    jobs: List[Dict[str, Any]] = []
    for job in queue.jobs:
        entry = job_to_dict(job)
        if cancelled and job.status == JobStatus.QUEUED:
            entry["status"] = "cancelled"
        elif cancelled and job.status == JobStatus.RENDERING:
            entry["status"] = "cancelled"
        jobs.append(entry)
    return RenderBatchRecord(
        id=uuid.uuid4().hex,
        started_at=started_at or _utc_now_iso(),
        finished_at=_utc_now_iso(),
        cancelled=cancelled,
        jobs=jobs,
    )


def load_history(path: str) -> List[RenderBatchRecord]:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    batches = data.get("batches") if isinstance(data, dict) else None
    if not isinstance(batches, list):
        return []
    out: List[RenderBatchRecord] = []
    for item in batches:
        record = RenderBatchRecord.from_dict(item)
        if record and record.jobs:
            out.append(record)
    return out


def save_history(path: str, batches: List[RenderBatchRecord]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {"batches": [b.to_dict() for b in batches[:MAX_BATCHES]]}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def append_batch(path: str, batch: RenderBatchRecord) -> List[RenderBatchRecord]:
    batches = load_history(path)
    batches.insert(0, batch)
    batches = batches[:MAX_BATCHES]
    save_history(path, batches)
    return batches


def clear_history(path: str) -> None:
    save_history(path, [])


def parse_history_job(data: Dict[str, Any]):
    """Rehydrate a job dict for display helpers (may be cancelled/skipped)."""
    status = data.get("status", JobStatus.QUEUED.value)
    if status == "cancelled":
        job = job_from_dict({**data, "status": JobStatus.QUEUED.value})
        if job:
            job.status = JobStatus.QUEUED  # type: ignore[assignment]
        return job, "cancelled"
    job = job_from_dict(data)
    return job, status
