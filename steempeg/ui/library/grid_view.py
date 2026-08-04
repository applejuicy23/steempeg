"""A clip card for the library grid: thumbnail, title, date and a type badge."""
from __future__ import annotations

import os
from typing import Callable, Optional

import PySide6.QtCore as qtc
import PySide6.QtGui as qtg
import PySide6.QtWidgets as qtw

from steempeg.infra.paths import get_resource_path
from steempeg.ui.widgets.thumb_loading_overlay import ThumbLoadingOverlay


def _circular_icon_pixmap(source: qtg.QPixmap, size: int) -> qtg.QPixmap:
    """Backward-compatible alias — prefer shaped_game_icon_pixmap. """
    from steempeg.ui.icon_shape import ICON_SHAPE_CIRCLE, shaped_game_icon_pixmap

    return shaped_game_icon_pixmap(source, size, ICON_SHAPE_CIRCLE)


class ClipCard(qtw.QWidget):
    def __init__(
        self,
        title,
        date_str,
        badge_text,
        thumb_path,
        icon_path,
        row_idx,
        health_color: Optional[str] = None,
        status_badge: Optional[str] = None,
        round_icon: bool = False,
        queue_index: Optional[int] = None,
        queue_color: Optional[str] = None,
        on_left_click: Optional[Callable[[qtc.QMouseEvent], None]] = None,
        on_right_click: Optional[Callable[[qtc.QMouseEvent], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.row_idx = row_idx
        self._on_left_click = on_left_click
        self._on_right_click = on_right_click
        self._selected = False
        self._hovered = False
        self.setObjectName("ClipCard")

        # Cell 260, border 3px. That means the inside is exactly 254 by 184!
        self.setFixedSize(254, 184)

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.thumb_label = qtw.QLabel(self)
        self.thumb_label.setFixedSize(254, 144)
        self.thumb_label.setStyleSheet("background-color: #1a1a1a; border-radius: 0px;")

        if thumb_path and os.path.exists(thumb_path):
            pixmap = qtg.QPixmap(thumb_path)
            if not pixmap.isNull():
                scaled_thumb = pixmap.scaled(
                    254, 144,
                    qtc.Qt.KeepAspectRatioByExpanding,
                    qtc.Qt.SmoothTransformation,
                )
                self.thumb_label.setPixmap(scaled_thumb)

        self.icon_label = qtw.QLabel(self.thumb_label)
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.move(8, 8)
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        pix_path = icon_path if icon_path and os.path.exists(icon_path) else get_resource_path("unknown_icon.png")
        from steempeg.ui.icon_shape import (
            ICON_SHAPE_CIRCLE,
            get_icon_shape,
            shaped_game_icon_pixmap,
        )

        # Unknown badge stays circular for recognition; games follow Settings → Visual.
        use_force_circle = round_icon or (
            pix_path and os.path.basename(pix_path).lower() == "unknown_icon.png"
        )
        shape = ICON_SHAPE_CIRCLE if use_force_circle else get_icon_shape()
        if pix_path and os.path.exists(pix_path):
            from steempeg.ui.icon_utils import apply_square_icon

            src = qtg.QPixmap(pix_path)
            shaped = shaped_game_icon_pixmap(src, 24, shape) if not src.isNull() else None
            apply_square_icon(self.icon_label, shaped, 24)

        self.badge_label = qtw.QLabel(badge_text, self.thumb_label)
        self.badge_label.setStyleSheet(
            "background-color: #b29ae7; color: black; font-weight: bold; font-size: 11px;"
            "border-radius: 4px; padding: 2px 6px;"
        )
        self.badge_label.adjustSize()
        badge_w = self.badge_label.width()
        self.badge_label.move(254 - badge_w - 6, 144 - 24)

        if status_badge:
            self.status_badge_label = qtw.QLabel(status_badge, self.thumb_label)
            self.status_badge_label.setStyleSheet(
                "background-color: #555555; color: #e0e0e0; font-weight: bold; font-size: 10px;"
                "border-radius: 4px; padding: 2px 6px;"
            )
            self.status_badge_label.adjustSize()
            self.status_badge_label.move(6, 144 - 22)

        if health_color:
            # True circle: radius = half the box (border counts toward the box).
            self.health_dot = qtw.QLabel(self.thumb_label)
            self.health_dot.setFixedSize(14, 14)
            self.health_dot.setStyleSheet(
                f"background-color: {health_color};"
                "border: 2px solid #1a1a1a;"
                "border-radius: 7px;"
            )
            self.health_dot.move(254 - 20, 6)

        # Queue index (portable Choose a clip) — bottom-left; game icon stays top-left.
        self.queue_index_badge = qtw.QLabel(self.thumb_label)
        self.queue_index_badge.setFixedSize(26, 26)
        self.queue_index_badge.setAlignment(qtc.Qt.AlignmentFlag.AlignCenter)
        self.queue_index_badge.move(6, 144 - 32)
        self.queue_index_badge.hide()
        self.set_queue_badge(queue_index, queue_color)

        text_widget = qtw.QWidget()
        text_widget.setStyleSheet("""
            QWidget {
                background-color: #383838;
                border: none;
                border-top-left-radius: 0px;
                border-top-right-radius: 0px;
                border-bottom-left-radius: 9px;
                border-bottom-right-radius: 9px;
            }
        """)

        text_layout = qtw.QHBoxLayout(text_widget)
        text_layout.setContentsMargins(12, 0, 12, 0)

        title_lbl = qtw.QLabel(title.strip())
        title_lbl.setTextInteractionFlags(qtc.Qt.TextInteractionFlag.NoTextInteraction)
        title_lbl.setStyleSheet(
            "QLabel { color: #e0e0e0; font-weight: bold; font-size: 13px; background: transparent; border: none; }"
        )

        date_lbl = qtw.QLabel(date_str)
        date_lbl.setTextInteractionFlags(qtc.Qt.TextInteractionFlag.NoTextInteraction)
        date_lbl.setStyleSheet(
            "QLabel { color: #888888; font-size: 11px; background: transparent; border: none; }"
        )

        text_layout.addWidget(title_lbl)
        text_layout.addStretch()
        text_layout.addWidget(date_lbl)

        layout.addWidget(self.thumb_label)
        layout.addWidget(text_widget)

        # The list itself can't draw a hover border: the card sits on top and eats the
        # mouse, so QListWidget::item:hover never fires, and a border on the card widget
        # is hidden behind the thumbnail/text children. This transparent overlay draws
        # the whole border (default / hover / selected) on top of everything instead.
        self._border_overlay = qtw.QFrame(self)
        self._border_overlay.setGeometry(0, 0, 254, 184)

        # Clicks must hit the card, not child labels — viewport filters never see child events.
        for child in self.findChildren(qtw.QWidget):
            if child is not self:
                child.setAttribute(qtc.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._border_overlay.raise_()
        self._apply_selection_style()
        # Dim overlay (not QGraphicsOpacityEffect) — opacity made the QListWidgetItem
        # sort-key text ("000084") bleed through empty thumbs.
        self._dim_veil = qtw.QFrame(self)
        self._dim_veil.setGeometry(0, 0, 254, 184)
        self._dim_veil.setStyleSheet("background-color: rgba(0, 0, 0, 140); border: none;")
        self._dim_veil.setAttribute(qtc.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._dim_veil.hide()
        self._dim_dead = False
        self._dim_no_preview = not bool(thumb_path and os.path.exists(thumb_path))
        self._sync_unavailable_dim()

        # Opening spinner sits on the thumbnail banner only.
        self._loading = False
        self._load_overlay = ThumbLoadingOverlay(self.thumb_label, radius=16.0, pen_w=4)
        self._load_overlay.setGeometry(0, 0, 254, 144)
        self._load_overlay.hide()

        self._border_overlay.raise_()

    def set_queue_badge(
        self,
        queue_index: Optional[int] = None,
        queue_color: Optional[str] = None,
    ) -> None:
        """Show/hide the portable queue # overlay (bottom-left; game icon stays top-left)."""
        badge = getattr(self, "queue_index_badge", None)
        icon = getattr(self, "icon_label", None)
        if badge is None:
            return
        # Game avatar always stays in the top-left corner.
        if icon is not None:
            icon.move(8, 8)
        if queue_index is None or int(queue_index) <= 0:
            badge.hide()
            return
        from steempeg.ui.queue_card_shared import status_dot_style

        color = queue_color or "#ffcc00"
        badge.setText(str(int(queue_index)))
        badge.setStyleSheet(status_dot_style(color, size=26))
        # Bottom-left of the thumbnail, clear of the FG/CLIP tag on the right.
        badge.move(6, 144 - 32)
        badge.show()
        badge.raise_()

    def set_loading(self, loading: bool, *, percent: int | None = None) -> None:
        """Show a spinner on the thumbnail while this clip opens in the player."""
        self._loading = bool(loading)
        overlay = getattr(self, "_load_overlay", None)
        if overlay is None:
            return
        if self._loading:
            overlay.setGeometry(0, 0, self.thumb_label.width(), self.thumb_label.height())
            overlay.start(percent=percent)
            overlay.raise_()
            border = getattr(self, "_border_overlay", None)
            if border is not None:
                border.raise_()
        else:
            overlay.stop()

    def set_loading_progress(self, percent: int | None) -> None:
        overlay = getattr(self, "_load_overlay", None)
        if overlay is None or not getattr(self, "_loading", False):
            return
        overlay.set_progress(percent)

    def is_loading(self) -> bool:
        return bool(getattr(self, "_loading", False))

    def set_unavailable(self, *, dead: bool | None = None, no_preview: bool | None = None) -> None:
        """Dim dead / empty-thumb cards without relying on Qt disabled look."""
        if dead is not None:
            self._dim_dead = bool(dead)
        if no_preview is not None:
            self._dim_no_preview = bool(no_preview)
        self._sync_unavailable_dim()

    def _sync_unavailable_dim(self) -> None:
        dim = bool(getattr(self, "_dim_dead", False) or getattr(self, "_dim_no_preview", False))
        veil = getattr(self, "_dim_veil", None)
        if veil is None:
            return
        if dim:
            veil.show()
            veil.raise_()
            border = getattr(self, "_border_overlay", None)
            if border is not None:
                border.raise_()
        else:
            veil.hide()
        # Never leave an opacity effect (legacy) — it ghosts the sort-key text.
        if self.graphicsEffect() is not None:
            self.setGraphicsEffect(None)

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_selection_style()

    def set_thumbnail(self, thumb_path: str) -> None:
        if thumb_path and os.path.exists(thumb_path):
            pixmap = qtg.QPixmap(thumb_path)
            if not pixmap.isNull():
                scaled_thumb = pixmap.scaled(
                    254, 144,
                    qtc.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    qtc.Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb_label.setPixmap(scaled_thumb)
                self._dim_no_preview = False
                self._sync_unavailable_dim()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._apply_selection_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._apply_selection_style()
        super().leaveEvent(event)

    def _apply_selection_style(self) -> None:
        if self._selected:
            border = "3px solid #b29ae7"
        elif self._hovered:
            border = "2px solid #7a6aa8"
        else:
            border = "2px solid #444444"
        self._border_overlay.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: {border};
                border-top-left-radius: 0px;
                border-top-right-radius: 0px;
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }}
        """)

    def mousePressEvent(self, event: qtc.QMouseEvent) -> None:
        if event.button() == qtc.Qt.MouseButton.RightButton and self._on_right_click is not None:
            self._on_right_click(event)
            event.accept()
            return
        if event.button() == qtc.Qt.MouseButton.LeftButton and self._on_left_click is not None:
            self._on_left_click(event)
            event.accept()
            return
        super().mousePressEvent(event)
