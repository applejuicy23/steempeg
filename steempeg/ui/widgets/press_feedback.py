"""Short press-in feedback for buttons.

Transport icons use ``mode="icon"`` (iconSize only).

Render-dash / Trim chips use ``mode="chip"`` — same language as ClipCard:
grab a snapshot, paint it scaled about center (``CARD_PRESS_*`` tokens).
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
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QAbstractButton, QWidget

from steempeg.ui.design_tokens import CARD_PRESS_DURATION_MS, CARD_PRESS_SCALE


def install_press_feedback(
    button: QAbstractButton,
    *,
    pressed_scale: float | None = None,
    duration_ms: int | None = None,
    mode: str = "icon",
) -> PressFeedbackFilter:
    """Attach press feedback; safe to call once per button.

    ``mode``:
      * ``icon`` — shrink ``iconSize`` (player transport).
      * ``chip`` — ClipCard-style whole-control snapshot scale.
    """
    if mode == "chip":
        if pressed_scale is None:
            pressed_scale = float(CARD_PRESS_SCALE)
        if duration_ms is None:
            duration_ms = int(CARD_PRESS_DURATION_MS)
    else:
        if pressed_scale is None:
            pressed_scale = 0.88
        if duration_ms is None:
            duration_ms = 80

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
    """ClipCard-style whole-chip press. No-op on ``None``."""
    if button is None:
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
        self._rest_icon: QSize | None = None
        self._scale = 1.0
        self._anim: QVariantAnimation | None = None
        self._snapshot: QPixmap | None = None
        self._pressed = False
        self._backdrop = QColor("#141414")
        button.installEventFilter(self)
        button.pressed.connect(self._on_pressed)
        button.released.connect(self._on_released)
        self.sync_rest()

    def sync_rest_icon_size(self) -> None:
        """Back-compat alias used by density / transport paths."""
        self.sync_rest()

    def sync_rest(self) -> None:
        """Call after density / icon / label changes so the next press grabs fresh."""
        if self._pressed or self._scale < 0.99:
            return
        self._end_chip_paint_mode()
        sz = self._btn.iconSize()
        if sz.isValid() and sz.width() > 0:
            self._rest_icon = QSize(sz)
        else:
            self._rest_icon = None
        self._scale = 1.0
        self._refresh_backdrop()

    def _refresh_backdrop(self) -> None:
        """Color behind the chip — fills corners when the grab is scaled down."""
        try:
            from steempeg.ui import design_tokens as tok

            self._backdrop = QColor(getattr(tok, "BG_SHELL", None) or "#1e1e1e")
        except Exception:
            self._backdrop = QColor("#1e1e1e")
        parent = self._btn.parentWidget()
        if parent is None:
            return
        try:
            # Sample the parent fill so dash / footer match (TrueDark / chrome theme).
            pal = parent.palette().color(parent.backgroundRole())
            if pal.isValid() and pal.alpha() > 0:
                # Prefer explicit shell token when parent palette is still default gray.
                name = pal.name().lower()
                if name not in ("#000000", "#ffffff", "#f0f0f0"):
                    self._backdrop = QColor(pal)
        except Exception:
            pass

    def _chip_radius(self, w: int, h: int) -> float:
        # Dash / Trim chips are pills: radius ≈ half height (same as _fmt_dash_btn).
        return float(max(8, h // 2))

    def _ensure_rest_icon(self) -> QSize | None:
        if self._rest_icon is None or not self._rest_icon.isValid():
            sz = self._btn.iconSize()
            if sz.isValid() and sz.width() > 0:
                self._rest_icon = QSize(sz)
        return self._rest_icon

    def _begin_chip_paint_mode(self) -> None:
        """ClipCard: grab the live control, then paint that pixmap scaled."""
        if self._snapshot is not None and not self._snapshot.isNull():
            return
        self._refresh_backdrop()
        try:
            snap = self._btn.grab()
        except Exception:
            snap = QPixmap()
        if snap.isNull():
            return
        # QSS pills still grab as an opaque rectangle — mask to a real round chip
        # so scaled paint never shows square corners.
        w = max(1, snap.width())
        h = max(1, snap.height())
        radius = self._chip_radius(w, h)
        masked = QPixmap(w, h)
        masked.fill(Qt.GlobalColor.transparent)
        mp = QPainter(masked)
        mp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, w - 1.0, h - 1.0, radius, radius)
        mp.setClipPath(path)
        mp.drawPixmap(0, 0, snap)
        mp.end()
        self._snapshot = masked
        self._btn.update()

    def _end_chip_paint_mode(self) -> None:
        if self._snapshot is None:
            return
        self._snapshot = None
        try:
            self._btn.update()
        except RuntimeError:
            pass

    def _apply_icon_scale(self, scale: float) -> None:
        rest = self._ensure_rest_icon()
        if rest is None:
            return
        w = max(1, int(round(rest.width() * scale)))
        h = max(1, int(round(rest.height() * scale)))
        self._btn.setIconSize(QSize(w, h))

    def _apply_scale(self, scale: float) -> None:
        self._scale = scale
        if self.mode == "icon":
            self._apply_icon_scale(scale)
            return
        self._btn.update()

    def _animate_to(self, target: float) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        start = float(self._scale)
        target = float(target)
        if abs(start - target) < 0.01:
            self._apply_scale(target)
            if self.mode == "chip" and abs(target - 1.0) < 0.01 and not self._pressed:
                self._end_chip_paint_mode()
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setDuration(self._duration)
        anim.setEasingCurve(
            QEasingCurve.Type.OutCubic
            if target >= start
            else QEasingCurve.Type.InCubic
        )
        anim.valueChanged.connect(lambda v: self._apply_scale(float(v)))
        anim.finished.connect(self._on_anim_finished)
        self._anim = anim
        anim.start()

    def _on_anim_finished(self) -> None:
        self._anim = None
        if (
            self.mode == "chip"
            and abs(self._scale - 1.0) < 0.01
            and not self._pressed
        ):
            self._end_chip_paint_mode()

    def _on_pressed(self) -> None:
        self._pressed = True
        if self.mode == "chip":
            # Snapshot preferably taken on MouseButtonPress (pre-:pressed). Fallback:
            if self._snapshot is None or self._snapshot.isNull():
                self._begin_chip_paint_mode()
        else:
            if abs(self._scale - 1.0) < 0.01:
                self.sync_rest()
        self._animate_to(self._pressed_scale)

    def _on_released(self) -> None:
        self._pressed = False
        self._animate_to(1.0)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is not self._btn:
            return False
        et = event.type()
        if self.mode == "chip" and et == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                # Grab before Qt flips :pressed (avoids rectangular pressed fill in snap).
                if abs(self._scale - 1.0) < 0.01:
                    self._end_chip_paint_mode()
                self._begin_chip_paint_mode()
            return False
        if et == QEvent.Type.Leave:
            if self._pressed or self._scale < 0.99:
                self._pressed = False
                self._animate_to(1.0)
            return False
        if (
            self.mode == "chip"
            and et == QEvent.Type.Paint
            and self._snapshot is not None
            and not self._snapshot.isNull()
        ):
            # ClipCard language: backdrop + rounded clip + grab scaled about center.
            p = QPainter(self._btn)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            w = max(1, int(self._btn.width()))
            h = max(1, int(self._btn.height()))
            # Clear the rectangular widget slot with the dash/footer fill.
            p.fillRect(0, 0, w, h, self._backdrop)
            scale = float(self._scale)
            if abs(scale - 1.0) > 0.001:
                cx = w / 2.0
                cy = h / 2.0
                p.translate(cx, cy)
                p.scale(scale, scale)
                p.translate(-cx, -cy)
            snap = self._snapshot
            if snap.width() != w or snap.height() != h:
                p.drawPixmap(
                    0,
                    0,
                    snap.scaled(
                        w,
                        h,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ),
                )
            else:
                p.drawPixmap(0, 0, snap)
            p.end()
            return True
        return False
