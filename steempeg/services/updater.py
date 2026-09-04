"""Background worker that downloads an application update and reports progress.

Receives the download URL, target directory and asset name through its constructor
and emits progress and completion signals; it holds no reference to the application.

Supports HTTP Range resume: a partial ``{asset}.tmp`` is kept across retryable
network failures and continued from disk rather than re-downloaded from byte 0.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import zipfile

import requests

from PySide6.QtCore import QThread, Signal


_log = logging.getLogger(__name__)

_RETRYABLE_STATUS = {403, 408, 425, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 5
_HEADERS = {"User-Agent": "Steempeg-Updater"}
_CONTENT_RANGE_RE = re.compile(
    r"bytes\s+(\d+)-(\d+)/(\d+|\*)",
    re.IGNORECASE,
)


class UpdateDownloadThread(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool, str, str)

    def __init__(
        self,
        url,
        save_dir,
        asset_name,
        *,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ):
        super().__init__()
        self.url = url
        self.save_dir = save_dir
        self.asset_name = asset_name
        self.expected_size = int(expected_size) if expected_size else None
        digest = (expected_sha256 or "").strip().lower()
        if digest.startswith("sha256:"):
            digest = digest.split(":", 1)[1]
        self.expected_sha256 = digest or None
        self.is_cancelled = False
        # Download the file with the .tmp appendix to avoid breaking anything
        self.dest_path = os.path.join(save_dir, f"{asset_name}.tmp")
        self._sidecar_path = os.path.join(save_dir, "cache", "update_download.json")

    def cancel(self):
        self.is_cancelled = True

    def _cleanup_tmp(self) -> None:
        try:
            if os.path.exists(self.dest_path):
                os.remove(self.dest_path)
        except OSError:
            pass
        self._clear_sidecar()

    def _clear_sidecar(self) -> None:
        try:
            if os.path.isfile(self._sidecar_path):
                os.remove(self._sidecar_path)
        except OSError:
            pass

    def _sidecar_payload(self) -> dict:
        return {
            "url": self.url,
            "asset_name": self.asset_name,
            "expected_size": self.expected_size,
            "expected_sha256": self.expected_sha256,
        }

    def _write_sidecar(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._sidecar_path), exist_ok=True)
            with open(self._sidecar_path, "w", encoding="utf-8") as handle:
                json.dump(self._sidecar_payload(), handle, indent=2)
        except OSError as exc:
            _log.debug("update download sidecar write skipped: %s", exc)

    def _partial_bytes(self) -> int:
        """Return resumable on-disk bytes, or 0 if partial must be discarded."""
        if not os.path.isfile(self.dest_path):
            return 0
        try:
            size = int(os.path.getsize(self.dest_path))
        except OSError:
            return 0
        if size <= 0:
            self._cleanup_tmp()
            return 0
        if self.expected_size and size > self.expected_size:
            _log.info("Discarding oversized update partial (%d > %d)", size, self.expected_size)
            self._cleanup_tmp()
            return 0
        if os.path.isfile(self._sidecar_path):
            try:
                with open(self._sidecar_path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                data = None
            if not isinstance(data, dict):
                _log.info("Discarding update partial (bad sidecar)")
                self._cleanup_tmp()
                return 0
            if data.get("url") != self.url or data.get("asset_name") != self.asset_name:
                _log.info("Discarding update partial (asset/url mismatch)")
                self._cleanup_tmp()
                return 0
            side_size = data.get("expected_size")
            if self.expected_size and side_size and int(side_size) != self.expected_size:
                self._cleanup_tmp()
                return 0
            side_sha = (data.get("expected_sha256") or "").strip().lower()
            if self.expected_sha256 and side_sha and side_sha != self.expected_sha256:
                self._cleanup_tmp()
                return 0
        else:
            # Same-asset .tmp without sidecar (crash mid-write) — adopt and refresh sidecar.
            _log.info("Adopting update partial without sidecar (%d bytes)", size)
            self._write_sidecar()
        return size

    def _on_disk_size(self) -> int:
        try:
            if os.path.isfile(self.dest_path):
                return int(os.path.getsize(self.dest_path))
        except OSError:
            pass
        return 0

    @staticmethod
    def _parse_content_range(header: str | None) -> tuple[int, int] | None:
        """Return (start, total) from a Content-Range header, or None."""
        if not header:
            return None
        match = _CONTENT_RANGE_RE.search(header.strip())
        if not match:
            return None
        start = int(match.group(1))
        total_raw = match.group(3)
        if total_raw == "*":
            return None
        return start, int(total_raw)

    def _validate_download(self, downloaded: int, content_length: int) -> str | None:
        """Return an error message if the .tmp is incomplete or corrupt."""
        if self.is_cancelled:
            return "cancelled"
        if downloaded <= 0 or not os.path.isfile(self.dest_path):
            return "Download produced an empty file."
        on_disk = os.path.getsize(self.dest_path)
        if content_length > 0 and downloaded != content_length:
            return (
                f"Incomplete download ({downloaded} / {content_length} bytes). "
                "Connection may have dropped."
            )
        if content_length > 0 and on_disk != content_length:
            return f"Downloaded size mismatch on disk ({on_disk} / {content_length} bytes)."
        if self.expected_size and on_disk != self.expected_size:
            return (
                f"Zip size mismatch (got {on_disk}, expected {self.expected_size}). "
                "Download may be truncated."
            )
        if self.expected_sha256:
            h = hashlib.sha256()
            with open(self.dest_path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    h.update(chunk)
            digest = h.hexdigest()
            if digest != self.expected_sha256:
                return "Zip checksum mismatch — file is corrupt or incomplete."
        try:
            with zipfile.ZipFile(self.dest_path, "r") as archive:
                bad = archive.testzip()
                if bad is not None:
                    return f"Zip archive is corrupt (bad member: {bad})."
        except zipfile.BadZipFile:
            return "Downloaded file is not a valid zip archive."
        except Exception as exc:
            return f"Could not validate zip: {exc}"
        return None

    def _is_retryable(self, exc: BaseException, status: int | None = None) -> bool:
        if self.is_cancelled:
            return False
        if status is not None and status in _RETRYABLE_STATUS:
            return True
        if isinstance(exc, requests.HTTPError):
            code = getattr(getattr(exc, "response", None), "status_code", None)
            return code in _RETRYABLE_STATUS
        return isinstance(
            exc,
            (
                requests.ConnectionError,
                requests.Timeout,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ContentDecodingError,
                ConnectionResetError,
                TimeoutError,
                OSError,
            ),
        ) or exc.__class__.__name__ in {
            "IncompleteRead",
            "ProtocolError",
            "ReadTimeoutError",
        }

    def _should_keep_partial(self, error: str | None) -> bool:
        if not error:
            return False
        low = error.lower()
        if "checksum" in low or "corrupt" in low or "not a valid zip" in low:
            return False
        return (
            "incomplete" in low
            or "truncated" in low
            or "size mismatch" in low
            or "connection may have dropped" in low
        )

    def _emit_progress(self, downloaded: int, total_size: int, start_time: float) -> None:
        if total_size <= 0:
            return
        percent = int(min(100, (downloaded / total_size) * 100))
        elapsed = time.time() - start_time
        speed_mbps = (downloaded / 1024 / 1024) / elapsed if elapsed > 0 else 0
        down_mb = downloaded / 1024 / 1024
        total_mb = total_size / 1024 / 1024
        label_text = (
            f"Downloading update...\n"
            f"{down_mb:.1f} MB / {total_mb:.1f} MB ({speed_mbps:.1f} MB/s)"
        )
        self.progress_signal.emit(percent, label_text)

    def run(self):
        last_error = "Download failed."
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            if self.is_cancelled:
                self._cleanup_tmp()
                self.finished_signal.emit(False, "", "")
                return

            existing = self._partial_bytes()
            try:
                if attempt > 1:
                    wait_s = min(16, 2 ** (attempt - 1))
                    resume_note = (
                        f"resuming from {existing / 1024 / 1024:.1f} MB — "
                        if existing > 0
                        else ""
                    )
                    pct = 0
                    if existing > 0 and self.expected_size:
                        pct = int(min(99, (existing / self.expected_size) * 100))
                    self.progress_signal.emit(
                        pct,
                        f"Connection interrupted — {resume_note}"
                        f"retrying ({attempt}/{_MAX_ATTEMPTS}) in {wait_s}s…",
                    )
                    for _ in range(wait_s * 10):
                        if self.is_cancelled:
                            self._cleanup_tmp()
                            self.finished_signal.emit(False, "", "")
                            return
                        time.sleep(0.1)
                    # Re-read after wait — another process shouldn't touch it, but be safe.
                    existing = self._partial_bytes()

                headers = dict(_HEADERS)
                if existing > 0:
                    headers["Range"] = f"bytes={existing}-"
                    _log.info(
                        "Resuming update download from byte %d (%s)",
                        existing,
                        self.asset_name,
                    )

                response = requests.get(
                    self.url,
                    stream=True,
                    timeout=(10, 60),
                    headers=headers,
                )
                if response.status_code in _RETRYABLE_STATUS:
                    response.close()
                    last_error = f"HTTP {response.status_code} while downloading."
                    if attempt < _MAX_ATTEMPTS:
                        continue
                    # Keep partial so a later Update attempt can Range-resume.
                    self.finished_signal.emit(False, last_error, "")
                    return

                if response.status_code == 416:
                    response.close()
                    # Range unsatisfiable — try validating what we already have.
                    if existing > 0 and self.expected_size and existing == self.expected_size:
                        error = self._validate_download(existing, self.expected_size)
                        if error is None:
                            self._clear_sidecar()
                            self.finished_signal.emit(True, self.dest_path, self.asset_name)
                            return
                        last_error = error
                        self._cleanup_tmp()
                        existing = 0
                        if attempt < _MAX_ATTEMPTS:
                            continue
                        self.finished_signal.emit(False, last_error, "")
                        return
                    self._cleanup_tmp()
                    existing = 0
                    last_error = "Server rejected resume range; restarting download."
                    if attempt < _MAX_ATTEMPTS:
                        continue
                    self.finished_signal.emit(False, last_error, "")
                    return

                response.raise_for_status()

                resume = response.status_code == 206 and existing > 0
                if existing > 0 and not resume:
                    # Server ignored Range and sent a full body — start over.
                    _log.info("Server returned full body; discarding partial and rewriting")
                    self._cleanup_tmp()
                    existing = 0

                total_size = 0
                if resume:
                    parsed = self._parse_content_range(response.headers.get("Content-Range"))
                    if parsed is not None:
                        range_start, total_size = parsed
                        if range_start != existing:
                            response.close()
                            self._cleanup_tmp()
                            last_error = (
                                f"Resume offset mismatch (have {existing}, "
                                f"server started at {range_start})."
                            )
                            if attempt < _MAX_ATTEMPTS:
                                continue
                            self.finished_signal.emit(False, last_error, "")
                            return
                    if total_size <= 0:
                        remaining = int(response.headers.get("content-length", 0) or 0)
                        if remaining > 0:
                            total_size = existing + remaining
                else:
                    total_size = int(response.headers.get("content-length", 0) or 0)

                if self.expected_size and total_size <= 0:
                    total_size = self.expected_size
                elif self.expected_size and total_size > 0 and total_size != self.expected_size:
                    # Prefer the GitHub release metadata size when headers disagree.
                    total_size = self.expected_size

                self._write_sidecar()
                downloaded = existing
                start_time = time.time()
                mode = "ab" if resume else "wb"

                # Use raw.read (not iter_content): on IncompleteRead, iter_content can
                # raise without yielding already-buffered bytes — killing resume.
                with open(self.dest_path, mode) as handle:
                    while True:
                        if self.is_cancelled:
                            break
                        try:
                            chunk = response.raw.read(256 * 1024)
                        except Exception:
                            handle.flush()
                            raise
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        self._emit_progress(downloaded, total_size, start_time)
                    handle.flush()

                if self.is_cancelled:
                    # User aborted this install — drop the partial.
                    self._cleanup_tmp()
                    self.finished_signal.emit(False, "", "")
                    return

                error = self._validate_download(downloaded, total_size)
                if error:
                    last_error = error
                    if self._should_keep_partial(error):
                        _log.info("Keeping partial update download for resume: %s", error)
                        if attempt < _MAX_ATTEMPTS:
                            continue
                        self.finished_signal.emit(False, last_error, "")
                        return
                    self._cleanup_tmp()
                    if attempt < _MAX_ATTEMPTS and "checksum" not in error.lower():
                        continue
                    self.finished_signal.emit(False, last_error, "")
                    return

                self._clear_sidecar()
                self.finished_signal.emit(True, self.dest_path, self.asset_name)
                return

            except Exception as exc:
                last_error = str(exc) or "Download failed."
                status = getattr(getattr(exc, "response", None), "status_code", None)
                # Keep .tmp on retryable network errors so the next attempt can Range-resume.
                if self._is_retryable(exc, status):
                    _log.info(
                        "Update download interrupted (%s); keeping %d bytes for resume",
                        last_error,
                        self._on_disk_size(),
                    )
                    if attempt < _MAX_ATTEMPTS:
                        continue
                    self.finished_signal.emit(False, last_error, "")
                    return
                self._cleanup_tmp()
                self.finished_signal.emit(False, last_error, "")
                return

        # Exhausted attempts on a keepable network/incomplete failure — leave .tmp.
        self.finished_signal.emit(False, last_error, "")
