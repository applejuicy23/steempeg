"""Shared pixmap/icon loaders for bundled UI assets."""
from __future__ import annotations

from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor, QTransform, QImage
from PySide6.QtCore import Qt

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


def theater_mode_icon(size: int = 22, *, closed: bool = False) -> QIcon:
    """Theatre chrome icon matched to fullscreen *height*, full plate visible.

    Asset is wider than tall. Scaling into a square with KeepAspectRatio leaves it
    short; Expanding crops the sides. Instead: strip empty padding only, then
    scale so height == ``size`` (same as fullscreen). Width may be a bit wider.
    """
    key = (bool(closed), int(size))
    cached = _THEATER_ICON_CACHE.get(key)
    if cached is not None:
        return cached

    name = "theatremodeclosed.png" if closed else "theatremode.png"
    src = QPixmap(get_resource_path(name))
    if src.isNull():
        return QIcon()

    img = src.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if img.pixelColor(x, y).alpha() < 16:
                continue
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y

    if max_x >= min_x and max_y >= min_y:
        cropped = QPixmap.fromImage(
            img.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
        )
    else:
        cropped = src

    cw = max(1, cropped.width())
    ch = max(1, cropped.height())
    out_h = int(size)
    out_w = max(out_h, int(round(cw * (out_h / float(ch)))))
    scaled = cropped.scaled(
        out_w,
        out_h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    icon = _icon_from_pixmap(scaled)
    _THEATER_ICON_CACHE[key] = icon
    return icon


_THEATER_ICON_CACHE: dict[tuple[bool, int], QIcon] = {}


def health_icon(level: ClipHealth, size: int = 16) -> QIcon:
    return load_icon(HEALTH_ICON_FILES.get(level, WARNING_ICON_FILE), size)


def warning_icon(size: int = 16) -> QIcon:
    return load_icon(WARNING_ICON_FILE, size)


def warning_pixmap(size: int = 16) -> QPixmap:
    return load_pixmap(WARNING_ICON_FILE, size)
