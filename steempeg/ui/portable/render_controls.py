"""Compact portable render control strip — progress + Start / Pause / Cancel / Logs."""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from steempeg.ui.widgets.animated_render_bar import AnimatedRenderBar

_FONT = "font-family: 'Segoe UI', 'Noto Sans', 'Twemoji', 'Noto Emoji', Arial, sans-serif;"

_STRIP_FRAME = """
QFrame#portableRenderStrip {
    background-color: #252525;
    border: 1px solid #353535;
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

        # Row 1: game (compact) | status dot + label
        top = QHBoxLayout()
        top.setSpacing(6)

        self.game_icon = QLabel()
        self.game_icon.setFixedSize(18, 18)
        self.game_icon.setStyleSheet("background: transparent; border: none;")
        top.addWidget(self.game_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self.game_label = QLabel("Select a clip…")
        self.game_label.setStyleSheet(
            f"color: #c8c8c8; font-size: 11px; font-weight: bold; {_FONT}"
        )
        self.game_label.setMinimumWidth(0)
        self.game_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        top.addWidget(self.game_label, 1)

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(_DOT_SIZE, _DOT_SIZE)
        self._set_dot_color(_STATUS_COLORS["ready"])
        top.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            f"color: {_STATUS_COLORS['ready']}; font-size: 12px; font-weight: bold; {_FONT}"
        )
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        top.addWidget(self.status_label, 0)
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

        for btn in (self.btn_start, self.btn_pause, self.btn_cancel, self.btn_logs):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn_row.addWidget(btn)

        root.addLayout(btn_row)
        self.sync_game_header()
        self.sync_from_app()

    def sync_game_header(self) -> None:
        """Compact game icon + name from the desktop summary / player header."""
        app = self._app
        icon_css = ""
        name = ""

        bottom_text = getattr(app, "bottom_text_label", None)
        bottom_icon = getattr(app, "bottom_icon_label", None)
        if bottom_text is not None:
            raw = (bottom_text.text() or "").strip()
            if raw and not raw.lower().startswith("select a clip"):
                name = raw.split("  •  ")[0].strip() or raw
        if bottom_icon is not None:
            icon_css = bottom_icon.styleSheet() or ""

        if not name:
            custom_text = getattr(app, "custom_text_label", None)
            if custom_text is not None:
                # May contain HTML: <b>Game</b> …
                import re

                plain = re.sub(r"<[^>]+>", "", custom_text.text() or "")
                plain = plain.replace("\xa0", " ").strip()
                if plain and "select a clip" not in plain.lower():
                    name = plain.split("•")[0].strip()
            custom_icon = getattr(app, "custom_icon_label", None)
            if custom_icon is not None and not icon_css:
                icon_css = custom_icon.styleSheet() or ""

        if not name:
            name = "Select a clip…"
            from steempeg.infra.paths import get_resource_path

            unknown = get_resource_path("unknown_icon.png").replace("\\", "/")
            self.game_icon.setStyleSheet(
                f"image: url('{unknown}'); background: transparent; border: none;"
            )
            self.game_label.setText(name)
            self.game_label.setToolTip(name)
            return

        self.game_label.setText(name)
        self.game_label.setToolTip(name)
        if "image: url(" in icon_css:
            # Keep pixmap size small via label fixed size; reuse CSS image.
            self.game_icon.setStyleSheet(icon_css)
        else:
            from steempeg.infra.paths import get_resource_path

            unknown = get_resource_path("unknown_icon.png").replace("\\", "/")
            self.game_icon.setStyleSheet(
                f"image: url('{unknown}'); background: transparent; border: none;"
            )

    def _set_dot_color(self, color: str) -> None:
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
            f"color: {color}; font-size: 13px; font-weight: bold; {_FONT}"
        )
        self.status_label.setToolTip(display)
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
            self.btn_start.setEnabled(start_on or has_clip or pending > 0)
            self.btn_pause.setEnabled(False)
            self.btn_cancel.setEnabled(False)
            self.btn_pause.setText("Pause")
            if pending > 0:
                self.btn_start.setText(f"🚩 Start ({pending})")
            else:
                self.btn_start.setText("🚩 Start")

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
