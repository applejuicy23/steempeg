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


# Opaque-crop + tint caches. info.png / update.png are ~400–860px masters;
# Settings alone used to re-scan them per hint (~20×) on the UI thread.
_OPAQUE_RECT_CACHE: dict[tuple[int, int], tuple[int, int, int, int]] = {}
_CROPPED_SQUARE_CACHE: dict[str, QPixmap] = {}
_TINTED_CROP_CACHE: dict[tuple[str, str, int], QPixmap] = {}


def _opaque_content_rect(pix: QPixmap, *, alpha_min: int = 24) -> tuple[int, int, int, int]:
    """Tight bbox of non-transparent pixels (x, y, w, h), or full pixmap if empty.

    Scans raw ARGB bytes (not per-pixel QColor) and caches by pixmap cacheKey.
    """
    key = (int(pix.cacheKey()), int(alpha_min))
    hit = _OPAQUE_RECT_CACHE.get(key)
    if hit is not None:
        return hit

    img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return 0, 0, max(w, 0), max(h, 0)

    min_x, min_y, max_x, max_y = w, h, -1, -1
    bpl = img.bytesPerLine()
    # ARGB32 little-endian layout is B,G,R,A — alpha at +3.
    try:
        mv = memoryview(img.constBits()).cast("B")
        for y in range(h):
            row = y * bpl
            for x in range(w):
                if mv[row + x * 4 + 3] >= alpha_min:
                    if x < min_x:
                        min_x = x
                    if y < min_y:
                        min_y = y
                    if x > max_x:
                        max_x = x
                    if y > max_y:
                        max_y = y
    except (TypeError, ValueError, BufferError):
        # Fallback if constBits is not a buffer on this Qt build.
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
        result = (0, 0, w, h)
    else:
        result = (min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
    _OPAQUE_RECT_CACHE[key] = result
    return result


def _cropped_opaque_square(asset_name: str) -> QPixmap:
    """Load ``asset_name``, crop to opaque glyph square once, cache forever."""
    hit = _CROPPED_SQUARE_CACHE.get(asset_name)
    if hit is not None and not hit.isNull():
        return hit

    raw = QPixmap(get_resource_path(asset_name))
    if raw.isNull():
        _CROPPED_SQUARE_CACHE[asset_name] = raw
        return raw

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
    painter = QPainter(cropped)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(src_x - left, src_y - top, raw.copy(src_x, src_y, src_w, src_h))
    painter.end()
    _CROPPED_SQUARE_CACHE[asset_name] = cropped
    return cropped


def _tinted_cropped_asset(asset_name: str, color: str | QColor, size: int) -> QPixmap:
    """Scale + SourceIn-tint a once-cropped opaque square (cached per color/size)."""
    if isinstance(color, QColor):
        color_key = color.name(QColor.NameFormat.HexArgb)
        fill = color
    else:
        color_key = str(color)
        fill = QColor(color)
    cache_key = (asset_name, color_key, int(size))
    hit = _TINTED_CROP_CACHE.get(cache_key)
    if hit is not None and not hit.isNull():
        return QPixmap(hit)

    cropped = _cropped_opaque_square(asset_name)
    if cropped.isNull():
        return QPixmap()
    edge = max(1, int(size))
    scaled = cropped.scaled(
        edge,
        edge,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    out = QPixmap(edge, edge)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawPixmap(0, 0, scaled)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), fill)
    painter.end()
    _TINTED_CROP_CACHE[cache_key] = out
    return QPixmap(out)


def title_bar_info_pixmap(color: str | QColor, size: int = 16) -> QPixmap:
    """Tinted info.png for the title-bar About (i), geometrically centered in ``size``.

    Crops to the opaque ring first so asymmetric PNG padding cannot skew the glyph
    inside the circular hover hitbox. Crop + tint are cached — Settings hints
    used to re-scan the 858px master on every ``_hint`` call.
    """
    return _tinted_cropped_asset("info.png", color, size)


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


# Same cadence as portable title-bar Updates button (_TitleBarUpdateButton).
UPDATE_ARROWS_TICK_MS = 16
UPDATE_ARROWS_DEG_PER_TICK = 7.5  # clockwise (top moves left→right)


def title_bar_update_pixmap(color: str | QColor, size: int = 16) -> QPixmap:
    """Tinted update.png for the portable title-bar Updates spinner.

    Crops to the opaque glyph and recenters in a square so rotation orbits the
    visual center (source asset is non-square 387×396 with uneven padding).
    """
    return _tinted_cropped_asset("update.png", color, size)


def title_bar_update_icons(size: int = 16) -> tuple[QIcon, QIcon]:
    """Idle + hot icons for the title-bar Updates spinner button."""
    idle = _icon_from_pixmap(title_bar_update_pixmap("#b8b8b8", size))
    hot = _icon_from_pixmap(title_bar_update_pixmap("#e8e8e8", size))
    return idle, hot


