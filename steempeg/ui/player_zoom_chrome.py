"""Player-header loupe + Vegas-style preview zoom (mpv scale / pan).

Preview only — never touches export / FFmpeg / queue math.
Zoom/pan reset on clip change; nothing is persisted across sessions.

Loupe chip = arm/disarm scroll-wheel zoom on the video surface.
% chip = discrete ladder (or shows the live wheel level).
"""
from __future__ import annotations

import logging
import math

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QActionGroup, QCursor
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QSizePolicy, QWidget

from steempeg.ui import design_tokens as tok
from steempeg.ui import ui_theme as ut

ZOOM_LADDER: tuple[int, ...] = (100, 125, 150, 200, 300)
DEFAULT_ZOOM_PCT = 100
ZOOM_MIN_PCT = 100
ZOOM_MAX_PCT = 400
# One notch of the mouse wheel ≈ this many percent.
ZOOM_WHEEL_STEP_PCT = 10

_LOG = logging.getLogger(__name__)


def clamp_zoom_pct(value: object | None) -> int:
    """Continuous zoom percent (wheel / live level), clamped to the allowed range."""
    try:
        pct = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_ZOOM_PCT
    return max(ZOOM_MIN_PCT, min(ZOOM_MAX_PCT, pct))


def snap_zoom_pct(value: object | None) -> int:
    """Snap to the nearest ladder step (menu picks)."""
    pct = clamp_zoom_pct(value)
    if pct in ZOOM_LADDER:
        return pct
    return min(ZOOM_LADDER, key=lambda s: abs(s - pct))


def normalize_zoom_pct(value: object | None) -> int:
    """Back-compat alias — continuous clamp (label / mpv use live %)."""
    return clamp_zoom_pct(value)


def pct_to_video_zoom(pct: int) -> float:
    """UI percent → mpv ``video-zoom`` (log2 scale factor)."""
    scale = max(0.01, float(clamp_zoom_pct(pct)) / 100.0)
    return math.log2(scale)


def _chip_qss(
    *,
    accent: str,
    accent_rgb: str,
    font_px: int,
    active: bool = False,
) -> str:
    # Glyphs/label stay white; purple is border/fill only (Emily 28 Sep).
    fg = "#ffffff"
    # Active loupe = filled chip so the arm/disarm state reads at a glance.
    if active:
        return (
            "QPushButton {"
            f"background-color: rgba({accent_rgb}, 0.55);"
            f"color: {fg};"
            f"border: 2px solid {accent};"
            "border-radius: 8px;"
            f"font-family: {tok.FONT_APP};"
            "font-weight: bold;"
            f"font-size: {font_px}px;"
            "padding: 0px 8px;"
            "}"
            f"QPushButton:hover {{ background-color: rgba({accent_rgb}, 0.68); }}"
            f"QPushButton:pressed {{ background-color: rgba({accent_rgb}, 0.80); }}"
        )
    return (
        "QPushButton {"
        f"background-color: rgba({accent_rgb}, 0.18);"
        f"color: {fg};"
        f"border: 2px solid {accent};"
        "border-radius: 8px;"
        f"font-family: {tok.FONT_APP};"
        "font-weight: bold;"
        f"font-size: {font_px}px;"
        "padding: 0px 8px;"
        "}"
        f"QPushButton:hover {{ background-color: rgba({accent_rgb}, 0.32); }}"
        f"QPushButton:pressed {{ background-color: rgba({accent_rgb}, 0.45); }}"
    )


