"""Shared Main Settings keys and apply helpers (render tab, export folder, updates)."""
from __future__ import annotations

import logging
import os
import time

# ----- Default Render panel tab -----

KEY_DEFAULT_RENDER_TAB = "default_render_tab"

RENDER_TAB_SOURCE_INFO = "source_info"
RENDER_TAB_VIDEO = "video_settings"
RENDER_TAB_AUDIO = "audio_settings"
RENDER_TAB_EXPORT = "export_settings"
RENDER_TAB_PRESETS = "presets"

# New installs land on Video Settings (desktop used to hard-open Source Info).
DEFAULT_RENDER_TAB = RENDER_TAB_VIDEO

RENDER_TAB_LABELS: tuple[tuple[str, str], ...] = (
    (RENDER_TAB_SOURCE_INFO, "Source Info"),
    (RENDER_TAB_VIDEO, "Video Settings"),
    (RENDER_TAB_AUDIO, "Audio Settings"),
    (RENDER_TAB_EXPORT, "Export Settings"),
    (RENDER_TAB_PRESETS, "Presets"),
)

_RENDER_TAB_TO_INDEX: dict[str, int] = {
    RENDER_TAB_SOURCE_INFO: 0,
    RENDER_TAB_VIDEO: 1,
    RENDER_TAB_AUDIO: 2,
    RENDER_TAB_EXPORT: 3,
    RENDER_TAB_PRESETS: 4,
}

# ----- Desktop render chrome (docked neo vs Portable-like settings window) -----

KEY_DESKTOP_RENDER_LAYOUT = "desktop_render_layout"

DESKTOP_RENDER_ITS_A_DESKTOP = "its_a_desktop"
DESKTOP_RENDER_LIKE_A_PORTABLE = "like_a_portable"
DEFAULT_DESKTOP_RENDER_LAYOUT = DESKTOP_RENDER_ITS_A_DESKTOP

DESKTOP_RENDER_LAYOUT_LABELS: tuple[tuple[str, str], ...] = (
    (DESKTOP_RENDER_ITS_A_DESKTOP, "It's a Desktop"),
    (DESKTOP_RENDER_LIKE_A_PORTABLE, "Like a Portable"),
)

KEY_PORTABLE_LIKE_MIDDLE_SPLITTER = "portable_like_middle_splitter"
DEFAULT_PORTABLE_LIKE_MIDDLE_SPLITTER = False

# ----- Permanent export folder -----

KEY_PERMANENT_EXPORT_FOLDER = "permanent_export_folder"

# ----- Update check interval -----

KEY_UPDATE_CHECK_INTERVAL = "update_check_interval"
KEY_LAST_UPDATE_CHECK_TS = "last_update_check_ts"
# Legacy boolean — migrated once into KEY_UPDATE_CHECK_INTERVAL.
KEY_CHECK_UPDATES_ON_STARTUP = "check_updates_on_startup"
# Title-bar «Update Available» plaque — silent badge only; Update Center stays.
KEY_HIDE_UPDATE_AVAILABLE_BADGE = "hide_update_available_badge"
DEFAULT_HIDE_UPDATE_AVAILABLE_BADGE = False

UPDATE_INTERVAL_OFF = "off"
UPDATE_INTERVAL_EVERY_LAUNCH = "every_launch"
UPDATE_INTERVAL_DAILY = "daily"
UPDATE_INTERVAL_WEEKLY = "weekly"

DEFAULT_UPDATE_CHECK_INTERVAL = UPDATE_INTERVAL_DAILY

UPDATE_INTERVAL_LABELS: tuple[tuple[str, str], ...] = (
    (UPDATE_INTERVAL_OFF, "Off"),
    (UPDATE_INTERVAL_EVERY_LAUNCH, "Every launch"),
    (UPDATE_INTERVAL_DAILY, "Daily"),
    (UPDATE_INTERVAL_WEEKLY, "Weekly"),
)

_DAY_SEC = 24 * 60 * 60
_UPDATE_INTERVAL_SECONDS: dict[str, float] = {
    UPDATE_INTERVAL_DAILY: _DAY_SEC,
    UPDATE_INTERVAL_WEEKLY: 7 * _DAY_SEC,
}


def normalize_render_tab(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "source": RENDER_TAB_SOURCE_INFO,
        "sourceinfo": RENDER_TAB_SOURCE_INFO,
        "info": RENDER_TAB_SOURCE_INFO,
        "0": RENDER_TAB_SOURCE_INFO,
        "video": RENDER_TAB_VIDEO,
        "videosettings": RENDER_TAB_VIDEO,
        "1": RENDER_TAB_VIDEO,
        "audio": RENDER_TAB_AUDIO,
        "audiosettings": RENDER_TAB_AUDIO,
        "2": RENDER_TAB_AUDIO,
        "export": RENDER_TAB_EXPORT,
        "exportsettings": RENDER_TAB_EXPORT,
        "3": RENDER_TAB_EXPORT,
        "preset": RENDER_TAB_PRESETS,
        "4": RENDER_TAB_PRESETS,
    }
    if text in _RENDER_TAB_TO_INDEX:
        return text
    return aliases.get(text, DEFAULT_RENDER_TAB)


