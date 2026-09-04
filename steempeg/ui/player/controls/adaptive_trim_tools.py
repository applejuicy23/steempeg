"""Adaptive player-footer chrome: Trim tools + marker pill placement.

Trim/Cancel always stays on the footer baseline. Compression order when Trim
is ON and the L/R splitters squeeze the player column:

1. First — Trim tools pill (cut start / cut end / reset) drops under Trim
   (Cancel). Rearrange; do not shrink chips.
2. Only later — if the right rail is still too close to the centered
   timestamp / play / ±15s dials, marker + marker-settings drop under the
   theater/fullscreen pill.

When both pills sit on the shared bottom row, markers share the same Y as
the trim-tool circles. Markers alone under theater/fs stay anchored to that
cluster.

Portable shell (``_portable_shell``): markers always inline on the footer row;
trim tools use the same width/crowding drop-below rule as desktop (narrow shell
or crowded right rail). Desktop compressed width keeps the adaptive two-step
squeeze above.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QHBoxLayout, QSpacerItem, QSizePolicy, QWidget

# Steam Deck landscape and similarly narrow shells.
_NARROW_SHELL_W = 1280
_DROP_GAP_PX = 10
_TIMER_CUSHION_PX = 100
# Gap between trim tools and Trim / marker cluster when markers are stacked.
_TRIM_LEFT_NUDGE_PX = 28


def _is_portable_shell(app) -> bool:
    return bool(getattr(app, "_portable_shell", False))


def sync_trim_tools_placement(app) -> None:
    """Sync Trim tools then marker pill for the current footer width."""
    trim = getattr(app, "btn_trim", None)
    tools = getattr(app, "trim_tools_pill", None)
    markers = getattr(app, "marker_pill", None)
    if trim is None or tools is None:
        return

    # Tear down legacy VBox cluster from the first portable trim attempt.
    _dissolve_legacy_cluster(app, trim, tools)

    # Compress priority: tools first, markers only after tools have dropped.
    want_below = _should_drop_below(app)
    mode = getattr(app, "_trim_tools_placement", None)

    if want_below:
        if mode != "below":
            _place_tools_below(app, trim, tools)
        elif tools.isVisible() or _trim_mode_active(app):
            _reposition_tools_below(app, trim, tools)
    else:
        if mode != "left":
            _place_tools_left(app, trim, tools)

    active = _trim_mode_active(app)
    _apply_trim_tools_visibility(app, tools, trim, active)

    if active and getattr(app, "_trim_tools_placement", None) == "below":
        _reposition_tools_below(app, trim, tools)
        tools.raise_()

    if markers is not None:
        _sync_marker_pill_placement(app, markers)
        if getattr(app, "_marker_pill_placement", None) == "below":
            pill = getattr(app, "pill_container", None)
            if pill is not None:
                _reposition_markers_below(app, markers, pill)
                markers.raise_()


def _apply_trim_tools_visibility(app, tools: QWidget, trim: QWidget, active: bool) -> None:
    """Show/hide trim tools with a short fade (works for left and below)."""
    from steempeg.ui.player.controls.footer_pill_anim import animate_footer_overlay_widget

    was = bool(tools.isVisible())
    if active and was:
        _sync_trim_tools_nudge(app, tools, trim, True)
        return
    if (not active) and (not was):
        _sync_trim_tools_nudge(app, tools, trim, False)
        return

    if active:
        # Layout first so geometry/sizeHint are correct, then fade in.
        tools.setVisible(True)
        _sync_trim_tools_nudge(app, tools, trim, True)
        final = None
        if getattr(app, "_trim_tools_placement", None) == "below":
            _reposition_tools_below(app, trim, tools)
            final = tools.geometry()
        animate_footer_overlay_widget(tools, show=True, final_geom=final)
    else:
        _sync_trim_tools_nudge(app, tools, trim, False)
        animate_footer_overlay_widget(tools, show=False)


def ensure_adaptive_trim_hook(app) -> None:
    """Wire footer resize → placement sync (idempotent)."""
    row = getattr(app, "_footer_controls_row", None)
    if row is None or getattr(row, "_trim_tools_hooked", False):
        return
    row.on_resized = lambda: sync_trim_tools_placement(app)
    row._trim_tools_hooked = True


def _trim_mode_active(app) -> bool:
    canvas = getattr(getattr(app, "custom_timeline", None), "canvas", None)
    if canvas is not None and bool(getattr(canvas, "is_trim_mode", False)):
        return True
    trim = getattr(app, "btn_trim", None)
    if trim is None:
        return False
    return "cancel" in (trim.text() or "").lower()


def _packed_right_width(app, *, include_tools: bool, include_markers: bool) -> int:
    """Approximate width of the right chrome rail (hints + gaps)."""
    packed = 0
    names: list[str] = []
    if include_markers:
        names.extend(("btn_add_marker", "btn_marker_settings", "marker_pill"))
    names.extend(("btn_screenshot", "btn_trim", "btn_portable_render", "pill_container"))
    if include_tools:
        names.insert(0, "trim_tools_pill")

    seen: set[int] = set()
    for name in names:
        wdg = getattr(app, name, None)
        if wdg is None:
            continue
        wid = id(wdg)
        if wid in seen:
            continue
        # marker_pill already spans add+settings — prefer the pill once.
        if name in ("btn_add_marker", "btn_marker_settings") and getattr(
            app, "marker_pill", None
        ) is not None:
            continue
        seen.add(wid)
        packed += max(wdg.sizeHint().width(), 24) + 10
    return packed


def _usable_right_half(app) -> int:
    row = getattr(app, "_footer_controls_row", None)
    if row is None or row.width() <= 0:
        return 0
    return max(0, row.width() // 2 - _TIMER_CUSHION_PX)


def _should_drop_below(app) -> bool:
    """Tight width / crowded right rail → tools under Trim.

    First compress step when Trim is ON — drop tools when the window is narrow
    or the right chrome would collide with the centered timer. Markers already
    stacked below are excluded from packed width so tools can still decide
    independently. Portable uses the same rule; markers never stack there.
    """
    ui = getattr(app, "ui", None)
    win_w = int(ui.width()) if ui is not None else 0
    if win_w <= _NARROW_SHELL_W:
        return True

    row = getattr(app, "_footer_controls_row", None)
    tools = getattr(app, "trim_tools_pill", None)
    if row is None or tools is None or row.width() <= 0:
        return False

    markers_below = getattr(app, "_marker_pill_placement", None) == "below"
    packed = _packed_right_width(
        app,
        include_tools=True,
        include_markers=not markers_below,
    )
    usable = _usable_right_half(app)
    return packed > usable


def _should_stack_markers(app) -> bool:
    """Stack markers only after tools have already relieved the rail.

    Portable: never stack — markers stay inline. Desktop second compress
    step: ignore trim-tools width (they sit under Trim or are hidden) so
    markers do not drop earlier than the tools pill.
    """
    if _is_portable_shell(app):
        return False

    ui = getattr(app, "ui", None)
    win_w = int(ui.width()) if ui is not None else 0
    if win_w <= _NARROW_SHELL_W:
        return True

    row = getattr(app, "_footer_controls_row", None)
    markers = getattr(app, "marker_pill", None)
    if row is None or markers is None or row.width() <= 0:
        return False

    # While Trim is on and tools still belong inline, prefer dropping tools
    # first — do not stack markers in the same squeeze step.
    if _trim_mode_active(app) and getattr(app, "_trim_tools_placement", None) != "below":
        if _should_drop_below(app):
            return False

    # Tools are excluded: either already below, not active, or not needed yet.
    packed = _packed_right_width(
        app, include_tools=False, include_markers=True
    )
    return packed > _usable_right_half(app)


def _sync_marker_pill_placement(app, markers: QWidget) -> None:
    pill = getattr(app, "pill_container", None)
    if pill is None:
        return

    want_below = _should_stack_markers(app)
    mode = getattr(app, "_marker_pill_placement", None)

    if want_below:
        if mode != "below":
            _place_markers_below(app, markers, pill)
        else:
            _reposition_markers_below(app, markers, pill)
    else:
        if mode != "inline":
            _place_markers_inline(app, markers)


def _right_host(trim: QWidget) -> tuple[QWidget | None, QHBoxLayout | None]:
    host = trim.parentWidget()
    while host is not None:
        lay = host.layout()
        if isinstance(lay, QHBoxLayout):
            return host, lay
        host = host.parentWidget()
    return None, None


def _dissolve_legacy_cluster(app, trim: QWidget, tools: QWidget) -> None:
    cluster = getattr(app, "_portable_trim_cluster", None)
    if cluster is None:
        return
    host, layout = _right_host(cluster) if cluster.parentWidget() else (None, None)
    if layout is None:
        host, layout = _right_host(trim)
    if layout is None:
        app._portable_trim_cluster = None
        app._portable_trim_stacked = False
        return

    idx = layout.indexOf(cluster)
    cl = cluster.layout()
    if cl is not None:
        if cl.indexOf(tools) >= 0:
            cl.removeWidget(tools)
        if cl.indexOf(trim) >= 0:
            cl.removeWidget(trim)
    if idx >= 0:
        layout.removeWidget(cluster)
        layout.insertWidget(idx, trim, 0, Qt.AlignmentFlag.AlignVCenter)
    cluster.deleteLater()
    app._portable_trim_cluster = None
    app._portable_trim_stacked = False
    if getattr(app, "_trim_tools_placement", None) is None:
        app._trim_tools_placement = None  # force re-place next


def _place_tools_left(app, trim: QWidget, tools: QWidget) -> None:
    host, layout = _right_host(trim)
    if host is None or layout is None:
        return

    if tools.parentWidget() is not host:
        tools.setParent(host)

    # Clear drop-below fixed size so the pill can layout normally again.
    tools.setMinimumSize(0, 0)
    tools.setMaximumSize(16777215, 16777215)

    if layout.indexOf(tools) >= 0:
        layout.removeWidget(tools)

    trim_idx = layout.indexOf(trim)
    if trim_idx < 0:
        layout.addWidget(trim, 0, Qt.AlignmentFlag.AlignVCenter)
        trim_idx = layout.indexOf(trim)

    layout.insertWidget(trim_idx, tools, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    app._trim_tools_placement = "left"


def _place_tools_below(app, trim: QWidget, tools: QWidget) -> None:
    host, layout = _right_host(trim)
    if layout is not None and layout.indexOf(tools) >= 0:
        layout.removeWidget(tools)
    if layout is not None:
        layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    overlay = _overlay_host(app, trim)
    tools.setParent(overlay)
    app._trim_tools_placement = "below"
    _reposition_tools_below(app, trim, tools)


def _overlay_host(app, trim: QWidget) -> QWidget:
    footer = getattr(app, "player_footer_frame", None)
    if footer is not None:
        return footer
    row = getattr(app, "_footer_controls_row", None)
    if row is not None:
        return row
    return trim.window()


def _tools_left_nudge(app) -> int:
    if getattr(app, "_marker_pill_placement", None) != "below":
        return 0
    return _TRIM_LEFT_NUDGE_PX


def _reposition_tools_below(app, trim: QWidget, tools: QWidget) -> None:
    if getattr(app, "_trim_tools_placement", None) != "below":
        return
    overlay = tools.parentWidget()
    if overlay is None:
        return

    hint = tools.sizeHint()
    tw = max(hint.width(), tools.minimumSizeHint().width(), 120)
    th = max(hint.height(), tools.minimumSizeHint().height(), 40)
    bottom_center = trim.mapTo(
        overlay, QPoint(trim.width() // 2, trim.height())
    )
    x = int(bottom_center.x() - tw // 2) - _tools_left_nudge(app)
    y = int(bottom_center.y() + _DROP_GAP_PX)
    x = max(0, min(x, max(0, overlay.width() - tw)))
    tools.setGeometry(x, y, tw, th)
    tools.raise_()


def _sync_trim_tools_nudge(app, tools: QWidget, trim: QWidget, active: bool) -> None:
    """When markers sit under theater/fs, keep left-of-Trim tools clear of them."""
    host, layout = _right_host(trim)
    if layout is None:
        return

    want = (
        active
        and getattr(app, "_trim_tools_placement", None) == "left"
        and getattr(app, "_marker_pill_placement", None) == "below"
        and tools.isVisible()
    )
    spacer = getattr(app, "_trim_tools_nudge_spacer", None)

    if not want:
        if spacer is not None:
            layout.removeItem(spacer)
            app._trim_tools_nudge_spacer = None
        return

    tools_idx = layout.indexOf(tools)
    trim_idx = layout.indexOf(trim)
    if tools_idx < 0 or trim_idx < 0 or tools_idx >= trim_idx:
        return

    if spacer is None:
        spacer = QSpacerItem(
            _TRIM_LEFT_NUDGE_PX,
            1,
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Minimum,
        )
        app._trim_tools_nudge_spacer = spacer

    # Spacer between tools and Trim pushes tools left on a right-aligned rail.
    layout.removeItem(spacer)
    trim_idx = layout.indexOf(trim)
    if trim_idx >= 0:
        layout.insertItem(trim_idx, spacer)


def _place_markers_below(app, markers: QWidget, pill: QWidget) -> None:
    host, layout = _right_host(pill)
    if layout is not None and layout.indexOf(markers) >= 0:
        layout.removeWidget(markers)
    if layout is not None:
        layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    overlay = _overlay_host(app, pill)
    markers.setParent(overlay)
    markers.show()
    app._marker_pill_placement = "below"
    _reposition_markers_below(app, markers, pill)


def _markers_below_target_rect(app, markers: QWidget, pill: QWidget) -> QRect:
    """Target geometry for markers under theater/fs (overlay coords)."""
    overlay = markers.parentWidget()
    if overlay is None:
        overlay = _overlay_host(app, pill)
    hint = markers.sizeHint()
    mw = max(hint.width(), markers.minimumSizeHint().width(), 90)
    mh = max(hint.height(), markers.minimumSizeHint().height(), 40)
    if markers.width() > 0:
        mw = max(mw, markers.width())
    if markers.height() > 0:
        mh = max(mh, markers.height())
    pill_center = pill.mapTo(overlay, pill.rect().center())
    x = int(pill_center.x() - mw // 2)
    y = _marker_stack_y(app, overlay, pill, mh)
    x = max(0, min(x, max(0, overlay.width() - mw)))
    return QRect(x, y, mw, mh)


def _place_markers_inline(app, markers: QWidget) -> None:
    screenshot = getattr(app, "btn_screenshot", None)
    trim = getattr(app, "btn_trim", None)
    pill = getattr(app, "pill_container", None)
    anchor = screenshot or trim or pill
    if anchor is None:
        return
    host, layout = _right_host(anchor)
    if host is None or layout is None:
        return

    if markers.parentWidget() is not host:
        markers.setParent(host)

    markers.setMinimumSize(0, 0)
    markers.setMaximumSize(16777215, 16777215)

    if layout.indexOf(markers) >= 0:
        layout.removeWidget(markers)

    # Original order: … marker | screenshot | tools | trim | theater/fs
    if screenshot is not None and layout.indexOf(screenshot) >= 0:
        layout.insertWidget(
            layout.indexOf(screenshot), markers, 0, Qt.AlignmentFlag.AlignVCenter
        )
    elif trim is not None and layout.indexOf(trim) >= 0:
        layout.insertWidget(
            layout.indexOf(trim), markers, 0, Qt.AlignmentFlag.AlignVCenter
        )
    else:
        layout.addWidget(markers, 0, Qt.AlignmentFlag.AlignVCenter)

    layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    app._marker_pill_placement = "inline"
    markers.show()


def _overlay_row_top_y(app, overlay: QWidget) -> int | None:
    """Top Y of the shared bottom overlay row (Trim/Cancel baseline + gap).

    Trim tools drop from the Trim button bottom, not the taller theater/fs pill.
    Stacked markers must use the same anchor when trim tools are hidden so the
    bottom row stays level across Trim on/off.
    """
    trim = getattr(app, "btn_trim", None)
    if trim is not None and trim.isVisible():
        anchor = trim.mapTo(overlay, QPoint(trim.width() // 2, trim.height()))
        return int(anchor.y() + _DROP_GAP_PX)

    row = getattr(app, "_footer_controls_row", None)
    if row is not None and row.isVisible():
        anchor = row.mapTo(overlay, QPoint(0, row.height()))
        return int(anchor.y() + _DROP_GAP_PX)
    return None


def _overlay_row_height(app) -> int:
    tools = getattr(app, "trim_tools_pill", None)
    markers = getattr(app, "marker_pill", None)
    heights = [40]
    for w in (tools, markers):
        if w is None:
            continue
        if w.height() > 0:
            heights.append(w.height())
        heights.append(w.sizeHint().height())
        heights.append(w.minimumSizeHint().height())
    return max(heights)


def _marker_stack_y(app, overlay: QWidget, pill: QWidget, mh: int) -> int:
    """Y for stacked markers: Trim/Cancel baseline (+ gap), never theater/fs bottom.

    Theater/fs pill is taller than Trim — anchoring under it drops markers too low
    when Trim tools are hidden. Always match the row Trim tools would use.
    """
    del pill  # kept for call-site compatibility
    tools = getattr(app, "trim_tools_pill", None)
    if (
        tools is not None
        and tools.isVisible()
        and getattr(app, "_trim_tools_placement", None) == "below"
        and tools.parentWidget() is overlay
    ):
        th = max(tools.height(), 1)
        return int(tools.y() + (th - mh) // 2)

    row_top = _overlay_row_top_y(app, overlay)
    if row_top is not None:
        return int(row_top + max(0, (_overlay_row_height(app) - mh) // 2))

    # Last resort: still Trim button, not theater/fs.
    trim = getattr(app, "btn_trim", None)
    if trim is not None:
        anchor = trim.mapTo(overlay, QPoint(trim.width() // 2, trim.height()))
        return int(anchor.y() + _DROP_GAP_PX)
    return _DROP_GAP_PX


def _reposition_markers_below(app, markers: QWidget, pill: QWidget) -> None:
    if getattr(app, "_marker_pill_placement", None) != "below":
        return
    if markers.parentWidget() is None:
        return
    markers.setGeometry(_markers_below_target_rect(app, markers, pill))
    markers.raise_()
