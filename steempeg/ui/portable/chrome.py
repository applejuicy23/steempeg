"""Portable theatre chrome — Add a Clip / Render / Render settings."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton

from steempeg.ui.icon_assets import preview_settings_icon
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

_SETTINGS_CHIP = (
    "QPushButton {"
    "background-color: rgba(74, 159, 216, 0.18);"
    "color: #4a9fd8;"
    "border: 2px solid #4a9fd8;"
    "border-radius: 15px; padding: 0px;"
    "}"
    "QPushButton:hover { background-color: rgba(74, 159, 216, 0.32); }"
    "QPushButton:pressed { background-color: rgba(74, 159, 216, 0.45); }"
)


def ensure_portable_chrome(app) -> None:
    """Create (once) and show portable theatre CTAs."""
    _ensure_add_clip_button(app)
    _ensure_render_buttons(app)
    if hasattr(app, "btn_portable_add_clip"):
        app.btn_portable_add_clip.show()
    if hasattr(app, "btn_portable_render"):
        app.btn_portable_render.show()
    if hasattr(app, "btn_portable_render_settings"):
        app.btn_portable_render_settings.show()
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


def _ensure_render_buttons(app) -> None:
    if getattr(app, "btn_portable_render", None) is not None:
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
    btn_render.setToolTip("Render current clip")
    btn_render.clicked.connect(lambda: app.start_render_thread())
    app.btn_portable_render = btn_render

    btn_settings = QPushButton()
    btn_settings.setObjectName("portableRenderSettings")
    btn_settings.setFixedSize(30, 30)
    btn_settings.setIcon(preview_settings_icon(16))
    btn_settings.setIconSize(QSize(16, 16))
    btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_settings.setStyleSheet(_SETTINGS_CHIP)
    btn_settings.setToolTip("Render settings")
    btn_settings.clicked.connect(lambda: open_portable_render_settings(app))
    app.btn_portable_render_settings = btn_settings

    idx = host_layout.indexOf(pill) if pill is not None else -1
    if idx < 0:
        host_layout.addWidget(btn_render)
        host_layout.addWidget(btn_settings)
    else:
        host_layout.insertWidget(idx, btn_render)
        host_layout.insertWidget(idx + 1, btn_settings)


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
        # Re-fit Export filename / Save-as after density may have crushed them.
        dense = getattr(app, "_ui_density", None)
        if dense is not None and hasattr(app, "ui"):
            from steempeg.ui.render_panel import apply_settings_panel_density

            apply_settings_panel_density(app.ui, dense)
        dlg = PortableRenderSettingsDialog(app, parent=app.ui)
        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted and getattr(dlg, "_start_after", False):
            app.start_render_thread()
    finally:
        app._portable_render_settings_open = False


def sync_portable_render_button(app) -> None:
    """Mirror Start Render enabled/label onto the portable Render CTA."""
    btn = getattr(app, "btn_portable_render", None)
    if btn is None:
        return
    start = getattr(app.ui, "btn_start", None) if hasattr(app, "ui") else None
    if start is not None:
        btn.setEnabled(start.isEnabled())
    pending = app.render_queue.pending_count() if hasattr(app, "render_queue") else 0
    if pending > 0:
        btn.setText(f"🚩 Render ({pending})")
    else:
        btn.setText("🚩 Render")
