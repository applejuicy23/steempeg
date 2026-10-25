"""Shell splitter handles — always theme-visible (hover-reveal disabled).

Like a Portable middle hide-until-hover was killed after it caused whole-UI lag
(cursor polls / stylesheet thrash) and broke SplitH/V cursors. Keep this module
as a thin paint helper so call sites stay stable.

Like a Portable hides the middle handle by default (fixed air gap via
``PORTABLE_LIKE_MIDDLE_GAP``). Settings can opt in to restore the player↔dash
splitter handle and drag snap.
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


def _desktop_portable_like(app) -> bool:
    check = getattr(app, "_desktop_render_layout_is_portable_like", None)
    if callable(check):
        try:
            return bool(check())
        except Exception:
            return False
    return False


def _portable_like_hides_middle_handle(app) -> bool:
    if not _desktop_portable_like(app):
        return False
    check = getattr(app, "_portable_like_middle_splitter_enabled", None)
    if callable(check):
        try:
            return not bool(check())
        except Exception:
            return True
    from steempeg.ui.settings_prefs import load_portable_like_middle_splitter

    settings = {}
    if hasattr(app, "load_user_settings"):
        try:
            settings = app.load_user_settings() or {}
        except Exception:
            settings = {}
    return not load_portable_like_middle_splitter(settings)


def sync_portable_splitter_reveal(app) -> None:
    """No-op reveal: tear down any live controller and paint always-on handles."""
    _kill_reveal_controller(app)
    paint_desktop_splitter_handles(app)


def paint_desktop_splitter_handles(app) -> None:
    """Always-visible side handles; hide middle handle when pref is off."""
    _clear_handle_widget_styles(app)
    _apply_visible_splitter_styles(app)
    if _portable_like_hides_middle_handle(app):
        _hide_middle_handle(app)
    else:
        _restore_handle_cursors(app, names=_SHELL_SPLITTER_NAMES)
    _hide_queue_handle_for_hover(app)
    # Theme/layout refresh must not resurrect the dark right seam in FS/theatre.
    if bool(getattr(app, "is_fullscreen", False)) or bool(
        getattr(app, "is_theater", False)
    ):
        hide = getattr(app, "_hide_right_h_splitter_handle", None)
        if callable(hide):
            try:
                hide()
            except Exception:
                pass
        setter = getattr(app, "_set_splitter_handle_visible", None)
        if callable(setter):
            main = getattr(getattr(app, "ui", None), "main_splitter", None)
            if main is not None:
                try:
                    setter(main, False, 1)
                except Exception:
                    pass
    _enforce_user_hidden_handles(app)


def _hide_queue_handle_for_hover(app) -> None:
    """Hover slide-out owns the queue edge — keep that splitter handle gone."""
    check = getattr(app, "_queue_hover_is_floating", None)
    if not callable(check):
        return
    try:
        if not bool(check()):
            return
    except Exception:
        return
    setter = getattr(app, "_set_splitter_handle_visible", None)
    if not callable(setter):
        return
    queue_left = False
    side = getattr(app, "_queue_on_left", None)
    if callable(side):
        try:
            queue_left = bool(side())
        except Exception:
            queue_left = False
    if queue_left:
        splitter = getattr(getattr(app, "ui", None), "main_splitter", None)
    else:
        splitter = getattr(app, "right_h_splitter", None)
    setter(splitter, False, 1)
    if isinstance(splitter, QSplitter):
        try:
            live = int(splitter.handleWidth() or 0)
            if live > 0:
                app._queue_hover_saved_handle_w = live
            splitter.setHandleWidth(0)
            if splitter.count() >= 2:
                handle = splitter.handle(1)
                if handle is not None:
                    handle.setVisible(False)
        except RuntimeError:
            pass


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
        if splitter.count() >= 2:
            handle = splitter.handle(1)
            if handle is not None:
                handle.setMinimumWidth(0)
                handle.setMaximumWidth(16777215)
                handle.setStyleSheet("")
                handle.setVisible(True)
                handle.show()
        splitter.setHandleWidth(width)
    except RuntimeError:
        return
    paint_desktop_splitter_handles(app)


def user_hides_shell_handles(app) -> bool:
    """True when Settings says the Clips / player / queue handles stay hidden."""
    from steempeg.ui.settings_prefs import load_hide_splitter_handles

    settings = {}
    if hasattr(app, "load_user_settings"):
        try:
            settings = app.load_user_settings() or {}
        except Exception:
            settings = {}
    return load_hide_splitter_handles(settings)


def _shell_widgets(app):
    """Return (main splitter, inner splitter, clips, player, queue) or None."""
    ui = getattr(app, "ui", None)
    main = getattr(ui, "main_splitter", None) if ui is not None else None
    inner = getattr(app, "right_h_splitter", None)
    clips = getattr(ui, "left_panel", None) if ui is not None else None
    player = getattr(ui, "right_panel", None) if ui is not None else None
    queue = getattr(app, "render_queue_panel", None)
    if not all(isinstance(item, QSplitter) for item in (main, inner)):
        return None
    if clips is None or player is None or queue is None:
        return None
    return main, inner, clips, player, queue


def _width_in_splitter(splitter: QSplitter, widget) -> int:
    """Pixel width of ``widget`` inside ``splitter``, or 0 when it is not a child."""
    try:
        index = splitter.indexOf(widget)
        sizes = splitter.sizes()
    except RuntimeError:
        return 0
    if index < 0 or index >= len(sizes):
        return 0
    return int(sizes[index])


def shell_pane_widths(app) -> tuple[int, int, int] | None:
    """Live Clips, player and queue widths in pixels."""
    found = _shell_widgets(app)
    if found is None:
        return None
    main, inner, clips, player, queue = found
    return (
        _width_in_splitter(main, clips) or _width_in_splitter(inner, clips),
        _width_in_splitter(inner, player) or _width_in_splitter(main, player),
        _width_in_splitter(main, queue) or _width_in_splitter(inner, queue),
    )


def snapshot_shell_pane_percents(app) -> tuple[int, int, int]:
    """Read the live three-pane layout as percentages that sum to 100."""
    from steempeg.ui.settings_prefs import normalize_shell_pane_percents

    widths = shell_pane_widths(app)
    if widths is None or sum(widths) <= 0:
        return normalize_shell_pane_percents(None)
    return normalize_shell_pane_percents(widths)


def _apply_shell_pane_percents(app, percents: tuple[int, int, int]) -> None:
    """Size Clips, the player and the queue from percentages of their current total."""
    found = _shell_widgets(app)
    if found is None:
        return
    main, inner, clips, player, queue = found
    clips_pct, player_pct, queue_pct = percents
    widths = shell_pane_widths(app)
    total = sum(widths) if widths else 0
    if total <= 0:
        try:
            total = int(main.width() or 0)
        except RuntimeError:
            total = 0
    if total <= 0:
        return
    clips_w = total * int(clips_pct) // 100
    queue_w = total * int(queue_pct) // 100
    player_w = max(0, total - clips_w - queue_w)
    main.blockSignals(True)
    inner.blockSignals(True)
    try:
        _set_pair_sizes(main, clips, clips_w, player_w + queue_w)
        if main.indexOf(queue) == 0:
            _set_pair_sizes(main, queue, queue_w, player_w + clips_w)
            _set_pair_sizes(inner, player, player_w, clips_w)
        else:
            _set_pair_sizes(inner, player, player_w, queue_w)
    finally:
        main.blockSignals(False)
        inner.blockSignals(False)


def _set_pair_sizes(splitter: QSplitter, first, first_w: int, second_w: int) -> None:
    """Write a two-child splitter so ``first`` gets ``first_w`` pixels."""
    try:
        index = splitter.indexOf(first)
    except RuntimeError:
        return
    if index < 0 or splitter.count() < 2:
        return
    sizes = [0, 0]
    sizes[index] = max(0, int(first_w))
    sizes[1 - index] = max(0, int(second_w))
    try:
        splitter.setSizes(sizes)
    except RuntimeError:
        return


def _set_side_handles_visible(app, visible: bool) -> None:
    """Show or hide the two handles that separate Clips, the player and the queue.

    A width of 0 still paints the handle stylesheet as a dark seam, so a hidden
    handle also drops that paint.
    """
    setter = getattr(app, "_set_splitter_handle_visible", None)
    for _name, splitter in _iter_shell_splitters(app, _SIDE_SPLITTER_NAMES):
        try:
            if splitter.count() < 2:
                continue
            handle = splitter.handle(1)
        except RuntimeError:
            continue
        if visible:
            if handle is not None:
                handle.setMinimumWidth(0)
                handle.setMaximumWidth(16777215)
                handle.setStyleSheet("")
                handle.setEnabled(True)
                handle.setVisible(True)
                handle.show()
            splitter.setHandleWidth(6)
            if callable(setter):
                setter(splitter, True, 1)
            continue
        splitter.setHandleWidth(0)
        if handle is not None:
            handle.setStyleSheet("background: transparent; border: none; margin: 0px;")
            handle.setEnabled(False)
            handle.setVisible(False)
            handle.hide()
        if callable(setter):
            setter(splitter, False, 1)


def _enforce_user_hidden_handles(app) -> None:
    """Re-hide side handles after a paint pass that would show them again."""
    if not user_hides_shell_handles(app):
        return
    _set_side_handles_visible(app, False)


def apply_user_shell_handle_visibility(app) -> None:
    """Apply the Settings choice: hidden handles keep the saved pane widths."""
    if getattr(app, "_portable_shell", False):
        return
    if bool(getattr(app, "is_theater", False)) or bool(getattr(app, "is_fullscreen", False)):
        return
    if not user_hides_shell_handles(app):
        _set_side_handles_visible(app, True)
        paint_desktop_splitter_handles(app)
        return
    from steempeg.ui.settings_prefs import saved_shell_pane_percents

    settings = {}
    if hasattr(app, "load_user_settings"):
        try:
            settings = app.load_user_settings() or {}
        except Exception:
            settings = {}
    percents = saved_shell_pane_percents(settings)
    if percents is not None:
        _apply_shell_pane_percents(app, percents)
    _set_side_handles_visible(app, False)


def _hide_middle_handle(app) -> None:
    """Like a Portable: zero-width middle handle + side cursors only."""
    apply = getattr(app, "_set_main_v_splitter_handle_visible", None)
    if callable(apply):
        try:
            apply(False)
        except Exception:
            pass
    else:
        for _name, splitter in _iter_shell_splitters(app, (_MIDDLE_SPLITTER_NAME,)):
            try:
                splitter.setHandleWidth(0)
                if splitter.count() >= 2:
                    handle = splitter.handle(1)
                    if handle is not None:
                        handle.setEnabled(False)
                        handle.hide()
            except RuntimeError:
                continue
    _restore_handle_cursors(app, names=_SIDE_SPLITTER_NAMES)


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
    hide_middle = _portable_like_hides_middle_handle(app)

    for name, splitter in _iter_shell_splitters(app):
        try:
            splitter.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            if name == _MIDDLE_SPLITTER_NAME:
                if hide_middle:
                    # No painted bar — gap comes from layout margins only.
                    splitter.setStyleSheet(
                        f"QSplitter {{ {shell} }} "
                        "QSplitter::handle { height: 0px; margin: 0px; "
                        "background: transparent; }"
                    )
                else:
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


def _restore_handle_cursors(
    app, names: tuple[str, ...] = _SIDE_SPLITTER_NAMES
) -> None:
    """Ensure Qt splitter drag cursors after any prior handle QSS / filter mess.

    ``SplitHCursor`` / ``SplitVCursor`` — left/right (or up/down) arrows with
    the double bar in the middle, not plain SizeHor ↔.
    """
    for _name, splitter in _iter_shell_splitters(app, names):
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


def restore_shell_splitter_cursors(app=None) -> None:
    """Public: re-apply drag cursors on shell splitter handles (desktop + Portable)."""
    if app is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        # Prefer the Steempeg main window if present.
        for w in app.topLevelWidgets():
            if hasattr(w, "main_splitter") or hasattr(
                getattr(w, "ui", None), "main_splitter"
            ):
                app = w
                break
    _restore_handle_cursors(app, names=_SHELL_SPLITTER_NAMES)
