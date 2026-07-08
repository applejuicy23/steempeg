"""Shared pixmap/icon loaders for bundled UI assets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

from steempeg.core.dash.health import WARNING_ICON_FILE, ClipHealth, HEALTH_ICON_FILES
from steempeg.infra.paths import get_resource_path


def load_pixmap(name: str, size: int = 16) -> QPixmap:
    pix = QPixmap(get_resource_path(name))
    if pix.isNull():
        return QPixmap()
    return pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def load_icon(name: str, size: int = 16) -> QIcon:
    pix = load_pixmap(name, size)
    if pix.isNull():
        return QIcon()
    icon = QIcon()
    # Keep icons colored even when actions/widgets are temporarily disabled.
    # Qt otherwise auto-generates a greyscale Disabled mode variant.
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Disabled, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Selected, QIcon.State.Off)
    return icon


def health_icon(level: ClipHealth, size: int = 16) -> QIcon:
    return load_icon(HEALTH_ICON_FILES.get(level, WARNING_ICON_FILE), size)


def warning_icon(size: int = 16) -> QIcon:
    return load_icon(WARNING_ICON_FILE, size)


def warning_pixmap(size: int = 16) -> QPixmap:
    return load_pixmap(WARNING_ICON_FILE, size)
