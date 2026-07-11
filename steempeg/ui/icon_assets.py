"""Shared pixmap/icon loaders for bundled UI assets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor, QTransform

from steempeg.core.dash.health import WARNING_ICON_FILE, ClipHealth, HEALTH_ICON_FILES
from steempeg.infra.paths import get_resource_path

_ARROW_ROTATIONS = {
    "down": 0,
    "up": 180,
    "left": 90,
    "right": -90,
}


def load_pixmap(name: str, size: int = 16) -> QPixmap:
    pix = QPixmap(get_resource_path(name))
    if pix.isNull():
        return QPixmap()
    return pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def _icon_from_pixmap(pix: QPixmap) -> QIcon:
    if pix.isNull():
        return QIcon()
    icon = QIcon()
    # Keep icons colored even when actions/widgets are temporarily disabled.
    icon.addPixmap(pix, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Disabled, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(pix, QIcon.Mode.Selected, QIcon.State.Off)
    return icon


def load_icon(name: str, size: int = 16) -> QIcon:
    return _icon_from_pixmap(load_pixmap(name, size))


def arrow_pixmap(size: int = 12, *, direction: str = "down") -> QPixmap:
    """arrow.png points down by default."""
    pix = load_pixmap("arrow.png", size)
    if pix.isNull():
        return pix
    angle = _ARROW_ROTATIONS.get(direction, 0)
    if not angle:
        return pix
    return pix.transformed(QTransform().rotate(angle), Qt.TransformationMode.SmoothTransformation)


def arrow_icon(size: int = 12, *, direction: str = "down") -> QIcon:
    return _icon_from_pixmap(arrow_pixmap(size, direction=direction))


def info_icon(size: int = 14) -> QIcon:
    return load_icon("info.png", size)


def tinted_pixmap(name: str, color: str | QColor, size: int = 16) -> QPixmap:
    """Recolor a bundled asset (keeps alpha) via SourceIn tint."""
    src = QPixmap(get_resource_path(name))
    if src.isNull():
        return QPixmap()
    scaled = src.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if isinstance(color, str):
        color = QColor(color)
    out = QPixmap(scaled.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawPixmap(0, 0, scaled)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), color)
    painter.end()
    return out


def tinted_icon(name: str, color: str | QColor, size: int = 16) -> QIcon:
    return _icon_from_pixmap(tinted_pixmap(name, color, size))


def close_clip_icon(size: int = 16) -> QIcon:
    """Red-tinted cancel.png for the player header close chip."""
    return tinted_icon("cancel.png", "#e05555", size)


def preview_settings_icon(size: int = 16) -> QIcon:
    """settings.png for the player header preview-quality chip."""
    return load_icon("settings.png", size)


def health_icon(level: ClipHealth, size: int = 16) -> QIcon:
    return load_icon(HEALTH_ICON_FILES.get(level, WARNING_ICON_FILE), size)


def warning_icon(size: int = 16) -> QIcon:
    return load_icon(WARNING_ICON_FILE, size)


def warning_pixmap(size: int = 16) -> QPixmap:
    return load_pixmap(WARNING_ICON_FILE, size)
