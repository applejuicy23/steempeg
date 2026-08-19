#!/usr/bin/env python3
"""Render Pipeline QA — diagnostic test suite for Steempeg.

Picks random clips from the library cache, renders them with varied presets,
probes the output with ffprobe, and reports PASS/FAIL per metric.

Usage:
    python scripts/diag_render_qa.py                        # 10 clips, full length
    python scripts/diag_render_qa.py --count 5 --light      # 5 clips, first 5 s only
    python scripts/diag_render_qa.py --clips-dir W:\\clips   # explicit clip folder
    python scripts/diag_render_qa.py --verbose               # per-metric detail
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from steempeg.infra.process import subprocess_hide_console_kwargs

# ── colour helpers ──────────────────────────────────────────────────────────
try:
    from colorama import Fore, Style, init as _colorama_init
    _colorama_init()
    _GREEN = Fore.GREEN
    _RED = Fore.RED
    _YELLOW = Fore.YELLOW
    _CYAN = Fore.CYAN
    _RESET = Style.RESET_ALL
except ImportError:
    _GREEN = _RED = _YELLOW = _CYAN = _RESET = ""

# ── constants mirroring Steempeg internals ──────────────────────────────────
RESOLUTIONS = [144, 240, 360, 480, 720, 1080]  # "Original" handled separately
CODECS = ["libx264", "libx265"]
CODEC_LABELS = {"libx264": "H.264", "libx265": "H.265"}
BITRATE_PRESETS = {
    "Ultra":  {4320: 120, 2160: 50,   1440: 32,   1080: 24,  720: 12,   480: 6,   360: 3,   260: 1.5, 144: 0.5},
    "High":   {4320: 90,  2160: 38,   1440: 22,   1080: 12,  720: 7.5,  480: 4,   360: 2,   260: 1.0, 144: 0.3},
    "Medium": {4320: 60,  2160: 28.5, 1440: 16.5, 1080: 9,   720: 5.6,  480: 2.5, 360: 1.2, 260: 0.6, 144: 0.2},
    "Low":    {4320: 40,  2160: 19,   1440: 11,   1080: 6,   720: 3.75, 480: 1.5, 360: 0.8, 260: 0.4, 144: 0.1},
}
FPS_OPTIONS = [30, 60]  # plus "Original"


def _snap_height(h: int) -> int:
    """Round to nearest known resolution tier (for bitrate lookup)."""
    tiers = sorted(BITRATE_PRESETS["Ultra"].keys(), reverse=True)
    for t in tiers:
        if h >= t:
            return t
    return tiers[-1]


def _bitrate_for(preset: str, height: int) -> float:
    """Mbps for a given preset + height, with interpolation for non-standard heights."""
    table = BITRATE_PRESETS.get(preset, BITRATE_PRESETS["Medium"])
    snapped = _snap_height(height)
    return table.get(snapped, table[1080])


# ── ffprobe helpers ─────────────────────────────────────────────────────────
def _ffprobe(path: str | Path) -> dict | None:
    """Run ffprobe and return parsed JSON, or None on failure."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(path),
            ],
            capture_output=True, text=True, timeout=30,
            **subprocess_hide_console_kwargs(),
        )
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)
    except Exception:
        return None


def _probe_source(clip_dir: str | Path) -> dict | None:
    """Probe the first video file inside a clip folder."""
    p = Path(clip_dir)
    candidates = []
    for ext in ("*.mp4", "*.mkv", "*.webm", "*.mov"):
        candidates.extend(p.glob(ext))
    if not candidates:
        # Steam multi-part MPD — look for session.mpd or any .m4s
        mpd = list(p.glob("*.mpd"))
        if mpd:
            return _ffprobe(mpd[0])
        return None
    return _ffprobe(sorted(candidates)[0])


def _video_stream(probe: dict) -> dict | None:
    for s in probe.get("streams", []):
        if s.get("codec_type") == "video":
            return s
    return None


def _audio_stream(probe: dict) -> dict | None:
    for s in probe.get("streams", []):
        if s.get("codec_type") == "audio":
            return s
    return None


def _source_video_path(clip_dir: str | Path) -> Path | None:
    """Return the primary video file inside a clip folder (flat or nested)."""
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
    mpd = sorted(p.rglob("*.mpd"), key=lambda path: len(path.parts))
    return mpd[0] if mpd else None


