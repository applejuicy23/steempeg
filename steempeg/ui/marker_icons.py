"""Pixmap helpers for marker icons (tint white glyphs with class color)."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

from steempeg.services import marker_prefs as mprefs
from steempeg.ui.icon_utils import primary_device_pixel_ratio, square_fit_pixmap

# On-canvas timeline pin size (logical px). Buffer uses ≥2× DPR for crisp HD.
# Windows keeps compact Steam-like pins; Linux / Deck need a larger logical size
# (typical 100% scale + XWayland) or pins look tiny vs the seek strip.
TIMELINE_MARKER_LOGICAL = 18 if sys.platform == "win32" else 20


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


def tint_pixmap(src: QPixmap, color: str, *, height: int | None = None) -> QPixmap:
    """Recolor opaque pixels to ``color`` (keeps alpha) — for white mono icons.

    When ``height`` is set, scale by height only (KeepAspectRatio). Never squash
    wide pins (round digit strips, panoramic class art) into a square — that is
    what made class-tinted markers look "sausaged" on the timeline.
    """
    if src is None or src.isNull():
        return QPixmap()
    base = src
    if height is not None:
        edge = max(1, int(height))
        dpr = max(float(base.devicePixelRatio() or 1.0), 1.0)
        logical_h = base.height() / dpr
        if abs(logical_h - edge) > 0.51:
            phys_h = max(1, int(round(edge * dpr)))
            raw = QPixmap(base)
            raw.setDevicePixelRatio(1.0)
            base = raw.scaledToHeight(
                phys_h, Qt.TransformationMode.SmoothTransformation
            )
            base.setDevicePixelRatio(dpr)
    out = QPixmap(base.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(0, 0, base)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), QColor(color))
    painter.end()
    out.setDevicePixelRatio(base.devicePixelRatio())
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