def install_player_zoom_chrome(app) -> QWidget | None:
    """Build loupe + % chips into ``app.player_header_zoom`` (left dock)."""
    existing = getattr(app, "player_header_zoom", None)
    if existing is not None:
        try:
            existing.objectName()
            return existing
        except RuntimeError:
            pass

    host = QWidget()
    host.setObjectName("playerHeaderZoom")
    host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    # Soft purple — sits with Healthy/Preview language, distinct from gear blue.
    accent = "#b29ae7"
    accent_rgb = "178, 154, 231"
    font_px = 12

    btn_loupe = QPushButton()
    btn_loupe.setObjectName("playerHeaderZoomLoupe")
    btn_loupe.setCheckable(True)
    btn_loupe.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_loupe.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn_loupe.setToolTip("Loupe: click to arm — wheel zooms toward cursor; drag pans")
    btn_loupe.setAccessibleName("Preview loupe")

    btn_pct = QPushButton()
    btn_pct.setObjectName("playerHeaderZoomPct")
    btn_pct.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_pct.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn_pct.setToolTip("Preview zoom level (does not affect export)")
    btn_pct.setAccessibleName("Preview zoom percent")

    row.addWidget(btn_loupe, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(btn_pct, 0, Qt.AlignmentFlag.AlignVCenter)

    app.player_header_zoom = host
    app.btn_preview_zoom_loupe = btn_loupe
    app.btn_preview_zoom_pct = btn_pct
    if not hasattr(app, "_preview_zoom_pct"):
        app._preview_zoom_pct = DEFAULT_ZOOM_PCT
    if not hasattr(app, "_preview_zoom_pan"):
        app._preview_zoom_pan = (0.0, 0.0)
    if not hasattr(app, "_preview_loupe_armed"):
        app._preview_loupe_armed = False

    btn_loupe.clicked.connect(lambda _checked=False: toggle_preview_loupe(app))
    btn_pct.clicked.connect(lambda: show_preview_zoom_menu(app))

    try:
        from steempeg.ui.widgets.press_feedback import install_press_feedback_chip

        # Match QSS border-radius: 8 — half-height pill mask looked square on these chips.
        install_press_feedback_chip(btn_loupe, chip_radius=8.0)
        install_press_feedback_chip(btn_pct, chip_radius=8.0)
    except Exception:
        pass

    sync_preview_zoom_chrome(app, font_px=font_px, accent=accent, accent_rgb=accent_rgb)
    pin_player_zoom_dock(app)
    return host


def pin_player_zoom_dock(app) -> None:
    """Keep zoom chips at the far left of the header (before Steam-like mirror)."""
    host = getattr(app, "player_header_zoom", None)
    header = getattr(app, "player_header_frame", None)
    if host is None or header is None:
        return
    lay = header.layout()
    if lay is None:
        return
    idx = lay.indexOf(host)
    if idx < 0:
        lay.insertWidget(0, host, 0)
    elif idx != 0:
        lay.removeWidget(host)
        lay.insertWidget(0, host, 0)
    host.show()


def measure_left_zoom_span(app, spacing: int = 10) -> int:
    """Width consumed by the left zoom dock (0 if missing/hidden)."""
    host = getattr(app, "player_header_zoom", None)
    if host is None:
        return 0
    try:
        if not host.isVisible():
            return 0
        laid = int(host.width()) if host.width() > 0 else 0
        hint = max(0, int(host.sizeHint().width()))
        return max(laid, hint)
    except RuntimeError:
        return 0


def is_preview_loupe_armed(app) -> bool:
    return bool(getattr(app, "_preview_loupe_armed", False))


def toggle_preview_loupe(app) -> None:
    """Arm / disarm scroll-wheel zoom on the video surface."""
    app._preview_loupe_armed = not is_preview_loupe_armed(app)
    sync_preview_zoom_chrome(app)
    sync_preview_zoom_cursor(app)


def set_preview_loupe_armed(app, armed: bool) -> None:
    app._preview_loupe_armed = bool(armed)
    sync_preview_zoom_chrome(app)
    sync_preview_zoom_cursor(app)


def sync_preview_zoom_chrome(
    app,
    *,
    font_px: int | None = None,
    chip: int | None = None,
    chip_icon: int | None = None,
    accent: str = "#b29ae7",
    accent_rgb: str = "178, 154, 231",
) -> None:
    """Refresh loupe / % chip sizes, icons, and label for current density + pct."""
    btn_loupe = getattr(app, "btn_preview_zoom_loupe", None)
    btn_pct = getattr(app, "btn_preview_zoom_pct", None)
    if btn_loupe is None or btn_pct is None:
        return

    if font_px is None or chip is None or chip_icon is None:
        try:
            from steempeg.ui.player_header_layout import player_header_density

            dense = player_header_density(app)
            if font_px is None:
                font_px = max(11, int(dense.header_font))
            if chip is None:
                chip = max(24, int(dense.header_chip))
            if chip_icon is None:
                chip_icon = max(12, int(dense.header_chip_icon))
        except Exception:
            font_px = font_px or 12
            chip = chip or 30
            chip_icon = chip_icon or 16

    pct = clamp_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT))
    app._preview_zoom_pct = pct
    armed = is_preview_loupe_armed(app)

    loupe_qss = _chip_qss(
        accent=accent, accent_rgb=accent_rgb, font_px=int(font_px), active=armed
    )
    pct_qss = _chip_qss(
        accent=accent, accent_rgb=accent_rgb, font_px=int(font_px), active=False
    )

    btn_loupe.blockSignals(True)
    btn_loupe.setChecked(armed)
    btn_loupe.blockSignals(False)
    btn_loupe.setFixedSize(int(chip), int(chip))
    btn_loupe.setStyleSheet(loupe_qss)
    btn_loupe.setToolTip(
        "Loupe on — wheel zooms toward cursor; LMB/RMB drag pans (click to disarm)"
        if armed
        else "Loupe off — click to arm: wheel zooms toward cursor, drag pans when zoomed"
    )
    try:
        from steempeg.ui.icon_assets import loupe_icon

        btn_loupe.setIcon(loupe_icon(int(chip_icon), color="#ffffff"))
        btn_loupe.setIconSize(QSize(int(chip_icon), int(chip_icon)))
        btn_loupe.setText("")
    except Exception:
        btn_loupe.setText("🔍")

    try:
        from steempeg.ui.player_header_layout import player_header_chip_qfont

        btn_pct.setFont(player_header_chip_qfont(int(font_px)))
    except Exception:
        pass
    btn_pct.setMinimumHeight(int(chip))
    btn_pct.setMaximumHeight(int(chip))
    btn_pct.setMinimumWidth(0)
    btn_pct.setMaximumWidth(16777215)
    btn_pct.setStyleSheet(pct_qss)
    btn_pct.setText(f" {pct}% ▾ ")

    # Keep ClipCard press radius matched to QSS (8px) after density/restyle.
    try:
        from steempeg.ui.widgets.press_feedback import install_press_feedback_chip

        install_press_feedback_chip(btn_loupe, chip_radius=8.0)
        install_press_feedback_chip(btn_pct, chip_radius=8.0)
    except Exception:
        pass


