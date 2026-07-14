"""The background render worker: a QThread that drives FFmpeg to produce the output clip.

Receives every render parameter (including the ffmpeg executable path) through its
constructor, so it carries no reference back to the application or its widgets. The
Qt-free command-building and execution logic will later move into render/command.py
and render/job.py; for now the whole worker lives here in the Qt layer.
"""
import logging
import os
import re
import shutil
import subprocess
import sys

import psutil

from PySide6.QtCore import QThread, Signal

from steempeg.render.output_formats import build_audio_args, video_encoder_extra_args
from steempeg.core.dash.mpd import estimate_render_duration_sec


class RenderThread(QThread):
    progress_signal = Signal(str)  
    finished_signal = Signal(bool, str, str) 

    def __init__(self, mpd_paths, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate, fps_text, audio_only, mute_audio, audio_format, audio_bitrate_kbps, target_scale_h=-1, trim_start_sec=-1.0, trim_duration_sec=-1.0, encode_speed="balanced"):
        super().__init__()
        self.target_scale_h = target_scale_h 
        self.trim_start_sec = trim_start_sec
        self.trim_duration_sec = trim_duration_sec
        self.mpd_paths = mpd_paths
        self.quality_text = quality_text
        self.output_file = output_file
        self.ffmpeg_exe = ffmpeg_exe
        self.save_dir = save_dir
        
        self.selected_encoder = selected_encoder
        self.video_bitrate = video_bitrate
        self.fps_text = fps_text
        self.encode_speed = encode_speed
        
        self.audio_only = audio_only
        self.mute_audio = mute_audio
        self.audio_format = audio_format
        self.audio_bitrate_kbps = audio_bitrate_kbps
        
        self.target_scale_h = target_scale_h
        
        self.is_cancelled = False
        self.is_paused = False
        self.current_process = None

    @staticmethod
    def _parse_ffmpeg_time_hms(line: str) -> float | None:
        match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
        if not match:
            return None
        h, m, s = float(match.group(1)), float(match.group(2)), float(match.group(3))
        return h * 3600 + m * 60 + s

    @staticmethod
    def _parse_ffmpeg_duration_hms(line: str) -> float | None:
        match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", line)
        if not match:
            return None
        h, m, s = float(match.group(1)), float(match.group(2)), float(match.group(3))
        return h * 3600 + m * 60 + s

    def _emit_part_progress(
        self,
        part_index: int,
        part_count: int,
        current_sec: float,
        duration_sec: float,
        last_pct: list,
    ) -> None:
        if duration_sec <= 0:
            return
        part_frac = min(1.0, max(0.0, current_sec / duration_sec))
        overall = ((part_index + part_frac) / part_count) * 100.0
        overall = min(99.9, overall)
        if last_pct and abs(overall - last_pct[0]) < 0.4:
            return
        last_pct[:] = [overall]
        self.progress_signal.emit(
            f"Part {part_index + 1}/{part_count}.. ({overall:.1f}%)"
        )

    def cancel(self):
        """ Force kills the FFmpeg process. """
        self.is_cancelled = True
        if self.current_process:
            try:
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.current_process.pid)])
            except: pass

    def toggle_pause(self):
        """ Pauses or resumes FFmpeg at the OS level. """
        if not self.current_process:
            return False
            
        self.is_paused = not self.is_paused
        try:
            p = psutil.Process(self.current_process.pid)
            if self.is_paused: p.suspend()
            else: p.resume() 
        except:
            self.is_paused = not self.is_paused
            
        return self.is_paused

    def run(self):
        """ Main thread loop """
        if os.environ.get("STEEMPEG_DEBUG_RENDER_FAIL"):
            self.progress_signal.emit("Part 1/1.. (0%)")
            self.finished_signal.emit(
                False,
                "DEBUG: Simulated FFmpeg crash (STEEMPEG_DEBUG_RENDER_FAIL=1).\n"
                "ffmpeg version N/A\nError: Invalid data found when processing input",
                "",
            )
            return

        temp_files = []
        concat_file = None
        # Tracks whether any part was produced via raw stream copy. Copied parts can
        # inherit a corrupt Steam decode timeline, so single-file output needs a final
        # remux pass (instead of a plain move) to rewrite clean container headers.
        self._stream_copy_used = False
        try:
            creation_flags = 0x08000000 if sys.platform == "win32" else 0
            # Get the target extension (.mp4, .mp3, .aac) from the final output file
            _, ext = os.path.splitext(self.output_file)
            
            # STEP 1: Render each .mpd part
            for idx, mpd in enumerate(self.mpd_paths):
                if self.is_cancelled:
                    raise Exception("Render cancelled by user.")
                    
                # Use the correct extension for temporary files
                temp_mp4 = os.path.join(self.save_dir, f"temp_steempeg_part_{idx}{ext}")
                temp_files.append(temp_mp4)
                
                self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. (0%)")
                
                # Fix paths for FFmpeg (replace backslashes with forward slashes)
                safe_mpd = mpd.replace('\\', '/')

                fps_arg = ""
                if hasattr(self, 'fps_text') and "Original" not in self.fps_text:
                    match_fps = re.search(r'(\d+)', self.fps_text)
                    if match_fps:
                        fps_arg = f"-r {match_fps.group(1)} "

                # Some Steam DASH clips ship a corrupt decode timeline: the first
                # fragment carries a baseMediaDecodeTime that is offset by hundreds of
                # seconds from the rest (e.g. chunk-0 at 0s, chunk-1 at +944s). ffprobe
                # and the player hide this because they trust the presentation (PTS)
                # timeline, but a raw "-c copy" mux writes the broken DTS verbatim and
                # the muxer pads the gap, turning a 2-minute clip into a 15-minute file
                # with a frozen tail. +igndts tells ffmpeg to drop the source DTS and
                # regenerate a clean monotonic one from the (correct) PTS, which fixes
                # stream copy losslessly and is a harmless no-op for re-encodes.
                input_fix = "-fflags +igndts "

                # Companion fix for stream copy: a few Steam clips also carry one absurd
                # multi-hundred-second jump between the first fragment and the rest
                # (e.g. frame 0 at 0s, the rest anchored at +944s). The mp4 muxer turns
                # that single gap into an inflated track duration (a 2-minute clip
                # becomes a 15-minute file with a frozen tail). setts rewrites the
                # timestamps so any gap larger than 30s collapses to one normal frame
                # interval, while leaving real sub-30s gaps (legit capture stalls)
                # untouched. B-frame reorder is preserved because pts keeps its original
                # offset from dts. Applied to copy only; re-encode paths don't need it.
                copy_ts_fix = (
                    r"-bsf:v setts=dts='PREV_OUTDTS+if(gt(DTS-PREV_INDTS\,30000000)\,16667\,DTS-PREV_INDTS)'"
                    r":pts='PTS-DTS+PREV_OUTDTS+if(gt(DTS-PREV_INDTS\,30000000)\,16667\,DTS-PREV_INDTS)' "
                )
                

                
                
                # --- FFMPEG COMMAND GENERATION ---
                
                # 0. Inject Trim Arguments BEFORE the input for maximum seeking speed!
                trim_args = ""
                is_trim = self.trim_start_sec >= 0 and self.trim_duration_sec > 0
                if is_trim:
                    trim_args = f"-ss {self.trim_start_sec:.3f} -t {self.trim_duration_sec:.3f} "
                trim_args = f"{trim_args}{input_fix}"

                # Trimmed stream-copy segments: the input -ss seek already lands past
                # the corrupt head fragment, so the video-only setts retimestamp isn't
                # needed. Worse, setts rewrites ONLY the video timeline (forces it to
                # start at 0) while the audio keeps its seek-relative timestamps, which
                # desynced the audio on trims ("кривой звук"). Drop setts for trims and
                # let avoid_negative_ts shift BOTH streams together so A/V stays in sync.
                if is_trim:
                    copy_ts_fix = "-avoid_negative_ts make_zero "
                
                # 1. Prepare the audio arguments
                base_audio = build_audio_args(
                    self.audio_format, self.audio_bitrate_kbps, self.mute_audio
                )
                v_extra = video_encoder_extra_args(self.selected_encoder, self.encode_speed)

                # 2. Construct the final command based on video settings
                if self.audio_only:
                    cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vn {base_audio} -y "{temp_mp4}"'
                    
                elif "Original" in self.quality_text and "Target File" not in self.quality_text:
                    self._stream_copy_used = True
                    if self.mute_audio:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c:v copy {copy_ts_fix}-an -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c copy {copy_ts_fix}-y "{temp_mp4}"'
                        
                elif "Target File Size" in self.quality_text:
                    bitrate_val = int(self.video_bitrate.replace('k', ''))
                    bufsize = f"{bitrate_val * 2}k" 
                    
                    if self.target_scale_h > 0:
                        scale_filter = f"scale=-2:min(ih\\,{self.target_scale_h})"
                    else:
                        scale_filter = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
                    
                    cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vf "{scale_filter}" {fps_arg}{v_extra}-c:v {self.selected_encoder} -b:v {self.video_bitrate} -maxrate {self.video_bitrate} -bufsize {bufsize} {base_audio} -y "{temp_mp4}"'
                    
                else:
                    match = re.search(r'^(\d+)p', self.quality_text)
                    if match:
                        target_height = match.group(1)
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vf scale=-2:{target_height} {fps_arg}{v_extra}-c:v {self.selected_encoder} -b:v {self.video_bitrate} {base_audio} -y "{temp_mp4}"'
                    else:
                        self._stream_copy_used = True
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c copy {copy_ts_fix}-y "{temp_mp4}"'

                logging.debug(f"FFmpeg cmd for part {idx}: {cmd}")

                expected_duration = estimate_render_duration_sec(
                    mpd,
                    trim_duration_sec=self.trim_duration_sec if is_trim else -1.0,
                )

                # Launch FFmpeg
                self.current_process = subprocess.Popen( 
                    cmd, shell=False, cwd=os.path.dirname(mpd),
                    creationflags=creation_flags, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', errors='ignore'
                )

                ffmpeg_duration = 0.0
                progress_duration = expected_duration
                last_ffmpeg_output = []
                last_emitted_pct: list[float] = []

                # Read FFmpeg logs in real time
                for line in self.current_process.stdout:
                    if self.is_cancelled:
                        break
                        
                    clean_line = line.strip()
                    if clean_line:
                        logging.debug(f"[FFmpeg] {clean_line}")
                        last_ffmpeg_output.append(clean_line)
                        if len(last_ffmpeg_output) > 5:
                            last_ffmpeg_output.pop(0)

                    parsed_dur = self._parse_ffmpeg_duration_hms(line)
                    if parsed_dur and parsed_dur > 0:
                        ffmpeg_duration = parsed_dur
                        if progress_duration <= 0:
                            progress_duration = ffmpeg_duration
                        elif ffmpeg_duration > progress_duration * 2:
                            # Manifest/ffmpeg duration inflated — keep chunk-based estimate.
                            pass
                        else:
                            progress_duration = min(progress_duration, ffmpeg_duration)

                    current_time = self._parse_ffmpeg_time_hms(line)
                    if current_time is not None and progress_duration > 0:
                        self._emit_part_progress(
                            idx,
                            len(self.mpd_paths),
                            current_time,
                            progress_duration,
                            last_emitted_pct,
                        )

                self.current_process.wait()
                
                self.progress_signal.emit(
                    f"Part {idx + 1}/{len(self.mpd_paths)}.. (100%)"
                )
                
                # Post-process checks
                if self.is_cancelled:
                    raise Exception("Render cancelled by user.")
                    
                if self.current_process.returncode != 0:
                    error_details = "\n".join(last_ffmpeg_output)

                    logging.error(f"FFmpeg ERROR in part {idx}:\n{error_details}")


                    raise Exception(f"Failed to render part {idx+1}.\nFFmpeg error:\n{error_details}")

            # Final check before gluing
            if self.is_cancelled:
                raise Exception("Render cancelled by user.")

            # --- FIX FOR 0 BYTES (BYPASS CONCAT FOR SINGLE FILES) ---
            # STAGE 2: Merging all rendered parts into one file
            if len(temp_files) == 1:
                # 99% of cases: No need to use the buggy 'concat' demuxer for a single file!
                self.progress_signal.emit("Finalizing...")

                if os.path.exists(self.output_file):
                    os.remove(self.output_file)

                if self._stream_copy_used:
                    # The setts pass fixes presentation timestamps but MKV/Matroska can
                    # still inherit a bogus segment Duration when audio track metadata is
                    # corrupt (Steam A/V offset clips). Remux with -shortest so the
                    # container length follows the real video packets, not INT64_MAX.
                    safe_in = temp_files[0].replace("\\", "/")
                    safe_out = self.output_file.replace("\\", "/")
                    remux_cmd = (
                        f'"{self.ffmpeg_exe}" -i "{safe_in}" '
                        f"-map 0:v:0 -map 0:a:0? -c copy -shortest "
                        f"-avoid_negative_ts make_zero -fflags +genpts "
                        f'-y "{safe_out}"'
                    )
                    remux = subprocess.Popen(
                        remux_cmd,
                        shell=False, cwd=self.save_dir, creationflags=creation_flags,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        universal_newlines=True, encoding='utf-8', errors='ignore'
                    )
                    self.current_process = remux
                    remux_tail = []
                    for line in remux.stdout:
                        clean = line.strip()
                        if clean:
                            logging.debug(f"[FFmpeg] {clean}")
                            remux_tail.append(clean)
                            if len(remux_tail) > 5:
                                remux_tail.pop(0)
                    remux.wait()
                    if remux.returncode != 0:
                        # Header rewrite failed; fall back to the raw copied file so the
                        # user still gets a playable (if slightly mis-tagged) result.
                        logging.error("Finalize remux failed:\n" + "\n".join(remux_tail))
                        if not os.path.exists(self.output_file):
                            shutil.move(temp_files[0], self.output_file)
                    else:
                        try:
                            os.remove(temp_files[0])
                        except OSError:
                            pass
                else:
                    # Directly move/rename the perfectly rendered temp file to the final destination!
                    shutil.move(temp_files[0], self.output_file)

                self.finished_signal.emit(True, "", self.output_file)
            else:
                self.progress_signal.emit("Merging all parts...")
                concat_file = os.path.join(self.save_dir, "temp_concat_list.txt")
                
                # Create a text file with a list of chunks for FFmpeg
                with open(concat_file, "w", encoding="utf-8") as f:
                    for tmp in temp_files:
                        safe_path = tmp.replace('\\', '/')
                        f.write(f"file '{safe_path}'\n")

                # Run the merge without compression (-c copy)
                self.current_process = subprocess.Popen(
                    f'"{self.ffmpeg_exe}" -f concat -safe 0 -i "{concat_file}" -c copy -y "{self.output_file}"', 
                    shell=False, cwd=self.save_dir,
                    creationflags=creation_flags, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                self.current_process.wait()

                if self.is_cancelled:
                    raise Exception("Render cancelled by user.")

                if self.current_process.returncode == 0:
                    self.finished_signal.emit(True, "", self.output_file) # success
                else:
                    self.finished_signal.emit(False, "Merge failed.", "")

        except Exception as e:
            self.finished_signal.emit(False, str(e), "") # error
            
        finally:
            # STEP 3: CLEANING. Remove all temporary debris
            if concat_file and os.path.exists(concat_file):
                try: os.remove(concat_file)
                except: pass
            for tmp in temp_files:
                if os.path.exists(tmp):
                    try: os.remove(tmp)
                    except: pass

# BACKGROUND DOWNLOAD THREAD FOR UPDATER