def render_tab_index(value: object | None) -> int:
    return _RENDER_TAB_TO_INDEX.get(normalize_render_tab(value), 1)


def load_default_render_tab(settings: dict | None) -> str:
    raw = (settings or {}).get(KEY_DEFAULT_RENDER_TAB, DEFAULT_RENDER_TAB)
    return normalize_render_tab(raw)


def normalize_desktop_render_layout(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "its_a_desktop": DESKTOP_RENDER_ITS_A_DESKTOP,
        "desktop": DESKTOP_RENDER_ITS_A_DESKTOP,
        "classic": DESKTOP_RENDER_ITS_A_DESKTOP,
        "like_a_portable": DESKTOP_RENDER_LIKE_A_PORTABLE,
        "portable": DESKTOP_RENDER_LIKE_A_PORTABLE,
        "portable_like": DESKTOP_RENDER_LIKE_A_PORTABLE,
    }
    return aliases.get(text, DEFAULT_DESKTOP_RENDER_LAYOUT)


def load_desktop_render_layout(settings: dict | None = None) -> str:
    return normalize_desktop_render_layout(
        (settings or {}).get(KEY_DESKTOP_RENDER_LAYOUT, DEFAULT_DESKTOP_RENDER_LAYOUT)
    )


def normalize_portable_like_middle_splitter(value: object | None) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return DEFAULT_PORTABLE_LIKE_MIDDLE_SPLITTER


def load_portable_like_middle_splitter(settings: dict | None) -> bool:
    return normalize_portable_like_middle_splitter(
        (settings or {}).get(
            KEY_PORTABLE_LIKE_MIDDLE_SPLITTER, DEFAULT_PORTABLE_LIKE_MIDDLE_SPLITTER
        )
    )


def apply_default_render_tab(app, tab: object | None = None) -> int:
    """Set neo-nav / settings_tabs to the preferred landing tab. Returns index."""
    tabs = getattr(getattr(app, "ui", None), "settings_tabs", None)
    if tabs is None:
        return -1
    if tab is None:
        settings = {}
        if hasattr(app, "load_user_settings"):
            try:
                settings = app.load_user_settings() or {}
            except Exception:
                settings = {}
        tab = load_default_render_tab(settings)
    idx = render_tab_index(tab)
    count = tabs.count()
    if count <= 0:
        return -1
    idx = max(0, min(idx, count - 1))
    # Skip no-op tab switches — setCurrentIndex still forces a layout pass.
    if tabs.currentIndex() == idx:
        buttons = getattr(app, "neo_nav_buttons", None) or []
        if idx < len(buttons) and not buttons[idx].isChecked():
            buttons[idx].setChecked(True)
        return idx
    tabs.setCurrentIndex(idx)
    buttons = getattr(app, "neo_nav_buttons", None) or []
    if idx < len(buttons):
        buttons[idx].setChecked(True)
    return idx


def default_export_dir() -> str:
    """Default ``{install}/rendered_videos`` — create parents if missing."""
    from steempeg.infra.paths import default_rendered_videos_dir

    path = default_rendered_videos_dir().replace("\\", "/")
    if not os.path.isdir(path):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            logging.exception("Could not create default export dir %s", path)
    return path


def normalize_export_folder(value: object | None) -> str:
    text = str(value or "").strip().replace("\\", "/")
    return text


def _norm_export_path(folder: str) -> str:
    return os.path.normcase(os.path.normpath(folder.replace("/", os.sep)))


def _dir_is_writable(folder: str) -> bool:
    """Probe-write a tiny temp file (more reliable than ``os.access`` on Windows)."""
    probe = os.path.join(folder, ".steempeg_write_test")
    try:
        with open(probe, "wb") as fh:
            fh.write(b"0")
        try:
            os.remove(probe)
        except OSError:
            pass
        return True
    except OSError:
        return False


def export_folder_is_usable(folder: str | None) -> bool:
    """True when path exists as a directory and is writable."""
    folder = normalize_export_folder(folder)
    if not folder or not os.path.isdir(folder):
        return False
    return _dir_is_writable(folder)


def ensure_usable_export_folder(preferred: str | None = None) -> tuple[str, bool]:
    """Return ``(usable_folder, fell_back)``.

    Tries ``preferred`` (creates it when the parent allows). If still missing,
    invalid, or not writable → default ``rendered_videos`` (created if needed).
    Empty preferred uses the default without counting as a fallback.
    """
    preferred = normalize_export_folder(preferred)
    if preferred:
        if not os.path.isdir(preferred):
            try:
                os.makedirs(preferred, exist_ok=True)
            except OSError:
                logging.warning("Could not create export folder %s", preferred)
        if export_folder_is_usable(preferred):
            return preferred, False

    safe = default_export_dir()
    if not export_folder_is_usable(safe):
        # Last resort: still return the default path; caller continues with it.
        logging.error("Default export folder is not writable: %s", safe)

    if not preferred:
        return safe, False

    if _norm_export_path(preferred) == _norm_export_path(safe) and export_folder_is_usable(
        safe
    ):
        return safe, False

    logging.warning(
        "Export folder unavailable (%s); falling back to %s",
        preferred,
        safe,
    )
    return safe, True


