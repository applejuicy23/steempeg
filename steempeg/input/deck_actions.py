"""Map Deck buttons → Portable / theatre actions (v1).

Locked mapping (Emily 27 Aug 2026):

| Button | Theatre (no sheet) | Sheet open |
|--------|--------------------|------------|
| **View** | **Choose a Clip** | — (or keep open / focus) |
| **Menu** | **Render** settings | — |
| **A** | Play / Pause | Confirm clip / activate focus |
| **B** | — | **Close** top sheet |
| **X** | Add to queue | — |
| **Y** | **Trim** | Toggle trim on open clip |
| D-pad | — | **Choose a Clip:** move card focus |
| L1 / R1 | — | **Choose a Clip:** library tabs · **Render:** settings tabs |
| L2 / R2 | — | **Render:** Queue rail / settings panel focus zones |
| D-pad (Render) | — | Queue ▲▼ · settings ▲▼ focus · ◀▶ tabs · ◀ queue zone |
| STEAM / QAM | never | never |

Trackpads stay mouse/cursor — not handled here.
"""
from __future__ import annotations

import logging
from typing import Any

from steempeg.input.deck_navigation import try_deck_navigation
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
    # Prefer closing a sheet on B even outside portable (no-op if none).
    if button == DeckButton.B:
        if _close_top_sheet(app):
            return
        return

    if try_deck_navigation(app, button):
        return

    if button == DeckButton.VIEW:
        _open_choose_clip(app)
        return
    if button == DeckButton.MENU:
        _open_render(app)
        return
    if button == DeckButton.A:
        if hasattr(app, "toggle_play"):
            app.toggle_play()
        return
    if button == DeckButton.X:
        _add_current_to_queue(app)
        return
    if button == DeckButton.Y:
        if hasattr(app, "toggle_trim_state"):
            app.toggle_trim_state()
        return
    _log.debug("Deck button unbound: %s", button.value)


def _open_choose_clip(app: Any) -> None:
    from steempeg.ui.portable.chrome import open_portable_clip_picker

    # Works best in Portable; still try so Dev Mode can QA the path.
    open_portable_clip_picker(app)


def _open_render(app: Any) -> None:
    from steempeg.ui.portable.chrome import open_portable_render_settings

    open_portable_render_settings(app)


def _add_current_to_queue(app: Any) -> None:
    resolve = getattr(app, "_resolve_export_clip_path", None)
    path = resolve() if callable(resolve) else None
    if not path:
        return
    if hasattr(app, "add_clip_to_render_queue"):
        app.add_clip_to_render_queue(path)


def _close_top_sheet(app: Any) -> bool:
    """Close Choose-a-Clip first, then Render sheet. True if something closed."""
    if getattr(app, "_portable_clip_picker_open", False):
        dlg = getattr(app, "_portable_clip_picker_dlg", None)
        if dlg is not None:
            try:
                force = getattr(dlg, "_force_close", None)
                if callable(force):
                    force()
                else:
                    dlg.reject()
                return True
            except RuntimeError:
                pass
        app._portable_clip_picker_open = False
        return True

    if getattr(app, "_portable_render_settings_open", False):
        dlg = getattr(app, "_portable_render_sheet_dlg", None)
        if dlg is not None:
            try:
                force = getattr(dlg, "_force_close", None)
                if callable(force):
                    force()
                else:
                    dlg.reject()
                return True
            except RuntimeError:
                pass
        app._portable_render_settings_open = False
        return True

    # Fallback: raise visible dialogs if flags drifted.
    for attr in ("_portable_clip_picker_dlg", "_portable_render_sheet_dlg"):
        dlg = getattr(app, attr, None)
        if dlg is None:
            continue
        try:
            if dlg.isVisible():
                force = getattr(dlg, "_force_close", None)
                if callable(force):
                    force()
                else:
                    dlg.reject()
                return True
        except RuntimeError:
            continue
    return False
