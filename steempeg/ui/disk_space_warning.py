"""Linux-only Steempeg chrome dialog when the remux/cache volume is too full."""
from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, Qt

from steempeg.infra.disk_space import (
    DiskSpaceStatus,
    format_gib,
    is_linux_disk_guard_enabled,
    probe_cache_volume,
)
from steempeg.ui.message_dialog import DialogButton, SteempegMessageDialog

_log = logging.getLogger(__name__)

_TITLE = "Not enough free space"
_MESSAGE = (
    "The disk is full or does not have enough free space. "
    "The application may work incorrectly."
)

_session_warned = False


def _parent_widget(app_or_parent):
    if app_or_parent is None:
        return None
    ui = getattr(app_or_parent, "ui", None)
    return ui if ui is not None else app_or_parent


def _bring_widget_to_front(widget) -> None:
    if widget is None:
        return
    try:
        widget.raise_()
        widget.activateWindow()
        handle = widget.windowHandle()
        if handle is not None:
            handle.requestActivate()
    except Exception:
        pass
    try:
        from steempeg.infra.window_focus import force_widget_foreground

        force_widget_foreground(widget)
    except Exception:
        pass


def _detail_for(status: DiskSpaceStatus, *, cannot_proceed: bool) -> str:
    free = format_gib(status.free)
    path = status.path
    if cannot_proceed and status.need_bytes > 0:
        return (
            f"This clip needs about {format_gib(status.need_bytes)}, but only "
            f"{free} is free on {path}. Free some space and try again."
        )
    if status.need_bytes > 0:
        return (
            f"This clip needs about {format_gib(status.need_bytes)}; "
            f"{free} is free on {path}."
        )
    return f"About {free} free on {path}."


def _show_disk_dialog(parent, status: DiskSpaceStatus, *, cannot_proceed: bool) -> None:
    global _session_warned
    _session_warned = True
    parent = _parent_widget(parent)
    _bring_widget_to_front(parent)
    dlg = SteempegMessageDialog(
        _TITLE,
        _MESSAGE,
        parent,
        detail=_detail_for(status, cannot_proceed=cannot_proceed),
        buttons=(DialogButton("OK", "danger" if cannot_proceed else "primary", accept=True),),
        min_width=420,
    )
    dlg.setModal(True)
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    _log.warning(
        "Linux disk space dialog: free=%s need=%s path=%s cannot_proceed=%s",
        format_gib(status.free),
        format_gib(status.need_bytes) if status.need_bytes else "—",
        status.path,
        cannot_proceed,
    )
    QTimer.singleShot(0, lambda: _bring_widget_to_front(dlg))
    dlg.exec()


def warn_linux_low_disk_at_startup(app_or_parent) -> None:
    """Modal once-per-session warning after the main window exists (Linux only)."""
    global _session_warned
    if not is_linux_disk_guard_enabled() or _session_warned:
        return
    status = probe_cache_volume()
    if not (status.low_free or status.volume_nearly_full):
        return
    _show_disk_dialog(app_or_parent, status, cannot_proceed=False)


def schedule_linux_low_disk_startup_warning(app_or_parent) -> None:
    if not is_linux_disk_guard_enabled():
        return
    QTimer.singleShot(100, lambda: warn_linux_low_disk_at_startup(app_or_parent))


def ensure_linux_disk_for_remux(parent, need_bytes: int = 0) -> bool:
    """Show the disk dialog if needed. Return False when remux must not start."""
    if not is_linux_disk_guard_enabled():
        return True
    status = probe_cache_volume(need_bytes)
    if status.remux_cannot_fit:
        _show_disk_dialog(parent, status, cannot_proceed=True)
        return False
    if status.should_warn and not _session_warned:
        _show_disk_dialog(parent, status, cannot_proceed=False)
    return True


def warn_linux_disk_remux_blocked(parent, exc_or_text: object | None = None) -> None:
    """Always-on remux refusal dialog (even if the session warning already ran)."""
    if not is_linux_disk_guard_enabled():
        return
    if exc_or_text:
        _log.warning("DASH remux blocked by disk space: %s", exc_or_text)
    _show_disk_dialog(parent, probe_cache_volume(), cannot_proceed=True)
