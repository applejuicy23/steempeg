"""Short appear/disappear anims for player-footer pills (Markers gear, Trim tools).

Placement (inline / under theater / under Cancel) stays in ``adaptive_trim_tools`` —
these helpers only fade and, for chips inside a pill, grow/shrink width so the
capsule expands instead of popping.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QAbstractAnimation,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

_DUR_MS = 200


def _stop_group(widget: QWidget, attr: str) -> None:
    group = getattr(widget, attr, None)
    if group is not None:
        try:
            group.stop()
        except RuntimeError:
            pass
        setattr(widget, attr, None)


def _opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect:
    fx = widget.graphicsEffect()
    if isinstance(fx, QGraphicsOpacityEffect):
        return fx
    fx = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(fx)
    return fx


def _clear_opacity_effect(widget: QWidget) -> None:
    fx = widget.graphicsEffect()
    if isinstance(fx, QGraphicsOpacityEffect):
        widget.setGraphicsEffect(None)


def animate_chip_in_pill(
    chip: QWidget,
    pill: QWidget | None,
    *,
    show: bool,
    target_w: int = 40,
    on_finished=None,
) -> None:
    """Grow/shrink ``chip`` inside ``pill`` (Marker settings gear)."""
    if chip is None:
        return
    _stop_group(chip, "_footer_chip_anim")
    if show == chip.isVisible() and (
        show and chip.width() >= max(8, target_w - 2)
        or (not show and not chip.isVisible())
    ):
        return

    if show:
        chip.setVisible(True)
        chip.setFixedWidth(0)
        fx = _opacity_effect(chip)
        fx.setOpacity(0.0)
        start_w, end_w = 0, max(1, int(target_w))
        start_o, end_o = 0.0, 1.0
    else:
        if not chip.isVisible():
            return
        fx = _opacity_effect(chip)
        fx.setOpacity(1.0)
        start_w, end_w = max(chip.width(), 1), 0
        start_o, end_o = 1.0, 0.0

    group = QParallelAnimationGroup(chip)
    w_anim = QPropertyAnimation(chip, b"maximumWidth", chip)
    w_anim.setDuration(_DUR_MS)
    w_anim.setStartValue(start_w)
    w_anim.setEndValue(end_w)
    w_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    # Keep min in sync so layout actually shrinks the pill.
    w_min = QPropertyAnimation(chip, b"minimumWidth", chip)
    w_min.setDuration(_DUR_MS)
    w_min.setStartValue(start_w)
    w_min.setEndValue(end_w)
    w_min.setEasingCurve(QEasingCurve.Type.OutCubic)
    o_anim = QPropertyAnimation(fx, b"opacity", chip)
    o_anim.setDuration(_DUR_MS)
    o_anim.setStartValue(start_o)
    o_anim.setEndValue(end_o)
    o_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    group.addAnimation(w_anim)
    group.addAnimation(w_min)
    group.addAnimation(o_anim)

    def _finish() -> None:
        chip._footer_chip_anim = None  # type: ignore[attr-defined]
        if show:
            chip.setMinimumWidth(0)
            chip.setMaximumWidth(16777215)
            chip.setFixedWidth(target_w)
            _clear_opacity_effect(chip)
        else:
            chip.hide()
            chip.setMinimumWidth(0)
            chip.setMaximumWidth(16777215)
            chip.setFixedWidth(target_w)
            _clear_opacity_effect(chip)
        if pill is not None:
            pill.updateGeometry()
            pill.adjustSize()
        if on_finished is not None:
            try:
                on_finished()
            except Exception:
                pass

    group.finished.connect(_finish)
    chip._footer_chip_anim = group  # type: ignore[attr-defined]
    group.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


def animate_geometry_move(widget: QWidget, start: QRect, end: QRect, on_finished=None) -> None:
    """Slide ``widget`` from ``start`` to ``end`` (marker pill teleport)."""
    if widget is None or not start.isValid() or not end.isValid():
        return
    if start == end:
        widget.setGeometry(end)
        if on_finished is not None:
            try:
                on_finished()
            except Exception:
                pass
        return
    _stop_group(widget, "_footer_geom_anim")
    widget.setGeometry(start)
    widget.show()
    widget.raise_()
    anim = QPropertyAnimation(widget, b"geometry", widget)
    anim.setDuration(_DUR_MS)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _finish() -> None:
        widget._footer_geom_anim = None  # type: ignore[attr-defined]
        widget.setGeometry(end)
        widget.raise_()
        if on_finished is not None:
            try:
                on_finished()
            except Exception:
                pass

    anim.finished.connect(_finish)
    widget._footer_geom_anim = anim  # type: ignore[attr-defined]
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


def animate_footer_overlay_widget(
    widget: QWidget,
    *,
    show: bool,
    final_geom: QRect | None = None,
) -> None:
    """Fade (and optional slide) for trim tools / overlay-placed pills."""
    if widget is None:
        return
    _stop_group(widget, "_footer_overlay_anim")

    if show:
        widget.show()
        widget.raise_()
        if final_geom is not None and final_geom.isValid():
            # Start slightly tucked toward the parent (under Cancel / theater).
            start = QRect(final_geom)
            start.moveTop(max(0, final_geom.top() - 8))
            widget.setGeometry(start)
        fx = _opacity_effect(widget)
        fx.setOpacity(0.0)
        start_o, end_o = 0.0, 1.0
    else:
        if not widget.isVisible():
            return
        fx = _opacity_effect(widget)
        fx.setOpacity(float(fx.opacity()) if fx.opacity() > 0 else 1.0)
        start_o, end_o = float(fx.opacity()), 0.0
        final_geom = widget.geometry()

    group = QParallelAnimationGroup(widget)
    o_anim = QPropertyAnimation(fx, b"opacity", widget)
    o_anim.setDuration(_DUR_MS)
    o_anim.setStartValue(start_o)
    o_anim.setEndValue(end_o)
    o_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    group.addAnimation(o_anim)

    if show and final_geom is not None and final_geom.isValid():
        g_anim = QPropertyAnimation(widget, b"geometry", widget)
        g_anim.setDuration(_DUR_MS)
        g_anim.setStartValue(widget.geometry())
        g_anim.setEndValue(final_geom)
        g_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(g_anim)

    def _finish() -> None:
        widget._footer_overlay_anim = None  # type: ignore[attr-defined]
        if show:
            if final_geom is not None and final_geom.isValid():
                widget.setGeometry(final_geom)
            _clear_opacity_effect(widget)
            widget.raise_()
        else:
            widget.hide()
            _clear_opacity_effect(widget)

    group.finished.connect(_finish)
    widget._footer_overlay_anim = group  # type: ignore[attr-defined]
    group.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