def is_outside_default_rendered(folder: str) -> bool:
    from steempeg.infra.paths import default_rendered_videos_dir

    if not folder:
        return False
    root = os.path.normcase(os.path.normpath(default_rendered_videos_dir()))
    path = os.path.normcase(os.path.normpath(folder))
    try:
        return os.path.commonpath([root, path]) != root
    except ValueError:
        return True


def resolve_permanent_export_folder(settings: dict | None) -> str:
    """Return a usable export dir from Main Settings (or migrate portable snapshot)."""
    settings = settings or {}
    folder = normalize_export_folder(settings.get(KEY_PERMANENT_EXPORT_FOLDER))
    if folder and export_folder_is_usable(folder):
        return folder
    blob = settings.get("render_export_settings")
    if isinstance(blob, dict):
        legacy = normalize_export_folder(blob.get("save_dir"))
        if legacy and export_folder_is_usable(legacy):
            return legacy
    safe, _fell = ensure_usable_export_folder(None)
    return safe


def sync_export_folder_to_settings(app, folder: str) -> None:
    """Write permanent folder and keep render_export_settings.save_dir in sync."""
    folder = normalize_export_folder(folder) or default_export_dir()
    if not hasattr(app, "save_user_settings"):
        return
    app.save_user_settings(KEY_PERMANENT_EXPORT_FOLDER, folder)
    try:
        settings = app.load_user_settings() or {}
        blob = settings.get("render_export_settings")
        if isinstance(blob, dict):
            blob = dict(blob)
            blob["save_dir"] = folder
            app.save_user_settings("render_export_settings", blob)
    except Exception:
        logging.exception("Failed syncing render_export_settings.save_dir")


def notify_export_folder_fallback(
    app,
    requested: str,
    safe: str,
    *,
    use_dialog: bool = False,
) -> None:
    """Log + status (or dialog) when export path was reset to the default."""
    logging.warning(
        "Export folder fallback: %r → %r",
        requested,
        safe,
    )
    if use_dialog:
        try:
            from steempeg.ui.message_dialog import steempeg_information

            parent = getattr(app, "ui", None) or app
            steempeg_information(
                parent,
                "Export folder reset",
                "That export path is missing, invalid, or not writable.\n\n"
                f"Requested:\n{requested}\n\n"
                f"Using the default folder instead:\n{safe}",
            )
            return
        except Exception:
            logging.exception("Export-folder fallback dialog failed")
    if hasattr(app, "set_status"):
        try:
            app.set_status("Export folder unavailable, using default rendered_videos")
        except Exception:
            pass


def apply_export_folder(
    app,
    folder: str | None = None,
    *,
    persist: bool = False,
    notify: bool = False,
    notify_dialog: bool = False,
) -> str:
    """Set ``custom_destination`` to a usable folder and refresh the Export label.

    Invalid / unwritable paths fall back to default ``rendered_videos``.
    """
    if folder is None:
        settings = {}
        if hasattr(app, "load_user_settings"):
            try:
                settings = app.load_user_settings() or {}
            except Exception:
                settings = {}
        folder = resolve_permanent_export_folder(settings)
    requested = normalize_export_folder(folder) or default_export_dir()
    safe, fell_back = ensure_usable_export_folder(requested)
    if fell_back and (notify or notify_dialog):
        notify_export_folder_fallback(
            app, requested, safe, use_dialog=notify_dialog
        )
    app.custom_destination = safe
    if persist:
        sync_export_folder_to_settings(app, safe)
    if hasattr(app, "update_final_setup"):
        try:
            app.update_final_setup()
        except Exception:
            logging.exception("update_final_setup after export folder apply failed")
    return safe


def resolve_app_export_folder(
    app,
    preferred: str | None = None,
    *,
    notify: bool = True,
) -> str:
    """Resolve a writable export dir for the live app (render / UI path labels)."""
    if preferred is None:
        preferred = getattr(app, "custom_destination", "") or ""
    requested = normalize_export_folder(preferred)
    safe, fell_back = ensure_usable_export_folder(requested or None)
    if fell_back and notify:
        notify_export_folder_fallback(app, requested or "(empty)", safe)
    app.custom_destination = safe
    return safe


