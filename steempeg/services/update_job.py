"""Update handoff job written by the main app and read by --update-handler."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, fields


@dataclass
class UpdateJob:
    url: str
    asset_name: str
    from_version: str
    target_version: str
    keep_backup: bool
    exe_dir: str
    chrome_theme: str = "exp2"
    expected_size: int | None = None
    expected_sha256: str | None = None

    @property
    def backup_folder_name(self) -> str:
        return f"old_version_v{self.from_version}" if self.keep_backup else "None"


def job_file_path(exe_dir: str) -> str:
    cache = os.path.join(exe_dir, "cache")
    os.makedirs(cache, exist_ok=True)
    return os.path.join(cache, "update_job.json")


def save_update_job(job: UpdateJob) -> str:
    path = job_file_path(job.exe_dir)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(asdict(job), handle, indent=2)
    return path


def load_update_job(path: str) -> UpdateJob:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    # Older jobs lack size/hash fields — keep defaults.
    known = {f.name for f in fields(UpdateJob)}
    filtered = {k: v for k, v in data.items() if k in known}
    return UpdateJob(**filtered)


def spawn_update_handler(job: UpdateJob) -> None:
    """Start a detached --update-handler process (survives main app exit)."""
    job_path = save_update_job(job)
    env = os.environ.copy()
    env.pop("_MEIPASS2", None)
    env.pop("_MEIPASS", None)
    subprocess.Popen(
        [sys.executable, "--update-handler", "--job", job_path],
        cwd=job.exe_dir,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        close_fds=False,
        env=env,
    )
