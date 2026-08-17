"""HiDPI-aware pixmaps/icons from bundled Steempeg logo assets."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

from steempeg.infra.paths import get_resource_path


def app_window_icon() -> QIcon:
    """Best bundled icon for window chrome and taskbar / dock buttons."""
    # Linux docks (GNOME) often ignore .ico; Windows prefers the multi-size .ico.
    names = ("logo.png", "logo.ico") if sys.platform != "win32" else ("logo.ico", "logo.png")
    for name in names:
        path = get_resource_path(name)
        if os.path.isfile(path):
            icon = QIcon(path)
            if not icon.isNull():
                if sys.platform != "win32" and path.lower().endswith(".png"):
                    for edge in (16, 24, 32, 48, 64, 128, 256):
                        icon.addFile(path, QSize(edge, edge))
                return icon
    return QIcon()


def primary_device_pixel_ratio() -> float:
    """Primary screen DPR (1.0 on 100% HD, 1.25/1.5/2.0 on scaled / HiDPI)."""
    app = QGuiApplication.instance()
    if app is None:
        return 1.0
    screen = app.primaryScreen()
    if screen is None:
        return 1.0
    dpr = float(screen.devicePixelRatio())
    return dpr if dpr > 0 else 1.0


# Back-compat alias for older call sites.
_primary_device_pixel_ratio = primary_device_pixel_ratio


def chrome_icon_slot_size(preferred: int = 16, *, bar_height: int | None = None) -> int:
    """Square icon edge that fits inside a title-bar without clipping.

    HD / 100% DPI bars are short (``TITLE_BAR_HEIGHT``); never let the glyph be
    taller than the chrome or sit in a non-square ``QLabel`` slot.
    """
    from steempeg.ui import design_tokens as tok

    bar = int(bar_height if bar_height is not None else tok.TITLE_BAR_HEIGHT)
    # 4px total vertical slack so Soft/Circle antialias is not clipped.
    cap = max(12, bar - 4)
    return max(12, min(int(preferred), cap))


def square_fit_pixmap(
    source: QPixmap,
    logical_size: int,
    *,
    dpr: float | None = None,
) -> QPixmap:
    """KeepAspectRatio-fit ``source`` into a transparent ``logical_size`` square.

    Never stretches. Non-square assets (e.g. steamdeck.png) are letterboxed.
    Output buffer is ``round(logical_size * dpr)`` device pixels with DPR set so
    QLabel paints at the intended logical size on HiDPI and 100% HD alike.
    """
    size = max(1, int(logical_size))
    if dpr is None:
        dpr = _primary_device_pixel_ratio()
    dpr = float(dpr) if dpr and dpr > 0 else 1.0
    phys = max(1, int(round(size * dpr)))

    out = QPixmap(phys, phys)
    out.fill(Qt.GlobalColor.transparent)
    if source is None or source.isNull():
        out.setDevicePixelRatio(dpr)
        return out

    # Treat the buffer as raw device pixels regardless of source DPR metadata.
    raw = QPixmap(source)
    raw.setDevicePixelRatio(1.0)
    scaled = raw.scaled(
        phys,
        phys,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if scaled.isNull():
        out.setDevicePixelRatio(dpr)
        return out

    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    x = (phys - scaled.width()) // 2
    y = (phys - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    out.setDevicePixelRatio(dpr)
    return out


def apply_square_icon(
    label: QLabel,
    pixmap: QPixmap | None,
    size: int,
) -> None:
    """Put an icon in a square ``QLabel`` slot — never stretch to a rectangle."""
    edge = max(1, int(size))
    label.setScaledContents(False)
    label.setFixedSize(edge, edge)
    label.setMinimumSize(edge, edge)
    label.setMaximumSize(edge, edge)
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if pixmap is not None and not pixmap.isNull():
        logical_w = int(round(pixmap.width() / max(float(pixmap.devicePixelRatio()), 1.0)))
        logical_h = int(round(pixmap.height() / max(float(pixmap.devicePixelRatio()), 1.0)))
        if logical_w != edge or logical_h != edge:
            label.setPixmap(square_fit_pixmap(pixmap, edge))
        else:
            label.setPixmap(pixmap)
    else:
        label.clear()


def app_logo_pixmap(size_px: int, *, dpr: float | None = None) -> QPixmap | None:
    """Crisp inline logo for title bars and small chrome affordances."""
    if size_px <= 0:
        return None
    if dpr is None:
        dpr = _primary_device_pixel_ratio()
    dpr = float(dpr) if dpr and dpr > 0 else 1.0
    phys = max(1, int(round(size_px * dpr)))

    source = QPixmap()
    icon = app_window_icon()
    if not icon.isNull():
        # Request device pixels; square_fit_pixmap owns the final DPR metadata.
        candidate = icon.pixmap(phys, phys)
        if not candidate.isNull():
            candidate.setDevicePixelRatio(1.0)
            source = candidate

    if source.isNull():
        png_path = get_resource_path("logo.png")
        if not os.path.isfile(png_path):
            return None
        source = QPixmap(png_path)
        if source.isNull():
            return None

    return square_fit_pixmap(source, size_px, dpr=dpr)
