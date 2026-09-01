"""Portable / Steam Deck shell overlays — clip picker + render settings sheets."""
from __future__ import annotations

import logging
from dataclasses import asdict, fields

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.render.queue import RenderJobSettings
from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut
from steempeg.ui.message_dialog import dialog_theme
from steempeg.ui.portable.render_controls import PortableRenderControlStrip
from steempeg.ui.render_job_builder import apply_job_settings_to_ui, snapshot_settings_from_ui
from steempeg.ui.widgets.dialog_chrome import SteempegDialog

RENDER_SETTINGS_KEY = "render_export_settings"

# Host shell ≤ this width → compact portable Render sheet (Deck / ~1400 laptops).
# Wider shells (e.g. 1920×1080) keep full comfort chrome — no trim hacks.
PORTABLE_SHEET_COMPACT_MAX_W = 1600

# Compact-only neo rail trim (comfort default is 220).
# Right margin matches settings page left (16) so tab→strip ≈ strip→content.
_PORTABLE_NEO_SIDEBAR_W = 210
_PORTABLE_NEO_SIDEBAR_MARGINS = (10, 15, 16, 15)

# Inner chrome: content L/R margins (12+12) + body gap (10) + card rails (~4).
_SHEET_INNER_CHROME_W = 38
# Compact column floors / caps — used only for wide (~1480+) compact shells.
_QUEUE_RAIL_MIN = 340
_QUEUE_RAIL_MAX = 400
_QUEUE_RAIL_SPACIOUS = 400
_QUEUE_RAIL_GOLDEN = 390  # Deck / 1280×800: golden + room for queue text
_RIGHT_COL_MIN = 720
# True Deck LCD/OLED (~1280×800). Wider "Deck sims" (e.g. 1480×925) stay roomier.
_DECK_NATIVE_MAX_W = 1320
_DECK_NATIVE_MAX_H = 850


def portable_shell_height(app=None, host=None) -> int:
    shell = portable_shell_widget(app, host)
    if shell is not None:
        try:
            h = int(shell.height() or 0)
            if h > 32:
                return h
        except Exception:
            pass
    return 0


def portable_shell_is_deck_native(host=None, app=None) -> bool:
    """Steam Deck class footprint — not a stretched ~1480×925 desk simulation."""
    w = portable_shell_width(app=app, host=host)
    h = portable_shell_height(app=app, host=host)
    if w <= 0:
        return True
    return w <= _DECK_NATIVE_MAX_W and (h <= 0 or h <= _DECK_NATIVE_MAX_H)

_log = logging.getLogger(__name__)


def portable_shell_widget(app=None, host=None):
    """Main Steempeg window used for portable size/compact decisions.

    Prewarm parents sheets under a 0×0 garage widget — never treat that as the
    shell width (Linux then fell back to a maximized activeWindow and baked
    spacious chrome forever).
    """
    ui = getattr(app, "ui", None) if app is not None else None
    if ui is not None:
        return ui
    if host is not None:
        try:
            if int(host.width() or 0) > 32 and int(host.height() or 0) > 32:
                return host
        except Exception:
            pass
    try:
        aw = QApplication.activeWindow()
        if aw is not None and int(aw.width() or 0) > 32:
            return aw
    except Exception:
        pass
    return None


def portable_shell_width(app=None, host=None) -> int:
    """Logical width of the main shell (or primary work area as last resort)."""
    shell = portable_shell_widget(app, host)
    if shell is not None:
        try:
            w = int(shell.width() or 0)
            if w > 32:
                return w
        except Exception:
            pass
    try:
        screen = QApplication.primaryScreen()
        if screen is not None:
            return int(screen.availableGeometry().width() or 0)
    except Exception:
        pass
    return 0


def portable_render_sheet_compact(host=None, app=None) -> bool:
    """True when the shell is Deck / small-laptop class — use space-saving sheet chrome."""
    w = portable_shell_width(app=app, host=host)
    if w <= 0:
        return True  # safe default: compact fits more places
    return w <= PORTABLE_SHEET_COMPACT_MAX_W


