#!/usr/bin/env python3
"""System Diagnostics Report for Steempeg.

Quick dump of hardware, software, dependencies, config, and cache health.

Usage:
    python scripts/diag_system.py
    python scripts/diag_system.py --verbose
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from colorama import Fore, Style, init as _colorama_init
    _colorama_init()
    _CYAN = Fore.CYAN
    _GREEN = Fore.GREEN
    _YELLOW = Fore.YELLOW
    _RED = Fore.RED
    _RESET = Style.RESET_ALL
except ImportError:
    _CYAN = _GREEN = _YELLOW = _RED = _RESET = ""


def _run(cmd: list[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else f"(error: {r.stderr.strip()[:100]})"
    except FileNotFoundError:
        return "(not found)"
    except Exception as e:
        return f"(error: {e})"


def _section(title: str):
    print(f"\n{_CYAN}── {title} ──{_RESET}")


def _kv(key: str, value: str, warn: bool = False):
    colour = _YELLOW if warn else ""
    reset = _RESET if warn else ""
    print(f"  {key:.<30s} {colour}{value}{reset}")


# ── system info ─────────────────────────────────────────────────────────────
def _collect_system(info: dict):
    _section("System")
    info["os"] = f"{platform.system()} {platform.release()} ({platform.version()})"
    info["cpu"] = platform.processor() or _run(["wmic", "cpu", "get", "name"]).replace("Name", "").strip()
    _kv("OS", info["os"])
    _kv("CPU", info["cpu"])

    try:
        import psutil
        mem = psutil.virtual_memory()
        info["ram_total_gb"] = round(mem.total / (1024**3), 1)
        info["ram_free_gb"] = round(mem.available / (1024**3), 1)
        _kv("RAM", f"{info['ram_total_gb']} GB total, {info['ram_free_gb']} GB free")
    except ImportError:
        if platform.system() == "Windows":
            raw = _run(["wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory", "/value"])
            info["ram_raw"] = raw
            _kv("RAM", raw.replace("\n", " "))
        else:
            _kv("RAM", "(install psutil for details)")

    # GPU
    if platform.system() == "Windows":
        gpu = _run(["wmic", "path", "win32_VideoController", "get", "name"])
        gpu_clean = "\n".join(l.strip() for l in gpu.splitlines() if l.strip() and l.strip() != "Name")
        info["gpu"] = gpu_clean
        _kv("GPU", gpu_clean or "(unknown)")
    else:
        gpu = _run(["lspci"])
        vga = [l for l in gpu.splitlines() if "VGA" in l or "3D" in l]
        info["gpu"] = "; ".join(vga) if vga else "(unknown)"
        _kv("GPU", info["gpu"])

    # Disk
    repo = Path(__file__).resolve().parent.parent
    try:
        usage = shutil.disk_usage(repo)
        info["disk_free_gb"] = round(usage.free / (1024**3), 1)
        _kv("Disk free (repo drive)", f"{info['disk_free_gb']} GB")
    except Exception:
        pass


# ── dependencies ────────────────────────────────────────────────────────────
def _collect_deps(info: dict):
    _section("Dependencies")
    info["python"] = sys.version.split()[0]
    _kv("Python", info["python"])

    try:
        import PySide6
        info["pyside6"] = PySide6.__version__
        _kv("PySide6", info["pyside6"])
    except ImportError:
        info["pyside6"] = "(not installed)"
        _kv("PySide6", info["pyside6"], warn=True)

    ffmpeg_v = _run(["ffmpeg", "-version"])
    info["ffmpeg"] = ffmpeg_v.splitlines()[0] if ffmpeg_v and not ffmpeg_v.startswith("(") else ffmpeg_v
    _kv("ffmpeg", info["ffmpeg"])

    ffprobe_v = _run(["ffprobe", "-version"])
    info["ffprobe"] = ffprobe_v.splitlines()[0] if ffprobe_v and not ffprobe_v.startswith("(") else ffprobe_v
    _kv("ffprobe", info["ffprobe"])

    # Codec support
    codecs_raw = _run(["ffmpeg", "-codecs", "-hide_banner"], timeout=10)
    for tag in ("h264", "hevc", "av1", "vp9"):
        found = any(tag in l.lower() for l in codecs_raw.splitlines())
        info[f"codec_{tag}"] = found
        _kv(f"  codec {tag}", "available" if found else "missing", warn=not found)

    # HW encoders
    encoders_raw = _run(["ffmpeg", "-encoders", "-hide_banner"], timeout=10)
    for enc in ("h264_nvenc", "hevc_nvenc", "av1_nvenc", "h264_amf", "hevc_amf", "h264_qsv"):
        found = enc in encoders_raw
        info[f"encoder_{enc}"] = found
        _kv(f"  encoder {enc}", "yes" if found else "no", warn=False)

    mpv_v = _run(["mpv", "--version"])
    info["mpv"] = mpv_v.splitlines()[0] if mpv_v and not mpv_v.startswith("(") else mpv_v
    _kv("mpv", info["mpv"])


# ── steempeg config ────────────────────────────────────────────────────────
def _collect_config(info: dict, verbose: bool):
    _section("Steempeg Config")
    repo = Path(__file__).resolve().parent.parent
    settings_path = repo / "cache" / "settings.json"

    if not settings_path.exists():
        _kv("settings.json", "(not found)", warn=True)
        return

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as e:
        _kv("settings.json", f"(parse error: {e})", warn=True)
        return

    keys_of_interest = [
        "chrome_theme", "ui_shell", "ui_theme", "date_format", "clock_format",
        "display_timezone",
    ]
    for k in keys_of_interest:
        if k in settings:
            info[f"config_{k}"] = settings[k]
            _kv(k, str(settings[k]))

    render = settings.get("render_export_settings", {})
    if render:
        for rk in ("quality_text", "fps_text", "bitrate_text", "codec_text",
                    "container_format", "encode_speed", "save_dir"):
            v = render.get(rk)
            if v is not None:
                info[f"render_{rk}"] = v
                _kv(f"render.{rk}", str(v))

    clips_folders = settings.get("clips_folders", [])
    info["clips_folders"] = clips_folders
    _kv("clips_folders", f"{len(clips_folders)} folder(s)")

    presets = settings.get("export_presets", {})
    info["export_presets_count"] = len(presets)
    _kv("export_presets", f"{len(presets)} saved")

    if verbose:
        for name in sorted(presets.keys()):
            _kv(f"  preset '{name}'", str(presets[name].get("quality_text", "?"))[:60])


# ── cache health ────────────────────────────────────────────────────────────
def _collect_cache(info: dict):
    _section("Cache Health")
    repo = Path(__file__).resolve().parent.parent
    cache_dir = repo / "cache"

    if not cache_dir.is_dir():
        _kv("cache/", "(missing)", warn=True)
        return

    cache_files = sorted(cache_dir.glob("*"))
    info["cache_file_count"] = len(cache_files)
    total_size = 0
    for f in cache_files:
        if f.is_file():
            sz = f.stat().st_size
            total_size += sz
            _kv(f.name, f"{sz / 1024:.1f} KB")
    info["cache_total_kb"] = round(total_size / 1024, 1)

    # Clips count
    clips_cache = cache_dir / "clips_library_cache.json"
    if clips_cache.exists():
        try:
            data = json.loads(clips_cache.read_text(encoding="utf-8"))
            n = len(data.get("clips", []))
            info["cached_clips"] = n
            _kv("cached clips", str(n))
        except Exception:
            pass

    # Screenshots count
    ss_cache = cache_dir / "screenshots_library_cache.json"
    if ss_cache.exists():
        try:
            data = json.loads(ss_cache.read_text(encoding="utf-8"))
            n = len(data.get("files", []))
            info["cached_screenshots"] = n
            _kv("cached screenshots", str(n))
        except Exception:
            pass

    # Thumbnail count
    thumb_dir = cache_dir / "thumbnails"
    if thumb_dir.is_dir():
        thumbs = list(thumb_dir.glob("*"))
        info["thumbnail_count"] = len(thumbs)
        _kv("thumbnails", str(len(thumbs)))

    # Render queue
    queue_file = cache_dir / "render_queue.json"
    if queue_file.exists():
        try:
            q = json.loads(queue_file.read_text(encoding="utf-8"))
            n = len(q) if isinstance(q, list) else len(q.get("jobs", q.get("queue", [])))
            info["render_queue_length"] = n
            _kv("render queue jobs", str(n))
        except Exception:
            _kv("render queue", "(parse error)")


# ── main ────────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Steempeg System Diagnostics")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print(f"{_CYAN}Steempeg System Diagnostics{_RESET}")
    print(f"  Generated: {datetime.now().isoformat()}")

    info: dict = {}
    _collect_system(info)
    _collect_deps(info)
    _collect_config(info, args.verbose)
    _collect_cache(info)

    # Save JSON
    repo = Path(__file__).resolve().parent.parent
    log_dir = repo / "logs"
    log_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = log_dir / f"diag_system_{stamp}.json"
    info["timestamp"] = stamp
    report_path.write_text(json.dumps(info, indent=2, default=str), encoding="utf-8")

    print(f"\n{_GREEN}Report saved to {report_path}{_RESET}")


if __name__ == "__main__":
    main()
