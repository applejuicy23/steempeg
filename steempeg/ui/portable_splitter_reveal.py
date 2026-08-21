"""Shell splitter handles — always theme-visible (hover-reveal disabled).

Like a Portable middle hide-until-hover was killed after it caused whole-UI lag
(cursor polls / stylesheet thrash) and broke SplitH/V cursors. Keep this module
as a thin paint helper so call sites stay stable; reintroduce reveal only with a
cheap, transition-only design later.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QSplitterHandle

from steempeg.ui.layout_defaults import (
    horizontal_splitter_handle_qss,
    vertical_splitter_handle_qss,
)

_SIDE_SPLITTER_NAMES = ("main_splitter", "right_h_splitter")
_MIDDLE_SPLITTER_NAME = "main_v_splitter"
_SHELL_SPLITTER_NAMES = _SIDE_SPLITTER_NAMES + (_MIDDLE_SPLITTER_NAME,)


def sync_portable_splitter_reveal(app) -> None:
    """No-op reveal: tear down any live controller and paint always-on handles."""
    _kill_reveal_controller(app)
    paint_desktop_splitter_handles(app)


def paint_desktop_splitter_handles(app) -> None:
    """Always-visible, theme-aware handles + native resize cursors."""
    _clear_handle_widget_styles(app)
    _apply_visible_splitter_styles(app)
    _restore_handle_cursors(app)


def ensure_right_h_handle_chrome(app) -> None:
    """Force player|queue handle back after immersive hide (width 0 / setVisible).

    Fullscreen/theatre zero the right handle to kill the dark edge strip. Qt can
    leave it missing after exit if we only paint styles — restore geometry first,
    then re-apply the always-on theme paint (no hover-reveal poll).
    """
    splitter = getattr(app, "right_h_splitter", None)
    if not isinstance(splitter, QSplitter):
        return
    width = int(getattr(app, "_immersive_right_h_handle_width", 0) or 0)
    if width <= 0:
        width = int(getattr(app, "_pre_theater_right_handle_width", 0) or 0)
    if width <= 0:
        width = 6
    try:
        splitter.setHandleWidth(width)
        if splitter.count() >= 2:
            handle = splitter.handle(1)
            if handle is not None:
                handle.setVisible(True)
                handle.show()
    except RuntimeError:
        return
    paint_desktop_splitter_handles(app)


def _kill_reveal_controller(app) -> None:
    controller = getattr(app, "_portable_splitter_reveal", None)
    if controller is None:
        return
    try:
        stop = getattr(controller, "deactivate", None) or getattr(
            controller, "stop", None
        )
        if callable(stop):
            stop()
    except Exception:
        pass
    # Hard-stop leftover timers / filters even if deactivate is a stub.
    for attr in ("_cursor_poll", "_leave_poll", "_poll"):
        timer = getattr(controller, attr, None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
    try:
        delattr(app, "_portable_splitter_reveal")
    except Exception:
        app._portable_splitter_reveal = None


def _iter_shell_splitters(app, names: tuple[str, ...] = _SHELL_SPLITTER_NAMES):
    for name in names:
        splitter = getattr(app, name, None)
        if splitter is None and hasattr(app, "ui"):
            splitter = getattr(app.ui, name, None)
        if isinstance(splitter, QSplitter):
            yield name, splitter


def _shell_bg(app) -> str:
    dark = "#1e1e1e"
    try:
        if hasattr(app, "_current_app_bg"):
            dark = app._current_app_bg()
    except Exception:
        pass
    return dark


def _visible_handle_qss(*, vertical: bool) -> str:
    from steempeg.ui.ui_theme import splitter_handle_colors

    idle, hover = splitter_handle_colors(vertical=vertical)
    if vertical:
        return vertical_splitter_handle_qss(idle, hover)
    return horizontal_splitter_handle_qss(idle, hover)


def _apply_visible_splitter_styles(app) -> None:
    dark = _shell_bg(app)
    shell = f"background-color: {dark};"
    h_qss = f"QSplitter {{ {shell} }} {_visible_handle_qss(vertical=False)}"
    v_qss = _visible_handle_qss(vertical=True)

    for name, splitter in _iter_shell_splitters(app):
        try:
            splitter.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            if name == _MIDDLE_SPLITTER_NAME:
                splitter.setStyleSheet(v_qss)
            else:
                splitter.setStyleSheet(h_qss)
        except RuntimeError:
            continue


def _clear_handle_widget_styles(app) -> None:
    for _name, splitter in _iter_shell_splitters(app):
        try:
            if splitter.count() < 2:
                continue
            handle = splitter.handle(1)
            if handle is not None:
                handle.setStyleSheet("")
                handle.unsetCursor()
        except RuntimeError:
            continue


def _restore_handle_cursors(app) -> None:
    """Ensure Qt resize arrows after any prior handle QSS / filter mess."""
    for name, splitter in _iter_shell_splitters(app):
        try:
            if splitter.count() < 2:
                continue
            handle = splitter.handle(1)
            if handle is None:
                continue
            if not isinstance(handle, QSplitterHandle):
                continue
            # Clear widget-level override first so orientation cursor sticks.
            handle.unsetCursor()
            if splitter.orientation() == Qt.Orientation.Horizontal:
                handle.setCursor(Qt.CursorShape.SplitHCursor)
            else:
                handle.setCursor(Qt.CursorShape.SplitVCursor)
        except RuntimeError:
            continue
