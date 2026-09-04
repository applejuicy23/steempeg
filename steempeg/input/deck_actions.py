"""Map Deck buttons → Portable / theatre actions (Console mode).

Theatre (no sheet) — player:

| Button | Trim off | Trim on |
|--------|----------|---------|
| **A** | Play / Pause | Set trim **end** |
| **X** | Add to queue | Set trim **start** |
| **Y** | Toggle trim | Toggle trim |
| **L1** / **R1** | −15s / +15s | −15s / +15s |
| **R2** | Fullscreen | Fullscreen |
| **L2** | — | Jump to trim start |
| **View** / **Menu** | Choose a Clip / Render | same |

Sheets keep their own maps in ``deck_navigation`` (Queue / Choose a Clip / Render).

Console mode: Settings → General → Shell. Default on for Steam Deck builds,
off for Windows / Linux. Developer mode also enables the pad for QA.

Future: a simpler ▲▼◀▶-only Console style (PlayStation-home focus).
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt

from steempeg.input.deck_navigation import (
    close_deck_combo_popup,
    close_deck_picker_overlays,
    hide_deck_focus_ring,
    try_deck_navigation,
)
from steempeg.input.gamepad import DeckButton, gamepad_bus
from steempeg.ui.settings_prefs import deck_controls_enabled

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
    _log.info("Deck gamepad actions installed")


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
