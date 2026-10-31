"""Shell splitter handles — always theme-visible (hover-reveal disabled).

Like a Portable middle hide-until-hover was killed after it caused whole-UI lag
(cursor polls / stylesheet thrash) and broke SplitH/V cursors. Keep this module
as a thin paint helper so call sites stay stable.

Like a Portable hides the middle handle by default (fixed air gap via
``PORTABLE_LIKE_MIDDLE_GAP``). Settings can opt in to restore the player↔dash
splitter handle and drag snap.
"""
from __future__ import annotations

import logging

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


def _shell_span(app) -> tuple[int, int]:
    """Return (window width, splitter width) for the desktop shell."""
    ui = getattr(app, "ui", None)
    win_w = 0
    if ui is not None:
        try:
            win_w = int(ui.width() or 0)
        except RuntimeError:
            win_w = 0
    main = getattr(ui, "main_splitter", None) if ui is not None else None
    shell = 0
    if main is not None:
        try:
            sizes = main.sizes()
            shell = sum(int(part) for part in sizes)
            if shell <= 0:
                shell = int(main.width() or 0)
        except RuntimeError:
            shell = 0
    if shell <= 0:
        shell = win_w
    return win_w, shell


def _queue_hover_is_on(app) -> bool:
    """True when the queue is the slide-out overlay, not a docked splitter pane."""
    check = getattr(app, "_queue_hover_is_floating", None)
    if not callable(check):
        return False
    try:
        return bool(check())
    except Exception:
        return False


def _queue_slot(app, panel):
    """Widget that occupies the queue's splitter slot.

    Hover mode lifts the real panel into the overlay and leaves a zero-width
    placeholder in the splitter. Side checks have to use that placeholder:
    the panel itself is no longer a splitter child, so ``indexOf`` misses it
    and a queue-left layout is written as if the library were still on the left.
    """
    getter = getattr(app, "_queue_dock_widget", None)
    if callable(getter):
        try:
            dock = getter()
        except Exception:
            dock = None
        if dock is not None:
            return dock
    return panel


def _cancel_shell_pane_snap(app) -> None:
    """Drop a kiss snap armed by a programmatic splitter change.

    ``splitterMoved`` starts the same timer a handle drag uses. A side swap or
    a percent apply must not be finished as a kiss, or the width just written
    for the library or the player is replaced with 0.
    """
    timer = getattr(app, "_right_h_snap_timer", None)
    if timer is None:
        return
    try:
        timer.stop()
    except RuntimeError:
        return


def _apply_hover_overlay_width(app, width: int) -> None:
    """Resize the slide-out queue. A hidden overlay keeps the width for the next reveal."""
    ctrl = getattr(app, "_queue_hover", None)
    overlay = getattr(ctrl, "_overlay", None) if ctrl is not None else None
    if overlay is None or not hasattr(overlay, "set_panel_width"):
        return
    try:
        overlay.set_panel_width(int(width))
    except RuntimeError:
        return