def update_arrows_spin_frame(
    color: str | QColor,
    size: int,
    angle: float,
    *,
    glyph_size: int | None = None,
) -> QPixmap:
    """Transparent square with purple-tinted ``update.png`` rotated by ``angle``.

    Orbit math matches the portable title-bar Updates button ``paintEvent``.
    """
    from PySide6.QtCore import QPointF

    sz = max(1, int(size))
    g = max(1, int(glyph_size if glyph_size is not None else sz))
    pix = title_bar_update_pixmap(color, g)
    out = QPixmap(sz, sz)
    out.fill(Qt.GlobalColor.transparent)
    if pix.isNull():
        return out
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    cx = sz * 0.5
    cy = sz * 0.5
    dpr = max(float(pix.devicePixelRatio()), 1.0)
    logical_w = pix.width() / dpr
    logical_h = pix.height() / dpr
    painter.translate(cx, cy)
    painter.rotate(float(angle) % 360.0)
    painter.drawPixmap(QPointF(-logical_w * 0.5, -logical_h * 0.5), pix)
    painter.end()
    return out


# Library Loading / search busy chrome — Gemini-style staggered bounce dots.
LOADING_WAVE_TICK_MS = 80
LOADING_WAVE_PHASE_STEP = 0.38  # rad/tick → ~1.3s full cycle
LOADING_WAVE_DOT_COUNT = 3

# Player-header status glyphs (Rendering cube / Completed check).
_STATUS_GLYPH_CACHE: dict[tuple[str, str, int], QPixmap] = {}


def _status_glyph_pixmap(name: str, color: str | QColor, size: int) -> QPixmap:
    """White-on-black master → tinted glyph (cached). Same pipeline as dash buttons."""
    # Local import — ``_glyph_pixmap_from_bw`` is defined later in this module.
    if isinstance(color, QColor):
        color_key = color.name(QColor.NameFormat.HexArgb)
        fill = color.name(QColor.NameFormat.HexRgb)
    else:
        color_key = str(color)
        fill = str(color)
    edge = max(1, int(size))
    cache_key = (name, color_key, edge)
    hit = _STATUS_GLYPH_CACHE.get(cache_key)
    if hit is not None and not hit.isNull():
        return QPixmap(hit)
    pix = _glyph_pixmap_from_bw(name, edge, color=fill)
    if not pix.isNull():
        _STATUS_GLYPH_CACHE[cache_key] = pix
    return QPixmap(pix)


def completed_status_pixmap(color: str | QColor, size: int = 22) -> QPixmap:
    """Tinted ``completed.png`` for Completed plaques / status badges."""
    return _status_glyph_pixmap("completed.png", color, size)


def completed_badge_icon(color: str | QColor, size: int = 18) -> QIcon:
    """Player-header Completed plaque icon (left of “Completed” text)."""
    return _icon_from_pixmap(completed_status_pixmap(color, size))


def rendering_status_pixmap(color: str | QColor, size: int = 22) -> QPixmap:
    """Tinted static ``rendering.png`` cube for the Rendering plaque."""
    return _status_glyph_pixmap("rendering.png", color, size)


def rendering_badge_icon(color: str | QColor, size: int = 18) -> QIcon:
    """Player-header Rendering plaque icon — static cube only (no orbit/square)."""
    return _icon_from_pixmap(rendering_status_pixmap(color, size))


def loading_wave_frame(
    color: str | QColor,
    width: int,
    height: int,
    phase: float,
) -> QPixmap:
    """Transparent badge with three purple dots in a staggered Y/opacity wave."""
    import math

    from PySide6.QtGui import QBrush, QPen

    w = max(1, int(width))
    h = max(1, int(height))
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    base = QColor(color) if not isinstance(color, QColor) else QColor(color)
    if not base.isValid():
        base = QColor("#a871ff")

    # Fit three dots in the badge; leave vertical room for bounce.
    radius = max(2.0, min(w / (LOADING_WAVE_DOT_COUNT * 2.6), h * 0.22))
    gap = radius * 0.9
    span = LOADING_WAVE_DOT_COUNT * (radius * 2) + (LOADING_WAVE_DOT_COUNT - 1) * gap
    start_x = (w - span) * 0.5 + radius
    cy = h * 0.55
    amp = max(1.5, h * 0.18)
    stagger = (2.0 * math.pi) / LOADING_WAVE_DOT_COUNT

    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(Qt.PenStyle.NoPen))
    for i in range(LOADING_WAVE_DOT_COUNT):
        t = float(phase) + i * stagger
        # Half-sine bounce (up only) — Gemini-like pulse.
        lift = max(0.0, math.sin(t))
        opacity = 0.28 + 0.72 * lift
        fill = QColor(base)
        fill.setAlphaF(max(0.0, min(1.0, opacity)))
        painter.setBrush(QBrush(fill))
        x = start_x + i * (radius * 2 + gap)
        y = cy - amp * lift
        painter.drawEllipse(
            int(round(x - radius)),
            int(round(y - radius)),
            int(round(radius * 2)),
            int(round(radius * 2)),
        )
    painter.end()
    return out


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


