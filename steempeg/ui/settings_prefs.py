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

# ----- Permanent export folder -----

KEY_PERMANENT_EXPORT_FOLDER = "permanent_export_folder"

# ----- Update check interval -----

KEY_UPDATE_CHECK_INTERVAL = "update_check_interval"
KEY_LAST_UPDATE_CHECK_TS = "last_update_check_ts"
# Legacy boolean — migrated once into KEY_UPDATE_CHECK_INTERVAL.
KEY_CHECK_UPDATES_ON_STARTUP = "check_updates_on_startup"

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
            app.set_status("Export folder unavailable — using default rendered_videos")
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