def _split_wide_compact_columns(inner_w: int) -> tuple[int, int]:
    """Split for wide compact shells (~1480+): modest Queue, rest to render."""
    gap = 10
    usable = max(inner_w - gap, 1)
    q_min, r_min = _QUEUE_RAIL_MIN, _RIGHT_COL_MIN
    if usable >= q_min + r_min:
        extra = usable - q_min - r_min
        q_add = min(_QUEUE_RAIL_MAX - q_min, extra // 4)
        return q_min + q_add, r_min + (extra - q_add)
    queue = max(320, min(q_min, usable - 620))
    right = max(620, usable - queue)
    if queue + right > usable:
        right = max(580, usable - queue)
    return queue, right


def portable_render_sheet_geometry(*, compact: bool, shell) -> tuple[int, int, int]:
    """Return ``(sheet_w, sheet_h, queue_rail_w)`` for the current shell."""
    from steempeg.ui.ui_density import scaled_dialog_size

    hw = 0
    hh = 0
    if shell is not None:
        try:
            hw = int(shell.width() or 0)
            hh = int(shell.height() or 0)
        except Exception:
            hw = hh = 0

    if compact:
        # --- Golden standard: true Deck / 1280×800 (pre-Gemini sim) ---
        if portable_shell_is_deck_native(shell):
            w, h = scaled_dialog_size(1480, 620, parent=shell, factor=0.98)
            if hw > 0:
                w = min(max(w, 1240), hw - 8, 1520)
                w = min(w, hw - 8)
            else:
                w = max(1240, w)
            if hh > 0:
                h = min(max(h, 480), hh - 40)
            else:
                h = max(480, h)
            return max(640, w), max(480, h), _QUEUE_RAIL_GOLDEN

        # --- Wide compact (Gemini-style ~1480×925 desk sim) ---
        margin = 16
        if hw > 0:
            sheet_w = max(640, hw - margin)
        else:
            sheet_w, _ = scaled_dialog_size(1180, 600, parent=shell, factor=0.98)
            sheet_w = max(1080, min(sheet_w, 1280))
        _, design_h = scaled_dialog_size(1180, 600, parent=shell, factor=0.98)
        sheet_h = max(480, min(design_h, 640))
        if hh > 0:
            sheet_h = min(sheet_h, hh - 40)
            sheet_h = max(480, sheet_h)
        inner = max(sheet_w - _SHEET_INNER_CHROME_W, _QUEUE_RAIL_MIN + _RIGHT_COL_MIN + 10)
        queue_w, _right = _split_wide_compact_columns(inner)
        return sheet_w, sheet_h, queue_w

    w, h = scaled_dialog_size(1480, 700, parent=shell, factor=0.90)
    if hw > 0:
        w = min(max(w, 1280), hw - 48)
    else:
        w = max(1280, w)
    if hh > 0:
        h = min(max(h, 560), hh - 64)
    else:
        h = max(560, h)
    return max(640, w), max(560, h), _QUEUE_RAIL_SPACIOUS


def portable_render_sheet_size(*, compact: bool, shell) -> tuple[int, int]:
    """Fixed dialog size for the current shell footprint."""
    w, h, _queue = portable_render_sheet_geometry(compact=compact, shell=shell)
    return w, h


def portable_settings_density(app):
    """Settings column for the portable Render sheet.

    Deck / compact: narrow Source·Video·Audio·Export so content clears the
    Render right edge — width only. Keep comfort fonts/chrome (lerp made
    the panel look intentionally squashed).
    """
    from dataclasses import replace

    from steempeg.ui.ui_density import COMFORT

    ui = getattr(app, "ui", None)
    try:
        tight = portable_shell_is_deck_native(ui, app=app) or portable_render_sheet_compact(
            ui, app=app
        )
    except Exception:
        tight = True
    if not tight:
        return COMFORT

    # Comfort content is 646; ~560 + R=20 clears the scroll groove on Deck.
    content_w = 560
    gap = 8
    warn = 8 + 16  # spacing + warn slot (same formula as UiDensity)
    combo_w = (content_w - 16 - 2 * warn) // 2
    stat_w = (content_w - 2 * gap) // 3
    return replace(
        COMFORT,
        settings_content_w=content_w,
        settings_stat_w=stat_w,
        settings_combo_w=combo_w,
        settings_page_margin=(16, 15, 20, 8),
    )


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

    dense = portable_settings_density(app)
    left, top, right, bottom = dense.settings_page_margin
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

    restore_neo_dock_masks(app)

    # Undo Deck content shrink — restore shell settings column.
    ui = getattr(app, "ui", None)
    if ui is not None:
        try:
            from steempeg.ui.render_panel import apply_settings_panel_density
            from steempeg.ui.ui_density import COMFORT

            dense = getattr(app, "_ui_density", None) or COMFORT
            apply_settings_panel_density(ui, dense)
        except Exception:
            pass


def expand_neo_for_floating_dialog(neo, dialog) -> None:
    """Clear 0×0 garage constraints so neo can fill a floating Render sheet.

    Do **not** set ``minimumSize`` to the dialog content box: that fights the
    dialog layout, overlaps neo-nav hitboxes (hover on A paints B), and
    squashes settings chrome.

    Suspend only the outer ``neo_wrapper`` mask while floating. Translucent
    frameless dialogs used to desync nav hit-tests against a masked wrapper;
    opaque float dialogs are fine without it. The settings scroll's left-only
    mask (nav↔content divider curve) does not touch the nav rail and must stay
    active — clearing it leaves square TL/BL corners on Windows.
    """
    if neo is None or dialog is None:
        return
    from PySide6.QtWidgets import QPushButton, QScrollArea, QTabWidget

    neo.setMinimumSize(0, 0)
    neo.setMaximumSize(16777215, 16777215)
    neo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    app = getattr(dialog, "_app", None)
    if app is not None:
        wrapper_mask = getattr(app, "_neo_wrapper_mask", None)
        if wrapper_mask is not None:
            wrapper_mask._suspended = True
    try:
        neo.clearMask()
    except RuntimeError:
        pass

    for scroll in neo.findChildren(QScrollArea):
        if scroll.objectName() == "neo_settings_scroll":
            scroll.setMinimumSize(0, 0)
            scroll.setMaximumSize(16777215, 16777215)
            scroll.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
    for tabs in neo.findChildren(QTabWidget):
        if tabs.objectName() == "settings_tabs":
            tabs.setMinimumSize(0, 0)
            tabs.setMaximumSize(16777215, 16777215)
            tabs.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )

    # Keep the nav rail from being width-crushed; raise above the scroll so a
    # stale overlap cannot steal clicks from the pills.
    sidebar = neo.findChild(QWidget, "neo_sidebar")
    if sidebar is not None:
        try:
            if sidebar.width() > 0:
                sidebar.setFixedWidth(max(180, int(sidebar.width())))
            elif sidebar.minimumWidth() < 180:
                sidebar.setFixedWidth(220)
            sidebar.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
            )
            sidebar.raise_()
            for btn in sidebar.findChildren(QPushButton):
                # Fixed height — min-only still let a tight layout overlap rows.
                btn.setFixedHeight(44)
                btn.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
                try:
                    btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                except Exception:
                    pass
        except RuntimeError:
            pass

    if app is not None:
        corner_mask = getattr(app, "corner_mask", None)
        if corner_mask is not None:
            corner_mask._suspended = False
            timer = getattr(corner_mask, "_timer", None)
            if timer is not None:
                try:
                    timer.start(0)
                except RuntimeError:
                    pass

    neo.updateGeometry()