# ── preset generation ───────────────────────────────────────────────────────
@dataclass
class RenderPreset:
    resolution: int | None  # None = Original
    codec: str              # ffmpeg encoder name
    bitrate_preset: str | None  # Ultra/High/Medium/Low or None = Original
    fps: int | None         # None = Original
    label: str = ""

    def __post_init__(self):
        res_label = f"{self.resolution}p" if self.resolution else "Original"
        br_label = self.bitrate_preset or "Original"
        fps_label = f"{self.fps}fps" if self.fps else "OrigFPS"
        self.label = f"{res_label}_{CODEC_LABELS.get(self.codec, self.codec)}_{br_label}_{fps_label}"


def _generate_presets(source_height: int, source_fps: float, count: int = 4) -> list[RenderPreset]:
    """Generate a random mix of render presets for one clip."""
    pool: list[RenderPreset] = []

    usable_res = [r for r in RESOLUTIONS if r <= source_height]
    if not usable_res:
        usable_res = [144]

    for _ in range(count * 3):
        res = random.choice(usable_res + [None])  # None = Original
        codec = random.choice(CODECS)
        bp = random.choice(["Ultra", "High", "Medium", "Low", None])
        fps_val = random.choice([f for f in FPS_OPTIONS if f <= source_fps] + [None])
        pool.append(RenderPreset(res, codec, bp, fps_val))

    # de-duplicate by label and sample
    seen: set[str] = set()
    unique: list[RenderPreset] = []
    for p in pool:
        if p.label not in seen:
            seen.add(p.label)
            unique.append(p)
    random.shuffle(unique)
    return unique[:count]


# ── render + verify ─────────────────────────────────────────────────────────
@dataclass
class MetricResult:
    name: str
    expected: str
    actual: str
    passed: bool
    detail: str = ""


@dataclass
class JobResult:
    clip: str
    preset: str
    output_path: str
    metrics: list[MetricResult] = field(default_factory=list)
    passed: bool = True
    error: str = ""
    skipped: bool = False


def _build_ffmpeg_cmd(
    source_path: Path,
    output_path: Path,
    preset: RenderPreset,
    source_probe: dict,
    light: bool,
) -> list[str]:
    cmd = ["ffmpeg", "-y"]

    if light:
        cmd += ["-t", "5"]

    cmd += ["-i", str(source_path)]

    # Video filters
    vf_parts = []
    if preset.resolution:
        vf_parts.append(f"scale=-2:{preset.resolution}")
    if preset.fps:
        vf_parts.append(f"fps={preset.fps}")
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]

    # Video codec
    cmd += ["-c:v", preset.codec]

    # Bitrate
    if preset.bitrate_preset and preset.resolution:
        mbps = _bitrate_for(preset.bitrate_preset, preset.resolution)
        kbps = int(mbps * 1000)
        cmd += ["-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k", "-bufsize", f"{kbps * 2}k"]
    elif preset.bitrate_preset:
        vs = _video_stream(source_probe)
        h = int(vs.get("height", 1080)) if vs else 1080
        mbps = _bitrate_for(preset.bitrate_preset, h)
        kbps = int(mbps * 1000)
        cmd += ["-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k", "-bufsize", f"{kbps * 2}k"]

    # Audio
    cmd += ["-c:a", "aac", "-b:a", "128k"]

    cmd.append(str(output_path))
    return cmd


