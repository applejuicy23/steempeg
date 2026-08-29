"""Slow soft border breath for attention without harsh flashing.

Photosensitive-safe: one smooth sine cycle every few seconds (well under WCAG
flash limits). Only the outline color moves (light ↔ purple); fill, font, and
geometry stay on the stock dash button chrome.
"""
from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QPushButton

# Soft light → Steempeg accent. Visible pulse; stock fill/font/geometry stay put.
_DEFAULT_FROM = "#f2eef8"
_DEFAULT_TO = "#b29ae7"
# Full round-trip period (A→B→A). ~0.25 Hz — gentle, not a flash.
_PERIOD_MS = 4000
_TICK_MS = 40


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class SoftAccentBorderBreath(QObject):
    """Drive a QPushButton border through a slow light↔purple sine."""

    def __init__(
        self,
        button: QPushButton,
        *,
        style_builder: Callable[[str], str],
        from_color: str = _DEFAULT_FROM,
        to_color: str = _DEFAULT_TO,
        parent: QObject | None = None,
    ):
        super().__init__(parent or button)
        self._button = button
        self._style_builder = style_builder
        self._from = QColor(from_color)
        self._to = QColor(to_color)
        self._elapsed_ms = 0
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._on_tick)

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._elapsed_ms = 0
        self._apply_border(self._from)
        self._timer.start()

    def stop(self, *, restore_style: str | None = None) -> None:
        self._active = False
        self._timer.stop()
        if restore_style is not None:
            try:
                self._button.setStyleSheet(restore_style)
            except RuntimeError:
                pass
        else:
            # Land on the stock border.
            self._apply_border(self._from)

    def _on_tick(self) -> None:
        if not self._active:
            return
        try:
            if not self._button.isVisible():
                return
        except RuntimeError:
            self.stop()
            return
        self._elapsed_ms = (self._elapsed_ms + _TICK_MS) % _PERIOD_MS
        # Cosine ease: 0 → 1 → 0 with no hard corners.
        phase = (2.0 * math.pi) * (self._elapsed_ms / float(_PERIOD_MS))
        t = (1.0 - math.cos(phase)) * 0.5
        self._apply_border(_lerp_color(self._from, self._to, t))

    def _apply_border(self, color: QColor) -> None:
        try:
            self._button.setStyleSheet(self._style_builder(color.name()))
        except RuntimeError:
            self.stop()
