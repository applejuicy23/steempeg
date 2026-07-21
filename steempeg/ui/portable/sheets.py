"""Portable / Steam Deck shell overlays — clip picker + render settings sheets."""
from __future__ import annotations

import logging
from dataclasses import asdict, fields

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.render.queue import RenderJobSettings
from steempeg.ui import design_tokens as tok
from steempeg.ui.message_dialog import _BTN_PRIMARY, _BTN_SECONDARY, dialog_theme
from steempeg.ui.render_job_builder import apply_job_settings_to_ui, snapshot_settings_from_ui
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

RENDER_SETTINGS_KEY = "render_export_settings"

_log = logging.getLogger(__name__)


def persist_render_settings(app) -> None:
    """Snapshot export panel into settings.json."""
    try:
        data = asdict(snapshot_settings_from_ui(app))
        app.save_user_settings(RENDER_SETTINGS_KEY, data)
    except Exception:
        _log.exception("Failed to persist render settings")


def restore_render_settings(app) -> None:
    """Apply last saved export panel snapshot if present."""
    raw = app.load_user_settings().get(RENDER_SETTINGS_KEY)
    if not isinstance(raw, dict) or not raw:
        return
    allowed = {f.name for f in fields(RenderJobSettings)}
    cleaned = {k: v for k, v in raw.items() if k in allowed}
    try:
        apply_job_settings_to_ui(app, RenderJobSettings(**cleaned))
    except Exception:
        _log.exception("Failed to restore render settings")


def _borrow_widget(widget: QWidget):
    """Detach widget from layout or QSplitter parent.

    Returns (parent, layout_or_None, index, kind) where kind is ``\"layout\"`` or ``\"splitter\"``.
    """
    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is not None:
        index = layout.indexOf(widget)
        if index >= 0:
            layout.removeWidget(widget)
            widget.setParent(None)
            return parent, layout, index, "layout"

    # QSplitter (main library column) has no QLayout.
    from PySide6.QtWidgets import QSplitter

    if isinstance(parent, QSplitter):
        index = -1
        for i in range(parent.count()):
            if parent.widget(i) is widget:
                index = i
                break
        widget.setParent(None)
        return parent, None, index, "splitter"

    widget.setParent(None)
    return parent, None, -1, "orphan"


def _return_widget(
    widget: QWidget,
    parent: QWidget | None,
    layout,
    index: int,
    kind: str,
    *,
    visible: bool,
) -> None:
    if kind == "layout" and layout is not None and index >= 0:
        layout.insertWidget(index, widget)
    elif kind == "splitter" and parent is not None:
        from PySide6.QtWidgets import QSplitter

        if isinstance(parent, QSplitter):
            parent.insertWidget(max(index, 0), widget)
        else:
            widget.setParent(parent)
    elif parent is not None:
        widget.setParent(parent)
    widget.setVisible(visible)