def _apply_shell_pane_percents(app, percents: tuple[int, int, int]) -> None:
    """Size Clips, the player and the queue from percentages of their current total.

    Hover queue is not a splitter pane: its percent is the overlay width, and
    the docked slot stays shut. A stored queue of 0 means "leave the overlay
    on its remembered width" so an older save does not collapse the slide-out.
    """
    from steempeg.ui.layout_defaults import (
        fit_shell_pane_pixels,
        shell_pane_pixel_limits,
        shell_percents_to_pixels,
    )

    found = _shell_widgets(app)
    if found is None:
        return
    main, inner, clips, player, queue = found
    win_w, shell = _shell_span(app)
    if shell <= 0:
        return
    hover = _queue_hover_is_on(app)
    limits = shell_pane_pixel_limits(win_w or shell, hover=hover, shell_width=shell)
    clips_pct, player_pct, queue_pct = (int(percents[0]), int(percents[1]), int(percents[2]))
    # Keep the requested shares. fit_shell_pane_pixels may legally floor a pane
    # on a short window, and those pixels are not the ratio a later maximize
    # should grow back to.
    if not getattr(app, "_shell_pane_refitting", False):
        app._shell_pane_ratio = (clips_pct, player_pct, queue_pct)
    clips_w, player_w, queue_w = shell_percents_to_pixels(
        clips_pct,
        player_pct,
        queue_pct,
        shell=shell,
        window=win_w or shell,
        hover=hover,
    )
    clips_w, player_w, queue_w = fit_shell_pane_pixels(
        clips_w,
        player_w,
        queue_w,
        limits,
        shell,
        hover=hover,
        changed="clips",
    )
    # The overlay width must not be written into the splitter slot.
    slot_q = 0 if hover else queue_w
    dock = _queue_slot(app, queue)
    try:
        queue_on_left = main.indexOf(dock) == 0
    except RuntimeError:
        queue_on_left = False
    # A boot-time kiss latches the player shut. Saved percents are the layout
    # the user asked for, so writing them opens the column again.
    app._player_column_kissed = False
    main.blockSignals(True)
    inner.blockSignals(True)
    try:
        if queue_on_left:
            # Queue slot | (player | library). The library is the inner
            # sibling, so it must receive the Clips width, not the shut slot.
            _set_pair_sizes(main, dock, slot_q, player_w + clips_w)
            _set_pair_sizes(inner, player, player_w, clips_w)
        else:
            _set_pair_sizes(main, clips, clips_w, player_w + slot_q)
            _set_pair_sizes(inner, player, player_w, slot_q)
    finally:
        main.blockSignals(False)
        inner.blockSignals(False)
    _cancel_shell_pane_snap(app)
    if hover and queue_pct > 0:
        _apply_hover_overlay_width(app, queue_w)


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

    The handle property is 6px, but its stylesheet margin makes the widget 10px
    and the layout keeps that. Width 0 alone leaves those 4px, still painted.
    Hiding also drops the splitter's handle rule so the slot is really gone.
    """
    setter = getattr(app, "_set_splitter_handle_visible", None)
    shell = _shell_bg(app)
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
        splitter.setStyleSheet(
            f"QSplitter {{ background-color: {shell}; }} "
            "QSplitter::handle, QSplitter::handle:hover {"
            " background: transparent; border: none; margin: 0px; }"
        )
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


def _stored_pane_percents(app):
    """Saved Clips / player / queue percents, or None if the user never set them."""
    from steempeg.ui.settings_prefs import read_shell_pane_percents

    settings = {}
    if hasattr(app, "load_user_settings"):
        try:
            settings = app.load_user_settings() or {}
        except Exception:
            settings = {}
    return read_shell_pane_percents(settings)


def apply_user_shell_handle_visibility(app) -> None:
    """Apply the Settings choice: hidden handles keep the saved pane widths.

    Percents are a share of the panes, and the handle sits outside that sum.
    Fit them after the handle slot appears or disappears. Doing it before lets
    Qt add the freed handle pixels on top, so Clips is no longer the saved percent.
    """
    if getattr(app, "_portable_shell", False):
        return
    if bool(getattr(app, "is_theater", False)) or bool(getattr(app, "is_fullscreen", False)):
        return
    if not user_hides_shell_handles(app):
        _set_side_handles_visible(app, True)
        paint_desktop_splitter_handles(app)
        _sync_hover_resize_grip(app)
    else:
        _set_side_handles_visible(app, False)
        _sync_hover_resize_grip(app)
    percents = _stored_pane_percents(app)
    if percents is not None:
        _apply_shell_pane_percents(app, percents)
    # Hiding the handle emits splitterMoved and arms the kiss snap. Stop it
    # after the widths are written, including when the percent pass bails out.
    _cancel_shell_pane_snap(app)


def remember_shell_pane_ratio(app) -> None:
    """Store the live Clips / player / queue split as the resize ratio.

    A handle drag is the user choosing new proportions. Queue width 0 is a
    closed pane, not a new percent: the previous queue share stays, and the
    collapsed flag keeps it shut until it is opened again.
    """
    if getattr(app, "_shell_pane_refitting", False):
        return
    if getattr(app, "_splitter_dragging", False):
        return
    from steempeg.ui.layout_defaults import shell_pixels_to_percents

    widths = shell_pane_widths(app)
    if widths is None or sum(widths) <= 0:
        return
    win_w, shell = _shell_span(app)
    if shell <= 0:
        return
    hover = _queue_hover_is_on(app)
    clips, player, queue = shell_pixels_to_percents(
        widths[0],
        widths[1],
        widths[2],
        shell=shell,
        window=win_w or shell,
        hover=hover,
    )
    prev = getattr(app, "_shell_pane_ratio", None)
    if queue <= 0 and isinstance(prev, tuple) and len(prev) == 3 and int(prev[2]) > 0:
        queue = int(prev[2])
    app._shell_pane_ratio = (int(clips), int(player), int(queue))


def _shut_queue_pane(app) -> None:
    """Give a closed legacy queue's pixels to its sibling.

    The percent fit will not leave the pane at 0: an open queue has a floor,
    and that floor is what a later maximize would scale into a wide column.
    """
    found = _shell_widgets(app)
    if found is None:
        return
    _main, inner, _clips, _player, queue = found
    dock = _queue_slot(app, queue)
    try:
        dock.setMinimumWidth(1)
    except RuntimeError:
        return
    for splitter in (inner, _main):
        try:
            index = splitter.indexOf(dock)
            sizes = [int(part) for part in splitter.sizes()]
        except RuntimeError:
            continue
        if index < 0 or len(sizes) < 2:
            continue
        other = 1 - index
        sizes[other] = sizes[other] + sizes[index]
        sizes[index] = 0
        splitter.blockSignals(True)
        try:
            splitter.setSizes(sizes)
        except RuntimeError:
            return
        finally:
            splitter.blockSignals(False)
        return


def refit_shell_panes_for_window(app) -> None:
    """Put Clips, the player and the queue back on their chosen shares.

    QSplitter scales whatever pixel sizes it was last given. The minimum-width
    clamp writes a new pair while the window is small, and the next maximize
    scales that pair, so Clips stays fatter than the setting. The share itself
    (Settings when the handles are hidden, otherwise the last drag) is applied
    again for the width the window has now.
    """
    if getattr(app, "_portable_shell", False):
        return
    if getattr(app, "is_theater", False) or getattr(app, "is_fullscreen", False):
        return
    if getattr(app, "_splitter_dragging", False):
        return
    if getattr(app, "_shell_pane_refitting", False):
        return
    ui = getattr(app, "ui", None)
    if ui is None:
        return
    try:
        if not bool(ui.isVisible()):
            return
        width = int(ui.width() or 0)
    except RuntimeError:
        return
    if width < 200:
        return
    if user_hides_shell_handles(app):
        percents = _stored_pane_percents(app)
        if percents is None:
            percents = getattr(app, "_shell_pane_ratio", None)
    else:
        percents = getattr(app, "_shell_pane_ratio", None)
    if not isinstance(percents, tuple) or len(percents) != 3:
        return
    clips, player, queue = (int(percents[0]), int(percents[1]), int(percents[2]))
    # A closed legacy queue is a latch, not a saved share of 0. Keep the share
    # for the next open, and give its pixels to the player until then.
    if not _queue_hover_is_on(app) and bool(getattr(app, "_queue_user_collapsed", False)):
        queue = 0
    app._shell_pane_refitting = True
    try:
        _apply_shell_pane_percents(app, (clips, player, queue))
        if queue == 0 and not _queue_hover_is_on(app):
            _shut_queue_pane(app)
    finally:
        app._shell_pane_refitting = False


def schedule_hidden_handle_pane_restore(app) -> None:
    """Write the saved pane percents again once the window is really on screen.

    Autostart keeps the shell hidden through sign-in. The percent pass can
    run while that shell is still a few pixels wide, and hiding the handles
    then looks like a closed player. Try again after the first show, including
    once maximize has settled.
    """
    if getattr(app, "_portable_shell", False):
        return
    if not user_hides_shell_handles(app):
        return
    from PySide6.QtCore import QTimer

    for delay in (0, 400, 900, 1800):
        QTimer.singleShot(delay, lambda: restore_hidden_handle_panes(app))


def restore_hidden_handle_panes(app) -> None:
    """Re-apply saved Clips / player / queue percents if the window is wide enough."""
    if getattr(app, "is_theater", False) or getattr(app, "is_fullscreen", False):
        return
    ui = getattr(app, "ui", None)
    if ui is None:
        return
    try:
        visible = bool(ui.isVisible())
        width = int(ui.width() or 0)
    except RuntimeError:
        return
    if not visible or width < 640:
        return
    app._player_column_kissed = False
    apply_user_shell_handle_visibility(app)
    if not getattr(app, "_hidden_handle_panes_restored", False):
        app._hidden_handle_panes_restored = True
        logging.info(
            "Shell panes restored after show (hidden handles, width=%s)", width
        )


def _sync_hover_resize_grip(app) -> None:
    """Hide the hover queue's drag tab while splitter handles are hidden.

    That tab is its own window, not a QSplitter handle, so the side-handle
    pass never sees it. Width then comes only from the pane percents.
    """
    ctrl = getattr(app, "_queue_hover", None)
    sync = getattr(ctrl, "sync_resize_grip", None)
    if not callable(sync):
        return
    try:
        sync()
    except Exception:
        return


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
