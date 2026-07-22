"""Portable / Steam Deck shell overlays — clip picker + render settings sheets."""
from __future__ import annotations

import logging
from dataclasses import asdict, fields

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.render.queue import RenderJobSettings
from steempeg.ui import design_tokens as tok
from steempeg.ui.message_dialog import _BTN_SECONDARY, dialog_theme
from steempeg.ui.portable.render_controls import PortableRenderControlStrip
from steempeg.ui.render_job_builder import apply_job_settings_to_ui, snapshot_settings_from_ui
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

RENDER_SETTINGS_KEY = "render_export_settings"

# Host shell ≤ this width → compact portable Render sheet (Deck / ~1400 laptops).
# Wider shells (e.g. 1920×1080) keep full comfort chrome — no trim hacks.
PORTABLE_SHEET_COMPACT_MAX_W = 1600

# Compact-only neo rail trim (comfort default is 220).
_PORTABLE_NEO_SIDEBAR_W = 200
_PORTABLE_NEO_SIDEBAR_MARGINS = (10, 15, 6, 15)

_log = logging.getLogger(__name__)


def portable_render_sheet_compact(host) -> bool:
    """True when the shell is Deck / small-laptop class — use space-saving sheet chrome."""
    w = 0
    if host is not None:
        try:
            w = int(host.width() or 0)
        except Exception:
            w = 0
    if w <= 0:
        try:
            from PySide6.QtWidgets import QApplication

            aw = QApplication.activeWindow()
            if aw is not None:
                w = int(aw.width() or 0)
        except Exception:
            w = 0
    if w <= 0:
        return True  # safe default: compact fits more places
    return w <= PORTABLE_SHEET_COMPACT_MAX_W


def apply_portable_neo_chrome(app) -> None:
    """Tighten neo sidebar width for compact portable Render sheets only."""
    if getattr(app, "_portable_neo_chrome_on", False):
        return
    if not getattr(app, "_portable_sheet_compact", True):
        return
    sidebar = getattr(app, "_neo_sidebar", None)
    lay = getattr(app, "_neo_sidebar_layout", None)
    if sidebar is None:
        return

    app._portable_neo_chrome_on = True
    app._portable_neo_sidebar_w_saved = sidebar.width()
    if lay is not None:
        m = lay.contentsMargins()
        app._portable_neo_margins_saved = (m.left(), m.top(), m.right(), m.bottom())
        app._portable_neo_spacing_saved = lay.spacing()
        lay.setContentsMargins(*_PORTABLE_NEO_SIDEBAR_MARGINS)

    sidebar.setFixedWidth(_PORTABLE_NEO_SIDEBAR_W)

    # Keep desktop content inset from the nav divider (comfort left pad = 16).
    from steempeg.ui.ui_density import COMFORT

    left, top, right, bottom = COMFORT.settings_page_margin
    tabs = getattr(getattr(app, "ui", None), "settings_tabs", None)
    if tabs is not None:
        for i in range(tabs.count()):
            page = tabs.widget(i)
            pl = page.layout() if page is not None else None
            if pl is not None:
                pl.setContentsMargins(left, top, right, bottom)