def normalize_update_check_interval(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in (UPDATE_INTERVAL_OFF, "never", "disabled", "false", "0"):
        return UPDATE_INTERVAL_OFF
    if text in (
        UPDATE_INTERVAL_EVERY_LAUNCH,
        "always",
        "launch",
        "startup",
        "on_startup",
        "every_run",
        "every_session",
    ):
        return UPDATE_INTERVAL_EVERY_LAUNCH
    if text in (UPDATE_INTERVAL_DAILY, "day", "true", "1", "on"):
        return UPDATE_INTERVAL_DAILY
    if text in (UPDATE_INTERVAL_WEEKLY, "week"):
        return UPDATE_INTERVAL_WEEKLY
    return DEFAULT_UPDATE_CHECK_INTERVAL


def resolve_update_check_interval(settings: dict | None) -> str:
    """Prefer new interval key; migrate legacy ``check_updates_on_startup`` boolean.

    Legacy checkbox meant check on every startup — ``true`` maps to ``every_launch``.
    """
    settings = settings or {}
    if KEY_UPDATE_CHECK_INTERVAL in settings:
        return normalize_update_check_interval(settings.get(KEY_UPDATE_CHECK_INTERVAL))
    if KEY_CHECK_UPDATES_ON_STARTUP in settings:
        return (
            UPDATE_INTERVAL_EVERY_LAUNCH
            if bool(settings.get(KEY_CHECK_UPDATES_ON_STARTUP))
            else UPDATE_INTERVAL_OFF
        )
    return DEFAULT_UPDATE_CHECK_INTERVAL


def should_run_silent_update_check(settings: dict | None, *, now: float | None = None) -> bool:
    settings = settings or {}
    interval = resolve_update_check_interval(settings)
    if interval == UPDATE_INTERVAL_OFF:
        return False
    if interval == UPDATE_INTERVAL_EVERY_LAUNCH:
        return True
    period = _UPDATE_INTERVAL_SECONDS.get(interval)
    if period is None:
        return False
    try:
        last = float(settings.get(KEY_LAST_UPDATE_CHECK_TS) or 0)
    except (TypeError, ValueError):
        last = 0.0
    stamp = time.time() if now is None else now
    if last <= 0:
        return True
    return (stamp - last) >= period


def stamp_last_update_check(app, *, ts: float | None = None) -> None:
    if not hasattr(app, "save_user_settings"):
        return
    app.save_user_settings(KEY_LAST_UPDATE_CHECK_TS, float(time.time() if ts is None else ts))


def normalize_hide_update_available_badge(value: object | None) -> bool:
    if value is None:
        return DEFAULT_HIDE_UPDATE_AVAILABLE_BADGE
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return DEFAULT_HIDE_UPDATE_AVAILABLE_BADGE


def load_hide_update_available_badge(settings: dict | None) -> bool:
    return normalize_hide_update_available_badge(
        (settings or {}).get(
            KEY_HIDE_UPDATE_AVAILABLE_BADGE, DEFAULT_HIDE_UPDATE_AVAILABLE_BADGE
        )
    )


def save_hide_update_available_badge(app, hide: bool) -> None:
    if not hasattr(app, "save_user_settings"):
        return
    app.save_user_settings(
        KEY_HIDE_UPDATE_AVAILABLE_BADGE,
        normalize_hide_update_available_badge(hide),
    )


# ----- Update Center: Keep when updating -----

KEY_UPDATE_KEEP_WHEN = "update_keep_when_updating"

UPDATE_KEEP_VIDEOS = "videos"
UPDATE_KEEP_SETTINGS = "settings"
UPDATE_KEEP_RENDER_HISTORY = "render_history"
UPDATE_KEEP_PRESETS = "presets"

DEFAULT_UPDATE_KEEP_WHEN: dict[str, bool] = {
    UPDATE_KEEP_VIDEOS: True,
    UPDATE_KEEP_SETTINGS: True,
    UPDATE_KEEP_RENDER_HISTORY: True,
    UPDATE_KEEP_PRESETS: True,
}


def normalize_update_keep_when(value: object | None) -> dict[str, bool]:
    """Normalize Keep when updating checkbox prefs (defaults all on)."""
    out = dict(DEFAULT_UPDATE_KEEP_WHEN)
    if not isinstance(value, dict):
        return out
    for key in DEFAULT_UPDATE_KEEP_WHEN:
        if key in value:
            out[key] = bool(value.get(key))
    return out


def load_update_keep_when(settings: dict | None) -> dict[str, bool]:
    return normalize_update_keep_when(
        (settings or {}).get(KEY_UPDATE_KEEP_WHEN)
    )


def save_update_keep_when(app, prefs: dict[str, bool] | None) -> None:
    if not hasattr(app, "save_user_settings"):
        return
    app.save_user_settings(
        KEY_UPDATE_KEEP_WHEN,
        normalize_update_keep_when(prefs),
    )


# ----- Date / time / timezone display -----

KEY_DATE_FORMAT = "date_format"
KEY_CLOCK_FORMAT = "clock_format"
KEY_DISPLAY_TIMEZONE = "display_timezone"

DATE_FMT_SYSTEM = "system"
DATE_FMT_US = "us"
DATE_FMT_EU = "eu"
DATE_FMT_ISO = "iso"
DEFAULT_DATE_FORMAT = DATE_FMT_SYSTEM

DATE_FORMAT_LABELS: tuple[tuple[str, str], ...] = (
    (DATE_FMT_SYSTEM, "System locale (e.g. 11 May 2026)"),
    (DATE_FMT_US, "US, 12/03/01"),
    (DATE_FMT_EU, "EU, 29.12.2001"),
    (DATE_FMT_ISO, "ISO, 2000/12/22"),
)

CLOCK_AUTO = "auto"
CLOCK_12 = "12"
CLOCK_24 = "24"
DEFAULT_CLOCK_FORMAT = CLOCK_AUTO

CLOCK_FORMAT_LABELS: tuple[tuple[str, str], ...] = (
    (CLOCK_AUTO, "Auto (follow date / OS)"),
    (CLOCK_12, "12-hour (AM/PM)"),
    (CLOCK_24, "24-hour"),
)

TZ_SYSTEM = "system"
DEFAULT_DISPLAY_TIMEZONE = TZ_SYSTEM

# Common IANA zones for the Settings combo (System always first).
DISPLAY_TIMEZONE_LABELS: tuple[tuple[str, str], ...] = (
    (TZ_SYSTEM, "System local"),
    ("UTC", "UTC"),
    ("America/New_York", "America/New_York"),
    ("America/Chicago", "America/Chicago"),
    ("America/Denver", "America/Denver"),
    ("America/Los_Angeles", "America/Los_Angeles"),
    ("America/Sao_Paulo", "America/Sao_Paulo"),
    ("Europe/London", "Europe/London"),
    ("Europe/Berlin", "Europe/Berlin"),
    ("Europe/Moscow", "Europe/Moscow"),
    ("Asia/Tokyo", "Asia/Tokyo"),
    ("Asia/Shanghai", "Asia/Shanghai"),
    ("Asia/Seoul", "Asia/Seoul"),
    ("Australia/Sydney", "Australia/Sydney"),
)


def normalize_date_format(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "locale": DATE_FMT_SYSTEM,
        "default": DATE_FMT_SYSTEM,
        "os": DATE_FMT_SYSTEM,
        "usa": DATE_FMT_US,
        "us_ish": DATE_FMT_US,
        "eu_day_first": DATE_FMT_EU,
        "european": DATE_FMT_EU,
        "server": DATE_FMT_ISO,
        "iso_ish": DATE_FMT_ISO,
        "ymd": DATE_FMT_ISO,
    }
    if text in (DATE_FMT_SYSTEM, DATE_FMT_US, DATE_FMT_EU, DATE_FMT_ISO):
        return text
    return aliases.get(text, DEFAULT_DATE_FORMAT)


def normalize_clock_format(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in (CLOCK_AUTO, "os", "locale", "system", ""):
        return CLOCK_AUTO
    if text in (CLOCK_12, "12h", "12_hour", "ampm", "am_pm"):
        return CLOCK_12
    if text in (CLOCK_24, "24h", "24_hour"):
        return CLOCK_24
    return DEFAULT_CLOCK_FORMAT


def normalize_display_timezone(value: object | None) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in ("local", "system", "os"):
        return TZ_SYSTEM
    return text


def load_date_format(settings: dict | None) -> str:
    return normalize_date_format((settings or {}).get(KEY_DATE_FORMAT))


def load_clock_format(settings: dict | None) -> str:
    return normalize_clock_format((settings or {}).get(KEY_CLOCK_FORMAT))


def load_display_timezone(settings: dict | None) -> str:
    return normalize_display_timezone((settings or {}).get(KEY_DISPLAY_TIMEZONE))


# ----- Marker trim offset -----

KEY_MARKER_TRIM_OFFSET_MS = "marker_trim_offset_ms"

MARKER_TRIM_EXACT = 0
MARKER_TRIM_1S = 1000
MARKER_TRIM_2S = 2000
DEFAULT_MARKER_TRIM_OFFSET_MS = MARKER_TRIM_EXACT

MARKER_TRIM_LABELS: tuple[tuple[int, str], ...] = (
    (MARKER_TRIM_EXACT, "Exact (at marker)"),
    (MARKER_TRIM_1S, "Lead-in 1 second"),
    (MARKER_TRIM_2S, "Lead-in 2 seconds"),
)


def normalize_marker_trim_offset_ms(value: object | None) -> int:
    try:
        ms = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_MARKER_TRIM_OFFSET_MS
    if ms in (MARKER_TRIM_EXACT, MARKER_TRIM_1S, MARKER_TRIM_2S):
        return ms
    # Tolerate seconds typed as 1 / 2.
    if ms in (1, 2):
        return ms * 1000
    return DEFAULT_MARKER_TRIM_OFFSET_MS


def load_marker_trim_offset_ms(settings: dict | None) -> int:
    return normalize_marker_trim_offset_ms(
        (settings or {}).get(KEY_MARKER_TRIM_OFFSET_MS, DEFAULT_MARKER_TRIM_OFFSET_MS)
    )


# ----- Markers on the strip (optional v20-style overlay) -----

KEY_MARKERS_ON_STRIP = "markers_on_strip"
DEFAULT_MARKERS_ON_STRIP = False


def normalize_markers_on_strip(value: object | None) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return DEFAULT_MARKERS_ON_STRIP


def load_markers_on_strip(settings: dict | None) -> bool:
    return normalize_markers_on_strip(
        (settings or {}).get(KEY_MARKERS_ON_STRIP, DEFAULT_MARKERS_ON_STRIP)
    )


# ----- Startup library scan -----

KEY_STARTUP_LIBRARY_SCAN = "startup_library_scan"

SCAN_PROGRESSIVE = "progressive"
SCAN_SMART = "smart"
SCAN_FULL = "full"
SCAN_QUICK = "quick"
SCAN_CACHE = "cache"
DEFAULT_STARTUP_LIBRARY_SCAN = SCAN_PROGRESSIVE

STARTUP_SCAN_LABELS: tuple[tuple[str, str], ...] = (
    (SCAN_PROGRESSIVE, "Progressive, load as you scroll"),
    (SCAN_QUICK, "Quick, folders + cached health"),
    (SCAN_FULL, "Full, first launch / new folder"),
    (SCAN_CACHE, "Skip, last session list"),
)


def normalize_startup_library_scan(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        # Smart Launch tested slow (= Skip path); migrate to Progressive.
        "smart": SCAN_PROGRESSIVE,
        "smart_launch": SCAN_PROGRESSIVE,
        "auto": SCAN_PROGRESSIVE,
        "fast": SCAN_QUICK,
        "incremental": SCAN_QUICK,
        "cached_health": SCAN_QUICK,
        "ffprobe": SCAN_FULL,
        "complete": SCAN_FULL,
        "first_launch": SCAN_FULL,
        "off": SCAN_CACHE,
        "skip": SCAN_CACHE,
        "none": SCAN_CACHE,
        "open_from_cache": SCAN_CACHE,
        "from_cache": SCAN_CACHE,
        "no_scan": SCAN_CACHE,
        "stupid_launch": SCAN_PROGRESSIVE,
        "viewport": SCAN_PROGRESSIVE,
        "lazy": SCAN_PROGRESSIVE,
        "as_you_scroll": SCAN_PROGRESSIVE,
    }
    if text in (SCAN_PROGRESSIVE, SCAN_FULL, SCAN_QUICK, SCAN_CACHE):
        return text
    # Legacy key still in old settings.json — do not keep users on Smart.
    if text == SCAN_SMART:
        return SCAN_PROGRESSIVE
    return aliases.get(text, DEFAULT_STARTUP_LIBRARY_SCAN)


def load_startup_library_scan(settings: dict | None) -> str:
    return normalize_startup_library_scan(
        (settings or {}).get(KEY_STARTUP_LIBRARY_SCAN, DEFAULT_STARTUP_LIBRARY_SCAN)
    )


# ----- Media / PyAV-style disk cache -----

KEY_MEDIA_CACHE_LIMIT_GB = "media_cache_limit_gb"
# 0 = unlimited. Default 4 GiB covers posters + remux leftovers.
DEFAULT_MEDIA_CACHE_LIMIT_GB = 4

MEDIA_CACHE_LIMIT_LABELS: tuple[tuple[int, str], ...] = (
    (0, "Unlimited"),
    (1, "1 GB"),
    (2, "2 GB"),
    (4, "4 GB"),
    (8, "8 GB"),
)


def normalize_media_cache_limit_gb(value: object | None) -> int:
    try:
        gb = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_MEDIA_CACHE_LIMIT_GB
    if gb < 0:
        return 0
    allowed = {v for v, _ in MEDIA_CACHE_LIMIT_LABELS}
    if gb in allowed:
        return gb
    # Snap to nearest allowed bucket.
    return min(allowed, key=lambda x: abs(x - gb))


def load_media_cache_limit_gb(settings: dict | None) -> int:
    return normalize_media_cache_limit_gb(
        (settings or {}).get(KEY_MEDIA_CACHE_LIMIT_GB, DEFAULT_MEDIA_CACHE_LIMIT_GB)
    )


# ----- Log levels -----

KEY_APP_LOG_LEVEL = "app_log_level"
KEY_FFMPEG_LOG_LEVEL = "ffmpeg_log_level"
KEY_MPV_LOG_LEVEL = "mpv_log_level"

LOG_LEVEL_DEBUG = "debug"
LOG_LEVEL_INFO = "info"
LOG_LEVEL_WARNING = "warning"
LOG_LEVEL_ERROR = "error"

DEFAULT_APP_LOG_LEVEL = LOG_LEVEL_DEBUG
DEFAULT_FFMPEG_LOG_LEVEL = LOG_LEVEL_ERROR
DEFAULT_MPV_LOG_LEVEL = LOG_LEVEL_INFO

LOG_LEVEL_LABELS: tuple[tuple[str, str], ...] = (
    (LOG_LEVEL_DEBUG, "Debug"),
    (LOG_LEVEL_INFO, "Info"),
    (LOG_LEVEL_WARNING, "Warning"),
    (LOG_LEVEL_ERROR, "Error"),
)

_FFMPEG_LEVEL_MAP = {
    LOG_LEVEL_DEBUG: "debug",
    LOG_LEVEL_INFO: "info",
    LOG_LEVEL_WARNING: "warning",
    LOG_LEVEL_ERROR: "error",
}


def normalize_log_level(value: object | None, *, default: str) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "warn": LOG_LEVEL_WARNING,
        "err": LOG_LEVEL_ERROR,
        "critical": LOG_LEVEL_ERROR,
        "fatal": LOG_LEVEL_ERROR,
        "verbose": LOG_LEVEL_DEBUG,
        "trace": LOG_LEVEL_DEBUG,
    }
    if text in (
        LOG_LEVEL_DEBUG,
        LOG_LEVEL_INFO,
        LOG_LEVEL_WARNING,
        LOG_LEVEL_ERROR,
    ):
        return text
    return aliases.get(text, default)


def load_app_log_level(settings: dict | None) -> str:
    return normalize_log_level(
        (settings or {}).get(KEY_APP_LOG_LEVEL), default=DEFAULT_APP_LOG_LEVEL
    )


def load_ffmpeg_log_level(settings: dict | None) -> str:
    return normalize_log_level(
        (settings or {}).get(KEY_FFMPEG_LOG_LEVEL), default=DEFAULT_FFMPEG_LOG_LEVEL
    )


def load_mpv_log_level(settings: dict | None) -> str:
    return normalize_log_level(
        (settings or {}).get(KEY_MPV_LOG_LEVEL), default=DEFAULT_MPV_LOG_LEVEL
    )


def ffmpeg_cli_loglevel(settings: dict | None = None) -> str:
    """Value for FFmpeg ``-loglevel``."""
    level = load_ffmpeg_log_level(settings)
    return _FFMPEG_LEVEL_MAP.get(level, "error")


def apply_app_log_level(level: object | None) -> None:
    """Reconfigure root logger level (immediate)."""
    import logging as _logging

    name = normalize_log_level(level, default=DEFAULT_APP_LOG_LEVEL)
    py_level = {
        LOG_LEVEL_DEBUG: _logging.DEBUG,
        LOG_LEVEL_INFO: _logging.INFO,
        LOG_LEVEL_WARNING: _logging.WARNING,
        LOG_LEVEL_ERROR: _logging.ERROR,
    }.get(name, _logging.DEBUG)
    root = _logging.getLogger()
    root.setLevel(py_level)
    for handler in root.handlers:
        try:
            handler.setLevel(py_level)
        except Exception:
            pass


# ----- Advanced -----

KEY_CONFIRM_BEFORE_DELETE = "confirm_before_delete"
DEFAULT_CONFIRM_BEFORE_DELETE = True

KEY_REMEMBER_LIBRARY_TAB = "remember_library_tab"
DEFAULT_REMEMBER_LIBRARY_TAB = True

KEY_SCREENSHOTS_FOLDER = "screenshots_folder"

KEY_HWDEC_PREVIEW = "hwdec_preview"
HWDEC_OFF = "no"
HWDEC_AUTO = "auto"
HWDEC_YES = "yes"
DEFAULT_HWDEC_PREVIEW = HWDEC_AUTO

HWDEC_LABELS: tuple[tuple[str, str], ...] = (
    (HWDEC_AUTO, "Auto"),
    (HWDEC_YES, "Force on"),
    (HWDEC_OFF, "Off (software)"),
)


def normalize_hwdec_preview(value: object | None) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "off": HWDEC_OFF,
        "software": HWDEC_OFF,
        "sw": HWDEC_OFF,
        "false": HWDEC_OFF,
        "0": HWDEC_OFF,
        "on": HWDEC_YES,
        "force": HWDEC_YES,
        "true": HWDEC_YES,
        "1": HWDEC_YES,
        "hw": HWDEC_YES,
        "hardware": HWDEC_YES,
    }
    if text in (HWDEC_OFF, HWDEC_AUTO, HWDEC_YES):
        return text
    return aliases.get(text, DEFAULT_HWDEC_PREVIEW)


