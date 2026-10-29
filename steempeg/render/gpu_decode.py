"""NVDEC decode and CUDA scale for a Healthy clip on an NVIDIA encoder.

Issues, Dead, and Cured stay on the software decoder. Those manifests are the
ones a hardware decoder has died on. NVDEC runs inside the ffmpeg child; if
that child exits with an error, the render retries the same part on the CPU.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_VF = re.compile(r'-vf\s+(?:"([^"]+)"|(\S+))')
_ENCODER = re.compile(r"-c:v\s+(\S+)")
_FPS = re.compile(r"(?:^|\s)-r\s+\d+")

_RANGE = {
    "pc": "pc",
    "jpeg": "pc",
    "full": "pc",
    "tv": "tv",
    "mpeg": "tv",
    "limited": "tv",
}
_SPACE = frozenset({
    "bt709", "bt470m", "bt470bg", "smpte170m", "smpte240m",
    "bt2020", "bt2020nc", "bt2020c", "fcc", "ycgco",
})
_TRC = frozenset({
    "bt709", "gamma22", "gamma28", "smpte170m", "smpte240m",
    "linear", "iec61966-2-1", "bt2020-10", "bt2020-12",
})
_PRIMARIES = frozenset({
    "bt709", "bt470m", "bt470bg", "smpte170m", "smpte240m", "bt2020", "film",
})


@dataclass(frozen=True)
class NvdecSource:
    """ffprobe result used to decide whether NVDEC may open this manifest."""

    opens: bool
    color_suffix: str


def nvdec_allowed(report, encoder: str, *, audio_only: bool) -> bool:
    """True when this job may try NVDEC decode and a CUDA scale.

    Only a Healthy report qualifies. Issues, Dead, and Cured keep the
    software decoder. ``probe_failed`` means ffprobe never confirmed the
    manifest, so that clip stays on the CPU too.
    """
    if audio_only or report is None:
        return False
    if bool(getattr(report, "probe_failed", False)):
        return False
    level = getattr(getattr(report, "level", None), "value", None)
    if level is None:
        level = str(getattr(report, "level", "") or "")
    if str(level).strip().lower() != "healthy":
        return False
    return "nvenc" in (encoder or "").lower()


def job_uses_nvdec(app, job, encoder: str, *, audio_only: bool) -> bool:
    """Healthy NVENC jobs only. A salvage manifest stays on the CPU decoder."""
    if getattr(job, "salvage_mpds", None):
        logging.info("NVDEC decode+scale eligible: no (salvage manifest)")
        return False
    report = None
    getter = getattr(app, "get_clip_health_report", None)
    if callable(getter):
        try:
            report = getter(getattr(job, "clip_path", ""))
        except Exception:
            logging.exception("NVDEC health lookup failed")
            report = None
    allowed = nvdec_allowed(report, encoder, audio_only=audio_only)
    level = getattr(getattr(report, "level", None), "value", "unknown")
    logging.info(
        "NVDEC decode+scale eligible: %s (health=%s, encoder=%s)",
        "yes" if allowed else "no",
        level,
        encoder,
    )
    return allowed


def ffprobe_beside(ffmpeg_exe: str) -> str:
    """Returns the ffprobe that ships next to this ffmpeg, or ``ffprobe``."""
    directory = os.path.dirname(ffmpeg_exe or "")
    name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    candidate = os.path.join(directory, name) if directory else ""
    if candidate and os.path.isfile(candidate):
        return candidate
    return name


def probe_nvdec_source(
    ffprobe_exe: str, media_path: str, *, timeout: float = 8.0
) -> NvdecSource:
    """Opens the manifest with ffprobe and copies its color tags.

    ``opens`` is false when ffprobe rejects the file or does not finish.
    A timeout is a refusal: NVDEC does not run on an unverified manifest.
    """
    try:
        proc = subprocess.run(
            [
                ffprobe_exe,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=pix_fmt,color_range,color_space,color_transfer,color_primaries",
                "-of", "default=noprint_wrappers=1:nokey=0",
                "-i", media_path,
            ],
            creationflags=_NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        logging.info("NVDEC skipped: ffprobe did not finish on the manifest")
        return NvdecSource(False, "")
    if proc.returncode != 0:
        logging.info("NVDEC skipped: ffprobe could not open the manifest")
        return NvdecSource(False, "")
    fields: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip().lower()
    suffix = _color_suffix_from_fields(fields)
    if suffix:
        logging.info("NVDEC color tags: %s", suffix)
    else:
        logging.info("NVDEC color tags: ffmpeg will pick the range")
    return NvdecSource(True, suffix)


def _color_suffix_from_fields(fields: dict[str, str]) -> str:
    """Turns ffprobe stream fields into ffmpeg output color flags."""
    pix = fields.get("pix_fmt", "")
    range_name = _RANGE.get(fields.get("color_range", ""), "")
    if not range_name and pix.startswith("yuvj"):
        range_name = "pc"
    parts: list[str] = []
    if range_name:
        parts.append(f"-color_range {range_name}")
    space = fields.get("color_space", "")
    if space in _SPACE:
        parts.append(f"-colorspace {space}")
    prim = fields.get("color_primaries", "")
    if prim in _PRIMARIES:
        parts.append(f"-color_primaries {prim}")
    trc = fields.get("color_transfer", "")
    if trc in _TRC:
        parts.append(f"-color_trc {trc}")
    return " ".join(parts)


def _cuda_scale_body(body: str, *, ten_bit: bool) -> str | None:
    """Maps one software scale onto scale_cuda. None when it is not a plain scale."""
    fmt = ":format=p010le" if ten_bit else ""
    tail = f":interp_algo=bicubic{fmt}"
    if body == "scale=trunc(iw/2)*2:trunc(ih/2)*2":
        return f"scale_cuda=w=iw:h=ih:force_divisible_by=2{tail}"
    match = re.fullmatch(r"scale=-2:(\d+)", body)
    if match:
        return f"scale_cuda=w=-2:h={match.group(1)}{tail}"
    match = re.fullmatch(r"scale=-2:min\(ih\\?,(\d+)\)", body)
    if match:
        return f"scale_cuda=w=-2:h='min(ih,{match.group(1)})'{tail}"
    return None


def promote_nvdec_command(cmd: str, *, ten_bit: bool, color_suffix: str) -> str | None:
    """Returns the same ffmpeg command with CUDA decode and scale, or None.

    None keeps the CPU command: stream copy, a frame-rate change, a
    non-NVIDIA encoder, or a filter that is not a plain scale. A frame-rate
    change needs a software filter, so that command is not mixed with CUDA.
    """
    if not cmd or _FPS.search(cmd):
        return None
    encoder = _ENCODER.search(cmd)
    if encoder is None or "nvenc" not in encoder.group(1).lower():
        return None
    found = _VF.search(cmd)
    if found is None:
        return None
    body = found.group(1) if found.group(1) is not None else found.group(2)
    cuda = _cuda_scale_body(body or "", ten_bit=ten_bit)
    if cuda is None:
        return None
    vf = f'-vf "{cuda}"' if ("'" in cuda or " " in cuda) else f"-vf {cuda}"
    rewritten = cmd[: found.start()] + vf + cmd[found.end() :]
    input_at = rewritten.find(" -i ")
    if input_at < 0:
        return None
    hw = "-hwaccel cuda -hwaccel_output_format cuda"
    rewritten = rewritten[:input_at] + " " + hw + rewritten[input_at:]
    suffix = (color_suffix or "").strip()
    if suffix:
        rewritten = _insert_color_suffix(rewritten, suffix)
    return rewritten


def _insert_color_suffix(cmd: str, suffix: str) -> str:
    """Places color flags on the output, just before ``-y`` or the null muxer."""
    for marker in (" -y ", " -f null", " -f matroska"):
        pos = cmd.rfind(marker)
        if pos >= 0:
            return cmd[:pos] + " " + suffix + cmd[pos:]
    return cmd + " " + suffix
