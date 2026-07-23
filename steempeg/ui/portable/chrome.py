"""Portable theatre chrome — Choose a Clip / Render (opens settings+control sheet)."""
from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from steempeg.ui.icon_assets import add_clip_icon
from steempeg.ui.player.controls.adaptive_trim_tools import (
    ensure_adaptive_trim_hook,
    sync_trim_tools_placement,
)
from steempeg.ui.portable.sheets import (
    PortableClipPickerDialog,
    PortableRenderSettingsDialog,
    restore_render_settings,
)

_log = logging.getLogger(__name__)


# Match clip-health chip chrome (icon + label, soft fill, 2px border).
_ADD_CLIP_COLOR = "#8e7cc3"
_ADD_CLIP_TEXT = "#d4c8f5"
_ADD_CLIP_ICON = 18

_ADD_CLIP_STYLE = (
    "QPushButton {"
    f"background-color: rgba(142, 124, 195, 0.22);"
    f"color: {_ADD_CLIP_TEXT};"
    f"border: 2px solid {_ADD_CLIP_COLOR};"
    "border-radius: 8px;"
    "font-weight: bold;"
    "font-size: 13px;"
    "padding: 2px 10px 2px 8px;"
    "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"
    "}"
    "QPushButton:hover { background-color: rgba(142, 124, 195, 0.35); }"
    "QPushButton:pressed { background-color: rgba(142, 124, 195, 0.48); }"
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
    for name in ("portable_add_clip_divider", "btn_portable_add_clip"):
        w = getattr(app, name, None)
        if w is not None:
            w.show()
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
        "portable_add_clip_divider",
        "btn_portable_add_clip",
        "btn_portable_render",
        "btn_portable_render_settings",
    ):
        btn = getattr(app, name, None)
        if btn is not None:
            btn.hide()
    dispose_portable_sheets(app)


def _style_add_clip_button(btn: QPushButton) -> None:
    btn.setIcon(add_clip_icon(_ADD_CLIP_ICON))
    btn.setIconSize(QSize(_ADD_CLIP_ICON, _ADD_CLIP_ICON))
    btn.setText(" Choose a Clip")
    btn.setStyleSheet(_ADD_CLIP_STYLE)
    btn.setFixedHeight(30)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip("Open Clips Manager")


def _ensure_add_clip_button(app) -> None:
    header = getattr(app, "player_header_frame", None)
    if header is None or header.layout() is None:
        return

    lay: QHBoxLayout = header.layout()
    insert_at = 2
    for i in range(lay.count()):
        item = lay.itemAt(i)
        if item is not None and item.spacerItem() is not None:
            insert_at = i
            break

    btn = getattr(app, "btn_portable_add_clip", None)
    if btn is not None:
        try:
            # Deleted Qt wrapper after header rebuild — recreate below.
            btn.objectName()
        except RuntimeError:
            app.btn_portable_add_clip = None
            btn = None
    if btn is not None:
        _style_add_clip_button(btn)
        try:
            btn.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        btn.clicked.connect(lambda: open_portable_clip_picker(app))
        # Older sessions created the button without the title|chip divider.
        if getattr(app, "portable_add_clip_divider", None) is None:
            divider = QFrame()
            divider.setObjectName("portableAddClipDivider")
            divider.setFrameShape(QFrame.Shape.VLine)
            divider.setFixedWidth(1)
            divider.setFixedHeight(22)
            divider.setStyleSheet(
                "color: #555555; background-color: #555555; margin: 4px 2px;"
            )
            app.portable_add_clip_divider = divider
            idx = lay.indexOf(btn)
            lay.insertWidget(idx if idx >= 0 else insert_at, divider)
        return

    # Same VLine chrome as health | actions divider — separates title from the chip.
    divider = QFrame()
    divider.setObjectName("portableAddClipDivider")
    divider.setFrameShape(QFrame.Shape.VLine)
    divider.setFixedWidth(1)
    divider.setFixedHeight(22)
    divider.setStyleSheet("color: #555555; background-color: #555555; margin: 4px 2px;")
    app.portable_add_clip_divider = divider

    btn = QPushButton()
    btn.setObjectName("portableAddClip")
    _style_add_clip_button(btn)
    btn.clicked.connect(lambda: open_portable_clip_picker(app))
    app.btn_portable_add_clip = btn

    lay.insertWidget(insert_at, divider)
    lay.insertWidget(insert_at + 1, btn)


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


def _ensure_sheet_garage(app) -> QWidget:
    """Hidden non-window host for prewarmed sheets (no top-level HWND)."""
    garage = getattr(app, "_portable_sheet_garage", None)
    if garage is not None:
        try:
            garage.objectName()
            return garage
        except RuntimeError:
            pass
    host = getattr(app, "ui", None)
    garage = QWidget(host)
    garage.setObjectName("portableSheetGarage")
    garage.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    garage.hide()
    garage.setFixedSize(0, 0)
    app._portable_sheet_garage = garage
    return garage


