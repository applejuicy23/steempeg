"""Map Deck buttons → Portable / theatre actions (Console mode).

Two styles (Settings → General → Console style):

* **Simple** — ▲▼◀▶ moves a highlight. The scroller click presses it.
  A plays (trim: set end); inside a window, A presses the highlight.
  X closes the front window; on the bare player it queues (trim: set start).
  B steps back one layer. Y trims. L1/R1 seek. R2 fullscreen.
  L2 jumps to the trim start. View opens Choose a Clip. Menu opens Render.
* **Actions** — the shortcut map below.

Theatre (no sheet) — player, Actions style only:

| Button | Trim off | Trim on |
|--------|----------|---------|
| **A** | Play / Pause | Set trim **end** |
| **X** | Add to queue | Set trim **start** |
| **Y** | Toggle trim | Toggle trim |
| **L1** / **R1** | −15s / +15s | −15s / +15s |
| **R2** | Fullscreen | Fullscreen |
| **L2** | — | Jump to trim start |
| **View** / **Menu** | Choose a Clip / Render | same |

Sheets keep their own maps in ``deck_navigation`` when the style is Actions.

Console mode: Settings → General → Shell. Default on for Steam Deck builds,
off for Windows / Linux. Developer mode also enables the pad for QA.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget

from steempeg.input.deck_navigation import (
    close_deck_combo_popup,
    close_deck_picker_overlays,
    hide_deck_focus_ring,
    try_deck_navigation,
)
from steempeg.input.gamepad import DeckButton, gamepad_bus
from steempeg.ui.settings_prefs import deck_controls_enabled, deck_style_is_simple

_log = logging.getLogger(__name__)
_installed_apps: set[int] = set()


def install_deck_actions(app: Any) -> None:
    """Connect the shared gamepad bus to this Steempeg app (once)."""
    aid = id(app)
    if aid in _installed_apps:
        return
    _installed_apps.add(aid)
    bus = gamepad_bus()
    bus.button_pressed.connect(lambda btn, a=app: _on_press(a, btn))
    from steempeg.input.deck_navigation import install_deck_popup_hold

    install_deck_popup_hold(app)
    _install_front_memory(app)
    _log.info("Deck gamepad actions installed")


class _DeckFrontMemory(QObject):
    """Remember Express when the Dev pad takes activation on the next click."""

    def __init__(self, app: Any) -> None:
        super().__init__()
        self._app = app

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 — Qt override
        """Keep the last real window. The Dev pad must not erase it."""
        if event.type() != QEvent.Type.WindowActivate or not isinstance(watched, QWidget):
            return False
        try:
            if watched.objectName() == "ExpressPlayer":
                self._app._deck_front_express = watched
            elif watched is getattr(self._app, "ui", None):
                self._app._deck_front_express = None
        except RuntimeError:
            self._app._deck_front_express = None
        return False


def _install_front_memory(app: Any) -> None:
    """Install the activation memory once for this process."""
    qapp = QApplication.instance()
    if qapp is None or getattr(app, "_deck_front_memory", None) is not None:
        return
    filt = _DeckFrontMemory(app)
    qapp.installEventFilter(filt)
    app._deck_front_memory = filt


def _on_press(app: Any, button: DeckButton) -> None:
    if not deck_controls_enabled(app=app):
        return
    try:
        _dispatch(app, button)
    except Exception:
        _log.exception("Deck action failed for %s", button)


def _dispatch(app: Any, button: DeckButton) -> None:
    # Combo / filter overlays first — B must not close the whole sheet.
    if button == DeckButton.B:
        if close_deck_combo_popup(app):
            return
        if close_deck_picker_overlays(app):
            return
        if _close_top_sheet(app):
            return
        _close_loose_window(app, step=True)
        return

    # Simple keeps the highlight walk and adds the player verbs.
    # Actions keeps the shortcut map below.
    if deck_style_is_simple(app=app):
        from steempeg.input.deck_simple import try_simple_deck

        if button == DeckButton.X and _close_front_window(app):
            return
        try_simple_deck(app, button)
        return

    if try_deck_navigation(app, button):
        return

    # --- Theatre / player (no sheet) ---
    if button == DeckButton.VIEW:
        _open_choose_clip(app)
        return
    if button == DeckButton.MENU:
        _open_render(app)
        return

    if button == DeckButton.L1:
        if hasattr(app, "skip_backward"):
            app.skip_backward()
        return
    if button == DeckButton.R1:
        if hasattr(app, "skip_forward"):
            app.skip_forward()
        return
    if button == DeckButton.R2:
        if hasattr(app, "toggle_fullscreen"):
            app.toggle_fullscreen()
        return

    trim_on = _trim_mode_on(app)

    if button == DeckButton.L2:
        if trim_on and hasattr(app, "jump_to_trim_start"):
            app.jump_to_trim_start()
        return

    if button == DeckButton.Y:
        if hasattr(app, "toggle_trim_state"):
            app.toggle_trim_state()
        return

    if button == DeckButton.X:
        if trim_on and hasattr(app, "set_trim_start_to_playhead"):
            app.set_trim_start_to_playhead()
            return
        _add_current_to_queue(app)
        return

    if button == DeckButton.A:
        if trim_on and hasattr(app, "set_trim_end_to_playhead"):
            app.set_trim_end_to_playhead()
            return
        if hasattr(app, "toggle_play"):
            app.toggle_play()
        return

    _log.debug("Deck button unbound: %s", button.value)


def dispatch_simple_verb(app: Any, button: DeckButton) -> None:
    """Player verbs for Simple. A window does not steal seek, trim, or fullscreen."""
    express = _front_express(app)
    if button == DeckButton.X:
        if express is not None:
            return
        _player_x(app)
        return
    if button == DeckButton.Y:
        _player_y(app, express)
        return
    if button == DeckButton.L1:
        _player_seek(app, express, -15000)
        return
    if button == DeckButton.R1:
        _player_seek(app, express, 15000)
        return
    if button == DeckButton.R2:
        _player_fullscreen(app, express)
        return
    if button == DeckButton.L2:
        _player_trim_start_jump(app, express)
        return
    if button == DeckButton.VIEW:
        _open_choose_clip(app)
        return
    if button == DeckButton.MENU:
        _open_render(app)


def play_simple_a(app: Any) -> None:
    """A on the bare player: play, or set the trim end while trim is on."""
    express = _front_express(app)
    if express is not None:
        if _express_trim_on(express):
            _express_set_trim_end(express)
            return
        toggle = getattr(express, "toggle_play", None)
        if callable(toggle):
            toggle()
        return
    if _trim_mode_on(app) and hasattr(app, "set_trim_end_to_playhead"):
        app.set_trim_end_to_playhead()
        return
    if hasattr(app, "toggle_play"):
        app.toggle_play()


def _player_x(app: Any) -> None:
    """Queue the current clip, or set the trim start while trim is on."""
    if _trim_mode_on(app) and hasattr(app, "set_trim_start_to_playhead"):
        app.set_trim_start_to_playhead()
        return
    _add_current_to_queue(app)


def _player_y(app: Any, express: Any) -> None:
    """Toggle trim on the player that is actually in front."""
    if express is not None:
        toggle = getattr(express, "toggle_trim", None)
        if callable(toggle):
            toggle()
        return
    if hasattr(app, "toggle_trim_state"):
        app.toggle_trim_state()


def _player_seek(app: Any, express: Any, delta_ms: int) -> None:
    """Seek the front player by ``delta_ms``."""
    if express is not None:
        skip = getattr(express, "skip_by", None)
        if callable(skip):
            skip(delta_ms)
        return
    if delta_ms < 0 and hasattr(app, "skip_backward"):
        app.skip_backward()
        return
    if delta_ms > 0 and hasattr(app, "skip_forward"):
        app.skip_forward()


def _player_fullscreen(app: Any, express: Any) -> None:
    """Toggle fullscreen on the front player."""
    target = express if express is not None else app
    toggle = getattr(target, "toggle_fullscreen", None)
    if callable(toggle):
        toggle()


def _player_trim_start_jump(app: Any, express: Any) -> None:
    """Jump to the trim start when trim is on."""
    if express is not None:
        if not _express_trim_on(express):
            return
        timeline = getattr(express, "_timeline", None)
        jump = getattr(timeline, "force_jump", None)
        if callable(jump):
            jump(timeline.trim_start_ms)
        return
    if _trim_mode_on(app) and hasattr(app, "jump_to_trim_start"):
        app.jump_to_trim_start()


def _sheet_in_front(app: Any) -> bool:
    """True when a window, not the bare player, owns the highlight."""
    if getattr(app, "_app_settings_open", False):
        return True
    if getattr(app, "_portable_render_settings_open", False):
        return True
    if getattr(app, "_portable_clip_picker_open", False):
        return True
    from steempeg.input.deck_simple import _overlay_dialog

    return _overlay_dialog(app) is not None


def _express_visible(widget: Any) -> bool:
    """True for a living, visible Express window."""
    if widget is None:
        return False
    try:
        if widget.objectName() != "ExpressPlayer" or not widget.isVisible():
            return False
    except RuntimeError:
        return False
    return True


def _front_express(app: Any) -> Any:
    """The Express window when it is the player in front, else None.

    A click on the Dev pad activates that pad before the button runs, so the
    last real activation is remembered.
    """
    if _sheet_in_front(app):
        return None
    remembered = getattr(app, "_deck_front_express", None)
    if _express_visible(remembered):
        return remembered
    app._deck_front_express = None
    active = QApplication.activeWindow()
    if _express_visible(active):
        app._deck_front_express = active
        return active
    return None


def _express_trim_on(express: Any) -> bool:
    """True when the Express timeline is in trim."""
    timeline = getattr(express, "_timeline", None)
    try:
        return bool(getattr(timeline, "is_trim_mode", False))
    except RuntimeError:
        return False


def _express_set_trim_end(express: Any) -> None:
    """Set the Express trim end at the playhead. Same U-turn as the main player."""
    timeline = getattr(express, "_timeline", None)
    canvas = getattr(timeline, "canvas", None)
    if timeline is None or canvas is None:
        return
    pos = canvas.visual_ms
    old_start = canvas.trim_start_ms
    old_end = canvas.trim_end_ms
    duration = old_end - old_start
    if pos <= old_start:
        canvas.trim_end_ms = pos
        canvas.trim_start_ms = max(pos - duration, 0.0)
    else:
        canvas.trim_end_ms = pos
    timeline.trim_changed.emit(int(canvas.trim_start_ms), int(canvas.trim_end_ms))
    canvas.update()


def _close_front_window(app: Any) -> bool:
    """Close the window in front. True when one closed. An open list goes with it."""
    if _close_top_sheet(app):
        return True
    return _close_loose_window(app, step=False)


def _close_loose_window(app: Any, *, step: bool) -> bool:
    """Close a dialog or Express that is not one of the three sheets.

    ``step`` hides an Express screenshot before the window itself, so B can
    leave that layer first. X passes False and closes the window.
    """
    from steempeg.input.deck_simple import _overlay_dialog

    overlay = _overlay_dialog(app)
    if overlay is not None:
        _drop_simple_highlight(app)
        try:
            overlay.reject()
        except RuntimeError:
            return False
        return True
    express = _front_express(app)
    if express is None:
        return False
    if step:
        preview = getattr(express, "_shot_preview", None)
        try:
            if preview is not None and preview.isVisible():
                preview.hide()
                return True
        except RuntimeError:
            pass
    _drop_simple_highlight(app)
    try:
        express.close()
    except RuntimeError:
        return False
    return True


def _drop_simple_highlight(app: Any) -> None:
    """Clear the purple ring after the window it sat on has gone."""
    hide_deck_focus_ring(app)
    app._deck_simple_focus_id = None


def _trim_mode_on(app: Any) -> bool:
    tl = getattr(app, "custom_timeline", None)
    if tl is None:
        return False
    try:
        return bool(getattr(tl, "is_trim_mode", False))
    except RuntimeError:
        return False


def _open_choose_clip(app: Any) -> None:
    from steempeg.ui.portable.chrome import open_portable_clip_picker

    # Works best in Portable; still try so Dev Mode can QA the path.
    open_portable_clip_picker(app)


def _open_render(app: Any) -> None:
    from steempeg.ui.portable.chrome import open_portable_render_settings

    open_portable_render_settings(app)


def _add_current_to_queue(app: Any) -> None:
    if bool(getattr(app, "_deck_clip_multi", False)):
        grid = getattr(app, "grid_clips", None)
        if grid is not None:
            paths = []
            seen: set[str] = set()
            for item in grid.selectedItems():
                path = item.data(Qt.UserRole + 1) if item is not None else None
                if not path or path in seen:
                    continue
                seen.add(path)
                paths.append(path)
            if len(paths) > 1 and hasattr(app, "add_clips_to_render_queue"):
                app.add_clips_to_render_queue(paths)
                return
            if len(paths) == 1:
                if hasattr(app, "add_clip_to_render_queue"):
                    app.add_clip_to_render_queue(paths[0])
                return
    resolve = getattr(app, "_resolve_export_clip_path", None)
    path = resolve() if callable(resolve) else None
    if not path:
        return
    if hasattr(app, "add_clip_to_render_queue"):
        app.add_clip_to_render_queue(path)


def _close_top_sheet(app: Any) -> bool:
    """Close Settings, Choose-a-Clip, then Render sheet. True if something closed."""
    if getattr(app, "_app_settings_open", False):
        dlg = getattr(app, "_app_settings_dlg", None)
        if dlg is not None:
            try:
                hide_deck_focus_ring(app)
                dlg.reject()
                return True
            except RuntimeError:
                pass
        hide_deck_focus_ring(app)
        app._app_settings_open = False
        app._app_settings_dlg = None
        return True

    if getattr(app, "_portable_clip_picker_open", False):
        dlg = getattr(app, "_portable_clip_picker_dlg", None)
        if dlg is not None:
            try:
                force = getattr(dlg, "_force_close", None)
                if callable(force):
                    force()
                else:
                    dlg.reject()
                app._deck_clip_multi = False
                return True
            except RuntimeError:
                pass
        app._portable_clip_picker_open = False
        app._deck_clip_multi = False
        return True

    if getattr(app, "_portable_render_settings_open", False):
        dlg = getattr(app, "_portable_render_sheet_dlg", None)
        if dlg is not None:
            try:
                hide_deck_focus_ring(app)
                force = getattr(dlg, "_force_close", None)
                if callable(force):
                    force()
                else:
                    dlg.reject()
                return True
            except RuntimeError:
                pass
        hide_deck_focus_ring(app)
        app._portable_render_settings_open = False
        return True

    # Fallback: raise visible dialogs if flags drifted.
    for attr in (
        "_app_settings_dlg",
        "_portable_clip_picker_dlg",
        "_portable_render_sheet_dlg",
    ):
        dlg = getattr(app, attr, None)
        if dlg is None:
            continue
        try:
            if dlg.isVisible():
                hide_deck_focus_ring(app)
                force = getattr(dlg, "_force_close", None)
                if callable(force):
                    force()
                else:
                    dlg.reject()
                return True
        except RuntimeError:
            continue
    return False
