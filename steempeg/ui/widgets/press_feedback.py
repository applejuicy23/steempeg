"""Short press-in feedback for buttons.

Transport buttons scale the icon. Render and player chips scale the live
button paint around its center. Both leave the hitbox and layout unchanged.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import QAbstractButton, QPushButton, QStyle, QStyleOptionButton, QWidget

from steempeg.ui.design_tokens import CARD_PRESS_SCALE


def install_press_feedback(
    button: QAbstractButton,
    *,
    pressed_scale: float | None = None,
    duration_ms: int | None = None,
    mode: str = "icon",
) -> PressFeedbackFilter:
    """Attach press feedback; safe to call once per button.

    ``mode``:
      * ``icon`` — scale the painted icon (player transport).
      * ``chip`` — scale the whole button paint.
    """
    if mode == "chip":
        if pressed_scale is None:
            pressed_scale = float(CARD_PRESS_SCALE)
    else:
        if pressed_scale is None:
            pressed_scale = 0.91
    if duration_ms is None:
        duration_ms = 95

    existing = getattr(button, "_press_feedback_filter", None)
    if isinstance(existing, PressFeedbackFilter):
        if existing.mode != mode:
            existing.mode = mode
        existing._pressed_scale = float(pressed_scale)
        existing._duration = max(40, int(duration_ms))
        existing.sync_rest()
        return existing
    filt = PressFeedbackFilter(
        button,
        pressed_scale=float(pressed_scale),
        duration_ms=int(duration_ms),
        mode=mode,
    )
    button._press_feedback_filter = filt  # type: ignore[attr-defined]
    return filt


def install_press_feedback_chip(
    button: QAbstractButton | None,
    *,
    pressed_scale: float | None = None,
    duration_ms: int | None = None,
) -> PressFeedbackFilter | None:
    """Scale the whole button in place. No-op for missing or unsupported controls."""
    if not isinstance(button, QPushButton):
        return None
    try:
        button.objectName()
    except RuntimeError:
        return None
    return install_press_feedback(
        button,
        pressed_scale=pressed_scale,
        duration_ms=duration_ms,
        mode="chip",
    )


def install_render_chrome_press_feedback(host: QWidget) -> None:
    """Wire Trim / Start / Leave / Render Settings / Pause / Cancel — not Logs.

    ``host`` is the Steempeg app (or anything that owns these attrs / ``ui``).
    Safe to call repeatedly after density or chrome rebuilds.
    """
    ui = getattr(host, "ui", None)

    install_press_feedback_chip(getattr(host, "btn_trim", None))

    if ui is not None:
        install_press_feedback_chip(getattr(ui, "btn_start", None))
        install_press_feedback_chip(getattr(ui, "btn_pause", None))
        install_press_feedback_chip(getattr(ui, "btn_cancel", None))

    install_press_feedback_chip(getattr(host, "btn_render_settings", None))
    install_press_feedback_chip(getattr(host, "_btn_queue_leave_resume", None))

    strip = getattr(host, "_portable_render_strip", None)
    if strip is not None:
        install_press_feedback_chip(getattr(strip, "btn_start", None))
        install_press_feedback_chip(getattr(strip, "btn_leave", None))
        install_press_feedback_chip(getattr(strip, "btn_pause", None))
        install_press_feedback_chip(getattr(strip, "btn_cancel", None))

    install_press_feedback_chip(getattr(host, "btn_portable_render", None))


class PressFeedbackFilter(QObject):
    def __init__(
        self,
        button: QAbstractButton,
        *,
        pressed_scale: float = 0.88,
        duration_ms: int = 80,
        mode: str = "icon",
    ):
        super().__init__(button)
        self._btn = button
        self._pressed_scale = float(pressed_scale)
        self._duration = max(40, int(duration_ms))
        self.mode = "chip" if mode == "chip" else "icon"
        self._scale = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(lambda value: self._apply_scale(float(value)))
        self._icon_pixmaps = {}
        self._pressed = False
        button.installEventFilter(self)
        button.pressed.connect(self._on_pressed)
        button.released.connect(self._on_released)
        self.sync_rest()

    def sync_rest_icon_size(self) -> None:
        """Back-compat alias used by density / transport paths."""
        self.sync_rest()

    def sync_rest(self) -> None:
        """Refresh the resting paint after density, icon or label changes."""
        self._btn.update()

    def _apply_scale(self, scale: float) -> None:
        self._scale = scale
        self._btn.update()

    def _animate_to(self, target: float) -> None:
        self._anim.stop()
        start = float(self._scale)
        target = float(target)
        if abs(start - target) < 0.01:
            self._apply_scale(target)
            return
        anim = self._anim
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setDuration(self._duration + (25 if target >= start else 0))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()

    def _on_pressed(self) -> None:
        self._pressed = True
        self._animate_to(self._pressed_scale)

    def _on_released(self) -> None:
        self._pressed = False
        self._animate_to(1.0)

    def _paint_icon(self) -> bool:
        icon = self._btn.icon()
        if icon.isNull():
            return False
        size = self._btn.iconSize()
        dpr = self._btn.devicePixelRatioF()
        mode = QIcon.Mode.Normal if self._btn.isEnabled() else QIcon.Mode.Disabled
        key = (icon.cacheKey(), size.width(), size.height(), dpr, mode)
        if key not in self._icon_pixmaps:
            if len(self._icon_pixmaps) >= 8:
                self._icon_pixmaps.clear()
            self._icon_pixmaps[key] = icon.pixmap(size, dpr, mode)
        pixmap = self._icon_pixmaps[key]
        if pixmap.isNull():
            return False
        logical = pixmap.deviceIndependentSize()
        with QPainter(self._btn) as painter:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.translate(self._btn.width() / 2.0, self._btn.height() / 2.0)
            painter.scale(self._scale, self._scale)
            painter.drawPixmap(QPointF(-logical.width() / 2, -logical.height() / 2), pixmap)
        return True

    def _paint_chip(self) -> bool:
        if not isinstance(self._btn, QPushButton) or self._scale == 1.0:
            return False

        option = QStyleOptionButton()
        self._btn.initStyleOption(option)
        center = QPointF(self._btn.width() / 2.0, self._btn.height() / 2.0)
        with QPainter(self._btn) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.translate(center)
            painter.scale(self._scale, self._scale)
            painter.translate(-center)
            draw_button = getattr(self._btn, "draw_press_feedback_chip", None)
            if draw_button is None:
                self._btn.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self._btn)
            else:
                draw_button(painter, option)
        return True

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is not self._btn:
            return False
        et = event.type()
        if et == QEvent.Type.Paint:
            return self._paint_icon() if self.mode == "icon" else self._paint_chip()
        if et == QEvent.Type.Leave and (self._pressed or self._scale < 0.99):
            self._on_released()
        elif et == QEvent.Type.Hide or (et == QEvent.Type.EnabledChange and not self._btn.isEnabled()):
            self._anim.stop()
            self._pressed = False
            self._apply_scale(1.0)
        return False
