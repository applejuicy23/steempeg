"""Block mouse-wheel value changes on combos/spinboxes in scrollable forms."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QScrollArea, QWidget


class NoWheelValueFilter(QObject):
    """Ignore wheel on combo/spin so scrollable dialogs do not change values.

    When a combo popup is open, wheel is left alone so the list can scroll.
    Otherwise the event is forwarded to the nearest QScrollArea viewport.
    Keyboard and click selection are unaffected.
    """

    def eventFilter(self, obj, event):  # noqa: N802 — Qt API
        if event.type() != QEvent.Type.Wheel:
            return False

        if isinstance(obj, QComboBox):
            view = obj.view()
            if view is not None and view.isVisible():
                return False
            _forward_wheel_to_scroll(obj, event)
            return True

        if isinstance(obj, QAbstractSpinBox):
            _forward_wheel_to_scroll(obj, event)
            return True

        return False


def _forward_wheel_to_scroll(widget: QWidget, event) -> None:
    w = widget.parentWidget()
    while w is not None:
        if isinstance(w, QScrollArea):
            vp = w.viewport()
            if vp is not None:
                QGuiApplication.sendEvent(vp, event)
            return
        w = w.parentWidget()
    parent = widget.parentWidget()
    if parent is not None:
        QGuiApplication.sendEvent(parent, event)


def install_no_wheel_value_filter(
    root: QWidget,
    *,
    include_spinboxes: bool = True,
) -> NoWheelValueFilter:
    """Install the filter on all QComboBox (and optionally spinboxes) under ``root``."""
    filt = NoWheelValueFilter(root)
    for combo in root.findChildren(QComboBox):
        combo.installEventFilter(filt)
    if include_spinboxes:
        for spin in root.findChildren(QAbstractSpinBox):
            spin.installEventFilter(filt)
    # Keep alive for the dialog lifetime (filters are not QObject-parented by install).
    root._no_wheel_value_filter = filt  # type: ignore[attr-defined]
    return filt