def load_hwdec_preview(settings: dict | None) -> str:
    return normalize_hwdec_preview(
        (settings or {}).get(KEY_HWDEC_PREVIEW, DEFAULT_HWDEC_PREVIEW)
    )


def load_confirm_before_delete(settings: dict | None) -> bool:
    if KEY_CONFIRM_BEFORE_DELETE not in (settings or {}):
        return DEFAULT_CONFIRM_BEFORE_DELETE
    return bool((settings or {}).get(KEY_CONFIRM_BEFORE_DELETE))


def load_remember_library_tab(settings: dict | None) -> bool:
    if KEY_REMEMBER_LIBRARY_TAB not in (settings or {}):
        return DEFAULT_REMEMBER_LIBRARY_TAB
    return bool((settings or {}).get(KEY_REMEMBER_LIBRARY_TAB))


# Experimental: skip the grey #1e1e1e flash cover on immersive fullscreen
# enter/exit (same as STEEMPEG_FS_COVER=0). Default keeps the cover.
KEY_TEST_NEW_FULLSCREEN = "test_new_fullscreen"
DEFAULT_TEST_NEW_FULLSCREEN = False


def load_test_new_fullscreen(settings: dict | None) -> bool:
    if KEY_TEST_NEW_FULLSCREEN not in (settings or {}):
        return DEFAULT_TEST_NEW_FULLSCREEN
    return bool((settings or {}).get(KEY_TEST_NEW_FULLSCREEN))


