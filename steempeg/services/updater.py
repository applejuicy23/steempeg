"""Background worker that downloads an application update and reports progress.

Receives the download URL, target directory and asset name through its constructor
and emits progress and completion signals; it holds no reference to the application.
"""
from __future__ import annotations

import hashlib
import os
import time
import zipfile

import requests

from PySide6.QtCore import QThread, Signal


_RETRYABLE_STATUS = {403, 408, 425, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 5
_HEADERS = {"User-Agent": "Steempeg-Updater"}


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

    def cancel(self):
        self.is_cancelled = True

    def _cleanup_tmp(self) -> None:
        try:
            if os.path.exists(self.dest_path):
                os.remove(self.dest_path)
        except OSError:
            pass

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
        )

    def run(self):
        last_error = "Download failed."
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            if self.is_cancelled:
                self._cleanup_tmp()
                self.finished_signal.emit(False, "", "")
                return

            self._cleanup_tmp()
            try:
                if attempt > 1:
                    wait_s = min(16, 2 ** (attempt - 1))
                    self.progress_signal.emit(
                        0,
                        f"Connection interrupted — retrying ({attempt}/{_MAX_ATTEMPTS}) "
                        f"in {wait_s}s…",
                    )
                    for _ in range(wait_s * 10):
                        if self.is_cancelled:
                            self._cleanup_tmp()
                            self.finished_signal.emit(False, "", "")
                            return
                        time.sleep(0.1)

                response = requests.get(
                    self.url,
                    stream=True,
                    timeout=(10, 60),
                    headers=_HEADERS,
                )
                if response.status_code in _RETRYABLE_STATUS:
                    response.close()
                    last_error = f"HTTP {response.status_code} while downloading."
                    if attempt < _MAX_ATTEMPTS:
                        continue
                    self._cleanup_tmp()
                    self.finished_signal.emit(False, last_error, "")
                    return

                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0) or 0)
                if self.expected_size and total_size <= 0:
                    total_size = self.expected_size

                downloaded = 0
                start_time = time.time()

                with open(self.dest_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if self.is_cancelled:
                            break
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            elapsed = time.time() - start_time
                            speed_mbps = (downloaded / 1024 / 1024) / elapsed if elapsed > 0 else 0
                            down_mb = downloaded / 1024 / 1024
                            total_mb = total_size / 1024 / 1024
                            label_text = (
                                f"Downloading update...\n"
                                f"{down_mb:.1f} MB / {total_mb:.1f} MB ({speed_mbps:.1f} MB/s)"
                            )
                            self.progress_signal.emit(percent, label_text)

                if self.is_cancelled:
                    self._cleanup_tmp()
                    self.finished_signal.emit(False, "", "")
                    return

                error = self._validate_download(downloaded, total_size)
                if error:
                    last_error = error
                    self._cleanup_tmp()
                    if attempt < _MAX_ATTEMPTS and "checksum" not in error.lower():
                        continue
                    self.finished_signal.emit(False, last_error, "")
                    return

                self.finished_signal.emit(True, self.dest_path, self.asset_name)
                return

            except Exception as exc:
                last_error = str(exc) or "Download failed."
                status = getattr(getattr(exc, "response", None), "status_code", None)
                self._cleanup_tmp()
                if attempt < _MAX_ATTEMPTS and self._is_retryable(exc, status):
                    continue
                self.finished_signal.emit(False, last_error, "")
                return

        self._cleanup_tmp()
        self.finished_signal.emit(False, last_error, "")
