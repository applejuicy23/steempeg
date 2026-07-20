"""Classify exported / rendered flat media by duration *metadata* integrity.

This is NOT a full content/corruption scan — mid-file A/V breaks, silent tracks,
and bad thumbnails can still happen on a \"Healthy\" export.

Separate from DASH folder health — same ClipHealth tiers/icons, different signals.

  healthy  — readable; stream duration sane; format agrees; optional export-expected
             matches when the sidecar recorded one
  degraded — playable but container/sidecar duration disagrees with stream, or the
             recorded export expectation (trim length / full-job) diverges
  dead     — missing file or ffprobe cannot open
  cured    — UI overlay after Fix duration / Remux (metadata/timeline only)

Pure filesystem + ffprobe — no Qt.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Optional, Tuple

from steempeg.core.dash.health import ClipHealth, ClipHealthReport
from steempeg.core.rendered_media import (
    is_sane_media_duration,
    load_rendered_companion_meta,
    parse_media_duration_text,
    probe_matroska_tag_duration_sec,
    resolve_ffmpeg_exe,
    resolve_ffprobe_exe,
)

# Bump when assess rules change so disk cache is not reused with old verdicts.
RENDERED_HEALTH_RULES_VERSION = 2

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_ABS_TOL_SEC = 0.75
_REL_TOL = 0.02
_FROZEN_TAIL_RATIO = 1.5
_FROZEN_TAIL_MIN_GAP_SEC = 2.0


@dataclass
class RenderedHealthAssessment:
    report: ClipHealthReport
    duration_stream_sec: Optional[float] = None
    duration_format_sec: Optional[float] = None
    duration_sec: Optional[float] = None  # playable truth (stream preferred)


def durations_diverge(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    try:
        aa = float(a)
        bb = float(b)
    except (TypeError, ValueError):
        return False
    if not (is_sane_media_duration(aa) and is_sane_media_duration(bb)):
        return False
    diff = abs(aa - bb)
    if diff <= _ABS_TOL_SEC:
        return False
    return diff > max(_ABS_TOL_SEC, min(aa, bb) * _REL_TOL)


def _ffprobe_duration(file_path: str, *, stream_sel: str | None) -> float | None:
    cmd = [resolve_ffprobe_exe(), "-v", "error"]
    if stream_sel:
        cmd += ["-select_streams", stream_sel, "-show_entries", "stream=duration"]
    else:
        cmd += ["-show_entries", "format=duration"]
    cmd += ["-of", "default=noprint_wrappers=1:nokey=1", file_path]
    try:
        out = subprocess.check_output(
            cmd,
            creationflags=_NO_WINDOW,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
        ).strip()
        return parse_media_duration_text(out.splitlines()[0] if out else None)
    except Exception:
        return None


def probe_stream_and_format_durations(file_path: str) -> Tuple[Optional[float], Optional[float]]:
    """Return (stream_duration, format_duration). Stream prefers video then audio.

    For Matroska, stream/format duration are often N/A; fall back to TAG:DURATION
    so both slots share the tag length (container truth for MKV).
    """
    stream = _ffprobe_duration(file_path, stream_sel="v:0")
    if stream is None:
        stream = _ffprobe_duration(file_path, stream_sel="a:0")
    fmt = _ffprobe_duration(file_path, stream_sel=None)
    if stream is None and fmt is None:
        tag = probe_matroska_tag_duration_sec(file_path)
        if tag is not None:
            logging.debug(
                "Rendered health: using Matroska TAG:DURATION=%.3fs for %s",
                tag,
                file_path,
            )
            return tag, tag
    return stream, fmt


def _ffprobe_opens(file_path: str, timeout: float = 8.0) -> bool:
    try:
        proc = subprocess.run(
            [resolve_ffprobe_exe(), "-v", "error", "-i", file_path],
            creationflags=_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def assess_rendered_health(
    file_path: str,
    *,
    expected_duration_sec: float | None = None,
) -> RenderedHealthAssessment:
    """Assess a flat export. Does not apply the cured overlay."""
    if not file_path or not os.path.isfile(file_path):
        return RenderedHealthAssessment(
            ClipHealthReport(ClipHealth.DEAD, ["File missing or unreadable"]),
        )

    stream, fmt = probe_stream_and_format_durations(file_path)
    playable = stream if stream is not None else fmt
    logging.debug(
        "Rendered health probe %s: stream=%s format=%s",
        file_path,
        stream,
        fmt,
    )

    if playable is None:
        if not _ffprobe_opens(file_path):
            return RenderedHealthAssessment(
                ClipHealthReport(ClipHealth.DEAD, ["Media cannot be opened (unplayable)"]),
            )
        # File opens (mpv can play) but neither stream/format nor tags have duration.
        return RenderedHealthAssessment(
            ClipHealthReport(
                ClipHealth.DEGRADED,
                ["No usable duration metadata (file opens; timeline length unknown)"],
            ),
        )

    issues: list[str] = []

    if stream is not None and fmt is not None and durations_diverge(stream, fmt):
        if fmt > stream * _FROZEN_TAIL_RATIO and (fmt - stream) >= _FROZEN_TAIL_MIN_GAP_SEC:
            issues.append(
                f"Container duration {fmt:.1f}s far exceeds stream {stream:.1f}s "
                f"(likely frozen-tail / bad Original metadata)"
            )
        else:
            issues.append(
                f"Container duration {fmt:.1f}s vs stream {stream:.1f}s"
            )

    expected = expected_duration_sec
    if expected is None:
        meta = load_rendered_companion_meta(file_path) or {}
        raw = meta.get("expected_duration_sec")
        if is_sane_media_duration(raw):
            expected = float(raw)
        # Do NOT fall back to full source-clip length here. Trimmed exports would
        # otherwise look "broken" (12s file vs 849s Steam clip). Expected length is
        # only meaningful when the export job recorded it in the sidecar.

    if expected is not None and durations_diverge(expected, playable):
        issues.append(
            f"Export expected ~{float(expected):.1f}s but playable length is {playable:.1f}s"
        )

    level = ClipHealth.DEGRADED if issues else ClipHealth.HEALTHY
    return RenderedHealthAssessment(
        ClipHealthReport(level, issues),
        duration_stream_sec=stream,
        duration_format_sec=fmt,
        duration_sec=playable,
    )


def remux_shortest(file_path: str, *, ffmpeg_exe: str | None = None) -> bool:
    """Remux with ``-c copy -shortest`` so container length follows real packets."""
    if not file_path or not os.path.isfile(file_path):
        return False
    ffmpeg = ffmpeg_exe or resolve_ffmpeg_exe()
    folder = os.path.dirname(file_path) or "."
    base, ext = os.path.splitext(os.path.basename(file_path))
    fd, tmp_path = tempfile.mkstemp(prefix=f"{base}_fix_", suffix=ext or ".mp4", dir=folder)
    os.close(fd)
    try:
        safe_in = file_path.replace("\\", "/")
        safe_out = tmp_path.replace("\\", "/")
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-i", safe_in,
            "-map", "0:v:0", "-map", "0:a:0?",
            "-c", "copy", "-shortest",
            "-avoid_negative_ts", "make_zero", "-fflags", "+genpts",
            "-y", safe_out,
        ]
        proc = subprocess.run(
            cmd,
            creationflags=_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) < 100:
            logging.warning(
                "Remux shortest failed for %s: %s",
                file_path,
                (proc.stderr or "").strip()[:400],
            )
            return False
        backup = file_path + ".steempeg.bak"
        try:
            if os.path.isfile(backup):
                os.remove(backup)
            os.replace(file_path, backup)
            os.replace(tmp_path, file_path)
            try:
                os.remove(backup)
            except OSError:
                pass
        except OSError:
            if os.path.isfile(backup) and not os.path.isfile(file_path):
                shutil.move(backup, file_path)
            return False
        return True
    except Exception as exc:
        logging.warning("Remux shortest error for %s: %s", file_path, exc)
        return False
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def apply_assessment_to_companion(
    file_path: str,
    assessment: RenderedHealthAssessment,
    *,
    cured: bool = False,
    stream_copy: bool | None = None,
    expected_duration_sec: float | None = None,
    extra: dict | None = None,
) -> None:
    """Merge health + playable duration into ``<file>.steempeg.json`` (preserve game fields)."""
    from steempeg.core.rendered_media import save_rendered_companion_meta

    meta = load_rendered_companion_meta(file_path) or {}
    if extra:
        meta.update(extra)

    app_id = meta.get("app_id") or ""
    game_name = meta.get("game_name") or ""
    clip_path = meta.get("clip_path") or ""
    game_icon_path = meta.get("game_icon_path") or ""

    health_level = ClipHealth.CURED.value if cured else assessment.report.level.value
    kwargs = {
        "app_id": app_id or None,
        "game_name": game_name,
        "clip_path": clip_path,
        "game_icon_path": game_icon_path,
        "duration_sec": assessment.duration_sec,
        "duration_stream_sec": assessment.duration_stream_sec,
        "duration_format_sec": assessment.duration_format_sec,
        "health": health_level,
        "health_issues": list(assessment.report.issues),
        "health_cured": bool(cured),
        "health_rules_version": RENDERED_HEALTH_RULES_VERSION,
        "expected_duration_sec": expected_duration_sec
        if expected_duration_sec is not None
        else meta.get("expected_duration_sec"),
    }
    if stream_copy is not None:
        kwargs["stream_copy"] = bool(stream_copy)
    elif "stream_copy" in meta:
        kwargs["stream_copy"] = bool(meta.get("stream_copy"))

    save_rendered_companion_meta(file_path, **kwargs)


def display_report_from_companion(meta: dict | None, fs_report: ClipHealthReport) -> ClipHealthReport:
    """Apply cured overlay when companion marks a successful fix."""
    if not meta:
        return fs_report
    if fs_report.level == ClipHealth.DEAD:
        return fs_report
    if meta.get("health_cured") or meta.get("health") == ClipHealth.CURED.value:
        issues = list(fs_report.issues)
        if not any("fixed" in i.lower() or "cured" in i.lower() or "sidecar" in i.lower() for i in issues):
            issues.append(
                "Timeline sidecar updated (metadata only — does not repair A/V content)"
            )
        return ClipHealthReport(ClipHealth.CURED, issues)
    return fs_report
