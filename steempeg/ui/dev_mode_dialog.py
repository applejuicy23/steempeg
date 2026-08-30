"""Developer Mode dialog — Render QA, Filters QA, System Info.

Hidden behind ``dev_mode: true`` in cache/settings.json.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import shutil
import subprocess
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from steempeg.core.dash import discovery as dash_discovery

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.process import subprocess_hide_console_kwargs
from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-use constants from the CLI diagnostic script
# ---------------------------------------------------------------------------
RESOLUTIONS = [144, 240, 360, 480, 720, 1080]
CODECS = ["libx264", "libx265"]
CODEC_LABELS = {"libx264": "H.264", "libx265": "H.265"}
BITRATE_PRESETS = {
    "Ultra":  {4320: 120, 2160: 50,   1440: 32,   1080: 24,  720: 12,   480: 6,   360: 3,   260: 1.5, 144: 0.5},
    "High":   {4320: 90,  2160: 38,   1440: 22,   1080: 12,  720: 7.5,  480: 4,   360: 2,   260: 1.0, 144: 0.3},
    "Medium": {4320: 60,  2160: 28.5, 1440: 16.5, 1080: 9,   720: 5.6,  480: 2.5, 360: 1.2, 260: 0.6, 144: 0.2},
    "Low":    {4320: 40,  2160: 19,   1440: 11,   1080: 6,   720: 3.75, 480: 1.5, 360: 0.8, 260: 0.4, 144: 0.1},
}
FPS_OPTIONS = [30, 60]
TARGET_SIZE_PRESETS_MB = {
    "Tiny": 10,
    "Small": 50,
    "Medium": 100,
    "Large": 250,
    "XL": 500,
}
TARGET_SIZE_MAX_MB = 1024
TARGET_SIZE_TOLERANCE = 0.30


# ── helpers (mirrors scripts/diag_render_qa.py) ─────────────────────────────
def _snap_height(h: int) -> int:
    tiers = sorted(BITRATE_PRESETS["Ultra"].keys(), reverse=True)
    for t in tiers:
        if h >= t:
            return t
    return tiers[-1]


def _bitrate_for(preset: str, height: int) -> float:
    table = BITRATE_PRESETS.get(preset, BITRATE_PRESETS["Medium"])
    return table.get(_snap_height(height), table[1080])


def _ffprobe(path: str | Path) -> dict | None:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30,
            **subprocess_hide_console_kwargs(),
        )
        return json.loads(r.stdout) if r.returncode == 0 else None
    except Exception:
        return None


def _video_stream(probe: dict) -> dict | None:
    for s in probe.get("streams", []):
        if s.get("codec_type") == "video":
            return s
    return None


def _parse_duration_seconds(dur_str: str) -> float | None:
    """Parse cache duration_str like '1m 49s' or '2h 3m 10s'."""
    if not dur_str:
        return None
    total = 0.0
    for m in re.finditer(r"(\d+)\s*h", dur_str):
        total += int(m.group(1)) * 3600
    for m in re.finditer(r"(\d+)\s*m", dur_str):
        total += int(m.group(1)) * 60
    for m in re.finditer(r"(\d+)\s*s", dur_str):
        total += int(m.group(1))
    return total if total > 0 else None


def _source_video_path(clip_dir: str | Path) -> Path | None:
    """Return the best ffmpeg input for a Steam clip folder (flat or nested)."""
    p = Path(clip_dir)
    if not p.is_dir():
        return None

    flat: list[Path] = []
    nested: list[Path] = []
    for ext in ("*.mp4", "*.mkv", "*.webm", "*.mov"):
        flat.extend(p.glob(ext))
        nested.extend(p.rglob(ext))
    if flat:
        return sorted(flat)[0]
    if nested:
        return sorted(nested, key=lambda path: len(path.parts))[0]

    mpds = dash_discovery.find_mpd_paths(str(p))
    if mpds:
        return Path(mpds[0])
    mpd = sorted(p.rglob("*.mpd"), key=lambda path: len(path.parts))
    return mpd[0] if mpd else None


def _pick_diverse_clips(pool: list[tuple[str, str]], count: int) -> list[str]:
    """Round-robin across shuffled games, then fill remainder at random."""
    if not pool or count <= 0:
        return []
    if len(pool) <= count:
        return [path for path, _ in random.sample(pool, len(pool))]

    by_game: dict[str, list[str]] = {}
    for path, game in pool:
        by_game.setdefault(game or "?", []).append(path)
    for paths in by_game.values():
        random.shuffle(paths)

    games = list(by_game.keys())
    random.shuffle(games)
    picked: list[str] = []
    while len(picked) < count and games:
        for game in list(games):
            if len(picked) >= count:
                break
            if by_game[game]:
                picked.append(by_game[game].pop())
            if not by_game[game]:
                games.remove(game)

    if len(picked) < count:
        remaining = [path for path, _ in pool if path not in picked]
        random.shuffle(remaining)
        picked.extend(remaining[: count - len(picked)])
    return picked


def _discover_clips(
    cache_dir: str,
    count: int,
    max_clip_dur_s: float,
    exclude_games: set[str],
    exclude_paths: set[str],
) -> tuple[list[str], dict[str, str], dict[str, int]]:
    """Return selected clip paths, path→game map, and discovery stats."""
    pool: list[tuple[str, str]] = []
    skipped: dict[str, int] = {
        "missing_dir": 0,
        "excluded_game": 0,
        "excluded_path": 0,
        "duration_over_max": 0,
        "no_video": 0,
    }
    path_games: dict[str, str] = {}
    cache_path = Path(cache_dir) / "clips_library_cache.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            for c in data.get("clips", []):
                fp = c.get("full_path", "")
                if not fp or not Path(fp).is_dir():
                    skipped["missing_dir"] += 1
                    continue
                if fp in exclude_paths:
                    skipped["excluded_path"] += 1
                    continue
                gn = c.get("game_name", "").strip()
                if gn and gn in exclude_games:
                    skipped["excluded_game"] += 1
                    continue
                if max_clip_dur_s > 0:
                    dur_s = _parse_duration_seconds(c.get("duration_str", ""))
                    if dur_s is not None and dur_s > max_clip_dur_s:
                        skipped["duration_over_max"] += 1
                        continue
                if not _source_video_path(fp):
                    skipped["no_video"] += 1
                    continue
                path_games[fp] = gn or "?"
                pool.append((fp, gn or "?"))
        except Exception:
            pass

    games_in_pool = len({game for _, game in pool})
    stats = {
        "pool_size": len(pool),
        "games_in_pool": games_in_pool,
        **skipped,
    }
    return _pick_diverse_clips(pool, count), path_games, stats


# ── Render preset dataclass ──────────────────────────────────────────────────
class _RenderPreset:
    __slots__ = (
        "resolution",
        "codec",
        "bitrate_preset",
        "fps",
        "mode",
        "target_size_mb",
        "is_custom_target",
        "label",
    )

    def __init__(
        self,
        resolution,
        codec,
        bitrate_preset,
        fps,
        mode: str = "bitrate",
        target_size_mb: int | None = None,
        is_custom_target: bool = False,
    ):
        self.resolution = resolution
        self.codec = codec
        self.bitrate_preset = bitrate_preset
        self.fps = fps
        self.mode = mode
        self.target_size_mb = target_size_mb
        self.is_custom_target = is_custom_target
        res_l = f"{resolution}p" if resolution else "Original"
        fps_l = f"{fps}fps" if fps else "OrigFPS"
        if self.mode == "target_size" and self.target_size_mb is not None:
            size_tag = "Custom" if self.is_custom_target else "Preset"
            mode_l = f"TargetSize{self.target_size_mb}MB_{size_tag}"
        else:
            br_l = bitrate_preset or "Original"
            mode_l = br_l
        self.label = f"{res_l}_{CODEC_LABELS.get(codec, codec)}_{mode_l}_{fps_l}"


def _generate_presets(
    source_height: int,
    source_fps: float,
    count: int,
    resolutions: list[int | None],
    codecs: list[str],
    bitrate_presets: list[str | None],
    fps_options: list[int | None],
    include_target_size_mode: bool,
    target_size_presets: list[str],
    custom_target_min_mb: int,
    custom_target_max_mb: int,
) -> list[_RenderPreset]:
    pool: list[_RenderPreset] = []
    usable_res = [r for r in resolutions if r is None or r <= source_height]
    if not usable_res:
        usable_res = [144]
    usable_fps = [f for f in fps_options if f is None or f <= source_fps]
    if not usable_fps:
        usable_fps = [None]

    selected_target_sizes = [
        TARGET_SIZE_PRESETS_MB[name]
        for name in target_size_presets
        if name in TARGET_SIZE_PRESETS_MB
    ]
    custom_enabled = "Custom" in target_size_presets
    custom_target_min_mb = max(1, min(int(custom_target_min_mb), TARGET_SIZE_MAX_MB))
    custom_target_max_mb = max(1, min(int(custom_target_max_mb), TARGET_SIZE_MAX_MB))
    if custom_target_min_mb > custom_target_max_mb:
        custom_target_min_mb, custom_target_max_mb = custom_target_max_mb, custom_target_min_mb

    base_modes = ["bitrate"]
    if include_target_size_mode and (selected_target_sizes or custom_enabled):
        base_modes.append("target_size")

    for _ in range(count * 3):
        mode = random.choice(base_modes)
        if mode == "target_size":
            use_custom = custom_enabled and (
                not selected_target_sizes or random.random() < 0.5
            )
            if use_custom:
                target_mb = random.randint(custom_target_min_mb, custom_target_max_mb)
            else:
                target_mb = random.choice(selected_target_sizes)
            target_mb = min(target_mb, TARGET_SIZE_MAX_MB)
            pool.append(
                _RenderPreset(
                    random.choice(usable_res),
                    random.choice(codecs),
                    None,
                    random.choice(usable_fps),
                    mode="target_size",
                    target_size_mb=target_mb,
                    is_custom_target=use_custom,
                )
            )
        else:
            pool.append(
                _RenderPreset(
                    random.choice(usable_res),
                    random.choice(codecs),
                    random.choice(bitrate_presets),
                    random.choice(usable_fps),
                )
            )
    seen: set[str] = set()
    unique: list[_RenderPreset] = []
    for p in pool:
        if p.label not in seen:
            seen.add(p.label)
            unique.append(p)
    random.shuffle(unique)
    return unique[:count]


# ── Worker thread ────────────────────────────────────────────────────────────
class _RenderQAWorker(QThread):
    """Runs render QA jobs off the UI thread."""

    log_line = Signal(str)
    progress = Signal(int, int, int, int)  # done, total, pass_count, fail_count
    finished_all = Signal(str)  # report path

    def __init__(
        self,
        cache_dir: str,
        clip_count: int,
        presets_per_clip: int,
        max_clip_dur_s: float,
        max_render_dur_s: float,
        random_trim: bool,
        resolutions: list[int | None],
        codecs: list[str],
        bitrate_presets: list[str | None],
        fps_options: list[int | None],
        include_target_size_mode: bool,
        target_size_presets: list[str],
        custom_target_min_mb: int,
        custom_target_max_mb: int,
        exclude_games: set[str],
        exclude_paths: set[str],
        output_dir: str,
        verbose: bool,
    ):
        super().__init__()
        self._cache_dir = cache_dir
        self._clip_count = clip_count
        self._presets_per_clip = presets_per_clip
        self._max_clip_dur = max_clip_dur_s
        self._max_render_dur = max_render_dur_s
        self._random_trim = random_trim
        self._resolutions = resolutions
        self._codecs = codecs
        self._bitrate_presets = bitrate_presets
        self._fps_options = fps_options
        self._include_target_size_mode = include_target_size_mode
        self._target_size_presets = target_size_presets
        self._custom_target_min_mb = custom_target_min_mb
        self._custom_target_max_mb = custom_target_max_mb
        self._exclude_games = exclude_games
        self._exclude_paths = exclude_paths
        self._output_dir = output_dir
        self._verbose = verbose
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):  # noqa: C901  (complexity acceptable for QA runner)
        report_path = ""
        try:
            if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
                self.log_line.emit("ERROR: ffmpeg / ffprobe not found in PATH")
                return

            clips, path_games, stats = _discover_clips(
                self._cache_dir, self._clip_count,
                self._max_clip_dur, self._exclude_games, self._exclude_paths,
            )
            self.log_line.emit(
                f"Clip pool: {stats['pool_size']} eligible across "
                f"{stats['games_in_pool']} game(s)"
            )
            if stats["pool_size"] < self._clip_count:
                self.log_line.emit(
                    f"WARNING: Requested {self._clip_count} clips but only "
                    f"{stats['pool_size']} eligible"
                )
            for reason, n in (
                ("excluded game", stats["excluded_game"]),
                ("excluded path", stats["excluded_path"]),
                ("duration > max", stats["duration_over_max"]),
                ("no video path", stats["no_video"]),
                ("missing dir", stats["missing_dir"]),
            ):
                if n:
                    self.log_line.emit(f"  Filtered out {n} clip(s): {reason}")

            if not clips:
                self.log_line.emit("ERROR: No clips found in library cache.")
                return

            selected_games = len({path_games.get(p, "?") for p in clips})
            self.log_line.emit(
                f"Selected {len(clips)} clip(s) from {selected_games} game(s)"
            )

            out_dir = Path(self._output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            total_jobs = 0
            pass_count = fail_count = skip_count = 0
            all_results: list[dict] = []

            for ci, clip_dir in enumerate(clips):
                if self._cancelled:
                    self.log_line.emit("— Cancelled —")
                    break
                clip_name = Path(clip_dir).name
                game_name = path_games.get(clip_dir, "?")
                src_path = _source_video_path(clip_dir)
                if not src_path:
                    self.log_line.emit(
                        f"[{ci+1}/{len(clips)}] SKIP {clip_name} ({game_name}) — no video path"
                    )
                    skip_count += 1
                    all_results.append({
                        "clip": clip_dir, "game": game_name,
                        "skipped": True, "reason": "no video path",
                    })
                    continue
                src_probe = _ffprobe(src_path)
                if not src_probe:
                    self.log_line.emit(
                        f"[{ci+1}/{len(clips)}] SKIP {clip_name} ({game_name}) — ffprobe failed"
                    )
                    skip_count += 1
                    all_results.append({
                        "clip": clip_dir, "game": game_name,
                        "skipped": True, "reason": "ffprobe failed",
                    })
                    continue

                vs = _video_stream(src_probe)
                src_h = int(vs.get("height", 1080)) if vs else 1080
                try:
                    rn, rd = (vs.get("r_frame_rate", "30/1") if vs else "30/1").split("/")
                    src_fps = round(float(rn) / float(rd), 1)
                except (ValueError, ZeroDivisionError):
                    src_fps = 30.0

                src_dur = float(src_probe.get("format", {}).get("duration", 0))

                presets = _generate_presets(
                    src_h, src_fps, self._presets_per_clip,
                    self._resolutions, self._codecs,
                    self._bitrate_presets, self._fps_options,
                    self._include_target_size_mode,
                    self._target_size_presets,
                    self._custom_target_min_mb,
                    self._custom_target_max_mb,
                )

                for preset in presets:
                    if self._cancelled:
                        break
                    total_jobs += 1
                    out_path = out_dir / f"{clip_name}_{preset.label}.mp4"
                    cmd = ["ffmpeg", "-y"]

                    # Trimming logic
                    seg_dur = self._max_render_dur if self._max_render_dur > 0 else 0
                    if seg_dur > 0 and src_dur > seg_dur:
                        if self._random_trim:
                            max_start = max(0, src_dur - seg_dur)
                            ss = round(random.uniform(0, max_start), 2)
                            cmd += ["-ss", str(ss)]
                        cmd += ["-t", str(seg_dur)]

                    cmd += ["-i", str(src_path)]

                    vf_parts = []
                    if preset.resolution:
                        vf_parts.append(f"scale=-2:{preset.resolution}")
                    if preset.fps:
                        vf_parts.append(f"fps={preset.fps}")
                    if vf_parts:
                        cmd += ["-vf", ",".join(vf_parts)]

                    cmd += ["-c:v", preset.codec]

                    if preset.mode == "target_size" and preset.target_size_mb:
                        target_mb = min(int(preset.target_size_mb), TARGET_SIZE_MAX_MB)
                        effective_dur = min(src_dur, seg_dur) if seg_dur > 0 else src_dur
                        if effective_dur <= 0:
                            effective_dur = src_dur if src_dur > 0 else 1.0
                        audio_kbps = 128
                        target_total_kbps = int(target_mb * 8192 / effective_dur * 0.96)
                        video_kbps = max(100, target_total_kbps - audio_kbps)
                        cmd += [
                            "-b:v", f"{video_kbps}k",
                            "-maxrate", f"{video_kbps}k",
                            "-bufsize", f"{max(200, video_kbps * 2)}k",
                        ]
                    elif preset.bitrate_preset:
                        h = preset.resolution or src_h
                        mbps = _bitrate_for(preset.bitrate_preset, h)
                        kbps = int(mbps * 1000)
                        cmd += ["-b:v", f"{kbps}k", "-maxrate", f"{int(kbps*1.5)}k",
                                "-bufsize", f"{kbps*2}k"]

                    cmd += ["-c:a", "aac", "-b:a", "128k", str(out_path)]

                    self.log_line.emit(f"[{ci+1}/{len(clips)}] {clip_name} / {preset.label} ...")

                    try:
                        r = subprocess.run(
                            cmd, capture_output=True, text=True, timeout=600,
                            **subprocess_hide_console_kwargs(),
                        )
                        if r.returncode != 0:
                            fail_count += 1
                            self.log_line.emit(f"  FAIL — ffmpeg exit {r.returncode}")
                            all_results.append({"clip": clip_dir, "preset": preset.label,
                                                "passed": False, "error": r.stderr[-300:]})
                        else:
                            # Quick probe check
                            out_probe = _ffprobe(out_path)
                            if out_probe and out_path.exists() and out_path.stat().st_size > 0:
                                if preset.mode == "target_size" and preset.target_size_mb:
                                    target_mb = min(int(preset.target_size_mb), TARGET_SIZE_MAX_MB)
                                    actual_mb = out_path.stat().st_size / (1024 * 1024)
                                    low_mb = target_mb * (1.0 - TARGET_SIZE_TOLERANCE)
                                    high_mb = target_mb * (1.0 + TARGET_SIZE_TOLERANCE)
                                    passed = low_mb <= actual_mb <= high_mb
                                    delta_pct = ((actual_mb - target_mb) / max(target_mb, 1)) * 100.0
                                    if passed:
                                        pass_count += 1
                                        self.log_line.emit(
                                            f"  PASS — target {target_mb} MB, actual {actual_mb:.1f} MB "
                                            f"(tol {int(TARGET_SIZE_TOLERANCE*100)}%, delta {delta_pct:+.1f}%)"
                                        )
                                    else:
                                        fail_count += 1
                                        self.log_line.emit(
                                            f"  FAIL — target {target_mb} MB, actual {actual_mb:.1f} MB "
                                            f"(expected {low_mb:.1f}-{high_mb:.1f} MB)"
                                        )
                                    all_results.append(
                                        {
                                            "clip": clip_dir,
                                            "preset": preset.label,
                                            "mode": "target_size",
                                            "target_mb": target_mb,
                                            "actual_mb": round(actual_mb, 2),
                                            "tolerance_pct": int(TARGET_SIZE_TOLERANCE * 100),
                                            "expected_mb_min": round(low_mb, 2),
                                            "expected_mb_max": round(high_mb, 2),
                                            "delta_pct": round(delta_pct, 2),
                                            "passed": passed,
                                        }
                                    )
                                else:
                                    pass_count += 1
                                    self.log_line.emit(f"  PASS")
                                    all_results.append({"clip": clip_dir, "preset": preset.label, "passed": True})
                            else:
                                fail_count += 1
                                self.log_line.emit(f"  FAIL — output unreadable or empty")
                                all_results.append({"clip": clip_dir, "preset": preset.label,
                                                    "passed": False, "error": "probe failed"})
                    except subprocess.TimeoutExpired:
                        fail_count += 1
                        self.log_line.emit(f"  FAIL — timeout")
                        all_results.append({"clip": clip_dir, "preset": preset.label,
                                            "passed": False, "error": "timeout"})
                    except Exception as exc:
                        fail_count += 1
                        self.log_line.emit(f"  FAIL — {exc}")
                        all_results.append({"clip": clip_dir, "preset": preset.label,
                                            "passed": False, "error": str(exc)})

                    self.progress.emit(pass_count + fail_count + skip_count,
                                       len(clips) * self._presets_per_clip,
                                       pass_count, fail_count)

            summary = f"{pass_count} PASS, {fail_count} FAIL, {skip_count} SKIP"
            self.log_line.emit(f"\n{'='*50}\n{summary}\n{'='*50}")

            # Write JSON report
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_dir = Path(self._cache_dir).parent / "logs"
            log_dir.mkdir(exist_ok=True)
            report_path = log_dir / f"diag_render_qa_{stamp}.json"
            report = {
                "timestamp": stamp,
                "pool_size": stats["pool_size"],
                "games_in_pool": stats["games_in_pool"],
                "clip_count": len(clips),
                "total_pass": pass_count,
                "total_fail": fail_count,
                "total_skip": skip_count,
                "jobs": all_results,
            }
            try:
                report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
                self.log_line.emit(f"Report: {report_path}")
            except Exception as exc:
                self.log_line.emit(f"Failed to write report: {exc}")
        except Exception as exc:
            self.log_line.emit(f"ERROR: Render QA worker crashed: {exc}")
            _log.exception("Render QA worker failed")
        finally:
            self.finished_all.emit(str(report_path) if report_path else "")


# ── Filters QA worker ───────────────────────────────────────────────────────
class _FiltersQAWorker(QThread):
    log_line = Signal(str)
    finished_all = Signal()

    def __init__(self, cache_dir: str):
        super().__init__()
        self._cache_dir = cache_dir

    def run(self):
        try:
            repo = Path(self._cache_dir).parent
            script = repo / "scripts" / "diag_filters_qa.py"
            if not script.exists():
                self.log_line.emit("ERROR: scripts/diag_filters_qa.py not found")
                self.finished_all.emit()
                return
            import sys
            r = subprocess.run(
                [sys.executable, str(script), "--verbose"],
                capture_output=True, text=True, timeout=120,
                cwd=str(repo),
                **subprocess_hide_console_kwargs(),
            )
            for line in (r.stdout + r.stderr).splitlines():
                self.log_line.emit(line)
        except Exception as exc:
            self.log_line.emit(f"ERROR: {exc}")
        self.finished_all.emit()


# ── System Info worker ───────────────────────────────────────────────────────
class _SystemInfoWorker(QThread):
    log_line = Signal(str)
    finished_all = Signal()

    def __init__(self, cache_dir: str):
        super().__init__()
        self._cache_dir = cache_dir

    def run(self):
        try:
            repo = Path(self._cache_dir).parent
            script = repo / "scripts" / "diag_system.py"
            if not script.exists():
                self.log_line.emit("ERROR: scripts/diag_system.py not found")
                self.finished_all.emit()
                return
            import sys
            r = subprocess.run(
                [sys.executable, str(script), "--verbose"],
                capture_output=True, text=True, timeout=60,
                cwd=str(repo),
                **subprocess_hide_console_kwargs(),
            )
            for line in (r.stdout + r.stderr).splitlines():
                self.log_line.emit(line)
        except Exception as exc:
            self.log_line.emit(f"ERROR: {exc}")
        self.finished_all.emit()


# ══════════════════════════════════════════════════════════════════════════════
# Dialog
# ══════════════════════════════════════════════════════════════════════════════

_SECTION_QSS = f"""
    QGroupBox {{
        color: {tok.TEXT_PRIMARY};
        font-family: {tok.FONT_UI};
        font-weight: bold;
        border: 1px solid #3a3a3a;
        border-radius: 6px;
        margin-top: 8px;
        padding: 12px 8px 8px 8px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }}
    QLabel {{
        color: {tok.TEXT_PRIMARY};
        font-family: {tok.FONT_UI};
    }}
    QSpinBox, QLineEdit {{
        background: #2a2a2a;
        color: {tok.TEXT_PRIMARY};
        border: 1px solid #444;
        border-radius: 4px;
        padding: 3px 6px;
        font-family: {tok.FONT_UI};
    }}
    QCheckBox {{
        color: {tok.TEXT_PRIMARY};
        font-family: {tok.FONT_UI};
        spacing: 5px;
    }}
    QCheckBox::indicator {{
        width: 14px; height: 14px;
        border: 1px solid #555; border-radius: 3px;
        background: #2a2a2a;
    }}
    QCheckBox::indicator:checked {{
        background: {tok.ACCENT_PRIMARY};
        border-color: {tok.ACCENT_PRIMARY};
    }}
    QPushButton {{
        font-family: {tok.FONT_UI};
        font-weight: bold;
        background: #383838;
        color: #fff;
        border: 1px solid #555;
        border-radius: 5px;
        padding: 6px 16px;
    }}
    QPushButton:hover {{ background: #484848; border-color: #7b6b9e; }}
    QPushButton:pressed {{ background: #3a324a; }}
    QPushButton:disabled {{ background: #252525; color: #555; }}
    QProgressBar {{
        background: #2a2a2a;
        border: 1px solid #444;
        border-radius: 4px;
        text-align: center;
        color: {tok.TEXT_PRIMARY};
        font-family: {tok.FONT_UI};
    }}
    QProgressBar::chunk {{
        background: {tok.ACCENT_PRIMARY};
        border-radius: 3px;
    }}
    QPlainTextEdit {{
        background: #1a1a1a;
        color: #ccc;
        border: 1px solid #333;
        border-radius: 4px;
        font-family: 'Cascadia Mono', 'Consolas', monospace;
        font-size: 11px;
    }}
    QTabWidget::pane {{
        border: 1px solid #3a3a3a;
        border-radius: 4px;
        background: transparent;
    }}
    QTabBar::tab {{
        background: #2a2a2a;
        color: {tok.TEXT_PRIMARY};
        font-family: {tok.FONT_UI};
        font-weight: bold;
        padding: 6px 14px;
        border: 1px solid #3a3a3a;
        border-bottom: none;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
    }}
    QTabBar::tab:selected {{
        background: #383838;
        border-color: {tok.ACCENT_PRIMARY};
    }}
    QTabBar::tab:hover {{ background: #3a3a3a; }}
"""


class DevModeDialog(SteempegDialog):
    def __init__(self, cache_dir: str, parent=None):
        super().__init__("Developer Tools", parent)
        self._cache_dir = cache_dir
        self._worker: _RenderQAWorker | None = None
        self._filters_worker: _FiltersQAWorker | None = None
        self._system_worker: _SystemInfoWorker | None = None
        self._dev_size_default = (720, 760)
        self._dev_size_deck_pad = (920, 640)
        self.set_comfort_size(*self._dev_size_default)

        root = self.content_layout
        root.setContentsMargins(12, 8, 12, 12)

        tabs = QTabWidget()
        tabs.setStyleSheet(_SECTION_QSS)
        root.addWidget(tabs, 1)

        tabs.addTab(self._build_render_qa_tab(), "Render QA")
        tabs.addTab(self._build_tools_tab(), "Tools")
        tabs.addTab(self._build_deck_pad_tab(), "Deck pad")
        self._dev_tabs = tabs
        tabs.currentChanged.connect(self._on_dev_tab_changed)

    # ── Render QA Tab ────────────────────────────────────────────────────────

    def _build_render_qa_tab(self) -> QWidget:
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        from steempeg.ui.library.library_styles import (
            LIBRARY_SCROLLBAR_VERTICAL,
            install_library_vertical_scrollbar,
        )

        scroll.setStyleSheet("QScrollArea { border: none; }" + LIBRARY_SCROLLBAR_VERTICAL)
        install_library_vertical_scrollbar(scroll)

        lay = QVBoxLayout(page)
        lay.setSpacing(8)

        # -- Clip Selection --
        g1 = QGroupBox("Clip Selection")
        g1l = QVBoxLayout(g1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Clip count:"))
        self._spin_count = QSpinBox()
        self._spin_count.setRange(1, 500)
        self._spin_count.setValue(10)
        row.addWidget(self._spin_count)
        row.addSpacing(16)
        row.addWidget(QLabel("Max clip duration (min):"))
        self._spin_max_clip = QSpinBox()
        self._spin_max_clip.setRange(1, 600)
        self._spin_max_clip.setValue(10)
        row.addWidget(self._spin_max_clip)
        row.addStretch()
        g1l.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Exclude games:"))
        self._txt_exclude_games = QLineEdit()
        self._txt_exclude_games.setPlaceholderText("Game1, Game2, ...")
        row2.addWidget(self._txt_exclude_games, 1)
        g1l.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Exclude clips:"))
        self._txt_exclude_clips = QLineEdit()
        self._txt_exclude_clips.setPlaceholderText("path1, path2, ...")
        row3.addWidget(self._txt_exclude_clips, 1)
        g1l.addLayout(row3)

        lay.addWidget(g1)

        # -- Preset Priority --
        g2 = QGroupBox("Preset Priority")
        g2l = QVBoxLayout(g2)

        g2l.addWidget(QLabel("Resolutions:"))
        res_row = QHBoxLayout()
        self._cb_res: dict[str, QCheckBox] = {}
        for label in ["144p", "240p", "360p", "480p", "720p", "1080p", "Original"]:
            cb = QCheckBox(label)
            cb.setChecked(True)
            self._cb_res[label] = cb
            res_row.addWidget(cb)
        res_row.addStretch()
        g2l.addLayout(res_row)

        g2l.addWidget(QLabel("Codecs:"))
        codec_row = QHBoxLayout()
        self._cb_codecs: dict[str, QCheckBox] = {}
        for label in ["H.264", "H.265"]:
            cb = QCheckBox(label)
            cb.setChecked(True)
            self._cb_codecs[label] = cb
            codec_row.addWidget(cb)
        codec_row.addStretch()
        g2l.addLayout(codec_row)

        g2l.addWidget(QLabel("Bitrate presets:"))
        br_row = QHBoxLayout()
        self._cb_bitrate: dict[str, QCheckBox] = {}
        for label in ["Ultra", "High", "Medium", "Low", "Original"]:
            cb = QCheckBox(label)
            cb.setChecked(True)
            self._cb_bitrate[label] = cb
            br_row.addWidget(cb)
        br_row.addStretch()
        g2l.addLayout(br_row)

        g2l.addWidget(QLabel("FPS:"))
        fps_row = QHBoxLayout()
        self._cb_fps: dict[str, QCheckBox] = {}
        for label in ["30", "60", "Original"]:
            cb = QCheckBox(label)
            cb.setChecked(True)
            self._cb_fps[label] = cb
            fps_row.addWidget(cb)
        fps_row.addStretch()
        g2l.addLayout(fps_row)

        ppc_row = QHBoxLayout()
        ppc_row.addWidget(QLabel("Presets per clip:"))
        self._spin_presets = QSpinBox()
        self._spin_presets.setRange(1, 50)
        self._spin_presets.setValue(3)
        ppc_row.addWidget(self._spin_presets)
        ppc_row.addStretch()
        g2l.addLayout(ppc_row)

        lay.addWidget(g2)

        # -- Trimming --
        g3 = QGroupBox("Trimming / Duration")
        g3l = QHBoxLayout(g3)
        g3l.addWidget(QLabel("Max render duration (s):"))
        self._spin_render_dur = QSpinBox()
        self._spin_render_dur.setRange(0, 36000)
        self._spin_render_dur.setValue(10)
        self._spin_render_dur.setSpecialValueText("Full")
        g3l.addWidget(self._spin_render_dur)
        g3l.addSpacing(16)
        self._cb_random_trim = QCheckBox("Random trim")
        self._cb_random_trim.setChecked(True)
        g3l.addWidget(self._cb_random_trim)
        g3l.addStretch()
        lay.addWidget(g3)

        # -- Target File Size --
        g_target = QGroupBox("Target File Size")
        gtl = QVBoxLayout(g_target)
        self._cb_include_target_size = QCheckBox("Include Target File Size mode")
        self._cb_include_target_size.setChecked(False)
        gtl.addWidget(self._cb_include_target_size)

        preset_row = QHBoxLayout()
        self._cb_target_size_presets: dict[str, QCheckBox] = {}
        for label in ["Tiny", "Small", "Medium", "Large", "XL", "Custom"]:
            cb = QCheckBox(label)
            cb.setChecked(label != "Custom")
            self._cb_target_size_presets[label] = cb
            preset_row.addWidget(cb)
        preset_row.addStretch()
        gtl.addLayout(preset_row)

        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Min custom size (MB):"))
        self._spin_target_custom_min = QSpinBox()
        self._spin_target_custom_min.setRange(1, TARGET_SIZE_MAX_MB)
        self._spin_target_custom_min.setValue(50)
        custom_row.addWidget(self._spin_target_custom_min)
        custom_row.addSpacing(16)
        custom_row.addWidget(QLabel("Max custom size (MB):"))
        self._spin_target_custom_max = QSpinBox()
        self._spin_target_custom_max.setRange(1, TARGET_SIZE_MAX_MB)
        self._spin_target_custom_max.setValue(500)
        custom_row.addWidget(self._spin_target_custom_max)
        custom_row.addWidget(QLabel("(max 1024 MB)"))
        custom_row.addStretch()
        gtl.addLayout(custom_row)
        lay.addWidget(g_target)

        # -- Output --
        g4 = QGroupBox("Output")
        g4l = QHBoxLayout(g4)
        self._txt_output_dir = QLineEdit()
        default_out = os.path.join(os.path.dirname(self._cache_dir), "logs", "diag_output")
        self._txt_output_dir.setText(default_out)
        g4l.addWidget(self._txt_output_dir, 1)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_output_dir)
        g4l.addWidget(btn_browse)
        self._cb_verbose = QCheckBox("Verbose")
        g4l.addWidget(self._cb_verbose)
        lay.addWidget(g4)

        # -- Actions --
        action_row = QHBoxLayout()
        self._btn_run = QPushButton("▶  Run")
        self._btn_run.setStyleSheet(
            self._btn_run.styleSheet()
            + "QPushButton { background: #2e6b32; border-color: #3e8e41; }"
            "QPushButton:hover { background: #3e8e41; }"
        )
        self._btn_run.clicked.connect(self._start_render_qa)
        action_row.addWidget(self._btn_run)
        self._btn_stop = QPushButton("■  Stop")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_render_qa)
        action_row.addWidget(self._btn_stop)
        action_row.addStretch()
        lay.addLayout(action_row)

        # -- Progress --
        self._lbl_progress = QLabel("")
        lay.addWidget(self._lbl_progress)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        lay.addWidget(self._progress_bar)

        # -- Log --
        self._log_area = QPlainTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setMaximumBlockCount(5000)
        lay.addWidget(self._log_area, 1)

        lay.addStretch()

        # Wrap in a container so scroll works
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(scroll, 1)
        return container

    # ── Tools Tab ────────────────────────────────────────────────────────────

    def _build_tools_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(10)

        btn_filters = QPushButton("Run Filters QA")
        btn_filters.clicked.connect(self._run_filters_qa)
        lay.addWidget(btn_filters)

        btn_system = QPushButton("Run System Info")
        btn_system.clicked.connect(self._run_system_info)
        lay.addWidget(btn_system)

        btn_ffmpeg_err = QPushButton("Simulate FFmpeg error dialog")
        btn_ffmpeg_err.setToolTip(
            "Show the Render Failed window with sample FFmpeg logs "
            "(cycles disk full / OOM / encoder / permission / … — "
            "TrueDark / theme visual checks, no real encode)."
        )
        btn_ffmpeg_err.clicked.connect(self._simulate_ffmpeg_error_dialog)
        lay.addWidget(btn_ffmpeg_err)

        # -- Splitter movement telemetry (layout debugging) --
        g_split = QGroupBox("Splitter movement telemetry")
        g_split_lay = QVBoxLayout(g_split)
        g_split_lay.addWidget(
            QLabel(
                "Opt-in layout debug for main / right-h / main-v splitters. "
                "Logs sizes, callers, and blockers to the session steempeg_*.log "
                "([splitter-tel]). Off = no hooks."
            )
        )
        self._chk_splitter_tel = QCheckBox("Track splitter movement")
        self._chk_splitter_tel.setToolTip(
            "Wrap setSizes + splitterMoved on tracked splitters. "
            "Persists as dev_splitter_telemetry in settings.json."
        )
        self._chk_splitter_tel_overlay = QCheckBox("On-screen overlay (last events)")
        self._chk_splitter_tel_overlay.setToolTip(
            "Floating corner readout. Persists as "
            "dev_splitter_telemetry_overlay in settings.json."
        )
        tel_row = QHBoxLayout()
        btn_dump = QPushButton("Dump snapshot now")
        btn_dump.setToolTip("One-shot log of current sizes / mins / blockers.")
        btn_dump.clicked.connect(self._dump_splitter_telemetry)
        tel_row.addWidget(btn_dump)
        tel_row.addStretch()
        g_split_lay.addWidget(self._chk_splitter_tel)
        g_split_lay.addWidget(self._chk_splitter_tel_overlay)
        g_split_lay.addLayout(tel_row)
        lay.addWidget(g_split)

        self._chk_splitter_tel.toggled.connect(self._on_splitter_tel_toggled)
        self._chk_splitter_tel_overlay.toggled.connect(
            self._on_splitter_tel_overlay_toggled
        )
        self._sync_splitter_tel_checkboxes()

        self._tools_log = QPlainTextEdit()
        self._tools_log.setReadOnly(True)
        self._tools_log.setMaximumBlockCount(5000)
        lay.addWidget(self._tools_log, 1)

        return page

    def _on_dev_tab_changed(self, index: int) -> None:
        name = self._dev_tabs.tabText(index)
        if name == "Deck pad":
            self.set_comfort_size(*self._dev_size_deck_pad)
        else:
            self.set_comfort_size(*self._dev_size_default)

    def _build_deck_pad_tab(self) -> QWidget:
        """Virtual Steam Deck face — taps feed ``steempeg.input.gamepad`` bus."""
        from steempeg.input.gamepad import DeckButton, OS_ONLY_BUTTONS, gamepad_bus

        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(10)

        tip = QLabel(
            "Same bus as a real pad. Enable Settings → General → Shell → Console mode "
            "(or Developer mode). View → Choose a Clip · Menu → Render · Y Trim · "
            "A play (trim: set end) · X queue (trim: set start) · "
            "L1/R1 ±15s · R2 fullscreen · L2 jump trim start. "
            "Sheets + Settings: L1/R1 tabs · D-pad focus · A · B. "
            "STEAM / QAM are SteamOS-only."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #b0b0b0;")
        lay.addWidget(tip)

        pad_px = 52

        def _mk(
            label: str,
            btn: DeckButton,
            *,
            enabled: bool = True,
            tooltip: str = "",
        ) -> QPushButton:
            b = QPushButton(label)
            b.setEnabled(enabled)
            if tooltip:
                b.setToolTip(tooltip)
            if enabled:
                b.clicked.connect(lambda *_args, button=btn: gamepad_bus().tap(button))
            elif not tooltip:
                b.setToolTip("SteamOS overlay — not bound in Steempeg")
            return b

        def _wide(label: str, btn: DeckButton, *, enabled: bool = True) -> QPushButton:
            b = _mk(label, btn, enabled=enabled)
            b.setMinimumHeight(44)
            b.setMaximumHeight(48)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return b

        def _key(label: str, btn: DeckButton, *, tooltip: str = "") -> QPushButton:
            b = _mk(label, btn, tooltip=tooltip)
            b.setFixedSize(pad_px, pad_px)
            return b

        def _diamond(cells: list[tuple[int, int, QPushButton]]) -> QWidget:
            wrap = QWidget()
            grid = QGridLayout(wrap)
            grid.setContentsMargins(0, 4, 0, 4)
            grid.setSpacing(6)
            for row, col, widget in cells:
                grid.addWidget(widget, row, col)
            return wrap

        g_left = QGroupBox("Left")
        left = QVBoxLayout(g_left)
        left.setSpacing(8)
        left.addWidget(_wide("View", DeckButton.VIEW))
        left.addWidget(
            _diamond(
                [
                    (0, 1, _key("▲", DeckButton.DPAD_UP)),
                    (1, 0, _key("◀", DeckButton.DPAD_LEFT)),
                    (1, 2, _key("▶", DeckButton.DPAD_RIGHT)),
                    (2, 1, _key("▼", DeckButton.DPAD_DOWN)),
                ]
            )
        )
        left.addWidget(_wide("L1", DeckButton.L1))
        left.addWidget(_wide("L2", DeckButton.L2))
        left.addWidget(_wide("STEAM (OS)", DeckButton.STEAM, enabled=False))

        g_right = QGroupBox("Right")
        right = QVBoxLayout(g_right)
        right.setSpacing(8)
        right.addWidget(_wide("Menu → Render", DeckButton.MENU))
        right.addWidget(
            _diamond(
                [
                    (0, 1, _key("Y", DeckButton.Y, tooltip="Trim")),
                    (1, 0, _key("X", DeckButton.X, tooltip="Add to queue")),
                    (1, 2, _key("B", DeckButton.B, tooltip="Close / back")),
                    (2, 1, _key("A", DeckButton.A, tooltip="Play / confirm")),
                ]
            )
        )
        right.addWidget(_wide("R1", DeckButton.R1))
        right.addWidget(_wide("R2", DeckButton.R2))
        right.addWidget(_wide("QAM … (OS)", DeckButton.QAM, enabled=False))

        clusters = QHBoxLayout()
        clusters.setSpacing(12)
        clusters.addWidget(g_left, 1)
        clusters.addWidget(g_right, 1)
        lay.addLayout(clusters)
        lay.addStretch(1)
        page.setMinimumSize(700, 480)

        _ = OS_ONLY_BUTTONS

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        from steempeg.ui.library.library_styles import (
            LIBRARY_SCROLLBAR_VERTICAL,
            install_library_vertical_scrollbar,
        )

        scroll.setStyleSheet("QScrollArea { border: none; }" + LIBRARY_SCROLLBAR_VERTICAL)
        install_library_vertical_scrollbar(scroll)

        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(scroll, 1)
        return container

    # ── Slots ────────────────────────────────────────────────────────────────

    def _browse_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Output Directory", self._txt_output_dir.text())
        if d:
            self._txt_output_dir.setText(d)

    def _collect_resolutions(self) -> list[int | None]:
        res = []
        mapping = {"144p": 144, "240p": 240, "360p": 360, "480p": 480,
                    "720p": 720, "1080p": 1080, "Original": None}
        for label, val in mapping.items():
            if self._cb_res.get(label) and self._cb_res[label].isChecked():
                res.append(val)
        return res or [None]

    def _collect_codecs(self) -> list[str]:
        mapping = {"H.264": "libx264", "H.265": "libx265"}
        out = [v for k, v in mapping.items()
               if self._cb_codecs.get(k) and self._cb_codecs[k].isChecked()]
        return out or ["libx264"]

    def _collect_bitrate_presets(self) -> list[str | None]:
        out: list[str | None] = []
        for label in ["Ultra", "High", "Medium", "Low"]:
            if self._cb_bitrate.get(label) and self._cb_bitrate[label].isChecked():
                out.append(label)
        if self._cb_bitrate.get("Original") and self._cb_bitrate["Original"].isChecked():
            out.append(None)
        return out or [None]

    def _collect_fps(self) -> list[int | None]:
        out: list[int | None] = []
        mapping = {"30": 30, "60": 60, "Original": None}
        for label, val in mapping.items():
            if self._cb_fps.get(label) and self._cb_fps[label].isChecked():
                out.append(val)
        return out or [None]

    def _collect_target_size_presets(self) -> list[str]:
        out: list[str] = []
        for label in ["Tiny", "Small", "Medium", "Large", "XL", "Custom"]:
            cb = self._cb_target_size_presets.get(label)
            if cb and cb.isChecked():
                out.append(label)
        return out

    def _validate_target_size_inputs(self) -> tuple[bool, int, int]:
        min_mb = max(1, min(self._spin_target_custom_min.value(), TARGET_SIZE_MAX_MB))
        max_mb = max(1, min(self._spin_target_custom_max.value(), TARGET_SIZE_MAX_MB))
        if min_mb > max_mb:
            return False, min_mb, max_mb
        return True, min_mb, max_mb

    def _start_render_qa(self):
        if self._worker and self._worker.isRunning():
            self._log_area.appendPlainText(
                "ERROR: A run is still in progress — click Stop or wait for it to finish."
            )
            return

        custom_ok, custom_min_mb, custom_max_mb = self._validate_target_size_inputs()
        if not custom_ok:
            self._log_area.appendPlainText(
                "ERROR: Target File Size custom range invalid (min must be <= max)."
            )
            self._lbl_progress.setText("Invalid Target File Size range.")
            return

        include_target_size = self._cb_include_target_size.isChecked()
        target_size_presets = self._collect_target_size_presets()
        if include_target_size and not target_size_presets:
            self._log_area.appendPlainText(
                "ERROR: Enable at least one Target File Size preset (or Custom)."
            )
            self._lbl_progress.setText("No Target File Size preset selected.")
            return

        exclude_games = {g.strip() for g in self._txt_exclude_games.text().split(",") if g.strip()}
        exclude_paths = {p.strip() for p in self._txt_exclude_clips.text().split(",") if p.strip()}

        self._log_area.clear()
        self._progress_bar.setValue(0)
        self._lbl_progress.setText("Starting...")
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)

        self._worker = _RenderQAWorker(
            cache_dir=self._cache_dir,
            clip_count=self._spin_count.value(),
            presets_per_clip=self._spin_presets.value(),
            max_clip_dur_s=self._spin_max_clip.value() * 60,
            max_render_dur_s=self._spin_render_dur.value(),
            random_trim=self._cb_random_trim.isChecked(),
            resolutions=self._collect_resolutions(),
            codecs=self._collect_codecs(),
            bitrate_presets=self._collect_bitrate_presets(),
            fps_options=self._collect_fps(),
            include_target_size_mode=include_target_size,
            target_size_presets=target_size_presets,
            custom_target_min_mb=custom_min_mb,
            custom_target_max_mb=custom_max_mb,
            exclude_games=exclude_games,
            exclude_paths=exclude_paths,
            output_dir=self._txt_output_dir.text(),
            verbose=self._cb_verbose.isChecked(),
        )
        self._worker.log_line.connect(self._on_log_line)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.finished.connect(self._on_worker_thread_finished)
        self._worker.start()

    def _on_worker_thread_finished(self):
        """Safety net if finished_all was missed."""
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)

    def _stop_render_qa(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._lbl_progress.setText("Cancelling...")

    @Slot(str)
    def _on_log_line(self, line: str):
        self._log_area.appendPlainText(line)

    @Slot(int, int, int, int)
    def _on_progress(self, done: int, total: int, pass_c: int, fail_c: int):
        pct = int(done / max(total, 1) * 100)
        self._progress_bar.setValue(pct)
        self._lbl_progress.setText(f"{done}/{total}  —  {pass_c} pass, {fail_c} fail")

    @Slot(str)
    def _on_finished(self, report_path: str):
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        if report_path:
            self._lbl_progress.setText(f"Done. Report: {Path(report_path).name}")
        else:
            self._lbl_progress.setText("Done (no report).")

    # -- Tools tab actions --
    def _run_filters_qa(self):
        if self._filters_worker and self._filters_worker.isRunning():
            return
        self._tools_log.clear()
        self._tools_log.appendPlainText("Running Filters QA...")
        self._filters_worker = _FiltersQAWorker(self._cache_dir)
        self._filters_worker.log_line.connect(lambda l: self._tools_log.appendPlainText(l))
        self._filters_worker.finished_all.connect(
            lambda: self._tools_log.appendPlainText("\n— Filters QA complete —"))
        self._filters_worker.start()

    def _run_system_info(self):
        if self._system_worker and self._system_worker.isRunning():
            return
        self._tools_log.clear()
        self._tools_log.appendPlainText("Collecting System Info...")
        self._system_worker = _SystemInfoWorker(self._cache_dir)
        self._system_worker.log_line.connect(lambda l: self._tools_log.appendPlainText(l))
        self._system_worker.finished_all.connect(
            lambda: self._tools_log.appendPlainText("\n— System Info complete —"))
        self._system_worker.start()

    def _resolve_app_host(self):
        """Walk parents for MainWindow._app_host (SteempegApp)."""
        parent = self.parent()
        while parent is not None:
            host = getattr(parent, "_app_host", None)
            if host is not None:
                return host
            parent = parent.parent() if hasattr(parent, "parent") else None
        return None

    def _sync_splitter_tel_checkboxes(self) -> None:
        from steempeg.ui.splitter_telemetry import get_splitter_telemetry

        ctl = get_splitter_telemetry()
        host = self._resolve_app_host()
        if host is not None:
            ctl.attach_host(host)
        for chk, val in (
            (self._chk_splitter_tel, ctl.enabled),
            (self._chk_splitter_tel_overlay, ctl.overlay_enabled),
        ):
            chk.blockSignals(True)
            chk.setChecked(bool(val))
            chk.blockSignals(False)

    def _on_splitter_tel_toggled(self, checked: bool) -> None:
        from steempeg.ui.splitter_telemetry import get_splitter_telemetry

        host = self._resolve_app_host()
        ctl = get_splitter_telemetry()
        if host is not None:
            ctl.attach_host(host)
        ctl.set_enabled(
            bool(checked),
            overlay=self._chk_splitter_tel_overlay.isChecked(),
            persist=True,
        )
        self._tools_log.appendPlainText(
            "Splitter telemetry "
            + ("ON — drag handles / open RQ / theater; see [splitter-tel] in logs."
               if checked
               else "OFF.")
        )

    def _on_splitter_tel_overlay_toggled(self, checked: bool) -> None:
        from steempeg.ui.splitter_telemetry import get_splitter_telemetry

        ctl = get_splitter_telemetry()
        host = self._resolve_app_host()
        if host is not None:
            ctl.attach_host(host)
        ctl.set_overlay(bool(checked), persist=True)
        self._tools_log.appendPlainText(
            "Splitter telemetry overlay " + ("ON." if checked else "OFF.")
        )

    def _dump_splitter_telemetry(self) -> None:
        from steempeg.ui.splitter_telemetry import get_splitter_telemetry

        host = self._resolve_app_host()
        ctl = get_splitter_telemetry()
        if host is not None:
            ctl.attach_host(host)
        was_on = ctl.enabled
        if not was_on:
            # Temporarily arm so dump lines are emitted + ring updated.
            ctl.set_enabled(True, overlay=ctl.overlay_enabled, persist=False)
        try:
            text = ctl.dump_snapshot("manual_dump")
            self._tools_log.appendPlainText(text)
            self._tools_log.appendPlainText(
                "(also written to session steempeg_*.log as [splitter-tel])"
            )
        finally:
            if not was_on:
                ctl.set_enabled(False, overlay=ctl.overlay_enabled, persist=False)

    def _simulate_ffmpeg_error_dialog(self):
        """Open the real Render Failed chrome with classified sample logs (theme QA)."""
        from steempeg.render.ffmpeg_error_hints import (
            classify_ffmpeg_error,
            next_simulate_sample,
        )

        host = self._resolve_app_host()
        if host is None or not hasattr(host, "_show_steempeg_render_error_dialog"):
            self._tools_log.appendPlainText(
                "ERROR: Could not reach the render controller to show the FFmpeg error dialog."
            )
            return

        idx = int(getattr(self, "_ffmpeg_err_sim_index", 0) or 0)
        next_idx, kind, sample = next_simulate_sample(idx)
        self._ffmpeg_err_sim_index = next_idx
        hint = classify_ffmpeg_error(sample)
        self._tools_log.appendPlainText(
            f"Showing simulated FFmpeg error dialog ({kind} → {hint.message!r})…"
        )
        try:
            host._show_steempeg_render_error_dialog(sample)
        except Exception as exc:
            self._tools_log.appendPlainText(f"ERROR: simulate failed: {exc}")
