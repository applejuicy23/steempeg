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
_PPI_SCALE_MIN = 0.78
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
    """Multiplier for chrome pixel sizes relative to ``REF_PPI``.

    * Low PPI (big inches / coarse pixels) → ``< 1`` — smaller DIP chrome.
    * At/above ref → ``1.0`` (do not inflate high-PPI desktop chrome).
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
    return (
        f"screen={name} geo={geo} diag={diag_s} ppi={ppi:.1f} "
        f"chrome_ppi_scale={scale:.3f} (ref={REF_PPI:g})"
    )