def _glyph_pixmap_from_bw(name: str, size: int = 16, *, color: str = "#ffffff") -> QPixmap:
    """Black-bg white line art → tinted glyph with alpha (black becomes transparent)."""
    src = QPixmap(get_resource_path(name))
    if src.isNull():
        return QPixmap()
    tint = QColor(color)
    img = src.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    for y in range(h):
        for x in range(w):
            c = img.pixelColor(x, y)
            # Luminance as alpha so anti-aliased edges stay soft.
            alpha = max(c.red(), c.green(), c.blue())
            img.setPixelColor(
                x,
                y,
                QColor(tint.red(), tint.green(), tint.blue(), alpha),
            )
    pix = QPixmap.fromImage(img)
    from steempeg.ui.icon_utils import square_fit_pixmap

    return square_fit_pixmap(pix, size, dpr=1.0)


def _white_glyph_pixmap(name: str, size: int = 16) -> QPixmap:
    return _glyph_pixmap_from_bw(name, size, color="#ffffff")


def _dash_button_glyph_icon(name: str, size: int = 16) -> QIcon:
    """Enabled = white; disabled = #555555 to match dash ``QPushButton:disabled`` text."""
    normal = _glyph_pixmap_from_bw(name, size, color="#ffffff")
    disabled = _glyph_pixmap_from_bw(name, size, color="#555555")
    if normal.isNull():
        return QIcon()
    icon = QIcon()
    icon.addPixmap(normal, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(normal, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(normal, QIcon.Mode.Selected, QIcon.State.Off)
    icon.addPixmap(
        disabled if not disabled.isNull() else normal,
        QIcon.Mode.Disabled,
        QIcon.State.Off,
    )
    return icon


def start_render_icon(size: int = 16) -> QIcon:
    """Desktop Start Render / Render Queue dash button glyph."""
    return _dash_button_glyph_icon("startrender.png", size)


def pause_render_icon(size: int = 16) -> QIcon:
    """Desktop Pause dash button glyph."""
    return _dash_button_glyph_icon("pauserender.png", size)


def cancel_render_icon(size: int = 16) -> QIcon:
    """Desktop Cancel dash button glyph."""
    return _dash_button_glyph_icon("cancelrender.png", size)


def logs_info_icon(size: int = 16) -> QIcon:
    """Desktop Logs dash button glyph."""
    return _dash_button_glyph_icon("logsinfo.png", size)


# Neo settings sidebar + content page-header glyphs (BW white-on-black masters).
# Colorized assets can drop in later without API change — keep filenames stable.
NEO_NAV_ICON_FILES: tuple[str, ...] = (
    "sourceinfo.png",
    "videosettings.png",
    "audiosettings.png",
    "exportsettings.png",
    "presetsettings.png",
)


def _glyph_icon_with_trailing_gap(name: str, size: int, trailing_gap: int) -> QIcon:
    """Dash-style white glyph; optional transparent pad on the right (icon→text gap)."""
    base = _dash_button_glyph_icon(name, size)
    gap = max(0, int(trailing_gap))
    if gap <= 0 or base.isNull():
        return base
    # Enabled + disabled faces so gray-out still matches dash buttons.
    out = QIcon()
    for mode, color in (
        (QIcon.Mode.Normal, "#ffffff"),
        (QIcon.Mode.Active, "#ffffff"),
        (QIcon.Mode.Selected, "#ffffff"),
        (QIcon.Mode.Disabled, "#555555"),
    ):
        glyph = _glyph_pixmap_from_bw(name, size, color=color)
        if glyph.isNull():
            continue
        canvas = QPixmap(size + gap, size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, glyph)
        painter.end()
        out.addPixmap(canvas, mode, QIcon.State.Off)
    return out if not out.isNull() else base


def neo_nav_tab_icon(index: int, size: int = 16, *, trailing_gap: int = 0) -> QIcon:
    """White glyph for neo sidebar tab ``index`` (Source…Presets).

    ``trailing_gap`` adds transparent pixels after the glyph so QPushButton
    icon→label spacing isn't cramped (Qt stylesheets don't expose that gap).
    """
    if index < 0 or index >= len(NEO_NAV_ICON_FILES):
        return QIcon()
    name = NEO_NAV_ICON_FILES[index]
    if trailing_gap > 0:
        return _glyph_icon_with_trailing_gap(name, size, trailing_gap)
    return _dash_button_glyph_icon(name, size)


def neo_page_title_icon(index: int, size: int = 16) -> QIcon:
    """White glyph for neo content page header ``index`` (no trailing gap)."""
    return neo_nav_tab_icon(index, size)


def preview_badge_icon(size: int = 16, *, color: str = "#ffffff") -> QIcon:
    """Desktop player-header Preview chip glyph (``play2.png``)."""
    return _icon_from_pixmap(_glyph_pixmap_from_bw("play2.png", size, color=color))


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