# ----- Console mode / Deck gamepad (General → Shell) -----
# Stored as deck_controls for older settings.json. Default: on for steamdeck
# builds, off for Windows / Linux desktop. Future: a simpler D-pad-only
# "PlayStation home" nav style beside this full Console mapping.

KEY_DEV_MODE = "dev_mode"
KEY_DECK_CONTROLS = "deck_controls"
DEFAULT_DEV_MODE = False


def default_deck_controls() -> bool:
    """Steam Deck builds → Console on; Windows / Linux → off."""
    try:
        from steempeg.ui.shell_chooser import is_steamdeck_build

        return bool(is_steamdeck_build())
    except Exception:
        return False


DEFAULT_DECK_CONTROLS = False  # used only when platform probe fails mid-normalize


def normalize_dev_mode(value: object | None) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return DEFAULT_DEV_MODE


def load_dev_mode(settings: dict | None) -> bool:
    return normalize_dev_mode((settings or {}).get(KEY_DEV_MODE, DEFAULT_DEV_MODE))


def normalize_deck_controls(value: object | None) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    if text == "":
        return default_deck_controls()
    return default_deck_controls()


def load_deck_controls(settings: dict | None) -> bool:
    """Console mode — missing key uses platform default (Deck on / desktop off)."""
    settings = settings or {}
    if KEY_DECK_CONTROLS not in settings:
        return default_deck_controls()
    return normalize_deck_controls(settings.get(KEY_DECK_CONTROLS))