def restore_neo_dock_masks(app) -> None:
    """Re-enable neo corner masks after floating Render Settings returns neo."""
    if app is None:
        return
    for attr in ("_neo_wrapper_mask", "corner_mask"):
        mask = getattr(app, attr, None)
        if mask is None:
            continue
        mask._suspended = False
        timer = getattr(mask, "_timer", None)
        if timer is not None:
            try:
                timer.start(0)
            except RuntimeError:
                pass


def persist_render_settings(app) -> bool:
    """Snapshot export panel into settings.json (shared by Desktop and Portable)."""
    try:
        data = asdict(snapshot_settings_from_ui(app))
        if not hasattr(app, "save_user_settings"):
            return False
        return bool(app.save_user_settings(RENDER_SETTINGS_KEY, data))
    except Exception:
        _log.exception("Failed to persist render settings")
        return False


def restore_render_settings(app) -> None:
    """Apply last saved export panel snapshot if present."""
    raw = app.load_user_settings().get(RENDER_SETTINGS_KEY)
    if not isinstance(raw, dict) or not raw:
        # Still honour Main Settings permanent export folder.
        try:
            from steempeg.ui.settings_prefs import apply_export_folder

            apply_export_folder(app, persist=False)
        except Exception:
            pass
        return
    allowed = {f.name for f in fields(RenderJobSettings)}
    cleaned = {k: v for k, v in raw.items() if k in allowed}
    try:
        apply_job_settings_to_ui(app, RenderJobSettings(**cleaned))
    except Exception:
        _log.exception("Failed to restore render settings")
    # Main Settings permanent folder wins over snapshot save_dir.
    try:
        from steempeg.ui.settings_prefs import (
            KEY_PERMANENT_EXPORT_FOLDER,
            apply_export_folder,
            normalize_export_folder,
        )

        settings = app.load_user_settings() or {}
        permanent = normalize_export_folder(settings.get(KEY_PERMANENT_EXPORT_FOLDER))
        if permanent:
            apply_export_folder(app, permanent, persist=False)
    except Exception:
        _log.exception("Failed re-applying permanent export folder")


def ensure_render_settings_restored(app) -> None:
    """Restore the shared panel snapshot once per process (Desktop or Portable)."""
    if getattr(app, "_render_settings_restored", False):
        return
    restore_render_settings(app)
    app._render_settings_restored = True
    # Back-compat for older portable chrome checks.
    app._portable_render_settings_restored = True


def _find_layout_index(layout, widget: QWidget):
    """Return (layout, index) for widget in this layout or any nested sub-layout."""
    if layout is None:
        return None
    idx = layout.indexOf(widget)
    if idx >= 0:
        return layout, idx
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        child = item.layout()
        if child is not None:
            found = _find_layout_index(child, widget)
            if found is not None:
                return found
    return None


# Hidden host so borrowed widgets never become top-level HWNDs (Aero/white flash).
_BORROW_SINK: QWidget | None = None


def _borrow_sink() -> QWidget:
    global _BORROW_SINK
    if _BORROW_SINK is None:
        sink = QWidget()
        sink.setObjectName("steempegBorrowSink")
        sink.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        sink.hide()
        _BORROW_SINK = sink
    return _BORROW_SINK


def _reparent_borrowed(widget: QWidget) -> None:
    """Park under the borrow sink — never ``setParent(None)`` (maps at 0,0)."""
    from PySide6.QtCore import Qt

    try:
        widget.hide()
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        widget.setParent(_borrow_sink())
    except RuntimeError:
        pass