def apply_preview_zoom(
    app, pct: int | None = None, *, pan: tuple[float, float] | None = None
) -> None:
    """Push zoom (+ optional pan) to mpv and refresh the % chip label."""
    target = clamp_zoom_pct(
        pct if pct is not None else getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT)
    )
    app._preview_zoom_pct = target
    if pan is not None:
        app._preview_zoom_pan = (float(pan[0]), float(pan[1]))
    elif target <= DEFAULT_ZOOM_PCT:
        app._preview_zoom_pan = (0.0, 0.0)

    sync_preview_zoom_chrome(app)
    sync_preview_zoom_cursor(app)
    _push_zoom_to_mpv(app)


def reset_preview_zoom(app) -> None:
    """100% + centered pan + loupe disarmed — call on clip change / close / idle."""
    app._preview_zoom_pct = DEFAULT_ZOOM_PCT
    app._preview_zoom_pan = (0.0, 0.0)
    app._preview_loupe_armed = False
    sync_preview_zoom_chrome(app)
    sync_preview_zoom_cursor(app)
    _push_zoom_to_mpv(app)


def set_preview_zoom_pct(app, pct: int) -> None:
    """Menu / ladder: snap to a discrete step."""
    target = snap_zoom_pct(pct)
    if target <= DEFAULT_ZOOM_PCT:
        apply_preview_zoom(app, target, pan=(0.0, 0.0))
    else:
        apply_preview_zoom(app, target)


def _video_fit_size(app, surface_w: int, surface_h: int) -> tuple[float, float]:
    """Size of the video rect at 100% (aspect-fit into the surface), in surface px.

    mpv ``video-pan-*`` is a fraction of the *scaled video*, not the window, so
    letterboxed clips need the fitted rect rather than the surface size.
    """
    w = float(max(1, int(surface_w)))
    h = float(max(1, int(surface_h)))
    player = getattr(app, "player", None)
    try:
        params = player["video-params"] if player is not None else None
        dw = float((params or {}).get("dw") or 0)
        dh = float((params or {}).get("dh") or 0)
    except Exception:
        dw = dh = 0.0
    if dw <= 0 or dh <= 0:
        return w, h
    fit = min(w / dw, h / dh)
    return dw * fit, dh * fit


def _clamp_pan(
    pan_x: float,
    pan_y: float,
    scale: float,
    *,
    fit_w: float | None = None,
    fit_h: float | None = None,
    surface_w: int | None = None,
    surface_h: int | None = None,
) -> tuple[float, float]:
    """Keep the scaled video covering the surface (no panning past its edges)."""
    s = max(scale, 0.01)

    def _limit(fit: float | None, surface: int | None) -> float:
        if fit and surface:
            return max(0.0, (1.0 - float(surface) / (float(fit) * s)) / 2.0)
        return max(0.0, (1.0 - 1.0 / s) / 2.0)

    lx = _limit(fit_w, surface_w)
    ly = _limit(fit_h, surface_h)
    return (
        max(-lx, min(lx, float(pan_x))),
        max(-ly, min(ly, float(pan_y))),
    )


