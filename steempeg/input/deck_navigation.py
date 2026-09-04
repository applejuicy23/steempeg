"""D-pad / shoulder navigation for Portable sheets + app Settings."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QComboBox,
    QFrame,
    QLineEdit,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabBar,
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
_RENDER_ZONE_ACTIONS = "actions"
_RING_OBJECT = "DeckFocusRing"
_RING_ACCENT = "#b29ae7"
_ACTION_BUTTON_ATTRS = (
    "btn_start",
    "btn_leave",
    "btn_pause",
    "btn_cancel",
    "btn_logs",
)


def try_deck_navigation(app: Any, button: DeckButton) -> bool:
    """Handle sheet-local nav/focus. True = consumed (skip default dispatch)."""
    # App Settings is modal — it wins over Portable sheets while open.
    if getattr(app, "_app_settings_open", False):
        return _nav_app_settings(app, button)

    if getattr(app, "_portable_clip_picker_open", False):
        # Sort popup ▲▼ / A / B while open.
        if _nav_open_combo(app, button):
            return True
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
        if button == DeckButton.L2:
            app._deck_clip_multi = not bool(getattr(app, "_deck_clip_multi", False))
            _log.info(
                "Deck Choose a Clip multi-select %s",
                "on" if app._deck_clip_multi else "off",
            )
            return True
        # Toolbar chrome — only while the sheet is open.
        if button == DeckButton.Y:
            _picker_open_filters(app)
            return True
        if button == DeckButton.R2:
            _picker_open_sort(app)
            return True
        if button == DeckButton.VIEW:
            _picker_choose_folder(app)
            return True
        if button == DeckButton.MENU:
            _picker_refresh(app)
            return True
        if button == DeckButton.X:
            # Queue when a clip/export is selected; otherwise open folders (+).
            if _picker_can_queue(app):
                return False
            _picker_folders_plus(app)
            return True
        return False

    if getattr(app, "_portable_render_settings_open", False):
        return _nav_render_sheet(app, button)

    return False


def close_deck_picker_overlays(app: Any) -> bool:
    """B while Choose a Clip chrome is open — dismiss filter/sort first."""
    if not getattr(app, "_portable_clip_picker_open", False):
        return False
    menu = getattr(app, "filter_menu", None)
    if menu is not None:
        try:
            if menu.isVisible():
                menu.hide()
                return True
        except RuntimeError:
            pass
    combo = getattr(app, "combo_sort", None)
    if combo is not None and _combo_popup_visible(combo):
        combo.hidePopup()
        return True
    return False


def _picker_open_filters(app: Any) -> None:
    fn = getattr(app, "show_filter_menu", None)
    if callable(fn):
        try:
            fn()
        except Exception:
            _log.exception("Deck: open filters failed")


def _picker_open_sort(app: Any) -> None:
    combo = getattr(app, "combo_sort", None)
    if combo is None:
        return
    try:
        if not combo.isEnabled():
            return
        combo.setFocus(Qt.FocusReason.OtherFocusReason)
        combo.showPopup()
    except RuntimeError:
        pass


def _picker_choose_folder(app: Any) -> None:
    picker = getattr(app, "folder_picker", None)
    main = getattr(picker, "main_btn", None) if picker is not None else None
    if main is not None:
        try:
            main.click()
            return
        except RuntimeError:
            pass
    fn = getattr(app, "choose_folder", None)
    if callable(fn):
        fn()


def _picker_refresh(app: Any) -> None:
    btn = getattr(app, "btn_refresh", None)
    main = getattr(btn, "main_btn", None) if btn is not None else None
    if main is not None:
        try:
            main.click()
            return
        except RuntimeError:
            pass
    fn = getattr(app, "refresh_library", None)
    if callable(fn):
        fn()


def _picker_folders_plus(app: Any) -> None:
    picker = getattr(app, "folder_picker", None)
    add = getattr(picker, "add_btn", None) if picker is not None else None
    if add is not None and add.isVisible() and add.isEnabled():
        try:
            add.click()
            return
        except RuntimeError:
            pass
    fn = getattr(app, "show_folders_panel", None)
    if callable(fn):
        fn()


def _picker_can_queue(app: Any) -> bool:
    mode = getattr(app, "_library_panel_mode", "clips")
    if mode == "screenshots":
        return False
    return bool(getattr(app, "library_has_item_selection", lambda: False)())


def _nav_render_sheet(app: Any, button: DeckButton) -> bool:
    # Combo / Quality dual-popup first — never dump ◀ into Queue while open.
    if _nav_open_combo(app, button):
        return True

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
            return True
        if button == DeckButton.DPAD_LEFT:
            hide_deck_focus_ring(app)
            return True
        if button == DeckButton.A:
            _activate_render_queue(app)
            return True
        return False

    if zone == _RENDER_ZONE_ACTIONS:
        return _nav_render_actions(app, button)

    # Settings — L2 only jumps to Queue (◀ stays among fields).
    if button == DeckButton.L1:
        _cycle_render_tab(app, -1)
        return True
    if button == DeckButton.R1:
        _cycle_render_tab(app, 1)
        return True
    if button == DeckButton.DPAD_LEFT:
        _focus_settings_horizontal(app, -1)
        return True
    if button == DeckButton.DPAD_RIGHT:
        _focus_settings_horizontal(app, 1)
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


def _nav_render_actions(app: Any, button: DeckButton) -> bool:
    if button == DeckButton.DPAD_UP:
        _focus_actions_by_delta(app, -1)
        return True
    if button == DeckButton.DPAD_DOWN:
        _focus_actions_by_delta(app, 1)
        return True
    if button == DeckButton.DPAD_LEFT:
        # Stay on the strip — L2 is the only escape to Queue.
        _focus_actions_by_delta(app, -1)
        return True
    if button == DeckButton.DPAD_RIGHT:
        _focus_actions_by_delta(app, 1)
        return True
    if button == DeckButton.L1:
        _cycle_render_tab(app, -1)
        _set_render_zone(app, _RENDER_ZONE_SETTINGS)
        return True
    if button == DeckButton.R1:
        _cycle_render_tab(app, 1)
        _set_render_zone(app, _RENDER_ZONE_SETTINGS)
        return True
    if button == DeckButton.A:
        _activate_render_actions(app)
        return True
    return False


def _render_zone(app: Any) -> str:
    zone = getattr(app, "_deck_render_zone", _RENDER_ZONE_SETTINGS)
    if zone not in (
        _RENDER_ZONE_QUEUE,
        _RENDER_ZONE_SETTINGS,
        _RENDER_ZONE_ACTIONS,
    ):
        return _RENDER_ZONE_SETTINGS
    return zone


def _set_render_zone(app: Any, zone: str) -> None:
    app._deck_render_zone = zone
    if zone == _RENDER_ZONE_QUEUE:
        hide_deck_focus_ring(app)
        try:
            w = QApplication.focusWidget()
            page = _render_tab_page(app)
            strip = getattr(app, "_portable_render_strip", None)
            if w is not None and (
                (page is not None and page.isAncestorOf(w))
                or (strip is not None and strip.isAncestorOf(w))
            ):
                w.clearFocus()
        except RuntimeError:
            pass
        return
    if zone == _RENDER_ZONE_ACTIONS:
        app._deck_actions_focus_idx = 0
        _focus_actions_by_delta(app, 0)
        return
    _focus_settings_by_delta(app, 0)


def reset_render_deck_focus(app: Any) -> None:
    """Call when the Render sheet opens — settings panel is the default zone."""
    app._deck_render_zone = _RENDER_ZONE_SETTINGS
    app._deck_settings_focus_idx = 0
    hide_deck_focus_ring(app)
    QTimer.singleShot(0, lambda: _focus_settings_by_delta(app, 0))


def hide_deck_focus_ring(app: Any) -> None:
    ring = getattr(app, "_deck_focus_ring", None)
    if ring is not None:
        try:
            ring.hide()
        except RuntimeError:
            pass
        app._deck_focus_ring = None
    # Tab pages + Start strip + app Settings can each host a ring — hide orphans.
    hosts: list[QWidget] = []
    tabs = getattr(getattr(app, "ui", None), "settings_tabs", None)
    if tabs is not None:
        try:
            for i in range(tabs.count()):
                page = tabs.widget(i)
                if page is not None:
                    hosts.append(page)
        except RuntimeError:
            pass
    strip = getattr(app, "_portable_render_strip", None)
    if strip is not None:
        hosts.append(strip)
    settings_dlg = getattr(app, "_app_settings_dlg", None)
    if settings_dlg is not None:
        hosts.append(settings_dlg)
        content = _app_settings_content(app)
        if content is not None and content is not settings_dlg:
            hosts.append(content)
    for host in hosts:
        try:
            for orphan in host.findChildren(QFrame, _RING_OBJECT):
                try:
                    orphan.hide()
                except RuntimeError:
                    pass
        except RuntimeError:
            pass


def _ensure_focus_ring(host: QWidget) -> QFrame:
    ring = host.findChild(QFrame, _RING_OBJECT)
    if ring is None:
        ring = QFrame(host)
        ring.setObjectName(_RING_OBJECT)
        ring.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        ring.setStyleSheet(
            f"QFrame#{_RING_OBJECT} {{"
            f" border: 2px solid {_RING_ACCENT};"
            f" border-radius: 8px;"
            f" background: transparent;"
            f"}}"
        )
    return ring


def _focus_ring_host(app: Any, target: QWidget) -> QWidget | None:
    strip = getattr(app, "_portable_render_strip", None)
    if strip is not None and (
        target is strip or strip.isAncestorOf(target)
    ):
        return strip
    page = _render_tab_page(app)
    if page is not None and (
        target is page or page.isAncestorOf(target)
    ):
        return page
    dlg = getattr(app, "_portable_render_sheet_dlg", None)
    if dlg is not None and (
        target is dlg or dlg.isAncestorOf(target)
    ):
        return dlg
    settings_dlg = getattr(app, "_app_settings_dlg", None)
    if settings_dlg is not None and (
        target is settings_dlg or settings_dlg.isAncestorOf(target)
    ):
        content = _app_settings_content(app)
        if content is not None and (
            target is content or content.isAncestorOf(target)
        ):
            return content
        return settings_dlg
    return page


def _show_focus_ring(app: Any, target: QWidget) -> None:
    if target is None:
        hide_deck_focus_ring(app)
        return
    host = _focus_ring_host(app, target)
    if host is None:
        hide_deck_focus_ring(app)
        return
    try:
        hide_deck_focus_ring(app)
        ring = _ensure_focus_ring(host)
        app._deck_focus_ring = ring
        pad = 3
        tl = target.mapTo(host, QPoint(-pad, -pad))
        ring.setGeometry(
            tl.x(), tl.y(), target.width() + pad * 2, target.height() + pad * 2
        )
        ring.show()
        ring.raise_()
    except RuntimeError:
        hide_deck_focus_ring(app)


def _focused_combo(app: Any) -> QComboBox | None:
    w = QApplication.focusWidget()
    while w is not None:
        if isinstance(w, QComboBox):
            return w
        w = w.parentWidget()
    # Choose a Clip sort — popup may steal focus onto the list view.
    if getattr(app, "_portable_clip_picker_open", False):
        sort = getattr(app, "combo_sort", None)
        if isinstance(sort, QComboBox) and _combo_popup_visible(sort):
            return sort
    if getattr(app, "_app_settings_open", False):
        items = _collect_app_settings_focusables(app)
        idx = int(getattr(app, "_deck_app_settings_focus_idx", 0))
        if items and 0 <= idx < len(items) and isinstance(items[idx], QComboBox):
            return items[idx]
    idx = int(getattr(app, "_deck_settings_focus_idx", 0))
    page = _render_tab_page(app)
    items = _collect_settings_focusables(page) if page is not None else []
    if items and 0 <= idx < len(items) and isinstance(items[idx], QComboBox):
        return items[idx]
    return None


def _dual_quality_popup(combo: QComboBox):
    popup = getattr(combo, "_steempeg_dual_popup", None)
    if popup is None:
        return None
    try:
        if popup.isVisible():
            return popup
    except RuntimeError:
        return None
    return None


def _combo_popup_visible(combo: QComboBox) -> bool:
    if _dual_quality_popup(combo) is not None:
        return True
    view = combo.view()
    if view is None:
        return False
    try:
        return bool(view.isVisible())
    except RuntimeError:
        return False


def close_deck_combo_popup(app: Any) -> bool:
    """B while a settings combo is open — dismiss popup, keep the sheet."""
    combo = _focused_combo(app)
    if combo is None or not _combo_popup_visible(combo):
        return False
    combo.hidePopup()
    return True


def _nav_open_combo(app: Any, button: DeckButton) -> bool:
    """Drive an open QComboBox / Quality dual-popup. True = consumed."""
    combo = _focused_combo(app)
    if combo is None or not _combo_popup_visible(combo):
        return False

    dual = _dual_quality_popup(combo)
    if dual is not None:
        if button == DeckButton.A:
            dual.deck_confirm()
            return True
        if button == DeckButton.B:
            dual.hide()
            return True
        name = {
            DeckButton.DPAD_UP: "up",
            DeckButton.DPAD_DOWN: "down",
            DeckButton.DPAD_LEFT: "left",
            DeckButton.DPAD_RIGHT: "right",
        }.get(button)
        if name:
            dual.deck_navigate(name)
            return True
        return True

    count = combo.count()
    if button == DeckButton.A:
        combo.hidePopup()
        return True
    if button == DeckButton.B:
        combo.hidePopup()
        return True
    if count <= 0:
        return True
    idx = combo.currentIndex()
    if button == DeckButton.DPAD_UP:
        combo.setCurrentIndex(max(0, idx - 1))
        return True
    if button == DeckButton.DPAD_DOWN:
        combo.setCurrentIndex(min(count - 1, idx + 1))
        return True
    if button in (DeckButton.DPAD_LEFT, DeckButton.DPAD_RIGHT):
        return True
    return True


def _nav_combo_popup(app: Any, button: DeckButton) -> bool:
    """Legacy name — D-pad only path used by older call sites."""
    if button not in _DPAD:
        return False
    return _nav_open_combo(app, button)


def _focus_settings_horizontal(app: Any, direction: int) -> None:
    """◀▶ among controls on roughly the same row — never jumps to Queue."""
    page = _render_tab_page(app)
    if page is None:
        return
    items = _collect_settings_focusables(page)
    if not items:
        return
    cur = int(getattr(app, "_deck_settings_focus_idx", 0))
    cur = max(0, min(len(items) - 1, cur))
    origin = items[cur]
    try:
        o_tl = origin.mapToGlobal(origin.rect().topLeft())
        o_cx = o_tl.x() + origin.width() // 2
        o_cy = o_tl.y() + origin.height() // 2
        row_slop = max(28, origin.height())
    except RuntimeError:
        return

    best_i = None
    best_score = None
    for i, other in enumerate(items):
        if i == cur:
            continue
        try:
            t_tl = other.mapToGlobal(other.rect().topLeft())
            t_cx = t_tl.x() + other.width() // 2
            t_cy = t_tl.y() + other.height() // 2
        except RuntimeError:
            continue
        if abs(t_cy - o_cy) > row_slop:
            continue
        dx = t_cx - o_cx
        if direction < 0 and dx >= 0:
            continue
        if direction > 0 and dx <= 0:
            continue
        score = abs(dx) + abs(t_cy - o_cy) * 2
        if best_score is None or score < best_score:
            best_score = score
            best_i = i

    if best_i is None:
        return
    app._deck_settings_focus_idx = best_i
    w = items[best_i]
    w.setFocus(Qt.FocusReason.OtherFocusReason)
    _scroll_widget_visible(w)
    _show_focus_ring(app, w)


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
                multi = bool(getattr(app, "_deck_clip_multi", False))
                mods = (
                    Qt.KeyboardModifier.ControlModifier
                    if multi
                    else Qt.KeyboardModifier.NoModifier
                )
                fn(item, force_single=not multi, mods=mods)
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
    """L1/R1 — switch Source/Video/… by index (not neo-button .click())."""
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
        hide_deck_focus_ring(app)
        # Direct tab switch — neo pills sync via currentChanged (setChecked).
        # Avoid btn.click(): same setCurrentIndex, but goes through QAbstractButton
        # press/release and can steal focus / flash in Portable.
        if tabs.currentIndex() != idx:
            tabs.setCurrentIndex(idx)
        elif btn is not None and not btn.isChecked():
            btn.setChecked(True)
        app._deck_settings_focus_idx = 0
        # Wait for the stacked page to become current before painting the ring.
        QTimer.singleShot(0, lambda a=app: _focus_settings_by_delta(a, 0))
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
        if w.objectName() == _RING_OBJECT:
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

    parent_ids = {id(w) for w in found}

    def _nested(widget: QWidget) -> bool:
        p = widget.parentWidget()
        while p is not None and p is not page:
            if id(p) in parent_ids:
                return True
            p = p.parentWidget()
        return False

    found = [w for w in found if not _nested(w)]

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
        # No fields on this tab — ▼ still reaches Start.
        if delta > 0:
            _set_render_zone(app, _RENDER_ZONE_ACTIONS)
        else:
            hide_deck_focus_ring(app)
        return
    cur = int(getattr(app, "_deck_settings_focus_idx", 0))
    if delta == 0:
        nxt = max(0, min(len(items) - 1, cur))
    elif delta > 0 and cur >= len(items) - 1:
        _set_render_zone(app, _RENDER_ZONE_ACTIONS)
        return
    elif delta < 0 and cur <= 0:
        nxt = 0
    else:
        nxt = max(0, min(len(items) - 1, cur + delta))
    app._deck_settings_focus_idx = nxt
    w = items[nxt]
    w.setFocus(Qt.FocusReason.OtherFocusReason)
    _scroll_widget_visible(w)
    _show_focus_ring(app, w)


def _collect_action_focusables(app: Any) -> list[QWidget]:
    strip = getattr(app, "_portable_render_strip", None)
    if strip is None:
        return []
    found: list[QWidget] = []
    for attr in _ACTION_BUTTON_ATTRS:
        btn = getattr(strip, attr, None)
        if btn is None:
            continue
        try:
            if not btn.isVisible() or not btn.isEnabled():
                continue
        except RuntimeError:
            continue
        found.append(btn)
    return found


def _focus_actions_by_delta(app: Any, delta: int) -> None:
    items = _collect_action_focusables(app)
    if not items:
        hide_deck_focus_ring(app)
        app._deck_render_zone = _RENDER_ZONE_SETTINGS
        _focus_settings_by_delta(app, 0)
        return
    cur = int(getattr(app, "_deck_actions_focus_idx", 0))
    if delta == 0:
        nxt = max(0, min(len(items) - 1, cur))
    elif delta < 0 and cur <= 0:
        # ▲ on Start → last settings control.
        app._deck_render_zone = _RENDER_ZONE_SETTINGS
        page = _render_tab_page(app)
        settings = _collect_settings_focusables(page) if page is not None else []
        if settings:
            app._deck_settings_focus_idx = len(settings) - 1
            _focus_settings_by_delta(app, 0)
        else:
            hide_deck_focus_ring(app)
        return
    else:
        nxt = max(0, min(len(items) - 1, cur + delta))
    app._deck_actions_focus_idx = nxt
    w = items[nxt]
    w.setFocus(Qt.FocusReason.OtherFocusReason)
    _show_focus_ring(app, w)


def _activate_render_actions(app: Any) -> None:
    items = _collect_action_focusables(app)
    idx = int(getattr(app, "_deck_actions_focus_idx", 0))
    if not items:
        return
    idx = max(0, min(len(items) - 1, idx))
    app._deck_actions_focus_idx = idx
    w = items[idx]
    w.setFocus(Qt.FocusReason.OtherFocusReason)
    _show_focus_ring(app, w)
    _activate_widget(w)


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
        _show_focus_ring(app, w)
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
    hide_deck_focus_ring(app)
    sidebar = _queue_sidebar(app)
    if sidebar is None:
        return
    fn = getattr(sidebar, "deck_select_relative", None)
    if callable(fn):
        fn(delta)


def _activate_render_queue(app: Any) -> None:
    hide_deck_focus_ring(app)
    sidebar = _queue_sidebar(app)
    if sidebar is None:
        return
    fn = getattr(sidebar, "deck_activate_selected", None)
    if callable(fn):
        fn()


def _confirm_clip_picker(app: Any) -> None:
    """A in Choose a Clip — open the highlighted card, then dismiss the sheet."""
    picker = getattr(app, "_portable_clip_picker_dlg", None)
    if picker is None:
        return

    mode = getattr(app, "_library_panel_mode", "clips")

    if mode == "screenshots":
        grid = getattr(app, "grid_screenshots", None)
        items = list(grid.selectedItems()) if grid is not None else []
        if not items:
            return
        path = items[0].data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        open_fn = getattr(app, "_on_screenshot_open", None)
        if not callable(open_fn):
            return
        open_fn(str(path))
    else:
        # Clips / Rendered — selection already loads preview; A closes the sheet.
        if not getattr(app, "library_has_item_selection", lambda: False)():
            return

    picker._armed = False
    app._deck_clip_multi = False
    try:
        picker.accept()
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# App Settings dialog (modal) — same pad language as Render settings.
# ---------------------------------------------------------------------------


def reset_app_settings_deck_focus(app: Any) -> None:
    """Paint the purple ring on the first control when Settings opens."""
    app._deck_app_settings_focus_idx = 0
    hide_deck_focus_ring(app)
    QTimer.singleShot(0, lambda: _focus_app_settings_by_delta(app, 0))


def _nav_app_settings(app: Any, button: DeckButton) -> bool:
    """D-pad / shoulders / A inside the modal Settings dialog."""
    if _nav_open_combo(app, button):
        return True

    if button == DeckButton.L1:
        _cycle_app_settings_tab(app, -1)
        return True
    if button == DeckButton.R1:
        _cycle_app_settings_tab(app, 1)
        return True
    if button == DeckButton.DPAD_LEFT:
        _focus_app_settings_horizontal(app, -1)
        return True
    if button == DeckButton.DPAD_RIGHT:
        _focus_app_settings_horizontal(app, 1)
        return True
    if button == DeckButton.DPAD_UP:
        _focus_app_settings_by_delta(app, -1)
        return True
    if button == DeckButton.DPAD_DOWN:
        _focus_app_settings_by_delta(app, 1)
        return True
    if button == DeckButton.A:
        _activate_app_settings_focus(app)
        return True
    # Modal: swallow other face/shoulder buttons so theatre map does not fire.
    return True


def _app_settings_content(app: Any) -> QWidget | None:
    """Inner widget of the current Settings tab scroll page."""
    dlg = getattr(app, "_app_settings_dlg", None)
    tabs = getattr(dlg, "_settings_tabs", None) if dlg is not None else None
    if tabs is None:
        return None
    try:
        page = tabs.currentWidget()
    except RuntimeError:
        return None
    if page is None:
        return None
    if isinstance(page, QScrollArea):
        inner = page.widget()
        return inner if inner is not None else page
    return page


def _under_tab_bar(widget: QWidget) -> bool:
    p = widget.parentWidget()
    while p is not None:
        if isinstance(p, QTabBar):
            return True
        p = p.parentWidget()
    return False


def _collect_app_settings_focusables(app: Any) -> list[QWidget]:
    """Current tab fields + Cancel / Save footer."""
    content = _app_settings_content(app)
    items: list[QWidget] = []
    if content is not None:
        items = [
            w
            for w in _collect_settings_focusables(content)
            if not _under_tab_bar(w)
        ]

    dlg = getattr(app, "_app_settings_dlg", None)
    if dlg is not None:
        for attr in ("_btn_cancel", "_btn_save"):
            btn = getattr(dlg, attr, None)
            if btn is None:
                continue
            try:
                if not btn.isVisible() or not btn.isEnabled():
                    continue
            except RuntimeError:
                continue
            if btn not in items:
                items.append(btn)
    return items


def _cycle_app_settings_tab(app: Any, delta: int) -> None:
    dlg = getattr(app, "_app_settings_dlg", None)
    tabs: QTabWidget | None = (
        getattr(dlg, "_settings_tabs", None) if dlg is not None else None
    )
    if tabs is None or tabs.count() <= 0:
        return
    count = tabs.count()
    cur = tabs.currentIndex()
    nxt = (cur + delta) % count
    hide_deck_focus_ring(app)
    if tabs.currentIndex() != nxt:
        tabs.setCurrentIndex(nxt)
    app._deck_app_settings_focus_idx = 0
    QTimer.singleShot(0, lambda a=app: _focus_app_settings_by_delta(a, 0))


def _focus_app_settings_by_delta(app: Any, delta: int) -> None:
    items = _collect_app_settings_focusables(app)
    if not items:
        hide_deck_focus_ring(app)
        return
    cur = int(getattr(app, "_deck_app_settings_focus_idx", 0))
    if delta == 0:
        nxt = max(0, min(len(items) - 1, cur))
    else:
        nxt = max(0, min(len(items) - 1, cur + delta))
    app._deck_app_settings_focus_idx = nxt
    w = items[nxt]
    w.setFocus(Qt.FocusReason.OtherFocusReason)
    _scroll_widget_visible(w)
    _show_focus_ring(app, w)


def _focus_app_settings_horizontal(app: Any, direction: int) -> None:
    items = _collect_app_settings_focusables(app)
    if not items:
        return
    cur = int(getattr(app, "_deck_app_settings_focus_idx", 0))
    cur = max(0, min(len(items) - 1, cur))
    origin = items[cur]
    try:
        o_tl = origin.mapToGlobal(origin.rect().topLeft())
        o_cx = o_tl.x() + origin.width() // 2
        o_cy = o_tl.y() + origin.height() // 2
        row_slop = max(28, origin.height())
    except RuntimeError:
        return

    best_i = None
    best_score = None
    for i, other in enumerate(items):
        if i == cur:
            continue
        try:
            t_tl = other.mapToGlobal(other.rect().topLeft())
            t_cx = t_tl.x() + other.width() // 2
            t_cy = t_tl.y() + other.height() // 2
        except RuntimeError:
            continue
        if abs(t_cy - o_cy) > row_slop:
            continue
        dx = t_cx - o_cx
        if direction < 0 and dx >= 0:
            continue
        if direction > 0 and dx <= 0:
            continue
        score = abs(dx) + abs(t_cy - o_cy) * 2
        if best_score is None or score < best_score:
            best_score = score
            best_i = i

    if best_i is None:
        return
    app._deck_app_settings_focus_idx = best_i
    w = items[best_i]
    w.setFocus(Qt.FocusReason.OtherFocusReason)
    _scroll_widget_visible(w)
    _show_focus_ring(app, w)


def _activate_app_settings_focus(app: Any) -> None:
    items = _collect_app_settings_focusables(app)
    idx = int(getattr(app, "_deck_app_settings_focus_idx", 0))
    w = QApplication.focusWidget()
    dlg = getattr(app, "_app_settings_dlg", None)
    in_dialog = False
    if w is not None and dlg is not None:
        try:
            in_dialog = w is dlg or dlg.isAncestorOf(w)
        except RuntimeError:
            in_dialog = False
    if items and (w is None or not in_dialog):
        idx = max(0, min(len(items) - 1, idx))
        w = items[idx]
        w.setFocus(Qt.FocusReason.OtherFocusReason)
        app._deck_app_settings_focus_idx = idx
        _show_focus_ring(app, w)
    elif items and w is not None:
        try:
            if w in items:
                app._deck_app_settings_focus_idx = items.index(w)
        except ValueError:
            pass
    if w is None:
        return
    _activate_widget(w)