def restore_portable_neo_chrome(app) -> None:
    """Undo portable neo tightening when the Render sheet closes."""
    if not getattr(app, "_portable_neo_chrome_on", False):
        return
    sidebar = getattr(app, "_neo_sidebar", None)
    lay = getattr(app, "_neo_sidebar_layout", None)

    saved_w = getattr(app, "_portable_neo_sidebar_w_saved", None)
    if sidebar is not None and saved_w is not None:
        sidebar.setFixedWidth(int(saved_w))

    saved_m = getattr(app, "_portable_neo_margins_saved", None)
    if lay is not None and saved_m is not None:
        lay.setContentsMargins(*saved_m)
        sp = getattr(app, "_portable_neo_spacing_saved", None)
        if sp is not None:
            lay.setSpacing(int(sp))

    app._portable_neo_chrome_on = False
    for attr in (
        "_portable_neo_sidebar_w_saved",
        "_portable_neo_margins_saved",
        "_portable_neo_spacing_saved",
    ):
        if hasattr(app, attr):
            delattr(app, attr)


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
    """Embed desktop neo export panel + queue rail + portable render control strip."""

    def __init__(self, app, parent=None):
        theme = dialog_theme(parent or getattr(app, "ui", None))
        super().__init__("Render", parent or app.ui, **theme)
        self._app = app
        self._neo = getattr(app, "neo_wrapper", None)
        self._home = (None, None, -1, "orphan")
        self._hw = getattr(app, "hide_watcher", None)
        if self._hw is not None:
            self._hw.set_suppressed(True)

        from steempeg.ui.portable.queue_sidebar import PortableQueueSidebar
        from steempeg.ui.ui_density import scaled_dialog_size

        host = parent or getattr(app, "ui", None)
        compact = portable_render_sheet_compact(host)
        app._portable_sheet_compact = compact

        self.setMinimumSize(1040, 420)
        if compact:
            # Deck / small: near-full shell so 291px combos + queue rail fit.
            w, h = scaled_dialog_size(1480, 620, parent=host, factor=0.98)
            if host is not None:
                hw = int(host.width() or 0)
                hh = int(host.height() or 0)
                if hw > 0:
                    w = min(max(w, 1240), hw - 8, 1520)
                    w = min(w, hw - 8)
                if hh > 0:
                    h = min(max(h, 480), hh - 40)
                self.setFixedSize(w, max(480, h))
            else:
                self.setFixedSize(max(1240, w), max(480, h))
        else:
            # Roomy shell: comfort footprint with breathing room — no squeeze hacks.
            w, h = scaled_dialog_size(1480, 700, parent=host, factor=0.90)
            if host is not None:
                hw = int(host.width() or 0)
                hh = int(host.height() or 0)
                if hw > 0:
                    w = min(max(w, 1280), hw - 48)
                if hh > 0:
                    h = min(max(h, 560), hh - 64)
                self.setFixedSize(w, max(560, h))
            else:
                self.setFixedSize(max(1280, w), max(560, h))
        self.content_layout.setContentsMargins(12, 8, 12, 0)
        self.content_layout.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(10)

        self._queue = PortableQueueSidebar(app, self, compact=compact)
        self._queue.job_selected.connect(self._on_queue_job)
        body.addWidget(self._queue, 0)
        app._portable_queue_sidebar = self._queue

        # Right column: settings + launch strip. Bottoms align with the queue list panel.
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        if self._neo is None:
            from PySide6.QtWidgets import QLabel

            empty = QLabel("Render settings panel is not available.")
            empty.setStyleSheet(f"color: {tok.TEXT_MUTED};")
            right.addWidget(empty, 1)
        else:
            self._home = _borrow_widget(self._neo)
            self._neo.show()
            self._neo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            if compact:
                apply_portable_neo_chrome(app)
            # Theatre / portable hide settings_tabs separately from neo_wrapper —
            # without this the sheet opens empty (sidebar only / blank content).
            tabs = getattr(getattr(app, "ui", None), "settings_tabs", None)
            if tabs is not None:
                tabs.show()
                # Landing tab for a "Render settings" sheet — not Source Info.
                if tabs.count() > 1:
                    tabs.setCurrentIndex(1)
            for name in ("_neo_sidebar", "right_scroll"):
                w = getattr(app, name, None)
                if w is not None:
                    w.show()
            if hasattr(app, "fit_settings_tab_to_page"):
                QTimer.singleShot(0, app.fit_settings_tab_to_page)
            right.addWidget(self._neo, 1)

        self._strip = PortableRenderControlStrip(app, self)
        right.addWidget(self._strip, 0)
        app._portable_render_strip = self._strip

        body.addLayout(right, 1)
        self.content_layout.addLayout(body, 1)

        # Full-width dark footer — Save only (queue + strip sit above).
        footer = QFrame()
        footer.setObjectName("portableRenderSaveBar")
        footer.setStyleSheet(
            "QFrame#portableRenderSaveBar {"
            " background-color: #141414; border: none;"
            " border-top: 1px solid #2a2a2a; }"
        )
        footer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(12, 10, 12, 12)
        footer_lay.setSpacing(8)
        footer_lay.addStretch(1)

        btn_save = QPushButton("Save")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(_BTN_SECONDARY)
        btn_save.clicked.connect(self._on_save)
        footer_lay.addWidget(btn_save)
        self.content_layout.addWidget(footer, 0)

    def _on_queue_job(self, job_id: str) -> None:
        if hasattr(self._app, "activate_queue_job"):
            self._app.activate_queue_job(job_id)
        if hasattr(self._strip, "sync_game_header"):
            self._strip.sync_game_header()
        self._strip.sync_from_app()
        self._queue.refresh()

    def _on_save(self) -> None:
        persist_render_settings(self._app)
        # Persist edits onto the selected queue job when applicable.
        if hasattr(self._app, "_sync_active_queue_job_from_ui"):
            try:
                if self._app._sync_active_queue_job_from_ui():
                    if hasattr(self._app, "_persist_render_queue"):
                        self._app._persist_render_queue()
                    self._queue.refresh()
            except Exception:
                pass
        self.accept()

    def done(self, result: int) -> None:
        restore_portable_neo_chrome(self._app)
        if hasattr(self._app, "_portable_sheet_compact"):
            delattr(self._app, "_portable_sheet_compact")
        if getattr(self._app, "_portable_render_strip", None) is self._strip:
            self._app._portable_render_strip = None
        if getattr(self._app, "_portable_queue_sidebar", None) is self._queue:
            self._app._portable_queue_sidebar = None
        if self._neo is not None:
            parent, layout, index, kind = self._home
            _return_widget(self._neo, parent, layout, index, kind, visible=False)
            self._neo = None
            # Keep tabs hidden while portable theatre remains active.
            if getattr(self._app, "is_theater", False):
                tabs = getattr(getattr(self._app, "ui", None), "settings_tabs", None)
                if tabs is not None:
                    tabs.hide()
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
