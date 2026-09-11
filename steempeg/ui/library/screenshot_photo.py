"""Screenshot tiles — Size ladder × ClipCard language.

Medium = classic Screenshots photo (~168×142). Big ≈ Clips Big (time + size).
Small ≈ Clips Small (thumb logo + marquee title + info). List → v51.
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
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import QLabel, QWidget

from steempeg.infra.paths import get_resource_path
from steempeg.ui import design_tokens as tok
from steempeg.ui.design_tokens import CARD_PRESS_DURATION_MS, CARD_PRESS_SCALE
from steempeg.ui.library.card_sizes import (
    DEFAULT_SCREENSHOTS_CARD_SIZE,
    screenshot_card_size_spec,
)
from steempeg.ui.widgets.overflow_marquee import OverflowMarqueeLabel

# ClipCard accent family
_ACCENT = QColor("#b29ae7")
_ACCENT_HOVER = QColor("#7a6aa8")
_ACCENT_OPENED = QColor("#d4c4f5")
_IDLE_BORDER = QColor("#444444")
# Steempeg-shot idle identity (not selection — keep selection ring dominant).
_STEEMPEG_IDLE_BORDER = QColor("#8b7ab8")
_STEEMPEG_META_FG = QColor("#b29ae7")
_STEEMPEG_IMG_WASH = QColor(178, 154, 231, 18)  # #b29ae7 @ ~7%
_STEEMPEG_FOOTER_WASH = QColor(178, 154, 231, 36)  # footer a bit stronger


def _photo_chrome() -> tuple[QColor, QColor, QColor]:
    from steempeg.ui import ui_theme as ut

    footer, plate, idle = ut.clip_card_chrome()
    return QColor(plate), QColor(footer), QColor(idle)


_TITLE_FG = QColor("#e0e0e0")
_META_FG = QColor("#888888")

# Legacy aliases = Medium (stock Screenshots before Size ladder).
_MED = screenshot_card_size_spec(DEFAULT_SCREENSHOTS_CARD_SIZE)
_W = _MED.card_w
_IMG_H = _MED.thumb_h
_FOOTER_H = _MED.footer_h
_H = _MED.card_h
SCREENSHOT_PHOTO_W = _W
SCREENSHOT_PHOTO_H = _H
SCREENSHOT_PHOTO_SIZE = QSize(_W, _H)
_RADIUS = 10.0
_TITLE_GAP = 3
_ICON_GAP = 5
_SOURCE_ICON_PX = 14
_SOURCE_ICON_GAP = 4
_DRAG_SLOP = 6
_INFO_PX = 14

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

            pix = app_logo_pixmap(_SOURCE_ICON_PX, dpr=dpr)
        except Exception:
            pix = QPixmap()
    if pix.isNull():
        name = "steam.png" if key == "steam" else "logo.png"
        path = get_resource_path(name)
        if path and os.path.isfile(path):
            raw = QPixmap(path)
            if not raw.isNull():
                pix = raw.scaled(
                    int(_SOURCE_ICON_PX * dpr),
                    int(_SOURCE_ICON_PX * dpr),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                pix.setDevicePixelRatio(dpr)
    if not pix.isNull():
        _source_icon_cache[cache_key] = pix
    return pix


class ScreenshotPhoto(QWidget):
    """Photo card: rounded thumb + ClipCard-style footer (Size-aware)."""

    def __init__(
        self,
        thumb_path: str = "",
        *,
        title: str = "",
        subtitle: str = "",
        game_icon_path: str = "",
        card_size: str | None = None,
        info_tip: str = "",
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
        self._info_tip = (info_tip or "").strip()
        self._source = self._normalize_source(source)
        self._spec = screenshot_card_size_spec(card_size)
        self._w = int(self._spec.card_w)
        self._h = int(self._spec.card_h)
        self._img_h = int(self._spec.thumb_h)
        self._footer_h = int(self._spec.footer_h)
        self._pix = QPixmap()
        self._icon = QPixmap()
        self._info_pix = QPixmap()
        self._title_marquee: OverflowMarqueeLabel | None = None
        self._info_btn: QLabel | None = None
        self._hovered = False
        self._pressed = False
        self._selected = False
        self._opened = False
        self._scale = 1.0
        self._press_pos: QPoint | None = None
        self._dragged = False
        self._anim: QVariantAnimation | None = None
        self.setFixedSize(self._w, self._h)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        if self._spec.footer_mode == "info":
            tip = self._info_tip or f"{self._title}\n{self._subtitle}".strip()
            self.setToolTip(tip)
            self._load_info_glyph()
            self._build_info_footer_widgets(tip)
        if thumb_path:
            self.set_thumbnail(thumb_path)
        if game_icon_path:
            self.set_game_icon(game_icon_path)

    def _load_info_glyph(self) -> None:
        try:
            from steempeg.ui.icon_assets import title_bar_info_pixmap

            self._info_pix = title_bar_info_pixmap("#b29ae7", _INFO_PX)
        except Exception:
            self._info_pix = QPixmap()

    def _build_info_footer_widgets(self, tip: str) -> None:
        """Small: [marquee title | info] — game logo paints on the thumb."""
        pad_h = int(self._spec.pad_h)
        pad_v = int(self._spec.pad_v)
        foot_top = self._img_h
        foot_h = self._footer_h
        info_w = _INFO_PX if not self._info_pix.isNull() else 0
        gap = 4 if info_w else 0
        title_w = max(
            24, self._w - pad_h * 2 - info_w - gap - 3
        )  # outer inset ~1.5/side

        marquee = OverflowMarqueeLabel(self._title, self)
        marquee.setStyleSheet(
            f"QLabel {{ color: #e0e0e0; font-weight: bold; font-size: {int(self._spec.title_font)}px; "
            f"font-family: {tok.FONT_APP}; background: transparent; border: none; }}"
        )
        marquee.setGeometry(
            pad_h + 2,
            foot_top + pad_v,
            title_w,
            max(12, foot_h - pad_v * 2),
        )
        marquee.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._title_marquee = marquee

        if info_w:
            btn = QLabel(self)
            btn.setFixedSize(_INFO_PX, _INFO_PX)
            btn.setPixmap(self._info_pix)
            btn.setToolTip(tip)
            btn.setStyleSheet("QLabel { background: transparent; border: none; }")
            btn.move(
                self._w - pad_h - _INFO_PX - 2,
                foot_top + max(0, (foot_h - _INFO_PX) // 2),
            )
            btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._info_btn = btn

    def _info_footer_widgets_visible(self) -> bool:
        """Hide child chrome while press-scale paints (children don't transform)."""
        return abs(float(self._scale) - 1.0) < 0.001 and not self._pressed

    def _sync_info_footer_widgets(self) -> None:
        show = self._info_footer_widgets_visible()
        for w in (self._title_marquee, self._info_btn):
            if w is None:
                continue
            if w.isVisible() != show:
                w.setVisible(show)

    def set_title(self, title: str) -> None:
        text = (title or "").strip()
        if text == self._title:
            return
        self._title = text
        if self._title_marquee is not None:
            self._title_marquee.setText(text)
        if self._spec.footer_mode == "info":
            tip = self._info_tip or f"{self._title}\n{self._subtitle}".strip()
            self.setToolTip(tip)
            if self._info_btn is not None:
                self._info_btn.setToolTip(tip)
        self.update()

    def set_subtitle(self, subtitle: str) -> None:
        text = (subtitle or "").strip()
        if text == self._subtitle:
            return
        self._subtitle = text
        if self._spec.footer_mode == "info":
            tip = self._info_tip or f"{self._title}\n{self._subtitle}".strip()
            self.setToolTip(tip)
            if self._info_btn is not None:
                self._info_btn.setToolTip(tip)
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
        icon_px = int(self._spec.icon_px)
        if icon_path and os.path.isfile(icon_path):
            try:
                from steempeg.ui.icon_shape import shaped_game_icon_pixmap

                src = QPixmap(icon_path)
                if not src.isNull():
                    shaped = shaped_game_icon_pixmap(src, icon_px)
                    if shaped is not None and not shaped.isNull():
                        self._icon = shaped
                        self.update()
                        return
            except Exception:
                pix = QPixmap(icon_path)
                if not pix.isNull():
                    self._icon = pix.scaled(
                        icon_px,
                        icon_px,
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
        self._sync_info_footer_widgets()
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
            self._sync_info_footer_widgets()
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
        anim.finished.connect(self._on_scale_anim_finished)
        self._anim = anim
        anim.start()

    def _on_scale(self, value) -> None:
        self._scale = float(value)
        self._sync_info_footer_widgets()
        self.update()

    def _on_scale_anim_finished(self) -> None:
        self._anim = None
        self._sync_info_footer_widgets()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._w, self._h)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        img_bg, footer_bg, idle_border = _photo_chrome()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        w, h, img_h = self._w, self._h, self._img_h
        pad_h = int(self._spec.pad_h)
        pad_v = int(self._spec.pad_v)
        icon_px = int(self._spec.icon_px)

        # Whole-card press: scale the entire tile (not only the image well).
        scale = float(self._scale)
        if abs(scale - 1.0) > 0.001:
            cx = w / 2.0
            cy = h / 2.0
            p.translate(cx, cy)
            p.scale(scale, scale)
            p.translate(-cx, -cy)

        # Inset so a 3px ClipCard-style ring never clips.
        outer = QRectF(1.5, 1.5, w - 3.0, h - 3.0)
        card = QPainterPath()
        card.addRoundedRect(outer, _RADIUS, _RADIUS)

        # --- image well (rounded top, square join into footer) ---
        img = QRectF(outer.left(), outer.top(), outer.width(), float(img_h))
        img_path = QPainterPath()
        img_path.addRoundedRect(img, _RADIUS, _RADIUS)
        flat = QPainterPath()
        flat.addRect(QRectF(img.left(), img.bottom() - _RADIUS, img.width(), _RADIUS))
        img_path = img_path.united(flat)

        is_steempeg = self._source != "steam"

        p.save()
        p.setClipPath(img_path.intersected(card))
        p.fillRect(img, img_bg)
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
        if is_steempeg:
            p.fillRect(img, _STEEMPEG_IMG_WASH)
        # Small: game logo on the thumb (Clips Small language) — frees the strip.
        if self._spec.footer_mode == "info" and not self._icon.isNull():
            inset = 6
            p.drawPixmap(int(img.left()) + inset, int(img.top()) + inset, self._icon)
        p.restore()

        # --- ClipCard footer ---
        foot = QRectF(outer.left(), outer.top() + img_h, outer.width(), float(self._footer_h))
        foot_path = QPainterPath()
        foot_path.addRoundedRect(foot, _RADIUS, _RADIUS)
        top_sq = QPainterPath()
        top_sq.addRect(QRectF(foot.left(), foot.top(), foot.width(), _RADIUS))
        foot_path = foot_path.united(top_sq)
        foot_clip = foot_path.intersected(card)
        p.fillPath(foot_clip, footer_bg)
        if is_steempeg:
            p.fillPath(foot_clip, _STEEMPEG_FOOTER_WASH)

        from PySide6.QtGui import QFont as _QF

        title_font = tok.ui_qfont(pixel_size=int(self._spec.title_font), weight=_QF.Weight.Bold)
        meta_font = tok.ui_qfont(pixel_size=int(self._spec.meta_font))
        fm_title = QFontMetrics(title_font)
        fm_meta = QFontMetrics(meta_font)

        text_left = int(foot.left()) + pad_h
        text_width = int(foot.width()) - pad_h * 2
        title_top = int(foot.top()) + pad_v
        title_left = text_left
        title_width = text_width

        # Clip footer chrome so oversized logos can't bleed into the meta row.
        p.save()
        p.setClipPath(foot_clip)

        if self._spec.footer_mode == "info":
            # Child marquee + info handle idle; paint fallback while press-scaling.
            if not self._info_footer_widgets_visible():
                info_w = _INFO_PX if not self._info_pix.isNull() else 0
                gap = 4 if info_w else 0
                title_width = max(24, text_width - info_w - gap)
                title_rect = QRect(
                    title_left,
                    title_top,
                    title_width,
                    int(foot.height()) - pad_v * 2,
                )
                p.setFont(title_font)
                p.setPen(_TITLE_FG)
                p.drawText(
                    title_rect,
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    fm_title.elidedText(self._title, Qt.TextElideMode.ElideRight, title_width),
                )
                if not self._info_pix.isNull():
                    ix = int(foot.right()) - pad_h - _INFO_PX
                    iy = int(foot.center().y() - _INFO_PX / 2)
                    p.drawPixmap(ix, iy, self._info_pix)
        else:
            title_line_h = fm_title.height()
            if not self._icon.isNull():
                draw_icon_px = min(icon_px, title_line_h)
                icon_y = title_top + max(0, (title_line_h - draw_icon_px) // 2)
                if draw_icon_px == icon_px:
                    p.drawPixmap(text_left, icon_y, self._icon)
                else:
                    p.drawPixmap(
                        text_left,
                        icon_y,
                        self._icon.scaled(
                            draw_icon_px,
                            draw_icon_px,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        ),
                    )
                title_left = text_left + draw_icon_px + _ICON_GAP
                title_width = max(24, text_width - draw_icon_px - _ICON_GAP)

            if self._subtitle:
                title_rect = QRect(title_left, title_top, title_width, title_line_h)
                meta_rect = QRect(
                    text_left,
                    title_rect.bottom() + _TITLE_GAP,
                    text_width,
                    fm_meta.height(),
                )
                max_meta_bottom = int(foot.bottom()) - pad_v
                if meta_rect.bottom() > max_meta_bottom:
                    meta_rect.moveBottom(max_meta_bottom)
                p.setFont(title_font)
                p.setPen(_TITLE_FG)
                p.drawText(
                    title_rect,
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    fm_title.elidedText(
                        self._title, Qt.TextElideMode.ElideRight, title_width
                    ),
                )
                source_icon = _load_source_icon(
                    self._source, dpr=max(1.0, float(self.devicePixelRatioF()))
                )
                meta_left = text_left
                meta_text_width = text_width
                if not source_icon.isNull():
                    icon_y = meta_rect.top() + max(
                        0, (meta_rect.height() - _SOURCE_ICON_PX) // 2
                    )
                    p.drawPixmap(text_left, icon_y, source_icon)
                    meta_left = text_left + _SOURCE_ICON_PX + _SOURCE_ICON_GAP
                    meta_text_width = max(
                        24, text_width - _SOURCE_ICON_PX - _SOURCE_ICON_GAP
                    )
                meta_draw = QRect(
                    meta_left,
                    meta_rect.top(),
                    meta_text_width,
                    meta_rect.height(),
                )
                p.setFont(meta_font)
                p.setPen(_STEEMPEG_META_FG if is_steempeg else _META_FG)
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
                    int(foot.height()) - pad_v * 2,
                )
                p.setFont(title_font)
                p.setPen(_TITLE_FG)
                p.drawText(
                    title_rect,
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    fm_title.elidedText(
                        self._title, Qt.TextElideMode.ElideRight, title_width
                    ),
                )

        p.restore()

        # --- ClipCard border overlay ---
        if self._opened:
            border, width = _ACCENT_OPENED, 2.5
        elif self._selected:
            border, width = _ACCENT, 3.0
        elif self._hovered:
            border, width = _ACCENT_HOVER, 2.0
        elif is_steempeg:
            border, width = _STEEMPEG_IDLE_BORDER, 1.5
        else:
            border, width = idle_border, 1.0

        pen = p.pen()
        pen.setColor(border)
        pen.setWidthF(width)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(card)
        p.end()
