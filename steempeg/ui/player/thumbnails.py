"""Background worker threads that produce video thumbnails.

PreviewSniperWorker decodes single DASH chunks with PyAV on demand to feed the
timeline's hover preview, emitting each frame as a QPixmap. ThumbnailBatchThread
shells out to ffmpeg once per clip to render the full strip of timeline thumbnails.
"""
import glob
import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

import av

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage, QPixmap

_log = logging.getLogger(__name__)

_SNIPER_CACHE_MAX = 48
# Full-strip batch thumbs are only worth generating for the first N seconds of a clip.
# Longer clips rely on on-demand sniper hover frames instead of a multi-hour ffmpeg job.
MAX_BATCH_SEC = 600


def _ensure_thumb_dir(path: str) -> None:
    """Create a batch thumbnail folder; recover if a same-named file exists (WinError 183)."""
    if os.path.isdir(path):
        return
    if os.path.isfile(path) or os.path.islink(path):
        try:
            os.remove(path)
        except OSError:
            shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


class PreviewSniperWorker(QThread):
    preview_ready = Signal(int, QPixmap)

    def __init__(self):
        super().__init__()
        self.video_path = ""
        self.target_sec = -1
        self.cache = {}
        self.interval = 3

        self._is_killed = False
        self._in_flight_sec = -1
        self._cache_order: list[int] = []
        self._fail_until: dict[int, float] = {}
        self._decode_gen = 0

        # --- Manifest variables ---
        self.base_dir = ""
        self.init_filename = ""
        self.chunk_template = ""
        self.chunk_duration_sec = 3.0
        self.start_number = 1
        self.rep_id = "1"

    def kill_worker(self):
        if self.cache or self._in_flight_sec >= 0:
            _log.info(
                "Sniper stopped (%s): cache=%d entries",
                os.path.basename(self.video_path or ""),
                len(self.cache),
            )
        self._is_killed = True
        self.cache.clear()
        self._cache_order.clear()
        self._fail_until.clear()
        self.target_sec = -1
        self._in_flight_sec = -1
        self._decode_gen += 1
        self.base_dir = ""
        self.init_filename = ""
        self.chunk_template = ""
        if self.isRunning():
            if not self.wait(800):
                self.terminate()
                self.wait(200)

    def _dash_manifest_ready(self) -> bool:
        return bool(
            self.base_dir
            and self.init_filename
            and self.chunk_template
            and os.path.isdir(self.base_dir)
        )

    @staticmethod
    def _is_usable_media_file(path: str) -> bool:
        if not path:
            return False
        norm = os.path.normpath(path)
        if norm in (".", ".."):
            return False
        return os.path.isfile(norm)

    @staticmethod
    def _norm_media_path(path: str) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.normpath(path)).replace("\\", "/")

    def _is_dash_manifest(self, path: str) -> bool:
        return path.lower().endswith(".mpd")

    def _remember_cache(self, sec: int, pixmap: QPixmap) -> None:
        if sec in self.cache:
            self._cache_order.remove(sec)
        elif len(self._cache_order) >= _SNIPER_CACHE_MAX:
            oldest = self._cache_order.pop(0)
            self.cache.pop(oldest, None)
        self.cache[sec] = pixmap
        self._cache_order.append(sec)

    def _decode_frame_ffmpeg(self, media_path: str, sec: int):
        """Single-frame extract for plain media files (rendered mp4, etc.)."""
        if not media_path or not os.path.isfile(media_path):
            _log.debug("Sniper ffmpeg skip sec=%s: missing file %s", sec, media_path)
            return None
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(max(0, sec)),
            "-i", media_path,
            "-frames:v", "1",
            "-vf", "scale=160:90",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-",
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, creationflags=creationflags, timeout=8,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if proc.returncode != 0 or not proc.stdout:
                _log.info(
                    "Sniper ffmpeg miss sec=%s (%.0fms) file=%s rc=%s",
                    sec, elapsed_ms, os.path.basename(media_path), proc.returncode,
                )
                return None
            qimg = QImage.fromData(proc.stdout)
            if qimg.isNull():
                _log.info("Sniper ffmpeg miss sec=%s (%.0fms): empty image", sec, elapsed_ms)
                return None
            _log.info(
                "Sniper ffmpeg ok sec=%s (%.0fms) file=%s",
                sec, elapsed_ms, os.path.basename(media_path),
            )
            return QPixmap.fromImage(qimg)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            _log.info(
                "Sniper ffmpeg error sec=%s (%.0fms) file=%s: %s",
                sec, elapsed_ms, os.path.basename(media_path), exc,
            )
            return None

    def parse_mpd(self, mpd_path):
        self.base_dir = os.path.dirname(mpd_path)
        try:
            tree = ET.parse(mpd_path)
            root = tree.getroot()

            for adapt_set in root.iter():
                if 'AdaptationSet' in adapt_set.tag:
                    is_video = False
                    if 'video' in adapt_set.attrib.get('mimeType', ''):
                        is_video = True
                    else:
                        for rep in adapt_set.iter():
                            if 'Representation' in rep.tag and 'video' in rep.attrib.get('mimeType', ''):
                                is_video = True
                                break

                    if is_video:
                        for elem in adapt_set.iter():
                            if 'Representation' in elem.tag:
                                self.rep_id = elem.attrib.get('id', '1')
                            if 'SegmentTemplate' in elem.tag:
                                self.init_filename = elem.attrib.get('initialization', 'init.mp4')
                                self.chunk_template = elem.attrib.get('media', 'chunk_$Number$.m4s')
                                timescale = float(elem.attrib.get('timescale', 1000))
                                duration = float(elem.attrib.get('duration', 3000))
                                self.chunk_duration_sec = duration / timescale
                                self.start_number = int(elem.attrib.get('startNumber', 1))
                        break
            _log.debug(
                "Sniper parsed MPD chunk=%.2fs rep=%s dir=%s",
                self.chunk_duration_sec, self.rep_id, self.base_dir,
            )
        except Exception as exc:
            _log.warning("Sniper MPD parse failed for %s: %s", mpd_path, exc)

    def request_frame(self, media_path, hover_sec):
        self._is_killed = False

        target_sec = round(hover_sec / self.interval) * self.interval
        norm_path = self._norm_media_path(media_path)

        if self._norm_media_path(self.video_path) != norm_path:
            self.video_path = media_path
            self.cache.clear()
            self._cache_order.clear()
            self._fail_until.clear()
            self._in_flight_sec = -1
            self._decode_gen += 1
            _log.info("Sniper opened %s", os.path.basename(media_path or ""))
            if self._is_dash_manifest(media_path):
                self.parse_mpd(media_path)
            else:
                self.base_dir = ""
                self.init_filename = ""
                self.chunk_template = ""

        if target_sec in self.cache:
            self.preview_ready.emit(target_sec, self.cache[target_sec])
            return

        if self.target_sec != target_sec:
            self._fail_until.pop(target_sec, None)

        self.target_sec = target_sec
        if not self.isRunning():
            self._is_killed = False
            self.start()

    def _decode_dash_frame(self, sec: int):
        if not self._dash_manifest_ready():
            _log.debug("Sniper dash manifest not ready, ffmpeg fallback sec=%s", sec)
            return self._decode_frame_ffmpeg(self.video_path, sec)

        chunk_offset = int(sec // self.chunk_duration_sec)
        chunk_num = self.start_number + chunk_offset

        real_init = self.init_filename.replace('$RepresentationID$', self.rep_id)
        real_chunk = self.chunk_template.replace('$RepresentationID$', self.rep_id)

        match = re.search(r'\$Number([^$]*)\$', real_chunk)
        if match:
            format_spec = match.group(1)
            num_str = format_spec % chunk_num if format_spec else str(chunk_num)
            real_chunk = real_chunk[:match.start()] + num_str + real_chunk[match.end():]
        else:
            real_chunk = real_chunk.replace('$Number$', str(chunk_num))

        init_path = os.path.normpath(os.path.join(self.base_dir, real_init))
        chunk_path = os.path.normpath(os.path.join(self.base_dir, real_chunk))

        if not self._is_usable_media_file(init_path) or not self._is_usable_media_file(chunk_path):
            _log.debug(
                "Sniper PyAV miss sec=%s chunk=%s (init=%s chunk=%s missing)",
                sec, chunk_num, os.path.basename(init_path), os.path.basename(chunk_path),
            )
            return self._decode_frame_ffmpeg(self.video_path, sec)

        gen = self._decode_gen
        t0 = time.perf_counter()
        try:
            with open(init_path, 'rb') as f:
                init_bytes = f.read()
            with open(chunk_path, 'rb') as f:
                chunk_bytes = f.read()

            if self._is_killed or gen != self._decode_gen:
                return None

            ram_buffer = io.BytesIO(init_bytes + chunk_bytes)
            container = av.open(ram_buffer)

            pixmap = None
            stream = container.streams.video[0]
            for frame in container.decode(stream):
                if self._is_killed or gen != self._decode_gen:
                    break
                img = frame.to_image()
                img = img.resize((160, 90))
                img_data = img.convert("RGBA").tobytes("raw", "RGBA")
                qimg = QImage(img_data, img.width, img.height, QImage.Format_RGBA8888)
                pixmap = QPixmap.fromImage(qimg)
                break

            container.close()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if pixmap is not None and not pixmap.isNull():
                _log.info(
                    "Sniper PyAV ok sec=%s chunk=%s (%.0fms)",
                    sec, chunk_num, elapsed_ms,
                )
                return pixmap
            _log.info(
                "Sniper PyAV miss sec=%s chunk=%s (%.0fms, no frame)",
                sec, chunk_num, elapsed_ms,
            )
            return self._decode_frame_ffmpeg(self.video_path, sec)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            _log.info(
                "Sniper PyAV error sec=%s chunk=%s (%.0fms): %s — trying ffmpeg",
                sec, chunk_num, elapsed_ms, exc,
            )
            return self._decode_frame_ffmpeg(self.video_path, sec)

    def _run_on_demand(self, decode_fn):
        """Decode only the bucket under the cursor — never background prefill."""
        while not self._is_killed:
            sec = self.target_sec
            if sec < 0:
                self.msleep(60)
                continue

            if sec in self.cache:
                self.msleep(60)
                continue

            retry_at = self._fail_until.get(sec, 0.0)
            if retry_at and time.monotonic() < retry_at:
                self.msleep(60)
                continue

            if self._in_flight_sec == sec:
                self.msleep(40)
                continue

            self._in_flight_sec = sec
            pixmap = decode_fn(sec)
            self._in_flight_sec = -1

            if self._is_killed or self.target_sec != sec:
                continue

            if pixmap is not None and not pixmap.isNull():
                self._fail_until.pop(sec, None)
                self._remember_cache(sec, pixmap)
                self.preview_ready.emit(sec, pixmap)
            else:
                self._fail_until[sec] = time.monotonic() + 2.0
                self.msleep(200)

    def run(self):
        if self._is_dash_manifest(self.video_path):
            self._run_on_demand(self._decode_dash_frame)
        else:
            self._run_on_demand(lambda sec: self._decode_frame_ffmpeg(self.video_path, sec))


class ThumbnailBatchThread(QThread):
    """ Generates all thumbnails in the background ONCE, using GPU. """
    finished_generation = Signal(str)

    def __init__(self, mpd_path, duration_sec, interval=3, parent=None):
        super().__init__(parent)
        self.mpd_path = mpd_path
        self.duration_sec = duration_sec
        self.interval = interval
        self.process = None
        self._cancelled = False

        path_hash = hashlib.md5(mpd_path.encode('utf-8')).hexdigest()[:10]
        self.thumb_dir = os.path.join(tempfile.gettempdir(), f"steempeg_batch_{path_hash}_{self.interval}s")
        _ensure_thumb_dir(self.thumb_dir)

    def stop(self):
        """Stop ffmpeg and end the batch thread without leaving a zombie process."""
        self._cancelled = True
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass
            self.process = None
        if self.isRunning():
            if not self.wait(3000):
                self.terminate()
                self.wait(500)

    def _emit_if_current(self) -> None:
        if self._cancelled:
            return
        self.finished_generation.emit(self.thumb_dir)

    def run(self):
        if self._cancelled:
            return
        if self.duration_sec <= 0 or self.duration_sec < self.interval:
            self._emit_if_current()
            return

        batch_sec = min(float(self.duration_sec), float(MAX_BATCH_SEC))
        existing_files = glob.glob(os.path.join(self.thumb_dir, "thumb_*.jpg"))
        expected_count = max(1, int(batch_sec // self.interval))

        if len(existing_files) >= expected_count * 0.9:
            _log.debug(
                "Batch thumbs cache hit: %d/%d for %s",
                len(existing_files), expected_count, self.mpd_path,
            )
            self._emit_if_current()
            return

        shutil.rmtree(self.thumb_dir, ignore_errors=True)
        _ensure_thumb_dir(self.thumb_dir)

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-hwaccel", "auto",
            "-threads", "2",
            "-t", str(batch_sec),
            "-i", self.mpd_path,
            "-vf", f"fps=1/{self.interval}",
            "-q:v", "7",
            "-s", "160x90",
            os.path.join(self.thumb_dir, "thumb_%04d.jpg")
        ]

        if self.duration_sec > MAX_BATCH_SEC:
            _log.info(
                "Batch thumbs capped to %ds (clip is %.0fs): %s",
                int(batch_sec), self.duration_sec, self.mpd_path,
            )
        else:
            _log.info(
                "Batch thumbs start: %s (~%d frames, interval=%ds)",
                self.mpd_path, expected_count, self.interval,
            )
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        t0 = time.perf_counter()
        self.process = subprocess.Popen(cmd, creationflags=creationflags)
        self.process.wait()
        elapsed_s = time.perf_counter() - t0
        if self._cancelled:
            _log.debug("Batch thumbs cancelled: %s", self.mpd_path)
            return
        produced = len(glob.glob(os.path.join(self.thumb_dir, "thumb_*.jpg")))
        _log.info(
            "Batch thumbs done: %s produced=%d (%.1fs)",
            self.mpd_path, produced, elapsed_s,
        )

        self._emit_if_current()
