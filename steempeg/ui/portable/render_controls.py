"""Compact portable render control strip — progress + Start / Pause / Cancel / Logs."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.infra.paths import get_resource_path
from steempeg.ui.widgets.animated_render_bar import AnimatedRenderBar

_FONT = "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"

_STRIP_FRAME = """
QFrame#portableRenderStrip {
    background-color: #2d2d2d;
    border: 1px solid #383838;
    border-radius: 10px;
}
QFrame#portableRenderStrip QLabel {
    background: transparent;
    border: none;
}
"""

# Same templates as desktop render dashboard (app.py), compact padding.
_DASH_START = (
    "QPushButton {{ font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; "
    "font-size: {font}px; font-weight: bold; background-color: #2e6b32; color: #ffffff; "
    "border: 2px solid #3e8e41; border-radius: {radius}px; padding: {pad}; }}"
    "QPushButton:hover {{ background-color: #3e8e41; border: 2px solid #57c75b; }}"
    "QPushButton:pressed {{ background-color: #235226; border: 2px solid #3e8e41; }}"
    "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
)
_DASH_PAUSE = (
    "QPushButton {{ font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; "
    "font-size: {font}px; font-weight: bold; background-color: #8c7314; color: #ffffff; "
    "border: 2px solid #a88b11; border-radius: {radius}px; padding: {pad}; }}"
    "QPushButton:hover {{ background-color: #a88b11; border: 2px solid #c9a716; }}"
    "QPushButton:pressed {{ background-color: #6b570d; border: 2px solid #a88b11; }}"
    "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
)
_DASH_CANCEL = (
    "QPushButton {{ font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; "
    "font-size: {font}px; font-weight: bold; background-color: #8a2525; color: #ffffff; "
    "border: 2px solid #a82e2e; border-radius: {radius}px; padding: {pad}; }}"
    "QPushButton:hover {{ background-color: #a82e2e; border: 2px solid #cc3939; }}"
    "QPushButton:pressed {{ background-color: #661a1a; border: 2px solid #a82e2e; }}"
    "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
)
_DASH_LEAVE = (
    "QPushButton {{ font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; "
    "font-size: {font}px; font-weight: bold; background-color: #383838; color: #e0e0e0; "
    "border: 2px solid #4a4a4a; border-radius: {radius}px; padding: {pad}; }}"
    "QPushButton:hover {{ background-color: #404040; color: #ffffff; border: 2px solid #6b5a8e; }}"
    "QPushButton:pressed {{ background-color: #3a324a; border: 2px solid #b29ae7; }}"
    "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
)
_DASH_RESUME = (
    "QPushButton {{ font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; "
    "font-size: {font}px; font-weight: bold; background-color: #5a4b7a; color: #ffffff; "
    "border: 2px solid #8e7cc3; border-radius: {radius}px; padding: {pad}; }}"
    "QPushButton:hover {{ background-color: #6b5a8e; border: 2px solid #b29ae7; }}"
    "QPushButton:pressed {{ background-color: #3a324a; border: 2px solid #b29ae7; }}"
    "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
)
_DASH_LOGS = (
    "QPushButton {{ font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji'; "
    "font-size: {font}px; font-weight: bold; background-color: #383838; color: #ffffff; "
    "border: 2px solid #444444; border-radius: {radius}px; padding: {pad}; }}"
    "QPushButton:hover {{ background-color: #404040; border: 2px solid #6b5a8e; }}"
    "QPushButton:pressed {{ background-color: #3a324a; border: 2px solid #b29ae7; }}"
    "QPushButton:disabled {{ background-color: #222222; color: #555555; border: 2px solid #2d2d2d; }}"
    "QPushButton::menu-indicator {{ image: none; }}"
)

_STATUS_COLORS = {
    "ready": "#4CAF50",
    "rendering": "#a871ff",
    "busy": "#a871ff",
    "paused": "#ffcc00",
    "error": "#ff4444",
    "success": "#4CAF50",
    "cancelling": "#ff4444",
    "cancelled": "#ff4444",
}

_DOT_SIZE = 12
_PCT_COL = 40
_STATUS_ROW_H = 24
_GAME_ICON = 24


def _fmt_dash(template: str, *, font: int = 13, radius: int = 8, pad: str = "6px 12px") -> str:
    return template.format(font=font, radius=radius, pad=pad)


class PortableRenderControlStrip(QFrame):
    """Laconic footer for the portable Render sheet (desktop bar + status dot)."""

    def __init__(self, app, parent: QWidget | None = None):
        super().__init__(parent)
        self._app = app
        self._state = "ready"
        self.setObjectName("portableRenderStrip")
        self.setStyleSheet(_STRIP_FRAME)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # Row 1: game summary (desktop sizing) | Ready text + dot above %
        top = QHBoxLayout()
        top.setSpacing(4)

        summary_left = QWidget()
        summary_left.setMinimumWidth(0)
        summary_left.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        summary_layout = QHBoxLayout(summary_left)
        summary_layout.setContentsMargins(0, 0, 0, 2)
        summary_layout.setSpacing(8)

        self.game_icon = QLabel()
        self.game_icon.setFixedSize(_GAME_ICON, _GAME_ICON)
        self.game_icon.setStyleSheet("background: transparent; border: none;")
        summary_layout.addWidget(self.game_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self.game_label = QLabel("Select a clip…")
        self.game_label.setStyleSheet(
            f"color: #e0e0e0; font-size: 14px; font-weight: bold; {_FONT}"
        )
        self.game_label.setMinimumWidth(0)
        self.game_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        summary_layout.addWidget(self.game_label, 1, Qt.AlignmentFlag.AlignVCenter)

        top.addWidget(summary_left, 1, Qt.AlignmentFlag.AlignVCenter)

        ready_cluster = QWidget()
        ready_cluster.setFixedHeight(_STATUS_ROW_H)
        ready_layout = QHBoxLayout(ready_cluster)
        ready_layout.setContentsMargins(0, 0, 0, 0)
        ready_layout.setSpacing(4)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            f"color: {_STATUS_COLORS['ready']}; font-size: 14px; font-weight: bold; {_FONT}"
        )
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.status_label.setMinimumWidth(120)
        self.status_label.setMaximumWidth(280)
        ready_layout.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignVCenter)

        dot_col = QWidget()
        dot_col.setFixedSize(_PCT_COL, _STATUS_ROW_H)
        dot_col_layout = QHBoxLayout(dot_col)
        dot_col_layout.setContentsMargins(0, 0, 0, 0)
        dot_col_layout.setSpacing(0)
        dot_col_layout.addStretch()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(_DOT_SIZE, _DOT_SIZE)
        self.status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_dot_color(_STATUS_COLORS["ready"])
        dot_col_layout.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignCenter)
        dot_col_layout.addStretch()
        ready_layout.addWidget(dot_col, 0, Qt.AlignmentFlag.AlignVCenter)

        top.addWidget(ready_cluster, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top)

        # Row 2: smooth AnimatedRenderBar + %
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)

        self.progress = AnimatedRenderBar(self)
        progress_row.addWidget(self.progress, 1)

        self.pct_label = QLabel("0%")
        self.pct_label.setFixedWidth(_PCT_COL)
        self.pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pct_label.setStyleSheet(
            f"color: #ffffff; font-size: 13px; font-weight: bold; {_FONT}"
        )
        progress_row.addWidget(self.pct_label, 0)
        root.addLayout(progress_row)

        # Row 3: desktop-styled actions
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_start = QPushButton("🚩 Start")
        self.btn_start.setStyleSheet(_fmt_dash(_DASH_START))
        self.btn_start.clicked.connect(self._on_start)

        # Leave / Resume — sits beside Start / Start Queue (N); purple while deferred.
        self.btn_leave = QPushButton(" Leave")
        self.btn_leave.setObjectName("portableQueueLeaveResume")
        self.btn_leave.setStyleSheet(_fmt_dash(_DASH_LEAVE))
        self.btn_leave.setToolTip(
            "Leave queue mode — keep all jobs. Preview or render something else, then Resume."
        )
        leave_icon = get_resource_path("exit.png")
        if leave_icon and os.path.isfile(leave_icon):
            self.btn_leave.setIcon(QIcon(leave_icon))
            self.btn_leave.setIconSize(QSize(16, 16))
        self.btn_leave.clicked.connect(self._on_leave_resume)
        self.btn_leave.hide()
        # Alias for older sync helpers that still look for btn_resume.
        self.btn_resume = self.btn_leave

        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setStyleSheet(_fmt_dash(_DASH_PAUSE))
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._on_pause)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(_fmt_dash(_DASH_CANCEL))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)

        self.btn_logs = QPushButton("Logs")
        self.btn_logs.setStyleSheet(_fmt_dash(_DASH_LOGS))
        self.btn_logs.clicked.connect(self._on_logs)

        for btn in (
            self.btn_start,
            self.btn_leave,
            self.btn_pause,
            self.btn_cancel,
            self.btn_logs,
        ):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn_row.addWidget(btn)

        root.addLayout(btn_row)
        self.sync_game_header()
        self.sync_from_app()

    def sync_game_header(self) -> None:
        """Compact game icon + name — queue-first when Render Queue has jobs."""
        app = self._app
        name = ""
        icon_path = ""

        # Prefer the status-strip / queue-context job when queue identity chrome
        # is on (not a library preview diversion or Left).
        job = None
        owns = True
        if hasattr(app, "_queue_owns_identity_chrome"):
            owns = bool(app._queue_owns_identity_chrome())
        elif hasattr(app, "_queue_is_active"):
            owns = bool(app._queue_is_active())
        if owns:
            if hasattr(app, "_status_strip_context_job"):
                job = app._status_strip_context_job()
            elif hasattr(app, "_queue_context_job"):
                job = app._queue_context_job()
        if job is not None:
            name = (getattr(job, "game_name", "") or "").strip()
            from steempeg.render.queue import resolve_job_game_icon_path

            cache_dir = getattr(app, "cache_dir", "") or ""
            icon_path = resolve_job_game_icon_path(cache_dir, job)

        if not name:
            bottom_text = getattr(app, "bottom_text_label", None)
            if bottom_text is not None:
                raw = (bottom_text.text() or "").strip()
                if raw and not raw.lower().startswith("select a clip"):
                    name = raw.split("  •  ")[0].strip() or raw

        if not name:
            custom_text = getattr(app, "custom_text_label", None)
            if custom_text is not None:
                from steempeg.ui.player_header_layout import plain_header_title

                title = plain_header_title(custom_text.text() or "")
                if title and "select a clip" not in title.lower():
                    name = title

        from PySide6.QtGui import QPixmap

        from steempeg.infra.paths import get_resource_path
        from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap
        from steempeg.ui.icon_utils import apply_square_icon

        def _set_unknown_icon() -> None:
            unknown = get_resource_path("unknown_icon.png")
            self.game_icon.setStyleSheet("background: transparent; border: none;")
            apply_square_icon(
                self.game_icon,
                shaped_game_icon_pixmap(QPixmap(unknown), _GAME_ICON, ICON_SHAPE_CIRCLE),
                _GAME_ICON,
            )

        if not name:
            name = "Select a clip…"
            _set_unknown_icon()
            self.game_label.setText(name)
            self.game_label.setToolTip(name)
            return

        self.game_label.setText(name)
        self.game_label.setToolTip(name)
        if icon_path:
            try:
                if os.path.isfile(icon_path):
                    self.game_icon.setStyleSheet("background: transparent; border: none;")
                    apply_square_icon(
                        self.game_icon,
                        shaped_game_icon_pixmap(QPixmap(icon_path), _GAME_ICON, None),
                        _GAME_ICON,
                    )
                    return
            except OSError:
                pass
        # Prefer live header/bottom pixmaps (square-safe). Never use CSS ``image:``.
        for attr in ("custom_icon_label", "bottom_icon_label"):
            src_lbl = getattr(app, attr, None)
            header_pm = src_lbl.pixmap() if src_lbl is not None else None
            if header_pm is not None and not header_pm.isNull():
                self.game_icon.setStyleSheet("background: transparent; border: none;")
                apply_square_icon(self.game_icon, header_pm, _GAME_ICON)
                return
        _set_unknown_icon()

    def _set_dot_color(self, color: str) -> None:
        self.status_dot.setFixedSize(_DOT_SIZE, _DOT_SIZE)
        self.status_dot.setText("")
        try:
            self.status_dot.setPixmap(QPixmap())
        except Exception:
            pass
        r = max(3, _DOT_SIZE // 2)
        self.status_dot.setStyleSheet(
            f"background-color: {color}; border-radius: {r}px;"
        )

    def apply_status(self, text: str, state: str = "ready", percent: float | None = None) -> None:
        state = state or "ready"
        self._state = state
        color = _STATUS_COLORS.get(state, "#a871ff")
        display = (text or "Ready").strip() or "Ready"
        self.status_label.setText(display)
        self.status_label.setStyleSheet(
            f"color: {color}; font-size: 14px; font-weight: bold; {_FONT}"
        )
        self.status_label.setToolTip(display)
        # Update-check owns spinning arrows; library scan owns the wave dots.
        # Queue-first Ready uses the numbered badge — don't flatten to a plain dot.
        app = self._app
        if getattr(app, "_update_check_busy", False):
            if hasattr(app, "_paint_status_dot_update_spin"):
                app._paint_status_dot_update_spin(color)
        elif (
            getattr(app, "_clips_scan_active", False)
            or getattr(app, "_rendered_scan_active", False)
        ) and hasattr(app, "_paint_status_dot_loading_wave"):
            app._paint_status_dot_loading_wave(color)
        elif (
            state in ("ready", "success")
            and not getattr(app, "_is_rendering", False)
            and hasattr(app, "_sync_dash_queue_status_chrome")
            and app._sync_dash_queue_status_chrome()
        ):
            pass  # badge + labels already applied
        else:
            # Keep numbered queue badge during render progress when queue owns the strip.
            # Rendering / Completed glyphs belong on the player-header plaque only.
            queue_index = None
            if hasattr(app, "_queue_is_active") and app._queue_is_active():
                job = (
                    app._status_strip_context_job()
                    if hasattr(app, "_status_strip_context_job")
                    else None
                )
                if job is not None:
                    queue_index = int(getattr(job, "queue_index", 0) or 0) or None
            if queue_index and hasattr(app, "_paint_status_dot_queue_badge"):
                app._paint_status_dot_queue_badge(queue_index, color)
            else:
                self._set_dot_color(color)

        if state == "success":
            percent = 100.0
        elif state in ("ready", "error") and percent is None:
            percent = 0.0

        self.progress.set_state(state)
        if percent is not None:
            pct = max(0.0, min(100.0, float(percent)))
            self.progress.set_progress(pct)
            if hasattr(self._app, "_format_pct_label"):
                self.pct_label.setText(self._app._format_pct_label(pct))
            else:
                self.pct_label.setText(f"{int(round(pct))}%" if pct < 100 else "100%")
        self.sync_game_header()
        self.sync_from_app()

    def sync_from_app(self) -> None:
        app = self._app
        rendering = bool(getattr(app, "_is_rendering", False))
        pending = 0
        if hasattr(app, "render_queue"):
            try:
                pending = int(app.render_queue.pending_count())
            except Exception:
                pending = 0

        has_clip = False
        resolve = getattr(app, "_resolve_export_clip_path", None)
        if callable(resolve):
            try:
                has_clip = bool(resolve())
            except Exception:
                has_clip = False

        start_desktop = getattr(getattr(app, "ui", None), "btn_start", None)
        start_on = bool(start_desktop is not None and start_desktop.isEnabled())
        deferred = bool(getattr(app, "_queue_scheme_deferred", False))

        if rendering:
            self.btn_start.setEnabled(False)
            self.btn_pause.setEnabled(True)
            self.btn_cancel.setEnabled(True)
            pause_desktop = getattr(getattr(app, "ui", None), "btn_pause", None)
            if pause_desktop is not None:
                self.btn_pause.setText(pause_desktop.text() or "Pause")
            else:
                self.btn_pause.setText("Pause")
        else:
            self.btn_start.setEnabled(
                start_on or has_clip or (pending > 0 and not deferred)
            )
            self.btn_pause.setEnabled(False)
            self.btn_cancel.setEnabled(False)
            self.btn_pause.setText("Pause")
            if pending > 0 and not deferred:
                self.btn_start.setText(f"🚩 Start Queue ({pending})")
            else:
                self.btn_start.setText("🚩 Start")
        has_jobs = False
        if hasattr(app, "render_queue"):
            try:
                has_jobs = len(app.render_queue) > 0
            except Exception:
                has_jobs = pending > 0
        busy = rendering or bool(getattr(app, "_queue_batch_active", False))
        self.sync_queue_leave_resume(
            deferred=deferred and has_jobs,
            has_jobs=has_jobs,
            busy=busy,
        )

    def set_queue_resume_visible(self, visible: bool) -> None:
        """Compat shim — prefer ``sync_queue_leave_resume``."""
        if not visible:
            btn = getattr(self, "btn_leave", None) or getattr(self, "btn_resume", None)
            if btn is not None:
                btn.hide()
                btn.setEnabled(False)
            return
        app = self._app
        has_jobs = False
        if hasattr(app, "render_queue"):
            try:
                has_jobs = len(app.render_queue) > 0
            except Exception:
                has_jobs = False
        deferred = bool(getattr(app, "_queue_scheme_deferred", False)) and has_jobs
        busy = bool(
            getattr(app, "_is_rendering", False)
            or getattr(app, "_queue_batch_active", False)
        )
        self.sync_queue_leave_resume(
            deferred=deferred, has_jobs=has_jobs, busy=busy
        )

    def sync_queue_leave_resume(
        self, *, deferred: bool, has_jobs: bool, busy: bool
    ) -> None:
        btn = getattr(self, "btn_leave", None) or getattr(self, "btn_resume", None)
        if btn is None:
            return
        show = bool(has_jobs)
        btn.setVisible(show)
        btn.setEnabled(show and not bool(busy))
        if not show:
            return
        if deferred:
            btn.setText(" Resume")
            btn.setToolTip("Return to queue mode with the same jobs and order")
            btn.setStyleSheet(_fmt_dash(_DASH_RESUME))
            resume_icon = get_resource_path("resume.png")
            if resume_icon and os.path.isfile(resume_icon):
                btn.setIcon(QIcon(resume_icon))
                btn.setIconSize(QSize(16, 16))
        else:
            btn.setText(" Leave")
            btn.setToolTip(
                "Leave queue mode — keep all jobs. Preview or render something else, then Resume."
            )
            btn.setStyleSheet(_fmt_dash(_DASH_LEAVE))
            leave_icon = get_resource_path("exit.png")
            if leave_icon and os.path.isfile(leave_icon):
                btn.setIcon(QIcon(leave_icon))
                btn.setIconSize(QSize(16, 16))

    def _on_leave_resume(self) -> None:
        if hasattr(self._app, "toggle_render_queue_scheme"):
            self._app.toggle_render_queue_scheme()
        self.sync_from_app()

    def _on_resume(self) -> None:
        self._on_leave_resume()

    def _on_start(self) -> None:
        from steempeg.ui.portable.sheets import persist_render_settings

        persist_render_settings(self._app)
        if hasattr(self._app, "_sync_active_queue_job_from_ui"):
            try:
                if self._app._sync_active_queue_job_from_ui():
                    if hasattr(self._app, "_persist_render_queue"):
                        self._app._persist_render_queue()
            except Exception:
                pass
        self._app.start_render_thread()
        sidebar = getattr(self._app, "_portable_queue_sidebar", None)
        if sidebar is not None and hasattr(sidebar, "refresh"):
            sidebar.refresh()
        self.sync_game_header()
        self.sync_from_app()

    def _on_pause(self) -> None:
        if hasattr(self._app, "toggle_pause"):
            self._app.toggle_pause()
        self.sync_from_app()

    def _on_cancel(self) -> None:
        if hasattr(self._app, "cancel_render"):
            self._app.cancel_render()
        self.sync_from_app()

    def _on_logs(self) -> None:
        """Reuse the desktop Logs menu when present."""
        desktop = getattr(getattr(self._app, "ui", None), "btn_logs", None)
        menu = desktop.menu() if desktop is not None else None
        if menu is not None:
            menu.exec(self.btn_logs.mapToGlobal(QPoint(0, self.btn_logs.height())))
            return
        if hasattr(self._app, "open_current_log"):
            self._app.open_current_log()