def prewarm_portable_sheets(app) -> None:
    """Build Clips Manager + Render sheets once while theatre is idle.

    Build as garage widgets (no flash), then silently promote to Dialog HWNDs
    while still DontShowOnScreen — so the first click skips setWindowFlags lag.
    """
    if not getattr(app, "_portable_shell", False):
        return
    if getattr(app, "_portable_sheets_warm", False):
        return
    if getattr(app, "_portable_sheets_warming", False):
        return
    app._portable_sheets_warming = True
    try:
        garage = _ensure_sheet_garage(app)
        host = getattr(app, "ui", None)
        if getattr(app, "_portable_clip_picker_dlg", None) is None:
            dlg = PortableClipPickerDialog(app, parent=garage, warm=True)
            dlg._park_as_embedded_widget(garage)
            if host is not None and hasattr(dlg, "silent_promote_for_prewarm"):
                dlg.silent_promote_for_prewarm(host)
            app._portable_clip_picker_dlg = dlg
        if getattr(app, "_portable_render_sheet_dlg", None) is None:
            from steempeg.ui.render_panel import apply_settings_panel_density
            from steempeg.ui.ui_density import COMFORT

            if hasattr(app, "ui"):
                app._ui_density = COMFORT
                apply_settings_panel_density(app.ui, COMFORT)
            dlg = PortableRenderSettingsDialog(app, parent=garage, warm=True)
            dlg._park_as_embedded_widget(garage)
            if host is not None and hasattr(dlg, "silent_promote_for_prewarm"):
                dlg.silent_promote_for_prewarm(host)
            app._portable_render_sheet_dlg = dlg
        app._portable_sheets_warm = True
        if hasattr(app, "preload_render_history"):
            app.preload_render_history(announce=False)
        _log.info("Portable sheets prewarmed (Dialog HWND ready, unmapped)")
    except Exception:
        _log.exception("Portable sheets prewarm failed")
    finally:
        app._portable_sheets_warming = False


def dispose_portable_sheets(app) -> None:
    """Tear down warm sheets and return borrowed panels to the main shell."""
    for attr in ("_portable_clip_picker_dlg", "_portable_render_sheet_dlg"):
        dlg = getattr(app, attr, None)
        if dlg is None:
            continue
        try:
            if hasattr(dlg, "dispose_warm"):
                dlg.dispose_warm()
            else:
                dlg.close()
                dlg.deleteLater()
        except RuntimeError:
            pass
        setattr(app, attr, None)
    app._portable_sheets_warm = False
    app._portable_render_strip = None
    app._portable_queue_sidebar = None
    garage = getattr(app, "_portable_sheet_garage", None)
    if garage is not None:
        try:
            garage.deleteLater()
        except RuntimeError:
            pass
        app._portable_sheet_garage = None


def open_portable_clip_picker(app) -> None:
    if getattr(app, "_portable_clip_picker_open", False):
        return
    app._portable_clip_picker_open = True
    try:
        dlg = getattr(app, "_portable_clip_picker_dlg", None)
        try:
            if dlg is not None:
                dlg.objectName()
        except RuntimeError:
            dlg = None
            app._portable_clip_picker_dlg = None

        if dlg is None:
            garage = _ensure_sheet_garage(app)
            dlg = PortableClipPickerDialog(app, parent=garage, warm=True)
            dlg._park_as_embedded_widget(garage)
            host = getattr(app, "ui", None)
            if host is not None:
                dlg.silent_promote_for_prewarm(host)
            app._portable_clip_picker_dlg = dlg
            app._portable_sheets_warm = True
        dlg.prepare_for_show()
        dlg.exec()
    except Exception:
        _log.exception("Open Clips Manager failed")
    finally:
        app._portable_clip_picker_open = False


def open_portable_render_settings(app) -> None:
    if getattr(app, "_portable_render_settings_open", False):
        return
    app._portable_render_settings_open = True
    try:
        from steempeg.ui.render_panel import apply_settings_panel_density
        from steempeg.ui.ui_density import COMFORT

        if hasattr(app, "ui"):
            app._ui_density = COMFORT
            apply_settings_panel_density(app.ui, COMFORT)

        dlg = getattr(app, "_portable_render_sheet_dlg", None)
        try:
            if dlg is not None:
                dlg.objectName()
        except RuntimeError:
            dlg = None
            app._portable_render_sheet_dlg = None

        if dlg is None:
            garage = _ensure_sheet_garage(app)
            dlg = PortableRenderSettingsDialog(app, parent=garage, warm=True)
            dlg._park_as_embedded_widget(garage)
            host = getattr(app, "ui", None)
            if host is not None:
                dlg.silent_promote_for_prewarm(host)
            app._portable_render_sheet_dlg = dlg
            app._portable_sheets_warm = True
        dlg.prepare_for_show()
        dlg.exec()
    except Exception:
        _log.exception("Open Render sheet failed")
    finally:
        app._portable_render_settings_open = False
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