def _borrow_widget(widget: QWidget):
    """Detach widget from layout or QSplitter parent.

    Returns (parent, layout_or_None, index, kind) where kind is ``\"layout\"`` or ``\"splitter\"``.

    Never orphan with ``setParent(None)``: that briefly maps a top-level HWND at
    (0,0) — the white/Aero «прослойка» when opening Render Settings. Layout
    borrows stay under the old parent until ``addWidget`` reparents; splitter /
    orphan cases park under a hidden sink.
    """
    from PySide6.QtCore import Qt

    try:
        widget.hide()
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    except RuntimeError:
        pass

    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    found = _find_layout_index(layout, widget) if layout is not None else None
    if found is not None:
        host_layout, index = found
        host_layout.removeWidget(widget)
        # Keep old parent until the destination layout reparents — no orphan HWND.
        return parent, host_layout, index, "layout"

    # QSplitter (main library column) has no QLayout.
    from PySide6.QtWidgets import QSplitter

    if isinstance(parent, QSplitter):
        index = -1
        for i in range(parent.count()):
            if parent.widget(i) is widget:
                index = i
                break
        _reparent_borrowed(widget)
        return parent, None, index, "splitter"

    _reparent_borrowed(widget)
    return parent, None, -1, "orphan"


def _clear_borrow_dont_show(widget: QWidget) -> None:
    """Allow a borrowed widget to paint after it has a real parent again."""
    from PySide6.QtCore import Qt

    try:
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)
    except RuntimeError:
        pass


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

    def __init__(self, app, parent=None, *, warm: bool = False):
        theme = dialog_theme(parent or getattr(app, "ui", None))
        super().__init__("Render", parent or app.ui, suppress_map=bool(warm), **theme)
        self._app = app
        self._warm = bool(warm)
        self._neo = getattr(app, "neo_wrapper", None)
        self._home = (None, None, -1, "orphan")
        self._hw = getattr(app, "hide_watcher", None)
        if self._hw is not None:
            self._hw.set_suppressed(True)

        from steempeg.ui.portable.queue_sidebar import PortableQueueSidebar

        # Prefer app.ui — parent is often the 0×0 prewarm garage.
        shell = portable_shell_widget(app, parent)
        compact = portable_render_sheet_compact(shell, app=app)
        self._sheet_compact = bool(compact)
        app._portable_sheet_compact = compact

        self.setMinimumSize(1040, 420)
        w, h, queue_w = portable_render_sheet_geometry(compact=compact, shell=shell)
        self.setFixedSize(w, h)
        self.content_layout.setContentsMargins(12, 8, 12, 0)
        self.content_layout.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(10)

        self._queue = PortableQueueSidebar(app, self, compact=compact)
        self._queue.apply_rail_width(compact=compact, width=queue_w)
        self._queue.job_selected.connect(self._on_queue_job)
        body.addWidget(self._queue, 0)
        app._portable_queue_sidebar = self._queue
        if hasattr(app, "_sync_library_scan_interaction_lock"):
            app._sync_library_scan_interaction_lock(
                busy=bool(getattr(app, "_clips_scan_active", False))
            )

        # Right column: settings + launch strip. Bottoms align with the queue list panel.
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        # Keep a handle so prepare_for_show can reclaim neo if dock chrome stole it.
        self._neo_host_layout = right

        if self._neo is None:
            from PySide6.QtWidgets import QLabel

            empty = QLabel("Render settings panel is not available.")
            empty.setStyleSheet(f"color: {tok.TEXT_MUTED};")
            right.addWidget(empty, 1)
        else:
            self._home = _borrow_widget(self._neo)
            # Warm/prewarm: keep neo hidden — showing it forces a top-level HWND flash.
            _clear_borrow_dont_show(self._neo)
            if not self._warm:
                self._neo.show()
            self._neo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            if compact:
                apply_portable_neo_chrome(app)
            # Theatre / portable hide settings_tabs separately from neo_wrapper —
            # without this the sheet opens empty (sidebar only / blank content).
            tabs = getattr(getattr(app, "ui", None), "settings_tabs", None)
            if tabs is not None and not self._warm:
                tabs.show()
                # Landing tab from Settings → Default Render panel tab.
                from steempeg.ui.settings_prefs import apply_default_render_tab

                apply_default_render_tab(app)
            if not self._warm:
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
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        footer.setStyleSheet(ut.portable_render_save_bar_stylesheet())
        footer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._save_bar = footer
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(12, 10, 12, 12)
        footer_lay.setSpacing(8)

        sec_btn = ut.settings_dialog_secondary_button_stylesheet()
        btn_choose = QPushButton("Choose a Clip")
        btn_choose.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_choose.setStyleSheet(sec_btn)
        btn_choose.setToolTip("Open Clips Manager without closing Render settings")
        btn_choose.clicked.connect(self._on_choose_clip)
        footer_lay.addWidget(btn_choose, 0)

        footer_lay.addStretch(1)

        btn_save = QPushButton("Save")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(sec_btn)
        btn_save.clicked.connect(self._on_save)
        footer_lay.addWidget(btn_save)
        self.content_layout.addWidget(footer, 0)

        # Title-bar X must always dismiss — bypass any future reject() overrides.
        try:
            self._title_bar.close_requested.disconnect(self.reject)
        except (TypeError, RuntimeError):
            pass
        self._title_bar.close_requested.connect(self._force_close)

        if self._warm:
            # Prewarm builds the sheet hidden — don't leave hide_watcher suppressed.
            if self._hw is not None:
                self._hw.set_suppressed(False)
            garage = self.parentWidget()
            self._park_as_embedded_widget(garage)

    def _reclaim_neo_into_sheet(self) -> None:
        """Re-embed neo if dock / Like-a-Portable chrome parked it in the garage."""
        neo = self._neo or getattr(self._app, "neo_wrapper", None)
        host = getattr(self, "_neo_host_layout", None)
        if neo is None or host is None:
            return
        self._neo = neo
        try:
            if self.isAncestorOf(neo):
                return
        except RuntimeError:
            return
        parent = neo.parentWidget()
        if parent is not None:
            lay = parent.layout()
            if lay is not None:
                lay.removeWidget(neo)
            else:
                _reparent_borrowed(neo)
        neo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Insert above the control strip when present.
        strip = getattr(self, "_strip", None)
        insert_at = host.count()
        if strip is not None:
            for i in range(host.count()):
                item = host.itemAt(i)
                if item is not None and item.widget() is strip:
                    insert_at = i
                    break
        host.insertWidget(insert_at, neo, 1)
        # Dock chrome may have snapshotted this sheet as neo's "home" — drop it.
        if getattr(self._app, "_neo_dock_home", None):
            self._app._neo_dock_home = None
        from steempeg.ui.portable.sheets import expand_neo_for_floating_dialog

        expand_neo_for_floating_dialog(neo, self)

    def _sync_floating_neo_geometry(self) -> None:
        from steempeg.ui.portable.sheets import expand_neo_for_floating_dialog

        neo = self._neo or getattr(self._app, "neo_wrapper", None)
        expand_neo_for_floating_dialog(neo, self)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_floating_neo_geometry)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_floating_neo_geometry()

    def prepare_for_show(self) -> None:
        """Re-arm a warm sheet before show (no reparent)."""
        host = getattr(self._app, "ui", None)
        if hasattr(self, "release_map_suppression"):
            self.release_map_suppression(host)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._hw = getattr(self._app, "hide_watcher", None)
        if self._hw is not None:
            self._hw.set_suppressed(True)
        self._app._portable_queue_sidebar = self._queue
        self._app._portable_render_strip = self._strip
        from steempeg.input.deck_navigation import reset_render_deck_focus

        reset_render_deck_focus(self._app)
        # Keep footprint in sync when the user resized the shell after prewarm.
        compact = bool(getattr(self, "_sheet_compact", True))
        self._app._portable_sheet_compact = compact
        w, h, queue_w = portable_render_sheet_geometry(compact=compact, shell=host)
        self.setFixedSize(w, h)
        if hasattr(self._queue, "apply_rail_width"):
            self._queue.apply_rail_width(compact=compact, width=queue_w)
        self._reclaim_neo_into_sheet()
        if self._neo is not None:
            self._neo.show()
            tabs = getattr(getattr(self._app, "ui", None), "settings_tabs", None)
            if tabs is not None:
                tabs.show()
                from steempeg.ui.settings_prefs import apply_default_render_tab

                apply_default_render_tab(self._app)
            for name in ("_neo_sidebar", "right_scroll"):
                wdg = getattr(self._app, name, None)
                if wdg is not None:
                    wdg.show()
            if getattr(self, "_sheet_compact", True):
                apply_portable_neo_chrome(self._app)
        if hasattr(self._app, "refresh_export_presets_list"):
            try:
                self._app.refresh_export_presets_list()
            except Exception:
                pass
        if hasattr(self._queue, "refresh"):
            self._queue.refresh()
        if hasattr(self._strip, "sync_from_app"):
            self._strip.sync_from_app()
        # Queue-first Ready badge + summary (not plain green / "Select a clip…").
        if hasattr(self._app, "update_status_indicator"):
            try:
                self._app.update_status_indicator("Ready", "ready")
            except Exception:
                pass
        if hasattr(self._strip, "sync_game_header"):
            self._strip.sync_game_header()
        if hasattr(self._app, "fit_settings_tab_to_page"):
            QTimer.singleShot(0, self._app.fit_settings_tab_to_page)
        if hasattr(self, "reset_title_bar_chrome"):
            self.reset_title_bar_chrome()
        QTimer.singleShot(0, self._sync_floating_neo_geometry)

    def apply_ui_theme_chrome(self) -> None:
        """Retint dialog chrome + Queue rail + Render strip when UI theme changes."""
        super().apply_ui_theme_chrome()
        from steempeg.ui.render_panel import (
            apply_neo_shell_theme_chrome,
            apply_render_panel_theme_chrome,
        )

        apply_neo_shell_theme_chrome(self._app)
        ui = getattr(self._app, "ui", None)
        if ui is not None:
            apply_render_panel_theme_chrome(ui)
        strip = getattr(self, "_strip", None)
        if strip is not None and hasattr(strip, "apply_ui_theme_chrome"):
            try:
                strip.apply_ui_theme_chrome()
            except Exception:
                pass
        queue = getattr(self, "_queue", None)
        if queue is not None and hasattr(queue, "apply_ui_theme_chrome"):
            try:
                queue.apply_ui_theme_chrome()
            except Exception:
                pass
        save_bar = getattr(self, "_save_bar", None)
        if save_bar is not None:
            try:
                save_bar.setStyleSheet(ut.portable_render_save_bar_stylesheet())
                sec = ut.settings_dialog_secondary_button_stylesheet()
                for btn in save_bar.findChildren(QPushButton):
                    btn.setStyleSheet(sec)
            except Exception:
                pass

    def _force_close(self) -> None:
        from PySide6.QtWidgets import QDialog

        QDialog.reject(self)

    def dispose_warm(self) -> None:
        """Return borrowed neo to the main shell and destroy this dialog."""
        self._warm = False
        self.done(0)
        self.deleteLater()

    def _on_queue_job(self, job_id: str) -> None:
        # Selection chrome is already updated by the sidebar click handler.
        # Skip the portable list rebuild inside activate_queue_job — on Linux,
        # setParent(None) while tearing down rows maps brief top-level windows.
        app = self._app
        app._skip_portable_queue_rebuild = True
        try:
            if hasattr(app, "activate_queue_job"):
                app.activate_queue_job(job_id)
        finally:
            app._skip_portable_queue_rebuild = False
        if hasattr(self._strip, "sync_game_header"):
            self._strip.sync_game_header()
        self._strip.sync_from_app()
        if hasattr(self._queue, "sync_selection"):
            self._queue.sync_selection(job_id)

    def _on_choose_clip(self) -> None:
        """Open Choose a Clip without blocking this Render sheet."""
        from steempeg.ui.portable.chrome import open_portable_clip_picker

        open_portable_clip_picker(self._app, host_parent=self)

    def _close_nested_clip_picker(self) -> None:
        app = self._app
        if not getattr(app, "_portable_clip_picker_open", False):
            return
        # Avoid raising this sheet from picker close while we are dismissing.
        app._portable_clip_picker_host = None
        picker = getattr(app, "_portable_clip_picker_dlg", None)
        if picker is None:
            app._portable_clip_picker_open = False
            return
        try:
            picker.done(0)
        except RuntimeError:
            app._portable_clip_picker_open = False

    def _notify_sheet_closed(self) -> None:
        from steempeg.ui.portable.chrome import mark_portable_render_sheet_closed

        mark_portable_render_sheet_closed(self._app)

    def _on_save(self) -> None:
        from steempeg.ui.message_dialog import steempeg_warning

        if not persist_render_settings(self._app):
            steempeg_warning(
                self,
                "Settings not saved",
                "Could not save render settings.",
                detail="Check that the Steempeg cache folder is writable, then try again.",
            )
            return
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
        self._close_nested_clip_picker()
        if self._warm:
            # Keep neo embedded — next open is show/hide, not reparent thrash.
            if self._hw is not None:
                self._hw.set_suppressed(False)
            if getattr(self._app, "is_theater", False):
                tabs = getattr(getattr(self._app, "ui", None), "settings_tabs", None)
                if tabs is not None:
                    tabs.hide()
            from PySide6.QtWidgets import QDialog

            QDialog.done(self, result)
            # Keep Dialog HWND — only unmap. Demoting to Widget made every reopen slow.
            self._park_hidden_dialog()
            self._notify_sheet_closed()
            return

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
        self._notify_sheet_closed()