def _verify_output(
    output_path: Path,
    preset: RenderPreset,
    source_probe: dict,
    light: bool,
) -> list[MetricResult]:
    results: list[MetricResult] = []

    # File existence & size
    exists = output_path.exists() and output_path.stat().st_size > 0
    results.append(MetricResult("file_exists", "True, >0 bytes",
                                f"{exists}, {output_path.stat().st_size if output_path.exists() else 0} bytes",
                                exists))
    if not exists:
        return results

    probe = _ffprobe(output_path)
    if not probe:
        results.append(MetricResult("probe", "success", "failed", False))
        return results

    vs_out = _video_stream(probe)
    vs_src = _video_stream(source_probe)
    as_out = _audio_stream(probe)
    as_src = _audio_stream(source_probe)

    # Resolution
    if vs_out and preset.resolution:
        actual_h = int(vs_out.get("height", 0))
        tolerance = max(preset.resolution * 0.1, 4)  # allow rounding
        ok = abs(actual_h - preset.resolution) <= tolerance
        results.append(MetricResult("resolution", f"~{preset.resolution}p", f"{actual_h}p", ok))
    elif vs_out and vs_src:
        actual_h = int(vs_out.get("height", 0))
        expected_h = int(vs_src.get("height", 0))
        ok = abs(actual_h - expected_h) <= 4
        results.append(MetricResult("resolution", f"~{expected_h}p (orig)", f"{actual_h}p", ok))

    # Codec
    if vs_out:
        actual_codec = vs_out.get("codec_name", "")
        expected_family = "h264" if "264" in preset.codec else "hevc" if "265" in preset.codec else preset.codec
        ok = expected_family in actual_codec or actual_codec == expected_family
        results.append(MetricResult("codec", expected_family, actual_codec, ok))

    # Bitrate (within ±30%)
    if vs_out and preset.bitrate_preset:
        target_h = preset.resolution or (int(vs_src["height"]) if vs_src else 1080)
        target_mbps = _bitrate_for(preset.bitrate_preset, target_h)
        actual_bps = float(vs_out.get("bit_rate", 0) or probe.get("format", {}).get("bit_rate", 0) or 0)
        actual_mbps = actual_bps / 1_000_000
        ok = actual_mbps <= target_mbps * 1.3 if actual_mbps > 0 else False
        results.append(MetricResult("bitrate", f"~{target_mbps:.1f} Mbps (±30%)",
                                    f"{actual_mbps:.2f} Mbps", ok,
                                    f"target={target_mbps:.1f}, actual={actual_mbps:.2f}"))

    # FPS
    if vs_out:
        r_fps = vs_out.get("r_frame_rate", "0/1")
        try:
            num, den = r_fps.split("/")
            actual_fps = round(float(num) / float(den), 1)
        except (ValueError, ZeroDivisionError):
            actual_fps = 0
        if preset.fps:
            ok = abs(actual_fps - preset.fps) <= 1.5
            results.append(MetricResult("fps", str(preset.fps), str(actual_fps), ok))
        elif vs_src:
            src_r = vs_src.get("r_frame_rate", "0/1")
            try:
                sn, sd = src_r.split("/")
                src_fps = round(float(sn) / float(sd), 1)
            except (ValueError, ZeroDivisionError):
                src_fps = 0
            ok = abs(actual_fps - src_fps) <= 1.5
            results.append(MetricResult("fps", f"{src_fps} (orig)", str(actual_fps), ok))

    # Duration
    src_dur = float(source_probe.get("format", {}).get("duration", 0))
    out_dur = float(probe.get("format", {}).get("duration", 0))
    if light:
        expected_dur = min(src_dur, 5.0)
        tol = 1.0
    else:
        expected_dur = src_dur
        tol = 2.0
    ok = abs(out_dur - expected_dur) <= tol if expected_dur > 0 else out_dur > 0
    results.append(MetricResult("duration", f"~{expected_dur:.1f}s (±{tol}s)",
                                f"{out_dur:.1f}s", ok))

    # Audio presence
    if as_src:
        ok = as_out is not None
        results.append(MetricResult("audio_present", "yes", "yes" if ok else "no", ok))

    return results


# ── clip discovery ──────────────────────────────────────────────────────────
def _discover_clips(clips_dir: str | None, cache_path: Path | None, count: int) -> list[str]:
    """Return up to `count` clip folder paths."""
    folders: list[str] = []

    if cache_path and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            for c in data.get("clips", []):
                fp = c.get("full_path", "")
                if fp and Path(fp).is_dir():
                    folders.append(fp)
        except Exception:
            pass

    if clips_dir:
        p = Path(clips_dir)
        if p.is_dir():
            for child in p.iterdir():
                if child.is_dir() and str(child) not in folders:
                    folders.append(str(child))

    if not folders:
        return []
    random.shuffle(folders)
    return folders[:count]


