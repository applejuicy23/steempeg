"""Simple Console style: the D-pad moves a highlight, A presses it.

Actions style keeps the shortcut map in ``deck_actions``. This path never
fires Y / X / View / Menu on its own. B is still handled before we get here.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QDialog, QSlider, QWidget

from steempeg.input.deck_navigation import (
    _activate_widget,
    _active_library_grid,
    _collect_settings_focusables,
    _confirm_clip_picker,
    _grid_accepts_selection,
    _nav_clip_picker_grid,
    _nav_open_combo,
    _scroll_widget_visible,
    _select_grid_item,
    _show_focus_ring,
    _visible_grid_items,
    hide_deck_focus_ring,
)
from steempeg.input.gamepad import DeckButton

_DPAD = {
    DeckButton.DPAD_UP: "up",
    DeckButton.DPAD_DOWN: "down",
    DeckButton.DPAD_LEFT: "left",
    DeckButton.DPAD_RIGHT: "right",
}

_SKIP_DIALOG_TYPES = frozenset({"DevModeDialog"})


def try_simple_deck(app: Any, button: DeckButton) -> bool:
    """Consume one pad press. True always: shortcuts must not run after this."""
    if _nav_open_combo(app, button):
        return True
    if getattr(app, "_portable_clip_picker_open", False):
        _simple_picker(app, button)
        return True
    if button == DeckButton.A:
        _activate_current(app)
        return True
    direction = _DPAD.get(button)
    if direction is None:
        return True
    items = _focusables(app)
    if not items:
        hide_deck_focus_ring(app)
        return True
    if _adjust_value(app, items, direction):
        return True
    _move(app, items, direction)
    return True


def pick_focus_neighbor(
    rects: list[tuple[int, int, int, int]],
    index: int,
    direction: str,
) -> int | None:
    """Index of the nearest control in ``direction``, or None at the edge.

    ``rects`` are ``(x, y, w, h)`` in one coordinate space. Up / down stay in
    a column. Left / right stay on a row.
    """
    if not rects or index < 0 or index >= len(rects):
        return None
    ox, oy, ow, oh = rects[index]
    ocx = ox + ow / 2
    ocy = oy + oh / 2
    best_i: int | None = None
    best_score: float | None = None
    for i, (x, y, w, h) in enumerate(rects):
        if i == index:
            continue
        cx = x + w / 2
        cy = y + h / 2
        dx = cx - ocx
        dy = cy - ocy
        if direction == "up" and dy >= -8:
            continue
        if direction == "down" and dy <= 8:
            continue
        if direction == "left" and dx >= -8:
            continue
        if direction == "right" and dx <= 8:
            continue
        if direction in ("up", "down"):
            primary = abs(dy)
            secondary = abs(dx)
            if secondary > max(ow, w, 48) * 1.25 and secondary > primary:
                continue
        else:
            primary = abs(dx)
            secondary = abs(dy)
            if secondary > max(oh, h, 28) * 1.5:
                continue
        score = primary + secondary * 3
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    return best_i


def _simple_picker(app: Any, button: DeckButton) -> None:
    """Choose a Clip: the grid moves like a list. Up from the top row reaches the toolbar."""
    chrome_on = bool(getattr(app, "_deck_simple_picker_chrome", False))
    chrome = _picker_chrome(app)
    if button == DeckButton.A:
        if chrome_on:
            _activate_listed(app, chrome)
        else:
            _confirm_clip_picker(app)
        return
    direction = _DPAD.get(button)
    if direction is None:
        return
    if not chrome_on:
        if direction == "up" and chrome and _grid_on_first_row(app):
            _enter_picker_chrome(app, chrome)
            return
        _nav_clip_picker_grid(app, button)
        return
    if not chrome:
        app._deck_simple_picker_chrome = False
        _nav_clip_picker_grid(app, button)
        return
    if direction == "down" and _neighbor_index(chrome, _current_index(app, chrome), "down") is None:
        _enter_picker_grid(app)
        return
    _move(app, chrome, direction)


def _enter_picker_chrome(app: Any, chrome: list[QWidget]) -> None:
    """Leave the clip grid and highlight the toolbar control just above it."""
    app._deck_simple_picker_chrome = True
    app._deck_simple_focus_id = id(chrome[-1])
    _show_item(app, chrome[-1])


def _enter_picker_grid(app: Any) -> None:
    """Drop the toolbar highlight and keep the clip selection."""
    app._deck_simple_picker_chrome = False
    app._deck_simple_focus_id = None
    hide_deck_focus_ring(app)
    grid, source = _active_library_grid(app)
    if grid is None or not _grid_accepts_selection(app, source):
        return
    items = _visible_grid_items(grid)
    if items and not grid.selectedItems():
        _select_grid_item(app, items[0], source=source)


def _grid_on_first_row(app: Any) -> bool:
    """True when ▲ should leave the grid (nothing picked, or the top row)."""
    grid, source = _active_library_grid(app)
    if grid is None or not _grid_accepts_selection(app, source):
        return False
    items = _visible_grid_items(grid)
    if not items:
        return False
    selected = grid.selectedItems()
    current = selected[0] if selected else None
    try:
        cur = items.index(current) if current in items else -1
    except ValueError:
        cur = -1
    if cur < 0:
        return True
    cols_fn = getattr(app, "_clip_grid_column_count_for", None)
    cols = int(cols_fn(grid)) if callable(cols_fn) else 1
    row, _col = divmod(cur, max(1, cols))
    return row == 0


def _picker_chrome(app: Any) -> list[QWidget]:
    """Toolbar controls on Choose a Clip, not the cards themselves."""
    dlg = getattr(app, "_portable_clip_picker_dlg", None)
    if dlg is None:
        return []
    return [w for w in _collect(dlg) if not _under_card(w)]


def _under_card(widget: QWidget) -> bool:
    """True for a control that lives on a library card or a queue row."""
    node: QWidget | None = widget
    while node is not None:
        name = node.objectName()
        if name in ("ClipCard", "portableQueueRow") or type(node).__name__ == "ScreenshotPhoto":
            return True
        try:
            node = node.parentWidget()
        except RuntimeError:
            return False
    return False


def _focusables(app: Any) -> list[QWidget]:
    """Controls on the front dialog, or the player header and footer."""
    roots = _focus_roots(app)
    signature = tuple(id(root) for root in roots)
    if getattr(app, "_deck_simple_roots", None) != signature:
        app._deck_simple_roots = signature
        app._deck_simple_focus_id = None
        app._deck_simple_picker_chrome = False
    found: list[QWidget] = []
    seen: set[int] = set()
    for root in roots:
        for widget in _collect(root):
            token = id(widget)
            if token in seen:
                continue
            seen.add(token)
            found.append(widget)
    found.sort(key=_sort_key)
    return found


def _focus_roots(app: Any) -> list[QWidget]:
    """The surface the highlight is allowed to walk."""
    if getattr(app, "_app_settings_open", False):
        dlg = getattr(app, "_app_settings_dlg", None)
        if dlg is not None:
            return [dlg]
    if getattr(app, "_portable_render_settings_open", False):
        dlg = getattr(app, "_portable_render_sheet_dlg", None)
        if dlg is not None:
            return [dlg]
    overlay = _overlay_dialog(app)
    if overlay is not None:
        return [overlay]
    active = QApplication.activeWindow()
    if active is not None and active.objectName() == "ExpressPlayer":
        try:
            if active.isVisible():
                return [active]
        except RuntimeError:
            pass
    roots: list[QWidget] = []
    for name in ("player_header_frame", "player_footer_frame"):
        frame = getattr(app, name, None)
        if frame is None:
            continue
        try:
            if frame.isVisible():
                roots.append(frame)
        except RuntimeError:
            continue
    return roots


def _overlay_dialog(app: Any) -> QDialog | None:
    """A dialog in front of the player. The Dev pad and the main window are not one."""
    modal = QApplication.activeModalWidget()
    if _is_overlay(app, modal):
        return modal
    active = QApplication.activeWindow()
    if _is_overlay(app, active):
        return active
    for widget in QApplication.topLevelWidgets():
        if _is_overlay(app, widget):
            return widget
    return None


def _is_overlay(app: Any, widget: QWidget | None) -> bool:
    """True for a visible dialog that is not the main window or Developer tools."""
    if not isinstance(widget, QDialog):
        return False
    if type(widget).__name__ in _SKIP_DIALOG_TYPES:
        return False
    ui = getattr(app, "ui", None)
    if widget is ui:
        return False
    try:
        return bool(widget.isVisible())
    except RuntimeError:
        return False


def _collect(root: QWidget) -> list[QWidget]:
    """Buttons, fields, and queue cards. A button inside a card is the card."""
    items = list(_collect_settings_focusables(root))
    seen = {id(w) for w in items}
    for widget in root.findChildren(QWidget):
        if widget.objectName() != "portableQueueRow":
            continue
        token = id(widget)
        if token in seen:
            continue
        try:
            if not widget.isVisible() or not widget.isEnabled():
                continue
        except RuntimeError:
            continue
        seen.add(token)
        items.append(widget)
    parent_ids = {id(w) for w in items}

    def _nested(widget: QWidget) -> bool:
        parent = widget.parentWidget()
        while parent is not None and parent is not root:
            if id(parent) in parent_ids:
                return True
            try:
                parent = parent.parentWidget()
            except RuntimeError:
                return False
        return False

    items = [w for w in items if not _nested(w)]
    items.sort(key=_sort_key)
    return items


def _sort_key(widget: QWidget) -> tuple[int, int]:
    """Top to bottom, then left to right. Same order as Tab."""
    try:
        top_left = widget.mapToGlobal(widget.rect().topLeft())
    except RuntimeError:
        return (0, 0)
    return (top_left.y(), top_left.x())


def _rects(items: list[QWidget]) -> list[tuple[int, int, int, int]]:
    """Global rectangles for the neighbor search."""
    rects: list[tuple[int, int, int, int]] = []
    for widget in items:
        try:
            top_left = widget.mapToGlobal(widget.rect().topLeft())
            rects.append((top_left.x(), top_left.y(), widget.width(), widget.height()))
        except RuntimeError:
            rects.append((0, 0, 0, 0))
    return rects


def _current_index(app: Any, items: list[QWidget]) -> int:
    """Highlighted row, or Play when nothing is highlighted yet."""
    token = getattr(app, "_deck_simple_focus_id", None)
    for i, widget in enumerate(items):
        if id(widget) == token:
            return i
    for i, widget in enumerate(items):
        if widget.objectName() == "btn_play":
            return i
    return 0


def _neighbor_index(items: list[QWidget], index: int, direction: str) -> int | None:
    """Spatial neighbor, then the next control in Tab order."""
    spatial = pick_focus_neighbor(_rects(items), index, direction)
    if spatial is not None:
        return spatial
    if direction in ("down", "right"):
        nxt = index + 1
        return nxt if nxt < len(items) else None
    prev = index - 1
    return prev if prev >= 0 else None


def _move(app: Any, items: list[QWidget], direction: str) -> None:
    """Step the highlight. The first press starts at Play, then moves."""
    if not items:
        return
    known = getattr(app, "_deck_simple_focus_id", None)
    index = _current_index(app, items)
    if known not in {id(w) for w in items}:
        nxt = _neighbor_index(items, index, direction)
        _remember(app, items[index if nxt is None else nxt])
        return
    nxt = _neighbor_index(items, index, direction)
    if nxt is None:
        _remember(app, items[index])
        return
    _remember(app, items[nxt])


def _remember(app: Any, widget: QWidget) -> None:
    """Store the highlight and paint the ring."""
    app._deck_simple_focus_id = id(widget)
    _show_item(app, widget)


def _show_item(app: Any, widget: QWidget) -> None:
    """Focus, scroll, and outline one control."""
    try:
        widget.setFocus(Qt.FocusReason.OtherFocusReason)
    except RuntimeError:
        hide_deck_focus_ring(app)
        return
    _scroll_widget_visible(widget)
    _show_focus_ring(app, widget, require_console=False)


def _activate_current(app: Any) -> None:
    """A presses the highlighted control on the current surface."""
    _activate_listed(app, _focusables(app))


def _activate_listed(app: Any, items: list[QWidget]) -> None:
    """A presses the highlighted control in ``items``."""
    if not items:
        return
    widget = items[_current_index(app, items)]
    _remember(app, widget)
    _activate_target(widget)


def _activate_target(widget: QWidget) -> None:
    """Click a button, or the same path a queue card uses for a mouse click."""
    if widget.objectName() == "portableQueueRow":
        job_id = getattr(widget, "_job_id", None)
        emit = getattr(getattr(widget, "clicked", None), "emit", None)
        if job_id and callable(emit):
            emit(job_id, Qt.KeyboardModifier.NoModifier)
        return
    _activate_widget(widget)


def _adjust_value(app: Any, items: list[QWidget], direction: str) -> bool:
    """Left / right changes a slider when nothing else sits on that side."""
    if direction not in ("left", "right"):
        return False
    known = getattr(app, "_deck_simple_focus_id", None)
    widget = next((w for w in items if id(w) == known), None)
    if widget is None:
        return False
    if not isinstance(widget, (QSlider, QAbstractSpinBox)):
        return False
    index = items.index(widget)
    if pick_focus_neighbor(_rects(items), index, direction) is not None:
        return False
    step = -1 if direction == "left" else 1
    if isinstance(widget, QSlider):
        widget.setValue(widget.value() + step * max(1, widget.singleStep()))
        _show_item(app, widget)
        return True
    if isinstance(widget, QAbstractSpinBox):
        widget.stepBy(step)
        _show_item(app, widget)
        return True
    return False