def nudge_preview_zoom_wheel(
    app,
    delta_y: float,
    *,
    cursor_x: float | None = None,
    cursor_y: float | None = None,
    surface_w: int | None = None,
    surface_h: int | None = None,
) -> bool:
    """Scroll-wheel zoom while loupe is armed. ``delta_y`` > 0 = zoom in.

    When cursor + surface size are given, zoom toward the cursor (pan adjusts so
    the point under the pointer stays put). Returns True if consumed.
    """
    if not is_preview_loupe_armed(app):
        return False
    steps = float(delta_y) / 120.0
    if abs(steps) < 0.01:
        # Trackpads sometimes send tiny deltas — treat any non-zero as one notch.
        if delta_y == 0:
            return False
        steps = 1.0 if delta_y > 0 else -1.0
    cur = clamp_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT))
    nxt = clamp_zoom_pct(cur + int(round(steps * ZOOM_WHEEL_STEP_PCT)))
    if nxt == cur:
        return True

    if nxt <= DEFAULT_ZOOM_PCT:
        apply_preview_zoom(app, nxt, pan=(0.0, 0.0))
        return True

    old_s = max(0.01, float(cur) / 100.0)
    new_s = max(0.01, float(nxt) / 100.0)
    pan = getattr(app, "_preview_zoom_pan", (0.0, 0.0)) or (0.0, 0.0)
    px, py = float(pan[0]), float(pan[1])

    w = int(surface_w or 0)
    h = int(surface_h or 0)
    if w > 0 and h > 0:
        fit_w, fit_h = _video_fit_size(app, w, h)
        if (
            cursor_x is not None
            and cursor_y is not None
            and abs(new_s - old_s) > 1e-6
        ):
            # Cursor offset from center in units of the 100% video rect. The
            # content point under it is ``o/s - pan``; hold that fixed across s.
            ox = (float(cursor_x) - w / 2.0) / fit_w
            oy = (float(cursor_y) - h / 2.0) / fit_h
            px = px + ox * (1.0 / new_s - 1.0 / old_s)
            py = py + oy * (1.0 / new_s - 1.0 / old_s)
        px, py = _clamp_pan(
            px, py, new_s, fit_w=fit_w, fit_h=fit_h, surface_w=w, surface_h=h
        )
    else:
        px, py = _clamp_pan(px, py, new_s)

    apply_preview_zoom(app, nxt, pan=(px, py))
    return True


def show_preview_zoom_menu(app) -> None:
    """Popup ladder: 100% · 125% · 150% · 200% · 300%."""
    from steempeg.ui.player import preview_quality as pq

    menu = QMenu(getattr(app, "ui", app))
    try:
        menu.setStyleSheet(pq.menu_stylesheet())
    except Exception:
        menu.setStyleSheet(ut.menu_stylesheet())

    title = menu.addAction("Preview zoom")
    title.setEnabled(False)

    group = QActionGroup(menu)
    group.setExclusive(True)
    current = clamp_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT))
    # Check the nearest ladder step so a wheel level still highlights something.
    nearest = snap_zoom_pct(current)

    for step in ZOOM_LADDER:
        action = menu.addAction(f"{step}%")
        action.setCheckable(True)
        action.setChecked(step == nearest)
        action.setData(step)
        group.addAction(action)

    def _picked(action) -> None:
        if action is None:
            return
        data = action.data()
        if data is not None:
            set_preview_zoom_pct(app, int(data))

    group.triggered.connect(_picked)

    menu.addSeparator()
    footnote = menu.addAction("Does not affect export")
    footnote.setEnabled(False)

    anchor = getattr(app, "btn_preview_zoom_pct", None)
    if anchor is not None:
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
    else:
        menu.exec()


def _set_mpv_prop(player, name: str, value) -> bool:
    """Set an mpv property via bracket, attribute, or command — soft-fail."""
    try:
        player[name] = value
        return True
    except Exception:
        pass
    attr = name.replace("-", "_")
    try:
        setattr(player, attr, value)
        return True
    except Exception:
        pass
    try:
        player.command("set", name, str(value))
        return True
    except Exception:
        return False


