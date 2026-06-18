"""Background worker threads that produce video thumbnails.

PreviewSniperWorker decodes single DASH chunks with PyAV on demand to feed the
timeline's hover preview, emitting each frame as a QPixmap. ThumbnailBatchThread
shells out to ffmpeg once per clip to render the full strip of timeline thumbnails.
"""
import glob
import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import av

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage, QPixmap


class PreviewSniperWorker(QThread):
    preview_ready = Signal(int, QPixmap)

    def __init__(self):
        super().__init__()
        self.video_path = ""
        self.target_sec = -1
        self.cache = {}
        self.interval = 3

        self._is_killed = False

        # --- Manifest variables ---
        self.base_dir = ""
        self.init_filename = ""
        self.chunk_template = ""
        self.chunk_duration_sec = 3.0
        self.start_number = 1
        self.rep_id = "1"

        # --- RADAR (Radial Loader) ---
        self.bg_anchor = 0
        self.bg_radius = 3
        self.bg_left_done = False
        self.bg_right_done = False
        self.bg_side = "right"

    def kill_worker(self):
        self._is_killed = True
        self.cache.clear()

    def parse_mpd(self, mpd_path):
        self.base_dir = os.path.dirname(mpd_path)
        try:
            tree = ET.parse(mpd_path)
            root = tree.getroot()

            # Smart search: only the VIDEO track.
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
        except Exception:
            pass

    def request_frame(self, mpd_path, hover_sec):
        if self._is_killed:
            return

        target_sec = round(hover_sec / self.interval) * self.interval

        if self.video_path != mpd_path:
            self.video_path = mpd_path
            self.cache.clear()
            self.bg_anchor = 0
            self.bg_radius = self.interval
            self.bg_left_done = False
            self.bg_right_done = False
            self.parse_mpd(mpd_path)

        if target_sec in self.cache:
            self.preview_ready.emit(target_sec, self.cache[target_sec])
            return
        if self.target_sec == target_sec:
            return

        self.target_sec = target_sec
        if not self.isRunning():
            self.start()

    def run(self):
        last_serviced = -1

        while not self._is_killed:
            # --- SMART TASK DISTRIBUTOR ---
            if self.target_sec != -1 and self.target_sec != last_serviced:
                # Foreground: the frame right under the cursor.
                sec = self.target_sec
                is_background = False
                self.bg_anchor = self.target_sec
                self.bg_radius = self.interval
                self.bg_left_done = False
                self.bg_right_done = False
            else:
                # Background: radial fill outward from the last cursor anchor.
                is_background = True
                sec = -1
                while not (self.bg_left_done and self.bg_right_done):
                    if self.target_sec != last_serviced or self._is_killed:
                        break

                    if not self.bg_right_done:
                        candidate = self.bg_anchor + self.bg_radius
                        if candidate not in self.cache:
                            sec = candidate
                            self.bg_side = "right"
                            break
                        else:
                            self.bg_right_done = True

                    if not self.bg_left_done:
                        candidate = self.bg_anchor - self.bg_radius
                        if candidate >= 0:
                            if candidate not in self.cache:
                                sec = candidate
                                self.bg_side = "left"
                                break
                            else:
                                self.bg_left_done = True
                        else:
                            self.bg_left_done = True

                # Radar guard: keep widening the radius instead of spinning at 100% CPU.
                if self.bg_left_done and self.bg_right_done:
                    self.bg_radius += self.interval
                    self.bg_left_done = False
                    self.bg_right_done = False
                    continue

            if sec == -1:
                if self.target_sec == last_serviced:
                    self.msleep(100)
                continue

            try:
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

                if not os.path.exists(init_path) or not os.path.exists(chunk_path):
                    if is_background:
                        if self.bg_side == "right":
                            self.bg_right_done = True
                        elif self.bg_side == "left":
                            self.bg_left_done = True
                    else:
                        last_serviced = sec
                    continue

                # Decode one frame straight from RAM (init + chunk) via PyAV.
                with open(init_path, 'rb') as f:
                    init_bytes = f.read()
                with open(chunk_path, 'rb') as f:
                    chunk_bytes = f.read()

                ram_buffer = io.BytesIO(init_bytes + chunk_bytes)
                container = av.open(ram_buffer)

                stream = container.streams.video[0]
                for frame in container.decode(stream):
                    if self._is_killed:
                        break

                    img = frame.to_image()
                    img = img.resize((160, 90))
                    img_data = img.convert("RGBA").tobytes("raw", "RGBA")
                    qimg = QImage(img_data, img.width, img.height, QImage.Format_RGBA8888)
                    pixmap = QPixmap.fromImage(qimg)
                    self.cache[sec] = pixmap

                    if not is_background and self.target_sec == sec and not self._is_killed:
                        self.preview_ready.emit(sec, pixmap)
                    break  # one frame per chunk is enough!

                container.close()
                if not is_background:
                    last_serviced = sec

            except Exception:
                if is_background:
                    if self.bg_side == "right":
                        self.bg_right_done = True
                    else:
                        self.bg_left_done = True
                else:
                    last_serviced = sec


class ThumbnailBatchThread(QThread):
    """ Generates all thumbnails in the background ONCE, using GPU. """
    finished_generation = Signal(str)

    def __init__(self, mpd_path, duration_sec, interval=3, parent=None):
        super().__init__(parent)
        self.mpd_path = mpd_path
        self.duration_sec = duration_sec
        self.interval = interval
        self.process = None

        path_hash = hashlib.md5(mpd_path.encode('utf-8')).hexdigest()[:10]
        self.thumb_dir = os.path.join(tempfile.gettempdir(), f"steempeg_batch_{path_hash}_{self.interval}s")
        os.makedirs(self.thumb_dir, exist_ok=True)

    def stop(self):
        """ FORCE-KILLING THE FFMPEG PROCESS BEFORE STOPPING THE STREAM! """
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass
        self.terminate()

    def run(self):
        existing_files = glob.glob(os.path.join(self.thumb_dir, "thumb_*.jpg"))
        expected_count = int(self.duration_sec // self.interval)

        if len(existing_files) >= expected_count * 0.9:
            self.finished_generation.emit(self.thumb_dir)
            return

        shutil.rmtree(self.thumb_dir, ignore_errors=True)
        os.makedirs(self.thumb_dir, exist_ok=True)

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-hwaccel", "auto",
            "-threads", "2",
            "-i", self.mpd_path,
            "-vf", f"fps=1/{self.interval}",
            "-q:v", "7",
            "-s", "160x90",
            os.path.join(self.thumb_dir, "thumb_%04d.jpg")
        ]

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        self.process = subprocess.Popen(cmd, creationflags=creationflags)
        self.process.wait()

        self.finished_generation.emit(self.thumb_dir)