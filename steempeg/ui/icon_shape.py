"""Game-icon corner shape preference (list / grid / queue / headers).

Three modes from the v42 Settings Visual tab:

* ``square`` — sharp corners (classic)
* ``soft`` — Steam-like near-round / squircle (**default**)
* ``circle`` — full pill / circle
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap

KEY_GAME_ICON_SHAPE = "game_icon_shape"

ICON_SHAPE_SQUARE = "square"
ICON_SHAPE_SOFT = "soft"
ICON_SHAPE_CIRCLE = "circle"

ICON_SHAPE_DEFAULT = ICON_SHAPE_SOFT

ICON_SHAPE_LABELS: tuple[tuple[str, str], ...] = (
    (ICON_SHAPE_SQUARE, "Square"),
    (ICON_SHAPE_SOFT, "Soft (Steam-like)"),
    (ICON_SHAPE_CIRCLE, "Circle"),
)

# Sizes we bake into QIcon so list/grid/header scales stay crisp.
_ICON_SIZES: tuple[int, ...] = (16, 20, 24, 26, 28, 32, 40, 48)

_current_shape: str = ICON_SHAPE_DEFAULT


def normalize_icon_shape(value: object | None) -> str:
    text = str(value or "").strip().lower()
    if text in (ICON_SHAPE_SQUARE, ICON_SHAPE_SOFT, ICON_SHAPE_CIRCLE):
        return text
    # Older / friendly aliases
    if text in ("round", "rounded", "full"):
        return ICON_SHAPE_CIRCLE
    if text in ("squircle", "near", "near-round", "steam"):
        return ICON_SHAPE_SOFT
    return ICON_SHAPE_DEFAULT


def get_icon_shape() -> str:
    return _current_shape


def set_icon_shape(shape: object | None) -> str:
    global _current_shape
    _current_shape = normalize_icon_shape(shape)
    return _current_shape


def load_icon_shape_from_settings(settings: dict | None) -> str:
    raw = (settings or {}).get(KEY_GAME_ICON_SHAPE, ICON_SHAPE_DEFAULT)
    return set_icon_shape(raw)


def soft_corner_radius(size: int) -> float:
    """Near-round radius — clearly softer than square, not a full circle."""
    return float(max(4, round(size * 0.32)))


def shaped_game_icon_pixmap(
    source: QPixmap,
    size: int,
    shape: str | None = None,
) -> QPixmap:
    """Return a transparent ``size×size`` pixmap clipped to ``shape``."""
    if source is None or source.isNull() or size <= 0:
        out = QPixmap(max(1, size), max(1, size))
        out.fill(Qt.GlobalColor.transparent)
        return out

    mode = normalize_icon_shape(shape if shape is not None else _current_shape)
    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - size) // 2)
    y = max(0, (scaled.height() - size) // 2)
    cropped = scaled.copy(x, y, size, size)

    if mode == ICON_SHAPE_SQUARE:
        if cropped.width() == size and cropped.height() == size:
            return cropped
        square = QPixmap(size, size)
        square.fill(Qt.GlobalColor.transparent)
        p = QPainter(square)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(0, 0, cropped)
        p.end()
        return square

    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    if mode == ICON_SHAPE_CIRCLE:
        clip.addEllipse(0, 0, float(size), float(size))
    else:
        r = soft_corner_radius(size)
        clip.addRoundedRect(0, 0, float(size), float(size), r, r)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    return result


def shaped_game_icon(source: QPixmap, shape: str | None = None) -> QIcon:
    """QIcon with shaped pixmaps at common list/grid sizes."""
    icon = QIcon()
    if source is None or source.isNull():
        return icon
    mode = normalize_icon_shape(shape if shape is not None else _current_shape)
    for sz in _ICON_SIZES:
        icon.addPixmap(shaped_game_icon_pixmap(source, sz, mode))
    return icon
