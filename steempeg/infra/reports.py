"""Bug-report bundle builder for GitHub issues and local debugging."""
import json
import os
import platform
import zipfile
from datetime import datetime, timezone

from PySide6.QtCore import Qt

from steempeg.version import APP_VERSION_STR


GITHUB_ISSUES_URL = "https://github.com/applejuicy23/steempeg/issues/new"


def collect_context(app):
    """Gather automatic diagnostics from the running application."""
    clip_path = getattr(app, "_preview_clip_path", None)
    if not clip_path and hasattr(app.ui, "table_clips"):
        row = app.ui.table_clips.currentRow()
        if row >= 0:
            item = app.ui.table_clips.item(row, 0)
            if item:
                clip_path = item.data(Qt.UserRole)

    health = None
    if clip_path and hasattr(app, "get_clip_health_report"):
        try:
            report = app.get_clip_health_report(clip_path)
            health = {
                "level": report.level.name,
                "issues": list(report.issues),
            }
        except Exception:
            pass

    render_summary = {}
    for key, attr in (
        ("quality", "combo_quality"),
        ("codec", "combo_codec"),
        ("fps", "combo_fps"),
        ("bitrate", "combo_bitrate"),
        ("encoder", "combo_encoder"),
    ):
        combo = getattr(app.ui, attr, None)
        if combo is not None:
            render_summary[key] = combo.currentText()

    trim = {}
    timeline = getattr(app, "custom_timeline", None)
    if timeline is not None and getattr(timeline, "is_trim_mode", False):
        trim = {
            "start_ms": timeline.trim_start_ms,
            "end_ms": timeline.trim_end_ms,
        }

    return {
        "version": APP_VERSION_STR,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "clips_folders": list(getattr(app, "clips_folders", []) or []),
        "logs_dir": getattr(app, "logs_dir", ""),
        "cache_dir": getattr(app, "cache_dir", ""),
        "selected_clip": clip_path,
        "clip_health": health,
        "render_settings": render_summary,
        "trim": trim,
    }


def build_report_text(description, context):
    lines = [
        "## Steempeg bug report",
        "",
        description.strip() or "(no description provided)",
        "",
        "---",
        f"Version: {context.get('version')}",
        f"Platform: {context.get('platform')}",
        f"Python: {context.get('python')}",
        f"UTC: {context.get('timestamp_utc')}",
        "",
        "Library folders:",
    ]
    for folder in context.get("clips_folders") or []:
        lines.append(f"  - {folder}")
    if not context.get("clips_folders"):
        lines.append("  (none)")

    clip = context.get("selected_clip")
    lines.append("")
    lines.append(f"Selected clip: {clip or '(none)'}")
    if context.get("clip_health"):
        h = context["clip_health"]
        lines.append(f"Clip health: {h.get('level')}")
        for issue in h.get("issues") or []:
            lines.append(f"  - {issue}")

    if context.get("render_settings"):
        lines.append("")
        lines.append("Render settings:")
        for key, val in context["render_settings"].items():
            lines.append(f"  {key}: {val}")

    if context.get("trim"):
        t = context["trim"]
        lines.append("")
        lines.append(f"Trim: {t.get('start_ms')}ms → {t.get('end_ms')}ms")

    return "\n".join(lines)


def create_report_bundle(app, description, include_app_log=True, include_mpv_log=True):
    """Write a zip report under logs_dir. Returns the zip path."""
    logs_dir = getattr(app, "logs_dir", None)
    if not logs_dir:
        raise ValueError("logs_dir is not configured")

    os.makedirs(logs_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(logs_dir, f"steempeg_report_{stamp}.zip")

    context = collect_context(app)
    report_text = build_report_text(description, context)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.md", report_text)
        zf.writestr("metadata.json", json.dumps(context, indent=2, ensure_ascii=False))

        if include_app_log:
            app_log = getattr(app, "current_log_file", None)
            if app_log and os.path.isfile(app_log):
                zf.write(app_log, arcname=f"logs/{os.path.basename(app_log)}")

        if include_mpv_log:
            mpv_log = getattr(app, "current_mpv_log_file", None)
            if mpv_log and os.path.isfile(mpv_log):
                zf.write(mpv_log, arcname=f"logs/{os.path.basename(mpv_log)}")

    return zip_path


def github_issue_body(description, context):
    """Markdown body suitable for pasting into a new GitHub issue."""
    return build_report_text(description, context)
