"""Short press-in feedback for icon buttons (player transport first).

Full animations pack (tokens, hover settle, app-wide) stays on the v44–v45 track.
This helper is the early slice: shrink the icon slightly on press, spring back.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtWidgets import QAbstractButton


def install_press_feedback(
    button: QAbstractButton,
    *,
    pressed_scale: float = 0.88,
    duration_ms: int = 80,
) -> PressFeedbackFilter:
    """Attach press feedback; safe to call once per button."""
    existing = getattr(button, "_press_feedback_filter", None)
    if isinstance(existing, PressFeedbackFilter):
        existing.sync_rest_icon_size()
        return existing
    filt = PressFeedbackFilter(
        button, pressed_scale=pressed_scale, duration_ms=duration_ms
    )
    button._press_feedback_filter = filt  # type: ignore[attr-defined]
    return filt


class PressFeedbackFilter(QObject):
    def __init__(
        self,
        button: QAbstractButton,
        *,
        pressed_scale: float = 0.88,
        duration_ms: int = 80,
    ):
        super().__init__(button)
        self._btn = button
        self._pressed_scale = float(pressed_scale)
        self._duration = max(40, int(duration_ms))
        self._rest: QSize | None = None
        self._scale = 1.0
        self._anim: QVariantAnimation | None = None
        button.installEventFilter(self)
        button.pressed.connect(self._on_pressed)
        button.released.connect(self._on_released)

    def sync_rest_icon_size(self) -> None:
        """Call after density / iconSize changes so press scales from the new rest."""
        sz = self._btn.iconSize()
        if sz.isValid() and sz.width() > 0:
            self._rest = QSize(sz)
            self._scale = 1.0

    def _ensure_rest(self) -> QSize | None:
        if self._rest is None or not self._rest.isValid():
            sz = self._btn.iconSize()
            if sz.isValid() and sz.width() > 0:
                self._rest = QSize(sz)
        return self._rest

    def _apply_scale(self, scale: float) -> None:
        rest = self._ensure_rest()
        if rest is None:
            return
        self._scale = scale
        w = max(1, int(round(rest.width() * scale)))
        h = max(1, int(round(rest.height() * scale)))
        self._btn.setIconSize(QSize(w, h))

    def _animate_to(self, target: float) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        start = float(self._scale)
        if abs(start - target) < 0.01:
            self._apply_scale(target)
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(float(target))
        anim.setDuration(self._duration)
        anim.setEasingCurve(
            QEasingCurve.Type.OutCubic
            if target >= start
            else QEasingCurve.Type.InCubic
        )
        anim.valueChanged.connect(lambda v: self._apply_scale(float(v)))
        anim.finished.connect(lambda: setattr(self, "_anim", None))
        self._anim = anim
        anim.start()

    def _on_pressed(self) -> None:
        self._animate_to(self._pressed_scale)

    def _on_released(self) -> None:
        self._animate_to(1.0)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._btn and event.type() == QEvent.Type.Leave:
            # Mouse drag-out without release still springs back.
            if self._scale < 0.99:
                self._animate_to(1.0)
        return False
