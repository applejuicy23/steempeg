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

from steempeg.core.rendered_media import resolve_ffmpeg_exe

_log = logging.getLogger(__name__)

_SNIPER_CACHE_MAX = 160
# Full-strip batch thumbs are only worth generating for the first N seconds of a clip.
# Longer clips rely on on-demand sniper hover frames instead of a multi-hour ffmpeg job.
MAX_BATCH_SEC = 600
# Only warm ±3s neighbors after the cursor parks on a bucket (fast scrub skips this).
_NEIGHBOR_STABLE_SEC = 0.18
# After the cursor leaves the strip: keep warming L/R for this wall-clock budget,
# then fully idle and leave the strip to batch thumbs (from the start).
_BACKGROUND_WARM_WINDOW_SEC = 15.0
_BACKGROUND_WALL_BUDGET_SEC = 15.0
_BACKGROUND_MAX_FRAMES = 80
_STEAM_CHUNK_SEC = 3.0
_STEAM_VIDEO_INIT = "init-stream0.m4s"
_STEAM_VIDEO_CHUNK_TMPL = "chunk-stream0-$Number%05d$.m4s"


def preview_bucket_sec(hover_ms: float, duration_ms: float = 0, *, interval: int = 3) -> int:
    """Map a hover position to the start of its DASH chunk bucket (floor, never round up)."""
    sec = max(0, int(hover_ms // 1000))
    bucket = (sec // interval) * interval
    if duration_ms > 0:
        last_sec = max(0.0, (float(duration_ms) / 1000.0) - 0.001)
        last_bucket = int(last_sec // interval) * interval
        bucket = min(bucket, last_bucket)
    return bucket


def _kill_process_tree(proc, *, label: str = "ffmpeg") -> None:
    """Terminate a subprocess and its children."""
    from steempeg.infra.process import kill_process_tree

    kill_process_tree(proc, label=label)


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
        self._ffmpeg_proc = None
        # -1 = left, +1 = right — neighbor prefill prefers scrub direction.
        self._prefer_dir = 0
        self._stable_since = 0.0
        # Buckets below this already have batch disk thumbs — skip sniper prefill there.
        self.disk_cover_until_sec = 0
        # After hover leave, warm L/R around the leave point for a wall-clock budget.
        self._last_hover_bucket_sec = -1
        self._background_active = False
        self._background_end_time = 0.0
        self._background_queue: list[int] = []
        self._background_center = -1
        self._background_radius = 0
        self._background_max_radius = 0
        self._background_prefer_radius = 0
        self._background_done_count = 0

        # --- Manifest variables ---
        self.base_dir = ""
        self.init_filename = ""
        self.chunk_template = ""
        self.chunk_duration_sec = 3.0
        self.start_number = 1
        self.max_chunk_number = 1
        self.rep_id = "1"

    def _kill_ffmpeg_subprocess(self) -> None:
        proc = self._ffmpeg_proc
        self._ffmpeg_proc = None
        if proc is not None:
            _kill_process_tree(proc, label="sniper-ffmpeg")

    def kill_worker(self):
        if self.cache or self._in_flight_sec >= 0:
            _log.info(
                "Sniper stopped (%s): cache=%d entries",
                os.path.basename(self.video_path or ""),
                len(self.cache),
            )
        self._is_killed = True
        self._kill_ffmpeg_subprocess()
        self.cache.clear()
        self._cache_order.clear()
        self._fail_until.clear()
        self.target_sec = -1
        self._in_flight_sec = -1
        self._prefer_dir = 0
        self._stable_since = 0.0
        self.disk_cover_until_sec = 0
        self._cancel_background_warm()
        self._decode_gen += 1
        self.base_dir = ""
        self.init_filename = ""
        self.chunk_template = ""
        if self.isRunning():
            if not self.wait(800):
                self.terminate()
                self.wait(200)

    def pause_hover(self, background_window_sec: float = _BACKGROUND_WARM_WINDOW_SEC) -> None:
        """Leave the strip: keep warming ±window for a wall-clock budget, then idle.

        After the budget, sniper stops and batch thumbs own the strip again.
        """
        center = self._last_hover_bucket_sec
        self.target_sec = -1
        self._stable_since = 0.0
        self._kill_ffmpeg_subprocess()

        if center < 0:
            self._cancel_background_warm()
            return

        step = max(1, int(self.interval))
        window_steps = max(1, int(float(background_window_sec) // float(step)))
        # Prefer ±window first; if wall budget remains, keep expanding until budget/max frames.
        expand_steps = max(window_steps, min(_BACKGROUND_MAX_FRAMES // 2, 40))
        self._background_center = int(center)
        self._background_radius = 0
        self._background_max_radius = expand_steps
        self._background_prefer_radius = window_steps
        self._background_done_count = 0
        self._background_queue.clear()
        self._background_end_time = time.monotonic() + float(_BACKGROUND_WALL_BUDGET_SEC)
        self._refill_background_queue()
        self._background_active = True
        if not self.isRunning():
            self._is_killed = False
            self.start()
        _log.info(
            "Sniper background warm start center=%s window=±%.0fs budget=%.0fs",
            center,
            float(background_window_sec),
            float(_BACKGROUND_WALL_BUDGET_SEC),
        )

    def _cancel_background_warm(self) -> None:
        self._background_active = False
        self._background_end_time = 0.0
        self._background_queue.clear()
        self._background_center = -1
        self._background_radius = 0
        self._background_max_radius = 0
        self._background_prefer_radius = 0
        self._background_done_count = 0

    def _bucket_allowed_for_warm(self, n: int) -> bool:
        if n < 0:
            return False
        step = max(1, int(self.interval))
        disk_until = max(0, int(self.disk_cover_until_sec or 0))
        if disk_until > 0 and n < disk_until:
            return False
        if self.base_dir and self.chunk_template and self.max_chunk_number > 0:
            chunk = int(n // step) + int(self.start_number or 0)
            if chunk > self.max_chunk_number:
                return False
        return True

    def _refill_background_queue(self) -> None:
        """Push the next L/R ring around the leave center into the background queue."""
        if self._background_center < 0:
            return
        if self._background_done_count >= _BACKGROUND_MAX_FRAMES:
            return
        if self._background_radius >= self._background_max_radius:
            return

        step = max(1, int(self.interval))
        self._background_radius += 1
        i = self._background_radius
        left = self._background_center - i * step
        right = self._background_center + i * step
        candidates = (left, right) if self._prefer_dir < 0 else (right, left)
        for n in candidates:
            if self._background_done_count + len(self._background_queue) >= _BACKGROUND_MAX_FRAMES:
                break
            if not self._bucket_allowed_for_warm(n):
                continue
            if n in self.cache or n in self._background_queue:
                continue
            self._background_queue.append(n)

    def _infer_chunk_number_bounds(self, stream_idx: int = 0) -> tuple[int, int]:
        pattern = os.path.join(self.base_dir, f"chunk-stream{stream_idx}-*.m4s")
        nums = []
        for path in glob.glob(pattern):
            m = re.search(rf"chunk-stream{stream_idx}-(\d+)\.m4s", os.path.basename(path))
            if m and os.path.getsize(path) > 0:
                nums.append(int(m.group(1)))
        if not nums:
            return 1, 1
        return min(nums), max(nums)

    def _infer_chunk_start_number(self, stream_idx: int = 0) -> int:
        return self._infer_chunk_number_bounds(stream_idx)[0]

    def _apply_steam_dash_defaults(self) -> bool:
        """Fallback when MPD XML parsing misses SegmentTemplate (common on session_fixed.mpd)."""
        if not self.base_dir or not os.path.isdir(self.base_dir):
            return False
        init_path = os.path.join(self.base_dir, _STEAM_VIDEO_INIT)
        if not self._is_usable_media_file(init_path):
            return False
        if not glob.glob(os.path.join(self.base_dir, "chunk-stream0-*.m4s")):
            return False
        self.init_filename = _STEAM_VIDEO_INIT
        self.chunk_template = _STEAM_VIDEO_CHUNK_TMPL
        self.chunk_duration_sec = _STEAM_CHUNK_SEC
        self.start_number, self.max_chunk_number = self._infer_chunk_number_bounds(0)
        self.rep_id = "0"
        return True

    def _ensure_dash_manifest(self, mpd_path: str) -> bool:
        if self._dash_manifest_ready():
            return True
        if mpd_path and self._is_dash_manifest(mpd_path):
            self.base_dir = os.path.dirname(mpd_path)
            self.parse_mpd(mpd_path)
        if self._dash_manifest_ready():
            return True
        return self._apply_steam_dash_defaults()

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
        if self._is_dash_manifest(media_path):
            # Seeking into a DASH manifest is extremely slow and often times out.
            _log.debug("Sniper skip ffmpeg on DASH manifest sec=%s", sec)
            return None
        if self._is_killed:
            return None
        gen = self._decode_gen
        cmd = [
            resolve_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(max(0, sec)),
            "-i", media_path,
            "-frames:v", "1",
            "-vf", "scale=160:90",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-",
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        t0 = time.perf_counter()
        self._kill_ffmpeg_subprocess()
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
            self._ffmpeg_proc = proc
            deadline = time.monotonic() + 8.0
            while proc.poll() is None:
                if self._is_killed or gen != self._decode_gen:
                    self._kill_ffmpeg_subprocess()
                    return None
                if time.monotonic() > deadline:
                    self._kill_ffmpeg_subprocess()
                    _log.info("Sniper ffmpeg timeout sec=%s file=%s", sec, os.path.basename(media_path))
                    return None
                time.sleep(0.05)
            stdout = proc.stdout.read() if proc.stdout else b""
            if proc.stderr:
                proc.stderr.read()
            self._ffmpeg_proc = None
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if proc.returncode != 0 or not stdout:
                _log.info(
                    "Sniper ffmpeg miss sec=%s (%.0fms) file=%s rc=%s",
                    sec, elapsed_ms, os.path.basename(media_path), proc.returncode,
                )
                return None
            qimg = QImage.fromData(stdout)
            if qimg.isNull():
                _log.info("Sniper ffmpeg miss sec=%s (%.0fms): empty image", sec, elapsed_ms)
                return None
            _log.info(
                "Sniper ffmpeg ok sec=%s (%.0fms) file=%s",
                sec, elapsed_ms, os.path.basename(media_path),
            )
            return QPixmap.fromImage(qimg)
        except Exception as exc:
            self._kill_ffmpeg_subprocess()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            _log.info(
                "Sniper ffmpeg error sec=%s (%.0fms) file=%s: %s",
                sec, elapsed_ms, os.path.basename(media_path), exc,
            )
            return None
        finally:
            if proc is not None and self._ffmpeg_proc is proc:
                self._ffmpeg_proc = None

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
                "Sniper parsed MPD chunk=%.2fs start=%s rep=%s dir=%s",
                self.chunk_duration_sec, self.start_number, self.rep_id, self.base_dir,
            )
        except Exception as exc:
            _log.warning("Sniper MPD parse failed for %s: %s", mpd_path, exc)
        if not self.init_filename or not self.chunk_template:
            self._apply_steam_dash_defaults()
        elif self.base_dir:
            lo, hi = self._infer_chunk_number_bounds(0)
            self.start_number = lo
            self.max_chunk_number = hi

    def request_frame(self, media_path, hover_sec):
        self._is_killed = False
        self._cancel_background_warm()

        # hover_sec is already a floor bucket from preview_bucket_sec — do not re-round.
        interval = max(1, int(self.interval))
        target_sec = max(0, int(hover_sec) // interval * interval)
        norm_path = self._norm_media_path(media_path)

        if self._norm_media_path(self.video_path) != norm_path:
            self.video_path = media_path
            self.cache.clear()
            self._cache_order.clear()
            self._fail_until.clear()
            self._in_flight_sec = -1
            self._prefer_dir = 0
            self._stable_since = 0.0
            self._cancel_background_warm()
            self._decode_gen += 1
            _log.info("Sniper opened %s", os.path.basename(media_path or ""))
            if self._is_dash_manifest(media_path):
                self._ensure_dash_manifest(media_path)
            else:
                self.base_dir = ""
                self.init_filename = ""
                self.chunk_template = ""

        if self.target_sec >= 0 and target_sec != self.target_sec:
            self._prefer_dir = 1 if target_sec > self.target_sec else -1
            self._fail_until.pop(target_sec, None)
            self._stable_since = time.monotonic()
        elif self.target_sec != target_sec:
            self._stable_since = time.monotonic()

        # Always retarget — cache hits must still drive left/right neighbor prefill.
        self.target_sec = target_sec
        self._last_hover_bucket_sec = target_sec

        if target_sec in self.cache:
            self.preview_ready.emit(target_sec, self.cache[target_sec])
            if not self.isRunning():
                self.start()
            return

        if not self.isRunning():
            self.start()
        elif self._in_flight_sec < 0:
            # Worker idle after kill_worker — wake the loop for a new target.
            self._is_killed = False

    def _decode_dash_frame(self, sec: int):
        if not self._dash_manifest_ready():
            self._ensure_dash_manifest(self.video_path)
        if not self._dash_manifest_ready():
            _log.debug("Sniper dash manifest not ready sec=%s", sec)
            return None

        chunk_offset = int(max(0, sec) // self.chunk_duration_sec)
        chunk_num = self.start_number + chunk_offset
        chunk_num = min(chunk_num, getattr(self, "max_chunk_number", chunk_num))

        real_init = self.init_filename.replace('$RepresentationID$', self.rep_id)
        real_chunk = self.chunk_template.replace('$RepresentationID$', self.rep_id)

        def _chunk_path_for(num: int) -> str:
            name = real_chunk
            match = re.search(r'\$Number([^$]*)\$', name)
            if match:
                format_spec = match.group(1)
                num_str = format_spec % num if format_spec else str(num)
                name = name[:match.start()] + num_str + name[match.end():]
            else:
                name = name.replace('$Number$', str(num))
            return os.path.normpath(os.path.join(self.base_dir, name))

        init_path = os.path.normpath(os.path.join(self.base_dir, real_init))
        chunk_path = _chunk_path_for(chunk_num)
        while (
            chunk_num > self.start_number
            and not self._is_usable_media_file(chunk_path)
        ):
            chunk_num -= 1
            chunk_path = _chunk_path_for(chunk_num)

        if not self._is_usable_media_file(init_path) or not self._is_usable_media_file(chunk_path):
            _log.debug(
                "Sniper PyAV miss sec=%s chunk=%s (init=%s chunk=%s missing)",
                sec, chunk_num, os.path.basename(init_path), os.path.basename(chunk_path),
            )
            return None

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
            return None
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            _log.info(
                "Sniper PyAV error sec=%s chunk=%s (%.0fms): %s",
                sec, chunk_num, elapsed_ms, exc,
            )
            return None

    def _decode_frame_av_file(self, media_path: str, sec: int):
        """Decode one hover frame from a flat file (rendered mp4/mkv/…) via PyAV."""
        if not media_path or not os.path.isfile(media_path):
            return None
        if self._is_dash_manifest(media_path):
            return None
        if self._is_killed:
            return None
        gen = self._decode_gen
        t0 = time.perf_counter()
        container = None
        try:
            container = av.open(media_path)
            if not container.streams.video:
                return None
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            seek_ts = int(max(0.0, sec) / stream.time_base)
            container.seek(seek_ts, stream=stream, backward=True, any_frame=False)
            pixmap = None
            for frame in container.decode(stream):
                if self._is_killed or gen != self._decode_gen:
                    break
                img = frame.to_image()
                img = img.resize((160, 90))
                img_data = img.convert("RGBA").tobytes("raw", "RGBA")
                qimg = QImage(img_data, img.width, img.height, QImage.Format_RGBA8888)
                pixmap = QPixmap.fromImage(qimg)
                break
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if pixmap is not None and not pixmap.isNull():
                _log.info(
                    "Sniper PyAV file ok sec=%s (%.0fms) file=%s",
                    sec, elapsed_ms, os.path.basename(media_path),
                )
                return pixmap
            _log.info(
                "Sniper PyAV file miss sec=%s (%.0fms) file=%s",
                sec, elapsed_ms, os.path.basename(media_path),
            )
            return None
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            _log.info(
                "Sniper PyAV file error sec=%s (%.0fms) file=%s: %s",
                sec, elapsed_ms, os.path.basename(media_path), exc,
            )
            return None
        finally:
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass

    def _decode_plain_file_frame(self, media_path: str, sec: int):
        """Hover frame for finished exports — PyAV first, ffmpeg fallback."""
        pixmap = self._decode_frame_av_file(media_path, sec)
        if pixmap is not None and not pixmap.isNull():
            return pixmap
        return self._decode_frame_ffmpeg(media_path, sec)

    def _neighbor_buckets(self, sec: int) -> list[int]:
        """Left/right 3s neighbors after the cursor bucket lands — soft prefill.

        Prefers the side the cursor was scrubbing toward so the next bucket is
        warm before the hover arrives.
        """
        interval = max(1, int(self.interval))
        left, right = sec - interval, sec + interval
        if self._prefer_dir < 0:
            candidates = (left, right)
        else:
            # Default and rightward scrub: warm the next bucket first.
            candidates = (right, left)

        neighbors: list[int] = []
        dash = bool(self.base_dir and self.chunk_template)
        disk_until = max(0, int(self.disk_cover_until_sec or 0))
        for n in candidates:
            if n < 0:
                continue
            # Batch disk thumbs already cover this range — don't burn PyAV on them.
            if disk_until > 0 and n < disk_until:
                continue
            if dash and self.max_chunk_number > 0:
                chunk = int(n // interval) + int(self.start_number or 0)
                if chunk > self.max_chunk_number:
                    continue
            neighbors.append(n)
        return neighbors

    def _run_on_demand(self, decode_fn):
        """Decode the cursor bucket; warm ±3s neighbors only after the cursor parks."""
        while not self._is_killed:
            sec = self.target_sec
            if sec < 0:
                if self._background_active:
                    now = time.monotonic()
                    if now >= self._background_end_time:
                        done = self._background_done_count
                        self._cancel_background_warm()
                        _log.info(
                            "Sniper background warm done (budget, %d frames) — idle, batch thumbs continue",
                            done,
                        )
                        self.msleep(60)
                        continue

                    if not self._background_queue:
                        # Expand next L/R ring. Prefer ±window first; then keep going
                        # until wall budget / max frames so leave-warm isn't a one-second blip.
                        before = self._background_radius
                        self._refill_background_queue()
                        if not self._background_queue:
                            if self._background_radius >= self._background_max_radius:
                                done = self._background_done_count
                                self._cancel_background_warm()
                                _log.info(
                                    "Sniper background warm done (%d frames) — idle, batch thumbs continue",
                                    done,
                                )
                            elif self._background_radius == before:
                                done = self._background_done_count
                                self._cancel_background_warm()
                                _log.info(
                                    "Sniper background warm done (%d frames) — idle, batch thumbs continue",
                                    done,
                                )
                            self.msleep(40)
                            continue

                    next_sec = self._background_queue.pop(0)
                    if next_sec in self.cache:
                        continue
                    retry_at = self._fail_until.get(next_sec, 0.0)
                    if retry_at and time.monotonic() < retry_at:
                        continue
                    self._in_flight_sec = next_sec
                    pixmap = decode_fn(next_sec)
                    self._in_flight_sec = -1
                    if self._is_killed:
                        continue
                    if pixmap is not None and not pixmap.isNull():
                        self._fail_until.pop(next_sec, None)
                        self._remember_cache(next_sec, pixmap)
                        self._background_done_count += 1
                    else:
                        self._fail_until[next_sec] = time.monotonic() + 2.0
                    continue

                self.msleep(60)
                continue

            if sec in self.cache:
                parked = (
                    self._stable_since > 0
                    and (time.monotonic() - self._stable_since) >= _NEIGHBOR_STABLE_SEC
                )
                if parked:
                    for neighbor in self._neighbor_buckets(sec):
                        if self._is_killed:
                            break
                        if self.target_sec != sec:
                            break
                        if neighbor in self.cache:
                            continue
                        retry_at = self._fail_until.get(neighbor, 0.0)
                        if retry_at and time.monotonic() < retry_at:
                            continue
                        self._in_flight_sec = neighbor
                        pixmap = decode_fn(neighbor)
                        self._in_flight_sec = -1
                        if self._is_killed:
                            break
                        if pixmap is not None and not pixmap.isNull():
                            self._fail_until.pop(neighbor, None)
                            self._remember_cache(neighbor, pixmap)
                            if self.target_sec == neighbor:
                                self.preview_ready.emit(neighbor, pixmap)
                                break
                        else:
                            self._fail_until[neighbor] = time.monotonic() + 2.0
                        if self.target_sec != sec:
                            break
                self.msleep(40 if not parked else 60)
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

            if self._is_killed:
                continue

            if pixmap is not None and not pixmap.isNull():
                self._fail_until.pop(sec, None)
                # Keep valid frames even if the cursor already moved — they warm the trail.
                self._remember_cache(sec, pixmap)
                if self.target_sec == sec:
                    self.preview_ready.emit(sec, pixmap)
            else:
                self._fail_until[sec] = time.monotonic() + 2.0
                self.msleep(200)

    def run(self):
        if self._is_dash_manifest(self.video_path):
            self._run_on_demand(self._decode_dash_frame)
        else:
            path = self.video_path
            self._run_on_demand(lambda sec, p=path: self._decode_plain_file_frame(p, sec))


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
            _kill_process_tree(self.process, label="batch-thumbs")
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
            resolve_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
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
        try:
            while True:
                proc = self.process
                if proc is None:
                    break
                if proc.poll() is not None:
                    break
                if self._cancelled:
                    _kill_process_tree(proc, label="batch-thumbs")
                    _log.debug("Batch thumbs cancelled: %s", self.mpd_path)
                    return
                time.sleep(0.1)
        finally:
            self.process = None
        elapsed_s = time.perf_counter() - t0
        if self._cancelled:
            return
        produced = len(glob.glob(os.path.join(self.thumb_dir, "thumb_*.jpg")))
        _log.info(
            "Batch thumbs done: %s produced=%d (%.1fs)",
            self.mpd_path, produced, elapsed_s,
        )

        self._emit_if_current()