class PortableClipPickerDialog(SteempegDialog):
    """Theatre overlay: Clips Manager (grid) + Rendered tab."""

    def __init__(self, app, parent=None, *, warm: bool = False):
        theme = dialog_theme(parent or getattr(app, "ui", None))
        super().__init__("Choose a Clip", parent or app.ui, suppress_map=bool(warm), **theme)
        self._app = app
        self._warm = bool(warm)
        self._panel = getattr(app.ui, "left_panel", None)
        self._home = (None, None, -1, "orphan")
        self._armed = False
        self._pick_wired = False
        self._prev_clips_mode = None
        self._prev_rendered_mode = None
        self._prev_sel_modes: list[tuple[object, object]] = []
        self._toggle_was_visible = True
        self._folder_refresh_mounted = False
        self._folder_home = None
        self._refresh_home = None
        self._folder_size_policy = None
        self._refresh_size_policy = None
        self._folder_max_width = None
        self._refresh_max_width = None

        self.setMinimumSize(640, 480)
        self.content_layout.setContentsMargins(10, 6, 10, 10)

        # Esc → reject() (clear selection first). Title-bar X must always close.
        try:
            self._title_bar.close_requested.disconnect(self.reject)
        except (TypeError, RuntimeError):
            pass
        self._title_bar.close_requested.connect(self._force_close)

        if self._panel is None:
            from PySide6.QtWidgets import QLabel

            empty = QLabel("Clips Manager is not available.")
            empty.setStyleSheet(f"color: {tok.TEXT_MUTED};")
            self.content_layout.addWidget(empty)
        else:
            self._prepare_library_for_sheet()
            self._home = _borrow_widget(self._panel)
            # Warm: do not show the panel — parent.show() forces a top-level HWND flash.
            _clear_borrow_dont_show(self._panel)
            if not self._warm:
                self._panel.show()
            self._panel.setMinimumWidth(0)
            self._panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.content_layout.addWidget(self._panel, 1)

        self._sync_size_to_shell()

        if not self._warm:
            QTimer.singleShot(350, self._arm_selection_close)
        else:
            garage = self.parentWidget()
            self._park_as_embedded_widget(garage)

    def _sync_size_to_shell(self) -> None:
        """Fit the sheet to the live main window (not the 0×0 prewarm garage)."""
        shell = portable_shell_widget(self._app, getattr(self._app, "ui", None))
        if shell is None:
            return
        try:
            geo = shell.geometry()
        except Exception:
            return
        # Clip cards are fixed 254px (+15 spacing). Cap to a shell fraction, then
        # snap *down* to a whole number of columns so the right edge isn't a
        # dead strip (growing toward the next column left emptiness again).
        shell_w = int(geo.width())
        shell_h = int(geo.height())
        # Wider caps (Windows 40.2) + column snap (Linux) so the right edge
        # isn't a dead strip beside the scrollbar.
        if shell_w >= 1920:
            w_frac = 0.94
        elif shell_w > 1600:
            w_frac = 0.92
        elif shell_w > 1280:
            w_frac = 0.90
        else:
            w_frac = 0.88
        if shell_h >= 1080:
            h_frac = 0.88
        elif shell_h > 900:
            h_frac = 0.86
        else:
            h_frac = 0.82

        card_pitch = 254 + 15
        # Dialog margins + library chrome + vertical scrollbar gutter (~16–20px).
        # Without the gutter the last column leaves a dead strip beside the bar.
        chrome_w = 56 + 80
        max_w = max(720, int(shell_w * w_frac))
        inner = max(0, max_w - chrome_w)
        cols = max(1, inner // card_pitch) if card_pitch > 0 else 1
        target_w = cols * card_pitch + chrome_w
        target_w = min(max(target_w, 720), shell_w - 16)
        self.resize(
            target_w,
            max(520, int(shell_h * h_frac)),
        )

    def prepare_for_show(self) -> None:
        """Re-arm a warm picker before show (panel already embedded)."""
        host = getattr(self._app, "ui", None)
        if hasattr(self, "release_map_suppression"):
            self.release_map_suppression(host)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._armed = False
        # Prewarm may have sized against a maximized shell — re-fit now.
        self._sync_size_to_shell()
        # Theatre / fullscreen may have called left_panel.hide() while the panel
        # lived in this sheet — without show() Add a Clip opens a blank dialog.
        if self._panel is not None:
            try:
                _clear_borrow_dont_show(self._panel)
                self._panel.show()
                self._panel.setMinimumWidth(0)
                self._panel.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
                )
            except RuntimeError:
                self._panel = None
        if self._panel is None:
            panel = getattr(getattr(self._app, "ui", None), "left_panel", None)
            if panel is not None:
                self._panel = panel
                self._prepare_library_for_sheet()
                self._home = _borrow_widget(self._panel)
                _clear_borrow_dont_show(self._panel)
                self._panel.show()
                self._panel.setMinimumWidth(0)
                self._panel.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
                )
                self.content_layout.addWidget(self._panel, 1)
        else:
            self._wire_pick_signals()
        self._mount_folder_refresh_in_toolbar()
        QTimer.singleShot(200, self._arm_selection_close)

    def dispose_warm(self) -> None:
        self._warm = False
        self.done(0)
        self.deleteLater()

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

        # Keep ExtendedSelection so Ctrl/Alt/Shift+LMB multi-select works.
        # Plain LMB still closes the sheet via _on_pick; modifier clicks stay open.
        widgets = []
        for name in ("grid_clips", "grid_rendered"):
            w = getattr(app, name, None)
            if w is not None:
                widgets.append(w)
        if hasattr(app, "ui") and hasattr(app.ui, "table_clips"):
            widgets.append(app.ui.table_clips)
        if hasattr(app, "table_rendered") and app.table_rendered is not None:
            widgets.append(app.table_rendered)

        self._prev_sel_modes = []
        for w in widgets:
            prev = w.selectionMode()
            self._prev_sel_modes.append((w, prev))
            w.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        self._wire_pick_signals()
        self._mount_folder_refresh_in_toolbar()
        if hasattr(app, "sync_library_filter_view"):
            app.sync_library_filter_view()

    def _mount_folder_refresh_in_toolbar(self) -> None:
        """Place View → Choose Folder → Refresh → count in the library toolbar."""
        if self._folder_refresh_mounted:
            return
        app = self._app
        layout = getattr(app, "_top_pill_layout", None)
        folder = getattr(app, "folder_picker", None)
        refresh = getattr(app, "btn_refresh", None)
        if layout is None or folder is None or refresh is None:
            return

        self._folder_home = _borrow_widget(folder)
        self._refresh_home = _borrow_widget(refresh)
        _clear_borrow_dont_show(folder)
        _clear_borrow_dont_show(refresh)
        self._folder_size_policy = folder.sizePolicy()
        self._refresh_size_policy = refresh.sizePolicy()
        self._folder_max_width = folder.maximumWidth()
        self._refresh_max_width = refresh.maximumWidth()

        folder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        folder.setMaximumWidth(320)
        refresh.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        refresh.setMaximumWidth(160)
        # Density passes while the footer was parked can leave ▾ hidden; restore.
        if hasattr(refresh, "set_menu_visible"):
            refresh.set_menu_visible(True)

        # View and its Grid/List toggle already lead the row. Mount the borrowed
        # folder controls immediately after them so the count stays after Refresh:
        # View · Choose Folder · Refresh · count.
        toggle = getattr(app, "toggle_pill", None)
        insert_at = layout.indexOf(toggle) + 1 if toggle is not None else 0
        layout.insertWidget(insert_at, folder)
        layout.insertWidget(insert_at + 1, refresh)
        folder.show()
        refresh.show()

        footer = getattr(app, "_footer_mega_pill", None)
        if footer is not None:
            footer.hide()

        self._folder_refresh_mounted = True

    def _unmount_folder_refresh_from_toolbar(self) -> None:
        if not self._folder_refresh_mounted:
            return
        app = self._app
        folder = getattr(app, "folder_picker", None)
        refresh = getattr(app, "btn_refresh", None)
        layout = getattr(app, "_top_pill_layout", None)

        if layout is not None:
            if folder is not None:
                idx = layout.indexOf(folder)
                if idx >= 0:
                    layout.removeWidget(folder)
            if refresh is not None:
                idx = layout.indexOf(refresh)
                if idx >= 0:
                    layout.removeWidget(refresh)

        if folder is not None and self._folder_home is not None:
            if self._folder_size_policy is not None:
                folder.setSizePolicy(self._folder_size_policy)
            if self._folder_max_width is not None:
                folder.setMaximumWidth(self._folder_max_width)
            parent, lay, index, kind = self._folder_home
            _return_widget(folder, parent, lay, index, kind, visible=False)

        if refresh is not None and self._refresh_home is not None:
            if self._refresh_size_policy is not None:
                refresh.setSizePolicy(self._refresh_size_policy)
            if self._refresh_max_width is not None:
                refresh.setMaximumWidth(self._refresh_max_width)
            parent, lay, index, kind = self._refresh_home
            _return_widget(refresh, parent, lay, index, kind, visible=False)

        self._folder_refresh_mounted = False
        self._folder_home = None
        self._refresh_home = None

    def _wire_pick_signals(self) -> None:
        if self._pick_wired:
            return
        app = self._app
        if hasattr(app, "grid_clips"):
            app.grid_clips.itemSelectionChanged.connect(self._on_pick)
        if hasattr(app, "grid_rendered"):
            app.grid_rendered.itemSelectionChanged.connect(self._on_pick)
        if hasattr(app, "ui") and hasattr(app.ui, "table_clips"):
            app.ui.table_clips.itemSelectionChanged.connect(self._on_pick)
        if hasattr(app, "table_rendered"):
            app.table_rendered.itemSelectionChanged.connect(self._on_pick)
        self._pick_wired = True

    def _unwire_pick_signals(self) -> None:
        if not self._pick_wired:
            return
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
        self._pick_wired = False

    def _arm_selection_close(self) -> None:
        self._armed = True

    def _try_clear_library_selection(self) -> bool:
        """Esc with a selection: deselect instead of closing the sheet."""
        app = self._app
        # Avoid selection-changed → accept while we clear.
        was_armed = self._armed
        self._armed = False
        try:
            if hasattr(app, "clear_library_item_selection"):
                return bool(app.clear_library_item_selection())
        finally:
            self._armed = was_armed
        return False

    def _force_close(self) -> None:
        """Title-bar close — always dismiss, even if clips are selected."""
        from PySide6.QtWidgets import QDialog

        QDialog.reject(self)

    def reject(self) -> None:
        # QDialog wires Esc → reject(). Clear multi-select first; second Esc closes.
        if self._try_clear_library_selection():
            return
        super().reject()

    def _on_pick(self) -> None:
        if not self._armed:
            return
        if getattr(self._app, "_deck_grid_nav_active", False):
            return
        mods = QApplication.keyboardModifiers()
        # Ctrl/Alt/Shift+LMB builds a multi-selection (context menu / queue) —
        # don't dismiss the Clips Manager sheet.
        if mods & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier
            | Qt.KeyboardModifier.AltModifier
        ):
            return
        self._armed = False
        QTimer.singleShot(0, self.accept)

    def _restore_library(self) -> None:
        app = self._app
        self._unwire_pick_signals()
        self._unmount_folder_refresh_from_toolbar()

        for w, mode in self._prev_sel_modes:
            try:
                w.setSelectionMode(mode)
            except RuntimeError:
                pass
        self._prev_sel_modes = []

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
        if self._warm:
            self._armed = False
            self._unwire_pick_signals()
            from PySide6.QtWidgets import QDialog

            QDialog.done(self, result)
            self._park_hidden_dialog()
            self._notify_picker_closed()
            return

        self._restore_library()
        if self._panel is not None:
            parent, layout, index, kind = self._home
            _return_widget(self._panel, parent, layout, index, kind, visible=False)
            if kind == "splitter" and parent is not None:
                try:
                    if parent.count() > 1:
                        handle = parent.handle(1)
                        if handle is not None:
                            handle.setVisible(False)
                except Exception:
                    pass
            self._panel = None
        super().done(result)
        self._notify_picker_closed()

    def _notify_picker_closed(self) -> None:
        from steempeg.ui.portable.chrome import mark_portable_clip_picker_closed

        mark_portable_clip_picker_closed(self._app)
