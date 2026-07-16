"""Steempeg-styled countdown while waiting for the GitHub API rate limit to reset."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel

from steempeg.services.release_catalog import RateLimitInfo
from steempeg.ui import design_tokens as tok
from steempeg.ui.widgets.animated_render_bar import AnimatedRenderBar
from steempeg.ui.widgets.dialog_chrome import SteempegDialog


def _format_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    minutes, secs = divmod(seconds, 60)
    if minutes:
        return f"{minutes} min {secs:02d} sec"
    return f"{secs} sec"


class GitHubRateLimitDialog(SteempegDialog):
    def __init__(
        self,
        rate_limit: RateLimitInfo,
        parent=None,
        *,
        bar_color: str | None = None,
        bg_color: str | None = None,
    ):
        super().__init__("GitHub API limit", parent, bar_color=bar_color, bg_color=bg_color)
        self.setMinimumWidth(420)
        self.resize(460, 220)
        self._reset_at = rate_limit.reset_at
        self._started_at = int(time.time())
        self._wait_seconds = max(1, rate_limit.seconds_remaining)
        self._timer_completed = False

        root = self.content_layout

        heading = QLabel("GitHub API rate limit reached")
        heading.setStyleSheet(
            f"color: {tok.TEXT_TITLE}; font-size: 14px; font-weight: 600; background: transparent;"
        )
        root.addWidget(heading)

        body = QLabel(
            f"You used all <b>{rate_limit.limit}</b> unauthenticated GitHub API requests for this hour. "
            "Steempeg will reopen Update Center when the limit resets."
        )
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet(f"color: {tok.TEXT_PRIMARY}; font-size: 12px; background: transparent;")
        root.addWidget(body)

        self._remaining_label = QLabel()
        self._remaining_label.setStyleSheet(
            f"color: {tok.ACCENT_PRIMARY}; font-size: 13px; font-weight: 600; background: transparent;"
        )
        root.addWidget(self._remaining_label)

        self._bar = AnimatedRenderBar()
        self._bar.set_state("rendering")
        self._bar.set_progress(0.0)
        root.addWidget(self._bar)

        hint = QLabel("This window closes automatically when the API unlocks. Close to cancel.")
        hint.setStyleSheet(f"color: {tok.TEXT_MUTED}; font-size: 10px; background: transparent;")
        root.addWidget(hint)

        # Allow cancel — a stuck/wrong reset_at used to trap the user with close disabled.
        self._title_bar.btn_close.setEnabled(True)
        self.rejected.connect(self._on_dialog_rejected)

        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._on_tick()

    @property
    def timer_completed(self) -> bool:
        return self._timer_completed

    def _on_dialog_rejected(self) -> None:
        self._timer_completed = False
        self._tick.stop()

    def _on_tick(self) -> None:
        now = int(time.time())
        remaining = max(0, self._reset_at - now)
        elapsed = max(0, now - self._started_at)
        wait = max(1, self._wait_seconds)
        progress = min(100.0, (elapsed / wait) * 100.0)
        self._remaining_label.setText(f"Time until unlock: {_format_duration(remaining)}")
        self._bar.set_progress(progress)

        if remaining <= 0:
            self._timer_completed = True
            self._tick.stop()
            self._bar.set_progress(100.0)
            self._remaining_label.setText("API unlocked — reopening Update Center…")
            QTimer.singleShot(350, self.accept)
