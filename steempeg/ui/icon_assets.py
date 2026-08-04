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
    """Load a bundled asset into a transparent ``size×size`` pixmap (never stretched)."""
    pix = QPixmap(get_resource_path(name))
    if pix.isNull():
        return QPixmap()
    from steempeg.ui.icon_utils import square_fit_pixmap

    # dpr=1.0: callers pass these to QLabel/QIcon at logical px; HiDPI chrome
    # logos go through app_logo_pixmap instead.
    return square_fit_pixmap(pix, size, dpr=1.0)


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


def _opaque_content_rect(pix: QPixmap, *, alpha_min: int = 24) -> tuple[int, int, int, int]:
    """Tight bbox of non-transparent pixels (x, y, w, h), or full pixmap if empty."""
    img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if img.pixelColor(x, y).alpha() >= alpha_min:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if max_x < min_x or max_y < min_y:
        return 0, 0, w, h
    return min_x, min_y, max_x - min_x + 1, max_y - min_y + 1


def title_bar_info_pixmap(color: str | QColor, size: int = 16) -> QPixmap:
    """Tinted info.png for the title-bar About (i), geometrically centered in ``size``.

    Crops to the opaque ring first so asymmetric PNG padding cannot skew the glyph
    inside the circular hover hitbox.
    """
    raw = QPixmap(get_resource_path("info.png"))
    if raw.isNull():
        return QPixmap()
    x, y, bw, bh = _opaque_content_rect(raw)
    side = max(bw, bh)
    # Square crop around the opaque content center.
    cx = x + bw / 2.0
    cy = y + bh / 2.0
    left = int(round(cx - side / 2.0))
    top = int(round(cy - side / 2.0))
    cropped = raw.copy(max(left, 0), max(top, 0), side, side)
    if isinstance(color, str):
        color = QColor(color)
    scaled = cropped.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawPixmap(0, 0, scaled)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), color)
    painter.end()
    return out


def title_bar_info_icons(size: int = 16) -> tuple[QIcon, QIcon]:
    """Idle (soft gray) + hot (near-white) icons for the title-bar About (i)."""
    # Slightly muted vs Steempeg title white — not as gray as TitleBarSubtitle (#858585).
    idle = _icon_from_pixmap(title_bar_info_pixmap("#b8b8b8", size))
    hot = _icon_from_pixmap(title_bar_info_pixmap("#e8e8e8", size))
    return idle, hot


def title_bar_settings_pixmap(color: str | QColor, size: int = 16) -> QPixmap:
    """Tinted settings2.png for the title-bar Settings control."""
    return tinted_pixmap("settings2.png", color, size)


def title_bar_settings_icons(size: int = 16) -> tuple[QIcon, QIcon]:
    """Idle + hot icons for the title-bar Settings (settings2.png)."""
    idle = _icon_from_pixmap(title_bar_settings_pixmap("#b8b8b8", size))
    hot = _icon_from_pixmap(title_bar_settings_pixmap("#e8e8e8", size))
    return idle, hot


def title_bar_update_pixmap(color: str | QColor, size: int = 16) -> QPixmap:
    """Tinted update.png for the portable title-bar Updates spinner.

    Crops to the opaque glyph and recenters in a square so rotation orbits the
    visual center (source asset is non-square 387×396 with uneven padding).
    """
    raw = QPixmap(get_resource_path("update.png"))
    if raw.isNull():
        return QPixmap()
    x, y, bw, bh = _opaque_content_rect(raw)
    side = max(bw, bh, 1)
    cx = x + bw / 2.0
    cy = y + bh / 2.0
    left = int(round(cx - side / 2.0))
    top = int(round(cy - side / 2.0))
    src_x, src_y = max(left, 0), max(top, 0)
    src_w = min(side, raw.width() - src_x)
    src_h = min(side, raw.height() - src_y)
    cropped = QPixmap(side, side)
    cropped.fill(Qt.GlobalColor.transparent)
    crop_p = QPainter(cropped)
    crop_p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    crop_p.drawPixmap(src_x - left, src_y - top, raw.copy(src_x, src_y, src_w, src_h))
    crop_p.end()
    if isinstance(color, str):
        color = QColor(color)
    scaled = cropped.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawPixmap(0, 0, scaled)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), color)
    painter.end()
    return out


def title_bar_update_icons(size: int = 16) -> tuple[QIcon, QIcon]:
    """Idle + hot icons for the title-bar Updates spinner button."""
    idle = _icon_from_pixmap(title_bar_update_pixmap("#b8b8b8", size))
    hot = _icon_from_pixmap(title_bar_update_pixmap("#e8e8e8", size))
    return idle, hot


def tinted_pixmap(name: str, color: str | QColor, size: int = 16) -> QPixmap:
    """Recolor a bundled asset (keeps alpha) via SourceIn tint into a square."""
    from steempeg.ui.icon_utils import square_fit_pixmap

    src = QPixmap(get_resource_path(name))
    if src.isNull():
        return QPixmap()
    scaled = square_fit_pixmap(src, size, dpr=1.0)
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


def add_clip_icon(size: int = 18) -> QIcon:
    """Purple-tinted addclip.png for the portable «Choose a Clip» chip."""
    return tinted_icon("addclip.png", "#d4c8f5", size)


def add_to_queue_icon(size: int = 14) -> QIcon:
    """Painted bold plus — weight matched to 13px bold chip text (not plus.png)."""
    return bold_plus_icon(size, "#ffcc00")


def bold_plus_icon(size: int = 12, color: str | QColor = "#ffcc00") -> QIcon:
    """Plus for chip labels — tight box, glyph ≈ cap-height of bold 13px Q."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen

    if isinstance(color, str):
        color = QColor(color)
    dpr = 2.0
    px = max(int(round(size * dpr)), 1)
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    # Fill most of the (small) icon box — no empty 18px margins.
    arm = max(size - 2, 8) * dpr
    thickness = max(2.0, size * 0.22) * dpr
    mid = px * 0.5
    mid_y = mid + 0.5 * dpr
    half = arm * 0.5
    pen = QPen(color)
    pen.setWidthF(thickness)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(mid - half, mid_y), QPointF(mid + half, mid_y))
    painter.drawLine(QPointF(mid, mid_y - half), QPointF(mid, mid_y + half))
    painter.end()
    pix.setDevicePixelRatio(dpr)
    return _icon_from_pixmap(pix)


def queue_chip_icon(size: int = 16, *, color: str = "#ffcc00") -> QIcon:
    """Tinted queue.png for portable queue chips (yellow header / green theatre CTA)."""
    return tinted_icon("queue.png", color, size)


def preview_settings_icon(size: int = 16) -> QIcon:
    """settings.png for the player header preview-quality chip."""
    return load_icon("settings.png", size)


def playinfo_pixmap(color: str | QColor, size: int = 16) -> QPixmap:
    """Tinted playinfo2.png for the player header Clip info chip."""
    return tinted_pixmap("playinfo2.png", color, size)


def playinfo_icons(size: int = 16) -> tuple[QIcon, QIcon]:
    """Idle (soft gray) + hot (near-white) icons — same tints as title-bar tools."""
    idle = _icon_from_pixmap(playinfo_pixmap("#b8b8b8", size))
    hot = _icon_from_pixmap(playinfo_pixmap("#e8e8e8", size))
    return idle, hot


def playinfo_icon(size: int = 16) -> QIcon:
    """Idle playinfo2.png for the player header Clip info chip."""
    return playinfo_icons(size)[0]


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