class PortableRenderSettingsDialog(SteempegDialog):
    """Embed desktop neo export panel; Save / Save & Render."""

    def __init__(self, app, parent=None):
        theme = dialog_theme(parent or getattr(app, "ui", None))
        super().__init__("Render settings", parent or app.ui, **theme)
        self._app = app
        self._start_after = False
        self._neo = getattr(app, "neo_wrapper", None)
        self._home = (None, None, -1, "orphan")
        self._hw = getattr(app, "hide_watcher", None)
        if self._hw is not None:
            self._hw.set_suppressed(True)

        self.setMinimumSize(720, 480)
        self.content_layout.setContentsMargins(12, 8, 12, 12)
        self.content_layout.setSpacing(10)

        if self._neo is None:
            from PySide6.QtWidgets import QLabel

            empty = QLabel("Render settings panel is not available.")
            empty.setStyleSheet(f"color: {tok.TEXT_MUTED};")
            self.content_layout.addWidget(empty)
        else:
            self._home = _borrow_widget(self._neo)
            self._neo.show()
            self._neo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.content_layout.addWidget(self._neo, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        btn_save = QPushButton("Save")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(_BTN_SECONDARY)
        btn_save.clicked.connect(self._on_save)

        btn_go = QPushButton("Save & Render")
        btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_go.setStyleSheet(_BTN_PRIMARY)
        btn_go.clicked.connect(self._on_save_and_render)

        actions.addWidget(btn_save)
        actions.addWidget(btn_go)
        self.content_layout.addLayout(actions)

        # Size relative to main window
        host = parent or getattr(app, "ui", None)
        if host is not None:
            geo = host.geometry()
            self.resize(max(720, int(geo.width() * 0.72)), max(480, int(geo.height() * 0.72)))

    def _on_save(self) -> None:
        persist_render_settings(self._app)
        self._start_after = False
        self.accept()

    def _on_save_and_render(self) -> None:
        persist_render_settings(self._app)
        self._start_after = True
        self.accept()

    def reject(self) -> None:
        self._start_after = False
        super().reject()

    def done(self, result: int) -> None:
        if self._neo is not None:
            parent, layout, index, kind = self._home
            _return_widget(self._neo, parent, layout, index, kind, visible=False)
            self._neo = None
        if self._hw is not None:
            self._hw.set_suppressed(False)
            self._hw = None
        super().done(result)


class PortableClipPickerDialog(SteempegDialog):
    """Theatre overlay: Clips Manager (grid) + Rendered tab."""

    def __init__(self, app, parent=None):
        theme = dialog_theme(parent or getattr(app, "ui", None))
        super().__init__("Add a Clip", parent or app.ui, **theme)
        self._app = app
        self._panel = getattr(app.ui, "left_panel", None)
        self._home = (None, None, -1, "orphan")
        self._armed = False
        self._prev_clips_mode = None
        self._prev_rendered_mode = None
        self._prev_sel_modes: list[tuple[object, object]] = []
        self._toggle_was_visible = True

        self.setMinimumSize(640, 480)
        self.content_layout.setContentsMargins(10, 6, 10, 10)

        if self._panel is None:
            from PySide6.QtWidgets import QLabel

            empty = QLabel("Clips Manager is not available.")
            empty.setStyleSheet(f"color: {tok.TEXT_MUTED};")
            self.content_layout.addWidget(empty)
        else:
            self._prepare_library_for_sheet()
            self._home = _borrow_widget(self._panel)
            self._panel.show()
            self._panel.setMinimumWidth(0)
            self._panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.content_layout.addWidget(self._panel, 1)

        host = parent or getattr(app, "ui", None)
        if host is not None:
            geo = host.geometry()
            self.resize(max(640, int(geo.width() * 0.78)), max(480, int(geo.height() * 0.78)))

        QTimer.singleShot(350, self._arm_selection_close)

    def _prepare_library_for_sheet(self) -> None:
        app = self._app
        self._prev_clips_mode = getattr(app, "_clips_view_mode", None) or getattr(
            app, "current_view_mode", "grid"
        )
        self._prev_rendered_mode = getattr(app, "_rendered_view_mode", "grid")

        if hasattr(app, "set_view_mode"):
            app.set_view_mode("grid")
        app._rendered_view_mode = "grid"
        if hasattr(app, "_apply_rendered_view_mode"):
            app._apply_rendered_view_mode()

        toggle = getattr(app, "toggle_pill", None)
        lbl = getattr(app, "_lbl_view", None)
        if toggle is not None:
            self._toggle_was_visible = toggle.isVisible()
            toggle.hide()
        if lbl is not None:
            lbl.hide()

        widgets = []
        for name in ("grid_clips", "grid_rendered"):
            w = getattr(app, name, None)
            if w is not None:
                widgets.append(w)
        if hasattr(app, "ui") and hasattr(app.ui, "table_clips"):
            widgets.append(app.ui.table_clips)
        if hasattr(app, "table_rendered") and app.table_rendered is not None:
            widgets.append(app.table_rendered)

        for w in widgets:
            prev = w.selectionMode()
            self._prev_sel_modes.append((w, prev))
            w.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        if hasattr(app, "grid_clips"):
            app.grid_clips.itemSelectionChanged.connect(self._on_pick)
        if hasattr(app, "grid_rendered"):
            app.grid_rendered.itemSelectionChanged.connect(self._on_pick)
        if hasattr(app, "ui") and hasattr(app.ui, "table_clips"):
            app.ui.table_clips.itemSelectionChanged.connect(self._on_pick)
        if hasattr(app, "table_rendered"):
            app.table_rendered.itemSelectionChanged.connect(self._on_pick)

    def _arm_selection_close(self) -> None:
        self._armed = True

    def _on_pick(self) -> None:
        if not self._armed:
            return
        self._armed = False
        QTimer.singleShot(0, self.accept)

    def _restore_library(self) -> None:
        app = self._app
        try:
            if hasattr(app, "grid_clips"):
                app.grid_clips.itemSelectionChanged.disconnect(self._on_pick)
        except (TypeError, RuntimeError):
            pass
        try:
            if hasattr(app, "grid_rendered"):
                app.grid_rendered.itemSelectionChanged.disconnect(self._on_pick)
        except (TypeError, RuntimeError):
            pass
        try:
            if hasattr(app.ui, "table_clips"):
                app.ui.table_clips.itemSelectionChanged.disconnect(self._on_pick)
        except (TypeError, RuntimeError):
            pass
        try:
            if hasattr(app, "table_rendered"):
                app.table_rendered.itemSelectionChanged.disconnect(self._on_pick)
        except (TypeError, RuntimeError):
            pass

        for w, mode in self._prev_sel_modes:
            try:
                w.setSelectionMode(mode)
            except RuntimeError:
                pass

        toggle = getattr(app, "toggle_pill", None)
        lbl = getattr(app, "_lbl_view", None)
        if toggle is not None and self._toggle_was_visible:
            toggle.show()
        if lbl is not None and self._toggle_was_visible:
            lbl.show()

        # Keep grid in portable shell — don't restore list mode.
        if not getattr(app, "_portable_shell", False):
            if self._prev_clips_mode and hasattr(app, "set_view_mode"):
                app.set_view_mode(self._prev_clips_mode)
            if self._prev_rendered_mode:
                app._rendered_view_mode = self._prev_rendered_mode
                if hasattr(app, "_apply_rendered_view_mode"):
                    app._apply_rendered_view_mode()

    def done(self, result: int) -> None:
        self._restore_library()
        if self._panel is not None:
            parent, layout, index, kind = self._home
            _return_widget(self._panel, parent, layout, index, kind, visible=False)
            if kind == "splitter" and parent is not None:
                try:
                    parent.handle(1).setVisible(False)
                except Exception:
                    pass
            self._panel = None
        super().done(result)
