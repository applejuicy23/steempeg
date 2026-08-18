"""Compact screenshot tiles — photo size × ClipCard language.

Size matches the classic Screenshots grid (~160×90 image + caption).
Chrome borrows ClipCard: footer bar, purple hover/selection ring, press scale,
inline source logo in the meta row (Steam vs Steempeg), and a persistent
«just opened» accent — without the large 254×184 clip cards.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.ui.design_tokens import CARD_PRESS_DURATION_MS, CARD_PRESS_SCALE

# ClipCard accent family
_ACCENT = QColor("#b29ae7")
_ACCENT_HOVER = QColor("#7a6aa8")
_ACCENT_OPENED = QColor("#d4c4f5")
_IDLE_BORDER = QColor("#444444")
_IMG_BG = QColor("#1a1a1a")
_FOOTER_BG = QColor("#383838")
_TITLE_FG = QColor("#e0e0e0")
_META_FG = QColor("#888888")

# Photo-scale (pre-enlargement footprint); footer stays roomy for text padding
_W = 168
_IMG_H = 94
_FOOTER_H = 48
_H = _IMG_H + _FOOTER_H
# Public cell size for QListWidget sizeHints (must match setFixedSize).
SCREENSHOT_PHOTO_W = _W
SCREENSHOT_PHOTO_H = _H
SCREENSHOT_PHOTO_SIZE = QSize(_W, _H)
_RADIUS = 10.0
_PAD_X = 12
_PAD_TOP = 8
_PAD_BOTTOM = 8
_TITLE_GAP = 3
_DRAG_SLOP = 6
_ICON_PX = 16
_ICON_GAP = 5
_SOURCE_ICON_PX = 14
_SOURCE_ICON_GAP = 4

_source_icon_cache: dict[str, QPixmap] = {}


def _load_source_icon(source: str, dpr: float = 1.0) -> QPixmap:
    """Bundled Steam / Steempeg logo for the footer meta row."""
    key = "steam" if (source or "").strip().lower() == "steam" else "steempeg"
    dpr = max(1.0, float(dpr or 1.0))
    cache_key = f"{key}@{_SOURCE_ICON_PX}@{dpr:.2f}"
    cached = _source_icon_cache.get(cache_key)
    if cached is not None and not cached.isNull():
        return cached
    pix = QPixmap()
    if key == "steempeg":
        try:
            from steempeg.ui.icon_utils import app_logo_pixmap

            logo = app_logo_pixmap(_SOURCE_ICON_PX, dpr=dpr)
            if logo is not None and not logo.isNull():
                pix = logo
        except Exception:
            pix = QPixmap()
    if pix.isNull():
        asset = "steam.png" if key == "steam" else "logo.png"
        path = get_resource_path(asset)
        if path and os.path.isfile(path):
            src = QPixmap(path)
            if not src.isNull():
                phys = max(1, int(round(_SOURCE_ICON_PX * dpr)))
                try:
                    from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap

                    shaped = shaped_game_icon_pixmap(src, phys, ICON_SHAPE_CIRCLE)
                    if shaped is not None and not shaped.isNull():
                        pix = shaped
                        pix.setDevicePixelRatio(dpr)
                except Exception:
                    pix = src.scaled(
                        phys,
                        phys,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    pix.setDevicePixelRatio(dpr)
    if not pix.isNull():
        _source_icon_cache[cache_key] = pix
    return pix


class ScreenshotPhoto(QWidget):
    """Mini photo card: rounded thumb + ClipCard-style footer."""

    def __init__(
        self,
        thumb_path: str = "",
        *,
        title: str = "",
        subtitle: str = "",
        game_icon_path: str = "",
        on_left_click: Optional[Callable[[QMouseEvent], None]] = None,
        on_right_click: Optional[Callable[[QMouseEvent], None]] = None,
        on_activate: Optional[Callable[[], None]] = None,
        on_drag_over: Optional[Callable[[QPoint], None]] = None,
        source: str = "steempeg",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._on_left_click = on_left_click
        self._on_right_click = on_right_click
        self._on_activate = on_activate
        self._on_drag_over = on_drag_over
        self._title = (title or "").strip()
        self._subtitle = (subtitle or "").strip()
        self._source = self._normalize_source(source)
        self._pix = QPixmap()
        self._icon = QPixmap()
        self._hovered = False
        self._pressed = False
        self._selected = False
        self._opened = False
        self._scale = 1.0
        self._press_pos: QPoint | None = None
        self._dragged = False
        self._anim: QVariantAnimation | None = None
        self.setFixedSize(_W, _H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        if thumb_path:
            self.set_thumbnail(thumb_path)
        if game_icon_path:
            self.set_game_icon(game_icon_path)

    def set_title(self, title: str) -> None:
        text = (title or "").strip()
        if text == self._title:
            return
        self._title = text
        self.update()

    def set_subtitle(self, subtitle: str) -> None:
        text = (subtitle or "").strip()
        if text == self._subtitle:
            return
        self._subtitle = text
        self.update()

    @staticmethod
    def _normalize_source(source: str) -> str:
        key = (source or "steempeg").strip().lower()
        return "steam" if key == "steam" else "steempeg"

    def set_source(self, source: str) -> None:
        key = self._normalize_source(source)
        if key == self._source:
            return
        self._source = key
        self.update()

    def source_key(self) -> str:
        return self._source

    def set_thumbnail(self, thumb_path: str) -> None:
        if thumb_path and os.path.isfile(thumb_path):
            pix = QPixmap(thumb_path)
            if not pix.isNull():
                self._pix = pix
                self.update()
                return
        self._pix = QPixmap()
        self.update()

    def set_game_icon(self, icon_path: str) -> None:
        """Optional ClipCard-style game logo in the footer (local path only)."""
        if icon_path and os.path.isfile(icon_path):
            try:
                from steempeg.ui.icon_shape import shaped_game_icon_pixmap

                src = QPixmap(icon_path)
                if not src.isNull():
                    shaped = shaped_game_icon_pixmap(src, _ICON_PX)
                    if shaped is not None and not shaped.isNull():
                        self._icon = shaped
                        self.update()
                        return
            except Exception:
                pix = QPixmap(icon_path)
                if not pix.isNull():
                    self._icon = pix.scaled(
                        _ICON_PX,
                        _ICON_PX,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.update()
                    return
        if not self._icon.isNull():
            self._icon = QPixmap()
            self.update()

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = bool(selected)
        self.update()

    def set_opened(self, opened: bool) -> None:
        if self._opened == opened:
            return
        self._opened = bool(opened)
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        # With grabMouse (paint-drag / press-scale), leaving the tile must not
        # cancel the press — release still arrives on this widget.
        if self._pressed and self.mouseGrabber() is not self:
            self._finish_press(activate=False)
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton and self._on_right_click:
            self._on_right_click(event)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin_press(event.position().toPoint())
            if self._on_left_click:
                self._on_left_click(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def begin_external_press(self, global_pos: QPoint) -> None:
        """Continue an LMB press that started on a lazy placeholder (viewport)."""
        self._begin_press(self.mapFromGlobal(global_pos))

    def _begin_press(self, local_pos: QPoint) -> None:
        self._pressed = True
        self._dragged = False
        self._press_pos = QPoint(local_pos)
        self._animate_to(float(CARD_PRESS_SCALE))
        self.grabMouse()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pressed and self._press_pos is not None:
            delta = event.position().toPoint() - self._press_pos
            if abs(delta.x()) > _DRAG_SLOP or abs(delta.y()) > _DRAG_SLOP:
                self._dragged = True
                # Paint-select: while LMB is held, select every card under the cursor
                # (mouse is grabbed, so other cards never see enter events).
                if self._on_drag_over is not None:
                    self._on_drag_over(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            activate = not self._dragged
            self._finish_press(activate=activate)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _finish_press(self, *, activate: bool) -> None:
        self._pressed = False
        self._press_pos = None
        if self.mouseGrabber() is self:
            self.releaseMouse()
        self._animate_to(1.0)
        if activate and self._on_activate:
            self._on_activate()

    def _animate_to(self, target: float) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        start = float(self._scale)
        if abs(start - target) < 0.01:
            self._scale = target
            self.update()
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(float(target))
        anim.setDuration(int(CARD_PRESS_DURATION_MS))
        anim.setEasingCurve(
            QEasingCurve.Type.OutCubic if target >= start else QEasingCurve.Type.InCubic
        )
        anim.valueChanged.connect(self._on_scale)
        anim.finished.connect(lambda: setattr(self, "_anim", None))
        self._anim = anim
        anim.start()

    def _on_scale(self, value) -> None:
        self._scale = float(value)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_W, _H)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # Whole-card press: scale the entire tile (not only the image well).
        scale = float(self._scale)
        if abs(scale - 1.0) > 0.001:
            cx = _W / 2.0
            cy = _H / 2.0
            p.translate(cx, cy)
            p.scale(scale, scale)
            p.translate(-cx, -cy)

        # Inset so a 3px ClipCard-style ring never clips.
        outer = QRectF(1.5, 1.5, _W - 3.0, _H - 3.0)
        card = QPainterPath()
        card.addRoundedRect(outer, _RADIUS, _RADIUS)

        # --- image well (rounded top, square join into footer) ---
        img = QRectF(outer.left(), outer.top(), outer.width(), float(_IMG_H))
        img_path = QPainterPath()
        img_path.addRoundedRect(img, _RADIUS, _RADIUS)
        flat = QPainterPath()
        flat.addRect(QRectF(img.left(), img.bottom() - _RADIUS, img.width(), _RADIUS))
        img_path = img_path.united(flat)

        p.save()
        p.setClipPath(img_path.intersected(card))
        p.fillRect(img, _IMG_BG)
        if not self._pix.isNull():
            target = self._pix.scaled(
                max(1, int(round(img.width()))),
                max(1, int(round(img.height()))),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = int(round(img.left() + (img.width() - target.width()) / 2))
            y = int(round(img.top() + (img.height() - target.height()) / 2))
            p.drawPixmap(x, y, target)
        p.restore()

        # --- ClipCard footer ---
        foot = QRectF(outer.left(), outer.top() + _IMG_H, outer.width(), float(_FOOTER_H))
        foot_path = QPainterPath()
        foot_path.addRoundedRect(foot, _RADIUS, _RADIUS)
        top_sq = QPainterPath()
        top_sq.addRect(QRectF(foot.left(), foot.top(), foot.width(), _RADIUS))
        foot_path = foot_path.united(top_sq)
        p.fillPath(foot_path.intersected(card), _FOOTER_BG)

        # Match ClipCard title/date faces (13px bold / 11px meta) with real padding
        # so text doesn't glue to the image edge or the card bottom.
        title_font = QFont("Segoe UI")
        title_font.setPixelSize(13)
        title_font.setBold(True)
        meta_font = QFont("Segoe UI")
        meta_font.setPixelSize(11)
        fm_title = QFontMetrics(title_font)
        fm_meta = QFontMetrics(meta_font)

        text_left = int(foot.left()) + _PAD_X
        text_width = int(foot.width()) - _PAD_X * 2
        title_top = int(foot.top()) + _PAD_TOP
        title_left = text_left
        title_width = text_width

        if not self._icon.isNull():
            icon_y = title_top + max(0, (fm_title.height() - _ICON_PX) // 2)
            p.drawPixmap(text_left, icon_y, self._icon)
            title_left = text_left + _ICON_PX + _ICON_GAP
            title_width = max(24, text_width - _ICON_PX - _ICON_GAP)

        if self._subtitle:
            # Meta uses full footer text width (under the logo) so the date is
            # not squeezed by the icon; game name elides first if needed.
            title_rect = QRect(title_left, title_top, title_width, fm_title.height())
            meta_rect = QRect(
                text_left,
                title_rect.bottom() + _TITLE_GAP,
                text_width,
                fm_meta.height(),
            )
            # Keep date clear of the bottom curve.
            max_meta_bottom = int(foot.bottom()) - _PAD_BOTTOM
            if meta_rect.bottom() > max_meta_bottom:
                meta_rect.moveBottom(max_meta_bottom)
            p.setFont(title_font)
            p.setPen(_TITLE_FG)
            p.drawText(
                title_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                fm_title.elidedText(self._title, Qt.TextElideMode.ElideRight, title_width),
            )
            source_icon = _load_source_icon(
                self._source, dpr=max(1.0, float(self.devicePixelRatioF()))
            )
            meta_left = text_left
            meta_text_width = text_width
            if not source_icon.isNull():
                icon_y = meta_rect.top() + max(0, (meta_rect.height() - _SOURCE_ICON_PX) // 2)
                p.drawPixmap(text_left, icon_y, source_icon)
                meta_left = text_left + _SOURCE_ICON_PX + _SOURCE_ICON_GAP
                meta_text_width = max(24, text_width - _SOURCE_ICON_PX - _SOURCE_ICON_GAP)
            meta_draw = QRect(
                meta_left,
                meta_rect.top(),
                meta_text_width,
                meta_rect.height(),
            )
            p.setFont(meta_font)
            p.setPen(_META_FG)
            p.drawText(
                meta_draw,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                fm_meta.elidedText(
                    self._subtitle, Qt.TextElideMode.ElideRight, meta_text_width
                ),
            )
        else:
            title_rect = QRect(
                title_left,
                title_top,
                title_width,
                int(foot.height()) - _PAD_TOP - _PAD_BOTTOM,
            )
            p.setFont(title_font)
            p.setPen(_TITLE_FG)
            p.drawText(
                title_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                fm_title.elidedText(self._title, Qt.TextElideMode.ElideRight, title_width),
            )

        # --- ClipCard border overlay ---
        if self._opened:
            border, width = _ACCENT_OPENED, 2.5
        elif self._selected:
            border, width = _ACCENT, 3.0
        elif self._hovered:
            border, width = _ACCENT_HOVER, 2.0
        else:
            # Soft idle ring — photo float, but still reads as a card.
            border, width = _IDLE_BORDER, 1.0

        pen = p.pen()
        pen.setColor(border)
        pen.setWidthF(width)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(card)
        p.end()