def deck_controls_enabled(settings: dict | None = None, *, app=None) -> bool:
    """Console / Dev-pad actions — Console mode opt-in or Developer mode (QA)."""
    if settings is None:
        settings = {}
        if app is not None and hasattr(app, "load_user_settings"):
            try:
                settings = app.load_user_settings() or {}
            except Exception:
                settings = {}
    if load_deck_controls(settings):
        return True
    if load_dev_mode(settings):
        return True
    return False


def normalize_screenshots_folder(value: object | None) -> str:
    return str(value or "").strip().replace("\\", "/")


def default_screenshots_dir() -> str:
    from steempeg.infra.paths import get_save_directory

    path = os.path.join(get_save_directory(), "Screenshots").replace("\\", "/")
    if not os.path.isdir(path):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            logging.exception("Could not create screenshots dir %s", path)
    return path


def resolve_screenshots_folder(settings: dict | None) -> str:
    folder = normalize_screenshots_folder((settings or {}).get(KEY_SCREENSHOTS_FOLDER))
    if folder and os.path.isdir(folder):
        return folder
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
            if os.path.isdir(folder):
                return folder
        except OSError:
            logging.warning("Could not create screenshots folder %s", folder)
    return default_screenshots_dir()


# Live values used by FFmpeg CLI / MPV create (updated at startup + Settings Save).
_runtime_ffmpeg_loglevel = "error"
_runtime_mpv_loglevel = DEFAULT_MPV_LOG_LEVEL
_runtime_hwdec = DEFAULT_HWDEC_PREVIEW
_runtime_marker_trim_ms = DEFAULT_MARKER_TRIM_OFFSET_MS
_runtime_markers_on_strip = DEFAULT_MARKERS_ON_STRIP
_runtime_test_new_fullscreen = DEFAULT_TEST_NEW_FULLSCREEN


