"""Hide crooked chrome until density / splitters / footer stabilize after show.

Maximized geometry often differs from the pre-show work-area size, so the first
visible frames used to thrash Ready badge + footer + splitters for a few seconds.
An opaque shell-colored veil covers that churn; a timeout always reveals.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

# Failsafe — never leave the shell covered forever.
STARTUP_SETTLE_TIMEOUT_MS = 4000
# After maximize: density defer + dock settle tick + Skip screenshot restore (300ms).
STARTUP_SETTLE_REVEAL_MS = 420
# Quick/Full: no opaque veil — only a short post-show settle pass (Skip thrash
# is the crooked-chrome path; Quick/Full flash of "Preparing workspace…" felt
# unnecessary).
STARTUP_SETTLE_REVEAL_MS_NO_VEIL = 80


class _StartupVeilResizeFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            host = getattr(self, "_app", None)
            if host is not None and hasattr(host, "_sync_startup_settle_veil_geometry"):
                host._sync_startup_settle_veil_geometry()
        return False


def begin_startup_settle(app, *, use_veil: bool = True) -> None:
    """Install the opaque veil before the first ShowWindow / showMaximized.

    ``use_veil=False`` still runs the settle pass / density defer (Quick/Full),
    but skips the «Preparing workspace…» cover so those modes do not flash it.
    Skip keeps the veil — that is where post-show chrome thrash is worst.
    """
    if getattr(app, "_startup_settle_done", False):
        return
    app._startup_settle_active = True
    app._startup_settle_use_veil = bool(use_veil)
    app._startup_settle_gen = int(getattr(app, "_startup_settle_gen", 0) or 0) + 1
    gen = app._startup_settle_gen
    if use_veil:
        _ensure_startup_settle_veil(app)
        _sync_startup_settle_veil_geometry(app)
        veil = getattr(app, "_startup_settle_veil", None)
        if veil is not None:
            veil.show()
            veil.raise_()
    # Density must apply under the veil ASAP after maximize (not 120ms later).
    app._density_resize_defer_ms = 0
    QTimer.singleShot(
        STARTUP_SETTLE_TIMEOUT_MS,
        lambda g=gen: _finish_startup_settle(app, g, reason="timeout"),
    )


def kick_startup_settle_after_show(app) -> None:
    """One coherent post-maximize pass, then reveal once chrome stops thrashing."""
    if not getattr(app, "_startup_settle_active", False):
        return
    _run_startup_settle_pass(app)
    gen = int(getattr(app, "_startup_settle_gen", 0) or 0)
    reveal_ms = (
        STARTUP_SETTLE_REVEAL_MS
        if getattr(app, "_startup_settle_use_veil", True)
        else STARTUP_SETTLE_REVEAL_MS_NO_VEIL
    )
    QTimer.singleShot(
        reveal_ms,
        lambda g=gen: _finish_startup_settle(app, g, reason="settle"),
    )


def _finish_startup_settle(app, gen: int, *, reason: str = "settle") -> None:
    if int(getattr(app, "_startup_settle_gen", 0) or 0) != gen:
        return
    if not getattr(app, "_startup_settle_active", False):
        return
    # Second pass after maximize geometry + deferred density / dock settle.
    _run_startup_settle_pass(app)
    # Flush any pending density timer immediately before uncovering.
    timer = getattr(app, "_density_resize_timer", None)
    if timer is not None and timer.isActive():
        timer.stop()
        if hasattr(app, "_flush_ui_density_after_resize"):
            app._flush_ui_density_after_resize()
    if hasattr(app, "_restore_library_ui_state"):
        try:
            app._restore_library_ui_state()
        except Exception:
            logging.debug("startup settle: library UI restore failed", exc_info=True)
    _reveal_startup_settle_if(app, gen, reason=reason)


def _reveal_startup_settle_if(app, gen: int, *, reason: str) -> None:
    if int(getattr(app, "_startup_settle_gen", 0) or 0) != gen:
        return
    if getattr(app, "_startup_settle_done", False):
        return
    app._startup_settle_done = True
    app._startup_settle_active = False
    app._density_resize_defer_ms = 120
    veil = getattr(app, "_startup_settle_veil", None)
    if veil is not None:
        try:
            veil.hide()
            veil.deleteLater()
        except RuntimeError:
            pass
        app._startup_settle_veil = None
    filt = getattr(app, "_startup_settle_resize_filter", None)
    if filt is not None and getattr(app, "ui", None) is not None:
        try:
            app.ui.removeEventFilter(filt)
        except RuntimeError:
            pass
        app._startup_settle_resize_filter = None
    logging.info("Startup settle veil revealed (%s)", reason)
    try:
        app.ui.update()
    except Exception:
        pass


def _run_startup_settle_pass(app) -> None:
    """Re-assert splitters / density mins / queue / footer without thrashing timers."""
    try:
        if hasattr(app, "_apply_startup_splitter_sizes"):
            app._apply_startup_splitter_sizes()
        if hasattr(app, "apply_desktop_render_layout"):
            app.apply_desktop_render_layout()
        if hasattr(app, "_ensure_startup_queue_open"):
            app._ensure_startup_queue_open()
        if hasattr(app, "_refresh_player_footer_chrome"):
            app._refresh_player_footer_chrome()
        # Keep Ready / queue badge painted for the real density.
        if hasattr(app, "update_status_indicator"):
            label = getattr(getattr(app, "ui", None), "label_status", None)
            text = label.text() if label is not None else "Ready"
            if not str(text or "").strip():
                text = "Ready"
            # Only re-stamp idle Ready — don't interrupt busy/scan chrome.
            busy = (
                getattr(app, "_clips_scan_active", False)
                or getattr(app, "_rendered_scan_active", False)
                or getattr(app, "_update_check_busy", False)
                or getattr(app, "_is_rendering", False)
            )
            if not busy and "Ready" in str(text):
                app.update_status_indicator(str(text), "ready")
    except Exception:
        logging.debug("startup settle pass failed", exc_info=True)
    veil = getattr(app, "_startup_settle_veil", None)
    if veil is not None:
        try:
            _sync_startup_settle_veil_geometry(app)
            veil.raise_()
        except RuntimeError:
            pass


def _ensure_startup_settle_veil(app) -> None:
    ui = getattr(app, "ui", None)
    if ui is None:
        return
    veil = getattr(app, "_startup_settle_veil", None)
    if veil is not None:
        return

    parent = getattr(ui, "_custom_chrome_shell", None) or ui
    bg = "#1e1e1e"
    if hasattr(app, "_current_app_bg"):
        try:
            bg = app._current_app_bg() or bg
        except Exception:
            pass

    veil = QWidget(parent)
    veil.setObjectName("startupSettleVeil")
    veil.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    veil.setStyleSheet(
        f"QWidget#startupSettleVeil {{ background-color: {bg}; }}"
        f"QLabel {{ background: transparent; color: #cccccc; }}"
    )
    lay = QVBoxLayout(veil)
    lay.setContentsMargins(24, 24, 24, 24)
    lay.setSpacing(14)
    lay.addStretch(1)

    logo = QLabel(veil)
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    try:
        from steempeg.infra.paths import get_resource_path

        pix = QPixmap(get_resource_path("logo.png"))
        if not pix.isNull():
            logo.setPixmap(
                pix.scaled(
                    72,
                    72,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
    except Exception:
        pass
    lay.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)

    title = QLabel("Steempeg", veil)
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title.setStyleSheet(
        "font-size: 22px; font-weight: 600; color: #e8e8e8;"
        "font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif;"
    )
    lay.addWidget(title)

    hint = QLabel("Preparing workspace…", veil)
    hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hint.setStyleSheet(
        "font-size: 13px; color: #858585;"
        "font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif;"
    )
    lay.addWidget(hint)
    lay.addStretch(1)

    app._startup_settle_veil = veil
    # Keep the veil edge-to-edge across maximize / FRAMECHANGED.
    filt = _StartupVeilResizeFilter(ui)
    filt._app = app
    ui.installEventFilter(filt)
    app._startup_settle_resize_filter = filt
    app._sync_startup_settle_veil_geometry = lambda: _sync_startup_settle_veil_geometry(app)


def _sync_startup_settle_veil_geometry(app) -> None:
    veil = getattr(app, "_startup_settle_veil", None)
    if veil is None:
        return
    parent = veil.parentWidget()
    if parent is None:
        return
    try:
        veil.setGeometry(parent.rect())
        veil.raise_()
    except RuntimeError:
        pass
