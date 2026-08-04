"""Portable theatre chrome — Choose a Clip / Render (opens settings+control sheet)."""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import QRectF, Qt, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from steempeg.ui.design_tokens import with_tooltip_style
from steempeg.ui.icon_assets import add_clip_icon
from steempeg.ui.player.controls.adaptive_trim_tools import (
    ensure_adaptive_trim_hook,
    sync_trim_tools_placement,
)
from steempeg.ui.portable.sheets import (
    PortableClipPickerDialog,
    PortableRenderSettingsDialog,
    ensure_render_settings_restored,
    portable_render_sheet_compact,
)

_log = logging.getLogger(__name__)


# Match clip-health chip chrome (icon + label, soft fill, 2px border).
_ADD_CLIP_COLOR = "#8e7cc3"
_ADD_CLIP_TEXT = "#d4c8f5"
_ADD_CLIP_ICON = 18

# Local QSS without QToolTip → Windows paints a native black tip; wrap both.
_ADD_CLIP_STYLE = with_tooltip_style(
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

_RENDER_STYLE = with_tooltip_style(
    # Same pill language as Trim — rounded ends, bold label; flag emoji for now.
    "QPushButton {"
    "background-color: #2e6b32; color: #ffffff;"
    "border: 2px solid #3e8e41; border-radius: 15px;"
    "padding: 0 12px; font-weight: bold;"
    "}"
    "QPushButton:hover { background-color: #3e8e41; border: 2px solid #57c75b; }"
    "QPushButton:pressed { background-color: #235226; }"
    "QPushButton:disabled { background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }"
)

_SCAN_RING_SIZE = 28
_SCAN_RING_COLOR = QColor(_ADD_CLIP_COLOR)
_SCAN_RING_TRACK = QColor(70, 70, 70)
_SCAN_RING_TEXT = QColor(_ADD_CLIP_TEXT)


class _LibraryScanRing(QWidget):
    """Compact % ring beside Choose a Clip while the library scan is locked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("portableLibraryScanRing")
        self.setFixedSize(_SCAN_RING_SIZE, _SCAN_RING_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._pct = 0.0
        self._searching = True
        self._angle = 0
        self._spin = QTimer(self)
        self._spin.setInterval(40)
        self._spin.timeout.connect(self._tick)
        self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 18) % 360
        self.update()

    def set_progress(self, percent: float | None = None, *, searching: bool = False) -> None:
        self._searching = bool(searching) or percent is None
        if percent is not None:
            self._pct = max(0.0, min(100.0, float(percent)))
        if self._searching:
            if not self._spin.isActive():
                self._spin.start()
        else:
            self._spin.stop()
        if not self.isVisible():
            self.show()
        self.update()

    def clear_progress(self) -> None:
        self._spin.stop()
        self.hide()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pad = 2.5
        rect = QRectF(pad, pad, self.width() - 2 * pad, self.height() - 2 * pad)

        track = QPen(_SCAN_RING_TRACK)
        track.setWidthF(2.6)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawEllipse(rect)

        arc = QPen(_SCAN_RING_COLOR)
        arc.setWidthF(2.6)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc)
        # Qt arcs: 16ths of a degree, 0 = 3 o'clock, counter-clockwise.
        if self._searching:
            painter.drawArc(rect, int((90 - self._angle) * 16), int(-110 * 16))
            label = "…"
        else:
            span = int(-360 * 16 * (self._pct / 100.0))
            painter.drawArc(rect, 90 * 16, span)
            label = f"{int(self._pct)}"

        painter.setPen(_SCAN_RING_TEXT)
        font = QFont("Segoe UI")
        font.setBold(True)
        # Same face as Choose a Clip (bold Segoe); slightly smaller so digits fit.
        font.setPixelSize(9 if len(label) <= 2 else 8)
        painter.setFont(font)
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), label)
        painter.end()


def sync_portable_library_scan_badge(
    app,
    *,
    percent: float | None = None,
    searching: bool = False,
    clear: bool = False,
) -> None:
    """Show/update/hide the Choose-a-Clip scan ring (portable only)."""
    if not getattr(app, "_portable_shell", False):
        return
    badge = getattr(app, "portable_library_scan_badge", None)
    if badge is None:
        return
    try:
        badge.objectName()
    except RuntimeError:
        app.portable_library_scan_badge = None
        return
    if clear:
        badge.clear_progress()
        return
    badge.set_progress(percent, searching=searching)


def ensure_portable_chrome(app) -> None:
    """Create (once) and show portable theatre CTAs."""
    _ensure_add_clip_button(app)
    _ensure_queue_header_controls(app)
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
    if not getattr(app, "_render_settings_restored", False) and not getattr(
        app, "_portable_render_settings_restored", False
    ):
        ensure_render_settings_restored(app)
    sync_portable_render_button(app)
    if hasattr(app, "_sync_library_scan_interaction_lock"):
        app._sync_library_scan_interaction_lock(
            busy=bool(getattr(app, "_clips_scan_active", False))
        )
    # Re-balance header once Choose a Clip (+ divider) exist — same path Settings
    # uses when the user re-selects SteempegUI / Steam-like.
    def _rebalance_header() -> None:
        if hasattr(app, "refresh_player_header_layout"):
            try:
                app.refresh_player_header_layout()
                return
            except Exception:
                pass
        try:
            from steempeg.ui.player_header_layout import apply_player_header_layout

            apply_player_header_layout(app)
        except Exception:
            pass

    _rebalance_header()
    # Pre-show apply can run before the header has a real width; one deferred
    # pass after the event loop maps the window matches a Settings re-select.
    if not getattr(app, "_portable_header_layout_deferred", False):
        app._portable_header_layout_deferred = True
        try:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, _rebalance_header)
        except Exception:
            app._portable_header_layout_deferred = False


def hide_portable_chrome(app) -> None:
    # Restore tools left-of-Trim without clearing the portable shell flag.
    was = getattr(app, "_portable_shell", False)
    app._portable_shell = False
    sync_trim_tools_placement(app)
    app._portable_shell = was
    for name in (
        "portable_add_clip_divider",
        "btn_portable_add_clip",
        "portable_library_scan_badge",
        "btn_portable_render",
        "btn_portable_render_settings",
        "btn_portable_add_to_queue",
        "btn_portable_in_queue",
        "btn_portable_queue_gear",
    ):
        btn = getattr(app, name, None)
        if btn is not None:
            btn.hide()
    dispose_portable_sheets(app)
    if hasattr(app, "refresh_player_header_layout"):
        try:
            app.refresh_player_header_layout()
        except Exception:
            pass


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
    # Insert after the title cluster (icon+name+info), before the trailing
    # stretch / status chips. Works for both SteempegUI (left) and Steam-like
    # (centered). If the title lives inside a center wing, park after that wing
    # — apply_player_header_layout (from ensure_portable_chrome) finalizes order.
    title = getattr(app, "player_header_title", None)
    insert_at = -1
    if title is not None:
        idx = lay.indexOf(title)
        if idx >= 0:
            insert_at = idx + 1
    if insert_at < 0:
        left_wing = getattr(app, "player_header_left_wing", None)
        if left_wing is not None:
            wi = lay.indexOf(left_wing)
            if wi >= 0:
                insert_at = wi + 1
    if insert_at < 0:
        insert_at = lay.count()
        for name in (
            "player_header_status",
            "player_header_divider",
            "player_header_actions",
        ):
            dock = getattr(app, name, None)
            if dock is not None:
                di = lay.indexOf(dock)
                if di >= 0:
                    insert_at = di
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
        # Re-parent onto the header if a layout pass left them orphaned.
        divider = getattr(app, "portable_add_clip_divider", None)
        if divider is not None and lay.indexOf(divider) < 0:
            at = lay.indexOf(btn) if lay.indexOf(btn) >= 0 else insert_at
            lay.insertWidget(at if at >= 0 else lay.count(), divider)
        if lay.indexOf(btn) < 0:
            at = lay.indexOf(divider) + 1 if divider is not None and lay.indexOf(divider) >= 0 else insert_at
            lay.insertWidget(max(0, at), btn)
        _ensure_library_scan_badge(app, lay)
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
    _ensure_library_scan_badge(app, lay)


# + Queue = white CTA (clip not queued yet); In queue stays yellow (QUEUED status).
_ADD_QUEUE_COLOR = "#ffffff"
_IN_QUEUE_COLOR = "#ffcc00"
# Painted plus + " Queue" — same padding rhythm as Choose a Clip.
_ADD_QUEUE_STYLE = with_tooltip_style(
    "QPushButton {"
    f"background-color: rgba(255, 255, 255, 0.12);"
    f"color: {_ADD_QUEUE_COLOR};"
    f"border: 2px solid {_ADD_QUEUE_COLOR};"
    "border-radius: 8px;"
    "font-weight: bold;"
    "font-size: 13px;"
    "padding: 2px 10px 2px 8px;"
    "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"
    "}"
    "QPushButton:hover { background-color: rgba(255, 255, 255, 0.22); }"
    "QPushButton:pressed { background-color: rgba(255, 255, 255, 0.32); }"
    "QPushButton:disabled {"
    "background-color: rgba(80, 80, 80, 0.25);"
    "color: #777777;"
    "border-color: #555555;"
    "}"
)

_IN_QUEUE_STYLE = with_tooltip_style(
    "QPushButton {"
    f"background-color: rgba(255, 204, 0, 0.18);"
    f"color: {_IN_QUEUE_COLOR};"
    f"border: 2px solid {_IN_QUEUE_COLOR};"
    "border-radius: 8px;"
    "font-weight: bold;"
    "font-size: 13px;"
    "padding: 2px 10px 2px 8px;"
    "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"
    "}"
    "QPushButton:hover { background-color: rgba(255, 204, 0, 0.32); }"
    "QPushButton:pressed { background-color: rgba(255, 204, 0, 0.45); }"
)


def _style_add_to_queue_button(btn: QPushButton) -> None:
    from steempeg.ui.icon_assets import bold_plus_icon

    # Glyph is ~10px; keep iconSize tight so side padding matches Choose a Clip
    # (an 18px empty box was reading as fat left/right margins).
    icon_sz = 12
    btn.setIcon(bold_plus_icon(icon_sz, _ADD_QUEUE_COLOR))
    btn.setIconSize(QSize(icon_sz, icon_sz))
    btn.setText(" Queue")
    btn.setStyleSheet(_ADD_QUEUE_STYLE)
    btn.setFixedHeight(30)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip("Add the current clip to the render queue")


def _style_in_queue_button(btn: QPushButton, text: str) -> None:
    from steempeg.ui.icon_assets import queue_chip_icon

    icon_sz = 16
    btn.setIcon(queue_chip_icon(icon_sz))
    btn.setIconSize(QSize(icon_sz, icon_sz))
    btn.setText(f" {text}")
    btn.setStyleSheet(_IN_QUEUE_STYLE)
    btn.setFixedHeight(30)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip("Open queue and render settings")


def _on_portable_add_to_queue(app) -> None:
    resolve = getattr(app, "_resolve_export_clip_path", None)
    path = resolve() if callable(resolve) else None
    if not path:
        return
    if hasattr(app, "add_clip_to_render_queue"):
        app.add_clip_to_render_queue(path)


def _ensure_queue_header_controls(app) -> None:
    """+ Queue CTA and combined In queue / Queue chip (opens the sheet)."""
    status = getattr(app, "player_header_status", None)
    if status is None or status.layout() is None:
        return
    lay: QHBoxLayout = status.layout()
    badge = getattr(app, "label_playback_badge", None)

    # Legacy separate gear — hide forever; In queue chip replaces it.
    legacy_gear = getattr(app, "btn_portable_queue_gear", None)
    if legacy_gear is not None:
        try:
            legacy_gear.hide()
        except RuntimeError:
            app.btn_portable_queue_gear = None

    add_btn = getattr(app, "btn_portable_add_to_queue", None)
    if add_btn is not None:
        try:
            add_btn.objectName()
        except RuntimeError:
            app.btn_portable_add_to_queue = None
            add_btn = None
    if add_btn is None:
        add_btn = QPushButton()
        add_btn.setObjectName("portableAddToQueue")
        add_btn.clicked.connect(lambda: _on_portable_add_to_queue(app))
        add_btn.hide()
        app.btn_portable_add_to_queue = add_btn
        insert_at = lay.indexOf(badge) if badge is not None else -1
        if insert_at >= 0:
            lay.insertWidget(insert_at, add_btn)
        else:
            lay.addWidget(add_btn)
    _style_add_to_queue_button(add_btn)

    in_btn = getattr(app, "btn_portable_in_queue", None)
    if in_btn is not None:
        try:
            in_btn.objectName()
        except RuntimeError:
            app.btn_portable_in_queue = None
            in_btn = None
    if in_btn is None:
        in_btn = QPushButton()
        in_btn.setObjectName("portableInQueue")
        in_btn.clicked.connect(lambda: open_portable_render_settings(app))
        in_btn.hide()
        app.btn_portable_in_queue = in_btn
        # After the Add button / badge slot.
        insert_at = lay.indexOf(add_btn) if add_btn is not None else -1
        if insert_at >= 0:
            lay.insertWidget(insert_at + 1, in_btn)
        else:
            insert_at = lay.indexOf(badge) if badge is not None else -1
            if insert_at >= 0:
                lay.insertWidget(insert_at, in_btn)
            else:
                lay.addWidget(in_btn)
    _style_in_queue_button(in_btn, "Queue")

    if hasattr(app, "update_playback_badge"):
        try:
            app.update_playback_badge()
        except Exception:
            pass


def sync_portable_queue_header(app) -> None:
    """Show + Queue (clip open) vs Queue / In queue chip (open the sheet)."""
    if not getattr(app, "_portable_shell", False):
        return
    add_btn = getattr(app, "btn_portable_add_to_queue", None)
    in_btn = getattr(app, "btn_portable_in_queue", None)
    gear = getattr(app, "btn_portable_queue_gear", None)
    badge = getattr(app, "label_playback_badge", None)
    if add_btn is None and in_btn is None:
        return

    if gear is not None:
        try:
            gear.hide()
        except RuntimeError:
            pass

    # Sticky export path still resolves after Close — only a live preview counts.
    idle = False
    if hasattr(app, "_is_player_idle_placeholder"):
        try:
            idle = bool(app._is_player_idle_placeholder())
        except Exception:
            idle = False
    preview = getattr(app, "_preview_clip_path", None)
    path = None
    if not idle and preview and hasattr(app, "_is_export_clip_path"):
        try:
            if app._is_export_clip_path(preview):
                path = os.path.normpath(preview)
        except Exception:
            path = None
    elif not idle and preview:
        path = os.path.normpath(str(preview))

    job = None
    if path and hasattr(app, "_queue_job_for_clip"):
        try:
            job = app._queue_job_for_clip(path)
        except Exception:
            job = None

    rendering = bool(getattr(app, "_is_rendering", False))
    has_clip = bool(path)
    can_add = has_clip and not rendering

    pending = 0
    if hasattr(app, "render_queue"):
        try:
            pending = int(app.render_queue.pending_count())
        except Exception:
            pending = 0

    from steempeg.render.queue import JobStatus

    show_add = False
    show_queue_chip = False
    queue_chip_text = "Queue"
    if has_clip and job is not None:
        st = job.status
        if st == JobStatus.QUEUED:
            show_queue_chip = True
            queue_chip_text = f"In queue ({job.queue_index})"
        elif st == JobStatus.RENDERING:
            show_queue_chip = True
            queue_chip_text = "Rendering"
        elif st in (JobStatus.COMPLETED, JobStatus.ERROR):
            # Status label handles these; no add/queue chip needed.
            show_add = False
            show_queue_chip = False
        else:
            show_add = can_add
    elif has_clip:
        # Clip open, not queued → add CTA.
        show_add = can_add
    else:
        # Idle player: only show Queue when there is something in it.
        if pending > 0:
            show_queue_chip = True
            queue_chip_text = f"Queue ({pending})"
        else:
            show_queue_chip = False

    if add_btn is not None:
        if show_add:
            add_btn.setEnabled(can_add)
            add_btn.show()
        else:
            add_btn.hide()

    if in_btn is not None:
        if show_queue_chip:
            _style_in_queue_button(in_btn, queue_chip_text)
            in_btn.show()
            if badge is not None and (
                show_add
                or badge.text().strip().lower().startswith("in queue")
                or badge.text().strip().lower() == "preview"
            ):
                badge.hide()
        else:
            in_btn.hide()

    # Preview chip is replaced by + Queue / Queue.
    if (
        badge is not None
        and (show_add or show_queue_chip)
        and badge.isVisible()
        and badge.text().strip().lower() == "preview"
    ):
        badge.hide()


def _ensure_library_scan_badge(app, lay: QHBoxLayout) -> None:
    """Ring sits immediately after Choose a Clip (same header row)."""
    badge = getattr(app, "portable_library_scan_badge", None)
    if badge is not None:
        try:
            badge.objectName()
        except RuntimeError:
            app.portable_library_scan_badge = None
            badge = None
    if badge is not None:
        return

    badge = _LibraryScanRing()
    app.portable_library_scan_badge = badge
    btn = getattr(app, "btn_portable_add_clip", None)
    idx = lay.indexOf(btn) if btn is not None else -1
    if idx >= 0:
        lay.insertWidget(idx + 1, badge)
    else:
        lay.addWidget(badge)


def _style_portable_render_button(btn: QPushButton, *, pending: int = 0, has_clip: bool = False) -> None:
    """Pill like Trim; flag emoji for now. Queue label only when a clip is open."""
    btn.setIcon(QIcon())
    if pending > 0 and has_clip:
        btn.setText(f"🚩 Queue ({pending})")
    else:
        btn.setText("🚩 Render")
    btn.setStyleSheet(_RENDER_STYLE)
    btn.setFixedHeight(30)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip("Render settings and progress")


def _ensure_render_button(app) -> None:
    if getattr(app, "btn_portable_render", None) is not None:
        # Rebind click to open the combined sheet (upgrade older instant-start wiring).
        try:
            app.btn_portable_render.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        app.btn_portable_render.clicked.connect(lambda: open_portable_render_settings(app))
        pending = app.render_queue.pending_count() if hasattr(app, "render_queue") else 0
        has_clip = False
        resolve = getattr(app, "_resolve_export_clip_path", None)
        if callable(resolve):
            try:
                has_clip = bool(resolve())
            except Exception:
                has_clip = False
        _style_portable_render_button(
            app.btn_portable_render, pending=pending, has_clip=has_clip
        )
        trim = getattr(app, "btn_trim", None)
        if trim is not None:
            app.btn_portable_render.setFont(trim.font())
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

    btn_render = QPushButton()
    btn_render.setObjectName("portableRender")
    _style_portable_render_button(btn_render, pending=0, has_clip=False)
    if trim is not None:
        btn_render.setFont(trim.font())
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
            _apply_portable_shell_density(app)
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


def open_portable_clip_picker(app, *, host_parent=None) -> None:
    if getattr(app, "_portable_clip_picker_open", False):
        return
    # Allow opening during scan so the user sees the grayed/locked library;
    # selection stays gated by _clips_library_accepts_selection / setEnabled(False).
    if hasattr(app, "hide_floating_overlays"):
        app.hide_floating_overlays()

    # Nest under an open Render sheet when caller didn't pass a parent.
    if host_parent is None and getattr(app, "_portable_render_settings_open", False):
        host_parent = getattr(app, "_portable_render_sheet_dlg", None)

    nested = host_parent is not None
    app._portable_clip_picker_open = True
    try:
        # Toolbar / tabs / combos live in left_panel — refresh density for the
        # current shell width before the sheet borrows that chrome.
        # Skip when nested: Render already owns neo/settings density.
        if not nested:
            _apply_portable_shell_density(app)

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
        if hasattr(app, "_sync_library_scan_interaction_lock"):
            app._sync_library_scan_interaction_lock(
                busy=bool(getattr(app, "_clips_scan_active", False))
            )
        dlg.exec()
    except Exception:
        _log.exception("Open Clips Manager failed")
    finally:
        app._portable_clip_picker_open = False
        # After nested exec, park back under the garage (not the Render sheet).
        dlg = getattr(app, "_portable_clip_picker_dlg", None)
        if dlg is not None and nested:
            try:
                from PySide6.QtCore import Qt

                if dlg.windowFlags() & Qt.WindowType.Dialog:
                    dlg._park_hidden_dialog()
                else:
                    garage = _ensure_sheet_garage(app)
                    dlg._park_as_embedded_widget(garage)
            except Exception:
                _log.exception("Re-park Choose a Clip after nested open failed")
            if host_parent is not None and hasattr(host_parent, "reset_title_bar_chrome"):
                try:
                    host_parent.reset_title_bar_chrome()
                    host_parent.raise_()
                    host_parent.activateWindow()
                except Exception:
                    _log.exception("Refresh Render sheet after nested Choose a Clip failed")
        if hasattr(app, "_sync_library_scan_interaction_lock"):
            app._sync_library_scan_interaction_lock(
                busy=bool(getattr(app, "_clips_scan_active", False))
            )


def _apply_portable_shell_density(app) -> None:
    """Portable keeps comfort chrome; Linux compact sheets may narrow settings.

    Windows portable keeps the comfort settings column the user tuned there.
    On Linux, Source/Export use a hard content-width clamp — without a mild
    densify they stay at 646px on narrow sheets while Video/Audio still fit.
    """
    ui = getattr(app, "ui", None)
    if ui is None:
        return
    import sys

    from steempeg.ui.render_panel import apply_settings_panel_density
    from steempeg.ui.ui_density import COMFORT, lerp_density

    app._ui_density = COMFORT
    if hasattr(app, "_apply_ui_density"):
        try:
            app._apply_ui_density(COMFORT)
        except Exception:
            _log.exception("Portable comfort density apply failed")

    # Windows: leave settings at comfort (user's layout). Linux compact only.
    if sys.platform != "win32" and portable_render_sheet_compact(ui, app=app):
        settings_dense = lerp_density(0.55)
    else:
        settings_dense = COMFORT
    apply_settings_panel_density(ui, settings_dense)


def _dispose_portable_render_sheet(app) -> None:
    """Tear down a warm Render sheet so it can be rebuilt for a new compact mode."""
    dlg = getattr(app, "_portable_render_sheet_dlg", None)
    if dlg is None:
        return
    try:
        if hasattr(dlg, "dispose_warm"):
            dlg.dispose_warm()
        else:
            dlg.close()
            dlg.deleteLater()
    except RuntimeError:
        pass
    except Exception:
        _log.exception("Dispose portable Render sheet failed")
    app._portable_render_sheet_dlg = None
    if hasattr(app, "_portable_sheet_compact"):
        try:
            delattr(app, "_portable_sheet_compact")
        except Exception:
            pass


def open_portable_render_settings(app) -> None:
    if getattr(app, "_portable_render_settings_open", False):
        return
    if hasattr(app, "hide_floating_overlays"):
        app.hide_floating_overlays()
    app._portable_render_settings_open = True
    try:
        _apply_portable_shell_density(app)

        want_compact = portable_render_sheet_compact(getattr(app, "ui", None), app=app)

        dlg = getattr(app, "_portable_render_sheet_dlg", None)
        try:
            if dlg is not None:
                dlg.objectName()
        except RuntimeError:
            dlg = None
            app._portable_render_sheet_dlg = None

        # Prewarm may have baked spacious chrome while the shell was fake-maximized
        # (common on Linux). Rebuild when the live shell crossed the 1600px cliff.
        if dlg is not None:
            have = getattr(dlg, "_sheet_compact", getattr(app, "_portable_sheet_compact", None))
            if have is None or bool(have) != bool(want_compact):
                _log.info(
                    "Portable Render sheet compact %s → %s; rebuilding",
                    have,
                    want_compact,
                )
                _dispose_portable_render_sheet(app)
                dlg = None

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
    idle = False
    if hasattr(app, "_is_player_idle_placeholder"):
        try:
            idle = bool(app._is_player_idle_placeholder())
        except Exception:
            idle = False
    preview = getattr(app, "_preview_clip_path", None)
    has_clip = bool(preview) and not idle
    if has_clip and hasattr(app, "_is_export_clip_path"):
        try:
            has_clip = bool(app._is_export_clip_path(preview))
        except Exception:
            has_clip = False
    _style_portable_render_button(btn, pending=pending, has_clip=has_clip)
    trim = getattr(app, "btn_trim", None)
    if trim is not None:
        btn.setFont(trim.font())

    # Keep the theatre CTA clickable so the user can open the sheet even mid-render
    # (to watch progress / Pause / Cancel). Always enabled in portable shell.
    btn.setEnabled(True)

    strip = getattr(app, "_portable_render_strip", None)
    if strip is not None and hasattr(strip, "sync_from_app"):
        strip.sync_from_app()