# ── main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Steempeg Render Pipeline QA")
    parser.add_argument("--count", type=int, default=10, help="Number of clips to test (default 10)")
    parser.add_argument("--light", action="store_true", help="Render only first 5 seconds")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory for rendered outputs")
    parser.add_argument("--clips-dir", type=str, default=None, help="Explicit clips directory to scan")
    parser.add_argument("--presets-per-clip", type=int, default=4, help="Preset variations per clip (default 4)")
    parser.add_argument("--verbose", action="store_true", help="Print per-metric detail")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    cache_path = repo / "cache" / "clips_library_cache.json"
    log_dir = repo / "logs"
    log_dir.mkdir(exist_ok=True)

    out_dir = Path(args.output_dir) if args.output_dir else repo / "logs" / "diag_render_output"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print(f"{_RED}ERROR: ffmpeg/ffprobe not found in PATH{_RESET}")
        sys.exit(1)

    clips = _discover_clips(args.clips_dir, cache_path, args.count)
    if not clips:
        print(f"{_RED}ERROR: No clips found. Use --clips-dir or ensure cache exists.{_RESET}")
        sys.exit(1)

    print(f"{_CYAN}Steempeg Render Pipeline QA{_RESET}")
    print(f"  Clips: {len(clips)}  |  Mode: {'light (5s)' if args.light else 'full'}  |  Presets/clip: {args.presets_per_clip}")
    print()

    all_results: list[JobResult] = []
    total_pass = total_fail = total_skip = 0

    for i, clip_dir in enumerate(clips, 1):
        clip_name = Path(clip_dir).name
        print(f"{_CYAN}[{i}/{len(clips)}]{_RESET} {clip_name}")

        src_path = _source_video_path(clip_dir)
        if not src_path:
            print(f"  {_YELLOW}SKIP — no video file found{_RESET}")
            all_results.append(JobResult(clip_dir, "", "", skipped=True))
            total_skip += 1
            continue

        src_probe = _ffprobe(src_path)
        if not src_probe:
            print(f"  {_YELLOW}SKIP — ffprobe failed on source{_RESET}")
            all_results.append(JobResult(clip_dir, "", "", skipped=True))
            total_skip += 1
            continue

        vs = _video_stream(src_probe)
        src_h = int(vs.get("height", 1080)) if vs else 1080
        try:
            rn, rd = (vs.get("r_frame_rate", "30/1") if vs else "30/1").split("/")
            src_fps = round(float(rn) / float(rd), 1)
        except (ValueError, ZeroDivisionError):
            src_fps = 30.0

        presets = _generate_presets(src_h, src_fps, args.presets_per_clip)
        for preset in presets:
            out_path = out_dir / f"{clip_name}_{preset.label}.mp4"
            cmd = _build_ffmpeg_cmd(src_path, out_path, preset, src_probe, args.light)

            if args.verbose:
                print(f"    {preset.label}")
                print(f"      cmd: {' '.join(cmd[:6])}...")

            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=600,
                    **subprocess_hide_console_kwargs(),
                )
                if r.returncode != 0:
                    jr = JobResult(clip_dir, preset.label, str(out_path),
                                   error=f"ffmpeg exit {r.returncode}: {r.stderr[-200:]}", passed=False)
                    all_results.append(jr)
                    total_fail += 1
                    print(f"    {_RED}FAIL{_RESET} {preset.label} — ffmpeg error")
                    continue
            except subprocess.TimeoutExpired:
                jr = JobResult(clip_dir, preset.label, str(out_path), error="timeout", passed=False)
                all_results.append(jr)
                total_fail += 1
                print(f"    {_RED}FAIL{_RESET} {preset.label} — timeout")
                continue

            metrics = _verify_output(out_path, preset, src_probe, args.light)
            passed = all(m.passed for m in metrics)
            jr = JobResult(clip_dir, preset.label, str(out_path),
                           metrics=[asdict(m) for m in metrics], passed=passed)
            all_results.append(jr)

            if passed:
                total_pass += 1
                print(f"    {_GREEN}PASS{_RESET} {preset.label}")
            else:
                total_fail += 1
                fails = [m for m in metrics if not m.passed]
                print(f"    {_RED}FAIL{_RESET} {preset.label} — {', '.join(f.name for f in fails)}")

            if args.verbose:
                for m in metrics:
                    tag = f"{_GREEN}✓{_RESET}" if m.passed else f"{_RED}✗{_RESET}"
                    print(f"      {tag} {m.name}: expected={m.expected}  actual={m.actual}")

    # ── summary ─────────────────────────────────────────────────────────────
    print()
    print(f"{_CYAN}{'='*60}{_RESET}")
    print(f"  {_GREEN}PASS: {total_pass}{_RESET}  |  {_RED}FAIL: {total_fail}{_RESET}  |  {_YELLOW}SKIP: {total_skip}{_RESET}")
    print(f"{_CYAN}{'='*60}{_RESET}")

    if total_fail:
        print(f"\n{_RED}Worst offenders:{_RESET}")
        for jr in all_results:
            if not jr.passed and not jr.skipped:
                bad = [m["name"] for m in jr.metrics if not m.get("passed", True)] if jr.metrics else [jr.error]
                print(f"  • {Path(jr.clip).name} / {jr.preset}: {', '.join(bad)}")

    # ── write JSON report ───────────────────────────────────────────────────
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = log_dir / f"diag_render_qa_{stamp}.json"
    report = {
        "timestamp": stamp,
        "mode": "light" if args.light else "full",
        "clip_count": len(clips),
        "total_pass": total_pass,
        "total_fail": total_fail,
        "total_skip": total_skip,
        "jobs": [asdict(jr) for jr in all_results],
    }
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
