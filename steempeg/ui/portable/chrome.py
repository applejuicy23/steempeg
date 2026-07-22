"""Portable theatre chrome — Add a Clip / Render (opens settings+control sheet)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton

from steempeg.ui.player.controls.adaptive_trim_tools import (
    ensure_adaptive_trim_hook,
    sync_trim_tools_placement,
)
from steempeg.ui.portable.sheets import (
    PortableClipPickerDialog,
    PortableRenderSettingsDialog,
    restore_render_settings,
)


_HEADER_CHIP = (
    "border-radius: 8px;"
    "padding: 0px 10px;"
    "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"
    "font-size: 12px; font-weight: bold;"
)

_ADD_CLIP_STYLE = (
    "QPushButton {"
    "background-color: rgba(142, 124, 195, 0.22);"
    "color: #d4c8f5;"
    "border: 2px solid #8e7cc3;"
    + _HEADER_CHIP
    + "}"
    "QPushButton:hover { background-color: rgba(142, 124, 195, 0.38); }"
    "QPushButton:pressed { background-color: rgba(142, 124, 195, 0.52); }"
)

_RENDER_STYLE = (
    "QPushButton {"
    "background-color: #2e6b32; color: #ffffff;"
    "border: 2px solid #3e8e41; border-radius: 15px;"
    "padding: 0 14px; font-weight: bold; font-size: 12px;"
    "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"
    "}"
    "QPushButton:hover { background-color: #3e8e41; border: 2px solid #57c75b; }"
    "QPushButton:pressed { background-color: #235226; }"
    "QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }"
)


def ensure_portable_chrome(app) -> None:
    """Create (once) and show portable theatre CTAs."""
    _ensure_add_clip_button(app)
    _ensure_render_button(app)
    ensure_adaptive_trim_hook(app)
    sync_trim_tools_placement(app)
    if hasattr(app, "btn_portable_add_clip"):
        app.btn_portable_add_clip.show()
    if hasattr(app, "btn_portable_render"):
        app.btn_portable_render.show()
    # Legacy gear — hide if an older session created it.
    gear = getattr(app, "btn_portable_render_settings", None)
    if gear is not None:
        gear.hide()
    if hasattr(app, "set_view_mode"):
        app.set_view_mode("grid")
    toggle = getattr(app, "toggle_pill", None)
    lbl = getattr(app, "_lbl_view", None)
    if toggle is not None:
        toggle.hide()
    if lbl is not None:
        lbl.hide()
    if not getattr(app, "_portable_render_settings_restored", False):
        restore_render_settings(app)
        app._portable_render_settings_restored = True
    sync_portable_render_button(app)


def hide_portable_chrome(app) -> None:
    # Restore tools left-of-Trim without clearing the portable shell flag.
    was = getattr(app, "_portable_shell", False)
    app._portable_shell = False
    sync_trim_tools_placement(app)
    app._portable_shell = was
    for name in (
        "btn_portable_add_clip",
        "btn_portable_render",
        "btn_portable_render_settings",
    ):
        btn = getattr(app, name, None)
        if btn is not None:
            btn.hide()


def _ensure_add_clip_button(app) -> None:
    if getattr(app, "btn_portable_add_clip", None) is not None:
        return
    header = getattr(app, "player_header_frame", None)
    if header is None or header.layout() is None:
        return

    btn = QPushButton("Add a Clip")
    btn.setObjectName("portableAddClip")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedHeight(30)
    btn.setStyleSheet(_ADD_CLIP_STYLE)
    btn.setToolTip("Open Clips Manager")
    btn.clicked.connect(lambda: open_portable_clip_picker(app))
    app.btn_portable_add_clip = btn

    lay: QHBoxLayout = header.layout()
    insert_at = 2
    for i in range(lay.count()):
        item = lay.itemAt(i)
        if item is not None and item.spacerItem() is not None:
            insert_at = i
            break
    lay.insertWidget(insert_at, btn)


def _ensure_render_button(app) -> None:
    if getattr(app, "btn_portable_render", None) is not None:
        # Rebind click to open the combined sheet (upgrade older instant-start wiring).
        try:
            app.btn_portable_render.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        app.btn_portable_render.clicked.connect(lambda: open_portable_render_settings(app))
        app.btn_portable_render.setToolTip("Render settings and progress")
        return

    pill = getattr(app, "pill_container", None)
    trim = getattr(app, "btn_trim", None)
    anchor = pill or trim
    if anchor is None:
        return
    right_wrap = anchor.parentWidget()
    if right_wrap is None or right_wrap.layout() is None:
        return
    host_layout = right_wrap.layout()

    btn_render = QPushButton("🚩 Render")
    btn_render.setObjectName("portableRender")
    btn_render.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_render.setFixedHeight(30)
    btn_render.setStyleSheet(_RENDER_STYLE)
    btn_render.setToolTip("Render settings and progress")
    btn_render.clicked.connect(lambda: open_portable_render_settings(app))
    app.btn_portable_render = btn_render

    idx = host_layout.indexOf(pill) if pill is not None else -1
    if idx < 0:
        host_layout.addWidget(btn_render)
    else:
        host_layout.insertWidget(idx, btn_render)


def open_portable_clip_picker(app) -> None:
    if getattr(app, "_portable_clip_picker_open", False):
        return
    app._portable_clip_picker_open = True
    try:
        dlg = PortableClipPickerDialog(app, parent=app.ui)
        dlg.exec()
    finally:
        app._portable_clip_picker_open = False


def open_portable_render_settings(app) -> None:
    if getattr(app, "_portable_render_settings_open", False):
        return
    app._portable_render_settings_open = True
    try:
        # Portable sheet must stay at comfort sizing — never re-apply a crushed
        # density snapshot from a Deck-narrow shell window.
        from steempeg.ui.render_panel import apply_settings_panel_density
        from steempeg.ui.ui_density import COMFORT

        if hasattr(app, "ui"):
            app._ui_density = COMFORT
            apply_settings_panel_density(app.ui, COMFORT)
        dlg = PortableRenderSettingsDialog(app, parent=app.ui)
        dlg.exec()
    finally:
        app._portable_render_settings_open = False
        app._portable_render_strip = None
        app._portable_queue_sidebar = None
        sync_portable_render_button(app)


def sync_portable_render_button(app) -> None:
    """Theatre Render CTA: always opens the sheet; enable when a clip/queue is ready."""
    btn = getattr(app, "btn_portable_render", None)
    if btn is None:
        return
    pending = app.render_queue.pending_count() if hasattr(app, "render_queue") else 0
    if pending > 0:
        btn.setText(f"🚩 Render ({pending})")
    else:
        btn.setText("🚩 Render")

    # Keep the theatre CTA clickable so the user can open the sheet even mid-render
    # (to watch progress / Pause / Cancel). Always enabled in portable shell.
    btn.setEnabled(True)

    strip = getattr(app, "_portable_render_strip", None)
    if strip is not None and hasattr(strip, "sync_from_app"):
        strip.sync_from_app()
