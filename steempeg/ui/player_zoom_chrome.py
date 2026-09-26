"""Player-header loupe + Vegas-style preview zoom (mpv video-zoom / pan).

Preview only — never touches export / FFmpeg / queue math.
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

_LOG = logging.getLogger(__name__)


def normalize_zoom_pct(value: object | None) -> int:
    try:
        pct = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_ZOOM_PCT
    if pct in ZOOM_LADDER:
        return pct
    # Snap to nearest ladder step.
    return min(ZOOM_LADDER, key=lambda s: abs(s - pct))


def pct_to_video_zoom(pct: int) -> float:
    """UI percent → mpv ``video-zoom`` (log2 scale factor)."""
    scale = max(0.01, float(normalize_zoom_pct(pct)) / 100.0)
    return math.log2(scale)


def next_zoom_pct(current: int) -> int:
    """Loupe click: advance one step; wrap from top back to 100%."""
    cur = normalize_zoom_pct(current)
    try:
        idx = ZOOM_LADDER.index(cur)
    except ValueError:
        return DEFAULT_ZOOM_PCT
    nxt = idx + 1
    if nxt >= len(ZOOM_LADDER):
        return DEFAULT_ZOOM_PCT
    return ZOOM_LADDER[nxt]


def _chip_qss(*, accent: str, accent_rgb: str, font_px: int) -> str:
    return (
        "QPushButton {"
        f"background-color: rgba({accent_rgb}, 0.18);"
        f"color: {accent};"
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
    btn_loupe.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_loupe.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn_loupe.setToolTip("Zoom preview (click to step)")
    btn_loupe.setAccessibleName("Preview zoom")

    btn_pct = QPushButton()
    btn_pct.setObjectName("playerHeaderZoomPct")
    btn_pct.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_pct.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn_pct.setToolTip("Preview zoom level")
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

    btn_loupe.clicked.connect(lambda: step_preview_zoom(app))
    btn_pct.clicked.connect(lambda: show_preview_zoom_menu(app))

    try:
        from steempeg.ui.widgets.press_feedback import install_press_feedback_chip

        install_press_feedback_chip(btn_loupe)
        install_press_feedback_chip(btn_pct)
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

    pct = normalize_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT))
    app._preview_zoom_pct = pct

    qss = _chip_qss(accent=accent, accent_rgb=accent_rgb, font_px=int(font_px))
    btn_loupe.setFixedSize(int(chip), int(chip))
    btn_loupe.setStyleSheet(qss)
    try:
        from steempeg.ui.icon_assets import loupe_icon

        btn_loupe.setIcon(loupe_icon(int(chip_icon)))
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
    btn_pct.setStyleSheet(qss)
    btn_pct.setText(f" {pct}% ▾ ")


def apply_preview_zoom(app, pct: int | None = None, *, pan: tuple[float, float] | None = None) -> None:
    """Push zoom (+ optional pan) to mpv and refresh the % chip label."""
    target = normalize_zoom_pct(
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
    """100% + centered pan — call on clip change / close / idle."""
    app._preview_zoom_pct = DEFAULT_ZOOM_PCT
    app._preview_zoom_pan = (0.0, 0.0)
    sync_preview_zoom_chrome(app)
    sync_preview_zoom_cursor(app)
    _push_zoom_to_mpv(app)


def step_preview_zoom(app) -> None:
    """Loupe: one ladder step; wraps to 100% from the top."""
    cur = normalize_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT))
    nxt = next_zoom_pct(cur)
    # Stepping to 100% recenters; other steps keep pan (Vegas-ish).
    if nxt <= DEFAULT_ZOOM_PCT:
        apply_preview_zoom(app, nxt, pan=(0.0, 0.0))
    else:
        apply_preview_zoom(app, nxt)


def set_preview_zoom_pct(app, pct: int) -> None:
    target = normalize_zoom_pct(pct)
    if target <= DEFAULT_ZOOM_PCT:
        apply_preview_zoom(app, target, pan=(0.0, 0.0))
    else:
        apply_preview_zoom(app, target)


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
    current = normalize_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT))

    for step in ZOOM_LADDER:
        action = menu.addAction(f"{step}%")
        action.setCheckable(True)
        action.setChecked(step == current)
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


def _push_zoom_to_mpv(app) -> None:
    player = getattr(app, "player", None)
    if player is None:
        return
    pct = normalize_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT))
    pan = getattr(app, "_preview_zoom_pan", (0.0, 0.0)) or (0.0, 0.0)
    try:
        player["video-zoom"] = pct_to_video_zoom(pct)
        player["video-pan-x"] = float(pan[0])
        player["video-pan-y"] = float(pan[1])
    except Exception:
        _LOG.debug("preview zoom apply failed", exc_info=True)


def preview_zoom_scale(app) -> float:
    pct = normalize_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT))
    return max(1.0, float(pct) / 100.0)


def is_preview_zoomed(app) -> bool:
    return normalize_zoom_pct(getattr(app, "_preview_zoom_pct", DEFAULT_ZOOM_PCT)) > DEFAULT_ZOOM_PCT


def sync_preview_zoom_cursor(app) -> None:
    """Open-hand when zoomed; arrow when at 100%."""
    screen = getattr(app, "mpv_screen", None)
    if screen is None:
        return
    try:
        if is_preview_zoomed(app):
            screen.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        else:
            screen.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
    except RuntimeError:
        pass


def nudge_preview_pan(app, dx_px: float, dy_px: float, *, surface_w: int, surface_h: int) -> None:
    """Convert screen-pixel drag into mpv video-pan-x/y (scaled by zoom)."""
    if not is_preview_zoomed(app):
        return
    w = max(1, int(surface_w))
    h = max(1, int(surface_h))
    scale = preview_zoom_scale(app)
    # Positive drag (right/down) moves the picture with the cursor.
    d_x = float(dx_px) / float(w) / scale
    d_y = float(dy_px) / float(h) / scale
    cur = getattr(app, "_preview_zoom_pan", (0.0, 0.0)) or (0.0, 0.0)
    # Soft clamp so you can't lose the frame entirely.
    limit = max(0.0, 1.0 - (1.0 / scale)) + 0.15
    nx = max(-limit, min(limit, float(cur[0]) + d_x))
    ny = max(-limit, min(limit, float(cur[1]) + d_y))
    app._preview_zoom_pan = (nx, ny)
    player = getattr(app, "player", None)
    if player is None:
        return
    try:
        player["video-pan-x"] = nx
        player["video-pan-y"] = ny
    except Exception:
        _LOG.debug("preview pan apply failed", exc_info=True)
