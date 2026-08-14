"""LMB drag paint-select / paint-deselect for checkable filter pill chips."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QPushButton, QWidget


def pill_at(layout, pos: QPoint) -> Optional[QPushButton]:
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if isinstance(w, QPushButton) and w.geometry().contains(pos):
            return w
    return None


class PillPaintDragMixin:
    """Bidirectional paint drag on FlowLayout checkable pills.

    Register zones with ``_register_pill_paint_zone``, then
    ``_wire_pill_paint_button`` on each pill when it is created.
    """

    def _init_pill_paint_drag(self) -> None:
        self._pill_drag_active = False
        self._pill_drag_select_mode = True
        self._pill_drag_layout = None
        self._pill_drag_on_change: Callable[[], None] | None = None
        self._pill_drag_buttons: set[QPushButton] = set()
        self._pill_paint_zones: list[tuple[QWidget, object, Callable[[], None]]] = []

    def _register_pill_paint_zone(
        self, container: QWidget, layout, on_changed: Callable[[], None]
    ) -> None:
        container.installEventFilter(self)
        self._pill_paint_zones.append((container, layout, on_changed))

    def _wire_pill_paint_button(self, btn: QPushButton) -> None:
        btn.installEventFilter(self)
        self._pill_drag_buttons.add(btn)

    def _drop_pill_layout_buttons(self, layout) -> None:
        to_drop: set[QPushButton] = set()
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                to_drop.add(w)
        self._pill_drag_buttons -= to_drop

    def _zone_for_layout(self, layout):
        for container, lay, on_change in self._pill_paint_zones:
            if lay is layout:
                return container, on_change
        return None, None

    def _layout_for_button(self, btn: QPushButton):
        for container, layout, on_change in self._pill_paint_zones:
            for i in range(layout.count()):
                if layout.itemAt(i).widget() is btn:
                    return layout, container, on_change
        return None, None, None

    def _apply_pill_paint(self, btn: QPushButton, on_change: Callable[[], None]) -> None:
        target = self._pill_drag_select_mode
        if btn.isChecked() == target:
            return
        btn.setChecked(target)
        on_change()

    def _pill_paint_at_global(self, global_pos: QPoint) -> None:
        layout = self._pill_drag_layout
        on_change = self._pill_drag_on_change
        if layout is None or on_change is None:
            return
        container, _ = self._zone_for_layout(layout)
        if container is None:
            return
        local = container.mapFromGlobal(global_pos)
        btn = pill_at(layout, local)
        if btn is not None:
            self._apply_pill_paint(btn, on_change)

    def _try_handle_pill_paint_filter(self, source, event) -> bool:
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        btn = None
        layout = None
        on_change = None
        if isinstance(source, QPushButton) and source in self._pill_drag_buttons:
            layout, _, on_change = self._layout_for_button(source)
            btn = source
        else:
            for container, lay, cb in self._pill_paint_zones:
                if source is container:
                    btn = pill_at(lay, event.position().toPoint())
                    if btn is not None:
                        layout, on_change = lay, cb
                    break
        if btn is None or layout is None or on_change is None:
            return False

        self._pill_drag_select_mode = not btn.isChecked()
        self._apply_pill_paint(btn, on_change)
        self._pill_drag_active = True
        self._pill_drag_layout = layout
        self._pill_drag_on_change = on_change
        self.grabMouse()
        return True

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._pill_drag_active:
            self._pill_paint_at_global(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._pill_drag_active and event.button() == Qt.MouseButton.LeftButton:
            self._pill_drag_active = False
            self._pill_drag_layout = None
            self._pill_drag_on_change = None
            self.releaseMouse()
            event.accept()
            return
        super().mouseReleaseEvent(event)
