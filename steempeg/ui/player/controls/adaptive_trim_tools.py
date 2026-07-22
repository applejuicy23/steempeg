"""Adaptive Trim tools placement: left of Trim when roomy, drop below when tight.

Trim/Cancel always stays on the footer baseline. In drop-below mode the tools
pill is an overlay under the button (small gap) — it must not inflate the row
or shove Trim upward.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QHBoxLayout, QWidget

# Steam Deck landscape and similarly narrow shells.
_NARROW_SHELL_W = 1280
_DROP_GAP_PX = 10
_TIMER_CUSHION_PX = 100


def sync_trim_tools_placement(app) -> None:
    """Pick left-of-Trim vs drop-below and apply without breaking the baseline."""
    trim = getattr(app, "btn_trim", None)
    tools = getattr(app, "trim_tools_pill", None)
    if trim is None or tools is None:
        return

    # Tear down legacy VBox cluster from the first portable trim attempt.
    _dissolve_legacy_cluster(app, trim, tools)

    want_below = _should_drop_below(app)
    mode = getattr(app, "_trim_tools_placement", None)

    if want_below:
        if mode != "below":
            _place_tools_below(app, trim, tools)
        elif tools.isVisible():
            _reposition_tools_below(app, trim, tools)
    else:
        if mode != "left":
            _place_tools_left(app, trim, tools)

    active = _trim_mode_active(app)
    tools.setVisible(active)
    if active and getattr(app, "_trim_tools_placement", None) == "below":
        _reposition_tools_below(app, trim, tools)
        tools.raise_()


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


def _should_drop_below(app) -> bool:
    """Portable + tight width / crowded right rail → tools under Trim."""
    if not getattr(app, "_portable_shell", False):
        return False

    ui = getattr(app, "ui", None)
    win_w = int(ui.width()) if ui is not None else 0
    if win_w <= _NARROW_SHELL_W:
        return True

    row = getattr(app, "_footer_controls_row", None)
    tools = getattr(app, "trim_tools_pill", None)
    if row is None or tools is None or row.width() <= 0:
        return False

    tools_w = max(tools.sizeHint().width(), 120)
    right = getattr(row, "_right", None)
    if right is None or right.layout() is None:
        return False

    packed = tools_w + 10
    for name in (
        "btn_add_marker",
        "btn_screenshot",
        "btn_trim",
        "btn_portable_render",
        "pill_container",
    ):
        wdg = getattr(app, name, None)
        if wdg is None:
            continue
        packed += max(wdg.sizeHint().width(), 24) + 10

    usable = max(0, row.width() // 2 - _TIMER_CUSHION_PX)
    return packed > usable


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
    x = int(bottom_center.x() - tw // 2)
    y = int(bottom_center.y() + _DROP_GAP_PX)
    x = max(0, min(x, max(0, overlay.width() - tw)))
    tools.setGeometry(x, y, tw, th)
    tools.raise_()
