"""Pixmap helpers for marker icons (tint white glyphs with class color)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

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
    """Boost soft anti-aliased glyphs so class tints keep a readable solid core.

    Assets like ``screenshot.png`` are mostly translucent glow. SourceIn tint
    then concentrates visible color into a tiny blob — markers look even smaller
    once a class color is applied. Threshold + mild boost keeps the silhouette.
    """
    from PySide6.QtGui import QImage

    img = src.toImage().convertToFormat(QImage.Format.Format_ARGB32).copy()
    w, h = img.width(), img.height()
    for y in range(h):
        for x in range(w):
            c = img.pixelColor(x, y)
            a = c.alpha()
            if a <= 24:
                c.setAlpha(0)
            elif a < 220:
                c.setAlpha(min(255, int(40 + a * 1.35)))
            else:
                continue
            img.setPixelColor(x, y, c)
    out = QPixmap.fromImage(img)
    out.setDevicePixelRatio(src.devicePixelRatio())
    return out


def tint_pixmap(src: QPixmap, color: str, *, height: int | None = None) -> QPixmap:
    """Recolor opaque pixels to ``color`` (keeps alpha) — for white mono icons.

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
    # Work in raw device pixels for harden + SourceIn tint.
    raw = QPixmap(base)
    raw.setDevicePixelRatio(1.0)
    raw = _harden_tint_alpha(raw)
    out = QPixmap(raw.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(0, 0, raw)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), QColor(color))
    painter.end()
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
