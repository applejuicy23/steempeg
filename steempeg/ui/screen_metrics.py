"""Physical screen metrics (PPI / diagonal) for layout density.

Qt window sizes are in device-independent pixels. Two 1920-wide shells can feel
completely different when one is a 15.6″ laptop and the other a 27″ monitor —
same resolution, different inches. Density must follow **physical** pixel size.

``physicalDotsPerInch()`` / ``physicalSize()`` come from EDID and sometimes lie
(RDP, bad drivers). Nonsense values fall back to a safe reference so we never
blow up chrome.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QScreen
    from PySide6.QtWidgets import QWidget

# Design reference: ~27″ 1440p / mid desktop (~110 PPI). Emily's daily shell.
# Lower PPI (big-inch FHD TV/monitor) → each DIP is physically larger → shrink.
# At/above ref → leave width-based density alone (Deck portable forces COMFORT).
REF_PPI = 110.0
_MIN_SANE_PPI = 72.0
_MAX_SANE_PPI = 400.0
# How hard low PPI may shrink chrome (never enlarge past 1.0 for desktop).
# Floor used to be 0.78 — fine for TVs, but 27″ FHD (~82 PPI) clamped there and
# looked tiny vs Windows taskbar. 0.90 is a *mild pixel* floor, applied once in
# density_for_width (not multiplied into shell_layout_scale). 75–95 PPI on an
# already-FHD-wide window is blended toward 1.0 (~0.95). Emily’s ~110 PPI ref
# stays at 1.0 (ratio ≥ floor, skip if within 2%).
_PPI_SCALE_MIN = 0.90
_PPI_SCALE_MAX = 1.0


def _qscreen_for(widget: QWidget | None = None, screen: QScreen | None = None):
    if screen is not None:
        return screen
    if widget is not None:
        try:
            sc = widget.screen()
            if sc is not None:
                return sc
        except Exception:
            pass
        try:
            win = widget.window()
            if win is not None:
                sc = win.screen()
                if sc is not None:
                    return sc
        except Exception:
            pass
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            return app.primaryScreen()
    except Exception:
        pass
    return None


def screen_diagonal_inches(
    widget: QWidget | None = None,
    screen: QScreen | None = None,
) -> float | None:
    """Physical diagonal in inches, or None if EDID size is missing/nonsense."""
    sc = _qscreen_for(widget, screen)
    if sc is None:
        return None
    try:
        mm = sc.physicalSize()
        w_mm = float(mm.width())
        h_mm = float(mm.height())
    except Exception:
        return None
    if w_mm < 40.0 or h_mm < 40.0:  # < ~1.5″ — junk / unknown
        return None
    diag = math.hypot(w_mm, h_mm) / 25.4
    if diag < 4.0 or diag > 60.0:
        return None
    return diag


def screen_ppi(
    widget: QWidget | None = None,
    screen: QScreen | None = None,
) -> float:
    """Best-effort physical PPI; falls back to ``REF_PPI`` when EDID is junk."""
    sc = _qscreen_for(widget, screen)
    if sc is None:
        return REF_PPI

    ppi = 0.0
    try:
        ppi = float(sc.physicalDotsPerInch())
    except Exception:
        ppi = 0.0

    if ppi < _MIN_SANE_PPI or ppi > _MAX_SANE_PPI:
        # Derive from physical mm + pixel geometry when the DPI field is wrong.
        try:
            mm = sc.physicalSize()
            geo = sc.geometry()
            w_mm = float(mm.width())
            h_mm = float(mm.height())
            if w_mm >= 40.0 and geo.width() > 0:
                ppi_x = float(geo.width()) / (w_mm / 25.4)
                ppi_y = (
                    float(geo.height()) / (h_mm / 25.4)
                    if h_mm >= 40.0 and geo.height() > 0
                    else ppi_x
                )
                ppi = 0.5 * (ppi_x + ppi_y)
        except Exception:
            ppi = 0.0

    if ppi < _MIN_SANE_PPI or ppi > _MAX_SANE_PPI:
        return REF_PPI
    return ppi


def chrome_ppi_scale(
    widget: QWidget | None = None,
    screen: QScreen | None = None,
) -> float:
    """Multiplier for chrome *pixel* sizes relative to ``REF_PPI``.

    * Low PPI (big inches / coarse pixels) → ``< 1`` — smaller DIP chrome.
    * At/above ref → ``1.0`` (do not inflate high-PPI desktop chrome).

    This is the coarse-pixel path only. Do **not** also fold it into
    ``shell_layout_scale`` (that double-applied on 24–27″ FHD). Wide FHD
    windows further damp this in ``density_for_width``.
    """
    ppi = screen_ppi(widget, screen)
    if ppi >= REF_PPI:
        return 1.0
    return max(_PPI_SCALE_MIN, min(_PPI_SCALE_MAX, ppi / REF_PPI))


def describe_screen(
    widget: QWidget | None = None,
    screen: QScreen | None = None,
) -> str:
    """One-line debug summary for startup logs."""
    sc = _qscreen_for(widget, screen)
    name = "?"
    geo = ""
    if sc is not None:
        try:
            name = repr(sc.name())
            g = sc.geometry()
            geo = f"{g.width()}x{g.height()}"
        except Exception:
            pass
    ppi = screen_ppi(widget, screen)
    diag = screen_diagonal_inches(widget, screen)
    scale = chrome_ppi_scale(widget, screen)
    diag_s = f"{diag:.1f}\"" if diag is not None else "?"
    cramped = is_screen_undersized(widget, screen)
    return (
        f"screen={name} geo={geo} diag={diag_s} ppi={ppi:.1f} "
        f"chrome_ppi_scale={scale:.3f} cramped={cramped} (ref={REF_PPI:g})"
    )


# Comfort floor matches Steam Deck / layout_defaults TARGET_MIN_*.
_MIN_COMFORT_W = 1280
_MIN_COMFORT_H = 800
# Below this diagonal, even "enough" DIPs feel cramped for Desktop chrome.
_SMALL_DIAG_IN = 15.5
_TINY_DIAG_IN = 13.0


def is_screen_undersized(
    widget: QWidget | None = None,
    screen: QScreen | None = None,
) -> bool:
    """True when resolution and/or physical size are below Steempeg comfort.

    Used for the startup «screen a bit small» tip (Desktop especially; also
    shown on the shell chooser). Steam Deck Portable is designed for 1280×800 —
    we still flag it so the tip can steer users, but callers may soft-skip Deck.
    """
    sc = _qscreen_for(widget, screen)
    if sc is None:
        return False

    try:
        avail = sc.availableGeometry()
        w = int(avail.width())
        h = int(avail.height())
    except Exception:
        return False

    if w < _MIN_COMFORT_W or h < _MIN_COMFORT_H:
        return True

    diag = screen_diagonal_inches(widget, screen)
    if diag is not None:
        if diag < _TINY_DIAG_IN:
            return True
        # Small laptop: enough DIPs on paper, but inches + mid width → artifacts.
        if diag < _SMALL_DIAG_IN and (w < 1520 or h < 900):
            return True
    return False


def screen_size_summary(
    widget: QWidget | None = None,
    screen: QScreen | None = None,
) -> str:
    """Short human line for warning dialogs (e.g. ``1366×768 · 15.6\"``)."""
    sc = _qscreen_for(widget, screen)
    parts: list[str] = []
    if sc is not None:
        try:
            g = sc.availableGeometry()
            parts.append(f"{g.width()}×{g.height()}")
        except Exception:
            pass
    diag = screen_diagonal_inches(widget, screen)
    if diag is not None:
        parts.append(f'{diag:.1f}"')
    return " · ".join(parts) if parts else "unknown display"