def _player_fit_baseline(app, player) -> tuple[object, object]:
    """``(panscan, keepaspect)`` the player was created with, read once per player.

    Embed creates with ``panscan=1`` / ``keepaspect=no``, but the Linux external
    window fallback uses ``keepaspect=yes`` — 100% must restore whichever it was.
    """
    cached = getattr(app, "_preview_zoom_fit_baseline", None)
    if cached is not None and cached[0] is player:
        return cached[1], cached[2]
    try:
        panscan = player["panscan"]
    except Exception:
        panscan = 1.0
    try:
        keepaspect = player["keepaspect"]
    except Exception:
        keepaspect = "no"
    app._preview_zoom_fit_baseline = (player, panscan, keepaspect)
    return panscan, keepaspect


def _push_zoom_to_mpv(app) -> None:
    """Apply live zoom/pan to mpv.

    Embed uses ``panscan=1`` + ``keepaspect=no`` to fill the 16:9 hole.
    ``video-zoom`` alone often looks like a no-op under that fill path, so we
    drive linear ``video-scale-x/y`` (applied *after* panscan) and keep
    ``video-zoom`` cleared. When zoomed we also drop panscan so pan doesn't
    fight the crop.
    """
    player = getattr(app, "player", None)
    if player is None:
        return
    pct = clamp_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT))
    pan = getattr(app, "_preview_zoom_pan", (0.0, 0.0)) or (0.0, 0.0)
    scale = float(pct) / 100.0
    try:
        base_panscan, base_keepaspect = _player_fit_baseline(app, player)
        if pct > DEFAULT_ZOOM_PCT:
            _set_mpv_prop(player, "panscan", 0.0)
            _set_mpv_prop(player, "keepaspect", "yes")
        else:
            _set_mpv_prop(player, "panscan", base_panscan)
            _set_mpv_prop(player, "keepaspect", base_keepaspect)

        # Clear log2 zoom so it cannot stack with linear scale.
        _set_mpv_prop(player, "video-zoom", 0.0)
        ok_sx = _set_mpv_prop(player, "video-scale-x", scale)
        ok_sy = _set_mpv_prop(player, "video-scale-y", scale)
        # Fallback if this mpv build lacks video-scale-*: log2 zoom alone.
        if not (ok_sx and ok_sy):
            _set_mpv_prop(player, "video-zoom", pct_to_video_zoom(pct))
        _set_mpv_prop(player, "video-pan-x", float(pan[0]))
        _set_mpv_prop(player, "video-pan-y", float(pan[1]))
        if not (ok_sx or ok_sy):
            _LOG.warning("preview zoom: mpv rejected scale/zoom (pct=%s)", pct)
    except Exception:
        _LOG.warning("preview zoom apply failed", exc_info=True)


def preview_zoom_scale(app) -> float:
    pct = clamp_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT))
    return max(1.0, float(pct) / 100.0)


def is_preview_zoomed(app) -> bool:
    return clamp_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT)) > DEFAULT_ZOOM_PCT


def sync_preview_zoom_cursor(app) -> None:
    """Open-hand when zoomed; cross when loupe armed at 100%; arrow otherwise."""
    screen = getattr(app, "mpv_screen", None)
    if screen is None:
        return
    try:
        if is_preview_zoomed(app):
            screen.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        elif is_preview_loupe_armed(app):
            screen.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        else:
            screen.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
    except RuntimeError:
        pass


def nudge_preview_pan(
    app, dx_px: float, dy_px: float, *, surface_w: int, surface_h: int
) -> None:
    """Convert screen-pixel drag into mpv video-pan-x/y (scaled by zoom)."""
    if not is_preview_zoomed(app):
        return
    w = max(1, int(surface_w))
    h = max(1, int(surface_h))
    scale = preview_zoom_scale(app)
    fit_w, fit_h = _video_fit_size(app, w, h)
    # Positive drag (right/down) moves the picture with the cursor.
    d_x = float(dx_px) / fit_w / scale
    d_y = float(dy_px) / fit_h / scale
    cur = getattr(app, "_preview_zoom_pan", (0.0, 0.0)) or (0.0, 0.0)
    nx, ny = _clamp_pan(
        float(cur[0]) + d_x,
        float(cur[1]) + d_y,
        scale,
        fit_w=fit_w,
        fit_h=fit_h,
        surface_w=w,
        surface_h=h,
    )
    app._preview_zoom_pan = (nx, ny)
    player = getattr(app, "player", None)
    if player is None:
        return
    _set_mpv_prop(player, "video-pan-x", nx)
    _set_mpv_prop(player, "video-pan-y", ny)
