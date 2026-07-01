"""Shared constants and helpers for render-queue list/grid cards."""
from steempeg.render.queue import JobStatus, RenderJob

_FONT = "font-family: 'Segoe UI', Arial, sans-serif;"
_MIME_JOB_ID = "application/x-steempeg-queue-job"

_QUEUE_MENU_STYLE = """
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
    QMenu::item:disabled {
        color: #777777;
    }
    QMenu::separator {
        height: 1px;
        background: #444444;
        margin: 4px 10px;
    }
"""


def job_accepts_drop(job: RenderJob) -> bool:
    return job.status == JobStatus.QUEUED


def job_can_remove(job: RenderJob) -> bool:
    return job.status != JobStatus.RENDERING
