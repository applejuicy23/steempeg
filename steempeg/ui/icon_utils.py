"""HiDPI-aware pixmaps/icons from bundled Steempeg logo assets."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap

from steempeg.infra.paths import get_resource_path


def app_window_icon() -> QIcon:
    """Best bundled icon for window chrome and taskbar buttons."""
    ico_path = get_resource_path("logo.ico")
    if os.path.isfile(ico_path):
        icon = QIcon(ico_path)
        if not icon.isNull():
            return icon
    png_path = get_resource_path("logo.png")
    if os.path.isfile(png_path):
        icon = QIcon(png_path)
        if not icon.isNull():
            return icon
    return QIcon()


def _primary_device_pixel_ratio() -> float:
    app = QGuiApplication.instance()
    if app is None:
        return 1.0
    screen = app.primaryScreen()
    if screen is None:
        return 1.0
    dpr = float(screen.devicePixelRatio())
    return dpr if dpr > 0 else 1.0


def app_logo_pixmap(size_px: int, *, dpr: float | None = None) -> QPixmap | None:
    """Crisp inline logo for title bars and small chrome affordances."""
    if size_px <= 0:
        return None
    if dpr is None:
        dpr = _primary_device_pixel_ratio()
    px = max(1, int(round(size_px * dpr)))

    icon = app_window_icon()
    if not icon.isNull():
        pixmap = icon.pixmap(px, px)
        if not pixmap.isNull():
            pixmap.setDevicePixelRatio(dpr)
            return pixmap

    png_path = get_resource_path("logo.png")
    if not os.path.isfile(png_path):
        return None
    source = QPixmap(png_path)
    if source.isNull():
        return None
    scaled = source.scaled(
        px,
        px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if scaled.isNull():
        return None
    scaled.setDevicePixelRatio(dpr)
    return scaled
