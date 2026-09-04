"""D-pad / shoulder navigation for Portable sheets (Choose a Clip + Render)."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QComboBox,
    QLineEdit,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QWidget,
)

from steempeg.input.gamepad import DeckButton

_log = logging.getLogger(__name__)

_DPAD = frozenset(
    {
        DeckButton.DPAD_UP,
        DeckButton.DPAD_DOWN,
        DeckButton.DPAD_LEFT,
        DeckButton.DPAD_RIGHT,
    }
)

_RENDER_ZONE_QUEUE = "queue"
_RENDER_ZONE_SETTINGS = "settings"


def try_deck_navigation(app: Any, button: DeckButton) -> bool:
    """Handle sheet-local nav/focus. True = consumed (skip default dispatch)."""
    if getattr(app, "_portable_clip_picker_open", False):
        if button in _DPAD:
            _nav_clip_picker_grid(app, button)
            return True
        if button == DeckButton.L1:
            _cycle_library_panel(app, -1)
            return True
        if button == DeckButton.R1:
            _cycle_library_panel(app, 1)
            return True
        if button == DeckButton.A:
            _confirm_clip_picker(app)
            return True
        return False

    if getattr(app, "_portable_render_settings_open", False):
        return _nav_render_sheet(app, button)

    return False


def _nav_render_sheet(app: Any, button: DeckButton) -> bool:
    if button == DeckButton.L2:
        _set_render_zone(app, _RENDER_ZONE_QUEUE)
        return True
    if button == DeckButton.R2:
        _set_render_zone(app, _RENDER_ZONE_SETTINGS)
        return True

    zone = _render_zone(app)
    if zone == _RENDER_ZONE_QUEUE:
        if button == DeckButton.DPAD_UP:
            _nav_render_queue(app, -1)
            return True
        if button == DeckButton.DPAD_DOWN:
            _nav_render_queue(app, 1)
            return True
        if button == DeckButton.DPAD_RIGHT:
            _set_render_zone(app, _RENDER_ZONE_SETTINGS)
            _focus_settings_by_delta(app, 0)
            return True
        if button == DeckButton.A:
            _activate_render_queue(app)
            return True
        return False

    if button in (DeckButton.L1, DeckButton.DPAD_LEFT):
        _cycle_render_tab(app, -1)
        return True
    if button in (DeckButton.R1, DeckButton.DPAD_RIGHT):
        _cycle_render_tab(app, 1)
        return True
    if button == DeckButton.DPAD_LEFT:
        _set_render_zone(app, _RENDER_ZONE_QUEUE)
        return True
    if button == DeckButton.DPAD_UP:
        _focus_settings_by_delta(app, -1)
        return True
    if button == DeckButton.DPAD_DOWN:
        _focus_settings_by_delta(app, 1)
        return True
    if button == DeckButton.A:
        _activate_render_focus(app)
        return True
    return False


def _render_zone(app: Any) -> str:
    zone = getattr(app, "_deck_render_zone", _RENDER_ZONE_SETTINGS)
    if zone not in (_RENDER_ZONE_QUEUE, _RENDER_ZONE_SETTINGS):
        return _RENDER_ZONE_SETTINGS
    return zone


def _set_render_zone(app: Any, zone: str) -> None:
    app._deck_render_zone = zone


def reset_render_deck_focus(app: Any) -> None:
    """Call when the Render sheet opens — settings panel is the default zone."""
    app._deck_render_zone = _RENDER_ZONE_SETTINGS
    app._deck_settings_focus_idx = 0


def _visible_grid_items(grid) -> list:
    if grid is None:
        return []
    out = []
    for i in range(grid.count()):
        item = grid.item(i)
        if item is not None and not item.isHidden():
            out.append(item)
    return out


def _active_library_grid(app: Any):
    mode = getattr(app, "_library_panel_mode", "clips")
    if mode == "rendered":
        return getattr(app, "grid_rendered", None), "rendered"
    if mode == "screenshots":
        return getattr(app, "grid_screenshots", None), "screenshots"
    return getattr(app, "grid_clips", None), "clips"


def _grid_accepts_selection(app: Any, source: str) -> bool:
    if source == "clips":
        fn = getattr(app, "_clips_library_accepts_selection", None)
        return bool(fn()) if callable(fn) else True
    if source == "rendered":
        return not getattr(app, "_rendered_scan_active", False)
    return True


def _select_grid_item(app: Any, item, *, source: str) -> None:
    if item is None:
        return
    setattr(app, "_deck_grid_nav_active", True)
    try:
        if source == "rendered":
            fn = getattr(app, "_rendered_grid_select_item", None)
            if callable(fn):
                fn(item, force_single=True, mods=Qt.KeyboardModifier.NoModifier)
        elif source == "clips":
            fn = getattr(app, "_grid_select_item", None)
            if callable(fn):
                fn(item, force_single=True, mods=Qt.KeyboardModifier.NoModifier)
        elif source == "screenshots":
            fn = getattr(app, "_screenshot_grid_select_item", None)
            if callable(fn):
                fn(item, force_single=True)
        else:
            grid, _ = _active_library_grid(app)
            if grid is not None:
                grid.setCurrentItem(item)
                item.setSelected(True)
        grid, _ = _active_library_grid(app)
        if grid is not None:
            grid.scrollToItem(item)
    finally:
        setattr(app, "_deck_grid_nav_active", False)


def _nav_clip_picker_grid(app: Any, button: DeckButton) -> None:
    grid, source = _active_library_grid(app)
    if grid is None or not _grid_accepts_selection(app, source):
        return

    items = _visible_grid_items(grid)
    if not items:
        return

    cols_fn = getattr(app, "_clip_grid_column_count_for", None)
    cols = int(cols_fn(grid)) if callable(cols_fn) else 1
    cols = max(1, cols)
    count = len(items)

    selected = grid.selectedItems()
    current_item = selected[0] if selected else None
    try:
        cur = items.index(current_item) if current_item in items else -1
    except ValueError:
        cur = -1

    if cur < 0:
        _select_grid_item(app, items[0], source=source)
        return

    row, col = divmod(cur, cols)
    rows = max(1, (count + cols - 1) // cols)

    if button == DeckButton.DPAD_LEFT:
        nxt = cur - 1 if col > 0 else cur
    elif button == DeckButton.DPAD_RIGHT:
        nxt = cur + 1 if col < cols - 1 and cur + 1 < count else cur
    elif button == DeckButton.DPAD_UP:
        nxt = cur - cols if row > 0 else cur
    elif button == DeckButton.DPAD_DOWN:
        candidate = cur + cols
        nxt = candidate if row < rows - 1 and candidate < count else cur
    else:
        return

    if nxt != cur and 0 <= nxt < count:
        _select_grid_item(app, items[nxt], source=source)


def _open_library_modes(app: Any) -> list[str]:
    tabs = getattr(app, "_library_tabs", None) or {}
    order = ("clips", "rendered", "screenshots")
    return [m for m in order if m in tabs]


def _cycle_library_panel(app: Any, delta: int) -> None:
    modes = _open_library_modes(app)
    if len(modes) <= 1:
        return
    cur = getattr(app, "_library_panel_mode", "clips")
    try:
        idx = modes.index(cur)
    except ValueError:
        idx = 0
    nxt = modes[(idx + delta) % len(modes)]
    fn = getattr(app, "set_library_panel", None)
    if callable(fn):
        fn(nxt)


def _cycle_render_tab(app: Any, delta: int) -> None:
    tabs: QTabWidget | None = getattr(getattr(app, "ui", None), "settings_tabs", None)
    buttons = getattr(app, "neo_nav_buttons", None) or []
    if tabs is None or tabs.count() <= 0:
        return
    count = tabs.count()
    cur = tabs.currentIndex()
    for step in range(1, count + 1):
        idx = (cur + delta * step) % count
        page = tabs.widget(idx)
        btn = buttons[idx] if idx < len(buttons) else None
        page_ok = page is not None and page.isEnabled()
        btn_ok = btn is None or btn.isEnabled()
        if not page_ok or not btn_ok:
            continue
        if btn is not None:
            btn.click()
        else:
            tabs.setCurrentIndex(idx)
        app._deck_settings_focus_idx = 0
        fit = getattr(app, "fit_settings_tab_to_page", None)
        if callable(fit):
            fit(idx)
        return


def _render_tab_page(app: Any) -> QWidget | None:
    tabs = getattr(getattr(app, "ui", None), "settings_tabs", None)
    if tabs is None:
        return None
    return tabs.currentWidget()


def _collect_settings_focusables(page: QWidget) -> list[QWidget]:
    """Visible, enabled controls in paint order (top→bottom, left→right)."""
    types = (QAbstractButton, QComboBox, QSpinBox, QLineEdit, QSlider)
    found: list[QWidget] = []
    seen: set[int] = set()
    for w in page.findChildren(QWidget):
        token = id(w)
        if token in seen:
            continue
        if not w.isVisible() or not w.isEnabled():
            continue
        if w.focusPolicy() == Qt.FocusPolicy.NoFocus and not isinstance(
            w, (QAbstractButton, QComboBox)
        ):
            continue
        if not isinstance(w, types):
            click = getattr(w, "click", None)
            if not callable(click):
                continue
        seen.add(token)
        found.append(w)

    def _sort_key(widget: QWidget) -> tuple[int, int]:
        top_left = widget.mapToGlobal(widget.rect().topLeft())
        return (top_left.y(), top_left.x())

    found.sort(key=_sort_key)
    return found


def _scroll_widget_visible(w: QWidget) -> None:
    parent = w.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(w, 24, 24)
            return
        parent = parent.parentWidget()


def _focus_settings_by_delta(app: Any, delta: int) -> None:
    page = _render_tab_page(app)
    if page is None:
        return
    items = _collect_settings_focusables(page)
    if not items:
        return
    cur = int(getattr(app, "_deck_settings_focus_idx", 0))
    if delta == 0:
        nxt = max(0, min(len(items) - 1, cur))
    else:
        nxt = max(0, min(len(items) - 1, cur + delta))
    app._deck_settings_focus_idx = nxt
    w = items[nxt]
    w.setFocus(Qt.FocusReason.OtherFocusReason)
    _scroll_widget_visible(w)


def _activate_render_focus(app: Any) -> None:
    page = _render_tab_page(app)
    items = _collect_settings_focusables(page) if page is not None else []
    idx = int(getattr(app, "_deck_settings_focus_idx", 0))
    w = QApplication.focusWidget()
    if items and (
        w is None or page is None or not page.isAncestorOf(w)
    ):
        idx = max(0, min(len(items) - 1, idx))
        w = items[idx]
        w.setFocus(Qt.FocusReason.OtherFocusReason)
        app._deck_settings_focus_idx = idx
    if w is None:
        return
    _activate_widget(w)


def _activate_widget(w: QWidget) -> None:
    if isinstance(w, QAbstractButton):
        w.click()
        return
    if isinstance(w, QComboBox):
        if w.isEnabled():
            w.showPopup()
        return
    if isinstance(w, (QSpinBox, QLineEdit)):
        w.setFocus(Qt.FocusReason.OtherFocusReason)
        return
    if isinstance(w, QSlider):
        return
    click = getattr(w, "click", None)
    if callable(click):
        try:
            click()
        except Exception:
            _log.debug("Deck A: could not activate %r", w)


def _queue_sidebar(app: Any):
    return getattr(app, "_portable_queue_sidebar", None)


def _nav_render_queue(app: Any, delta: int) -> None:
    sidebar = _queue_sidebar(app)
    if sidebar is None:
        return
    fn = getattr(sidebar, "deck_select_relative", None)
    if callable(fn):
        fn(delta)


def _activate_render_queue(app: Any) -> None:
    sidebar = _queue_sidebar(app)
    if sidebar is None:
        return
    fn = getattr(sidebar, "deck_activate_selected", None)
    if callable(fn):
        fn()


def _confirm_clip_picker(app: Any) -> None:
    if not getattr(app, "library_has_item_selection", lambda: False)():
        return
    picker = getattr(app, "_portable_clip_picker_dlg", None)
    if picker is None:
        return
    armed = getattr(picker, "_armed", False)
    if not armed:
        return
    picker._armed = False
    try:
        picker.accept()
    except RuntimeError:
        pass
