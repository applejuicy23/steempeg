"""Pixmap helpers for marker icons (tint white glyphs with class color)."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

from steempeg.services import marker_prefs as mprefs


def load_scaled_pixmap(path: str, height: int = 36) -> QPixmap | None:
    if not path or not os.path.isfile(path):
        return None
    pix = QPixmap(path)
    if pix.isNull():
        return None
    return pix.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)


def tint_pixmap(src: QPixmap, color: str, *, height: int | None = None) -> QPixmap:
    """Recolor opaque pixels to ``color`` (keeps alpha) — for white mono icons."""
    if src is None or src.isNull():
        return QPixmap()
    base = src
    if height and base.height() != height:
        base = base.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(base.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(0, 0, base)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), QColor(color))
    painter.end()
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
