"""Pixmap helpers for marker icons (tint white glyphs with class color)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap

from steempeg.services import marker_prefs as mprefs
from steempeg.ui.icon_utils import primary_device_pixel_ratio, square_fit_pixmap

# On-canvas timeline pin size (logical px). Buffer uses ≥2× DPR for crisp HD.
# Same size on Windows / Linux / Deck — the old Windows-only 18px path left pins
# looking tiny next to the 13px seek strip (same bug the Linux bump fixed).
TIMELINE_MARKER_LOGICAL = 20


def timeline_marker_dpr() -> float:
    """Device ratio for timeline marker buffers — never below 2× (old retina path)."""
    return max(primary_device_pixel_ratio(), 2.0)


def load_scaled_pixmap(
    path: str,
    size: int = 36,
    *,
    dpr: float | None = None,
) -> QPixmap | None:
    """Load an image and KeepAspectRatio-fit it into a ``size``×``size`` square.

    Wide (or tall) custom icons letterbox into the square — never stretch into a
    thin rectangle. Pass ``dpr`` for HiDPI; default uses the primary screen ratio.
    """
    if not path or not os.path.isfile(path):
        return None
    pix = QPixmap(path)
    if pix.isNull():
        return None
    return square_fit_pixmap(pix, size, dpr=dpr)


def load_timeline_marker_pixmap(path: str) -> QPixmap | None:
    """Square-fit a file for the seek-bar marker row (DPR-aware, ≥2× buffer)."""
    return load_scaled_pixmap(
        path, TIMELINE_MARKER_LOGICAL, dpr=timeline_marker_dpr()
    )


def _harden_tint_alpha(src: QPixmap) -> QPixmap:
    """Mildly boost soft anti-aliased edges so recolor keeps a readable silhouette.

    Soft glow assets (e.g. screenshot.png) otherwise fade into near-invisible
    tinted mist. This is NOT a solid fill — only alpha is adjusted.
    """
    from PySide6.QtGui import QImage

    img = src.toImage().convertToFormat(QImage.Format.Format_ARGB32).copy()
    w, h = img.width(), img.height()
    for y in range(h):
        for x in range(w):
            c = img.pixelColor(x, y)
            a = c.alpha()
            if a <= 20:
                c.setAlpha(0)
            elif a < 180:
                c.setAlpha(min(255, int(28 + a * 1.2)))
            else:
                continue
            img.setPixelColor(x, y, c)
    out = QPixmap.fromImage(img)
    out.setDevicePixelRatio(src.devicePixelRatio())
    return out


def tint_pixmap(src: QPixmap, color: str, *, height: int | None = None) -> QPixmap:
    """Recolor a glyph while keeping shading / outlines (not a flat paint fill).

    White mono icons take the tint's hue+saturation; each pixel's brightness
    stays from the source so edges and inner detail stay readable — pinkish
    skull, not a solid pink blob.

    When ``height`` is set, scale by height only (KeepAspectRatio). Never squash
    wide pins (round digit strips, panoramic class art) into a square — that is
    what made class-tinted markers look "sausaged" on the timeline.

    Drawing must ignore ``devicePixelRatio`` on the painter target: otherwise a
    DPR-aware source is stamped at logical size into the top-left of a physical
    buffer, and class-tinted pins shrink to half size on the timeline.
    """
    if src is None or src.isNull():
        return QPixmap()
    base = src
    dpr = max(float(base.devicePixelRatio() or 1.0), 1.0)
    if height is not None:
        edge = max(1, int(height))
        logical_h = base.height() / dpr
        if abs(logical_h - edge) > 0.51:
            phys_h = max(1, int(round(edge * dpr)))
            raw = QPixmap(base)
            raw.setDevicePixelRatio(1.0)
            base = raw.scaledToHeight(
                phys_h, Qt.TransformationMode.SmoothTransformation
            )
            base.setDevicePixelRatio(dpr)
            dpr = max(float(base.devicePixelRatio() or 1.0), 1.0)

    tint = QColor(color)
    if not tint.isValid():
        return QPixmap(base)

    # Work in raw device pixels.
    raw = QPixmap(base)
    raw.setDevicePixelRatio(1.0)
    raw = _harden_tint_alpha(raw)

    from PySide6.QtGui import QImage

    img = raw.toImage().convertToFormat(QImage.Format.Format_ARGB32).copy()
    th = tint.hue()
    ts = tint.saturation()
    # Grayscale / near-gray tints (self-kill skull): keep value path but allow
    # low sat so outlines stay soft gray rather than forced chroma.
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            a = c.alpha()
            if a == 0:
                continue
            # Brightness from the glyph (white core → full tint, AA edge → darker).
            src_v = max(c.red(), c.green(), c.blue())
            if ts <= 0 or th < 0:
                # Achromatic tint (#9a9a9a): scale gray by source value.
                g = int(round(tint.red() * (src_v / 255.0)))
                img.setPixelColor(x, y, QColor(g, g, g, a))
            else:
                # Hue/sat from class color; value from the artwork.
                img.setPixelColor(x, y, QColor.fromHsv(th, ts, src_v, a))
    out = QPixmap.fromImage(img)
    out.setDevicePixelRatio(dpr)
    return out


def class_has_custom_icon(cls: dict) -> bool:
    path = str(cls.get("icon") or "").strip()
    return bool(path and os.path.isfile(path))


def class_display_pixmap(cls: dict, *, height: int = 22) -> QPixmap | None:
    """Class row / preview: custom file, or default pin (tinted only if class has color)."""
    if class_has_custom_icon(cls):
        return load_scaled_pixmap(str(cls["icon"]), height)
    base_path = mprefs.legacy_asset_path("usermarker")
    if not base_path:
        return None
    base = load_scaled_pixmap(base_path, height)
    if base is None:
        return None
    color = str(cls.get("color") or "").strip()
    if not color:
        return base
    return tint_pixmap(base, color, height=height)