def configure_runtime_prefs(settings: dict | None = None) -> None:
    """Apply log / hwdec / marker-trim / date prefs for the live process."""
    global _runtime_ffmpeg_loglevel, _runtime_mpv_loglevel
    global _runtime_hwdec, _runtime_marker_trim_ms
    global _runtime_markers_on_strip
    global _runtime_test_new_fullscreen
    settings = settings or {}
    apply_app_log_level(load_app_log_level(settings))
    _runtime_ffmpeg_loglevel = ffmpeg_cli_loglevel(settings)
    try:
        from steempeg.infra.logging import set_ffmpeg_cli_loglevel

        set_ffmpeg_cli_loglevel(_runtime_ffmpeg_loglevel)
    except Exception:
        pass
    _runtime_mpv_loglevel = load_mpv_log_level(settings)
    _runtime_hwdec = load_hwdec_preview(settings)
    _runtime_marker_trim_ms = load_marker_trim_offset_ms(settings)
    _runtime_markers_on_strip = load_markers_on_strip(settings)
    _runtime_test_new_fullscreen = load_test_new_fullscreen(settings)
    try:
        from steempeg.infra.locale_time import configure_display_time

        configure_display_time(settings)
    except Exception:
        logging.exception("configure_display_time failed")


def immersive_transition_cover_enabled() -> bool:
    """Whether the grey fullscreen enter/exit cover should show.

    Env STEEMPEG_FS_COVER overrides the Settings toggle (0=off, 1=on).
    """
    raw = (os.environ.get("STEEMPEG_FS_COVER") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return not bool(_runtime_test_new_fullscreen)


def current_ffmpeg_loglevel() -> str:
    return _runtime_ffmpeg_loglevel or "error"


def current_mpv_loglevel() -> str:
    return _runtime_mpv_loglevel or DEFAULT_MPV_LOG_LEVEL


def current_hwdec_preview() -> str:
    return _runtime_hwdec or DEFAULT_HWDEC_PREVIEW


def current_marker_trim_offset_ms() -> int:
    return int(_runtime_marker_trim_ms or 0)


def current_markers_on_strip() -> bool:
    return bool(_runtime_markers_on_strip)


def set_markers_on_strip(enabled: object | None) -> bool:
    """Update the live overlay flag (Settings preview / Save)."""
    global _runtime_markers_on_strip
    _runtime_markers_on_strip = normalize_markers_on_strip(enabled)
    return _runtime_markers_on_strip


# Player chrome outline — runtime in player_outline.py; re-export for Settings.
from steempeg.ui.player_outline import (  # noqa: E402
    KEY_PLAYER_OUTLINE,
    PLAYER_OUTLINE_CHROME_ONLY,
    PLAYER_OUTLINE_DEFAULT,
    PLAYER_OUTLINE_LABELS,
    PLAYER_OUTLINE_WITH_LINES,
    PLAYER_OUTLINE_WITHOUT_LINES,
    get_player_outline,
    load_player_outline_from_settings,
    normalize_player_outline,
    set_player_outline,
)