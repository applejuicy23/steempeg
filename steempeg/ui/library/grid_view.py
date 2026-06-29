"""A clip card for the library grid: thumbnail, title, date and a type badge."""
from __future__ import annotations

import os
from typing import Callable, Optional

import PySide6.QtCore as qtc
import PySide6.QtGui as qtg
import PySide6.QtWidgets as qtw


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
        if icon_path and os.path.exists(icon_path):
            self.icon_label.setPixmap(
                qtg.QPixmap(icon_path).scaled(24, 24, qtc.Qt.KeepAspectRatio, qtc.Qt.SmoothTransformation)
            )

        self.badge_label = qtw.QLabel(badge_text, self.thumb_label)
        self.badge_label.setStyleSheet(
            "background-color: #b29ae7; color: black; font-weight: bold; font-size: 11px;"
            "border-radius: 4px; padding: 2px 6px;"
        )
        self.badge_label.adjustSize()
        badge_w = self.badge_label.width()
        self.badge_label.move(254 - badge_w - 6, 144 - 24)

        if health_color:
            self.health_dot = qtw.QLabel(self.thumb_label)
            self.health_dot.setFixedSize(12, 12)
            self.health_dot.setStyleSheet(
                f"background-color: {health_color}; border: 2px solid #1a1a1a; border-radius: 8px;"
            )
            self.health_dot.move(254 - 18, 6)

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

        title_lbl = qtw.QLabel(title)
        title_lbl.setStyleSheet(
            "QLabel { color: #e0e0e0; font-weight: bold; font-size: 13px; background: transparent; border: none;"
            " font-family: 'Liberation Sans', 'Segoe UI', Arial, sans-serif; }"
        )

        date_lbl = qtw.QLabel(date_str)
        date_lbl.setStyleSheet(
            "QLabel { color: #888888; font-size: 11px; background: transparent; border: none;"
            " font-family: 'Liberation Sans', 'Segoe UI', Arial, sans-serif; }"
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

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_selection_style()

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
