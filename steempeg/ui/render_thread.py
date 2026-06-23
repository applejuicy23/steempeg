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


class RenderThread(QThread):
    progress_signal = Signal(str)  
    finished_signal = Signal(bool, str, str) 

    def __init__(self, mpd_paths, quality_text, output_file, ffmpeg_exe, save_dir, selected_encoder, video_bitrate, fps_text, audio_only, mute_audio, audio_format, audio_bitrate_kbps, target_scale_h=-1, trim_start_sec=-1.0, trim_duration_sec=-1.0):
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
        
        self.audio_only = audio_only
        self.mute_audio = mute_audio
        self.audio_format = audio_format
        self.audio_bitrate_kbps = audio_bitrate_kbps
        
        self.target_scale_h = target_scale_h
        
        self.is_cancelled = False
        self.is_paused = False
        self.current_process = None

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
                

                
                
                # --- FFMPEG COMMAND GENERATION ---
                
                # 0. Inject Trim Arguments BEFORE the input for maximum seeking speed!
                trim_args = ""
                if self.trim_start_sec >= 0 and self.trim_duration_sec > 0:
                    trim_args = f"-ss {self.trim_start_sec:.3f} -t {self.trim_duration_sec:.3f} "
                
                # 1. Prepare the audio arguments
                if self.mute_audio:
                    base_audio = "-an" 
                else:
                    a_codec = "libmp3lame" if self.audio_format == "MP3" else "aac"
                    base_audio = f"-c:a {a_codec} -b:a {self.audio_bitrate_kbps}"

                # 2. Construct the final command based on video settings
                if self.audio_only:
                    cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vn {base_audio} -y "{temp_mp4}"'
                    
                elif "Original" in self.quality_text and "Target File" not in self.quality_text:
                    if self.mute_audio:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c:v copy -an -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c copy -y "{temp_mp4}"'
                        
                elif "Target File Size" in self.quality_text:
                    bitrate_val = int(self.video_bitrate.replace('k', ''))
                    bufsize = f"{bitrate_val * 2}k" 
                    
                    if self.target_scale_h > 0:
                        scale_filter = f"scale=-2:min(ih\\,{self.target_scale_h})"
                    else:
                        scale_filter = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
                    
                    cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vf "{scale_filter}" {fps_arg}-c:v {self.selected_encoder} -b:v {self.video_bitrate} -maxrate {self.video_bitrate} -bufsize {bufsize} {base_audio} -y "{temp_mp4}"'
                    
                else:
                    match = re.search(r'^(\d+)p', self.quality_text)
                    if match:
                        target_height = match.group(1)
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" -vf scale=-2:{target_height} {fps_arg}-c:v {self.selected_encoder} -b:v {self.video_bitrate} {base_audio} -y "{temp_mp4}"'
                    else:
                        cmd = f'"{self.ffmpeg_exe}" {trim_args}-i "{safe_mpd}" {fps_arg}-c copy -y "{temp_mp4}"'

                logging.debug(f"FFmpeg cmd for part {idx}: {cmd}")

                # Launch FFmpeg
                self.current_process = subprocess.Popen( 
                    cmd, shell=False, cwd=os.path.dirname(mpd),
                    creationflags=creation_flags, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', errors='ignore'
                )

                total_duration = 0
                last_ffmpeg_output = []

                # Read FFmpeg logs in real time
                for line in self.current_process.stdout:
                    if self.is_cancelled:
                        break
                        
                    clean_line = line.strip()
                    if clean_line:
                        # Collect the last 5 lines of logs for output in case of an error
                        logging.debug(f"[FFmpeg] {clean_line}")
                        last_ffmpeg_output.append(clean_line)
                        if len(last_ffmpeg_output) > 5:
                            last_ffmpeg_output.pop(0)
                            
                    # Parse the total duration of the video
                    if total_duration == 0:
                        dur_match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                        if dur_match:
                            h, m, s = float(dur_match.group(1)), float(dur_match.group(2)), float(dur_match.group(3))
                            total_duration = h * 3600 + m * 60 + s

                    # Parse the current render time to calculate percentages
                    time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                    if time_match and total_duration > 0:
                        h, m, s = float(time_match.group(1)), float(time_match.group(2)), float(time_match.group(3))
                        current_time = h * 3600 + m * 60 + s
                        
                        # Calculating tenths of a unit for perfect smoothness!
                        percent = (current_time / total_duration) * 100.0
                        self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. ({min(percent, 100.0):.1f}%)")

                self.current_process.wait()
                
                # If this was an ultra-fast copy (Original), manually set to 100%.
                self.progress_signal.emit(f"Part {idx+1}/{len(self.mpd_paths)}.. (100%)")
                
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
                
                # Directly move/rename the perfectly rendered temp file to the final destination!
                if os.path.exists(self.output_file):
                    os.remove(self.output_file)
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
